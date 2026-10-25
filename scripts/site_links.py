#!/usr/bin/env python3
"""Copy the landing page with its download links pointing straight at the latest release's archives."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import urllib.request
from pathlib import Path


PLATFORMS = ("macos-arm64", "macos-x64", "windows-x64")


def latest_release(repo: str, token: str = "") -> dict:
    """The latest published release; drafts and pre-releases don't count."""
    request = urllib.request.Request(f"https://api.github.com/repos/{repo}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def fill_links(html: str, release: dict) -> str:
    """Puts each archive's address, name and size into its link, and the version next to the buttons."""
    for platform in PLATFORMS:
        asset = next((a for a in release["assets"] if a["name"].endswith(f"-{platform}.zip")), None)
        if asset is None:
            raise SystemExit(f"Release {release['tag_name']} has no archive for {platform}")
        link = re.compile(rf'(<a class="file" data-asset="{platform}"[^>]* href=")[^"]*(">.*?<span>)[^<]*(</span>)')
        html, found = link.subn(
            lambda m: f"{m[1]}{asset['browser_download_url']}{m[2]}{asset['name']} · {asset['size'] / 1048576:.0f} MB{m[3]}",
            html)
        if found != 1:
            raise SystemExit(f"site/index.html has no download link for {platform}")
    tag = release["tag_name"]
    html = html.replace('<small id="primary-version"></small>', f'<small id="primary-version">{tag}</small>')
    html = html.replace('<span class="eyebrow" id="release-name">Latest release</span>',
                        f'<span class="eyebrow" id="release-name">Latest release · {tag}</span>')
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path, help="the folder with index.html")
    parser.add_argument("out", type=Path, help="where to put the finished copy")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""), help="owner/name on GitHub")
    args = parser.parse_args()

    release = latest_release(args.repo, os.environ.get("GITHUB_TOKEN", ""))
    shutil.copytree(args.site, args.out, dirs_exist_ok=True)
    page = args.out / "index.html"
    page.write_text(fill_links(page.read_text(encoding="utf-8"), release), encoding="utf-8")
    print(f"Download links point at {release['tag_name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
