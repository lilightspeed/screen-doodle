from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtCore import QPointF

from .models import Stroke, ToolType


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
        return self._current

    def add_point(self, point: QPointF) -> None:
        """Append a point to the in-progress stroke."""
        if self._current is not None:
            self._current.points.append(point)

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
