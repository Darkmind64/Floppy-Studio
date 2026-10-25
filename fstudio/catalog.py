"""Catalogue de la collection : base SQLite des images lues ou explorées."""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
import zlib
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QStandardPaths, QThread, Signal

from . import archive as AR

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
CREATE TABLE IF NOT EXISTS dat(md5 TEXT, sha1 TEXT, crc TEXT, size INTEGER, game TEXT, rom TEXT, source TEXT);
CREATE INDEX IF NOT EXISTS dat_md5 ON dat(md5);
CREATE INDEX IF NOT EXISTS dat_sha1 ON dat(sha1);
CREATE INDEX IF NOT EXISTS dat_crc ON dat(crc, size);
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
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(images)")}
        if "crc" not in cols:
            self.db.execute("ALTER TABLE images ADD COLUMN crc TEXT DEFAULT ''")
        self.db.commit()
        self.lock = threading.RLock()

    # ------------------------------------------------------------ Ajout
    def add_image(self, path: str, title: Optional[str] = None, flux: str = "", fmt: Optional[str] = None,
                  force: bool = False) -> Optional[int]:
        with self.lock:
            return self._add_image(path, title, flux, fmt, force)

    def _add_image(self, path, title, flux, fmt, force) -> Optional[int]:
        from .fs import open_image
        a, m = AR.split(path)
        path = os.path.abspath(a) + (AR.SEP + m if m else "")
        real = AR.extract(path)
        st = os.stat(AR.split(path)[0])
        row = self.db.execute("SELECT id, mtime FROM images WHERE path=?", (path,)).fetchone()
        if row and not force and abs((row[1] or 0) - st.st_mtime) < 1:
            if flux:
                self.db.execute("UPDATE images SET flux=? WHERE id=?", (flux, row[0]))
                self.db.commit()
            return row[0]
        with open(real, "rb") as f:
            data = f.read()
        md5, sha1 = hashlib.md5(data).hexdigest(), hashlib.sha1(data).hexdigest()
        crc = "%08x" % (zlib.crc32(data) & 0xFFFFFFFF)
        platform = fsname = label = ""
        bad = 0
        files: List[Tuple[str, int, str, int]] = []
        try:
            disk, vols = open_image(real, fmt)
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
                or os.path.splitext(os.path.basename(m or path))[0]
        if row:
            iid = row[0]
            self.db.execute("UPDATE images SET title=?, platform=?, fs=?, label=?, fmt=?, size=?, md5=?, sha1=?, "
                            "mtime=?, bad=?, nfiles=?, flux=COALESCE(NULLIF(?, ''), flux), crc=? WHERE id=?",
                            (title, platform, fsname, label, fmt or "", len(data), md5, sha1, st.st_mtime, bad,
                             len(files), flux, crc, iid))
            self.db.execute("DELETE FROM files WHERE image_id=?", (iid,))
        else:
            cur = self.db.execute("INSERT INTO images(path,title,platform,fs,label,fmt,size,md5,sha1,added,mtime,"
                                  "bad,nfiles,flux,crc) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                  (path, title, platform, fsname, label, fmt or "", len(data), md5, sha1,
                                   time.time(), st.st_mtime, bad, len(files), flux, crc))
            iid = cur.lastrowid
        self.db.executemany("INSERT INTO files(image_id,path,size,md5,deleted) VALUES(?,?,?,?,?)",
                            [(iid,) + f for f in files])
        self.db.commit()
        return iid

    # ------------------------------------------------------------ Consultation
    def images(self, text: str = "", platform: str = "") -> List[Dict]:
        q = ("SELECT images.*, COALESCE("
             "(SELECT game || '\t' || source FROM dat WHERE dat.md5 = images.md5 LIMIT 1),"
             "(SELECT game || '\t' || source FROM dat WHERE dat.sha1 = images.sha1 LIMIT 1),"
             "(SELECT game || '\t' || source FROM dat WHERE dat.crc = images.crc AND dat.size = images.size "
             "LIMIT 1), '') AS ident FROM images")
        args, cond = [], []
        if text:
            like = f"%{text}%"
            cond.append("(title LIKE ? OR path LIKE ? OR label LIKE ? OR notes LIKE ? OR fs LIKE ? OR "
                        "id IN (SELECT image_id FROM files WHERE path LIKE ?) OR "
                        "md5 IN (SELECT md5 FROM dat WHERE game LIKE ?) OR sha1 IN (SELECT sha1 FROM dat WHERE game LIKE ?))")
            args += [like] * 8
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

    # ------------------------------------------------------------ Bases DAT (TOSEC, No-Intro…)
    def identify(self, md5: str = "", sha1: str = "", crc: str = "", size: int = 0) -> List[Tuple[str, str, str]]:
        """[(jeu, fichier rom, base)] correspondant à une empreinte."""
        with self.lock:
            return self.db.execute(
                "SELECT DISTINCT game, rom, source FROM dat WHERE (md5<>'' AND md5=?) OR (sha1<>'' AND sha1=?) "
                "OR (crc<>'' AND crc=? AND size=?) LIMIT 20", (md5.lower(), sha1.lower(), crc.lower(), size)).fetchall()

    def identify_file(self, path: str) -> List[Tuple[str, str, str]]:
        with open(AR.extract(path), "rb") as f:
            data = f.read()
        return self.identify(hashlib.md5(data).hexdigest(), hashlib.sha1(data).hexdigest(),
                             "%08x" % (zlib.crc32(data) & 0xFFFFFFFF), len(data))

    def import_dat(self, path: str) -> Tuple[int, List[str]]:
        """Importe un fichier DAT (XML Logiqx ou ClrMamePro), ou une archive .zip de DAT."""
        blobs = []
        if path.lower().endswith(".zip"):
            import zipfile
            with zipfile.ZipFile(path) as z:
                for i in z.infolist():
                    if i.filename.lower().endswith((".dat", ".xml")):
                        blobs.append((os.path.basename(i.filename), z.read(i)))
        else:
            with open(path, "rb") as f:
                blobs.append((os.path.basename(path), f.read()))
        n, sources = 0, []
        with self.lock:
            for name, raw in blobs:
                src, rows = parse_dat(raw, os.path.splitext(name)[0])
                if not rows:
                    continue
                self.db.execute("DELETE FROM dat WHERE source=?", (src,))
                self.db.executemany("INSERT INTO dat(md5,sha1,crc,size,game,rom,source) VALUES(?,?,?,?,?,?,?)",
                                    [r + (src,) for r in rows])
                n += len(rows)
                sources.append(src)
            self._backfill_crc()
            self.db.commit()
        return n, sources

    def _backfill_crc(self):
        for iid, p in self.db.execute("SELECT id, path FROM images WHERE crc IS NULL OR crc=''").fetchall():
            try:
                with open(AR.extract(p), "rb") as f:
                    c = "%08x" % (zlib.crc32(f.read()) & 0xFFFFFFFF)
                self.db.execute("UPDATE images SET crc=? WHERE id=?", (c, iid))
            except Exception:
                pass

    def dat_sources(self) -> List[Tuple[str, int]]:
        return self.db.execute("SELECT source, COUNT(*) FROM dat GROUP BY source ORDER BY source").fetchall()

    def clear_dats(self):
        with self.lock:
            self.db.execute("DELETE FROM dat")
            self.db.commit()

    def apply_dat_names(self) -> int:
        """Remplace les titres par défaut (nom du fichier) par le nom identifié."""
        n = 0
        for r in self.images():
            if not r["ident"]:
                continue
            a, m = AR.split(r["path"])
            default = os.path.splitext(os.path.basename(m or a))[0]
            game = r["ident"].split("\t")[0]
            if r["title"] == default and game != r["title"]:
                self.update(r["id"], title=game)
                n += 1
        return n

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
            if not AR.exists(p):
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
                        "MD5", "SHA-1", "Chemin", "Flux", "Notes", "Identification", "Base DAT"])
            for r in rows:
                w.writerow([r["title"], PLATFORM_LABEL.get(r["platform"], r["platform"]), r["fs"], r["label"],
                            r["nfiles"], r["size"], r["bad"], r["md5"], r["sha1"], r["path"], r["flux"], r["notes"]]
                           + ((r.get("ident") or "").split("\t") + ["", ""])[:2])


