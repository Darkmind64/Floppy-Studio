"""Conversions de fichiers : listing → BASIC tokenisé, image → écran CPC, WAV → sample Akai."""
from __future__ import annotations

import io
import math
import re
import struct
import wave
from decimal import Decimal
from typing import List, Optional, Tuple

from . import basic as B


# --------------------------------------------------------------------------
# Outils communs
# --------------------------------------------------------------------------
def _lines(text: str) -> List[Tuple[int, str]]:
    out = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = re.match(r"\s*(\d+)\s?(.*)$", raw)
        if m and raw.strip():
            out.append((int(m.group(1)), m.group(2).rstrip()))
    out.sort(key=lambda x: x[0])
    return out


def _word(s: str, i: int) -> str:
    j = i
    while j < len(s) and (s[j].isalnum() or s[j] == "."):
        j += 1
    return s[i:j]


LINE_KW = {"GOTO", "GOSUB", "THEN", "ELSE", "RESTORE", "RUN", "LIST", "DELETE", "RENUM", "AUTO", "EDIT",
           "RESUME", "LLIST", "GO"}


# --------------------------------------------------------------------------
# Locomotive BASIC
# --------------------------------------------------------------------------
_LOCO_KW = {v: k for k, v in B.LOCO.items() if v[0].isalpha()}
_LOCO_FN = {v: k for k, v in B.LOCO_FN.items()}
_LOCO_OPS = [(">=", 0xF0), ("<=", 0xF3), ("<>", 0xF2), ("=>", 0xF0), ("=<", 0xF3), (">", 0xEE), ("=", 0xEF),
             ("<", 0xF1), ("+", 0xF4), ("-", 0xF5), ("*", 0xF6), ("/", 0xF7), ("^", 0xF8), ("\\", 0xF9)]


def _loco_float(v: float) -> bytes:
    if v == 0:
        return b"\0\0\0\0\0"
    neg = v < 0
    v = abs(v)
    e = math.floor(math.log2(v)) + 1
    mant = round(v / 2.0 ** e * 2 ** 32)
    if mant >= 2 ** 32:
        mant >>= 1
        e += 1
    mant &= 0x7FFFFFFF
    if neg:
        mant |= 0x80000000
    return mant.to_bytes(4, "little") + bytes([(e + 128) & 0xFF])


def _loco_number(tok: str, linectx: bool) -> bytes:
    if linectx and tok.isdigit():
        n = int(tok)
        return bytes([0x1E, n & 255, n >> 8 & 255])
    if tok.isdigit():
        n = int(tok)
        if n <= 9:
            return bytes([0x0E + n])
        if n <= 255:
            return bytes([0x19, n])
        if n <= 32767:
            return bytes([0x1A, n & 255, n >> 8])
    return b"\x1F" + _loco_float(float(tok))


