#!/usr/bin/env python3
"""Map Arc profiles to Zen containers and put migrated workspaces into them."""

from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .profile_paths import resolve_arc_profile, zen_session_files
from .sessions import read_mozilla_lz4, resolve_zen_profile, write_mozilla_lz4

logger = logging.getLogger(__name__)

# Built-in Firefox containers have no stored name, only a localized label.
DEFAULT_CONTAINER_NAMES = {1: "Personal", 2: "Work", 3: "Banking", 4: "Shopping"}
NEW_CONTAINER_COLORS = ["blue", "turquoise", "green", "yellow", "orange", "red", "pink", "purple"]


def container_name(identity: Dict[str, Any]) -> Optional[str]:
    if identity.get("name"):
        return identity["name"]
    if identity.get("public", True):
        return DEFAULT_CONTAINER_NAMES.get(identity.get("userContextId"))
    return None


def load_containers(path: Path) -> Dict[str, Any]:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"version": 5, "lastUserContextId": 0, "identities": []}


def ensure_container(containers: Dict[str, Any], name: str) -> tuple[int, bool]:
    """Return the userContextId of a public container with this name, creating it if needed."""
    for identity in containers.get("identities", []):
        if identity.get("public", True) and container_name(identity) == name:
            return identity["userContextId"], False

    identities = containers.setdefault("identities", [])
    used = [i.get("userContextId", 0) for i in identities if i.get("userContextId", 0) < 2**31]
    context_id = max([containers.get("lastUserContextId", 0), *used]) + 1
    public_count = sum(1 for identity in identities if identity.get("public", True))
    identities.append(
        {
            "userContextId": context_id,
            "public": True,
            "icon": "fingerprint",
            "color": NEW_CONTAINER_COLORS[public_count % len(NEW_CONTAINER_COLORS)],
            "name": name,
        }
    )
    containers["lastUserContextId"] = context_id
    return context_id, True


def arc_profile_names(arc_profile: str | Path | None = None) -> Dict[str, str]:
    """Arc profile names as Arc shows them, keyed by profile folder ("Profile 2": "Work").

    Arc shows its unrenamed default profile as "Default"; other profiles still on
    Chromium's generated name ("Person 2") are left out.
    """
    try:
        local_state = resolve_arc_profile(arc_profile) / "User Data" / "Local State"
        with open(local_state, encoding="utf-8") as f:
            info_cache = json.load(f).get("profile", {}).get("info_cache", {})
    except (OSError, ValueError):
        return {}
    names = {}
    for folder, info in info_cache.items():
        name = info.get("name")
        if not name or name.startswith("__ARC_"):
            continue
        if info.get("is_using_default_name"):
            if folder == "Default":
                names[folder] = "Default"
            continue
        names[folder] = name
    return names


def spaces_by_arc_profile(export_spaces: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Group exported space names by their Arc profile, keeping sidebar order."""
    grouped: Dict[str, List[str]] = {}
    for space in export_spaces:
        profile = space.get("arc_profile")
        if profile:
            grouped.setdefault(profile, []).append(space["space_name"])
    return grouped


def assign_workspace_containers(data: Dict[str, Any], containers_by_space: Dict[str, int]) -> int:
    """Set each workspace's default container and move its tabs into that container."""
    if "windows" in data:
        windows = data.get("windows", [])
        spaces = windows[0].get("spaces", []) if windows else []
        tabs = [tab for window in windows for tab in window.get("tabs", [])]
    else:
        spaces = data.get("spaces", [])
        tabs = data.get("tabs", [])

    workspace_context = {}
    changed = 0
    for space in spaces:
        context_id = containers_by_space.get(space.get("name"))
        if context_id is None:
            continue
        workspace_context[space.get("uuid")] = context_id
        if space.get("containerTabId") != context_id:
            space["containerTabId"] = context_id
            changed += 1

    for tab in tabs:
        context_id = workspace_context.get(tab.get("zenWorkspace"))
        if context_id is None:
            continue
        if tab.get("userContextId", 0) != context_id:
            tab["userContextId"] = context_id
            changed += 1
        # Zen marks tabs that live in their workspace's default container
        tab["zenDefaultUserContextId"] = "true"
    return changed


def prune_containers(containers: Dict[str, Any], keep_ids: set[int]) -> List[Dict[str, Any]]:
    """Remove public containers outside keep_ids; Zen's hidden internal ones stay."""
    identities = containers.get("identities", [])
    removed = [i for i in identities if i.get("public", True) and i.get("userContextId") not in keep_ids]
    containers["identities"] = [i for i in identities if i not in removed]
    return removed


CONTEXT_PATTERN = re.compile(r"(?:^\^|&)userContextId=(\d+)(?:&|$)")

# (database, table, column) rows keyed by origin attributes or an origin with a ^suffix
CONTAINER_TABLES = (
    ("cookies.sqlite", "moz_cookies", "originAttributes"),
    ("permissions.sqlite", "moz_perms", "origin"),
    ("permissions.sqlite", "moz_origin_interactions", "origin"),
    ("webappsstore.sqlite", "webappsstore2", "originAttributes"),
    ("storage/ls-archive.sqlite", "webappsstore2", "originAttributes"),
    ("storage.sqlite", "origin", "suffix"),
)


def container_of(value: str | None) -> int | None:
    """userContextId in origin attributes ("^userContextId=3") or an origin ending with them."""
    if not value or "^" not in value:
        return None
    match = CONTEXT_PATTERN.search(value[value.index("^"):])
    return int(match.group(1)) if match else None


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def delete_container_data(profile: Path, context_ids: set[int], backup_dir: Optional[Path]) -> Dict[str, int]:
    """Delete cookies, permissions, and site storage of the given containers.

    With backup_dir the databases are copied and the storage folders moved there.
    """
    counts = {"cookies": 0, "permissions": 0, "local storage": 0, "storage folders": 0}
    if not context_ids:
        return counts

    def in_removed(value: str | None) -> int:
        return int(container_of(value) in context_ids)

    kinds = {"moz_cookies": "cookies", "moz_perms": "permissions", "moz_origin_interactions": "permissions",
             "webappsstore2": "local storage", "origin": None}
    for db_name in dict.fromkeys(name for name, _, _ in CONTAINER_TABLES):
        db_path = profile / db_name
        if not db_path.exists():
            continue
        if backup_dir:
            for suffix in ("", "-wal", "-shm"):
                source = Path(f"{db_path}{suffix}")
                if source.exists():
                    target = backup_dir / source.relative_to(profile)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
        con = sqlite3.connect(db_path)
        try:
            con.create_function("in_removed_container", 1, in_removed)
            for name, table, column in CONTAINER_TABLES:
                if name != db_name or not table_exists(con, table):
                    continue
                deleted = con.execute(f"DELETE FROM {table} WHERE in_removed_container({column})").rowcount
                if kinds[table]:
                    counts[kinds[table]] += deleted
            if db_name == "storage.sqlite" and table_exists(con, "cache"):
                # Make the quota manager rescan storage/ instead of trusting its cache
                con.execute("UPDATE cache SET valid = 0")
            con.commit()
        finally:
            con.close()

    storage = profile / "storage"
    if storage.is_dir():
        for repository in storage.iterdir():
            if not repository.is_dir():
                continue
            for origin_dir in repository.iterdir():
                if not origin_dir.is_dir() or container_of(origin_dir.name) not in context_ids:
                    continue
                if backup_dir:
                    target = backup_dir / origin_dir.relative_to(profile)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(origin_dir), target)
                else:
                    shutil.rmtree(origin_dir)
                counts["storage folders"] += 1
    return counts


