from __future__ import annotations

import math

from PySide6.QtCore import QPointF
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    Qt,
)

from .models import Stroke, ToolType
from .rendering_config import cfg

# Only these tools get velocity-sensitive variable-width rendering.
_VELOCITY_TOOLS = {ToolType.PEN, ToolType.PEN2, ToolType.PEN3}


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
# Centripetal Catmull-Rom spline interpolation
# ---------------------------------------------------------------------------

# Knot parameterisation constant.  0.5 = centripetal, 0 = uniform,
# 1 = chordal.  Stick with 0.5 for drawing — it handles unevenly
# spaced mouse points much better than uniform.
_ALPHA = 0.5


def _centripetal_knots(points: list[QPointF]) -> list[float]:
    """Compute the knot vector for centripetal (α=0.5) Catmull-Rom.

    Knot spacing = |P[i+1] − P[i]|^α, so points that are close
    together get proportionally less parameter space, which eliminates
    the overshoot / self‑intersection artifacts of uniform Catmull-Rom.
    """
    knots = [0.0]
    for i in range(len(points) - 1):
        dx = points[i + 1].x() - points[i].x()
        dy = points[i + 1].y() - points[i].y()
        dist = math.sqrt(dx * dx + dy * dy)
        knots.append(knots[-1] + dist ** _ALPHA)
    return knots


def _tangent(
    p_prev: QPointF,
    p_next: QPointF,
    dt: float,
) -> tuple[float, float]:
    """Return (dx, dy) of the tangent at one node, or (0, 0) if *dt* ≤ 0."""
    if dt <= 1e-12:
        return 0.0, 0.0
    return (
        (p_next.x() - p_prev.x()) / dt,
        (p_next.y() - p_prev.y()) / dt,
    )


def _add_smooth_path(path: QPainterPath, points: list[QPointF]) -> None:
    """Extend *path* with cubic Bezier segments (centripetal Catmull-Rom).

    The spline passes through every point in *points* with C¹ continuity
    and no overshoot / looping.  Falls back to ``lineTo`` for < 3 points.
    """
    n = len(points)
    if n < 3:
        path.moveTo(points[0])
        for pt in points[1:]:
            path.lineTo(pt)
        return

    knots = _centripetal_knots(points)
    path.moveTo(points[0])

    for i in range(n - 1):
        p1 = points[i]
        p2 = points[i + 1]

        interval = knots[i + 1] - knots[i]

        # Centripetal Catmull-Rom → cubic Bezier control points.
        # CP₁ = Pᵢ + (tᵢ₊₁−tᵢ) · (Pᵢ₊₁−Pᵢ₋₁) / 3·(tᵢ₊₁−tᵢ₋₁)
        # CP₂ = Pᵢ₊₁ − (tᵢ₊₁−tᵢ) · (Pᵢ₊₂−Pᵢ) / 3·(tᵢ₊₂−tᵢ)
        dx1, dy1 = _tangent(
            points[max(0, i - 1)],
            p2,
            knots[i + 1] - knots[max(0, i - 1)],
        )
        cp1 = QPointF(
            p1.x() + interval * dx1 / 3.0,
            p1.y() + interval * dy1 / 3.0,
        )

        dx2, dy2 = _tangent(
            p1,
            points[min(n - 1, i + 2)],
            knots[min(n - 1, i + 2)] - knots[i],
        )
        cp2 = QPointF(
            p2.x() - interval * dx2 / 3.0,
            p2.y() - interval * dy2 / 3.0,
        )

        path.cubicTo(cp1, cp2, p2)