def tokenize_locomotive(text: str) -> bytes:
    prog = bytearray()
    for num, src in _lines(text):
        body = bytearray()
        i, linectx = 0, False
        s = src
        while i < len(s):
            ch = s[i]
            if ch == '"':
                j = s.find('"', i + 1)
                j = len(s) if j < 0 else j + 1
                body += s[i:j].encode("latin-1", "replace")
                i = j
                continue
            if ch == ":":
                body.append(0x01)
                i += 1
                linectx = False
                continue
            if ch == "'":
                body += b"\x01\xC0" + s[i + 1:].encode("latin-1", "replace")
                break
            if ch == "|":
                m = re.match(r"\|([A-Za-z0-9.]+)", s[i:])
                if m:
                    nm = m.group(1).upper().encode()
                    body += b"\x7C\x00" + nm[:-1] + bytes([nm[-1] | 0x80])
                    i += len(m.group(0))
                    continue
            if ch == "&":
                m = re.match(r"&(X)([01]+)|&H?([0-9A-Fa-f]+)", s[i:], re.I)
                if m:
                    if m.group(1):
                        v = int(m.group(2), 2)
                        body += bytes([0x1B, v & 255, v >> 8 & 255])
                    else:
                        v = int(m.group(3), 16) & 0xFFFF
                        body += bytes([0x1C, v & 255, v >> 8])
                    i += len(m.group(0))
                    continue
            if ch.isdigit() or (ch == "." and i + 1 < len(s) and s[i + 1].isdigit()):
                m = re.match(r"\d*\.?\d*(?:[Ee][+-]?\d+)?", s[i:])
                tok = m.group(0)
                body += _loco_number(tok, linectx)
                i += len(tok)
                continue
            if ch.isalpha():
                w = _word(s, i)
                up = w.upper()
                dollar = i + len(w) < len(s) and s[i + len(w)] == "$"
                # mots-clés composés
                if up == "ON":
                    rest = s[i + 2:].upper()
                    m = re.match(r"\s*(BREAK|ERROR\s+GOTO|SQ)\b", rest)
                    if m:
                        code = {"BREAK": 0xB3, "SQ": 0xB5}.get(m.group(1).split()[0], 0xB4)
                        body.append(code)
                        i += 2 + len(m.group(0))
                        linectx = code == 0xB4
                        continue
                cand = up + "$" if dollar else up
                if cand in _LOCO_KW or cand in _LOCO_FN:
                    if cand in _LOCO_KW:
                        code = _LOCO_KW[cand]
                        if code == 0x97:                       # ELSE
                            body += b"\x01"
                        body.append(code)
                    else:
                        body += bytes([0xFF, _LOCO_FN[cand]])
                    i += len(w) + (1 if dollar else 0)
                    linectx = cand in LINE_KW
                    if cand == "REM":
                        body += s[i:].encode("latin-1", "replace")
                        break
                    if cand == "DATA":
                        j = s.find(":", i)
                        j = len(s) if j < 0 else j
                        body += s[i:j].encode("latin-1", "replace")
                        i = j
                    continue
                if up in _LOCO_KW or up in _LOCO_FN:
                    code = _LOCO_KW.get(up)
                    body += bytes([code]) if code is not None else bytes([0xFF, _LOCO_FN[up]])
                    i += len(w)
                    linectx = up in LINE_KW
                    continue
                # variable
                suf = s[i + len(w)] if i + len(w) < len(s) and s[i + len(w)] in "%$!" else ""
                code = {"%": 0x02, "$": 0x03, "!": 0x04}.get(suf, 0x0D)
                nm = w.encode("latin-1", "replace")
                body += bytes([code, 0, 0]) + nm[:-1] + bytes([nm[-1] | 0x80])
                i += len(w) + len(suf)
                linectx = False
                continue
            op = next(((t, c) for t, c in _LOCO_OPS if s.startswith(t, i)), None)
            if op:
                body.append(op[1])
                i += len(op[0])
                if op[0] != "-":
                    linectx = False
                continue
            if ch not in " ,":
                linectx = linectx and ch in " ,-"
            body += ch.encode("latin-1", "replace")
            i += 1
        ln = len(body) + 5
        prog += struct.pack("<HH", ln, num) + body + b"\0"
    return bytes(prog + b"\0\0")


def amsdos_file(name: str, data: bytes, ftype: int = 0, load: int = 0x170, exec_: int = 0) -> bytes:
    base, _, ext = name.upper().rpartition(".") if "." in name else (name.upper(), "", "")
    h = bytearray(128)
    h[1:9] = base[:8].ljust(8).encode("ascii", "replace")
    h[9:12] = ext[:3].ljust(3).encode("ascii", "replace")
    h[18] = ftype
    struct.pack_into("<HHH", h, 21, load, len(data), exec_)
    h[64:67] = len(data).to_bytes(3, "little")
    struct.pack_into("<H", h, 67, sum(h[:67]) & 0xFFFF)
    return bytes(h) + data


