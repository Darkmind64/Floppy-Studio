"""Amstrad CPC / PCW : CP/M 2.2 (AMSDOS) — formats Data, Système, IBM."""
from __future__ import annotations

from collections import OrderedDict
from typing import List, Optional

from .base import Entry, FileSystem, FSError, human, u16

# premier ID secteur : (nom, pistes réservées, bloc, entrées répertoire)
LAYOUTS = {0xC1: ("Data", 0, 1024, 64), 0x41: ("Système", 2, 1024, 64),
           0x01: ("IBM", 1, 1024, 64)}
AMS_TYPES = {0: "BASIC", 1: "BASIC protégé", 2: "Binaire", 3: "Binaire protégé",
             0x16: "ASCII"}


def amsdos_header(data: bytes) -> Optional[dict]:
    if len(data) < 128:
        return None
    if sum(data[:67]) & 0xFFFF != u16(data, 67) or not any(data[:67]):
        return None
    return {"type": data[18], "load": u16(data, 21), "length": u16(data, 24),
            "exec": u16(data, 26), "real": data[64] | data[65] << 8 | data[66] << 16,
            "user": data[0], "name": data[1:12].decode("ascii", "replace")}


class CPMFS(FileSystem):
    platform = "cpc"
    charset = "latin-1"

    def __init__(self, disk, first_id: int):
        super().__init__()
        self.disk = disk
        lname, self.off, self.bsize, self.ndir = LAYOUTS[first_id]
        self.name = f"AMSDOS / CP/M ({lname})"
        self.first = first_id
        self.spt = len(disk.track(0, 0))
        self.ssize = 512
        self.ntracks = disk.cyls
        total = (self.ntracks - self.off) * self.spt * self.ssize
        self.nblocks = total // self.bsize
        raw = self._blocks(range(0, self.ndir * 32 // self.bsize))
        self._parse(raw)
        used = set()
        for e in self.files:
            used.update(e.ref["blocks"])
        free = (self.nblocks - len(used) - self.ndir * 32 // self.bsize) * self.bsize
        bad = disk.bad_sectors()
        self.info = [("Système", self.name), ("Pistes", str(self.ntracks)),
                     ("Secteurs", f"{self.spt} × 512 o (ID {first_id:02X}…)"),
                     ("Bloc", f"{self.bsize} o"), ("Libre", human(max(free, 0))),
                     ("Fichiers", str(len(self.files)))] + \
                    ([("Secteurs défectueux", str(bad))] if bad else [])

    def _lsector(self, n: int) -> bytes:
        tr, idx = divmod(n, self.spt)
        tr += self.off
        s = self.disk.sector(tr, 0, self.first + idx)
        return (s.data if s and s.data else b"\xE5" * self.ssize)[:self.ssize].ljust(self.ssize, b"\0")

    def _blocks(self, blocks) -> bytes:
        k = self.bsize // self.ssize
        return b"".join(self._lsector(b * k + i) for b in blocks for i in range(k))

    def _parse(self, raw: bytes):
        files: "OrderedDict[tuple, list]" = OrderedDict()
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            user = e[0]
            if user > 15:
                continue
            name = bytes(c & 0x7F for c in e[1:9]).decode("ascii", "replace").rstrip()
            ext = bytes(c & 0x7F for c in e[9:12]).decode("ascii", "replace").rstrip()
            if not name or not all(32 <= ord(ch) < 127 for ch in name + ext):
                continue
            key = (user, name, ext)
            files.setdefault(key, []).append((e[12] + 32 * e[14], e[15], list(e[16:32]),
                                              e[9] & 0x80, e[10] & 0x80))
        for (user, name, ext), exts in files.items():
            exts.sort()
            blocks = [b for x in exts for b in x[2] if b]
            size = (exts[-1][0] - exts[0][0]) * 16384 + exts[-1][1] * 128 if exts else 0
            size = min(size, len(blocks) * self.bsize) if len(exts) == 1 else size
            fname = f"{name}.{ext}" if ext else name
            if user:
                fname = f"{user}-{fname}"
            attrs = ("R" if exts[0][3] else "") + ("S" if exts[0][4] else "")
            ent = Entry(fname, size, False, "", "", attrs, {"utilisateur": user, "blocs": len(blocks)},
                        {"blocks": [b for b in blocks if b < self.nblocks]})
            data = self.read(ent)
            h = amsdos_header(data)
            if h:
                ent.meta.update({"en-tête AMSDOS": "oui", "type AMSDOS": AMS_TYPES.get(h["type"] & 0x0F,
                                 f"{h['type']}"), "chargement": f"&{h['load']:04X}",
                                 "exécution": f"&{h['exec']:04X}"})
                ent.kind = AMS_TYPES.get(h["type"] & 0x0F, "Binaire")
                ent.size = h["real"] or h["length"]
            else:
                ent.kind = "ASCII / CP/M"
            self.root.add(ent)

    # ------------------------------------------------------------ Analyse
    def allocation(self):
        sys_units = self.off * self.spt * self.ssize // self.bsize
        own = ["sys"] * sys_units
        dirb = self.ndir * 32 // self.bsize
        own += ["sys"] * dirb + ["free"] * (self.nblocks - dirb)
        for e in self.files:
            for b in e.ref["blocks"]:
                if b < self.nblocks:
                    own[sys_units + b] = e
        bad = set()
        for b in range(self.nblocks):
            k = self.bsize // self.ssize
            for i in range(k):
                tr, idx = divmod(b * k + i, self.spt)
                s = self.disk.sector(tr + self.off, 0, self.first + idx)
                if s is None or not s.ok:
                    bad.add(b)
        for b in bad:
            own[sys_units + b] = "bad"
        return self.bsize, own

    def deleted(self) -> List[Entry]:
        raw = self._dir()
        groups: "OrderedDict[bytes, list]" = OrderedDict()
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            if e[0] != 0xE5:
                continue
            nm = bytes(c & 0x7F for c in e[1:12])
            if not all(32 <= c < 127 for c in nm) or not nm.strip():
                continue
            groups.setdefault(nm, []).append((e[12] + 32 * e[14], e[15], [b for b in e[16:32] if b]))
        live = {b for f in self.files for b in f.ref["blocks"]}
        out = []
        for nm, exts in groups.items():
            exts.sort()
            blocks = [b for x in exts for b in x[2] if b < self.nblocks]
            if not blocks:
                continue
            size = (exts[-1][0] - exts[0][0]) * 16384 + exts[-1][1] * 128
            name = nm[:8].decode().rstrip() + ("." + nm[8:].decode().rstrip() if nm[8:].strip() else "")
            reused = any(b in live for b in blocks)
            ent = Entry(name, size, False, "Supprimé — " + ("partiellement écrasé" if reused else "récupérable"),
                        "", "", {"blocs": len(blocks)}, {"blocks": blocks})
            data = self._blocks(blocks)
            h = amsdos_header(data)
            if h:
                ent.meta["en-tête AMSDOS"] = "oui"
                ent.size = h["real"] or h["length"]
            ent.deleted = True
            out.append(ent)
        return out

    # ------------------------------------------------------------ Écriture
    writable = True
    save_ext = ".dsk"

    def _wlsector(self, n: int, data: bytes):
        tr, idx = divmod(n, self.spt)
        s = self.disk.sector(tr + self.off, 0, self.first + idx)
        if s is None:
            raise FSError(f"Secteur absent (piste {tr + self.off}, ID {self.first + idx:02X})")
        s.data, s.ok = bytes(data[:self.ssize].ljust(self.ssize, b"\0")), True
        self.disk.raw = None

    def _wblock(self, b: int, data: bytes):
        k = self.bsize // self.ssize
        data = data.ljust(self.bsize, b"\0")
        for i in range(k):
            self._wlsector(b * k + i, data[i * self.ssize:(i + 1) * self.ssize])

    def _dir(self) -> bytearray:
        return bytearray(self._blocks(range(0, self.ndir * 32 // self.bsize)))

    def _wdir(self, raw: bytearray):
        for b in range(self.ndir * 32 // self.bsize):
            self._wblock(b, bytes(raw[b * self.bsize:(b + 1) * self.bsize]))

    @staticmethod
    def _name11(name: str) -> bytes:
        base, _, ext = name.upper().rpartition(".") if "." in name else (name.upper(), "", "")
        ok = lambda t: "".join(c if c.isascii() and c.isalnum() or c in "-_$#!&" else "_" for c in t)
        return (ok(base)[:8] or "FICHIER").ljust(8).encode() + ok(ext)[:3].ljust(3).encode()

    def add_file(self, parent: Entry, name: str, data: bytes) -> str:
        raw = self._dir()
        n11 = self._name11(name)
        used = set(range(self.ndir * 32 // self.bsize))
        for i in range(0, len(raw), 32):
            e = raw[i:i + 32]
            if e[0] <= 15:
                if bytes(c & 0x7F for c in e[1:12]) == n11 and e[0] == 0:
                    raise FSError(f"{name} existe déjà")
                used.update(b for b in e[16:32] if b)
        free = [b for b in range(self.nblocks) if b not in used]
        nb = max(1, -(-len(data) // self.bsize))
        if nb > len(free):
            raise FSError(f"Espace insuffisant : {nb} Ko requis, {len(free)} Ko libres")
        blocks = free[:nb]
        per = 16384 // self.bsize
        next_ = max(1, -(-len(data) // 16384))
        slots = [i for i in range(0, len(raw), 32) if raw[i] == 0xE5]
        if len(slots) < next_:
            raise FSError("Répertoire plein")
        for b_i, b in enumerate(blocks):
            self._wblock(b, data[b_i * self.bsize:(b_i + 1) * self.bsize])
        for x in range(next_):
            chunk = data[x * 16384:(x + 1) * 16384]
            ent = bytearray(32)
            ent[0] = 0
            ent[1:12] = n11
            ent[12], ent[14] = x % 32, x // 32
            ent[15] = min(128, -(-len(chunk) // 128))
            bl = blocks[x * per:(x + 1) * per]
            ent[16:16 + len(bl)] = bytes(bl)
            raw[slots[x]:slots[x] + 32] = ent
        self._wdir(raw)
        self.refresh()
        return n11[:8].decode().rstrip() + "." + n11[8:].decode().rstrip()

    def delete(self, e: Entry):
        raw = self._dir()
        user = e.meta.get("utilisateur", 0)
        nm = e.name.split("-", 1)[1] if user and "-" in e.name else e.name
        n11 = self._name11(nm)
        for i in range(0, len(raw), 32):
            if raw[i] == user and bytes(c & 0x7F for c in raw[i + 1:i + 12]) == n11:
                raw[i] = 0xE5
        self._wdir(raw)
        self.refresh()

    def refresh(self):
        self.__init__(self.disk, self.first)

    def save(self, path: str):
        from .disk import write_edsk
        write_edsk(self.disk, path)

    def read(self, e: Entry) -> bytes:
        return self._blocks(e.ref["blocks"])[:max(e.size, 0) + 128 if self._has_hdr(e) else e.size]

    @staticmethod
    def _has_hdr(e: Entry) -> bool:
        return e.meta.get("en-tête AMSDOS") == "oui"

    def content(self, e: Entry) -> bytes:
        d = self._blocks(e.ref["blocks"])
        h = amsdos_header(d)
        if h:
            n = h["real"] or h["length"]
            return d[128:128 + n]
        # fichier ASCII : couper au ^Z
        cut = d.find(b"\x1a")
        return d[:cut] if cut >= 0 else d[:e.size]


def probe(disk) -> List[FileSystem]:
    t0 = disk.track(0, 0)
    if not t0 or any(s.n != 2 for s in t0):
        return []
    first = min(s.r for s in t0)
    if first not in LAYOUTS or len(t0) < 8 or len(t0) > 10:
        return []
    if first == 0x01 and disk.kind not in ("edsk", "dsk"):
        return []
    try:
        fs = CPMFS(disk, first)
        return [fs]
    except Exception:
        return []
