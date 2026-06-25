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


    class _Win32HitTestFilter(QAbstractNativeEventFilter):
        """Override WM_NCHITTEST so the overlay reliably receives mouse events
        in drawing mode, regardless of layered-window alpha or Qt's
        WA_TransparentForMouseEvents implementation quirks."""

        def __init__(self, overlay: "OverlayWindow"):
            super().__init__()
            self._overlay = overlay

        def nativeEventFilter(self, eventType, message):
            if eventType != b"windows_generic_MSG":
                return False, 0
            try:
                msg = wintypes.MSG.from_address(message.__int__())
                # WM_NCHITTEST == 0x0084
                if msg.message != 0x0084:
                    return False, 0
                if int(msg.hwnd) != int(self._overlay.winId()):
                    return False, 0
                # HTCLIENT = 1     → the window receives the mouse event
                # HTTRANSPARENT = -1 → the event passes through to the window below
                return True, 1 if self._overlay._drawing_mode else -1
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

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Default: mouse passthrough (hidden mode)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.show()
        self.raise_()
        self.activateWindow()

    def exit_drawing_mode(self) -> None:
        """Hide the overlay and release mouse events."""
        self._drawing_mode = False
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

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
        """Re-apply drawing mode state after window re-show."""
        if event.type() == QEvent.WindowStateChange and self._drawing_mode:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        super().changeEvent(event)
