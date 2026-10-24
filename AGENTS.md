# AGENTS.md

This repository contains a Python package to migrate all Arc workspaces data
into Zen.

## Current Migration Flow

Zen must be closed before any command that writes Zen profile files.

Desktop UI:

```bash
pip install -e ".[desktop]"
python desktop.py
```

Local desktop package build:

```bash
pip install -e ".[build]"
python scripts/build_desktop.py --version dev
```

CLI equivalent:

```bash
python cli.py --nuke
```

`--nuke` is destructive for the target Zen profile: it clears tabs, folders,
pins, groups, closed-tab state, and regular bookmarks before importing Arc data.
Use `--nuke-only` to perform only that cleanup. Every run backs the profile up
first and can be undone with `--rollback <backup folder>`.

## Main Files

- `src/arc2zen/extract.py`
  - Reads Arc `StorableSidebar.json`.
  - Exports Arc spaces, pinned tabs, temporary/unpinned tabs, essential tabs,
    folders, icons, and a basic color field.
  - Writes `arc_pinned_tabs_export.json`, which is ignored by Git.
  - `arc_space_name()` is the single source of Arc space names for every step;
    Arc's untitled built-in personal space is named `Personal`.
    `arc_space_legacy_names()` lists names older versions used, and the import
    renames such Zen workspaces so re-runs reuse them.

- `src/arc2zen/profile_paths.py`
  - Discovers and validates Arc/Zen profile paths across supported platforms.
  - Arc scans macOS Application Support and Windows Store-package roots.
  - Zen scans macOS Application Support, Windows AppData, Linux tarball/AppImage
    `~/.zen`, and both documented/manifest-derived Flatpak roots.
  - Parses Zen `profiles.ini` and `installs.ini` before falling back to profile
    directories containing `zen-sessions.jsonlz4`.

- `src/arc2zen/migration.py`
  - Shared migration orchestration used by both CLI and GUI.
  - Owns the ordered step list for core import, favicons, folder states,
    workspace icons, and workspace themes.
  - Filters the synthetic `Orphaned` workspace by default unless explicitly
    disabled.
  - `MigrationOptions.spaces` limits the migration to the named Arc spaces;
    `list_arc_spaces()` returns the names in the same form the export uses.
  - Refuses to write a Zen profile whose lock file is held by a running Zen.

- `src/arc2zen/cli.py`
  - Unified CLI with switches for profile selection, nuke mode, nuke-only mode,
    space selection (`--space`, `--list-spaces`), and optional migration elements.

- `src/arc2zen/desktop.py`
  - PySide6 single window around the shared migration orchestrator: spaces on
    the left, presets and option chips on the right, a summary, the add/replace
    choice and the Migrate button in one footer row; chips map one-to-one to
    `MigrationOptions` fields (`CATEGORIES`, `SAFETY`, presets in `PRESETS`).
  - Space rows come from `space_overview.arc_space_overview()`; built-in
    Arc icons are drawn from the installed Zen's `omni.ja`
    (`zen_assets.zen_selectable_icon_svg`).
  - Lets users pick Arc/Zen profiles, Arc spaces, optional migration steps, and
    nuke mode.
  - Offers runtime options for skipping `Orphaned` and closing Zen automatically.
  - Offers to roll back to the run's backup on the result screen and deletes the
    backup when the window closes.
  - Confirms a replacing migration in the footer, closes only the Zen running the target profile
    (found by its `.parentlock` / `parent.lock`), then streams migration
    progress into the UI and ends on a result screen.
  - A log line starting with `⚠️` is a note of the running step: the result
    screen lists it and the step gets an "i". Use it for things the user
    should act on or know (skipped tabs, boost JavaScript, missing dictionary),
    not for routine skips. Keep the note a short summary; a list behind it
    (tabs, addresses) follows it one item per line, each starting with `↳`:
    the step lists them, the result screen's notes don't.
  - Uses a temporary export file so GUI runs do not leave `arc_pinned_tabs_export.json`.

- `src/arc2zen/snapshot.py`
  - The run's backup: before the first step `run_migration` copies the whole
    Zen profile, except caches, telemetry, plugins, lock files and site storage
    other than localStorage (`storage/default/*/ls`), into
    `<profile>/arc-to-zen-backup-<time>/` with a manifest that also records what
    did not exist yet. `rollback()` restores it and deletes what the run created.
    Steps get `create_backups=False`; their own backups are for running a module
    by itself.

- Root `cli.py` and `desktop.py`
  - Thin user-facing entrypoints for the packaged CLI and GUI.

- `scripts/build_desktop.py`
  - Builds a PyInstaller native-style package for the current OS.
  - macOS emits `Arc to Zen.app`, Windows emits a windowed app folder, and
    Linux emits an app folder with a `.desktop` entry.
  - Packages output into `release-artifacts/`.
  - Uses native builds, not cross-compilation.

