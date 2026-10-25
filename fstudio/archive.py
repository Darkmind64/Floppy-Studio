"""Images disquette contenues dans des archives .zip (chemins virtuels « archive.zip::membre »)."""
from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from typing import List, Optional, Tuple

SEP = "::"
ARCHIVE_EXT = {".zip"}
IMAGE_EXT = {".img", ".ima", ".st", ".msa", ".adf", ".d64", ".d71", ".d81", ".fd", ".dsk", ".edsk", ".hfe",
             ".scp", ".imd", ".td0", ".dmk", ".do", ".po", ".2mg", ".vfd", ".flp", ".raw", ".ipf", ".dim",
             ".sap", ".hdm", ".ssd", ".dsd", ".adm", ".adl", ".ads", ".d88", ".86f", ".img"}


def is_archive(path: str) -> bool:
    return os.path.splitext(split(path)[0])[1].lower() in ARCHIVE_EXT and SEP not in path


def split(path: str) -> Tuple[str, Optional[str]]:
    """'a.zip::x/y.adf' → ('a.zip', 'x/y.adf') ; chemin ordinaire → (chemin, None)."""
    if SEP in path:
        a, m = path.split(SEP, 1)
        if os.path.splitext(a)[1].lower() in ARCHIVE_EXT:
            return a, m
    return path, None


def is_virtual(path: str) -> bool:
    return split(path)[1] is not None


def exists(path: str) -> bool:
    a, m = split(path)
    if m is None:
        return os.path.isfile(path)
    try:
        with zipfile.ZipFile(a) as z:
            return m in z.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def images_in(archive: str) -> List[str]:
    """Membres de l'archive qui ressemblent à des images disquette (zip imbriqués exclus)."""
    try:
        with zipfile.ZipFile(archive) as z:
            return [i.filename for i in z.infolist()
                    if not i.is_dir() and os.path.splitext(i.filename)[1].lower() in IMAGE_EXT
                    and not os.path.basename(i.filename).startswith(".")]
    except (OSError, zipfile.BadZipFile):
        return []


def cache_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "FloppyStudio", "zip")
    os.makedirs(d, exist_ok=True)
    return d


def extract(path: str) -> str:
    """Chemin réel d'une image : extrait le membre d'un chemin virtuel (cache par archive et date)."""
    a, m = split(path)
    if m is None:
        return path
    st = os.stat(a)
    key = hashlib.md5(f"{os.path.abspath(a)}|{st.st_mtime}|{st.st_size}|{m}".encode()).hexdigest()[:12]
    d = os.path.join(cache_dir(), key)
    out = os.path.join(d, os.path.basename(m))
    if not os.path.isfile(out):
        os.makedirs(d, exist_ok=True)
        with zipfile.ZipFile(a) as z, z.open(m) as src, open(out + ".part", "wb") as dst:
            while True:
                b = src.read(1 << 20)
                if not b:
                    break
                dst.write(b)
        os.replace(out + ".part", out)
    return out


def display(path: str) -> str:
    a, m = split(path)
    return f"{os.path.basename(a)} › {m}" if m else os.path.basename(path)


def mtime(path: str) -> float:
    return os.stat(split(path)[0]).st_mtime


def purge_cache(days: int = 7):
    """Supprime les extractions anciennes du cache."""
    import shutil
    import time
    root = cache_dir()
    limit = time.time() - days * 86400
    for n in os.listdir(root):
        p = os.path.join(root, n)
        try:
            if os.path.getmtime(p) < limit:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass
