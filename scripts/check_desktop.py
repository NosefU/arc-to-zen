#!/usr/bin/env python3
"""Import every module and open the app window off screen; CI runs it on macOS and Windows."""

from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    import arc2zen

    for module in pkgutil.iter_modules(arc2zen.__path__):
        importlib.import_module(f"arc2zen.{module.name}")

    from PySide6.QtWidgets import QApplication

    from arc2zen.desktop import MainWindow

    app = QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    # Every preset, as a click on its card would pick it
    for preset in ("tabs", "all", "look", "custom"):
        window.preset_cards[preset].clicked.emit()
        app.processEvents()
    window.close()
    print(f"OK: {len(list(pkgutil.iter_modules(arc2zen.__path__)))} modules, window opened")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