# --------------------------------------------------------------------------
# MSX-BASIC / GW-BASIC
# --------------------------------------------------------------------------
def _ms_tables(dialect: str):
    if dialect == "msx":
        main = {v: k for k, v in B.MSX.items() if v[0].isalpha()}
        ext = {v: (0xFF, k) for k, v in B.MSX_FF.items()}
    else:
        main = {v: k for k, v in B.GW.items() if v[0].isalpha()}
        ext = {}
        for pre, tbl in ((0xFD, B.GW_FD), (0xFE, B.GW_FE), (0xFF, B.GW_FF)):
            ext.update({v: (pre, k) for k, v in tbl.items()})
    ops = {"msx": [(">", 0xEE), ("=", 0xEF), ("<", 0xF0), ("+", 0xF1), ("-", 0xF2), ("*", 0xF3), ("/", 0xF4),
                   ("^", 0xF5), ("\\", 0xFC)],
           "gw": [(">", 0xE6), ("=", 0xE7), ("<", 0xE8), ("+", 0xE9), ("-", 0xEA), ("*", 0xEB), ("/", 0xEC),
                  ("^", 0xED), ("\\", 0xF4)]}[dialect]
    return main, ext, ops


def _bcd_single(v: float) -> bytes:
    if v == 0:
        return b"\0\0\0\0"
    d = Decimal(repr(abs(v))).normalize()
    t = d.as_tuple()
    digits = "".join(map(str, t.digits))
    exp = len(digits) + t.exponent
    digits = (digits + "000000")[:6]
    b0 = (exp + 0x40) & 0x7F | (0x80 if v < 0 else 0)
    return bytes([b0]) + bytes.fromhex(digits)


def _mbf_single(v: float) -> bytes:
    if v == 0:
        return b"\0\0\0\0"
    neg = v < 0
    v = abs(v)
    e = math.floor(math.log2(v)) + 1
    mant = round(v / 2.0 ** e * 2 ** 24)
    if mant >= 2 ** 24:
        mant >>= 1
        e += 1
    mant &= 0x7FFFFF
    if neg:
        mant |= 0x800000
    return mant.to_bytes(3, "little") + bytes([(e + 128) & 0xFF])


