"""Akai S900/S950 (DD 800 Ko) et S1000/S3000 (HD 1,6 Mo) — expérimental."""
from __future__ import annotations

import struct
from typing import List, Optional

from .base import Entry, FileSystem, human, u16

AKAI_CHARS = "0123456789 ABCDEFGHIJKLMNOPQRSTUVWXYZ#+-."
BLOCK = 1024
NDIR = 64
FAT_OFF = 0x600
TYPES = {0x70: "Programme S1000", 0x73: "Sample S1000", 0x78: "Effets", 0x71: "Liste QL",
         0x64: "Drum settings", 0x6D: "Multi", 0xF0: "Programme S3000", 0xF3: "Sample S3000",
         0xED: "Multi S3000", 0x63: "Cue list", 0x53: "Sample S900", 0x50: "Programme S900",
         0x44: "Drum S900", 0x4F: "Overall S900"}
SAMPLE_TYPES = (0x73, 0xF3, 0x53)


def akai_str(b: bytes) -> Optional[str]:
    if all(c < len(AKAI_CHARS) for c in b):
        return "".join(AKAI_CHARS[c] for c in b).rstrip()
    return None


class AkaiFS(FileSystem):
    platform = "akai"
    charset = "latin-1"

    def __init__(self, data: bytes, s900: bool):
        super().__init__()
        self.d = data
        self.s900 = s900
        self.nblocks = len(data) // BLOCK
        self.name = "Akai " + ("S900/S950" if s900 else "S1000/S3000") + " (expérimental)"
        self.fat = [u16(data, FAT_OFF + i * 2) for i in range(self.nblocks)]
        lbl_off = FAT_OFF + self.nblocks * 2
        self.label = (akai_str(data[lbl_off:lbl_off + 12]) or "") if not s900 else ""
        for i in range(NDIR):
            e = data[i * 24:(i + 1) * 24]
            if not any(e) or e[0x10] == 0:
                continue
            name = (e[0:10].decode("ascii", "replace").rstrip() if s900 else akai_str(e[0:12]))
            if not name:
                continue
            ftype = e[0x10]
            size = e[0x11] | e[0x12] << 8 | e[0x13] << 16
            start = u16(e, 0x14)
            kind = TYPES.get(ftype, f"type 0x{ftype:02X}")
            self.root.add(Entry(name, size, False, kind, "", "",
                                {"type": f"0x{ftype:02X}", "bloc de départ": start}, (start, ftype)))
        used = sum(1 for v in self.fat if v)
        self.info = [("Système", self.name), ("Volume", self.label or "—"),
                     ("Blocs", f"{self.nblocks} × 1 Ko"), ("Libre", human((self.nblocks - used) * BLOCK)),
                     ("Fichiers", str(len(self.files)))]

    def read(self, e: Entry) -> bytes:
        start, _ = e.ref
        out, b, seen = bytearray(), start, set()
        while 0 < b < self.nblocks and b not in seen and len(out) < e.size:
            seen.add(b)
            out += self.d[b * BLOCK:(b + 1) * BLOCK]
            nxt = self.fat[b]
            if nxt == 0 or nxt >= 0x4000:
                break
            b = nxt
        if len(out) < e.size:  # chaîne incomplète : lecture contiguë
            out = bytearray(self.d[start * BLOCK:start * BLOCK + e.size])
        return bytes(out[:e.size])


def sample_to_wav(data: bytes, ftype: int) -> Optional[bytes]:
    """Échantillon S1000/S3000 → WAV 16 bits mono."""
    if ftype not in (0x73, 0xF3) or len(data) < 0xC0:
        return None
    hdr = 0x96 if ftype == 0x73 else 0xBE
    rate = u16(data, 0x8A) or 44100
    n = struct.unpack_from("<I", data, 0x1A)[0]
    pcm = data[hdr:hdr + n * 2]
    return wav16(pcm, rate)


def wav16(pcm: bytes, rate: int, channels: int = 1, bits: int = 16) -> bytes:
    ba = channels * bits // 8
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * ba, ba, bits) +
            b"data" + struct.pack("<I", len(pcm)) + pcm)


def probe(disk) -> List[FileSystem]:
    d = disk.linear()
    if len(d) not in (819200, 1638400):
        return []
    # S1000 : noms en jeu de caractères Akai
    for s900 in (False, True):
        ok = bad = 0
        for i in range(NDIR):
            e = d[i * 24:(i + 1) * 24]
            if not any(e):
                continue
            if e[0x10] == 0:
                continue
            nm = e[0:10].decode("ascii", "ignore") if s900 else akai_str(e[0:12])
            if s900:
                good = all(32 <= c < 127 for c in e[0:10]) and e[0x10] in TYPES
            else:
                good = nm is not None and nm.strip() != ""
            ok += good
            bad += not good
        if ok and bad == 0:
            try:
                return [AkaiFS(d, s900)]
            except Exception:
                return []
    return []
