#!/usr/bin/env python3
"""Desktop UI for Arc to Zen: one window around the shared migration."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from ctypes.util import find_library
from typing import Callable, Dict, List, Optional

# PyInstaller windowed builds on Windows can start with no console streams.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

try:
    import psutil
    from PySide6.QtCore import QByteArray, QEvent, QPoint, QRect, QRectF, QSize, Qt, QThread, QTimer, QUrl, Signal
    from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QIcon, QPainter, QPalette, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QFileDialog,
        QFrame,
        QGraphicsOpacityEffect,
        QHBoxLayout,
        QLabel,
        QLayout,
        QMainWindow,
        QMenu,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QStackedWidget,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    print("Missing desktop dependency:", exc)
    print('Install dependencies with: pip install -e ".[desktop]"')
    raise

from .link_routing import ARC_HAS_LINK_ROUTING
from .migration import ARC_LOOK_KEYS, MigrationOptions, look_only, migration_steps, run_migration, use_utf8_output
from .profile_paths import (
    discover_arc_profiles,
    discover_zen_profiles,
    is_arc_profile,
    is_zen_profile_in_use,
    resolve_zen_profile,
    zen_profile_lock_files,
)
from .sessions import read_mozilla_lz4
from .snapshot import discard, rollback, snapshot_profile
from .space_overview import SpaceOverview, arc_space_overview
from .zen_assets import zen_selectable_icon_svg
from .zen_runner import ZenRunnerError, find_zen_binary
from .zen_settings import ARC_WINDOWS_TOP_BAR


# Palette of the window; the window always uses the light appearance.
BG = "#f1f0f6"
WINDOW = "#ffffff"
CARD = "#fafafc"
LINE = "#e3e1eb"
TEXT = "#1b1a22"
MUTED = "#5e5b6b"
ACCENT = "#4b3fe0"
ACCENT_TEXT = "#3a2fc4"
ACCENT_SOFT = "#eeecfd"
OK = "#1f7a4d"
OK_SOFT = "#e8f5ee"
OK_LINE = "#bfe3cf"
WARN = "#8a5100"
WARN_SOFT = "#fdf3e3"
WARN_LINE = "#f0d7a8"
# Notes on a finished run: in the accent color, part of the app rather than an alarm
NOTE_SOFT = "#f5f4fe"
NOTE_LINE = "#dcd8fb"
DANGER = "#b42318"
DANGER_SOFT = "#fdf0ee"
DANGER_LINE = "#f3c9c4"
OFF = "#c9c6d4"

APP_STYLESHEET = f"""
QWidget {{ color: {TEXT}; font-size: 13px; }}
QMainWindow, QWidget#Root {{ background: {BG}; }}
QFrame#Window {{ background: {WINDOW}; border: 1px solid {LINE}; border-radius: 14px; }}
QFrame#Header {{ background: transparent; border: 0; border-bottom: 1px solid {LINE}; }}
QFrame#Pinned {{ background: transparent; border: 0; border-bottom: 1px solid {LINE}; }}
QFrame#Footer {{ background: {CARD}; border: 0; border-top: 1px solid {LINE};
    border-bottom-left-radius: 14px; border-bottom-right-radius: 14px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: 0; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: 15px; font-weight: 700; }}
QLabel[role="h2"] {{ font-size: 17px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="small"] {{ color: {MUTED}; font-size: 12px; }}
QLabel[role="caps"] {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel[role="ok"] {{ color: {OK}; font-size: 12px; }}
QLabel[role="warn"] {{ color: {WARN}; font-size: 12px; }}
QLabel[role="error"] {{ color: {DANGER}; font-size: 12px; }}
QFrame#Card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#Aside {{ background: transparent; border: 0; border-right: 1px solid {LINE}; }}
QFrame#Divider {{ background: {LINE}; border: 0; max-height: 1px; min-height: 1px; }}
QFrame#Notes {{ background: {NOTE_SOFT}; border: 1px solid {NOTE_LINE}; border-radius: 12px; }}
QFrame#Confirm {{ background: {DANGER_SOFT}; border: 1px solid {DANGER_LINE}; border-radius: 12px; }}
QFrame#Stat {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; }}
QFrame#Endpoint {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#Endpoint:hover, QFrame#Endpoint:focus {{ border-color: {ACCENT}; }}
QFrame#Endpoint[tone="warn"] {{ background: {WARN_SOFT}; border-color: {WARN_LINE}; }}
QFrame#Endpoint[tone="danger"] {{ background: {DANGER_SOFT}; border-color: {DANGER}; }}
QFrame#Warning {{ background: {WARN_SOFT}; border: 1px solid {WARN_LINE}; border-radius: 12px; }}
QFrame#SpaceRow {{ background: transparent; border: 1.5px solid transparent; border-radius: 10px; }}
QFrame#SpaceRow[checked="true"] {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QFrame#SpaceRow:focus {{ border-color: {ACCENT}; }}
QFrame#SpaceRow:disabled {{ background: transparent; border-color: transparent; }}
QFrame#Preset {{ background: {WINDOW}; border: 1.5px solid {LINE}; border-radius: 12px; }}
QFrame#Preset[checked="true"] {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QFrame#Preset:disabled {{ background: transparent; }}
QFrame#Preset:focus {{ border-color: {ACCENT}; }}
QFrame#Mode {{ background: transparent; border: 1.5px solid {LINE}; border-radius: 10px; }}
QFrame#Mode[checked="true"] {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QFrame#Mode[checked="true"][danger="true"] {{ background: {DANGER_SOFT}; border-color: {DANGER}; }}
QFrame#Mode:focus {{ border-color: {ACCENT}; }}
QComboBox {{ background: {WINDOW}; border: 1px solid {LINE}; border-radius: 8px; padding: 6px 10px; }}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {WINDOW}; border: 1px solid {LINE};
    selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; }}
QPushButton {{ background: {WINDOW}; border: 1px solid {LINE}; border-radius: 10px;
    padding: 9px 16px; font-weight: 600; min-height: 22px; }}
