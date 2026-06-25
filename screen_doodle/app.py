from __future__ import annotations

import json
import os

from PySide6.QtCore import Qt, QObject, QStandardPaths, Signal, QTimer
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QSystemTrayIcon,
)

from .models import ToolType
from .overlay import OverlayWindow
from .toolbar import ToolBarWindow

import keyboard


class ScreenDoodleApp(QObject):
    """Application coordinator — hotkeys, windows, wiring."""

    # Cross-thread signals emitted by keyboard callbacks
    toggle_requested = Signal()
    exit_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()

    SETTINGS_FILE = "settings.json"

    DEFAULTS = {
        "hotkey": "ctrl+shift+d",
        "default_tool": ToolType.PEN.value,
        "pen_color": "#FF0000",
        "pen_width": 3.0,
        "pen2_color": "#0064FF",
        "pen2_width": 3.0,
        "pen3_color": "#00B400",
        "pen3_width": 3.0,
        "highlighter_color": "#FFEE00",
        "highlighter_width": 12.0,
        "eraser_width": 20.0,
        "opacity": 1.0,
        "toolbar_x": None,
        "toolbar_y": None,
    }

    def __init__(self, app: QApplication):
        super().__init__()
        self._app = app
        self._drawing_mode = False
        self._hotkey_ids: dict[str, object] = {}

        # Load settings
        self._settings_path = self._resolve_settings_path()
        self._settings = dict(self.DEFAULTS)
        self._load_settings()

        # Build UI
        self.toolbar = ToolBarWindow()

        # One overlay per screen
        self.overlays: list[OverlayWindow] = []
        for screen in QApplication.screens():
            self._create_overlay(screen)

        # Connect screen hot-plug (connect via instance in PySide6)
        gui_app = QGuiApplication.instance()
        if gui_app is not None:
            gui_app.screenAdded.connect(self._on_screen_added)
            gui_app.screenRemoved.connect(self._on_screen_removed)

        # Wire toolbar → all canvases
        self._wire_toolbar()

        # Wire internal cross-thread signals
        self.toggle_requested.connect(self.toggle_drawing_mode)
        self.exit_requested.connect(self._on_exit_requested)
        self.undo_requested.connect(self._on_undo)
        self.redo_requested.connect(self._on_redo)

        # Set up system tray
        self._setup_tray()

        # Register the permanent toggle hotkey
        self._register_toggle_hotkey()

        # Apply saved settings
        self._apply_settings()

        # Start in hidden mode
        self._drawing_mode = True
        self.toggle_drawing_mode()

    # ------------------------------------------------------------------
    # Overlay lifecycle
    # ------------------------------------------------------------------

    def _create_overlay(self, screen) -> OverlayWindow:
        overlay = OverlayWindow(screen, None)
        self.overlays.append(overlay)
        return overlay

    def _on_screen_added(self, screen) -> None:
        overlay = self._create_overlay(screen)
        if self._drawing_mode:
            overlay.enter_drawing_mode()

    def _on_screen_removed(self, screen) -> None:
        self.overlays = [
            o for o in self.overlays if o._screen != screen
        ]

    # ------------------------------------------------------------------
    # Toolbar wiring
    # ------------------------------------------------------------------

    def _wire_toolbar(self) -> None:
        """Connect each toolbar signal to every overlay's canvas."""
        for overlay in self.overlays:
            canvas = overlay.canvas
            self.toolbar.tool_changed.connect(canvas.set_tool)
            self.toolbar.color_changed.connect(canvas.set_color)
            self.toolbar.width_changed.connect(canvas.set_width)
            self.toolbar.undo_requested.connect(canvas.undo)
            self.toolbar.redo_requested.connect(canvas.redo)
            self.toolbar.clear_requested.connect(canvas.clear_all)
            self.toolbar.eraser_width_changed.connect(canvas.set_eraser_width)

        self.toolbar.hide_requested.connect(self.toggle_drawing_mode)

        # Settings persistence — per-tool settings + tool + eraser
        self.toolbar.tool_settings_changed.connect(self._on_tool_settings_changed)
        self.toolbar.eraser_width_changed.connect(self._on_eraser_width_changed)
        self.toolbar.tool_changed.connect(self._on_tool_changed)

    # ------------------------------------------------------------------
    # Hotkey management
    # ------------------------------------------------------------------

    def _register_toggle_hotkey(self) -> None:
        """Register the always-active toggle hotkey."""
        hotkey = self._settings.get("hotkey", "ctrl+shift+d")
        try:
            keyboard.add_hotkey(hotkey, self.toggle_requested.emit)
        except Exception as exc:
            print(f"[ScreenDoodle] Failed to register hotkey '{hotkey}': {exc}")

    def _register_mode_hotkeys(self) -> None:
        """Register hotkeys that are only active during drawing mode."""
        mode_hotkeys = {
            "esc": (self.exit_requested.emit, {"suppress": True}),
            "ctrl+z": (self.undo_requested.emit, {"suppress": True}),
            "ctrl+y": (self.redo_requested.emit, {"suppress": True}),
        }
        for combo, (callback, kwargs) in mode_hotkeys.items():
            try:
                hid = keyboard.add_hotkey(combo, callback, **kwargs)
                self._hotkey_ids[combo] = hid
            except Exception as exc:
                print(f"[ScreenDoodle] Failed to register hotkey '{combo}': {exc}")

    def _unregister_mode_hotkeys(self) -> None:
        for combo, hid in list(self._hotkey_ids.items()):
            try:
                keyboard.remove_hotkey(hid)
            except Exception:
                pass
        self._hotkey_ids.clear()

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def toggle_drawing_mode(self) -> None:
        if self._drawing_mode:
            self._exit_drawing_mode()
        else:
            self._enter_drawing_mode()

    def _enter_drawing_mode(self) -> None:
        if self._drawing_mode:
            return
        self._drawing_mode = True

        for overlay in self.overlays:
            overlay.enter_drawing_mode()

        self.toolbar.show()
        self.toolbar.raise_()

        self._register_mode_hotkeys()

    def _exit_drawing_mode(self) -> None:
        if not self._drawing_mode:
            return
        self._drawing_mode = False

        self._unregister_mode_hotkeys()

        self.toolbar.hide()
        for overlay in self.overlays:
            overlay.exit_drawing_mode()

    def _on_exit_requested(self) -> None:
        self._exit_drawing_mode()

    # ------------------------------------------------------------------
    # Toolbar action handlers
    # ------------------------------------------------------------------

    def _on_undo(self) -> None:
        # delegate to whichever canvas has mouse focus, or all
        for overlay in self.overlays:
            overlay.canvas.undo()
            break  # only one for now

    def _on_redo(self) -> None:
        for overlay in self.overlays:
            overlay.canvas.redo()
            break

    def _on_quit(self) -> None:
        self._unregister_mode_hotkeys()
        # Remove the toggle hotkey too
        try:
            keyboard.remove_hotkey(self._settings.get("hotkey", "ctrl+shift+d"))
        except Exception:
            pass
        # Clean up overlay native event filters
        for overlay in self.overlays:
            overlay.cleanup()
        self._app.quit()

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _on_tool_settings_changed(self, tool: ToolType, color: QColor, width: float) -> None:
        if tool == ToolType.PEN:
            self._settings["pen_color"] = color.name()
            self._settings["pen_width"] = width
        elif tool == ToolType.PEN2:
            self._settings["pen2_color"] = color.name()
            self._settings["pen2_width"] = width
        elif tool == ToolType.PEN3:
            self._settings["pen3_color"] = color.name()
            self._settings["pen3_width"] = width
        elif tool == ToolType.HIGHLIGHTER:
            self._settings["highlighter_color"] = color.name()
            self._settings["highlighter_width"] = width
        self._save_settings()

    def _on_eraser_width_changed(self, width: float) -> None:
        self._settings["eraser_width"] = width
        self._save_settings()

    def _on_tool_changed(self, tool: ToolType) -> None:
        self._settings["default_tool"] = tool.value
        self._save_settings()

    # ------------------------------------------------------------------
    # System tray
    # ------------------------------------------------------------------

    def _setup_tray(self) -> None:
        icon = self._make_tray_icon()
        self._tray = QSystemTrayIcon(icon, self._app.activeWindow())
        self._tray.setToolTip("Screen Doodle")

        menu = QMenu()
        toggle_action = menu.addAction("Show / Hide  (Ctrl+Shift+D)")
        toggle_action.triggered.connect(self.toggle_drawing_mode)
        menu.addSeparator()
        quit_action = menu.addAction("Exit")
        quit_action.triggered.connect(self._on_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason: int) -> None:
        if reason in (QSystemTrayIcon.DoubleClick, QSystemTrayIcon.Trigger):
            self.toggle_drawing_mode()

    @staticmethod
    def _make_tray_icon() -> QIcon:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setPen(QPen(Qt.white, 2))
        painter.drawLine(2, 14, 14, 2)
        painter.end()
        return QIcon(pixmap)

    # ------------------------------------------------------------------
    # Settings persistence
    # ------------------------------------------------------------------

    def _resolve_settings_path(self) -> str:
        data_dir = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppDataLocation
        )
        return os.path.join(data_dir, self.SETTINGS_FILE)

    def _load_settings(self) -> None:
        try:
            with open(self._settings_path, "r") as f:
                stored = json.load(f)
                self._settings = {**self.DEFAULTS, **stored}
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _save_settings(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._settings_path), exist_ok=True)
            with open(self._settings_path, "w") as f:
                json.dump(self._settings, f, indent=2)
        except OSError as exc:
            print(f"[ScreenDoodle] Failed to save settings: {exc}")

    def _apply_settings(self) -> None:
        pen_color = QColor(self._settings.get("pen_color", "#FF0000"))
        pen_width = self._settings.get("pen_width", 3.0)
        pen2_color = QColor(self._settings.get("pen2_color", "#0064FF"))
        pen2_width = self._settings.get("pen2_width", 3.0)
        pen3_color = QColor(self._settings.get("pen3_color", "#00B400"))
        pen3_width = self._settings.get("pen3_width", 3.0)
        hl_color = QColor(self._settings.get("highlighter_color", "#FFEE00"))
        hl_width = self._settings.get("highlighter_width", 12.0)
        tool_val = self._settings.get("default_tool", ToolType.PEN.value)
        eraser_width = self._settings.get("eraser_width", 20.0)

        self.toolbar.set_tool_settings(ToolType.PEN, pen_color, pen_width)
        self.toolbar.set_tool_settings(ToolType.PEN2, pen2_color, pen2_width)
        self.toolbar.set_tool_settings(ToolType.PEN3, pen3_color, pen3_width)
        self.toolbar.set_tool_settings(ToolType.HIGHLIGHTER, hl_color, hl_width)
        self.toolbar.set_eraser_width(eraser_width)

        try:
            tool = ToolType(tool_val)
        except ValueError:
            tool = ToolType.PEN
        self.toolbar.activate_tool(tool)

        tx = self._settings.get("toolbar_x")
        ty = self._settings.get("toolbar_y")
        if tx is not None and ty is not None:
            self.toolbar.move(int(tx), int(ty))

    def save_toolbar_position(self) -> None:
        pos = self.toolbar.pos()
        self._settings["toolbar_x"] = pos.x()
        self._settings["toolbar_y"] = pos.y()
        self._save_settings()
