"""Acorn : DFS (BBC Micro) et ADFS (BBC Master, Archimedes / RISC OS) — lecture."""
from __future__ import annotations

import struct
from typing import Callable, List, Optional

from .base import Entry, FileSystem, human

RISCOS_TYPES = {0xFFF: "Texte", 0xFFB: "BASIC", 0xFF9: "Sprite", 0xFEB: "Obey", 0xFFA: "Module",
                0xFF8: "Absolu", 0xFFD: "Données", 0xFEA: "Desktop", 0xFFE: "Commande", 0xFFC: "Utilitaire",
                0xAFF: "DrawFile", 0xC85: "JPEG", 0xFAF: "HTML", 0xDDC: "Archive", 0xFE4: "DOS",
                0xFF6: "Police", 0xFF0: "TIFF", 0xFC8: "DOS disc", 0xB60: "PNG", 0xFF5: "PostScript"}
BOOT_OPT = {0: "aucune", 1: "*LOAD", 2: "*RUN", 3: "*EXEC"}


def _l24(b, o):
    return b[o] | b[o + 1] << 8 | b[o + 2] << 16


def _l32(b, o):
    return struct.unpack_from("<I", b, o)[0]


def _riscos_kind(load: int, execa: int, riscos: bool = True):
    if riscos and load & 0xFFF00000 == 0xFFF00000:
        ft = (load >> 8) & 0xFFF
        return f"{RISCOS_TYPES.get(ft, 'Type')} &{ft:03X}", ft
    return f"Chargement &{load:08X}", None


