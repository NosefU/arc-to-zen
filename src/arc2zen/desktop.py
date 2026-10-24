#!/usr/bin/env python3
"""Desktop UI for Arc to Zen: one window around the shared migration."""

from __future__ import annotations

import logging
import os
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
    from PySide6.QtCore import QByteArray, QPoint, QRect, QRectF, QSize, Qt, QThread, Signal
    from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
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

from .migration import MigrationOptions, migration_steps, run_migration
from .profile_paths import (
    discover_arc_profiles,
    discover_zen_profiles,
    is_arc_profile,
    is_zen_profile_in_use,
    resolve_zen_profile,
    zen_profile_lock_files,
)
from .space_overview import SpaceOverview, arc_space_overview
from .zen_assets import zen_selectable_icon_svg


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
DANGER = "#b42318"
DANGER_SOFT = "#fdf0ee"
DANGER_LINE = "#f3c9c4"
OFF = "#c9c6d4"

APP_STYLESHEET = f"""
QWidget {{ color: {TEXT}; font-size: 13px; }}
QMainWindow, QWidget#Root {{ background: {BG}; }}
QFrame#Window {{ background: {WINDOW}; border: 1px solid {LINE}; border-radius: 14px; }}
QFrame#Header {{ background: transparent; border: 0; border-bottom: 1px solid {LINE}; }}
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
QFrame#Success {{ background: {OK_SOFT}; border: 1px solid {OK_LINE}; border-radius: 12px; }}
QFrame#Failure {{ background: {DANGER_SOFT}; border: 1px solid {DANGER_LINE}; border-radius: 12px; }}
QFrame#Endpoint {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; }}
QFrame#Endpoint:hover, QFrame#Endpoint:focus {{ border-color: {ACCENT}; }}
QFrame#SpaceRow {{ background: transparent; border: 1.5px solid transparent; border-radius: 10px; }}
QFrame#SpaceRow[checked="true"] {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
QFrame#SpaceRow:focus {{ border-color: {ACCENT}; }}
QFrame#Preset {{ background: {WINDOW}; border: 1.5px solid {LINE}; border-radius: 12px; }}
QFrame#Preset[checked="true"] {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; }}
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
QPushButton#Link {{ background: transparent; border: 0; color: {ACCENT_TEXT}; padding: 4px 8px; }}
QPushButton#Link:hover {{ color: #2a2190; }}
QPushButton#Chip {{ background: transparent; border: 1px solid {LINE}; border-radius: 15px;
    color: {MUTED}; font-weight: 500; padding: 5px 12px; min-height: 20px; }}
QPushButton#Chip:hover {{ border-color: #b3afc2; }}
QPushButton#Chip:checked {{ background: {ACCENT_SOFT}; border-color: {ACCENT}; color: {ACCENT_TEXT}; font-weight: 600; }}
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


def terminate_zen_processes(processes: list[psutil.Process]) -> list[psutil.Process]:
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

    def set_status(self, title: str, subtitle: str, color: str, tooltip: str) -> None:
        self.dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.setToolTip(tooltip)


class SpaceRow(Clickable):
    """A selectable row for one Arc space: icon, name, counts, and its container."""

    toggled = Signal(bool)

    def __init__(self, space: SpaceOverview, checked: bool, parent=None):
        super().__init__("SpaceRow", f"Space {space.name}", parent)
        self.space = space

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

        name = label(space.name)
        name.setStyleSheet("font-weight: 600;")
        counts = f"{count(space.tabs, 'tab')} · {count(space.folders, 'folder')}"
        if space.container:
            counts += f" · {space.container} container"
        self.check = QLabel()
        self.check.setFixedSize(20, 20)
        self.check.setAlignment(Qt.AlignCenter)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(12)
        layout.addWidget(badge)
        layout.addLayout(text_column(name, label(counts, "small", wrap=True)), 1)
        layout.addWidget(self.check)
        self.clicked.connect(self.toggle)
        self.set_checked(checked)

    def set_checked(self, checked: bool) -> None:
        self.check.setText("✓" if checked else "")
        self.check.setStyleSheet(
            f"background: {ACCENT}; color: #ffffff; border-radius: 6px; font-weight: 700;"
            if checked else f"background: transparent; border: 1.5px solid {OFF}; border-radius: 6px;"
        )
        super().set_checked(checked)

    def toggle(self) -> None:
        self.set_checked(not self.is_checked())
        self.toggled.emit(self.is_checked())


class PresetCard(Clickable):
    """One of the ready-made selections: Just tabs, Arc as it was, Custom."""

    def __init__(self, title: str, hint: str, recommended: bool):
        super().__init__("Preset", title)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        title_label = label(title)
        title_label.setStyleSheet("font-size: 15px; font-weight: 600;")
        heading.addWidget(title_label, 1)
        if recommended:
            badge = label("Recommended")
            badge.setStyleSheet(
                f"background: {OK_SOFT}; color: {OK}; border-radius: 9px; padding: 2px 8px;"
                " font-size: 11px; font-weight: 600;"
            )
            heading.addWidget(badge)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        layout.addLayout(heading)
        layout.addWidget(label(hint, "small", wrap=True))
        layout.addStretch(1)
        self.setMinimumHeight(76)


class ModeCard(Clickable):
    """A compact radio card next to the Migrate button: spaces added to Zen, or replacing its contents."""

    def __init__(self, title: str, subtitle: str, hint: str, danger: bool = False):
        super().__init__("Mode", title)
        self.danger = danger
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
        }
        box, mark, color, weight = styles[state]
        self.icon.setStyleSheet(box + " font-size: 11px;")
        self.icon.setText(mark)
        self.title.setStyleSheet(f"color: {color}; font-weight: {weight};")
        self.note.setText(note)
        self.note.setVisible(bool(note))
        self.note.setProperty("role", "error" if state == "failed" else "small")
        restyle(self.note)


class MigrationWorker(QThread):
    line = Signal(str)
    step = Signal(int, int, str)
    done = Signal(bool, str)

    def __init__(self, config: MigrationOptions):
        super().__init__()
        self.config = config

    def run(self):
        try:
            self._run()
        except Exception as exc:
            self.done.emit(False, str(exc))

    def _run(self):
        run_migration(self.config, emit_line=self.line.emit, on_step=self.step.emit)
        self.done.emit(True, "Migration finished successfully.")


@dataclass(frozen=True)
class Choice:
    key: str  # MigrationOptions field, or "" for the always-on core import
    label: str
    hint: str
    depends_on: str = ""


KEYCHAIN_NOTE = "macOS will ask once for access to “Arc Safe Storage” in your Keychain."

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
    ], KEYCHAIN_NOTE, ("cookies", "local_storage", "passwords")),
    ("Rules", [
        Choice("boosts", "Boosts", "CSS and hidden elements per site; Zen boosts have no JavaScript"),
        Choice("link_routing", "Air Traffic Control", "Rules that open links in a space become Zen Space Routing"),
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
    Choice("create_backups", "Back up Zen files", "Copies every Zen file before changing it"),
    Choice("auto_close_zen", "Close Zen if needed", "Only the Zen running this profile"),
    Choice("skip_orphaned", "Skip “Orphaned”", "Unmatched Essentials go to the first selected space"),
]

PRESET_KEYS = [c.key for _, choices, _, _ in CATEGORIES for c in choices if c.key]
TABS_ONLY = {"favicons", "folder_states", "repair_tabs", "workspace_icons", "workspace_themes", "default_theme"}
PRESETS = [
    ("tabs", "Just tabs", "Spaces, tabs and how they look. Nothing else in Zen changes.", False),
    ("all", "Arc as it was", "Plus sign-ins, boosts, routing and an Arc-like Zen.", True),
    ("custom", "Custom", "Turn items on and off below.", False),
]


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
        self.step_rows: Dict[str, StepRow] = {}
        self.current_step_title = ""
        self.step_notes: Dict[str, str] = {}

        self.setWindowTitle("Arc to Zen")
        self.setWindowIcon(QIcon(str(resource_path("assets", "app-icon.png"))))
        self.resize(1040, 760)
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
        self.go_button.setFocus()

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
        self.pages.addWidget(self._scroll(self._build_run_page()))
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
        heading.addWidget(self._link("All", lambda: self.set_all_spaces(True)))
        heading.addWidget(self._link("None", lambda: self.set_all_spaces(False)))
        layout.addLayout(heading)
        self.spaces_list = QVBoxLayout()
        self.spaces_list.setSpacing(4)
        layout.addLayout(self.spaces_list)
        self.spaces_message = label("", "muted", wrap=True)
        layout.addWidget(self.spaces_message)
        layout.addWidget(label(
            "Each space opens in a container named after its Arc profile. "
            "Unchecked spaces stay as they are in Zen.", "small", wrap=True))
        layout.addStretch(1)

        outer = QVBoxLayout(aside)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._scroll(content))
        return aside

    def _chip(self, choice: Choice) -> QPushButton:
        chip = QPushButton()
        chip.setObjectName("Chip")
        chip.setCheckable(True)
        chip.setToolTip(choice.hint)
        chip.setAccessibleName(choice.label)
        if choice.key:
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda checked, key=choice.key: self.set_value(key, checked))
            self.chips[choice.key] = chip
        else:
            # Always moved: it stays on and only explains itself
            chip.setText("✓  " + choice.label)
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
        layout.addWidget(label("WHAT COMES ALONG", "caps"))

        presets = QHBoxLayout()
        presets.setSpacing(10)
        self.preset_cards: Dict[str, PresetCard] = {}
        for key, title, hint, recommended in PRESETS:
            card = PresetCard(title, hint, recommended)
            if key == "custom":
                card.setCursor(Qt.ArrowCursor)
            else:
                card.clicked.connect(lambda k=key: self.apply_preset(k))
            self.preset_cards[key] = card
            presets.addWidget(card, 1)
        layout.addLayout(presets)

        self.chips: Dict[str, QPushButton] = {}
        self.notes: List[tuple[QLabel, tuple]] = []
        card = frame("Card")
        rows = QVBoxLayout(card)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(0)
        for index, (title, choices, note, note_keys) in enumerate(CATEGORIES):
            if index:
                rows.addWidget(divider())
            rows.addWidget(self._category_row(title, choices, note, note_keys))
        rows.addWidget(divider())
        safety = self._category_row("Safety", SAFETY, "", ())
        self.backup_note = label("Without backups, a failed run can't be undone.", "warn", wrap=True)
        safety.layout().itemAt(1).layout().addWidget(self.backup_note)
        rows.addWidget(safety)
        layout.addWidget(card)
        layout.addWidget(label("Hover an item for details. Changing any item switches to Custom.", "small", wrap=True))
        layout.addStretch(1)
        return page

    def _build_run_page(self) -> QWidget:
        page = QWidget()
        run = QVBoxLayout(page)
        run.setContentsMargins(24, 20, 24, 24)
        run.setSpacing(14)

        self.result_card = QFrame()
        result = QHBoxLayout(self.result_card)
        result.setContentsMargins(18, 16, 18, 16)
        result.setSpacing(14)
        self.result_mark = QLabel()
        self.result_mark.setFixedSize(40, 40)
        self.result_mark.setAlignment(Qt.AlignCenter)
        self.result_title = label("")
        self.result_title.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.result_text = label("", "muted", wrap=True)
        result.addWidget(self.result_mark, 0, Qt.AlignTop)
        result.addLayout(text_column(self.result_title, self.result_text), 1)
        self.result_card.setVisible(False)
        run.addWidget(self.result_card)

        self.progress_box = QWidget()
        progress = QVBoxLayout(self.progress_box)
        progress.setContentsMargins(0, 0, 0, 0)
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
        run.addWidget(self.progress_box)

        self.steps_card = frame("Card")
        self.steps_layout = QVBoxLayout(self.steps_card)
        self.steps_layout.setContentsMargins(16, 6, 16, 6)
        self.steps_layout.setSpacing(0)
        run.addWidget(self.steps_card)
        self.log_toggle = self._link("Show log", self.toggle_log)
        run.addWidget(self.log_toggle, 0, Qt.AlignLeft)
        run.addWidget(self.log)
        run.addStretch(1)
        return page

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
        self.restart_button.clicked.connect(self.reset_run)
        self.go_button = QPushButton()
        self.go_button.setObjectName("Primary")
        self.go_button.setDefault(True)
        self.go_button.clicked.connect(self.go_clicked)
        layout.addWidget(self.cancel_button)
        layout.addWidget(self.restart_button)
        layout.addWidget(self.go_button)
        return footer

    def apply_platform_window_polish(self) -> None:
        polish_macos_window(self)

    # ----- state ----------------------------------------------------------

    def enabled(self, key: str) -> bool:
        depends_on = self.choices[key].depends_on
        return not depends_on or self.values[depends_on]

    def preset(self) -> str:
        for key in ("all", "tabs"):
            values = preset_values(key)
            if all(self.values[k] == values[k] for k in PRESET_KEYS):
                return key
        return "custom"

    def apply_preset(self, preset: str) -> None:
        self.values.update(preset_values(preset))
        self.refresh()

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
        if not is_arc_profile(arc_profile):
            self.arc_endpoint.set_status("Arc", "No Arc data here", DANGER,
                                         f"{path}\nChoose the folder with StorableSidebar.json.")
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
            self.zen_endpoint.set_status("Zen", "Not a Zen profile", DANGER,
                                         f"{text}\nChoose a profile folder or Zen's data folder.")
        else:
            title = f"Zen · {profile.name}"
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
        if not is_arc_profile(arc_profile):
            raise ValueError(f"Arc profile must contain a valid StorableSidebar.json:\n{arc_profile}")
        zen_profile = resolve_zen_profile(self.zen_combo.currentText())
        v = self.values
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
            link_routing=v["link_routing"],
            arc_look_mod=v["arc_look_mod"],
            sidebar_mode=v["sidebar_mode"],
            toolbar_layout=v["toolbar_layout"],
            split_drag=v["split_drag"],
            cookies=v["cookies"],
            passwords=v["passwords"],
            local_storage=v["local_storage"],
            repair_tabs=v["repair_tabs"],
            skip_orphaned=v["skip_orphaned"],
            create_backups=v["create_backups"],
            auto_close_zen=v["auto_close_zen"],
            spaces=self.selected_spaces(),
        )

    def toggle_log(self) -> None:
        self.log.setVisible(not self.log.isVisible())
        self.log_toggle.setText("Hide log" if self.log.isVisible() else "Show log")

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
            chip.setToolTip(choice.hint if enabled else "Turn on space colors first")
            chip.setProperty("dimmed", "false" if enabled else "true")
            restyle(chip)
        for note, keys in self.notes:
            note.setVisible(any(v[key] for key in keys))
        self.backup_note.setVisible(not v["create_backups"])
        preset = self.preset()
        for key, card in self.preset_cards.items():
            card.set_checked(key == preset)
        self.add_mode.set_checked(not v["nuke"])
        self.replace_mode.set_checked(v["nuke"])

        chosen = self.chosen_spaces()
        self.spaces_caption.setText(f"SPACES · {len(chosen)} OF {len(self.space_rows)}")
        tabs = sum(space.tabs for space in chosen)
        folders = sum(space.folders for space in chosen)
        preset_name = {key: title for key, title, _, _ in PRESETS}[preset]
        title = f"{len(chosen)} of {count(len(self.space_rows), 'space')}"
        text = f"{count(tabs, 'tab')} · {count(folders, 'folder')} · {preset_name}"
        color = MUTED
        if not chosen:
            text, color = "Pick at least one space.", WARN
        if self.confirming:
            title = f"Replace everything in {self.zen_target()}?"
            text = ("Tabs, folders, bookmarks, workspaces and containers Arc doesn't have will be removed. "
                    + ("Backups are on." if v["create_backups"] else "Backups are off!"))
            color = DANGER
        if self.running:
            title, text, color = "Migrating…", "Keep Zen closed until it finishes.", MUTED
        elif self.finished and self.succeeded:
            title, text, color = "Done", "You can close this window.", MUTED
        elif self.finished:
            title, text, color = "Migration stopped", "Fix the problem above and start over.", DANGER
        self.summary_title.setText(title)
        self.summary_text.setText(text)
        self.summary_text.setStyleSheet(f"color: {color}; font-size: 12px;")

        idle = not self.running and not self.finished
        self.aside.setEnabled(idle)
        self.aside_fade.setOpacity(1.0 if idle else 0.5)
        self.arc_endpoint.setEnabled(idle)
        self.zen_endpoint.setEnabled(idle)
        # While confirming the warning needs the room; Cancel brings the choice back
        self.add_mode.setVisible(idle and not self.confirming)
        self.replace_mode.setVisible(idle and not self.confirming)
        self.cancel_button.setVisible(idle and self.confirming)
        self.restart_button.setVisible(self.finished)
        self.go_button.setVisible(idle)
        self.go_button.setEnabled(bool(chosen))
        if self.confirming:
            self.go_button.setText("Yes, replace and migrate")
        elif v["nuke"]:
            self.go_button.setText("Replace and migrate")
        else:
            self.go_button.setText(f"Migrate {count(len(chosen), 'space')}")
        self.go_button.setObjectName("PrimaryDanger" if v["nuke"] else "Primary")
        restyle(self.go_button)

    # ----- running --------------------------------------------------------

    def go_clicked(self) -> None:
        if self.values["nuke"] and not self.confirming:
            self.confirming = True
            self.refresh()
            return
        self.start_migration()

    def cancel_confirm(self) -> None:
        self.confirming = False
        self.refresh()

    def reset_run(self) -> None:
        self.finished = False
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

        while self.steps_layout.count():
            item = self.steps_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.step_rows = {}
        self.step_notes = {}
        titles = [step.title for step in migration_steps(config, Path(tempfile.gettempdir()) / "arc-to-zen-plan.json")]
        for index, title in enumerate(titles):
            if index:
                self.steps_layout.addWidget(divider())
            row = StepRow(title)
            self.step_rows[title] = row
            self.steps_layout.addWidget(row)

        self.pages.setCurrentIndex(1)
        self.result_card.setVisible(False)
        self.progress_box.setVisible(True)
        self.progress.setMaximum(len(titles))
        self.progress.setValue(0)
        self.progress_text.setText(f"1 of {len(titles)}")
        self.log.clear()
        self.running = True
        self.refresh()

        self.worker = MigrationWorker(config)
        self.worker.line.connect(self.append_log)
        self.worker.step.connect(self.update_step)
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
        if line.lstrip().startswith("❌") and self.current_step_title:
            self.step_notes[self.current_step_title] = line.strip().lstrip("❌").strip()

    def update_step(self, current: int, total: int, title: str):
        for row_title, row in self.step_rows.items():
            if row_title == title:
                break
            row.set_state("done")
        if title in self.step_rows:
            self.step_rows[title].set_state("running")
        self.current_step_title = title
        self.progress_title.setText(title)
        self.progress.setValue(current - 1)
        self.progress_text.setText(f"{current} of {total}")

    def finish_migration(self, ok: bool, message: str):
        self.running = False
        self.finished = True
        self.succeeded = ok
        self.progress_box.setVisible(False)
        if ok:
            for row in self.step_rows.values():
                row.set_state("done")
        elif self.current_step_title in self.step_rows:
            note = self.step_notes.get(self.current_step_title) or message
            self.step_rows[self.current_step_title].set_state("failed", note)

        chosen = self.chosen_spaces()
        self.result_card.setObjectName("Success" if ok else "Failure")
        self.result_mark.setText("✓" if ok else "!")
        self.result_mark.setStyleSheet(
            f"background: {OK if ok else DANGER}; color: #ffffff; border-radius: 20px; font-size: 18px; font-weight: 700;"
        )
        if ok:
            self.result_title.setText("Migration complete")
            self.result_text.setText(
                f"{count(len(chosen), 'space')}, {count(sum(s.tabs for s in chosen), 'tab')} and "
                f"{count(sum(s.folders for s in chosen), 'folder')} are in Zen. Open Zen to see them."
            )
        else:
            self.result_title.setText("Migration stopped")
            reason = message if message.endswith(".") else f"{message}."
            backups = " Backups of changed files are in the Zen profile." if self.values["create_backups"] else ""
            self.result_text.setText(reason + backups)
            self.log.setVisible(True)
            self.log_toggle.setText("Hide log")
        restyle(self.result_card)
        self.result_card.setVisible(True)
        self.refresh()


def main() -> int:
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
