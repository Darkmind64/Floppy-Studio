"""Apple II : DOS 3.3 et ProDOS (images .dsk / .do / .po / .2mg)."""
from __future__ import annotations

from typing import List, Optional

from .base import Entry, FileSystem, human, u16

# Index ProDOS (ordre .po) d'un secteur logique DOS 3.3, et inverse
PO_OF_DOS = [0, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 15]
DOS_OF_PO = [PO_OF_DOS.index(i) for i in range(16)]

DOS_TYPES = {0x00: "T", 0x01: "I", 0x02: "A", 0x04: "B", 0x08: "S", 0x10: "R", 0x20: "A", 0x40: "B"}
DOS_KIND = {"T": "Texte", "I": "Integer BASIC", "A": "Applesoft BASIC", "B": "Binaire", "S": "Type S",
            "R": "Relocatable"}
PRODOS_TYPES = {0x00: "UNK", 0x01: "BAD", 0x04: "TXT", 0x06: "BIN", 0x0F: "DIR", 0x19: "ADB", 0x1A: "AWP",
                0x1B: "ASP", 0xB3: "S16", 0xC0: "PNT", 0xC1: "PIC", 0xE0: "LBR", 0xEF: "PAS", 0xF0: "CMD",
                0xFA: "INT", 0xFB: "IVR", 0xFC: "BAS", 0xFD: "VAR", 0xFE: "REL", 0xFF: "SYS"}


class _Media:
    """Accès secteurs DOS / blocs ProDOS quel que soit l'ordre de l'image."""

    def __init__(self, data: bytes, po_order: bool):
        self.d, self.po = data, po_order
        self.ntracks = len(data) // 4096

    def sector(self, t: int, s: int) -> bytes:
        if not (0 <= t < self.ntracks and 0 <= s < 16):
            return b"\0" * 256
        idx = PO_OF_DOS[s] if self.po else s
        o = (t * 16 + idx) * 256
        return self.d[o:o + 256]

    def block(self, b: int) -> bytes:
        if self.po or len(self.d) != 143360:
            return self.d[b * 512:(b + 1) * 512].ljust(512, b"\0")
        t, k = divmod(b, 8)
        return self.sector(t, DOS_OF_PO[2 * k]) + self.sector(t, DOS_OF_PO[2 * k + 1])


def apple_text(b: bytes) -> str:
    out = []
    for c in b:
        c &= 0x7F
        if c == 0:
            break
        if c == 0x0D:
            out.append("\n")
        elif 32 <= c < 127 or c == 9:
            out.append(chr(c))
        else:
            out.append("·")
    return "".join(out)


