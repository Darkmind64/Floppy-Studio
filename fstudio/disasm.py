"""Désassembleurs : Z80 (intégré), 6502 / 6809 / 68000 / x86-16 (Capstone)."""
from __future__ import annotations

from typing import List, Optional, Tuple

CPUS = [("Z80 (CPC, MSX, Spectrum, CP/M)", "z80"), ("6809 (Thomson)", "6809"),
        ("6502 (Commodore, Apple II, Atari 8 bits)", "6502"), ("68000 (Amiga, Atari ST, Mac)", "68000"),
        ("x86 16 bits (PC .COM / .EXE)", "x86")]

MAX_BYTES = 32 * 1024

# --------------------------------------------------------------------------
# Z80
# --------------------------------------------------------------------------
_R = ["B", "C", "D", "E", "H", "L", "(HL)", "A"]
_RP = ["BC", "DE", "HL", "SP"]
_RP2 = ["BC", "DE", "HL", "AF"]
_CC = ["NZ", "Z", "NC", "C", "PO", "PE", "P", "M"]
_ALU = ["ADD A,", "ADC A,", "SUB ", "SBC A,", "AND ", "XOR ", "OR ", "CP "]
_ROT = ["RLC", "RRC", "RL", "RR", "SLA", "SRA", "SLL", "SRL"]
_IM = ["0", "0/1", "1", "2", "0", "0/1", "1", "2"]
_BLI = [["LDI", "CPI", "INI", "OUTI"], ["LDD", "CPD", "IND", "OUTD"],
        ["LDIR", "CPIR", "INIR", "OTIR"], ["LDDR", "CPDR", "INDR", "OTDR"]]


def _h8(v):
    return f"&{v:02X}"


def _h16(v):
    return f"&{v:04X}"


