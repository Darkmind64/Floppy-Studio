"""Moteur : connexion Greaseweazle et tâches (lecture, écriture, outils) en thread."""
from __future__ import annotations

import contextlib
import copy
import os
import io
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import serial
from PySide6.QtCore import QObject, QThread, Signal

from greaseweazle import error as gw_error
from greaseweazle import track as gw_track
from greaseweazle import usb as USB
from greaseweazle.codec import codec
from greaseweazle.image.img import IMG
from greaseweazle.track import MasterTrack
from greaseweazle.tools import util

from . import formats as F

PLLS = gw_track.plls

HIST_BINS = 160          # 0 → 16 µs
HIST_STEP_US = 0.1

MODELS = {
    1: {0: "F1", 1: "F1 Plus", 2: "F1 Plus (Unbuffered)"},
    4: {0: "V4", 1: "V4 Slim", 2: "V4.1"},
    7: {0: "F7 v1", 1: "F7 Plus v1", 2: "F7 Lightning", 3: "F7 v2",
        4: "F7 Plus v2", 5: "F7 Lightning Plus", 6: "F7 Slim", 7: "F7 v3 Thunderbolt"},
    8: {0: "Adafruit Floppy"},
}
MCUS = {2: "AT32F403", 7: "AT32F403A", 5: "AT32F415"}
DRIVES = {"A": (USB.BusType.IBMPC, 0), "B": (USB.BusType.IBMPC, 1),
          "0": (USB.BusType.Shugart, 0), "1": (USB.BusType.Shugart, 1),
          "2": (USB.BusType.Shugart, 2), "3": (USB.BusType.Shugart, 3)}


class Cancelled(Exception):
    pass


# --------------------------------------------------------------------------
# Redirection de stdout (les outils greaseweazle impriment) vers le journal.
# --------------------------------------------------------------------------
class _StdoutRouter(io.TextIOBase):
    def __init__(self, orig):
        self.orig = orig
        self.sink: Optional[Callable[[str], None]] = None
        self._buf = ""
        self._lock = threading.Lock()

    def write(self, s):
        if self.orig:
            try:
                self.orig.write(s)
            except Exception:
                pass
        sink = self.sink
        if sink is None:
            return len(s)
        with self._lock:
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    sink(line.rstrip())
        return len(s)

    def flush(self):
        pass


STDOUT = _StdoutRouter(sys.stdout)


def install_stdout_router():
    sys.stdout = STDOUT
    sys.stderr = STDOUT


# --------------------------------------------------------------------------
# Connexion
# --------------------------------------------------------------------------
@dataclass
class DeviceInfo:
    port: str
    model: str
    firmware: Tuple[int, int]
    serial: str
    mcu: str
    usb: str
    sample_freq: int
    update_mode: bool

    def lines(self) -> List[Tuple[str, str]]:
        return [("Port", self.port), ("Modèle", self.model),
                ("Firmware", "%d.%d" % self.firmware + (" (bootloader)" if self.update_mode else "")),
                ("N° série", self.serial), ("MCU", self.mcu), ("USB", self.usb),
                ("Échantillonnage", f"{self.sample_freq / 1e6:.0f} MHz")]


def list_ports() -> List[Tuple[str, str, bool]]:
    """(port, description, est_un_greaseweazle) triés : Greaseweazle d'abord."""
    from serial.tools.list_ports import comports
    out = []
    for p in comports():
        gw = util.score_port(p) > 0
        desc = p.description or p.device
        out.append((p.device, desc, gw))
    out.sort(key=lambda x: (not x[2], x[0]))
    return out


class Device:
    """Connexion unique, partagée par les tâches (une seule tâche à la fois)."""

    def __init__(self):
        self.unit: Optional[USB.Unit] = None
        self.info: Optional[DeviceInfo] = None
        self.lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self.unit is not None

    def open(self, port: Optional[str]) -> DeviceInfo:
        self.close()
        if not port:
            port = util.find_port()
        try:
            unit = util.usb_open(port, mode_check=False)
        except SystemExit:
            raise gw_error.Fatal("Le périphérique a refusé la connexion.")
        if unit.update_mode and unit.can_mode_switch:
            unit = util.usb_reopen(unit, False)
        info = self._describe(unit, port)
        if not unit.update_mode and getattr(unit, "update_needed", False):
            unit.ser.close()
            raise gw_error.Fatal("Firmware %d.%d trop ancien : mise à jour nécessaire." % unit.version)
        self.unit, self.info = unit, info
        return info

    @staticmethod
    def _describe(u: USB.Unit, port: str) -> DeviceInfo:
        try:
            model = MODELS[u.hw_model][u.hw_submodel]
            if u.hw_model != 8:
                model = "Greaseweazle " + model
        except KeyError:
            model = "Inconnu (0x%02X%02X)" % (u.hw_model, u.hw_submodel)
        mcu = [MCUS.get(u.mcu_id, "STM32" if u.mcu_id == 0 else "0x%02X" % u.mcu_id)]
        if u.mcu_mhz:
            mcu.append(f"{u.mcu_mhz} MHz")
        if u.mcu_sram_kb:
            mcu.append(f"{u.mcu_sram_kb} Ko SRAM")
        pi = getattr(u, "port_info", None)
        ser = (pi.serial_number if pi and pi.serial_number else "—")
        usb = {0: "Full Speed (12 Mbit/s)", 1: "High Speed (480 Mbit/s)"}.get(u.usb_speed, "?")
        if u.usb_buf_kb:
            usb += f", tampon {u.usb_buf_kb} Ko"
        return DeviceInfo(port, model, u.version, ser, ", ".join(mcu), usb,
                          getattr(u, "sample_freq", 0), u.update_mode)

    def close(self):
        if self.unit is not None:
            try:
                self.unit.ser.close()
            except Exception:
                pass
        self.unit = None


