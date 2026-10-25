"""Création de systèmes de fichiers vierges (formatage logique)."""
from __future__ import annotations

import random
import struct
import time
from dataclasses import dataclass
from typing import Callable, List

from .disk import Disk, write_edsk


@dataclass
class MkSpec:
    key: str
    group: str
    label: str
    fmt: str            # diskdef greaseweazle pour l'écriture
    ext: str            # extension de l'image vierge
    build: Callable[[str], bytes]
    max_label: int = 11
    note: str = ""


# --------------------------------------------------------------------------
# FAT (PC, Atari ST, MSX, synthés)
# --------------------------------------------------------------------------
def fat_image(total: int, spt: int, heads: int, spc: int, nroot: int, spf: int, media: int,
              label: str = "", flavour: str = "pc") -> bytes:
    d = bytearray(total * 512)
    b = bytearray(512)
    if flavour == "atari":
        b[0:2] = b"\x60\x38"
        b[2:8] = b"Loader"
        b[8:11] = random.getrandbits(24).to_bytes(3, "little")
    else:
        b[0:3] = b"\xEB\x3C\x90" if flavour == "pc" else b"\xEB\xFE\x90"
        b[3:11] = b"MSDOS5.0" if flavour == "pc" else b"MSX_04  "
    struct.pack_into("<HBHBHHBHHHI", b, 11, 512, spc, 1, 2, nroot, total if total < 65536 else 0,
                     media, spf, spt, heads, 0)
    if total >= 65536:
        struct.pack_into("<I", b, 32, total)
    if flavour == "pc":
        b[36] = 0x00
        b[38] = 0x29
        struct.pack_into("<I", b, 39, random.getrandbits(32))
        b[43:54] = (label.upper() or "NO NAME").encode("ascii", "replace")[:11].ljust(11, b" ")
        b[54:62] = b"FAT12   "
        msg = b"\r\nDisquette non systeme - Floppy Studio\r\n\0"
        b[62:64] = b"\xFA\xEB"              # cli ; boucle
        b[64:64 + len(msg)] = msg
        b[510:512] = b"\x55\xAA"
    elif flavour == "atari":
        b[510:512] = b"\0\0"
    d[:512] = b
    for i in range(2):
        o = (1 + i * spf) * 512
        d[o:o + 3] = bytes([media, 0xFF, 0xFF])
    if label:
        ro = (1 + 2 * spf) * 512
        ent = bytearray(32)
        ent[0:11] = label.upper().encode("ascii", "replace")[:11].ljust(11, b" ")
        ent[11] = 0x08
        t = time.localtime()
        struct.pack_into("<HH", ent, 22, t.tm_hour << 11 | t.tm_min << 5 | t.tm_sec // 2,
                         (t.tm_year - 1980) << 9 | t.tm_mon << 5 | t.tm_mday)
        d[ro:ro + 32] = ent
    data_start = (1 + 2 * spf) * 512 + nroot * 32
    d[data_start:] = b"\xF6" * (len(d) - data_start) if flavour == "pc" else bytes(len(d) - data_start)
    return bytes(d)


# --------------------------------------------------------------------------
# AmigaDOS OFS / FFS
# --------------------------------------------------------------------------
def _amiga_csum(blk: bytearray, off: int = 20):
    struct.pack_into(">I", blk, off, 0)
    s = sum(struct.unpack(">128I", blk)) & 0xFFFFFFFF
    struct.pack_into(">I", blk, off, (-s) & 0xFFFFFFFF)