# --------------------------------------------------------------------------
# DOS 3.3
# --------------------------------------------------------------------------
class DOS33FS(FileSystem):
    platform = "apple2"
    charset = "apple2"

    def __init__(self, m: _Media):
        super().__init__()
        self.m = m
        v = m.sector(17, 0)
        self.name = f"Apple DOS 3.{v[3] if v[3] < 10 else 3}" + (" (ordre ProDOS)" if m.po else "")
        self.label = f"Volume {v[6]}"
        self._deleted: List[Entry] = []
        t, s, seen = v[1], v[2], set()
        while t and (t, s) not in seen and len(seen) < 64:
            seen.add((t, s))
            c = m.sector(t, s)
            for i in range(7):
                e = c[0x0B + i * 35:0x0B + (i + 1) * 35]
                if e[0] == 0:
                    continue
                deleted = e[0] == 0xFF
                ft = e[2] & 0x7F
                code = DOS_TYPES.get(ft, "?")
                name = bytes(x & 0x7F for x in e[3:33]).decode("ascii", "replace").rstrip()
                if deleted:
                    name = name[:-1].rstrip() if len(name) > 29 else name
                ts = (e[0x20] if deleted else e[0], e[1])
                ent = Entry(name or "?", u16(e, 33) * 256, False, DOS_KIND.get(code, code),
                            "", ("L" if e[2] & 0x80 else "") + code,
                            {"type": code, "secteurs": u16(e, 33), "liste T/S": f"{ts[0]}/{ts[1]}"}, ts)
                if deleted:
                    ent.deleted = True
                    ent.kind = "Supprimé — " + ent.kind
                    self._deleted.append(ent)
                    continue
                self.root.add(ent)
                try:
                    raw = self._raw(ent)
                    if code == "B" and len(raw) >= 4:
                        ent.meta["chargement"] = f"${u16(raw, 0):04X}"
                        ent.size = u16(raw, 2)
                    elif code in ("A", "I") and len(raw) >= 2:
                        ent.size = u16(raw, 0)
                    elif code == "T":
                        z = raw.find(b"\0")
                        ent.size = z if z >= 0 else len(raw)
                except Exception:
                    pass
            t, s = c[1], c[2]
        free = sum(bin(int.from_bytes(v[0x38 + tr * 4:0x38 + tr * 4 + 2], "big")).count("1")
                   for tr in range(min(v[0x34] or 35, 50)))
        self.info = [("Système", self.name), ("Volume", str(v[6])), ("Pistes", str(v[0x34] or 35)),
                     ("Libre", human(free * 256)), ("Fichiers", str(len(self.files)))]

    def _raw(self, e: Entry) -> bytes:
        t, s = e.ref
        out, seen = bytearray(), set()
        while t and (t, s) not in seen and len(seen) < 200:
            seen.add((t, s))
            ts = self.m.sector(t, s)
            for k in range(122):
                dt, dsec = ts[0x0C + 2 * k], ts[0x0D + 2 * k]
                if dt == 0 and dsec == 0:
                    continue
                out += self.m.sector(dt, dsec)
            t, s = ts[1], ts[2]
        return bytes(out)

    def read(self, e: Entry) -> bytes:
        return self._raw(e)

    def content(self, e: Entry) -> bytes:
        raw = self._raw(e)
        code = e.meta.get("type")
        if code == "B" and len(raw) >= 4:
            return raw[4:4 + u16(raw, 2)]
        if code in ("A", "I") and len(raw) >= 2:
            return raw[2:2 + u16(raw, 0)]
        if code == "T":
            z = raw.find(b"\0")
            return raw[:z] if z >= 0 else raw
        return raw

    def deleted(self) -> List[Entry]:
        return list(self._deleted)

    def allocation(self):
        v = self.m.sector(17, 0)
        own = []
        order = [(t, s) for t in range(self.m.ntracks) for s in range(16)]
        idx = {ts: i for i, ts in enumerate(order)}
        for t, s in order:
            if t == 17 or t == 0:
                own.append("sys")
                continue
            bm = int.from_bytes(v[0x38 + t * 4:0x38 + t * 4 + 2], "big") if t < 50 else 0
            own.append("free" if bm >> s & 1 else "used")
        for e in self.files:
            t, s, seen = e.ref[0], e.ref[1], set()
            while t and (t, s) not in seen and len(seen) < 200:
                seen.add((t, s))
                if (t, s) in idx:
                    own[idx[t, s]] = e
                ts = self.m.sector(t, s)
                for k in range(122):
                    dt, dsec = ts[0x0C + 2 * k], ts[0x0D + 2 * k]
                    if (dt or dsec) and (dt, dsec) in idx:
                        own[idx[dt, dsec]] = e
                t, s = ts[1], ts[2]
        return 256, own


# --------------------------------------------------------------------------
# ProDOS
# --------------------------------------------------------------------------
def _pdate(b: bytes) -> str:
    d, t = u16(b, 0), u16(b, 2)
    if not d:
        return ""
    y, mo, da = d >> 9, (d >> 5) & 15, d & 31
    y += 1900 if y >= 40 else 2000
    if not (1 <= mo <= 12 and 1 <= da <= 31):
        return ""
    return f"{da:02d}/{mo:02d}/{y} {(t >> 8) & 31:02d}:{t & 63:02d}"


