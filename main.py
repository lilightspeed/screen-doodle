"""Screen Doodle — lightweight Windows screen annotation tool.

Press Ctrl+Shift+D to toggle drawing mode.
"""

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from screen_doodle.app import ScreenDoodleApp


def main() -> None:
    # Enable high-DPI support (default in Qt6, but explicit is safe)
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Screen Doodle")
    app.setOrganizationName("ScreenDoodle")
    app.setQuitOnLastWindowClosed(False)  # allow background / tray operation

    doodle = ScreenDoodleApp(app)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
