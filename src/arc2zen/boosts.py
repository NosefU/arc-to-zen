#!/usr/bin/env python3
"""Copy Arc Boosts into Zen Boosts.

Arc keeps boosts in its account data, cached locally by the Firestore SDK in
~/Library/Application Support/firestore/Arc/bcny-arc-server/main (LevelDB with
protobuf documents). Zen keeps them in zen-boosts.jsonlz4, keyed by host, with
each boost's CSS in zen-boosts/<id>.css.
"""

from __future__ import annotations

import copy
import json
import logging
import shutil
import struct
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .chromium_leveldb import LevelDBError, read_leveldb, read_varint
from .profile_paths import resolve_arc_profile
from .sessions import read_mozilla_lz4, resolve_zen_profile, write_mozilla_lz4

logger = logging.getLogger(__name__)

FIRESTORE_DIR = Path("firestore") / "Arc" / "bcny-arc-server" / "main"
BOOST_KEY_PREFIX = b"\x85remote_document\x00\x01\xbeboosts\x00"

# ZenBoostsManager.getEmptyBoostEntry(); the colour dots depend on each other
ZEN_EMPTY_BOOST_DATA = {
    "boostName": "My Boost",
    "dotAngleDeg": 131.61,
    "dotPos": {"x": 0.76, "y": 0.66},
    "dotDistance": 0.91,
    "secondaryDotAngleDegDelta": 55,
    "secondaryDotPos": {"x": 0.5, "y": 0.81},
    "brightness": 0.5,
    "saturation": 0.5,
    "contrast": 0.75,
    "fontFamily": "",
    "enableColorBoost": False,
    "smartInvert": False,
    "autoTheme": False,
    "textCaseOverride": "none",
    "sizeOverride": 1,
    "zapSelectors": [],
    "focusSelectors": [],
    "changeWasMade": True,
}


def protobuf_fields(buf: bytes) -> Iterator[Tuple[int, Any]]:
    pos = 0
    while pos < len(buf):
        tag, pos = read_varint(buf, pos)
        number, wire_type = tag >> 3, tag & 7
        if wire_type == 0:
            value, pos = read_varint(buf, pos)
        elif wire_type == 1:
            value, pos = buf[pos:pos + 8], pos + 8
        elif wire_type == 2:
            length, pos = read_varint(buf, pos)
            value, pos = buf[pos:pos + length], pos + length
        elif wire_type == 5:
            value, pos = buf[pos:pos + 4], pos + 4
        else:
            raise LevelDBError(f"unsupported protobuf wire type {wire_type}")
        yield number, value


def firestore_value(buf: bytes) -> Any:
    """Decode a google.firestore.v1.Value."""
    for number, value in protobuf_fields(buf):
        if number == 17:
            return value.decode("utf-8", "replace")
        if number == 1:
            return bool(value)
        if number == 2:
            return value
        if number == 3:
            return struct.unpack("<d", value)[0]
        if number == 11:
            return None
        if number == 6:
            return firestore_map(value)
        if number == 9:
            return [firestore_value(item) for n, item in protobuf_fields(value) if n == 1]
    return None


def firestore_map(buf: bytes) -> Dict[str, Any]:
    result = {}
    for number, entry in protobuf_fields(buf):
        if number != 1:
            continue
        key = value = None
        for n, item in protobuf_fields(entry):
            if n == 1:
                key = item.decode("utf-8", "replace")
            elif n == 2:
                value = firestore_value(item)
        if key is not None:
            result[key] = value
    return result


def firestore_document(buf: bytes) -> Optional[Dict[str, Any]]:
    """Decode a Firestore client MaybeDocument into {"name", "fields"}."""
    for number, document in protobuf_fields(buf):
        if number != 2:
            continue
        name, fields = None, {}
        for n, item in protobuf_fields(document):
            if n == 1:
                name = item.decode("utf-8", "replace")
            elif n == 2:
                key = value = None
                for nn, part in protobuf_fields(item):
                    if nn == 1:
                        key = part.decode("utf-8", "replace")
                    elif nn == 2:
                        value = firestore_value(part)
                fields[key] = value
        return {"name": name or "", "fields": fields}
    return None