def backup(path: Path, timestamp: str) -> None:
    backup_path = path.with_name(f"{path.name}.codex-container-backup-{timestamp}")
    shutil.copy2(path, backup_path)
    logger.info(f"✅ Backed up {path.name} to {backup_path.name}")


def sync_containers(
    arc_profile: str | Path | None = None,
    zen_profile: str | Path | None = None,
    export_file: str | Path = "arc_pinned_tabs_export.json",
    create_backups: bool = True,
    prune: bool = False,
) -> bool:
    """Create a Zen container per Arc profile and assign the migrated workspaces to it.

    With prune (a clean rebuild) containers no migrated profile uses are removed
    together with their cookies, permissions, and site storage.
    """
    profile = resolve_zen_profile(zen_profile)
    with open(Path(export_file).expanduser(), encoding="utf-8") as f:
        export_spaces = json.load(f).get("spaces", [])

    grouped = spaces_by_arc_profile(export_spaces)
    if not grouped:
        logger.info("No Arc profile information in the export; skipping containers")
        return True

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    containers_path = profile / "containers.json"
    containers = load_containers(containers_path)

    profile_names = arc_profile_names(arc_profile)
    containers_by_space: Dict[str, int] = {}
    created = 0
    for profile_folder, space_names in grouped.items():
        # Use the Arc profile name; unnamed profiles take their first space's name
        name = profile_names.get(profile_folder) or space_names[0]
        context_id, is_new = ensure_container(containers, name)
        created += int(is_new)
        verb = "Created" if is_new else "Using"
        logger.info(f"   {verb} container {name!r} ({context_id}) for Arc profile {profile_folder!r}: {', '.join(space_names)}")
        for name in space_names:
            containers_by_space[name] = context_id

    removed = prune_containers(containers, set(containers_by_space.values())) if prune else []
    if removed:
        logger.info(
            "   Removed containers not used by Arc profiles: "
            + ", ".join(f"{container_name(i) or '?'} ({i['userContextId']})" for i in removed)
        )

    if created or removed:
        if create_backups and containers_path.exists():
            backup(containers_path, timestamp)
        with open(containers_path, "w", encoding="utf-8") as f:
            json.dump(containers, f, ensure_ascii=False)

    if removed:
        backup_dir = profile / f"container-cleanup-backup-{timestamp}" if create_backups else None
        counts = delete_container_data(profile, {i["userContextId"] for i in removed}, backup_dir)
        logger.info(
            "   Deleted data of removed containers: "
            + ", ".join(f"{count} {kind}" for kind, count in counts.items())
        )
        if backup_dir and backup_dir.exists():
            logger.info(f"✅ Backed up removed container data to {backup_dir.name}")

    total = 0
    for path in zen_session_files(profile):
        if not path.exists():
            logger.info(f"Skipping missing file: {path}")
            continue
        data = read_mozilla_lz4(path)
        changed = assign_workspace_containers(data, containers_by_space)
        if changed:
            if create_backups:
                backup(path, timestamp)
            write_mozilla_lz4(path, data, create_backup=False)
        logger.info(f"{path.name}: changed {changed} workspace/tab container fields")
        total += changed

    logger.info(f"Done. {created} containers created, {total} container fields changed.")
    return True
