from __future__ import annotations

from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    Qt,
)

from .models import Stroke, ToolType
from .rendering_config import cfg


def render_stroke(
    painter: QPainter,
    stroke: Stroke,
    is_preview: bool = False,
) -> None:
    """Render a single stroke onto *painter*.

    This function is used both by the live canvas and by the export service,
    keeping rendering logic in one place.
    """
    if not stroke.points:
        return

    tool = stroke.tool

    if tool == ToolType.ERASER:
        _draw_eraser(painter, stroke, is_preview)
    else:
        _draw_freehand(painter, stroke, is_preview)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pen_and_brush(
    stroke: Stroke,
    is_preview: bool,
) -> tuple[QPen, None]:
    """Build the QPen for a stroke.

    Returns (pen, brush) where *brush* is always ``None``.
    """
    color = QColor(stroke.color)
    width = stroke.width

    if stroke.tool == ToolType.HIGHLIGHTER:
        alpha = int(255 * stroke.opacity * cfg.highlighter_opacity_scale)
        color.setAlpha(alpha)
        width *= cfg.highlighter_width_scale
    else:
        alpha = int(255 * stroke.opacity)
        color.setAlpha(alpha)

    pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    return pen, None


def _apply_preview(painter: QPainter) -> None:
    """Make the painter draw semi-transparently for preview."""
    painter.setOpacity(cfg.preview_opacity)


# ---------------------------------------------------------------------------
# Drawing routines
# ---------------------------------------------------------------------------


def _draw_eraser(painter: QPainter, stroke: Stroke, is_preview: bool) -> None:
    """Erase by setting pixels to transparent."""
    if len(stroke.points) < 2:
        return

    painter.setCompositionMode(QPainter.CompositionMode_Clear)
    pen = QPen(QColor(0, 0, 0, 0), stroke.width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    # Use lineTo for the same reason as _draw_freehand — bezier midpoint
    # interpolation truncates the final half-step, causing visible gaps
    # at direction reversals.
    path = QPainterPath()
    path.moveTo(stroke.points[0])
    for pt in stroke.points[1:]:
        path.lineTo(pt)
    painter.drawPath(path)

    # Restore composition mode for subsequent strokes
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _draw_freehand(painter: QPainter, stroke: Stroke, is_preview: bool) -> None:
    """Draw a freehand path by connecting data points with straight segments.

    Using ``lineTo`` with ``RoundCap`` / ``RoundJoin`` gives a smooth
    appearance while ensuring the stroke exactly follows the mouse path —
    unlike quadratic Bézier midpoint interpolation, which truncates the last
    half-step and creates visible clipping at direction reversals.

    When per-point velocity-based widths are available, dispatches to
    ``_draw_variable_width`` for a natural speed-sensitive stroke.
    """
    if len(stroke.points) < 2:
        return

    n = len(stroke.points)
    pw = stroke.point_widths

    # Use variable-width rendering when we have per-point data
    if pw and len(pw) == n:
        _draw_variable_width(painter, stroke, is_preview)
        return

    # ── Uniform-width path (original) ──────────────────────────────────
    if is_preview:
        _apply_preview(painter)

    pen, _ = _pen_and_brush(stroke, is_preview)
    painter.setPen(pen)

    path = QPainterPath()
    path.moveTo(stroke.points[0])
    for pt in stroke.points[1:]:
        path.lineTo(pt)
    painter.drawPath(path)


def _draw_variable_width(painter: QPainter, stroke: Stroke, is_preview: bool) -> None:
    """Render a variable-width stroke as per-segment lines with alternating widths.

    Each consecutive pair of points is drawn as an individual line whose
    width is the average of the two endpoint widths.  ``RoundCap`` / ``RoundJoin``
    make adjacent segments blend smoothly, while anti-aliasing eliminates
    pixel-level jaggedness.  No circles or outline polygons = no fill-rule
    complications or self-intersections.
    """
    if is_preview:
        _apply_preview(painter)

    color = QColor(stroke.color)
    alpha = int(255 * stroke.opacity)
    color.setAlpha(alpha)

    points = stroke.points
    widths = stroke.point_widths
    n = len(points)

    if n < 2:
        return

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.NoBrush)

    for i in range(n - 1):
        seg_w = (widths[i] + widths[i + 1]) / 2.0
        if seg_w < cfg.min_segment_width:
            seg_w = cfg.min_segment_width
        pen = QPen(color, seg_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(points[i], points[i + 1])


