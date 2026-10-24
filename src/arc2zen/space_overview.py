#!/usr/bin/env python3
"""What the GUI shows about each Arc space before a migration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from .containers import arc_profile_names
from .extract import ArcPinnedTabExtractor, arc_space_name
from .workspace_icons import arc_workspace_icons, load_arc_sidebar
from .workspace_themes import ARC_DEFAULT_THEME_COLORS, arc_workspace_themes

logger = logging.getLogger(__name__)


@dataclass
class SpaceOverview:
    name: str
    tabs: int
    folders: int
    arc_profile: Optional[str]
    container: Optional[str]
    emoji: Optional[str] = None
    icon_name: Optional[str] = None  # Arc built-in icon, same name as Zen's selectable icon
    colors: List[str] = field(default_factory=list)  # hex, first is primary


def rgb_hex(color) -> str:
    if isinstance(color, str):
        return color
    return "#{:02x}{:02x}{:02x}".format(*[max(0, min(255, int(c))) for c in color[:3]])


def arc_space_overview(arc_profile: str | Path | None = None, include_orphaned: bool = False) -> List[SpaceOverview]:
    """Spaces in sidebar order with their counts, icon, colors, and target container."""
    extract_logger = logging.getLogger(ArcPinnedTabExtractor.__module__)
    old_level = extract_logger.level
    extract_logger.setLevel(logging.WARNING)
    try:
        spaces = ArcPinnedTabExtractor(arc_profile).extract_pinned_tabs(include_orphaned=include_orphaned)
    finally:
        extract_logger.setLevel(old_level)

    icon_names = {}
    models = load_arc_sidebar(arc_profile).get("firebaseSyncState", {}).get("syncData", {}).get("spaceModels", [])
    for i in range(0, len(models) - 1):
        if isinstance(models[i], str) and isinstance(models[i + 1], dict):
            value = models[i + 1].get("value", {})
            icon = (value.get("customInfo") or {}).get("iconType") or {}
            if icon.get("icon") and not icon.get("emoji_v2"):
                icon_names[arc_space_name(models[i], value)] = icon["icon"]

    emojis = {name: icon for name, icon in arc_workspace_icons(arc_profile).items() if not icon.startswith("chrome://")}
    themes = arc_workspace_themes(arc_profile)
    profile_names = arc_profile_names(arc_profile)

    result: List[SpaceOverview] = []
    first_space_of_profile = {}
    for space in spaces:
        if any(item.name == space.space_name for item in result):
            continue
        profile = space.profile
        if profile and profile not in first_space_of_profile:
            first_space_of_profile[profile] = space.space_name
        theme = themes.get(space.space_name)
        colors = [rgb_hex(dot["c"]) for dot in theme["gradientColors"]] if theme else list(ARC_DEFAULT_THEME_COLORS)
        result.append(
            SpaceOverview(
                name=space.space_name,
                tabs=len(space.pinned_tabs),
                folders=len(space.folders),
                arc_profile=profile,
                # Same rule as containers.sync_containers: the Arc profile's name, else its first space
                container=(profile_names.get(profile) or first_space_of_profile.get(profile)) if profile else None,
                emoji=emojis.get(space.space_name),
                icon_name=icon_names.get(space.space_name),
                colors=colors,
            )
        )
    return result
