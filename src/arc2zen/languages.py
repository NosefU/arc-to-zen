#!/usr/bin/env python3
"""Carry Arc's language settings over to Zen: website languages, translation, spellcheck, interface."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .profile_paths import arc_profile_dir
from .sessions import resolve_zen_profile
from .zen_prefs import set_user_prefs
from .zen_settings import arc_user_defaults

logger = logging.getLogger(__name__)

# Zen holds one set of language settings; Arc keeps the user's own in its first profile.
ARC_LANGUAGE_PROFILE = "Default"
# Zen ships only this spellcheck dictionary; others come as add-ons.
BUNDLED_DICTIONARIES = ("en-US",)
DICTIONARIES_URL = "https://addons.mozilla.org/firefox/language-tools/"
# Chromium's legacy translate codes and their current tags
LEGACY_LANGUAGE_CODES = {"iw": "he", "jw": "jv", "no": "nb", "tl": "fil"}


def arc_chromium_prefs(arc_profile: str | Path | None = None) -> Dict[str, Any]:
    try:
        path = arc_profile_dir(ARC_LANGUAGE_PROFILE, arc_profile) / "Preferences"
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def split_tags(value: Any) -> List[str]:
    tags = value.split(",") if isinstance(value, str) else list(value or [])
    seen, result = set(), []
    for tag in (str(t).strip() for t in tags):
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            result.append(tag)
    return result


def translate_tag(tag: str) -> str:
    return LEGACY_LANGUAGE_CODES.get(tag, tag)


def zen_dictionaries(profile: Path) -> List[str]:
    """Spellcheck dictionaries Zen has: the bundled one plus dictionary add-ons."""
    found = list(BUNDLED_DICTIONARIES)
    try:
        with open(profile / "extensions.json", encoding="utf-8") as f:
            addons = json.load(f).get("addons") or []
    except (OSError, ValueError):
        addons = []
    for addon in addons:
        if addon.get("type") == "dictionary" and addon.get("active", True):
            found.extend((addon.get("startupData") or {}).get("dictionaries") or {})
    return found


def match_dictionary(wanted: str, available: Iterable[str]) -> str | None:
    """Exact tag first, then the same language: Arc's "ru" matches Zen's "ru-RU"."""
    available = list(available)
    for name in available:
        if name.lower() == wanted.lower():
            return name
    base = wanted.split("-")[0].lower()
    return next((name for name in available if name.split("-")[0].lower() == base), None)


def website_language_prefs(arc_profile: str | Path | None, profile: Path) -> Dict[str, Any]:
    """Languages sites are asked for, what never/always gets translated, spellcheck."""
    arc = arc_chromium_prefs(arc_profile)
    intl = arc.get("intl") or {}
    prefs: Dict[str, Any] = {}

    accept = split_tags(intl.get("accept_languages") or intl.get("selected_languages"))
    if accept:
        prefs["intl.accept_languages"] = ",".join(translate_tag(tag).lower() for tag in accept)
    else:
        logger.info("   Arc website languages not found; Zen's left as is")

    never = [translate_tag(tag) for tag in split_tags(arc.get("translate_blocked_languages"))]
    if never:
        prefs["browser.translations.neverTranslateLanguages"] = ",".join(never)
    always = [translate_tag(tag) for tag in split_tags(list(arc.get("translate_allowlists") or {}))]
    if always:
        prefs["browser.translations.alwaysTranslateLanguages"] = ",".join(always)

    wanted = split_tags((arc.get("spellcheck") or {}).get("dictionaries"))
    available = zen_dictionaries(profile)
    matched, missing = [], []
    for tag in wanted:
        name = match_dictionary(tag, available)
        (matched if name else missing).append(name or tag)
    if matched:
        prefs["spellchecker.dictionary"] = ",".join(dict.fromkeys(matched))
    if missing:
        some, it = ("1 language", "it") if len(missing) == 1 else (f"{len(missing)} languages", "them")
        logger.info(
            f"⚠️ Zen has no spellcheck dictionary for {some}; "
            f"add {it} from {DICTIONARIES_URL} and pick {it} in Zen's settings")
        for tag in missing:
            logger.info(f"↳ {tag}")
    return prefs


def interface_language_prefs(arc_profile: str | Path | None = None) -> Dict[str, Any]:
    """Arc follows macOS (or its own language from System Settings) for menus and date formats."""
    own = split_tags(arc_user_defaults(arc_profile).get("AppleLanguages"))
    return {
        # An empty list makes Zen follow macOS, as Arc does
        "intl.locale.requested": ",".join(own),
        "intl.regional_prefs.use_os_locales": True,
    }


def migrate_languages(
    arc_profile: str | Path | None = None,
    zen_profile: str | Path | None = None,
    create_backups: bool = True,
    website: bool = True,
    interface: bool = True,
) -> bool:
    profile = resolve_zen_profile(zen_profile)
    prefs: Dict[str, Any] = {}
    if website:
        prefs.update(website_language_prefs(arc_profile, profile))
    if interface:
        found = interface_language_prefs(arc_profile)
        prefs.update(found)
        if found["intl.locale.requested"]:
            logger.info(f"   Arc has its own interface language: {found['intl.locale.requested']}")
        else:
            logger.info("   Zen will use the system language and formats, as Arc does")

    for name, value in prefs.items():
        logger.info(f"   {name} = {json.dumps(value, ensure_ascii=False)}")
    changed = set_user_prefs(profile, prefs, create_backups=create_backups) if prefs else 0
    logger.info(f"Done. {changed} Zen preferences changed.")
    return True
