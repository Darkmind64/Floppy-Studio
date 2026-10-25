"""Analyse du contenu des fichiers : texte, BASIC, images, audio, hexadécimal."""
from __future__ import annotations

import struct
import unicodedata
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from PySide6.QtGui import QImage

from . import basic as B
from .fs.base import Entry, FileSystem
from .fs import akai as AK
from .fs.cpm import amsdos_header
from .fs.thomson import binary_info

HEX_LIMIT = 512 * 1024


@dataclass
class Preview:
    kind: str                      # text | image | audio | hex
    title: str
    text: str = ""
    image: Optional[QImage] = None
    wav: Optional[bytes] = None
    note: str = ""
    converted: Optional[Tuple[str, bytes]] = None   # (extension, données) pour l'export converti
    props: List[Tuple[str, str]] = field(default_factory=list)
    data: bytes = b""
    charset: str = "latin-1"


# --------------------------------------------------------------------------
# Texte
# --------------------------------------------------------------------------
_ACCENTS = {0x41: "̀", 0x42: "́", 0x43: "̂", 0x48: "̈", 0x4B: "̧"}


def thomson_text(b: bytes) -> str:
    out, i = [], 0
    while i < len(b):
        c = b[i]
        if c == 0x16 and i + 2 < len(b) and b[i + 1] in _ACCENTS:
            out.append(unicodedata.normalize("NFC", chr(b[i + 2]) + _ACCENTS[b[i + 1]]))
            i += 3
            continue
        if c == 0x0D:
            out.append("\n")
            if i + 1 < len(b) and b[i + 1] == 0x0A:
                i += 1
        else:
            out.append(chr(c) if 32 <= c < 127 or c in (9, 10) else "·")
        i += 1
    return "".join(out)


def petscii_text(b: bytes) -> str:
    out = []
    for c in b:
        if c == 0x0D:
            out.append("\n")
        elif 0x41 <= c <= 0x5A:
            out.append(chr(c + 0x20))
        elif 0xC1 <= c <= 0xDA:
            out.append(chr(c - 0x80))
        elif 0x20 <= c <= 0x3F or c in (0x5B, 0x5D):
            out.append(chr(c))
        elif c == 0xA0:
            out.append(" ")
        else:
            out.append("·")
    return "".join(out)


def decode_text(b: bytes, charset: str) -> str:
    cut = b.find(b"\x1a")
    if cut >= 0 and charset in ("latin-1", "cp437") and cut > len(b) - 1024:
        b = b[:cut]
    if charset == "petscii":
        return petscii_text(b)
    if charset == "thomson":
        return thomson_text(b)
    if charset == "apple2":
        from .fs.apple import apple_text
        return apple_text(bytes(c if c != 0 else 0x20 for c in b))
    s = b.decode(charset, "replace")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(ch if ch >= " " or ch in "\n\t" else "·" for ch in s)


TEXT_LIMIT = 256 * 1024


def flow(txt: str, width: int = 128) -> str:
    """Coupe les lignes trop longues (affichage rapide des binaires)."""
    out = []
    for line in txt.split("\n"):
        if len(line) <= width:
            out.append(line)
        else:
            out.extend(line[i:i + width] for i in range(0, len(line), width))
    return "\n".join(out)


def looks_text(b: bytes, charset: str = "latin-1") -> bool:
    if not b:
        return False
    sample = b[:8192]
    cut = sample.find(b"\x1a")
    if cut > 16:
        sample = sample[:cut]
    if charset == "apple2":
        sample = bytes(c & 0x7F for c in sample)
        charset = "ascii"
    if charset == "petscii":
        good = sum(1 for c in sample if c in (13, 32) or 0x20 <= c <= 0x5D or 0xC1 <= c <= 0xDA)
    else:
        good = sum(1 for c in sample if c in (9, 10, 12, 13) or 32 <= c < 127 or
                   (c >= 128 and charset != "ascii") or c == 0x16)
    return good / len(sample) > 0.93 and sample.count(0) < len(sample) * 0.01


