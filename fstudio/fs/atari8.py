"""Atari 8 bits : Atari DOS 2.0 / 2.5 (et compatibles) — lecture."""
from __future__ import annotations

from typing import List

from .base import Entry, FileSystem, human


def _sectors(disk) -> List[bytes]:
    out = []
    for c in range(disk.cyls):
        for h in range(disk.heads):
            for s in sorted(disk.track(c, h), key=lambda x: x.r):
                out.append(s.data or b"")
    return out


class AtariDOS(FileSystem):
    platform = "atari8"
    charset = "atascii"

    def __init__(self, secs: List[bytes]):
        super().__init__()
        self.secs = secs
        self._deleted: List[Entry] = []
        vtoc = self.sec(360)
        self.ssize = len(self.sec(361)) or 128
        total = vtoc[1] | vtoc[2] << 8
        free = vtoc[3] | vtoc[4] << 8
        ed = len(secs) >= 1040 and self.ssize == 128
        self.name = "Atari DOS " + ("2.5 (densité étendue)" if ed else "2.0" + ("D" if self.ssize == 256 else "S"))
        for di in range(8):
            d = self.sec(361 + di)
            for k in range(8):
                e = d[k * 16:(k + 1) * 16]
                if len(e) < 16 or e[0] == 0:
                    continue
                flags = e[0]
                count, start = e[1] | e[2] << 8, e[3] | e[4] << 8
                base = e[5:13].decode("latin-1").rstrip()
                ext = e[13:16].decode("latin-1").rstrip()
                name = base + ("." + ext if ext else "")
                if not name.strip() or not all(32 <= ord(c) < 127 for c in name):
                    continue
                fno = di * 8 + k
                ent = Entry(name, 0, False, "", "", "L" if flags & 0x20 else "",
                            {"secteurs": count, "secteur de départ": start, "n° de fichier": fno},
                            (start, fno, count))
                if flags & 0x80:
                    ent.deleted = True
                    self._deleted.append(ent)
                    continue
                data = self.read(ent)
                ent.size = len(data)
                ent.kind = "Atari BASIC" if _looks_atari_basic(data) else (
                    "Binaire (exécutable)" if data[:2] == b"\xff\xff" else "Fichier")
                self.root.add(ent)
        self.info = [("Système", self.name), ("Secteurs", f"{total} × {self.ssize} o"),
                     ("Libre", human(free * (self.ssize - 3))), ("Fichiers", str(len(self.files)))]

    def sec(self, n: int) -> bytes:
        return self.secs[n - 1] if 0 < n <= len(self.secs) else b""

    def read(self, e: Entry) -> bytes:
        start, fno, count = e.ref
        out, n, seen = bytearray(), start, set()
        while 0 < n <= len(self.secs) and n not in seen and len(seen) <= count + 2:
            seen.add(n)
            s = self.sec(n)
            if len(s) < 4:
                break
            used = s[-1] & (0x7F if len(s) == 128 else 0xFF)
            if (s[-3] >> 2) != fno and not e.deleted:
                break
            out += s[:min(used, len(s) - 3)]
            n = (s[-3] & 3) << 8 | s[-2]
        return bytes(out)

    def deleted(self) -> List[Entry]:
        for e in self._deleted:
            try:
                e.size = len(self.read(e))
            except Exception:
                pass
        return list(self._deleted)


def _looks_atari_basic(d: bytes) -> bool:
    if len(d) < 14:
        return False
    w = [d[i] | d[i + 1] << 8 for i in range(0, 14, 2)]
    return w[0] == 0 and w[1] <= w[2] <= w[3] <= w[4] <= w[5] <= w[6] < 0xC000


def probe(disk) -> List[FileSystem]:
    if not disk.tracks:
        return []
    t0 = disk.track(0, 0)
    if not t0 or len(t0) not in (18, 26) or any(s.n > 1 for s in t0[3:]):
        return []
    secs = _sectors(disk)
    if len(secs) < 368:
        return []
    vtoc = secs[359]
    if not vtoc or vtoc[0] not in (1, 2, 3):
        return []
    total = vtoc[1] | vtoc[2] << 8
    if not 0 < total <= len(secs):
        return []
    try:
        fs = AtariDOS(secs)
    except Exception:
        return []
    return [fs]