class _Z80:
    def __init__(self, data: bytes, pc: int, base: int):
        self.d, self.p, self.base = data, pc, base

    def b(self) -> int:
        v = self.d[self.p] if self.p < len(self.d) else 0
        self.p += 1
        return v

    def w(self) -> int:
        lo = self.b()
        return lo | self.b() << 8

    def disp(self) -> int:
        v = self.b()
        return v - 256 if v > 127 else v

    def one(self) -> str:
        op = self.b()
        if op == 0xCB:
            return self.cb(None)
        if op == 0xED:
            return self.ed()
        if op in (0xDD, 0xFD):
            idx = "IX" if op == 0xDD else "IY"
            nxt = self.d[self.p] if self.p < len(self.d) else 0
            if nxt in (0xDD, 0xED, 0xFD):
                return "NOP*"
            op = self.b()
            if op == 0xCB:
                return self.cb(idx)
            return self.main(op, idx)
        return self.main(op, None)

    def r(self, i: int, idx: Optional[str], mem_used=False) -> str:
        if i == 6:
            if idx:
                d = self.disp()
                return f"({idx}{'+' if d >= 0 else '-'}{_h8(abs(d))})"
            return "(HL)"
        if idx and i in (4, 5) and not mem_used:
            return idx + ("H" if i == 4 else "L")
        return _R[i]

    def rp(self, p, idx, tbl=_RP):
        return idx if (p == 2 and idx) else tbl[p]

    def main(self, op: int, idx: Optional[str]) -> str:
        x, y, z, p, q = op >> 6, (op >> 3) & 7, op & 7, (op >> 4) & 3, (op >> 3) & 1
        hl = idx or "HL"
        if x == 0:
            if z == 0:
                if y == 0:
                    return "NOP"
                if y == 1:
                    return "EX AF,AF'"
                d = self.disp()
                tgt = _h16((self.base + self.p + d) & 0xFFFF)
                if y == 2:
                    return f"DJNZ {tgt}"
                if y == 3:
                    return f"JR {tgt}"
                return f"JR {_CC[y - 4]},{tgt}"
            if z == 1:
                return f"LD {self.rp(p, idx)},{_h16(self.w())}" if q == 0 else f"ADD {hl},{self.rp(p, idx)}"
            if z == 2:
                if p < 2:
                    rr = "(BC)" if p == 0 else "(DE)"
                    return f"LD {rr},A" if q == 0 else f"LD A,{rr}"
                nn = _h16(self.w())
                src = hl if p == 2 else "A"
                return f"LD ({nn}),{src}" if q == 0 else f"LD {src},({nn})"
            if z == 3:
                return ("INC " if q == 0 else "DEC ") + self.rp(p, idx)
            if z in (4, 5):
                return ("INC " if z == 4 else "DEC ") + self.r(y, idx)
            if z == 6:
                reg = self.r(y, idx)
                return f"LD {reg},{_h8(self.b())}"
            return ["RLCA", "RRCA", "RLA", "RRA", "DAA", "CPL", "SCF", "CCF"][y]
        if x == 1:
            if op == 0x76:
                return "HALT"
            mem = y == 6 or z == 6
            return f"LD {self.r(y, idx, mem)},{self.r(z, idx, mem)}"
        if x == 2:
            return _ALU[y] + self.r(z, idx)
        if z == 0:
            return f"RET {_CC[y]}"
        if z == 1:
            if q == 0:
                return "POP " + self.rp(p, idx, _RP2)
            return ["RET", "EXX", f"JP ({hl})", f"LD SP,{hl}"][p]
        if z == 2:
            return f"JP {_CC[y]},{_h16(self.w())}"
        if z == 3:
            if y == 0:
                return f"JP {_h16(self.w())}"
            if y == 2:
                return f"OUT ({_h8(self.b())}),A"
            if y == 3:
                return f"IN A,({_h8(self.b())})"
            return {4: f"EX (SP),{hl}", 5: "EX DE,HL", 6: "DI", 7: "EI"}.get(y, "?")
        if z == 4:
            return f"CALL {_CC[y]},{_h16(self.w())}"
        if z == 5:
            if q == 0:
                return "PUSH " + self.rp(p, idx, _RP2)
            return f"CALL {_h16(self.w())}" if p == 0 else "?"
        if z == 6:
            return _ALU[y] + _h8(self.b())
        return f"RST {_h8(y * 8)}"

    def cb(self, idx: Optional[str]) -> str:
        if idx:
            d = self.disp()
            op = self.b()
            mem = f"({idx}{'+' if d >= 0 else '-'}{_h8(abs(d))})"
        else:
            op = self.b()
            mem = None
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        reg = mem if mem else _R[z]
        suffix = f",{_R[z]}" if mem and z != 6 and x != 1 else ""
        if x == 0:
            return f"{_ROT[y]} {reg}{suffix}"
        return f"{['', 'BIT', 'RES', 'SET'][x]} {y},{reg}{suffix}"

    def ed(self) -> str:
        op = self.b()
        x, y, z, p, q = op >> 6, (op >> 3) & 7, op & 7, (op >> 4) & 3, (op >> 3) & 1
        if x == 1:
            if z == 0:
                return "IN (C)" if y == 6 else f"IN {_R[y]},(C)"
            if z == 1:
                return "OUT (C),0" if y == 6 else f"OUT (C),{_R[y]}"
            if z == 2:
                return ("SBC HL," if q == 0 else "ADC HL,") + _RP[p]
            if z == 3:
                nn = _h16(self.w())
                return f"LD ({nn}),{_RP[p]}" if q == 0 else f"LD {_RP[p]},({nn})"
            if z == 4:
                return "NEG"
            if z == 5:
                return "RETI" if y == 1 else "RETN"
            if z == 6:
                return f"IM {_IM[y]}"
            return ["LD I,A", "LD R,A", "LD A,I", "LD A,R", "RRD", "RLD", "NOP*", "NOP*"][y]
        if x == 2 and z <= 3 and y >= 4:
            return _BLI[y - 4][z]
        return f"DB &ED,{_h8(op)}"


def z80(data: bytes, org: int) -> List[Tuple[int, bytes, str]]:
    out, p = [], 0
    data = data[:MAX_BYTES]
    while p < len(data):
        d = _Z80(data, p, org)
        try:
            txt = d.one()
        except Exception:
            txt = f"DB {_h8(data[p])}"
            d.p = p + 1
        n = max(1, min(d.p, len(data)) - p)
        out.append((org + p, data[p:p + n], txt))
        p += n
    return out


# --------------------------------------------------------------------------
# Capstone
# --------------------------------------------------------------------------
def _capstone(cpu: str):
    import capstone as C
    if cpu == "6502":
        return C.Cs(C.CS_ARCH_MOS65XX, C.CS_MODE_MOS65XX_6502)
    if cpu == "6809":
        return C.Cs(C.CS_ARCH_M680X, C.CS_MODE_M680X_6809)
    if cpu == "68000":
        return C.Cs(C.CS_ARCH_M68K, C.CS_MODE_M68K_000 | C.CS_MODE_BIG_ENDIAN)
    if cpu == "x86":
        return C.Cs(C.CS_ARCH_X86, C.CS_MODE_16)
    raise ValueError(cpu)


