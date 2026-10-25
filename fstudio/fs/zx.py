"""ZX Spectrum : +3DOS (Spectrum +3, CP/M) et TR-DOS (Beta Disk) — lecture (+3DOS : écriture)."""
from __future__ import annotations

from typing import List, Optional

from .base import Entry, FileSystem, human
from .cpm import CPMFS

P3_TYPES = {0: "Programme BASIC", 1: "Tableau numérique", 2: "Tableau de caractères", 3: "Code"}


def plus3_header(d: bytes) -> Optional[dict]:
    if len(d) < 128 or d[:8] != b"PLUS3DOS" or d[8] != 0x1A:
        return None
    if sum(d[:127]) & 0xFF != d[127]:
        return None
    return {"size": int.from_bytes(d[11:15], "little"), "type": d[15],
            "length": d[16] | d[17] << 8, "p1": d[18] | d[19] << 8, "p2": d[20] | d[21] << 8}


class Plus3FS(CPMFS):
    platform = "zx"
    prefix = "Spectrum +3DOS"

    def __init__(self, disk, first_id: int, layout: Optional[tuple] = None):
        super().__init__(disk, first_id, layout)
        self.writable = self.nblocks <= 255
        for e in self.files:
            h = plus3_header(self._blocks(e.ref["blocks"][:1]))
            if h:
                e.meta.pop("en-tête AMSDOS", None)
                e.meta.pop("type AMSDOS", None)
                e.meta.update({"en-tête +3DOS": "oui", "type +3": P3_TYPES.get(h["type"], str(h["type"]))})
                if h["type"] == 0:
                    e.meta["démarrage"] = h["p1"] if h["p1"] < 32768 else "—"
                else:
                    e.meta["adresse"] = h["p1"]
                e.kind = P3_TYPES.get(h["type"], "Fichier +3")
                e.size = h["length"]

    def content(self, e: Entry) -> bytes:
        d = self._blocks(e.ref["blocks"])
        h = plus3_header(d)
        if h:
            return d[128:128 + h["length"]]
        return super().content(e)


def plus3_layout(disk) -> Optional[tuple]:
    """Paramètres du disque d'après l'enregistrement de spécification (piste 0, secteur 1)."""
    s = disk.sector(0, 0, 1)
    b = s.data if s and s.data else b""
    if not b:
        return None
    if b[0] == 0xE5 or b[:10] == bytes(10):
        return ("+3", 1, 1024, 64, 1)
    fmt, sides, tracks, spt, psh, res, bsh, dirblk = b[:8]
    if fmt not in (0, 1, 2, 3) or spt not in (8, 9, 10) or psh != 2 or not 0 <= res <= 3 or bsh not in (3, 4, 5):
        return None
    bsize = 128 << bsh
    nsides = 2 if (sides & 3) else 1
    return ("+3" if nsides == 1 else "+3 double face", res, bsize, dirblk * bsize // 32, nsides)


# --------------------------------------------------------------------------
# TR-DOS
# --------------------------------------------------------------------------
TR_TYPES = {"B": "Programme BASIC", "C": "Code", "D": "Données", "#": "Fichier séquentiel"}
TR_DISK = {0x16: "80 pistes, 2 faces", 0x17: "40 pistes, 2 faces", 0x18: "80 pistes, 1 face",
           0x19: "40 pistes, 1 face"}


class TRDOS(FileSystem):
    platform = "zx"
    charset = "latin-1"

    def __init__(self, d: bytes):
        super().__init__()
        self.d = d
        info = d[0x800:0x900]
        self.label = info[0xF5:0xFD].decode("latin-1", "replace").strip()
        dtype, nfiles = info[0xE3], info[0xE4]
        free = info[0xE5] | info[0xE6] << 8
        self.name = "TR-DOS"
        self._deleted: List[Entry] = []
        for i in range(128):
            e = d[i * 16:(i + 1) * 16]
            if e[0] == 0:
                break
            name = e[0:8].decode("latin-1", "replace").rstrip()
            ext = chr(e[8]) if 32 <= e[8] < 127 else "?"
            p1, p2 = e[9] | e[10] << 8, e[11] | e[12] << 8
            nsec, sec, trk = e[13], e[14], e[15]
            length = p1 if ext == "B" else (p2 if ext == "C" else nsec * 256)
            length = min(length or nsec * 256, nsec * 256)
            meta = {"secteurs": nsec, "piste": trk, "secteur": sec}
            if ext == "C":
                meta["adresse"] = p1
            ent = Entry(f"{name}.{ext}", length, False, TR_TYPES.get(ext, "Fichier"), "", "", meta,
                        ((trk * 16 + sec) * 256, length, ext, p2))
            if e[0] == 1:
                ent.name = "?" + ent.name[1:]
                ent.deleted = True
                self._deleted.append(ent)
                continue
            self.root.add(ent)
        self.info = [("Système", self.name), ("Disque", self.label or "—"),
                     ("Géométrie", TR_DISK.get(dtype, f"type {dtype:02X}")),
                     ("Libre", human(free * 256)), ("Fichiers", str(nfiles))]

    def read(self, e: Entry) -> bytes:
        off, length, _ext, _p2 = e.ref
        return self.d[off:off + length]

    def content(self, e: Entry) -> bytes:
        off, length, ext, p2 = e.ref
        if ext == "B":
            return self.d[off:off + (p2 or length)]
        return self.read(e)

    def deleted(self) -> List[Entry]:
        return list(self._deleted)


def probe(disk) -> List[FileSystem]:
    d = disk.linear()
    # TR-DOS : secteur 9 de la piste 0
    if len(d) >= 0x900 and d[0x8E7] == 0x10 and d[0x8E3] in TR_DISK:
        try:
            return [TRDOS(d)]
        except Exception:
            pass
    # +3DOS : secteurs ID 1…9 de 512 octets, spécification de disque ou en-têtes PLUS3DOS
    t0 = disk.track(0, 0)
    if not t0 or any(s.n != 2 for s in t0) or min(s.r for s in t0) != 1 or len(t0) not in (8, 9, 10):
        return []
    lay = plus3_layout(disk)
    if lay is None:
        return []
    try:
        fs = Plus3FS(disk, 1, lay)
    except Exception:
        return []
    spec = disk.sector(0, 0, 1)
    spec_ok = spec is not None and spec.data[:1] in (b"\x00", b"\x03")
    p3 = any(e.meta.get("en-tête +3DOS") for e in fs.files)
    return [fs] if (p3 or spec_ok) else []
