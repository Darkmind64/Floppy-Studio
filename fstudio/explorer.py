"""Explorateur de fichiers des images disque."""
from __future__ import annotations

import html
import os
import re
import shutil
import struct
import tempfile
import time
import traceback
from typing import List, Optional

from PySide6.QtCore import QMimeData, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSplitter, QStyle, QTableWidget, QTableWidgetItem,
                               QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import emulators as EM
from . import formats as F
from . import theme as T
from . import viewers as V
from .fs import Disk, Entry, FileSystem, human, open_image, write_edsk
from .fs.disk import Sec, count_bad
from .fs import detect

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_name(n: str) -> str:
    n = INVALID.sub("_", n).strip(" .") or "_"
    if n.split(".")[0].upper() in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT1"):
        n = "_" + n
    return n


def export_entries(fs: FileSystem, entries: List[Entry], dest: str, dos83: bool = False,
                   content: bool = True) -> int:
    """Exporte fichiers et dossiers (récursif). Renvoie le nombre de fichiers écrits."""
    n = 0
    for e in entries:
        name = e.meta.get("nom 8.3", e.name) if dos83 else e.name
        target = os.path.join(dest, safe_name(name))
        if e.is_dir:
            os.makedirs(target, exist_ok=True)
            n += export_entries(fs, e.children, target, dos83, content)
            continue
        base, ext = os.path.splitext(target)
        i = 1
        while os.path.exists(target):
            target = f"{base} ({i}){ext}"
            i += 1
        data = fs.content(e) if content else fs.read(e)
        with open(target, "wb") as f:
            f.write(data)
        n += 1
    return n


def native_image(disk: Disk, fs: FileSystem) -> str:
    """Image dans le format natif attendu par l'émulateur de la plateforme."""
    plat = fs.platform
    src_ext = os.path.splitext(disk.path)[1].lower()
    wanted = {"pc": (".img", ".ima"), "msx": (".dsk", ".img"), "atarist": (".st", ".msa"),
              "amiga": (".adf",), "c64": (".d64", ".d71", ".d81"), "thomson": (".fd",),
              "cpc": (".dsk", ".edsk"), "apple2": (".dsk", ".do", ".po", ".2mg")}.get(plat, (".img",))
    d = os.path.join(EM.session_dir(), "images")
    os.makedirs(d, exist_ok=True)
    base = re.sub(r"[^A-Za-z0-9_-]", "_", os.path.splitext(os.path.basename(disk.path))[0])[:40]
    if src_ext in wanted and (plat != "cpc" or disk.kind in ("edsk", "dsk")):
        out = os.path.join(d, base + src_ext)
        shutil.copyfile(disk.path, out)
        return out
    ext = wanted[0]
    if plat == "c64":
        ext = {"1541": ".d64", "1571": ".d71", "1581": ".d81"}.get(getattr(fs, "model", ""), ".d64")
    out = os.path.join(d, base + ext)
    if plat == "cpc":
        write_edsk(disk, out)
    elif plat == "thomson":
        with open(out, "wb") as f:
            f.write(disk.linear(heads=list(range(disk.heads)), sequential=True))
    else:
        with open(out, "wb") as f:
            f.write(disk.linear())
    return out


# --------------------------------------------------------------------------
class LoadJob(QThread):
    loaded = Signal(object, object)          # Disk, [FileSystem]
    failed = Signal(str)

    def __init__(self, path: str, fmt: Optional[str]):
        super().__init__()
        self.path, self.fmt = path, fmt

    def run(self):
        try:
            disk, vols = open_image(self.path, self.fmt)
            self.loaded.emit(disk, vols)
        except Exception as e:
            self.failed.emit(f"{e}\n{traceback.format_exc()}")


class SortItem(QTreeWidgetItem):
    def __lt__(self, other):
        col = self.treeWidget().sortColumn() if self.treeWidget() else 0
        a, b = self.data(0, Qt.UserRole), other.data(0, Qt.UserRole)
        if a is not None and b is not None and a.is_dir != b.is_dir:
            return a.is_dir
        if col == 1 and a is not None and b is not None:
            return a.size < b.size
        return self.text(col).lower() < other.text(col).lower()


class FileTree(QTreeWidget):
    """Arborescence avec glisser-déposer vers / depuis l'Explorateur Windows."""
    drag_export = None   # callable(entries) -> list[path]
    drop_import = None   # callable(paths, entry_cible) -> None ; None = import refusé

    def _ext_drop(self, e) -> bool:
        return bool(self.drop_import and e.mimeData().hasUrls() and e.source() is None)

    def dragEnterEvent(self, e):
        if self._ext_drop(e):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if self._ext_drop(e):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if self._ext_drop(e):
            it = self.itemAt(e.position().toPoint())
            target = it.data(0, Qt.UserRole) if it else None
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            e.acceptProposedAction()
            self.drop_import(paths, target)
        else:
            e.ignore()

    def startDrag(self, actions):
        items = self.selectedItems()
        entries = [it.data(0, Qt.UserRole) for it in items if it.data(0, Qt.UserRole)]
        if not entries or not self.drag_export:
            return
        paths = self.drag_export(entries)
        if not paths:
            return
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(p) for p in paths])
        drag = QDrag(self)
        drag.setMimeData(md)
        drag.exec(Qt.CopyAction)


class ImageView(QScrollArea):
    def __init__(self, img: QImage):
        super().__init__()
        self.img = img
        self.setAlignment(Qt.AlignCenter)
        self.lbl = QLabel()
        self.lbl.setAlignment(Qt.AlignCenter)
        self.setWidget(self.lbl)
        self.setWidgetResizable(True)
        self.setStyleSheet(f"background:{T.DEEP};")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        avail = self.viewport().size() - QSize(16, 16)
        pm = QPixmap.fromImage(self.img)
        w, h = self.img.width(), self.img.height()
        k = min(avail.width() / max(w, 1), avail.height() / max(h, 1))
        k = max(1, int(k)) if k >= 1 else k
        self.lbl.setPixmap(pm.scaled(int(w * k), int(h * k), Qt.KeepAspectRatio,
                                     Qt.FastTransformation if k >= 1 else Qt.SmoothTransformation))


class AudioView(QWidget):
    def __init__(self, wav: bytes):
        super().__init__()
        self.wav = wav
        v = QVBoxLayout(self)
        self.wave = WaveWidget(wav)
        v.addWidget(self.wave, 1)
        row = QHBoxLayout()
        self.btn = QPushButton("▶  Lire")
        self.btn.clicked.connect(self.toggle)
        self.lbl = QLabel(self.wave.desc)
        self.lbl.setObjectName("muted")
        row.addWidget(self.btn)
        row.addWidget(self.lbl, 1)
        v.addLayout(row)
        self.player = None
        self.path = os.path.join(EM.session_dir(), f"preview_{int(time.time() * 1000)}.wav")
        with open(self.path, "wb") as f:
            f.write(wav)

    def toggle(self):
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except Exception:
            os.startfile(self.path) if hasattr(os, "startfile") else None
            return
        if self.player is None:
            self.player = QMediaPlayer(self)
            self.out = QAudioOutput(self)
            self.player.setAudioOutput(self.out)
            self.player.setSource(QUrl.fromLocalFile(self.path))
            self.player.playbackStateChanged.connect(
                lambda st: self.btn.setText("■  Stop" if st == QMediaPlayer.PlayingState else "▶  Lire"))
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.stop()
        else:
            self.player.play()

    def stop(self):
        if self.player:
            self.player.stop()


class WaveWidget(QWidget):
    def __init__(self, wav: bytes):
        super().__init__()
        self.setMinimumHeight(120)
        self.samples: List[float] = []
        self.desc = ""
        try:
            pos, fmt, data = 12, None, b""
            while pos + 8 <= len(wav):
                cid, size = wav[pos:pos + 4], struct.unpack("<I", wav[pos + 4:pos + 8])[0]
                if cid == b"fmt ":
                    fmt = struct.unpack("<HHIIHH", wav[pos + 8:pos + 24])
                elif cid == b"data":
                    data = wav[pos + 8:pos + 8 + size]
                pos += 8 + size + (size & 1)
            _, ch, rate, _, ba, bits = fmt
            n = len(data) // ba
            step = max(1, n // 2000)
            for i in range(0, n, step):
                o = i * ba
                if bits == 16:
                    v = struct.unpack_from("<h", data, o)[0] / 32768
                else:
                    v = (data[o] - 128) / 128
                self.samples.append(v)
            self.desc = f"{rate} Hz · {bits} bits · {'stéréo' if ch == 2 else 'mono'} · {n / rate:.2f} s"
        except Exception:
            self.desc = "WAV"

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(T.DEEP))
        if not self.samples:
            return
        p.setPen(QPen(QColor(T.ACCENT), 1))
        w, h = self.width(), self.height()
        mid = h / 2
        n = len(self.samples)
        for x in range(w):
            a = int(x * n / w)
            b = max(a + 1, int((x + 1) * n / w))
            seg = self.samples[a:b]
            lo, hi = min(seg), max(seg)
            p.drawLine(x, int(mid - hi * mid * 0.95), x, int(mid - lo * mid * 0.95))


