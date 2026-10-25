"""What a bug report needs: versions, the files involved, and text cleared of personal details.

Nothing here reads what is inside cookies, passwords or site data; the report lists
files by name and size. Every text that goes into a report passes Sanitizer.clean(),
and a report that still names the user or the computer is not written.
"""

from __future__ import annotations

import configparser
import os
import platform
import plistlib
import re
import sys
import zipfile
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

from . import __version__
from .profile_paths import resolve_arc_profile, resolve_zen_profile

REPO_URL = "https://github.com/NosefU/arc-to-zen"
# GitHub refuses longer new-issue links; the full details are in the report
MAX_ISSUE_URL = 7000

ARC_FILES = ("StorableSidebar.json", "StorableWindows.json", "StorableLinkRouting.json", "User Data/Local State")
ARC_PROFILE_FILES = ("Network/Cookies", "Cookies", "Login Data", "Login Data For Account", "Preferences")
ZEN_FILES = ("zen-sessions.jsonlz4", "sessionstore.jsonlz4", "prefs.js", "user.js", "containers.json", "cookies.sqlite",
             "logins.json", "key4.db", "zen-boosts.jsonlz4", "zen-space-routing.jsonlz4", "compatibility.ini",
             "parent.lock", "lock", ".parentlock")
# Chromium's own profile folder names say nothing about the user and help reading the log
CHROMIUM_PROFILE_NAME = re.compile(r"^(Default|Profile \d+|Guest Profile|System Profile)$")


# ----- versions -----------------------------------------------------------

def system_name() -> str:
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}"
    if sys.platform == "win32":
        version = sys.getwindowsversion()
        name = "Windows 11" if version.major == 10 and version.build >= 22000 else f"Windows {version.major}"
        return f"{name} (build {version.build})"
    return f"{platform.system()} {platform.release()}"


def app_version() -> str:
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    kind = "app" if getattr(sys, "frozen", False) else "source"
    return f"{__version__} ({kind}, {arch})"


def runtime_versions() -> str:
    versions = [f"Python {platform.python_version()}"]
    try:
        import PySide6

        versions.append(f"Qt {PySide6.__version__}")
    except ImportError:
        pass
    return ", ".join(versions)


def arc_version(arc_profile: str | Path | None = None) -> str:
    if sys.platform == "darwin":
        for app in (Path("/Applications/Arc.app"), Path.home() / "Applications" / "Arc.app"):
            try:
                with open(app / "Contents" / "Info.plist", "rb") as f:
                    return plistlib.load(f).get("CFBundleShortVersionString", "unknown")
            except OSError:
                continue
        return "unknown"
    try:
        # Arc for Windows keeps a folder named after its package next to its data folder
        local = resolve_arc_profile(arc_profile).parent
        folders = sorted(local.glob("TheBrowserCompany.Arc_*"))
    except (FileNotFoundError, OSError):
        return "unknown"
    return folders[-1].name.rsplit("_", 1)[-1] if folders else "unknown"


def zen_version(zen_profile: str | Path | None = None) -> str:
    try:
        parser = configparser.ConfigParser()
        parser.read(resolve_zen_profile(zen_profile) / "compatibility.ini", encoding="utf-8")
        # LastVersion=1.17.3b_20251010000000/20251010000000
        return parser.get("Compatibility", "LastVersion").split("_", 1)[0]
    except (configparser.Error, FileNotFoundError, OSError, ValueError):
        return "unknown"


def header_lines(arc_profile: str | Path | None, zen_profile: str | Path | None) -> List[str]:
    """What a run's log starts with, so a pasted log says where it came from."""
    return [
        f"Arc to Zen {app_version()} · {system_name()} · {runtime_versions()}",
        f"Arc {arc_version(arc_profile)} · Zen {zen_version(zen_profile)}",
    ]


def options_lines(options) -> List[str]:
    """A run's choices: the items on and off by name, the folders, and how many spaces."""
    on, off, other = [], [], []
    for item in fields(options):
        value = getattr(options, item.name)
        if isinstance(value, bool):
            (on if value else off).append(item.name)
        elif item.name == "spaces":
            other.append(f"Spaces: {'all' if value is None else len(value)}")
    return [f"On: {', '.join(on) or '-'}", f"Off: {', '.join(off) or '-'}", *other]