CHARSETS = [("Latin-1 (ISO 8859-1)", "latin-1"), ("PC CP437", "cp437"), ("PC CP850", "cp850"),
            ("Atari ST / ASCII", "ascii"), ("Amstrad CPC", "latin-1"), ("Thomson", "thomson"),
            ("Commodore PETSCII", "petscii"), ("Apple II", "apple2"), ("Mac Roman", "mac_roman"), ("UTF-8", "utf-8"),
            ("Windows-1252", "cp1252")]


def hexdump(b: bytes, limit: int = HEX_LIMIT, ascii_col: bool = True) -> str:
    lines = []
    view = b[:limit]
    for o in range(0, len(view), 16):
        chunk = view[o:o + 16]
        hx = " ".join(f"{x:02X}" for x in chunk[:8]) + "  " + " ".join(f"{x:02X}" for x in chunk[8:])
        if not ascii_col:
            lines.append(f"{o:06X}  {hx}")
            continue
        asc = "".join(chr(x) if 32 <= x < 127 else "." for x in chunk)
        lines.append(f"{o:06X}  {hx:<49}  {asc}")
    if len(b) > limit:
        lines.append(f"… ({len(b) - limit} octets non affichés)")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# BASIC Commodore V2
# --------------------------------------------------------------------------
C64_TOKENS = ("END FOR NEXT DATA INPUT# INPUT DIM READ LET GOTO RUN IF RESTORE GOSUB RETURN REM "
              "STOP ON WAIT LOAD SAVE VERIFY DEF POKE PRINT# PRINT CONT LIST CLR CMD SYS OPEN CLOSE "
              "GET NEW TAB( TO FN SPC( THEN NOT STEP + - * / ^ AND OR > = < SGN INT ABS USR FRE POS "
              "SQR RND LOG EXP COS SIN TAN ATN PEEK LEN STR$ VAL ASC CHR$ LEFT$ RIGHT$ MID$ GO").split()


def c64_basic(b: bytes) -> Optional[str]:
    if len(b) < 6 or (b[0], b[1]) not in ((0x01, 0x08), (0x01, 0x04), (0x01, 0x1C), (0x01, 0x12)):
        return None
    p, lines, guard = 2, [], 0
    while p + 4 <= len(b) and guard < 10000:
        guard += 1
        nxt = b[p] | b[p + 1] << 8
        if nxt == 0:
            break
        num = b[p + 2] | b[p + 3] << 8
        p += 4
        s, quote = [], False
        while p < len(b) and b[p] != 0:
            c = b[p]
            if c == 0x22:
                quote = not quote
            if c >= 0x80 and not quote and c - 0x80 < len(C64_TOKENS):
                s.append(C64_TOKENS[c - 0x80])
            elif c == 0xFF and not quote:
                s.append("π")
            else:
                s.append(chr(c) if 0x20 <= c < 0x60 else chr(c - 0x80) if 0xC1 <= c <= 0xDA
                         else "·")
            p += 1
        p += 1
        lines.append(f"{num} {''.join(s)}")
    return "\n".join(lines) if lines else None


# --------------------------------------------------------------------------
# Images
# --------------------------------------------------------------------------
def _qimage(w: int, h: int, pixels: List[int]) -> QImage:
    buf = struct.pack(f"<{w * h}I", *[0xFF000000 | p for p in pixels[:w * h]])
    return QImage(buf, w, h, w * 4, QImage.Format_RGB32).copy()


def _rgb(r, g, b):
    return (r << 16) | (g << 8) | b


def _byterun1(src: bytes, need: int) -> bytes:
    out, i = bytearray(), 0
    while i < len(src) and len(out) < need:
        n = src[i]
        i += 1
        if n < 128:
            out += src[i:i + n + 1]
            i += n + 1
        elif n > 128:
            if i < len(src):
                out += bytes([src[i]]) * (257 - n)
            i += 1
    return bytes(out)