# --------------------------------------------------------------------------
# Résultats par piste
# --------------------------------------------------------------------------
@dataclass
class TrackResult:
    cyl: int
    head: int
    status: str                      # ok | retried | bad | empty | flux | written | verified | failed | erased | skipped
    nsec: int = 0
    good: List[bool] = field(default_factory=list)
    retries: int = 0
    summary: str = ""
    hist: List[int] = field(default_factory=list)
    rpm: float = 0.0
    nflux: int = 0
    quality: float = 0.0             # % d'intervalles proches d'un pic
    jitter: float = 0.0
    peak: float = 0.0                # premier pic (µs)
    encoding: str = ""
    sectors: List[dict] = field(default_factory=list)
    weak: List[int] = field(default_factory=list)

    def enrich(self, dat=None, flux=None, fmt_cls=None, deep=False):
        from . import analysis as A
        if self.hist:
            self.quality, self.jitter = A.flux_quality(self.hist)
            self.peak = A.peak_us(self.hist)
        if dat is not None:
            self.encoding = A.encoding_of(dat)
            self.sectors = A.sector_info(dat)
        if deep and flux is not None:
            try:
                sc = F.get_diskdef("ibm.scan").decode_flux(self.cyl, self.head, flux)
                info = A.sector_info(sc)
                if len(info) > len(self.sectors) or (info and self.sectors and self.sectors[0]["n"] is None):
                    self.sectors = info
                    if not self.encoding or self.encoding == "—":
                        self.encoding = A.encoding_of(sc)
            except Exception:
                pass
            if fmt_cls is not None:
                try:
                    self.weak = A.weak_sectors(fmt_cls, self.cyl, self.head, flux)
                except Exception:
                    self.weak = []
        return self

    @property
    def nbad(self) -> int:
        return self.good.count(False)


def flux_histogram(flux) -> List[int]:
    h = [0] * HIST_BINS
    k = 1e6 / flux.sample_freq / HIST_STEP_US
    for x in flux.list:
        i = int(x * k)
        if i < HIST_BINS:
            h[i] += 1
    return h


def flux_rpm(flux) -> float:
    try:
        return 60.0 / flux.time_per_rev
    except Exception:
        return 0.0


def density_guess(hist: List[int]) -> str:
    """Estimation de densité à partir du premier pic de l'histogramme."""
    if not hist or max(hist) == 0:
        return "aucun flux (piste vierge ?)"
    thr = max(hist) * 0.15
    first = next((i for i, v in enumerate(hist) if v >= thr), None)
    if first is None:
        return "?"
    peak = max(range(first, min(first + 10, HIST_BINS)), key=lambda i: hist[i])
    us = peak * HIST_STEP_US
    if us < 1.4:
        return f"ED ~1 Mbit/s (pic {us:.1f} µs)"
    if us < 2.6:
        return f"HD ~500 kbit/s (pic {us:.1f} µs)"
    if us < 3.4:
        return f"DD 300 tr/min 360 ou GCR (pic {us:.1f} µs)"
    if us < 5.0:
        return f"DD ~250 kbit/s (pic {us:.1f} µs)"
    return f"SD/FM ~125 kbit/s (pic {us:.1f} µs)"


# --------------------------------------------------------------------------
# Tâche de base
# --------------------------------------------------------------------------
class Job(QThread):
    log = Signal(str, str)                 # message, niveau (info|ok|warn|err)
    track_started = Signal(int, int)
    track_done = Signal(object)            # TrackResult
    progress = Signal(int, int)
    result = Signal(object)                # dict libre
    failed = Signal(str)

    title = "Tâche"
    needs_drive = True

    def __init__(self, dev: Device, drive: str = "A"):
        super().__init__()
        self.dev = dev
        self.drive = drive
        self._cancel = False

    # API
    def cancel(self):
        self._cancel = True

    def check(self):
        if self._cancel:
            raise Cancelled()

    def info(self, s):
        self.log.emit(s, "info")

    def ok(self, s):
        self.log.emit(s, "ok")

    def warn(self, s):
        self.log.emit(s, "warn")

    # Exécution
    def run(self):
        STDOUT.sink = lambda s: self.log.emit(s, "dim")
        try:
            with self.dev.lock:
                if self.needs_drive:
                    u = self.dev.unit
                    if u is None:
                        raise gw_error.Fatal("Aucun Greaseweazle connecté.")
                    self._with_drive(u)
                else:
                    self.work(self.dev.unit)
        except Cancelled:
            self.log.emit("Opération annulée.", "warn")
            self.failed.emit("Annulé")
        except USB.CmdError as e:
            self.log.emit(f"Commande refusée par le Greaseweazle : {e}", "err")
            self.failed.emit(str(e))
        except gw_error.Fatal as e:
            self.log.emit(str(e), "err")
            self.failed.emit(str(e))
        except (serial.SerialException, OSError) as e:
            self.log.emit(f"Erreur de communication : {e}", "err")
            self.failed.emit(str(e))
        except SystemExit:
            self.log.emit("Le périphérique a interrompu l'opération.", "err")
            self.failed.emit("SystemExit")
        except Exception as e:
            self.log.emit("Erreur inattendue : %s\n%s" % (e, traceback.format_exc()), "err")
            self.failed.emit(str(e))
        finally:
            STDOUT.sink = None

    def _with_drive(self, u: USB.Unit):
        bus, unit_id = DRIVES[self.drive]
        try:
            u.set_bus_type(bus.value)
        except USB.CmdError as err:
            if err.code == USB.Ack.BadCommand:
                raise gw_error.Fatal("Type de bus non supporté par ce matériel.")
            raise
        try:
            u.drive_select(unit_id)
            u.drive_motor(unit_id, True)
            self.work(u)
        finally:
            try:
                if self._cancel:
                    u.reset()
                u.drive_motor(unit_id, False)
                u.drive_deselect()
            except Exception:
                pass

    def work(self, u: USB.Unit):
        raise NotImplementedError


def track_list(ts) -> List[Tuple[int, int, int, int]]:
    """(cyl_physique, tête_physique, cyl, tête) — TrackIter n'est pas itérable en compréhension."""
    out = []
    for t in ts:
        out.append((t.physical_cyl, t.physical_head, t.cyl, t.head))
    return out


DOUBLE_STEP = False     # disquettes 40 pistes dans un lecteur 80 pistes


def _trackset(fmt_cls, spec: Optional[str], default: str) -> util.TrackSet:
    if fmt_cls is not None:
        ts = copy.copy(fmt_cls.tracks)
        ts.cyls, ts.heads = list(ts.cyls), list(ts.heads)
        ts.h_off = list(ts.h_off)
    else:
        ts = util.TrackSet(default)
    if spec:
        ts.update_from_trackspec(spec)
    if DOUBLE_STEP and ts.step == 1 and ts.cyls and max(ts.cyls) <= 43 and "step=" not in (spec or ""):
        ts.step = 2
    return ts