def arc_boosts(arc_profile: str | Path | None = None) -> List[Dict[str, Any]]:
    """Return Arc boosts with their content; deleted boosts (no data) are skipped."""
    firestore = resolve_arc_profile(arc_profile).parent / FIRESTORE_DIR
    if not firestore.is_dir():
        return []
    records = read_leveldb(firestore, key_filter=lambda key: key.startswith(BOOST_KEY_PREFIX))
    boosts = []
    for raw in records.values():
        document = firestore_document(raw)
        if not document or "/boosts/" not in document["name"]:
            continue
        fields = document["fields"]
        if not fields.get("data") or not fields.get("hostPattern"):
            continue
        try:
            data = json.loads(fields["data"])
        except ValueError:
            continue
        boosts.append(
            {
                "id": document["name"].rsplit("/", 1)[-1].lower(),
                # Zen looks boosts up by host without the port
                "host": fields["hostPattern"].split(":", 1)[0].lower(),
                "title": fields.get("title") or "",
                "active": str(fields.get("isActive")).lower() == "true",
                "css": data.get("css") or "",
                "js": data.get("js") or "",
                "zaps": [zap for zap in data.get("zaps") or [] if isinstance(zap, str)],
                "lastModified": fields.get("lastModified") or "",
            }
        )
    return sorted(boosts, key=lambda boost: (boost["host"], boost["lastModified"]))


def migrate_boosts(
    arc_profile: str | Path | None = None,
    zen_profile: str | Path | None = None,
    create_backups: bool = True,
) -> bool:
    """Add Arc boosts to Zen. Boosts Zen already has active for a host stay active."""
    profile = resolve_zen_profile(zen_profile)
    try:
        boosts = arc_boosts(arc_profile)
    except LevelDBError as exc:
        logger.error(f"❌ Could not read Arc boosts: {exc}")
        return False
    if not boosts:
        logger.info("No Arc boosts found")
        return True

    store_path = profile / "zen-boosts.jsonlz4"
    css_dir = profile / "zen-boosts"
    store = read_mozilla_lz4(store_path) if store_path.exists() else {}
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if create_backups:
        if store_path.exists():
            shutil.copy2(store_path, store_path.with_name(f"{store_path.name}.codex-boost-backup-{timestamp}"))
        if css_dir.is_dir():
            shutil.copytree(css_dir, css_dir.with_name(f"zen-boosts.codex-boost-backup-{timestamp}"))
    css_dir.mkdir(exist_ok=True)

    added = updated = 0
    with_js = []
    for boost in boosts:
        domain = store.setdefault(boost["host"], {"activeBoostId": None, "boostEntries": {}})
        entries = domain.setdefault("boostEntries", {})
        is_new = boost["id"] not in entries
        data = copy.deepcopy(ZEN_EMPTY_BOOST_DATA)
        data["boostName"] = boost["title"] or "My Boost"
        data["zapSelectors"] = boost["zaps"]
        entries[boost["id"]] = {"boostData": data}
        css_file = css_dir / f"{boost['id']}.css"
        if boost["css"]:
            css_file.write_text(boost["css"], encoding="utf-8")
        else:
            css_file.unlink(missing_ok=True)

        state = "inactive"
        if boost["active"]:
            if domain.get("activeBoostId") in (None, boost["id"]) or domain.get("activeBoostId") not in entries:
                domain["activeBoostId"] = boost["id"]
                state = "active"
            else:
                state = "inactive, Zen already has an active boost for this site"
        added += int(is_new)
        updated += int(not is_new)
        note = f"; its JavaScript ({len(boost['js'])} chars) is not copied, Zen boosts have no JS" if boost["js"] else ""
        logger.info(f"   {boost['host']}: {data['boostName']!r} ({state}){note}")
        if boost["js"]:
            with_js.append(f"{data['boostName']} ({boost['host']})")

    if with_js:
        logger.info(f"⚠️ Zen boosts run no JavaScript, so it was left out of: {', '.join(with_js)}")
    write_mozilla_lz4(store_path, store, create_backup=False)
    logger.info(f"Done. {added} boosts added, {updated} updated.")
    return True
