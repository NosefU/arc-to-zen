#!/usr/bin/env python3
"""One backup of a Zen profile per migration run, and the rollback to it.

Before the first step, everything a migration may change in the profile is copied
into a folder inside the profile, with a manifest that also records which paths did
not exist yet. Rolling back puts the copies back and deletes what the run created.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

SNAPSHOT_PREFIX = "arc-to-zen-backup-"
MANIFEST = "manifest.json"

# The whole profile is copied except these: caches, telemetry and plugins that Zen
# rebuilds, Zen's lock files, and backups lying in the profile. A feature that has to
# change something in here extends the snapshot (see AGENTS.md).
SKIPPED_NAMES = {
    "cache2", "startupCache", "shader-cache", "safebrowsing", "security_state", "datareporting",
    "crashes", "minidumps", "saved-telemetry-pings", ".parentlock", "parent.lock", "lock",
}
SKIPPED_PREFIXES = ("gmp-", SNAPSHOT_PREFIX, "claude-backup-", "container-cleanup-backup-")
# Sites' storage is large and only its localStorage part ("ls") is ever changed:
# that part is copied, and the list of site folders is kept so that folders a run
# creates can be removed.
SITE_STORAGE = "storage/default"


def skipped(name: str) -> bool:
    return name in SKIPPED_NAMES or name.startswith(SKIPPED_PREFIXES) or ".codex-" in name


def snapshot_paths(profile: Path) -> List[str]:
    """Profile paths a snapshot copies (relative), site storage aside."""
    paths = []
    for child in sorted(profile.iterdir()):
        if skipped(child.name):
            continue
        if child.name == "storage" and child.is_dir():
            paths += [f"storage/{c.name}" for c in sorted(child.iterdir()) if c.name != "default"]
        else:
            paths.append(child.name)
    return paths


_active: Optional["Snapshot"] = None


def active_snapshot() -> Optional["Snapshot"]:
    """The snapshot of the run in progress, for steps that delete whole folders."""
    return _active


def set_active_snapshot(snapshot: Optional["Snapshot"]) -> None:
    global _active
    _active = snapshot


class Snapshot:
    def __init__(self, root: Path, profile: Path, entries: List[Dict], children: Dict[str, List[str]]):
        self.root = root
        self.profile = profile
        self.entries = entries
        self.children = children

    @classmethod
    def load(cls, root: str | Path) -> "Snapshot":
        """An earlier snapshot, for another run that should roll back to the same point."""
        root = Path(root)
        manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
        return cls(root, Path(manifest["profile"]), manifest["entries"], manifest["children"])

    @classmethod
    def take(cls, profile: Path) -> "Snapshot":
        profile = Path(profile)
        root = profile / f"{SNAPSHOT_PREFIX}{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        paths = snapshot_paths(profile)
        root.mkdir()
        # Names that existed in the profile root and in storage/; anything else there is the run's
        top = [p for p in paths if "/" not in p]
        in_storage = [p.split("/", 1)[1] for p in paths if p.startswith("storage/")]
        snapshot = cls(root, profile, [], {"": top, "storage": in_storage})
        site_storage = profile / SITE_STORAGE
        sites = sorted(p.name for p in site_storage.iterdir() if p.is_dir()) if site_storage.is_dir() else []
        snapshot.children[SITE_STORAGE] = sites
        paths += [f"{SITE_STORAGE}/{site}/ls" for site in sites]
        for relative in paths:
            snapshot._copy_in(relative, f"files/{relative}")
        snapshot._save()
        size = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
        logger.info(f"✅ Backed up the Zen profile to {root.name} ({size / 1_000_000:.1f} MB)")
        return snapshot

    def preserve(self, path: Path) -> None:
        """Move a folder a step is about to delete into the snapshot."""
        relative = Path(path).relative_to(self.profile).as_posix()
        target = self.root / "removed" / relative
        parent, _, name = relative.rpartition("/")
        # A folder an earlier run made, or one already kept, is not the profile's own: just delete it
        if (parent in self.children and name not in self.children[parent]) or target.exists():
            _remove(Path(path))
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), target)
        self.entries.append({"path": relative, "existed": True, "dir": True, "copy": f"removed/{relative}"})
        self._save()

    def _copy_in(self, relative: str, copy: str) -> None:
        source = self.profile / relative
        entry = {"path": relative, "existed": source.exists(), "dir": source.is_dir(), "copy": copy}
        if source.exists():
            target = self.root / copy
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target)
        self.entries.append(entry)

    def _save(self) -> None:
        manifest = {"profile": str(self.profile), "entries": self.entries, "children": self.children}
        (self.root / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def snapshot_profile(snapshot_dir: str | Path) -> Path:
    """The Zen profile a snapshot belongs to."""
    manifest = json.loads((Path(snapshot_dir) / MANIFEST).read_text(encoding="utf-8"))
    return Path(manifest["profile"])


def rollback(snapshot_dir: str | Path) -> int:
    """Put the profile back as it was when the snapshot was taken; returns restored paths."""
    root = Path(snapshot_dir)
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    profile = Path(manifest["profile"])
    # What the run created goes first, so restored paths are not touched again
    for relative, names in manifest["children"].items():
        folder = profile / relative if relative else profile
        if not folder.is_dir():
            continue
        for child in folder.iterdir():
            if relative == "" and (skipped(child.name) or child.name == "storage"):
                continue
            if relative == "storage" and child.name == "default":
                continue
            if child.name not in names:
                _remove(child)
    restored = 0
    for entry in manifest["entries"]:
        target = profile / entry["path"]
        _remove(target)
        if entry["existed"]:
            source = root / entry["copy"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if entry["dir"]:
                shutil.copytree(source, target, symlinks=True)
            else:
                shutil.copy2(source, target)
            restored += 1
    logger.info(f"✅ Rolled back {profile.name}: {restored} files and folders restored")
    return restored


def discard(snapshot_dir: str | Path | None) -> None:
    """Delete a snapshot that is no longer needed."""
    if snapshot_dir and Path(snapshot_dir).is_dir():
        shutil.rmtree(snapshot_dir, ignore_errors=True)
