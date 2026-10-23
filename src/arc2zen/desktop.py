#!/usr/bin/env python3
"""Simple cross-platform desktop UI for Arc to Zen migration."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from ctypes.util import find_library

# PyInstaller windowed builds on Windows can start with no console streams.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

try:
    import psutil
    from PySide6.QtCore import QThread, Qt, Signal
    from PySide6.QtGui import QColor, QIcon, QPalette
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFileDialog,
        QFrame,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    print("Missing desktop dependency:", exc)
    print('Install dependencies with: pip install -e ".[desktop]"')
    raise

from .migration import MigrationOptions, list_arc_spaces, run_migration
from .profile_paths import (
    discover_arc_profiles,
    discover_zen_profiles,
    is_arc_profile,
    is_zen_profile_in_use,
    resolve_zen_profile,
    zen_profile_lock_files,
)


APP_STYLESHEET = """
QWidget {
    color: #111827;
}

QMainWindow {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #e9edf2, stop:0.18 #f4f6f8, stop:1 #f6f7f9);
    color: #111827;
}

QWidget#Root {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #e9edf2, stop:0.18 #f4f6f8, stop:1 #f6f7f9);
    color: #111827;
}

QFrame#CardPanel,
QFrame#DangerPanel {
    border-radius: 12px;
    border: 1px solid #d9dde5;
}

QFrame#CardPanel {
    background: #ffffff;
}

QFrame#DangerPanel {
    background: #fff1f1;
    border-color: #efc2c2;
}

QLabel[role="cardTitle"] {
    color: #111827;
    font-size: 15px;
    font-weight: 650;
}

QLabel {
    color: #374151;
}

QComboBox,
QLineEdit,
QListWidget,
QTextEdit {
    background: #ffffff;
    border: 1px solid #cfd5df;
    border-radius: 8px;
    color: #111827;
    padding: 7px 10px;
    selection-background-color: #dbeafe;
    selection-color: #111827;
}

QComboBox:focus,
QLineEdit:focus,
QListWidget:focus,
QTextEdit:focus {
    border-color: #3b82f6;
}

QComboBox QAbstractItemView {
    background: #ffffff;
    color: #111827;
    border: 1px solid #cfd5df;
    selection-background-color: #dbeafe;
    selection-color: #111827;
}

QCheckBox {
    spacing: 8px;
    color: #1f2937;
}

QCheckBox:disabled {
    color: #6b7280;
}

QPushButton {
    background: #ffffff;
    border: 1px solid #cfd5df;
    border-radius: 8px;
    color: #111827;
    padding: 8px 14px;
}

QPushButton:hover {
    background: #f3f4f6;
}

QPushButton:pressed {
    background: #e5e7eb;
}

QPushButton:disabled {
    color: #9ca3af;
    background: #f3f4f6;
}

QPushButton#PrimaryButton {
    background: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#PrimaryButton:hover {
    background: #1d4ed8;
}

QProgressBar {
    background: #e5e7eb;
    border: 0;
    border-radius: 6px;
    color: #111827;
    height: 10px;
    text-align: center;
}

QProgressBar::chunk {
    background: #2563eb;
    border-radius: 6px;
}

