"""DOS BASIC Thomson (TO7/TO8/TO9/MO5/MO6) — une face = un volume."""
from __future__ import annotations

import time
from typing import List, Optional

from .base import Entry, FileSystem, FSError, b16, human, mark_bad

TYPES = {0: "Programme BASIC", 1: "Données BASIC", 2: "Langage machine", 3: "Source assembleur"}
DIR_TRACK = 20


class ThomsonFS(FileSystem):
    platform = "thomson"
    charset = "thomson"

    def __init__(self, data: bytes, side: int, ssize: int = 256, inverted: bool = False):
        super().__init__()
        self._args = (side, ssize, inverted)
        self.inverted = inverted
        self.d = bytes(b ^ 0xFF for b in data) if inverted else data
        self.ss = ssize
        self.spb = 8                                     # secteurs par bloc
        self.side = side
        self.name = "DOS BASIC Thomson"
        self.volume_name = f"Face {side}"
        self.ntracks = len(data) // (16 * ssize)
        self.nblocks = self.ntracks * 2
        fat = self.sector(DIR_TRACK, 2)
        self.fat = fat[1:1 + self.nblocks]
        self._parse()
        free = sum(1 for v in self.fat if v == 0xFF) * self.spb * self.ss
        self.info = [("Système", self.name), ("Face", str(side)), ("Pistes", str(self.ntracks)),
                     ("Secteurs", f"16 × {ssize} o"), ("Libre", human(free)),
                     ("Fichiers", str(len(self.files)))] + ([("Note", "données inversées")] if inverted else [])

    def sector(self, track: int, sec: int) -> bytes:
        o = (track * 16 + sec - 1) * self.ss
        return self.d[o:o + self.ss].ljust(self.ss, b"\0")

    def _parse(self):
        for s in range(3, 17):
            b = self.sector(DIR_TRACK, s)
            for i in range(0, self.ss, 32):
                e = b[i:i + 32]
                if e[0] == 0xFF:
                    return
                if e[0] == 0:
                    continue
                name = e[0:8].decode("latin-1", "replace").rstrip()
                ext = e[8:11].decode("latin-1", "replace").rstrip()
                ftype, ascii_ = e[11], e[12] == 0xFF
                comment = e[16:24].decode("latin-1", "replace").strip("\0 ")
                date = ""
                if 1 <= e[24] <= 31 and 1 <= e[25] <= 12:
                    date = f"{e[24]:02d}/{e[25]:02d}/{1900 + e[26] if e[26] > 50 else 2000 + e[26]}"
                kind = TYPES.get(ftype, f"type {ftype}") + (" (ASCII)" if ascii_ else "")
                meta = {"type": ftype, "ascii": ascii_, "1er bloc": e[13]}
                if comment:
                    meta["commentaire"] = comment
                ent = Entry(f"{name}.{ext}" if ext else name, 0, False, kind, date,
                            "A" if ascii_ else "B", meta, (e[13], b16(e, 14)))
                ent.slot = (s, i)
                try:
                    ent.size = len(self.read(ent))
                except Exception:
                    pass
                self.root.add(ent)

    def read(self, e: Entry) -> bytes:
        blk, last_bytes = e.ref
        out, seen = bytearray(), set()
        while 0 <= blk < self.nblocks and blk not in seen:
            seen.add(blk)
            nxt = self.fat[blk]
            base = blk * self.spb
            if 0xC1 <= nxt <= 0xC8:
                n = nxt - 0xC0
                for i in range(n):
                    tr, sc = divmod(base + i, 16)
                    data = self.sector(tr, sc + 1)
                    out += data[:last_bytes] if i == n - 1 else data
                break
            for i in range(self.spb):
                tr, sc = divmod(base + i, 16)
                out += self.sector(tr, sc + 1)
            if nxt >= self.nblocks:
                break
            blk = nxt
        return bytes(out)

    def content(self, e: Entry) -> bytes:
        return self.read(e)

    def allocation(self):
        own = []
        bsize = self.spb * self.ss
        for b in range(self.nblocks):
            v = self.fat[b] if b < len(self.fat) else 0xFE
            own.append("sys" if v == 0xFE else "free" if v == 0xFF else "used")
        for e in self.files:
            blk, seen = e.ref[0], set()
            while 0 <= blk < self.nblocks and blk not in seen:
                seen.add(blk)
                own[blk] = e
                nxt = self.fat[blk]
                if nxt >= self.nblocks:
                    break
                blk = nxt
        mark_bad(own, bsize, self.d)
        return bsize, own

    def deleted(self) -> List[Entry]:
        out = []
        for s in range(3, 17):
            b = self.sector(DIR_TRACK, s)
            for i in range(0, self.ss, 32):
                e = b[i:i + 32]
                if e[0] == 0xFF:
                    return out
                if e[0] != 0 or not e[1:8].strip(b" \0") or not all(32 <= c < 127 for c in e[1:11]):
                    continue
                name = "?" + e[1:8].decode("latin-1").rstrip()
                ext = e[8:11].decode("latin-1").rstrip()
                if e[13] >= self.nblocks:
                    continue
                ent = Entry(name + ("." + ext if ext else ""), 0, False,
                            "Supprimé — 1er bloc seulement (chaînage effacé)", "", "",
                            {"type": e[11], "1er bloc": e[13]}, (e[13], b16(e, 14)))
                ent.deleted = True
                try:
                    ent.size = len(self.read(ent))
                except Exception:
                    pass
                out.append(ent)
        return out


