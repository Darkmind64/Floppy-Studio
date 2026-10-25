"""Macintosh : MFS (400 Ko) et HFS (800 Ko, 1,44 Mo) — lecture."""
from __future__ import annotations

import struct
import time
from typing import Dict, List, Optional

from .base import Entry, FileSystem, human

MAC_EPOCH = 2082844800          # 1904-01-01 → 1970-01-01


def _date(v: int) -> str:
    if not v:
        return ""
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.gmtime(v - MAC_EPOCH))
    except (OverflowError, OSError, ValueError):
        return ""


def _pstr(b: bytes, o: int, maxlen: int = 255) -> str:
    n = min(b[o], maxlen)
    return b[o + 1:o + 1 + n].decode("mac_roman", "replace").replace("/", ":")


def _code(b: bytes) -> str:
    return b.decode("mac_roman", "replace") if any(b) else "    "


KINDS = {"TEXT": "Texte", "APPL": "Application", "PICT": "Image PICT", "PNTG": "Image MacPaint",
         "ttro": "Texte (lecture seule)", "INIT": "Extension", "cdev": "Tableau de bord", "ZSYS": "Système",
         "FNDR": "Finder", "dfil": "Accessoire", "FFIL": "Police", "tfil": "Police TrueType",
         "rsrc": "Ressources", "MPS ": "Fichier MPW", "MWII": "MacWrite II", "WORD": "MacWrite"}


class _MacBase(FileSystem):
    platform = "mac"
    charset = "mac_roman"

    def _fork_entry(self, parent: Entry, name: str, ftype: bytes, creator: bytes, dlen: int, rlen: int,
                    dref, rref, crd: int, mdd: int, locked: bool):
        t, c = _code(ftype), _code(creator)
        meta = {"type": t, "créateur": c, "créé le": _date(crd), "fourche données": dlen,
                "fourche ressources": rlen}
        kind = KINDS.get(t, f"{t} / {c}")
        e = Entry(name, dlen, False, kind, _date(mdd), "L" if locked else "", meta, dref)
        parent.add(e)
        if rlen:
            r = Entry(name + " [ressources]", rlen, False, "Fourche de ressources", _date(mdd), "",
                      dict(meta), rref)
            parent.add(r)