def _catmull_rom_points(
    points: list[QPointF],
    segments: int,
) -> list[QPointF]:
    """Evaluate centripetal Catmull-Rom at regular intervals.

    For *n* input points the result contains ~(n−1) × *segments* + 1
    points forming a smooth curve that passes through every original
    point without overshoot or looping.
    """
    n = len(points)
    if n < 3:
        return list(points)

    knots = _centripetal_knots(points)
    out: list[QPointF] = [points[0]]

    for i in range(n - 1):
        p1 = points[i]
        p2 = points[i + 1]

        t1 = knots[i]
        t2 = knots[i + 1]
        interval = t2 - t1

        # Centripetal tangents at the two endpoints of this segment
        dx1, dy1 = _tangent(
            points[max(0, i - 1)],
            p2,
            t2 - knots[max(0, i - 1)],
        )
        dx2, dy2 = _tangent(
            p1,
            points[min(n - 1, i + 2)],
            knots[min(n - 1, i + 2)] - t1,
        )

        is_last = i == n - 2
        limit = segments + 1 if is_last else segments

        for s in range(1, limit):
            τ = s / segments  # noqa: PLW2901
            τ2 = τ * τ
            τ3 = τ2 * τ

            # Cubic Hermite basis functions
            h00 = 2.0 * τ3 - 3.0 * τ2 + 1.0
            h10 = τ3 - 2.0 * τ2 + τ
            h01 = -2.0 * τ3 + 3.0 * τ2
            h11 = τ3 - τ2

            x = (h00 * p1.x() + h10 * interval * dx1
                 + h01 * p2.x() + h11 * interval * dx2)
            y = (h00 * p1.y() + h10 * interval * dy1
                 + h01 * p2.y() + h11 * interval * dy2)
            out.append(QPointF(x, y))

    out[-1] = points[-1]
    return out


def _interp_widths(widths: list[float], segments: int) -> list[float]:
    """Linearly interpolate widths to match ``_catmull_rom_points`` output.

    Each original width corresponds to one control point; the returned
    list has the same length as the point list from ``_catmull_rom_points``
    so the two can be zipped for per-segment variable-width drawing.
    """
    n = len(widths)
    if n < 2:
        return widths[:]

    out: list[float] = [widths[0]]

    for i in range(n - 1):
        w1 = widths[i]
        w2 = widths[i + 1]

        is_last = i == n - 2
        limit = segments + 1 if is_last else segments

        for _s in range(1, limit):
            t = _s / segments
            out.append(w1 + t * (w2 - w1))

    out[-1] = widths[-1]
    return out


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

    path = QPainterPath()
    path.moveTo(stroke.points[0])
    for pt in stroke.points[1:]:
        path.lineTo(pt)
    painter.drawPath(path)

    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _draw_freehand(painter: QPainter, stroke: Stroke, is_preview: bool) -> None:
    """Draw a freehand path with Catmull-Rom smoothing.

    Uniform-width strokes use ``QPainterPath.cubicTo`` with Catmull-Rom →
    Bezier control points for a perfectly smooth curve through all input
    points.  Velocity-sensitive strokes dispatch to
    ``_draw_variable_width`` which applies Catmull-Rom interpolation to
    both position and width together.
    """
    n = len(stroke.points)
    if n < 2:
        return

    pw = stroke.point_widths

    # Velocity-sensitive path — smooth both position and width
    if pw and len(pw) == n and stroke.tool in _VELOCITY_TOOLS:
        _draw_variable_width(painter, stroke, is_preview)
        return

    # ── Uniform-width path with Catmull-Rom smoothing ──────────────────
    if is_preview:
        _apply_preview(painter)

    pen, _ = _pen_and_brush(stroke, is_preview)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)

    path = QPainterPath()
    _add_smooth_path(path, stroke.points)
    painter.drawPath(path)


def _draw_variable_width(
    painter: QPainter,
    stroke: Stroke,
    is_preview: bool,
) -> None:
    """Render a variable-width stroke using Catmull-Rom interpolated data.

    Both position and width are interpolated with a Catmull-Rom spline so
    that sparse fast‑movement points produce a smooth curve and dense slow‑
    movement points smoothly transition between width values instead of
    creating bumps at segment boundaries.
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

    seg = cfg.interpolation_segments

    if n < 3 or seg < 2:
        # Too few points for Catmull-Rom — draw as-is
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.NoBrush)
        for i in range(n - 1):
            seg_w = (widths[i] + widths[i + 1]) / 2.0
            if seg_w < cfg.min_segment_width:
                seg_w = cfg.min_segment_width
            pen = QPen(color, seg_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawLine(points[i], points[i + 1])
        return

    # Catmull-Rom interpolation for both position and width
    smooth_pts = _catmull_rom_points(points, seg)
    smooth_w = _interp_widths(widths, seg)
    m = len(smooth_pts)

    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.NoBrush)

    for i in range(m - 1):
        seg_w = (smooth_w[i] + smooth_w[i + 1]) / 2.0
        if seg_w < cfg.min_segment_width:
            seg_w = cfg.min_segment_width
        pen = QPen(color, seg_w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(smooth_pts[i], smooth_pts[i + 1])


