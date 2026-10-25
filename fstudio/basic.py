"""Détokeniseurs BASIC : Locomotive (CPC), Thomson 1.0/512, MSX, GW-BASIC."""
from __future__ import annotations

import struct
from decimal import Decimal
from typing import Dict, List, Optional


def _tbl(spec: str, base: int = 0) -> Dict[int, str]:
    out = {}
    for item in spec.split("|"):
        k, v = item.strip().split(" ", 1)
        out[int(k, 16) + base] = v
    return out


def _fmt(v: float) -> str:
    s = format(v, ".9g")
    if "e" in s:
        m, e = s.split("e")
        s = f"{m}E{int(e):+03d}"
    if s.startswith("0."):
        s = s[1:]
    return s


# --------------------------------------------------------------------------
# Locomotive BASIC (Amstrad CPC)
# --------------------------------------------------------------------------
LOCO = _tbl(
    "80 AFTER|81 AUTO|82 BORDER|83 CALL|84 CAT|85 CHAIN|86 CLEAR|87 CLG|88 CLOSEIN|89 CLOSEOUT|"
    "8A CLS|8B CONT|8C DATA|8D DEF|8E DEFINT|8F DEFREAL|90 DEFSTR|91 DEG|92 DELETE|93 DIM|94 DRAW|"
    "95 DRAWR|96 EDIT|97 ELSE|98 END|99 ENT|9A ENV|9B ERASE|9C ERROR|9D EVERY|9E FOR|9F GOSUB|"
    "A0 GOTO|A1 IF|A2 INK|A3 INPUT|A4 KEY|A5 LET|A6 LINE|A7 LIST|A8 LOAD|A9 LOCATE|AA MEMORY|"
    "AB MERGE|AC MID$|AD MODE|AE MOVE|AF MOVER|B0 NEXT|B1 NEW|B2 ON|B3 ON BREAK|B4 ON ERROR GOTO|"
    "B5 ON SQ|B6 OPENIN|B7 OPENOUT|B8 ORIGIN|B9 OUT|BA PAPER|BB PEN|BC PLOT|BD PLOTR|BE POKE|"
    "BF PRINT|C0 '|C1 RAD|C2 RANDOMIZE|C3 READ|C4 RELEASE|C5 REM|C6 RENUM|C7 RESTORE|C8 RESUME|"
    "C9 RETURN|CA RUN|CB SAVE|CC SOUND|CD SPEED|CE STOP|CF SYMBOL|D0 TAG|D1 TAGOFF|D2 TROFF|D3 TRON|"
    "D4 WAIT|D5 WEND|D6 WHILE|D7 WIDTH|D8 WINDOW|D9 WRITE|DA ZONE|DB DI|DC EI|DD FILL|DE GRAPHICS|"
    "DF MASK|E0 FRAME|E1 CURSOR|E3 ERL|E4 FN|E5 SPC|E6 STEP|E7 SWAP|EA TAB|EB THEN|EC TO|ED USING|"
    "EE >|EF =|F0 >=|F1 <|F2 <>|F3 <=|F4 +|F5 -|F6 *|F7 /|F8 ^|F9 \\|FA AND|FB MOD|FC OR|FD XOR|FE NOT")
LOCO_FN = _tbl(
    "00 ABS|01 ASC|02 ATN|03 CHR$|04 CINT|05 COS|06 CREAL|07 EXP|08 FIX|09 FRE|0A INKEY|0B INP|"
    "0C INT|0D JOY|0E LEN|0F LOG|10 LOG10|11 LOWER$|12 PEEK|13 REMAIN|14 SGN|15 SIN|16 SPACE$|17 SQ|"
    "18 SQR|19 STR$|1A TAN|1B UNT|1C UPPER$|1D VAL|40 EOF|41 ERR|42 HIMEM|43 INKEY$|44 PI|45 RND|"
    "46 TIME|47 XPOS|48 YPOS|49 DERR|71 BIN$|72 DEC$|73 HEX$|74 INSTR|75 LEFT$|76 MAX|77 MIN|78 POS|"
    "79 RIGHT$|7A ROUND|7B STRING$|7C TEST|7D TESTR|7E COPYCHR$|7F VPOS")
_LOCO_SUFFIX = {2: "%", 3: "$", 4: "!", 0x0B: "", 0x0C: "", 0x0D: ""}