# --------------------------------------------------------------------------
# MFS
# --------------------------------------------------------------------------
class MFS(_MacBase):
    def __init__(self, d: bytes):
        super().__init__()
        self.d = d
        m = d[1024:1024 + 512]
        (sig, crd, _lsb, _atr, nfiles, dirst, dirlen, nblks, blksiz, _clp, albst, _nxt,
         free) = struct.unpack_from(">HIIHHHHHIIHIH", m, 0)
        self.blksiz, self.albst, self.nblks = blksiz, albst, nblks
        self.label = _pstr(m, 36, 27)
        self.name = "Macintosh MFS"
        mp = d[1024 + 64:1024 + 64 + (nblks * 12 + 7) // 8 + 2]
        self.map = [0, 0] + [self._map12(mp, i) for i in range(nblks)]
        o = dirst * 512
        end = o + dirlen * 512
        while o < end:
            flags = d[o]
            if flags == 0:
                o = (o // 512 + 1) * 512
                continue
            ftype, creator = d[o + 2:o + 6], d[o + 6:o + 10]
            fnum, stb, dlen, _dpy, rstb, rlen, _rpy, fcr, fmd = struct.unpack_from(">IHIIHIIII", d, o + 18)
            name = _pstr(d, o + 50)
            if flags & 0x80:
                self._fork_entry(self.root, name, ftype, creator, dlen, rlen, (stb, dlen), (rstb, rlen),
                                 fcr, fmd, bool(flags & 1))
            o += 51 + d[o + 50]
            o += o & 1
        self.info = [("Système", self.name), ("Volume", self.label or "—"),
                     ("Créé le", _date(crd)), ("Blocs", f"{nblks} × {blksiz} o"),
                     ("Libre", human(free * blksiz)), ("Fichiers", str(nfiles))]
        self.info = [(k, v) for k, v in self.info if v]

    @staticmethod
    def _map12(mp: bytes, i: int) -> int:
        o = i * 12 // 8
        v = mp[o] << 8 | mp[o + 1]
        return (v >> 4) if i % 2 == 0 else (v & 0xFFF)

    def read(self, e: Entry) -> bytes:
        blk, size = e.ref
        out, seen = bytearray(), set()
        while 2 <= blk < len(self.map) and blk not in seen and len(out) < size:
            seen.add(blk)
            o = self.albst * 512 + (blk - 2) * self.blksiz
            out += self.d[o:o + self.blksiz]
            blk = self.map[blk]
        return bytes(out[:size])


# --------------------------------------------------------------------------
# HFS
# --------------------------------------------------------------------------
class HFS(_MacBase):
    def __init__(self, d: bytes):
        super().__init__()
        self.d = d
        m = d[1024:1024 + 512]
        crd, lsm = struct.unpack_from(">II", m, 2)
        nfiles = struct.unpack_from(">H", m, 12)[0]
        self.nblks, self.blksiz = struct.unpack_from(">HI", m, 18)
        self.albst = struct.unpack_from(">H", m, 28)[0]
        free = struct.unpack_from(">H", m, 34)[0]
        self.label = _pstr(m, 36, 27)
        self.name = "Macintosh HFS"
        ct_ext = [struct.unpack_from(">HH", m, 150 + i * 4) for i in range(3)]
        cat = b"".join(self._extent(s, n) for s, n in ct_ext if n)
        dirs: Dict[int, Entry] = {}
        pending = []
        for key, rec in self._leaves(cat):
            parid = struct.unpack_from(">I", key, 2)[0]
            name = _pstr(key, 6, 31)
            t = rec[0]
            if t == 1:
                did = struct.unpack_from(">I", rec, 6)[0]
                crd2, mdd = struct.unpack_from(">II", rec, 10)
                e = Entry(name, 0, True, "Dossier", _date(mdd), "", {"id": did})
                dirs[did] = e
                pending.append((parid, e))
            elif t == 2:
                flags = rec[2]
                ftype, creator = rec[4:8], rec[8:12]
                dlen = struct.unpack_from(">I", rec, 26)[0]
                rlen = struct.unpack_from(">I", rec, 36)[0]
                fcr, fmd = struct.unpack_from(">II", rec, 44)
                dext = [struct.unpack_from(">HH", rec, 74 + i * 4) for i in range(3)]
                rext = [struct.unpack_from(">HH", rec, 86 + i * 4) for i in range(3)]
                pending.append((parid, (name, ftype, creator, dlen, rlen, (dext, dlen), (rext, rlen), fcr, fmd,
                                        bool(flags & 1))))
        root_id = 2
        if root_id in dirs:
            self.root.meta = dirs[root_id].meta
        for parid, item in pending:
            if isinstance(item, Entry):
                if item.meta.get("id") == root_id:
                    continue
                (self.root if parid == root_id else dirs.get(parid, self.root)).add(item)
        for parid, item in pending:
            if not isinstance(item, Entry):
                parent = self.root if parid == root_id else dirs.get(parid, self.root)
                self._fork_entry(parent, *item)
        self.info = [("Système", self.name), ("Volume", self.label or "—"), ("Créé le", _date(crd)),
                     ("Modifié le", _date(lsm)), ("Blocs", f"{self.nblks} × {self.blksiz} o"),
                     ("Libre", human(free * self.blksiz)), ("Fichiers (racine)", str(nfiles))]
        self.info = [(k, v) for k, v in self.info if v]

    def _extent(self, start: int, count: int) -> bytes:
        o = self.albst * 512 + start * self.blksiz
        return self.d[o:o + count * self.blksiz]

    def _leaves(self, cat: bytes):
        if len(cat) < 512:
            return
        hdr = cat[14:14 + 106]
        _depth, _root, _nrec, first, _last, nsize = struct.unpack_from(">HIIIIH", hdr, 0)
        nsize = nsize or 512
        n, seen = first, set()
        while n and n not in seen and (n + 1) * nsize <= len(cat):
            seen.add(n)
            node = cat[n * nsize:(n + 1) * nsize]
            flink = struct.unpack_from(">I", node, 0)[0]
            ntype, _h, nrec = struct.unpack_from(">bBH", node, 8)
            if ntype != -1:
                break
            offs = [struct.unpack_from(">H", node, nsize - 2 * (i + 1))[0] for i in range(nrec + 1)]
            for i in range(nrec):
                o = offs[i]
                klen = node[o]
                if klen == 0:
                    continue
                key = node[o:o + 1 + klen]
                ro = o + 1 + klen
                ro += ro & 1
                yield key, node[ro:offs[i + 1] if offs[i + 1] > ro else nsize]
            n = flink

    def read(self, e: Entry) -> bytes:
        exts, size = e.ref
        out = b"".join(self._extent(s, c) for s, c in exts if c)
        return out[:size]


def probe(disk) -> List[FileSystem]:
    d = disk.linear()
    if len(d) < 2048:
        return []
    sig = d[1024:1026]
    fs: Optional[FileSystem] = None
    try:
        if sig == b"BD":
            fs = HFS(d)
        elif sig == b"\xd2\xd7":
            fs = MFS(d)
    except Exception:
        fs = None
    return [fs] if fs is not None else []
