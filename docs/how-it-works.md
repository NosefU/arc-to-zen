# How Arc to Zen works

Implementation notes behind the [README](../README.md): which files are read and
written, how each part of Arc maps onto Zen, and how to build the app.

## Reading Arc

The migrator only reads Arc's files; nothing in Arc is changed.

- Spaces, tabs, folders and Essentials come from `StorableSidebar.json` in the
  Arc data folder; Arc's internal pages are mapped to Zen pages (`arc://downloads`
  → `about:downloads`, `arc://settings` → `about:preferences`,
  `arc://extensions` → `about:addons`, passwords → `about:logins`). Arc for
  Windows, which keeps no synced copy of the spaces, has them read from the
  sidebar itself. The tabs of a split view come in its place, side by side.
- Cookies and passwords are read from Arc's SQLite databases with
  `mode=ro&immutable=1`, without locks. Changes Arc has not flushed to disk yet
  (Chromium writes cookies about every 30 seconds) are not seen.
- localStorage and boosts are Chromium LevelDB stores, parsed in pure Python
  from both the table (`.ldb`) and log (`.log`) files. If Arc compacts a store
  while it is read, the step can fail; running again helps.

## Backup and rollback

`snapshot.py` copies the whole Zen profile into
`<profile>/arc-to-zen-backup-<time>/` before the first step, except caches,
telemetry and plugins Zen rebuilds (`cache2`, `startupCache`, `datareporting`,
`gmp-*`, …), Zen's lock files, earlier backups, and sites' storage other than
localStorage. A manifest records what existed, so a rollback also deletes what
the run created. Folders a step deletes (a removed container's site data) are
moved into the backup first. In the app one backup covers every run on that
profile from the window.

## Containers

Every Arc profile behind a migrated space becomes a Zen container with the same
name as the Arc profile, so the unrenamed default profile becomes `Default`.
Other profiles that still have Chromium's generated name ("Person 2") are named
after their first space instead. Containers that already exist are reused by
name, including the built-in `Personal` and `Work`. Each migrated workspace gets
that container as its default, and its tabs and Essentials move into it.

A clean rebuild (`--nuke`, Replace Zen's contents) also removes containers no
migrated Arc profile uses, such as the built-in `Banking` and `Shopping`,
together with their cookies, site permissions, and site storage (localStorage,
IndexedDB).

## Cookies

The Arc cookie key comes from the macOS Keychain item `Arc Safe Storage`
(`ARC_SAFE_STORAGE_PASSWORD` overrides it for tests). Only persistent,
unexpired, unpartitioned cookies are copied into `cookies.sqlite` with the
container's `userContextId`; existing Zen cookies with the same name, host,
path, and container are overwritten. Session cookies are skipped.

## Passwords

Arc's `Login Data` and `Login Data For Account` are decrypted with the same
Keychain key, then Zen is started headless on the target profile for a few
seconds so Zen encrypts the logins with its own key. Passwords never touch the
disk in plain text. Logins that already exist for the same site, auth kind, and
username are skipped; "never save" entries and federated sign-ins are not
copied.

## localStorage

Values from Arc's `Local Storage/leveldb` are written through a headless Zen
into the container of each profile, so they land in Zen's own format. Only web
sites (`http`/`https`) are copied, keys a site already has in Zen are kept, and
values over Zen's per-site quota (5 MB) are skipped. IndexedDB and Session
Storage are not migrated: converting Chromium's IndexedDB format is fragile, and
sites re-download that data themselves.

## Boosts

Arc keeps boosts in its account data; the migrator reads the local Firestore
cache in `~/Library/Application Support/firestore/Arc` (next to the Arc data
folder) and adds each boost to `zen-boosts.jsonlz4` for the same host, with its
CSS, name, and zap selectors. A boost active in Arc becomes the active Zen boost
for its site unless Zen already has one active there. Re-running updates the
same boosts instead of duplicating them.

## Air Traffic Control

Arc rules that open matching links in a specific space
(`StorableLinkRouting.json`) become Zen Space Routing routes to the workspace
with the same name. "Contains" and regex conditions map directly, "is" maps to
Zen's "equal to", and "starts/ends with" become a regex; a rule with several URL
conditions becomes one regex that requires all of them. Rules that open links in
the most recent space need no route, since that is Zen's default.

## Zen settings

- **Arc Look mod** (`src/arc2zen/mods/arc-look`): container line on the left of
  tabs and none on Essentials, a 32 px top bar, an address bar sized to the URL
  (up to 640 px) without a background, light Peek buttons, and a rounded Peek
  window. The migrator installs it, rebuilds Zen's mod stylesheet, sets the
  mod's default settings, and sets `zen.urlbar.behavior = float`.
- **Sidebar**: `sidebarMode = noChrome` in `StorableWindows.json` (a hidden Arc
  sidebar) sets `zen.view.compact.enable-at-startup = true`; a shown sidebar
  sets it to `false`.
- **Toolbars**: `topBarURLEnabled` in
  `~/Library/Preferences/company.thebrowser.Browser.plist` sets
  `zen.view.use-single-toolbar = false`; otherwise `true`.
- Without Arc (Just the look, `--look-only`) both follow a fresh Arc:
  compact mode off and a single toolbar (`ARC_DEFAULT_LAYOUT`).
- **Drag-to-split**: `zen.splitView.drag-over-split-threshold = 15` and
  `zen.splitView.drag-over-split-delayMC = 250`.

## Languages

Zen keeps one set of language settings, so they come from Arc's first profile
(`User Data/Default/Preferences`):

- `intl.accept_languages` from Arc's preferred languages for sites;
- `browser.translations.neverTranslateLanguages` /
  `alwaysTranslateLanguages` from the languages Arc never or always translates;
- `spellchecker.dictionary` from Arc's spellcheck dictionaries that Zen has
  (it ships only English (US); others come as dictionary add-ons);
- `intl.locale.requested = ""` and `intl.regional_prefs.use_os_locales = true`,
  so Zen follows macOS as Arc does, or the language picked for Arc alone in
  System Settings (`AppleLanguages` in Arc's preferences).

## Finding profiles

Common roots:

- Arc macOS: `~/Library/Application Support/Arc`
- Arc Windows: `%LOCALAPPDATA%\Packages\TheBrowserCompany.Arc_*\LocalCache\Local\Arc`
- Zen macOS: `~/Library/Application Support/zen`
- Zen Windows: `%APPDATA%\zen`
- Zen Linux: `~/.zen` or the Zen Flatpak profile directory

Zen profile resolution uses explicit selection first, then `ZEN_PROFILE_PATH`,
`ZEN_PROFILE_NAME`, Zen defaults from `installs.ini` / `profiles.ini`, and
finally the first profile containing `zen-sessions.jsonlz4`. Arc desktop on
Linux is not auto-detected because Arc desktop exists for macOS and Windows only.

## Building

Build a native package for the current OS:

```bash
pip install -e ".[build]"
python scripts/build_desktop.py --version dev
```

Release builds are created by GitHub Actions when a `v*` tag is pushed.
`python scripts/render_readme_screenshot.py` renders the app window into
`docs/app-screenshot.png`.
