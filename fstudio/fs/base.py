"""Structures communes aux systèmes de fichiers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple


@dataclass(eq=False)
class Entry:
    name: str
    size: int = 0
    is_dir: bool = False
    kind: str = ""                     # type lisible (« Programme BASIC », « Dossier »…)
    date: str = ""
    attrs: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)
    ref: Any = None                    # donnée interne au FS pour relire le fichier
    children: List["Entry"] = field(default_factory=list)
    parent: Optional["Entry"] = None
    deleted: bool = False

    def add(self, e: "Entry") -> "Entry":
        e.parent = self
        self.children.append(e)
        return e

    @property
    def path(self) -> str:
        parts, e = [], self
        while e is not None and e.parent is not None:
            parts.append(e.name)
            e = e.parent
        return "/".join(reversed(parts))

    @property
    def ext(self) -> str:
        n = self.name
        return n.rsplit(".", 1)[1].lower() if "." in n else ""

    def walk(self) -> Iterator["Entry"]:
        for c in self.children:
            yield c
            if c.is_dir:
                yield from c.walk()


class FSError(Exception):
    pass


class FileSystem:
    name = "?"                     # « FAT12 », « AmigaDOS (FFS) »…
    platform = "pc"                # pc | atarist | msx | amiga | c64 | thomson | cpc | akai
    charset = "cp437"

    def __init__(self):
        self.label = ""
        self.root = Entry("", is_dir=True, kind="Racine")
        self.info: List[Tuple[str, str]] = []
        self.volume_name = ""      # pour distinguer plusieurs volumes d'une même image

    writable = False               # ajout / suppression de fichiers possibles

    def allocation(self):
        """(taille d'unité en octets, [propriétaire par unité]) ; propriétaire = Entry,
        "sys", "free", "bad" ou "used" (occupé sans fichier connu). None si non pris en charge."""
        return None

    def deleted(self) -> List["Entry"]:
        """Fichiers supprimés encore présents dans le répertoire."""
        return []
    save_ext = ".img"

    def read(self, e: Entry) -> bytes:
        raise NotImplementedError

    def add_file(self, parent: Entry, name: str, data: bytes) -> str:
        raise FSError("Modification non prise en charge pour ce système")

    def delete(self, e: Entry):
        raise FSError("Modification non prise en charge pour ce système")

    def save(self, path: str):
        raise FSError("Enregistrement non pris en charge pour ce système")

    def content(self, e: Entry) -> bytes:
        """Données utiles (sans en-tête système éventuel)."""
        return self.read(e)

    @property
    def files(self) -> List[Entry]:
        return [e for e in self.root.walk() if not e.is_dir]

    def title(self) -> str:
        t = self.name
        if self.volume_name:
            t = f"{self.volume_name} — {t}"
        if self.label:
            t += f" « {self.label} »"
        return t


def mark_bad(own: list, unit: int, data: bytes, base: int = 0):
    """Marque « bad » les unités contenant le motif des secteurs illisibles."""
    from .disk import BAD
    pos = data.find(BAD)
    while pos >= 0:
        k = (pos - base) // unit
        if 0 <= k < len(own):
            own[k] = "bad"
        pos = data.find(BAD, pos + 16)


def u16(b, o):
    return b[o] | (b[o + 1] << 8)


def u32(b, o):
    return b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)


def b16(b, o):
    return (b[o] << 8) | b[o + 1]


def b32(b, o):
    return (b[o] << 24) | (b[o + 1] << 16) | (b[o + 2] << 8) | b[o + 3]


def human(n: int) -> str:
    if n < 1024:
        return f"{n} o"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} Ko".replace(".", ",")
    return f"{n / 1048576:.2f} Mo".replace(".", ",")
