"""Création d'une image disquette à partir d'un dossier Windows."""
from __future__ import annotations

import os
import time
from typing import Dict, List

from .fs import open_image
from .fs import mkfs as MK
from .fs.base import FileSystem


def _save(disk, fs: FileSystem, path: str):
    """Enregistre l'image modifiée (même logique que l'explorateur)."""
    from .fs.base import FileSystem as Base
    if type(fs).save is not Base.save:
        fs.save(path)
        return
    data = disk.linear(heads=list(range(disk.heads)), sequential=True) if path.lower().endswith(".fd") \
        else disk.linear()
    with open(path, "wb") as f:
        f.write(data)


def build_from_folder(spec: MK.MkSpec, label: str, folder: str, out_dir: str) -> Dict:
    """Formate une image vierge, y copie le contenu du dossier et l'enregistre.
    Retourne {path, fmt, added, errors, free, fs}."""
    blank_ext = {".st": ".st"}.get(spec.ext, spec.ext)
    tmp = os.path.join(out_dir, f"dossier_{int(time.time() * 1000)}{blank_ext}")
    with open(tmp, "wb") as f:
        f.write(spec.build(label))
    disk, vols = open_image(tmp, spec.fmt)
    if not vols:
        raise RuntimeError("Système de fichiers vierge non reconnu")
    fs = vols[0]
    if not fs.writable:
        raise RuntimeError(f"{fs.name} : écriture de fichiers non prise en charge")
    added: List[str] = []
    errors: List[str] = []

    def find(path: str):
        e = fs.root
        for part in [x for x in path.split("/") if x]:
            e = next((c for c in e.children if c.name == part or c.meta.get("nom 8.3") == part), e)
        return e

    def walk(src: str, dest: str):
        for name in sorted(os.listdir(src), key=str.lower):
            p = os.path.join(src, name)
            if name.startswith(".") or name.lower() in ("thumbs.db", "desktop.ini"):
                continue
            try:
                if os.path.isdir(p):
                    if not hasattr(fs, "mkdir"):
                        walk(p, dest)          # système sans dossiers : contenu aplati
                        continue
                    nm = fs.mkdir(find(dest), name)
                    sub = (dest + "/" if dest else "") + nm
                    added.append(sub + "/")
                    walk(p, sub)
                else:
                    with open(p, "rb") as f:
                        data = f.read()
                    added.append(((dest + "/") if dest else "") + fs.add_file(find(dest), name, data))
            except Exception as ex:
                errors.append(f"{os.path.relpath(p, folder)} : {ex}")

    walk(folder, "")
    base = label or os.path.basename(os.path.normpath(folder)) or "disquette"
    base = "".join(c if c not in '<>:"/\\|?*' else "_" for c in base)
    out = os.path.join(out_dir, base + (fs.save_ext if hasattr(fs, "save_ext") else spec.ext))
    _save(disk, fs, out)
    try:
        os.remove(tmp)
    except OSError:
        pass
    disk2, vols2 = open_image(out, spec.fmt)
    fs2 = vols2[0] if vols2 else fs
    free = dict(fs2.info).get("Libre", "")
    return {"path": out, "fmt": spec.fmt, "added": added, "errors": errors, "free": free, "fs": fs2.name,
            "files": len(fs2.files)}
