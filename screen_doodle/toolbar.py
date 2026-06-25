from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QColorDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .models import ToolType


class ColorSwatch(QPushButton):
    """A square button that displays a colour and emits when clicked."""

    def __init__(self, color: QColor, parent: QWidget | None = None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(color.name())
        self._update_style()

    def _update_style(self) -> None:
        r, g, b = self._color.red(), self._color.green(), self._color.blue()
        border = "1px solid #aaa" if self._color.lightness() > 128 else "1px solid #666"
        self.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: {border}; border-radius: 3px;"
        )

    @property
    def color(self) -> QColor:
        return self._color


class ColorPalettePopup(QWidget):
    """A popup widget showing preset colour swatches + a 'Custom…' button."""

    color_selected = Signal(QColor)

    PRESET_COLORS = [
        "#000000", "#FFFFFF", "#FF0000", "#FF6600",
        "#FFEE00", "#00CC00", "#00CCCC", "#0066FF",
        "#0000FF", "#9900FF", "#FF00FF", "#FF6699",
        "#996633", "#808080", "#404040", "#E0E0E0",
    ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Swatch grid (4 columns)
        grid = QFrame(self)
        grid.setStyleSheet(
            "QFrame { background: rgba(240,240,245,240); border-radius: 6px; padding: 6px; }"
        )
        grid_layout = QHBoxLayout(grid)
        grid_layout.setSpacing(4)
        grid_layout.setContentsMargins(4, 4, 4, 4)

        col_layouts = []
        for _ in range(4):
            col = QVBoxLayout()
            col.setSpacing(4)
            col_layouts.append(col)

        for i, hex_color in enumerate(self.PRESET_COLORS):
            swatch = ColorSwatch(QColor(hex_color))
            swatch.clicked.connect(lambda _checked, c=hex_color: self._on_swatch(c))
            col_layouts[i % 4].addWidget(swatch)

        for col in col_layouts:
            grid_layout.addLayout(col)

        layout.addWidget(grid)

        # Custom colour button
        custom_btn = QPushButton("Custom…")
        custom_btn.setStyleSheet(
            """
            QPushButton {
                background: rgba(240,240,245,240); color: #444;
                border: 1px solid #ccc; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }
            QPushButton:hover { background: rgba(220,220,230,240); color: #222; }
            """
        )
        custom_btn.clicked.connect(self._on_custom)
        layout.addWidget(custom_btn)

    def _on_swatch(self, hex_color: str) -> None:
        self.color_selected.emit(QColor(hex_color))
        self.close()

    def _on_custom(self) -> None:
        color = QColorDialog.getColor(QColor(255, 0, 0), self, "Pick Color")
        if color.isValid():
            self.color_selected.emit(color)
        self.close()


class ToolBarWindow(QWidget):
    """Floating, draggable, semi-transparent toolbar."""

    # --- signals ---
    tool_changed = Signal(ToolType)
    color_changed = Signal(QColor)
    width_changed = Signal(float)
    opacity_changed = Signal(float)
    eraser_width_changed = Signal(float)
    undo_requested = Signal()
    redo_requested = Signal()
    clear_requested = Signal()
    hide_requested = Signal()

    TOOL_BUTTON_DATA: list[tuple[str, ToolType]] = [
        ("✏️", ToolType.PEN),
        ("🖍️", ToolType.HIGHLIGHTER),
        ("🧹", ToolType.ERASER),
    ]

    ACTION_BUTTON_DATA: list[tuple[str, str]] = [
        ("↩", "Undo"),
        ("↪", "Redo"),
        ("🗑", "Clear"),
    ]

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._drag_pos: QPoint | None = None
        self._current_color: QColor = QColor(255, 0, 0)
        self._palette_popup: ColorPalettePopup | None = None

        self._setup_window()
        self._build_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _setup_window(self) -> None:
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        # Position at top-centre of primary screen
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            tw, th = 620, 48
            self.setGeometry(sg.center().x() - tw // 2, sg.top() + 30, tw, th)

        self.setObjectName("ToolBarWindow")
        self.setStyleSheet("""
            QToolButton {
                color: #333;
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 4px 6px;
                font-size: 15px;
                min-width: 28px;
                min-height: 28px;
            }
            QToolButton:hover {
                background: rgba(0,0,0,0.06);
            }
            QToolButton:checked {
                background: rgba(70,130,255,0.20);
                border-color: rgba(70,130,255,0.45);
            }
            QSlider::groove:horizontal {
                background: rgba(0,0,0,0.12);
                height: 4px;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #888;
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }
            QSlider::handle:horizontal:hover {
                background: #555;
            }
            QPushButton {
                color: #555;
                background: rgba(0,0,0,0.04);
                border: 1px solid #bbb;
                border-radius: 4px;
                padding: 3px 8px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: rgba(0,0,0,0.10);
                color: #222;
            }
            QLabel {
                color: #888;
                font-size: 11px;
            }
        """)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # noqa: N802
        """Paint the translucent background and ensure hit-test coverage.

        Without this override the toolbar (a ``WA_TranslucentBackground``
        window) would have alpha=0 in the gaps between child widgets,
        causing Windows to skip those pixels during hit-testing — making
        buttons feel "dead" at their edges.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Full-area fill with near-zero alpha ensures *every* pixel in the
        # toolbar window has alpha > 0, so Windows layered-window hit-testing
        # delivers mouse events everywhere within the toolbar boundary.
        painter.fillRect(self.rect(), QColor(255, 255, 255, 1))

        # The visible semi-transparent background with rounded corners.
        painter.setBrush(QColor(235, 235, 240, 240))
        painter.setPen(QPen(QColor(200, 200, 210, 200), 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(8, 4, 8, 4)
        main_layout.setSpacing(4)

        # -- Tool buttons --
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        for label, tool in self.TOOL_BUTTON_DATA:
            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            btn.setToolTip(tool.name.capitalize())
            self._tool_group.addButton(btn, tool.value)
            main_layout.addWidget(btn)

        main_layout.addWidget(self._sep())

        # -- Colour button --
        self._color_btn = QPushButton()
        self._color_btn.setFixedSize(28, 28)
        self._color_btn.setCursor(Qt.PointingHandCursor)
        self._color_btn.setToolTip("Color")
        self._update_color_btn()
        main_layout.addWidget(self._color_btn)

        # -- Width slider --
        self._width_label = QLabel("3")
        self._width_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self._width_label.setFixedWidth(18)
        self._width_slider = QSlider(Qt.Horizontal)
        self._width_slider.setRange(1, 50)
        self._width_slider.setValue(3)
        self._width_slider.setFixedWidth(80)
        self._width_slider.setToolTip("Brush size")
        main_layout.addWidget(self._width_slider)
        main_layout.addWidget(self._width_label)

        main_layout.addWidget(self._sep())

        # -- Eraser width slider --
        self._eraser_label = QLabel("20")
        self._eraser_label.setStyleSheet("color: #aaa; font-size: 11px;")
        self._eraser_label.setFixedWidth(18)
        self._eraser_slider = QSlider(Qt.Horizontal)
        self._eraser_slider.setRange(5, 100)
        self._eraser_slider.setValue(20)
        self._eraser_slider.setFixedWidth(80)
        self._eraser_slider.setToolTip("Eraser size")
        main_layout.addWidget(self._eraser_slider)
        main_layout.addWidget(self._eraser_label)

        main_layout.addWidget(self._sep())

        # -- Undo / Redo / Clear --
        self._undo_btn = QToolButton()
        self._undo_btn.setText("↩")
        self._undo_btn.setToolTip("Undo (Ctrl+Z)")
        self._redo_btn = QToolButton()
        self._redo_btn.setText("↪")
        self._redo_btn.setToolTip("Redo (Ctrl+Y)")
        self._clear_btn = QToolButton()
        self._clear_btn.setText("🗑")
        self._clear_btn.setToolTip("Clear all")
        for btn in (self._undo_btn, self._redo_btn, self._clear_btn):
            btn.setStyleSheet(btn.styleSheet() + "QToolButton { font-size: 13px; }")
        main_layout.addWidget(self._undo_btn)
        main_layout.addWidget(self._redo_btn)
        main_layout.addWidget(self._clear_btn)

        # Spacer + Hide
        main_layout.addStretch()
        self._hide_btn = QPushButton("─")
        self._hide_btn.setFixedSize(22, 22)
        self._hide_btn.setToolTip("Hide (Esc)")
        self._hide_btn.setStyleSheet(
            "QPushButton { color: #666; font-size: 14px; "
            "background: transparent; border: none; }"
            "QPushButton:hover { color: #222; }"
        )
        main_layout.addWidget(self._hide_btn)

        # Default tool: PEN selected
        pen_btn = self._tool_group.button(ToolType.PEN.value)
        if pen_btn:
            pen_btn.setChecked(True)

    def _sep(self) -> QFrame:
        """Vertical separator line."""
        f = QFrame()
        f.setFrameShape(QFrame.VLine)
        f.setStyleSheet("color: rgba(0,0,0,0.12);")
        f.setFixedWidth(1)
        return f

    def _update_color_btn(self) -> None:
        r, g, b = self._current_color.red(), self._current_color.green(), self._current_color.blue()
        self._color_btn.setStyleSheet(
            f"background-color: rgb({r},{g},{b}); border: 1px solid #888; "
            f"border-radius: 4px;"
        )

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._tool_group.idClicked.connect(self._on_tool_clicked)
        self._color_btn.clicked.connect(self._show_palette)
        self._width_slider.valueChanged.connect(self._on_width_changed)
        self._eraser_slider.valueChanged.connect(self._on_eraser_width_changed)
        self._undo_btn.clicked.connect(self.undo_requested.emit)
        self._redo_btn.clicked.connect(self.redo_requested.emit)
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        self._hide_btn.clicked.connect(self.hide_requested.emit)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_tool_clicked(self, tool_id: int) -> None:
        tool = ToolType(tool_id)
        self.tool_changed.emit(tool)

    def _show_palette(self) -> None:
        if self._palette_popup is None:
            self._palette_popup = ColorPalettePopup(self)
            self._palette_popup.color_selected.connect(self._on_palette_color)
        pos = self._color_btn.mapToGlobal(
            self._color_btn.rect().bottomLeft()
        )
        self._palette_popup.move(pos)
        self._palette_popup.show()

    def _on_palette_color(self, color: QColor) -> None:
        self._current_color = color
        self._update_color_btn()
        self.color_changed.emit(color)

    def _on_width_changed(self, value: int) -> None:
        self._width_label.setText(str(value))
        self.width_changed.emit(float(value))

    def _on_eraser_width_changed(self, value: int) -> None:
        self._eraser_label.setText(str(value))
        self.eraser_width_changed.emit(float(value))

    # Public helpers used by the app coordinator
    def set_color(self, color: QColor) -> None:
        self._current_color = color
        self._update_color_btn()

    def set_width(self, width: float) -> None:
        self._width_slider.setValue(int(round(width)))
        self._width_label.setText(str(int(round(width))))

    def set_eraser_width(self, width: float) -> None:
        self._eraser_slider.setValue(int(round(width)))
        self._eraser_label.setText(str(int(round(width))))

    # ------------------------------------------------------------------
    # Drag support
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_pos = None
