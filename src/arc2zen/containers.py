#!/usr/bin/env python3
"""Map Arc profiles to Zen containers and put migrated workspaces into them."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .profile_paths import zen_session_files
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


def backup(path: Path, timestamp: str) -> None:
    backup_path = path.with_name(f"{path.name}.codex-container-backup-{timestamp}")
    shutil.copy2(path, backup_path)
    logger.info(f"✅ Backed up {path.name} to {backup_path.name}")


def sync_containers(
    zen_profile: str | Path | None = None,
    export_file: str | Path = "arc_pinned_tabs_export.json",
    create_backups: bool = True,
) -> bool:
    """Create a Zen container per Arc profile and assign the migrated workspaces to it."""
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

    containers_by_space: Dict[str, int] = {}
    created = 0
    for arc_profile, space_names in grouped.items():
        # Name the container after the first space so it reads like Arc's sidebar
        context_id, is_new = ensure_container(containers, space_names[0])
        created += int(is_new)
        verb = "Created" if is_new else "Using"
        logger.info(f"   {verb} container {space_names[0]!r} ({context_id}) for Arc profile {arc_profile!r}: {', '.join(space_names)}")
        for name in space_names:
            containers_by_space[name] = context_id

    if created:
        if create_backups and containers_path.exists():
            backup(containers_path, timestamp)
        with open(containers_path, "w", encoding="utf-8") as f:
            json.dump(containers, f, ensure_ascii=False)

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
