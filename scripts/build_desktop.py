#!/usr/bin/env python3
"""Build a native-feeling desktop app package for release."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "arc-to-zen"
APP_DISPLAY_NAME = "Arc to Zen"
ASSETS_DIR = REPO_ROOT / "assets"


def platform_label() -> str:
    system = platform.system().lower() or "unknown"
    machine = platform.machine().lower() or "unknown"
    aliases = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
    }
    return f"{system}-{aliases.get(machine, machine)}"


def system_name() -> str:
    return platform.system().lower()


def pyinstaller_name() -> str:
    return APP_DISPLAY_NAME if system_name() in {"darwin", "windows"} else APP_NAME


def icon_path() -> Path:
    if system_name() == "darwin":
        return ASSETS_DIR / "app-icon.icns"
    if system_name() == "windows":
        return ASSETS_DIR / "app-icon.ico"
    return ASSETS_DIR / "app-icon.png"


def run_pyinstaller(label: str) -> Path:
    dist_dir = REPO_ROOT / "build" / "dist" / label
    work_dir = REPO_ROOT / "build" / "pyinstaller" / label
    spec_dir = REPO_ROOT / "build" / "pyinstaller" / "spec"

    for path in (dist_dir, work_dir):
        if path.exists():
            shutil.rmtree(path)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--name",
        pyinstaller_name(),
        "--hidden-import",
        "lz4.block",
        "--paths",
        str(REPO_ROOT / "src"),
        "--icon",
        str(icon_path()),
        "--add-data",
        f"{ASSETS_DIR / 'app-icon.png'}{os.pathsep}assets",
        # The bundled Arc Look mod, read next to arc2zen/arc_look_mod.py
        "--add-data",
        f"{REPO_ROOT / 'src' / 'arc2zen' / 'mods'}{os.pathsep}arc2zen/mods",
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        str(spec_dir),
        str(REPO_ROOT / "desktop.py"),
    ]

    if system_name() in {"darwin", "windows"}:
        command.insert(command.index("--name"), "--windowed")
    if system_name() == "darwin":
        command.extend(["--osx-bundle-identifier", "com.thinkscape.arc-to-zen"])

    subprocess.run(command, cwd=REPO_ROOT, check=True)

    if system_name() == "darwin":
        target = dist_dir / f"{APP_DISPLAY_NAME}.app"
        if not target.exists():
            raise FileNotFoundError(f"PyInstaller did not create {target}")
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(target)], check=True)
        return target

    target = dist_dir / pyinstaller_name()
    if not target.exists():
        raise FileNotFoundError(f"PyInstaller did not create {target}")

    executable = target / f"{APP_DISPLAY_NAME}.exe" if system_name() == "windows" else target / APP_NAME
    if not executable.exists():
        raise FileNotFoundError(f"PyInstaller did not create {executable}")

    if system_name() == "linux":
        executable.chmod(executable.stat().st_mode | 0o755)
        desktop_file = target / f"{APP_NAME}.desktop"
        desktop_file.write_text(
            "\n".join(
                [
                    "[Desktop Entry]",
                    "Type=Application",
                    f"Name={APP_DISPLAY_NAME}",
                    f"Exec=./{APP_NAME}",
                    f"Icon={APP_NAME}",
                    "Terminal=false",
                    "Categories=Utility;",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        shutil.copy2(ASSETS_DIR / "app-icon.png", target / f"{APP_NAME}.png")

    return target


def add_path_to_zip(zip_file: zipfile.ZipFile, source: Path, arcname: Path) -> None:
    if source.is_dir():
        for path in source.rglob("*"):
            zip_file.write(path, arcname / path.relative_to(source))
    else:
        zip_file.write(source, arcname)


def package_artifact(target: Path, label: str, version: str, artifact_dir: Path) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{APP_NAME}-{version}-{label}"

    if system_name() == "darwin":
        archive = artifact_dir / f"{base_name}.zip"
        subprocess.run(
            ["ditto", "-c", "-k", "--keepParent", "--norsrc", str(target), str(archive)],
            check=True,
        )
    elif system_name() == "windows":
        archive = artifact_dir / f"{base_name}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            add_path_to_zip(zip_file, target, Path(target.name))
    else:
        archive = artifact_dir / f"{base_name}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar_file:
            tar_file.add(target, arcname=target.name)

    return archive


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and package the Arc to Zen desktop app.")
    parser.add_argument("--version", default=os.environ.get("ARC_TO_ZEN_VERSION", "dev"))
    parser.add_argument("--platform-label", default=platform_label())
    parser.add_argument("--artifact-dir", type=Path, default=REPO_ROOT / "release-artifacts")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact_dir = args.artifact_dir.expanduser()
    if not artifact_dir.is_absolute():
        artifact_dir = REPO_ROOT / artifact_dir

    target = run_pyinstaller(args.platform_label)
    archive = package_artifact(target, args.platform_label, args.version, artifact_dir)
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
