"""The landing page gets the latest release's archives in its download links."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from site_links import fill_links  # noqa: E402

PAGE = (ROOT / "site" / "index.html").read_text(encoding="utf-8")


def release(*platforms):
    url = "https://github.com/NosefU/arc-to-zen/releases/download/v9.9.9"
    return {"tag_name": "v9.9.9", "assets": [
        {"name": f"arc-to-zen-v9.9.9-{p}.zip", "size": 43 * 1048576, "browser_download_url": f"{url}/arc-to-zen-v9.9.9-{p}.zip"}
        for p in platforms] + [{"name": "SHA256SUMS.txt", "size": 300, "browser_download_url": f"{url}/SHA256SUMS.txt"}]}


class DownloadLinks(unittest.TestCase):
    def test_each_platform_gets_its_archive(self):
        html = fill_links(PAGE, release("macos-arm64", "macos-x64", "windows-x64"))
        for platform in ("macos-arm64", "macos-x64", "windows-x64"):
            name = f"arc-to-zen-v9.9.9-{platform}.zip"
            self.assertRegex(html, rf'data-asset="{platform}"[^>]* href="https://github.com/NosefU/arc-to-zen/releases/download/v9.9.9/{name}"')
            self.assertIn(f"<span>{name} · 43 MB</span>", html)
        self.assertIn('<small id="primary-version">v9.9.9</small>', html)
        self.assertIn("Latest release · v9.9.9", html)

    def test_a_missing_archive_stops_the_deploy(self):
        with self.assertRaises(SystemExit):
            fill_links(PAGE, release("macos-arm64", "windows-x64"))


if __name__ == "__main__":
    unittest.main()
