from __future__ import annotations

import math

from PySide6.QtCore import QObject, Signal
from PySide6.QtCore import QPointF

from .models import Stroke, ToolType

# ── Velocity-to-width mapping constants ──────────────────────────────────
# Only these tools get dynamic width based on drawing speed.
_VELOCITY_TOOLS = {ToolType.PEN, ToolType.PEN2, ToolType.PEN3}

_THIN_MULT = 0.4      # fastest drawing → 0.4× base width (thin)
_THICK_MULT = 2.5     # slowest drawing → 2.5× base width (thick)
_REF_DIST = 20.0      # pixel distance at which the curve is roughly halfway
_ALPHA = 0.3          # exponential smoothing factor (lower = smoother)


class StrokeManager(QObject):
    """Manages the ordered list of strokes with undo/redo support."""

    data_changed = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.strokes: list[Stroke] = []
        self.redo_stack: list[Stroke] = []
        self._current: Stroke | None = None

    def start_stroke(
        self,
        point: QPointF,
        color,
        width: float,
        opacity: float,
        tool: ToolType,
    ) -> Stroke:
        """Begin a new stroke at the given point. Clears the redo stack."""
        self.redo_stack.clear()
        self._current = Stroke(
            points=[point],
            color=color,
            width=width,
            opacity=opacity,
            tool=tool,
        )
        # The first point has no predecessor for velocity calculation,
        # so it gets the base width.
        self._current.point_widths = [width]
        return self._current

    def add_point(self, point: QPointF) -> None:
        """Append a point to the in-progress stroke.

        For velocity-sensitive tools (PEN / PEN2 / PEN3), the width of
        the new point is derived from the distance to the previous point —
        fast movement yields a thinner segment, slow movement a thicker one.
        """
        if self._current is None:
            return

        last = self._current.points[-1]
        dist = math.hypot(point.x() - last.x(), point.y() - last.y())

        tool = self._current.tool
        if tool in _VELOCITY_TOOLS:
            prev = self._current.point_widths[-1] if self._current.point_widths else None
            w = self._compute_point_width(self._current.width, dist, prev)
        else:
            w = self._current.width

        self._current.points.append(point)
        self._current.point_widths.append(w)

    @staticmethod
    def _compute_point_width(
        base_width: float,
        distance: float,
        prev_width: float | None,
    ) -> float:
        """Map pixel distance to a smoothed stroke width.

        Small distance (slow) → wide, large distance (fast) → narrow.
        Exponential smoothing prevents width jitter from mouse noise.
        """
        t = min(distance / _REF_DIST, 1.0)
        # Inverted curve: t=0 → THICK_MULT, t=1 → THIN_MULT
        raw_mult = _THICK_MULT - (_THICK_MULT - _THIN_MULT) * (t ** 0.7)

        if prev_width is not None:
            prev_mult = prev_width / base_width
            smoothed = _ALPHA * raw_mult + (1 - _ALPHA) * prev_mult
        else:
            smoothed = raw_mult

        return base_width * smoothed

    def end_stroke(self) -> Stroke | None:
        """Finalize the current stroke. Returns it, or None if too short."""
        if self._current is None:
            return None

        # Discard strokes with fewer than 2 points
        if len(self._current.points) < 2:
            self._current = None
            return None

        finalized = self._current
        self.strokes.append(finalized)
        self._current = None
        self.data_changed.emit()
        return finalized

    def undo(self) -> bool:
        """Undo the last stroke. Returns True if anything was undone."""
        if not self.strokes:
            return False
        stroke = self.strokes.pop()
        self.redo_stack.append(stroke)
        self.data_changed.emit()
        return True

    def redo(self) -> bool:
        """Redo the last undone stroke. Returns True if anything was redone."""
        if not self.redo_stack:
            return False
        stroke = self.redo_stack.pop()
        self.strokes.append(stroke)
        self.data_changed.emit()
        return True

    def clear(self) -> None:
        """Remove all strokes and clear redo history."""
        self.strokes.clear()
        self.redo_stack.clear()
        self._current = None
        self.data_changed.emit()

    def preview_stroke(self) -> Stroke | None:
        """Return the in-progress stroke for real-time preview rendering."""
        return self._current

    def get_strokes(self) -> list[Stroke]:
        """Return a copy of the finalized stroke list."""
        return list(self.strokes)