def parse_dat(raw: bytes, default_name: str) -> Tuple[str, List[Tuple]]:
    """(nom de la base, [(md5, sha1, crc, taille, jeu, rom)])."""
    rows: List[Tuple] = []
    name = default_name
    head = raw[:4096].lstrip()
    if head.startswith(b"<") or b"<datafile" in head:
        import xml.etree.ElementTree as ET
        import io
        game = ""
        for ev, el in ET.iterparse(io.BytesIO(raw), events=("start", "end")):
            tag = el.tag.rsplit("}", 1)[-1]
            if ev == "start" and tag in ("game", "machine", "software"):
                game = el.get("name", "")
            elif ev == "end" and tag == "name" and el.text and not game and name == default_name:
                name = el.text.strip()
            elif ev == "end" and tag == "rom":
                try:
                    size = int(el.get("size", "0") or 0)
                except ValueError:
                    size = 0
                rows.append(((el.get("md5") or "").lower(), (el.get("sha1") or "").lower(),
                             (el.get("crc") or "").lower().zfill(8) if el.get("crc") else "", size, game,
                             el.get("name", "")))
            elif ev == "end" and tag in ("game", "machine", "software"):
                el.clear()
    else:
        import re
        toks = re.findall(r'"[^"]*"|\(|\)|[^\s()"]+', raw.decode("utf-8", "replace"))

        def block(k):
            """Lit un bloc « ( clé valeur … ) » à partir de toks[k] == '(' → (dict, liste de sous-blocs, k)."""
            d, subs, k = {}, [], k + 1
            while k < len(toks) and toks[k] != ")":
                key = toks[k]
                if k + 1 < len(toks) and toks[k + 1] == "(":
                    sub, _s, k = block(k + 1)
                    subs.append((key, sub))
                else:
                    d.setdefault(key, toks[k + 1].strip('"') if k + 1 < len(toks) else "")
                    k += 2
                    continue
                k += 1
            return d, subs, k

        k = 0
        while k < len(toks):
            if k + 1 < len(toks) and toks[k + 1] == "(":
                kind = toks[k]
                d, subs, k = block(k + 1)
                if kind == "clrmamepro" and d.get("name"):
                    name = d["name"]
                elif kind in ("game", "machine", "resource"):
                    for sk, r in subs:
                        if sk != "rom":
                            continue
                        try:
                            size = int(r.get("size", "0") or 0)
                        except ValueError:
                            size = 0
                        rows.append((r.get("md5", "").lower(), r.get("sha1", "").lower(),
                                     r.get("crc", "").lower(), size, d.get("name", ""), r.get("name", "")))
            k += 1
    return name, rows


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
                    for n in names:
                        q = os.path.join(root, n)
                        if os.path.splitext(n)[1].lower() in IMAGE_EXT:
                            todo.append(q)
                        elif AR.is_archive(q):
                            todo += [q + AR.SEP + x for x in AR.images_in(q)]
            elif AR.is_archive(p):
                todo += [p + AR.SEP + x for x in AR.images_in(p)]
            elif os.path.isfile(p) or AR.is_virtual(p):
                todo.append(p)
        n = 0
        for i, p in enumerate(todo):
            if self.cancel:
                break
            self.progress.emit(i, len(todo), AR.display(p))
            try:
                if self.cat.add_image(p, **self.extra.get(p, {})) is not None:
                    n += 1
            except Exception:
                pass
        self.done.emit(n)