def _bit7name(b: bytes, p: int):
    s = []
    while p < len(b):
        c = b[p]
        s.append(chr(c & 0x7F))
        p += 1
        if c & 0x80:
            break
    return "".join(s), p


def locomotive(b: bytes) -> Optional[str]:
    # Repérage des lignes (pour résoudre les pointeurs 0x1D)
    lines, p = [], 0
    while p + 4 <= len(b):
        ln = b[p] | b[p + 1] << 8
        if ln == 0:
            break
        if ln < 5 or p + ln > len(b) or b[p + ln - 1] != 0:
            return None
        lines.append((p, b[p + 2] | b[p + 3] << 8, b[p + 4:p + ln - 1]))
        p += ln
    if not lines or any(lines[i][1] >= lines[i + 1][1] for i in range(len(lines) - 1)):
        return None
    addr = {}
    for off, num, _ in lines:
        for base in (0x16F, 0x170):
            addr[base + off] = num
    out = []
    for _, num, body in lines:
        s, i, quote, lit = [], 0, False, False
        while i < len(body):
            c = body[i]
            i += 1
            if lit or quote:
                if c == 0x22:
                    quote = False
                s.append(chr(c) if 32 <= c < 127 else f"[{c:02X}]")
                continue
            if c == 0x22:
                quote = True
                s.append('"')
            elif c == 0x01:
                if i < len(body) and body[i] in (0x97, 0xC0):
                    continue
                s.append(":")
            elif c in _LOCO_SUFFIX:
                name, i = _bit7name(body, i + 2)
                s.append(name + _LOCO_SUFFIX[c])
            elif 0x0E <= c <= 0x18:
                s.append(str(c - 0x0E))
            elif c == 0x19:
                s.append(str(body[i]) if i < len(body) else "")
                i += 1
            elif c in (0x1A, 0x1B, 0x1C, 0x1D, 0x1E):
                v = body[i] | body[i + 1] << 8 if i + 1 < len(body) else 0
                i += 2
                s.append({0x1A: str(v), 0x1B: f"&X{v:b}", 0x1C: f"&{v:X}",
                          0x1D: str(addr.get(v, v)), 0x1E: str(v)}[c])
            elif c == 0x1F:
                m = body[i:i + 5].ljust(5, b"\0")
                i += 5
                if m[4] == 0:
                    s.append("0")
                else:
                    mant = (m[0] | m[1] << 8 | m[2] << 16 | (m[3] | 0x80) << 24)
                    v = mant / 2 ** 32 * 2.0 ** (m[4] - 128)
                    s.append(_fmt(-v if m[3] & 0x80 else v))
            elif c == 0x7C:
                name, i = _bit7name(body, i + 1)
                s.append("|" + name)
            elif c == 0xFF:
                f = body[i] if i < len(body) else 0
                i += 1
                s.append(LOCO_FN.get(f, f"[FF{f:02X}]"))
            elif c >= 0x80:
                t = LOCO.get(c, f"[{c:02X}]")
                s.append(t)
                if c in (0xC0, 0xC5):
                    lit = True
                elif c == 0x8C:     # DATA : texte brut jusqu'au ':'
                    j = body.find(b"\x01", i)
                    j = len(body) if j < 0 else j
                    s.append(body[i:j].decode("latin-1"))
                    i = j
            elif 32 <= c < 127:
                s.append(chr(c))
            elif c == 0x09:
                s.append(" ")
            else:
                s.append(f"[{c:02X}]")
        out.append(f"{num} {''.join(s)}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Thomson BASIC 1.0 / 512
# --------------------------------------------------------------------------
TH10 = _tbl(
    "00 END|01 FOR|02 NEXT|03 DATA|04 DIM|05 READ|07 GO|08 RUN|09 IF|0A RESTORE|0B RETURN|0C REM|"
    "0D '|0E STOP|0F ELSE|10 TRON|11 TROFF|12 DEFSTR|13 DEFINT|14 DEFSNG|16 ON|17 TUNE|18 ERROR|"
    "19 RESUME|1A AUTO|1B DELETE|1C LOCATE|1D CLS|1E CONSOLE|1F PSET|20 MOTOR|21 SKIPF|22 EXEC|"
    "23 BEEP|24 COLOR|25 LINE|26 BOX|28 ATTRB|29 DEF|2A POKE|2B PRINT|2C CONT|2D LIST|2E CLEAR|"
    "2F DOS|31 NEW|32 SAVE|33 LOAD|34 MERGE|35 OPEN|36 CLOSE|37 INPEN|38 PEN|39 PLAY|3A TAB|3B TO|"
    "3C SUB|3D FNS|3E SPC|3F USING|40 USR|41 ERL|42 ERR|43 OFF|44 THEN|45 NOT|46 STEP|47 +|48 -|"
    "49 *|4A /|4B ^|4C AND|4D OR|4E XOR|4F EQV|50 IMP|51 MOD|52 @|53 >|54 =|55 <|56 DSKINI|57 DSKO$|"
    "58 KILL|59 NAME|5A FIELD|5B LSET|5C RSET|5D PUT|5E GET|5F VERIFY|60 DEVICE|61 DIR|62 FILES|"
    "63 WRITE|64 UNLOAD|65 BACKUP|66 COPY|67 CIRCLE|68 PAINT|69 DRAW|6A RENUM|6B SWAP", 0x80)
TH512 = dict(TH10)
TH512.update(_tbl(
    "06 LET|15 DEFDBL|27 UNMASK|2F INTERVAL|30 KEY|3D FN|3E SPC(|69 RESET|6C *|6D WINDOW|6E PATTERN|"
    "6F DO|70 LOOP|71 EXIT|72 INMOUSE|73 MOUSE|74 CHAIN|75 COMMON|76 SEARCH|77 FWD|78 TURTLE", 0x80))
TH_FN = _tbl(
    "00 SGN|01 INT|02 ABS|03 FRE|04 SQR|05 LOG|06 EXP|07 COS|08 SIN|09 TAN|0A PEEK|0B LEN|0C STR$|"
    "0D VAL|0E ASC|0F CHR$|10 EOF|11 CINT|12 CSNG|13 CDBL|14 FIX|15 HEX$|16 OCT$|17 STICK|18 STRIG|"
    "19 GR$|1A LEFT$|1B RIGHT$|1C MID$|1D INSTR|1E VARPTR|1F RND|20 INKEY$|21 INPUT|22 CSRLIN|"
    "23 POINT|24 SCREEN|25 POS|26 PTRIG|27 DSKF|28 CVI|29 CVS|2A CVD|2B MKI$|2C MKS$|2D MKD$|2E LOC|"
    "2F LOF|30 SPACE$|31 STRING$|32 DSKI$|33 FKEY$|34 MIN(|35 MAX(|36 ATN|37 CRUNCH(|38 MTRIG|"
    "39 EVAL|3A PALETTE|3B BANK|3C HEAD|3D ROT|3E SHOW|3F ZOOM|40 TRACE", 0x80)
_TH512_ONLY = {0x86, 0x95, 0xA7, 0xB0} | set(range(0xEC, 0xF9))


_OPLEN = {0x0B: 2, 0x0C: 2, 0x0D: 2, 0x0E: 2, 0x0F: 1, 0x1C: 2, 0x1D: 4, 0x1F: 8}


def _line_end(b: bytes, p: int, binary_nums: bool) -> int:
    quote = rem = False
    while p < len(b):
        c = b[p]
        if c == 0:
            return p
        if c == 0x22:
            quote = not quote
        elif not quote and not rem:
            if binary_nums and c in _OPLEN:
                p += _OPLEN[c]
            elif c in (0x8F,):
                rem = True
            elif c in (0xFD, 0xFE, 0xFF):
                p += 1
        p += 1
    return -1


def _ms_lines(b: bytes, start: int, big: bool, binary_nums: bool = False):
    """Lignes « Microsoft » : pointeur suivant (2), numéro (2), corps, 00."""
    p, lines = start, []
    while p + 4 <= len(b):
        nxt = struct.unpack_from(">H" if big else "<H", b, p)[0]
        if nxt == 0:
            break
        num = struct.unpack_from(">H" if big else "<H", b, p + 2)[0]
        e = _line_end(b, p + 4, binary_nums) if binary_nums else b.find(b"\0", p + 4)
        if e < 0:
            return None
        lines.append((num, b[p + 4:e]))
        p = e + 1
    if len(lines) < 1 or any(lines[i][0] >= lines[i + 1][0] for i in range(len(lines) - 1)):
        return None
    return lines


def thomson(b: bytes) -> Optional[str]:
    from .viewers import thomson_text
    lines = None
    for start, big in ((3, True), (0, True), (3, False), (1, True)):
        if start and b[:1] != b"\xff":
            continue
        lines = _ms_lines(b, start, big)
        if lines:
            break
    if not lines:
        return None
    used = {c for _, body in lines for c in body}
    tbl = TH512 if used & _TH512_ONLY else TH10
    out = []
    for num, body in lines:
        s, lit, i, quote, rem = [], bytearray(), 0, False, False

        def flush():
            if lit:
                s.append(thomson_text(bytes(lit)))
                lit.clear()
        while i < len(body):
            c = body[i]
            i += 1
            if quote or rem or c < 0x80:
                if c == 0x22 and not rem:
                    quote = not quote
                if c == 0x3A and not quote and not rem and i < len(body) and body[i] == 0x8F:
                    continue
                lit.append(c)
                continue
            flush()
            if c == 0xFF and i < len(body):
                f = body[i]
                i += 1
                s.append(TH_FN.get(f, f"[FF{f:02X}]"))
            else:
                s.append(tbl.get(c, f"[{c:02X}]"))
                rem = c in (0x8C, 0x8D)
        flush()
        out.append(f"{num} {''.join(s)}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# MSX BASIC / GW-BASIC (format Microsoft, en-tête 0xFF)
# --------------------------------------------------------------------------
MSX = _tbl(
    "81 END|82 FOR|83 NEXT|84 DATA|85 INPUT|86 DIM|87 READ|88 LET|89 GOTO|8A RUN|8B IF|8C RESTORE|"
    "8D GOSUB|8E RETURN|8F REM|90 STOP|91 PRINT|92 CLEAR|93 LIST|94 NEW|95 ON|96 WAIT|97 DEF|98 POKE|"
    "99 CONT|9A CSAVE|9B CLOAD|9C OUT|9D LPRINT|9E LLIST|9F CLS|A0 WIDTH|A1 ELSE|A2 TRON|A3 TROFF|"
    "A4 SWAP|A5 ERASE|A6 ERROR|A7 RESUME|A8 DELETE|A9 AUTO|AA RENUM|AB DEFSTR|AC DEFINT|AD DEFSNG|"
    "AE DEFDBL|AF LINE|B0 OPEN|B1 FIELD|B2 GET|B3 PUT|B4 CLOSE|B5 LOAD|B6 MERGE|B7 FILES|B8 LSET|"
    "B9 RSET|BA SAVE|BB LFILES|BC CIRCLE|BD COLOR|BE DRAW|BF PAINT|C0 BEEP|C1 PLAY|C2 PSET|C3 PRESET|"
    "C4 SOUND|C5 SCREEN|C6 VPOKE|C7 SPRITE|C8 VDP|C9 BASE|CA CALL|CB TIME|CC KEY|CD MAX|CE MOTOR|"
    "CF BLOAD|D0 BSAVE|D1 DSKO$|D2 SET|D3 NAME|D4 KILL|D5 IPL|D6 COPY|D7 CMD|D8 LOCATE|D9 TO|DA THEN|"
    "DB TAB(|DC STEP|DD USR|DE FN|DF SPC(|E0 NOT|E1 ERL|E2 ERR|E3 STRING$|E4 USING|E5 INSTR|E6 '|"
    "E7 VARPTR|E8 CSRLIN|E9 ATTR$|EA DSKI$|EB OFF|EC INKEY$|ED POINT|EE >|EF =|F0 <|F1 +|F2 -|F3 *|"
    "F4 /|F5 ^|F6 AND|F7 OR|F8 XOR|F9 EQV|FA IMP|FB MOD|FC \\")
MSX_FF = _tbl(
    "81 LEFT$|82 RIGHT$|83 MID$|84 SGN|85 INT|86 ABS|87 SQR|88 RND|89 SIN|8A LOG|8B EXP|8C COS|"
    "8D TAN|8E ATN|8F FRE|90 INP|91 POS|92 LEN|93 STR$|94 VAL|95 ASC|96 CHR$|97 PEEK|98 VPEEK|"
    "99 SPACE$|9A OCT$|9B HEX$|9C LPOS|9D BIN$|9E CINT|9F CSNG|A0 CDBL|A1 FIX|A2 STICK|A3 STRIG|"
    "A4 PDL|A5 PAD|A6 DSKF|A7 FPOS|A8 CVI|A9 CVS|AA CVD|AB EOF|AC LOC|AD LOF|AE MKI$|AF MKS$|B0 MKD$")
GW = _tbl(
    "81 END|82 FOR|83 NEXT|84 DATA|85 INPUT|86 DIM|87 READ|88 LET|89 GOTO|8A RUN|8B IF|8C RESTORE|"
    "8D GOSUB|8E RETURN|8F REM|90 STOP|91 PRINT|92 CLEAR|93 LIST|94 NEW|95 ON|96 WAIT|97 DEF|98 POKE|"
    "99 CONT|9C OUT|9D LPRINT|9E LLIST|A0 WIDTH|A1 ELSE|A2 TRON|A3 TROFF|A4 SWAP|A5 ERASE|A6 EDIT|"
    "A7 ERROR|A8 RESUME|A9 DELETE|AA AUTO|AB RENUM|AC DEFSTR|AD DEFINT|AE DEFSNG|AF DEFDBL|B0 LINE|"
    "B1 WHILE|B2 WEND|B3 CALL|B7 WRITE|B8 OPTION|B9 RANDOMIZE|BA OPEN|BB CLOSE|BC LOAD|BD MERGE|"
    "BE SAVE|BF COLOR|C0 CLS|C1 MOTOR|C2 BSAVE|C3 BLOAD|C4 SOUND|C5 BEEP|C6 PSET|C7 PRESET|C8 SCREEN|"
    "C9 KEY|CA LOCATE|CC TO|CD THEN|CE TAB(|CF STEP|D0 USR|D1 FN|D2 SPC(|D3 NOT|D4 ERL|D5 ERR|"
    "D6 STRING$|D7 USING|D8 INSTR|D9 '|DA VARPTR|DB CSRLIN|DC POINT|DD OFF|DE INKEY$|E6 >|E7 =|E8 <|"
    "E9 +|EA -|EB *|EC /|ED ^|EE AND|EF OR|F0 XOR|F1 EQV|F2 IMP|F3 MOD|F4 \\")
GW_FD = _tbl("81 CVI|82 CVS|83 CVD|84 MKI$|85 MKS$|86 MKD$|8B EXTERR")
GW_FE = _tbl(
    "81 FILES|82 FIELD|83 SYSTEM|84 NAME|85 LSET|86 RSET|87 KILL|88 PUT|89 GET|8A RESET|8B COMMON|"
    "8C CHAIN|8D DATE$|8E TIME$|8F PAINT|90 COM|91 CIRCLE|92 DRAW|93 PLAY|94 TIMER|95 ERDEV|96 IOCTL|"
    "97 CHDIR|98 MKDIR|99 RMDIR|9A SHELL|9B ENVIRON|9C VIEW|9D WINDOW|9E PMAP|9F PALETTE|A0 LCOPY|"
    "A1 CALLS|A4 PCOPY|A6 LOCK|A7 UNLOCK")
GW_FF = _tbl(
    "81 LEFT$|82 RIGHT$|83 MID$|84 SGN|85 INT|86 ABS|87 SQR|88 RND|89 SIN|8A LOG|8B EXP|8C COS|"
    "8D TAN|8E ATN|8F FRE|90 INP|91 POS|92 LEN|93 STR$|94 VAL|95 ASC|96 CHR$|97 PEEK|98 SPACE$|"
    "99 OCT$|9A HEX$|9B LPOS|9C CINT|9D CSNG|9E CDBL|9F FIX|A0 PEN|A1 STICK|A2 STRIG|A3 EOF|A4 LOC|"
    "A5 LOF")


def _bcd(m: bytes) -> str:
    if not m or m[0] & 0x7F == 0:
        return "0"
    digits = "".join(f"{x:02X}" for x in m[1:]).rstrip("0") or "0"
    v = Decimal("0." + digits).scaleb((m[0] & 0x7F) - 0x40)
    s = format(v.normalize(), "f")
    s = s[1:] if s.startswith("0.") else s
    return ("-" if m[0] & 0x80 else "") + s


def _mbf(m: bytes) -> str:
    if m[-1] == 0:
        return "0"
    mant = int.from_bytes(m[:-1], "little")
    bits = 8 * (len(m) - 1)
    neg = mant >> (bits - 1) & 1
    mant |= 1 << (bits - 1)
    v = mant / 2 ** bits * 2.0 ** (m[-1] - 128)
    return _fmt(-v if neg else v)


def microsoft(b: bytes, dialect: str) -> Optional[str]:
    if b[:1] != b"\xff":
        return None
    lines = _ms_lines(b, 1, False, True)
    if not lines:
        return None
    msx = dialect == "msx"
    main = MSX if msx else GW
    rem_tok = {0x8F, 0xE6} if msx else {0x8F, 0xD9}
    else_tok, apos = 0xA1, (0xE6 if msx else 0xD9)
    out = []
    for num, body in lines:
        s, i, quote, lit = [], 0, False, False
        while i < len(body):
            c = body[i]
            i += 1
            if quote or lit:
                if c == 0x22:
                    quote = False
                s.append(chr(c) if 32 <= c < 127 else f"[{c:02X}]")
                continue
            if c == 0x22:
                quote = True
                s.append('"')
            elif c == 0x3A and i < len(body) and body[i] == else_tok:
                continue
            elif c == 0x3A and body[i:i + 2] == bytes([0x8F, apos]):
                s.append("'")
                i += 2
                lit = True
            elif c in (0x0B, 0x0C, 0x0D, 0x0E, 0x1C):
                v = body[i] | body[i + 1] << 8 if i + 1 < len(body) else 0
                i += 2
                s.append({0x0B: f"&O{v:o}", 0x0C: f"&H{v:X}", 0x0D: str(v), 0x0E: str(v),
                          0x1C: str(v - 65536 if v >= 32768 else v)}[c])
            elif c == 0x0F:
                s.append(str(body[i]) if i < len(body) else "")
                i += 1
            elif 0x11 <= c <= 0x1B:
                s.append(str(c - 0x11))
            elif c in (0x1D, 0x1F):
                n = 4 if c == 0x1D else 8
                m = body[i:i + n].ljust(n, b"\0")
                i += n
                if msx:
                    s.append(_bcd(m) + ("#" if c == 0x1F else ""))
                else:
                    s.append(_mbf(m) + ("!" if c == 0x1D else "#"))
            elif c in (0xFD, 0xFE, 0xFF) and i < len(body):
                f = body[i]
                i += 1
                t = (MSX_FF if c == 0xFF else {}) if msx else {0xFD: GW_FD, 0xFE: GW_FE, 0xFF: GW_FF}[c]
                s.append(t.get(f, f"[{c:02X}{f:02X}]"))
            elif c >= 0x80:
                s.append(main.get(c, f"[{c:02X}]"))
                if c in rem_tok:
                    lit = True
                elif c == 0x84:
                    j = body.find(b":", i)
                    j = len(body) if j < 0 else j
                    s.append(body[i:j].decode("latin-1"))
                    i = j
                elif not msx and c == 0xB1 and i < len(body) and body[i] == 0xE9:
                    i += 1
            elif 32 <= c < 127:
                s.append(chr(c))
            else:
                s.append(f"[{c:02X}]")
        out.append(f"{num} {''.join(s)}")
    return "\n".join(out)


def detokenize(platform: str, data: bytes, meta: dict, ext: str) -> Optional[tuple]:
    """Retourne (dialecte, listing) ou None."""
    if len(data) < 5:
        return None
    tries: List[tuple] = []
    if platform == "cpc":
        tries.append(("Locomotive BASIC", locomotive))
    elif platform == "thomson":
        if meta.get("type") == 0 and not meta.get("ascii"):
            tries.append(("BASIC Thomson", thomson))
    elif platform == "msx":
        tries.append(("MSX-BASIC", lambda d: microsoft(d, "msx")))
    elif platform in ("pc", "atarist"):
        tries.append(("GW-BASIC", lambda d: microsoft(d, "gw")))
        if ext == "bas":
            tries.append(("MSX-BASIC", lambda d: microsoft(d, "msx")))
    if not tries and ext == "bas":
        tries = [("Locomotive BASIC", locomotive), ("GW-BASIC", lambda d: microsoft(d, "gw"))]
    for name, fn in tries:
        try:
            r = fn(data)
        except Exception:
            r = None
        if r:
            return name, r
    return None
