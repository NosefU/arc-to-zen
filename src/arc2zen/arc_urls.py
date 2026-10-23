#!/usr/bin/env python3
"""Turn Arc-only tab URLs into their Zen counterparts, or drop them."""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

# Arc's internal pages (arc:// and the Chromium chrome:// aliases) with a Zen equivalent.
# Zen has no history page, only the Library window, so arc://history is dropped.
INTERNAL_PAGES = {
    "downloads": "about:downloads",
    "settings": "about:preferences",
    "extensions": "about:addons",
    "password-manager": "about:logins",
    "passwords": "about:logins",
}

INTERNAL_SCHEMES = ("arc", "chrome")

# Pages that only existed inside Arc: extension pages and in-memory blobs.
DEAD_SCHEMES = ("chrome-extension", "blob", "filesystem", "devtools", "chrome-untrusted")


def convert_arc_url(url: Optional[str]) -> Optional[str]:
    """Return the URL to open in Zen, or None when the tab cannot be opened there."""
    if not url:
        return url
    scheme = url.split(":", 1)[0].lower()
    if scheme in INTERNAL_SCHEMES:
        parts = urlsplit(url)
        page = parts.netloc.lower()
        if page == "settings" and parts.path.lower().startswith("/passwords"):
            return "about:logins"
        return INTERNAL_PAGES.get(page)
    if scheme in DEAD_SCHEMES:
        return None
    return url
