"""Oric (Microdisc / Telestrat) : Sedoric — lecture."""
from __future__ import annotations

from typing import List, Optional

from .base import Entry, FileSystem, human

DIR_TRACK = 20


class Sedoric(FileSystem):
    platform = "oric"
    charset = "latin-1"

    def __init__(self, disk):
        super().__init__()
        self.disk = disk
        sysd = self.sec(DIR_TRACK, 1) or b""
        bmp = self.sec(DIR_TRACK, 2) or b""
        self.label = sysd[9:30].decode("latin-1", "replace").replace("\x1b", " ").strip()
        free = bmp[2] | bmp[3] << 8 if bmp else 0
        nfiles = bmp[4] | bmp[5] << 8 if bmp else 0
        tracks, spt = (bmp[6], bmp[7]) if bmp else (0, 0)
        ds = bool(bmp[9] & 0x80) if bmp else False
        self.name = "Sedoric"
        t, s, seen = DIR_TRACK, 4, set()
        while (t, s) not in seen and len(seen) < 64:
            seen.add((t, s))
            d = self.sec(t, s)
            if not d:
                break
            for o in range(0x10, 0x100, 0x10):
                e = d[o:o + 16]
                if e[0] in (0, 0xFF) or e[12] == 0 and e[13] == 0:
                    continue
                name = e[0:9].decode("latin-1", "replace").rstrip()
                ext = e[9:12].decode("latin-1", "replace").rstrip()
                if not name or not all(32 <= ord(c) < 127 for c in name + ext):
                    continue
                full = f"{name}.{ext}" if ext else name
                ent = self._file(full, e[12], e[13], bool(e[15] & 0x80))
                if ent:
                    self.root.add(ent)
            t, s = d[0], d[1]
            if s == 0:
                break
        self.info = [("Système", self.name), ("Disque", self.label or "—"),
                     ("Géométrie", f"{tracks & 0x7F} pistes × {spt} secteurs" + (", 2 faces" if ds else "")),
                     ("Libre", human(free * 256)), ("Fichiers", str(nfiles))]

    def sec(self, trk: int, sec: int) -> Optional[bytes]:
        s = self.disk.sector(trk & 0x7F, 1 if trk & 0x80 else 0, sec)
        return s.data if s and s.data else None

    def _file(self, name: str, dt: int, ds: int, locked: bool) -> Optional[Entry]:
        d = self.sec(dt, ds)
        if not d or d[2] != 0xFF:
            return None
        ftype = d[3]
        start, end, execa = d[4] | d[5] << 8, d[6] | d[7] << 8, d[8] | d[9] << 8
        nsec = d[10] | d[11] << 8
        chain, off, seen = [], 0x0C, {(dt, ds)}
        while len(chain) < nsec:
            if off >= 0x100:
                nt, ns = d[0], d[1]
                if ns == 0 or (nt, ns) in seen:
                    break
                seen.add((nt, ns))
                d = self.sec(nt, ns)
                if not d:
                    break
                off = 2
                continue
            t, s = d[off], d[off + 1]
            if s == 0:
                break
            chain.append((t, s))
            off += 2
        size = max(end - start + 1, 0) if end >= start else nsec * 256
        kind = "Programme BASIC" if ftype & 0x80 else ("Code" if ftype & 0x40 else "Fichier")
        if ftype & 0x40 and execa:
            kind = "Code (exécutable)"
        meta = {"début": f"#{start:04X}", "fin": f"#{end:04X}", "secteurs": nsec}
        if execa:
            meta["exécution"] = f"#{execa:04X}"
        return Entry(name, size, False, kind, "", "L" if locked else "", meta, (chain, size))

    def read(self, e: Entry) -> bytes:
        chain, size = e.ref
        out = b"".join(self.sec(t, s) or bytes(256) for t, s in chain)
        return out[:size]


def probe(disk) -> List[FileSystem]:
    t = disk.track(DIR_TRACK, 0)
    if not t or len(t) < 15 or any(s.n != 1 for s in t):
        return []
    s2 = disk.sector(DIR_TRACK, 0, 2)
    if not s2 or not s2.data or s2.data[0] != 0xFF:
        return []
    bmp = s2.data
    if not (bmp[7] in (16, 17, 18, 19) and 20 < (bmp[6] & 0x7F) <= 101):
        return []
    try:
        return [Sedoric(disk)]
    except Exception:
        return []
