"""Fenêtre principale de Floppy Studio."""
from __future__ import annotations

import html
import os
import time
from typing import Optional

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QFont, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QDialog,
                               QComboBox, QFileDialog, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QSplitter, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout,
                               QWidget)

from . import APP_NAME, __version__
from . import engine as E
from . import emulators as EM
from . import formats as F
from . import theme as T
from . import analysis as A
from .explorer import EmulatorDialog, ExplorerView
from .fs import mkfs as MK
from .fs import open_disk
from .widgets import FluxHistogram, Legend, RpmChart, StatTile, TrackMap, card

ANALYSE_ROW = 3
EXPLORER_ROW = 4


def _row(*widgets, stretch_last=False):
    w = QWidget()
    l = QHBoxLayout(w)
    l.setContentsMargins(0, 0, 0, 0)
    l.setSpacing(6)
    for x in widgets:
        if x is None:
            l.addStretch()
        else:
            l.addWidget(x)
    return w


def _muted(text, wrap=True):
    l = QLabel(text)
    l.setObjectName("muted")
    l.setTextFormat(Qt.RichText)
    l.setWordWrap(wrap)
    return l


class FormatPicker(QWidget):
    """Choix plateforme + format, avec géométrie affichée."""

    def __init__(self, allow_none=True):
        super().__init__()
        lay = QFormLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.plat = QComboBox()
        self.fmt = QComboBox()
        for cb in (self.plat, self.fmt):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(12)
        self.geo = _muted("")
        for p in F.platforms():
            self.plat.addItem(p.name)
        lay.addRow("Plateforme", self.plat)
        lay.addRow("Format", self.fmt)
        lay.addRow("", self.geo)
        self.plat.currentIndexChanged.connect(self._fill)
        self.fmt.currentIndexChanged.connect(self._geo)
        self._fill()

    def _fill(self):
        self.fmt.blockSignals(True)
        self.fmt.clear()
        p = F.platforms()[self.plat.currentIndex()]
        for pr in p.presets:
            self.fmt.addItem(pr.label, pr)
            if pr.fmt:
                self.fmt.setItemData(self.fmt.count() - 1, pr.fmt + ("\n" + pr.note if pr.note else ""),
                                     Qt.ToolTipRole)
        self.fmt.blockSignals(False)
        self._geo()

    def _geo(self):
        pr = self.preset()
        if pr is None:
            self.geo.setText("")
            return
        if pr.fmt is None:
            txt = "Flux magnétique brut : aucune interprétation, archivage fidèle."
        else:
            g = F.geometry(pr.fmt)
            txt = f"<code>{pr.fmt}</code> · " + (g.desc if g else "")
        if pr.tracks:
            txt += f"<br>Pistes : <code>{pr.tracks}</code>"
        if pr.note:
            txt += f"<br>{html.escape(pr.note)}"
        self.geo.setText(txt)
        self.changed()

    def changed(self):  # surchargée via callback
        pass

    def preset(self) -> Optional[F.Preset]:
        return self.fmt.currentData()

    def select_format(self, fmt: Optional[str]) -> bool:
        for i, p in enumerate(F.platforms()):
            for j, pr in enumerate(p.presets):
                if pr.fmt == fmt:
                    self.plat.setCurrentIndex(i)
                    self.fmt.setCurrentIndex(j)
                    return True
        return False


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.resize(1360, 860)
        self.settings = QSettings("FloppyStudio", "FloppyStudio")
        self.dev = E.Device()
        self.job: Optional[E.Job] = None
        self.job_t0 = 0.0
        self.track_results = {}

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_topbar())

        body = QSplitter(Qt.Horizontal)
        body.setHandleWidth(1)
        outer.addWidget(body, 1)
        body.addWidget(self._build_sidebar())
        self.right = QStackedWidget()
        self.right.addWidget(self._build_workspace())
        self.explorer = ExplorerView()
        self.explorer.log.connect(self.log)
        self.explorer.write_request.connect(self.write_image_now)
        self.right.addWidget(self.explorer)
        body.addWidget(self.right)
        body.setStretchFactor(1, 1)
        body.setSizes([540, 860])

        self.setAcceptDrops(True)
        self.statusBar().showMessage("Prêt")
        self.refresh_ports(auto_connect=True)
        self._restore()
        self._update_enabled()

    # ------------------------------------------------------------------ UI
    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("sidebar")
        bar.setFixedHeight(58)
        l = QHBoxLayout(bar)
        l.setContentsMargins(16, 8, 16, 8)
        l.setSpacing(10)
        logo = QLabel("💾")
        logo.setStyleSheet("font-size:20pt;")
        title = QLabel(APP_NAME)
        title.setObjectName("h1")
        l.addWidget(logo)
        l.addWidget(title)
        l.addSpacing(24)

        self.port_cb = QComboBox()
        self.port_cb.setMinimumWidth(260)
        btn_ref = QPushButton("↻")
        btn_ref.setToolTip("Rafraîchir la liste des ports")
        btn_ref.setFixedWidth(40)
        btn_ref.clicked.connect(lambda: self.refresh_ports(False))
        self.btn_conn = QPushButton("Connecter")
        self.btn_conn.clicked.connect(self.toggle_connect)
        self.drive_cb = QComboBox()
        for k, v in [("A", "Lecteur A (PC, après torsade)"), ("B", "Lecteur B (PC, avant torsade)"),
                     ("0", "Shugart DS0"), ("1", "Shugart DS1"), ("2", "Shugart DS2"),
                     ("3", "Shugart DS3")]:
            self.drive_cb.addItem(v, k)
        self.drive_cb.setToolTip("Sélection du lecteur sur le câble")
        self.chip = QLabel("Déconnecté")
        self.chip.setObjectName("chip")
        self._chip(False)

        l.addWidget(QLabel("Port"))
        l.addWidget(self.port_cb)
        l.addWidget(btn_ref)
        l.addWidget(self.btn_conn)
        l.addSpacing(12)
        l.addWidget(QLabel("Lecteur"))
        l.addWidget(self.drive_cb)
        l.addStretch()
        l.addWidget(self.chip)
        return bar

    def _chip(self, on: bool, text: Optional[str] = None):
        if on:
            self.chip.setText(text or "Connecté")
            self.chip.setStyleSheet("background:#123326; color:#4fd18f;")
        else:
            self.chip.setText(text or "Déconnecté")
            self.chip.setStyleSheet("background:#2a1d22; color:#ff8c88;")

    def _build_sidebar(self):
        side = QWidget()
        side.setObjectName("sidebar")
        side.setMinimumWidth(500)
        side.setMaximumWidth(600)
        l = QHBoxLayout(side)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(132)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for icon, name in [("📥", "Lire"), ("📤", "Écrire"), ("🧹", "Formater"), ("🔍", "Analyser"),
                           ("📂", "Explorer"), ("📑", "Copier"), ("🛠", "Outils"), ("🔁", "Convertir"),
                           ("ℹ", "Appareil")]:
            self.nav.addItem(QListWidgetItem(f"{icon}  {name}"))
        l.addWidget(self.nav)

        self.pages = QStackedWidget()
        for build in (self._page_read, self._page_write, self._page_format, self._page_analyse,
                      self._page_explore, self._page_copy, self._page_tools, self._page_convert,
                      self._page_device):
            sc = QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QFrame.NoFrame)
            sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            w = build()
            w.setObjectName("page")
            sc.setWidget(w)
            self.pages.addWidget(sc)
        l.addWidget(self.pages, 1)
        self._fit_pages()
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.currentRowChanged.connect(self._nav_changed)
        self.nav.setCurrentRow(0)
        return side

    def _fit_pages(self):
        """Empêche les listes déroulantes et textes longs d'élargir les pages latérales."""
        for cb in self.pages.findChildren(QComboBox):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(min(cb.minimumContentsLength() or 6, 10))
            for i in range(cb.count()):
                if not cb.itemData(i, Qt.ToolTipRole):
                    cb.setItemData(i, cb.itemText(i), Qt.ToolTipRole)
        for le in self.pages.findChildren(QLineEdit):
            le.setMinimumWidth(60)
        for cbx in self.pages.findChildren(QCheckBox):
            if len(cbx.text()) > 34 and not cbx.toolTip():
                cbx.setToolTip(cbx.text())

    def _page(self, title, subtitle):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(12)
        h = QLabel(title)
        h.setObjectName("h1")
        v.addWidget(h)
        v.addWidget(_muted(subtitle))
        return w, v

    # --- Lire
    def _page_read(self):
        w, v = self._page("Lire une disquette", "Crée une image disque à partir de la disquette insérée.")
        g = QGroupBox("Format")
        gl = QVBoxLayout(g)
        self.r_pick = FormatPicker()
        self.r_pick.changed = self._read_fmt_changed
        gl.addWidget(self.r_pick)
        b = QPushButton("🔍  Détecter automatiquement")
        b.clicked.connect(self.start_analyse)
        gl.addWidget(b)
        v.addWidget(g)

        g = QGroupBox("Fichier de sortie")
        gl = QVBoxLayout(g)
        self.r_path = QLineEdit()
        self.r_path.setPlaceholderText("Choisir l'emplacement de l'image…")
        bb = QPushButton("…")
        bb.setFixedWidth(40)
        bb.clicked.connect(self._read_browse)
        gl.addWidget(_row(self.r_path, bb))
        self.r_flux = QCheckBox("Garder aussi le flux brut (.scp)")
        self.r_flux.setToolTip("Archive fidèle de la disquette, utile pour récupérer\n"
                               "plus tard des secteurs ou réessayer un autre format.")
        gl.addWidget(self.r_flux)
        self.r_deep = QCheckBox("Analyse approfondie (protections)")
        self.r_deep.setToolTip("Décode chaque tour séparément et scanne les secteurs non standard.\n"
                               "Plus lent ; un rapport s'affiche à la fin.")
        gl.addWidget(self.r_deep)
        self.r_auto = QCheckBox("Nom automatique horodaté")
        self.r_auto.setChecked(True)
        gl.addWidget(self.r_auto)
        v.addWidget(g)

        g = QGroupBox("Options avancées")
        f = QFormLayout(g)
        self.r_revs = QSpinBox()
        self.r_revs.setRange(0, 20)
        self.r_revs.setSpecialValueText("auto")
        self.r_revs.setToolTip("Révolutions lues par piste (auto = valeur du format)")
        self.r_retries = QSpinBox()
        self.r_retries.setRange(0, 50)
        self.r_retries.setValue(3)
        self.r_seek = QSpinBox()
        self.r_seek.setRange(0, 20)
        self.r_seek.setValue(1)
        self.r_seek.setToolTip("Après échec des relectures : ramener la tête en piste 0 puis réessayer")
        self.r_tracks = QLineEdit()
        self.r_tracks.setPlaceholderText("auto (ex. c=0-39:h=0, step=2)")
        f.addRow("Révolutions", self.r_revs)
        f.addRow("Relectures", self.r_retries)
        f.addRow("Repositionnements", self.r_seek)
        f.addRow("Pistes", self.r_tracks)
        v.addWidget(g)

        self.r_go = QPushButton("📥  Lire la disquette")
        self.r_go.setObjectName("primary")
        self.r_go.clicked.connect(self.start_read)
        v.addWidget(self.r_go)
        b = QPushButton("📂  Explorer l'image lue")
        b.clicked.connect(lambda: self._explore_last())
        v.addWidget(b)

        g = QGroupBox("Lecture par lot")
        gl = QVBoxLayout(g)
        self.r_batch = QCheckBox("Enchaîner plusieurs disquettes")
        self.r_watch = QCheckBox("Détecter l'insertion suivante")
        self.r_watch.setChecked(True)
        self.r_watch.setToolTip("Utilise la ligne « disk change » du lecteur (broche 34) ;\n"
                                "à défaut, détecte les impulsions d'index.")
        gl.addWidget(self.r_batch)
        gl.addWidget(self.r_watch)
        self.r_batch_lbl = _muted("")
        gl.addWidget(self.r_batch_lbl)
        v.addWidget(g)
        v.addStretch()
        return w

    def _batch_continue(self):
        if not getattr(self, "_batch_active", False):
            return
        self.r_batch_lbl.setText(f"{self._batch_count} disquette(s) lue(s).")
        if self.r_watch.isChecked() and self.dev.connected:
            self._batch_wait = True
            self.log("Lot : retirez la disquette et insérez la suivante (Annuler pour terminer).", "info")
            self.run_job(E.WatchJob(self.dev, self._drive(), True), "En attente de la disquette suivante")
            return
        r = QMessageBox.question(self, "Lecture par lot", f"{self._batch_count} disquette(s) lue(s).<br>"
                                 "Insérez la disquette suivante puis <b>Oui</b>, ou <b>Non</b> pour terminer.")
        if r == QMessageBox.Yes:
            self.start_read()
        else:
            self._batch_active = False
            self.log(f"Lot terminé : {self._batch_count} disquette(s).", "ok")

    # --- Écrire
    def _page_write(self):
        w, v = self._page("Écrire une disquette", "Écrit une image sur la disquette insérée (contenu actuel écrasé).")
        g = QGroupBox("Image source")
        gl = QVBoxLayout(g)
        self.w_path = QLineEdit()
        self.w_path.setPlaceholderText("Choisir une image…")
        self.w_path.editingFinished.connect(self._write_path_changed)
        bb = QPushButton("…")
        bb.setFixedWidth(40)
        bb.clicked.connect(self._write_browse)
        gl.addWidget(_row(self.w_path, bb))
        self.w_info = _muted("")
        gl.addWidget(self.w_info)
        v.addWidget(g)

        g = QGroupBox("Format")
        gl = QVBoxLayout(g)
        self.w_pick = FormatPicker()
        gl.addWidget(self.w_pick)
        self.w_rawfmt = QCheckBox("Écrire le flux tel quel (SCP, HFE…)")
        self.w_rawfmt.setChecked(True)
        self.w_rawfmt.toggled.connect(lambda on: self.w_pick.setEnabled(not on))
        gl.addWidget(self.w_rawfmt)
        v.addWidget(g)

        g = QGroupBox("Options")
        f = QFormLayout(g)
        self.w_verify = QCheckBox("Vérifier chaque piste après écriture")
        self.w_verify.setChecked(True)
        self.w_erase = QCheckBox("Effacer chaque piste avant écriture")
        self.w_erase_empty = QCheckBox("Effacer les pistes absentes de l'image")
        self.w_retries = QSpinBox()
        self.w_retries.setRange(0, 20)
        self.w_retries.setValue(3)
        self.w_tracks = QLineEdit()
        self.w_tracks.setPlaceholderText("auto")
        f.addRow(self.w_verify)
        f.addRow(self.w_erase)
        f.addRow(self.w_erase_empty)
        f.addRow("Essais si échec", self.w_retries)
        f.addRow("Pistes", self.w_tracks)
        v.addWidget(g)

        self.w_go = QPushButton("📤  Écrire sur la disquette")
        self.w_go.setObjectName("primary")
        self.w_go.clicked.connect(self.start_write)
        v.addWidget(self.w_go)
        v.addStretch()
        self._write_path_changed()
        return w

    # --- Formater
    def _page_format(self):
        w, v = self._page("Formater une disquette",
                          "Système de fichiers vierge sur la disquette, ou image vierge.")
        g = QGroupBox("Système de fichiers")
        f = QFormLayout(g)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.f_group = QComboBox()
        groups = []
        for sp in MK.SPECS:
            if sp.group not in groups:
                groups.append(sp.group)
        for gname in groups:
            self.f_group.addItem(gname)
        self.f_group.addItem("Bas niveau (tous formats)")
        self.f_spec = QComboBox()
        self.f_label = QLineEdit()
        self.f_label.setPlaceholderText("facultatif")
        f.addRow("Plateforme", self.f_group)
        f.addRow("Format", self.f_spec)
        f.addRow("Nom du volume", self.f_label)
        self.f_info = _muted("")
        f.addRow("", self.f_info)
        v.addWidget(g)

        self.f_low = QGroupBox("Format bas niveau")
        fl = QVBoxLayout(self.f_low)
        self.f_pick = FormatPicker()
        fl.addWidget(self.f_pick)
        self.f_fill = QSpinBox()
        self.f_fill.setRange(0, 255)
        self.f_fill.setDisplayIntegerBase(16)
        self.f_fill.setPrefix("0x")
        self.f_fill.setValue(0xE5)
        fl.addWidget(_row(QLabel("Octet de remplissage"), self.f_fill, stretch_last=False))
        fl.addWidget(_muted("Pistes et secteurs écrits selon la géométrie choisie, sans système de fichiers."))
        v.addWidget(self.f_low)

        g = QGroupBox("Options")
        f = QFormLayout(g)
        self.f_verify = QCheckBox("Vérifier chaque piste après écriture")
        self.f_verify.setChecked(True)
        self.f_erase = QCheckBox("Effacer chaque piste avant écriture")
        self.f_erase.setToolTip("Utile pour une disquette d'un autre format ou d'une autre densité")
        f.addRow(self.f_verify)
        f.addRow(self.f_erase)
        v.addWidget(g)

        self.f_go = QPushButton("🧹  Formater la disquette")
        self.f_go.setObjectName("primary")
        self.f_go.clicked.connect(self.start_format)
        v.addWidget(self.f_go)
        b = QPushButton("💾  Créer une image vierge…")
        b.setToolTip("Image vierge pour émulateur, ou à remplir dans l'explorateur puis écrire")
        b.clicked.connect(self.create_blank)
        v.addWidget(b)
        v.addStretch()
        self.f_group.currentIndexChanged.connect(self._fmt_group_changed)
        self.f_spec.currentIndexChanged.connect(self._fmt_spec_changed)
        self._fmt_group_changed()
        self.f_spec.setCurrentIndex(max(0, self.f_spec.findText(MK.SPECS[3].label)))
        return w

    def _fmt_group_changed(self):
        gname = self.f_group.currentText()
        low = self.f_group.currentIndex() == self.f_group.count() - 1
        self.f_spec.blockSignals(True)
        self.f_spec.clear()
        for sp in MK.SPECS:
            if sp.group == gname:
                self.f_spec.addItem(sp.label, sp)
        self.f_spec.blockSignals(False)
        self.f_spec.setEnabled(not low)
        self.f_low.setVisible(low)
        self._fmt_spec_changed()

    def _fmt_spec(self) -> Optional[MK.MkSpec]:
        if self.f_group.currentIndex() == self.f_group.count() - 1:
            return None
        return self.f_spec.currentData()

    def _fmt_spec_changed(self):
        sp = self._fmt_spec()
        if sp is None:
            self.f_label.setEnabled(False)
            self.f_info.setText("")
            return
        self.f_label.setEnabled(sp.max_label > 0)
        self.f_label.setMaxLength(max(sp.max_label, 1))
        g = F.geometry(sp.fmt)
        txt = f"<code>{sp.fmt}</code> · " + (g.desc if g else "")
        if sp.note:
            txt += f"<br>{html.escape(sp.note)}"
        self.f_info.setText(txt)

    def _format_payload(self):
        """(données, extension d'écriture, format) selon la page Formater."""
        sp = self._fmt_spec()
        if sp is None:
            pr = self.f_pick.preset()
            if pr is None or not pr.fmt:
                raise ValueError("Choisissez un format décodé (pas un flux brut).")
            g = F.geometry(pr.fmt)
            if not g or not g.capacity:
                raise ValueError("Géométrie inconnue pour ce format.")
            ext = ".fd" if pr.fmt.startswith("thomson") else ".img"
            return MK.blank_for(pr.fmt, g.capacity, self.f_fill.value()), ext, pr.fmt, pr.fmt
        ext = {".dsk": ".img", ".st": ".img"}.get(sp.ext, sp.ext)
        return sp.build(self.f_label.text().strip()), ext, sp.fmt, f"{sp.group} — {sp.label}"

    def start_format(self):
        try:
            data, ext, fmt, desc = self._format_payload()
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        if QMessageBox.warning(
                self, "Confirmer le formatage",
                f"La disquette va être <b>entièrement effacée</b> et formatée en :<br><br><b>"
                f"{html.escape(desc)}</b><br><br>Vérifiez que la disquette n'est pas protégée en écriture.",
                QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return
        path = os.path.join(EM.session_dir(), f"format_{int(time.time())}{ext}")
        with open(path, "wb") as fh:
            fh.write(data)
        self._write_file(path, fmt, self.f_verify.isChecked(), self.f_erase.isChecked(),
                         f"Formatage — {desc}")

    def create_blank(self):
        sp = self._fmt_spec()
        try:
            data, ext, fmt, desc = self._format_payload()
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, str(e))
            return
        ext = sp.ext if sp else ext
        name = (self.f_label.text().strip() or "vierge") + ext
        p, _ = QFileDialog.getSaveFileName(self, "Créer une image vierge",
                                           os.path.join(self._last_dir(), name), f"*{ext}")
        if not p:
            return
        if sp:
            MK.save_blank(sp, self.f_label.text().strip(), p)
        else:
            with open(p, "wb") as fh:
                fh.write(data)
        self.log(f"Image vierge créée : {p}", "ok")
        if QMessageBox.question(self, APP_NAME, "Image créée. L'ouvrir dans l'explorateur pour y "
                                "ajouter des fichiers ?") == QMessageBox.Yes:
            self.explore(p)

    def _write_file(self, path, fmt, verify, erase, title, retries=3, tracks=None):
        if not self.dev.connected:
            QMessageBox.information(self, APP_NAME, "Connectez d'abord le Greaseweazle.")
            return
        try:
            planned, cyls = self._planned(fmt, tracks, "c=0-79:h=0-1")
        except Exception:
            planned, cyls = None, 80
        g = F.geometry(fmt)
        self._reset_stats(cyls, [0, 1], g.nsec if g else 0, planned)
        job = E.WriteJob(self.dev, self._drive(), path, fmt, tracks, verify, erase, retries, False)
        self.run_job(job, title)

    def write_image_now(self, path: str, fmt: str, tracks: str = ""):
        """Demande de l'explorateur : écrire l'image modifiée sur la disquette."""
        if QMessageBox.warning(
                self, "Confirmer l'écriture",
                f"Écrire <code>{html.escape(os.path.basename(path))}</code> sur la disquette "
                f"(format {html.escape(fmt)}) ?<br>Le contenu actuel sera remplacé.",
                QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return
        self.nav.setCurrentRow(1)
        self.right.setCurrentIndex(0)
        self._write_file(path, fmt, True, False, f"Écriture ← {os.path.basename(path)}"
                         + (f" ({tracks})" if tracks else ""), tracks=tracks or None)

    # --- Copier / comparer / tester
    def _page_copy(self):
        w, v = self._page("Copier et vérifier", "Duplication, comparaison, test de surface.")
        g = QGroupBox("Format de la disquette")
        gl = QVBoxLayout(g)
        self.cp_pick = FormatPicker()
        self.cp_pick.select_format("ibm.1440")
        gl.addWidget(self.cp_pick)
        v.addWidget(g)

        g = QGroupBox("Copie de disquette")
        gl = QVBoxLayout(g)
        gl.addWidget(_muted("Lit la disquette source, puis demande d'insérer la disquette de destination. "
                            "Choisissez « Flux brut » pour copier les disquettes protégées."))
        self.c_verify = QCheckBox("Vérifier l'écriture")
        self.c_verify.setChecked(True)
        self.c_keep = QCheckBox("Conserver l'image de la source")
        self.c_keep.setToolTip("Enregistre l'image lue dans le dossier des images (nom horodaté)")
        gl.addWidget(self.c_verify)
        gl.addWidget(self.c_keep)
        self.c_go = QPushButton("📑  Copier une disquette")
        self.c_go.setObjectName("primary")
        self.c_go.clicked.connect(self.start_copy)
        gl.addWidget(self.c_go)
        v.addWidget(g)

        g = QGroupBox("Comparer avec une image")
        gl = QVBoxLayout(g)
        self.c_ref = QLineEdit()
        self.c_ref.setPlaceholderText("Image de référence…")
        bb = QPushButton("…")
        bb.setFixedWidth(40)
        bb.clicked.connect(lambda: self._browse_open(self.c_ref))
        gl.addWidget(_row(self.c_ref, bb))
        self.c_cmp = QPushButton("⚖  Lire et comparer")
        self.c_cmp.clicked.connect(self.start_compare)
        gl.addWidget(self.c_cmp)
        self.c_cmp_lbl = _muted("")
        gl.addWidget(self.c_cmp_lbl)
        v.addWidget(g)

        g = QGroupBox("Test de surface")
        gl = QVBoxLayout(g)
        gl.addWidget(_muted("Lit toute la disquette sans rien enregistrer et affiche les secteurs faibles "
                            "ou illisibles sur la carte."))
        self.c_surf = QPushButton("🩺  Tester la surface")
        self.c_surf.clicked.connect(self.start_surface)
        gl.addWidget(self.c_surf)
        v.addWidget(g)

        g = QGroupBox("Récupération des secteurs illisibles")
        gl = QVBoxLayout(g)
        gl.addWidget(_muted("Relit uniquement les secteurs manquants d'une image (format ci-dessus), en "
                            "plusieurs passes avec repositionnement de la tête, et complète l'image. "
                            "Ou fusionne plusieurs lectures du même disque (lecteurs différents…)."))
        self.c_rec = QLineEdit()
        self.c_rec.setPlaceholderText("Image à compléter (IMG, ST, ADF, FD…)")
        bb = QPushButton("…")
        bb.setFixedWidth(40)
        bb.clicked.connect(lambda: self._browse_open(self.c_rec))
        gl.addWidget(_row(self.c_rec, bb))
        self.c_passes = QSpinBox()
        self.c_passes.setRange(1, 200)
        self.c_passes.setValue(20)
        gl.addWidget(_row(QLabel("Passes par piste"), self.c_passes, None))
        self.c_rec_go = QPushButton("♻  Relire les secteurs illisibles")
        self.c_rec_go.clicked.connect(self.start_recover)
        gl.addWidget(self.c_rec_go)
        b = QPushButton("🧬  Fusionner avec d'autres lectures…")
        b.clicked.connect(self.start_merge)
        gl.addWidget(b)
        self.c_rec_lbl = _muted("")
        gl.addWidget(self.c_rec_lbl)
        v.addWidget(g)
        v.addStretch()
        return w

    def _rec_check(self):
        p = self.c_rec.text().strip()
        pr = self.cp_pick.preset()
        if not os.path.isfile(p):
            QMessageBox.warning(self, APP_NAME, "Choisissez l'image à compléter.")
            return None
        if pr is None or not pr.fmt or pr.fmt == "ibm.scan":
            QMessageBox.warning(self, APP_NAME, "Choisissez le format exact de l'image (pas « scan » ni flux).")
            return None
        if F.is_flux_image(p) or os.path.splitext(p)[1].lower() in (".edsk", ".imd", ".hfe", ".scp", ".d64"):
            QMessageBox.warning(self, APP_NAME, "Seules les images secteurs brutes (IMG, ST, ADF, FD, D81…) "
                                "peuvent être complétées.")
            return None
        return p, pr.fmt

    def start_recover(self):
        r = self._rec_check()
        if not r:
            return
        if not self.dev.connected:
            QMessageBox.information(self, APP_NAME, "Connectez d'abord le Greaseweazle.")
            return
        p, fmt = r
        self._reset_stats(80, [0, 1], F.geometry(fmt).nsec if F.geometry(fmt) else 0, None)
        self.run_job(E.RecoverJob(self.dev, self._drive(), p, fmt, self.c_passes.value()),
                     f"Récupération ← {os.path.basename(p)}")

    def start_merge(self):
        r = self._rec_check()
        if not r:
            return
        p, fmt = r
        others, _ = QFileDialog.getOpenFileNames(self, "Autres lectures du même disque", os.path.dirname(p))
        others = [o for o in others if os.path.abspath(o) != os.path.abspath(p)]
        if others:
            self.run_job(E.RecoverJob(self.dev, self._drive(), p, fmt, merge=others), "Fusion de lectures")

    def _copy_read(self, purpose: str, ext: Optional[str] = None):
        if not self.dev.connected:
            QMessageBox.information(self, APP_NAME, "Connectez d'abord le Greaseweazle.")
            return None
        pr = self.cp_pick.preset()
        if pr is None:
            return None
        ext = ext or pr.ext
        if purpose == "copy" and self.c_keep.isChecked():
            path = self._auto_name(ext)
        else:
            path = os.path.join(EM.session_dir(), f"{purpose}_{int(time.time())}{ext}")
        try:
            planned, cyls = self._planned(pr.fmt, pr.tracks, "c=0-79:h=0-1")
        except Exception:
            planned, cyls = None, 80
        g = F.geometry(pr.fmt)
        self._reset_stats(cyls, [0, 1], g.nsec if g else 0, planned)
        self._pending = {"purpose": purpose, "path": path, "fmt": pr.fmt, "tracks": pr.tracks}
        job = E.ReadJob(self.dev, self._drive(), path, pr.fmt, pr.tracks, self.r_revs.value() or None,
                        self.r_retries.value(), self.r_seek.value())
        titles = {"copy": "Copie : lecture de la source", "cmp": "Comparaison : lecture",
                  "surf": "Test de surface"}
        self.run_job(job, titles[purpose])
        return path

    def start_copy(self):
        self._copy_read("copy")

    def start_surface(self):
        self._copy_read("surf")

    def start_compare(self):
        ref = self.c_ref.text().strip()
        if not os.path.isfile(ref):
            QMessageBox.warning(self, APP_NAME, "Choisissez l'image de référence.")
            return
        pr = self.cp_pick.preset()
        if pr is None or not pr.fmt:
            QMessageBox.warning(self, APP_NAME, "Choisissez le format décodé de la disquette.")
            return
        self.c_cmp_lbl.setText("")
        self._copy_read("cmp", ".img")

    def _after_pending(self):
        p, self._pending = getattr(self, "_pending", None), None
        if not p or not os.path.isfile(p["path"]):
            return
        if not p.get("ok"):
            if p["purpose"] != "copy" or not self.c_keep.isChecked():
                try:
                    os.remove(p["path"])
                except OSError:
                    pass
            return
        if p["purpose"] == "surf":
            try:
                os.remove(p["path"])
            except OSError:
                pass
        elif p["purpose"] == "cmp":
            self._compare(p)
        elif p["purpose"] == "copy":
            if QMessageBox.information(
                    self, "Copie", "Lecture terminée.<br><br>Insérez la disquette de <b>destination</b> "
                    "(son contenu sera remplacé), puis cliquez OK.",
                    QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
                return
            self._write_file(p["path"], p["fmt"], self.c_verify.isChecked(), False,
                             "Copie : écriture de la destination")

    def _compare(self, p):
        ref = self.c_ref.text().strip()
        try:
            a = open_disk(ref, p["fmt"])
            b = open_disk(p["path"], p["fmt"])
        except Exception as e:
            self.c_cmp_lbl.setText(f"Comparaison impossible : {html.escape(str(e))}")
            return
        diffs, missing, total = [], 0, 0
        if a.tracks and b.tracks:
            for (c, h), secs in sorted(a.tracks.items()):
                for s in secs:
                    total += 1
                    t = b.sector(c, h, s.r)
                    if t is None or not t.ok:
                        missing += 1
                        diffs.append(f"{c}.{h}.{s.r} illisible")
                    elif (t.data or b"") != (s.data or b""):
                        diffs.append(f"{c}.{h}.{s.r} différent")
        else:
            la, lb = a.linear(), b.linear()
            ss = 512
            total = len(la) // ss
            for i in range(total):
                if la[i * ss:(i + 1) * ss] != lb[i * ss:(i + 1) * ss]:
                    diffs.append(f"secteur logique {i} différent")
        os.remove(p["path"]) if os.path.dirname(p["path"]) == EM.session_dir() else None
        if not diffs:
            msg = f"✔ Identique : {total} secteurs comparés."
            self.log(msg, "ok")
        else:
            msg = f"✖ {len(diffs)} secteur(s) sur {total} diffèrent ({missing} illisible(s))."
            self.log(msg + "\n" + ", ".join(diffs[:200]), "warn")
        self.c_cmp_lbl.setText(msg)

    def export_map(self):
        p, _ = QFileDialog.getSaveFileName(self, "Exporter la carte",
                                           os.path.join(self._last_dir(), "carte.png"), "PNG (*.png)")
        if p:
            self.map.grab().save(p, "PNG")
            self.log(f"Carte exportée : {p}", "ok")

    # --- Analyser
    def _page_analyse(self):
        w, v = self._page("Analyser", "Lit quelques pistes et identifie le format le plus probable.")
        self.a_go = QPushButton("🔍  Analyser la disquette")
        self.a_go.setObjectName("primary")
        self.a_go.clicked.connect(self.start_analyse)
        v.addWidget(self.a_go)
        fr, fl = card("Résultat")
        self.a_rpm = StatTile("Vitesse (tr/min)")
        self.a_dens = _muted("—")
        fl.addWidget(self.a_rpm)
        fl.addWidget(QLabel("Densité estimée"))
        fl.addWidget(self.a_dens)
        self.a_table = QTableWidget(0, 2)
        self.a_table.setHorizontalHeaderLabels(["Format probable", "Secteurs"])
        self.a_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.a_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.a_table.verticalHeader().hide()
        self.a_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.a_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.a_table.setMinimumHeight(200)
        self.a_table.doubleClicked.connect(self._use_analysed)
        fl.addWidget(self.a_table)
        self.a_scan = _muted("")
        fl.addWidget(self.a_scan)
        b = QPushButton("Utiliser ce format pour la lecture")
        b.clicked.connect(self._use_analysed)
        fl.addWidget(b)
        v.addWidget(fr)

        g = QGroupBox("Analyse complète (qualité, protections)")
        gl = QVBoxLayout(g)
        gl.addWidget(_muted("Lit toute la disquette au format choisi dans « Lire », mesure la qualité du "
                            "signal piste par piste et recherche les protections (secteurs faibles, "
                            "tailles non standard, pistes longues, IDs falsifiés…)."))
        self.a_full = QPushButton("🧪  Analyser toute la disquette")
        self.a_full.clicked.connect(self.start_full_analyse)
        gl.addWidget(self.a_full)
        gl.addWidget(_muted("Ou une image flux existante (SCP, HFE, KryoFlux…) sans lecteur :"))
        self.a_img = QLineEdit()
        self.a_img.setPlaceholderText("Image flux…")
        bb = QPushButton("…")
        bb.setFixedWidth(40)
        bb.clicked.connect(lambda: self._browse_open(self.a_img))
        gl.addWidget(_row(self.a_img, bb))
        b = QPushButton("🧪  Analyser l'image flux")
        b.clicked.connect(self.start_flux_analyse)
        gl.addWidget(b)
        v.addWidget(g)
        v.addStretch()
        return w

    def start_full_analyse(self):
        if not self.dev.connected:
            QMessageBox.information(self, APP_NAME, "Connectez d'abord le Greaseweazle.")
            return
        pr = self.r_pick.preset()
        ext = ".scp" if pr is None or pr.fmt is None else ".img"
        if pr is not None and pr.fmt == "ibm.scan":
            ext = ".imd"
        path = os.path.join(EM.session_dir(), f"analyse_{int(time.time())}{ext}")
        tracks = self.r_tracks.text().strip() or (pr.tracks if pr else None)
        fmt = pr.fmt if pr else None
        try:
            planned, cyls = self._planned(fmt, tracks, "c=0-79:h=0-1")
        except Exception:
            planned, cyls = None, 80
        g = F.geometry(fmt)
        self._reset_stats(cyls, [0, 1], g.nsec if g else 0, planned)
        self._health_btn.setChecked(True)
        self._last_image = None
        self._last_fmt = fmt
        job = E.ReadJob(self.dev, self._drive(), path, fmt, tracks, self.r_revs.value() or 3,
                        self.r_retries.value(), self.r_seek.value(), deep=True)
        self.run_job(job, "Analyse complète")

    def start_flux_analyse(self):
        p = self.a_img.text().strip()
        if not os.path.isfile(p):
            QMessageBox.warning(self, APP_NAME, "Choisissez une image flux.")
            return
        self._reset_stats(80, [0, 1], 0, None)
        self._health_btn.setChecked(True)
        self._last_image = p
        self.run_job(E.FluxAnalyseJob(self.dev, p, None), f"Analyse ← {os.path.basename(p)}")

    def show_report(self):
        if not self.track_results:
            QMessageBox.information(self, APP_NAME, "Aucune piste lue ou analysée pour l'instant.")
            return
        fmt = getattr(self, "_last_fmt", None)
        fnd = A.detect_protections(self.track_results, fmt)
        rs = list(self.track_results.values())
        tot = sum(x.nsec for x in rs)
        bad = sum(x.nbad for x in rs)
        qs = [x.quality for x in rs if x.quality]
        rpms = [x.rpm for x in rs if x.rpm]
        info = [("Pistes", str(len(rs))), ("Secteurs lisibles", f"{tot - bad}/{tot}"),
                ("Secteurs illisibles", str(bad)),
                ("Pistes relues", str(sum(1 for x in rs if x.retries))),
                ("Vitesse moyenne", f"{sum(rpms) / len(rpms):.2f} tr/min" if rpms else "—"),
                ("Qualité moyenne", f"{sum(qs) / len(qs):.1f} % — {A.quality_label(sum(qs) / len(qs))}"
                 if qs else "—"),
                ("Pire piste", (lambda w: f"{w.cyl}.{w.head} ({w.quality:.1f} %)")(
                    min((x for x in rs if x.quality), key=lambda x: x.quality)) if qs else "—"),
                ("Format", fmt or "—")]
        if self.dev.info:
            info.append(("Matériel", f"{self.dev.info.model} fw {self.dev.info.firmware[0]}."
                                     f"{self.dev.info.firmware[1]}"))
        dlg = QDialog(self)
        dlg.setWindowTitle("Rapport de la disquette")
        dlg.resize(820, 560)
        lay = QVBoxLayout(dlg)
        t = QTableWidget(len(info), 2)
        t.horizontalHeader().hide()
        t.verticalHeader().hide()
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for i, (k, v) in enumerate(info):
            t.setItem(i, 0, QTableWidgetItem(k))
            t.setItem(i, 1, QTableWidgetItem(v))
        t.resizeColumnToContents(0)
        t.resizeRowsToContents()
        t.setFixedHeight(t.verticalHeader().length() + 6)
        lay.addWidget(t)
        lab = QLabel(f"<b>Protections et anomalies : {len(fnd) or 'aucune'}</b>")
        lay.addWidget(lab)
        ft = QTableWidget(len(fnd), 3)
        ft.setHorizontalHeaderLabels(["Piste", "Constat", "Schémas possibles"])
        ft.verticalHeader().hide()
        ft.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        ft.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        ft.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for i, f in enumerate(fnd):
            for k, val in enumerate((f["where"], f["text"], f["schemes"])):
                ft.setItem(i, k, QTableWidgetItem(val))
        ft.cellDoubleClicked.connect(lambda r, _c: self._show_track(*map(int, fnd[r]["where"].split("."))))
        lay.addWidget(ft, 1)
        bb = QHBoxLayout()
        bx = QPushButton("💾  Exporter HTML / PDF…")
        bb.addStretch()
        bb.addWidget(bx)
        bc = QPushButton("Fermer")
        bc.clicked.connect(dlg.accept)
        bb.addWidget(bc)
        lay.addLayout(bb)

        def export():
            p, _ = QFileDialog.getSaveFileName(dlg, "Exporter le rapport",
                                               os.path.join(self._last_dir(), "rapport.html"),
                                               "Page web (*.html);;PDF (*.pdf)")
            if not p:
                return
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            self.map.grab().save(buf, "PNG")
            img = getattr(self, "_last_image", None)
            txt = A.report_html(f"Rapport — {os.path.basename(img) if img else 'disquette'}", info,
                                self.track_results, bytes(ba), fnd,
                                img if img and os.path.isfile(img) else None)
            A.save_report(p, txt)
            self.log(f"Rapport exporté : {p}", "ok")
            if hasattr(os, "startfile"):
                os.startfile(p)
        bx.clicked.connect(export)
        dlg.exec()

    # --- Explorer
    def _page_explore(self):
        w, v = self._page("Explorer", "Parcourt les fichiers d'une image : aperçu, export, exécution.")
        b = QPushButton("📂  Ouvrir une image…")
        b.setObjectName("primary")
        b.clicked.connect(self._explore_browse)
        v.addWidget(b)
        b = QPushButton("📥  Lire et explorer la disquette")
        b.setToolTip("Utilise le format choisi dans « Lire »")
        b.clicked.connect(self._read_and_explore)
        self.x_read = b
        v.addWidget(b)
        b = QPushButton("Explorer la dernière image lue")
        b.clicked.connect(self._explore_last)
        self.x_last = b
        v.addWidget(b)

        g = QGroupBox("Décodage des images flux (SCP, HFE, RAW…)")
        gl = QVBoxLayout(g)
        self.x_auto = QCheckBox("Détection automatique du codage")
        self.x_auto.setChecked(True)
        gl.addWidget(self.x_auto)
        self.x_pick = FormatPicker()
        self.x_pick.setEnabled(False)
        self.x_auto.toggled.connect(lambda on: self.x_pick.setEnabled(not on))
        gl.addWidget(self.x_pick)
        v.addWidget(g)

        g = QGroupBox("Images récentes")
        gl = QVBoxLayout(g)
        self.x_recent = QListWidget()
        self.x_recent.setMinimumHeight(150)
        self.x_recent.itemDoubleClicked.connect(lambda it: self.explore(it.data(Qt.UserRole)))
        gl.addWidget(self.x_recent)
        v.addWidget(g)

        b = QPushButton("⚙  Configurer les émulateurs…")
        b.clicked.connect(lambda: EmulatorDialog(self).exec())
        v.addWidget(b)
        v.addWidget(_muted("Systèmes reconnus : FAT12/16 (PC, Atari ST, MSX, synthés DOS), AmigaDOS OFS/FFS, "
                           "Commodore 1541/1571/1581, DOS BASIC Thomson, Amstrad CPC (AMSDOS/CP/M), "
                           "Akai S900/S1000/S3000 (expérimental)."))
        v.addStretch()
        return w

    def _nav_changed(self, row):
        if hasattr(self, "right"):
            self.right.setCurrentIndex(1 if row == EXPLORER_ROW else 0)

    def _recent_list(self):
        r = self.settings.value("recent_images") or []
        return [x for x in (r if isinstance(r, list) else [r]) if x]

    def _fill_recent(self):
        self.x_recent.clear()
        for p in self._recent_list():
            it = QListWidgetItem(os.path.basename(p))
            it.setToolTip(p)
            it.setData(Qt.UserRole, p)
            self.x_recent.addItem(it)

    def _explore_browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Ouvrir une image", self._last_dir(), F.image_filter())
        if p:
            self.settings.setValue("last_dir", os.path.dirname(p))
            self.explore(p)

    def explore(self, path: str):
        if not path or not os.path.isfile(path):
            QMessageBox.warning(self, APP_NAME, "Fichier introuvable.")
            return
        r = [path] + [x for x in self._recent_list() if x != path]
        self.settings.setValue("recent_images", r[:15])
        self._fill_recent()
        fmt = None
        if not self.x_auto.isChecked():
            pr = self.x_pick.preset()
            fmt = pr.fmt if pr else None
        self.nav.setCurrentRow(EXPLORER_ROW)
        self.explorer.open_path(path, fmt)

    def _explore_last(self):
        p = self.settings.value("last_read")
        if p and os.path.isfile(p):
            self.explore(p)
        else:
            QMessageBox.information(self, APP_NAME, "Aucune image lue récemment.")

    def _read_and_explore(self):
        if not self.dev.connected:
            QMessageBox.information(self, APP_NAME, "Connectez d'abord le Greaseweazle.")
            return
        self._explore_after_read = True
        self.nav.setCurrentRow(0)
        self.start_read()

    # --- Outils
    def _page_tools(self):
        w, v = self._page("Outils du lecteur", "Diagnostic et maintenance.")

        fr, fl = card("Vitesse de rotation")
        self.t_rpm_n = QSpinBox()
        self.t_rpm_n.setRange(2, 200)
        self.t_rpm_n.setValue(20)
        b = QPushButton("Mesurer")
        b.clicked.connect(self.start_rpm)
        fl.addWidget(_row(QLabel("Mesures"), self.t_rpm_n, None, b))
        self.t_rpm_chart = RpmChart()
        fl.addWidget(self.t_rpm_chart)
        self.t_rpm_lbl = _muted("Un lecteur 3,5\" sain tourne à 300 tr/min ±1,5 %.")
        fl.addWidget(self.t_rpm_lbl)
        v.addWidget(fr)

        fr, fl = card("Calibrage / alignement")
        fl.addWidget(_muted("Lit en boucle des pistes de référence d'une disquette saine au format choisi dans "
                            "« Lire » et affiche la qualité du signal en direct : utile pour régler l'alignement "
                            "radial (vis de la tête) ou comparer des lecteurs. Annuler pour arrêter."))
        self.t_cal_tracks = QLineEdit("0.0, 40.0, 79.0, 0.1, 40.1, 79.1")
        self.t_cal_tracks.setToolTip("Pistes « cylindre.face » lues à tour de rôle")
        b = QPushButton("▶  Démarrer")
        b.clicked.connect(self.start_calibrate)
        fl.addWidget(_row(QLabel("Pistes"), self.t_cal_tracks, b))
        self.t_cal_chart = RpmChart((80, 95, 100), 120)
        fl.addWidget(self.t_cal_chart)
        self.t_cal_lbl = _muted("Qualité > 97 % : excellent · 92–97 % : correct · < 90 % : réglage ou support à vérifier.")
        self.t_cal_lbl.setTextFormat(Qt.RichText)
        fl.addWidget(self.t_cal_lbl)
        v.addWidget(fr)

        fr, fl = card("Déplacer la tête")
        self.t_cyl = QSpinBox()
        self.t_cyl.setRange(0, 85)
        self.t_head = QComboBox()
        self.t_head.addItems(["Face 0", "Face 1"])
        b = QPushButton("Aller")
        b.clicked.connect(self.start_seek)
        b0 = QPushButton("Piste 0")
        b0.clicked.connect(lambda: (self.t_cyl.setValue(0), self.start_seek()))
        fl.addWidget(_row(QLabel("Cylindre"), self.t_cyl, self.t_head, None))
        fl.addWidget(_row(None, b0, b))
        v.addWidget(fr)

        fr, fl = card("Nettoyage des têtes")
        fl.addWidget(_muted("Insérer une disquette de nettoyage (humidifiée) avant de lancer."))
        self.t_passes = QSpinBox()
        self.t_passes.setRange(1, 20)
        self.t_passes.setValue(3)
        b = QPushButton("Nettoyer")
        b.clicked.connect(self.start_clean)
        fl.addWidget(_row(QLabel("Passes"), self.t_passes, None, b))
        v.addWidget(fr)

        fr, fl = card("Effacement")
        fl.addWidget(_muted("Efface magnétiquement toutes les pistes (contenu définitivement perdu)."))
        self.t_erase_heads = QComboBox()
        self.t_erase_heads.addItems(["2 faces, 80 cyl.", "Face 0, 80 cyl.", "2 faces, 84 cyl."])
        b = QPushButton("Effacer la disquette")
        b.setObjectName("danger")
        b.clicked.connect(self.start_erase)
        fl.addWidget(self.t_erase_heads)
        fl.addWidget(_row(None, b))
        v.addWidget(fr)

        fr, fl = card("Greaseweazle")
        b1 = QPushButton("Réinitialiser")
        b1.clicked.connect(lambda: self.run_job(E.ResetJob(self.dev)))
        b2 = QPushButton("Vérifier firmware")
        b2.clicked.connect(lambda: self.run_job(E.FirmwareCheckJob(self.dev)))
        b3 = QPushButton("Mettre à jour…")
        b3.clicked.connect(self.start_fw_update)
        fl.addWidget(_row(b1, b2))
        fl.addWidget(_row(b3, None))
        v.addWidget(fr)
        v.addStretch()
        return w

    # --- Convertir
    def _page_convert(self):
        w, v = self._page("Convertir", "Convertit une image vers un autre format (sans le lecteur).")
        g = QGroupBox("Image disque")
        f = QFormLayout(g)
        self.c_src = QLineEdit()
        bs = QPushButton("…")
        bs.setFixedWidth(40)
        bs.clicked.connect(lambda: self._browse_open(self.c_src))
        self.c_dst = QLineEdit()
        bd = QPushButton("…")
        bd.setFixedWidth(40)
        bd.clicked.connect(lambda: self._browse_save(self.c_dst))
        f.addRow("Source", _row(self.c_src, bs))
        f.addRow("Destination", _row(self.c_dst, bd))
        v.addWidget(g)
        g = QGroupBox("Format de décodage")
        gl = QVBoxLayout(g)
        self.c_pick = FormatPicker()
        gl.addWidget(self.c_pick)
        gl.addWidget(_muted("Requis pour passer d'un flux (SCP, HFE…) à une image secteurs (IMG, ADF…)."))
        v.addWidget(g)
        b = QPushButton("🔁  Convertir l'image")
        b.setObjectName("primary")
        b.clicked.connect(self.start_convert)
        v.addWidget(b)

        g = QGroupBox("Conversion de fichiers")
        gl = QVBoxLayout(g)
        self.fc_kind = QComboBox()
        for label, key in (("Texte → BASIC CPC (Locomotive)", "loco"),
                           ("Texte → MSX-BASIC", "msx"),
                           ("Texte → GW-BASIC (PC)", "gw"),
                           ("Image → écran CPC mode 0 (16 coul.)", "scr0"),
                           ("Image → écran CPC mode 1 (4 coul.)", "scr1"),
                           ("Image → écran CPC mode 2 (2 coul.)", "scr2"),
                           ("WAV → sample Akai S1000 (expér.)", "akai")):
            self.fc_kind.addItem(label, key)
        self.fc_kind.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.fc_kind.setMinimumContentsLength(16)
        gl.addWidget(self.fc_kind)
        self.fc_src = QLineEdit()
        self.fc_src.setPlaceholderText("Fichier source…")
        bb = QPushButton("…")
        bb.setFixedWidth(40)
        bb.clicked.connect(lambda: self._browse_any(self.fc_src))
        gl.addWidget(_row(self.fc_src, bb))
        self.fc_dither = QCheckBox("Tramage des images (Floyd-Steinberg)")
        self.fc_dither.setChecked(True)
        gl.addWidget(self.fc_dither)
        b = QPushButton("🔁  Convertir le fichier…")
        b.clicked.connect(self.convert_file)
        gl.addWidget(b)
        gl.addWidget(_muted("Le résultat peut ensuite être ajouté à une image dans l'explorateur. Pour un écran "
                            "CPC, un chargeur BASIC (encres + LOAD) est créé à côté."))
        v.addWidget(g)
        v.addStretch()
        return w

    def _browse_any(self, edit: QLineEdit):
        p, _ = QFileDialog.getOpenFileName(self, "Choisir un fichier", self._last_dir())
        if p:
            edit.setText(p)
            self.settings.setValue("last_dir", os.path.dirname(p))

    def convert_file(self):
        from . import convert as CV
        src = self.fc_src.text().strip()
        if not os.path.isfile(src):
            QMessageBox.warning(self, APP_NAME, "Choisissez le fichier source.")
            return
        kind = self.fc_kind.currentData()
        base = os.path.splitext(os.path.basename(src))[0]
        short = "".join(c for c in base.upper() if c.isalnum())[:8] or "FICHIER"
        try:
            if kind in ("loco", "msx", "gw"):
                with open(src, "r", encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                if kind == "loco":
                    data = CV.amsdos_file(short + ".BAS", CV.tokenize_locomotive(text))
                else:
                    data = CV.tokenize_ms(text, kind)
                outs = [(short + ".BAS", data)]
            elif kind.startswith("scr"):
                from PySide6.QtGui import QImage
                img = QImage(src)
                if img.isNull():
                    raise ValueError("image illisible")
                mode = int(kind[3])
                scr, inks = CV.image_to_cpc(img, mode, self.fc_dither.isChecked())
                loader = CV.tokenize_locomotive(CV.cpc_loader(short + ".SCR", mode, inks))
                outs = [(short + ".SCR", CV.amsdos_file(short + ".SCR", scr, 2, 0xC000, 0)),
                        ("LOADER.BAS", CV.amsdos_file("LOADER.BAS", loader))]
                self.log(f"Encres CPC : {', '.join(map(str, inks))}", "info")
            else:
                with open(src, "rb") as fh:
                    data, rate, n = CV.wav_to_akai(fh.read(), base)
                outs = [(short + ".S", data)]
                self.log(f"Sample Akai : {n} échantillons à {rate} Hz", "info")
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Conversion impossible : {e}")
            return
        d = QFileDialog.getExistingDirectory(self, "Dossier de destination", os.path.dirname(src))
        if not d:
            return
        for name, data in outs:
            p = os.path.join(d, name)
            with open(p, "wb") as fh:
                fh.write(data)
            self.log(f"Converti : {p}", "ok")

    # --- Appareil
    def _page_device(self):
        w, v = self._page("Appareil", "Informations sur le Greaseweazle connecté.")
        fr, fl = card()
        self.d_grid = QGridLayout()
        self.d_grid.setHorizontalSpacing(16)
        fl.addLayout(self.d_grid)
        v.addWidget(fr)
        v.addWidget(_muted(
            "Astuce : sur un câble PC à torsade, le lecteur branché après la torsade est le lecteur A. "
            "Un lecteur 3,5\" seul sur un câble droit se pilote généralement en Shugart DS0 ou DS1."))
        v.addStretch()
        return w

    def _workspace_header(self):
        top = QWidget()
        l = QHBoxLayout(top)
        l.setContentsMargins(0, 0, 0, 0)
        self.ws_title = QLabel("Carte de la disquette")
        self.ws_title.setObjectName("h2")
        l.addWidget(self.ws_title)
        l.addStretch()
        grp = QButtonGroup(self)
        for i, (k, label) in enumerate([("grid", "Grille"), ("disk", "Disque")]):
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _=False, k=k: self.map.set_mode(k))
            grp.addButton(b)
            l.addWidget(b)
        hb = QPushButton("Santé")
        hb.setObjectName("seg")
        hb.setCheckable(True)
        hb.setToolTip("Colore les pistes selon la qualité du signal magnétique\n(violet : secteurs faibles)")
        hb.toggled.connect(self.map.set_health if hasattr(self, "map") else lambda _: None)
        self._health_btn = hb
        l.addWidget(hb)
        b = QPushButton("📋")
        b.setToolTip("Rapport : protections, anomalies, export HTML / PDF")
        b.setFixedWidth(40)
        b.clicked.connect(self.show_report)
        l.addWidget(b)
        b = QPushButton("🖼")
        b.setToolTip("Exporter la carte en PNG")
        b.setFixedWidth(40)
        b.clicked.connect(self.export_map)
        l.addWidget(b)
        return top

    def _build_workspace(self):
        ws = QWidget()
        ws.setObjectName("root")
        v = QVBoxLayout(ws)
        v.setContentsMargins(14, 14, 14, 10)
        v.setSpacing(10)

        # Statistiques
        stats = QFrame()
        stats.setObjectName("card")
        sl = QHBoxLayout(stats)
        sl.setContentsMargins(16, 10, 16, 10)
        self.s_tracks = StatTile("Pistes")
        self.s_sect = StatTile("Secteurs OK")
        self.s_bad = StatTile("Illisibles")
        self.s_rpm = StatTile("tr/min")
        self.s_time = StatTile("Écoulé / restant")
        for x in (self.s_tracks, self.s_sect, self.s_bad, self.s_rpm, self.s_time):
            sl.addWidget(x)
            sl.addStretch()
        v.addWidget(stats)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(8)
        v.addWidget(split, 1)

        mapcard, ml = card()
        self.map = TrackMap()
        ml.addWidget(self._workspace_header())
        self.map.track_clicked.connect(self._show_track)
        ml.addWidget(self.map, 1)
        ml.addWidget(Legend(["pending", "ok", "retried", "bad", "empty", "flux", "verified", "erased"]))
        split.addWidget(mapcard)

        bottom = QSplitter(Qt.Horizontal)
        bottom.setHandleWidth(8)
        dcard, dl = card("Détail de la piste")
        self.det_lbl = _muted("Survolez ou cliquez une piste.")
        self.det_lbl.setTextFormat(Qt.RichText)
        dl.addWidget(self.det_lbl)
        self.hist = FluxHistogram()
        self.det_tabs = QTabWidget()
        self.det_tabs.setDocumentMode(True)
        self.det_tabs.addTab(self.hist, "Flux")
        self.det_tbl = QTableWidget(0, 7)
        self.det_tbl.setHorizontalHeaderLabels(["#", "ID", "C", "H", "Taille", "En-tête", "Données"])
        self.det_tbl.verticalHeader().hide()
        self.det_tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.det_tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.det_tabs.addTab(self.det_tbl, "Secteurs")
        dl.addWidget(self.det_tabs, 1)
        bottom.addWidget(dcard)

        lcard, ll = card()
        hdr = QWidget()
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(0, 0, 0, 0)
        t = QLabel("Journal")
        t.setObjectName("h2")
        hl.addWidget(t)
        hl.addStretch()
        bclr = QPushButton("Effacer")
        bclr.clicked.connect(lambda: self.logw.clear())
        bsave = QPushButton("Enregistrer…")
        bsave.clicked.connect(self._save_log)
        hl.addWidget(bclr)
        hl.addWidget(bsave)
        ll.addWidget(hdr)
        self.logw = QTextEdit()
        self.logw.setReadOnly(True)
        self.logw.document().setMaximumBlockCount(5000)
        ll.addWidget(self.logw, 1)
        bottom.addWidget(lcard)
        bottom.setSizes([420, 520])
        split.addWidget(bottom)
        split.setSizes([430, 300])

        # Barre de progression
        pb = QWidget()
        pl = QHBoxLayout(pb)
        pl.setContentsMargins(0, 0, 0, 0)
        self.prog = QProgressBar()
        self.prog.setTextVisible(False)
        self.prog_lbl = _muted("", wrap=False)
        self.btn_cancel = QPushButton("Annuler")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.clicked.connect(self.cancel_job)
        self.btn_cancel.setVisible(False)
        pl.addWidget(self.prog, 1)
        pl.addWidget(self.prog_lbl)
        pl.addWidget(self.btn_cancel)
        v.addWidget(pb)
        return ws

    # ------------------------------------------------------------- Connexion
    def refresh_ports(self, auto_connect=False):
        cur = self.port_cb.currentData()
        self.port_cb.clear()
        ports = E.list_ports()
        gw_first = None
        for dev, desc, gw in ports:
            label = f"{dev} — {'Greaseweazle' if gw else desc}"
            self.port_cb.addItem(("★ " if gw else "") + label, dev)
            if gw and gw_first is None:
                gw_first = dev
        if not ports:
            self.port_cb.addItem("Aucun port série", None)
        want = cur or self.settings.value("port") or gw_first
        i = self.port_cb.findData(want)
        if i >= 0:
            self.port_cb.setCurrentIndex(i)
        if auto_connect and gw_first and not self.dev.connected:
            QTimer.singleShot(200, lambda: self.connect_device(self.port_cb.currentData() or gw_first))

    def toggle_connect(self):
        if self.dev.connected:
            if self.job and self.job.isRunning():
                return
            self.dev.close()
            self._chip(False)
            self.log("Déconnecté.", "info")
            self._fill_device(None)
            self._update_enabled()
        else:
            self.connect_device(self.port_cb.currentData())

    def connect_device(self, port):
        try:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            info = self.dev.open(port)
        except Exception as e:
            self._chip(False, "Erreur")
            self.log(f"Connexion impossible ({port}) : {e}", "err")
            self._update_enabled()
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.settings.setValue("port", info.port)
        self._chip(True, f"{info.model} · fw {info.firmware[0]}.{info.firmware[1]}")
        self.log(f"Connecté à {info.model} sur {info.port} (firmware {info.firmware[0]}.{info.firmware[1]}).", "ok")
        if info.update_mode:
            self.log("Le Greaseweazle est en mode mise à jour : seule la mise à jour du firmware est possible.", "warn")
        self._fill_device(info)
        self._update_enabled()

    def _fill_device(self, info):
        while self.d_grid.count():
            it = self.d_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not info:
            self.d_grid.addWidget(_muted("Aucun appareil connecté."), 0, 0)
            return
        for r, (k, val) in enumerate(info.lines()):
            self.d_grid.addWidget(_muted(k, False), r, 0)
            lv = QLabel(val)
            lv.setWordWrap(True)
            lv.setMinimumWidth(80)
            lv.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.d_grid.addWidget(lv, r, 1)
        self.d_grid.setColumnStretch(1, 1)

    def _update_enabled(self):
        busy = bool(self.job and self.job.isRunning())
        ok = self.dev.connected and not busy
        self.btn_conn.setText("Déconnecter" if self.dev.connected else "Connecter")
        self.btn_conn.setEnabled(not busy)
        self.port_cb.setEnabled(not self.dev.connected and not busy)
        self.drive_cb.setEnabled(not busy)
        for b in (self.r_go, self.w_go, self.a_go, self.f_go, self.c_go, self.c_cmp, self.c_surf,
                  self.c_rec_go, self.a_full):
            b.setEnabled(ok)
        self.btn_cancel.setVisible(busy)

    # ---------------------------------------------------------------- Journal
    def log(self, msg: str, level: str = "info"):
        col = T.LOG_COLORS.get(level, T.TEXT)
        ts = time.strftime("%H:%M:%S")
        safe = html.escape(msg).replace("\n", "<br>")
        self.logw.append(f'<span style="color:{T.MUTED}">{ts}</span>&nbsp; '
                         f'<span style="color:{col}">{safe}</span>')
        self.logw.moveCursor(QTextCursor.End)
        if level in ("ok", "warn", "err"):
            self.statusBar().showMessage(msg.splitlines()[0], 8000)

    def _save_log(self):
        p, _ = QFileDialog.getSaveFileName(self, "Enregistrer le journal", "journal.txt", "Texte (*.txt)")
        if p:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.logw.toPlainText())

    # ------------------------------------------------------------ Navigation fichiers
    def _last_dir(self):
        d = self.settings.value("last_dir")
        if d and os.path.isdir(d):
            return d
        d = os.path.join(os.path.expanduser("~"), "Documents", "Floppy Studio")
        os.makedirs(d, exist_ok=True)
        return d

    def _browse_open(self, edit: QLineEdit):
        p, _ = QFileDialog.getOpenFileName(self, "Ouvrir une image", self._last_dir(), F.image_filter())
        if p:
            self.settings.setValue("last_dir", os.path.dirname(p))
            edit.setText(p)
        return p

    def _browse_save(self, edit: QLineEdit, default_name="disquette.img"):
        p, _ = QFileDialog.getSaveFileName(self, "Enregistrer l'image",
                                           os.path.join(self._last_dir(), default_name), F.image_filter())
        if p:
            self.settings.setValue("last_dir", os.path.dirname(p))
            edit.setText(p)
        return p

    def _auto_name(self, ext):
        base = "disquette_" + time.strftime("%Y%m%d_%H%M%S")
        return os.path.join(self._last_dir(), base + ext)

    def _read_browse(self):
        pr = self.r_pick.preset()
        ext = pr.ext if pr else ".img"
        if self._browse_save(self.r_path, "disquette" + ext):
            self.r_auto.setChecked(False)

    def _read_fmt_changed(self):
        pr = self.r_pick.preset()
        if not pr:
            return
        if self.r_auto.isChecked() or not self.r_path.text():
            self.r_path.setText(self._auto_name(pr.ext))
        else:
            root, _ = os.path.splitext(self.r_path.text())
            self.r_path.setText(root + pr.ext)
        self.r_flux.setEnabled(pr.fmt is not None)

    def _write_browse(self):
        if self._browse_open(self.w_path):
            self._write_path_changed()

    def _write_path_changed(self):
        p = self.w_path.text().strip()
        if not p or not os.path.isfile(p):
            self.w_info.setText("")
            return
        ext = os.path.splitext(p)[1].lower()
        size = os.path.getsize(p)
        flux = F.is_flux_image(p)
        self.w_rawfmt.setChecked(flux)
        self.w_rawfmt.setEnabled(flux)
        info = f"{F.IMAGE_DESC.get(ext, ext)} · {size:,} octets".replace(",", " ")
        fmt = F.default_format_for(p)
        guesses = [] if fmt else F.guess_by_size(p)
        if fmt:
            self.w_pick.select_format(fmt)
            info += f"<br>Format : <code>{fmt}</code>"
        elif guesses:
            self.w_pick.select_format(guesses[0])
            info += "<br>Format(s) correspondant à la taille : " + ", ".join(
                f"<code>{g}</code>" for g in guesses[:4])
        elif not flux:
            info += "<br><span style='color:#e3a73b'>Choisissez le format manuellement.</span>"
        self.w_info.setText(info)

    # ---------------------------------------------------------------- Tâches
    def _drive(self):
        return self.drive_cb.currentData()

    def run_job(self, job: E.Job, ws_title: Optional[str] = None):
        if self.job and self.job.isRunning():
            QMessageBox.information(self, APP_NAME, "Une opération est déjà en cours.")
            return
        self.job = job
        job.log.connect(self.log)
        job.track_started.connect(self.map.set_current)
        job.track_done.connect(self._on_track)
        job.progress.connect(self._on_progress)
        job.result.connect(self._on_result)
        job.finished.connect(self._on_finished)
        if ws_title:
            self.ws_title.setText(ws_title)
        self.job_t0 = time.monotonic()
        self.prog.setRange(0, 0)
        self.prog_lbl.setText(job.title + "…")
        self.log(f"— {job.title} —", "info")
        job.start()
        self._update_enabled()

    def cancel_job(self):
        if self.job and self.job.isRunning():
            self.job.cancel()
            self.prog_lbl.setText("Annulation…")

    def _reset_stats(self, cyls, heads, nsec, planned=None):
        self.track_results = {}
        self.map.selected = None
        self.map.reset(cyls, heads, nsec, planned)
        for s in (self.s_tracks, self.s_sect, self.s_bad, self.s_rpm, self.s_time):
            s.set("—")
        self.hist.set_hist([])
        self.det_lbl.setText("Survolez ou cliquez une piste.")

    def _planned(self, fmt, tracks_spec, default):
        d = F.get_diskdef(fmt) if fmt else None
        ts = E._trackset(d, tracks_spec, default)
        pl = {(c, h) for _, _, c, h in E.track_list(ts)}
        cyls = max(c for c, _ in pl) + 1 if pl else 80
        return pl, max(cyls, 80 if cyls > 40 else cyls)

    def start_read(self):
        pr = self.r_pick.preset()
        path = self.r_path.text().strip()
        if self.r_batch.isChecked():
            if not getattr(self, "_batch_active", False):
                self._batch_active, self._batch_count = True, 0
        else:
            self._batch_active = False
        if self.r_auto.isChecked() or not path or getattr(self, "_batch_active", False):
            path = self._auto_name(pr.ext)
            self.r_path.setText(path)
        try:
            F.image_class(path)
        except Exception:
            QMessageBox.warning(self, APP_NAME, "Extension de fichier non reconnue.")
            return
        if os.path.exists(path) and QMessageBox.question(
                self, APP_NAME, f"{os.path.basename(path)} existe déjà. Remplacer ?") != QMessageBox.Yes:
            return
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tracks = self.r_tracks.text().strip() or pr.tracks
        flux_copy = os.path.splitext(path)[0] + ".scp" if (self.r_flux.isChecked() and pr.fmt
                                                         and not F.is_flux_image(path)) else None
        try:
            planned, cyls = self._planned(pr.fmt, tracks, "c=0-79:h=0-1")
        except Exception as e:
            QMessageBox.warning(self, APP_NAME, f"Spécification de pistes invalide : {e}")
            return
        g = F.geometry(pr.fmt)
        self._reset_stats(cyls, [0, 1], g.nsec if g else 0, planned)
        self.settings.setValue("read_fmt", pr.fmt or "")
        self._last_fmt = pr.fmt
        job = E.ReadJob(self.dev, self._drive(), path, pr.fmt, tracks, self.r_revs.value() or None,
                        self.r_retries.value(), self.r_seek.value(), flux_copy,
                        deep=self.r_deep.isChecked())
        self.run_job(job, f"Lecture → {os.path.basename(path)}")

    def start_write(self):
        path = self.w_path.text().strip()
        if not os.path.isfile(path):
            QMessageBox.warning(self, APP_NAME, "Choisissez une image à écrire.")
            return
        flux = F.is_flux_image(path) and self.w_rawfmt.isChecked()
        pr = self.w_pick.preset()
        fmt = None if flux else (pr.fmt if pr else None)
        if not flux and fmt is None:
            QMessageBox.warning(self, APP_NAME, "Sélectionnez le format de l'image.")
            return
        if QMessageBox.warning(
                self, "Confirmer l'écriture",
                f"Le contenu de la disquette va être <b>définitivement remplacé</b> par :<br><br>"
                f"<code>{html.escape(os.path.basename(path))}</code><br>Format : {fmt or 'flux brut'}<br><br>"
                "Vérifiez que la disquette n'est pas protégée en écriture (volet fermé).",
                QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return
        tracks = self.w_tracks.text().strip() or (pr.tracks if pr and not flux else None)
        try:
            planned, cyls = self._planned(fmt, tracks, "c=0-79:h=0-1")
        except Exception:
            planned, cyls = None, 80
        g = F.geometry(fmt)
        self._reset_stats(cyls, [0, 1], g.nsec if g else 0, planned)
        job = E.WriteJob(self.dev, self._drive(), path, fmt, tracks, self.w_verify.isChecked(),
                         self.w_erase.isChecked(), self.w_retries.value(), self.w_erase_empty.isChecked())
        self.run_job(job, f"Écriture ← {os.path.basename(path)}")

    def start_analyse(self):
        if not self.dev.connected:
            QMessageBox.information(self, APP_NAME, "Connectez d'abord le Greaseweazle.")
            return
        self.nav.setCurrentRow(ANALYSE_ROW)
        self._reset_stats(80, [0, 1], 0, {(0, 0), (1, 1), (40, 0)})
        self.a_table.setRowCount(0)
        self.run_job(E.AnalyseJob(self.dev, self._drive()), "Analyse")

    def _use_analysed(self):
        r = self.a_table.currentRow()
        if r < 0:
            r = 0
        it = self.a_table.item(r, 0)
        if it is None:
            return
        fmt = it.data(Qt.UserRole)
        self.r_pick.select_format(fmt)
        self.nav.setCurrentRow(0)

    def start_calibrate(self):
        try:
            tracks = [tuple(int(x) for x in t.strip().split(".")) for t in self.t_cal_tracks.text().split(",") if t.strip()]
            tracks = [(c, h) for c, h in tracks]
        except ValueError:
            QMessageBox.warning(self, APP_NAME, "Pistes invalides (format : 0.0, 40.1…).")
            return
        if not tracks:
            return
        pr = self.r_pick.preset()
        fmt = pr.fmt if pr and pr.fmt != "ibm.scan" else None
        self.t_cal_chart.clear()
        self._reset_stats(80, [0, 1], F.geometry(fmt).nsec if fmt and F.geometry(fmt) else 0, set(tracks))
        self.map.set_health(True)
        self._health_btn.setChecked(True)
        self.run_job(E.CalibrateJob(self.dev, self._drive(), fmt, tracks), "Calibrage")

    def start_rpm(self):
        self.t_rpm_chart.clear()
        self.run_job(E.RpmJob(self.dev, self._drive(), self.t_rpm_n.value()))

    def start_seek(self):
        self.run_job(E.SeekJob(self.dev, self._drive(), self.t_cyl.value(), self.t_head.currentIndex()))

    def start_clean(self):
        if QMessageBox.question(self, APP_NAME, "Disquette de nettoyage insérée ?") == QMessageBox.Yes:
            self.run_job(E.CleanJob(self.dev, self._drive(), 80, self.t_passes.value()))

    def start_erase(self):
        spec = ["c=0-79:h=0-1", "c=0-79:h=0", "c=0-83:h=0-1"][self.t_erase_heads.currentIndex()]
        if QMessageBox.warning(self, "Effacer la disquette",
                               "Toutes les données de la disquette seront perdues. Continuer ?",
                               QMessageBox.Ok | QMessageBox.Cancel) != QMessageBox.Ok:
            return
        pl, cyls = self._planned(None, None, spec)
        self._reset_stats(cyls, [0, 1], 0, pl)
        self.run_job(E.EraseJob(self.dev, self._drive(), spec), "Effacement")

    def start_fw_update(self):
        if not self.dev.info:
            QMessageBox.information(self, APP_NAME, "Connectez d'abord le Greaseweazle.")
            return
        msg = ("Le firmware le plus récent va être téléchargé depuis GitHub et installé.\n\n"
               "Ne débranchez pas le Greaseweazle pendant l'opération.")
        if self.dev.info.model.startswith("Greaseweazle F1"):
            msg += ("\n\nModèle F1 : il faut d'abord débrancher, poser le cavalier DCLK-GND, "
                    "rebrancher, puis lancer la mise à jour. Retirer le cavalier ensuite.")
        alt = QMessageBox(QMessageBox.Question, "Mise à jour firmware", msg,
                          QMessageBox.Ok | QMessageBox.Cancel, self)
        bfile = alt.addButton("Depuis un fichier .upd…", QMessageBox.ActionRole)
        r = alt.exec()
        file = None
        if alt.clickedButton() == bfile:
            file, _ = QFileDialog.getOpenFileName(self, "Fichier de mise à jour", self._last_dir(),
                                                  "Firmware (*.upd)")
            if not file:
                return
        elif r != QMessageBox.Ok:
            return
        self.run_job(E.FirmwareUpdateJob(self.dev, self.dev.info.port, file))

    def start_convert(self):
        src, dst = self.c_src.text().strip(), self.c_dst.text().strip()
        if not os.path.isfile(src) or not dst:
            QMessageBox.warning(self, APP_NAME, "Choisissez une source et une destination.")
            return
        pr = self.c_pick.preset()
        fmt = pr.fmt if pr else None
        if fmt is None:
            fmt = F.default_format_for(src) or F.default_format_for(dst)
        try:
            planned, cyls = self._planned(fmt, None, "c=0-79:h=0-1")
        except Exception:
            planned, cyls = None, 80
        g = F.geometry(fmt)
        self._reset_stats(cyls, [0, 1], g.nsec if g else 0, planned)
        self.run_job(E.ConvertJob(self.dev, src, dst, fmt), f"Conversion → {os.path.basename(dst)}")

    # ------------------------------------------------------------ Événements tâche
    def _on_track(self, r: E.TrackResult):
        self.track_results[r.cyl, r.head] = r
        self.map.set_result(r)
        rs = list(self.track_results.values())
        tot = sum(x.nsec for x in rs)
        bad = sum(x.nbad for x in rs)
        self.s_tracks.set(str(len(rs)))
        if tot:
            self.s_sect.set(f"{tot - bad}/{tot}", T.STATUS["ok"] if not bad else None)
            self.s_bad.set(str(bad), T.STATUS["bad"] if bad else T.STATUS["ok"])
        rpms = [x.rpm for x in rs if x.rpm]
        if rpms:
            self.s_rpm.set(f"{sum(rpms) / len(rpms):.1f}")
        if self.map.selected is None or self.map.selected == (r.cyl, r.head):
            self._show_track(r.cyl, r.head, select=False)

    def _on_progress(self, i, n):
        self.prog.setRange(0, max(n, 1))
        self.prog.setValue(i)
        el = time.monotonic() - self.job_t0
        rest = el / i * (n - i) if i else 0
        self.s_time.set(f"{el:.0f} s / {rest:.0f} s" if i else f"{el:.0f} s")
        self.prog_lbl.setText(f"{i}/{n}")

    def _on_result(self, d: dict):
        k = d.get("kind")
        if k == "analyse":
            self.a_rpm.set(f"{d['rpm']:.1f}")
            self.a_dens.setText(d["density"])
            self.a_scan.setText("<br>".join(html.escape(s) for s in d["scan"]))
            self.a_table.setRowCount(0)
            for c in d["candidates"][:15]:
                r = self.a_table.rowCount()
                self.a_table.insertRow(r)
                it = QTableWidgetItem(f"{c['platform']} — {c['label']}")
                it.setToolTip(c["fmt"])
                it.setData(Qt.UserRole, c["fmt"])
                pct = 100 * c["ratio"]
                col = T.STATUS["ok"] if pct >= 95 else (T.STATUS["retried"] if pct >= 50 else T.STATUS["bad"])
                it.setForeground(QColor(col))
                self.a_table.setItem(r, 0, it)
                self.a_table.setItem(r, 1, QTableWidgetItem(f"{c['good']}/{c['expected']}"))
            if d["candidates"]:
                self.a_table.selectRow(0)
                best = d["candidates"][0]
                if best["ratio"] >= 0.95:
                    self.r_pick.select_format(best["fmt"])
            self.hist.set_hist(d.get("hist", []), "Flux piste 0.0")
        elif k == "rpm_sample":
            self.t_rpm_chart.add(d["rpm"])
            self.s_rpm.set(f"{d['rpm']:.1f}")
        elif k == "rpm":
            m = d["mean"]
            nominal = 360 if m > 330 else 300
            dev = 100 * (m - nominal) / nominal
            verdict = "conforme" if abs(dev) <= 1.5 else "hors tolérance : réglage ou courroie à vérifier"
            self.t_rpm_lbl.setText(f"Moyenne {m:.2f} tr/min ({dev:+.2f} % vs {nominal}) — {verdict}.")
        elif k == "fluxanalyse":
            self._last_fmt = d.get("fmt")
            if d.get("findings"):
                QTimer.singleShot(0, self.show_report)
        elif k == "inserted":
            if getattr(self, "_batch_wait", False):
                self._batch_go = True
        elif k == "recover":
            self.c_rec_lbl.setText(f"{d['fixed']} secteur(s) récupéré(s), {d['left']} toujours illisible(s).")
        elif k == "calib":
            self.t_cal_chart.add(d["quality"])
            col = TrackMap.health_color(d["quality"]).name()
            self.t_cal_lbl.setText(
                f"Piste {d['cyl']}.{d['head']} — <span style='color:{col}'><b>{d['quality']:.1f} %</b></span> "
                f"(gigue {d['jitter']:.1f} %, cellule {d['peak']:.2f} µs) · secteurs {d['good']}/{d['nsec']} · "
                f"{d['rpm']:.2f} tr/min")
        elif k == "read":
            if getattr(self, "_batch_active", False) and not getattr(self, "_pending", None):
                self._batch_count += 1
                self._batch_next = True
            self._last_image = d["path"] if os.path.dirname(d["path"]) != EM.session_dir() else None
            if d.get("findings") is not None:
                QTimer.singleShot(0, self.show_report)
            if getattr(self, "_pending", None) and self._pending["path"] == d["path"]:
                self._pending["ok"] = True
                if self._pending["purpose"] == "surf":
                    self.log(f"Test de surface : {d['sectors'] - d['bad']}/{d['sectors']} secteurs lisibles"
                             + (f" — pistes en échec : {', '.join(d['bad_tracks'])}" if d["bad_tracks"] else ""),
                             "warn" if d["bad"] else "ok")
                return
            self.settings.setValue("last_read", d["path"])
            if d["bad"]:
                QApplication.beep()
            if getattr(self, "_explore_after_read", False):
                self._explore_after_read = False
                self.explore(d["path"])
        elif k == "write" and d["failed"]:
            QMessageBox.warning(self, APP_NAME, f"{d['failed']} piste(s) n'ont pas pu être vérifiées.\n"
                                "Disquette probablement abîmée.")

    def _on_finished(self):
        self._explore_after_read = False
        if getattr(self, "_batch_next", False):
            self._batch_next = False
            QTimer.singleShot(400, self._batch_continue)
        if getattr(self, "_batch_wait", False):
            self._batch_wait = False
            if getattr(self, "_batch_go", False):
                self._batch_go = False
                QTimer.singleShot(400, self.start_read)
            else:
                self._batch_active = False
                self.log(f"Lot terminé : {getattr(self, '_batch_count', 0)} disquette(s).", "ok")
        if getattr(self, "_pending", None):
            QTimer.singleShot(0, self._after_pending)
        self.map.clear_current()
        if self.prog.maximum() == 0:
            self.prog.setRange(0, 1)
            self.prog.setValue(1)
        self.prog_lbl.setText("Terminé")
        if self.dev.info:
            info = self.dev.info
            self._chip(self.dev.connected, f"{info.model} · fw {info.firmware[0]}.{info.firmware[1]}"
                       if self.dev.connected else None)
            self._fill_device(info if self.dev.connected else None)
        self._update_enabled()

    def _show_track(self, c, h, select=True):
        r = self.track_results.get((c, h))
        if r is None:
            self.det_lbl.setText(f"<b>Cylindre {c} · face {h}</b> — pas encore lue.")
            self.hist.set_hist([])
            return
        col = T.STATUS.get(r.status, T.TEXT)
        parts = [f"<b>Cylindre {c} · face {h}</b> &nbsp; "
                 f"<span style='color:{col}'>● {T.STATUS_LABEL.get(r.status, r.status)}</span>"]
        if r.nsec:
            bad = [str(i) for i, g in enumerate(r.good) if not g]
            parts.append(f"Secteurs {r.nsec - r.nbad}/{r.nsec}" + (f" — illisibles : {', '.join(bad)}" if bad else ""))
        if r.retries:
            parts.append(f"Relectures : {r.retries}")
        if r.rpm:
            parts.append(f"{r.rpm:.2f} tr/min · {r.nflux:,} transitions".replace(",", " "))
        if r.quality:
            qcol = TrackMap.health_color(r.quality).name()
            parts.append(f"Signal : <span style='color:{qcol}'>{r.quality:.1f} % — "
                         f"{A.quality_label(r.quality)}</span> · gigue {r.jitter:.1f} % · "
                         f"cellule {r.peak:.2f} µs · {html.escape(r.encoding or '—')}")
        if r.weak:
            parts.append(f"<span style='color:#a970ff'>Secteurs faibles : {r.weak}</span>")
        if r.summary:
            parts.append(f"<span style='color:{T.MUTED}'>{html.escape(r.summary)}</span>")
        self.det_lbl.setText("<br>".join(parts))
        if r.hist:
            self.hist.set_hist(r.hist, f"Flux piste {c}.{h} — {E.density_guess(r.hist)}")
        secs = r.sectors or [{"r": i, "c": None, "h": None, "size": 0, "id_ok": g, "data_ok": g,
                              "deleted": False} for i, g in enumerate(r.good)]
        self.det_tbl.setRowCount(len(secs))
        ok_c, bad_c = QColor(T.STATUS["ok"]), QColor(T.STATUS["bad"])
        for i, sx in enumerate(secs):
            weak = i in r.weak
            vals = [str(i), (f"{sx['r']:02X}h" if sx.get("c") is not None else str(sx["r"])),
                    "" if sx.get("c") is None else str(sx["c"]), "" if sx.get("h") is None else str(sx["h"]),
                    str(sx["size"]) if sx.get("size") else "",
                    "OK" if sx["id_ok"] else "absent/CRC",
                    ("faible" if weak else "OK" if sx["data_ok"] else "CRC") + (" · supprimé" if sx.get("deleted") else "")]
            for k, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if k >= 5:
                    good = sx["id_ok"] if k == 5 else sx["data_ok"] and not weak
                    it.setForeground(QColor("#a970ff") if weak and k == 6 else ok_c if good else bad_c)
                self.det_tbl.setItem(i, k, it)

    # ---------------------------------------------------------------- Paramètres
    def _restore(self):
        g = self.settings.value("geometry")
        if g:
            self.restoreGeometry(g)
        fmt = self.settings.value("read_fmt") or "ibm.1440"
        if fmt:
            self.r_pick.select_format(fmt)
        drv = self.settings.value("drive")
        if drv:
            i = self.drive_cb.findData(drv)
            if i >= 0:
                self.drive_cb.setCurrentIndex(i)
        self.r_flux.setChecked(self.settings.value("flux_copy", "false") == "true")
        self._read_fmt_changed()
        self._fill_recent()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if os.path.isfile(p):
                self.explore(p)
                break

    def closeEvent(self, e):
        if self.job and self.job.isRunning():
            if QMessageBox.question(self, APP_NAME, "Une opération est en cours. Interrompre et quitter ?") \
                    != QMessageBox.Yes:
                e.ignore()
                return
            self.job.cancel()
            self.job.wait(5000)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("drive", self._drive())
        self.settings.setValue("flux_copy", "true" if self.r_flux.isChecked() else "false")
        self.dev.close()
        super().closeEvent(e)