# ----------------------------------------------------------------------------
# Écriture
# ----------------------------------------------------------------------------
EXT_TYPES = {"BAS": 0, "DAT": 1, "BIN": 2, "MAP": 2, "CHG": 2, "ASM": 3, "TXT": 1}


def _wsector(self, track: int, sec: int, data: bytes):
    o = (track * 16 + sec - 1) * self.ss
    self.d[o:o + self.ss] = data[:self.ss].ljust(self.ss, b"\0")


def _wfat(self):
    sec = bytearray(self.sector(DIR_TRACK, 2))
    sec[1:1 + len(self.fat)] = bytes(self.fat)
    self._wsector(DIR_TRACK, 2, bytes(sec))


def _t_prepare(self):
    if not isinstance(self.d, bytearray):
        self.d = bytearray(self.d)
    if not isinstance(self.fat, bytearray):
        self.fat = bytearray(self.fat)


def _t_add(self, parent: Entry, name: str, data: bytes) -> str:
    self._prepare()
    up = name.upper()
    base, _, ext = up.rpartition(".") if "." in up else (up, "", "")
    clean = lambda t: "".join(c if c.isascii() and (c.isalnum() or c in "-_") else "_" for c in t)
    base, ext = (clean(base)[:8] or "FICHIER"), clean(ext)[:3]
    n11 = base.ljust(8).encode() + ext.ljust(3).encode()
    for e in self.files:
        nm = e.name.upper()
        b2, _, e2 = nm.rpartition(".") if "." in nm else (nm, "", "")
        if b2.ljust(8).encode() + e2.ljust(3).encode() == n11:
            raise FSError(f"{base}.{ext} existe déjà")
    ftype = EXT_TYPES.get(ext, 2)
    text = all(c in (9, 10, 13) or 32 <= c < 127 or c >= 0xA0 or c == 0x16 for c in data[:2048])
    ascii_ = ftype in (1, 3) or (ftype == 0 and text and data[:1] != b"\xff")
    spb_bytes = self.spb * self.ss
    nblk = max(1, -(-len(data) // spb_bytes))
    free = [b for b in range(self.nblocks) if self.fat[b] == 0xFF]
    if len(free) < nblk:
        raise FSError(f"Espace insuffisant : {nblk} bloc(s) requis, {len(free)} libre(s)")
    # emplacement de répertoire
    slot = None
    for sct in range(3, 17):
        b = self.sector(DIR_TRACK, sct)
        for i in range(0, self.ss, 32):
            if b[i] in (0x00, 0xFF):
                slot = (sct, i)
                break
        if slot:
            break
    if slot is None:
        raise FSError("Répertoire plein")
    blocks = free[:nblk]
    for k, blk in enumerate(blocks):
        chunk = data[k * spb_bytes:(k + 1) * spb_bytes]
        for i in range(self.spb):
            part = chunk[i * self.ss:(i + 1) * self.ss]
            if not part and k == nblk - 1 and i > 0:
                break
            tr, sc = divmod(blk * self.spb + i, 16)
            self._wsector(tr, sc + 1, part)
        if k + 1 < nblk:
            self.fat[blk] = blocks[k + 1]
        else:
            rest = len(data) - k * spb_bytes
            nsec = max(1, -(-rest // self.ss))
            self.fat[blk] = 0xC0 + nsec
            last = rest - (nsec - 1) * self.ss
    ent = bytearray(32)
    ent[0:11] = n11
    ent[11] = ftype
    ent[12] = 0xFF if ascii_ else 0x00
    ent[13] = blocks[0]
    ent[14:16] = max(last, 0).to_bytes(2, "big")
    ent[16:24] = b" " * 8
    t = time.localtime()
    ent[24:27] = bytes([t.tm_mday, t.tm_mon, t.tm_year % 100])
    sec = bytearray(self.sector(DIR_TRACK, slot[0]))
    sec[slot[1]:slot[1] + 32] = ent
    self._wsector(DIR_TRACK, slot[0], bytes(sec))
    self._wfat()
    self.refresh()
    return f"{base}.{ext}" if ext else base


def _t_delete(self, e: Entry):
    self._prepare()
    blk, seen = e.ref[0], set()
    while 0 <= blk < self.nblocks and blk not in seen:
        seen.add(blk)
        nxt = self.fat[blk]
        self.fat[blk] = 0xFF
        if nxt >= self.nblocks:
            break
        blk = nxt
    sct, off = e.slot
    sec = bytearray(self.sector(DIR_TRACK, sct))
    sec[off] = 0
    self._wsector(DIR_TRACK, sct, bytes(sec))
    self._wfat()
    self.refresh()


def _t_refresh(self):
    data = bytes(b ^ 0xFF for b in self.d) if self.inverted else bytes(self.d)
    disk, head = getattr(self, "disk", None), getattr(self, "head", None)
    self.__init__(data, *self._args)
    self.disk, self.head = disk, head
    if disk is not None and head is not None:
        n = 16
        for tr in range(self.ntracks):
            for sc in range(1, n + 1):
                s = disk.sector(tr, head, sc)
                if s is not None:
                    o = (tr * 16 + sc - 1) * self.ss
                    s.data, s.ok = data[o:o + self.ss], True
        disk.raw = None


def _t_save(self, path: str):
    disk = getattr(self, "disk", None)
    if disk is not None and disk.tracks:
        data = disk.linear(heads=list(range(disk.heads)), sequential=True)
    else:
        data = bytes(b ^ 0xFF for b in self.d) if self.inverted else bytes(self.d)
    with open(path, "wb") as f:
        f.write(data)


ThomsonFS.writable = True
ThomsonFS.save_ext = ".fd"
ThomsonFS._wsector = _wsector
ThomsonFS._wfat = _wfat
ThomsonFS._prepare = _t_prepare
ThomsonFS.add_file = _t_add
ThomsonFS.delete = _t_delete
ThomsonFS.refresh = _t_refresh
ThomsonFS.save = _t_save


def binary_info(data: bytes) -> Optional[dict]:
    """Format des fichiers binaires Thomson : blocs 00 LL LL AA AA ..., fin FF 00 00 EE EE."""
    i, chunks = 0, []
    while i + 5 <= len(data):
        if data[i] == 0x00:
            ln, ad = b16(data, i + 1), b16(data, i + 3)
            chunks.append((ad, ln))
            i += 5 + ln
        elif data[i] == 0xFF:
            return {"blocs": chunks, "exec": b16(data, i + 3)}
        else:
            return None
    return None


def _valid(data: bytes, ss: int) -> bool:
    o = (DIR_TRACK * 16 + 1) * ss
    if len(data) < o + ss:
        return False
    fat = data[o:o + ss]
    nb = len(data) // (16 * ss) * 2
    return fat[0] == 0 and fat[41] == 0xFE and fat[42] == 0xFE and \
        all(v in (0xFF, 0xFE) or v < nb or 0xC1 <= v <= 0xC8 for v in fat[1:1 + nb])


def probe(disk) -> List[FileSystem]:
    out = []
    sides = []
    if disk.tracks:
        ss_set = {128 << s.n for t in disk.tracks.values() for s in t}
        nsec = {len(t) for t in disk.tracks.values()}
        if not (ss_set <= {256, 128} and nsec and max(nsec) == 16):
            return []
        ss = max(ss_set)
        for h in range(disk.heads):
            sides.append((h, disk.linear(heads=[h], sequential=True), ss))
    elif disk.raw is not None and len(disk.raw) % (16 * 256) == 0:
        sides.append((0, disk.raw, 256))
    for side, data, ss in sides:
        for inv in (False, True):
            d = bytes(b ^ 0xFF for b in data) if inv else data
            if _valid(d, ss):
                try:
                    fs = ThomsonFS(data, side, ss, inv)
                    if disk.tracks:
                        fs.disk, fs.head = disk, side
                    out.append(fs)
                except Exception:
                    pass
                break
    return out
