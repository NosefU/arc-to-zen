#!/usr/bin/env python3
"""Decrypt values Arc (Chromium) encrypts with the "Arc Safe Storage" key."""

from __future__ import annotations

import functools
import hashlib
import os
import subprocess
import sys

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

KEYCHAIN_SERVICE = "Arc Safe Storage"
PASSWORD_ENV = "ARC_SAFE_STORAGE_PASSWORD"


class ArcDecryptionError(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def arc_safe_storage_password() -> bytes:
    """Read Arc's encryption password from the macOS Keychain once per run; macOS asks the user first."""
    override = os.environ.get(PASSWORD_ENV)
    if override:
        return override.encode()
    if sys.platform != "darwin":
        raise ArcDecryptionError("Decrypting Arc data is only supported for Arc on macOS for now.")
    import pwd

    # security finds the login keychain through HOME, so use the account's real home
    env = {**os.environ, "HOME": pwd.getpwuid(os.getuid()).pw_dir}
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", KEYCHAIN_SERVICE],
            capture_output=True,
            text=True,
            check=True,
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        reason = exc.stderr.strip().removeprefix("security: ") or f"exit code {exc.returncode}"
        raise ArcDecryptionError(f'Could not read "{KEYCHAIN_SERVICE}" from the Keychain: {reason}') from exc
    return result.stdout.rstrip("\n").encode()


class ChromiumDecryptor:
    """Decrypts macOS Chromium "v10" values (AES-128-CBC with a PBKDF2 key)."""

    def __init__(self, password: bytes):
        key = hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16)
        self._cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))

    def decrypt(self, encrypted: bytes) -> bytes:
        if encrypted[:3] != b"v10":
            raise ArcDecryptionError(f"unsupported encryption {encrypted[:3]!r}")
        decryptor = self._cipher.decryptor()
        padded = decryptor.update(encrypted[3:]) + decryptor.finalize()
        pad = padded[-1] if padded else 0
        if not 1 <= pad <= 16 or padded[-pad:] != bytes([pad]) * pad:
            raise ArcDecryptionError("bad padding; wrong Keychain password?")
        return padded[:-pad]
