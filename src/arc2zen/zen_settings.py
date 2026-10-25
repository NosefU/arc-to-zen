#!/usr/bin/env python3
"""Carry Arc's window layout over to Zen and tune Zen's tab drag-to-split."""

from __future__ import annotations

import json
import logging
import plistlib
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from .profile_paths import arc_json_path, resolve_arc_profile
from .sessions import resolve_zen_profile
from .zen_prefs import set_user_prefs

logger = logging.getLogger(__name__)

ARC_DEFAULTS_DOMAIN = "company.thebrowser.Browser"

# Dropping a tab on another tab splits the view: a wider target (70% of the tab
# height instead of 20%) and half the hover delay make it far less fiddly.
SPLIT_DRAG_PREFS = {
    "zen.splitView.drag-over-split-threshold": 15,
    "zen.splitView.drag-over-split-delayMC": 250,
}


# Arc for Windows always shows the URL in a top bar; Arc for macOS has a setting for it
ARC_WINDOWS_TOP_BAR = sys.platform == "win32"

# How a fresh Arc looks: the sidebar shown, the URL in it rather than in a top bar (on macOS)
ARC_DEFAULT_LAYOUT = {
    "zen.view.compact.enable-at-startup": False,
    "zen.view.use-single-toolbar": not ARC_WINDOWS_TOP_BAR,
}


def arc_sidebar_mode(arc_profile: str | Path | None = None) -> Optional[str]:
    """Arc's sidebar mode of the last window, e.g. "noChrome" when the sidebar is hidden."""
    try:
        with open(arc_json_path("StorableWindows.json", arc_profile), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    windows = data.get("windows") or []
    mode = (windows[0] if windows else {}).get("sidebarMode")
    return mode or (data.get("sidebarViewPreferences") or {}).get("sidebarMode")


def arc_user_defaults(arc_profile: str | Path | None = None) -> Dict[str, Any]:
    """Arc's macOS preferences (~/Library/Preferences/company.thebrowser.Browser.plist)."""
    library = resolve_arc_profile(arc_profile).parent.parent
    try:
        with open(library / "Preferences" / f"{ARC_DEFAULTS_DOMAIN}.plist", "rb") as f:
            return plistlib.load(f)
    except (OSError, plistlib.InvalidFileException):
        return {}


def sidebar_prefs(arc_profile: str | Path | None = None) -> Dict[str, Any]:
    """Hidden Arc sidebar -> Zen compact mode at startup (sidebar shows on hover)."""
    mode = arc_sidebar_mode(arc_profile)
    if mode is None:
        return {}
    return {"zen.view.compact.enable-at-startup": mode == "noChrome"}


def toolbar_prefs(arc_profile: str | Path | None = None) -> Dict[str, Any]:
    """Arc's URL in the top bar -> Zen "Multiple toolbars"; otherwise "Single toolbar"."""
    if ARC_WINDOWS_TOP_BAR:
        return {"zen.view.use-single-toolbar": False}
    defaults = arc_user_defaults(arc_profile)
    if "topBarURLEnabled" not in defaults:
        return {}
    return {"zen.view.use-single-toolbar": not bool(defaults["topBarURLEnabled"])}


def apply_zen_settings(
    arc_profile: str | Path | None = None,
    zen_profile: str | Path | None = None,
    create_backups: bool = True,
    sidebar: bool = True,
    toolbar: bool = True,
    split_drag: bool = True,
    arc_defaults: bool = False,
) -> bool:
    """With arc_defaults (no Arc on this Mac) the sidebar and toolbars take Arc's defaults."""
    profile = resolve_zen_profile(zen_profile)
    prefs: Dict[str, Any] = {}
    if arc_defaults:
        logger.info("   No Arc here; using Arc's default layout")
    if sidebar:
        name = "zen.view.compact.enable-at-startup"
        found = {name: ARC_DEFAULT_LAYOUT[name]} if arc_defaults else sidebar_prefs(arc_profile)
        prefs.update(found)
        if not found:
            logger.info("   Arc sidebar mode not found; Zen compact mode left as is")
    if toolbar:
        name = "zen.view.use-single-toolbar"
        found = {name: ARC_DEFAULT_LAYOUT[name]} if arc_defaults else toolbar_prefs(arc_profile)
        prefs.update(found)
        if not found:
            logger.info("   Arc top bar setting not found; Zen toolbar layout left as is")
    if split_drag:
        prefs.update(SPLIT_DRAG_PREFS)

    for name, value in prefs.items():
        logger.info(f"   {name} = {json.dumps(value)}")
    changed = set_user_prefs(profile, prefs, create_backups=create_backups) if prefs else 0
    logger.info(f"Done. {changed} Zen preferences changed.")
    return True
