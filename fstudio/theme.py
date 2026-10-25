"""Thèmes sombre / clair et couleurs d'état."""
import os

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

PALETTES = {
    "dark": {
        "BG": "#0f1115", "PANEL": "#161a21", "CARD": "#1b2029", "BORDER": "#2a313c", "TEXT": "#e6e9ef",
        "MUTED": "#8b95a5", "ACCENT": "#4f8cff", "ACCENT_2": "#7aa7ff", "INPUT": "#12161c", "DEEP": "#0b0d11",
        "BTN": "#232a35", "BTN_HOVER": "#2b3341", "BTN_BORDER_HOVER": "#3a4352", "BTN_PRESSED": "#1d232c",
        "DISABLED": "#5c6574", "SEL": "#223152", "NAV_HOVER": "#1f2530", "SCROLL": "#2e3644",
        "CODE": "#0c0e12", "PRIMARY_DIS_BG": "#2a3a5c", "PRIMARY_DIS_TXT": "#8ea2c8",
        "DANGER_BG": "#3a1d22", "DANGER_BORDER": "#6b2b33", "DANGER_TXT": "#ffb3b0", "DANGER_HOVER": "#4a2229",
        "CHIP_ON_BG": "#123326", "CHIP_ON": "#4fd18f", "CHIP_OFF_BG": "#2a1d22", "CHIP_OFF": "#ff8c88",
        "CHECK_BORDER": "#45505f", "RING": "#1d222b",
        "pending": "#262c36", "empty": "#59616e", "skipped": "#333a46", "absent": "#151920",
    },
    "light": {
        "BG": "#eef1f5", "PANEL": "#f7f8fa", "CARD": "#ffffff", "BORDER": "#d5dbe3", "TEXT": "#1d2330",
        "MUTED": "#66707f", "ACCENT": "#2f6fe4", "ACCENT_2": "#4a86f0", "INPUT": "#ffffff", "DEEP": "#e6eaf0",
        "BTN": "#f0f2f5", "BTN_HOVER": "#e4e8ee", "BTN_BORDER_HOVER": "#c4ccd7", "BTN_PRESSED": "#d8dde5",
        "DISABLED": "#a0a8b5", "SEL": "#d6e4ff", "NAV_HOVER": "#e8ecf2", "SCROLL": "#c4ccd7",
        "CODE": "#fbfcfd", "PRIMARY_DIS_BG": "#b9cdf3", "PRIMARY_DIS_TXT": "#ffffff",
        "DANGER_BG": "#fde8e8", "DANGER_BORDER": "#f2b8b8", "DANGER_TXT": "#a12626", "DANGER_HOVER": "#fbd5d5",
        "CHIP_ON_BG": "#dff5e9", "CHIP_ON": "#157a45", "CHIP_OFF_BG": "#fde8e8", "CHIP_OFF": "#b3261e",
        "CHECK_BORDER": "#9aa4b2", "RING": "#d7dce4",
        "pending": "#dfe4eb", "empty": "#a7b0bd", "skipped": "#cfd5de", "absent": "#edf0f4",
    },
}

MODE = "dark"
BG = PANEL = CARD = BORDER = TEXT = MUTED = ACCENT = ACCENT_2 = INPUT = DEEP = BTN = BTN_HOVER = BTN_BORDER_HOVER = BTN_PRESSED = DISABLED = SEL = NAV_HOVER = SCROLL = CODE = PRIMARY_DIS_BG = PRIMARY_DIS_TXT = DANGER_BG = DANGER_BORDER = DANGER_TXT = DANGER_HOVER = CHIP_ON_BG = CHIP_ON = CHIP_OFF_BG = CHIP_OFF = CHECK_BORDER = RING = ""
STATUS = {}
LOG_COLORS = {}
STATUS_LABEL = {
    "pending": "En attente", "current": "En cours", "ok": "OK", "verified": "Vérifiée",
    "retried": "OK après relecture", "written": "Écrite", "bad": "Secteurs illisibles",
    "failed": "Échec", "empty": "Aucun secteur", "flux": "Flux capturé",
    "erased": "Effacée", "skipped": "Ignorée",
}


def set_mode(mode: str):
    """Charge une palette dans les variables du module (avant la création des widgets)."""
    global MODE
    MODE = mode if mode in PALETTES else "dark"
    pal = PALETTES[MODE]
    g = globals()
    for k, v in pal.items():
        if k.isupper():
            g[k] = v
    STATUS.clear()
    STATUS.update({
        "pending": pal["pending"], "current": pal["ACCENT"], "ok": "#34c47c" if MODE == "dark" else "#22a35f",
        "verified": "#34c47c" if MODE == "dark" else "#22a35f",
        "retried": "#e3a73b" if MODE == "dark" else "#d18a12", "written": "#2bb3c0",
        "bad": "#f0524f" if MODE == "dark" else "#d93b38", "failed": "#f0524f" if MODE == "dark" else "#d93b38",
        "empty": pal["empty"], "flux": pal["ACCENT"], "erased": "#9b7bf2", "skipped": pal["skipped"],
        "absent": pal["absent"],
    })
    LOG_COLORS.clear()
    LOG_COLORS.update({"info": pal["TEXT"], "ok": STATUS["ok"], "warn": STATUS["retried"], "err": STATUS["bad"],
                       "dim": pal["MUTED"]})