def tokenize_ms(text: str, dialect: str = "msx") -> bytes:
    main, ext, ops = _ms_tables(dialect)
    base_addr = 0x8001 if dialect == "msx" else 0x126E
    names = sorted(set(main) | set(ext), key=len, reverse=True)
    apos = 0xE6 if dialect == "msx" else 0xD9
    lines = []
    for num, s in _lines(text):
        body = bytearray()
        i, linectx = 0, False
        while i < len(s):
            ch = s[i]
            if ch == '"':
                j = s.find('"', i + 1)
                j = len(s) if j < 0 else j + 1
                body += s[i:j].encode("latin-1", "replace")
                i = j
                continue
            if ch == "'":
                body += bytes([0x3A, 0x8F, apos]) + s[i + 1:].encode("latin-1", "replace")
                break
            if ch == "&":
                m = re.match(r"&([HhOoBb])([0-9A-Fa-f]+)", s[i:])
                if m:
                    kind = m.group(1).upper()
                    if kind == "B":
                        body += m.group(0).encode()
                    else:
                        v = int(m.group(2), 16 if kind == "H" else 8) & 0xFFFF
                        body += bytes([0x0C if kind == "H" else 0x0B, v & 255, v >> 8])
                    i += len(m.group(0))
                    continue
            if ch.isdigit() or (ch == "." and i + 1 < len(s) and s[i + 1].isdigit()):
                m = re.match(r"\d*\.?\d*(?:[EeDd][+-]?\d+)?[!#%]?", s[i:])
                tok = m.group(0)
                i += len(tok)
                core = tok.rstrip("!#%")
                if linectx and core.isdigit():
                    n = int(core)
                    body += bytes([0x0E, n & 255, n >> 8 & 255])
                elif core.isdigit() and int(core) <= 32767 and not tok.endswith(("!", "#")):
                    n = int(core)
                    body += bytes([0x11 + n]) if n <= 9 else bytes([0x0F, n]) if n <= 255 else \
                        bytes([0x1C, n & 255, n >> 8])
                else:
                    v = float(core.replace("D", "E").replace("d", "e"))
                    body += b"\x1D" + (_bcd_single(v) if dialect == "msx" else _mbf_single(v))
                continue
            if ch.isalpha():
                up = s[i:].upper()
                kw = next((n for n in names if up.startswith(n)), None)
                if kw:
                    if kw in main:
                        code = main[kw]
                        if code == 0xA1:                  # ELSE
                            body.append(0x3A)
                        body.append(code)
                        if dialect == "gw" and code == 0xB1:   # WHILE
                            body.append(0xE9)
                    else:
                        body += bytes(ext[kw])
                    i += len(kw)
                    linectx = kw in LINE_KW
                    if kw == "REM":
                        body += s[i:].encode("latin-1", "replace")
                        break
                    if kw == "DATA":
                        j = s.find(":", i)
                        j = len(s) if j < 0 else j
                        body += s[i:j].encode("latin-1", "replace")
                        i = j
                    continue
                m = re.match(r"[A-Za-z][A-Za-z0-9]*[$%!#]?", s[i:])
                body += m.group(0).upper().encode()
                i += len(m.group(0))
                linectx = False
                continue
            op = next(((t, c) for t, c in ops if s.startswith(t, i)), None)
            if op:
                body.append(op[1])
                i += 1
                linectx = False
                continue
            if ch == ":":
                linectx = False
            body += ch.encode("latin-1", "replace")
            i += 1
        lines.append((num, bytes(body)))
    out = bytearray(b"\xFF")
    addr = base_addr
    for num, body in lines:
        nxt = addr + 4 + len(body) + 1
        out += struct.pack("<HH", nxt, num) + body + b"\0"
        addr = nxt
    out += b"\0\0"
    return bytes(out)


