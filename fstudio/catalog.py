"""Catalogue de la collection : base SQLite des images lues ou explorées."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QStandardPaths, QThread, Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS images(
  id INTEGER PRIMARY KEY, path TEXT UNIQUE, title TEXT, platform TEXT, fs TEXT, label TEXT,
  fmt TEXT, size INTEGER, md5 TEXT, sha1 TEXT, added REAL, mtime REAL, bad INTEGER,
  nfiles INTEGER, notes TEXT DEFAULT '', flux TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS files(
  image_id INTEGER, path TEXT, size INTEGER, md5 TEXT, deleted INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS files_img ON files(image_id);
CREATE INDEX IF NOT EXISTS files_md5 ON files(md5);
CREATE INDEX IF NOT EXISTS images_md5 ON images(md5);
"""
IMAGE_EXT = {".img", ".ima", ".st", ".msa", ".adf", ".d64", ".d71", ".d81", ".fd", ".dsk", ".edsk", ".hfe",
             ".scp", ".imd", ".td0", ".dmk", ".do", ".po", ".2mg", ".vfd", ".flp", ".raw", ".ipf", ".dim"}
PLATFORM_LABEL = {"pc": "PC", "atarist": "Atari ST", "amiga": "Amiga", "c64": "Commodore", "cpc": "Amstrad CPC",
                  "thomson": "Thomson", "msx": "MSX", "akai": "Akai", "apple2": "Apple II", "": "?"}


def db_path() -> str:
    d = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation) or os.path.expanduser("~/.floppystudio")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "catalogue.sqlite")


