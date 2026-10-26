# Arc to Zen

![Arc to Zen full migration](docs/full-migration.png)

Move your Arc spaces, tabs, sign-ins and settings into Zen — or just make Zen
look like Arc.

## What moves

- 🧭 Arc spaces to Zen workspaces, with their icons and colors
- 📌 pinned tabs, Essentials and temporary open tabs
- 🗂️ nested pinned folders, open or closed as in Arc
- 🌐 site icons, so tabs don't start blank
- 🧳 Arc profiles as Zen containers: each space opens in its profile's container
- 🍪 cookies, so sites stay signed in
- 🔑 saved passwords
- 🗄️ sites' localStorage, such as site settings and some sign-ins
- 🚀 boosts, as Zen boosts
- 🛫 Air Traffic Control rules, as Zen Space Routing (macOS; Arc for Windows
  has none)
- 🗣️ languages: the languages sites are asked for, what to always or never
  translate, the spellcheck dictionary, and the interface language
- 🎛️ an Arc-like Zen: the Arc Look mod, Arc's sidebar and toolbars, easier
  drag-to-split and Peek on Shift-click

Along the way Arc's own pages open as their Zen counterparts (downloads,
settings, extensions, passwords), and tabs with broken addresses become blank
tabs, because such a tab makes Zen's menus stop responding. Arc pages Zen has no
counterpart for and extension pages are skipped; the result lists them.

## Just want Zen to look like Arc?

You don't have to migrate anything. **Just the look** ✨ only restyles Zen —
the bundled Arc Look mod (compact top bar, floating address bar, Arc-style
Peek and Ctrl+Tab panel), Arc's sidebar and toolbars, easier drag-to-split,
Peek on Shift-click, and Arc's icons and
colors for Zen spaces named like your Arc spaces — and leaves your tabs, spaces
and sign-ins as they are. It works without Arc too, with a fresh Arc's layout.

Pick **Just the look** in the app, or run `python cli.py --look-only`. Like a
migration, it is backed up first and can be rolled back.

## Download

Download the latest desktop app from
[GitHub Releases](https://github.com/NosefU/arc-to-zen/releases/latest).

Pick the archive for your OS:

- macOS Apple Silicon: `macos-arm64`
- macOS Intel: `macos-x64`
- Windows: `windows-x64`

`SHA256SUMS.txt` next to the archives holds their checksums: compare it with
`shasum -a 256 <archive>` on macOS or `Get-FileHash <archive>` on Windows.

<details>
<summary>macOS: opening the unsigned app</summary>

The macOS build is not signed yet, so Gatekeeper may block it the first time.

![macOS Privacy and Security Open Anyway button](docs/open-anyway.png)

1. Unzip the macOS download.
2. Try to open `Arc to Zen.app` once.
3. When macOS blocks it, open **System Settings**.
4. Go to **Privacy & Security**.
5. Scroll to **Security** and click **Open Anyway** next to `Arc to Zen.app`.
6. Confirm with **Open Anyway** and enter your password or use Touch ID if asked.
7. Open `Arc to Zen.app` again.

</details>

## Using the app

Everything is on one screen.

- **Header**: the app's version and a link to this page. Arc and Zen are found
  automatically, with their status; click either to pick another folder. Without
  a Zen profile nothing can run yet: a note above the presets offers **Download
  Zen** and **Choose profile folder…**, and once Zen is installed and opened,
  coming back to the window finds it.
- **Spaces** (left): pick the Arc spaces to bring; each row shows the space's
  icon, colors, tab and folder counts, and its Arc profile. As in Arc, spaces
  stay bound to their profile: each profile becomes one Zen container of the
  same name, and all its spaces open in it.
- **What comes along** (right): pick a preset, or turn single items on and off,
  which makes it **Custom**. Hover an item for what it does.
  - **Just tabs**: spaces, tabs and how they look; nothing else in Zen changes.
  - **Arc as it was** (picked when the app opens): also sign-ins, boosts,
    Air Traffic Control (macOS), languages and an Arc-like Zen.
  - **Just the look**: no migration, only the Arc look for Zen (see above). The
    spaces list marks which spaces Zen has; only those get their Arc icon and
    colors. Without Arc it is the only preset.
  - **Safety**: close Zen automatically if it's open (only the Zen running the
    target profile; other Zen windows keep running), and where Essentials that
    belong to no space go. On Windows also close Arc for cookies and boosts (see
    below).
- **Footer**: how much goes, whether it is **added to what's there** (spaces
  with the same name are updated, the rest of Zen stays) or **replaces Zen's
  contents** (tabs, folders, bookmarks, workspaces and containers Arc doesn't
  have are removed; asks for confirmation), and the **Migrate** button.
- **While it runs**: the progress stays on top and the list of steps follows
  the running one; the full log is one click away.
- **Result**: a clean run shows what is in Zen now and an **Open Zen** button. A
  run with notes (tabs Zen cannot open, boost JavaScript left out, a missing
  spellcheck dictionary, …) lists them; the details are under the steps. A
  failed run shows the reason, the steps and the log. **Start over** goes back
  to the choices, **Exit** closes the window.

When only some spaces are picked, only the Zen workspaces with the same names
are replaced and every other workspace stays, so spaces can be moved one at a
time.

Arc can stay open: the migrator only reads its files. Quitting Arc first makes
sure its latest changes, like a tab moved or a site signed into a moment ago,
are on disk. Arc for Windows is the exception for cookies and boosts: it locks
them while it runs, so the app closes Arc before the migration, as with its
close button. Without **Close Arc if needed** it asks you to quit Arc.

### Backup and rollback

