"""AmigaDOS OFS / FFS (ADF DD et HD)."""
from __future__ import annotations

import datetime
import struct
import time
from typing import List

from .base import Entry, FileSystem, FSError, b32, human, mark_bad

BS = 512
T_SHORT, ST_ROOT, ST_DIR, ST_FILE = 2, 1, 2, 0xFFFFFFFD


def _date(days, mins, ticks) -> str:
    try:
        d = datetime.datetime(1978, 1, 1) + datetime.timedelta(days=days, minutes=mins,
                                                                seconds=ticks / 50)
        return d.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


def _prot(p: int) -> str:
    # bits 0-3 actifs à 0 (d e w r), 4-7 actifs à 1 (a p s h)
    s = "".join(ch for bit, ch in ((7, "h"), (6, "s"), (5, "p"), (4, "a")) if p >> bit & 1)
    s += "".join(ch if not p >> bit & 1 else "-" for bit, ch in ((3, "r"), (2, "w"), (1, "e"), (0, "d")))
    return s


class AmigaFS(FileSystem):
    platform = "amiga"
    charset = "latin-1"

    def __init__(self, data: bytes):
        super().__init__()
        self.d = data
        self.nblocks = len(data) // BS
        flags = data[3]
        self.ffs = bool(flags & 1)
        self.name = "AmigaDOS " + ("FFS" if self.ffs else "OFS") + (" intl" if flags & 2 else "") \
                    + (" dircache" if flags & 4 else "")
        self.rootblk = self.nblocks // 2
        r = self.blk(self.rootblk)
        if b32(r, 0) != T_SHORT or b32(r, BS - 4) != ST_ROOT:
            raise ValueError("pas de bloc racine")
        self.label = self._name(r)
        self.root.date = _date(b32(r, 420), b32(r, 424), b32(r, 428))
        self._seen = set()
        self._dir(r, self.root, 0)
        nfiles = len(self.files)
        self.info = [("Système", self.name), ("Volume", self.label), ("Blocs", str(self.nblocks)),
                     ("Bloc racine", str(self.rootblk)), ("Fichiers", str(nfiles)),
                     ("Bootable", "oui" if any(data[12:1024].strip(b"\0")) else "non")]

    def blk(self, n: int) -> bytes:
        return self.d[n * BS:(n + 1) * BS]

    @staticmethod
    def _name(b: bytes) -> str:
        n = min(b[432], 30)
        return b[433:433 + n].decode("latin-1", "replace")

    def _dir(self, hdr: bytes, parent: Entry, depth: int):
        for i in range(72):
            key = b32(hdr, 24 + i * 4)
            guard = 0
            while key and key < self.nblocks and key not in self._seen and guard < 1000:
                guard += 1
                self._seen.add(key)
                b = self.blk(key)
                st = b32(b, BS - 4)
                name = self._name(b)
                date = _date(b32(b, 420), b32(b, 424), b32(b, 428))
                clen = min(b[328], 79)
                comment = b[329:329 + clen].decode("latin-1", "replace")
                meta = {"bloc": key}
                if comment:
                    meta["commentaire"] = comment
                if st == ST_DIR and depth < 32:
                    e = parent.add(Entry(name, 0, True, "Dossier", date, "", meta, key))
                    self._dir(b, e, depth + 1)
                elif st == ST_FILE:
                    size = b32(b, 324)
                    parent.add(Entry(name, size, False, "", date, _prot(b32(b, 320)), meta, key))
                key = b32(b, 496)

    def read(self, e: Entry) -> bytes:
        hdr = self.blk(e.ref)
        size = e.size
        out = bytearray()
        if not self.ffs:
            key, guard = b32(hdr, 16), 0
            while key and key < self.nblocks and len(out) < size and guard < 4000:
                guard += 1
                b = self.blk(key)
                n = min(b32(b, 12), 488)
                out += b[24:24 + n]
                key = b32(b, 16)
            return bytes(out[:size])
        h, guard = hdr, 0
        while h is not None and len(out) < size and guard < 200:
            guard += 1
            cnt = b32(h, 8)
            for i in range(min(cnt, 72)):
                key = b32(h, 24 + (71 - i) * 4)
                if not key or key >= self.nblocks:
                    break
                out += self.blk(key)
            ext = b32(h, BS - 8)
            h = self.blk(ext) if ext and ext < self.nblocks else None
        return bytes(out[:size])