def run_lines(options) -> List[str]:
    """Where a run reads and writes, and what it does; the log starts with them after the versions."""
    lines = []
    for label, resolve, value in (("Arc data", resolve_arc_profile, options.arc_profile),
                                  ("Zen profile", resolve_zen_profile, options.zen_profile)):
        try:
            lines.append(f"{label}: {resolve(value)}")
        except (FileNotFoundError, OSError, ValueError):
            lines.append(f"{label}: {value or 'not found'}")
    return lines + options_lines(options)


# ----- files --------------------------------------------------------------

def size_text(size: int) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def file_state(path: Path) -> str:
    if not path.exists():
        return "missing"
    if path.is_dir():
        files = [p for p in path.rglob("*") if p.is_file()]
        return f"folder, {len(files)} files, {size_text(sum(p.stat().st_size for p in files))}"
    try:
        with open(path, "rb") as f:
            f.read(1)
    except PermissionError:
        return f"{size_text(path.stat().st_size)}, locked"
    except OSError as exc:
        return f"{size_text(path.stat().st_size)}, unreadable ({type(exc).__name__})"
    return size_text(path.stat().st_size)


def sidebar_summary(arc_root: Path) -> List[str]:
    """The shape of StorableSidebar.json: what kinds of items it holds, never their names or addresses."""
    import json

    try:
        with open(arc_root / "StorableSidebar.json", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        return [f"  StorableSidebar.json can't be read: {type(exc).__name__}"]
    lines = []
    sidebar = data.get("sidebar", {})
    containers = sidebar.get("containers", [])
    sync = data.get("firebaseSyncState", {}).get("syncData", {})
    models = sync.get("spaceModels", [])
    lines.append(f"  spaceModels: {len(models) // 2 if models else 'empty'}")
    for index, container in enumerate(containers):
        if not isinstance(container, dict):
            continue
        kinds: Dict[str, int] = {}
        items = container.get("items", [])
        for item in items[1::2] if items and isinstance(items[0], str) else items:
            if isinstance(item, dict):
                kind = next(iter(item.get("data", {}) or {"unknown": None}))
                kinds[kind] = kinds.get(kind, 0) + 1
        spaces = container.get("spaces", [])
        keys = sorted(k for k in container if k not in ("items", "spaces"))
        lines.append(f"  container {index}: {len(spaces) // 2 if spaces else 0} spaces, items "
                     + (", ".join(f"{k} {n}" for k, n in sorted(kinds.items())) or "none")
                     + (f"; keys {', '.join(keys)}" if keys else ""))
        for space in spaces[1::2] if spaces and isinstance(spaces[0], str) else spaces:
            if isinstance(space, dict):
                lists = [key for key in ("containerIDs", "newContainerIDs") if key in space]
                lines.append(f"    space: {', '.join(lists) or 'no container lists'}")
                break
    return lines


def file_inventory(arc_profile: str | Path | None, zen_profile: str | Path | None) -> List[str]:
    lines = ["Arc"]
    try:
        arc_root = resolve_arc_profile(arc_profile)
    except (FileNotFoundError, OSError):
        lines.append("  not found")
    else:
        for name in ARC_FILES:
            lines.append(f"  {name}: {file_state(arc_root / name)}")
        user_data = arc_root / "User Data"
        profiles = sorted(p for p in user_data.iterdir() if (p / "Preferences").exists()) if user_data.is_dir() else []
        for profile in profiles:
            for name in ARC_PROFILE_FILES:
                path = profile / name
                if path.exists():
                    lines.append(f"  User Data/{profile.name}/{name}: {file_state(path)}")
            lines.append(f"  User Data/{profile.name}/Local Storage/leveldb: "
                         f"{file_state(profile / 'Local Storage' / 'leveldb')}")
        firestore = arc_root.parent / "firestore" / "Arc"
        for path in sorted(firestore.rglob("*")) if firestore.is_dir() else []:
            if path.is_file():
                lines.append(f"  firestore/{path.relative_to(firestore).as_posix()}: {file_state(path)}")
        lines.append("Arc sidebar")
        lines.extend(sidebar_summary(arc_root))

    lines.append("Zen profile")
    try:
        profile = resolve_zen_profile(zen_profile)
    except (FileNotFoundError, OSError, ValueError):
        lines.append("  not found")
    else:
        for name in ZEN_FILES:
            path = profile / name
            if path.exists():
                lines.append(f"  {name}: {file_state(path)}")
        backups = list(profile.glob("arc-to-zen-backup-*"))
        lines.append(f"  arc-to-zen backups: {len(backups)}")
    return lines


# ----- cleaning -----------------------------------------------------------

SEPARATOR = r"(?:[\\/]|%5[cC]|%2[fF])+"
URL = re.compile(r"\b(https?|wss?|ftp)://([^/\s'\"<>()\[\]\\]+)[^\s'\"<>()\[\]]*", re.I)
SID = re.compile(r"\bS-1-5-21(?:-\d+){1,4}\b")
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
ONEDRIVE_ORG = re.compile(r"OneDrive - [^\\/\r\n'\"]+", re.I)


def path_pattern(path: str) -> re.Pattern:
    """A path however a log writes it: either slash, doubled backslashes, URL-encoded, any case."""
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    leading = SEPARATOR if path[:1] in "\\/" and not re.match(r"^[A-Za-z]:", path) else ""
    if path.startswith(("\\\\", "//")) and not path.startswith(("\\\\?\\", "//?/")):
        leading = r"(?:\\\\|//|\\\\\\\\)"  # a network share
    body = SEPARATOR.join(re.escape(p).replace(r"\ ", "(?: |%20)") for p in parts)
    prefix = r"(?:\\\\\?\\|\\\\\\\\\?\\\\\\\\)?"  # \\?\ long-path prefix, also with doubled backslashes
    # Not a longer name that starts the same, such as jdoe2 or the short JDOE~1
    return re.compile(prefix + leading + body + r"(?![\w.~-])", re.I)


def word_pattern(word: str) -> re.Pattern:
    """A name on its own, also right after a URL-encoded slash."""
    return re.compile(rf"(?:(?<![\w-])|(?<=%5[cC])|(?<=%2[fF])){re.escape(word)}(?![\w-])", re.I)


def windows_short_path(path: str) -> Optional[str]:
    if sys.platform != "win32":
        return None
    import ctypes

    buffer = ctypes.create_unicode_buffer(1024)
    if ctypes.windll.kernel32.GetShortPathNameW(path, buffer, len(buffer)) and buffer.value.lower() != path.lower():
        return buffer.value
    return None


@dataclass
class Sanitizer:
    """Takes the user, the computer and the user's own names out of a text.

    paths: real path -> what it becomes, such as the home folder -> "~".
    words: names that can appear anywhere (user, computer, domain) -> a placeholder.
    names: space and profile names the user gave -> numbered placeholders.
    """

    paths: Dict[str, str] = field(default_factory=dict)
    words: Dict[str, str] = field(default_factory=dict)
    names: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def for_this_computer(cls, space_names: Iterable[str] = (), profile_names: Iterable[str] = (),
                          env: Optional[Dict[str, str]] = None, home: Optional[str] = None,
                          user: Optional[str] = None, computer: Optional[str] = None) -> "Sanitizer":
        env = dict(os.environ if env is None else env)
        home = home or str(Path.home())
        paths = {home: "~"}
        short = windows_short_path(home)
        if short:
            paths[short] = "~"
        # Folders Windows may keep away from the home folder: another drive, a network share, OneDrive
        for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "HOMESHARE", "OneDrive",
                     "OneDriveCommercial", "OneDriveConsumer"):
            value = env.get(name)
            if value and not (value.lower() + "\\").replace("/", "\\").startswith(home.lower().replace("/", "\\") + "\\"):
                paths[value] = f"%{name.upper()}%" if name != "USERPROFILE" else "~"
        words = {}
        user = user or env.get("USERNAME") or env.get("USER") or Path(home).name
        computer = computer or env.get("COMPUTERNAME") or platform.node().split(".")[0]
        # A local account's domain is the computer's name, which keeps its <computer>
        for value, placeholder in ((user, "<user>"), (computer, "<computer>"),
                                   (env.get("USERDOMAIN"), "<domain>"), (env.get("USERDNSDOMAIN"), "<domain>")):
            if value and len(value) >= 3 and value.lower() not in {word.lower() for word in words}:
                words[value] = placeholder
        if sys.platform == "darwin":
            try:
                import pwd

                full_name = pwd.getpwuid(os.getuid()).pw_gecos.strip()
                if len(full_name) >= 3:
                    words.setdefault(full_name, "<user>")
            except (ImportError, KeyError):
                pass
        names = {}
        for kind, values in (("space", space_names), ("profile", profile_names)):
            for value in values:
                if value and len(value) >= 3 and not CHROMIUM_PROFILE_NAME.match(value) and value not in names:
                    names[value] = f"<{kind} {sum(1 for v in names.values() if v.startswith('<' + kind)) + 1}>"
        return cls(paths, words, names)

    def clean(self, text: str) -> str:
        # Only the site: a path or query can carry tokens, and user:password@ the account
        text = URL.sub(lambda m: f"{m.group(1)}://{m.group(2).rsplit('@', 1)[-1]}", text)
        for path, placeholder in sorted(self.paths.items(), key=lambda item: -len(item[0])):
            text = path_pattern(path).sub(placeholder.replace("\\", "\\\\"), text)
        text = ONEDRIVE_ORG.sub("OneDrive", text)
        text = SID.sub("<SID>", text)
        text = EMAIL.sub("<email>", text)
        for word, placeholder in sorted({**self.names, **self.words}.items(), key=lambda item: -len(item[0])):
            text = word_pattern(word).sub(placeholder, text)
        return text

    def leaks(self, text: str) -> List[str]:
        """What a cleaned text still gives away; a report with any of it is not written."""
        found = [path for path in self.paths if path_pattern(path).search(text)]
        found += [word for word in self.words if word_pattern(word).search(text)]
        return found