QPushButton:hover {{ background: #f5f4f9; }}
QPushButton:disabled {{ color: #a3a0b0; }}
QPushButton#Primary {{ background: {ACCENT}; border-color: {ACCENT}; color: #ffffff; }}
QPushButton#Primary:hover {{ background: #3f33d0; }}
QPushButton#Primary:disabled {{ background: #a9a3f0; border-color: #a9a3f0; color: #ffffff; }}
QPushButton#PrimaryDanger {{ background: {DANGER}; border-color: {DANGER}; color: #ffffff; }}
QPushButton#Accent {{ border: 1.5px solid {ACCENT}; color: {ACCENT_TEXT}; }}
QPushButton#Accent:hover {{ background: {ACCENT_SOFT}; }}
QPushButton#Danger {{ border: 1.5px solid {DANGER}; color: {DANGER}; }}
QPushButton#Danger:hover {{ background: {DANGER_SOFT}; }}
QPushButton#Link {{ background: transparent; border: 0; color: {ACCENT_TEXT}; padding: 4px 8px; }}
QPushButton#Link:hover {{ color: #2a2190; }}
QPushButton#Chip {{ background: transparent; border: 1px solid {LINE}; border-radius: 15px;
    color: {MUTED}; font-weight: 500; padding: 5px 12px; min-height: 20px; }}
QPushButton#Chip:hover {{ border-color: #b3afc2; }}
QPushButton#Chip:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; color: {ACCENT_TEXT}; font-weight: 600; }}
QPushButton#Chip:disabled {{ background: transparent; border-color: {LINE}; color: #b5b2c2; }}
QPushButton#Chip[dimmed="true"] {{ background: transparent; border-color: {LINE}; color: #b5b2c2; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: #cfccda; border-radius: 3px; min-height: 32px; }}
QScrollBar::handle:vertical:hover {{ background: #b3afc2; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QProgressBar {{ background: {LINE}; border: 0; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QTextEdit {{ background: #f3f2f7; border: 0; border-radius: 10px; padding: 8px;
    font-family: "SF Mono", Menlo, Monaco, Consolas, monospace; font-size: 12px; }}
QToolTip {{ background: {WINDOW}; color: {TEXT}; border: 1px solid {LINE}; }}
"""

ZEN_PROCESS_NAMES = {
    "zen",
    "zen.exe",
    "zen-bin",
    "zen-browser",
    "zen-browser-bin",
    "zen-browser.exe",
    "zen browser",
    "zen browser.exe",
}


def format_path(path: Path) -> str:
    return str(path.expanduser())


def resource_path(*parts: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).joinpath(*parts)

    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root.joinpath(*parts)
    if candidate.exists():
        return candidate
    return Path(__file__).resolve().parent.joinpath(*parts)


def apply_light_theme(app: QApplication) -> None:
    """Keep the custom light UI readable even when the OS is in dark mode."""
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(WINDOW))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(CARD))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(WINDOW))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(WINDOW))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor(ACCENT_TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT_SOFT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT))

    disabled_text = QColor("#a3a0b0")
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)

    if hasattr(QPalette.ColorRole, "PlaceholderText"):
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED))

    app.setPalette(palette)


def force_macos_light_appearance() -> bool:
    if sys.platform != "darwin":
        return False

    try:
        import ctypes

        objc_path = find_library("objc")
        if not objc_path:
            return False

        objc = ctypes.cdll.LoadLibrary(objc_path)
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def selector(name: str) -> int:
            return objc.sel_registerName(name.encode("utf-8"))

        def send(obj: int, name: str, restype=ctypes.c_void_p, argtypes=None, *args):
            if argtypes is None:
                argtypes = []
            objc.objc_msgSend.restype = restype
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
            return objc.objc_msgSend(obj, selector(name), *args)

        ns_application = objc.objc_getClass(b"NSApplication")
        ns_string = objc.objc_getClass(b"NSString")
        ns_appearance = objc.objc_getClass(b"NSAppearance")
        ns_app = send(ns_application, "sharedApplication")
        if not ns_app:
            return False

        appearance = None
        for name in (b"NSAppearanceNameAqua", b"Aqua"):
            appearance_name = send(
                ns_string,
                "stringWithUTF8String:",
                ctypes.c_void_p,
                [ctypes.c_char_p],
                name,
            )
            appearance = send(
                ns_appearance,
                "appearanceNamed:",
                ctypes.c_void_p,
                [ctypes.c_void_p],
                appearance_name,
            )
            if appearance:
                break

        if not appearance:
            return False

        send(ns_app, "setAppearance:", None, [ctypes.c_void_p], appearance)
        return True
    except Exception:
        logging.getLogger(__name__).debug("Could not force macOS light appearance", exc_info=True)
        return False


def polish_macos_window(window: QMainWindow) -> bool:
    if sys.platform != "darwin":
        return False

    try:
        import ctypes

        objc_path = find_library("objc")
        if not objc_path:
            return False

        objc = ctypes.cdll.LoadLibrary(objc_path)
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]

        def selector(name: str) -> int:
            return objc.sel_registerName(name.encode("utf-8"))

        def send(obj: int, name: str, restype=ctypes.c_void_p, argtypes=None, *args):
            if argtypes is None:
                argtypes = []
            objc.objc_msgSend.restype = restype
            objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, *argtypes]
            return objc.objc_msgSend(obj, selector(name), *args)

        ns_view = int(window.winId())
        ns_window = send(ns_view, "window")
        if not ns_window:
            return False

        ns_string = objc.objc_getClass(b"NSString")
        ns_appearance = objc.objc_getClass(b"NSAppearance")
        for name in (b"NSAppearanceNameAqua", b"Aqua"):
            appearance_name = send(
                ns_string,
                "stringWithUTF8String:",
                ctypes.c_void_p,
                [ctypes.c_char_p],
                name,
            )
            appearance = send(
                ns_appearance,
                "appearanceNamed:",
                ctypes.c_void_p,
                [ctypes.c_void_p],
                appearance_name,
            )
            if appearance:
                send(ns_window, "setAppearance:", None, [ctypes.c_void_p], appearance)
                send(ns_view, "setAppearance:", None, [ctypes.c_void_p], appearance)
                break

        ns_color = objc.objc_getClass(b"NSColor")
        background = send(
            ns_color,
            "colorWithCalibratedRed:green:blue:alpha:",
            ctypes.c_void_p,
            [ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double],
            0.945,
            0.941,
            0.965,
            1.0,
        )

        send(ns_window, "setTitlebarAppearsTransparent:", None, [ctypes.c_bool], True)
        send(ns_window, "setBackgroundColor:", None, [ctypes.c_void_p], background)
        return True
    except Exception:
        logging.getLogger(__name__).debug("Could not apply macOS window polish", exc_info=True)
        return False


def zen_processes() -> list[psutil.Process]:
    processes = []
    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (process.info.get("name") or "").lower()
            exe_name = Path(process.info.get("exe") or name).name.lower()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

        if name in ZEN_PROCESS_NAMES or exe_name in ZEN_PROCESS_NAMES:
            processes.append(process)

    return processes


def zen_processes_using_profile(profile: str | Path) -> list[psutil.Process]:
    """Return only the Zen processes running the given profile."""
    profile_path = Path(profile).expanduser().resolve()
    lock_files = {str(path.resolve()) for path in zen_profile_lock_files(profile_path)}
    matches = []
    for process in zen_processes():
        try:
            open_paths = {str(Path(item.path).resolve()) for item in process.open_files()}
            if open_paths & lock_files:
                matches.append(process)
                continue
            cmdline = process.cmdline()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for index, arg in enumerate(cmdline[:-1]):
            if arg.lstrip("-") == "profile" and Path(cmdline[index + 1]).expanduser().resolve() == profile_path:
                matches.append(process)
                break
    return matches


def close_windows(pids: set[int]) -> None:
    """Close the windows of these processes as their close button does."""
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    wm_close = 0x0010

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def close(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and user32.IsWindowVisible(hwnd):
            user32.PostMessageW(hwnd, wm_close, 0, 0)
        return True

    user32.EnumWindows(close, 0)


def terminate_zen_processes(processes: list[psutil.Process]) -> list[psutil.Process]:
    if sys.platform == "win32":
        # terminate() is TerminateProcess on Windows, after which Zen offers to restore a crashed session
        close_windows({process.pid for process in processes})
    else:
        for process in processes:
            try:
                process.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

    _, alive = psutil.wait_procs(processes, timeout=15)
    return alive


def kill_zen_processes(processes: list[psutil.Process]) -> list[psutil.Process]:
    for process in processes:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    _, alive = psutil.wait_procs(processes, timeout=5)
    return alive


def label(text: str = "", role: Optional[str] = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if role:
        widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    return widget


def frame(name: str) -> QFrame:
    widget = QFrame()
    widget.setObjectName(name)
    return widget


def divider() -> QFrame:
    return frame("Divider")


def restyle(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def is_light(color: str) -> bool:
    c = QColor(color)
    return (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) > 170


def svg_pixmap(svg: bytes, color: str, size: int, ratio: float) -> QPixmap:
    """Render a Zen icon SVG (it paints with context-fill) in the given color."""
    data = svg.replace(b"context-fill-opacity", b"1").replace(b"context-fill", color.encode())
    renderer = QSvgRenderer(QByteArray(data))
    pixmap = QPixmap(int(size * ratio), int(size * ratio))
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter, QRectF(0, 0, size * ratio, size * ratio))
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


# The mark of "just the look": two sparkles
SPARKLES_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="context-fill"'
    b' stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    b'<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>'
    b'<path d="M19 17l.8 2.2L22 20l-2.2.8L19 23l-.8-2.2L16 20l2.2-.8z"/></svg>'
)


# The always-moved core import: a padlock instead of a tick
LOCK_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="context-fill"'
    b' stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">'
    b'<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>'
)


def zen_space_names(profile: Path) -> set[str]:
    """Names of the spaces a Zen profile has; "just the look" restyles only these."""
    try:
        spaces = read_mozilla_lz4(profile / "zen-sessions.jsonlz4").get("spaces") or []
    except Exception:
        return set()
    return {space.get("name") for space in spaces if space.get("name")}


class Chip(QPushButton):
    """An option pill; it is as wide as its label in the bolder font of the checked state.

    Qt sizes it with the unchecked font, and on Windows the bold label no longer fits.
    """

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        bold = QFont(self.font())
        bold.setWeight(QFont.Weight.DemiBold)
        extra = QFontMetrics(bold).horizontalAdvance(self.text()) - self.fontMetrics().horizontalAdvance(self.text())
        return QSize(hint.width() + max(0, extra), hint.height())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()


class FlowLayout(QLayout):
    """Lays widgets out left to right and wraps them onto new lines, like inline text."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:
        self.items.append(item)

    def count(self) -> int:
        return len(self.items)

    def itemAt(self, index: int):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index: int):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _arrange(self, rect: QRect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        for item in self.items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line:
                x, y, line = rect.x(), y + line + self.spacing(), 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line = max(line, hint.height())
        return y + line - rect.y()


class Clickable(QFrame):
    """A frame that acts as a button but sizes to its layout, unlike QPushButton."""

    clicked = Signal()

    def __init__(self, name: str, accessible_name: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName(name)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(accessible_name)

    def is_checked(self) -> bool:
        return self.property("checked") == "true"

    def set_checked(self, checked: bool) -> None:
        self.setProperty("checked", "true" if checked else "false")
        restyle(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


def count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def text_column(*widgets: QWidget) -> QVBoxLayout:
    column = QVBoxLayout()
    column.setSpacing(1)
    for widget in widgets:
        column.addWidget(widget)
    return column


class Endpoint(Clickable):
    """Arc or Zen in the header: a status dot, a name, and its state; opens a menu of profiles."""

    def __init__(self, accessible_name: str):
        super().__init__("Endpoint", accessible_name)
        self.dot = QLabel()
        self.dot.setFixedSize(8, 8)
        self.title = label()
        self.title.setStyleSheet("font-weight: 600;")
        self.subtitle = label("", "small")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 12, 6)
        layout.setSpacing(10)
        layout.addWidget(self.dot)
        layout.addLayout(text_column(self.title, self.subtitle))

    def set_status(self, title: str, subtitle: str, color: str, tooltip: str, tone: str = "") -> None:
        """tone "warn" or "danger" tints the card when what it stands for is missing."""
        self.dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.setToolTip(tooltip)
        self.setProperty("tone", tone)
        restyle(self)


class SpaceRow(Clickable):
    """A selectable row for one Arc space: icon, name, counts, and its container."""

    toggled = Signal(bool)

    def __init__(self, space: SpaceOverview, checked: bool, parent=None):
        super().__init__("SpaceRow", f"Space {space.name}", parent)
        self.space = space
        # In "just the look": whether Zen has a space of this name; None otherwise
        self.in_zen: Optional[bool] = None

        badge = QLabel()
        badge.setFixedSize(36, 36)
        badge.setAlignment(Qt.AlignCenter)
        colors = space.colors or ["#e3e3ff"]
        background = (
            f"qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {colors[0]}, stop:1 {colors[1]})"
            if len(colors) > 1 else colors[0]
        )
        ink = ACCENT_TEXT if is_light(colors[0]) else "#ffffff"
        badge.setStyleSheet(
            f"background: {background}; border: 1px solid {LINE}; border-radius: 9px;"
            f" color: {ink}; font-size: 15px; font-weight: 700;"
        )
        svg = None if space.emoji else zen_selectable_icon_svg(space.icon_name or "")
        if space.emoji:
            badge.setText(space.emoji)
            badge.setStyleSheet(badge.styleSheet() + " font-size: 19px;")
        elif svg:
            badge.setPixmap(svg_pixmap(svg, ink, 19, max(2.0, self.devicePixelRatioF())))
        else:
            badge.setText(space.name[:1].upper())

        self.name = name = label(space.name)
        name.setStyleSheet("font-weight: 600;")
        self.counts_text = f"{count(space.tabs, 'tab')} · {count(space.folders, 'folder')}"
        # Spaces keep their Arc profile; its container has the profile's name unless the profile has none
        if space.profile_name:
            self.counts_text += f"\n{space.profile_name} profile"
        elif space.container:
            self.counts_text += f"\nUnnamed profile → {space.container} container"
        self.counts = label(self.counts_text, "small", wrap=True)
        self.check = QLabel()
        self.check.setFixedSize(20, 20)
        self.check.setAlignment(Qt.AlignCenter)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)
        layout.addWidget(badge)
        layout.addLayout(text_column(name, self.counts), 1)
        layout.addWidget(self.check)
        self.clicked.connect(self.toggle)
        self.set_checked(checked)

    def set_checked(self, checked: bool) -> None:
        # A space Zen lacks shows unchecked but keeps its choice for migrating
        shown = checked and self.in_zen is not False
        self.check.setText("✓" if shown else "")
        self.check.setStyleSheet(
            f"background: {ACCENT}; color: #ffffff; border-radius: 6px; font-weight: 700;"
            if shown else f"background: transparent; border: 1.5px solid {OFF}; border-radius: 6px;"
        )
        super().set_checked(checked)

    def set_look(self, in_zen: Optional[bool]) -> None:
        """In "just the look" tell whether Zen has this space; one it lacks is skipped."""
        self.in_zen = in_zen
        if in_zen is None:
            self.counts.setText(self.counts_text)
        else:
            self.counts.setText("In Zen · gets its Arc icon and colors" if in_zen else "Not in Zen · skipped")
        self.setEnabled(in_zen is not False)
        grey = f" color: {OFF};" if in_zen is False else ""
        self.name.setStyleSheet("font-weight: 600;" + grey)
        self.counts.setStyleSheet(grey)
        self.set_checked(self.is_checked())

    def toggle(self) -> None:
        self.set_checked(not self.is_checked())
        self.toggled.emit(self.is_checked())


class PresetCard(Clickable):
    """One of the ready-made selections: Just tabs, Arc as it was, Custom."""

    def __init__(self, title: str, hint: str, recommended: bool, look: bool = False):
        super().__init__("Preset", title)
        self.hint = hint
        heading = QHBoxLayout()
        heading.setSpacing(6)
        if look:
            sparkles = QLabel()
            sparkles.setPixmap(svg_pixmap(SPARKLES_SVG, ACCENT_TEXT, 16, max(2.0, self.devicePixelRatioF())))
            heading.addWidget(sparkles)
        self.title_label = label(title)
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        heading.addWidget(self.title_label, 1)
        badge_style = "border-radius: 9px; padding: 2px 8px; font-size: 11px; font-weight: 600;"
        if recommended:
            badge = label("Recommended")
            badge.setStyleSheet(f"background: {OK_SOFT}; color: {OK}; {badge_style}")
            heading.addWidget(badge)
        self.hint_label = label(hint, "small", wrap=True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        layout.addLayout(heading)
        if look:
            # Under the title, so the four cards fit side by side
            badge = label("No migration")
            badge.setStyleSheet(f"background: {ACCENT_SOFT}; color: {ACCENT_TEXT}; {badge_style}")
            layout.addWidget(badge, 0, Qt.AlignLeft)
        layout.addWidget(self.hint_label)
        layout.addStretch(1)
        self.setMinimumHeight(76)

    def set_available(self, available: bool, reason: str = "") -> None:
        """Without Arc only "just the look" can run; without Zen nothing can. reason replaces the hint."""
        self.setEnabled(available)
        self.hint_label.setText(reason or self.hint)
        grey = "" if available else f" color: {OFF};"
        self.title_label.setStyleSheet("font-size: 15px; font-weight: 600;" + grey)
        self.hint_label.setStyleSheet(grey)


class ModeCard(Clickable):
    """A compact radio card next to the Migrate button: spaces added to Zen, or replacing its contents."""

    def __init__(self, title: str, subtitle: str, hint: str, danger: bool = False):
        super().__init__("Mode", title)
        self.danger = danger
        # Faded while nothing can run, e.g. before Zen is found
        self.fade = QGraphicsOpacityEffect(self)
        self.fade.setOpacity(1.0)
        self.setGraphicsEffect(self.fade)
        self.setProperty("danger", "true" if danger else "false")
        self.setToolTip(hint)
        self.radio = QLabel()
        self.radio.setFixedSize(18, 18)
        self.title = label(title)
        caption = label(subtitle)
        caption.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 12, 6)
        layout.setSpacing(8)
        layout.addWidget(self.radio, 0, Qt.AlignVCenter)
        layout.addLayout(text_column(self.title, caption))

    def set_checked(self, checked: bool) -> None:
        color = DANGER if self.danger else ACCENT
        self.radio.setStyleSheet(
            f"background: {WINDOW}; border: 5px solid {color}; border-radius: 9px;"
            if checked else f"background: transparent; border: 1.5px solid {OFF}; border-radius: 9px;"
        )
        self.title.setStyleSheet(
            f"font-size: 13px; font-weight: 600; color: {DANGER if checked and self.danger else TEXT};")
        super().set_checked(checked)


# An "i" in an accent ring marks a note: on a step and in the notes of a finished run
NOTE_ICON = (f"border: 1.5px solid {ACCENT}; border-radius: 10px; color: {ACCENT};"
             " font-family: Georgia, serif; font-size: 12px; font-weight: 700;")
# A log line starting with this is a note of the current step
NOTE_PREFIX = "⚠️"
# A log line starting with this is one item the note is about; the step lists it, the notes don't
DETAIL_PREFIX = "↳"


class StepRow(QWidget):
    """One migration step in the run list: status dot, title, and an optional note."""

    def __init__(self, title: str):
        super().__init__()
        self.icon = QLabel()
        self.icon.setFixedSize(20, 20)
        self.icon.setAlignment(Qt.AlignCenter)
        self.title = label(title)
        self.note = label("", "small", wrap=True)
        self.note.setVisible(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(12)
        layout.addWidget(self.icon, 0, Qt.AlignTop)
        layout.addLayout(text_column(self.title, self.note), 1)
        self.set_state("pending")

    def set_state(self, state: str, note: str = "") -> None:
        styles = {
            "pending": (f"border: 2px solid {OFF}; border-radius: 10px;", "", MUTED, 500),
            "running": (f"border: 2px solid {ACCENT}; border-radius: 10px;", "", TEXT, 600),
            "done": (f"background: {OK}; border-radius: 10px; color: #ffffff; font-weight: 700;", "✓", TEXT, 500),
            "failed": (f"background: {DANGER}; border-radius: 10px; color: #ffffff; font-weight: 700;", "!", TEXT, 600),
            "noted": (NOTE_ICON, "i", TEXT, 500),
        }
        box, mark, color, weight = styles[state]
        self.icon.setStyleSheet(box if state == "noted" else box + " font-size: 11px;")
        self.icon.setText(mark)
        self.title.setStyleSheet(f"color: {color}; font-weight: {weight};")
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.note.setProperty("role", "error" if state == "failed" else "small")
        restyle(self.note)


class MigrationWorker(QThread):
    line = Signal(str)
    step = Signal(int, int, str)
    snapshot = Signal(str)
    done = Signal(bool, str)

    def __init__(self, config: MigrationOptions, snapshot_dir: Optional[Path] = None):
        super().__init__()
        self.config = config
        self.snapshot_dir = snapshot_dir

    def run(self):
        try:
            self._run()
        except Exception as exc:
            self.done.emit(False, str(exc))

    def _run(self):
        run_migration(self.config, emit_line=self.line.emit, on_step=self.step.emit,
                      on_snapshot=lambda path: self.snapshot.emit(str(path)), snapshot_dir=self.snapshot_dir)
        self.done.emit(True, "Migration finished successfully.")


class RollbackWorker(QThread):
    """Puts the Zen profile back from the run's backup."""

    line = Signal(str)
    done = Signal(bool, str)

    def __init__(self, snapshot_dir: Path):
        super().__init__()
        self.snapshot_dir = snapshot_dir

    def run(self):
        try:
            restored = rollback(self.snapshot_dir)
            self.line.emit(f"✅ Rolled back: {restored} files and folders restored")
            self.done.emit(True, "")
        except Exception as exc:
            self.line.emit(f"❌ Rollback failed: {exc}")
            self.done.emit(False, str(exc))


@dataclass(frozen=True)
class Choice:
    key: str  # MigrationOptions field, or "" for the always-on core import
    label: str
    hint: str
    depends_on: str = ""


# Arc keeps its key in the macOS Keychain; on Windows it is unlocked for the signed-in user without asking
KEYCHAIN_NOTE = "macOS will ask once for access to “Arc Safe Storage” in your Keychain." if sys.platform == "darwin" else ""
THIS_COMPUTER = "this Mac" if sys.platform == "darwin" else "this computer"
# Where a fresh Arc shows the address, for "just the look" without Arc
ARC_DEFAULT_ADDRESS = "in a top bar" if ARC_WINDOWS_TOP_BAR else "in it"

# The rows of "What comes along": title, chips, and a note shown while any of its keys is on
CATEGORIES = [
    ("Tabs", [
        Choice("", "Tabs, folders, Essentials", "Pinned and open tabs, nested folders and Essentials. Always moved."),
        Choice("favicons", "Site icons", "From Arc's icon cache, so tabs don't start blank"),
        Choice("folder_states", "Folder open/closed", "Folders stay expanded or collapsed as in Arc"),
        Choice("repair_tabs", "Fix broken tabs", "Broken addresses become blank tabs; arc:// pages become Zen pages"),
    ], "", ()),
    ("Look", [
        Choice("workspace_icons", "Space icons", "Emoji and built-in icons"),
        Choice("workspace_themes", "Space colors", "Gradients and colors from Arc themes"),
        Choice("default_theme", "Arc default colors", "Spaces without a theme get Arc's pink-to-lavender gradient",
               depends_on="workspace_themes"),
    ], "", ()),
    ("Sign-ins", [
        Choice("containers", "Profiles → containers", "Each space opens in its Arc profile's container"),
        Choice("cookies", "Cookies", "Stay signed in to sites, per container"),
        Choice("local_storage", "localStorage", "Site settings and some sign-ins, per container"),
        Choice("passwords", "Passwords", "Into Zen's password manager; Zen runs in the background for a moment"),
    ], KEYCHAIN_NOTE, ("cookies", "passwords")),
    ("Rules", [
        Choice("boosts", "Boosts", "CSS and hidden elements per site; Zen boosts have no JavaScript"),
        *([Choice("link_routing", "Air Traffic Control", "Rules that open links in a space become Zen Space Routing")]
          if ARC_HAS_LINK_ROUTING else []),
    ], "", ()),
    ("Languages", [
        Choice("website_languages", "Website languages",
               "Languages sites are asked for, languages never to translate, spellcheck dictionary"),
        Choice("interface_language", "Interface language", "Menus and date formats follow the system, as in Arc"),
    ], "", ()),
    ("Zen setup", [
        Choice("arc_look_mod", "Arc Look mod", "Compact top bar, Arc-like address bar that always floats, Peek"),
        Choice("sidebar_mode", "Sidebar like Arc", "A hidden Arc sidebar starts Zen in compact mode"),
        Choice("toolbar_layout", "Toolbars like Arc", "Single or multiple toolbars, as Arc shows the URL"),
        Choice("split_drag", "Easier drag-to-split", "Drop a tab on another to split the view: wider target, half the delay"),
    ], "", ()),
]

# Not part of the presets
SAFETY = [
    Choice("auto_close_zen", "Close Zen if needed", "Only the Zen running this profile"),
    Choice("skip_orphaned", "Skip “Orphaned”", "Unmatched Essentials go to the first selected space"),
]

PRESET_KEYS = [c.key for _, choices, _, _ in CATEGORIES for c in choices if c.key]
TABS_ONLY = {"favicons", "folder_states", "repair_tabs", "workspace_icons", "workspace_themes", "default_theme"}
PRESETS = [
    ("tabs", "Just tabs", "Spaces, tabs and how they look. Nothing else in Zen changes.", False),
    ("all", "Arc as it was", f"Plus sign-ins, boosts{', routing' if ARC_HAS_LINK_ROUTING else ''} and an Arc-like Zen.", True),
    ("look", "Just the look", "Make Zen look like Arc. Your tabs and spaces in Zen stay.", False),
    ("custom", "Custom", "Turn items on and off below.", False),
]
ZEN_DOWNLOAD_URL = "https://zen-browser.app/download/"
# The rows "just the look" shows; the others don't apply to it
LOOK_ROWS = ("Look", "Zen setup", "Safety")
ZEN_SETUP = [("arc_look_mod", "Arc Look mod"), ("sidebar_mode", "sidebar"), ("toolbar_layout", "toolbars"),
             ("split_drag", "drag-to-split")]


def preset_values(preset: str) -> Dict[str, bool]:
    return {key: preset == "all" or key in TABS_ONLY for key in PRESET_KEYS}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker: MigrationWorker | None = None
        self.running = False
        self.finished = False
        self.succeeded = False
        self.confirming = False
        self.values: Dict[str, bool] = preset_values("all")
        self.values.update({c.key: True for c in SAFETY})
        self.values["nuke"] = False
        self.choices: Dict[str, Choice] = {c.key: c for _, cs, _, _ in CATEGORIES for c in cs if c.key}
        self.choices.update({c.key: c for c in SAFETY})
        self.space_rows: List[SpaceRow] = []
        self.unchecked_spaces: set[str] = set()
        # "Just the look": only Look and Zen setup are applied, no tabs are imported.
        # Without Arc it is the only choice; arc_forced remembers it was chosen for the user.
        self.look_mode = False
        # Custom picked by hand: it stays Custom even while the items match a preset
        self.custom_mode = False
        self.arc_ok = False
        self.arc_forced = False
        self.zen_spaces: set[str] = set()
        # "ok", "missing" (no Zen profile on this computer) or "wrong" (the chosen folder has none)
        self.zen_state = "ok"
        # What the last run was, for its result screen
        self.run_look = False
        self.run_look_spaces = 0
        self.step_rows: Dict[str, StepRow] = {}
        self.current_step_title = ""
        self.step_notes: Dict[str, str] = {}
        self.step_infos: Dict[str, List[str]] = {}
        self.step_details: Dict[str, List[str]] = {}
        # Each Zen profile is backed up once, before its first run from this window, and later
        # runs keep that backup, so rolling back undoes all of them. Deleted with the window.
        self.snapshots: Dict[str, Path] = {}
        self.runs: Dict[str, int] = {}
        # The backup the result screen rolls back to: that of the last run's profile
        self.snapshot_dir: Optional[Path] = None
        self.rollback_state = ""  # "", "running", "done" or "failed"
        self.result_has_notes = False

        self.setWindowTitle("Arc to Zen")
        self.setWindowIcon(QIcon(str(resource_path("assets", "app-icon.png"))))
        self.resize(1180, 760)
        self.setMinimumSize(940, 640)

        # The combos hold the chosen paths; the header endpoints show and change them
        self.arc_combo = self._profile_combo(discover_arc_profiles())
        self.zen_combo = self._profile_combo(discover_zen_profiles())
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setVisible(False)
        self.log.setMinimumHeight(160)

        self._build_ui()
        self.arc_combo.currentTextChanged.connect(self.reload_spaces)
        self.zen_combo.currentTextChanged.connect(self.refresh_zen_status)
        self.reload_spaces()
        self.refresh_zen_status()
        (self.download_zen if self.zen_state == "missing" else self.go_button).setFocus()

    # ----- building -------------------------------------------------------

    def _profile_combo(self, profiles: list[Path]) -> QComboBox:
        combo = QComboBox(self)
        combo.setEditable(True)
        combo.setVisible(False)
        for profile in profiles:
            combo.addItem(format_path(profile))
        return combo

    def _scroll(self, content: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(content)
        return area

    def _centered(self, widget: QWidget, width: int) -> QHBoxLayout:
        """Center a widget of up to width; a wrapped label keeps its height, unlike AlignHCenter."""
        widget.setMaximumWidth(width)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(widget, 100)
        row.addStretch(1)
        return row

    def _link(self, text: str, slot: Callable) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("Link")
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(slot)
        return button

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(20, 20, 20, 20)

        window = frame("Window")
        layout = QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_header())
        body = QHBoxLayout()
        body.setSpacing(0)
        self.aside = self._build_aside()
        body.addWidget(self.aside)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._scroll(self._build_choices_page()))
        # While a migration runs its progress stays pinned and the steps scroll under it
        run = QWidget()
        run_layout = QVBoxLayout(run)
        run_layout.setContentsMargins(0, 0, 0, 0)
        run_layout.setSpacing(0)
        run_layout.addWidget(self._build_progress())
        self.run_scroll = self._scroll(self._build_run_page())
        self.run_scroll.viewport().installEventFilter(self)
        run_layout.addWidget(self.run_scroll, 1)
        self.pages.addWidget(run)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        layout.addWidget(self._build_footer())
        outer.addWidget(window)
        self.setCentralWidget(root)

    def _build_header(self) -> QWidget:
        header = frame("Header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.setSpacing(10)
        logo = QLabel("→")
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #fff1f2, stop:1 #e3e3ff);"
            f" border: 1px solid {LINE}; border-radius: 9px; color: {ACCENT}; font-size: 16px; font-weight: 700;"
        )
        layout.addWidget(logo)
        layout.addLayout(text_column(
            label("Arc → Zen", "title"), label("Pick spaces, pick how much to bring, press Migrate", "small")), 1)
        self.arc_endpoint = Endpoint("Arc data folder")
        self.arc_endpoint.clicked.connect(lambda: self.choose_profile(self.arc_endpoint, self.arc_combo, self.browse_arc))
        self.zen_endpoint = Endpoint("Zen profile")
        self.zen_endpoint.clicked.connect(lambda: self.choose_profile(self.zen_endpoint, self.zen_combo, self.browse_zen))
        arrow = label("→", "muted")
        arrow.setStyleSheet(f"color: {MUTED}; font-size: 16px;")
        layout.addWidget(self.arc_endpoint)
        layout.addWidget(arrow)
        layout.addWidget(self.zen_endpoint)
        return header

    def _build_aside(self) -> QWidget:
        aside = frame("Aside")
        aside.setFixedWidth(330)
        self.aside_fade = QGraphicsOpacityEffect(aside)
        aside.setGraphicsEffect(self.aside_fade)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        heading = QHBoxLayout()
        self.spaces_caption = label("", "caps")
        heading.addWidget(self.spaces_caption, 1)
        self.all_link = self._link("All", lambda: self.set_all_spaces(True))
        self.none_link = self._link("None", lambda: self.set_all_spaces(False))
        heading.addWidget(self.all_link)
        heading.addWidget(self.none_link)
        layout.addLayout(heading)
        self.spaces_list = QVBoxLayout()
        self.spaces_list.setSpacing(4)
        layout.addLayout(self.spaces_list)
        self.spaces_message = label("", "muted", wrap=True)
        layout.addWidget(self.spaces_message)
        self.choose_arc_link = self._link("Choose Arc's folder…", self.browse_arc)
        layout.addWidget(self.choose_arc_link, 0, Qt.AlignLeft)
        self.spaces_note = label("", "small", wrap=True)
        layout.addWidget(self.spaces_note)
        layout.addStretch(1)

        outer = QVBoxLayout(aside)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll(content))
        return aside

    def _chip(self, choice: Choice) -> QPushButton:
        chip = Chip()
        chip.setObjectName("Chip")
        chip.setCheckable(True)
        chip.setToolTip(choice.hint)
        chip.setAccessibleName(choice.label)
        if choice.key:
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda checked, key=choice.key: self.set_value(key, checked))
            self.chips[choice.key] = chip
        else:
            # Always moved: it stays on, shows a padlock and only explains itself
            self.locked_chips.append(chip)
            chip.setText(" " + choice.label)
            chip.setIcon(QIcon(svg_pixmap(LOCK_SVG, ACCENT_TEXT, 12, max(2.0, self.devicePixelRatioF()))))
            chip.setChecked(True)
            chip.clicked.connect(lambda: chip.setChecked(True))
        return chip

    def _category_row(self, title: str, choices: List[Choice], note: str, note_keys) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)
        title_label = label(title)
        title_label.setStyleSheet("font-weight: 600; padding-top: 6px;")
        title_label.setFixedWidth(84)
        layout.addWidget(title_label, 0, Qt.AlignTop)
        right = QVBoxLayout()
        right.setSpacing(8)
        chips = QWidget()
        flow = FlowLayout(chips)
        for choice in choices:
            flow.addWidget(self._chip(choice))
        right.addWidget(chips)
        if note:
            note_label = label(note, "warn", wrap=True)
            self.notes.append((note_label, note_keys))
            right.addWidget(note_label)
        layout.addLayout(right, 1)
        return row

    def _build_choices_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 24)
        layout.setSpacing(14)
        self.zen_banner = frame("Warning")
        banner = QHBoxLayout(self.zen_banner)
        banner.setContentsMargins(16, 14, 16, 14)
        banner.setSpacing(14)
        mark = QLabel("!")
        mark.setFixedSize(36, 36)
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(f"background: {WINDOW}; border: 1px solid {WARN_LINE}; border-radius: 10px;"
                           f" color: {WARN}; font-size: 18px; font-weight: 700;")
        banner.addWidget(mark, 0, Qt.AlignTop)
        self.zen_banner_title = label()
        self.zen_banner_title.setStyleSheet("font-weight: 600;")
        self.zen_banner_text = label("", "muted", wrap=True)
        banner.addLayout(text_column(self.zen_banner_title, self.zen_banner_text), 1)
        self.download_zen = QPushButton("Download Zen")
        self.download_zen.setObjectName("Primary")
        self.download_zen.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ZEN_DOWNLOAD_URL)))
        banner.addWidget(self.download_zen, 0, Qt.AlignVCenter)
        choose_zen = QPushButton("Choose profile folder…")
        choose_zen.setObjectName("Accent")
        choose_zen.clicked.connect(self.browse_zen)
        banner.addWidget(choose_zen, 0, Qt.AlignVCenter)
        layout.addWidget(self.zen_banner)

        layout.addWidget(label("WHAT COMES ALONG", "caps"))

        presets = QHBoxLayout()
        presets.setSpacing(10)
        self.preset_cards: Dict[str, PresetCard] = {}
        for key, title, hint, recommended in PRESETS:
            card = PresetCard(title, hint, recommended, look=key == "look")
            card.clicked.connect(lambda k=key: self.apply_preset(k))
            self.preset_cards[key] = card
            presets.addWidget(card, 1)
        layout.addLayout(presets)

        self.look_note = frame("Notes")
        note = QHBoxLayout(self.look_note)
        note.setContentsMargins(14, 12, 14, 12)
        note.setSpacing(10)
        icon = QLabel("i")
        icon.setFixedSize(18, 18)
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(NOTE_ICON.replace("10px", "9px").replace("12px", "11px"))
        note.addWidget(icon, 0, Qt.AlignTop)
        self.look_note_text = label("", wrap=True)
        note.addWidget(self.look_note_text, 1)
        layout.addWidget(self.look_note)

        self.chips: Dict[str, QPushButton] = {}
        self.locked_chips: List[QPushButton] = []
        self.notes: List[tuple[QLabel, tuple]] = []
        card = frame("Card")
        rows = QVBoxLayout(card)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        # Each row with the divider above it, so "just the look" can hide rows
        self.category_rows: List[tuple[str, Optional[QFrame], QWidget]] = []
        for index, (title, choices, note, note_keys) in enumerate(CATEGORIES + [("Safety", SAFETY, "", ())]):
            line = divider() if index else None
            if line:
                rows.addWidget(line)
            row = self._category_row(title, choices, note, note_keys)
            rows.addWidget(row)
            self.category_rows.append((title, line, row))
        layout.addWidget(card)
        self.choices_hint = label("", "small", wrap=True)
        layout.addWidget(self.choices_hint)
        layout.addStretch(1)
        return page

    def _build_run_page(self) -> QWidget:
        page = QWidget()
        run = QVBoxLayout(page)
        run.setContentsMargins(24, 20, 24, 24)
        run.setSpacing(14)

        # A finished run shows its result in the middle of the column (a failure a bit higher);
        # the steps and the log hang below it, so opening them never moves the result
        self.result_spacer = QWidget()
        self.result_spacer.setFixedHeight(0)
        run.addWidget(self.result_spacer)
        self.result_head = QWidget()
        head = QVBoxLayout(self.result_head)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(12)
        # The mark, plus a filled accent "i" on its corner when the run left notes
        mark_box = QWidget()
        mark_box.setFixedSize(72, 60)
        self.result_mark = QLabel(mark_box)
        self.result_mark.setGeometry(8, 4, 56, 56)
        self.result_mark.setAlignment(Qt.AlignCenter)
        self.result_badge = QLabel(mark_box)
        self.result_badge.setGeometry(46, 0, 26, 26)
        self.result_badge.setStyleSheet(f"background: {WINDOW}; border-radius: 13px;")
        ring = QLabel("i", self.result_badge)
        ring.setGeometry(3, 3, 20, 20)
        ring.setAlignment(Qt.AlignCenter)
        ring.setStyleSheet(f"background: {ACCENT}; border-radius: 10px; color: {NOTE_SOFT};"
                           " font-family: Georgia, serif; font-size: 12px; font-weight: 700;")
        head.addWidget(mark_box, 0, Qt.AlignHCenter)
        self.result_title = label("")
        self.result_title.setAlignment(Qt.AlignCenter)
        self.result_title.setStyleSheet("font-size: 22px; font-weight: 700;")
        head.addWidget(self.result_title)
        self.result_text = label("", "muted", wrap=True)
        self.result_text.setAlignment(Qt.AlignCenter)
        head.addLayout(self._centered(self.result_text, 460))
        self.result_stats = QWidget()
        self.result_stats_layout = QHBoxLayout(self.result_stats)
        self.result_stats_layout.setContentsMargins(0, 4, 0, 0)
        self.result_stats_layout.setSpacing(8)
        head.addWidget(self.result_stats, 0, Qt.AlignHCenter)
        self.result_notes = frame("Notes")
        self.result_notes_layout = QVBoxLayout(self.result_notes)
        self.result_notes_layout.setContentsMargins(14, 12, 14, 12)
        self.result_notes_layout.setSpacing(10)
        head.addLayout(self._centered(self.result_notes, 480))
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        self.result_rollback = QPushButton("Roll back")
        self.result_rollback.setObjectName("Primary")
        self.result_rollback.clicked.connect(self.start_rollback)
        actions.addWidget(self.result_rollback)
        self.result_action = QPushButton()
        self.result_action.clicked.connect(self.result_action_clicked)
        actions.addWidget(self.result_action)
        # Exit closes the window, which deletes the backup
        self.result_exit = QPushButton("Exit")
        self.result_exit.setObjectName("PrimaryDanger")
        self.result_exit.clicked.connect(self.close)
        self.result_exit.setVisible(False)
        actions.addWidget(self.result_exit)
        self.steps_toggle = self._link("", self.toggle_steps)
        actions.addWidget(self.steps_toggle)
        actions.addStretch(1)
        head.addLayout(actions)
        self.result_hint = label("", "small", wrap=True)
        self.result_hint.setAlignment(Qt.AlignCenter)
        head.addLayout(self._centered(self.result_hint, 440))
        self.rollback_link = self._link("Something went wrong? Roll back", self.ask_rollback)
        head.addWidget(self.rollback_link, 0, Qt.AlignHCenter)
        self.rollback_confirm = frame("Confirm")
        confirm = QVBoxLayout(self.rollback_confirm)
        confirm.setContentsMargins(14, 12, 14, 12)
        confirm.setSpacing(8)
        self.rollback_confirm_title = label()
        self.rollback_confirm_title.setAlignment(Qt.AlignCenter)
        self.rollback_confirm_title.setStyleSheet("font-weight: 600;")
        confirm.addWidget(self.rollback_confirm_title)
        self.rollback_confirm_text = label("", "muted", wrap=True)
        self.rollback_confirm_text.setAlignment(Qt.AlignCenter)
        confirm.addWidget(self.rollback_confirm_text)
        confirm_buttons = QHBoxLayout()
        confirm_buttons.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.cancel_rollback)
        confirm_buttons.addWidget(cancel)
        yes = QPushButton("Yes, roll back")
        yes.setObjectName("PrimaryDanger")
        yes.clicked.connect(self.start_rollback)
        confirm_buttons.addWidget(yes)
        confirm_buttons.addStretch(1)
        confirm.addLayout(confirm_buttons)
        head.addLayout(self._centered(self.rollback_confirm, 440))
        self.result_head.setVisible(False)
        run.addWidget(self.result_head)

        self.log_toggle = self._link("Show log", self.toggle_log)
        run.addWidget(self.log_toggle, 0, Qt.AlignLeft)
        run.addWidget(self.log)
        self.steps_card = frame("Card")
        self.steps_layout = QVBoxLayout(self.steps_card)
        self.steps_layout.setContentsMargins(16, 6, 16, 6)
        self.steps_layout.setSpacing(0)
        run.addWidget(self.steps_card)
        run.addStretch(1)
        return page

    def _build_progress(self) -> QFrame:
        self.progress_box = frame("Pinned")
        progress = QVBoxLayout(self.progress_box)
        progress.setContentsMargins(24, 16, 24, 12)
        progress.setSpacing(8)
        progress_top = QHBoxLayout()
        self.progress_title = label("Migrating…")
        self.progress_title.setStyleSheet("font-weight: 600;")
        self.progress_text = label("", "muted")
        progress_top.addWidget(self.progress_title, 1)
        progress_top.addWidget(self.progress_text)
        progress.addLayout(progress_top)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(6)
        progress.addWidget(self.progress)
        self.progress_box.setVisible(False)
        return self.progress_box

    def _build_footer(self) -> QWidget:
        footer = frame("Footer")
        layout = QHBoxLayout(footer)
        layout.setContentsMargins(24, 14, 24, 14)
        layout.setSpacing(10)
        self.summary_title = label()
        self.summary_title.setStyleSheet("font-weight: 600;")
        self.summary_text = label("", "small", wrap=True)
        layout.addLayout(text_column(self.summary_title, self.summary_text), 1)
        self.add_mode = ModeCard(
            "Add to what's there", "The rest of Zen stays",
            "Updates spaces with the same name, leaves the rest of Zen alone")
        self.replace_mode = ModeCard(
            "Replace Zen's contents", "Removes what Arc doesn't have",
            "Removes tabs, folders, bookmarks, workspaces and containers Arc doesn't have", danger=True)
        self.add_mode.clicked.connect(lambda: self.set_value("nuke", False))
        self.replace_mode.clicked.connect(lambda: self.set_value("nuke", True))
        layout.addWidget(self.add_mode)
        layout.addWidget(self.replace_mode)
        layout.addSpacing(6)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel_confirm)
        self.restart_button = QPushButton("Start over")
        self.restart_button.setObjectName("Accent")
        self.restart_button.clicked.connect(self.reset_run)
        self.exit_button = QPushButton("Exit")
        self.exit_button.setObjectName("Danger")
        self.exit_button.clicked.connect(self.close)
        self.go_button = QPushButton()
        self.go_button.setObjectName("Primary")
        self.go_button.setDefault(True)
        self.go_button.clicked.connect(self.go_clicked)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.restart_button)
        layout.addWidget(self.exit_button)
        layout.addWidget(self.go_button)
        return footer

    def apply_platform_window_polish(self) -> None:
        polish_macos_window(self)

    # ----- state ----------------------------------------------------------

    def enabled(self, key: str) -> bool:
        if key in ARC_LOOK_KEYS and not self.arc_ok:
            return False
        depends_on = self.choices[key].depends_on
        return not depends_on or self.values[depends_on]

    def preset(self) -> str:
        if self.look_mode:
            return "look"
        if self.custom_mode:
            return "custom"
        for key in ("all", "tabs"):
            values = preset_values(key)
            if all(self.values[k] == values[k] for k in PRESET_KEYS):
                return key
        return "custom"

    def apply_preset(self, preset: str) -> None:
        if preset == "look":
            # The look as in "Arc as it was"; the other items stay as they were for migrating later
            self.values.update({key: True for key in ARC_LOOK_KEYS + tuple(k for k, _ in ZEN_SETUP)})
        elif not self.arc_ok:
            return
        elif preset != "custom":
            self.values.update(preset_values(preset))
        self.look_mode = preset == "look"
        self.custom_mode = preset == "custom"
        self.arc_forced = False
        self.confirming = False
        self.refresh()

    def look_spaces(self) -> List[SpaceOverview]:
        """Checked spaces that Zen has: the ones "just the look" restyles."""
        return [space for space in self.chosen_spaces() if space.name in self.zen_spaces]

    def look_parts(self) -> List[str]:
        v = self.values
        parts = [name for key, name in ZEN_SETUP if v[key]]
        spaces = self.look_spaces()
        if self.arc_ok and spaces and (v["workspace_icons"] or v["workspace_themes"]):
            parts.append(f"colors for {count(len(spaces), 'space')}")
        return parts

    def set_value(self, key: str, value: bool) -> None:
        if key in self.choices and not self.enabled(key):
            self.refresh()
            return
        self.values[key] = value
        if key == "nuke":
            self.confirming = False
        if key == "skip_orphaned":
            self.reload_spaces()
        if key == "auto_close_zen":
            self.refresh_zen_status()
        self.refresh()

    def chosen_spaces(self) -> List[SpaceOverview]:
        return [row.space for row in self.space_rows if row.is_checked()]

    def zen_target(self) -> str:
        try:
            return resolve_zen_profile(self.zen_combo.currentText()).name
        except Exception:
            return Path(self.zen_combo.currentText()).name

    def choose_profile(self, endpoint: Endpoint, combo: QComboBox, browse: Callable) -> None:
        menu = QMenu(self)
        for index in range(combo.count()):
            path = combo.itemText(index)
            action = menu.addAction(path)
            action.setCheckable(True)
            action.setChecked(path == combo.currentText())
            action.triggered.connect(lambda _=False, p=path: combo.setEditText(p))
        if combo.count():
            menu.addSeparator()
        menu.addAction("Choose folder…", browse)
        menu.exec(endpoint.mapToGlobal(endpoint.rect().bottomLeft()))

    def reload_spaces(self, *_):
        """Show the spaces of the selected Arc folder, keeping unchecked spaces unchecked."""
        self.unchecked_spaces |= {row.space.name for row in self.space_rows if not row.is_checked()}
        for row in self.space_rows:
            self.spaces_list.removeWidget(row)
            # deleteLater runs on the next event loop pass; hide the row now so it never lingers
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self.space_rows = []

        arc_profile = Path(self.arc_combo.currentText()).expanduser()
        overview: List[SpaceOverview] = []
        self.spaces_message.setVisible(False)
        path = format_path(arc_profile)
        self.arc_ok = is_arc_profile(arc_profile)
        # Without Arc only the look can be applied; once Arc is found, migrating is the default again
        if not self.arc_ok and not self.look_mode:
            self.look_mode = self.arc_forced = True
        elif self.arc_ok and self.arc_forced:
            self.look_mode = self.arc_forced = False
        if not self.arc_ok:
            missing = not self.arc_combo.currentText()
            self.arc_endpoint.set_status("Arc", f"Not found on {THIS_COMPUTER}" if missing else "No Arc data here",
                                         OFF if missing else DANGER,
                                         f"{path}\nChoose the folder with StorableSidebar.json.")
            self.spaces_message.setText(
                "Arc isn't here. There's nothing to migrate, but Zen can still look like Arc. "
                "Space icons and colors need Arc; everything else works without it.")
            self.spaces_message.setVisible(True)
        else:
            try:
                overview = arc_space_overview(arc_profile, include_orphaned=not self.values["skip_orphaned"])
            except Exception as exc:
                self.arc_endpoint.set_status("Arc", "Could not read spaces", DANGER, f"{path}\n{exc}")
            else:
                profiles = {space.arc_profile for space in overview if space.arc_profile}
                self.arc_endpoint.set_status("Arc", f"{len(overview)} spaces, {len(profiles)} profiles", OK, path)
                if not overview:
                    self.spaces_message.setText("This Arc folder has no spaces with tabs.")
                    self.spaces_message.setVisible(True)

        for space in overview:
            row = SpaceRow(space, space.name not in self.unchecked_spaces)
            row.toggled.connect(self.refresh)
            self.space_rows.append(row)
            self.spaces_list.addWidget(row)
        self.refresh()

    def set_all_spaces(self, checked: bool) -> None:
        for row in self.space_rows:
            row.set_checked(checked)
        self.unchecked_spaces = set() if checked else {row.space.name for row in self.space_rows}
        self.refresh()

    def refresh_zen_status(self, *_):
        text = self.zen_combo.currentText()
        try:
            profile = resolve_zen_profile(text)
        except Exception:
            self.zen_spaces = set()
            # Nothing chosen and nothing found means Zen isn't installed or never opened
            self.zen_state = "wrong" if text else "missing"
            if text:
                self.zen_endpoint.set_status("Zen", "No Zen profile here", DANGER,
                                             f"{text}\nChoose a profile folder or Zen's data folder.", "danger")
            else:
                self.zen_endpoint.set_status("Zen", f"Not found on {THIS_COMPUTER}", OFF,
                                             "Install Zen and open it once, or choose its profile folder.", "warn")
        else:
            self.zen_state = "ok"
            title = f"Zen · {profile.name}"
            self.zen_spaces = zen_space_names(profile)
            if is_zen_profile_in_use(profile):
                closing = "will be closed first" if self.values["auto_close_zen"] else "close it first"
                self.zen_endpoint.set_status(title, f"Open in Zen: {closing}", WARN, format_path(profile))
            else:
                self.zen_endpoint.set_status(title, "Ready, Zen is closed", OK, format_path(profile))
        self.refresh()

    def browse_arc(self):
        selected = QFileDialog.getExistingDirectory(self, "Select Arc data folder")
        if selected:
            self.arc_combo.setEditText(selected)

    def browse_zen(self):
        selected = QFileDialog.getExistingDirectory(self, "Select Zen profile or Zen root")
        if selected:
            try:
                self.zen_combo.setEditText(format_path(resolve_zen_profile(selected)))
            except Exception:
                self.zen_combo.setEditText(selected)

    def selected_spaces(self) -> tuple[str, ...] | None:
        """Checked space names, or None when every space is checked."""
        names = tuple(space.name for space in self.chosen_spaces())
        if len(names) == len(self.space_rows):
            return None
        if not names:
            raise ValueError("Select at least one Arc space to migrate.")
        return names

    def selected_config(self) -> MigrationOptions:
        arc_profile = Path(self.arc_combo.currentText()).expanduser()
        v = self.values
        if self.look_mode:
            names = tuple(space.name for space in self.look_spaces())
            colors = self.arc_ok and bool(names)
            return look_only(MigrationOptions(
                arc_profile=arc_profile if self.arc_ok else None,
                zen_profile=resolve_zen_profile(self.zen_combo.currentText()),
                workspace_icons=v["workspace_icons"] and colors,
                workspace_themes=v["workspace_themes"] and colors,
                default_theme=v["default_theme"] and v["workspace_themes"] and colors,
                arc_look_mod=v["arc_look_mod"],
                sidebar_mode=v["sidebar_mode"],
                toolbar_layout=v["toolbar_layout"],
                split_drag=v["split_drag"],
                auto_close_zen=v["auto_close_zen"],
                spaces=names,
            ))
        if not is_arc_profile(arc_profile):
            raise ValueError(f"Arc profile must contain a valid StorableSidebar.json:\n{arc_profile}")
        zen_profile = resolve_zen_profile(self.zen_combo.currentText())
        return MigrationOptions(
            arc_profile=arc_profile,
            zen_profile=zen_profile,
            nuke=v["nuke"],
            favicons=v["favicons"],
            folder_states=v["folder_states"],
            workspace_icons=v["workspace_icons"],
            workspace_themes=v["workspace_themes"],
            default_theme=v["default_theme"] and v["workspace_themes"],
            containers=v["containers"],
            boosts=v["boosts"],
            link_routing=v.get("link_routing", False),
            arc_look_mod=v["arc_look_mod"],
            sidebar_mode=v["sidebar_mode"],
            toolbar_layout=v["toolbar_layout"],
            split_drag=v["split_drag"],
            website_languages=v["website_languages"],
            interface_language=v["interface_language"],
            cookies=v["cookies"],
            passwords=v["passwords"],
            local_storage=v["local_storage"],
            repair_tabs=v["repair_tabs"],
            skip_orphaned=v["skip_orphaned"],
            auto_close_zen=v["auto_close_zen"],
            spaces=self.selected_spaces(),
        )

    def look_result_text(self) -> str:
        v = self.values
        done = []
        if v["arc_look_mod"]:
            done.append("the Arc Look mod")
        if v["sidebar_mode"] or v["toolbar_layout"]:
            done.append("Arc's layout" if self.arc_ok else "Arc's default layout")
        if v["split_drag"]:
            done.append("easier drag-to-split")
        text = ""
        if done:
            listed = done[0] if len(done) == 1 else ", ".join(done[:-1]) + " and " + done[-1]
            text = f"{listed[0].upper()}{listed[1:]} {'is' if len(done) == 1 else 'are'} in place. "
        if self.run_look_spaces:
            text += f"{count(self.run_look_spaces, 'space')} got their Arc icons and colors. "
        return text + "Your tabs, spaces and sign-ins weren't touched."

    def toggle_log(self) -> None:
        self.log.setVisible(not self.log.isVisible())
        self.log_toggle.setText("Hide log" if self.log.isVisible() else "Show log")
        if self.result_action.text() in ("Show log", "Hide log"):
            self.result_action.setText(self.log_toggle.text())

    def toggle_steps(self) -> None:
        self.steps_card.setVisible(not self.steps_card.isVisible())
        self.update_steps_toggle()

    def update_steps_toggle(self) -> None:
        shown = self.steps_card.isVisible()
        self.steps_toggle.setText("Hide all steps" if shown else f"Show all {count(len(self.step_rows), 'step')}")

    def result_action_clicked(self) -> None:
        if self.result_action.text() == "Start over":
            self.reset_run()
        elif self.result_action.text() in ("Show log", "Hide log"):
            self.toggle_log()
        else:
            self.open_zen()

    def open_zen(self) -> None:
        try:
            binary = find_zen_binary()
            profile = resolve_zen_profile(self.zen_combo.currentText())
            subprocess.Popen([str(binary), "-profile", str(profile)], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (ZenRunnerError, OSError, FileNotFoundError) as exc:
            QMessageBox.warning(self, "Can't open Zen", str(exc))

    def eventFilter(self, watched, event):
        # Only the run page viewport is watched; its resize moves the result
        if event.type() == QEvent.Resize and self.finished:
            QTimer.singleShot(0, self.place_result)
        return super().eventFilter(watched, event)

    def place_result(self) -> None:
        """Place the result in the column; the steps and the log hang below it."""
        if not self.result_head.isVisible():
            self.result_spacer.setFixedHeight(0)
            return
        if self.rollback_state or (self.succeeded and not self.result_has_notes):
            free = self.run_scroll.viewport().height() - 20 - 24 - self.result_head.sizeHint().height()
            self.result_spacer.setFixedHeight(max(0, free // 2))
        else:
            # A failure and a run with notes start at the same fixed height
            self.result_spacer.setFixedHeight(92)

    def refresh(self, *_):
        """Bring every chip, card, and the footer in line with the current choices."""
        if not hasattr(self, "go_button"):
            return
        v = self.values
        for key, chip in self.chips.items():
            choice = self.choices[key]
            enabled = self.enabled(key)
            on = v[key] and enabled
            chip.setChecked(on)
            chip.setText(("✓  " if on else "+  ") + choice.label)
            if enabled:
                chip.setToolTip(choice.hint)
            else:
                chip.setToolTip(f"Needs Arc on {THIS_COMPUTER}" if key in ARC_LOOK_KEYS and not self.arc_ok
                                else "Turn on space colors first")
            chip.setProperty("dimmed", "false" if enabled else "true")
            restyle(chip)
        for note, keys in self.notes:
            note.setVisible(any(v[key] for key in keys))
        preset = self.preset()
        for key, card in self.preset_cards.items():
            card.set_checked(key == preset)
            zen_ok = self.zen_state == "ok"
            needs_arc = not self.arc_ok and key != "look"
            card.set_available(zen_ok and not needs_arc, f"Needs Arc on {THIS_COMPUTER}." if needs_arc else "")
        self.add_mode.set_checked(not v["nuke"])
        self.replace_mode.set_checked(v["nuke"])

        zen_ok = self.zen_state == "ok"
        # Until Zen is found nothing can run, so nothing can be picked either
        for chip in self.chips.values():
            chip.setEnabled(zen_ok)
        for chip in self.locked_chips:
            chip.setEnabled(zen_ok)
        for mode in (self.add_mode, self.replace_mode):
            mode.setEnabled(zen_ok)
            mode.fade.setOpacity(1.0 if zen_ok else 0.45)
        missing = self.zen_state == "missing"
        self.zen_banner_title.setText(f"Zen isn't on {THIS_COMPUTER} yet" if missing else "This folder has no Zen profile")
        self.zen_banner_text.setText(
            "Install Zen and open it once so it creates a profile, then come back. Or point to a profile "
            "folder if Zen keeps it somewhere else." if missing else
            "Pick a Zen profile folder, or Zen's data folder with profiles.ini.")
        self.download_zen.setVisible(missing)

        look = self.look_mode
        first = True
        for title, line, row in self.category_rows:
            shown = not look or title in LOOK_ROWS
            row.setVisible(shown)
            if line:
                line.setVisible(shown and not first)
            first = first and not shown
        self.chips["skip_orphaned"].setVisible(not look)
        self.look_note.setVisible(look)
        self.look_note_text.setText(
            "Your tabs, spaces and sign-ins in Zen stay as they are. Only how Zen looks changes. "
            "Icons and colors go to Zen spaces named like your Arc spaces." if self.arc_ok else
            "Your tabs, spaces and sign-ins in Zen stay as they are. Without Arc, the sidebar and toolbars "
            f"take Arc's defaults: the sidebar always shown, the address {ARC_DEFAULT_ADDRESS}.")
        for row in self.space_rows:
            row.set_look(row.space.name in self.zen_spaces if look else None)
        self.choose_arc_link.setVisible(not self.arc_ok)
        self.all_link.setVisible(self.arc_ok)
        self.none_link.setVisible(self.arc_ok)
        self.choices_hint.setText("Hover an item for details." if look else
                                  "Hover an item for details. Changing any item switches to Custom.")
        self.spaces_note.setVisible(self.arc_ok)
        self.spaces_note.setText(
            "Zen spaces with the same name as in Arc get its icon and colors. Nothing is added or removed."
            if look else
            "Spaces keep their Arc profiles: each profile becomes a Zen container of the same name, and its "
            "spaces open in it. Unchecked spaces stay as they are in Zen.")

        chosen = self.chosen_spaces()
        if not self.arc_ok:
            self.spaces_caption.setText("SPACES")
        elif look:
            in_zen = sum(1 for row in self.space_rows if row.space.name in self.zen_spaces)
            self.spaces_caption.setText(f"SPACES · {len(self.look_spaces())} OF {in_zen} IN ZEN" if in_zen
                                        else "SPACES · NONE IN ZEN")
        else:
            self.spaces_caption.setText(f"SPACES · {len(chosen)} OF {len(self.space_rows)}")
        tabs = sum(space.tabs for space in chosen)
        folders = sum(space.folders for space in chosen)
        preset_name = {key: title for key, title, _, _ in PRESETS}[preset]
        title = f"{len(chosen)} of {count(len(self.space_rows), 'space')}"
        text = f"{count(tabs, 'tab')} · {count(folders, 'folder')} · {preset_name}"
        color = MUTED
        if not chosen:
            text, color = "Pick at least one space.", WARN
        parts = self.look_parts()
        if look:
            title = "Zen keeps its tabs and spaces"
            text, color = (" · ".join(parts), MUTED) if parts else ("Pick something to apply.", WARN)
        title_color = TEXT
        if not zen_ok:
            title_color = WARN if missing else DANGER
            title, color = ("Zen isn't set up yet", MUTED) if missing else ("No Zen profile in this folder", MUTED)
            text = ("Install Zen and open it once, then come back — or choose its profile folder in the Zen card "
                    "above." if missing else
                    "Choose a Zen profile folder, or Zen's data folder with profiles.ini, in the Zen card above.")
        if self.confirming:
            title_color = TEXT
            title = f"Replace everything in {self.zen_target()}?"
            text = ("Tabs, folders, bookmarks, workspaces and containers Arc doesn't have will be removed. "
                    "You can roll back afterwards.")
            color = DANGER
        if self.running:
            title = "Applying the look…" if self.run_look else "Migrating…"
            text, color = "Keep Zen closed until it finishes.", MUTED
        elif self.rollback_state == "running":
            title, text, color = "Rolling back…", "Keep Zen closed until it finishes.", MUTED
        elif self.rollback_state == "done":
            title, text, color = "Rolled back", "You can close this window.", MUTED
        elif self.rollback_state == "failed":
            title, text, color = "Rollback failed", "The backup is still in the Zen profile.", DANGER
        elif self.finished and self.succeeded:
            title, text, color = "Done", "The backup is deleted when you close this window.", MUTED
        elif self.finished:
            title = "Couldn't apply the look" if self.run_look else "Migration stopped"
            text, color = "Roll back, or fix the problem and start over.", DANGER
        if self.running or self.finished:
            title_color = TEXT
        self.summary_title.setText(title)
        self.summary_title.setStyleSheet(f"font-weight: 600; color: {title_color};")
        self.summary_text.setText(text)
        self.summary_text.setStyleSheet(f"color: {color}; font-size: 12px;")

        idle = not self.running and not self.finished
        self.zen_banner.setVisible(idle and not zen_ok)
        # In "just the look" the spaces matter only for their icons and colors
        spaces_matter = not look or not self.arc_ok or v["workspace_icons"] or v["workspace_themes"]
        self.aside.setEnabled(idle and spaces_matter)
        self.aside_fade.setOpacity(1.0 if idle and spaces_matter else 0.5)
        self.arc_endpoint.setEnabled(idle)
        self.zen_endpoint.setEnabled(idle)
        # While confirming the warning needs the room; Cancel brings the choice back
        self.add_mode.setVisible(idle and not self.confirming and not look)
        self.replace_mode.setVisible(idle and not self.confirming and not look)
        self.cancel_button.setVisible(idle and self.confirming)
        # After a rollback Start over and Exit sit on the result screen itself
        finished = self.finished and self.rollback_state not in ("running", "done")
        self.restart_button.setVisible(finished)
        self.exit_button.setVisible(finished)
        self.go_button.setVisible(idle)
        self.go_button.setEnabled(zen_ok and (bool(parts) if look else bool(chosen)))
        self.go_button.setIcon(QIcon(svg_pixmap(SPARKLES_SVG, "#ffffff", 16, max(2.0, self.devicePixelRatioF())))
                               if look else QIcon())
        if look:
            self.go_button.setText("Apply the look")
        elif self.confirming:
            self.go_button.setText("Yes, replace and migrate")
        elif v["nuke"]:
            self.go_button.setText("Replace and migrate")
        else:
            self.go_button.setText(f"Migrate {count(len(chosen), 'space')}")
        self.go_button.setObjectName("PrimaryDanger" if v["nuke"] and not look else "Primary")
        restyle(self.go_button)

    # ----- running --------------------------------------------------------

    def go_clicked(self) -> None:
        if self.values["nuke"] and not self.look_mode and not self.confirming:
            self.confirming = True
            self.refresh()
            return
        self.start_migration()

    def cancel_confirm(self) -> None:
        self.confirming = False
        self.refresh()

    def reset_run(self) -> None:
        self.finished = False
        self.rollback_state = ""
        self.log.clear()
        self.pages.setCurrentIndex(0)
        self.refresh_zen_status()

    def start_migration(self):
        self.confirming = False
        try:
            config = self.selected_config()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid selection", str(exc))
            self.refresh()
            return
        if not self.ensure_zen_closed(config):
            self.refresh()
            return
        profile = self.profile_key(config)
        kept = self.snapshots.get(profile)
        if kept and not kept.is_dir():
            kept = None
        self.runs[profile] = self.runs.get(profile, 0) + 1 if kept else 1
        self.snapshot_dir = kept
        self.rollback_state = ""
        self.run_look = not config.import_tabs
        self.run_look_spaces = len(config.spaces or ()) if config.workspace_icons or config.workspace_themes else 0

        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.step_rows = {}
        self.step_notes = {}
        self.step_infos = {}
        self.step_details = {}
        titles = [step.title for step in migration_steps(config, Path(tempfile.gettempdir()) / "arc-to-zen-plan.json")]
        for index, title in enumerate(titles):
            if index:
                self.steps_layout.addWidget(divider())
            row = StepRow(title)
            self.step_rows[title] = row
            self.steps_layout.addWidget(row)

        self.pages.setCurrentIndex(1)
        self.result_head.setVisible(False)
        self.place_result()
        self.steps_card.setVisible(True)
        self.log_toggle.setVisible(True)
        self.log.setVisible(False)
        self.log_toggle.setText("Show log")
        self.progress_box.setVisible(True)
        self.progress.setMaximum(len(titles))
        self.progress.setValue(0)
        self.progress_text.setText(f"1 of {len(titles)}")
        self.run_scroll.verticalScrollBar().setValue(0)
        self.log.clear()
        self.running = True
        self.refresh()

        self.worker = MigrationWorker(config, kept)
        self.worker.line.connect(self.append_log)
        self.worker.step.connect(self.update_step)
        self.worker.snapshot.connect(self.set_snapshot)
        self.worker.done.connect(self.finish_migration)
        self.worker.start()

    def ensure_zen_closed(self, config: MigrationOptions) -> bool:
        # Only the Zen running the target profile has to close; other Zen windows keep running.
        processes = zen_processes_using_profile(config.zen_profile)
        if not processes:
            if is_zen_profile_in_use(config.zen_profile):
                QMessageBox.critical(
                    self,
                    "Zen profile is in use",
                    f"The Zen profile is locked by a running process:\n{config.zen_profile}\n\nClose it and start the migration again.",
                )
                return False
            return True

        names = ", ".join(f"{process.info.get('name')} ({process.pid})" for process in processes)
        if not config.auto_close_zen:
            QMessageBox.critical(
                self,
                "Zen is running",
                f"Zen is running and automatic close is disabled:\n{names}\n\nClose Zen and start the migration again.",
            )
            return False

        alive = terminate_zen_processes(processes)
        if alive:
            alive = kill_zen_processes(alive)

        if alive:
            QMessageBox.critical(self, "Zen is still running", "Zen is still running. Migration was not started.")
            return False

        return True

    def append_log(self, line: str):
        self.log.append(line)
        text = line.strip()
        if text.startswith("❌") and self.current_step_title:
            self.step_notes[self.current_step_title] = text.lstrip("❌").strip()
        elif text.startswith(NOTE_PREFIX) and self.current_step_title:
            self.step_infos.setdefault(self.current_step_title, []).append(text[len(NOTE_PREFIX):].strip())
        elif text.startswith(DETAIL_PREFIX) and self.current_step_title:
            self.step_details.setdefault(self.current_step_title, []).append(text[len(DETAIL_PREFIX):].strip())

    def update_step(self, current: int, total: int, title: str):
        for row_title, row in self.step_rows.items():
            if row_title == title:
                break
            row.set_state("done")
        if title in self.step_rows:
            row = self.step_rows[title]
            row.set_state("running")
            # Keep the running step in sight, with the next ones peeking below it
            QTimer.singleShot(0, lambda: self.running and self.run_scroll.ensureWidgetVisible(row, 0, 56))
        self.current_step_title = title
        self.progress_title.setText(title)
        self.progress.setValue(current - 1)
        self.progress_text.setText(f"{current} of {total}")

    def finish_migration(self, ok: bool, message: str):
        self.running = False
        self.finished = True
        self.succeeded = ok
        self.progress_box.setVisible(False)
        self.log_toggle.setVisible(False)
        reached = True
        for title, row in self.step_rows.items():
            if not ok and title == self.current_step_title:
                row.set_state("failed", self.step_notes.get(title) or message)
                reached = False
            elif reached and title in self.step_infos:
                items = [f"•  {item}" for item in self.step_details.get(title, [])]
                row.set_state("noted", "\n".join(self.step_infos[title] + items))
            elif reached and ok:
                row.set_state("done")

        chosen = self.chosen_spaces()
        tabs = sum(s.tabs for s in chosen)
        folders = sum(s.folders for s in chosen)
        notes = [(title, note) for title, items in self.step_infos.items() if title in self.step_rows for note in items]
        color = OK if ok else DANGER
        self.result_badge.setVisible(ok and bool(notes))
        self.result_mark.setText("✓" if ok else "!")
        self.result_mark.setStyleSheet(
            f"background: {color}; color: #ffffff; border-radius: 28px; font-size: 26px; font-weight: 700;")
        self.result_has_notes = ok and bool(notes)
        can_roll_back = self.snapshot_dir is not None
        if self.run_look and ok:
            self.result_title.setText("Zen looks like Arc now")
            self.result_text.setText(self.look_result_text() + (
                " A few things didn't apply as they were — see the notes below." if notes else ""))
        elif not ok:
            self.result_title.setText("Couldn't apply the look" if self.run_look else "Migration stopped")
            reason = message if message.endswith(".") else f"{message}."
            undo = f" The steps before it already changed Zen; roll back to put it back as it was {self.before_runs()}." if can_roll_back else ""
            self.result_text.setText(reason + undo)
        elif notes:
            self.result_title.setText(f"Migration complete with {count(len(notes), 'note')}")
            self.result_text.setText("Your Arc spaces are in Zen. A few things didn't carry over as they were — "
                                     "see the notes below.")
        else:
            self.result_title.setText("Migration complete")
            self.result_text.setText("Your Arc spaces are in Zen, ready to open.")
        keep = ("The backup from before the first migration is kept until you close this window."
                if self.run_count() > 1 else "The backup is kept until you close this window.")
        check = "Check Zen." if self.run_look else "Check your spaces in Zen."
        self.result_hint.setText(f"{check} {keep}" if ok else keep)
        self.result_hint.setVisible(can_roll_back)
        self.rollback_link.setVisible(ok and can_roll_back)
        self.rollback_confirm.setVisible(False)
        self.rollback_confirm_title.setText(f"Roll Zen back to {self.before_runs()}?")
        self.rollback_confirm_text.setText(
            f"Spaces, tabs, settings and sign-ins in {self.zen_target()} go back to how they were {self.before_runs()}.")
        self.result_rollback.setVisible(not ok and can_roll_back)

        while self.result_stats_layout.count():
            item = self.result_stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        containers = {s.container for s in chosen if s.container} if self.values["containers"] else set()
        stats = [(len(chosen), "space", "spaces"), (tabs, "tab", "tabs"), (folders, "folder", "folders")]
        if containers:
            stats.append((len(containers), "container", "containers"))
        if self.run_look:
            settings = sum(1 for key, _ in ZEN_SETUP if self.values[key])
            stats = [(settings, "Zen setting", "Zen settings"),
                     (self.run_look_spaces, "space restyled", "spaces restyled"), (0, "tab changed", "tabs changed")]
        for number, one, many in stats:
            stat = frame("Stat")
            stat.setMinimumWidth(96)
            box = QVBoxLayout(stat)
            box.setContentsMargins(14, 10, 14, 10)
            box.setSpacing(0)
            value = label(str(number))
            value.setStyleSheet("font-size: 20px; font-weight: 700;")
            name = label(one if number == 1 else many, "small")
            for text in (value, name):
                text.setAlignment(Qt.AlignCenter)
                box.addWidget(text)
            self.result_stats_layout.addWidget(stat)
        self.result_stats.setVisible(ok)

        while self.result_notes_layout.count():
            item = self.result_notes_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for title, note in notes:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(10)
            icon = QLabel("i")
            icon.setFixedSize(18, 18)
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet(NOTE_ICON.replace("10px", "9px").replace("12px", "11px"))
            line.addWidget(icon, 0, Qt.AlignTop)
            heading = label(title)
            heading.setStyleSheet("font-weight: 600;")
            line.addLayout(text_column(heading, label(note, "muted", wrap=True)), 1)
            self.result_notes_layout.addWidget(row)
        self.result_notes.setVisible(ok and bool(notes))

        # A failure offers the rollback first; its log is the second button
        self.result_action.setObjectName("Primary" if ok else "" if can_roll_back else "PrimaryDanger")
        self.result_action.setText("Open Zen" if ok else "Show log")
        self.result_action.setVisible(True)
        self.result_exit.setVisible(False)
        restyle(self.result_action)
        self.steps_toggle.setVisible(ok)
        # A failure shows every step at once; a success keeps them one click away
        self.steps_card.setVisible(not ok)
        self.log.setVisible(False)
        self.log_toggle.setText("Show log")
        self.update_steps_toggle()
        self.result_head.setVisible(True)
        self.run_scroll.verticalScrollBar().setValue(0)
        self.refresh()
        QTimer.singleShot(0, self.place_result)

    # ----- rollback -------------------------------------------------------

    def set_snapshot(self, path: str) -> None:
        self.snapshot_dir = Path(path)
        self.snapshots[str(snapshot_profile(path))] = self.snapshot_dir

    def profile_key(self, config: MigrationOptions) -> str:
        try:
            return str(resolve_zen_profile(config.zen_profile))
        except Exception:
            return str(config.zen_profile)

    def run_count(self) -> int:
        """Runs from this window the current backup covers."""
        if not self.snapshot_dir:
            return 0
        return self.runs.get(next((p for p, d in self.snapshots.items() if d == self.snapshot_dir), ""), 1)

    def before_runs(self) -> str:
        return "before the first migration" if self.run_count() > 1 else "before the migration"

    def ask_rollback(self) -> None:
        self.rollback_link.setVisible(False)
        self.rollback_confirm.setVisible(True)
        QTimer.singleShot(0, self.place_result)
        # With notes the result is tall and the question lands below the fold
        QTimer.singleShot(0, lambda: self.run_scroll.ensureWidgetVisible(self.rollback_confirm, 0, 24))

    def cancel_rollback(self) -> None:
        self.rollback_confirm.setVisible(False)
        self.rollback_link.setVisible(True)
        QTimer.singleShot(0, self.place_result)

    def start_rollback(self) -> None:
        if not self.snapshot_dir:
            return
        try:
            config = self.selected_config()
        except Exception as exc:
            QMessageBox.critical(self, "Can't roll back", str(exc))
            return
        if not self.ensure_zen_closed(config):
            return
        self.rollback_state = "running"
        self.show_rollback_state("…", ACCENT, "Rolling back…",
                                 f"Putting back the files of {self.zen_target()} as they were {self.before_runs()}.")
        self.rollback_worker = RollbackWorker(self.snapshot_dir)
        self.rollback_worker.line.connect(self.log.append)
        self.rollback_worker.done.connect(self.finish_rollback)
        self.rollback_worker.start()

    def finish_rollback(self, ok: bool, message: str) -> None:
        if ok:
            self.rollback_state = "done"
            self.show_rollback_state("↺", ACCENT, "Zen is back as it was",
                                     f"{self.zen_target()} is now exactly as it was {self.before_runs()}. "
                                     "Fix what went wrong and start over, or close the window.")
            # The backup still holds the profile as it is now: the next run starts counting anew
            for profile, kept in self.snapshots.items():
                if kept == self.snapshot_dir:
                    self.runs[profile] = 0
            self.result_action.setText("Start over")
            self.result_action.setObjectName("Primary")
            restyle(self.result_action)
            self.result_action.setVisible(True)
            self.result_exit.setVisible(True)
        else:
            self.rollback_state = "failed"
            self.show_rollback_state("!", DANGER, "Rollback failed",
                                     f"{message} The backup is still in the Zen profile: {self.snapshot_dir.name}.")
            self.result_action.setText("Show log")
            self.result_action.setObjectName("PrimaryDanger")
            restyle(self.result_action)
            self.result_action.setVisible(True)

    def show_rollback_state(self, mark: str, color: str, title: str, text: str) -> None:
        self.result_mark.setText(mark)
        self.result_mark.setStyleSheet(
            f"background: {color}; color: #ffffff; border-radius: 28px; font-size: 26px; font-weight: 700;")
        self.result_badge.setVisible(False)
        self.result_title.setText(title)
        self.result_text.setText(text)
        for widget in (self.result_stats, self.result_notes, self.result_rollback, self.result_action, self.result_exit,
                       self.steps_toggle, self.result_hint, self.rollback_link, self.rollback_confirm,
                       self.steps_card, self.log):
            widget.setVisible(False)
        self.refresh()
        QTimer.singleShot(0, self.place_result)

    def changeEvent(self, event) -> None:
        # Back in the window after installing Zen or Arc: look for them again
        if event.type() == QEvent.ActivationChange and self.isActiveWindow() and not self.running and not self.finished:
            QTimer.singleShot(0, self.rediscover_profiles)
        super().changeEvent(event)

    def rediscover_profiles(self) -> None:
        """Fill in Zen or Arc when none was found before; a folder picked by hand is left alone."""
        for combo, missing, discover in ((self.zen_combo, self.zen_state == "missing", discover_zen_profiles),
                                         (self.arc_combo, not self.arc_ok and not self.arc_combo.currentText(),
                                          discover_arc_profiles)):
            if not missing:
                continue
            found = discover()
            if found:
                combo.clear()
                for profile in found:
                    combo.addItem(format_path(profile))
                combo.setEditText(format_path(found[0]))

    def closeEvent(self, event) -> None:
        if self.running or self.rollback_state == "running":
            event.ignore()
            return
        for kept in self.snapshots.values():
            discard(kept)
        super().closeEvent(event)


def main() -> int:
    use_utf8_output()
    QApplication.setDesktopSettingsAware(False)
    QApplication.setApplicationName("Arc to Zen")
    QApplication.setOrganizationName("Thinkscape")
    app = QApplication(sys.argv)
    force_macos_light_appearance()
    app.setWindowIcon(QIcon(str(resource_path("assets", "app-icon.png"))))
    apply_light_theme(app)
    app.setStyleSheet(APP_STYLESHEET)
    window = MainWindow()
    window.show()
    window.apply_platform_window_polish()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
