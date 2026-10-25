"""Systèmes de fichiers des disquettes rétro."""
from __future__ import annotations

from typing import List, Optional, Tuple

from . import acorn, akai, atari8, mac, oric, zx, amiga, apple, cbm, cpm, fat, thomson
from .base import Entry, FileSystem, human
from .disk import Disk, open_disk, write_edsk

PROBES = [cbm.probe, apple.probe, mac.probe, amiga.probe, fat.probe, thomson.probe, zx.probe, cpm.probe, acorn.probe, atari8.probe, oric.probe, akai.probe]


def detect(disk: Disk) -> List[FileSystem]:
    for p in PROBES:
        try:
            found = p(disk)
        except Exception:
            found = []
        if found:
            return found
    return []


def open_image(path: str, fmt: Optional[str] = None) -> Tuple[Disk, List[FileSystem]]:
    disk = open_disk(path, fmt)
    return disk, detect(disk)