# --------------------------------------------------------------------------
# Lecture
# --------------------------------------------------------------------------
class ReadJob(Job):
    title = "Lecture"

    def __init__(self, dev, drive, path: str, fmt: Optional[str], tracks: Optional[str],
                 revs: Optional[int], retries: int, seek_retries: int,
                 flux_copy: Optional[str] = None, overwrite: bool = True, deep: bool = False):
        super().__init__(dev, drive)
        self.deep = deep
        self.path, self.fmt, self.tracks = path, fmt, tracks
        self.revs, self.retries, self.seek_retries = revs, retries, seek_retries
        self.flux_copy = flux_copy
        self.overwrite = overwrite
        self.results: Dict[Tuple[int, int], TrackResult] = {}

    def _read(self, u, revs, ticks, tpr):
        flux = u.read_track(revs=revs, ticks=ticks)
        flux._ticks_per_rev = tpr
        return flux

    def work(self, u):
        self._oric_target = None
        ext = os.path.splitext(self.path)[1].lower()
        if self.fmt and ((self.fmt.startswith("oric.") and ext == ".dsk") or
                         (self.fmt.startswith("atari.") and ext in (".atr", ".xfd")) or ext == ".trd"):
            self._oric_target, self.path = self.path, os.path.splitext(self.path)[0] + "_secteurs.img"
        try:
            self._work(u)
        finally:
            if self._oric_target:
                self._oric_finish()

    def _oric_finish(self):
        """Image secteurs → format natif demandé : MFM_DISK (Oric), ATR / XFD (Atari), TRD (Spectrum)."""
        tmp, target, self._oric_target = self.path, self._oric_target, None
        self.path = target
        if not os.path.exists(tmp):
            return
        from .fs.disk import open_disk, write_oric_mfm
        ext = os.path.splitext(target)[1].lower()
        try:
            if ext == ".dsk":
                write_oric_mfm(open_disk(tmp, self.fmt), target)
            else:
                with open(tmp, "rb") as f:
                    data = f.read()
                if ext == ".atr":
                    ssize = 128
                    para = len(data) // 16
                    data = bytes([0x96, 0x02, para & 0xFF, para >> 8 & 0xFF, ssize & 0xFF, ssize >> 8,
                                  para >> 16 & 0xFF]) + bytes(9) + data
                with open(target, "wb") as f:
                    f.write(data)
        finally:
            os.remove(tmp)

    def _work(self, u):
        img_cls = F.image_class(self.path, self.fmt)
        raw = F.is_flux_image(self.path) or self.fmt is None
        fmt_cls = F.get_diskdef(self.fmt) if self.fmt else None
        if self.fmt and fmt_cls is None:
            raise gw_error.Fatal(f"Format inconnu : {self.fmt}")
        ts = _trackset(fmt_cls, self.tracks, "c=0-79:h=0-1")
        revs = self.revs if self.revs else (fmt_cls.default_revs if fmt_cls else 3)
        ticks, tpr = 0, None
        if isinstance(revs, float):
            if raw:
                revs = 2
            else:
                tpr = u.read_track(2).ticks_per_rev
                ticks, revs = int(tpr * revs), 2

        tracks = track_list(ts)
        self.info(f"Lecture de {len(tracks)} pistes ({ts}) → {self.path}")
        if self.fmt:
            self.info(f"Format : {self.fmt}  ({F.label_for(self.fmt)})")

        image = img_cls.to_file(self.path, None if raw else fmt_cls, not self.overwrite, {})
        flux_img = None
        if self.flux_copy and not raw:
            flux_img = F.image_class(self.flux_copy).to_file(self.flux_copy, None, False, {})

        t0 = time.monotonic()
        with contextlib.ExitStack() as stack:
            stack.enter_context(image)
            if flux_img is not None:
                stack.enter_context(flux_img)
            for i, (pc, ph, c, h) in enumerate(tracks):
                self.check()
                self.track_started.emit(c, h)
                self.progress.emit(i, len(tracks))
                res, flux, dat = self._read_track(u, pc, ph, c, h, fmt_cls, raw, revs, ticks, tpr)
                if raw:
                    image.emit_track(c, h, flux)
                elif dat is not None:
                    image.emit_track(c, h, dat)
                if flux_img is not None:
                    flux_img.emit_track(c, h, flux)
                self.results[c, h] = res
                self.track_done.emit(res)
            self.progress.emit(len(tracks), len(tracks))

        self._summary(time.monotonic() - t0, raw)

    def _read_track(self, u, pc, ph, c, h, fmt_cls, raw, revs, ticks, tpr):
        tag = f"T{c}.{h}" + (f" ← {pc}.{ph}" if (pc, ph) != (c, h) else "")
        u.seek(pc, ph)
        flux = self._read(u, revs, ticks, tpr)
        hist, rpm, nflux = flux_histogram(flux), flux_rpm(flux), len(flux.list)
        if fmt_cls is None:
            self.info(f"{tag} : {flux.summary_string()}")
            r = TrackResult(c, h, "flux", summary=flux.summary_string(), hist=hist, rpm=rpm, nflux=nflux)
            return r.enrich(None, flux, None, self.deep), flux, None

        dat = fmt_cls.decode_flux(c, h, flux)
        if dat is None:
            self.warn(f"{tag} : hors du format, ignorée")
            r = TrackResult(c, h, "skipped", hist=hist, rpm=rpm, nflux=nflux)
            return r.enrich(None, flux, None, self.deep), flux, None
        for pll in PLLS[1:]:
            if dat.nr_missing() == 0:
                break
            dat.decode_flux(flux, pll)

        retry, seek_retry, total = 0, 0, 0
        while dat.nr_missing() != 0:
            self.check()
            if self.retries == 0 or retry % self.retries == 0:
                if self.retries == 0 or seek_retry > self.seek_retries:
                    break
                if retry != 0:
                    u.seek(0, 0)
                    u.seek(pc, ph)
                seek_retry += 1
                retry = 0
            retry += 1
            total += 1
            _flux = self._read(u, max(revs, 3), 0, tpr)
            for pll in PLLS:
                if dat.nr_missing() == 0:
                    break
                dat.decode_flux(_flux, pll)
            if raw:
                flux.append(_flux)
            else:
                flux = _flux

        nsec = dat.nsec
        good = [bool(dat.has_sec(s)) for s in range(nsec)]
        missing = dat.nr_missing()
        if nsec == 0:
            status = "empty"
        elif missing == 0:
            status = "retried" if total else "ok"
        else:
            status = "bad"
        msg = f"{tag} : {dat.summary_string()}" + (f" — {total} relecture(s)" if total else "")
        self.log.emit(msg, {"ok": "info", "retried": "warn", "bad": "err", "empty": "warn"}[status])
        res = TrackResult(c, h, status, nsec, good, total, dat.summary_string(), hist, rpm, nflux)
        sink, STDOUT.sink = STDOUT.sink, None
        try:
            res.enrich(dat, flux, fmt_cls, self.deep)
        finally:
            STDOUT.sink = sink
        if res.weak:
            self.warn(f"{tag} : secteur(s) faible(s) {res.weak}")
        return res, flux, dat

    def _summary(self, dt: float, raw: bool):
        r = list(self.results.values())
        tot = sum(x.nsec for x in r)
        bad = sum(x.nbad for x in r)
        rpms = [x.rpm for x in r if x.rpm]
        if getattr(self, "_oric_target", None):
            self._oric_finish()
        d = {"kind": "read", "path": self.path, "tracks": len(r), "sectors": tot,
             "bad": bad, "seconds": dt,
             "rpm": sum(rpms) / len(rpms) if rpms else 0,
             "bad_tracks": [f"{x.cyl}.{x.head}" for x in r if x.status == "bad"]}
        if self.deep:
            from . import analysis as A
            d["findings"] = fnd = A.detect_protections(self.results, self.fmt)
            for f in fnd[:40]:
                self.warn(f"Piste {f['where']} : {f['text']} [{f['schemes']}]")
            if not fnd:
                self.ok("Aucune protection ni anomalie détectée.")
        if raw:
            self.ok(f"Flux capturé : {len(r)} pistes en {dt:.0f} s.")
        elif bad == 0:
            self.ok(f"Lecture parfaite : {tot} secteurs, {len(r)} pistes en {dt:.0f} s.")
        else:
            self.warn(f"Lecture terminée avec {bad} secteur(s) illisible(s) sur {tot} "
                      f"({100 * (tot - bad) / max(tot, 1):.1f} % récupérés).")
        self.result.emit(d)