# --------------------------------------------------------------------------
# DFS
# --------------------------------------------------------------------------
class DFS(FileSystem):
    platform = "acorn"
    charset = "latin-1"

    def __init__(self, data: bytes, side: int = 0):
        super().__init__()
        self.d = data
        s0, s1 = data[:256], data[256:512]
        self.label = (s0[:8] + s1[:4]).decode("latin-1", "replace").replace("\0", " ").strip()
        n = s1[5] // 8
        self.nsec = s1[7] | (s1[6] & 3) << 8
        self.boot = (s1[6] >> 4) & 3
        self.name = "Acorn DFS"
        if side:
            self.volume_name = f"Face {side} (lecteur {side * 2})"
        dirs = {}
        used = 2
        for i in range(n):
            o = 8 + i * 8
            nm = bytes(c & 0x7F for c in s0[o:o + 7]).decode("latin-1", "replace").rstrip()
            dch = chr(s0[o + 7] & 0x7F)
            locked = bool(s0[o + 7] & 0x80)
            mix = s1[o + 6]
            load = s1[o] | s1[o + 1] << 8 | ((mix >> 2) & 3) << 16
            execa = s1[o + 2] | s1[o + 3] << 8 | ((mix >> 6) & 3) << 16
            length = s1[o + 4] | s1[o + 5] << 8 | ((mix >> 4) & 3) << 16
            start = s1[o + 7] | (mix & 3) << 8
            used += -(-length // 256)
            if dch == "$":
                parent = self.root
            else:
                if dch not in dirs:
                    dirs[dch] = self.root.add(Entry(dch, 0, True, "Répertoire DFS"))
                parent = dirs[dch]
            e = Entry(nm, length, False, "", "", "L" if locked else "",
                      {"chargement": f"&{load:06X}", "exécution": f"&{execa:06X}", "secteur": start,
                       "répertoire": dch}, start)
            parent.add(e)
            e.kind = "BASIC BBC" if _is_bbc_basic(self._raw(e)) else "Fichier"
        self.info = [("Système", self.name), ("Titre", self.label or "—"),
                     ("Secteurs", f"{self.nsec} × 256 o"), ("Démarrage", BOOT_OPT.get(self.boot, "?")),
                     ("Libre", human(max(self.nsec - used, 0) * 256)), ("Fichiers", str(n))]

    def _raw(self, e: Entry) -> bytes:
        return self.d[e.ref * 256:e.ref * 256 + e.size]

    def read(self, e: Entry) -> bytes:
        return self._raw(e)


def _is_bbc_basic(d: bytes) -> bool:
    return len(d) >= 2 and d[0] == 0x0D and (d[1] == 0xFF or d.rstrip(b"\0")[-2:] == b"\x0d\xff")


def _dfs_ok(d: bytes) -> bool:
    if len(d) < 512:
        return False
    s0, s1 = d[:256], d[256:512]
    n = s1[5]
    if n % 8 or n > 31 * 8:
        return False
    nsec = s1[7] | (s1[6] & 3) << 8
    if nsec not in (400, 800) and not 2 < nsec <= 800:
        return False
    if s1[6] & 0xCC:
        return False
    for i in range(n // 8):
        o = 8 + i * 8
        nm = bytes(c & 0x7F for c in s0[o:o + 7])
        if not all(32 <= c < 127 for c in nm) or nm[0] == 32:
            return False
        start = s1[o + 7] | (s1[o + 6] & 3) << 8
        if start < 2 or start > nsec:
            return False
    title = s0[:8] + s1[:4]
    return all(c == 0 or 32 <= c < 127 for c in title)


# --------------------------------------------------------------------------
# ADFS (ancienne et nouvelle carte, répertoires Hugo / Nick / SBPr)
# --------------------------------------------------------------------------
class ADFS(FileSystem):
    platform = "acorn"
    charset = "latin-1"

    def __init__(self, data: bytes, kind: str, root: int, secsize: int,
                 locate: Callable[[int], Optional[List[tuple]]], dr: Optional[dict] = None):
        super().__init__()
        self.d, self.kind, self.secsize, self.locate = data, kind, secsize, locate
        self.name = f"Acorn ADFS ({kind})"
        self.dr = dr or {}
        self._seen = set()
        self.big = False
        title = self._load_dir(root, self.root, 0)
        if self.big and kind in ("E", "F"):
            self.kind = kind = kind + "+"
            self.name = f"Acorn ADFS ({kind})"
        lbl = (self.dr.get("name") or (title if title != "$" else "") or "")
        self.label = "".join(c if c.isprintable() else " " for c in lbl.replace("\xa0", " ")).strip()
        free = self.dr.get("free")
        self.info = [("Système", self.name), ("Volume", self.label or "—"),
                     ("Secteurs", f"{len(data) // secsize} × {secsize} o")] + \
                    ([("Libre", human(free))] if free is not None else []) + \
                    [("Fichiers", str(len(self.files)))]

    # Lecture d'un objet (adresse indirecte → octets)
    def _object(self, addr: int, size: int) -> bytes:
        runs = self.locate(addr)
        if not runs:
            return b""
        out = bytearray()
        for off, ln in runs:
            out += self.d[off:off + ln]
            if len(out) >= size:
                break
        return bytes(out[:size])

    def _load_dir(self, addr: int, node: Entry, depth: int) -> str:
        if depth > 32 or addr in self._seen:
            return ""
        self._seen.add(addr)
        head = self._object(addr, 2048)
        if head[4:8] == b"SBPr":
            return self._load_bigdir(addr, node, depth)
        tag = head[1:5]
        if tag not in (b"Hugo", b"Nick"):
            return ""
        newdir = len(head) >= 2048 and head[2048 - 5:2048 - 1] == tag
        size = 2048 if newdir else 1280
        nent = 77 if newdir else 47
        raw = head[:size]
        for i in range(nent):
            o = 5 + i * 26
            if raw[o] == 0:
                break
            nb = raw[o:o + 10]
            nm = ""
            for c in nb:
                c &= 0x7F
                if c in (0, 0x0D):
                    break
                nm += chr(c) if c >= 32 else "?"
            load, execa, length = struct.unpack_from("<III", raw, o + 10)
            ind = _l24(raw, o + 22)
            if newdir:
                atts = raw[o + 25]
                isdir = bool(atts & 8)
                attrs = "".join(ch for b, ch in ((1, "R"), (2, "W"), (4, "L"), (16, "E")) if atts & b)
            else:
                isdir = bool(nb[3] & 0x80)
                attrs = "".join(ch for i2, ch in ((0, "R"), (1, "W"), (2, "L"), (4, "E")) if nb[i2] & 0x80)
            kind, ft = _riscos_kind(load, execa, self.kind not in ("S", "M", "L"))
            e = Entry(nm, 0 if isdir else length, isdir, "Répertoire" if isdir else kind, "", attrs,
                      {"chargement": f"&{load:08X}", "exécution": f"&{execa:08X}",
                       "adresse": f"&{ind:06X}"}, (ind, length, ft))
            node.add(e)
            if isdir:
                self._load_dir(ind, e, depth + 1)
            elif ft is None and length and self._object(ind, 1) == b"\x0d":
                e.kind = "BASIC BBC"
        tail = raw[size - (41 if newdir else 53):]
        title = tail[6:25] if newdir else tail[14:33]
        return bytes(c for c in title if 32 <= c < 127).decode("latin-1").strip()

    def _load_bigdir(self, addr: int, node: Entry, depth: int) -> str:
        self.big = True
        h = self._object(addr, 4096)
        namelen, dsize, nent, namesize, _parent = struct.unpack_from("<IIIII", h, 8)
        raw = self._object(addr, dsize)
        base = 28 + ((namelen + 3) & ~3)
        heap = base + nent * 28
        for i in range(nent):
            o = base + i * 28
            load, execa, length, ind, atts, nl, np_ = struct.unpack_from("<IIIIIII", raw, o)
            nm = raw[heap + np_:heap + np_ + nl].decode("latin-1", "replace")
            isdir = bool(atts & 8)
            kind, ft = _riscos_kind(load, execa)
            e = Entry(nm, 0 if isdir else length, isdir, "Répertoire" if isdir else kind, "", "",
                      {"chargement": f"&{load:08X}", "exécution": f"&{execa:08X}"}, (ind, length, ft))
            node.add(e)
            if isdir:
                self._load_dir(ind, e, depth + 1)
        return raw[28:28 + namelen].decode("latin-1", "replace").strip("\r\0 ")

    def read(self, e: Entry) -> bytes:
        ind, length, _ft = e.ref
        return self._object(ind, length)


def _old_map_locate(secsize: int):
    def loc(addr: int):
        return [(addr * 256, 1 << 30)]
    return loc


def _old_map_free(d: bytes) -> int:
    n = d[0x1FE] // 3
    return sum(_l24(d, 0x100 + i * 3) for i in range(min(n, 82))) * 256


def _zonecheck(m: bytes) -> int:
    v0 = v1 = v2 = v3 = 0
    for i in range(len(m) - 4, 0, -4):
        v0 += m[i] + (v3 >> 8)
        v3 &= 0xFF
        v1 += m[i + 1] + (v0 >> 8)
        v0 &= 0xFF
        v2 += m[i + 2] + (v1 >> 8)
        v1 &= 0xFF
        v3 += m[i + 3] + (v2 >> 8)
        v2 &= 0xFF
    v0 += v3 >> 8
    v1 += m[1] + (v0 >> 8)
    v2 += m[2] + (v1 >> 8)
    v3 += m[3] + (v2 >> 8)
    return (v0 ^ v1 ^ v2 ^ v3) & 0xFF


def _new_map(d: bytes, dr_off: int) -> Optional[ADFS]:
    dr = d[dr_off:dr_off + 60]
    log2sec, spt, heads, density, idlen, log2bpmb, skew, boot, lowsec, nzones = dr[:10]
    zone_spare = struct.unpack_from("<H", dr, 10)[0]
    root, disc_size = struct.unpack_from("<II", dr, 12)
    nzones |= dr[42] << 8
    log2share = dr[40] & 0x0F
    secsize = 1 << log2sec
    if log2sec not in (8, 9, 10, 11) or not 1 <= nzones <= 256 or not 7 <= idlen <= 21 or log2bpmb > 12:
        return None
    if disc_size == 0 or disc_size > len(d) * 2:
        return None
    zone_bits = 8 * secsize - zone_spare
    map2blk = log2bpmb - log2sec
    map_addr = (nzones >> 1) * zone_bits - (480 if nzones > 1 else 0)
    map_off = (map_addr << map2blk if map2blk >= 0 else map_addr >> -map2blk) * secsize
    zones = []
    for z in range(nzones):
        zd = d[map_off + z * secsize:map_off + (z + 1) * secsize]
        if len(zd) < secsize or _zonecheck(zd) != zd[0]:
            return None
        start = 32 + 480 if z == 0 else 32
        startblk = 0 if z == 0 else z * zone_bits - 480
        end = 32 + zone_bits
        zones.append([zd, start, end, startblk])
    total = disc_size >> log2bpmb
    total -= (nzones - 1) * zone_bits - 480
    zones[-1][2] = 32 + total
    bpmb = 1 << log2bpmb
    ids_per_zone = zone_bits // (idlen + 1)

    def bits(zd, pos, n):
        v = int.from_bytes(zd[pos >> 3:(pos >> 3) + 4].ljust(4, b"\0"), "little") >> (pos & 7)
        return v & ((1 << n) - 1)

    def frags(z):
        zd, start, end, startblk = zones[z]
        free = bits(zd, 8, min(idlen, 15))
        freelink = 8 + free if free else 0
        p = start
        while p < end:
            fid = bits(zd, p, idlen)
            q = p + idlen
            while q < end and not (zd[q >> 3] >> (q & 7)) & 1:
                q += 1
            if q >= end:
                break
            if p == freelink:
                freelink += fid & 0x7FFF
                yield None, p, q + 1 - p, startblk - start
            else:
                yield fid, p, q + 1 - p, startblk - start
            p = q + 1

    def locate(addr: int):
        fid, share = addr >> 8, addr & 0xFF
        z0 = nzones >> 1 if fid == 2 else fid // max(ids_per_zone, 1)
        runs = []
        for k in range(nzones):
            z = (z0 + k) % nzones
            for f, p, ln, delta in frags(z):
                if f == fid:
                    runs.append(((p + delta) * bpmb, ln * bpmb))
            if runs:
                break
        if not runs:
            return None
        if share:
            off = (share - 1) << log2share << log2sec if log2share else (share - 1) * secsize
            out, skip = [], off
            for o, ln in runs:
                if skip >= ln:
                    skip -= ln
                    continue
                out.append((o + skip, ln - skip))
                skip = 0
            return out
        return runs

    free = 0
    try:
        for z in range(nzones):
            for f, _p, ln, _d in frags(z):
                if f is None:
                    free += ln * bpmb
    except Exception:
        free = None
    name = dr[22:32].decode("latin-1", "replace").strip("\0 \r")
    kind = {1: "E", 4: "F"}.get(nzones, f"{nzones} zones") if disc_size <= 1638400 else "disque dur"
    if disc_size == 1638400 and nzones > 1:
        kind = "F"
    return ADFS(d, kind, root, secsize, locate, {"name": name, "free": free})


def probe(disk) -> List[FileSystem]:
    kind = disk.kind if isinstance(disk.kind, str) else ""
    # DFS (.ssd / .dsd ou disquette 10 × 256)
    t0 = disk.track(0, 0)
    dfs_like = kind in (".ssd", ".dsd") or (t0 and len(t0) == 10 and all(s.n == 1 for s in t0))
    if dfs_like:
        out = []
        for h in range(disk.heads if disk.tracks else 1):
            d = disk.linear(heads=[h], sequential=True) if disk.tracks else (disk.raw or b"")
            if _dfs_ok(d):
                out.append(DFS(d, h * 1 if disk.heads > 1 else 0))
        if out:
            if len(out) == 1:
                out[0].volume_name = ""
            return out
    d = disk.linear()
    if len(d) < 2048:
        return []
    # Nouvelle carte : bloc d'amorçage (0xC00 + 0x1C0) ou enregistrement de disque en tête de zone 0
    for off in (0xDC0, 4):
        if len(d) > off + 60:
            try:
                fs = _new_map(d, off)
            except Exception:
                fs = None
            if fs is not None:
                return [fs]
    # Ancienne carte : répertoire racine en 0x200 (S/M/L) ou 0x400 (D)
    if disk.tracks and disk.heads == 2 and len(disk.track(0, 0)) == 16:
        d = disk.linear(heads=[0, 1], sequential=True)      # ADFS L : face 0 entière puis face 1
    for root, secsize, kind in ((2, 256, None), (4, 1024, "D")):
        o = root * 256
        if d[o + 1:o + 5] in (b"Hugo", b"Nick"):
            size = _l24(d, 0xFC) * 256
            kind = kind or {640: "S", 1280: "M", 2560: "L"}.get(size // 256, "") or \
                {163840: "S", 327680: "M", 655360: "L"}.get(size, "")
            try:
                fs = ADFS(d, kind or "ancienne carte", root, secsize if kind == "D" else 256,
                          _old_map_locate(256), {"name": "", "free": _old_map_free(d)})
            except Exception:
                continue
            return [fs]
    return []