Before the first step the Zen profile is backed up, always. Until the window is
closed, a failed run offers **Roll back** and a finished one **Something went
wrong? Roll back**; either puts Zen back exactly as it was. The backup is taken
before the window's first run on that profile, and later runs (after **Start
over**) keep it, so rolling back returns Zen to how it was before any of them.
Closing the window deletes the backup.

## Good to know

- **Keychain**: on macOS cookies and passwords need Arc's key from the
  Keychain ("Arc Safe Storage"), so macOS asks for access once per run. On
  Windows the key opens for the signed-in user without asking.
- **Cookies**: sign-ins that last only until the browser closes are not
  copied; cookies Zen already has for the same site and container are
  replaced.
- **Passwords**: Zen keeps passwords per profile, not per container, so the
  logins of all selected Arc profiles end up in one password manager. Logins
  Zen already has are kept; "never save" entries and sign-ins through another
  account (federated) are not copied. A Zen profile with a Primary Password is
  refused; remove it first. Zen briefly runs in the background while they are
  added.
- **localStorage**: only web sites are copied; data a site already has in Zen
  is kept, and values over Zen's 5 MB per site are skipped. IndexedDB is not
  copied; sites download that data again themselves. Zen briefly runs in the
  background here too.
- **Boosts**: all of your Arc boosts are copied, whatever spaces you pick. They
  come with your Arc account, so a computer where you never made one may still
  have some. Zen boosts have no JavaScript, so a boost's script is left out; the
  result names those boosts. A boost on in Arc is turned on in Zen unless Zen
  already has one on for that site. Running again updates the boosts instead of
  adding copies.
- **Air Traffic Control**: rules with conditions Zen cannot express, such as the
  app a link came from, and rules sending links to Little Arc are skipped; the
  result says how many. Rules that open links in the most recent space need
  nothing, since Zen does that anyway.
- **Reporting a problem**: after a failure, **Report it on GitHub…** says what
  goes into a report, saves it to Downloads and opens a GitHub issue with the
  versions and the error filled in; drag the report into the issue. The report
  has no cookies, passwords, site data, or addresses and titles of tabs; your
  user and computer names and your space and profile names are replaced. Show
  what's in the report opens it before you send it. For a migration that
  finished but left Zen wrong, or anything else, open a [new
  issue](https://github.com/NosefU/arc-to-zen/issues/new/choose) and pick
  **Problem with a migration** or **Something else**.
- **Languages**: Zen has only the English (US) spellcheck dictionary built in;
  for other languages the result links to
  [Firefox dictionaries](https://addons.mozilla.org/firefox/language-tools/),
  and the next migration picks up a dictionary added there.
- **Toolbars**: Zen gets a single toolbar when Arc shows the address only in
  the sidebar, and separate toolbars when Arc shows it in a top bar. Arc for
  Windows always shows it on top, so there Zen always gets separate toolbars.
- **Closing Zen on Windows**: Zen's windows are closed as with their close
  button, so Zen comes back with the last of them; the others are under
  History → Recently closed windows.

## Command line

Install:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Migrate:

```bash
python cli.py
```

The command line leaves cookies, passwords and localStorage out unless asked
(`--cookies`, `--passwords`, `--local-storage`); everything else is on, as in
**Arc as it was**.

Clean rebuild, the same as **Replace Zen's contents** in the app:

```bash
python cli.py --nuke
```

It clears Zen's tabs, folders, pins, groups, closed tabs and regular bookmarks
before importing, even when only some spaces are picked, and removes Zen
workspaces and containers Arc doesn't have, such as the default `Space` of a
new profile and the built-in `Banking` and `Shopping` containers with their
cookies and site data.

Every run backs up the Zen profile first and prints the backup folder with the
command that undoes the run:

```bash
python cli.py --rollback "<profile>/arc-to-zen-backup-<time>"
```

Delete that folder once Zen looks right.

Options:

- `--arc-profile PATH`, `--zen-profile PATH` pick the Arc data folder and the
  Zen profile
- `--list-spaces` prints the Arc space names
- `--space NAME` moves only that space; repeat it to pick several. Other Zen
  workspaces stay
- `--look-only` only makes Zen look like Arc (see
  [Just want Zen to look like Arc?](#just-want-zen-to-look-like-arc)); the
  `--no-…` options of the look still apply
- `--rollback BACKUP` puts Zen back from a run's backup folder
- `--nuke-only` only clears the Zen profile, without importing anything
- `--include-orphaned` puts Essentials that belong to no space into a separate
  `Orphaned` workspace instead of the first space
- `--cookies`, `--passwords`, `--local-storage` also copy sign-ins
- `--no-favicons`, `--no-folder-states`, `--no-workspace-icons`,
  `--no-workspace-themes` leave out site icons, folder states, space icons and
  colors
- `--no-default-theme` keeps Zen's colors on spaces without an Arc theme
  instead of Arc's default pink-to-lavender gradient
- `--no-tab-repair` keeps tabs with broken addresses as they are
- `--no-containers` keeps spaces and tabs out of per-profile containers
- `--no-boosts`, `--no-link-routing` leave out boosts and Air Traffic Control
- `--no-arc-look-mod`, `--no-sidebar-mode`, `--no-toolbar-layout`,
  `--no-split-drag`, `--no-peek` leave out parts of the Arc-like Zen
- `--no-website-languages`, `--no-interface-language` leave out the language
  settings
- `--export-file PATH` keeps the intermediate Arc export there
  (`./arc_pinned_tabs_export.json` by default)

Set `ZEN_BINARY` if Zen is not installed in a standard location; passwords and
localStorage need to start it.

## How it works

File formats, the Zen settings each option changes, how profiles are found, and
how to build the app: [docs/how-it-works.md](docs/how-it-works.md).
