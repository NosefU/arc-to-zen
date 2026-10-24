#!/usr/bin/env python3
"""Read files shipped inside the installed Zen (omni.ja), such as workspace icons."""

from __future__ import annotations

import functools
import mmap
import struct
import sys
import zlib
from pathlib import Path
from typing import Optional

from .zen_runner import ZenRunnerError, find_zen_binary

SELECTABLE_ICON_PATH = "chrome/browser/skin/classic/browser/zen-icons/selectable/{name}.svg"


def zen_omni_jar() -> Optional[Path]:
    try:
        binary = find_zen_binary()
    except ZenRunnerError:
        return None
    if sys.platform == "darwin":
        candidate = binary.parent.parent / "Resources" / "browser" / "omni.ja"
    else:
        candidate = binary.parent / "browser" / "omni.ja"
    return candidate if candidate.is_file() else None


def read_jar_entry(jar: Path, name: str) -> Optional[bytes]:
    """Read one file from a Mozilla jar.

    Mozilla's optimized jars put the central directory first, which Python's
    zipfile rejects, so the entry is found by its local file header instead.
    """
    wanted = name.encode()
    with open(jar, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        pos = 0
        while (index := data.find(wanted, pos)) >= 0:
            header = index - 30
            pos = index + 1
            if header < 0 or data[header:header + 4] != b"PK\x03\x04":
                continue
            method, = struct.unpack_from("<H", data, header + 8)
            compressed, _, name_length, extra_length = struct.unpack_from("<IIHH", data, header + 18)
            if name_length != len(wanted):
                continue
            start = header + 30 + name_length + extra_length
            raw = data[start:start + compressed]
            if method == 0:
                return bytes(raw)
            if method == 8:
                return zlib.decompress(raw, -15)
            return None
    return None


@functools.lru_cache(maxsize=128)
def zen_selectable_icon_svg(name: str) -> Optional[bytes]:
    """SVG of a Zen workspace icon by its Arc/Zen name, e.g. "planet"; None if Zen or the icon is missing."""
    if not name or "/" in name or ".." in name:
        return None
    jar = zen_omni_jar()
    if jar is None:
        return None
    try:
        return read_jar_entry(jar, SELECTABLE_ICON_PATH.format(name=name))
    except (OSError, ValueError, zlib.error):
        return None
