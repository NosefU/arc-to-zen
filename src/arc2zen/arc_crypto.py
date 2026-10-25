#!/usr/bin/env python3
"""Decrypt values Arc (Chromium) encrypts: with the "Arc Safe Storage" key on macOS, a DPAPI key on Windows."""

from __future__ import annotations

import base64
import functools
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .profile_paths import resolve_arc_profile

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
        raise ArcDecryptionError("Decrypting Arc data is only supported for Arc on macOS and Windows.")
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


class WindowsChromiumDecryptor:
    """Decrypts Windows Chromium "v10" values (AES-256-GCM with the key from Local State)."""

    def __init__(self, key: bytes):
        self._aead = AESGCM(key)

    def decrypt(self, encrypted: bytes) -> bytes:
        if encrypted[:3] != b"v10":
            raise ArcDecryptionError(f"unsupported encryption {encrypted[:3]!r}")
        try:
            return self._aead.decrypt(encrypted[3:15], encrypted[15:], None)
        except InvalidTag as exc:
            raise ArcDecryptionError("authentication failed; wrong key?") from exc


def dpapi_unprotect(data: bytes) -> bytes:
    """Decrypt data Windows protected for the current user."""
    import ctypes
    from ctypes import wintypes

    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
    ):
        raise ArcDecryptionError(f"Windows could not unlock Arc's key (error {ctypes.GetLastError()})")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def arc_windows_key(arc_profile: str | Path | None = None) -> bytes:
    """Arc's AES key from User Data/Local State, protected with DPAPI for the Windows user."""
    local_state = resolve_arc_profile(arc_profile) / "User Data" / "Local State"
    try:
        with open(local_state, encoding="utf-8") as f:
            encrypted_key = base64.b64decode(json.load(f)["os_crypt"]["encrypted_key"])
    except (OSError, ValueError, KeyError) as exc:
        raise ArcDecryptionError(f"Could not read Arc's key from {local_state}: {exc}") from exc
    if encrypted_key[:5] != b"DPAPI":
        raise ArcDecryptionError(f"unsupported Arc key {encrypted_key[:5]!r}")
    return dpapi_unprotect(encrypted_key[5:])


def arc_decryptor(arc_profile: str | Path | None = None) -> ChromiumDecryptor | WindowsChromiumDecryptor:
    """The decryptor for Arc's data on this OS; on macOS reading the key asks for Keychain access."""
    if sys.platform == "win32" and not os.environ.get(PASSWORD_ENV):
        return WindowsChromiumDecryptor(arc_windows_key(arc_profile))
    return ChromiumDecryptor(arc_safe_storage_password())