# --------------------------------------------------------------------------
# Écriture
# --------------------------------------------------------------------------
class WriteJob(Job):
    title = "Écriture"

    def __init__(self, dev, drive, path: str, fmt: Optional[str], tracks: Optional[str],
                 verify: bool, pre_erase: bool, retries: int, erase_empty: bool):
        super().__init__(dev, drive)
        self.path, self.fmt, self.tracks = path, fmt, tracks
        self.verify, self.pre_erase, self.retries = verify, pre_erase, retries
        self.erase_empty = erase_empty

    def work(self, u):
        img_cls = F.image_class(self.path)
        fmt_cls = F.get_diskdef(self.fmt) if self.fmt else None
        image = img_cls.from_file(self.path, fmt_cls, {})
        if fmt_cls is None and isinstance(image, IMG):
            fmt_cls = image.fmt
        if fmt_cls is not None:
            ts = _trackset(fmt_cls, self.tracks, "")
        else:
            mc = image.max_cylinder()
            heads = [h for h in range(2) if mc[h] >= 0]
            ts = util.TrackSet(f"c=0-{max(mc)}:h={','.join(map(str, heads))}")
            if self.tracks:
                ts.update_from_trackspec(self.tracks)
        tracks = track_list(ts)
        self.info(f"Écriture de {self.path} ({ts}) — vérification : {'oui' if self.verify else 'non'}")

        tpr = u.read_track(2).ticks_per_rev
        self.info(f"Vitesse lecteur : {60 * u.sample_freq / tpr:.2f} tr/min")
        t0, nver, nbad = time.monotonic(), 0, 0

        for i, (pc, ph, c, h) in enumerate(tracks):
            self.check()
            self.track_started.emit(c, h)
            self.progress.emit(i, len(tracks))
            tag = f"T{c}.{h}"
            trk = image.get_track(c, h)
            u.seek(pc, ph)
            if trk is None:
                if self.erase_empty:
                    u.erase_track(tpr * 1.1)
                    self.track_done.emit(TrackResult(c, h, "erased"))
                else:
                    self.track_done.emit(TrackResult(c, h, "skipped"))
                continue
            if not isinstance(trk, codec.Codec) and fmt_cls is not None:
                trk = fmt_cls.decode_flux(c, h, trk)
                if trk is None:
                    self.track_done.emit(TrackResult(c, h, "skipped"))
                    continue
                if trk.nr_missing():
                    self.warn(f"{tag} : {trk.nr_missing()} secteur(s) absent(s) dans l'image")
            if isinstance(trk, codec.Codec):
                trk = trk.master_track()
            wflux = trk.flux_for_writeout(cue_at_index=True)
            factor = tpr / wflux.ticks_to_index
            rem, wl = 0.0, []
            for x in wflux.list:
                y = x * factor + rem
                v = round(y)
                rem = y - v
                wl.append(v)

            status = "failed"
            for attempt in range(self.retries + 1):
                self.check()
                if self.pre_erase:
                    u.erase_track(tpr * 1.1)
                u.write_track(flux_list=wl, cue_at_index=wflux.index_cued,
                              terminate_at_index=wflux.terminate_at_index)
                verify = getattr(trk, "verify", None) if isinstance(trk, MasterTrack) else None
                if not self.verify or verify is None:
                    status = "written"
                    break
                v_revs, v_ticks = verify.verify_revs, 0
                if isinstance(v_revs, float):
                    v_ticks, v_revs = int(tpr * v_revs), 2
                vf = u.read_track(revs=v_revs, ticks=v_ticks)
                vf._ticks_per_rev = tpr
                if verify.verify_track(vf):
                    status = "verified"
                    break
                self.warn(f"{tag} : échec de vérification, nouvel essai {attempt + 1}")
            res = TrackResult(c, h, status, retries=attempt)
            if status == "verified":
                nver += 1
                self.info(f"{tag} : écrite et vérifiée" + (f" ({attempt} essai(s) suppl.)" if attempt else ""))
            elif status == "written":
                self.info(f"{tag} : écrite")
            else:
                nbad += 1
                self.log.emit(f"{tag} : ÉCHEC de vérification", "err")
            self.track_done.emit(res)
            if self.verify and nver == 0 and nbad >= 4 and i == nbad - 1:
                mean_us = sum(wl) / max(len(wl), 1) / u.sample_freq * 1e6
                hint = ("Format double densité (DD) : si la disquette est HD (trou à droite), masquez ce "
                        "trou avec un adhésif opaque ou utilisez une disquette DD." if mean_us > 4.5 else
                        "Format haute densité (HD) : la disquette doit être une HD (trou à droite).")
                raise gw_error.Fatal(f"Écriture abandonnée : les {nbad} premières pistes échouent à la "
                                     f"vérification.\n{hint}\nVérifiez aussi que la disquette n'est pas "
                                     "protégée en écriture.")
        self.progress.emit(len(tracks), len(tracks))
        dt = time.monotonic() - t0
        if nbad:
            self.warn(f"Écriture terminée : {nbad} piste(s) en échec.")
        else:
            self.ok(f"Écriture terminée en {dt:.0f} s" + (f", {nver} pistes vérifiées." if nver else "."))
        self.result.emit({"kind": "write", "failed": nbad, "verified": nver, "seconds": dt})


