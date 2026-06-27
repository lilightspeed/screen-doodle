from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF, QSize, QRectF
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPainterPath,
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

        # --- selection / move state ---
        self._selection_active: bool = False
        self._selection_polygon: list[QPointF] = []
        self._selected_stroke_indices: set[int] = set()
        self._selected_point_indices: dict[int, set[int]] = {}
        self._lasso_points: list[QPointF] = []

        # Point-based drag state: directly translate selected points
        self._is_dragging_selection: bool = False
        self._drag_start_pos: QPointF | None = None

        # Move undo/redo stacks
        # Each entry: {'indices': {stroke_idx, ...}, 'delta': QPointF}
        self._move_undo_stack: list[dict] = []
        self._move_redo_stack: list[dict] = []

        # Split state: when a crossing stroke is split at the polygon boundary,
        # the original stroke list is saved here so Ctrl+Z can restore it.
        self._pre_split_strokes: list[Stroke] | None = None
        # Number of strokes right after the split — used when restoring
        # _pre_split_strokes to preserve any strokes drawn after the split.
        self._post_split_count: int = 0

        # Rebuild cache when strokes change
        self.stroke_manager.data_changed.connect(self._invalidate_cache)

        # Force a crosshair cursor so the cursor never switches to I-beam
        # when hovering over text in the underlying window.
        self.setCursor(Qt.CrossCursor)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_tool(self, tool: ToolType) -> None:
        # Clear selection if switching away from SELECT tool
        if self.current_tool == ToolType.SELECT and tool != ToolType.SELECT:
            saved_select_active = self._selection_active
            self._clear_selection()
            if saved_select_active:
                self._invalidate_cache()

        self.current_tool = tool
        if tool == ToolType.MOUSE:
            self.setCursor(Qt.ArrowCursor)
        elif tool == ToolType.SELECT:
            if self._selection_active:
                self.setCursor(Qt.SizeAllCursor if self._point_in_polygon(
                    self._mouse_pos or QPointF(0, 0), self._selection_polygon
                ) else Qt.CrossCursor)
            else:
                self.setCursor(Qt.CrossCursor)
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
        # 1. Undo the last committed move
        if self._move_undo_stack:
            data = self._move_undo_stack.pop()
            self._move_redo_stack.append(data)
            self._apply_delta(data['indices'], -data['delta'])
            # Clear selection visual but keep _pre_split_strokes
            self._selection_active = False
            self._selection_polygon.clear()
            self._selected_stroke_indices.clear()
            self._selected_point_indices.clear()
            self._lasso_points.clear()
            self._is_dragging_selection = False
            self._drag_start_pos = None
            self._invalidate_cache()
            self.update()
            return

        # 2. Undo the split (restore pre-split stroke list)
        if self._pre_split_strokes is not None:
            current = self.stroke_manager.strokes
            # Preserve any strokes the user added *after* the split was
            # made — they are at indices >= _post_split_count.
            extra: list[Stroke] = []
            if self._post_split_count < len(current):
                extra = current[self._post_split_count:]
            current.clear()
            current.extend(self._pre_split_strokes)
            current.extend(extra)
            self._pre_split_strokes = None
            self._post_split_count = 0
            self._clear_selection()
            self.stroke_manager.data_changed.emit()
            self._invalidate_cache()
            self.update()
            return

        # 3. Normal stroke_manager undo
        self.stroke_manager.undo()
        self._reset_preview_state()
        self.update()

    def redo(self) -> None:
        # 1. Redo the last committed move
        if self._move_redo_stack:
            data = self._move_redo_stack.pop()
            self._move_undo_stack.append(data)
            self._apply_delta(data['indices'], data['delta'])
            self._selection_active = False
            self._selection_polygon.clear()
            self._selected_stroke_indices.clear()
            self._selected_point_indices.clear()
            self._lasso_points.clear()
            self._is_dragging_selection = False
            self._drag_start_pos = None
            self._invalidate_cache()
            self.update()
            return
        self.stroke_manager.redo()
        self._reset_preview_state()
        self.update()

    def clear_all(self) -> None:
        self._clear_selection()
        self._move_undo_stack.clear()
        self._move_redo_stack.clear()
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
            if self.current_tool == ToolType.SELECT:
                if self._selection_active:
                    if self._point_in_polygon(event.position(), self._selection_polygon):
                        # Start drag — translate points directly
                        self._start_move_drag(event.position())
                    else:
                        # Click outside — clear selection
                        self._clear_selection()
                else:
                    # No active selection — start lasso
                    self.grabMouse()
                    self._lasso_points = [event.position()]
                    self._mouse_pos = event.position()
                self.update()
                event.accept()
                return

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
        if self.current_tool == ToolType.SELECT:
            if self._is_dragging_selection:
                # Translate selected points by frame-to-frame delta
                delta = event.position() - self._mouse_pos
                self._translate_selection(delta)
                self._mouse_pos = event.position()
                self._invalidate_cache()
                event.accept()
                return
            elif event.buttons() & Qt.LeftButton and self._lasso_points:
                self._lasso_points.append(event.position())
                self.update()
                event.accept()
                return
            elif self._selection_active:
                # Update cursor when hovering over selection
                if self._point_in_polygon(event.position(), self._selection_polygon):
                    self.setCursor(Qt.SizeAllCursor)
                else:
                    self.setCursor(Qt.CrossCursor)
                event.accept()

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
            if self.current_tool == ToolType.SELECT:
                if self._is_dragging_selection:
                    self.releaseMouse()
                    self._commit_move()
                    self.update()
                elif self._lasso_points:
                    self.releaseMouse()
                    self._close_lasso()
                event.accept()
                return

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
        ss = cfg.aa_quality
        ss_cache = QSize(self.width() * ss, self.height() * ss)
        if (
            self._cache_dirty
            or self._cached_pixmap is None
            or self._cached_pixmap.size() != ss_cache
        ):
            self._cached_pixmap = QPixmap(ss_cache)
            self._cached_pixmap.fill(Qt.transparent)

            cp = QPainter(self._cached_pixmap)
            if ss > 1:
                cp.scale(ss, ss)
            cp.setRenderHint(QPainter.Antialiasing)

            for stroke in self.stroke_manager.get_strokes():
                render_stroke(cp, stroke, is_preview=False)

            cp.end()

            self._cache_dirty = False

        if not is_erasing:
            painter.drawPixmap(
                self.rect(), self._cached_pixmap, self._cached_pixmap.rect(),
            )

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
                painter.drawPixmap(
                    self.rect(), self._preview_pix, self._preview_pix.rect(),
                )
            elif self._preview_rendered_count > 0:
                painter.save()
                painter.setOpacity(cfg.preview_opacity)
                painter.drawPixmap(
                    self.rect(), self._preview_pix, self._preview_pix.rect(),
                )
                painter.restore()

        # ── Eraser cursor preview ────────────────────────────────────
        if self.current_tool == ToolType.ERASER and self._mouse_pos is not None:
            pen = QPen(QColor(128, 128, 128, 180), 1.5, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            r = self._eraser_width / 2.0
            painter.drawEllipse(self._mouse_pos, r, r)

        # ── Selection visuals ────────────────────────────────────────

        # Live lasso preview while drawing
        if self.current_tool == ToolType.SELECT and self._lasso_points:
            pen = QPen(QColor(100, 100, 220, 180), 1.5, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            path = QPainterPath()
            path.moveTo(self._lasso_points[0])
            for pt in self._lasso_points[1:]:
                path.lineTo(pt)
            painter.drawPath(path)

        # Active selection border + subtle fill
        if self._selection_active and self._selection_polygon:
            spath = QPainterPath()
            spath.moveTo(self._selection_polygon[0])
            for pt in self._selection_polygon[1:]:
                spath.lineTo(pt)
            spath.closeSubpath()

            # Subtle fill (very light blue, semi-transparent)
            painter.setBrush(QColor(100, 150, 255, 20))
            painter.setPen(Qt.NoPen)
            painter.drawPath(spath)

            # Dashed gray border
            pen = QPen(QColor(160, 160, 160, 200), 1.5, Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(spath)

        painter.end()

    # ------------------------------------------------------------------
    # Incremental preview rendering
    # ------------------------------------------------------------------

    def _reset_preview_state(self) -> None:
        """Clear the incremental preview for a new stroke."""
        self._preview_rendered_count = 0
        if self._preview_pix is not None:
            self._preview_pix.fill(Qt.transparent)

    def _init_eraser_preview(self) -> None:
        """Seed the preview pixmap with cached strokes for eraser compositing."""
        ss_prev = QSize(self.width() * cfg.aa_quality, self.height() * cfg.aa_quality)
        if (self._preview_pix is None
                or self._preview_pix.size() != ss_prev):
            self._preview_pix = QPixmap(ss_prev)
        self._preview_pix.fill(Qt.transparent)
        if self._cached_pixmap is not None:
            pp = QPainter(self._preview_pix)
            pp.drawPixmap(0, 0, self._cached_pixmap)
            pp.end()
        self._preview_rendered_count = 0

    def _update_preview_incremental(self) -> None:
        """Render only newly-added segments of the current stroke.

        All tools use raw ``drawLine`` on densified points so the user can
        visually distinguish the ≈3 px straight-segment preview from the
        fully-smoothed final render (Catmull-Rom 12 segments, ≈0.25 px).
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
        ss = cfg.aa_quality
        ss_prev = QSize(self.width() * ss, self.height() * ss)
        if (self._preview_pix is None
                or self._preview_pix.size() != ss_prev):
            self._preview_pix = QPixmap(ss_prev)
            self._preview_pix.fill(Qt.transparent)

        pp = QPainter(self._preview_pix)
        if ss > 1:
            pp.scale(ss, ss)
        if cfg.preview_antialias:
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
                # No Catmull-Rom smoothing during preview — raw densified
                # points are drawn directly so the user can visually tell
                # preview (≈3px segments) from the fully-smoothed final
                # render (CR 12 segments, ≈0.25px).
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

        ss = cfg.aa_quality
        ss_cache = QSize(self.width() * ss, self.height() * ss)
        if (self._cached_pixmap is None
                or self._cached_pixmap.size() != ss_cache):
            self._cached_pixmap = QPixmap(ss_cache)
            self._cached_pixmap.fill(Qt.transparent)

        cp = QPainter(self._cached_pixmap)
        if ss > 1:
            cp.scale(ss, ss)
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
        self._is_dragging_selection = False
        self._invalidate_cache()

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _point_on_polygon_boundary(
        point: QPointF, polygon: list[QPointF], eps: float = 0.5,
    ) -> bool:
        """Return True if *point* is within *eps* of any polygon edge."""
        n = len(polygon)
        for i in range(n):
            p1 = polygon[i]
            p2 = polygon[(i + 1) % n]
            dx = p2.x() - p1.x()
            dy = p2.y() - p1.y()
            seg_sq = dx * dx + dy * dy
            if seg_sq < 1e-12:
                continue
            t = ((point.x() - p1.x()) * dx + (point.y() - p1.y()) * dy) / seg_sq
            t = max(0.0, min(1.0, t))
            cx = p1.x() + t * dx
            cy = p1.y() + t * dy
            if math.hypot(point.x() - cx, point.y() - cy) <= eps:
                return True
        return False

    @staticmethod
    def _point_in_polygon(point: QPointF, polygon: list[QPointF]) -> bool:
        """Ray casting with boundary tolerance for robust classification."""
        # Treat points on or very near the boundary as inside
        if DrawingCanvas._point_on_polygon_boundary(point, polygon, eps=0.5):
            return True
        inside = False
        j = len(polygon) - 1
        for i in range(len(polygon)):
            yi, yj = polygon[i].y(), polygon[j].y()
            if (yi > point.y()) != (yj > point.y()):
                x_intersect = (
                    (polygon[j].x() - polygon[i].x())
                    * (point.y() - yi)
                    / (yj - yi)
                    + polygon[i].x()
                )
                if point.x() < x_intersect:
                    inside = not inside
            j = i
        return inside

    def _close_lasso(self) -> None:
        """Close the lasso into a polygon and find enclosed strokes.

        Strokes that cross the polygon boundary are **split** at the
        boundary so that only the portion inside the polygon can be
        moved without carrying the outside portion along.
        """
        if len(self._lasso_points) < 3:
            self._lasso_points.clear()
            return

        self._selection_polygon = list(self._lasso_points)
        self._lasso_points.clear()

        original_strokes = self.stroke_manager.strokes

        # Save pre-split state for undo
        self._pre_split_strokes = list(original_strokes)

        new_strokes: list[Stroke] = []
        selected_indices: set[int] = set()
        split_happened = False

        for stroke in original_strokes:
            pts = stroke.points
            if not pts:
                new_strokes.append(stroke)
                continue

            # Quick inside/outside/crossing classification
            has_inside = False
            has_outside = False
            for pt in pts:
                if self._point_in_polygon(pt, self._selection_polygon):
                    has_inside = True
                else:
                    has_outside = True
                if has_inside and has_outside:
                    break

            if not has_inside:
                # Fully outside — keep as-is, not selected
                new_strokes.append(stroke)
                continue

            if not has_outside:
                # Fully inside — keep, mark as selected
                new_strokes.append(stroke)
                selected_indices.add(len(new_strokes) - 1)
                continue

            # Crossing the boundary — split at polygon edges
            inside_parts, outside_parts = self._split_stroke_at_polygon(
                stroke, self._selection_polygon,
            )
            split_happened = True

            # Outside portion(s) replace the original position
            for op in outside_parts:
                new_strokes.append(op)

            # Inside portions are appended after outside ones, marked selected
            for ipart in inside_parts:
                new_strokes.append(ipart)
                selected_indices.add(len(new_strokes) - 1)

        if split_happened:
            # Split restructured the stroke list, making any previous
            # move-undo entries' stroke indices invalid — clear them.
            self._move_undo_stack.clear()
            self._move_redo_stack.clear()
        elif self._pre_split_strokes is not None:
            # No split was actually needed — discard saved state
            self._pre_split_strokes = None

        # Update stroke_manager's list
        original_strokes.clear()
        original_strokes.extend(new_strokes)

        # Track how many strokes the list has right after the split so that
        # undo can restore _pre_split_strokes without losing strokes drawn
        # later.
        self._post_split_count = len(new_strokes)

        # Populate selection state
        self._selected_stroke_indices = selected_indices
        self._selected_point_indices.clear()
        for idx in selected_indices:
            if idx < len(new_strokes):
                self._selected_point_indices[idx] = set(
                    range(len(new_strokes[idx].points))
                )

        if not selected_indices:
            self._selection_active = False
            self._selection_polygon.clear()
            self._pre_split_strokes = None
            self._post_split_count = 0
            self.update()
            return

        self._selection_active = True
        self.stroke_manager.data_changed.emit()
        self.update()

    def _clear_selection(self) -> None:
        """Clear the current selection, drag state, and split undo data."""
        self._selection_active = False
        self._selection_polygon.clear()
        self._selected_stroke_indices.clear()
        self._selected_point_indices.clear()
        self._lasso_points.clear()
        self._is_dragging_selection = False
        self._drag_start_pos = None
        self._pre_split_strokes = None
        self._post_split_count = 0
        self.update()

    # ------------------------------------------------------------------
    # Line-polygon intersection & stroke splitting
    # ------------------------------------------------------------------

    @staticmethod
    def _segment_intersection(
        p1: QPointF, p2: QPointF,
        q1: QPointF, q2: QPointF,
    ) -> tuple[float, QPointF] | None:
        """Find the intersection of line segments p1-p2 and q1-q2.

        Returns ``(t, point)`` where *t* in [0, 1] is the parametric
        position along p1-p2, or ``None`` if the segments are parallel
        or do not intersect (excluding shared endpoints on the q segment
        to avoid double-counting at polygon vertices).
        """
        dx1 = p2.x() - p1.x()
        dy1 = p2.y() - p1.y()
        dx2 = q2.x() - q1.x()
        dy2 = q2.y() - q1.y()

        det = dx1 * dy2 - dy1 * dx2
        if abs(det) < 1e-12:
            return None

        t = ((q1.x() - p1.x()) * dy2 - (q1.y() - p1.y()) * dx2) / det
        u = ((q1.x() - p1.x()) * dy1 - (q1.y() - p1.y()) * dx1) / det

        EPS = 1e-9
        # Allow the intersection to be at the p-segment endpoints (t in [0,1])
        # but require it to be strictly BETWEEN q-segment endpoints so that
        # polygon vertices are not double-counted by adjacent edges.
        if t >= -EPS and t <= 1.0 + EPS and u > EPS and u < 1.0 - EPS:
            tc = max(0.0, min(1.0, t))
            return (tc, QPointF(p1.x() + tc * dx1, p1.y() + tc * dy1))
        return None

    def _stroke_segment_intersection(
        self,
        p1: QPointF,
        p2: QPointF,
        polygon: list[QPointF],
    ) -> tuple[float, QPointF] | None:
        """Find the FIRST intersection of segment p1-p2 with *polygon*.

        Returns ``(t, point)`` along p1-p2, or ``None``.
        """
        best_t = 1.0
        best_pt: QPointF | None = None
        n = len(polygon)
        for i in range(n):
            q1 = polygon[i]
            q2 = polygon[(i + 1) % n]
            result = self._segment_intersection(p1, p2, q1, q2)
            if result is not None and result[0] < best_t:
                best_t = result[0]
                best_pt = result[1]

        if best_pt is not None:
            return (best_t, best_pt)
        return None

    def _split_stroke_at_polygon(
        self,
        stroke: Stroke,
        polygon: list[QPointF],
    ) -> tuple[list[Stroke], list[Stroke]]:
        """Split *stroke* at the *polygon* boundary.

        Returns ``(inside_strokes, outside_strokes)`` where each is a
        (possibly empty) list of strokes.  Multiple boundary crossings
        produce multiple inside / outside pieces.
        """
        pts = stroke.points
        n = len(pts)
        if n < 2:
            if n == 1 and self._point_in_polygon(pts[0], polygon):
                return ([stroke], [])
            return ([], [stroke])

        has_widths = (
            stroke.point_widths is not None
            and len(stroke.point_widths) == n
        )
        wids = stroke.point_widths if has_widths else []

        # Classify each point
        inside = [self._point_in_polygon(pt, polygon) for pt in pts]

        all_in = all(inside)
        all_out = not any(inside)
        if all_in:
            return ([stroke], [])
        if all_out:
            return ([], [stroke])

        # Build separate inside/outside sequences for each crossing.
        # Use list-of-lists so multiple boundary crossings each get their
        # own sequence (fixes the "thin thread" / missing-ip bug).
        in_seq_pts: list[list[QPointF]] = []
        in_seq_wids: list[list[float]] = [] if has_widths else None  # type: ignore
        out_seq_pts: list[list[QPointF]] = [[]]
        out_seq_wids: list[list[float]] = [[]] if has_widths else None  # type: ignore

        for i in range(n - 1):
            p1, p2 = pts[i], pts[i + 1]
            in1, in2 = inside[i], inside[i + 1]
            w1 = wids[i] if has_widths else stroke.width
            w2 = wids[i + 1] if has_widths else stroke.width

            if in1 and in2:
                # Both inside — extend the last inside sequence
                if not in_seq_pts:
                    # Started inside (first point was inside) — create seq
                    in_seq_pts.append([p1])
                    if has_widths:
                        in_seq_wids.append([w1])
                in_seq_pts[-1].append(p2)
                if has_widths:
                    in_seq_wids[-1].append(w2)

            elif not in1 and not in2:
                # Both outside — extend the last outside sequence
                out_pts = out_seq_pts[-1]
                if not out_pts:
                    out_pts.append(p1)
                    if has_widths:
                        out_seq_wids[-1].append(w1)
                out_pts.append(p2)
                if has_widths:
                    out_seq_wids[-1].append(w2)

            elif in1 and not in2:
                # Exiting the polygon
                interp = self._stroke_segment_intersection(p1, p2, polygon)
                if interp is not None:
                    t, ip = interp
                    iw = (w1 + t * (w2 - w1)) if has_widths else stroke.width
                    # End the current inside sequence at the boundary
                    if in_seq_pts:
                        in_seq_pts[-1].append(ip)
                        if has_widths:
                            in_seq_wids[-1].append(iw)
                    # Start a new outside sequence from the boundary
                    out_seq_pts.append([QPointF(ip), QPointF(p2)])
                    if has_widths:
                        out_seq_wids.append([iw, w2])
                else:
                    mp = QPointF(
                        (p1.x() + p2.x()) * 0.5, (p1.y() + p2.y()) * 0.5,
                    )
                    mw = (w1 + w2) * 0.5 if has_widths else stroke.width
                    if in_seq_pts:
                        in_seq_pts[-1].append(mp)
                        if has_widths:
                            in_seq_wids[-1].append(mw)
                    out_seq_pts.append([QPointF(mp), QPointF(p2)])
                    if has_widths:
                        out_seq_wids.append([mw, w2])

            else:  # not in1 and in2 — entering the polygon
                interp = self._stroke_segment_intersection(p1, p2, polygon)
                if interp is not None:
                    t, ip = interp
                    iw = (w1 + t * (w2 - w1)) if has_widths else stroke.width
                    # End the current outside sequence at the boundary
                    out_seq_pts[-1].append(ip)
                    if has_widths:
                        out_seq_wids[-1].append(iw)
                    # Start a new inside sequence from the boundary
                    in_seq_pts.append([QPointF(ip), QPointF(p2)])
                    if has_widths:
                        in_seq_wids.append([iw, w2])
                else:
                    mp = QPointF(
                        (p1.x() + p2.x()) * 0.5, (p1.y() + p2.y()) * 0.5,
                    )
                    mw = (w1 + w2) * 0.5 if has_widths else stroke.width
                    out_seq_pts[-1].append(mp)
                    if has_widths:
                        out_seq_wids[-1].append(mw)
                    in_seq_pts.append([QPointF(mp), QPointF(p2)])
                    if has_widths:
                        in_seq_wids.append([mw, w2])

        # Build strokes from inside sequences
        inside_strokes: list[Stroke] = []
        for j, in_pts in enumerate(in_seq_pts):
            if len(in_pts) >= 2:
                inside_strokes.append(Stroke(
                    points=in_pts,
                    color=stroke.color,
                    width=stroke.width,
                    opacity=stroke.opacity,
                    tool=stroke.tool,
                    point_widths=(
                        in_seq_wids[j] if has_widths else None
                    ),
                ))

        # Build strokes from outside sequences
        outside_strokes: list[Stroke] = []
        for j, out_pts in enumerate(out_seq_pts):
            if len(out_pts) >= 2:
                outside_strokes.append(Stroke(
                    points=out_pts,
                    color=stroke.color,
                    width=stroke.width,
                    opacity=stroke.opacity,
                    tool=stroke.tool,
                    point_widths=(
                        out_seq_wids[j] if has_widths else None
                    ),
                ))

        return (inside_strokes, outside_strokes)

    # ------------------------------------------------------------------
    # Point-based selection move
    # ------------------------------------------------------------------

    def _start_move_drag(self, pos: QPointF) -> None:
        """Begin dragging — selected stroke points will follow the mouse."""
        self._is_dragging_selection = True
        self._drag_start_pos = QPointF(pos.x(), pos.y())
        self._mouse_pos = QPointF(pos.x(), pos.y())
        self.grabMouse()
        self.update()

    def _translate_selection(self, delta: QPointF) -> None:
        """Translate ALL points of every selected stroke by *delta*.

        The entire stroke moves as a unit — no partial translation, so
        there is no "藕断丝连" (stroke-splitting) effect.
        The selection polygon follows the cursor as a whole.
        """
        strokes = self.stroke_manager.strokes
        for idx in self._selected_stroke_indices:
            if idx >= len(strokes):
                continue
            stroke = strokes[idx]
            for i in range(len(stroke.points)):
                stroke.points[i] += delta

        # Move the selection polygon along with the content
        for i in range(len(self._selection_polygon)):
            self._selection_polygon[i] += delta

    def _commit_move(self) -> None:
        """Finalize the move: save undo state, clean up drag state."""
        total_delta = self._mouse_pos - self._drag_start_pos
        if total_delta.manhattanLength() < 1:
            # No meaningful move
            self._is_dragging_selection = False
            self._drag_start_pos = None
            return

        # Save undo state (a reversed delta restores original positions)
        # Store selected stroke indices so undo can reverse the move for
        # every point of those strokes.
        data = {
            'indices': set(self._selected_stroke_indices),
            'delta': QPointF(total_delta.x(), total_delta.y()),
        }
        self._move_undo_stack.append(data)
        self._move_redo_stack.clear()

        # Clean up drag state (keep selection active for subsequent drags)
        self._is_dragging_selection = False
        self._drag_start_pos = None
        self._invalidate_cache()

    def _apply_delta(self, indices: set[int], delta: QPointF) -> None:
        """Apply *delta* to ALL points of the indexed strokes (for undo/redo)."""
        strokes = self.stroke_manager.strokes
        for idx in indices:
            if idx >= len(strokes):
                continue
            stroke = strokes[idx]
            for i in range(len(stroke.points)):
                stroke.points[i] += delta
