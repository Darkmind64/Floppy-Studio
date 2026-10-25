"""Catalogue des formats disque et des types d'image, organisé par plateforme."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from greaseweazle.codec import codec
from greaseweazle.tools import util


@dataclass
class Preset:
    label: str
    fmt: Optional[str]          # diskdef greaseweazle (None = flux brut)
    ext: str                    # extension d'image proposée par défaut
    tracks: Optional[str] = None  # trackspec forcé (ex. "c=0-39:h=0")
    note: str = ""


@dataclass
class Platform:
    name: str
    presets: List[Preset] = field(default_factory=list)


# Libellés lisibles pour les formats courants.
_LABELS: Dict[str, str] = {
    "ibm.160": "160 Ko (5,25\" SS 8 sect.)",
    "ibm.180": "180 Ko (5,25\" SS 9 sect.)",
    "ibm.320": "320 Ko (5,25\" DS 8 sect.)",
    "ibm.360": "360 Ko (5,25\" DD)",
    "ibm.720": "720 Ko (3,5\" DD)",
    "ibm.800": "800 Ko (3,5\" DD 10 sect.)",
    "ibm.1200": "1,2 Mo (5,25\" HD)",
    "ibm.1440": "1,44 Mo (3,5\" HD)",
    "ibm.1680": "1,68 Mo (3,5\" HD 21 sect.)",
    "ibm.dmf": "DMF 1,68 Mo (Microsoft)",
    "ibm.2880": "2,88 Mo (3,5\" ED)",
    "ibm.scan": "Auto-détection (scan IBM MFM/FM)",
    "thomson.1s80": "80 Ko 1 face (5,25\" SD, FM)",
    "thomson.1s160": "160 Ko 1 face (5,25\" DD)",
    "thomson.2s160": "2 × 160 Ko 2 faces (5,25\" DD)",
    "thomson.1s320": "320 Ko 1 face (3,5\" DD)",
    "thomson.2s320": "2 × 320 Ko 2 faces (3,5\" DD)",
    "amiga.amigados": "AmigaDOS 880 Ko (DD)",
    "amiga.amigados_hd": "AmigaDOS 1,76 Mo (HD)",
    "atarist.360": "360 Ko (SS 9 sect.)",
    "atarist.400": "400 Ko (SS 10 sect.)",
    "atarist.440": "440 Ko (SS 11 sect.)",
    "atarist.720": "720 Ko (DS 9 sect.)",
    "atarist.800": "800 Ko (DS 10 sect.)",
    "atarist.880": "880 Ko (DS 11 sect.)",
    "commodore.1541": "1541 (5,25\" GCR)",
    "commodore.1571": "1571 (5,25\" GCR DS)",
    "commodore.1581": "1581 (3,5\" 800 Ko)",
    "cpc.data": "AMSDOS Data (9 × 512, ID C1)",
    "cpc.system": "AMSDOS Système (9 × 512, ID 41)",
    "akai.800": "Akai S900/S950 – 800 Ko (DD)",
    "akai.1600": "Akai S1000/S3000 – 1,6 Mo (HD)",
    "ensoniq.800": "Ensoniq EPS/ASR – 800 Ko (DD)",
    "ensoniq.1600": "Ensoniq EPS16+/ASR – 1,6 Mo (HD)",
    "ensoniq.mirage": "Ensoniq Mirage (DD 1 face)",
}

# Ordre et noms des plateformes, par préfixe de diskdef.
_PREFIX_NAMES: List[Tuple[str, str]] = [
    ("ibm", "PC / IBM"),
    ("thomson", "Thomson TO/MO"),
    ("amiga", "Amiga"),
    ("atarist", "Atari ST"),
    ("commodore", "Commodore"),
    ("apple2", "Apple II"),
    ("mac", "Macintosh"),
    ("acorn", "Acorn / BBC"),
    ("msx", "MSX"),
    ("zx", "ZX Spectrum"),
    ("atari", "Atari 8-bit"),
    ("pc98", "NEC PC-98"),
    ("sharp", "Sharp"),
    ("coco", "Tandy CoCo"),
    ("dragon", "Dragon"),
    ("dec", "DEC"),
    ("hp", "Hewlett-Packard"),
    ("raw", "Flux brut (générique)"),
]

# Extensions d'image préférées par préfixe.
_PREFIX_EXT = {
    "ibm": ".img", "thomson": ".fd", "amiga": ".adf", "atarist": ".st",
    "commodore": ".d64", "apple2": ".do", "mac": ".img", "acorn": ".ssd",
    "msx": ".dsk", "zx": ".img", "atari": ".img", "pc98": ".hdm",
    "sharp": ".2d", "akai": ".img", "ensoniq": ".img", "raw": ".scp",
}

_EXT_OVERRIDE = {
    "commodore.1571": ".d71", "commodore.1581": ".d81",
    "apple2.prodos.140": ".po", "acorn.dfs.ds": ".dsd", "acorn.dfs.ds80": ".dsd",
    "acorn.adfs.160": ".ads", "acorn.adfs.320": ".adm", "acorn.adfs.640": ".adl",
    "ibm.scan": ".imd", "cpc.data": ".dsk", "cpc.system": ".dsk",
}

# Descriptions des types d'image (extension -> libellé).
IMAGE_DESC = {
    ".img": "Image secteurs brute (IMG/IMA)", ".ima": "Image secteurs brute",
    ".st": "Atari ST", ".msa": "Atari ST compressée (MSA)",
    ".adf": "Amiga Disk File", ".d64": "Commodore 1541", ".d71": "Commodore 1571",
    ".d81": "Commodore 1581", ".fd": "Thomson FD", ".dsk": "DSK",
    ".edsk": "Extended DSK (Amstrad CPC)", ".2mg": "Apple II 2IMG", ".imd": "ImageDisk (IMD)",
    ".td0": "Teledisk", ".hfe": "HxC (HFE)", ".scp": "SuperCard Pro (flux brut)",
    ".raw": "KryoFlux stream (flux brut)", ".ipf": "CAPS/SPS IPF",
    ".dmk": "DMK (TRS-80, MSX…)", ".d88": "D88", ".hdm": "PC-98 HDM", ".xdf": "XDF",
    ".do": "Apple II ordre DOS", ".po": "Apple II ordre ProDOS", ".a2r": "Applesauce A2R",
}

FLUX_EXTS = {".scp", ".hfe", ".raw", ".a2r", ".ipf", ".ctr"}


@lru_cache(maxsize=1)
def all_formats() -> List[str]:
    fmts = codec.get_all_formats("", codec.DiskDef_File(name=None))
    return sorted(set(fmts))


def label_for(fmt: Optional[str]) -> str:
    if fmt is None:
        return "Flux brut (aucun décodage)"
    if fmt in _LABELS:
        return _LABELS[fmt]
    return fmt.split(".", 1)[1] if "." in fmt else fmt


def ext_for(fmt: Optional[str]) -> str:
    if fmt is None:
        return ".scp"
    if fmt in _EXT_OVERRIDE:
        return _EXT_OVERRIDE[fmt]
    return _PREFIX_EXT.get(fmt.split(".")[0], ".img")


@lru_cache(maxsize=1)
def platforms() -> List[Platform]:
    fmts = all_formats()
    by_prefix: Dict[str, List[str]] = {}
    for f in fmts:
        by_prefix.setdefault(f.split(".")[0], []).append(f)

    def presets(prefix: str) -> List[Preset]:
        out = [Preset(label_for(f), f, ext_for(f)) for f in by_prefix.get(prefix, [])]
        # Formats « labellisés » d'abord, dans l'ordre du dictionnaire.
        order = {k: i for i, k in enumerate(_LABELS)}
        out.sort(key=lambda p: (order.get(p.fmt, 999), p.fmt))
        return out

    plats: List[Platform] = []
    for prefix, name in _PREFIX_NAMES[:5]:
        if prefix in by_prefix:
            plats.append(Platform(name, presets(prefix)))

    plats.append(Platform("Amstrad CPC", [
        Preset("AMSDOS Data (40 pistes, 9 × 512, ID C1)", "cpc.data", ".dsk", None,
               "Format CPC le plus courant (178 Ko)."),
        Preset("AMSDOS Système / Vendor (40 pistes, ID 41)", "cpc.system", ".dsk", None,
               "Disquettes système CP/M (169 Ko utiles)."),
        Preset("Auto (scan) – 40 pistes, 1 face", "ibm.scan", ".edsk", "c=0-39:h=0",
               "Lecteur 3,5\" : disquettes 3,5\" formatées CPC (40 pistes)."),
        Preset("Auto (scan) – 80 pistes, 2 faces", "ibm.scan", ".edsk", "c=0-79:h=0-1",
               "Formats étendus (Parados, Romdos, Vortex…)."),
        Preset("Auto (scan) – 40 pistes, 2 faces", "ibm.scan", ".edsk", "c=0-39:h=0-1"),
    ]))

    plats.append(Platform("Sampleurs & synthés",
        [p for p in presets("akai") + presets("ensoniq")] + [
        Preset("Format PC 720 Ko (Yamaha, Korg… compatibles DOS)", "ibm.720", ".img"),
        Preset("Format PC 1,44 Mo (Kurzweil, Yamaha… compatibles DOS)", "ibm.1440", ".img"),
        Preset("Autre / propriétaire : flux brut", None, ".scp",
               note="Capture fidèle du flux, décodable plus tard."),
    ]))

    used = {"ibm", "thomson", "amiga", "atarist", "commodore", "akai", "ensoniq"}
    for prefix, name in _PREFIX_NAMES[5:]:
        if prefix in by_prefix:
            plats.append(Platform(name, presets(prefix)))
            used.add(prefix)
    others = sorted(p for p in by_prefix if p not in used)
    if others:
        plats.append(Platform("Autres systèmes", [
            Preset(f, f, ext_for(f)) for p in others for f in by_prefix[p]]))
    plats.append(Platform("Flux brut / archivage", [
        Preset("SuperCard Pro (.scp)", None, ".scp"),
        Preset("HxC Floppy Emulator (.hfe)", None, ".hfe"),
        Preset("KryoFlux stream (.raw)", None, ".raw"),
    ]))
    return plats


CUSTOM_DISKDEFS = """
disk cpc.data
    cyls = 40
    heads = 1
    tracks * ibm.mfm
        secs = 9
        bps = 512
        id = 0xc1
        gap3 = 82
        interleave = 2
        rate = 250
    end