# --------------------------------------------------------------------------
# Image → écran CPC
# --------------------------------------------------------------------------
LEVELS = (0, 128, 255)
CPC_FW = [(LEVELS[(n // 3) % 3], LEVELS[n // 9], LEVELS[n % 3]) for n in range(27)]


def _nearest(pal, r, g, b) -> int:
    best, bi = 1 << 30, 0
    for i, (pr, pg, pb) in enumerate(pal):
        d = (pr - r) ** 2 * 3 + (pg - g) ** 2 * 4 + (pb - b) ** 2 * 2
        if d < best:
            best, bi = d, i
    return bi


def image_to_cpc(img, mode: int = 1, dither: bool = True):
    """QImage → (écran 16 Ko, [encres firmware]) ; résolution du mode, palette optimisée."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    w = {0: 160, 1: 320, 2: 640}[mode]
    ncol = {0: 16, 1: 4, 2: 2}[mode]
    im = img.convertToFormat(QImage.Format_RGB32).scaled(w, 200, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    px = [[(c >> 16 & 255, c >> 8 & 255, c & 255) for c in (im.pixel(x, y) for x in range(w))] for y in range(200)]
    hist = {}
    cache = {}
    for row in px:
        for c in row:
            k = cache.get(c)
            if k is None:
                k = cache[c] = _nearest(CPC_FW, *c)
            hist[k] = hist.get(k, 0) + 1
    inks = [k for k, _ in sorted(hist.items(), key=lambda x: -x[1])][:ncol]
    for k in (0, 26, 13, 6, 18, 2, 24, 20, 8, 3, 9, 1, 15, 12, 11, 4) + tuple(range(27)):
        if len(inks) >= ncol:
            break
        if k not in inks:
            inks.append(k)
    inks.sort(key=lambda k: sum(CPC_FW[k]))          # encre 0 = la plus sombre (fond)
    pal = [CPC_FW[k] for k in inks]
    idx = [[0] * w for _ in range(200)]
    err = [[[0.0, 0.0, 0.0] for _ in range(w + 2)] for _ in range(2)]
    cache2 = {}
    for y in range(200):
        cur, nxt = err[0], err[1]
        for x in range(w):
            r, g, b = px[y][x]
            if dither:
                r, g, b = r + cur[x + 1][0], g + cur[x + 1][1], b + cur[x + 1][2]
            r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
            key = (int(r) >> 2, int(g) >> 2, int(b) >> 2)
            k = cache2.get(key)
            if k is None:
                k = cache2[key] = _nearest(pal, r, g, b)
            idx[y][x] = k
            if dither:
                er, eg, eb = r - pal[k][0], g - pal[k][1], b - pal[k][2]
                for dx, dy, f in ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)):
                    tgt = (cur if dy == 0 else nxt)[x + 1 + dx]
                    tgt[0] += er * f
                    tgt[1] += eg * f
                    tgt[2] += eb * f
        err = [nxt, [[0.0, 0.0, 0.0] for _ in range(w + 2)]]
    scr = bytearray(16384)
    ppb = {0: 2, 1: 4, 2: 8}[mode]
    for y in range(200):
        base = (y // 8) * 80 + (y % 8) * 2048
        for xb in range(80):
            v = 0
            for i in range(ppb):
                c = idx[y][xb * ppb + i]
                if mode == 2:
                    v |= (c & 1) << (7 - i)
                elif mode == 1:
                    v |= (c & 1) << (7 - i) | (c >> 1 & 1) << (3 - i)
                else:
                    v |= (c & 1) << (7 - i) | (c >> 1 & 1) << (3 - i) | (c >> 2 & 1) << (5 - i) | \
                        (c >> 3 & 1) << (1 - i)
            scr[base + xb] = v
    return bytes(scr), inks


def cpc_loader(scr_name: str, mode: int, inks: List[int]) -> str:
    ink_cmds = ":".join(f"INK {i},{k}" for i, k in enumerate(inks))
    return (f"10 MODE {mode}:BORDER {inks[0]}:{ink_cmds}\n"
            f"20 LOAD \"{scr_name}\",&C000\n"
            f"30 CALL &BB18\n")


# --------------------------------------------------------------------------
# WAV → sample Akai S1000
# --------------------------------------------------------------------------
from .fs.akai import AKAI_CHARS  # noqa: E402


def wav_to_akai(wav: bytes, name: str) -> Tuple[bytes, int, int]:
    """WAV → échantillon S1000 (en-tête 150 o + PCM 16 bits mono). Retourne (données, fréquence, nb)."""
    with wave.open(io.BytesIO(wav)) as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    samples = []
    step = ch * sw
    for k in range(0, len(raw) - step + 1, step):
        acc = 0
        for c in range(ch):
            o = k + c * sw
            if sw == 1:
                v = (raw[o] - 128) << 8
            elif sw == 2:
                v = struct.unpack_from("<h", raw, o)[0]
            elif sw == 3:
                v = int.from_bytes(raw[o:o + 3], "little", signed=True) >> 8
            else:
                v = struct.unpack_from("<i", raw, o)[0] >> 16
            acc += v
        samples.append(int(acc / ch))
    n = len(samples)
    nm = "".join(c if c in AKAI_CHARS else " " for c in name.upper())[:12].ljust(12)
    h = bytearray(150)
    h[0] = 3
    h[1] = 1 if rate > 30000 else 0
    h[2] = 60
    h[3:15] = bytes(AKAI_CHARS.index(c) for c in nm)
    h[15] = 0x80
    h[16], h[17], h[19] = 0, 0, 2
    h[22:26] = b"\x00\x04\x01\x00"
    struct.pack_into("<III", h, 26, n, 0, n)
    struct.pack_into("<H", h, 0x8A, rate)
    pcm = struct.pack(f"<{n}h", *samples)
    return bytes(h) + pcm, rate, n
