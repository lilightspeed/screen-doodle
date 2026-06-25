from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor


class ToolType(Enum):
    MOUSE = auto()
    PEN = auto()
    HIGHLIGHTER = auto()
    ERASER = auto()
    PEN2 = auto()
    PEN3 = auto()


@dataclass
class Stroke:
    points: list[QPointF] = field(default_factory=list)
    color: QColor = field(default_factory=lambda: QColor(255, 0, 0))
    width: float = 3.0
    opacity: float = 1.0
    tool: ToolType = ToolType.PEN