def capstone_dis(cpu: str, data: bytes, org: int) -> List[Tuple[int, bytes, str]]:
    md = _capstone(cpu)
    md.skipdata = True
    out = []
    data = data[:MAX_BYTES]
    for i in md.disasm(data, org):
        txt = (i.mnemonic.upper() + " " + i.op_str).strip()
        if i.mnemonic == ".byte":
            txt = "DB " + i.op_str
        out.append((i.address, bytes(i.bytes), txt))
    return out


def disassemble(cpu: str, data: bytes, org: int) -> str:
    try:
        rows = z80(data, org) if cpu == "z80" else capstone_dis(cpu, data, org)
    except ImportError:
        return "Module « capstone » absent : pip install capstone"
    wide = 6 if cpu in ("68000", "x86") else 4
    lines = []
    for addr, b, txt in rows:
        hx = " ".join(f"{x:02X}" for x in b[:8])
        lines.append(f"{addr:0{wide}X}  {hx:<24}{txt}")
    if len(data) > MAX_BYTES:
        lines.append(f"… ({len(data) - MAX_BYTES} octets non désassemblés)")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Choix automatique du processeur et de l'adresse
# --------------------------------------------------------------------------
def guess(platform: str, data: bytes, meta: dict, ext: str, raw: bytes = b"") -> Optional[Tuple[str, bytes, int, str]]:
    """(cpu, code, adresse, description) si le fichier ressemble à du code exécutable."""
    from .fs.cpm import amsdos_header
    if platform == "cpc":
        h = amsdos_header(raw)
        if h and h["type"] & 0x0F in (2, 3) and not (h["load"] >= 0xC000 and len(data) >= 16000):
            return "z80", data, h["load"], f"Binaire AMSDOS chargé en &{h['load']:04X}, exécution &{h['exec']:04X}"
        if ext == "com":
            return "z80", data, 0x100, "Programme CP/M (.COM)"
        return None
    if platform == "msx":
        if data[:1] == b"\xFE" and len(data) > 7:
            start = data[1] | data[2] << 8
            ex = data[5] | data[6] << 8
            return "z80", data[7:], start, f"BLOAD &{start:04X}, exécution &{ex:04X}"
        if ext == "com":
            return "z80", data, 0x100, "MSX-DOS .COM"
        return None
    if platform == "thomson":
        if meta.get("type") == 2:
            from .fs.thomson import binary_info
            bi = binary_info(data)
            if bi and bi["blocs"]:
                ad, ln = bi["blocs"][0]
                return "6809", data[5:5 + ln], ad, f"Bloc &{ad:04X} ({ln} o), exécution &{bi['exec']:04X}"
        return None
    if platform == "c64":
        from .viewers import c64_basic
        if len(data) > 2 and ext in ("prg", "") and not c64_basic(data):
            la = data[0] | data[1] << 8
            return "6502", data[2:], la, f"Chargé en ${la:04X}"
        return None
    if platform in ("atarist", "pc", "msx") and data[:2] == b"\x60\x1A" and len(data) > 28:
        tlen = int.from_bytes(data[2:6], "big")
        return "68000", data[28:28 + tlen], 0, f"Programme TOS : segment texte {tlen} o"
    if platform == "amiga" and data[:4] == b"\x00\x00\x03\xF3":
        code = amiga_first_code(data)
        if code is not None:
            return "68000", code, 0, "Exécutable AmigaDOS : premier hunk CODE"
        return None
    if platform == "pc":
        if ext == "com":
            return "x86", data, 0x100, "Programme DOS .COM (CS:0100)"
        if data[:2] == b"MZ" and len(data) > 32:
            hdr = (data[8] | data[9] << 8) * 16
            ip = data[0x14] | data[0x15] << 8
            return "x86", data[hdr:], 0, f"Exécutable MZ, en-tête {hdr} o, point d'entrée CS:{ip:04X}"
    return None


def amiga_first_code(d: bytes) -> Optional[bytes]:
    try:
        p = 4
        while int.from_bytes(d[p:p + 4], "big"):
            p += 4 + 4 * int.from_bytes(d[p:p + 4], "big")
        p += 4
        first, last = int.from_bytes(d[p + 4:p + 8], "big"), int.from_bytes(d[p + 8:p + 12], "big")
        p += 12 + 4 * (last - first + 1)
        while p + 8 <= len(d):
            ht = int.from_bytes(d[p:p + 4], "big") & 0x3FFFFFFF
            ln = int.from_bytes(d[p + 4:p + 8], "big") * 4
            if ht == 0x3E9:
                return d[p + 8:p + 8 + ln]
            if ht in (0x3EA, 0x3EB):
                p += 8 + (ln if ht == 0x3EA else 0)
                continue
            return None
        return None
    except Exception:
        return None
