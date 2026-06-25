from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QEvent, QAbstractNativeEventFilter, QCoreApplication
from PySide6.QtGui import QCloseEvent, QScreen
from PySide6.QtWidgets import QWidget

from .canvas import DrawingCanvas


# ---------------------------------------------------------------------------
# Native event filter for reliable mouse hit-testing on Windows
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    # Win32 constants
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x00000020
    WM_NCHITTEST = 0x0084
    WM_SETCURSOR = 0x0020
    HTCLIENT = 1
    HTTRANSPARENT = -1


    class _Win32HitTestFilter(QAbstractNativeEventFilter):
        """Intercept WM_NCHITTEST and WM_SETCURSOR so the overlay reliably
        receives mouse events and shows the correct cursor in drawing mode,
        regardless of layered-window alpha or Qt's WA_TransparentForMouseEvents
        implementation quirks."""

        def __init__(self, overlay: "OverlayWindow"):
            super().__init__()
            self._overlay = overlay

        def nativeEventFilter(self, eventType, message):
            if eventType != b"windows_generic_MSG":
                return False, 0
            try:
                msg = wintypes.MSG.from_address(message.__int__())

                if msg.message == WM_NCHITTEST:
                    if int(msg.hwnd) != int(self._overlay.winId()):
                        return False, 0
                    # HTCLIENT = 1       → the window receives the mouse event
                    # HTTRANSPARENT = -1 → the event passes through
                    # Passthrough mode overrides drawing mode so events reach
                    # the desktop even while the overlay stays visible.
                    if self._overlay._drawing_mode and not self._overlay._passthrough_mode:
                        return True, HTCLIENT
                    return True, HTTRANSPARENT

                if msg.message == WM_SETCURSOR:
                    if int(msg.hwnd) != int(self._overlay.winId()):
                        return False, 0
                    if self._overlay._drawing_mode and not self._overlay._passthrough_mode:
                        # Force crosshair cursor so it never becomes I-beam
                        ctypes.windll.user32.SetCursor(
                            ctypes.windll.user32.LoadCursorW(None, 32515)  # IDC_CROSS
                        )
                        return True, 0  # Handled — stop default processing
                    return False, 0

                return False, 0
            except (ValueError, TypeError, AttributeError):
                return False, 0
else:
    _Win32HitTestFilter = None  # type: ignore


class OverlayWindow(QWidget):
    """Fullscreen transparent window that hosts the drawing canvas."""

    def __init__(self, screen: QScreen, parent: QWidget | None = None):
        super().__init__(parent)
        self._screen = screen
        self._drawing_mode = False
        self._passthrough_mode = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # NOTE: We do NOT use WA_TransparentForMouseEvents here because its
        # underlying WS_EX_TRANSPARENT style toggling is unreliable on Windows.
        # Instead we manage hit-testing purely via the native event filter
        # (_Win32HitTestFilter) below, and explicitly set/clear WS_EX_TRANSPARENT
        # via the Win32 API.
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # Position on the given screen
        geo = screen.geometry()
        self.setGeometry(geo)

        # Create the canvas
        self.canvas = DrawingCanvas(self)
        self.canvas.setGeometry(self.rect())

        # Install native event filter for reliable hit-testing on Windows
        self._hit_test_filter: QAbstractNativeEventFilter | None = None
        if _Win32HitTestFilter is not None:
            self._hit_test_filter = _Win32HitTestFilter(self)
            app = QCoreApplication.instance()
            if app is not None:
                app.installNativeEventFilter(self._hit_test_filter)

        # Start with WS_EX_TRANSPARENT so the hidden-but-visible window does
        # not interfere with desktop interaction.
        self._set_ws_ex_transparent(True)

        # Hide by default
        self.hide()

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    @property
    def drawing_mode(self) -> bool:
        return self._drawing_mode

    def enter_drawing_mode(self) -> None:
        """Show the overlay and capture mouse events."""
        self._drawing_mode = True
        self._set_ws_ex_transparent(False)
        # Cursor is managed by DrawingCanvas.set_tool() — don't override it
        # here so the MOUSE tool can keep the arrow cursor.
        self.show()
        self.raise_()
        self.activateWindow()

    def set_passthrough(self, enabled: bool) -> None:
        """Toggle mouse-event passthrough without hiding the overlay.

        When enabled, mouse events pass through to the desktop while the
        overlay stays visible — useful for the MOUSE tool.  The native
        event filter reads ``_passthrough_mode`` to decide WM_NCHITTEST
        and WM_SETCURSOR responses.
        """
        self._passthrough_mode = enabled
        self._set_ws_ex_transparent(enabled)

    def exit_drawing_mode(self) -> None:
        """Hide the overlay and release mouse events."""
        self._drawing_mode = False
        self._set_ws_ex_transparent(True)   # re-add WS_EX_TRANSPARENT
        self.canvas.release_input()
        self.canvas.unsetCursor()
        self.hide()

    # ------------------------------------------------------------------
    # Native window helpers
    # ------------------------------------------------------------------

    def _set_ws_ex_transparent(self, transparent: bool) -> None:
        """Directly add or remove the WS_EX_TRANSPARENT extended style.

        Qt's ``WA_TransparentForMouseEvents`` attribute *should* do this, but
        on Windows it is unreliable for layered windows — the style change
        sometimes does not take effect.  We bypass Qt and write the style
        ourselves.
        """
        if sys.platform != "win32":
            return
        hwnd = int(self.winId())
        current = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if transparent:
            new_style = current | WS_EX_TRANSPARENT
        else:
            new_style = current & ~WS_EX_TRANSPARENT
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        """Keep the canvas sized to the overlay."""
        super().resizeEvent(event)
        self.canvas.setGeometry(self.rect())

    def cleanup(self) -> None:
        """Remove the native event filter before the overlay is destroyed."""
        if self._hit_test_filter is not None:
            app = QCoreApplication.instance()
            if app is not None:
                app.removeNativeEventFilter(self._hit_test_filter)
            self._hit_test_filter = None

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Prevent accidental close (Alt+F4)."""
        if self._drawing_mode:
            # In drawing mode, just hide (the app will handle it)
            self.exit_drawing_mode()
            event.ignore()
        else:
            # Allow close only during app shutdown
            event.ignore()

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        """Re-apply mouse-transparent state after window re-show."""
        if event.type() == QEvent.WindowStateChange and self._drawing_mode:
            self._set_ws_ex_transparent(False)
        super().changeEvent(event)
