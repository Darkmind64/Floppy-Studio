"""Chargement d'une image disque vers un modèle secteurs commun."""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

BAD = b"-=[BAD SECTOR]=-"          # motif greaseweazle pour les secteurs illisibles


def is_bad(data: bytes) -> bool:
    return data[:32] == BAD * 2


def bad_fill(size: int) -> bytes:
    return (BAD * (size // 16 + 1))[:size]


def count_bad(data: bytes) -> int:
    """Nombre approximatif de secteurs illisibles (512 o) contenus dans des données."""
    n = data.count(BAD * 2)
    return (n + 15) // 16 if n else 0


RAW_EXT = {".img", ".ima", ".st", ".adf", ".d64", ".d71", ".d81", ".fd", ".vfd", ".flp",
           ".ssd", ".dsd", ".do", ".po", ".mgt", ".sf7", ".2d", ".xfd", ".atr_raw", ".2mg"}


@dataclass
class Sec:
    r: int
    n: int
    data: bytes
    ok: bool = True


@dataclass
class Disk:
    path: str
    kind: str                                     # extension ou type de conteneur
    raw: Optional[bytes] = None                   # image secteur brute (ordre IMG)
    tracks: Dict[Tuple[int, int], List[Sec]] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    fmt: Optional[str] = None                     # format greaseweazle utilisé pour décoder

    @property
    def heads(self) -> int:
        if not self.tracks:
            return 1
        return max(h for _, h in self.tracks) + 1

    @property
    def cyls(self) -> int:
        if not self.tracks:
            return 0
        return max(c for c, _ in self.tracks) + 1

    def track(self, c: int, h: int) -> List[Sec]:
        return self.tracks.get((c, h), [])

    def sector(self, c: int, h: int, r: int) -> Optional[Sec]:
        for s in self.tracks.get((c, h), []):
            if s.r == r:
                return s
        return None

    def bad_sectors(self) -> int:
        if self.tracks:
            return sum(1 for t in self.tracks.values() for s in t if not s.ok)
        if self.raw:
            return sum(1 for o in range(0, len(self.raw), 512) if is_bad(self.raw[o:o + 32]))
        return 0

    def _track_bytes(self, secs: List[Sec]) -> bytes:
        seen = {}
        for s in secs:
            if s.r not in seen or (s.ok and not seen[s.r].ok):
                seen[s.r] = s
        out = bytearray()
        for r in sorted(seen):
            s = seen[r]
            size = 128 << s.n if s.n < 8 else len(s.data)
            d = s.data if s.data and s.ok else bad_fill(size)
            out += d[:size].ljust(size, b"\0")
        return bytes(out)

    def linear(self, heads: Optional[List[int]] = None, sequential: bool = False) -> bytes:
        """Données concaténées : cylindre puis face (ordre IMG), ou face entière
        puis l'autre (sequential), limitées aux faces demandées."""
        if self.raw is not None and heads is None and not sequential:
            return self.raw
        if not self.tracks:
            return self.raw or b""
        hs = heads if heads is not None else list(range(self.heads))
        ncyl = self.cyls
        # taille de piste nominale pour combler les pistes absentes
        nominal = max((len(self._track_bytes(t)) for t in self.tracks.values()), default=0)
        out = bytearray()
        order = ([(c, h) for h in hs for c in range(ncyl)] if sequential
                 else [(c, h) for c in range(ncyl) for h in hs])
        for c, h in order:
            t = self.tracks.get((c, h))
            out += self._track_bytes(t) if t else bad_fill(nominal)
        return bytes(out)

    @staticmethod
    def from_geometry(path: str, data: bytes, cyls: int, heads: int, nsec: int,
                      ssize: int, first_id: int = 1, kind: str = "",
                      sequential: bool = False) -> "Disk":
        d = Disk(path, kind, raw=data if not sequential else None)
        n = {128: 0, 256: 1, 512: 2, 1024: 3, 2048: 4}.get(ssize, 2)
        tsz = nsec * ssize
        for c in range(cyls):
            for h in range(heads):
                idx = (h * cyls + c) if sequential else (c * heads + h)
                off = idx * tsz
                if off >= len(data):
                    continue
                secs = []
                for i in range(nsec):
                    sd = data[off + i * ssize: off + (i + 1) * ssize]
                    secs.append(Sec(first_id + i, n, sd, not is_bad(sd)))
                d.tracks[c, h] = secs
        return d


# --------------------------------------------------------------------------
# Conteneurs CPC (DSK standard / étendu)
# --------------------------------------------------------------------------
def parse_cpc_dsk(path: str, data: bytes) -> Disk:
    ext = data.startswith(b"EXTENDED")
    ntr, nsides = data[0x30], data[0x31]
    d = Disk(path, "edsk" if ext else "dsk")
    pos = 0x100
    std_size = struct.unpack_from("<H", data, 0x32)[0]
    for t in range(ntr * nsides):
        tsize = data[0x34 + t] * 256 if ext else std_size
        if tsize == 0:
            continue
        if pos + 0x100 > len(data) or data[pos:pos + 10] != b"Track-Info":
            pos += tsize
            continue
        c, h = data[pos + 0x10], data[pos + 0x11]
        nsec = data[pos + 0x15]
        secs, dpos = [], pos + 0x100
        for i in range(nsec):
            e = pos + 0x18 + i * 8
            sc, sh, sr, sn, st1, st2 = data[e:e + 6]
            alen = struct.unpack_from("<H", data, e + 6)[0] if ext else (128 << sn)
            if not ext:
                alen = 128 << data[pos + 0x14]
            sd = data[dpos:dpos + min(alen, 128 << min(sn, 6))]
            ok = not (st1 & 0x20 or st2 & 0x20)
            secs.append(Sec(sr, sn, sd, ok))
            dpos += alen
        d.tracks[c, h] = secs
        pos += tsize
    return d


def write_edsk(disk: Disk, path: str):
    """Écrit une image Extended DSK (pour émulateurs CPC)."""
    ncyl, nh = disk.cyls, disk.heads
    tracks = []
    for c in range(ncyl):
        for h in range(nh):
            secs = disk.track(c, h)
            if not secs:
                tracks.append(b"")
                continue
            info = bytearray(b"Track-Info\r\n\0\0\0\0")
            info += bytes([c, h, 0, 0, secs[0].n, len(secs), 0x4E, 0xE5])
            body = bytearray()
            for s in secs:
                size = 128 << s.n
                dat = (s.data or b"\0" * size)[:size].ljust(size, b"\0")
                info += bytes([c, h, s.r, s.n, 0 if s.ok else 0x20, 0 if s.ok else 0x20])
                info += struct.pack("<H", len(dat))
                body += dat
            info = info.ljust(256, b"\0")
            blk = bytes(info + body)
            blk += b"\0" * ((-len(blk)) % 256)
            tracks.append(blk)
    hdr = bytearray(b"EXTENDED CPC DSK File\r\nDisk-Info\r\n")
    hdr += b"Floppy Studio".ljust(14, b"\0")
    hdr += bytes([ncyl, nh, 0, 0])
    hdr += bytes(len(t) // 256 for t in tracks)
    hdr = hdr.ljust(256, b"\0")
    with open(path, "wb") as f:
        f.write(hdr)
        for t in tracks:
            f.write(t)


# --------------------------------------------------------------------------
# Chargement générique
# --------------------------------------------------------------------------
def _sectors_from_codec(t) -> List[Sec]:
    inner = getattr(t, "track", None)
    if inner is not None and hasattr(inner, "sectors"):
        t = inner
    secs = getattr(t, "sectors", None)
    if secs and hasattr(secs[0], "idam"):
        out = []
        for s in secs:
            dam = getattr(s, "dam", None)
            data = bytes(dam.data) if dam is not None and dam.data is not None else b""
            out.append(Sec(s.idam.r, s.idam.n, data, s.crc == 0 and bool(data)))
        return out
    try:
        img = bytes(t.get_img_track())
    except Exception:
        return []
    n = t.nsec or 1
    size = len(img) // n if n else len(img)
    nn = {128: 0, 256: 1, 512: 2, 1024: 3}.get(size, 2)
    out = []
    for i in range(n):
        try:
            ok = bool(t.has_sec(i))
        except Exception:
            ok = True
        out.append(Sec(i, nn, img[i * size:(i + 1) * size], ok))
    return out


def _load_via_greaseweazle(path: str, fmt: Optional[str]) -> Disk:
    from greaseweazle.codec import codec as gw_codec
    from greaseweazle.tools import util
    from .. import formats as F

    img_cls = util.get_image_class(path)
    fmt_name = fmt or img_cls.default_format
    fmt_cls = F.get_diskdef(fmt_name) if fmt_name else None
    try:
        image = img_cls.from_file(path, fmt_cls, {})
    except Exception:
        image = img_cls.from_file(path, None, {})
    maxc = image.max_cylinder()
    tracks_raw = {}
    for h in range(2):
        for c in range(0, max(maxc[h], -1) + 1):
            t = image.get_track(c, h)
            if t is not None:
                tracks_raw[c, h] = t

    def decode(defn, only=None):
        out = {}
        for (c, h), t in tracks_raw.items():
            if only is not None and (c, h) not in only:
                continue
            if isinstance(t, gw_codec.Codec):
                out[c, h] = _sectors_from_codec(t)
                continue
            if defn is None:
                continue
            try:
                dt = defn.decode_flux(c, h, t)
            except Exception:
                dt = None
            if dt is not None:
                out[c, h] = _sectors_from_codec(dt)
        return out

    all_codec = all(isinstance(t, gw_codec.Codec) for t in tracks_raw.values())
    if fmt_name or all_codec:
        best_fmt = fmt_name
    else:
        # flux brut : on essaie plusieurs codages sur quelques pistes
        probe_tr = {(0, 0), (0, 1), (1, 0), (2, 1)}
        best_fmt, best_score = "ibm.scan", -1
        for cand in ("ibm.scan", "amiga.amigados", "amiga.amigados_hd", "commodore.1541",
                     "apple2.appledos.140", "mac.800"):
            defn = F.get_diskdef(cand)
            if defn is None:
                continue
            tr = decode(defn, probe_tr)
            score = sum(len(s.data) for t in tr.values() for s in t if s.ok)
            if score > best_score:
                best_fmt, best_score = cand, score
    best = decode(F.get_diskdef(best_fmt) if best_fmt else None)
    d = Disk(path, os.path.splitext(path)[1].lower(), tracks=best, fmt=best_fmt)
    if best_fmt:
        d.notes.append(f"Décodé avec {best_fmt}")
    return d


def _raw_geometry(size: int, ext: str):
    """(cyls, heads, nsec, ssize, first_id, sequential) d'après la taille."""
    table = {
        163840: (40, 1, 8, 512, 1), 184320: (40, 1, 9, 512, 1), 327680: (40, 2, 8, 512, 1),
        368640: (40, 2, 9, 512, 1), 409600: (80, 1, 10, 512, 1), 737280: (80, 2, 9, 512, 1),
        819200: (80, 2, 10, 512, 1), 901120: (80, 2, 11, 512, 0), 1228800: (80, 2, 15, 512, 1),
        1474560: (80, 2, 18, 512, 1), 1720320: (80, 2, 21, 512, 1), 1802240: (80, 2, 22, 512, 0),
        2949120: (80, 2, 36, 512, 1),
    }
    if ext == ".fd":
        # Thomson : 16 secteurs, faces stockées l'une après l'autre
        per_side = {81920: (40, 16, 128), 163840: (40, 16, 256), 327680: (80, 16, 256)}
        for side_sz, (cyl, ns, ss) in sorted(per_side.items(), reverse=True):
            if size % side_sz == 0 and size // side_sz in (1, 2):
                if size == 163840 and ss == 256:
                    return cyl, 1, ns, ss, 1, True
                return cyl, size // side_sz, ns, ss, 1, True
        return None
    if ext == ".adf":
        return (80, 2, 11, 512, 0, False) if size == 901120 else (80, 2, 22, 512, 0, False)
    if ext == ".st" and size not in table:
        for ns in (9, 10, 11, 18):
            for hd in (1, 2):
                for cyl in (80, 81, 82, 83, 84):
                    if size == cyl * hd * ns * 512:
                        return cyl, hd, ns, 512, 1, False
    if size in table:
        return table[size] + (False,)
    if size % (1024 * 5 * 2 * 80) == 0 and size in (819200, 1638400):
        return (80, 2, size // (1024 * 2 * 80), 1024, 1, False)
    return None


def _raw_from_diskdef(path: str, data: bytes, fmt: str, ext: str) -> Optional["Disk"]:
    """Image brute au format greaseweazle (pistes dans l'ordre du diskdef, secteurs triés par ID)."""
    try:
        from ..formats import get_diskdef
        dd = get_diskdef(fmt)
        if dd is None:
            return None
        layout = []
        for c in dd.tracks.cyls:
            for h in dd.tracks.heads:
                t = dd.mk_track(c, h)
                if t is None or not hasattr(t, "sectors"):
                    return None
                layout.append((c, h, sorted((s.idam.r, s.idam.n, s.idam.h) for s in t.sectors)))
    except Exception:
        return None
    if sum(128 << n for _, _, secs in layout for _, n, _ in secs) != len(data):
        return None
    # Faces inversées (ex. Commodore 1581 : face logique 0 = tête physique 1)
    swapped = any(secs and secs[0][2] == (h ^ 1) for c, h, secs in layout if h in (0, 1)) and \
        all(secs and secs[0][2] == (h ^ 1) for c, h, secs in layout if h in (0, 1))
    d = Disk(path, ext, raw=None if swapped else data, fmt=fmt)
    off = 0
    for c, h, secs in layout:
        out = []
        for r, n, _ in secs:
            sd = data[off: off + (128 << n)]
            off += 128 << n
            out.append(Sec(r, n, sd, not is_bad(sd)))
        d.tracks[c, h ^ 1 if swapped else h] = out
    return d


def open_disk(path: str, fmt: Optional[str] = None) -> Disk:
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as f:
        head = f.read(64)
    if head.startswith(b"EXTENDED CPC DSK") or head.startswith(b"MV - CPC"):
        with open(path, "rb") as f:
            return parse_cpc_dsk(path, f.read())
    if ext in RAW_EXT or (ext == ".dsk" and not head.startswith(b"MV")):
        with open(path, "rb") as f:
            data = f.read()
        if fmt and ext not in (".fd", ".adf", ".st"):
            d = _raw_from_diskdef(path, data, fmt, ext)
            if d is not None:
                return d
        if ext == ".dsk" or ext in RAW_EXT:
            geo = _raw_geometry(len(data), ext)
            if geo:
                cyl, hd, ns, ss, fid, seq = geo
                d = Disk.from_geometry(path, data, cyl, hd, ns, ss, fid, ext, seq)
                d.raw = data
                return d
            return Disk(path, ext, raw=data)
    return _load_via_greaseweazle(path, fmt)
