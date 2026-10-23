#!/usr/bin/env python3
"""Copy Arc profile cookies into the Zen containers of the migrated workspaces."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .profile_paths import arc_profile_dir
from .sessions import read_mozilla_lz4, resolve_zen_profile

logger = logging.getLogger(__name__)

# Chromium stores times as microseconds since 1601-01-01.
CHROMIUM_EPOCH_OFFSET_US = 11_644_473_600 * 1_000_000

# Chromium cookie DB version 24 prefixes the plaintext with SHA-256(host_key).
HOST_HASH_DB_VERSION = 24

# Chromium CookieSameSite -> Firefox nsICookie sameSite
SAMESITE_MAP = {-1: 256, 0: 0, 1: 1, 2: 2}

# Firefox nsICookie scheme bits
SCHEME_HTTP = 1
SCHEME_HTTPS = 2

KEYCHAIN_SERVICE = "Arc Safe Storage"
PASSWORD_ENV = "ARC_SAFE_STORAGE_PASSWORD"


class CookieDecryptionError(RuntimeError):
    pass


def arc_safe_storage_password() -> bytes:
    """Read Arc's cookie password from the macOS Keychain; macOS asks the user first."""
    override = os.environ.get(PASSWORD_ENV)
    if override:
        return override.encode()
    if sys.platform != "darwin":
        raise CookieDecryptionError("Cookie migration is only supported for Arc on macOS for now.")
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", KEYCHAIN_SERVICE],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise CookieDecryptionError(
            f'Could not read "{KEYCHAIN_SERVICE}" from the Keychain (access denied or not found).'
        ) from exc
    return result.stdout.rstrip("\n").encode()


class ChromiumCookieDecryptor:
    """Decrypts macOS Chromium "v10" cookie values (AES-128-CBC, PBKDF2 key)."""

    def __init__(self, password: bytes):
        key = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16)
        self._cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))

    def decrypt(self, encrypted: bytes, host_key: str, db_version: int) -> str:
        if encrypted[:3] != b"v10":
            raise CookieDecryptionError(f"unsupported cookie encryption {encrypted[:3]!r}")
        decryptor = self._cipher.decryptor()
        padded = decryptor.update(encrypted[3:]) + decryptor.finalize()
        pad = padded[-1] if padded else 0
        if not 1 <= pad <= 16 or padded[-pad:] != bytes([pad]) * pad:
            raise CookieDecryptionError("bad padding; wrong Keychain password?")
        plain = padded[:-pad]
        if db_version >= HOST_HASH_DB_VERSION:
            if plain[:32] != hashlib.sha256(host_key.encode()).digest():
                raise CookieDecryptionError("host hash mismatch; wrong Keychain password?")
            plain = plain[32:]
        return plain.decode("utf-8")


def arc_cookie_db(arc_profile_name: str, arc_profile: str | Path | None) -> Optional[Path]:
    profile_dir = arc_profile_dir(arc_profile_name, arc_profile)
    for candidate in (profile_dir / "Network" / "Cookies", profile_dir / "Cookies"):
        if candidate.is_file():
            return candidate
    return None


def read_arc_cookies(db_path: Path, decryptor: ChromiumCookieDecryptor, stats: Dict[str, int]) -> Iterator[Dict[str, Any]]:
    """Yield persistent, unexpired, unpartitioned Arc cookies in Firefox field units."""
    con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        version_row = con.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
        db_version = int(version_row[0]) if version_row else 0
        now_us = int(time.time() * 1_000_000)
        rows = con.execute(
            # Arc stores some encrypted values with TEXT affinity; read them as bytes
            "SELECT host_key, top_frame_site_key, name, value, CAST(encrypted_value AS BLOB), path, expires_utc, "
            "is_secure, is_httponly, last_access_utc, has_expires, is_persistent, samesite, "
            "source_scheme, creation_utc, last_update_utc FROM cookies"
        )
        for (host, top_frame_site, name, value, encrypted, path, expires_utc, is_secure, is_httponly,
             last_access_utc, has_expires, is_persistent, samesite, source_scheme, creation_utc,
             last_update_utc) in rows:
            if top_frame_site:
                stats["partitioned"] += 1
                continue
            if not has_expires or not is_persistent:
                stats["session"] += 1
                continue
            expires_us = expires_utc - CHROMIUM_EPOCH_OFFSET_US
            if expires_us <= now_us:
                stats["expired"] += 1
                continue
            if encrypted:
                try:
                    value = decryptor.decrypt(encrypted, host, db_version)
                except (CookieDecryptionError, UnicodeDecodeError):
                    stats["undecryptable"] += 1
                    continue

            if source_scheme == 2 or (source_scheme == 0 and is_secure):
                scheme_map = SCHEME_HTTPS
            else:
                scheme_map = SCHEME_HTTP
            yield {
                "name": name,
                "value": value,
                "host": host,
                "path": path,
                "expiry": expires_us // 1000,
                "lastAccessed": max(last_access_utc - CHROMIUM_EPOCH_OFFSET_US, 0),
                "creationTime": max(creation_utc - CHROMIUM_EPOCH_OFFSET_US, 0),
                "updateTime": max((last_update_utc or creation_utc) - CHROMIUM_EPOCH_OFFSET_US, 0),
                "isSecure": int(bool(is_secure)),
                "isHttpOnly": int(bool(is_httponly)),
                "sameSite": SAMESITE_MAP.get(samesite, 256),
                "schemeMap": scheme_map,
            }
    finally:
        con.close()


