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
from .rendering_config import cfg
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
        self._cached_bg: QPixmap | None = None
        self._cached_pixmap: QPixmap | None = None
        self._cache_dirty: bool = True

        # --- incremental preview state ---
        self._preview_pix: QPixmap | None = None
        self._preview_rendered_count: int = 0

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
        self._cached_bg = None
        self._invalidate_cache()
        self.update()

    def clear_background(self) -> None:
        self._background = None
        self._cached_bg = None
        self._invalidate_cache()
        self.update()

    def release_input(self) -> None:
        """Release any active mouse grab.

        Called from the overlay when the user exits drawing mode — ensures
        we don't leave the mouse captured if Escape is pressed mid-drag."""
        self.releaseMouse()

    def undo(self) -> None:
        self.stroke_manager.undo()
        self._reset_preview_state()
        self.update()

    def redo(self) -> None:
        self.stroke_manager.redo()
        self._reset_preview_state()
        self.update()

    def clear_all(self) -> None:
        self.stroke_manager.clear()
        self._reset_preview_state()
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
            self._reset_preview_state()
            if self.current_tool == ToolType.ERASER:
                self._init_eraser_preview()
            self.update()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._mouse_pos = event.position()  # always track for eraser preview
        if event.buttons() & Qt.LeftButton:
            self.stroke_manager.add_point(event.position())
            self._update_preview_incremental()
            self.update()
            event.accept()
        elif self.current_tool == ToolType.ERASER:
            # Repaint to update eraser cursor preview even when not drawing
            self.update()
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self.releaseMouse()  # release mouse capture
            # Finalize the preview into the cache (incremental — single stroke)
            preview = self.stroke_manager.preview_stroke()
            if preview is not None and len(preview.points) >= 2:
                self._finalize_preview_to_cache()
            self.stroke_manager.end_stroke()
            self._reset_preview_state()
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
            if (self._cached_bg is None
                    or self._cached_bg.size() != self.size()):
                self._cached_bg = self._background.scaled(
                    self.size(),
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation,
                )
            # Composite screenshot on top of the alpha=3 fill so that
            # erasing strokes reveals the screenshot, not desktop.
            painter.fillRect(self.rect(), QColor(0, 0, 0, 3))
            painter.drawPixmap(0, 0, self._cached_bg)
        else:
            self._cached_bg = None
            painter.fillRect(self.rect(), QColor(0, 0, 0, 3))

        # Check if there is an active eraser preview — if so, Layer 2
        # must be skipped so the cached strokes are not drawn twice
        # (once here and once inside the eraser preview pixmap).
        preview = self.stroke_manager.preview_stroke()
        is_erasing = preview is not None and preview.tool == ToolType.ERASER

        # ── Layer 2: Cached completed strokes ────────────────────────
        # Completed strokes are rendered once into a cache pixmap and
        # reused across frames.  The cache is rebuilt only when strokes
        # change (stroke-end / undo / redo / clear / resize), NOT on
        # every mouse-move.  This keeps painting fast even with hundreds
        # of strokes.
        #
        # NOTE: When *is_erasing* is true this layer is skipped entirely;
        # the cached strokes are only shown via the eraser preview in
        # Layer 3 below, preventing the double-draw that made highlighters
        # appear abnormally bright and the eraser effect invisible.
        if (
            self._cache_dirty
            or self._cached_pixmap is None
            or self._cached_pixmap.size() != self.size()
        ):
            self._cached_pixmap = QPixmap(self.size())
            self._cached_pixmap.fill(Qt.transparent)
            cp = QPainter(self._cached_pixmap)
            cp.setRenderHint(QPainter.Antialiasing)
            for stroke in self.stroke_manager.get_strokes():
                render_stroke(cp, stroke, is_preview=False)
            cp.end()
            self._cache_dirty = False

        if not is_erasing:
            painter.drawPixmap(0, 0, self._cached_pixmap)

        # ── Layer 3: Preview stroke (in-progress) ─────────────────────
        # Instead of re-rendering the entire current stroke from scratch
        # every frame, we accumulate it into _preview_pix incrementally
        # inside _update_preview_incremental().  Here we just blit it —
        # O(1) regardless of stroke length.
        #
        # Eraser preview (is_erasing == True):
        #   Layer 2 is skipped — the cached completed strokes are only
        #   shown here, copied into _preview_pix on mouse press
        #   (_init_eraser_preview) with the eraser applied incrementally
        #   on each mouse move.  The result is drawn at FULL opacity so
        #   the user sees the actual erased state in real-time.
        #
        # All other tools:
        #   The preview is composited at *cfg.preview_opacity*.
        if preview is not None and self._preview_pix is not None:
            if is_erasing:
                painter.drawPixmap(0, 0, self._preview_pix)
            elif self._preview_rendered_count > 0:
                painter.save()
                painter.setOpacity(cfg.preview_opacity)
                painter.drawPixmap(0, 0, self._preview_pix)
                painter.restore()

        # ── Eraser cursor preview ────────────────────────────────────
        if self.current_tool == ToolType.ERASER and self._mouse_pos is not None:
            pen = QPen(QColor(128, 128, 128, 180), 1.5, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            r = self._eraser_width / 2.0
            painter.drawEllipse(self._mouse_pos, r, r)

        painter.end()

    # ------------------------------------------------------------------
    # Incremental preview rendering (Fix 2/4)
    # ------------------------------------------------------------------

    def _reset_preview_state(self) -> None:
        """Clear the incremental preview for a new stroke."""
        self._preview_rendered_count = 0
        if self._preview_pix is not None:
            self._preview_pix.fill(Qt.transparent)

    def _init_eraser_preview(self) -> None:
        """Seed the preview pixmap with cached strokes for eraser compositing."""
        if (self._preview_pix is None
                or self._preview_pix.size() != self.size()):
            self._preview_pix = QPixmap(self.size())
        self._preview_pix.fill(Qt.transparent)
        if self._cached_pixmap is not None:
            pp = QPainter(self._preview_pix)
            pp.drawPixmap(0, 0, self._cached_pixmap)
            pp.end()
        self._preview_rendered_count = 0

    def _update_preview_incremental(self) -> None:
        """Render only newly-added segments of the current stroke.

        StrokeManager densifies on the fly, so the points in *stroke.points*
        are already smooth enough to be drawn with plain ``drawLine`` — we
        skip the (expensive) second Catmull-Rom pass that ``render_stroke()``
        applies.  The result is O(1) per-frame rendering cost regardless of
        how long the current stroke has grown.
        """
        preview = self.stroke_manager.preview_stroke()
        if preview is None:
            return

        pts = preview.points
        wids = preview.point_widths
        n = len(pts)

        # Nothing new to render?
        if n < 2 or n <= self._preview_rendered_count:
            return

        # Start one point before the un-rendered region so the connecting
        # segment is always drawn (important when densification inserted
        # extra points at the previous boundary).
        start = max(0, self._preview_rendered_count - 1)

        # Ensure the preview pixmap exists and is the right size.
        if (self._preview_pix is None
                or self._preview_pix.size() != self.size()):
            self._preview_pix = QPixmap(self.size())
            self._preview_pix.fill(Qt.transparent)

        pp = QPainter(self._preview_pix)
        pp.setRenderHint(QPainter.Antialiasing)
        pp.setBrush(Qt.NoBrush)

        if preview.tool == ToolType.ERASER:
            # Eraser: use CompositionMode_Clear (idempotent at overlaps)
            pp.setCompositionMode(QPainter.CompositionMode_Clear)
            pen = QPen(
                QColor(0, 0, 0, 0), preview.width,
                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin,
            )
            pp.setPen(pen)
            for i in range(start, n - 1):
                pp.drawLine(pts[i], pts[i + 1])
            pp.setCompositionMode(QPainter.CompositionMode_SourceOver)
        else:
            color = QColor(preview.color)
            alpha = int(255 * preview.opacity)
            color.setAlpha(alpha)

            is_variable = (
                wids is not None
                and len(wids) == n
                and preview.tool in {ToolType.PEN, ToolType.PEN2, ToolType.PEN3}
            )

            if is_variable:
                # Variable width: one pen per segment
                for i in range(start, n - 1):
                    seg_w = max((wids[i] + wids[i + 1]) / 2.0,
                                cfg.min_segment_width)
                    pen = QPen(color, seg_w, Qt.SolidLine,
                               Qt.RoundCap, Qt.RoundJoin)
                    pp.setPen(pen)
                    pp.drawLine(pts[i], pts[i + 1])
            else:
                # Uniform width: single pen for all new segments
                if preview.tool == ToolType.HIGHLIGHTER:
                    ha = int(255 * preview.opacity * cfg.highlighter_opacity_scale)
                    color.setAlpha(ha)
                    pen_w = preview.width * cfg.highlighter_width_scale
                else:
                    pen_w = preview.width
                pen = QPen(color, pen_w, Qt.SolidLine,
                           Qt.RoundCap, Qt.RoundJoin)
                pp.setPen(pen)
                for i in range(start, n - 1):
                    pp.drawLine(pts[i], pts[i + 1])

        pp.end()
        self._preview_rendered_count = n

    def _finalize_preview_to_cache(self) -> None:
        """Paint the just-completed stroke onto ``_cached_pixmap``.

        This is an *incremental* cache update — only the one new stroke is
        rendered, not all strokes.  The full rebuild (undo / redo / clear /
        resize) still happens via ``_cache_dirty``.
        """
        preview = self.stroke_manager.preview_stroke()
        if preview is None:
            return

        if (self._cached_pixmap is None
                or self._cached_pixmap.size() != self.size()):
            self._cached_pixmap = QPixmap(self.size())
            self._cached_pixmap.fill(Qt.transparent)

        cp = QPainter(self._cached_pixmap)
        cp.setRenderHint(QPainter.Antialiasing)
        render_stroke(cp, preview, is_preview=False)
        cp.end()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _invalidate_cache(self) -> None:
        self._cache_dirty = True
        self.update()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._cached_bg = None
        self._preview_pix = None
        self._invalidate_cache()