# --------------------------------------------------------------------------
# Analyse automatique du format
# --------------------------------------------------------------------------
class AnalyseJob(Job):
    title = "Analyse"

    def work(self, u):
        probes = [(0, 0), (1, 1), (40, 0)]
        fluxes = {}
        for c, h in probes:
            self.check()
            self.track_started.emit(c, h)
            u.seek(c, h)
            f = u.read_track(revs=3)
            fluxes[c, h] = f
            self.track_done.emit(TrackResult(c, h, "flux", hist=flux_histogram(f),
                                             rpm=flux_rpm(f), nflux=len(f.list),
                                             summary=f.summary_string()))
        u.seek(0, 0)
        h00 = flux_histogram(fluxes[0, 0])
        rpm = flux_rpm(fluxes[0, 0])
        self.info(f"Vitesse : {rpm:.1f} tr/min — densité estimée : {density_guess(h00)}")

        # Scan IBM pour décrire la piste 0
        scan = []
        STDOUT.sink, _sink = None, STDOUT.sink
        for (c, h) in [(0, 0), (1, 1)]:
            try:
                d = F.get_diskdef("ibm.scan")
                t = d.decode_flux(c, h, fluxes[c, h])
                if t is not None and t.nsec:
                    scan.append(f"T{c}.{h} : {t.summary_string()}")
            except Exception:
                pass
        # Disquette 40 pistes dans un lecteur 80 pistes ? (la piste physique 2 porte l'ID cylindre 1)
        dstep = None
        try:
            self.check()
            u.seek(2, 0)
            t = F.get_diskdef("ibm.scan").decode_flux(2, 0, u.read_track(revs=2))
            inner = getattr(t, "track", t)
            ids = {s.idam.c for s in getattr(inner, "sectors", [])}
            if ids == {1}:
                dstep = True
                scan.append("Piste physique 2 = cylindre 1 : disquette 40 pistes (pas double nécessaire)")
            elif ids == {2}:
                dstep = False
        except Exception:
            pass
        u.seek(0, 0)
        STDOUT.sink = _sink

        cands = []
        sink, STDOUT.sink = STDOUT.sink, None   # décodages d'essai : messages sans intérêt
        try:
            cands = self._try_candidates(fluxes)
        finally:
            STDOUT.sink = sink
        cands.sort(key=lambda x: (x["ratio"] >= 0.95, x["good"], x["ratio"]), reverse=True)
        if cands:
            b = cands[0]
            self.ok(f"Format probable : {b['fmt']} — {b['label']} "
                    f"({b['good']}/{b['expected']} secteurs reconnus)")
        else:
            self.warn("Aucun format connu reconnu : disquette vierge, protégée ou format exotique "
                      "(utiliser la capture flux brut).")
        for s in scan:
            self.info("Scan IBM " + s)
        self.result.emit({"kind": "analyse", "candidates": cands, "rpm": rpm,
                          "density": density_guess(h00), "scan": scan, "double_step": dstep,
                          "hist": h00})

    def _try_candidates(self, fluxes):
        cands = []
        for fmt in F.ANALYSE_CANDIDATES:
            self.check()
            d = F.get_diskdef(fmt)
            if d is None:
                continue
            good = exp = 0
            for (c, h), fl in fluxes.items():
                if (c, h) not in d.track_map:
                    continue
                try:
                    t = d.decode_flux(c, h, fl)
                except Exception:
                    t = None
                if t is None:
                    continue
                exp += t.nsec
                good += t.nsec - t.nr_missing()
            if good:
                cands.append({"fmt": fmt, "label": F.label_for(fmt),
                              "platform": F.platform_of(fmt) or "",
                              "good": good, "expected": exp,
                              "ratio": good / exp if exp else 0})
        return cands


def best_format(fluxes: Dict[Tuple[int, int], object], check=lambda: None) -> List[dict]:
    cands = []
    for fmt in F.ANALYSE_CANDIDATES:
        check()
        d = F.get_diskdef(fmt)
        if d is None:
            continue
        good = exp = 0
        for (c, h), fl in fluxes.items():
            if (c, h) not in d.track_map:
                continue
            try:
                t = d.decode_flux(c, h, fl)
            except Exception:
                t = None
            if t is None:
                continue
            exp += t.nsec
            good += t.nsec - t.nr_missing()
        if good:
            cands.append({"fmt": fmt, "label": F.label_for(fmt), "platform": F.platform_of(fmt) or "",
                          "good": good, "expected": exp, "ratio": good / exp if exp else 0})
    cands.sort(key=lambda x: (x["ratio"] >= 0.95, x["good"], x["ratio"]), reverse=True)
    return cands


def as_flux(trk, revs=3):
    if trk is None:
        return None
    if hasattr(trk, "index_list") and hasattr(trk, "list"):
        return trk
    try:
        return trk.flux(revs=revs)
    except TypeError:
        return trk.flux()