def _amiga_blocks(fs: "AmigaFS", e: Entry) -> List[int]:
    out = [e.ref]
    if e.is_dir:
        return out
    h, guard = fs.blk(e.ref), 0
    while h is not None and guard < 200:
        guard += 1
        cnt = b32(h, 8)
        for i in range(min(cnt, 72)):
            key = b32(h, 24 + (71 - i) * 4)
            if key and key < fs.nblocks:
                out.append(key)
        ext = b32(h, BS - 8)
        if ext and ext < fs.nblocks:
            out.append(ext)
            h = fs.blk(ext)
        else:
            h = None
    return out


def _allocation(self):
    own = ["used"] * self.nblocks
    own[0] = own[1] = "sys"
    r = self.blk(self.rootblk)
    bm_ok = b32(r, 312) != 0
    for i in range(25):
        bmk = b32(r, 316 + i * 4)
        if not bmk or bmk >= self.nblocks:
            continue
        own[bmk] = "sys"
        bm = self.blk(bmk)
        for k in range(127 * 32):
            blk = 2 + i * 127 * 32 + k
            if blk >= self.nblocks:
                break
            if bm_ok and b32(bm, 4 + (k // 32) * 4) >> (k % 32) & 1:
                if own[blk] == "used":
                    own[blk] = "free"
    own[self.rootblk] = "sys"
    for e in self.root.walk():
        for b in _amiga_blocks(self, e):
            own[b] = e
    mark_bad(own, BS, self.d)
    return BS, own


def _deleted(self) -> List[Entry]:
    out = []
    for key in range(2, self.nblocks):
        if key in self._seen or key == self.rootblk:
            continue
        b = self.blk(key)
        if b32(b, 0) != T_SHORT or b32(b, BS - 4) != ST_FILE or b32(b, 4) != key:
            continue
        if sum(int.from_bytes(b[i:i + 4], "big") for i in range(0, BS, 4)) & 0xFFFFFFFF:
            continue
        e = Entry(self._name(b), b32(b, 324), False, "Supprimé — en-tête retrouvé", _date(b32(b, 420),
                  b32(b, 424), b32(b, 428)), "", {"bloc": key}, key)
        e.deleted = True
        out.append(e)
    return out


AmigaFS.allocation = _allocation
AmigaFS.deleted = _deleted

# ----------------------------------------------------------------------------
# Écriture
# ----------------------------------------------------------------------------
T_LIST, T_DATA = 16, 8


def _hash(name: str) -> int:
    h = len(name)
    for ch in name.upper():
        h = (h * 13 + ord(ch)) & 0x7FF
    return h % 72


def _csum(blk: bytearray, off: int = 20):
    struct.pack_into(">I", blk, off, 0)
    s_ = sum(struct.unpack(">128I", bytes(blk))) & 0xFFFFFFFF
    struct.pack_into(">I", blk, off, (-s_) & 0xFFFFFFFF)


def _now():
    t = time.time() - 252460800 + (time.localtime().tm_gmtoff if hasattr(time.localtime(), "tm_gmtoff") else 0)
    days = int(t // 86400)
    rem = t - days * 86400
    return days, int(rem // 60), int((rem % 60) * 50)


class _AmigaWriter:
    def __init__(self, fs: "AmigaFS"):
        self.fs = fs
        self.d = fs.d if isinstance(fs.d, bytearray) else bytearray(fs.d)
        fs.d = self.d
        r = self._blk(fs.rootblk)
        self.bm = [b32(r, 316 + 4 * i) for i in range(25) if b32(r, 316 + 4 * i)]

    def _blk(self, n) -> bytearray:
        return bytearray(self.d[n * BS:(n + 1) * BS])

    def _put(self, n, blk):
        self.d[n * BS:(n + 1) * BS] = blk

    def _bit(self, blk: int):
        k = blk - 2
        page, k = divmod(k, 127 * 32)
        return self.bm[page], 4 + (k // 32) * 4, k % 32

    def is_free(self, blk: int) -> bool:
        bmb, off, bit = self._bit(blk)
        return bool(b32(self.d, bmb * BS + off) >> bit & 1)

    def set_free(self, blk: int, free: bool):
        bmb, off, bit = self._bit(blk)
        o = bmb * BS + off
        v = b32(self.d, o)
        v = v | (1 << bit) if free else v & ~(1 << bit)
        struct.pack_into(">I", self.d, o, v & 0xFFFFFFFF)
        b = self._blk(bmb)
        _csum(b, 0)
        self._put(bmb, b)

    def alloc(self, n: int) -> list:
        root = self.fs.rootblk
        order = list(range(root + 1, self.fs.nblocks)) + list(range(2, root))
        out = [b for b in order if self.is_free(b)][:n]
        if len(out) < n:
            raise FSError(f"Espace insuffisant : {n} blocs requis")
        for b in out:
            self.set_free(b, False)
        return out

    def _touch_root(self):
        r = self._blk(self.fs.rootblk)
        struct.pack_into(">III", r, 472, *_now())
        _csum(r)
        self._put(self.fs.rootblk, r)

    def _link(self, parent_key: int, key: int, name: str):
        p = self._blk(parent_key)
        h = _hash(name)
        nb = self._blk(key)
        struct.pack_into(">I", nb, 496, b32(p, 24 + h * 4))
        _csum(nb)
        self._put(key, nb)
        struct.pack_into(">I", p, 24 + h * 4, key)
        struct.pack_into(">III", p, 420, *_now())
        _csum(p)
        self._put(parent_key, p)

    def _unlink(self, parent_key: int, key: int, name: str):
        p = self._blk(parent_key)
        h = _hash(name)
        cur = b32(p, 24 + h * 4)
        nxt = b32(self._blk(key), 496)
        if cur == key:
            struct.pack_into(">I", p, 24 + h * 4, nxt)
            _csum(p)
            self._put(parent_key, p)
            return
        guard = 0
        while cur and guard < 1000:
            guard += 1
            b = self._blk(cur)
            if b32(b, 496) == key:
                struct.pack_into(">I", b, 496, nxt)
                _csum(b)
                self._put(cur, b)
                return
            cur = b32(b, 496)

    def exists(self, parent_key: int, name: str) -> bool:
        p = self._blk(parent_key)
        cur, guard = b32(p, 24 + _hash(name) * 4), 0
        while cur and guard < 1000:
            guard += 1
            b = self._blk(cur)
            if AmigaFS._name(b).upper() == name.upper():
                return True
            cur = b32(b, 496)
        return False

    @staticmethod
    def _header(key, parent, name, sec_type) -> bytearray:
        b = bytearray(BS)
        struct.pack_into(">II", b, 0, T_SHORT, key)
        nm = name.encode("latin-1", "replace")[:30]
        b[432] = len(nm)
        b[433:433 + len(nm)] = nm
        struct.pack_into(">III", b, 420, *_now())
        struct.pack_into(">I", b, 500, parent)
        struct.pack_into(">I", b, BS - 4, sec_type & 0xFFFFFFFF)
        return b

    def add(self, parent_key: int, name: str, data: bytes, is_dir=False) -> str:
        name = "".join(c for c in name if c not in ":/")[:30] or "fichier"
        if self.exists(parent_key, name):
            raise FSError(f"{name} existe déjà")
        if is_dir:
            key = self.alloc(1)[0]
            b = self._header(key, parent_key, name, ST_DIR)
            _csum(b)
            self._put(key, b)
            self._link(parent_key, key, name)
            self._touch_root()
            return name
        pay = BS if self.fs.ffs else BS - 24
        ndata = -(-len(data) // pay)
        next_ = max(0, -(-(ndata - 72) // 72))
        blocks = self.alloc(1 + next_ + ndata)
        key, exts, dblk = blocks[0], blocks[1:1 + next_], blocks[1 + next_:]
        # blocs de données
        for i, bk in enumerate(dblk):
            chunk = data[i * pay:(i + 1) * pay]
            if self.fs.ffs:
                self._put(bk, bytearray(chunk.ljust(BS, b"\0")))
            else:
                b = bytearray(BS)
                struct.pack_into(">IIIII", b, 0, T_DATA, key, i + 1, len(chunk),
                                 dblk[i + 1] if i + 1 < len(dblk) else 0)
                b[24:24 + len(chunk)] = chunk
                _csum(b)
                self._put(bk, b)
        # en-tête + extensions
        tables = [dblk[i:i + 72] for i in range(0, max(len(dblk), 1), 72)] or [[]]
        hdr = self._header(key, parent_key, name, ST_FILE)
        struct.pack_into(">I", hdr, 324, len(data))
        holders = [(key, hdr)] + [(k, bytearray(BS)) for k in exts]
        for idx, (k, b) in enumerate(holders):
            tbl = tables[idx] if idx < len(tables) else []
            if idx:
                struct.pack_into(">II", b, 0, T_LIST, k)
                struct.pack_into(">I", b, 500, key)
                struct.pack_into(">I", b, BS - 4, ST_FILE)
            struct.pack_into(">I", b, 8, len(tbl))
            if idx == 0:
                struct.pack_into(">I", b, 16, dblk[0] if dblk else 0)
            for i, bk in enumerate(tbl):
                struct.pack_into(">I", b, 24 + (71 - i) * 4, bk)
            struct.pack_into(">I", b, BS - 8, holders[idx + 1][0] if idx + 1 < len(holders) else 0)
            if idx:
                _csum(b)
                self._put(k, b)
        _csum(hdr)
        self._put(key, hdr)
        self._link(parent_key, key, name)
        self._touch_root()
        return name

    def remove(self, e: Entry):
        for c in list(e.children):
            self.remove(c)
        parent_key = e.parent.ref if e.parent is not None and e.parent.ref else self.fs.rootblk
        self._unlink(parent_key, e.ref, e.name)
        blocks = set(_amiga_blocks(self.fs, e))
        if not self.fs.ffs and not e.is_dir:
            key, guard = b32(self._blk(e.ref), 16), 0
            while key and key < self.fs.nblocks and guard < 4000:
                guard += 1
                blocks.add(key)
                key = b32(self._blk(key), 16)
        for b in blocks:
            if 2 <= b < self.fs.nblocks:
                self.set_free(b, True)
        self._touch_root()


def _a_add(self, parent: Entry, name: str, data: bytes) -> str:
    w = _AmigaWriter(self)
    nm = w.add(parent.ref if parent is not self.root and parent.ref else self.rootblk, name, data)
    self.refresh()
    return nm


def _a_mkdir(self, parent: Entry, name: str) -> str:
    w = _AmigaWriter(self)
    nm = w.add(parent.ref if parent is not self.root and parent.ref else self.rootblk, name, b"", True)
    self.refresh()
    return nm


def _a_delete(self, e: Entry):
    _AmigaWriter(self).remove(e)
    self.refresh()


def _a_refresh(self):
    self.__init__(bytes(self.d))


def _a_save(self, path: str):
    with open(path, "wb") as f:
        f.write(bytes(self.d))


AmigaFS.writable = True
AmigaFS.save_ext = ".adf"
AmigaFS.add_file = _a_add
AmigaFS.mkdir = _a_mkdir
AmigaFS.delete = _a_delete
AmigaFS.refresh = _a_refresh
AmigaFS.save = _a_save


def probe(disk) -> List[FileSystem]:
    d = disk.linear()
    if len(d) < 880 * 1024 // 2 or d[:3] != b"DOS" or d[3] > 7:
        return []
    try:
        return [AmigaFS(d)]
    except Exception:
        return []