class Catalog:
    def __init__(self, path: Optional[str] = None):
        self.path = path or db_path()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()
        self.lock = threading.RLock()

    # ------------------------------------------------------------ Ajout
    def add_image(self, path: str, title: Optional[str] = None, flux: str = "", fmt: Optional[str] = None,
                  force: bool = False) -> Optional[int]:
        with self.lock:
            return self._add_image(path, title, flux, fmt, force)

    def _add_image(self, path, title, flux, fmt, force) -> Optional[int]:
        from .fs import open_image
        path = os.path.abspath(path)
        st = os.stat(path)
        row = self.db.execute("SELECT id, mtime FROM images WHERE path=?", (path,)).fetchone()
        if row and not force and abs((row[1] or 0) - st.st_mtime) < 1:
            if flux:
                self.db.execute("UPDATE images SET flux=? WHERE id=?", (flux, row[0]))
                self.db.commit()
            return row[0]
        with open(path, "rb") as f:
            data = f.read()
        md5, sha1 = hashlib.md5(data).hexdigest(), hashlib.sha1(data).hexdigest()
        platform = fsname = label = ""
        bad = 0
        files: List[Tuple[str, int, str, int]] = []
        try:
            disk, vols = open_image(path, fmt)
            bad = disk.bad_sectors()
            fmt = fmt or disk.fmt
            for fs in vols[:2]:
                platform = platform or fs.platform
                fsname = fsname or fs.name
                label = label or fs.label
                prefix = (fs.volume_name + "/") if len(vols) > 1 else ""
                for e in fs.root.walk():
                    if e.is_dir:
                        continue
                    try:
                        h = hashlib.md5(fs.read(e)).hexdigest()
                    except Exception:
                        h = ""
                    files.append((prefix + e.path, e.size, h, 0))
                try:
                    for e in fs.deleted():
                        files.append((prefix + "[supprimé] " + e.name, e.size, "", 1))
                except Exception:
                    pass
        except Exception:
            pass
        if not title:
            title = (row and self.db.execute("SELECT title FROM images WHERE id=?", (row[0],)).fetchone()[0]) \
                or os.path.splitext(os.path.basename(path))[0]
        if row:
            iid = row[0]
            self.db.execute("UPDATE images SET title=?, platform=?, fs=?, label=?, fmt=?, size=?, md5=?, sha1=?, "
                            "mtime=?, bad=?, nfiles=?, flux=COALESCE(NULLIF(?, ''), flux) WHERE id=?",
                            (title, platform, fsname, label, fmt or "", len(data), md5, sha1, st.st_mtime, bad,
                             len(files), flux, iid))
            self.db.execute("DELETE FROM files WHERE image_id=?", (iid,))
        else:
            cur = self.db.execute("INSERT INTO images(path,title,platform,fs,label,fmt,size,md5,sha1,added,mtime,"
                                  "bad,nfiles,flux) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (path, title, platform, fsname, label, fmt or "", len(data), md5, sha1,
                                   time.time(), st.st_mtime, bad, len(files), flux))
            iid = cur.lastrowid
        self.db.executemany("INSERT INTO files(image_id,path,size,md5,deleted) VALUES(?,?,?,?,?)",
                            [(iid,) + f for f in files])
        self.db.commit()
        return iid

    # ------------------------------------------------------------ Consultation
    def images(self, text: str = "", platform: str = "") -> List[Dict]:
        q = "SELECT * FROM images"
        args, cond = [], []
        if text:
            like = f"%{text}%"
            cond.append("(title LIKE ? OR path LIKE ? OR label LIKE ? OR notes LIKE ? OR fs LIKE ? OR "
                        "id IN (SELECT image_id FROM files WHERE path LIKE ?))")
            args += [like] * 6
        if platform:
            cond.append("platform=?")
            args.append(platform)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY title COLLATE NOCASE"
        cur = self.db.execute(q, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def file_hits(self, text: str, limit: int = 500) -> List[Tuple]:
        if not text:
            return []
        return self.db.execute(
            "SELECT i.id, i.title, i.path, f.path, f.size, f.deleted FROM files f JOIN images i ON i.id=f.image_id "
            "WHERE f.path LIKE ? ORDER BY i.title, f.path LIMIT ?", (f"%{text}%", limit)).fetchall()

    def files_of(self, iid: int) -> List[Tuple]:
        return self.db.execute("SELECT path, size, md5, deleted FROM files WHERE image_id=? ORDER BY path",
                               (iid,)).fetchall()

    def duplicates(self) -> Tuple[List[List[Dict]], List[Tuple]]:
        """(groupes d'images identiques, fichiers présents sur plusieurs images)."""
        groups = []
        for (md5,) in self.db.execute("SELECT md5 FROM images GROUP BY md5 HAVING COUNT(*)>1").fetchall():
            cur = self.db.execute("SELECT id, title, path FROM images WHERE md5=?", (md5,))
            groups.append([{"id": a, "title": b, "path": c} for a, b, c in cur.fetchall()])
        files = self.db.execute(
            "SELECT f.md5, MIN(f.path), f.size, COUNT(DISTINCT f.image_id), GROUP_CONCAT(DISTINCT i.title) "
            "FROM files f JOIN images i ON i.id=f.image_id WHERE f.md5<>'' AND f.size>0 AND f.deleted=0 "
            "GROUP BY f.md5 HAVING COUNT(DISTINCT f.image_id)>1 ORDER BY f.size DESC LIMIT 1000").fetchall()
        return groups, files

    def update(self, iid: int, **kw):
        for k, v in kw.items():
            if k in ("title", "notes", "flux"):
                self.db.execute(f"UPDATE images SET {k}=? WHERE id=?", (v, iid))
        self.db.commit()

    def remove(self, iid: int):
        self.db.execute("DELETE FROM files WHERE image_id=?", (iid,))
        self.db.execute("DELETE FROM images WHERE id=?", (iid,))
        self.db.commit()

    def purge_missing(self) -> int:
        n = 0
        for iid, p in self.db.execute("SELECT id, path FROM images").fetchall():
            if not os.path.isfile(p):
                self.remove(iid)
                n += 1
        return n

    def stats(self) -> Dict[str, int]:
        a = self.db.execute("SELECT COUNT(*), COALESCE(SUM(size),0), COALESCE(SUM(nfiles),0) FROM images").fetchone()
        return {"images": a[0], "size": a[1], "files": a[2]}

    def platforms(self) -> List[str]:
        return [r[0] for r in self.db.execute("SELECT DISTINCT platform FROM images ORDER BY platform")]

    def export_csv(self, path: str):
        import csv
        rows = self.images()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(["Titre", "Plateforme", "Système", "Étiquette", "Fichiers", "Taille", "Illisibles",
                        "MD5", "SHA-1", "Chemin", "Flux", "Notes"])
            for r in rows:
                w.writerow([r["title"], PLATFORM_LABEL.get(r["platform"], r["platform"]), r["fs"], r["label"],
                            r["nfiles"], r["size"], r["bad"], r["md5"], r["sha1"], r["path"], r["flux"], r["notes"]])


class ScanJob(QThread):
    """Ajoute des images (fichiers ou dossiers) au catalogue en tâche de fond."""
    progress = Signal(int, int, str)
    done = Signal(int)

    def __init__(self, cat: Catalog, paths: List[str], extra: Optional[dict] = None):
        super().__init__()
        self.cat, self.paths, self.extra = cat, paths, extra or {}
        self.cancel = False

    def run(self):
        todo = []
        for p in self.paths:
            if os.path.isdir(p):
                for root, _, names in os.walk(p):
                    todo += [os.path.join(root, n) for n in names if os.path.splitext(n)[1].lower() in IMAGE_EXT]
            elif os.path.isfile(p):
                todo.append(p)
        n = 0
        for i, p in enumerate(todo):
            if self.cancel:
                break
            self.progress.emit(i, len(todo), os.path.basename(p))
            try:
                if self.cat.add_image(p, **self.extra.get(p, {})) is not None:
                    n += 1
            except Exception:
                pass
        self.done.emit(n)
