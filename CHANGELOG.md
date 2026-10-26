# Changelog

Each release's notes on GitHub are its section here. A section starts with
`## v<version> — <date>`; the release fails if its tag has none.

## v0.4.0 — 2026-10-26

Two more of Arc's habits in Zen, and an Arc-like Ctrl+Tab panel.

- Peek on Shift-click: Shift-click a link to open it in Peek, as in Arc. Zen
  uses Option-click (Alt-click on Windows) by default.
- Ctrl+Tab like Arc: Ctrl+Tab goes to the tab used before, and Ctrl+Shift+Tab
  goes the other way. Zen's Ctrl+Shift+Tab "show all tabs" is turned off for
  it.
- The Arc Look mod (1.5.0) styles the Ctrl+Tab panel like Arc's: a compact
  light card with small previews and the selected tab in lavender. It has its
  own switch in Zen's mod settings.
- Both items are in Zen setup, on in Arc as it was and Just the look;
  `--no-peek` and `--no-ctrl-tab` leave them out of a CLI run.

## v0.3.0 — 2026-10-25

The first release of this fork: much more of Arc comes along, the app is new,
and Arc for Windows is supported.

### What moves

- Arc profiles become Zen containers, and each space opens in its profile's
  container.
- Cookies, saved passwords and sites' localStorage, per container.
- Boosts, as Zen boosts (without their JavaScript).
- Air Traffic Control rules, as Zen Space Routing (macOS).
- Languages: the languages sites are asked for, what to always or never
  translate, the spellcheck dictionary, and the interface language.
- An Arc-like Zen: the Arc Look mod, Arc's sidebar and toolbars, easier
  drag-to-split.
- Spaces without an Arc theme get Arc's default colors.
- The tabs of split views, which were lost before.
- Arc's own pages open as their Zen counterparts; tabs with broken addresses
  become blank tabs instead of making Zen's menus stop responding.

### The app

- One screen: pick spaces, pick a preset (Just tabs, Arc as it was, Just the
  look, Custom) or single items, and migrate.
- Just the look restyles Zen without migrating anything, even without Arc.
- Add to what's there, or replace Zen's contents; a clean rebuild also removes
  workspaces and containers Arc doesn't have.
- The Zen profile is backed up before every run, and the window can roll back
  to before the first run.
- Progress, a result screen with notes, and the log one click away.
- A faded bottom edge shows that a list or the result goes on below.
- After a failure, Report it on GitHub saves a diagnostic report without personal details and opens an
  issue with the versions and the error filled in.
- Close Zen if needed closes only the Zen running the target profile.
- Without Zen the app says how to get it.
- The window shows the app's version and links to its GitHub page.

### Windows

- Arc for Windows is read: spaces, cookies and passwords (no Keychain prompt),
  and Zen gets separate toolbars, as Arc for Windows always shows the address
  on top.
- Close Arc if needed quits Arc for cookies and boosts, which Arc for Windows
  locks while it runs.
- Zen is closed as with its close button instead of being killed.

### Releases

- Builds for macOS and Windows only, with `SHA256SUMS.txt`.