set_mode("dark")


def qc(name: str) -> QColor:
    return QColor(STATUS.get(name, name))


def qss() -> str:
    t = dict(PALETTES[MODE])
    return """
* {{ font-family: "Segoe UI Variable", "Segoe UI", "Inter", sans-serif; font-size: 10pt; color: {TEXT}; }}
QMainWindow, QWidget#root, QDialog {{ background: {BG}; }}
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
QListWidget#nav::item:hover {{ background: {NAV_HOVER}; color: {TEXT}; }}
QListWidget#nav::item:selected {{ background: {SEL}; color: {TEXT}; }}
QListWidget {{ background: {INPUT}; border: 1px solid {BORDER}; border-radius: 6px; }}
QPushButton {{ background: {BTN}; border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 14px; }}
QPushButton:hover {{ background: {BTN_HOVER}; border-color: {BTN_BORDER_HOVER}; }}
QPushButton:pressed {{ background: {BTN_PRESSED}; }}
QPushButton:disabled {{ color: {DISABLED}; background: {CARD}; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: white; font-weight: 600; padding: 9px 18px; }}
QPushButton#primary:hover {{ background: {ACCENT_2}; }}
QPushButton#primary:disabled {{ background: {PRIMARY_DIS_BG}; color: {PRIMARY_DIS_TXT}; }}
QPushButton#danger {{ background: {DANGER_BG}; border: 1px solid {DANGER_BORDER}; color: {DANGER_TXT}; }}
QPushButton#danger:hover {{ background: {DANGER_HOVER}; }}
QPushButton#seg {{ border-radius: 0; padding: 4px 12px; }}
QPushButton#seg:checked {{ background: {SEL}; border-color: {ACCENT}; }}
QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{ background: {INPUT}; border: 1px solid {BORDER};
    border-radius: 6px; padding: 5px 8px; selection-background-color: {ACCENT}; selection-color: white; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 18px;
    background: {BTN}; border-left: 1px solid {BORDER}; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 6px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 6px; }}
QAbstractSpinBox::up-arrow {{ image: url(@ASSETS@/up.svg); width: 9px; height: 6px; }}
QAbstractSpinBox::down-arrow {{ image: url(@ASSETS@/down.svg); width: 9px; height: 6px; }}
QComboBox::down-arrow {{ image: url(@ASSETS@/down.svg); width: 9px; height: 6px; margin-right: 8px; }}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {INPUT}; border: 1px solid {BORDER}; selection-background-color: {SEL}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid {CHECK_BORDER}; background: {INPUT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QProgressBar {{ background: {INPUT}; border: 1px solid {BORDER}; border-radius: 6px; height: 12px; text-align: center; font-size: 8pt; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}
QPlainTextEdit, QTextEdit, QTextBrowser {{ background: {CODE}; border: 1px solid {BORDER}; border-radius: 8px;
    font-family: "Cascadia Mono", "Consolas", monospace; font-size: 9pt; }}
QTextBrowser#help {{ font-family: "Segoe UI Variable", "Segoe UI", sans-serif; font-size: 10pt; padding: 8px; }}
QTableWidget, QTreeWidget {{ background: {INPUT}; border: 1px solid {BORDER}; border-radius: 6px; gridline-color: {BORDER}; }}
QHeaderView::section {{ background: {CARD}; border: none; border-bottom: 1px solid {BORDER}; padding: 5px; color: {MUTED}; }}
QTableWidget::item:selected, QTreeWidget::item:selected {{ background: {SEL}; color: {TEXT}; }}
QTabBar::tab {{ padding: 6px 14px; background: {CARD}; color: {MUTED}; border: none; margin-right: 2px;
    border-top-left-radius: 6px; border-top-right-radius: 6px; }}
QTabBar::tab:selected {{ background: {SEL}; color: {TEXT}; }}
QSplitter::handle {{ background: {BG}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; }}
QScrollBar::handle:vertical {{ background: {SCROLL}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:horizontal {{ background: {SCROLL}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QMenu {{ background: {CARD}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {SEL}; }}
QToolTip {{ background: {CARD}; border: 1px solid {BORDER}; color: {TEXT}; padding: 6px; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QFrame#formatbar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
QFrame#formatbar QComboBox {{ font-weight: 600; }}
QLabel#fmtnote {{ background: {CARD}; border: 1px solid {BORDER}; border-left: 3px solid {ACCENT};
    border-radius: 6px; padding: 7px 10px; }}
QFrame#banner {{ background: {CARD}; border: 1px solid {ACCENT}; border-radius: 10px; }}
""".format(**t)


def apply(app: QApplication, mode: str = None):
    if mode:
        set_mode(mode)
    app.setStyle("Fusion")
    p = QPalette()
    for role, col in [(QPalette.Window, BG), (QPalette.Base, INPUT), (QPalette.Text, TEXT),
                      (QPalette.WindowText, TEXT), (QPalette.Button, CARD), (QPalette.ButtonText, TEXT),
                      (QPalette.Highlight, ACCENT), (QPalette.ToolTipBase, CARD), (QPalette.ToolTipText, TEXT),
                      (QPalette.AlternateBase, PANEL), (QPalette.PlaceholderText, MUTED)]:
        p.setColor(role, QColor(col))
    app.setPalette(p)
    assets = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")
    app.setStyleSheet(qss().replace("@ASSETS@", assets))
