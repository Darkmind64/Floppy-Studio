"""Lancement d'émulateurs pour exécuter une image ou un fichier."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import QSettings

PLATFORM_NAMES = {"pc": "PC / MS-DOS", "atarist": "Atari ST", "amiga": "Amiga", "c64": "Commodore 64",
                  "cpc": "Amstrad CPC", "thomson": "Thomson", "msx": "MSX", "akai": "Akai"}


@dataclass
class Emu:
    platform: str
    name: str
    exe: str = ""
    args_image: str = ""
    args_file: str = ""
    candidates: str = ""        # noms d'exécutables pour la détection automatique (séparés par ;)
    url: str = ""


DEFAULTS: List[Emu] = [
    Emu("pc", "DOSBox / DOSBox-X / DOSBox Staging", "",
        '-c "imgmount a {image} -t floppy" -c "a:" -c "dir"',
        '-c "mount c {dir}" -c "c:" -c "{file}"',
        "dosbox-x.exe;dosbox.exe;dosbox_with_debugger.exe", "https://dosbox-x.com"),
    Emu("atarist", "Hatari", "", '--disk-a "{image}"', "", "hatari.exe",
        "https://hatari.tuxfamily.org"),
    Emu("amiga", "WinUAE / FS-UAE", "", '-s floppy0="{image}"', "",
        "winuae64.exe;winuae.exe;fs-uae.exe", "https://www.winuae.net"),
    Emu("c64", "VICE (x64sc)", "", '-autostart "{image}"', '-autostart "{file}"',
        "x64sc.exe;x64.exe", "https://vice-emu.sourceforge.io"),
    Emu("cpc", "WinAPE / Caprice32", "", '"{image}" /A', "", "WinAPE.exe;cap32.exe",
        "http://www.winape.net"),
    Emu("thomson", "DCMOTO / Teo", "", '"{image}"', "", "dcmoto.exe;dcmoto_fr.exe;teo.exe",
        "http://dcmoto.free.fr"),
    Emu("msx", "openMSX", "", '-diska "{image}"', "", "openmsx.exe", "https://openmsx.org"),
]

SEARCH_DIRS = [os.environ.get("ProgramFiles", r"C:\Program Files"),
               os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
               os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
               os.path.join(os.path.expanduser("~"), "scoop", "apps"),
               r"C:\Emulateurs", r"C:\Emulators", r"C:\Emu", r"D:\Emulateurs", r"D:\Emulators",
               os.path.join(os.path.expanduser("~"), "Desktop"),
               os.path.join(os.path.expanduser("~"), "Downloads")]


class EmuConfig:
    def __init__(self):
        self.s = QSettings("FloppyStudio", "FloppyStudio")
        self.emus: Dict[str, Emu] = {e.platform: Emu(**asdict(e)) for e in DEFAULTS}
        try:
            saved = json.loads(self.s.value("emulators", "{}"))
            for k, v in saved.items():
                if k in self.emus:
                    for f in ("exe", "args_image", "args_file"):
                        if f in v:
                            setattr(self.emus[k], f, v[f])
        except Exception:
            pass

    def save(self):
        self.s.setValue("emulators", json.dumps(
            {k: {"exe": e.exe, "args_image": e.args_image, "args_file": e.args_file}
             for k, e in self.emus.items()}))

    def get(self, platform: str) -> Optional[Emu]:
        return self.emus.get(platform)

    def autodetect(self, max_depth: int = 4) -> List[str]:
        found = []
        for e in self.emus.values():
            if e.exe and os.path.isfile(e.exe):
                continue
            names = [n.lower() for n in e.candidates.split(";") if n]
            hit = None
            for n in names:
                p = shutil.which(n)
                if p:
                    hit = p
                    break
            if not hit:
                for root in SEARCH_DIRS:
                    if not root or not os.path.isdir(root):
                        continue
                    base_depth = root.rstrip("\\/").count(os.sep)
                    for dp, dns, fns in os.walk(root):
                        if dp.count(os.sep) - base_depth >= max_depth:
                            dns[:] = []
                        for f in fns:
                            if f.lower() in names:
                                hit = os.path.join(dp, f)
                                break
                        if hit:
                            break
                    if hit:
                        break
            if hit:
                e.exe = hit
                found.append(f"{PLATFORM_NAMES.get(e.platform)} : {hit}")
        self.save()
        return found


def session_dir() -> str:
    d = os.path.join(tempfile.gettempdir(), "FloppyStudio")
    os.makedirs(d, exist_ok=True)
    return d


def launch(emu: Emu, image: Optional[str] = None, file: Optional[str] = None,
           directory: Optional[str] = None) -> subprocess.Popen:
    if not emu.exe or not os.path.isfile(emu.exe):
        raise FileNotFoundError("Émulateur non configuré")
    tpl = emu.args_file if file and emu.args_file else emu.args_image
    args = tpl.format(image=image or "", file=file or "", dir=directory or "")
    cmd = f'"{emu.exe}" {args}'
    return subprocess.Popen(cmd, cwd=os.path.dirname(emu.exe),
                            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