QTextEdit {
    font-family: "SF Mono", Menlo, Monaco, Consolas, "Courier New", monospace;
    font-size: 12px;
}
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
    palette.setColor(QPalette.ColorRole.Window, QColor("#f4f6f8"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#f3f4f6"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#111827"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#2563eb"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#dbeafe"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#111827"))

    disabled_text = QColor("#9ca3af")
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)

    if hasattr(QPalette.ColorRole, "PlaceholderText"):
        palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6b7280"))

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
            0.914,
            0.929,
            0.949,
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker: MigrationWorker | None = None
        self.setWindowTitle("Arc to Zen")
        self.setWindowIcon(QIcon(str(resource_path("assets", "app-icon.png"))))
        self.resize(900, 720)

        self.arc_combo = self._profile_combo(discover_arc_profiles())
        self.zen_combo = self._profile_combo(discover_zen_profiles())

        self.spaces_list = QListWidget()
        self.spaces_list.setMaximumHeight(140)
        self.spaces_hint = QLabel()
        self.spaces_hint.setWordWrap(True)
        self.spaces_all_button = QPushButton("All")
        self.spaces_all_button.clicked.connect(lambda: self.set_all_spaces_checked(True))
        self.spaces_none_button = QPushButton("None")
        self.spaces_none_button.clicked.connect(lambda: self.set_all_spaces_checked(False))

        self.core_check = QCheckBox("Workspaces, pinned tabs, temporary tabs, folders, and Essentials")
        self.core_check.setChecked(True)
        self.core_check.setEnabled(False)

        self.repair_tabs_check = QCheckBox("Repair tabs with invalid URLs")
        self.repair_tabs_check.setChecked(True)
        self.repair_tabs_check.setToolTip("Replaces URLs Zen cannot parse (e.g. bad punycode hosts) with about:blank; such tabs break Zen's menus.")
        self.favicons_check = QCheckBox("Favicons")
        self.favicons_check.setChecked(True)
        self.folder_states_check = QCheckBox("Pinned-folder open/closed state")
        self.folder_states_check.setChecked(True)
        self.workspace_icons_check = QCheckBox("Workspace icons")
        self.workspace_icons_check.setChecked(True)
        self.workspace_themes_check = QCheckBox("Workspace colors/themes")
        self.workspace_themes_check.setChecked(True)
        self.default_theme_check = QCheckBox("Arc's default colors for spaces without a theme")
        self.default_theme_check.setChecked(True)
        self.default_theme_check.setToolTip("Spaces that use Arc's default look get its pink-to-lavender gradient instead of Zen's default.")
        self.workspace_themes_check.toggled.connect(self.default_theme_check.setEnabled)
        self.containers_check = QCheckBox("Arc profiles as Zen containers")
        self.containers_check.setChecked(True)
        self.containers_check.setToolTip("Creates a Zen container per Arc profile and opens each migrated workspace in it.")
        self.cookies_check = QCheckBox("Cookies of the selected profiles (stay signed in)")
        self.cookies_check.setChecked(True)
        self.local_storage_check = QCheckBox("Site localStorage of the selected profiles")
        self.local_storage_check.setChecked(True)
        self.local_storage_check.setToolTip("Copies sites' localStorage (settings, some sign-ins) into the matching Zen containers. IndexedDB is not copied.")
        self.passwords_check = QCheckBox("Passwords of the selected profiles")
        self.passwords_check.setChecked(True)
        self.passwords_check.setToolTip("Adds Arc passwords to Zen's password manager; Zen starts briefly in the background with the target profile.")
        self.cookies_check.setToolTip("Copies Arc cookies into the matching Zen containers. macOS asks for access to \"Arc Safe Storage\" in the Keychain.")
        self.skip_orphaned_check = QCheckBox('Skip "Orphaned" workspace')
        self.skip_orphaned_check.setChecked(True)
        self.skip_orphaned_check.setToolTip("Avoids creating a synthetic Orphaned workspace; unmatched Essentials are kept in the first workspace.")
        self.backups_check = QCheckBox("Create backups for changed files")
        self.backups_check.setChecked(True)
        self.auto_close_zen_check = QCheckBox("Automatically close Zen if open")
        self.auto_close_zen_check.setChecked(True)
        self.nuke_check = QCheckBox("Clear out Zen profile before migration")
        self.nuke_check.setToolTip("Deletes existing Zen tabs, folders, pins, groups, closed-tab state, and regular bookmarks before importing.")

        self.progress = QProgressBar()
        self.progress.setMinimum(0)
        self.progress.setValue(0)
        self.log = QTextEdit()
        self.log.setReadOnly(True)

        self.run_button = QPushButton("Start Migration")
        self.run_button.setObjectName("PrimaryButton")
        self.run_button.clicked.connect(self.start_migration)

        self._build_ui()

        self.arc_combo.currentTextChanged.connect(self.reload_spaces)
        self.skip_orphaned_check.toggled.connect(self.reload_spaces)
        self.reload_spaces()

    def _profile_combo(self, profiles: list[Path]) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        for profile in profiles:
            combo.addItem(format_path(profile))
        return combo

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("Root")
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        profile_card, profile_body = self._card("Profiles")
        profile_body.addWidget(self._path_row("Source: Arc data folder", self.arc_combo, self.browse_arc))
        profile_body.addWidget(self._path_row("Target: Zen profile", self.zen_combo, self.browse_zen))
        layout.addWidget(profile_card)

        spaces_card, spaces_body = self._card("Spaces")
        spaces_buttons = QHBoxLayout()
        spaces_buttons.setContentsMargins(0, 0, 0, 0)
        spaces_buttons.addWidget(self.spaces_hint, stretch=1)
        spaces_buttons.addWidget(self.spaces_all_button)
        spaces_buttons.addWidget(self.spaces_none_button)
        spaces_body.addLayout(spaces_buttons)
        spaces_body.addWidget(self.spaces_list)
        layout.addWidget(spaces_card)

        options_row = QWidget()
        options_row_layout = QHBoxLayout(options_row)
        options_row_layout.setContentsMargins(0, 0, 0, 0)
        options_row_layout.setSpacing(14)

        options_card, options_layout = self._card("Choose what to migrate")
        for checkbox in (
            self.core_check,
            self.repair_tabs_check,
            self.favicons_check,
            self.folder_states_check,
            self.workspace_icons_check,
            self.workspace_themes_check,
            self.default_theme_check,
            self.containers_check,
            self.cookies_check,
            self.local_storage_check,
            self.passwords_check,
        ):
            options_layout.addWidget(checkbox)

        settings_card, settings_layout = self._card("Options")
        for checkbox in (
            self.skip_orphaned_check,
            self.backups_check,
            self.auto_close_zen_check,
        ):
            settings_layout.addWidget(checkbox)

        options_row_layout.addWidget(options_card, stretch=1)
        options_row_layout.addWidget(settings_card, stretch=1)
        layout.addWidget(options_row)

        danger_card, danger_layout = self._card("Danger Zone", danger=True)
        danger_layout.addWidget(self.nuke_check)
        layout.addWidget(danger_card)

        layout.addWidget(self.progress)
        layout.addWidget(self.log, stretch=1)
        layout.addWidget(self.run_button, alignment=Qt.AlignRight)

        self.setCentralWidget(root)

    def apply_platform_window_polish(self) -> None:
        polish_macos_window(self)

    def _card(self, title: str, danger: bool = False) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setObjectName("DangerPanel" if danger else "CardPanel")
        frame.setFrameShape(QFrame.NoFrame)

        outer_layout = QVBoxLayout(frame)
        outer_layout.setContentsMargins(18, 16, 18, 16)
        outer_layout.setSpacing(12)

        title_label = QLabel(title)
        title_label.setProperty("role", "cardTitle")
        outer_layout.addWidget(title_label)

        body_layout = QVBoxLayout()
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(8)
        outer_layout.addLayout(body_layout)
        outer_layout.addStretch(1)

        return frame, body_layout

    def _path_row(self, label_text: str, combo: QComboBox, browse_callback) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        label = QLabel(label_text)
        label.setMinimumWidth(150)
        label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(browse_callback)

        layout.addWidget(label)
        layout.addWidget(combo, stretch=1)
        layout.addWidget(browse_button)
        return row

    def reload_spaces(self, *_):
        """Fill the space list from the selected Arc folder, keeping unchecked spaces unchecked."""
        unchecked = {
            self.spaces_list.item(row).text()
            for row in range(self.spaces_list.count())
            if self.spaces_list.item(row).checkState() != Qt.Checked
        }
        self.spaces_list.clear()

        arc_profile = Path(self.arc_combo.currentText()).expanduser()
        names = []
        if is_arc_profile(arc_profile):
            try:
                names = list_arc_spaces(arc_profile, include_orphaned=not self.skip_orphaned_check.isChecked())
            except Exception as exc:
                self.spaces_hint.setText(f"Could not read Arc spaces: {exc}")
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked if name in unchecked else Qt.Checked)
            self.spaces_list.addItem(item)

        if names:
            self.spaces_hint.setText("Unchecked spaces are skipped; their Zen workspaces stay as they are.")
        elif not self.spaces_hint.text().startswith("Could not"):
            self.spaces_hint.setText("Choose an Arc data folder to list its spaces.")
        has_spaces = bool(names)
        self.spaces_all_button.setEnabled(has_spaces)
        self.spaces_none_button.setEnabled(has_spaces)

    def set_all_spaces_checked(self, checked: bool):
        state = Qt.Checked if checked else Qt.Unchecked
        for row in range(self.spaces_list.count()):
            self.spaces_list.item(row).setCheckState(state)

    def selected_spaces(self) -> tuple[str, ...] | None:
        """Return checked space names, or None when every listed space is checked."""
        items = [self.spaces_list.item(row) for row in range(self.spaces_list.count())]
        checked = tuple(item.text() for item in items if item.checkState() == Qt.Checked)
        if len(checked) == len(items):
            return None
        if not checked:
            raise ValueError("Select at least one Arc space to migrate.")
        return checked

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

    def selected_config(self) -> MigrationOptions:
        arc_profile = Path(self.arc_combo.currentText()).expanduser()
        if not is_arc_profile(arc_profile):
            raise ValueError(f"Arc profile must contain a valid StorableSidebar.json:\n{arc_profile}")

        zen_profile = resolve_zen_profile(self.zen_combo.currentText())
        return MigrationOptions(
            arc_profile=arc_profile,
            zen_profile=zen_profile,
            nuke=self.nuke_check.isChecked(),
            favicons=self.favicons_check.isChecked(),
            folder_states=self.folder_states_check.isChecked(),
            workspace_icons=self.workspace_icons_check.isChecked(),
            workspace_themes=self.workspace_themes_check.isChecked(),
            default_theme=self.default_theme_check.isChecked(),
            containers=self.containers_check.isChecked(),
            cookies=self.cookies_check.isChecked(),
            passwords=self.passwords_check.isChecked(),
            local_storage=self.local_storage_check.isChecked(),
            repair_tabs=self.repair_tabs_check.isChecked(),
            skip_orphaned=self.skip_orphaned_check.isChecked(),
            create_backups=self.backups_check.isChecked(),
            auto_close_zen=self.auto_close_zen_check.isChecked(),
            spaces=self.selected_spaces(),
        )

    def start_migration(self):
        try:
            config = self.selected_config()
        except Exception as exc:
            QMessageBox.critical(self, "Invalid selection", str(exc))
            return

        if not self.confirm_operation(config):
            return

        if not self.ensure_zen_closed(config):
            return

        self.log.clear()
        self.log.append("Zen is closed. Starting migration.")
        self.progress.setValue(0)
        self.run_button.setEnabled(False)

        self.worker = MigrationWorker(config)
        self.worker.line.connect(self.append_log)
        self.worker.step.connect(self.update_step)
        self.worker.done.connect(self.finish_migration)
        self.worker.start()

    def confirm_operation(self, config: MigrationOptions) -> bool:
        icon = QMessageBox.Warning if config.nuke else QMessageBox.Question
        response = QMessageBox(
            icon,
            "Confirm migration",
            "Are you sure you want to start the migration?\n\n"
            + (
                "Spaces: all"
                if config.spaces is None
                else "Spaces: " + ", ".join(config.spaces) + "\nOther Zen workspaces are kept."
            ),
            QMessageBox.Cancel | QMessageBox.Ok,
            self,
        )
        response.setDefaultButton(QMessageBox.Cancel if config.nuke else QMessageBox.Ok)
        return response.exec() == QMessageBox.Ok

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

    def update_step(self, current: int, total: int, title: str):
        self.progress.setMaximum(total)
        self.progress.setValue(current - 1)

    def finish_migration(self, ok: bool, message: str):
        self.progress.setValue(self.progress.maximum())
        self.run_button.setEnabled(True)
        if ok:
            self.log.append("\nMigration finished successfully.")
            QMessageBox.information(self, "Migration complete", message)
        else:
            self.log.append(f"\nMigration failed: {message}")
            QMessageBox.critical(self, "Migration failed", message)


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
