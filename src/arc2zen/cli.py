#!/usr/bin/env python3
"""Unified Arc to Zen command-line interface."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .migration import MigrationOptions, list_arc_spaces, nuke_zen_profile_only, run_migration


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate Arc Browser data into a Zen Browser profile.")
    parser.add_argument(
        "--arc-profile",
        help="Path to the Arc data folder containing StorableSidebar.json.",
    )
    parser.add_argument(
        "--zen-profile",
        help="Path to a Zen profile directory, or a Zen root containing profiles.ini.",
    )
    parser.add_argument(
        "--export-file",
        type=Path,
        default=Path("arc_pinned_tabs_export.json"),
        help="Path for the intermediate Arc export JSON. Defaults to ./arc_pinned_tabs_export.json.",
    )
    parser.add_argument(
        "--nuke",
        action="store_true",
        help="Clear existing Zen tabs, folders, pins, groups, closed-tab state, and regular bookmarks before importing.",
    )
    parser.add_argument(
        "--nuke-only",
        action="store_true",
        help="Only clear the selected Zen profile; do not import Arc data.",
    )
    parser.add_argument(
        "--include-orphaned",
        action="store_true",
        help='Import Arc essential tabs that could not be matched to a workspace into an "Orphaned" workspace.',
    )
    parser.add_argument(
        "--no-backups",
        action="store_true",
        help="Do not create backups before changing Zen profile files.",
    )
    parser.add_argument(
        "--space",
        action="append",
        dest="spaces",
        metavar="NAME",
        help="Migrate only this Arc space. Repeat to select several; other Zen workspaces are kept.",
    )
    parser.add_argument(
        "--list-spaces",
        action="store_true",
        help="Print the Arc space names that can be passed to --space and exit.",
    )
    parser.add_argument(
        "--no-containers",
        action="store_true",
        help="Do not create a Zen container per Arc profile or move workspaces into them.",
    )
    parser.add_argument(
        "--cookies",
        action="store_true",
        help="Copy cookies of the migrated Arc profiles into their Zen containers. macOS asks for Keychain access.",
    )
    parser.add_argument("--no-favicons", action="store_true", help="Do not copy cached Arc favicons.")
    parser.add_argument(
        "--no-folder-states",
        action="store_true",
        help="Do not sync pinned-folder open/closed state.",
    )
    parser.add_argument("--no-workspace-icons", action="store_true", help="Do not sync workspace icons.")
    parser.add_argument(
        "--no-workspace-themes",
        action="store_true",
        help="Do not sync workspace colors/themes.",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
    args = parse_args()

    if args.list_spaces:
        for name in list_arc_spaces(args.arc_profile, include_orphaned=args.include_orphaned):
            print(name)
        return 0

    if args.nuke_only:
        try:
            nuke_zen_profile_only(args.zen_profile, create_backups=not args.no_backups)
        except RuntimeError as exc:
            logging.error(f"❌ {exc}")
            return 1
        return 0

    options = MigrationOptions(
        arc_profile=args.arc_profile,
        zen_profile=args.zen_profile,
        export_file=args.export_file,
        nuke=args.nuke,
        favicons=not args.no_favicons,
        folder_states=not args.no_folder_states,
        workspace_icons=not args.no_workspace_icons,
        workspace_themes=not args.no_workspace_themes,
        containers=not args.no_containers,
        cookies=args.cookies,
        skip_orphaned=not args.include_orphaned,
        create_backups=not args.no_backups,
        spaces=tuple(args.spaces) if args.spaces else None,
    )
    try:
        run_migration(options)
    except RuntimeError as exc:
        logging.error(f"❌ {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
