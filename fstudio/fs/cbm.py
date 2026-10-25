"""Commodore 1541 / 1571 / 1581 (D64, D71, D81)."""
from __future__ import annotations

from typing import List, Optional, Tuple

from .base import Entry, FileSystem, FSError, mark_bad, u16

TYPES = {0: "DEL", 1: "SEQ", 2: "PRG", 3: "USR", 4: "REL", 5: "CBM"}


def petscii_to_str(b: bytes) -> str:
    out = []
    for c in b:
        if c == 0xA0:
            continue
        if 0x20 <= c <= 0x5F:
            out.append(chr(c))
        elif 0xC1 <= c <= 0xDA:
            out.append(chr(c - 0x80))
        elif 0x61 <= c <= 0x7A:
            out.append(chr(c - 0x20))
        else:
            out.append("·")
    return "".join(out).rstrip()


def _spt_1541(t: int) -> int:
    t = (t - 1) % 35 + 1 if t > 35 else t
    return 21 if t <= 17 else 19 if t <= 24 else 18 if t <= 30 else 17


class CBMFS(FileSystem):
    platform = "c64"
    charset = "petscii"

    def __init__(self, data: bytes, model: str):
        super().__init__()
        self._model = model
        self.d, self.model = data, model
        self.name = f"Commodore {model}"
        if model == "1581":
            self.offsets = {t: (t - 1) * 40 * 256 for t in range(1, 81)}
            self.spt = {t: 40 for t in range(1, 81)}
            hdr, dir_ts = self.sec(40, 0), (40, 3)
            self.label = petscii_to_str(hdr[4:20])
            disk_id = petscii_to_str(hdr[22:24])
        else:
            ntracks = 70 if model == "1571" else (40 if len(data) >= 196608 else 35)
            self.offsets, self.spt, off = {}, {}, 0
            for t in range(1, ntracks + 1):
                n = _spt_1541(t) if t <= 35 or model != "1571" else _spt_1541(t - 35)
                if t > 35 and model != "1571":
                    n = 17
                self.offsets[t], self.spt[t] = off, n
                off += n * 256
            bam = self.sec(18, 0)
            dir_ts = (bam[0] or 18, bam[1] or 1)
            self.label = petscii_to_str(bam[0x90:0xA0])
            disk_id = petscii_to_str(bam[0xA2:0xA4])
        self._parse(dir_ts)
        free = self._free()
        self.info = [("Système", f"CBM DOS {model}"), ("Nom", self.label), ("ID", disk_id),
                     ("Blocs libres", str(free) if free is not None else "—"),
                     ("Fichiers", str(len(self.files)))]

    def sec(self, t: int, s: int) -> bytes:
        if t not in self.offsets or s >= self.spt[t]:
            return b"\0" * 256
        o = self.offsets[t] + s * 256
        return self.d[o:o + 256].ljust(256, b"\0")

    def _free(self) -> Optional[int]:
        try:
            if self.model == "1581":
                n = 0
                for s in (1, 2):
                    b = self.sec(40, s)
                    for i in range(40):
                        if (s - 1) * 40 + i + 1 != 40:
                            n += b[0x10 + i * 6]
                return n
            b = self.sec(18, 0)
            return sum(b[4 + (t - 1) * 4] for t in range(1, 36) if t != 18)
        except Exception:
            return None

    def _parse(self, ts: Tuple[int, int]):
        seen = set()
        t, s = ts
        while t and (t, s) not in seen and len(seen) < 300:
            seen.add((t, s))
            b = self.sec(t, s)
            for i in range(8):
                e = b[i * 32:(i + 1) * 32]
                ft = e[2]
                if ft == 0:
                    continue
                kind = TYPES.get(ft & 7, "?")
                name = petscii_to_str(e[5:21])
                blocks = u16(e, 30)
                attrs = ("" if ft & 0x80 else "*") + ("<" if ft & 0x40 else "")
                slot = (t, s, i)
                ent = Entry(f"{name}.{kind.lower()}" if kind != "?" else name,
                            blocks * 254, False, kind, "", attrs,
                            {"blocs": blocks, "piste/secteur": f"{e[3]}/{e[4]}",
                             "nom CBM": name, "type": kind}, (e[3], e[4]))
                ent.slot = slot
                self.root.add(ent)
            t, s = b[0], b[1]
        for e in self.root.children:
            try:
                e.size = len(self.read(e))
            except Exception:
                pass

    def _bam_free(self, t: int, s: int) -> Optional[bool]:
        try:
            if self.model == "1581":
                b = self.sec(40, 1 if t <= 40 else 2)
                o = 0x10 + ((t - 1) % 40) * 6 + 1
                return bool(b[o + s // 8] >> (s % 8) & 1)
            if t > 35:
                return None
            b = self.sec(18, 0)
            o = 4 + (t - 1) * 4 + 1
            return bool(b[o + s // 8] >> (s % 8) & 1)
        except Exception:
            return None

    def _chain_ts(self, t, s):
        seen = []
        while t and (t, s) not in seen and len(seen) < 4000 and t in self.offsets:
            seen.append((t, s))
            b = self.sec(t, s)
            t, s = b[0], b[1]
        return seen

    def allocation(self):
        order = [(t, s) for t in sorted(self.offsets) for s in range(self.spt[t])]
        idx = {ts: i for i, ts in enumerate(order)}
        own = []
        dir_t = 40 if self.model == "1581" else 18
        for t, s in order:
            if t == dir_t:
                own.append("sys")
                continue
            f = self._bam_free(t, s)
            own.append("free" if f else "used" if f is not None else "used")
        for e in self.files:
            for ts in self._chain_ts(*e.ref):
                if ts in idx:
                    own[idx[ts]] = e
        mark_bad(own, 256, self.d)
        return 256, own

    def deleted(self) -> List[Entry]:
        out = []
        t, s = (40, 3) if self.model == "1581" else (self.sec(18, 0)[0] or 18, self.sec(18, 0)[1] or 1)
        seen = set()
        while t and (t, s) not in seen and len(seen) < 300:
            seen.add((t, s))
            b = self.sec(t, s)
            for i in range(8):
                e = b[i * 32:(i + 1) * 32]
                if e[2] != 0 or not e[3] or not e[5:21].strip(b"\xa0\0 "):
                    continue
                name = petscii_to_str(e[5:21])
                ent = Entry(name + ".del", 0, False, "Supprimé (scratch) — chaîne de secteurs",
                            "", "", {"piste/secteur": f"{e[3]}/{e[4]}", "nom CBM": name}, (e[3], e[4]))
                ent.deleted = True
                try:
                    ent.size = len(self.read(ent))
                except Exception:
                    pass
                out.append(ent)
            t, s = b[0], b[1]
        return out

    def read(self, e: Entry) -> bytes:
        t, s = e.ref
        out, seen = bytearray(), set()
        while t and (t, s) not in seen and len(seen) < 4000:
            seen.add((t, s))
            b = self.sec(t, s)
            if b[0] == 0:
                out += b[2:max(b[1] + 1, 2)]
                break
            out += b[2:]
            t, s = b[0], b[1]
        return bytes(out)


def probe(disk) -> List[FileSystem]:
    d = disk.linear()
    n = len(d)
    models = []
    if disk.kind == ".d81" or n in (819200, 822400):
        models.append("1581")
    if disk.kind == ".d71" or n in (349696, 351062):
        models.append("1571")
    if disk.kind == ".d64" or n in (174848, 175531, 196608, 197376):
        models.append("1541")
    out = []
    for m in models:
        try:
            if m == "1581":
                o = 39 * 40 * 256
                if d[o + 2] != 0x44:
                    continue
            elif d[0x16500 + 2] not in (0x41, 0x44, 0x00) and disk.kind not in (".d64", ".d71"):
                continue
            fs = CBMFS(d, m)
            if fs.files or disk.kind in (".d64", ".d71", ".d81") or m == "1581":
                out.append(fs)
                break
        except Exception:
            continue
    return out


# ----------------------------------------------------------------------------
# Écriture (1541 35/40 pistes, 1581)
# ----------------------------------------------------------------------------
def _ascii_to_petscii(name: str) -> bytes:
    out = bytearray()
    for ch in name.upper()[:16]:
        c = ord(ch)
        out.append(c if 0x20 <= c <= 0x5F else 0x2E)
    return bytes(out).ljust(16, b"\xA0")


class _CBMWriter:
    def __init__(self, fs: "CBMFS"):
        self.fs = fs
        if not isinstance(fs.d, bytearray):
            fs.d = bytearray(fs.d)
        self.d = fs.d
        self.m81 = fs.model == "1581"
        self.dir_t = 40 if self.m81 else 18

    def off(self, t, s):
        return self.fs.offsets[t] + s * 256

    def get(self, t, s) -> bytearray:
        o = self.off(t, s)
        return bytearray(self.d[o:o + 256])

    def put(self, t, s, b):
        o = self.off(t, s)
        self.d[o:o + 256] = bytes(b)

    def _bam_loc(self, t):
        if self.m81:
            return (40, 1 if t <= 40 else 2), 0x10 + ((t - 1) % 40) * 6
        return (18, 0), 4 + (t - 1) * 4

    def is_free(self, t, s) -> bool:
        (bt, bs), o = self._bam_loc(t)
        b = self.get(bt, bs)
        return bool(b[o + 1 + s // 8] >> (s % 8) & 1)

    def set_free(self, t, s, free: bool):
        (bt, bs), o = self._bam_loc(t)
        b = self.get(bt, bs)
        cur = bool(b[o + 1 + s // 8] >> (s % 8) & 1)
        if cur == free:
            return
        if free:
            b[o + 1 + s // 8] |= 1 << (s % 8)
            b[o] += 1
        else:
            b[o + 1 + s // 8] &= ~(1 << (s % 8)) & 0xFF
            b[o] -= 1
        self.put(bt, bs, b)

    def tracks_order(self):
        n = max(self.fs.offsets)
        if not self.m81:
            n = min(n, 35)
        order = []
        for k in range(1, n):
            for t in (self.dir_t - k, self.dir_t + k):
                if 1 <= t <= n and t != self.dir_t:
                    order.append(t)
        return order

    def alloc(self, n):
        out, inter = [], 1 if self.m81 else 10
        for t in self.tracks_order():
            spt = self.fs.spt[t]
            s = 0
            tried = 0
            while len(out) < n and tried < spt:
                cand = [x for x in range(spt) if self.is_free(t, x)]
                if not cand:
                    break
                s = min(cand, key=lambda x: (x - s) % spt)
                self.set_free(t, s, False)
                out.append((t, s))
                s = (s + inter) % spt
                tried += 1
            if len(out) >= n:
                return out
        for ts in out:
            self.set_free(*ts, True)
        raise FSError(f"Espace insuffisant : {n} blocs requis")

    def dir_slot(self):
        t, s = (40, 3) if self.m81 else (18, 1)
        seen = set()
        while (t, s) not in seen:
            seen.add((t, s))
            b = self.get(t, s)
            for i in range(8):
                if b[i * 32 + 2] == 0:
                    return t, s, i
            if b[0] == 0:
                break
            t, s = b[0], b[1]
        # nouveau secteur de répertoire sur la piste du répertoire
        spt = self.fs.spt[self.dir_t]
        free = [x for x in range(spt) if self.is_free(self.dir_t, x)]
        if not free:
            raise FSError("Répertoire plein")
        ns = min(free, key=lambda x: (x - s - 3) % spt)
        self.set_free(self.dir_t, ns, False)
        b = self.get(t, s)
        b[0], b[1] = self.dir_t, ns
        self.put(t, s, b)
        nb = bytearray(256)
        nb[1] = 0xFF
        self.put(self.dir_t, ns, nb)
        return self.dir_t, ns, 0

    def add(self, name: str, data: bytes) -> str:
        base, _, ext = name.rpartition(".") if "." in name else (name, "", "")
        ftype = {"seq": 0x81, "usr": 0x83, "prg": 0x82, "txt": 0x81}.get(ext.lower(), 0x82)
        pname = _ascii_to_petscii(base)
        for e in self.fs.files:
            if _ascii_to_petscii(e.meta.get("nom CBM", "")) == pname:
                raise FSError(f"{base.upper()} existe déjà")
        n = max(1, -(-len(data) // 254))
        secs = self.alloc(n)
        for i, (t, s) in enumerate(secs):
            chunk = data[i * 254:(i + 1) * 254]
            b = bytearray(256)
            if i + 1 < n:
                b[0], b[1] = secs[i + 1]
            else:
                b[0], b[1] = 0, len(chunk) + 1
            b[2:2 + len(chunk)] = chunk
            self.put(t, s, b)
        t, s, i = self.dir_slot()
        b = self.get(t, s)
        e = bytearray(30)
        e[0] = ftype
        e[1], e[2] = secs[0]
        e[3:19] = pname
        e[28:30] = n.to_bytes(2, "little")
        b[i * 32 + 2:i * 32 + 32] = e
        self.put(t, s, b)
        return pname.rstrip(b"\xA0").decode("ascii")

    def remove(self, e: Entry):
        for ts in self.fs._chain_ts(*e.ref):
            self.set_free(*ts, True)
        t, s, i = e.slot
        b = self.get(t, s)
        b[i * 32 + 2] = 0
        self.put(t, s, b)


def _c_add(self, parent: Entry, name: str, data: bytes) -> str:
    nm = _CBMWriter(self).add(name, data)
    self.refresh()
    return nm


def _c_delete(self, e: Entry):
    _CBMWriter(self).remove(e)
    self.refresh()


def _c_refresh(self):
    self.__init__(bytes(self.d), self._model)


def _c_save(self, path: str):
    with open(path, "wb") as f:
        f.write(bytes(self.d))


CBMFS.writable = property(lambda self: self.model in ("1541", "1581"))
CBMFS.save_ext = property(lambda self: ".d81" if self.model == "1581" else ".d64")
CBMFS.add_file = _c_add
CBMFS.delete = _c_delete
CBMFS.refresh = _c_refresh
CBMFS.save = _c_save
