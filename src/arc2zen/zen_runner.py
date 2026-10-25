#!/usr/bin/env python3
"""Run chrome-privileged JavaScript inside a headless Zen on one profile.

Used for data Zen has to write itself, such as logins encrypted with the
profile's own key. Zen is started on the target profile only, through
Marionette on a free local port, and every temporary change is undone after.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Iterator, List, Optional

from .profile_paths import is_zen_profile_in_use

logger = logging.getLogger(__name__)

ZEN_BINARY_ENV = "ZEN_BINARY"
PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
USER_JS_MARKER = "// arc-to-zen: temporary Marionette port"


class ZenRunnerError(RuntimeError):
    pass


def find_zen_binary() -> Path:
    override = os.environ.get(ZEN_BINARY_ENV)
    candidates: List[Path] = [Path(override)] if override else []
    if sys.platform == "darwin":
        candidates += [
            Path("/Applications/Zen.app/Contents/MacOS/zen"),
            Path.home() / "Applications" / "Zen.app" / "Contents" / "MacOS" / "zen",
        ]
    elif sys.platform == "win32":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if root:
                candidates.append(Path(root) / "Zen Browser" / "zen.exe")
    for name in ("zen", "zen-browser"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise ZenRunnerError(f"Zen executable not found; set {ZEN_BINARY_ENV} to its path.")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class MarionetteClient:
    def __init__(self, port: int, timeout: float = 60):
        deadline = time.monotonic() + timeout
        while True:
            try:
                self._sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise ZenRunnerError("Zen did not start Marionette in time.")
                time.sleep(0.5)
        self._file = self._sock.makefile("rb")
        self._id = 0
        self._read()  # server hello
        self.command("WebDriver:NewSession", {})
        self.command("Marionette:SetContext", {"value": "chrome"})

    def _read(self) -> Any:
        length = b""
        while (char := self._file.read(1)) != b":":
            if not char:
                raise ZenRunnerError("Marionette connection closed.")
            length += char
        return json.loads(self._file.read(int(length)))

    def command(self, name: str, params: dict) -> Any:
        self._id += 1
        body = json.dumps([0, self._id, name, params]).encode()
        self._sock.sendall(str(len(body)).encode() + b":" + body)
        _, _, error, result = self._read()
        if error:
            raise ZenRunnerError(f"{name}: {error.get('message', error)}")
        return result

    def execute(self, script: str, args: list) -> Any:
        # The script body may return a Promise; Marionette waits for it.
        result = self.command("WebDriver:ExecuteScript", {"script": script, "args": args, "scriptTimeout": 120000})
        return result.get("value") if isinstance(result, dict) else result

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


CHECK_PROFILE_SCRIPT = "return Services.dirsvc.get('ProfD', Ci.nsIFile).path;"
QUIT_SCRIPT = """
Services.prefs.clearUserPref("marionette.port");
Services.startup.quit(Ci.nsIAppStartup.eAttemptQuit);
return true;
"""


def log_output_tail(output, process: subprocess.Popen, lines: int = 40) -> None:
    """The end of what the headless Zen printed, and whether it is still running."""
    try:
        output.flush()
        output.seek(0)
        tail = output.read().decode("utf-8", errors="replace").splitlines()[-lines:]
    except OSError:
        return
    state = "still running" if process.poll() is None else f"exited with code {process.returncode}"
    logger.info(f"   Headless Zen {state}; its last output:\n" + ("\n".join(tail) or "(nothing)"))


@contextlib.contextmanager
def zen_session(profile: Path) -> Iterator[MarionetteClient]:
    """Start a headless Zen on profile and yield a chrome-context Marionette client.

    Zen quits and the temporary Marionette port is removed when the block ends.
    """
    profile = Path(profile).resolve()
    if is_zen_profile_in_use(profile):
        raise ZenRunnerError(f"Zen is already running with this profile: {profile}")

    binary = find_zen_binary()
    port = free_port()
    user_js = profile / "user.js"
    original_user_js = user_js.read_bytes() if user_js.exists() else None
    with open(user_js, "ab") as f:
        f.write(f'\n{USER_JS_MARKER}\nuser_pref("marionette.port", {port});\n'.encode())

    env = {key: value for key, value in os.environ.items() if key not in PROXY_ENV_VARS}
    command = [str(binary), "-profile", str(profile), "-no-remote", "-headless", "--marionette", "-remote-allow-system-access"]
    logger.info(f"   Starting headless Zen on {profile.name}")
    # Kept to show in the log when something goes wrong; Zen's output is noisy otherwise
    output = tempfile.TemporaryFile()
    process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT)
    client = None
    try:
        client = MarionetteClient(port)
        actual = Path(client.execute(CHECK_PROFILE_SCRIPT, [])).resolve()
        if actual != profile:
            raise ZenRunnerError(f"Connected to a Zen running another profile ({actual}); stopping.")
        yield client
    except Exception:
        log_output_tail(output, process)
        raise
    finally:
        if client:
            try:
                client.execute(QUIT_SCRIPT, [])
            except (ZenRunnerError, OSError):
                pass  # the connection drops while Zen quits
            client.close()
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=15)
        output.close()
        if original_user_js is None:
            user_js.unlink(missing_ok=True)
        else:
            user_js.write_bytes(original_user_js)
        # Zen copies user.js values into prefs.js; drop ours if the quit script did not run
        prefs_js = profile / "prefs.js"
        if prefs_js.exists():
            line = f'user_pref("marionette.port", {port});'
            text = prefs_js.read_text(encoding="utf-8")
            if line in text:
                prefs_js.write_text(
                    "\n".join(l for l in text.splitlines() if l.strip() != line) + "\n",
                    encoding="utf-8",
                )


def run_in_zen(profile: Path, script: str, args: Optional[list] = None) -> Any:
    """Start a headless Zen on profile, run script in the chrome context, and quit."""
    with zen_session(profile) as client:
        return client.execute(script, args or [])