class FluxAnalyseJob(Job):
    """Analyse hors lecteur d'une image flux (SCP, HFE, KryoFlux…) : qualité, protections."""
    title = "Analyse d'image flux"
    needs_drive = False

    def __init__(self, dev, path: str, fmt: Optional[str]):
        super().__init__(dev)
        self.path, self.fmt = path, fmt
        self.results: Dict[Tuple[int, int], TrackResult] = {}

    def work(self, _u):
        from . import analysis as A
        img = F.image_class(self.path).from_file(self.path, None, {})
        mc = img.max_cylinder()
        heads = [h for h in range(2) if mc[h] >= 0]
        tracks = [(c, h) for c in range(max(mc) + 1) for h in heads]
        sink, STDOUT.sink = STDOUT.sink, None
        try:
            fmt = self.fmt
            if not fmt:
                probe = {}
                for c, h in [(0, 0), (1, 1), (40, 0)]:
                    if (c, h) in tracks:
                        f = as_flux(img.get_track(c, h))
                        if f is not None:
                            probe[c, h] = f
                cands = best_format(probe, self.check)
                fmt = cands[0]["fmt"] if cands and cands[0]["ratio"] > 0.5 else None
        finally:
            STDOUT.sink = sink
        fmt_cls = F.get_diskdef(fmt) if fmt else None
        self.info(f"Image {self.path} : {len(tracks)} pistes — format : {fmt or 'inconnu (flux seul)'}")
        for i, (c, h) in enumerate(tracks):
            self.check()
            self.track_started.emit(c, h)
            self.progress.emit(i, len(tracks))
            flux = as_flux(img.get_track(c, h))
            if flux is None:
                self.track_done.emit(TrackResult(c, h, "empty"))
                continue
            hist = flux_histogram(flux)
            nrev = max(len(flux.index_list), 1)
            r = TrackResult(c, h, "flux", hist=hist, rpm=flux_rpm(flux), nflux=len(flux.list) // nrev)
            dat = None
            sink, STDOUT.sink = STDOUT.sink, None
            try:
                if fmt_cls is not None and (c, h) in fmt_cls.track_map:
                    dat = fmt_cls.decode_flux(c, h, flux)
                if dat is not None:
                    r.nsec = dat.nsec
                    r.good = [bool(dat.has_sec(k)) for k in range(dat.nsec)]
                    r.summary = dat.summary_string()
                    r.status = "empty" if not dat.nsec else ("ok" if not dat.nr_missing() else "bad")
                r.enrich(dat, flux, fmt_cls, True)
            finally:
                STDOUT.sink = sink
            self.results[c, h] = r
            self.track_done.emit(r)
        self.progress.emit(len(tracks), len(tracks))
        fnd = A.detect_protections(self.results, fmt)
        for f in fnd[:60]:
            self.warn(f"Piste {f['where']} : {f['text']} [{f['schemes']}]")
        qs = [r.quality for r in self.results.values() if r.quality]
        if qs:
            q = sum(qs) / len(qs)
            self.ok(f"Qualité moyenne du signal : {q:.1f} % ({A.quality_label(q)})")
        if not fnd:
            self.ok("Aucune protection ni anomalie détectée.")
        self.result.emit({"kind": "fluxanalyse", "findings": fnd, "fmt": fmt, "path": self.path})


# --------------------------------------------------------------------------
# Outils
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Récupération multi-passes
# --------------------------------------------------------------------------
BAD_PAT = b"-=[BAD SECTOR]=-"


def _img_layout(path: str, fmt_cls):
    """[(c, h, offset, taille, nsec)] dans l'ordre du fichier image (IMG ou FD séquentiel)."""
    cls = F.image_class(path)
    seq = bool(getattr(cls, "sequential", False))
    ts = _trackset(fmt_cls, None, "")
    tl = [(c, h) for _, _, c, h in track_list(ts)]
    if seq:
        tl.sort(key=lambda x: (x[1], x[0]))
    out, off = [], 0
    for c, h in tl:
        t = fmt_cls.mk_track(c, h)
        if t is None:
            continue
        size = len(t.get_img_track())
        out.append((c, h, off, size, t.nsec))
        off += size
    return out


def _bad_secs(chunk: bytes, nsec: int) -> List[int]:
    if not nsec:
        return []
    ss = len(chunk) // nsec
    return [k for k in range(nsec) if chunk[k * ss:k * ss + 16] == BAD_PAT]


class RecoverJob(Job):
    """Relit plusieurs fois les secteurs illisibles d'une image et fusionne les bonnes lectures."""
    title = "Récupération"

    def __init__(self, dev, drive, path: str, fmt: str, passes: int = 10, merge: Optional[List[str]] = None):
        super().__init__(dev, drive)
        self.path, self.fmt, self.passes = path, fmt, passes
        self.merge = merge or []
        self.needs_drive = not merge

    def work(self, u):
        fmt_cls = F.get_diskdef(self.fmt)
        if fmt_cls is None:
            raise gw_error.Fatal(f"Format inconnu : {self.fmt}")
        with open(self.path, "rb") as f:
            data = bytearray(f.read())
        layout = _img_layout(self.path, fmt_cls)
        if not layout or layout[-1][2] + layout[-1][3] > len(data) + 4096:
            raise gw_error.Fatal("La taille de l'image ne correspond pas au format choisi.")
        todo = {(c, h): (off, size, n, _bad_secs(bytes(data[off:off + size]), n))
                for c, h, off, size, n in layout}
        todo = {k: v for k, v in todo.items() if v[3]}
        before = sum(len(v[3]) for v in todo.values())
        self.info(f"{before} secteur(s) illisible(s) sur {len(todo)} piste(s).")
        if not before:
            self.ok("Rien à récupérer : l'image est complète.")
            self.result.emit({"kind": "recover", "fixed": 0, "left": 0, "path": self.path})
            return
        fixed = 0
        if self.merge:
            for other in self.merge:
                with open(other, "rb") as f:
                    od = f.read()
                for (c, h), (off, size, n, bad) in todo.items():
                    ss = size // n
                    for k in list(bad):
                        chunk = od[off + k * ss:off + (k + 1) * ss]
                        if len(chunk) == ss and chunk[:16] != BAD_PAT:
                            data[off + k * ss:off + (k + 1) * ss] = chunk
                            bad.remove(k)
                            fixed += 1
                self.info(f"Fusion avec {other} : {fixed} secteur(s) récupéré(s)")
        else:
            items = sorted(todo.items())
            for i, ((c, h), (off, size, n, bad)) in enumerate(items):
                self.track_started.emit(c, h)
                self.progress.emit(i, len(items))
                ss = size // n
                for p in range(self.passes):
                    self.check()
                    if not bad:
                        break
                    # « secouer » la tête entre les passes
                    if p % 2:
                        u.seek(min(c + 1, 83), h)
                    else:
                        u.seek(0, h)
                    u.seek(c, h)
                    flux = u.read_track(revs=3)
                    sink, STDOUT.sink = STDOUT.sink, None
                    try:
                        dat = fmt_cls.decode_flux(c, h, flux)
                        if dat is not None:
                            for pll in PLLS:
                                dat.decode_flux(flux, pll)
                    finally:
                        STDOUT.sink = sink
                    if dat is None:
                        continue
                    img = bytes(dat.get_img_track())
                    for k in list(bad):
                        if k < dat.nsec and dat.has_sec(k):
                            data[off + k * ss:off + (k + 1) * ss] = img[k * ss:(k + 1) * ss]
                            bad.remove(k)
                            fixed += 1
                            self.ok(f"T{c}.{h} secteur #{k} récupéré à la passe {p + 1}")
                good = [k not in bad for k in range(n)]
                self.track_done.emit(TrackResult(c, h, "bad" if bad else "retried", n, good, self.passes))
        left = before - fixed
        with open(self.path, "wb") as f:
            f.write(data)
        msg = f"{fixed} secteur(s) récupéré(s), {left} toujours illisible(s). Image mise à jour."
        (self.ok if not left else self.warn)(msg)
        self.result.emit({"kind": "recover", "fixed": fixed, "left": left, "path": self.path})


class CompareImagesJob(Job):
    """Compare deux images piste par piste et secteur par secteur (hors lecteur)."""
    title = "Comparaison d'images"
    needs_drive = False

    def __init__(self, dev, a: str, b: str, fmt: Optional[str] = None):
        super().__init__(dev)
        self.a, self.b, self.fmt = a, b, fmt

    def work(self, _u):
        from .fs import open_disk
        da, db = open_disk(self.a, self.fmt), open_disk(self.b, self.fmt)
        if not da.tracks or not db.tracks:
            # images brutes sans géométrie : comparaison par blocs de 512 o
            la, lb = da.linear(), db.linear()
            diff = [i for i in range(0, max(len(la), len(lb)), 512) if la[i:i + 512] != lb[i:i + 512]]
            self.info(f"Comparaison brute : {len(diff)} bloc(s) de 512 o différent(s)")
            self.result.emit({"kind": "compare", "same": not diff, "diff": [f"+{i}" for i in diff[:200]],
                              "only_a": 0, "only_b": 0, "total": max(len(la), len(lb)) // 512})
            return
        keys = sorted(set(da.tracks) | set(db.tracks))
        diffs, only_a, only_b, total, same_tr = [], 0, 0, 0, 0
        for i, (c, h) in enumerate(keys):
            self.check()
            self.progress.emit(i, len(keys))
            sa = {x.r: x for x in da.track(c, h)}
            sb = {x.r: x for x in db.track(c, h)}
            ids = sorted(set(sa) | set(sb))
            good, st = [], "ok"
            for r in ids:
                total += 1
                x, y = sa.get(r), sb.get(r)
                okx, oky = bool(x and x.ok), bool(y and y.ok)
                if okx and oky and x.data == y.data:
                    good.append(True)
                    continue
                good.append(False)
                if okx and not oky:
                    only_a += 1
                    st = "retried" if st == "ok" else st
                    diffs.append(f"{c}.{h}.{r} lisible seulement dans A")
                elif oky and not okx:
                    only_b += 1
                    st = "retried" if st == "ok" else st
                    diffs.append(f"{c}.{h}.{r} lisible seulement dans B")
                elif okx and oky:
                    st = "bad"
                    diffs.append(f"{c}.{h}.{r} contenu différent")
                else:
                    st = "bad"
                    diffs.append(f"{c}.{h}.{r} illisible dans les deux")
            if all(good):
                same_tr += 1
            self.track_done.emit(TrackResult(c, h, st if ids else "empty", len(ids), good,
                                             summary=f"{sum(good)}/{len(ids)} secteurs identiques"))
        self.progress.emit(len(keys), len(keys))
        msg = (f"{same_tr}/{len(keys)} pistes identiques ; {len(diffs)} secteur(s) diffèrent "
               f"({only_a} lisibles seulement dans A, {only_b} seulement dans B)")
        (self.ok if not diffs else self.warn)(msg)
        for d in diffs[:60]:
            self.info("  " + d)
        self.result.emit({"kind": "compare", "same": not diffs, "diff": diffs, "only_a": only_a,
                          "only_b": only_b, "total": total})


# --------------------------------------------------------------------------
# Surveillance de l'insertion
# --------------------------------------------------------------------------
class WatchJob(Job):
    """Attend qu'une disquette soit insérée (ligne DSKCHG 34, ou impulsions d'index à défaut)."""
    title = "Attente d'une disquette"

    def __init__(self, dev, drive, need_change: bool = True, timeout: float = 600):
        super().__init__(dev, drive)
        self.need_change, self.timeout = need_change, timeout

    def _present_index(self, u) -> bool:
        try:
            u.read_track(revs=1, nr_retries=1)
            return True
        except Exception:
            return False

    def _present_pin(self, u) -> Optional[bool]:
        try:
            if u.get_pin(34):
                return True
            u.seek(1, 0)
            u.seek(0, 0)
            return bool(u.get_pin(34))
        except USB.CmdError:
            return None

    def work(self, u):
        t0 = time.monotonic()
        method = "pin"
        state = self._present_pin(u)
        if state is None:
            method = "index"
            state = self._present_index(u)
        self.info("Insérez la disquette…" + (" (retirez d'abord la précédente)" if state and self.need_change else ""))
        seen_absent = not state or not self.need_change
        while time.monotonic() - t0 < self.timeout:
            self.check()
            time.sleep(0.6)
            cur = self._present_pin(u) if method == "pin" else self._present_index(u)
            if not cur:
                seen_absent = True
            elif seen_absent:
                time.sleep(0.8)
                self.ok("Disquette détectée.")
                self.result.emit({"kind": "inserted"})
                return
        self.warn("Délai d'attente dépassé.")


# --------------------------------------------------------------------------
# Calibrage / alignement
# --------------------------------------------------------------------------
class CalibrateJob(Job):
    """Lecture en boucle de pistes de référence : qualité du signal, secteurs décodés, vitesse."""
    title = "Calibrage"

    def __init__(self, dev, drive, fmt: Optional[str], tracks: List[Tuple[int, int]]):
        super().__init__(dev, drive)
        self.fmt, self.tracks = fmt, tracks

    def work(self, u):
        fmt_cls = F.get_diskdef(self.fmt) if self.fmt else None
        i = 0
        self.info("Calibrage en cours — réglez le lecteur en observant la qualité ; Annuler pour arrêter.")
        while True:
            self.check()
            c, h = self.tracks[i % len(self.tracks)]
            i += 1
            self.track_started.emit(c, h)
            u.seek(c, h)
            flux = u.read_track(revs=2)
            hist = flux_histogram(flux)
            r = TrackResult(c, h, "flux", hist=hist, rpm=flux_rpm(flux), nflux=len(flux.list) // 2)
            dat = None
            sink, STDOUT.sink = STDOUT.sink, None
            try:
                if fmt_cls is not None and (c, h) in fmt_cls.track_map:
                    dat = fmt_cls.decode_flux(c, h, flux)
            except Exception:
                dat = None
            finally:
                STDOUT.sink = sink
            if dat is not None:
                r.nsec = dat.nsec
                r.good = [bool(dat.has_sec(k)) for k in range(dat.nsec)]
                r.status = "ok" if not dat.nr_missing() else "bad"
                r.summary = dat.summary_string()
            r.enrich(dat)
            self.track_done.emit(r)
            self.result.emit({"kind": "calib", "cyl": c, "head": h, "quality": r.quality, "jitter": r.jitter,
                              "rpm": r.rpm, "good": r.nsec - r.nbad, "nsec": r.nsec, "peak": r.peak})


class RpmJob(Job):
    title = "Mesure de vitesse"

    def __init__(self, dev, drive, n=10):
        super().__init__(dev, drive)
        self.n = n

    def work(self, u):
        vals = []
        for i in range(self.n):
            self.check()
            f = u.read_track(1)
            tpr = f.index_list[-1] / f.sample_freq
            vals.append(60 / tpr)
            self.progress.emit(i + 1, self.n)
            self.result.emit({"kind": "rpm_sample", "rpm": 60 / tpr, "i": i})
        mean = sum(vals) / len(vals)
        self.ok(f"Vitesse : moyenne {mean:.2f} tr/min, min {min(vals):.2f}, max {max(vals):.2f}, "
                f"écart {max(vals) - min(vals):.2f}")
        self.result.emit({"kind": "rpm", "values": vals, "mean": mean})


class SeekJob(Job):
    title = "Positionnement"

    def __init__(self, dev, drive, cyl, head):
        super().__init__(dev, drive)
        self.cyl, self.head = cyl, head

    def work(self, u):
        u.seek(self.cyl, self.head)
        self.ok(f"Tête positionnée sur cylindre {self.cyl}, face {self.head}.")
        try:
            di = u.get_current_drive_info()
            self.info(f"Info lecteur : {di}")
        except Exception:
            pass
        self.result.emit({"kind": "seek"})


class CleanJob(Job):
    title = "Nettoyage des têtes"

    def __init__(self, dev, drive, cyls=80, passes=3, linger_ms=100):
        super().__init__(dev, drive)
        self.cyls, self.passes, self.linger = cyls, passes, linger_ms

    def work(self, u):
        step = max(self.cyls // 8, 2)
        total, n = self.passes * len(range(0, self.cyls, step)), 0
        for p in range(self.passes):
            for cyl in range(0, self.cyls, step):
                self.check()
                u.seek(min(cyl + step - 1, self.cyls - 1), 0)
                time.sleep(self.linger / 1000)
                u.seek(cyl, 0)
                time.sleep(self.linger / 1000)
                n += 1
                self.progress.emit(n, total)
            self.info(f"Passe {p + 1}/{self.passes} terminée")
        u.seek(0, 0)
        self.ok("Nettoyage terminé.")
        self.result.emit({"kind": "clean"})


class EraseJob(Job):
    title = "Effacement"

    def __init__(self, dev, drive, tracks="c=0-79:h=0-1"):
        super().__init__(dev, drive)
        self.tracks = tracks

    def work(self, u):
        ts = util.TrackSet(self.tracks)
        tracks = track_list(ts)
        tpr = u.read_track(2).ticks_per_rev
        for i, (pc, ph, c, h) in enumerate(tracks):
            self.check()
            self.track_started.emit(c, h)
            u.seek(pc, ph)
            u.erase_track(tpr * 1.1)
            self.track_done.emit(TrackResult(c, h, "erased"))
            self.progress.emit(i + 1, len(tracks))
        self.ok(f"{len(tracks)} pistes effacées.")
        self.result.emit({"kind": "erase"})


class ResetJob(Job):
    title = "Réinitialisation"
    needs_drive = False

    def work(self, u):
        if u is None:
            raise gw_error.Fatal("Aucun Greaseweazle connecté.")
        u.power_on_reset()
        self.ok("Greaseweazle réinitialisé (bus lecteur remis à zéro).")
        self.result.emit({"kind": "reset"})


class FirmwareCheckJob(Job):
    title = "Vérification firmware"
    needs_drive = False

    def work(self, u):
        from greaseweazle.tools.info import latest_firmware
        latest = latest_firmware()
        cur = self.dev.info.firmware if self.dev.info else None
        if cur and latest > cur:
            self.warn("Nouveau firmware disponible : %d.%d (installé : %d.%d)" % (latest + cur))
        else:
            self.ok("Firmware à jour (%d.%d)." % latest)
        self.result.emit({"kind": "fwcheck", "latest": latest, "current": cur})


class FirmwareUpdateJob(Job):
    title = "Mise à jour firmware"
    needs_drive = False

    def __init__(self, dev, port, file: Optional[str] = None):
        super().__init__(dev)
        self.port, self.file = port, file

    def work(self, _u):
        from greaseweazle.tools import update
        self.dev.close()
        argv = ["gw", "update", "--device", self.port]
        if self.file:
            argv += ["--file", self.file]
        self.info("Lancement de la mise à jour du firmware…")
        try:
            update.main(argv)
        except SystemExit as e:
            if e.code not in (0, None):
                raise gw_error.Fatal("La mise à jour a échoué (voir journal).")
        time.sleep(1.5)
        try:
            self.dev.open(None)
            self.ok("Mise à jour terminée, Greaseweazle reconnecté.")
        except Exception as e:
            self.warn(f"Mise à jour terminée ; reconnexion impossible : {e}")
        self.result.emit({"kind": "fwupdate"})


class ConvertJob(Job):
    """Conversion d'image à image (hors matériel)."""
    title = "Conversion"
    needs_drive = False

    def __init__(self, dev, src: str, dst: str, fmt: Optional[str]):
        super().__init__(dev)
        self.src, self.dst, self.fmt = src, dst, fmt

    def work(self, _u):
        fmt = self.fmt or F.default_format_for(self.src) or F.default_format_for(self.dst)
        fmt_cls = F.get_diskdef(fmt) if fmt else None
        src = F.image_class(self.src).from_file(self.src, fmt_cls, {})
        if fmt_cls is None and isinstance(src, IMG):
            fmt_cls = src.fmt
        raw_out = F.is_flux_image(self.dst)
        dst = F.image_class(self.dst, fmt).to_file(self.dst, None if raw_out else fmt_cls, False, {})
        if fmt_cls is not None:
            ts = _trackset(fmt_cls, None, "")
        else:
            mc = src.max_cylinder()
            heads = [h for h in range(2) if mc[h] >= 0]
            ts = util.TrackSet(f"c=0-{max(mc)}:h={','.join(map(str, heads))}")
        tl = [(c, h) for _, _, c, h in track_list(ts)]
        bad = 0
        with dst:
            for i, (c, h) in enumerate(tl):
                self.check()
                trk = src.get_track(c, h)
                if trk is None:
                    continue
                if fmt_cls is not None and not raw_out and not isinstance(trk, codec.Codec):
                    trk = fmt_cls.decode_flux(c, h, trk)
                    if trk is None:
                        continue
                    if trk.nr_missing():
                        bad += trk.nr_missing()
                        self.warn(f"T{c}.{h} : {trk.summary_string()}")
                    good = [bool(trk.has_sec(s)) for s in range(trk.nsec)]
                    self.track_done.emit(TrackResult(c, h, "ok" if all(good) else "bad",
                                                     trk.nsec, good))
                dst.emit_track(c, h, trk)
                self.progress.emit(i + 1, len(tl))
        self.ok(f"Conversion terminée → {self.dst}" + (f" ({bad} secteurs manquants)" if bad else ""))
        self.result.emit({"kind": "convert", "bad": bad})
