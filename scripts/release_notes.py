#!/usr/bin/env python3
"""Print a release's notes: its CHANGELOG.md section, and a link to the full diff."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from arc2zen import __version__  # noqa: E402


def changelog_section(tag: str, changelog: Path = REPO_ROOT / "CHANGELOG.md") -> str:
    """The text under "## <tag> — <date>", up to the next release."""
    text = changelog.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(tag)}(?: —[^\n]*)?$\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match or not match.group(1).strip():
        raise SystemExit(f"CHANGELOG.md has no section for {tag}")
    return match.group(1).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="the release tag, such as v0.3.0")
    parser.add_argument("--previous", default="", help="the tag before it, for the link to the full diff")
    parser.add_argument("--repo", default="", help="owner/name on GitHub, for the link to the full diff")
    args = parser.parse_args()

    if args.tag != f"v{__version__}":
        raise SystemExit(f"Tag {args.tag} doesn't match the package version {__version__}")
    notes = changelog_section(args.tag)
    if args.previous and args.repo:
        notes += f"\n\n**Full Changelog**: https://github.com/{args.repo}/compare/{args.previous}...{args.tag}"
    print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