end
disk cpc.system
    cyls = 40
    heads = 1
    tracks * ibm.mfm
        secs = 9
        bps = 512
        id = 0x41
        gap3 = 82
        interleave = 2
        rate = 250
    end
end
"""


def _custom_cfg() -> str:
    import tempfile
    p = os.path.join(tempfile.gettempdir(), "floppystudio_diskdefs.cfg")
    try:
        with open(p, "r") as f:
            if f.read() == CUSTOM_DISKDEFS:
                return p
    except OSError:
        pass
    with open(p, "w") as f:
        f.write(CUSTOM_DISKDEFS)
    return p


@lru_cache(maxsize=None)
def get_diskdef(fmt: str):
    try:
        if fmt.startswith("cpc."):
            return codec.get_diskdef(fmt, _custom_cfg())
        return codec.get_diskdef(fmt)
    except Exception:
        return None


@dataclass
class Geometry:
    cyls: int
    heads: int
    capacity: int       # octets décodés
    nsec: int           # secteurs sur la piste 0.0
    desc: str


@lru_cache(maxsize=None)
def geometry(fmt: Optional[str]) -> Optional[Geometry]:
    if not fmt:
        return None
    d = get_diskdef(fmt)
    if d is None:
        return None
    cap, nsec = 0, 0
    for (c, h) in d.track_map:
        try:
            t = d.mk_track(c, h)
            if (c, h) == (0, 0):
                nsec = t.nsec
            cap += len(t.get_img_track())
        except Exception:
            pass
    parts = [f"{d.cyls} cyl × {d.heads} face{'s' if d.heads > 1 else ''}"]
    if nsec:
        parts.append(f"{nsec} secteurs/piste")
    if cap:
        parts.append(human_size(cap))
    return Geometry(d.cyls, d.heads, cap, nsec, " · ".join(parts))


def human_size(n: int) -> str:
    k = n / 1024
    if k >= 1000:
        return f"{k / 1000:.2f} Mo".replace(".", ",")
    return f"{k:.0f} Ko"


def image_class(path: str, fmt: Optional[str] = None):
    """Classe d'image greaseweazle ; un .dsk CPC (format CPC demandé, ou en-tête EDSK) est un Extended DSK."""
    if os.path.splitext(path)[1].lower() == ".dsk":
        if fmt and fmt.startswith(("cpc.", "ibm.scan")):
            return util.get_image_class("x.edsk")
        head = b""
        try:
            with open(path, "rb") as f:
                head = f.read(16)
        except OSError:
            pass
        if head.startswith((b"EXTENDED CPC DSK", b"MV - CPC")):
            return util.get_image_class("x.edsk")
    return util.get_image_class(path)