- `assets/app-icon.svg`
  - Source app icon. It is an original Arc/Zen-inspired migration mark, not a
    direct copy of either browser logo.
  - Run `python scripts/generate_icon_assets.py` after editing it.

- `scripts/render_readme_screenshot.py`
  - Renders `docs/app-screenshot.png` from the actual Qt window.

- `.github/workflows/ci.yml`
  - Runs the Python syntax check on pushes to `main` and pull requests.

- `.github/workflows/release.yml`
  - Runs on pushed `v*` tags or manual dispatch for an existing tag.
  - Builds Linux x64, Windows x64, macOS x64, and macOS arm64 artifacts.
  - Creates or updates the matching GitHub Release with the build archives.

- `src/arc2zen/sessions.py`
  - Reads `arc_pinned_tabs_export.json`.
  - Resolves the Zen profile from `ZEN_PROFILE_PATH`, `ZEN_PROFILE_NAME`,
    Zen defaults, or the first profile containing `zen-sessions.jsonlz4`.
  - Writes `zen-sessions.jsonlz4`.
  - Also syncs `sessionstore.jsonlz4` and `sessionstore-backups/recovery.jsonlz4`
    so temporary/unpinned Arc tabs reopen as normal Zen tabs.
  - Preserves top-level pinned shortcuts instead of creating synthetic folders.
  - With selected spaces, clears only the matching Zen workspaces
    (`reset_zen_workspaces`) instead of every tab, folder, and group.
  - Creates hidden empty anchor tabs for folder-only parent folders so nested
    folder hierarchy survives in Zen.

- `src/arc2zen/favicons.py`
  - Reads Arc's Chromium favicon database in read-only immutable SQLite mode.
  - Copies matching favicons into Zen tab `image` and pinned initial state.

- `src/arc2zen/folder_states.py`
  - Reads Arc `StorableWindows.json` expanded-item state.
  - Applies Zen folder/group `collapsed` state by matching workspace and folder
    path.

- `src/arc2zen/workspace_icons.py`
  - Maps Arc emoji icons and built-in icon names into Zen workspace icons.

- `src/arc2zen/containers.py`
  - Groups exported spaces by Arc profile (`arc_profile` in the export) and
    creates or reuses a Zen container per profile in `containers.json`, named
    after the Arc profile (`User Data/Local State`; the unrenamed default
    profile is `Default`, as in Arc's UI) or, for other profiles with a
    generated name, after the profile's first space.
  - Sets each workspace's `containerTabId` and moves its tabs into it.

- `src/arc2zen/cookies.py`
  - Decrypts Arc's Chromium cookies (macOS `v10`, AES-128-CBC with a PBKDF2 key
    from the Keychain item `Arc Safe Storage`; DB version 24 strips the
    SHA-256 host prefix) and upserts them into Zen `cookies.sqlite` with
    `originAttributes = ^userContextId=N`.
  - `ARC_SAFE_STORAGE_PASSWORD` overrides the Keychain lookup for tests with
    synthetic cookie databases. Never log cookie values.

- `src/arc2zen/arc_crypto.py`
  - Reads the `Arc Safe Storage` Keychain password once per run and decrypts
    Chromium `v10` values; shared by cookies and passwords.

- `src/arc2zen/passwords.py`
  - Reads Arc `Login Data` / `Login Data For Account`, decrypts passwords, and
    adds them through `Services.logins.addLogins` in a headless Zen. Skips
    existing logins and refuses profiles with a Primary Password.

- `src/arc2zen/zen_runner.py`
  - `zen_session()` starts headless Zen on one profile with Marionette on a free port (set in
    `user.js`, restored afterwards), checks `ProfD` is that profile, runs a
    chrome-context script, and quits.

- `src/arc2zen/arc_urls.py`
  - Maps Arc internal pages (`arc://`, `chrome://`) to Zen `about:` pages and
    drops tabs Zen cannot open (`chrome-extension://`, `blob:`, unmapped
    internal pages). Applied in `migration.extract_arc_data` before export.

- `src/arc2zen/chromium_leveldb.py`
  - Pure-Python LevelDB reader (tables with Snappy blocks and logs; newest
    sequence wins, deletions honored) for Chromium data.

- `src/arc2zen/local_storage.py`
  - Decodes Chromium localStorage keys (`_<origin>\x00<key>`, strings prefixed
    with 0 = UTF-16LE or 1 = Latin-1) and writes them through
    `Services.domStorageManager.createStorage` in a headless Zen per container.

