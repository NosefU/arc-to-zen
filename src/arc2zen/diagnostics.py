"""What a run's log starts with: the versions involved, where the run reads and writes, and its choices."""

from __future__ import annotations

import configparser
import platform
import plistlib
import sys
from dataclasses import fields
from pathlib import Path
from typing import List

from . import __version__
from .profile_paths import resolve_arc_profile, resolve_zen_profile


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
