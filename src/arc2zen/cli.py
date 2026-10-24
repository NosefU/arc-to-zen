#!/usr/bin/env python3
"""Unified Arc to Zen command-line interface."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .migration import MigrationOptions, ensure_zen_profile_free, list_arc_spaces, nuke_zen_profile_only, run_migration
from .snapshot import rollback, snapshot_profile


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
        "--rollback",
        metavar="BACKUP",
        help="Put the Zen profile back as it was before a migration, from the backup folder it printed, and exit.",
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
        "--no-default-theme",
        action="store_true",
        help="Leave Zen's colors on spaces that have no Arc theme instead of using Arc's default gradient.",
    )
    parser.add_argument("--no-arc-look-mod", action="store_true", help="Do not install the bundled Arc Look Zen mod.")
    parser.add_argument(
        "--no-sidebar-mode",
        action="store_true",
        help="Do not turn Arc's hidden/shown sidebar into Zen compact mode on/off.",
    )
    parser.add_argument(
        "--no-toolbar-layout",
        action="store_true",
        help="Do not pick Zen's single or multiple toolbars from Arc's top bar setting.",
    )
    parser.add_argument(
        "--no-split-drag",
        action="store_true",
        help="Keep Zen's default thresholds for dragging a tab onto another to split the view.",
    )
    parser.add_argument(
        "--no-website-languages",
        action="store_true",
        help="Do not copy Arc's website languages, never-translate languages and spellcheck dictionary.",
    )
    parser.add_argument(
        "--no-interface-language",
        action="store_true",
        help="Do not make Zen's menus and date formats follow macOS (or Arc's own language) as Arc does.",
    )
    parser.add_argument(
        "--no-link-routing",
        action="store_true",
        help="Do not copy Arc Air Traffic Control rules into Zen Space Routing.",
    )
    parser.add_argument(
        "--no-boosts",
        action="store_true",
        help="Do not copy Arc boosts (custom CSS per site) into Zen boosts.",
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
    parser.add_argument(
        "--local-storage",
        action="store_true",
        help="Copy web-site localStorage of the migrated Arc profiles into their Zen containers.",
    )
    parser.add_argument(
        "--passwords",
        action="store_true",
        help="Copy saved passwords of the migrated Arc profiles into Zen. Starts Zen headless on the target profile.",
    )
    parser.add_argument(
        "--no-tab-repair",
        action="store_true",
        help="Keep tab URLs with invalid hosts instead of replacing them with about:blank.",
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

    if args.rollback:
        backup = Path(args.rollback).expanduser()
        try:
            ensure_zen_profile_free(snapshot_profile(backup))
            rollback(backup)
        except (OSError, ValueError, RuntimeError) as exc:
            logging.error(f"❌ {exc}")
            return 1
        logging.info(f"Delete {backup} when you no longer need it.")
        return 0

    backups: list[Path] = []
    if args.nuke_only:
        try:
            nuke_zen_profile_only(args.zen_profile, on_snapshot=backups.append)
        except RuntimeError as exc:
            logging.error(f"❌ {exc}")
            print_rollback_hint(backups)
            return 1
        print_rollback_hint(backups)
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
        default_theme=not args.no_default_theme,
        containers=not args.no_containers,
        boosts=not args.no_boosts,
        link_routing=not args.no_link_routing,
        arc_look_mod=not args.no_arc_look_mod,
        sidebar_mode=not args.no_sidebar_mode,
        toolbar_layout=not args.no_toolbar_layout,
        split_drag=not args.no_split_drag,
        website_languages=not args.no_website_languages,
        interface_language=not args.no_interface_language,
        cookies=args.cookies,
        passwords=args.passwords,
        local_storage=args.local_storage,
        repair_tabs=not args.no_tab_repair,
        skip_orphaned=not args.include_orphaned,
        spaces=tuple(args.spaces) if args.spaces else None,
    )
    try:
        run_migration(options, on_snapshot=backups.append)
    except RuntimeError as exc:
        logging.error(f"❌ {exc}")
        print_rollback_hint(backups)
        return 1
    print_rollback_hint(backups)
    return 0


def print_rollback_hint(backups: list[Path]) -> None:
    if backups:
        logging.info(
            f"\nThe Zen profile was backed up to {backups[0]}.\n"
            f"To undo this migration: python cli.py --rollback \"{backups[0]}\"\n"
            "Delete that folder once Zen looks right."
        )


if __name__ == "__main__":
    raise SystemExit(main())