# --------------------------------------------------------------------------
def mono_edit(txt: str = "", wrap: bool = False) -> QPlainTextEdit:
    w = QPlainTextEdit()
    w.setReadOnly(True)
    w.setLineWrapMode(QPlainTextEdit.WidgetWidth if wrap else QPlainTextEdit.NoWrap)
    f = QFont("Cascadia Mono")
    f.setStyleHint(QFont.Monospace)
    f.setPointSizeF(9.5)
    w.setFont(f)
    w.setPlainText(txt)
    return w


def _charset_combo(cs: str) -> QComboBox:
    cb = QComboBox()
    for label, code in V.CHARSETS:
        cb.addItem(label, code)
    i = next((k for k, (_, c) in enumerate(V.CHARSETS) if c == cs), 0)
    cb.setCurrentIndex(i)
    return cb


class TextPane(QWidget):
    """Texte avec choix du jeu de caractères et du retour à la ligne."""

    def __init__(self, data: bytes, charset: str, note: str = ""):
        super().__init__()
        self.data = data
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Jeu de caractères :"))
        self.cs = _charset_combo(charset)
        self.cs.currentIndexChanged.connect(self._render)
        bar.addWidget(self.cs)
        self.wrap = QPushButton("↩  Retour à la ligne")
        self.wrap.setCheckable(True)
        self.wrap.toggled.connect(lambda on: self.edit.setLineWrapMode(
            QPlainTextEdit.WidgetWidth if on else QPlainTextEdit.NoWrap))
        bar.addWidget(self.wrap)
        bar.addStretch()
        if note:
            n = QLabel(note)
            n.setObjectName("muted")
            bar.addWidget(n)
        v.addLayout(bar)
        self.edit = mono_edit()
        v.addWidget(self.edit, 1)
        self._render()

    def _render(self):
        txt = V.decode_text(self.data[:V.TEXT_LIMIT], self.cs.currentData())
        if len(self.data) > V.TEXT_LIMIT:
            txt += f"\n… ({len(self.data) - V.TEXT_LIMIT} octets non affichés)"
        self.edit.setPlainText(V.flow(txt, 256))


class HexPane(QWidget):
    """Hexadécimal : hexa + texte, hexa seul ou texte seul."""
    MODES = ["Hexa + texte", "Hexa seul", "Texte seul"]
    mode_memo = 0

    def __init__(self, data: bytes, charset: str, limit: int = V.HEX_LIMIT):
        super().__init__()
        self.data, self.limit = data, limit
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Affichage :"))
        self.mode = QComboBox()
        self.mode.addItems(self.MODES)
        self.mode.setCurrentIndex(HexPane.mode_memo)
        self.mode.currentIndexChanged.connect(self._render)
        bar.addWidget(self.mode)
        self.cs_lbl = QLabel("Jeu :")
        bar.addWidget(self.cs_lbl)
        self.cs = _charset_combo(charset)
        self.cs.currentIndexChanged.connect(self._render)
        bar.addWidget(self.cs)
        bar.addStretch()
        info = QLabel(f"{len(data)} octets")
        info.setObjectName("muted")
        bar.addWidget(info)
        v.addLayout(bar)
        self.edit = mono_edit()
        v.addWidget(self.edit, 1)
        self._render()

    def _render(self):
        m = self.mode.currentIndex()
        HexPane.mode_memo = m
        self.cs.setVisible(m == 2)
        self.cs_lbl.setVisible(m == 2)
        if m == 2:
            lim = min(self.limit, V.TEXT_LIMIT)
            txt = V.decode_text(self.data[:lim], self.cs.currentData())
            if len(self.data) > lim:
                txt += f"\n… ({len(self.data) - lim} octets non affichés)"
            self.edit.setLineWrapMode(QPlainTextEdit.NoWrap)
            self.edit.setPlainText(V.flow(txt, 128))
        else:
            self.edit.setLineWrapMode(QPlainTextEdit.NoWrap)
            self.edit.setPlainText(V.hexdump(self.data, self.limit, ascii_col=m == 0))


# --------------------------------------------------------------------------
# Carte d'occupation du volume
# --------------------------------------------------------------------------
OCC_COLORS = {"sys": "#4c78d8", "free": "#20262f", "bad": "#f0524f", "used": "#6b7280"}
if T.MODE == "light":
    OCC_COLORS.update({"free": "#e3e7ed", "used": "#9aa3b0"})


