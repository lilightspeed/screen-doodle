from __future__ import annotations

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import QWidget

from .models import Stroke, ToolType
from .renderer import render_stroke
from .stroke_manager import StrokeManager


class DrawingCanvas(QWidget):
    """The drawing surface — receives mouse events and paints all strokes."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)

        # --- current tool state ---
        self.stroke_manager = StrokeManager(self)
        self.current_tool: ToolType = ToolType.PEN
        self.current_color: QColor = QColor(255, 0, 0)
        self.current_width: float = 3.0
        self.current_opacity: float = 1.0

        # --- eraser (separate from pen width) ---
        self._eraser_width: float = 20.0
        self._mouse_pos: QPointF | None = None  # for eraser preview

        # --- optional screenshot background ---
        self._background: QPixmap | None = None
        self._cached_pixmap: QPixmap | None = None
        self._cache_dirty: bool = True

        # Rebuild cache when strokes change
        self.stroke_manager.data_changed.connect(self._invalidate_cache)

        # Force a crosshair cursor so the cursor never switches to I-beam
        # when hovering over text in the underlying window.
        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_tool(self, tool: ToolType) -> None:
        self.current_tool = tool
        if tool == ToolType.MOUSE:
            self.setCursor(Qt.ArrowCursor)
        else:
            self.setCursor(Qt.CrossCursor)

    def set_color(self, color: QColor) -> None:
        self.current_color = color

    def set_width(self, width: float) -> None:
        self.current_width = width

    def set_opacity(self, opacity: float) -> None:
        self.current_opacity = opacity

    def set_eraser_width(self, width: float) -> None:
        self._eraser_width = width

    def set_background(self, pixmap: QPixmap) -> None:
        self._background = pixmap
        self._invalidate_cache()
        self.update()

    def clear_background(self) -> None:
        self._background = None
        self._invalidate_cache()
        self.update()

    def release_input(self) -> None:
        """Release any active mouse grab.

        Called from the overlay when the user exits drawing mode — ensures
        we don't leave the mouse captured if Escape is pressed mid-drag."""
        self.releaseMouse()

    def undo(self) -> None:
        self.stroke_manager.undo()
        self.update()

    def redo(self) -> None:
        self.stroke_manager.redo()
        self.update()

    def clear_all(self) -> None:
        self.stroke_manager.clear()
        self.update()

    def get_strokes(self) -> list[Stroke]:
        return self.stroke_manager.get_strokes()

    def get_background(self) -> QPixmap | None:
        return self._background

    def has_strokes(self) -> bool:
        return len(self.stroke_manager.strokes) > 0

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.grabMouse()  # capture all mouse events during drag
            pos = event.position()
            width = self._eraser_width if self.current_tool == ToolType.ERASER else self.current_width
            self.stroke_manager.start_stroke(
                pos,
                self.current_color,
                width,
                self.current_opacity,
                self.current_tool,
            )
            self._cache_dirty = True
            self.update()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._mouse_pos = event.position()  # always track for eraser preview
        if event.buttons() & Qt.LeftButton:
            self.stroke_manager.add_point(event.position())
            self._cache_dirty = True
            self.update()
            event.accept()
        elif self.current_tool == ToolType.ERASER:
            # Repaint to update eraser cursor preview even when not drawing
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.releaseMouse()  # release mouse capture
            self.stroke_manager.end_stroke()
            self._cache_dirty = True
            self.update()
            event.accept()

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        # ── Layer 1: Background ──────────────────────────────────────
        # Always ensure every pixel has alpha >= 3 so Windows layered-window
        # per-pixel hit-testing delivers mouse events.  This layer is drawn
        # FIRST and is never touched by the eraser.

        if self._background is not None:
            scaled = self._background.scaled(
                self.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            # Composite screenshot on top of the alpha=3 fill so that
            # erasing strokes reveals the screenshot, not desktop.
            painter.fillRect(self.rect(), QColor(0, 0, 0, 3))
            painter.drawPixmap(0, 0, scaled)
        else:
            painter.fillRect(self.rect(), QColor(0, 0, 0, 3))

        # ── Layer 2: Strokes ─────────────────────────────────────────
        # Render all strokes onto a temporary pixmap filled with
        # Qt.transparent, then composite it over the background.  This way
        # the eraser (CompositionMode_Clear) only erases the stroke layer,
        # never the background — preserving alpha>0 for hit-testing.
        temp = QPixmap(self.size())
        temp.fill(Qt.transparent)
        temp_painter = QPainter(temp)
        temp_painter.setRenderHint(QPainter.Antialiasing)

        for stroke in self.stroke_manager.get_strokes():
            render_stroke(temp_painter, stroke, is_preview=False)

        preview = self.stroke_manager.preview_stroke()
        if preview is not None:
            render_stroke(temp_painter, preview, is_preview=True)

        temp_painter.end()
        painter.drawPixmap(0, 0, temp)

        # ── Eraser cursor preview ────────────────────────────────────
        if self.current_tool == ToolType.ERASER and self._mouse_pos is not None:
            pen = QPen(QColor(128, 128, 128, 180), 1.5, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            r = self._eraser_width / 2.0
            painter.drawEllipse(self._mouse_pos, r, r)

        painter.end()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _invalidate_cache(self) -> None:
        self._cache_dirty = True
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._invalidate_cache()