class ProDOSFS(FileSystem):
    platform = "apple2"
    charset = "apple2"

    def __init__(self, m: _Media, nblocks: int):
        super().__init__()
        self.m, self.nblocks = m, nblocks
        self.name = "ProDOS" + (" (ordre DOS)" if not m.po and len(m.d) == 143360 else "")
        hdr = m.block(2)
        self.label = hdr[5:5 + (hdr[4] & 15)].decode("ascii", "replace")
        self._seen = set()
        self._dir(2, self.root, 0)
        self.bitmap_ptr = u16(hdr, 0x27)
        total = u16(hdr, 0x29) or nblocks
        free = 0
        for b in range(total):
            blk = m.block(self.bitmap_ptr + b // 4096)
            if blk[(b % 4096) // 8] >> (7 - b % 8) & 1:
                free += 1
        self.info = [("Système", self.name), ("Volume", "/" + self.label), ("Blocs", str(total)),
                     ("Libre", human(free * 512)), ("Fichiers", str(len(self.files)))]

    def _dir(self, key: int, parent: Entry, depth: int):
        b, first = key, True
        while b and b not in self._seen and len(self._seen) < 4000:
            self._seen.add(b)
            blk = self.m.block(b)
            for i in range(13):
                o = 4 + i * 0x27
                if first and i == 0:
                    continue                     # en-tête de répertoire
                e = blk[o:o + 0x27]
                st, ln = e[0] >> 4, e[0] & 15
                if st == 0 or ln == 0:
                    continue
                name = e[1:1 + ln].decode("ascii", "replace")
                ft = e[0x10]
                kp = u16(e, 0x11)
                eof = e[0x15] | e[0x16] << 8 | e[0x17] << 16
                aux = u16(e, 0x1F)
                typ = PRODOS_TYPES.get(ft, f"${ft:02X}")
                meta = {"type": f"{typ} (${ft:02X})", "aux": f"${aux:04X}", "stockage": st,
                        "blocs": u16(e, 0x13)}
                if st == 0xD:
                    ent = parent.add(Entry(name, 0, True, "Dossier", _pdate(e[0x18:0x1C]), "", meta, (st, kp)))
                    if depth < 16:
                        self._dir(kp, ent, depth + 1)
                else:
                    parent.add(Entry(name, eof, False, typ, _pdate(e[0x21:0x25]),
                                     "" if e[0x1E] & 2 else "L", meta, (st, kp, ft, aux)))
            first = False
            b = u16(blk, 2)

    def _data_blocks(self, st: int, kp: int) -> List[int]:
        if st == 1:
            return [kp]
        if st == 2:
            ix = self.m.block(kp)
            return [ix[i] | ix[256 + i] << 8 for i in range(256)]
        if st == 3:
            mi = self.m.block(kp)
            out = []
            for j in range(128):
                p = mi[j] | mi[256 + j] << 8
                if p:
                    ix = self.m.block(p)
                    out += [ix[i] | ix[256 + i] << 8 for i in range(256)]
                else:
                    out += [0] * 256
            return out
        return []

    def read(self, e: Entry) -> bytes:
        st, kp = e.ref[0], e.ref[1]
        need = -(-e.size // 512)
        out = bytearray()
        for b in self._data_blocks(st, kp)[:need]:
            out += self.m.block(b) if b else b"\0" * 512
        return bytes(out[:e.size])

    def allocation(self):
        own = ["free"] * self.nblocks
        hdr = self.m.block(2)
        for b in range(self.nblocks):
            blk = self.m.block(self.bitmap_ptr + b // 4096)
            if not blk[(b % 4096) // 8] >> (7 - b % 8) & 1:
                own[b] = "used"
        for b in list(range(0, 2)) + list(self._seen):
            if b < self.nblocks:
                own[b] = "sys"
        nbm = -(-(u16(hdr, 0x29) or self.nblocks) // 4096)
        for b in range(self.bitmap_ptr, self.bitmap_ptr + nbm):
            if b < self.nblocks:
                own[b] = "sys"
        for e in self.root.walk():
            if e.is_dir:
                continue
            st, kp = e.ref[0], e.ref[1]
            if st in (2, 3) and kp < self.nblocks:
                own[kp] = e
            for b in self._data_blocks(st, kp)[:-(-e.size // 512)]:
                if 0 < b < self.nblocks:
                    own[b] = e
        return 512, own


# --------------------------------------------------------------------------
def _dos_ok(m: _Media) -> bool:
    v = m.sector(17, 0)
    return v[1] == 17 and 1 <= v[2] < 16 and v[0x35] == 16 and v[0x27] == 122


def _prodos_ok(m: _Media) -> bool:
    b = m.block(2)
    return u16(b, 0) == 0 and (b[4] >> 4) == 0xF and 1 <= (b[4] & 15) <= 15 and b[0x23] == 0x27


def probe(disk) -> List[FileSystem]:
    d = disk.linear()
    ext = disk.kind
    if d[:4] == b"2IMG":
        off, ln = u16(d, 0x18) | d[0x1A] << 16, int.from_bytes(d[0x1C:0x20], "little")
        po = int.from_bytes(d[0x0C:0x10], "little") == 1
        d = d[off:off + ln]
        orders = [po]
    elif len(d) == 143360:
        orders = [ext == ".po", ext != ".po"]
    elif len(d) in (409600, 819200) or (ext == ".po" and len(d) % 512 == 0):
        orders = [True]
    else:
        return []
    for po in orders:
        m = _Media(d, po)
        try:
            if len(d) == 143360 and _dos_ok(m):
                return [DOS33FS(m)]
            if _prodos_ok(m):
                return [ProDOSFS(m, len(d) // 512)]
        except Exception:
            continue
    return []


# --------------------------------------------------------------------------
# Applesoft BASIC
# --------------------------------------------------------------------------
APPLESOFT = ("END FOR NEXT DATA INPUT DEL DIM READ GR TEXT PR# IN# CALL PLOT HLIN VLIN HGR2 HGR "
             "HCOLOR= HPLOT DRAW XDRAW HTAB HOME ROT= SCALE= SHLOAD TRACE NOTRACE NORMAL INVERSE FLASH "
             "COLOR= POP VTAB HIMEM: LOMEM: ONERR RESUME RECALL STORE SPEED= LET GOTO RUN IF RESTORE & "
             "GOSUB RETURN REM STOP ON WAIT LOAD SAVE DEF POKE PRINT CONT LIST CLEAR GET NEW TAB( TO FN "
             "SPC( THEN AT NOT STEP + - * / ^ AND OR > = < SGN INT ABS USR FRE SCRN( PDL POS SQR RND LOG "
             "EXP COS SIN TAN ATN PEEK LEN STR$ VAL ASC CHR$ LEFT$ RIGHT$ MID$").split()


def _collapse(s: str) -> str:
    out, quote, prev = [], False, ""
    for ch in s:
        if ch == '"':
            quote = not quote
        if ch == " " and prev == " " and not quote:
            continue
        out.append(ch)
        prev = ch
    return "".join(out)


def applesoft(b: bytes) -> Optional[str]:
    p, lines, last = 0, [], -1
    while p + 4 <= len(b) and len(lines) < 20000:
        nxt = u16(b, p)
        if nxt == 0:
            break
        num = u16(b, p + 2)
        if num <= last:
            return None
        last = num
        p += 4
        s, quote = [], False
        while p < len(b) and b[p] != 0:
            c = b[p]
            if c == 0x22:
                quote = not quote
            if c >= 0x80 and not quote and c - 0x80 < len(APPLESOFT):
                s.append(f" {APPLESOFT[c - 0x80]} ")
            else:
                s.append(chr(c & 0x7F) if 32 <= (c & 0x7F) < 127 else "·")
            p += 1
        p += 1
        lines.append(f"{num} {_collapse(''.join(s)).strip()}")
    return "\n".join(lines) if lines else None
