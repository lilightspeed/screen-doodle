from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPen,
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


class ToolSettingsPopup(QWidget):
    """Popup with colour palette and width slider for one tool."""

    color_selected = Signal(QColor)
    width_changed = Signal(float)

    PRESET_COLORS = [
        "#000000", "#FFFFFF", "#FF0000", "#FF6600",
        "#FFEE00", "#00CC00", "#00CCCC", "#0066FF",
        "#0000FF", "#9900FF", "#FF00FF", "#FF6699",
        "#996633", "#808080", "#404040", "#E0E0E0",
    ]

    def __init__(
        self,
        current_color: QColor,
        current_width: float,
        tool_name: str,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self._bg_color = QColor(245, 245, 248)
        self._border_color = QColor(200, 200, 210)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Tool label
        title = QLabel(tool_name)
        title.setStyleSheet("color: #555; font-size: 12px; font-weight: bold;")
        layout.addWidget(title)

        # Colour grid
        grid = QFrame(self)
        grid.setStyleSheet("QFrame { background: #E4E4EC; border-radius: 6px; padding: 6px; }")
        grid_layout = QHBoxLayout(grid)
        grid_layout.setSpacing(4)
        grid_layout.setContentsMargins(4, 4, 4, 4)

        col_layouts = [QVBoxLayout() for _ in range(4)]
        for c in col_layouts:
            c.setSpacing(4)

        for i, hex_color in enumerate(self.PRESET_COLORS):
            swatch = ColorSwatch(QColor(hex_color))
            swatch.clicked.connect(lambda _checked, c=hex_color: self._on_swatch(c))
            col_layouts[i % 4].addWidget(swatch)

        for col in col_layouts:
            grid_layout.addLayout(col)

        layout.addWidget(grid)

        # Custom colour button
        custom_btn = QPushButton("Custom…")
        custom_btn.setStyleSheet("""
            QPushButton {
                background: #E4E4EC; color: #444;
                border: 1px solid #ccc; border-radius: 4px;
                padding: 4px 8px; font-size: 12px;
            }
            QPushButton:hover { background: #D4D4DC; color: #222; }
        """)
        custom_btn.clicked.connect(self._on_custom)
        layout.addWidget(custom_btn)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: rgba(0,0,0,0.12);")
        layout.addWidget(sep)

        # Width slider
        width_layout = QHBoxLayout()
        width_layout.setSpacing(4)
        w_label = QLabel("Width")
        w_label.setStyleSheet("color: #666; font-size: 11px;")
        self._w_slider = QSlider(Qt.Horizontal)
        self._w_slider.setRange(1, 50)
        self._w_slider.setValue(int(round(current_width)))
        self._w_slider.setFixedWidth(100)
        self._w_value = QLabel(str(int(round(current_width))))
        self._w_value.setStyleSheet("color: #888; font-size: 11px;")
        self._w_value.setFixedWidth(18)
        self._w_slider.valueChanged.connect(self._on_width_value_changed)
        width_layout.addWidget(w_label)
        width_layout.addWidget(self._w_slider)
        width_layout.addWidget(self._w_value)
        layout.addLayout(width_layout)

    def paintEvent(self, event) -> None:  # noqa: N802
        """Draw a solid background with rounded corners."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self._bg_color)
        painter.setPen(QPen(self._border_color, 1))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 8, 8)

    def _on_width_value_changed(self, value: int) -> None:
        self._w_value.setText(str(value))
        self.width_changed.emit(float(value))

    def _on_swatch(self, hex_color: str) -> None:
        self.color_selected.emit(QColor(hex_color))
        self.close()

    def _on_custom(self) -> None:
        color = QColorDialog.getColor(QColor(255, 0, 0), self, "Pick Color")
        if color.isValid():
            self.color_selected.emit(color)
        self.close()


class ToolBarWindow(QWidget):
    """Floating, draggable, semi-transparent toolbar.

    Each drawing tool (Pen, Highlighter) has its own colour and width
    settings, shown inline as a color swatch and width label next to
    each tool button. Click either to open the settings popup.
    """

    # --- signals ---
    tool_changed = Signal(ToolType)
    color_changed = Signal(QColor)
    width_changed = Signal(float)
    eraser_width_changed = Signal(float)
    undo_requested = Signal()
    redo_requested = Signal()
    clear_requested = Signal()
    hide_requested = Signal()
    tool_settings_changed = Signal(ToolType, QColor, float)

    TOOL_BUTTON_DATA: list[tuple[str, ToolType]] = [
        ("🖱️", ToolType.MOUSE),
        ("✏️", ToolType.PEN),
        ("\U0001f58a️", ToolType.PEN2),   # 🖊️
        ("✒️", ToolType.PEN3),
        ("\U0001f58d️", ToolType.HIGHLIGHTER),
        ("\U0001f9f9", ToolType.ERASER),
    ]

    # ── Tool display names for popup titles ──────────────────────
    _TOOL_POPUP_NAMES: dict[ToolType, str] = {
        ToolType.PEN: "✏️ Pen",
        ToolType.PEN2: "\U0001f58a️ Pen 2",
        ToolType.PEN3: "✒️ Pen 3",
        ToolType.HIGHLIGHTER: "\U0001f58d️ Highlighter",
    }

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._drag_pos: QPoint | None = None
        self._current_tool: ToolType = ToolType.PEN

        # Per-tool independent settings stored in a dict
        self._tool_settings: dict[ToolType, tuple[QColor, float]] = {
            ToolType.PEN: (QColor(255, 0, 0), 3.0),
            ToolType.PEN2: (QColor(0, 100, 255), 3.0),
            ToolType.PEN3: (QColor(0, 180, 0), 3.0),
            ToolType.HIGHLIGHTER: (QColor(255, 238, 0), 12.0),
        }
        # Swatch and width label references for display update
        self._tool_swatches: dict[ToolType, QPushButton] = {}
        self._tool_width_labels: dict[ToolType, QPushButton] = {}

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
            tw, th = 520, 66
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
                background: #C8E0F8;
            }
            QToolButton:checked {
                background: rgba(70,130,255,0.25);
                border-color: rgba(70,130,255,0.55);
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
                background: #C8E0F8;
                border-color: #7AA8F0;
                color: #111;
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
        """Paint the translucent background and ensure hit-test coverage."""
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
        # Outer vertical layout: stretch at top pushes buttons to bottom,
        # leaving empty drag space above.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(8, 0, 8, 6)
        main_layout.setSpacing(4)

        # -- Tool buttons with inline color swatch + width label --
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)

        for label, tool in self.TOOL_BUTTON_DATA:
            container = QWidget()
            container.setStyleSheet("QWidget { background: transparent; }")
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(2)

            btn = QToolButton()
            btn.setText(label)
            btn.setCheckable(True)
            if tool == ToolType.MOUSE:
                btn.setToolTip("Pointer — interact with desktop")
            else:
                btn.setToolTip(tool.name.capitalize())
            self._tool_group.addButton(btn, tool.value)
            row.addWidget(btn)

            # Inline color swatch + width label for pen & highlighter tools only
            if tool not in (ToolType.ERASER, ToolType.MOUSE):
                color, width_val = self._tool_settings.get(tool, (QColor(0, 0, 0), 3.0))

                swatch = QPushButton()
                swatch.setFixedSize(14, 14)
                swatch.setCursor(Qt.PointingHandCursor)
                swatch.setToolTip(f"Change {tool.name.lower()} color")
                r, g, b = color.red(), color.green(), color.blue()
                border = "1px solid #888" if color.lightness() > 128 else "1px solid #555"
                swatch.setStyleSheet(f"""
                    QPushButton {{
                        background-color: rgb({r},{g},{b});
                        border: {border};
                        border-radius: 7px;
                        padding: 0;
                    }}
                    QPushButton:hover {{
                        border: 2px solid #333;
                    }}
                """)
                self._tool_swatches[tool] = swatch

                wlabel = QPushButton(f"{int(round(width_val))}px")
                wlabel.setFixedWidth(28)
                wlabel.setCursor(Qt.PointingHandCursor)
                wlabel.setToolTip(f"Change {tool.name.lower()} width")
                wlabel.setStyleSheet("""
                    QPushButton {
                        color: #666;
                        background: transparent;
                        border: none;
                        font-size: 11px;
                        padding: 0;
                        min-width: 0;
                        min-height: 0;
                    }
                    QPushButton:hover {
                        color: #1565C0;
                        background: #C8E0F8;
                    }
                """)
                self._tool_width_labels[tool] = wlabel

                swatch.clicked.connect(lambda checked, t=tool: self._show_tool_settings_for(t))
                wlabel.clicked.connect(lambda checked, t=tool: self._show_tool_settings_for(t))

                row.addWidget(swatch)
                row.addWidget(wlabel)

            main_layout.addWidget(container)

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
        self._clear_btn.setText("\U0001f5d1")
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
            "background: transparent; border: none; border-radius: 4px; }"
            "QPushButton:hover { color: #1565C0; background: #C8E0F8; }"
        )
        main_layout.addWidget(self._hide_btn)

        outer.addLayout(main_layout)

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

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._tool_group.idClicked.connect(self._on_tool_clicked)
        self._eraser_slider.valueChanged.connect(self._on_eraser_width_changed)
        self._undo_btn.clicked.connect(self.undo_requested.emit)
        self._redo_btn.clicked.connect(self.redo_requested.emit)
        self._clear_btn.clicked.connect(self.clear_requested.emit)
        self._hide_btn.clicked.connect(self.hide_requested.emit)

    # ------------------------------------------------------------------
    # Tool switching — emit the active tool's colour & width to the canvas
    # ------------------------------------------------------------------

    def _on_tool_clicked(self, tool_id: int) -> None:
        tool = ToolType(tool_id)
        self._current_tool = tool
        self.tool_changed.emit(tool)
        if tool in self._tool_settings:
            color, width = self._tool_settings[tool]
            self.color_changed.emit(color)
            self.width_changed.emit(width)

    # ------------------------------------------------------------------
    # Per-tool settings popups
    # ------------------------------------------------------------------

    def _show_tool_settings_for(self, tool: ToolType) -> None:
        if tool not in self._tool_settings:
            return
        color, width = self._tool_settings[tool]
        name = self._TOOL_POPUP_NAMES.get(tool, tool.name)
        self._show_tool_settings(tool, color, width, name)

    def _show_tool_settings(
        self,
        tool: ToolType,
        color: QColor,
        width: float,
        name: str,
    ) -> None:
        popup = ToolSettingsPopup(color, width, name, self)

        popup.color_selected.connect(
            lambda c, t=tool: self._on_tool_settings_changed(t, c, self._tool_settings[t][1])
        )
        popup.width_changed.connect(
            lambda w, t=tool: self._on_tool_settings_changed(t, self._tool_settings[t][0], w)
        )

        swatch = self._tool_swatches.get(tool)
        if swatch:
            pos = swatch.mapToGlobal(swatch.rect().bottomLeft())
            popup.move(pos)
        popup.show()

    def _on_tool_settings_changed(self, tool: ToolType, color: QColor, width: float) -> None:
        self._tool_settings[tool] = (color, width)
        self._update_swatch_display(tool, color, width)
        self.tool_settings_changed.emit(tool, color, width)
        if self._current_tool == tool:
            self.color_changed.emit(color)
            self.width_changed.emit(width)

    def _update_swatch_display(self, tool: ToolType, color: QColor, width: float) -> None:
        """Update the inline color swatch and width label for the given tool."""
        swatch = self._tool_swatches.get(tool)
        if swatch:
            r, g, b = color.red(), color.green(), color.blue()
            border = "1px solid #888" if color.lightness() > 128 else "1px solid #555"
            swatch.setStyleSheet(f"""
                QPushButton {{
                    background-color: rgb({r},{g},{b});
                    border: {border};
                    border-radius: 7px;
                    padding: 0;
                }}
                QPushButton:hover {{
                    border: 2px solid #333;
                }}
            """)
        wlabel = self._tool_width_labels.get(tool)
        if wlabel:
            wlabel.setText(f"{int(round(width))}px")

    def _on_eraser_width_changed(self, value: int) -> None:
        self._eraser_label.setText(str(value))
        self.eraser_width_changed.emit(float(value))

    # ------------------------------------------------------------------
    # Public helpers used by the app coordinator
    # ------------------------------------------------------------------

    def set_tool_settings(self, tool: ToolType, color: QColor, width: float) -> None:
        if tool in self._tool_settings:
            self._tool_settings[tool] = (color, width)
            self._update_swatch_display(tool, color, width)

    def set_eraser_width(self, width: float) -> None:
        self._eraser_slider.setValue(int(round(width)))
        self._eraser_label.setText(str(int(round(width))))

    def activate_tool(self, tool: ToolType) -> None:
        """Select a tool and update the checked button state."""
        btn = self._tool_group.button(tool.value)
        if btn:
            btn.setChecked(True)
        self._on_tool_clicked(tool.value)

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