def origin_attributes(user_context_id: int) -> str:
    return f"^userContextId={user_context_id}" if user_context_id else ""


def write_zen_cookies(con: sqlite3.Connection, cookies: List[Dict[str, Any]], user_context_id: int) -> int:
    attrs = origin_attributes(user_context_id)
    con.executemany(
        """
        INSERT INTO moz_cookies (originAttributes, name, value, host, path, expiry, lastAccessed,
            creationTime, isSecure, isHttpOnly, inBrowserElement, sameSite, schemeMap,
            isPartitionedAttributeSet, updateTime)
        VALUES (:attrs, :name, :value, :host, :path, :expiry, :lastAccessed, :creationTime,
            :isSecure, :isHttpOnly, 0, :sameSite, :schemeMap, 0, :updateTime)
        ON CONFLICT (name, host, path, originAttributes) DO UPDATE SET
            value = excluded.value, expiry = excluded.expiry, lastAccessed = excluded.lastAccessed,
            isSecure = excluded.isSecure, isHttpOnly = excluded.isHttpOnly,
            sameSite = excluded.sameSite, schemeMap = excluded.schemeMap,
            updateTime = excluded.updateTime
        """,
        [{**cookie, "attrs": attrs} for cookie in cookies],
    )
    return len(cookies)


def workspace_containers(profile: Path) -> Dict[str, int]:
    """Map Zen workspace names to their default container ids."""
    data = read_mozilla_lz4(profile / "zen-sessions.jsonlz4")
    return {space.get("name"): space.get("containerTabId") or 0 for space in data.get("spaces", [])}


def backup_cookie_db(path: Path, timestamp: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        source = Path(f"{path}{suffix}")
        if source.exists():
            target = source.with_name(f"{source.name}.codex-cookie-backup-{timestamp}")
            shutil.copy2(source, target)
    logger.info(f"✅ Backed up {path.name}")


def migrate_cookies(
    arc_profile: str | Path | None = None,
    zen_profile: str | Path | None = None,
    export_file: str | Path = "arc_pinned_tabs_export.json",
    create_backups: bool = True,
) -> bool:
    """Copy cookies of the Arc profiles behind the migrated spaces into their Zen containers."""
    profile = resolve_zen_profile(zen_profile)
    with open(Path(export_file).expanduser(), encoding="utf-8") as f:
        export_spaces = json.load(f).get("spaces", [])

    containers_by_space = workspace_containers(profile)
    context_by_profile: Dict[str, int] = {}
    for space in export_spaces:
        arc_profile_name = space.get("arc_profile")
        if arc_profile_name and arc_profile_name not in context_by_profile:
            context_by_profile[arc_profile_name] = containers_by_space.get(space["space_name"], 0)
    if not context_by_profile:
        logger.info("No Arc profile information in the export; skipping cookies")
        return True

    zen_cookies = profile / "cookies.sqlite"
    if not zen_cookies.exists():
        logger.error(f"❌ Zen cookie database not found: {zen_cookies}. Start Zen once with this profile.")
        return False

    try:
        decryptor = ChromiumCookieDecryptor(arc_safe_storage_password())
    except CookieDecryptionError as exc:
        logger.error(f"❌ {exc}")
        return False

    if create_backups:
        backup_cookie_db(zen_cookies, datetime.now().strftime("%Y%m%d-%H%M%S"))

    total = 0
    con = sqlite3.connect(zen_cookies)
    try:
        for arc_profile_name, user_context_id in context_by_profile.items():
            db_path = arc_cookie_db(arc_profile_name, arc_profile)
            if not db_path:
                logger.info(f"   Arc profile {arc_profile_name!r} has no cookie database; skipping")
                continue
            stats = {"session": 0, "expired": 0, "partitioned": 0, "undecryptable": 0}
            cookies = list(read_arc_cookies(db_path, decryptor, stats))
            if stats["undecryptable"] and not cookies:
                raise CookieDecryptionError("No cookie could be decrypted; wrong Keychain password?")
            written = write_zen_cookies(con, cookies, user_context_id)
            total += written
            skipped = ", ".join(f"{count} {kind}" for kind, count in stats.items() if count) or "none"
            logger.info(
                f"   Arc profile {arc_profile_name!r} -> container {user_context_id}: "
                f"{written} cookies copied (skipped: {skipped})"
            )
        con.commit()
    except CookieDecryptionError as exc:
        con.rollback()
        logger.error(f"❌ {exc}")
        return False
    finally:
        con.close()

    logger.info(f"Done. Copied {total} cookies into Zen.")
    return True
