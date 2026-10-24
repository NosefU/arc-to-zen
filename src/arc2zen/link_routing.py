#!/usr/bin/env python3
"""Copy Arc Air Traffic Control rules into Zen Space Routing.

Arc: StorableLinkRouting.json, rules of URL conditions and a destination
space. Zen: zen-space-routing.jsonlz4, routes of {reference, matchType, openIn}.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .extract import arc_space_name
from .profile_paths import arc_json_path
from .sessions import read_mozilla_lz4, resolve_zen_profile, write_mozilla_lz4

logger = logging.getLogger(__name__)

# Arc URL condition kind -> (Zen matchType, how to turn the text into Zen's reference)
URL_MATCH_KINDS = {
    "contains": ("contains", lambda text: text),
    "is": ("equal-to", lambda text: text),
    "equals": ("equal-to", lambda text: text),
    "exactly": ("equal-to", lambda text: text),
    "regex": ("regex", lambda text: text),
    "startsWith": ("regex", lambda text: "^(?:https?://)?(?:www\\.)?" + re.escape(text)),
    "beginsWith": ("regex", lambda text: "^(?:https?://)?(?:www\\.)?" + re.escape(text)),
    "endsWith": ("regex", lambda text: re.escape(text) + "/?$"),
}


def swift_case(value: Any) -> Tuple[Optional[str], Any]:
    """Arc encodes Swift enums as {"case": payload}; return the case name and payload."""
    if isinstance(value, dict) and len(value) == 1:
        return next(iter(value.items()))
    return None, None


def strings_in(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


def url_condition(component: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Return (matchType, reference) for an Arc URL condition, or None."""
    case, payload = swift_case(component.get("componentType"))
    if case != "urlMatch" or not isinstance(payload, dict):
        return None
    kind, _ = swift_case(payload.get("_0"))
    text = payload.get("_1")
    if kind not in URL_MATCH_KINDS or not isinstance(text, str) or not text.strip():
        return None
    match_type, to_reference = URL_MATCH_KINDS[kind]
    return match_type, to_reference(text.strip())


def combine_conditions(conditions: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
    """Arc requires every condition of a rule; express that as one regex of lookaheads."""
    parts = []
    for match_type, reference in conditions:
        if match_type == "contains":
            parts.append(f"(?=.*{re.escape(reference)})")
        elif match_type == "regex":
            parts.append(f"(?=.*(?:{reference}))" if not reference.startswith("^") else f"(?={reference})")
        else:
            return None  # equal-to compares normalized URLs, which a regex cannot mirror
    return "regex", "^" + "".join(parts)


def arc_space_names_by_id(arc_profile: str | Path | None) -> Dict[str, str]:
    with open(arc_json_path("StorableSidebar.json", arc_profile), encoding="utf-8") as f:
        models = json.load(f).get("firebaseSyncState", {}).get("syncData", {}).get("spaceModels", [])
    return {
        models[i]: arc_space_name(models[i], models[i + 1].get("value", {}))
        for i in range(0, len(models) - 1)
        if isinstance(models[i], str) and isinstance(models[i + 1], dict)
    }


def arc_routes(arc_profile: str | Path | None, stats: Dict[str, int]) -> List[Dict[str, str]]:
    """Return Arc rules Zen can express as {id, reference, matchType, space}."""
    path = arc_json_path("StorableLinkRouting.json", arc_profile)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        rules = json.load(f).get("rules", [])
    names = arc_space_names_by_id(arc_profile)

    routes = []
    for rule in rules:
        target = next((names[s] for s in strings_in(rule.get("destination")) if s in names), None)
        if target is None:
            # "most recent space" is Zen's default; Little Arc has no Zen counterpart
            stats["no specific space"] += 1
            continue
        components = rule.get("sourceComponents") or []
        conditions = [url_condition(component) for component in components]
        if not conditions or any(condition is None for condition in conditions):
            # e.g. "links from Slack": Zen routes by URL only, and dropping a
            # condition would route more links than the Arc rule did
            stats["unsupported conditions"] += 1
            continue
        if len(conditions) == 1:
            match_type, reference = conditions[0]
        else:
            combined = combine_conditions(conditions)
            if combined is None:
                stats["unsupported conditions"] += 1
                continue
            match_type, reference = combined
        routes.append({
            "id": str(rule.get("id") or "").lower(),
            "reference": reference,
            "matchType": match_type,
            "space": target,
        })
    return routes


def migrate_link_routing(
    arc_profile: str | Path | None = None,
    zen_profile: str | Path | None = None,
    create_backups: bool = True,
    space_names: Optional[Iterable[str]] = None,
) -> bool:
    """Add Arc Air Traffic Control rules for the migrated spaces to Zen Space Routing."""
    profile = resolve_zen_profile(zen_profile)
    stats = {"no specific space": 0, "unsupported conditions": 0}
    routes = arc_routes(arc_profile, stats)
    if space_names is not None:
        selected = set(space_names)
        skipped = [route for route in routes if route["space"] not in selected]
        routes = [route for route in routes if route["space"] in selected]
        if skipped:
            stats["for unselected spaces"] = len(skipped)

    workspaces = {
        space.get("name"): space.get("uuid")
        for space in read_mozilla_lz4(profile / "zen-sessions.jsonlz4").get("spaces", [])
    }
    store_path = profile / "zen-space-routing.jsonlz4"
    store = read_mozilla_lz4(store_path) if store_path.exists() else {}
    store.setdefault("routes", [])
    store.setdefault("defaultRouteExternal", "most-recent-space")

    existing = {(r.get("reference", "").lower(), r.get("matchType"), r.get("openIn")) for r in store["routes"]}
    by_id = {r.get("id"): r for r in store["routes"]}
    added = updated = 0
    for route in routes:
        open_in = workspaces.get(route["space"])
        if not open_in:
            stats["space missing in Zen"] = stats.get("space missing in Zen", 0) + 1
            continue
        zen_route = {"id": route["id"], "reference": route["reference"], "openIn": open_in, "matchType": route["matchType"]}
        if route["id"] in by_id:
            by_id[route["id"]].update(zen_route)
            updated += 1
        elif (route["reference"].lower(), route["matchType"], open_in) in existing:
            continue
        else:
            store["routes"].append(zen_route)
            added += 1
        logger.info(f"   {route['matchType']} {route['reference']!r} -> {route['space']}")

    skipped = {kind: count for kind, count in stats.items() if count}
    if skipped:
        total = sum(skipped.values())
        rules = "1 Air Traffic Control rule was" if total == 1 else f"{total} Air Traffic Control rules were"
        logger.info(f"⚠️ {rules} not copied")
        for kind, count in skipped.items():
            logger.info(f"↳ {kind}: {count}")
    if added or updated:
        if create_backups and store_path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(store_path, store_path.with_name(f"{store_path.name}.codex-routing-backup-{stamp}"))
        write_mozilla_lz4(store_path, store, create_backup=False)
    logger.info(f"Done. {added} routes added, {updated} updated.")
    return True