- `src/arc2zen/boosts.py`
  - Reads Arc boosts from the Firestore LevelDB cache
    (`firestore/Arc/bcny-arc-server/main`, `remote_document` keys under
    `boosts`, protobuf `MaybeDocument` with a JSON `data` field of css/js/zaps)
    and writes Zen's `zen-boosts.jsonlz4` (keyed by host) plus
    `zen-boosts/<id>.css`, using the Arc boost id so re-runs update in place.

- `src/arc2zen/link_routing.py`
  - Converts Arc `StorableLinkRouting.json` rules (Swift-enum JSON: `urlMatch`
    conditions, destination space id) into `zen-space-routing.jsonlz4` routes
    (`contains` / `equal-to` / `regex`, `openIn` = workspace uuid). Rule ids are
    reused so re-runs update routes in place.

- `src/arc2zen/arc_look_mod.py`
  - Installs the bundled mod from `src/arc2zen/mods/arc-look` into
    `chrome/zen-themes/<id>`, registers it in `zen-themes.json`, regenerates
    `chrome/zen-themes.css` (Zen does not rebuild it at startup), and fills in
    the mod's default prefs. Packaged via `package-data` and PyInstaller
    `--add-data`.

- `src/arc2zen/zen_settings.py`, `src/arc2zen/zen_prefs.py`
  - Map Arc's sidebar mode and top bar setting to Zen compact mode and toolbar
    layout, add the drag-to-split thresholds, and write them to `prefs.js`.

- `src/arc2zen/languages.py`
  - Maps Arc's `Default` profile `Preferences` (`intl.accept_languages`,
    `translate_blocked_languages`, `translate_allowlists`,
    `spellcheck.dictionaries`) and Arc's own `AppleLanguages` to Zen language
    prefs. Spellcheck only names dictionaries Zen has (bundled `en-US` plus
    dictionary add-ons in `extensions.json`); an empty `intl.locale.requested`
    makes Zen follow macOS.

- `src/arc2zen/tab_repair.py`
  - Replaces tab URLs with hosts that fail IDNA round-trip (Zen throws
    `NS_ERROR_MALFORMED_URI` and its menus stop working) with `about:blank` in
    all session files, including `recovery.baklz4` and `previous.jsonlz4`.

- `src/arc2zen/workspace_themes.py`
  - Converts Arc gradient or single-color workspace themes into Zen workspace
    `theme.gradientColors`, `opacity`, and `texture`.

## Data Sources

Arc:

- `~/Library/Application Support/Arc/StorableSidebar.json`
- `~/Library/Application Support/Arc/StorableWindows.json`
- `~/Library/Application Support/Arc/User Data/Default/Favicons`
- `~/Library/Application Support/Arc/User Data/<profile>/Cookies`
- `~/Library/Application Support/Arc/User Data/<profile>/Login Data`
- `~/Library/Application Support/Arc/User Data/<profile>/Local Storage/leveldb`
- `~/Library/Application Support/Arc/User Data/Local State`

Zen:

- `~/Library/Application Support/zen/Profiles/<profile>/zen-sessions.jsonlz4`
- `~/Library/Application Support/zen/Profiles/<profile>/sessionstore.jsonlz4`
- `~/Library/Application Support/zen/Profiles/<profile>/sessionstore-backups/recovery.jsonlz4`
- `~/Library/Application Support/zen/Profiles/<profile>/places.sqlite`
- `~/Library/Application Support/zen/Profiles/<profile>/containers.json`
- `~/Library/Application Support/zen/Profiles/<profile>/cookies.sqlite`

## Implementation Notes

- Arc source files are read only.
- Zen JSONLZ4 files use Mozilla's format: 8-byte magic header, 4-byte
  little-endian uncompressed size, then an LZ4 block.
- Backups: whatever a feature changes in the Zen profile must come back on
  rollback. The run's snapshot copies the whole profile except `SKIPPED_NAMES`,
  `SKIPPED_PREFIXES` and site storage beyond localStorage (`snapshot.py`), so
  a new file or folder is covered by itself, and one the run creates is removed.
  A feature that changes anything the snapshot skips extends it (as container
  cleanup does with `Snapshot.preserve()` before deleting site folders). Check a
  new feature by hashing the profile, migrating, rolling back and comparing:
  only caches and telemetry may differ.
- Generated exports, snapshots, local virtualenvs, bytecode, and backup files
  should remain untracked.

## Verification

Syntax check:

```bash
python -m py_compile \
  cli.py \
  desktop.py \
  src/arc2zen/*.py \
  scripts/build_desktop.py \
  scripts/generate_icon_assets.py \
  scripts/render_readme_screenshot.py
```

Release a new version:

```bash
git checkout main
git pull origin main
git tag v0.1.0
git push origin v0.1.0
```

Run the optional theme/icon/folder/favicon modules twice against a disposable
Zen profile to check idempotence; the second run should report zero changes
when Zen files are already in sync.
