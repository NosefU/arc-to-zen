#!/usr/bin/env python3
"""Replace tab URLs Zen cannot parse with about:blank.

A host such as "ww.xn--15-.example.org" is not valid punycode. Zen throws
NS_ERROR_MALFORMED_URI for such a tab, and that breaks the menus: Settings,
Extensions, and workspace settings stop reacting to clicks.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List

from .sessions import read_mozilla_lz4, resolve_zen_profile, write_mozilla_lz4

logger = logging.getLogger(__name__)

URL_SCHEMES_WITH_HOST = ("http", "https", "ws", "wss", "ftp")

# Firefox restores from any of these, so every one must be repaired.
SESSION_FILES = (
    "zen-sessions.jsonlz4",
    "sessionstore.jsonlz4",
    "sessionstore-backups/recovery.jsonlz4",
    "sessionstore-backups/recovery.baklz4",
    "sessionstore-backups/previous.jsonlz4",
)


def valid_host(host: str) -> bool:
    if not host:
        return True
    try:
        host.encode("idna").decode("idna")
    except UnicodeError:
        return False
    return True


def broken_url_host(url: str) -> str | None:
    """Return the host of a URL Zen cannot parse, or None when the URL is fine."""
    scheme, sep, rest = url.partition("://")
    if not sep or scheme.lower() not in URL_SCHEMES_WITH_HOST:
        return None
    host = rest.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0].rsplit("@", 1)[-1]
    if host.startswith("["):
        return None
    host = host.split(":", 1)[0]
    return None if valid_host(host) else host


def session_tabs(data: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    yield from data.get("tabs", [])
    for window in [*data.get("windows", []), *data.get("_closedWindows", [])]:
        yield from window.get("tabs", [])
        for closed in window.get("_closedTabs", []):
            if isinstance(closed.get("state"), dict):
                yield closed["state"]


def tab_entries(tab: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    yield from tab.get("entries", [])
    initial = tab.get("_zenPinnedInitialState")
    if isinstance(initial, dict) and isinstance(initial.get("entry"), dict):
        yield initial["entry"]


def repair_session(data: Dict[str, Any], hosts: List[str]) -> int:
    changed = 0
    for tab in session_tabs(data):
        for entry in tab_entries(tab):
            host = broken_url_host(entry.get("url") or "")
            if host is None:
                continue
            entry["url"] = "about:blank"
            for field in ("resultPrincipalURI", "originalURI"):
                entry.pop(field, None)
            hosts.append(host)
            changed += 1
    return changed


def repair_broken_tabs(zen_profile: str | Path | None = None, create_backups: bool = True) -> bool:
    """Replace tab URLs with invalid hosts by about:blank in every Zen session file."""
    profile = resolve_zen_profile(zen_profile)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    total = 0
    hosts: List[str] = []
    for name in SESSION_FILES:
        path = profile / name
        if not path.exists():
            continue
        data = read_mozilla_lz4(path)
        changed = repair_session(data, hosts)
        if changed:
            if create_backups:
                backup_path = path.with_name(f"{path.name}.codex-tab-repair-backup-{timestamp}")
                shutil.copy2(path, backup_path)
                logger.info(f"✅ Backed up {path.name} to {backup_path.name}")
            write_mozilla_lz4(path, data, create_backup=False)
        logger.info(f"{path.name}: repaired {changed} tab URLs")
        total += changed

    if hosts:
        logger.info(f"⚠️ Tabs with broken addresses became blank tabs: {', '.join(sorted(set(hosts)))}")
    logger.info(f"Done. Replaced {total} invalid tab URLs with about:blank.")
    return True