def _amiga_date():
    t = time.time() - 252460800                 # 1978-01-01
    days = int(t // 86400)
    rem = t - days * 86400
    return days, int(rem // 60), int((rem % 60) * 50)


def amiga_image(nblocks: int, label: str, ffs: bool) -> bytes:
    d = bytearray(nblocks * 512)
    d[0:4] = b"DOS" + bytes([1 if ffs else 0])
    struct.pack_into(">I", d, 8, nblocks // 2)
    root_n, bm_n = nblocks // 2, nblocks // 2 + 1
    root = bytearray(512)
    struct.pack_into(">IIII", root, 0, 2, 0, 0, 72)
    struct.pack_into(">i", root, 312, -1)
    struct.pack_into(">I", root, 316, bm_n)
    days, mins, ticks = _amiga_date()
    for o in (420, 472, 484):
        struct.pack_into(">III", root, o, days, mins, ticks)
    name = (label or "Vide").encode("latin-1", "replace")[:30]
    root[432] = len(name)
    root[433:433 + len(name)] = name
    struct.pack_into(">I", root, 508, 1)
    _amiga_csum(root)
    bm = bytearray(512)
    for blk in range(2, nblocks):
        if blk in (root_n, bm_n):
            continue
        i = blk - 2
        o = 4 + (i // 32) * 4
        v = struct.unpack_from(">I", bm, o)[0] | (1 << (i % 32))
        struct.pack_into(">I", bm, o, v)
    _amiga_csum(bm, 0)
    d[root_n * 512:root_n * 512 + 512] = root
    d[bm_n * 512:bm_n * 512 + 512] = bm
    return bytes(d)


# --------------------------------------------------------------------------
# DOS BASIC Thomson
# --------------------------------------------------------------------------
def thomson_side(tracks: int, label: str) -> bytes:
    ss = 256
    d = bytearray(b"\xE5" * tracks * 16 * ss)
    o = 20 * 16 * ss
    s1 = bytearray(b"\xFF" * ss)
    if label:
        s1[0:8] = label.upper().encode("latin-1", "replace")[:8].ljust(8, b" ")
    d[o:o + ss] = s1
    fat = bytearray(b"\xFE" * ss)
    fat[0] = 0
    for blk in range(tracks * 2):
        fat[1 + blk] = 0xFE if blk in (40, 41) else 0xFF
    d[o + ss:o + 2 * ss] = fat
    d[o + 2 * ss:o + 16 * ss] = b"\xFF" * 14 * ss
    return bytes(d)


# --------------------------------------------------------------------------
# Amstrad CPC (AMSDOS)
# --------------------------------------------------------------------------
def cpc_disk(first_id: int, tracks: int = 40, heads: int = 1) -> Disk:
    nsec = 8 if first_id == 0x01 else 9
    data = b"\xE5" * (tracks * heads * nsec * 512)
    return Disk.from_geometry("", data, tracks, heads, nsec, 512, first_id, "edsk")


def cpc_image(first_id: int) -> bytes:
    return cpc_disk(first_id).linear()


# --------------------------------------------------------------------------
# Commodore 1581
# --------------------------------------------------------------------------
def d81_image(label: str) -> bytes:
    d = bytearray(80 * 40 * 256)
    o = 39 * 40 * 256
    name = (label.upper() or "VIDE").encode("ascii", "replace")[:16].ljust(16, b"\xA0")
    hdr = bytearray(256)
    hdr[0:4] = bytes([40, 3, 0x44, 0])
    hdr[4:20] = name
    hdr[20:22] = b"\xA0\xA0"
    hdr[22:24] = b"FS"
    hdr[24] = 0xA0
    hdr[25:27] = b"3D"
    hdr[27:29] = b"\xA0\xA0"
    d[o:o + 256] = hdr
    for side in range(2):
        bam = bytearray(256)
        bam[0:2] = bytes([40, 2]) if side == 0 else bytes([0, 0xFF])
        bam[2:6] = bytes([0x44, 0xBB]) + b"FS"
        bam[6] = 0xC0
        for t in range(40):
            track = side * 40 + t + 1
            free = 36 if track == 40 else 40
            bits = (1 << 40) - 1
            if track == 40:
                bits &= ~0b1111
            bam[16 + t * 6] = free
            bam[17 + t * 6:22 + t * 6] = bits.to_bytes(5, "little")
        d[o + (1 + side) * 256:o + (2 + side) * 256] = bam
    d[o + 3 * 256:o + 3 * 256 + 2] = b"\x00\xFF"
    return bytes(d)


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------
SPECS: List[MkSpec] = [
    MkSpec("pc360", "PC / DOS (FAT12)", "360 Ko — 5,25\" DD", "ibm.360", ".img",
           lambda l: fat_image(720, 9, 2, 2, 112, 2, 0xFD, l)),
    MkSpec("pc720", "PC / DOS (FAT12)", "720 Ko — 3,5\" DD", "ibm.720", ".img",
           lambda l: fat_image(1440, 9, 2, 2, 112, 3, 0xF9, l)),
    MkSpec("pc1200", "PC / DOS (FAT12)", "1,2 Mo — 5,25\" HD", "ibm.1200", ".img",
           lambda l: fat_image(2400, 15, 2, 1, 224, 7, 0xF9, l)),
    MkSpec("pc1440", "PC / DOS (FAT12)", "1,44 Mo — 3,5\" HD", "ibm.1440", ".img",
           lambda l: fat_image(2880, 18, 2, 1, 224, 9, 0xF0, l)),
    MkSpec("pc2880", "PC / DOS (FAT12)", "2,88 Mo — 3,5\" ED", "ibm.2880", ".img",
           lambda l: fat_image(5760, 36, 2, 2, 240, 9, 0xF0, l)),
    MkSpec("st720", "Atari ST (TOS)", "720 Ko — double face", "atarist.720", ".st",
           lambda l: fat_image(1440, 9, 2, 2, 112, 5, 0xF9, l, "atari")),
    MkSpec("st360", "Atari ST (TOS)", "360 Ko — simple face", "atarist.360", ".st",
           lambda l: fat_image(720, 9, 1, 2, 112, 5, 0xF8, l, "atari")),
    MkSpec("msx720", "MSX (MSX-DOS)", "720 Ko — 2DD", "msx.2dd", ".dsk",
           lambda l: fat_image(1440, 9, 2, 2, 112, 3, 0xF9, l, "msx")),
    MkSpec("synth720", "Sampleurs & synthés (DOS)", "720 Ko (Yamaha, Korg, Roland…)", "ibm.720", ".img",
           lambda l: fat_image(1440, 9, 2, 2, 112, 3, 0xF9, l)),
    MkSpec("synth1440", "Sampleurs & synthés (DOS)", "1,44 Mo (Kurzweil, Yamaha, E-mu…)", "ibm.1440",
           ".img", lambda l: fat_image(2880, 18, 2, 1, 224, 9, 0xF0, l)),
    MkSpec("ofs", "Amiga", "AmigaDOS OFS 880 Ko", "amiga.amigados", ".adf",
           lambda l: amiga_image(1760, l, False), 30),
    MkSpec("ffs", "Amiga", "AmigaDOS FFS 880 Ko", "amiga.amigados", ".adf",
           lambda l: amiga_image(1760, l, True), 30),
    MkSpec("ffshd", "Amiga", "AmigaDOS FFS 1,76 Mo (HD)", "amiga.amigados_hd", ".adf",
           lambda l: amiga_image(3520, l, True), 30),
    MkSpec("th1", "Thomson TO/MO", "DOS BASIC 320 Ko — 1 face", "thomson.1s320", ".fd",
           lambda l: thomson_side(80, l), 8),
    MkSpec("th2", "Thomson TO/MO", "DOS BASIC 2 × 320 Ko — 2 faces", "thomson.2s320", ".fd",
           lambda l: thomson_side(80, l) + thomson_side(80, l), 8),
    MkSpec("cpcdata", "Amstrad CPC", "AMSDOS Data (178 Ko, 40 pistes)", "cpc.data", ".dsk",
           lambda l: cpc_image(0xC1), 0, "Pour un lecteur 3,5\" branché en B: sur le CPC."),
    MkSpec("cpcsys", "Amstrad CPC", "AMSDOS Système / Vendor (169 Ko)", "cpc.system", ".dsk",
           lambda l: cpc_image(0x41), 0, "Pistes système vides (pas de CP/M)."),
    MkSpec("cpcibm", "Amstrad CPC", "AMSDOS IBM / CP/M (8 secteurs, 156 Ko)", "ibm.160", ".dsk",
           lambda l: cpc_image(0x01), 0, "Format IBM du CPC (compatible PC 160 Ko)."),
    MkSpec("d81", "Commodore", "1581 — 800 Ko", "commodore.1581", ".d81",
           lambda l: d81_image(l), 16),
]


def save_blank(spec: MkSpec, label: str, path: str):
    """Image vierge pour émulateur : DSK étendu pour le CPC, image brute sinon."""
    if spec.group == "Amstrad CPC":
        write_edsk(cpc_disk({"cpcdata": 0xC1, "cpcsys": 0x41}.get(spec.key, 0x01)), path)
        return
    with open(path, "wb") as f:
        f.write(spec.build(label))


def blank_for(fmt: str, capacity: int, fill: int = 0xE5) -> bytes:
    return bytes([fill]) * capacity
