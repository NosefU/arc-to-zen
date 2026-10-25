#!/usr/bin/env python3
"""Copy localStorage of the migrated Arc profiles into their Zen containers."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

from .chromium_leveldb import LevelDBError, read_leveldb
from .cookies import arc_profile_contexts
from .profile_paths import arc_profile_dir
from .sessions import resolve_zen_profile
from .zen_runner import ZenRunnerError, zen_session

logger = logging.getLogger(__name__)

WEB_SCHEMES = ("http://", "https://")


def decode_chromium_string(raw: bytes) -> str:
    """Chromium prefixes localStorage strings with their encoding: 0 UTF-16LE, 1 Latin-1."""
    if not raw:
        return ""
    if raw[0] == 0:
        return raw[1:].decode("utf-16-le")
    if raw[0] == 1:
        return raw[1:].decode("latin-1")
    raise ValueError(f"unknown localStorage string encoding {raw[0]}")


def read_arc_local_storage(leveldb_dir: Path, stats: Dict[str, int]) -> Dict[str, Dict[str, str]]:
    """Return {origin: {key: value}} for web origins; extension storage is skipped."""
    by_origin: Dict[str, Dict[str, str]] = {}
    for raw_key, raw_value in read_leveldb(leveldb_dir).items():
        if not raw_key.startswith(b"_"):
            continue  # VERSION, META:, METAACCESS: bookkeeping
        origin_bytes, sep, key_bytes = raw_key[1:].partition(b"\x00")
        if not sep:
            continue
        origin = origin_bytes.decode("utf-8", "replace")
        if not origin.startswith(WEB_SCHEMES):
            stats["non-web origins"] += 1
            continue
        try:
            key = decode_chromium_string(key_bytes)
            value = decode_chromium_string(raw_value)
        except (ValueError, UnicodeDecodeError):
            stats["undecodable"] += 1
            continue
        by_origin.setdefault(origin, {})[key] = value
    return by_origin


# Keeps each Marionette message well below its size limits
BATCH_BYTES = 4 * 1024 * 1024

WRITE_SCRIPT = """
const [contextId, origins] = arguments;
const win = Services.wm.getMostRecentWindow("navigator:browser");
const result = {added: 0, existing: 0, quota: 0, failedOrigins: 0};
for (const [origin, items] of Object.entries(origins)) {
  let storage;
  try {
    const principal = Services.scriptSecurityManager.createContentPrincipal(
      Services.io.newURI(origin), {userContextId: contextId});
    storage = Services.domStorageManager.createStorage(win, principal, principal, "");
  } catch (e) {
    result.failedOrigins++;
    continue;
  }
  for (const [key, value] of Object.entries(items)) {
    if (storage.getItem(key) !== null) { result.existing++; continue; }
    try { storage.setItem(key, value); result.added++; }
    catch (e) { result.quota++; }
  }
}
return result;
"""


def batches(by_origin: Dict[str, Dict[str, str]]) -> List[Dict[str, Dict[str, str]]]:
    chunks: List[Dict[str, Dict[str, str]]] = [{}]
    size = 0
    for origin, items in by_origin.items():
        item_size = len(json.dumps(items, ensure_ascii=False).encode())
        if chunks[-1] and size + item_size > BATCH_BYTES:
            chunks.append({})
            size = 0
        chunks[-1][origin] = items
        size += item_size
    return chunks


def migrate_local_storage(
    arc_profile: str | Path | None = None,
    zen_profile: str | Path | None = None,
    export_file: str | Path = "arc_pinned_tabs_export.json",
    create_backups: bool = True,
) -> bool:
    """Copy web-site localStorage of the migrated Arc profiles into their Zen containers.

    Keys a site already has in Zen are kept. A headless Zen writes the data, so it
    lands in Zen's own storage format.
    """
    profile = resolve_zen_profile(zen_profile)
    with open(Path(export_file).expanduser(), encoding="utf-8") as f:
        export_spaces = json.load(f).get("spaces", [])
    context_by_profile = arc_profile_contexts(profile, export_spaces)
    if not context_by_profile:
        logger.info("No Arc profile information in the export; skipping localStorage")
        return True

    work = []
    for arc_profile_name, context_id in context_by_profile.items():
        leveldb_dir = arc_profile_dir(arc_profile_name, arc_profile) / "Local Storage" / "leveldb"
        if not leveldb_dir.is_dir():
            logger.info(f"   Arc profile {arc_profile_name!r} has no localStorage; skipping")
            continue
        stats = {"non-web origins": 0, "undecodable": 0}
        try:
            by_origin = read_arc_local_storage(leveldb_dir, stats)
        except LevelDBError as exc:
            logger.error(f"❌ Could not read localStorage of Arc profile {arc_profile_name!r}: {exc}", exc_info=True)
            return False
        keys = sum(len(items) for items in by_origin.values())
        skipped = ", ".join(f"{count} {kind}" for kind, count in stats.items() if count) or "none"
        logger.info(
            f"   Arc profile {arc_profile_name!r}: {len(by_origin)} sites, {keys} keys read (skipped: {skipped})"
        )
        if by_origin:
            work.append((arc_profile_name, context_id, by_origin))

    if not work:
        logger.info("No localStorage to copy")
        return True

    try:
        with zen_session(profile) as client:
            for arc_profile_name, context_id, by_origin in work:
                totals = {"added": 0, "existing": 0, "quota": 0, "failedOrigins": 0}
                for chunk in batches(by_origin):
                    result = client.execute(WRITE_SCRIPT, [context_id, chunk])
                    for key in totals:
                        totals[key] += result.get(key, 0)
                logger.info(
                    f"   Arc profile {arc_profile_name!r} -> container {context_id}: {totals['added']} keys added, "
                    f"{totals['existing']} already in Zen, {totals['quota']} over the site quota, "
                    f"{totals['failedOrigins']} sites rejected"
                )
    except ZenRunnerError as exc:
        logger.error(f"❌ {exc}", exc_info=True)
        return False

    logger.info("Done. localStorage copied into Zen.")
    return True
