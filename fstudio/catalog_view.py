"""Vue « Catalogue » : la collection d'images avec recherche, doublons et notes."""
from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from . import archive as AR
from . import theme as T
from .catalog import PLATFORM_LABEL, Catalog, ScanJob
from .fs import human
from .widgets import FlowBar

COLS = ["Titre", "Plateforme", "Système", "Fichiers", "Taille", "Illisibles", "Ajouté", "Notes", "Chemin",
        "Identification (DAT)"]


class CatalogView(QWidget):
    explore_request = Signal(str, str)      # image, fichier à sélectionner
    log = Signal(str, str)

    def __init__(self, cat: Catalog):
        super().__init__()
        self.cat = cat
        self.job: Optional[ScanJob] = None
        self.rows = []
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 14, 14, 10)
        v.setSpacing(10)

        head = QFrame()
        head.setObjectName("card")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 10, 14, 10)
        col = QVBoxLayout()
        t = QLabel("Catalogue de la collection")
        t.setObjectName("h2")
        self.sub = QLabel("")
        self.sub.setObjectName("muted")
        col.addWidget(t)
        col.addWidget(self.sub)
        hl.addLayout(col, 1)
        self.prog = QProgressBar()
        self.prog.setFixedWidth(220)
        self.prog.setTextVisible(True)
        self.prog.hide()
        hl.addWidget(self.prog)
        v.addWidget(head)

        bar = FlowBar(6, 6)
        self.q = QLineEdit()
        self.q.setMinimumWidth(260)
        self.q.setPlaceholderText("Rechercher un titre, une étiquette, une note ou un nom de fichier…")
        self.q.textChanged.connect(lambda _: self._timer.start(250))
        self.plat = QComboBox()
        self.plat.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.q)
        bar.addWidget(self.plat)
        for txt, slot, tip in (("📂  Ouvrir", self.open_selected, "Ouvrir l'image dans l'explorateur"),
                               ("🗂  Doublons", self.show_duplicates, "Images identiques et fichiers en double"),
                               ("🏷  Bases DAT…", self.show_dats,
                                "Identifier les images avec les bases TOSEC, No-Intro… (fichiers DAT)"),
                               ("🗑  Retirer", self.remove_selected, "Retirer du catalogue (le fichier est conservé)"),
                               ("⤓  CSV…", self.export_csv, "Exporter le catalogue en CSV")):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
        v.addWidget(bar)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.refresh)

        split = QSplitter(Qt.Vertical)
        split.setHandleWidth(8)
        self.t = QTableWidget(0, len(COLS))
        self.t.setHorizontalHeaderLabels(COLS)
        self.t.verticalHeader().hide()
        self.t.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.t.setSortingEnabled(True)
        self.t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.t.horizontalHeader().moveSection(9, 1)
        self.t.itemChanged.connect(self._edited)
        self.t.itemSelectionChanged.connect(self._show_files)
        self.t.cellDoubleClicked.connect(lambda r, c: self.open_selected() if c not in (0, 7) else None)
        split.addWidget(self.t)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.files = QTableWidget(0, 3)
        self.files.setHorizontalHeaderLabels(["Fichier", "Taille", "MD5"])
        self.files.verticalHeader().hide()
        self.files.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.files.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.files.cellDoubleClicked.connect(self._open_file_row)
        self.hits = QTableWidget(0, 3)
        self.hits.setHorizontalHeaderLabels(["Image", "Fichier", "Taille"])
        self.hits.verticalHeader().hide()
        self.hits.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hits.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.hits.cellDoubleClicked.connect(self._open_hit)
        self.tabs.addTab(self.files, "Contenu de l'image")
        self.tabs.addTab(self.hits, "Fichiers trouvés")
        split.addWidget(self.tabs)
        split.setSizes([480, 260])
        v.addWidget(split, 1)
        self._fill_platforms()
        self.refresh()

    # ---------------------------------------------------------------- Données
    def _fill_platforms(self):
        cur = self.plat.currentData()
        self.plat.blockSignals(True)
        self.plat.clear()
        self.plat.addItem("Toutes plateformes", "")
        for p in self.cat.platforms():
            self.plat.addItem(PLATFORM_LABEL.get(p, p or "?"), p)
        i = self.plat.findData(cur)
        self.plat.setCurrentIndex(max(i, 0))
        self.plat.blockSignals(False)

    def refresh(self):
        text = self.q.text().strip()
        self.rows = self.cat.images(text, self.plat.currentData() or "")
        self.t.blockSignals(True)
        self.t.setSortingEnabled(False)
        self.t.setRowCount(len(self.rows))
        import time as _t
        for i, r in enumerate(self.rows):
            vals = [r["title"], PLATFORM_LABEL.get(r["platform"], r["platform"] or "?"), r["fs"] or "—",
                    r["nfiles"], human(r["size"] or 0), r["bad"] or 0,
                    _t.strftime("%d/%m/%Y", _t.localtime(r["added"] or 0)), r["notes"] or "", r["path"],
                    (r.get("ident") or "").split("\t")[0]]
            for c, val in enumerate(vals):
                it = QTableWidgetItem()
                if c in (3, 5):
                    it.setData(Qt.DisplayRole, int(val))
                else:
                    it.setText(str(val))
                it.setData(Qt.UserRole, r["id"])
                if c not in (0, 7):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c == 5 and val:
                    it.setForeground(QColor(T.STATUS["bad"]))
                if c == 9 and r.get("ident"):
                    it.setForeground(QColor(T.STATUS["ok"]))
                    it.setToolTip("Base : " + r["ident"].split("\t")[-1])
                if not os.path.isfile(AR.split(r["path"])[0]):
                    it.setForeground(QColor(T.MUTED))
                    it.setToolTip("Fichier introuvable")
                self.t.setItem(i, c, it)
        self.t.setSortingEnabled(True)
        self.t.blockSignals(False)
        self.t.resizeColumnsToContents()
        self.t.setColumnWidth(8, min(self.t.columnWidth(8), 220))
        self.t.setColumnWidth(7, max(self.t.columnWidth(7), 120))
        self.t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.t.horizontalHeader().setSectionResizeMode(7, QHeaderView.Interactive)
        st = self.cat.stats()
        self.sub.setText(f"{st['images']} image(s) · {st['files']} fichier(s) · {human(st['size'])}"
                         + (f" — {len(self.rows)} résultat(s)" if text or self.plat.currentData() else ""))
        hits = self.cat.file_hits(text) if len(text) >= 2 else []
        self.hits.setRowCount(len(hits))
        for i, (iid, title, path, fpath, size, dele) in enumerate(hits):
            for c, val in enumerate((title, fpath, human(size or 0))):
                it = QTableWidgetItem(str(val))
                it.setData(Qt.UserRole, (path, fpath))
                if dele:
                    it.setForeground(QColor(T.MUTED))
                self.hits.setItem(i, c, it)
        self.tabs.setTabText(1, f"Fichiers trouvés ({len(hits)})")
        if hits and not self.t.selectedItems():
            self.tabs.setCurrentIndex(1)

    def show_dats(self):
        dlg = QDialog(self)
        dlg.setWindowTitle("Bases d'identification (DAT)")
        dlg.resize(620, 420)
        lay = QVBoxLayout(dlg)
        lay.addWidget(QLabel("Les fichiers <b>DAT</b> (TOSEC, No-Intro, Redump… au format Logiqx XML ou ClrMamePro) "
                             "listent les empreintes des images connues. Une fois importés, les images du "
                             "catalogue et les disquettes lues sont reconnues automatiquement.<br>"
                             "<span style='color:%s'>Téléchargement : tosecdev.org (packs .zip acceptés tels "
                             "quels).</span>" % T.MUTED))
        lay.itemAt(0).widget().setWordWrap(True)
        tab = QTableWidget(0, 2)
        tab.setHorizontalHeaderLabels(["Base", "Entrées"])
        tab.verticalHeader().hide()
        tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tab.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(tab, 1)
        info = QLabel("")
        info.setObjectName("muted")
        lay.addWidget(info)

        def fill():
            src = self.cat.dat_sources()
            tab.setRowCount(len(src))
            for i, (n, c) in enumerate(src):
                tab.setItem(i, 0, QTableWidgetItem(n))
                it = QTableWidgetItem()
                it.setData(Qt.DisplayRole, c)
                tab.setItem(i, 1, it)
            ident = sum(1 for r in self.cat.images() if r["ident"])
            info.setText(f"{len(src)} base(s), {sum(c for _, c in src)} entrée(s) — "
                         f"{ident} image(s) du catalogue identifiée(s).")

        def imp():
            ps, _ = QFileDialog.getOpenFileNames(dlg, "Importer des fichiers DAT", os.path.expanduser("~"),
                                                 "Fichiers DAT (*.dat *.xml *.zip);;Tous les fichiers (*)")
            if not ps:
                return
            from PySide6.QtWidgets import QApplication
            QApplication.setOverrideCursor(Qt.WaitCursor)
            tot, errs = 0, []
            try:
                for p in ps:
                    try:
                        n, _src = self.cat.import_dat(p)
                        tot += n
                    except Exception as ex:
                        errs.append(f"{os.path.basename(p)} : {ex}")
            finally:
                QApplication.restoreOverrideCursor()
            self.log.emit(f"Bases DAT : {tot} entrée(s) importée(s).", "ok")
            if errs:
                QMessageBox.warning(dlg, "Import DAT", "\n".join(errs[:10]))
            fill()
            self.refresh()

        def names():
            n = self.cat.apply_dat_names()
            self.log.emit(f"{n} titre(s) renommé(s) d'après les bases DAT.", "ok")
            self.refresh()
            fill()

        def clear():
            if QMessageBox.question(dlg, "Bases DAT", "Effacer toutes les bases importées ?") == QMessageBox.Yes:
                self.cat.clear_dats()
                fill()
                self.refresh()

        row = QHBoxLayout()
        for txt, fn in (("⤒  Importer…", imp), ("🏷  Nommer les images identifiées", names),
                        ("🗑  Tout effacer", clear)):
            b = QPushButton(txt)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        close = QPushButton("Fermer")
        close.clicked.connect(dlg.accept)
        row.addWidget(close)
        lay.addLayout(row)
        fill()
        dlg.exec()

    def _selected_ids(self):
        return sorted({it.data(Qt.UserRole) for it in self.t.selectedItems()})

    def _row_of(self, iid):
        return next((r for r in self.rows if r["id"] == iid), None)

    def _show_files(self):
        ids = self._selected_ids()
        if not ids:
            return
        files = self.cat.files_of(ids[0])
        self.files.setRowCount(len(files))
        for i, (p, size, md5, dele) in enumerate(files):
            for c, val in enumerate((p, human(size or 0), md5)):
                it = QTableWidgetItem(val)
                it.setData(Qt.UserRole, p)
                if dele:
                    it.setForeground(QColor(T.MUTED))
                self.files.setItem(i, c, it)
        self.files.resizeColumnToContents(1)
        r = self._row_of(ids[0])
        self.tabs.setTabText(0, f"Contenu — {r['title']}" if r else "Contenu de l'image")
        self.tabs.setCurrentIndex(0)

    def _edited(self, it: QTableWidgetItem):
        iid = it.data(Qt.UserRole)
        if it.column() == 0:
            self.cat.update(iid, title=it.text())
        elif it.column() == 7:
            self.cat.update(iid, notes=it.text())

    # ---------------------------------------------------------------- Actions
    def open_selected(self):
        ids = self._selected_ids()
        r = self._row_of(ids[0]) if ids else None
        if r:
            self.explore_request.emit(r["path"], "")

    def _open_file_row(self, row, _c):
        ids = self._selected_ids()
        r = self._row_of(ids[0]) if ids else None
        if r:
            self.explore_request.emit(r["path"], self.files.item(row, 0).data(Qt.UserRole))

    def _open_hit(self, row, _c):
        path, fpath = self.hits.item(row, 0).data(Qt.UserRole)
        self.explore_request.emit(path, fpath)

    def remove_selected(self):
        ids = self._selected_ids()
        if ids and QMessageBox.question(self, "Catalogue", f"Retirer {len(ids)} image(s) du catalogue ?\n"
                                        "(les fichiers ne sont pas supprimés)") == QMessageBox.Yes:
            for i in ids:
                self.cat.remove(i)
            self._fill_platforms()
            self.refresh()

    def export_csv(self):
        p, _ = QFileDialog.getSaveFileName(self, "Exporter le catalogue", os.path.expanduser("~/catalogue.csv"),
                                           "CSV (*.csv)")
        if p:
            self.cat.export_csv(p)
            self.log.emit(f"Catalogue exporté : {p}", "ok")

    def show_duplicates(self):
        groups, files = self.cat.duplicates()
        dlg = QDialog(self)
        dlg.setWindowTitle("Doublons")
        dlg.resize(820, 520)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(f"<b>Images identiques : {len(groups)} groupe(s)</b>"))
        t1 = QTableWidget(sum(len(g) for g in groups), 2)
        t1.setHorizontalHeaderLabels(["Groupe / titre", "Chemin"])
        t1.verticalHeader().hide()
        t1.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t1.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        r = 0
        for k, g in enumerate(groups):
            for x in g:
                t1.setItem(r, 0, QTableWidgetItem(f"#{k + 1}  {x['title']}"))
                t1.setItem(r, 1, QTableWidgetItem(x["path"]))
                r += 1
        v.addWidget(t1, 1)
        v.addWidget(QLabel(f"<b>Fichiers présents sur plusieurs images : {len(files)}</b>"))
        t2 = QTableWidget(len(files), 4)
        t2.setHorizontalHeaderLabels(["Fichier", "Taille", "Images", "Titres"])
        t2.verticalHeader().hide()
        t2.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t2.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        for i, (_, p, size, n, titles) in enumerate(files):
            for c, val in enumerate((p, human(size or 0), str(n), titles)):
                t2.setItem(i, c, QTableWidgetItem(val))
        v.addWidget(t2, 1)
        b = QPushButton("Fermer")
        b.clicked.connect(dlg.accept)
        v.addWidget(b, 0, Qt.AlignRight)
        dlg.exec()

    def add_paths(self, paths, extra=None, quiet=False):
        if self.job and self.job.isRunning():
            if quiet:
                QTimer.singleShot(2000, lambda: self.add_paths(paths, extra, quiet))
            return
        self.job = ScanJob(self.cat, list(paths), extra)
        self.job.progress.connect(self._on_prog)
        self.job.done.connect(lambda n: self._on_done(n, quiet))
        if not quiet:
            self.prog.show()
        self.job.start()

    def _on_prog(self, i, n, name):
        self.prog.setRange(0, max(n, 1))
        self.prog.setValue(i)
        self.prog.setFormat(f"{i}/{n} {name[:24]}")

    def _on_done(self, n, quiet):
        self.prog.hide()
        if not quiet:
            self.log.emit(f"Catalogue : {n} image(s) ajoutée(s) ou mise(s) à jour", "ok")
        self._fill_platforms()
        self.refresh()

    def purge(self):
        n = self.cat.purge_missing()
        self.log.emit(f"Catalogue : {n} image(s) introuvable(s) retirée(s)", "info")
        self._fill_platforms()
        self.refresh()