def iff_chunks(b: bytes):
    if b[:4] != b"FORM" or len(b) < 12:
        return None, {}
    form, pos, ch = b[8:12], 12, {}
    end = min(len(b), 8 + struct.unpack(">I", b[4:8])[0])
    while pos + 8 <= end:
        cid = b[pos:pos + 4]
        size = struct.unpack(">I", b[pos + 4:pos + 8])[0]
        ch.setdefault(cid, b[pos + 8:pos + 8 + size])
        pos += 8 + size + (size & 1)
    return form, ch


def ilbm(b: bytes) -> Optional[QImage]:
    form, ch = iff_chunks(b)
    if form not in (b"ILBM", b"PBM ") or b"BMHD" not in ch or b"BODY" not in ch:
        return None
    w, h, _, _, npl, mask, comp = struct.unpack(">HHhhBBB", ch[b"BMHD"][:11])
    cmap = ch.get(b"CMAP", b"")
    pal = [_rgb(*cmap[i:i + 3]) for i in range(0, len(cmap) - 2, 3)] or \
          [_rgb(i * 255 // 15, i * 255 // 15, i * 255 // 15) for i in range(16)]
    camg = struct.unpack(">I", ch[b"CAMG"][:4])[0] if b"CAMG" in ch else 0
    ham, ehb = bool(camg & 0x800), bool(camg & 0x80)
    if ehb and len(pal) <= 32:
        pal = pal[:32] + [((p >> 1) & 0x7F7F7F) for p in pal[:32]]
    body = ch[b"BODY"]
    if form == b"PBM ":
        data = _byterun1(body, w * h) if comp else body
        return _qimage(w, h, [pal[x] if x < len(pal) else 0 for x in data[:w * h]])
    bpr = ((w + 15) // 16) * 2
    planes = npl + (1 if mask == 1 else 0)
    need = bpr * planes * h
    data = _byterun1(body, need) if comp == 1 else body
    if len(data) < need:
        data = data.ljust(need, b"\0")
    px = []
    for y in range(h):
        row = [0] * w
        for p in range(npl):
            o = (y * planes + p) * bpr
            line = data[o:o + bpr]
            bit = 1 << p
            for x in range(w):
                if line[x >> 3] & (0x80 >> (x & 7)):
                    row[x] |= bit
        if ham:
            sh = 6 if npl >= 8 else 4
            cur = pal[0] if pal else 0
            for x in range(w):
                v = row[x]
                ctl, val = v >> sh, v & ((1 << sh) - 1)
                full = val << (8 - sh) | (val >> (2 * sh - 8) if sh > 4 else val)
                if ctl == 0:
                    cur = pal[val] if val < len(pal) else 0
                elif ctl == 1:
                    cur = (cur & 0xFFFF00) | full
                elif ctl == 2:
                    cur = (cur & 0x00FFFF) | full << 16
                else:
                    cur = (cur & 0xFF00FF) | full << 8
                px.append(cur)
        else:
            px.extend(pal[v] if v < len(pal) else 0 for v in row)
    return _qimage(w, h, px)


def _st_color(v: int) -> int:
    def c(n):
        return (((n & 7) << 1) | ((n >> 3) & 1)) * 17
    return _rgb(c(v >> 8 & 0xF), c(v >> 4 & 0xF), c(v & 0xF))


def _st_planar(data: bytes, res: int, pal: List[int]) -> QImage:
    w, h, npl = {0: (320, 200, 4), 1: (640, 200, 2), 2: (640, 400, 1)}[res]
    if res == 2:
        pal = [0xFFFFFF, 0x000000]
    px, o = [], 0
    data = data.ljust(32000, b"\0")
    for y in range(h):
        for g in range(w // 16):
            words = struct.unpack_from(f">{npl}H", data, o)
            o += npl * 2
            for bit in range(15, -1, -1):
                v = 0
                for p in range(npl):
                    v |= ((words[p] >> bit) & 1) << p
                px.append(pal[v] if v < len(pal) else 0)
    return _qimage(w, h, px)


def degas(b: bytes, ext: str) -> Optional[QImage]:
    if len(b) < 34:
        return None
    res = struct.unpack(">H", b[:2])[0]
    comp = bool(res & 0x8000)
    res &= 3
    if res > 2:
        return None
    pal = [_st_color(v) for v in struct.unpack(">16H", b[2:34])]
    if not comp:
        if len(b) < 32034:
            return None
        return _st_planar(b[34:34 + 32000], res, pal)
    npl = {0: 4, 1: 2, 2: 1}[res]
    lb = {0: 40, 1: 80, 2: 80}[res]
    h = 400 if res == 2 else 200
    raw = _byterun1(b[34:], npl * lb * h)
    out = bytearray(32000)
    for y in range(h):
        for p in range(npl):
            line = raw[(y * npl + p) * lb:(y * npl + p + 1) * lb]
            for g in range(lb // 2):
                o = y * lb * npl + g * npl * 2 + p * 2
                out[o:o + 2] = line[g * 2:g * 2 + 2]
    return _st_planar(bytes(out), res, pal)


def neo(b: bytes) -> Optional[QImage]:
    if len(b) < 32128:
        return None
    res = struct.unpack(">H", b[2:4])[0]
    if res > 2:
        return None
    pal = [_st_color(v) for v in struct.unpack(">16H", b[4:36])]
    return _st_planar(b[128:128 + 32000], res, pal)


def pcx(b: bytes) -> Optional[QImage]:
    if len(b) < 129 or b[0] != 0x0A or b[2] != 1:
        return None
    bpp, (x0, y0, x1, y1) = b[3], struct.unpack("<4H", b[4:12])
    npl, bpl = b[65], struct.unpack("<H", b[66:68])[0]
    w, h = x1 - x0 + 1, y1 - y0 + 1
    if not (0 < w <= 4096 and 0 < h <= 4096):
        return None
    need = npl * bpl * h
    raw, i = bytearray(), 128
    while len(raw) < need and i < len(b):
        c = b[i]
        i += 1
        if c & 0xC0 == 0xC0 and i < len(b):
            raw += bytes([b[i]]) * (c & 0x3F)
            i += 1
        else:
            raw.append(c)
    raw = bytes(raw).ljust(need, b"\0")
    hpal = [_rgb(*b[16 + k * 3:19 + k * 3]) for k in range(16)]
    tail = b[-768:]
    pal = [_rgb(*tail[k * 3:k * 3 + 3]) for k in range(256)] \
        if len(b) > 769 and b[-769] == 0x0C else [_rgb(k, k, k) for k in range(256)]
    px = []
    for y in range(h):
        if bpp == 8 and npl == 1:
            px.extend(pal[v] for v in raw[y * bpl:y * bpl + w])
        elif bpp == 8 and npl == 3:
            o = y * 3 * bpl
            px.extend(_rgb(raw[o + x], raw[o + bpl + x], raw[o + 2 * bpl + x]) for x in range(w))
        elif bpp == 1:
            for x in range(w):
                v = 0
                for p in range(npl):
                    if raw[(y * npl + p) * bpl + (x >> 3)] & (0x80 >> (x & 7)):
                        v |= 1 << p
                px.append(hpal[v] if npl > 1 else (0xFFFFFF if v else 0))
        elif bpp == 2 and npl == 1:
            for x in range(w):
                v = (raw[y * bpl + (x >> 2)] >> (6 - 2 * (x & 3))) & 3
                px.append(hpal[v])
        else:
            return None
    return _qimage(w, h, px)


CPC_HW = [(0, 0, 128), (255, 255, 0), (0, 255, 255), (255, 0, 0)]
CPC_MODE0 = [(0, 0, 128), (255, 255, 0), (0, 255, 255), (255, 0, 0), (255, 255, 255), (0, 0, 0),
             (0, 0, 255), (255, 0, 255), (0, 128, 128), (128, 128, 0), (128, 128, 255),
             (255, 128, 128), (0, 255, 0), (128, 255, 128), (0, 0, 128), (255, 128, 128)]


def cpc_screen(b: bytes, mode: int = 1) -> Optional[QImage]:
    if not 16000 <= len(b) <= 16384:
        return None
    b = b.ljust(16384, b"\0")
    w = {0: 160, 1: 320, 2: 640}[mode]
    px = []
    for y in range(200):
        base = (y // 8) * 80 + (y % 8) * 2048
        for xb in range(80):
            v = b[base + xb]
            if mode == 1:
                for i in range(4):
                    c = ((v >> (7 - i)) & 1) | (((v >> (3 - i)) & 1) << 1)
                    px.append(_rgb(*CPC_HW[c]))
            elif mode == 0:
                for i in range(2):
                    c = ((v >> (7 - i)) & 1) | (((v >> (3 - i)) & 1) << 1) | \
                        (((v >> (5 - i)) & 1) << 2) | (((v >> (1 - i)) & 1) << 3)
                    px.append(_rgb(*CPC_MODE0[c]))
            else:
                for i in range(8):
                    px.append(0xFFFF00 if v >> (7 - i) & 1 else 0x000080)
    return _qimage(w, 200, px)


C64_PAL = [0x000000, 0xFFFFFF, 0x68372B, 0x70A4B2, 0x6F3D86, 0x588D43, 0x352879, 0xB8C76F,
           0x6F4F25, 0x433900, 0x9A6759, 0x444444, 0x6C6C6C, 0x9AD284, 0x6C5EB5, 0x959595]


def koala(b: bytes) -> Optional[QImage]:
    if len(b) in (10003, 10004) and b[0] == 0x00 and b[1] in (0x60, 0x40):
        b = b[2:]
    if len(b) not in (10001, 10002):
        return None
    bmp, scr, col, bg = b[:8000], b[8000:9000], b[9000:10000], b[10000] & 15
    px = [0] * (160 * 200)
    for cy in range(25):
        for cx in range(40):
            ci = cy * 40 + cx
            cols = [bg, scr[ci] >> 4, scr[ci] & 15, col[ci] & 15]
            for r in range(8):
                v = bmp[ci * 8 + r]
                y = cy * 8 + r
                for k in range(4):
                    px[y * 160 + cx * 4 + k] = C64_PAL[cols[(v >> (6 - 2 * k)) & 3]]
    img = _qimage(160, 200, px)
    return img.scaled(320, 200)


# --------------------------------------------------------------------------
# Audio
# --------------------------------------------------------------------------
def svx8_to_wav(b: bytes) -> Optional[bytes]:
    form, ch = iff_chunks(b)
    if form != b"8SVX" or b"BODY" not in ch:
        return None
    rate = struct.unpack(">H", ch[b"VHDR"][12:14])[0] if b"VHDR" in ch else 8363
    pcm = bytes((x + 128) & 0xFF for x in ch[b"BODY"])
    return AK.wav16(pcm, rate or 8363, 1, 8)


# --------------------------------------------------------------------------
# Analyse globale
# --------------------------------------------------------------------------
IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "bmp", "tga", "tif", "tiff", "ico", "webp", "ppm", "pgm"}


def binary_props(d: bytes, platform: str, ext: str) -> List[Tuple[str, str]]:
    """En-têtes d'exécutables reconnus."""
    out: List[Tuple[str, str]] = []
    be32 = lambda o: int.from_bytes(d[o:o + 4], "big")
    if d[:2] == b"\x60\x1A" and len(d) >= 28:
        out += [("Exécutable", "Atari TOS (PRG)"), ("Segment texte", f"{be32(2)} o"),
                ("Segment données", f"{be32(6)} o"), ("BSS", f"{be32(10)} o"),
                ("Symboles", f"{be32(14)} o"), ("Drapeaux", f"0x{be32(22):08X}"),
                ("Relocation", "non" if d[26:28] != b"\0\0" else "oui")]
    elif d[:4] == b"\x00\x00\x03\xF3":
        try:
            p = 4
            while be32(p):
                p += 4 + 4 * be32(p)
            p += 4
            n, first, last = be32(p), be32(p + 4), be32(p + 8)
            sizes = [be32(p + 12 + 4 * i) for i in range(last - first + 1)]
            mem = {0: "", 1: " CHIP", 2: " FAST"}
            out += [("Exécutable", "AmigaDOS (hunks)"), ("Hunks", str(n)),
                    ("Tailles", ", ".join(f"{(x & 0x3FFFFFFF) * 4} o{mem.get(x >> 30, '')}" for x in sizes[:12]))]
        except Exception:
            pass
    elif d[:2] in (b"MZ", b"ZM") and len(d) >= 32:
        u = lambda o: d[o] | d[o + 1] << 8
        pages, last = u(4), u(2)
        size = (pages - 1) * 512 + (last or 512) if pages else len(d)
        out += [("Exécutable", "DOS MZ (.EXE)"), ("Taille chargée", f"{size} o"),
                ("En-tête", f"{u(8) * 16} o"), ("Relocations", str(u(6))),
                ("CS:IP", f"{u(0x16):04X}:{u(0x14):04X}"), ("SS:SP", f"{u(0x0E):04X}:{u(0x10):04X}"),
                ("Mémoire min/max", f"{u(0x0A) * 16} / {u(0x0C) * 16} o")]
        if u(0x18) >= 0x40 and len(d) > 0x40:
            off = int.from_bytes(d[0x3C:0x40], "little")
            sig = d[off:off + 2] if off < len(d) else b""
            if sig in (b"NE", b"PE", b"LE", b"LX"):
                out.append(("Format étendu", {b"NE": "Windows 16 bits (NE)", b"PE": "Windows 32/64 bits (PE)",
                                             b"LE": "VxD / DOS4GW (LE)", b"LX": "OS/2 (LX)"}[sig]))
    elif platform == "msx" and d[:1] == b"\xFE" and len(d) >= 7:
        u = lambda o: d[o] | d[o + 1] << 8
        out += [("Exécutable", "MSX BLOAD"), ("Début", f"&H{u(1):04X}"), ("Fin", f"&H{u(3):04X}"),
                ("Exécution", f"&H{u(5):04X}")]
    elif ext == "com" and platform in ("pc", "msx", "cpc"):
        out.append(("Exécutable", "programme .COM chargé en 0100h"))
    return out


def analyse(fs: FileSystem, e: Entry, raw: bytes) -> List[Preview]:
    data = fs.content(e)
    ext = e.ext
    out: List[Preview] = []
    props: List[Tuple[str, str]] = [(k, str(v)) for k, v in e.meta.items()]

    # En-têtes système
    if fs.platform == "cpc":
        h = amsdos_header(raw)
        if h:
            props += [("Longueur", str(h["real"] or h["length"]))]
    if fs.platform == "thomson" and e.meta.get("type") == 2:
        bi = binary_info(data)
        if bi:
            props += [("Blocs", ", ".join(f"&{a:04X} ({l} o)" for a, l in bi["blocs"])),
                      ("Exécution", f"&{bi['exec']:04X}")]
    if fs.platform == "c64" and len(data) >= 2:
        props.append(("Adresse de chargement", f"${data[0] | data[1] << 8:04X}"))
    props += binary_props(data, fs.platform, ext)

    # Images
    img = None
    if ext in IMAGE_EXT or data[:4] in (b"\x89PNG", b"GIF8") or data[:2] in (b"BM", b"\xff\xd8"):
        q = QImage.fromData(data)
        img = q if not q.isNull() else None
    if img is None and data[:4] == b"FORM":
        img = ilbm(data)
    if img is None and ext in ("pi1", "pi2", "pi3", "pc1", "pc2", "pc3"):
        img = degas(data, ext)
    if img is None and ext == "neo":
        img = neo(data)
    if img is None and (ext == "pcx" or data[:1] == b"\x0a" and len(data) > 128 and data[2] == 1):
        img = pcx(data)
    if img is None and fs.platform == "c64" and ext in ("prg", "koa", "kla") and len(data) in (10003, 10004):
        img = koala(data)
    if img is None and fs.platform == "cpc" and len(data) in range(16000, 16385) and \
            (ext in ("scr", "bin", "") or (raw[21:23] == b"\x00\xc0")):
        img = cpc_screen(data, 1)
    if img is not None:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        out.append(Preview("image", "Image", image=img, note=f"{img.width()} × {img.height()}",
                           converted=("png", bytes(ba))))

    # Audio
    wav = None
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        wav = data
    elif data[:4] == b"FORM" and data[8:12] == b"8SVX":
        wav = svx8_to_wav(data)
    elif fs.platform == "akai" and e.ref and e.ref[1] in AK.SAMPLE_TYPES:
        wav = AK.sample_to_wav(data, e.ref[1])
    if wav:
        out.append(Preview("audio", "Audio", wav=wav, converted=("wav", wav)))

    # BASIC
    listing = c64_basic(data) if fs.platform == "c64" else None
    dialect = "BASIC V2" if listing else ""
    if not listing:
        r = B.detokenize(fs.platform, data, e.meta, ext)
        if r:
            dialect, listing = r
    if listing:
        props.append(("BASIC", dialect))
        out.append(Preview("text", "BASIC", text=listing, note=dialect,
                           converted=("txt", listing.encode("utf-8"))))

    # Code machine
    try:
        from . import disasm as DA
        g = DA.guess(fs.platform, data, e.meta, ext, raw)
    except Exception:
        g = None
    if g:
        out.append(Preview("disasm", "Désassemblage", data=g[1], note=g[3],
                           props=[("cpu", g[0]), ("org", str(g[2]))]))

    # Texte (toujours proposé ; forcé si le contenu n'a pas l'air textuel)
    cs = fs.charset
    is_txt = looks_text(data, cs)
    txt = decode_text(data, cs) if is_txt else ""
    out.append(Preview("textraw", "Texte", text=txt, data=data, charset=cs,
                       note="" if is_txt else "contenu binaire : affichage forcé",
                       converted=None if listing or not is_txt else ("txt", txt.encode("utf-8"))))
    hx = Preview("hex", "Hexa", data=raw, charset=cs)
    if is_txt or listing:
        out.append(hx)
    else:                               # binaire : l'hexa d'abord
        out.insert(len(out) - 1, hx)
    for p in out:
        if p.kind != "disasm":
            p.props = props
    return out


def runnable(fs: FileSystem, e: Entry, data: bytes = b"") -> bool:
    if e.is_dir:
        return False
    ext = e.ext
    return {
        "pc": ext in ("exe", "com", "bat"),
        "msx": ext in ("com", "bas"),
        "atarist": ext in ("prg", "tos", "ttp", "app"),
        "c64": ext == "prg",
        "cpc": e.kind in ("BASIC", "Binaire", "BASIC protégé", "Binaire protégé"),
        "thomson": e.meta.get("type") in (0, 2),
        "apple2": str(e.meta.get("type", "")).startswith(("A", "B", "BAS", "BIN", "SYS")),
        "amiga": data[:4] == b"\x00\x00\x03\xf3",
    }.get(fs.platform, False)
