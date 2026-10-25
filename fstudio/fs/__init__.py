"""Systèmes de fichiers des disquettes rétro."""
from __future__ import annotations

from typing import List, Optional, Tuple

from . import akai, amiga, cbm, cpm, fat, thomson
from .base import Entry, FileSystem, human
from .disk import Disk, open_disk, write_edsk

PROBES = [cbm.probe, amiga.probe, fat.probe, thomson.probe, cpm.probe, akai.probe]


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
