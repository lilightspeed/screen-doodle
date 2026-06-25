from __future__ import annotations

from PySide6.QtCore import QPointF
from PySide6.QtGui import (
    QColor,
    QPainter,
    QPainterPath,
    QPen,
    Qt,
)

from .models import Stroke, ToolType


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
    elif tool in (ToolType.HIGHLIGHTER, ToolType.PEN):
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
        alpha = int(255 * stroke.opacity * 0.3)
        color.setAlpha(alpha)
        width *= 4
    else:
        alpha = int(255 * stroke.opacity)
        color.setAlpha(alpha)

    pen = QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    return pen, None


def _apply_preview(painter: QPainter) -> None:
    """Make the painter draw semi-transparently for preview."""
    painter.setOpacity(0.7)


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
    for i in range(len(stroke.points) - 1):
        mid = QPointF(
            (stroke.points[i].x() + stroke.points[i + 1].x()) / 2.0,
            (stroke.points[i].y() + stroke.points[i + 1].y()) / 2.0,
        )
        path.quadTo(stroke.points[i], mid)
    painter.drawPath(path)

    # Restore composition mode for subsequent strokes
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)


def _draw_freehand(painter: QPainter, stroke: Stroke, is_preview: bool) -> None:
    """Draw a smooth freehand path using quadratic Bézier curves."""
    if len(stroke.points) < 2:
        return

    if is_preview:
        _apply_preview(painter)

    pen, _ = _pen_and_brush(stroke, is_preview)
    painter.setPen(pen)

    path = QPainterPath()
    path.moveTo(stroke.points[0])
    for i in range(len(stroke.points) - 1):
        mid = QPointF(
            (stroke.points[i].x() + stroke.points[i + 1].x()) / 2.0,
            (stroke.points[i].y() + stroke.points[i + 1].y()) / 2.0,
        )
        path.quadTo(stroke.points[i], mid)
    painter.drawPath(path)