def image_filter(explore: bool = False) -> str:
    exts = sorted(set(util.image_types) | ({".2mg", ".ima", ".vfd", ".flp", ".edsk"} if explore else set()))
    allf = " ".join("*" + e for e in exts)
    lines = [f"Toutes les images ({allf})"]
    for e in exts:
        lines.append(f"{IMAGE_DESC.get(e, e[1:].upper())} (*{e})")
    return ";;".join(lines)


def default_format_for(path: str) -> Optional[str]:
    try:
        return util.get_image_class(path).default_format
    except Exception:
        return None


def is_flux_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in FLUX_EXTS


# Candidats pour l'analyse automatique (formats fréquents, IBM d'abord).
ANALYSE_CANDIDATES = [
    "ibm.1440", "ibm.720", "ibm.2880", "ibm.dmf", "ibm.1680", "ibm.800",
    "ibm.360", "ibm.1200",
    "thomson.1s320", "thomson.2s320",
    "amiga.amigados", "amiga.amigados_hd",
    "atarist.720", "atarist.800", "atarist.880", "atarist.360",
    "commodore.1581",
    "akai.800", "akai.1600", "ensoniq.800", "ensoniq.1600", "ensoniq.mirage",
    "acorn.adfs.640", "acorn.adfs.800", "acorn.adfs.1600",
    "msx.2dd", "pc98.2hd", "mac.800", "mac.400", "cpc.data", "cpc.system",
]


_SIZE_GROUPS = {".img": {".img", ".ima"}, ".ima": {".img", ".ima"}}


def guess_by_size(path: str) -> List[str]:
    """Formats dont la capacité correspond à la taille d'une image secteur brute."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".img", ".ima", ".st", ".fd", ".dsk"):
        return []
    try:
        size = os.path.getsize(path)
    except OSError:
        return []
    exts = _SIZE_GROUPS.get(ext, {ext})
    out, seen = [], set()
    for p in platforms():
        for pr in p.presets:
            if pr.fmt and pr.fmt not in seen and pr.ext in exts:
                seen.add(pr.fmt)
                g = geometry(pr.fmt)
                if g and g.capacity == size:
                    out.append(pr.fmt)
    return out


def platform_of(fmt: Optional[str]) -> Optional[str]:
    if fmt is None:
        return None
    for p in platforms():
        if any(pr.fmt == fmt for pr in p.presets):
            return p.name
    return None