# ----- the report ---------------------------------------------------------

@dataclass
class FailureReport:
    options: object  # MigrationOptions
    steps: Sequence[Tuple[str, str]]  # title and how it ended: done, noted, failed or pending
    failed_step: str
    error: str
    traceback: str
    log: str
    space_names: Sequence[str] = ()
    profile_names: Sequence[str] = ()

    def sanitizer(self) -> Sanitizer:
        return Sanitizer.for_this_computer(self.space_names, self.profile_names)

    def files(self) -> Dict[str, str]:
        """The report's files, cleaned."""
        arc_profile = getattr(self.options, "arc_profile", None)
        zen_profile = getattr(self.options, "zen_profile", None)
        marks = {"done": "✓", "noted": "i", "failed": "✗", "pending": "·"}
        steps = [f"  {marks.get(state, '?')} {index}. {title}" for index, (title, state) in enumerate(self.steps, 1)]
        report = "\n".join([
            "# Arc to Zen failure report",
            "",
            *header_lines(arc_profile, zen_profile),
            "",
            "## Choices",
            *run_lines(self.options),
            "",
            "## Steps",
            *steps,
            "",
            "## Error",
            f"{self.failed_step}: {self.error}",
            "",
            self.traceback.strip() or "(no traceback)",
            "",
        ])
        clean = self.sanitizer().clean
        return {
            "report.md": clean(report),
            "log.txt": clean(self.log),
            "files.txt": clean("\n".join(file_inventory(arc_profile, zen_profile)) + "\n"),
        }

    def save(self, folder: Path) -> Path:
        files = self.files()
        sanitizer = self.sanitizer()
        leaks = sorted({leak for text in files.values() for leak in sanitizer.leaks(text)})
        if leaks:
            raise ValueError("The report still names this computer or its user, so it wasn't saved")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"arc-to-zen-report-{datetime.now():%Y%m%d-%H%M%S}.zip"
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, text in files.items():
                archive.writestr(name, text)
        return path

    def issue_url(self) -> str:
        clean = self.sanitizer().clean
        arc_profile = getattr(self.options, "arc_profile", None)
        zen_profile = getattr(self.options, "zen_profile", None)
        exception = self.traceback.strip().splitlines()[-1] if self.traceback.strip() else self.error
        kind = exception.split(":", 1)[0] if ":" in exception else "error"
        fields_ = {
            "template": "migration.yml",
            "title": clean(f"Migration stopped at “{self.failed_step}”: {kind}"),
            "version": app_version(),
            "system": system_name(),
            "browsers": f"Arc {arc_version(arc_profile)} · Zen {zen_version(zen_profile)}",
            "step": clean(self.failed_step),
            "error": clean(self.error),
        }
        url = f"{REPO_URL}/issues/new?{urlencode(fields_)}"
        while len(url) > MAX_ISSUE_URL and len(fields_["error"]) > 80:
            fields_["error"] = fields_["error"][: len(fields_["error"]) // 2] + "…"
            url = f"{REPO_URL}/issues/new?{urlencode(fields_)}"
        return url
