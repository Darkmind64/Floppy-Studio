"""Thème sombre et couleurs d'état."""
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#0f1115"
PANEL = "#161a21"
CARD = "#1b2029"
BORDER = "#2a313c"
TEXT = "#e6e9ef"
MUTED = "#8b95a5"
ACCENT = "#4f8cff"
ACCENT_2 = "#7aa7ff"

STATUS = {
    "pending": "#262c36",
    "current": "#4f8cff",
    "ok": "#34c47c",
    "verified": "#34c47c",
    "retried": "#e3a73b",
    "written": "#2bb3c0",
    "bad": "#f0524f",
    "failed": "#f0524f",
    "empty": "#59616e",
    "flux": "#4f8cff",
    "erased": "#9b7bf2",
    "skipped": "#333a46",
    "absent": "#151920",
}

STATUS_LABEL = {
    "pending": "En attente", "current": "En cours", "ok": "OK", "verified": "Vérifiée",
    "retried": "OK après relecture", "written": "Écrite", "bad": "Secteurs illisibles",
    "failed": "Échec", "empty": "Aucun secteur", "flux": "Flux capturé",
    "erased": "Effacée", "skipped": "Ignorée",
}

LOG_COLORS = {"info": TEXT, "ok": "#34c47c", "warn": "#e3a73b", "err": "#f0524f", "dim": MUTED}


def qc(name: str) -> QColor:
    return QColor(STATUS.get(name, name))


QSS = f"""
* {{ font-family: "Segoe UI Variable", "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#root {{ background: {BG}; }}
QWidget#sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QWidget#page {{ background: {PANEL}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#h1 {{ font-size: 15pt; font-weight: 600; }}
QLabel#h2 {{ font-size: 11.5pt; font-weight: 600; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#chip {{ border-radius: 10px; padding: 3px 10px; font-weight: 600; }}
QLabel#stat {{ font-size: 16pt; font-weight: 600; }}
QLabel#statlbl {{ color: {MUTED}; font-size: 8.5pt; }}
QListWidget#nav {{ background: transparent; border: none; outline: none; padding: 6px; }}
QListWidget#nav::item {{ padding: 10px 12px; border-radius: 8px; margin: 2px 0; color: {MUTED}; }}
QListWidget#nav::item:hover {{ background: #1f2530; color: {TEXT}; }}
QListWidget#nav::item:selected {{ background: #223152; color: {TEXT}; }}
QPushButton {{ background: #232a35; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 14px; }}
QPushButton:hover {{ background: #2b3341; border-color: #3a4352; }}
QPushButton:pressed {{ background: #1d232c; }}
QPushButton:disabled {{ color: #5c6574; background: #1b2029; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white; font-weight: 600; padding: 9px 18px; }}
QPushButton#primary:hover {{ background: {ACCENT_2}; }}
QPushButton#primary:disabled {{ background: #2a3a5c; color: #8ea2c8; }}
QPushButton#danger {{ background: #3a1d22; border: 1px solid #6b2b33; color: #ffb3b0; }}
QPushButton#danger:hover {{ background: #4a2229; }}
QPushButton#seg {{ border-radius: 0; padding: 4px 12px; }}
QPushButton#seg:checked {{ background: #223152; border-color: {ACCENT}; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{ background: #12161c; border: 1px solid {BORDER};
    border-radius: 6px; padding: 5px 8px; selection-background-color: {ACCENT}; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 18px;
    background: #232a35; border-left: 1px solid {BORDER}; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QAbstractSpinBox::up-arrow {{ image: url(@ASSETS@/up.svg); width: 9px; height: 6px; }}
QAbstractSpinBox::down-arrow {{ image: url(@ASSETS@/down.svg); width: 9px; height: 6px; }}
QComboBox::down-arrow {{ image: url(@ASSETS@/down.svg); width: 9px; height: 6px; margin-right: 8px; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: #12161c; border: 1px solid {BORDER}; selection-background-color: #223152; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #45505f; background: #12161c; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QProgressBar {{ background: #12161c; border: 1px solid {BORDER}; border-radius: 6px; height: 12px; text-align: center; font-size: 8pt; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QPlainTextEdit, QTextEdit {{ background: #0c0e12; border: 1px solid {BORDER}; border-radius: 8px;
    font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9pt; }}
QTableWidget {{ background: #12161c; border: 1px solid {BORDER}; border-radius: 6px; gridline-color: {BORDER}; }}
QHeaderView::section {{ background: #1b2029; border: none; border-bottom: 1px solid {BORDER}; padding: 5px; color: {MUTED}; }}
QTableWidget::item:selected {{ background: #223152; }}
QSplitter::handle {{ background: {BG}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #2e3644; border-radius: 4px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: #1f2530; border: 1px solid {BORDER}; color: {TEXT}; padding: 6px; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
"""


def apply(app: QApplication):
    app.setStyle("Fusion")
    p = QPalette()
    for role, col in [(QPalette.Window, BG), (QPalette.Base, "#12161c"), (QPalette.Text, TEXT),
                      (QPalette.WindowText, TEXT), (QPalette.Button, CARD), (QPalette.ButtonText, TEXT),
                      (QPalette.Highlight, ACCENT), (QPalette.ToolTipBase, CARD), (QPalette.ToolTipText, TEXT)]:
        p.setColor(role, QColor(col))
    app.setPalette(p)
    import os
    assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")
    app.setStyleSheet(QSS.replace("@ASSETS@", assets))