class OccupancyMap(QWidget):
    entry_clicked = Signal(object)

    def __init__(self, unit: int, owners: list, highlight: Optional[Entry] = None):
        super().__init__()
        self.unit, self.own, self.hl = unit, owners, highlight
        self.setMouseTracking(True)
        self.setMinimumHeight(120)
        self._colors = {}

    def _color(self, o) -> QColor:
        if isinstance(o, str):
            return QColor(OCC_COLORS.get(o, "#6b7280"))
        if o is self.hl:
            return QColor("#ffd54a")
        k = id(o)
        if k not in self._colors:
            h = (hash(o.path) * 2654435761) % 360
            c = QColor()
            c.setHsv(h, 120 if self.hl else 150, 150 if self.hl else 210)
            self._colors[k] = c
        return self._colors[k]

    def _geom(self):
        n = max(len(self.own), 1)
        w, h = max(self.width() - 4, 10), max(self.height() - 4, 10)
        side = max(3, int((w * h / n) ** 0.5))
        while side > 3 and (w // side) * (h // side) < n:
            side -= 1
        cols = max(1, w // side)
        return side, cols

    def paintEvent(self, _):
        p = QPainter(self)
        side, cols = self._geom()
        gap = 1 if side > 4 else 0
        for i, o in enumerate(self.own):
            r, c = divmod(i, cols)
            p.fillRect(2 + c * side, 2 + r * side, side - gap, side - gap, self._color(o))

    def _at(self, pos) -> Optional[int]:
        side, cols = self._geom()
        c, r = int((pos.x() - 2) // side), int((pos.y() - 2) // side)
        if c < 0 or c >= cols or r < 0:
            return None
        i = r * cols + c
        return i if i < len(self.own) else None

    def mouseMoveEvent(self, e):
        i = self._at(e.position())
        if i is None:
            return
        o = self.own[i]
        what = {"sys": "système (amorce, FAT, répertoire…)", "free": "libre", "bad": "illisible",
                "used": "occupé (aucun fichier connu : perdu ou réservé)"}.get(o) if isinstance(o, str) \
            else "/" + o.path
        from PySide6.QtWidgets import QToolTip
        QToolTip.showText(e.globalPosition().toPoint(),
                          f"Unité {i} · octets {i * self.unit}–{(i + 1) * self.unit - 1}<br>{html.escape(what)}", self)

    def mousePressEvent(self, e):
        i = self._at(e.position())
        if i is not None and not isinstance(self.own[i], str):
            self.entry_clicked.emit(self.own[i])


def occupancy_panel(fs: FileSystem, alloc, highlight: Optional[Entry], on_click) -> QWidget:
    unit, own = alloc
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 6, 0, 0)
    cnt = {"sys": 0, "free": 0, "bad": 0, "used": 0, "file": 0}
    for o in own:
        cnt[o if isinstance(o, str) else "file"] += 1
    parts = []
    for k, lbl in (("file", "Fichiers"), ("sys", "Système"), ("free", "Libre"), ("used", "Occupé sans fichier"),
                   ("bad", "Illisible")):
        if cnt[k] or k in ("file", "free"):
            col = "#c792ea" if k == "file" else OCC_COLORS[k]
            parts.append(f"<span style='color:{col}'>■</span>&nbsp;{lbl}&nbsp;: {cnt[k]} ({human(cnt[k] * unit)})")
    legend = QLabel(" &nbsp; ".join(parts))
    legend.setWordWrap(True)
    v.addWidget(legend)
    if highlight is not None:
        n = sum(1 for o in own if o is highlight)
        idx = [i for i, o in enumerate(own) if o is highlight]
        frag = sum(1 for a, b in zip(idx, idx[1:]) if b != a + 1)
        v.addWidget(QLabel(f"<span style='color:#ffd54a'>■</span> {html.escape(highlight.name)} : {n} unité(s) "
                           f"de {unit} o" + (f", {frag + 1} fragments" if frag else ", contigu")))
    m = OccupancyMap(unit, own, highlight)
    m.entry_clicked.connect(on_click)
    v.addWidget(m, 1)
    return w


class DisasmPane(QWidget):
    def __init__(self, data: bytes, cpu: str, org: int, note: str = ""):
        super().__init__()
        from . import disasm as DA
        self.DA, self.data = DA, data
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Processeur :"))
        self.cpu = QComboBox()
        for label, code in DA.CPUS:
            self.cpu.addItem(label, code)
        self.cpu.setCurrentIndex(max(0, self.cpu.findData(cpu)))
        bar.addWidget(self.cpu)
        bar.addWidget(QLabel("Adresse :"))
        self.org = QLineEdit(f"{org:04X}")
        self.org.setFixedWidth(80)
        bar.addWidget(self.org)
        bar.addWidget(QLabel("Décalage :"))
        self.skip = QLineEdit("0")
        self.skip.setFixedWidth(60)
        self.skip.setToolTip("Octets à ignorer au début (en-tête)")
        bar.addWidget(self.skip)
        b = QPushButton("↻")
        b.setFixedWidth(34)
        b.clicked.connect(self._render)
        bar.addWidget(b)
        bar.addStretch()
        if note:
            n = QLabel(note)
            n.setObjectName("muted")
            bar.addWidget(n)
        v.addLayout(bar)
        self.edit = mono_edit()
        v.addWidget(self.edit, 1)
        self.cpu.currentIndexChanged.connect(self._render)
        self.org.returnPressed.connect(self._render)
        self.skip.returnPressed.connect(self._render)
        self._render()

    def _render(self):
        try:
            org = int(self.org.text().strip().lstrip("&$#").removesuffix("h") or "0", 16)
            skip = int(self.skip.text().strip() or "0", 0)
        except ValueError:
            org, skip = 0, 0
        self.edit.setPlainText(self.DA.disassemble(self.cpu.currentData(), self.data[skip:], org))


# --------------------------------------------------------------------------
# Recherche
# --------------------------------------------------------------------------
def locate(disk: Disk, offset: int) -> str:
    """Position linéaire → piste / face / secteur."""
    if not disk.tracks:
        return f"+{offset}"
    pos = 0
    for c in range(disk.cyls):
        for h in range(disk.heads):
            secs = sorted({s.r: s for s in disk.track(c, h)}.values(), key=lambda s: s.r)
            for s in secs:
                size = 128 << s.n if s.n < 8 else len(s.data or b"")
                if pos <= offset < pos + size:
                    return f"piste {c} · face {h} · secteur {s.r} (+{offset - pos})"
                pos += size
    return f"+{offset}"


class SearchDialog(QDialog):
    goto = Signal(object)

    def __init__(self, parent, disk: Disk, fs: Optional[FileSystem]):
        super().__init__(parent)
        self.disk, self.fs = disk, fs
        self.setWindowTitle("Rechercher dans l'image")
        self.resize(760, 480)
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Texte, ou octets hexa (ex. 4E 71 00)")
        self.mode = QComboBox()
        self.mode.addItems(["Texte (sans casse)", "Texte exact", "Hexadécimal"])
        b = QPushButton("🔎  Rechercher")
        b.setObjectName("primary")
        b.clicked.connect(self.run)
        self.q.returnPressed.connect(self.run)
        bar.addWidget(self.q, 1)
        bar.addWidget(self.mode)
        bar.addWidget(b)
        v.addLayout(bar)
        self.t = QTableWidget(0, 3)
        self.t.setHorizontalHeaderLabels(["Emplacement", "Position", "Contexte"])
        self.t.verticalHeader().hide()
        self.t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.t.cellDoubleClicked.connect(self._open)
        v.addWidget(self.t, 1)
        self.info = QLabel("")
        self.info.setObjectName("muted")
        v.addWidget(self.info)
        self.hits = []

    def _needle(self):
        txt = self.q.text()
        m = self.mode.currentIndex()
        if m == 2:
            return bytes.fromhex(re.sub(r"[^0-9A-Fa-f]", "", txt)), False
        return txt.encode("latin-1", "replace"), m == 0

    @staticmethod
    def _find(hay: bytes, needle: bytes, nocase: bool, limit=500):
        if nocase:
            hay, needle = hay.lower(), needle.lower()
        out, p = [], hay.find(needle)
        while p >= 0 and len(out) < limit:
            out.append(p)
            p = hay.find(needle, p + 1)
        return out

    def run(self):
        try:
            needle, nocase = self._needle()
        except ValueError:
            self.info.setText("Hexadécimal invalide.")
            return
        if not needle:
            return
        self.hits = []
        if self.fs:
            for e in self.fs.files:
                try:
                    d = self.fs.read(e)
                except Exception:
                    continue
                for p in self._find(d, needle, nocase, 50):
                    self.hits.append((e, f"/{e.path}", f"+{p} (0x{p:X})", d[max(0, p - 16):p + len(needle) + 16]))
        raw = self.disk.linear()
        for p in self._find(raw, needle, nocase, 300):
            self.hits.append((None, "Image brute", locate(self.disk, p), raw[max(0, p - 16):p + len(needle) + 16]))
        self.t.setRowCount(len(self.hits))
        for i, (e, where, pos, ctx) in enumerate(self.hits):
            c = "".join(chr(x) if 32 <= x < 127 else "·" for x in ctx)
            for k, val in enumerate((where, pos, c)):
                self.t.setItem(i, k, QTableWidgetItem(val))
        self.t.resizeColumnToContents(0)
        self.t.resizeColumnToContents(1)
        self.info.setText(f"{len(self.hits)} occurrence(s). Double-clic : ouvrir le fichier.")

    def _open(self, r, _c):
        e = self.hits[r][0]
        if e is not None:
            self.goto.emit(e)


# --------------------------------------------------------------------------
# Éditeur de secteurs
# --------------------------------------------------------------------------
class SectorEditor(QDialog):
    changed = Signal()
    write_track = Signal(int, int)

    def __init__(self, parent, disk: Disk):
        super().__init__(parent)
        self.disk = disk
        self.setWindowTitle("Éditeur de secteurs")
        self.resize(820, 600)
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.cyl, self.head, self.sec = QComboBox(), QComboBox(), QComboBox()
        cyls = sorted({c for c, _ in disk.tracks})
        for c in cyls:
            self.cyl.addItem(str(c), c)
        for h in sorted({h for _, h in disk.tracks}):
            self.head.addItem(str(h), h)
        for lab, w in (("Piste", self.cyl), ("Face", self.head), ("Secteur", self.sec)):
            bar.addWidget(QLabel(lab))
            bar.addWidget(w)
        bprev, bnext = QPushButton("◀"), QPushButton("▶")
        bprev.setFixedWidth(34)
        bnext.setFixedWidth(34)
        bprev.clicked.connect(lambda: self._step(-1))
        bnext.clicked.connect(lambda: self._step(1))
        bar.addWidget(bprev)
        bar.addWidget(bnext)
        bar.addStretch()
        self.state = QLabel("")
        bar.addWidget(self.state)
        v.addLayout(bar)
        self.edit = mono_edit()
        self.edit.setReadOnly(False)
        v.addWidget(self.edit, 1)
        v.addWidget(_muted_label("Modifiez les octets hexadécimaux (la colonne texte est ignorée), puis "
                                 "« Appliquer ». L'image n'est modifiée sur disque qu'à l'enregistrement."))
        bb = QHBoxLayout()
        ba = QPushButton("✔  Appliquer au secteur")
        ba.setObjectName("primary")
        ba.clicked.connect(self.apply)
        bw = QPushButton("📤  Écrire cette piste sur la disquette")
        bw.clicked.connect(lambda: self.write_track.emit(self.cyl.currentData(), self.head.currentData()))
        bc = QPushButton("Fermer")
        bc.clicked.connect(self.accept)
        bb.addWidget(ba)
        bb.addWidget(bw)
        bb.addStretch()
        bb.addWidget(bc)
        v.addLayout(bb)
        self.cyl.currentIndexChanged.connect(self._fill_secs)
        self.head.currentIndexChanged.connect(self._fill_secs)
        self.sec.currentIndexChanged.connect(self._show)
        self._fill_secs()

    def _secs(self):
        return sorted(self.disk.track(self.cyl.currentData(), self.head.currentData()), key=lambda s: s.r)

    def _fill_secs(self):
        self.sec.blockSignals(True)
        self.sec.clear()
        for s in self._secs():
            self.sec.addItem(f"{s.r} (0x{s.r:02X})" + ("" if s.ok else " ⚠"), s.r)
        self.sec.blockSignals(False)
        self._show()

    def _step(self, d):
        i = self.sec.currentIndex() + d
        if 0 <= i < self.sec.count():
            self.sec.setCurrentIndex(i)
            return
        j = self.cyl.currentIndex() + d
        if 0 <= j < self.cyl.count():
            self.cyl.setCurrentIndex(j)
            self.sec.setCurrentIndex(0 if d > 0 else self.sec.count() - 1)

    def _cur(self) -> Optional[Sec]:
        return self.disk.sector(self.cyl.currentData(), self.head.currentData(), self.sec.currentData())

    def _show(self):
        s = self._cur()
        if s is None:
            self.edit.setPlainText("")
            return
        size = 128 << s.n if s.n < 8 else len(s.data or b"")
        data = (s.data or b"")[:size].ljust(size, b"\0")
        self.state.setText(f"{size} octets · " + ("OK" if s.ok else "<span style='color:#f0524f'>illisible</span>"))
        self.edit.setPlainText(V.hexdump(data, size))

    def apply(self):
        s = self._cur()
        if s is None:
            return
        size = 128 << s.n if s.n < 8 else len(s.data or b"")
        out = bytearray()
        try:
            for line in self.edit.toPlainText().splitlines():
                line = line.strip()
                if not line or line.startswith("…"):
                    continue
                body = line[8:57] if len(line) > 8 else ""
                out += bytes.fromhex(body.replace(" ", ""))
        except ValueError as ex:
            QMessageBox.warning(self, "Éditeur", f"Octets invalides : {ex}")
            return
        if len(out) != size:
            QMessageBox.warning(self, "Éditeur", f"{len(out)} octets au lieu de {size}.")
            return
        s.data, s.ok = bytes(out), True
        self.disk.raw = None
        self.changed.emit()
        self._show()


def _muted_label(t: str) -> QLabel:
    l = QLabel(t)
    l.setObjectName("muted")
    l.setWordWrap(True)
    return l


class EmulatorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Émulateurs")
        self.resize(980, 420)
        self.cfg = EM.EmuConfig()
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Chemins des émulateurs et arguments. Variables : {image}, {file}, {dir}."))
        self.t = QTableWidget(len(self.cfg.emus), 4)
        self.t.setHorizontalHeaderLabels(["Plateforme", "Exécutable", "Arguments (image)", "Arguments (fichier)"])
        self.t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.t.verticalHeader().hide()
        self.keys = list(self.cfg.emus)
        for r, k in enumerate(self.keys):
            e = self.cfg.emus[k]
            it = QTableWidgetItem(f"{EM.PLATFORM_NAMES.get(k, k)}\n{e.name}")
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            it.setToolTip(e.url)
            self.t.setItem(r, 0, it)
            self.t.setItem(r, 1, QTableWidgetItem(e.exe))
            self.t.setItem(r, 2, QTableWidgetItem(e.args_image))
            self.t.setItem(r, 3, QTableWidgetItem(e.args_file))
        self.t.resizeRowsToContents()
        self.t.cellDoubleClicked.connect(self._browse)
        v.addWidget(self.t, 1)
        row = QHBoxLayout()
        b = QPushButton("🔎  Détection automatique")
        b.clicked.connect(self._auto)
        row.addWidget(b)
        row.addWidget(QLabel("Double-clic sur « Exécutable » pour choisir le fichier."))
        row.addStretch()
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _browse(self, r, c):
        if c != 1:
            return
        p, _ = QFileDialog.getOpenFileName(self, "Exécutable de l'émulateur", "", "Programmes (*.exe)")
        if p:
            self.t.item(r, 1).setText(p)

    def _auto(self):
        self._collect()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            found = self.cfg.autodetect()
        finally:
            QApplication.restoreOverrideCursor()
        for r, k in enumerate(self.keys):
            self.t.item(r, 1).setText(self.cfg.emus[k].exe)
        QMessageBox.information(self, "Détection", "\n".join(found) if found else
                                "Aucun nouvel émulateur trouvé dans les emplacements usuels.")

    def _collect(self):
        for r, k in enumerate(self.keys):
            e = self.cfg.emus[k]
            e.exe = self.t.item(r, 1).text().strip()
            e.args_image = self.t.item(r, 2).text()
            e.args_file = self.t.item(r, 3).text()

    def _save(self):
        self._collect()
        self.cfg.save()
        self.accept()


# --------------------------------------------------------------------------
class ExplorerView(QWidget):
    log = Signal(str, str)
    write_request = Signal(str, str, str)     # chemin image, format greaseweazle, pistes
    loaded_path = Signal(str)                 # image ouverte avec succès (pour le catalogue)

    def __init__(self):
        super().__init__()
        self.disk: Optional[Disk] = None
        self.vols: List[FileSystem] = []
        self.fs: Optional[FileSystem] = None
        self.job: Optional[LoadJob] = None
        self.cur: Optional[Entry] = None
        self.previews: List[V.Preview] = []

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 10)
        v.setSpacing(10)

        head = QFrame()
        head.setObjectName("card")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 10, 14, 10)
        col = QVBoxLayout()
        self.title = QLabel("Aucune image ouverte")
        self.title.setObjectName("h2")
        self.sub = QLabel("Ouvrez une image (IMG, ADF, ST, D64, FD, DSK, HFE, SCP…) ou lisez une disquette.")
        self.sub.setObjectName("muted")
        self.sub.setWordWrap(True)
        col.addWidget(self.title)
        col.addWidget(self.sub)
        hl.addLayout(col, 1)
        self.vol_cb = QComboBox()
        self.vol_cb.setVisible(False)
        self.vol_cb.currentIndexChanged.connect(self._select_volume)
        hl.addWidget(self.vol_cb)
        v.addWidget(head)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.b_export = QPushButton("💾  Exporter…")
        self.b_export.setToolTip("Exporte la sélection (ou tout le disque si rien n'est sélectionné)")
        self.b_export.clicked.connect(self.export_selected)
        self.b_conv = QPushButton("🖼  Exporter converti…")
        self.b_conv.setToolTip("Image → PNG, son → WAV, BASIC/texte → TXT")
        self.b_conv.clicked.connect(self.export_converted)
        self.b_open = QPushButton("↗  Ouvrir avec Windows")
        self.b_open.clicked.connect(self.open_external)
        self.b_run = QPushButton("▶  Exécuter")
        self.b_run.setObjectName("primary")
        self.b_run.clicked.connect(self.run_file)
        self.b_boot = QPushButton("🕹  Lancer l'image dans l'émulateur")
        self.b_boot.clicked.connect(self.run_image)
        self.b_emus = QPushButton("⚙")
        self.b_emus.setToolTip("Configurer les émulateurs")
        self.b_emus.setFixedWidth(40)
        self.b_emus.clicked.connect(self.configure_emulators)
        for b in (self.b_export, self.b_conv, self.b_open, self.b_run, self.b_boot):
            bar.addWidget(b)
        bar.addStretch()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtrer…")
        self.filter.setFixedWidth(170)
        self.filter.textChanged.connect(self._apply_filter)
        bar.addWidget(self.filter)
        bar.addWidget(self.b_emus)
        v.addLayout(bar)

        ebar = QHBoxLayout()
        ebar.setSpacing(6)
        self.b_add = QPushButton("➕  Ajouter des fichiers…")
        self.b_add.setToolTip("Copie des fichiers dans l'image (ou glissez-les sur l'arborescence)")
        self.b_add.clicked.connect(self.add_files)
        self.b_mkdir = QPushButton("📁  Nouveau dossier")
        self.b_mkdir.clicked.connect(self.make_dir)
        self.b_del = QPushButton("🗑  Supprimer")
        self.b_del.clicked.connect(self.delete_selected)
        self.b_save = QPushButton("💾  Enregistrer l'image sous…")
        self.b_save.clicked.connect(self.save_image)
        self.b_write = QPushButton("📤  Écrire sur la disquette")
        self.b_write.clicked.connect(self.write_disk)
        self.mod_lbl = QLabel("")
        self.mod_lbl.setStyleSheet(f"color:{T.STATUS['retried']}")
        for b in (self.b_add, self.b_mkdir, self.b_del, self.b_save, self.b_write):
            ebar.addWidget(b)
        ebar.addSpacing(12)
        self.b_occ = QPushButton("🗺  Occupation")
        self.b_occ.setToolTip("Carte d'occupation du volume (clic : sélectionne le fichier)")
        self.b_occ.clicked.connect(self.show_occupancy)
        self.b_search = QPushButton("🔎  Rechercher…")
        self.b_search.setToolTip("Recherche d'un texte ou d'octets dans les fichiers et toute l'image")
        self.b_search.clicked.connect(self.search)
        self.b_sect = QPushButton("🧩  Secteurs…")
        self.b_sect.setToolTip("Éditeur hexadécimal des secteurs, écriture d'une piste sur la disquette")
        self.b_sect.clicked.connect(self.edit_sectors)
        for b in (self.b_occ, self.b_search, self.b_sect):
            ebar.addWidget(b)
        ebar.addWidget(self.mod_lbl)
        ebar.addStretch()
        v.addLayout(ebar)
        self.modified = False
        self._disk_dirty = False
        self._alloc = None

        split = QSplitter(Qt.Horizontal)
        split.setHandleWidth(8)
        tcard = QFrame()
        tcard.setObjectName("card")
        tl = QVBoxLayout(tcard)
        tl.setContentsMargins(8, 8, 8, 8)
        self.tree = FileTree()
        self.tree.drag_export = self._drag_paths
        self.tree.setAcceptDrops(True)
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Nom", "Taille", "Type", "Date"])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setDragEnabled(True)
        self.tree.setDragDropMode(QAbstractItemView.DragDrop)
        self.tree.setSortingEnabled(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setStyleSheet(f"QTreeWidget{{background:{T.INPUT};border:none;}}"
                                "QTreeWidget::item{padding:3px 2px;}")
        self.tree.currentItemChanged.connect(self._on_current)
        self.tree.itemDoubleClicked.connect(self._on_double)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        tl.addWidget(self.tree, 1)
        self.stats = QLabel("")
        self.stats.setObjectName("muted")
        tl.addWidget(self.stats)
        split.addWidget(tcard)

        pcard = QFrame()
        pcard.setObjectName("card")
        pl = QVBoxLayout(pcard)
        pl.setContentsMargins(8, 8, 8, 8)
        self.ptitle = QLabel("Aperçu")
        self.ptitle.setObjectName("h2")
        pl.addWidget(self.ptitle)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        pass
        pl.addWidget(self.tabs, 1)
        split.addWidget(pcard)
        split.setSizes([520, 560])
        v.addWidget(split, 1)
        self._update_buttons()

    # ---------------------------------------------------------------- Chargement
    def open_path(self, path: str, fmt: Optional[str] = None):
        if self.job and self.job.isRunning():
            return
        if self.modified and QMessageBox.question(
                self, "Image modifiée", "Les modifications de l'image ouverte ne sont pas enregistrées. "
                "Les abandonner ?") != QMessageBox.Yes:
            return
        self.modified = False
        self._disk_dirty = False
        self.title.setText(os.path.basename(path))
        self.sub.setText("Analyse de l'image…")
        self.tree.clear()
        self._clear_preview()
        QApplication.setOverrideCursor(Qt.BusyCursor)
        self.job = LoadJob(path, fmt)
        self.job.loaded.connect(self._loaded)
        self.job.failed.connect(self._failed)
        self.job.finished.connect(QApplication.restoreOverrideCursor)
        self.job.start()

    def _failed(self, msg: str):
        self.sub.setText("Impossible de lire l'image : " + msg.splitlines()[0])
        self.log.emit("Explorateur : " + msg.splitlines()[0], "err")

    def _loaded(self, disk: Disk, vols: List[FileSystem]):
        self.disk, self.vols = disk, vols
        self.vol_cb.blockSignals(True)
        self.vol_cb.clear()
        for fs in vols:
            self.vol_cb.addItem(fs.title())
        self.vol_cb.setVisible(len(vols) > 1)
        self.vol_cb.blockSignals(False)
        if not vols:
            self.fs = None
            bad = disk.bad_sectors()
            self.sub.setText("Aucun système de fichiers reconnu" +
                             (f" — {bad} secteur(s) illisible(s)" if bad else "") +
                             ". Format propriétaire, protégé ou disquette vierge : utilisez l'onglet Hexa.")
            self._show_raw_disk()
            self.log.emit(f"Explorateur : {os.path.basename(disk.path)} — système de fichiers non reconnu", "warn")
            self._update_buttons()
            return
        self._select_volume(0)
        self.loaded_path.emit(disk.path)
        sel = getattr(self, "pending_select", None)
        self.pending_select = None
        if sel:
            for k, fs in enumerate(vols):
                for e in fs.root.walk():
                    if sel == e.path or sel.endswith("/" + e.path) and (fs.volume_name + "/" + e.path) == sel:
                        if k != self.vol_cb.currentIndex():
                            self.vol_cb.setCurrentIndex(k)
                        self.goto_entry(e)
                        break
        names = ", ".join(fs.title() for fs in vols)
        self.log.emit(f"Explorateur : {os.path.basename(disk.path)} — {names}", "ok")

    def _select_volume(self, i: int):
        if not (0 <= i < len(self.vols)):
            return
        self.fs = fs = self.vols[i]
        self._alloc = None
        self.tree.drop_import = self._drop_import if fs.writable else None
        self.title.setText(f"{os.path.basename(self.disk.path)} — {fs.title()}")
        bits = [f"{k} : {v}" for k, v in fs.info if k not in ("Système",)]
        bad = self.disk.bad_sectors()
        if bad:
            bits.append(f"<span style='color:{T.STATUS['bad']}'>{bad} secteur(s) illisible(s)</span>")
        if self.disk.notes:
            bits += self.disk.notes
        self.sub.setText(" · ".join(bits))
        self.sub.setTextFormat(Qt.RichText)
        self._fill_tree()
        self._update_buttons()

    def _fill_tree(self):
        self.tree.setSortingEnabled(False)
        self.tree.clear()
        st = self.style()
        icon_dir, icon_file = st.standardIcon(QStyle.SP_DirIcon), st.standardIcon(QStyle.SP_FileIcon)

        def add(parent_item, e: Entry):
            it = SortItem(parent_item, [e.name, "" if e.is_dir else human(e.size),
                                               e.kind, e.date])
            it.setData(0, Qt.UserRole, e)
            it.setData(1, Qt.UserRole, e.size)
            it.setIcon(0, icon_dir if e.is_dir else icon_file)
            tip = [f"{k} : {v}" for k, v in e.meta.items()]
            if e.attrs:
                tip.append(f"Attributs : {e.attrs}")
            if not e.is_dir:
                try:
                    nb = count_bad(self.fs.read(e))
                except Exception:
                    nb = 0
                if nb:
                    e.meta["secteurs illisibles"] = nb
                    tip.insert(0, f"⚠ {nb} secteur(s) illisible(s) : contenu partiellement perdu")
                    for col in range(4):
                        it.setForeground(col, QColor(T.STATUS["bad"]))
                    self._damaged += 1
            it.setToolTip(0, "\n".join(tip))
            it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            for c in e.children:
                add(it, c)
            return it

        self._damaged = 0
        for e in self.fs.root.children:
            add(self.tree.invisibleRootItem(), e)
        try:
            dels = self.fs.deleted()
        except Exception:
            dels = []
        if dels:
            trash = Entry(f"Fichiers supprimés ({len(dels)})", 0, True, "Supprimés")
            trash.deleted = True
            for d in dels:
                trash.children.append(d)
            ti = add(self.tree.invisibleRootItem(), trash)
            ti.setIcon(0, st.standardIcon(QStyle.SP_TrashIcon))
            grey = QColor(T.MUTED)
            stack = [ti]
            while stack:
                it = stack.pop()
                for col in range(4):
                    it.setForeground(col, grey)
                f = it.font(0)
                f.setItalic(True)
                it.setFont(0, f)
                stack += [it.child(k) for k in range(it.childCount())]
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        self.tree.resizeColumnToContents(1)
        self.tree.resizeColumnToContents(2)
        self.tree.resizeColumnToContents(3)
        files = self.fs.files
        self.stats.setText(f"{len(files)} fichier(s) · {human(sum(e.size for e in files))}" +
                           (f" · <span style='color:{T.STATUS['bad']}'>{self._damaged} endommagé(s)</span>"
                            if self._damaged else ""))
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _apply_filter(self, txt: str):
        txt = txt.lower()

        def walk(it) -> bool:
            vis_child = False
            for i in range(it.childCount()):
                vis_child |= walk(it.child(i))
            me = not txt or txt in it.text(0).lower()
            it.setHidden(not (me or vis_child))
            return me or vis_child

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            walk(root.child(i))

    # ---------------------------------------------------------------- Aperçu
    def _clear_preview(self):
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, AudioView):
                w.stop()
        self.tabs.clear()
        self.previews = []
        self.cur = None

    def _text_widget(self, txt: str, mono=True) -> QPlainTextEdit:
        w = QPlainTextEdit()
        w.setReadOnly(True)
        w.setLineWrapMode(QPlainTextEdit.NoWrap if mono else QPlainTextEdit.WidgetWidth)
        f = QFont("Cascadia Mono")
        f.setStyleHint(QFont.Monospace)
        f.setPointSizeF(9.5)
        w.setFont(f)
        w.setPlainText(txt)
        return w

    def _show_raw_disk(self):
        self._clear_preview()
        raw = self.disk.linear() if self.disk else b""
        self.ptitle.setText("Contenu brut du disque")
        self.tabs.addTab(HexPane(raw, "latin-1", 2 * 1024 * 1024), "Hexa")

    def _selected_entries(self) -> List[Entry]:
        out = []
        for it in self.tree.selectedItems():
            e = it.data(0, Qt.UserRole)
            if e is not None and not any(p in out for p in self._parents(e)):
                out.append(e)
        return out

    @staticmethod
    def _parents(e: Entry):
        p = e.parent
        while p is not None:
            yield p
            p = p.parent

    def _on_current(self, it, _prev):
        self._clear_preview()
        if it is None or self.fs is None:
            self._update_buttons()
            return
        e: Entry = it.data(0, Qt.UserRole)
        self.cur = e
        if e.is_dir:
            self.ptitle.setText(f"📁 {e.name}")
            n = sum(1 for _ in e.walk() if not _.is_dir)
            self.tabs.addTab(self._props_table(e, [("Contenu", f"{n} fichier(s)")]), "Propriétés")
            self._update_buttons()
            return
        try:
            raw = self.fs.read(e)
            self.previews = V.analyse(self.fs, e, raw)
        except Exception as ex:
            self.previews = [V.Preview("text", "Erreur", text=f"Lecture impossible : {ex}\n\n"
                                       + traceback.format_exc())]
        self.ptitle.setText(f"{e.name}  ·  {human(e.size)}" + (f"  ·  {e.kind}" if e.kind else ""))
        for p in self.previews:
            if p.kind == "image":
                w = ImageView(p.image)
                self.tabs.addTab(w, f"Image ({p.note})")
            elif p.kind == "audio":
                self.tabs.addTab(AudioView(p.wav), "Audio")
            elif p.kind == "hex":
                self.tabs.addTab(HexPane(p.data, p.charset), "Hexa")
            elif p.kind == "disasm":
                d = dict(p.props)
                self.tabs.addTab(DisasmPane(p.data, d["cpu"], int(d["org"]), p.note), "Désassemblage")
            elif p.kind == "textraw":
                self.tabs.addTab(TextPane(p.data, p.charset, p.note), "Texte")
            else:
                self.tabs.addTab(self._text_widget(p.text), p.title)
        props = next((p.props for p in self.previews if p.kind != "disasm"), [])
        alloc = self._allocation()
        if alloc and not e.deleted:
            self.tabs.addTab(occupancy_panel(self.fs, alloc, e, self.goto_entry), "Emplacement")
        self.tabs.addTab(self._props_table(e, props), "Propriétés")
        self._update_buttons()

    def _props_table(self, e: Entry, extra) -> QTableWidget:
        rows = [("Nom", e.name), ("Chemin", "/" + e.path), ("Taille", f"{e.size} o")]
        if e.kind:
            rows.append(("Type", e.kind))
        if e.date:
            rows.append(("Date", e.date))
        if e.attrs:
            rows.append(("Attributs", e.attrs))
        rows += [(k, v) for k, v in extra if k not in dict(rows)]
        t = QTableWidget(len(rows), 2)
        t.horizontalHeader().hide()
        t.verticalHeader().hide()
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for r, (k, v) in enumerate(rows):
            a = QTableWidgetItem(k)
            a.setForeground(QColor(T.MUTED))
            t.setItem(r, 0, a)
            t.setItem(r, 1, QTableWidgetItem(str(v)))
        t.resizeColumnToContents(0)
        return t

    def _on_double(self, it, _col):
        e = it.data(0, Qt.UserRole)
        if e and not e.is_dir:
            if V.runnable(self.fs, e, self.fs.read(e)[:4]):
                self.run_file()
            else:
                self.open_external()

    def _menu(self, pos):
        if self.fs is None:
            return
        m = QMenu(self)
        for b in (self.b_export, self.b_conv, self.b_open, self.b_run, self.b_boot):
            a = m.addAction(b.text().strip())
            a.setEnabled(b.isEnabled())
            a.triggered.connect(b.click)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _update_buttons(self):
        has_fs = self.fs is not None
        e = self.cur
        is_file = bool(e and not e.is_dir)
        self.b_export.setEnabled(has_fs)
        self.b_conv.setEnabled(is_file and any(p.converted for p in self.previews))
        self.b_open.setEnabled(is_file)
        run_ok = False
        if is_file and has_fs:
            try:
                run_ok = V.runnable(self.fs, e, self.fs.read(e)[:4])
            except Exception:
                run_ok = False
        self.b_run.setEnabled(run_ok)
        self.b_boot.setEnabled(has_fs and self.fs.platform != "akai")
        w = has_fs and self.fs.writable
        for b in (self.b_add, self.b_del):
            b.setEnabled(w)
        self.b_save.setEnabled(w or bool(getattr(self, "_disk_dirty", False)))
        self.b_occ.setEnabled(has_fs)
        self.b_search.setEnabled(self.disk is not None)
        self.b_sect.setEnabled(bool(self.disk is not None and self.disk.tracks))
        self.b_mkdir.setEnabled(w and hasattr(self.fs, "mkdir"))
        self.b_write.setEnabled(w and self._write_fmt() is not None)
        for b in (self.b_add, self.b_mkdir, self.b_del, self.b_save, self.b_write):
            b.setToolTip(b.toolTip() if w else "Modification possible pour FAT (PC, Atari ST, MSX, synthés), "
                         "Amstrad CPC, Amiga, Thomson et Commodore 1541/1581")
        self.mod_lbl.setText("● modifiée (non enregistrée)" if self.modified else "")

    # ---------------------------------------------------------------- Actions
    def _drag_paths(self, entries: List[Entry]) -> List[str]:
        d = tempfile.mkdtemp(prefix="drag_", dir=EM.session_dir())
        try:
            export_entries(self.fs, entries, d)
        except Exception as ex:
            self.log.emit(f"Export impossible : {ex}", "err")
            return []
        return [os.path.join(d, x) for x in os.listdir(d)]

    def export_selected(self):
        if self.fs is None:
            return
        entries = self._selected_entries() or self.fs.root.children
        last = getattr(self, "_last_export", "") or os.path.expanduser("~")
        d = QFileDialog.getExistingDirectory(self, "Exporter vers…", last)
        if not d:
            return
        self._last_export = d
        sub = safe_name(os.path.splitext(os.path.basename(self.disk.path))[0]
                        + (f" - {self.fs.volume_name}" if self.fs.volume_name else ""))
        if not self._selected_entries():
            d = os.path.join(d, sub)
            os.makedirs(d, exist_ok=True)
        try:
            n = export_entries(self.fs, entries, d)
        except Exception as ex:
            QMessageBox.warning(self, "Export", f"Erreur : {ex}")
            return
        self.log.emit(f"{n} fichier(s) exporté(s) vers {d}", "ok")
        if hasattr(os, "startfile"):
            os.startfile(d)

    def export_converted(self):
        if not self.cur:
            return
        conv = next((p.converted for p in self.previews if p.converted), None)
        if not conv:
            return
        ext, data = conv
        base = os.path.splitext(safe_name(self.cur.name))[0]
        last = getattr(self, "_last_export", "") or os.path.expanduser("~")
        p, _ = QFileDialog.getSaveFileName(self, "Exporter converti", os.path.join(last, f"{base}.{ext}"),
                                           f"*.{ext}")
        if p:
            with open(p, "wb") as f:
                f.write(data)
            self.log.emit(f"Exporté : {p}", "ok")

    def open_external(self):
        if not self.cur or self.cur.is_dir:
            return
        e = self.cur
        d = tempfile.mkdtemp(prefix="open_", dir=EM.session_dir())
        conv = next((p.converted for p in self.previews if p.converted and p.kind in ("image", "audio")), None)
        name = safe_name(e.name)
        known_ext = os.path.splitext(name)[1].lower() in (".txt", ".png", ".jpg", ".gif", ".bmp", ".wav",
                                                          ".doc", ".pdf", ".htm", ".html", ".mid")
        if conv and not known_ext:
            path = os.path.join(d, os.path.splitext(name)[0] + "." + conv[0])
            data = conv[1]
        elif not known_ext and any(p.kind == "text" or (p.kind == "textraw" and p.converted)
                                   for p in self.previews):
            txt = next(p for p in self.previews if p.kind == "text" or (p.kind == "textraw" and p.converted))
            path = os.path.join(d, name + ".txt")
            data = txt.text.encode("utf-8-sig")
        else:
            path = os.path.join(d, name)
            data = self.fs.content(e)
        with open(path, "wb") as f:
            f.write(data)
        if hasattr(os, "startfile"):
            try:
                os.startfile(path)
            except OSError:
                os.startfile(d)
        self.log.emit(f"Ouvert : {path}", "info")

    def _emu(self) -> Optional[EM.Emu]:
        cfg = EM.EmuConfig()
        emu = cfg.get(self.fs.platform)
        if emu is None:
            QMessageBox.information(self, "Émulateur", "Aucun émulateur prévu pour cette plateforme.")
            return None
        if not emu.exe or not os.path.isfile(emu.exe):
            r = QMessageBox.question(self, "Émulateur non configuré",
                                     f"Aucun émulateur {EM.PLATFORM_NAMES.get(self.fs.platform)} configuré "
                                     f"({emu.name}).\n\nLancer la détection automatique ?\n\n"
                                     f"Téléchargement : {emu.url}")
            if r != QMessageBox.Yes:
                return None
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                cfg.autodetect()
            finally:
                QApplication.restoreOverrideCursor()
            emu = cfg.get(self.fs.platform)
            if not emu.exe:
                self.configure_emulators()
                emu = EM.EmuConfig().get(self.fs.platform)
                if not emu.exe:
                    return None
        return emu

    def run_image(self):
        if self.fs is None:
            return
        emu = self._emu()
        if not emu:
            return
        try:
            img = native_image(self.disk, self.fs)
            EM.launch(emu, image=img)
            self.log.emit(f"Lancement de {os.path.basename(emu.exe)} avec {img}", "ok")
        except Exception as ex:
            QMessageBox.warning(self, "Émulateur", f"Lancement impossible : {ex}")

    def run_file(self):
        e = self.cur
        if not e or e.is_dir or self.fs is None:
            return
        emu = self._emu()
        if not emu:
            return
        plat = self.fs.platform
        hint = ""
        try:
            if plat == "pc" and emu.args_file:
                d = tempfile.mkdtemp(prefix="run_", dir=EM.session_dir())
                export_entries(self.fs, self.fs.root.children, d, dos83=True)
                rel = []
                p = e
                while p is not None and p.parent is not None:
                    rel.append(p.meta.get("nom 8.3", p.name))
                    p = p.parent
                dos = "\\".join(reversed(rel))
                EM.launch(emu, file=dos, directory=d)
            elif plat == "c64" and emu.args_file:
                d = tempfile.mkdtemp(prefix="run_", dir=EM.session_dir())
                path = os.path.join(d, safe_name(e.name))
                with open(path, "wb") as f:
                    f.write(self.fs.content(e))
                EM.launch(emu, file=path)
            else:
                img = native_image(self.disk, self.fs)
                EM.launch(emu, image=img)
                base = e.name.rsplit(".", 1)[0]
                hint = {"cpc": f'Tapez : RUN"{base}',
                        "thomson": f'Tapez : RUN"{e.name}"' if e.meta.get("type") == 0
                        else f'Tapez : LOADM"{e.name}",,R',
                        "amiga": "Démarrez sur la disquette puis lancez le programme depuis le Shell.",
                        "atarist": f"Ouvrez le lecteur A: puis double-cliquez {e.name}.",
                        "msx": f'Tapez : RUN"{e.name}"'}.get(plat, "")
            self.log.emit(f"Exécution de {e.name} via {os.path.basename(emu.exe)}"
                          + (f" — {hint}" if hint else ""), "ok")
            if hint:
                QMessageBox.information(self, "Exécution", f"L'émulateur démarre avec la disquette.\n\n{hint}")
        except Exception as ex:
            QMessageBox.warning(self, "Exécution", f"Lancement impossible : {ex}")

    # ---------------------------------------------------------------- Modification
    def _target_dir(self, e: Optional[Entry] = None) -> Entry:
        if e is None:
            it = self.tree.currentItem()
            e = it.data(0, Qt.UserRole) if it else None
        if e is None or e.deleted:
            return self.fs.root
        return e if e.is_dir else (e.parent or self.fs.root)

    def _after_edit(self, msg: str):
        self.modified = True
        self._alloc = None
        self._select_volume(self.vols.index(self.fs))
        self.log.emit(msg, "ok")

    def _import(self, paths: List[str], parent: Entry):
        done, errs = [], []
        path_of = parent.path
        for p in paths:
            try:
                if os.path.isdir(p):
                    if not hasattr(self.fs, "mkdir"):
                        raise ValueError("dossiers non pris en charge")
                    nm = self.fs.mkdir(self._find(path_of), os.path.basename(p))
                    sub = (path_of + "/" if path_of else "") + nm
                    self._import([os.path.join(p, x) for x in sorted(os.listdir(p))], self._find(sub))
                    done.append(nm + "/")
                else:
                    with open(p, "rb") as f:
                        data = f.read()
                    data = self._maybe_tokenize(p, data)
                    done.append(self.fs.add_file(self._find(path_of), os.path.basename(p), data))
            except Exception as ex:
                errs.append(f"{os.path.basename(p)} : {ex}")
        if done:
            self._after_edit(f"Ajouté : {', '.join(done)}")
        if errs:
            QMessageBox.warning(self, "Ajout", "\n".join(errs))

    def _maybe_tokenize(self, path: str, data: bytes) -> bytes:
        """Listing BASIC texte ajouté sur CPC / MSX : proposer la tokenisation."""
        plat = self.fs.platform
        if not path.lower().endswith(".bas") or plat not in ("cpc", "msx") or not V.looks_text(data):
            return data
        if not re.match(rb"\s*\d+\s", data):
            return data
        if QMessageBox.question(self, "Listing BASIC", f"{os.path.basename(path)} est un listing texte.\n"
                                "Le convertir en BASIC tokenisé (chargement plus rapide, format natif) ?\n"
                                "Non : copié tel quel en ASCII.") != QMessageBox.Yes:
            return data
        from . import convert as CV
        text = data.decode("latin-1")
        if plat == "cpc":
            return CV.amsdos_file(os.path.basename(path), CV.tokenize_locomotive(text))
        return CV.tokenize_ms(text, "msx")

    def _find(self, path: str) -> Entry:
        e = self.fs.root
        for part in [x for x in path.split("/") if x]:
            e = next((c for c in e.children if c.name == part or c.meta.get("nom 8.3") == part), e)
        return e

    def _drop_import(self, paths: List[str], target: Optional[Entry]):
        if self.fs and self.fs.writable:
            self._import(paths, self._target_dir(target) if target else self.fs.root)

    def add_files(self):
        if not (self.fs and self.fs.writable):
            return
        last = getattr(self, "_last_import", "") or os.path.expanduser("~")
        paths, _ = QFileDialog.getOpenFileNames(self, "Ajouter des fichiers", last)
        if paths:
            self._last_import = os.path.dirname(paths[0])
            self._import(paths, self._target_dir())

    def make_dir(self):
        if not (self.fs and hasattr(self.fs, "mkdir")):
            return
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Nouveau dossier", "Nom (8.3) :")
        if ok and name.strip():
            try:
                nm = self.fs.mkdir(self._target_dir(), name.strip())
                self._after_edit(f"Dossier créé : {nm}")
            except Exception as ex:
                QMessageBox.warning(self, "Nouveau dossier", str(ex))

    def delete_selected(self):
        ents = [e for e in self._selected_entries() if not e.deleted]
        if not ents or not self.fs.writable:
            return
        if QMessageBox.question(self, "Supprimer", f"Supprimer {len(ents)} élément(s) de l'image ?\n"
                                "(l'image d'origine n'est modifiée qu'à l'enregistrement)") != QMessageBox.Yes:
            return
        paths = [e.path for e in ents]
        try:
            for p in paths:
                self.fs.delete(self._find(p))
        except Exception as ex:
            QMessageBox.warning(self, "Supprimer", str(ex))
        self._after_edit(f"Supprimé : {', '.join(paths)}")

    def _save_disk(self, p: str):
        ext = os.path.splitext(p)[1].lower()
        if ext in (".dsk", ".edsk") and (self.disk.kind in ("edsk", "dsk", ".edsk", ".dsk")
                                         and (self.fs is None or self.fs.platform == "cpc")):
            write_edsk(self.disk, p)
            return
        data = self.disk.linear(heads=list(range(self.disk.heads)), sequential=True) if ext == ".fd" \
            else self.disk.linear()
        with open(p, "wb") as f:
            f.write(data)

    def save_image(self):
        if self.disk is not None and getattr(self, "_disk_dirty", False):
            base, ext = os.path.splitext(self.disk.path)
            if ext.lower() not in (".img", ".ima", ".st", ".dsk", ".edsk", ".fd", ".adf", ".d64", ".d81"):
                ext = ".img"
            p, _ = QFileDialog.getSaveFileName(self, "Enregistrer l'image", base + "_modif" + ext, f"*{ext}")
            if not p:
                return
            try:
                self._save_disk(p)
            except Exception as ex:
                QMessageBox.warning(self, "Enregistrer", str(ex))
                return
            self.modified = self._disk_dirty = False
            self.disk.path = p
            self._update_buttons()
            self.log.emit(f"Image enregistrée : {p}", "ok")
            return
        if not (self.fs and self.fs.writable):
            return
        base, ext = os.path.splitext(self.disk.path)
        ext = ext.lower() if ext.lower() in (".img", ".ima", ".st", ".dsk", ".vfd") else self.fs.save_ext
        if self.fs.platform in ("cpc", "thomson", "amiga", "c64"):
            ext = self.fs.save_ext
        p, _ = QFileDialog.getSaveFileName(self, "Enregistrer l'image", base + ext, f"*{ext}")
        if not p:
            return
        try:
            self.fs.save(p)
        except Exception as ex:
            QMessageBox.warning(self, "Enregistrer", str(ex))
            return
        self.modified = False
        self.disk.path = p
        self.title.setText(f"{os.path.basename(p)} — {self.fs.title()}")
        self._update_buttons()
        self.log.emit(f"Image enregistrée : {p}", "ok")

    def _write_fmt(self) -> Optional[str]:
        fs = self.fs
        if fs is None:
            return None
        if self.disk.fmt and self.disk.fmt != "ibm.scan":
            return self.disk.fmt
        if fs.platform == "cpc":
            return {0xC1: "cpc.data", 0x41: "cpc.system", 0x01: "ibm.160"}.get(getattr(fs, "first", 0))
        if fs.platform == "thomson":
            heads = self.disk.heads if self.disk.tracks else 1
            if getattr(fs, "ss", 256) == 128:
                return "thomson.1s80"
            size = "320" if fs.ntracks >= 80 else "160"
            return f"thomson.{heads}s{size}" if heads == 2 else f"thomson.1s{size}"
        if fs.platform == "amiga":
            return "amiga.amigados_hd" if fs.nblocks > 1760 else "amiga.amigados"
        if fs.platform == "c64":
            return {"1541": "commodore.1541", "1581": "commodore.1581", "1571": "commodore.1571"}.get(fs.model)
        size = len(getattr(fs, "d", b""))
        if not size:
            return None
        if fs.platform == "atarist":
            cand = [f"atarist.{size // 1024}"]
        elif fs.platform == "msx":
            cand = ["msx.2dd" if size == 737280 else "msx.1dd"]
        else:
            cand = [f"ibm.{size // 1024}"]
        for c in cand:
            g = F.geometry(c)
            if g and g.capacity == size:
                return c
        return None

    def write_disk(self):
        fmt = self._write_fmt()
        if not (self.fs and self.fs.writable and fmt):
            return
        ext = {"thomson": ".fd", "amiga": ".adf", "c64": self.fs.save_ext}.get(self.fs.platform, ".img")
        path = os.path.join(EM.session_dir(), f"ecriture_{int(time.time())}{ext}")
        try:
            if self.fs.platform == "cpc":
                with open(path, "wb") as f:
                    f.write(self.disk.linear())
            else:
                self.fs.save(path)
        except Exception as ex:
            QMessageBox.warning(self, "Écriture", str(ex))
            return
        self.write_request.emit(path, fmt, "")

    # ---------------------------------------------------------------- Outils
    def _allocation(self):
        if self.fs is None:
            return None
        if self._alloc is None:
            try:
                self._alloc = self.fs.allocation() or False
            except Exception:
                self._alloc = False
        return self._alloc or None

    def show_occupancy(self):
        a = self._allocation()
        if not a:
            QMessageBox.information(self, "Occupation", "Carte non disponible pour ce système de fichiers.")
            return
        self._clear_preview()
        self.ptitle.setText(f"Occupation — {self.fs.title()}")
        self.tabs.addTab(occupancy_panel(self.fs, a, None, self.goto_entry), "Occupation")
        self._update_buttons()

    def goto_entry(self, e: Entry):
        from PySide6.QtWidgets import QTreeWidgetItemIterator
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            if it.value().data(0, Qt.UserRole) is e:
                self.tree.setCurrentItem(it.value())
                self.tree.scrollToItem(it.value())
                return
            it += 1

    def search(self):
        if self.disk is None:
            return
        dlg = SearchDialog(self, self.disk, self.fs)
        dlg.goto.connect(self.goto_entry)
        dlg.show()
        self._search_dlg = dlg

    def edit_sectors(self):
        if self.disk is None or not self.disk.tracks:
            QMessageBox.information(self, "Secteurs", "Géométrie inconnue pour cette image.")
            return
        if self.modified and not getattr(self, "_disk_dirty", False):
            QMessageBox.information(self, "Secteurs", "Enregistrez d'abord les modifications de fichiers.")
            return
        dlg = SectorEditor(self, self.disk)
        dlg.changed.connect(self._sectors_changed)
        dlg.write_track.connect(self._write_track)
        dlg.show()
        self._sect_dlg = dlg

    def _sectors_changed(self):
        self.modified = self._disk_dirty = True
        idx = self.vol_cb.currentIndex() if self.vols else 0
        self.vols = detect(self.disk)
        self.vol_cb.blockSignals(True)
        self.vol_cb.clear()
        for fs in self.vols:
            self.vol_cb.addItem(fs.title())
        self.vol_cb.blockSignals(False)
        if self.vols:
            self._select_volume(min(idx, len(self.vols) - 1))
        else:
            self.fs = None
            self.tree.clear()
        self._update_buttons()
        self.log.emit("Secteur modifié (image non enregistrée)", "warn")

    def _write_track(self, c: int, h: int):
        fmt = self._write_fmt() if self.fs else (self.disk.fmt if self.disk.fmt != "ibm.scan" else None)
        if not fmt:
            QMessageBox.warning(self, "Écriture", "Format d'écriture inconnu pour cette image.")
            return
        ext = ".fd" if fmt.startswith("thomson") else ".d81" if fmt == "commodore.1581" else ".img"
        from .fs.disk import _sides_swapped
        if _sides_swapped(F.get_diskdef(fmt)):
            h ^= 1          # la piste physique est sur l'autre tête
        if self.fs and self.fs.writable and not getattr(self, "_disk_dirty", False):
            ext = {"thomson": ".fd", "amiga": ".adf", "c64": self.fs.save_ext}.get(self.fs.platform, ext)
        path = os.path.join(EM.session_dir(), f"piste_{int(time.time())}{ext}")
        try:
            data = self.disk.linear(heads=list(range(self.disk.heads)), sequential=True) if ext == ".fd" \
                else self.disk.linear()
            if self.fs and self.fs.writable and not getattr(self, "_disk_dirty", False):
                self.fs.save(path)
            else:
                with open(path, "wb") as f:
                    f.write(data)
        except Exception as ex:
            QMessageBox.warning(self, "Écriture", str(ex))
            return
        self.write_request.emit(path, fmt, f"c={c}:h={h}")

    def configure_emulators(self):
        EmulatorDialog(self).exec()
