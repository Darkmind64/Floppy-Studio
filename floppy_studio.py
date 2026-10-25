"""Floppy Studio — interface moderne pour Greaseweazle."""
import os
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from fstudio import APP_NAME, engine, theme
from fstudio.main_window import MainWindow


def main():
    engine.install_stdout_router()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    ico = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), "icon.ico")
    if os.path.exists(ico):
        app.setWindowIcon(QIcon(ico))
    theme.apply(app)
    w = MainWindow()
    w.show()
    args = [a for a in sys.argv[1:] if os.path.isfile(a)]
    if args:
        w.explore(os.path.abspath(args[0]))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
