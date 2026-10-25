#!/usr/bin/env python3
"""Copy saved passwords of the migrated Arc profiles into Zen's password manager."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlsplit

from .arc_crypto import ArcDecryptionError, ChromiumDecryptor, WindowsChromiumDecryptor, arc_decryptor
from .profile_paths import arc_profile_dir
from .sessions import resolve_zen_profile
from .zen_runner import ZenRunnerError, run_in_zen

logger = logging.getLogger(__name__)

CHROMIUM_EPOCH_OFFSET_US = 11_644_473_600 * 1_000_000

# Chromium PasswordForm::Scheme
SCHEME_HTML = 0
SCHEME_BASIC = 1
SCHEME_DIGEST = 2

# Regular and account-stored passwords of a Chromium profile
LOGIN_DATABASES = ("Login Data", "Login Data For Account")


def url_origin(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return f"{parts.scheme}://{parts.netloc.rsplit('@', 1)[-1]}"


def chromium_time_ms(value: Optional[int]) -> Optional[int]:
    if not value:
        return None
    return max((value - CHROMIUM_EPOCH_OFFSET_US) // 1000, 0)


def read_arc_logins(db_path: Path, decryptor: ChromiumDecryptor | WindowsChromiumDecryptor, stats: Dict[str, int]) -> Iterator[Dict[str, Any]]:
    """Yield Arc logins as nsILoginInfo fields; never logs passwords."""
    con = sqlite3.connect(f"{db_path.as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        rows = con.execute(
            # Read encrypted passwords as bytes even if stored with TEXT affinity
            "SELECT origin_url, action_url, username_element, username_value, password_element, "
            "CAST(password_value AS BLOB), signon_realm, date_created, blacklisted_by_user, scheme, times_used, "
            "date_last_used, date_password_modified, federation_url FROM logins"
        )
        for (origin_url, action_url, username_element, username, password_element, encrypted,
             signon_realm, date_created, blacklisted, scheme, times_used, date_last_used,
             date_password_modified, federation_url) in rows:
            if blacklisted:
                stats["never-save"] += 1
                continue
            origin = url_origin(origin_url) or url_origin(signon_realm)
            if not origin or federation_url or not encrypted:
                stats["unsupported"] += 1
                continue
            try:
                password = decryptor.decrypt(encrypted).decode("utf-8")
            except (ArcDecryptionError, UnicodeDecodeError):
                stats["undecryptable"] += 1
                continue

            if scheme in (SCHEME_BASIC, SCHEME_DIGEST):
                # signon_realm is "<origin>/<realm>" for HTTP auth
                http_realm = signon_realm[len(origin) + 1:] if signon_realm.startswith(origin + "/") else signon_realm
                form_action_origin = None
            elif scheme == SCHEME_HTML:
                http_realm = None
                form_action_origin = url_origin(action_url) or ""
            else:
                stats["unsupported"] += 1
                continue

            yield {
                "origin": origin,
                "formActionOrigin": form_action_origin,
                "httpRealm": http_realm,
                "username": username or "",
                "password": password,
                "usernameField": username_element or "",
                "passwordField": password_element or "",
                "timeCreated": chromium_time_ms(date_created),
                "timeLastUsed": chromium_time_ms(date_last_used),
                "timePasswordChanged": chromium_time_ms(date_password_modified),
                "timesUsed": times_used or 0,
            }
    finally:
        con.close()


ADD_LOGINS_SCRIPT = """
const [logins] = arguments;
return (async () => {
const { LoginHelper } = ChromeUtils.importESModule("resource://gre/modules/LoginHelper.sys.mjs");
if (LoginHelper.isPrimaryPasswordSet()) {
  return {error: "primary-password"};
}
// Same site, same auth kind (form or HTTP realm), same user: the login already exists
const key = l => [l.origin, l.httpRealm ?? "<form>", l.username].join("\\n");
const existing = new Set((await Services.logins.getAllLogins()).map(key));
const infos = [];
let skipped = 0;
for (const login of logins) {
  const k = key(login);
  if (existing.has(k)) { skipped++; continue; }
  existing.add(k);
  const info = Cc["@mozilla.org/login-manager/loginInfo;1"].createInstance(Ci.nsILoginInfo);
  info.init(login.origin, login.formActionOrigin, login.httpRealm, login.username, login.password,
            login.usernameField, login.passwordField);
  info.QueryInterface(Ci.nsILoginMetaInfo);
  for (const field of ["timeCreated", "timeLastUsed", "timePasswordChanged"]) {
    if (login[field]) info[field] = login[field];
  }
  info.timesUsed = login.timesUsed;
  infos.push(info);
}
if (infos.length) await Services.logins.addLogins(infos);
return {added: infos.length, existing: skipped};
})();
"""


def migrate_passwords(
    arc_profile: str | Path | None = None,
    zen_profile: str | Path | None = None,
    export_file: str | Path = "arc_pinned_tabs_export.json",
    create_backups: bool = True,
) -> bool:
    """Copy passwords of the Arc profiles behind the migrated spaces into Zen.

    Zen encrypts logins with its own key, so a headless Zen adds them.
    """
    profile = resolve_zen_profile(zen_profile)
    with open(Path(export_file).expanduser(), encoding="utf-8") as f:
        export_spaces = json.load(f).get("spaces", [])
    arc_profiles = list(dict.fromkeys(space["arc_profile"] for space in export_spaces if space.get("arc_profile")))
    if not arc_profiles:
        logger.info("No Arc profile information in the export; skipping passwords")
        return True

    try:
        decryptor = arc_decryptor(arc_profile)
    except ArcDecryptionError as exc:
        logger.error(f"❌ {exc}")
        return False

    logins: List[Dict[str, Any]] = []
    for arc_profile_name in arc_profiles:
        stats = {"never-save": 0, "unsupported": 0, "undecryptable": 0}
        found = []
        for db_name in LOGIN_DATABASES:
            db_path = arc_profile_dir(arc_profile_name, arc_profile) / db_name
            if db_path.is_file():
                found.extend(read_arc_logins(db_path, decryptor, stats))
        if stats["undecryptable"] and not found:
            logger.error(f"❌ No password of Arc profile {arc_profile_name!r} could be decrypted; wrong key?")
            return False
        skipped = ", ".join(f"{count} {kind}" for kind, count in stats.items() if count) or "none"
        logger.info(f"   Arc profile {arc_profile_name!r}: {len(found)} passwords read (skipped: {skipped})")
        logins.extend(found)

    if not logins:
        logger.info("No passwords to copy")
        return True

    if create_backups:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        for name in ("logins.json", "logins.db", "key4.db"):
            source = profile / name
            if source.exists():
                backup = source.with_name(f"{name}.codex-password-backup-{timestamp}")
                backup.write_bytes(source.read_bytes())
        logger.info("✅ Backed up the Zen password store and key4.db")

    try:
        result = run_in_zen(profile, ADD_LOGINS_SCRIPT, [logins])
    except ZenRunnerError as exc:
        logger.error(f"❌ {exc}")
        return False
    if result.get("error") == "primary-password":
        logger.error("❌ The Zen profile has a Primary Password; remove it in Zen settings and run again.")
        return False

    logger.info(f"Done. Added {result['added']} passwords to Zen, {result['existing']} were already there.")
    return True

