#!/usr/bin/env python3
"""Render the desktop app window used in README.md."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from PySide6.QtWidgets import QApplication

from arc2zen.desktop import APP_STYLESHEET, MainWindow


def main() -> int:
    output = REPO_ROOT / "docs" / "app-screenshot.png"
    output.parent.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()
    # Show home-relative paths; keep the discovered profiles so the cards are real
    home = str(Path.home())
    for combo in (window.arc_combo, window.zen_combo):
        combo.setEditText(combo.currentText().replace(home, "~", 1))
    window.resize(1040, 760)
    window.show()
    app.processEvents()

    pixmap = window.grab()
    if not pixmap.save(str(output), "PNG"):
        raise RuntimeError(f"Failed to write {output}")

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
