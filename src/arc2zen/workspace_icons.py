#!/usr/bin/env python3
"""Sync Arc space icons into Zen workspaces."""

import argparse
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from .sessions import read_mozilla_lz4, resolve_zen_profile, write_mozilla_lz4
from .extract import arc_space_name, load_arc_sidebar


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

ZEN_SELECTABLE_ICON_BASE = "chrome://browser/skin/zen-icons/selectable"


def zen_icon_from_arc_icon_type(icon_type: Optional[Dict[str, Any]]) -> Optional[str]:
    if not icon_type:
        return None

    emoji = icon_type.get("emoji_v2")
    if emoji:
        return emoji

    icon_name = icon_type.get("icon")
    if icon_name:
        return f"{ZEN_SELECTABLE_ICON_BASE}/{icon_name}.svg"

    return None


def arc_workspace_icons(arc_profile: str | Path | None = None) -> Dict[str, str]:
    sidebar = load_arc_sidebar(arc_profile)
    space_models = sidebar.get("firebaseSyncState", {}).get("syncData", {}).get("spaceModels", [])
    icons = {}

    for i in range(0, len(space_models) - 1, 2):
        space_id = space_models[i]
        if not isinstance(space_id, str):
            continue

        value = space_models[i + 1].get("value", {})
        name = arc_space_name(space_id, value)
        icon = zen_icon_from_arc_icon_type(value.get("customInfo", {}).get("iconType"))
        if name and icon:
            icons[name] = icon

    return icons


def update_space_icons(spaces: list[Dict[str, Any]], icons: Dict[str, str]) -> int:
    changed = 0
    for space in spaces:
        name = space.get("name")
        icon = icons.get(name)
        if not icon:
            continue

        if space.get("icon") != icon:
            old = space.get("icon")
            space["icon"] = icon
            changed += 1
            logger.info(f"   {name}: {old!r} -> {icon!r}")

    return changed


def backup(path: Path, timestamp: str):
    backup_path = path.with_name(f"{path.name}.codex-workspace-icon-backup-{timestamp}")
    shutil.copy2(path, backup_path)
    logger.info(f"✅ Backed up {path.name} to {backup_path.name}")


def update_file(path: Path, icons: Dict[str, str], timestamp: str, create_backups: bool = True) -> int:
    if not path.exists():
        logger.info(f"Skipping missing file: {path}")
        return 0

    data = read_mozilla_lz4(path)
    if "windows" in data:
        spaces = data.get("windows", [{}])[0].get("spaces", [])
    else:
        spaces = data.get("spaces", [])

    changed = update_space_icons(spaces, icons)
    if changed:
        if create_backups:
            backup(path, timestamp)
        write_mozilla_lz4(path, data, create_backup=False)

    logger.info(f"{path.name}: changed {changed} workspace icons")
    return changed


def sync_workspace_icons(
    arc_profile: str | Path | None = None,
    zen_profile: str | Path | None = None,
    create_backups: bool = True,
    space_names: Iterable[str] | None = None,
) -> bool:
    """Sync Arc space icons into Zen workspaces."""
    profile = resolve_zen_profile(zen_profile)
    icons = arc_workspace_icons(arc_profile)
    if space_names is not None:
        selected = set(space_names)
        icons = {key: value for key, value in icons.items() if key in selected}
    logger.info(f"Loaded {len(icons)} Arc workspace icons")
    for name, icon in icons.items():
        logger.info(f"   {name}: {icon}")

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    files = [
        profile / "zen-sessions.jsonlz4",
        profile / "sessionstore.jsonlz4",
        profile / "sessionstore-backups" / "recovery.jsonlz4",
    ]

    total = 0
    for path in files:
        total += update_file(path, icons, timestamp, create_backups=create_backups)

    logger.info(f"Done. Changed {total} workspace icon fields across Zen session files.")
    return True


def main() -> bool:
    parser = argparse.ArgumentParser(description="Sync Arc space icons into Zen workspaces.")
    parser.add_argument(
        "--arc-profile",
        help="Path to the Arc profile root containing StorableSidebar.json.",
    )
    parser.add_argument(
        "--zen-profile",
        help="Path to a Zen profile directory, or a Zen root containing profiles.ini.",
    )
    parser.add_argument(
        "--no-backups",
        action="store_true",
        help="Do not create backups before changing Zen profile files.",
    )
    args = parser.parse_args()
    return sync_workspace_icons(args.arc_profile, args.zen_profile, create_backups=not args.no_backups)


if __name__ == "__main__":
    raise SystemExit(0 if main() else 1)
