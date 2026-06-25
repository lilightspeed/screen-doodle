from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication, QPixmap, QImage, QScreen


def capture_screen(screen: QScreen) -> QPixmap | None:
    """Capture the contents of *screen* as a QPixmap.

    Falls back to ``screen.grabWindow(0)`` if PIL is not available.
    """
    try:
        _pil_capture(screen)
    except Exception:
        return _qt_capture(screen)
    return _pil_capture(screen)


def _pil_capture(screen: QScreen) -> QPixmap | None:
    """Capture via Pillow (more reliable on Windows with transparent windows)."""
    from PIL import ImageGrab

    geo = screen.geometry()
    bbox = (geo.x(), geo.y(), geo.x() + geo.width(), geo.y() + geo.height())
    pil_img = ImageGrab.grab(bbox=bbox)
    return _pil_to_qpixmap(pil_img)


def _qt_capture(screen: QScreen) -> QPixmap | None:
    """Qt-native fallback — may capture transparent overlays on some setups."""
    return screen.grabWindow(0)


def _pil_to_qpixmap(pil_img) -> QPixmap:
    """Convert a PIL Image to a QPixmap."""
    # Use RGBX format (32-bit with padding) for reliable conversion
    img_data = pil_img.tobytes("raw", "BGRX")
    qimg = QImage(img_data, pil_img.width, pil_img.height, QImage.Format_RGB32)
    return QPixmap.fromImage(qimg)


def capture_all_screens() -> dict[QScreen, QPixmap]:
    """Capture every screen, returning a mapping."""
    result = {}
    for screen in QGuiApplication.screens():
        pixmap = capture_screen(screen)
        if pixmap is not None:
            result[screen] = pixmap
    return result
