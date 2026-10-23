#!/usr/bin/env python3
"""Write user preferences into a closed Zen profile's prefs.js."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


def pref_line(name: str, value: Any) -> str:
    return f"user_pref({json.dumps(name)}, {json.dumps(value, ensure_ascii=False)});"


def set_user_prefs(profile: Path, prefs: Dict[str, Any], create_backups: bool = True) -> int:
    """Set prefs in prefs.js, replacing earlier values; returns how many changed."""
    path = Path(profile) / "prefs.js"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    wanted = {name: pref_line(name, value) for name, value in prefs.items()}
    prefixes = {name: f"user_pref({json.dumps(name)}," for name in prefs}

    kept, current = [], {}
    for line in lines:
        name = next((n for n, prefix in prefixes.items() if line.startswith(prefix)), None)
        if name is None:
            kept.append(line)
        else:
            current[name] = line
    changed = sum(1 for name, line in wanted.items() if current.get(name) != line)
    if not changed:
        return 0

    if create_backups and path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(path, path.with_name(f"prefs.js.codex-prefs-backup-{stamp}"))
    path.write_text("\n".join(kept + list(wanted.values())) + "\n", encoding="utf-8")
    return changed
