"""Shared migration orchestration for the CLI and desktop app."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .arc_urls import convert_arc_url
from .boosts import migrate_boosts
from .containers import sync_containers
from .cookies import migrate_cookies
from .link_routing import migrate_link_routing
from .local_storage import migrate_local_storage
from .arc_look_mod import install_arc_look_mod
from .zen_settings import apply_zen_settings
from .languages import migrate_languages
from .passwords import migrate_passwords
from .extract import ArcPinnedTabExtractor
from .favicons import migrate_favicons
from .folder_states import sync_folder_states
from .profile_paths import is_zen_profile_in_use, resolve_zen_profile
from .sessions import import_arc_export
from .snapshot import Snapshot, set_active_snapshot
from .tab_repair import repair_broken_tabs
from .workspace_icons import sync_workspace_icons
from .workspace_themes import sync_workspace_themes

logger = logging.getLogger(__name__)

LineCallback = Callable[[str], None]
StepCallback = Callable[[int, int, str], None]
SnapshotCallback = Callable[[Path], None]


@dataclass(frozen=True)
class MigrationOptions:
    """Controls which Arc data is copied into the target Zen profile."""

    arc_profile: str | Path | None = None
    zen_profile: str | Path | None = None
    export_file: str | Path | None = None
    nuke: bool = False
    favicons: bool = True
    folder_states: bool = True
    workspace_icons: bool = True
    workspace_themes: bool = True
    default_theme: bool = True
    containers: bool = True
    cookies: bool = False
    passwords: bool = False
    local_storage: bool = False
    repair_tabs: bool = True
    boosts: bool = True
    link_routing: bool = True
    arc_look_mod: bool = True
    sidebar_mode: bool = True
    toolbar_layout: bool = True
    split_drag: bool = True
    website_languages: bool = True
    interface_language: bool = True
    skip_orphaned: bool = True
    auto_close_zen: bool = True
    # Arc space names to migrate; None migrates every space.
    spaces: tuple[str, ...] | None = None


@dataclass(frozen=True)
class MigrationStep:
    title: str
    operation: Callable[[], bool]


class CallbackLogHandler(logging.Handler):
    """Forwards package log records to the desktop progress window."""

    def __init__(self, emit_line: LineCallback):
        super().__init__(logging.INFO)
        self.emit_line = emit_line
        self.setFormatter(logging.Formatter("%(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            if message:
                self.emit_line(message)
        except Exception:
            self.handleError(record)


def _report(emit_line: LineCallback | None, line: str) -> None:
    if emit_line:
        emit_line(line)
    else:
        logger.info(line)


def is_orphaned_space(space) -> bool:
    return space.space_id == "orphaned-essential-tabs" or space.space_name == "Orphaned"


def list_arc_spaces(arc_profile: str | Path | None = None, include_orphaned: bool = False) -> list[str]:
    """Return Arc space names in sidebar order, as the migration would see them."""
    extract_logger = logging.getLogger(ArcPinnedTabExtractor.__module__)
    old_level = extract_logger.level
    extract_logger.setLevel(logging.WARNING)
    try:
        extractor = ArcPinnedTabExtractor(arc_profile)
        arc_spaces = extractor.extract_pinned_tabs(include_orphaned=include_orphaned)
    finally:
        extract_logger.setLevel(old_level)

    names = []
    for space in arc_spaces:
        if not include_orphaned and is_orphaned_space(space):
            continue
        if space.space_name not in names:
            names.append(space.space_name)
    return names


def filter_arc_spaces(arc_spaces: list, spaces: Iterable[str] | None, emit_line: LineCallback | None = None) -> list:
    """Keep only the Arc spaces whose names were selected."""
    if spaces is None:
        return arc_spaces

    selected = set(spaces)
    available = [space.space_name for space in arc_spaces]
    unknown = sorted(selected - set(available))
    if unknown:
        raise RuntimeError(
            f"Unknown Arc spaces: {', '.join(unknown)}. Available: {', '.join(available)}"
        )

    skipped = [space for space in arc_spaces if space.space_name not in selected]
    if skipped:
        skipped_tabs = sum(len(space.pinned_tabs) for space in skipped)
        _report(
            emit_line,
            f"Skipped {len(skipped)} unselected spaces ({skipped_tabs} tabs): "
            + ", ".join(space.space_name for space in skipped),
        )
    return [space for space in arc_spaces if space.space_name in selected]


def convert_arc_only_urls(arc_spaces: list, emit_line: LineCallback | None = None) -> None:
    """Point Arc internal pages at their Zen counterparts and drop tabs Zen cannot open."""
    converted = 0
    dropped = []
    for space in arc_spaces:
        kept = []
        for tab in space.pinned_tabs:
            url = convert_arc_url(tab.url)
            if url is None:
                dropped.append(tab.url.split("?", 1)[0])
                continue
            if url != tab.url:
                tab.url = url
                converted += 1
            kept.append(tab)
        space.pinned_tabs = kept

    if converted:
        _report(emit_line, f"Converted {converted} Arc internal pages to Zen pages")
    if dropped:
        tabs = "1 tab" if len(dropped) == 1 else f"{len(dropped)} tabs"
        _report(emit_line, f"⚠️ Skipped {tabs} Zen cannot open")
        for url in dropped:
            _report(emit_line, f"↳ {url}")


def extract_arc_data(
    arc_profile: str | Path | None,
    export_file: str | Path,
    emit_line: LineCallback | None = None,
    skip_orphaned: bool = True,
    spaces: Iterable[str] | None = None,
) -> dict:
    """Extract Arc sidebar data and write the intermediate JSON export."""
    export_path = Path(export_file).expanduser()
    export_path.parent.mkdir(parents=True, exist_ok=True)

    extractor = ArcPinnedTabExtractor(arc_profile)
    arc_spaces = extractor.extract_pinned_tabs(include_orphaned=not skip_orphaned, fallback_space_names=spaces)
    if not arc_spaces:
        raise RuntimeError("No Arc tabs or folders found to migrate.")

    if skip_orphaned:
        orphaned_spaces = [space for space in arc_spaces if is_orphaned_space(space)]
        arc_spaces = [space for space in arc_spaces if not is_orphaned_space(space)]
        if orphaned_spaces:
            skipped_tabs = sum(len(space.pinned_tabs) for space in orphaned_spaces)
            _report(emit_line, f'Skipped "Orphaned" workspace ({skipped_tabs} tabs)')
        if not arc_spaces:
            raise RuntimeError('Only the "Orphaned" Arc workspace was found, and skipping it is enabled.')

    arc_spaces = filter_arc_spaces(arc_spaces, spaces, emit_line)
    if not arc_spaces:
        raise RuntimeError("No Arc spaces selected to migrate.")

    convert_arc_only_urls(arc_spaces, emit_line)

    if not extractor.export_to_json(arc_spaces, export_path):
        raise RuntimeError("Failed to write Arc export.")

    summary = extractor.get_extraction_summary(arc_spaces)
    _report(
        emit_line,
        "Extracted "
        f"{summary['total_spaces']} spaces, "
        f"{summary['total_pinned_tabs']} tabs, "
        f"{summary['total_folders']} folders",
    )
    return summary


def migration_steps(options: MigrationOptions, export_file: Path) -> list[MigrationStep]:
    """Build the ordered migration step list for the selected options.

    Steps make no backups of their own (create_backups=False): the run backs up
    the whole profile before the first step.
    """
    steps = [
        MigrationStep(
            "Extract Arc sidebar data",
            lambda: bool(
                extract_arc_data(
                    options.arc_profile,
                    export_file,
                    skip_orphaned=options.skip_orphaned,
                    spaces=options.spaces,
                )
            ),
        ),
        MigrationStep(
            "Import tabs, folders, workspaces, and session state",
            lambda: import_arc_export(
                zen_profile=options.zen_profile,
                arc_export_file=export_file,
                nuke=options.nuke,
                create_backups=False,
                space_names=options.spaces,
            ),
        ),
    ]

    optional_steps: Iterable[tuple[bool, MigrationStep]] = (
        (
            options.repair_tabs,
            MigrationStep(
                "Repair tabs with invalid URLs",
                lambda: repair_broken_tabs(
                    zen_profile=options.zen_profile,
                    create_backups=False,
                ),
            ),
        ),
        (
            options.favicons,
            MigrationStep(
                "Copy favicons",
                lambda: migrate_favicons(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    export_file=export_file,
                    create_backups=False,
                ),
            ),
        ),
        (
            options.folder_states,
            MigrationStep(
                "Sync pinned-folder open/closed state",
                lambda: sync_folder_states(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    create_backups=False,
                    space_names=options.spaces,
                ),
            ),
        ),
        (
            options.workspace_icons,
            MigrationStep(
                "Sync workspace icons",
                lambda: sync_workspace_icons(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    create_backups=False,
                    space_names=options.spaces,
                ),
            ),
        ),
        (
            options.workspace_themes,
            MigrationStep(
                "Sync workspace themes",
                lambda: sync_workspace_themes(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    create_backups=False,
                    space_names=options.spaces,
                    default_theme=options.default_theme,
                ),
            ),
        ),
        (
            options.boosts,
            MigrationStep(
                "Copy Arc boosts",
                lambda: migrate_boosts(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    create_backups=False,
                ),
            ),
        ),
        (
            options.arc_look_mod,
            MigrationStep(
                "Install the Arc Look mod",
                lambda: install_arc_look_mod(
                    zen_profile=options.zen_profile,
                    create_backups=False,
                ),
            ),
        ),
        (
            options.sidebar_mode or options.toolbar_layout or options.split_drag,
            MigrationStep(
                "Apply Zen layout settings",
                lambda: apply_zen_settings(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    create_backups=False,
                    sidebar=options.sidebar_mode,
                    toolbar=options.toolbar_layout,
                    split_drag=options.split_drag,
                ),
            ),
        ),
        (
            options.website_languages or options.interface_language,
            MigrationStep(
                "Copy language settings",
                lambda: migrate_languages(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    create_backups=False,
                    website=options.website_languages,
                    interface=options.interface_language,
                ),
            ),
        ),
        (
            options.link_routing,
            MigrationStep(
                "Copy Air Traffic Control rules to Space Routing",
                lambda: migrate_link_routing(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    create_backups=False,
                    space_names=options.spaces,
                ),
            ),
        ),
        (
            options.containers,
            MigrationStep(
                "Assign Arc profiles to Zen containers",
                lambda: sync_containers(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    export_file=export_file,
                    create_backups=False,
                    prune=options.nuke,
                ),
            ),
        ),
        (
            options.cookies,
            MigrationStep(
                "Copy Arc profile cookies into Zen containers",
                lambda: migrate_cookies(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    export_file=export_file,
                    create_backups=False,
                ),
            ),
        ),
        (
            options.local_storage,
            MigrationStep(
                "Copy Arc profile localStorage into Zen containers",
                lambda: migrate_local_storage(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    export_file=export_file,
                    create_backups=False,
                ),
            ),
        ),
        (
            options.passwords,
            MigrationStep(
                "Copy Arc profile passwords into Zen",
                lambda: migrate_passwords(
                    arc_profile=options.arc_profile,
                    zen_profile=options.zen_profile,
                    export_file=export_file,
                    create_backups=False,
                ),
            ),
        ),
    )
    steps.extend(step for enabled, step in optional_steps if enabled)
    return steps


def ensure_zen_profile_free(zen_profile: str | Path | None) -> None:
    """Refuse to write a Zen profile that a running Zen has open."""
    profile = resolve_zen_profile(zen_profile)
    if is_zen_profile_in_use(profile):
        raise RuntimeError(f"Zen is running with this profile. Close it and try again: {profile}")


def run_migration(
    options: MigrationOptions,
    emit_line: LineCallback | None = None,
    on_step: StepCallback | None = None,
    on_snapshot: SnapshotCallback | None = None,
) -> bool:
    """Run a complete Arc to Zen migration.

    The Zen profile is backed up first, always; on_snapshot gets the backup folder,
    which snapshot.rollback() restores. The steps themselves make no backups.
    """
    if options.export_file is not None:
        export_path = Path(options.export_file).expanduser()
        return _run_migration_with_export(options, export_path, emit_line, on_step, on_snapshot)

    with tempfile.TemporaryDirectory(prefix="arc-to-zen-") as temp_dir:
        export_path = Path(temp_dir) / "arc_pinned_tabs_export.json"
        return _run_migration_with_export(options, export_path, emit_line, on_step, on_snapshot)


def _run_migration_with_export(
    options: MigrationOptions,
    export_file: Path,
    emit_line: LineCallback | None,
    on_step: StepCallback | None,
    on_snapshot: SnapshotCallback | None,
) -> bool:
    ensure_zen_profile_free(options.zen_profile)
    steps = migration_steps(options, export_file)
    handler = CallbackLogHandler(emit_line) if emit_line else None
    root_logger = logging.getLogger()

    old_level = root_logger.level
    if handler:
        root_logger.addHandler(handler)
        if old_level > logging.INFO:
            root_logger.setLevel(logging.INFO)

    try:
        snapshot = Snapshot.take(resolve_zen_profile(options.zen_profile))
        if on_snapshot:
            on_snapshot(snapshot.root)
        set_active_snapshot(snapshot)
        for index, step in enumerate(steps, start=1):
            if on_step:
                on_step(index, len(steps), step.title)
            _report(emit_line, f"\n[{index}/{len(steps)}] {step.title}")
            if step.operation() is False:
                raise RuntimeError(f"{step.title} failed")
    finally:
        set_active_snapshot(None)
        if handler:
            root_logger.removeHandler(handler)
            root_logger.setLevel(old_level)

    return True


def nuke_zen_profile_only(zen_profile: str | Path | None = None, on_snapshot: SnapshotCallback | None = None) -> bool:
    """Clear the target Zen profile without importing Arc data; the profile is backed up first."""
    ensure_zen_profile_free(zen_profile)
    snapshot = Snapshot.take(resolve_zen_profile(zen_profile))
    if on_snapshot:
        on_snapshot(snapshot.root)
    if not import_arc_export(zen_profile=zen_profile, nuke=True, nuke_only=True, create_backups=False):
        raise RuntimeError("Zen profile cleanup failed")
    return True
