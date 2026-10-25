"""FAT12/FAT16 : PC, Atari ST, MSX, synthés et samplers au format DOS."""
from __future__ import annotations

from typing import List, Optional

import struct
import time

from .base import Entry, FileSystem, FSError, human, mark_bad, u16, u32
from .disk import is_bad

# Géométries DOS 1.x sans BPB (octet média en tête de FAT)
_NO_BPB = {
    # taille : (sect/cluster, entrées racine, secteurs/FAT, réservés)
    163840: (1, 64, 1), 184320: (1, 64, 2), 327680: (2, 112, 1), 368640: (2, 112, 2),
    737280: (2, 112, 3), 1228800: (1, 224, 7), 1474560: (1, 224, 9), 2949120: (2, 240, 9),
}


def _dosdate(d: int, t: int) -> str:
    if d == 0:
        return ""
    day, mon, year = d & 31, (d >> 5) & 15, 1980 + (d >> 9)
    hh, mm = t >> 11, (t >> 5) & 63
    if not (1 <= mon <= 12 and 1 <= day <= 31):
        return ""
    return f"{day:02d}/{mon:02d}/{year} {hh:02d}:{mm:02d}"


class FATFS(FileSystem):
    def __init__(self, data: bytes, bps, spc, rsv, nfat, nroot, total, spf, media, bpb=True,
                 rescue=False):
        super().__init__()
        self._args = (bps, spc, rsv, nfat, nroot, total, spf, media, bpb, rescue)
        self.d = bytearray(data)
        self.rescue = rescue
        self.damaged_dir = False
        self.bps, self.spc, self.rsv, self.nfat = bps, spc, rsv, nfat
        self.nroot, self.total, self.spf, self.media = nroot, total, spf, media
        self.root_off = (rsv + nfat * spf) * bps
        self.data_off = self.root_off + nroot * 32
        self.csize = spc * bps
        self.nclus = max(0, (min(total * bps, len(data)) - self.data_off) // self.csize)
        self.fat16 = self.nclus >= 4085
        self.name = "FAT16" if self.fat16 else "FAT12"
        fo = rsv * bps
        self.fat = data[fo:fo + spf * bps]
        if (not any(self.fat[3:]) or is_bad(self.fat)) and nfat > 1:   # FAT 1 illisible : copie
            self.fat = data[fo + spf * bps:fo + 2 * spf * bps]
        blank = not any(self.fat[3:])
        self.fat_missing = is_bad(self.fat) or (blank and not (self.fat[0] >= 0xF0 and
                                                               self.fat[1:3] == b"\xff\xff"))
        boot = data[:512]
        oem = "" if is_bad(boot) else boot[3:11].decode("latin-1", "replace").strip("\0 ")
        if boot[0] == 0x60 or oem.startswith("Loader") or (boot[0] not in (0xEB, 0xE9) and bpb
                                                              and oem[:2] != "MS"):
            self.platform, self.name = "atarist", self.name + " (Atari ST)"
        if "MSX" in oem:
            self.platform, self.name = "msx", self.name + " (MSX)"
        self._parse()
        used = sum(1 for c in range(2, self.nclus + 2) if self._next(c) != 0)
        free = (self.nclus - used) * self.csize
        self.info = [("Système", self.name), ("OEM", oem or "—"), ("Étiquette", self.label or "—"),
                     ("Clusters", f"{self.nclus} × {self.csize} o"), ("Libre", "—" if self.fat_missing else human(free)),
                     ("Média", f"0x{media:02X}" + ("" if bpb else " (sans BPB, DOS 1.x)"))]
        if rescue:
            self.info.append(("Récupération", "secteur de démarrage illisible : géométrie standard supposée"))
        if self.fat_missing:
            self.info.append(("Récupération", "FAT illisible : fichiers lus comme contigus"))
        if self.damaged_dir:
            self.info.append(("Attention", "répertoire partiellement illisible : des fichiers peuvent manquer"))

    def _next(self, c: int) -> int:
        if self.fat16:
            o = c * 2
            return u16(self.fat, o) if o + 1 < len(self.fat) else 0xFFFF
        o = c * 3 // 2
        if o + 1 >= len(self.fat):
            return 0xFFF
        v = u16(self.fat, o)
        return (v >> 4) if c & 1 else (v & 0xFFF)

    def _eoc(self, v: int) -> bool:
        return v >= (0xFFF8 if self.fat16 else 0xFF8) or v < 2

    def _chain(self, c: int, size: Optional[int] = None) -> List[int]:
        if self.fat_missing:
            n = max(1, -(-size // self.csize)) if size else 4
            return [x for x in range(c, c + n) if 2 <= x < self.nclus + 2]
        out, seen = [], set()
        while 2 <= c < self.nclus + 2 and c not in seen:
            seen.add(c)
            out.append(c)
            n = self._next(c)
            if self._eoc(n):
                break
            c = n
        return out

    def _clus_data(self, chain: List[int]) -> bytes:
        return b"".join(self.d[self.data_off + (c - 2) * self.csize:
                               self.data_off + (c - 1) * self.csize] for c in chain)

    def _slots(self, first: Optional[int]) -> List[int]:
        """Offsets absolus des entrées d'un répertoire (None = racine)."""
        if first is None:
            return list(range(self.root_off, self.data_off, 32))
        out = []
        for c in self._chain(first):
            base = self.data_off + (c - 2) * self.csize
            out += range(base, base + self.csize, 32)
        return out

    def _parse_dir(self, raw: bytes, parent: Entry, depth: int, first: Optional[int] = None):
        lfn: List[str] = []
        slots = self._slots(first)
        lfn_slots: List[int] = []
        for i in range(0, len(raw) - 31, 32):
            if is_bad(raw[i - i % 512:i - i % 512 + 32]):
                self.damaged_dir = True
                continue
            e = raw[i:i + 32]
            if e[0] == 0:
                break
            attr = e[11]
            if attr == 0x0F:
                part = (e[1:11] + e[14:26] + e[28:32]).decode("utf-16-le", "ignore")
                part = part.split("\0")[0].rstrip("￿")
                if e[0] & 0x40:
                    lfn, lfn_slots = [part], []
                else:
                    lfn.insert(0, part)
                lfn_slots.append(slots[i // 32] if i // 32 < len(slots) else -1)
                continue
            if e[0] == 0xE5:
                lfn, lfn_slots = [], []
                continue
            name = e[0:8].decode(self.charset, "replace").rstrip()
            if e[0] == 0x05:
                name = "å" + name[1:]
            ext = e[8:11].decode(self.charset, "replace").rstrip()
            if attr & 0x08:
                if not attr & 0x10:
                    self.label = (name + ext).strip()
                lfn = []
                continue
            if name in (".", ".."):
                continue
            full = "".join(lfn) if lfn else (name + ("." + ext if ext else ""))
            lfn = []
            clus = u16(e, 26)
            size = u32(e, 28)
            flags = "".join(ch for b, ch in ((1, "L"), (2, "C"), (4, "S"), (0x20, "A")) if attr & b)
            ent = Entry(full, size, bool(attr & 0x10), "Dossier" if attr & 0x10 else "",
                        _dosdate(u16(e, 24), u16(e, 22)), flags, {"cluster": clus,
                        "nom 8.3": name + ("." + ext if ext else "")}, clus)
            ent.slot = (slots[i // 32] if i // 32 < len(slots) else -1, lfn_slots)
            lfn_slots = []
            parent.add(ent)
            if ent.is_dir and depth < 16 and clus >= 2:
                self._parse_dir(self._clus_data(self._chain(clus)), ent, depth + 1, clus)

    def _parse(self):
        self._parse_dir(self.d[self.root_off:self.data_off], self.root, 0)

    def read(self, e: Entry) -> bytes:
        if isinstance(e.ref, tuple):            # fichier supprimé : clusters supposés contigus
            c = e.ref[1]
            n = max(1, -(-e.size // self.csize))
            return self._clus_data([x for x in range(c, c + n) if 2 <= x < self.nclus + 2])[:e.size]
        if e.ref is None or e.ref < 2:
            return b""
        return self._clus_data(self._chain(e.ref, e.size))[:e.size]

    # ------------------------------------------------------------ Analyse
    def allocation(self):
        spc, total = self.spc, min(self.total, len(self.d) // self.bps)
        own = ["sys"] * (self.data_off // self.bps)
        own += ["free"] * max(0, total - len(own))
        def mark(c, who):
            s0 = self.data_off // self.bps + (c - 2) * spc
            for k in range(s0, min(s0 + spc, total)):
                own[k] = who
        if not self.fat_missing:
            bad_mark = 0xFFF7 if self.fat16 else 0xFF7
            for c in range(2, self.nclus + 2):
                v = self._next(c)
                if v == bad_mark:
                    mark(c, "bad")
                elif v:
                    mark(c, "used")
        for e in self.root.walk():
            if e.ref and isinstance(e.ref, int) and e.ref >= 2:
                for c in self._chain(e.ref, e.size or None):
                    mark(c, e)
        mark_bad(own, self.bps, self.d)
        return self.bps, own

    def deleted(self) -> List[Entry]:
        out = []
        dirs = [(None, self.root)] + [(e.ref, e) for e in self.root.walk() if e.is_dir and e.ref]
        for first, parent in dirs:
            try:
                slots = self._slots(first)
            except Exception:
                continue
            for o in slots:
                e = self.d[o:o + 32]
                if len(e) < 32 or e[0] != 0xE5 or e[11] == 0x0F or e[11] & 0x08:
                    continue
                if not all(0x20 <= c < 0x7F or c >= 0x80 for c in e[1:11]) or e[1:11].strip() == b"":
                    continue
                name = "?" + e[1:8].decode(self.charset, "replace").rstrip()
                ext = e[8:11].decode(self.charset, "replace").rstrip()
                clus, size = u16(e, 26), u32(e, 28)
                if e[11] & 0x10 or clus < 2 or clus >= self.nclus + 2:
                    continue
                n = max(1, -(-size // self.csize))
                free = self.fat_missing or all(self._next(c) == 0 for c in range(clus, min(clus + n, self.nclus + 2)))
                ent = Entry(name + ("." + ext if ext else ""), size, False,
                            "Supprimé — " + ("récupérable" if free else "partiellement écrasé"),
                            _dosdate(u16(e, 24), u16(e, 22)), "", {"cluster": clus, "dossier": "/" + parent.path,
                            "récupération": "clusters contigus supposés"}, ("del", clus))
                ent.deleted = True
                out.append(ent)
        return out

    # ------------------------------------------------------------ Écriture
    @property
    def writable(self):
        return not (self.fat_missing or self.rescue)

    @property
    def save_ext(self):
        return ".st" if self.platform == "atarist" else ".img"

    def _set(self, c: int, v: int):
        for k in range(self.nfat):
            fo = (self.rsv + k * self.spf) * self.bps
            if self.fat16:
                struct.pack_into("<H", self.d, fo + c * 2, v)
            else:
                o = fo + c * 3 // 2
                cur = u16(self.d, o)
                cur = (cur & 0x000F) | (v << 4) if c & 1 else (cur & 0xF000) | (v & 0xFFF)
                struct.pack_into("<H", self.d, o, cur)
        fo = self.rsv * self.bps
        self.fat = self.d[fo:fo + self.spf * self.bps]

    def _alloc(self, n: int) -> List[int]:
        free = [c for c in range(2, self.nclus + 2) if self._next(c) == 0]
        if len(free) < n:
            raise FSError(f"Espace insuffisant : {n} cluster(s) requis, {len(free)} libre(s)")
        return free[:n]

    @staticmethod
    def short_name(name: str, taken) -> bytes:
        bad = set(' "*+,./:;<=>?[\\]|')
        base, _, ext = name.upper().rpartition(".") if "." in name else (name.upper(), "", "")
        clean = lambda t: "".join(ch if ch.isascii() and ch.isprintable() and ch not in bad else "_"
                                  for ch in t)
        base, ext = clean(base)[:8] or "FICHIER", clean(ext)[:3]
        cand = base.ljust(8) + ext.ljust(3)
        n = 1
        while cand.encode("ascii", "replace") in taken:
            suf = f"~{n}"
            cand = (base[:8 - len(suf)] + suf).ljust(8) + ext.ljust(3)
            n += 1
        return cand.encode("ascii", "replace")

    def add_file(self, parent: Entry, name: str, data: bytes, is_dir: bool = False) -> str:
        first = parent.ref if parent is not self.root else None
        slots = self._slots(first)
        taken = {bytes(self.d[o:o + 11]) for o in slots if self.d[o] not in (0, 0xE5)}
        sn = self.short_name(name, taken)
        disp = sn[:8].decode("ascii").rstrip() + ("." + sn[8:].decode("ascii").rstrip() if sn[8:].strip() else "")
        lfn = self._lfn(name, sn) if self.platform == "pc" and name != disp else []
        need = len(lfn) + 1
        free_slot, run = None, 0
        for k, o in enumerate(slots):
            run = run + 1 if self.d[o] in (0, 0xE5) else 0
            if run == need:
                start = k - need + 1
                free_slot = slots[k]
                lfn_slots = slots[start:k]
                break
        if free_slot is None:
            raise FSError("Répertoire plein")
        n = max(1, -(-len(data) // self.csize)) if (data or is_dir) else 0
        chain = self._alloc(n)
        eoc = 0xFFFF if self.fat16 else 0xFFF
        for i, c in enumerate(chain):
            self._set(c, chain[i + 1] if i + 1 < len(chain) else eoc)
            o = self.data_off + (c - 2) * self.csize
            chunk = data[i * self.csize:(i + 1) * self.csize] if not is_dir else b""
            self.d[o:o + self.csize] = chunk.ljust(self.csize, b"\0")
        t = time.localtime()
        ent = bytearray(32)
        ent[0:11] = sn
        ent[11] = 0x10 if is_dir else 0x20
        struct.pack_into("<HHHHHHHI", ent, 14, t.tm_hour << 11 | t.tm_min << 5 | t.tm_sec // 2,
                         (t.tm_year - 1980) << 9 | t.tm_mon << 5 | t.tm_mday,
                         (t.tm_year - 1980) << 9 | t.tm_mon << 5 | t.tm_mday, 0,
                         t.tm_hour << 11 | t.tm_min << 5 | t.tm_sec // 2,
                         (t.tm_year - 1980) << 9 | t.tm_mon << 5 | t.tm_mday,
                         chain[0] if chain else 0, 0 if is_dir else len(data))
        self.d[free_slot:free_slot + 32] = ent
        for o, le in zip(lfn_slots, lfn):
            self.d[o:o + 32] = le
        if is_dir:
            o = self.data_off + (chain[0] - 2) * self.csize
            for k, nm in enumerate((b".          ", b"..         ")):
                de = bytearray(ent)
                de[0:11] = nm
                struct.pack_into("<H", de, 26, chain[0] if k == 0 else (first or 0))
                struct.pack_into("<I", de, 28, 0)
                self.d[o + k * 32:o + k * 32 + 32] = de
        self.refresh()
        return name if lfn else disp

    @staticmethod
    def _lfn(name: str, sn: bytes) -> List[bytes]:
        ck = 0
        for c in sn:
            ck = (((ck & 1) << 7) + (ck >> 1) + c) & 0xFF
        u = name[:255].encode("utf-16-le")
        chars = [u[i:i + 2] for i in range(0, len(u), 2)]
        n = -(-len(chars) // 13)
        chars += [b"\0\0"] if len(chars) % 13 else []
        chars += [b"\xff\xff"] * (n * 13 - len(chars))
        out = []
        for k in range(n, 0, -1):
            part = chars[(k - 1) * 13:k * 13]
            e = bytearray(32)
            e[0] = k | (0x40 if k == n else 0)
            e[1:11] = b"".join(part[0:5])
            e[11], e[12], e[13] = 0x0F, 0, ck
            e[14:26] = b"".join(part[5:11])
            e[28:32] = b"".join(part[11:13])
            out.append(bytes(e))
        return out

    def mkdir(self, parent: Entry, name: str) -> str:
        return self.add_file(parent, name, b"", is_dir=True)

    def delete(self, e: Entry):
        self._delete(e)
        self.refresh()

    def _delete(self, e: Entry):
        for c in list(e.children):
            self._delete(c)
        slot, lfn = getattr(e, "slot", (-1, []))
        if e.ref and e.ref >= 2:
            for c in self._chain(e.ref):
                self._set(c, 0)
        for o in [slot] + list(lfn):
            if o >= 0:
                self.d[o] = 0xE5

    def refresh(self):
        self.__init__(bytes(self.d), *self._args)

    def save(self, path: str):
        with open(path, "wb") as f:
            f.write(bytes(self.d))


def probe(disk) -> List[FileSystem]:
    d = disk.linear()
    if len(d) < 512 * 8:
        return []
    b = d[:512]
    bps, spc, rsv, nfat = u16(b, 11), b[13], u16(b, 14), b[16]
    nroot, tot, media, spf = u16(b, 17), u16(b, 19) or u32(b, 32), b[21], u16(b, 22)
    if (bps in (256, 512, 1024, 2048) and spc in (1, 2, 4, 8, 16, 32, 64, 128) and 1 <= nfat <= 2
            and 1 <= rsv <= 64 and 16 <= nroot <= 4096 and 1 <= spf <= 256 and tot > 0
            and (media >= 0xF0 or media == 0)):
        try:
            return [FATFS(d, bps, spc, rsv, nfat, nroot, tot, spf, media or 0xF9)]
        except Exception:
            pass
    # Sans BPB : octet média au début de la FAT
    if len(d) in _NO_BPB and d[512] >= 0xF8 and d[513] == 0xFF and d[514] == 0xFF:
        spc, nroot, spf = _NO_BPB[len(d)]
        try:
            return [FATFS(d, 512, spc, 1, 2, nroot, len(d) // 512, spf, d[512], bpb=False)]
        except Exception:
            pass
    # Secteur de démarrage illisible (vide) : géométrie DOS standard, si le répertoire est plausible
    if len(d) in _NO_BPB and (not any(b[:64]) or is_bad(b)):
        spc, nroot, spf0 = _NO_BPB[len(d)]
        for spf in [spf0] + [x for x in range(1, 17) if x != spf0]:
            root = d[(1 + 2 * spf) * 512:(1 + 2 * spf) * 512 + nroot * 32]
            if _plausible_dir(root):
                try:
                    return [FATFS(d, 512, spc, 1, 2, nroot, len(d) // 512, spf, 0xF0, bpb=False,
                                  rescue=True)]
                except Exception:
                    pass
    return []


def _plausible_dir(root: bytes) -> bool:
    good = 0
    for i in range(0, len(root), 32):
        if is_bad(root[i - i % 512:i - i % 512 + 32]):
            continue
        e = root[i:i + 32]
        if e[0] == 0:
            break
        if e[0] == 0xE5 or e[11] == 0x0F:
            continue
        if all(0x20 <= c < 0x7F or c >= 0x80 for c in e[:11]) and e[11] < 0x40:
            good += 1
        else:
            return False
    return good > 0
