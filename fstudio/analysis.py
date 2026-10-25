"""Analyses : qualité magnétique, détails des secteurs, protections, rapport."""
from __future__ import annotations

import base64
import hashlib
import html
import os
import statistics
import time
from typing import Dict, List, Optional, Tuple

HIST_STEP_US = 0.1


# --------------------------------------------------------------------------
# Qualité du flux
# --------------------------------------------------------------------------
def _smooth(h: List[int]) -> List[float]:
    return [(h[i - 1] if i else 0) * 0.25 + h[i] * 0.5 + (h[i + 1] if i + 1 < len(h) else 0) * 0.25
            for i in range(len(h))]


def peaks(hist: List[int]) -> List[int]:
    """Indices des pics principaux de l'histogramme (≥ 4 % du maximum)."""
    if not hist or max(hist) == 0:
        return []
    s = _smooth(hist)
    m = max(s)
    out = []
    for i in range(1, len(s) - 1):
        if s[i] >= m * 0.04 and s[i] >= s[i - 1] and s[i] > s[i + 1]:
            if out and i - out[-1] < 4:
                if s[i] > s[out[-1]]:
                    out[-1] = i
                continue
            out.append(i)
    return out


def flux_quality(hist: List[int]) -> Tuple[float, float]:
    """(qualité 0-100, gigue moyenne en %) : part des intervalles proches d'un pic."""
    pk = peaks(hist)
    tot = sum(hist)
    if not pk or not tot:
        return 0.0, 0.0
    inside, dev = 0, 0.0
    for i, v in enumerate(hist):
        if not v:
            continue
        p = min(pk, key=lambda x: abs(x - i))
        rel = abs(i - p) / max(p, 1)
        dev += rel * v
        if rel <= 0.10:
            inside += v
    return 100.0 * inside / tot, 100.0 * dev / tot


def quality_label(q: float) -> str:
    if q <= 0:
        return "—"
    if q >= 97:
        return "excellente"
    if q >= 92:
        return "bonne"
    if q >= 85:
        return "moyenne (support fatigué)"
    return "mauvaise (démagnétisation, moisissure ou rayure)"


def peak_us(hist: List[int]) -> float:
    pk = peaks(hist)
    return pk[0] * HIST_STEP_US if pk else 0.0


# --------------------------------------------------------------------------
# Détails d'une piste décodée
# --------------------------------------------------------------------------
def encoding_of(dat) -> str:
    if dat is None:
        return "—"
    t = getattr(dat, "track", dat)
    mode = getattr(t, "mode", None)
    if mode is not None:
        return str(mode).split(".")[-1]
    name = type(dat).__module__ + "." + type(dat).__name__
    for k, v in (("amiga", "Amiga MFM"), ("c64", "GCR Commodore"), ("apple2", "GCR Apple II"),
                 ("mac", "GCR Macintosh"), ("hp", "HP M²FM"), ("northstar", "Northstar FM")):
        if k in name.lower():
            return v
    return type(dat).__name__


def sector_info(dat) -> List[dict]:
    """Liste des secteurs avec ID, taille et état CRC (codecs IBM) ou état simple."""
    if dat is None:
        return []
    t = getattr(dat, "track", dat)
    secs = getattr(t, "sectors", None)
    out = []
    if secs is not None and secs and hasattr(secs[0], "idam"):
        for s in secs:
            i, d = s.idam, s.dam
            out.append({"c": i.c, "h": i.h, "r": i.r, "n": i.n, "size": 128 << i.n if i.n < 8 else 0,
                        "id_ok": i.crc == 0, "data_ok": d is not None and d.crc == 0,
                        "deleted": d is not None and getattr(d, "mark", 0xFB) in (0xF8, 0xF9, 0xFA)})
        return out
    n = getattr(dat, "nsec", 0)
    for k in range(n):
        try:
            ok = bool(dat.has_sec(k))
        except Exception:
            ok = False
        out.append({"c": None, "h": None, "r": k, "n": None, "size": 0, "id_ok": ok,
                    "data_ok": ok, "deleted": False})
    return out


def split_revs(flux) -> list:
    """Découpe un flux multi-tours en un flux par tour."""
    from greaseweazle.flux import Flux
    out, pos = [], 0
    fl = flux.list
    for t in flux.index_list:
        acc, start = 0.0, pos
        while pos < len(fl) and acc + fl[pos] <= t:
            acc += fl[pos]
            pos += 1
        if pos - start > 100:
            f = Flux([t], fl[start:pos], flux.sample_freq)
            out.append(f)
    return out


def weak_sectors(fmt_cls, c: int, h: int, flux) -> List[int]:
    """Index des secteurs dont le contenu change d'un tour à l'autre (bits faibles)."""
    revs = split_revs(flux)
    if len(revs) < 2 or fmt_cls is None:
        return []
    imgs = []
    for f in revs[:4]:
        try:
            t = fmt_cls.decode_flux(c, h, f)
        except Exception:
            t = None
        if t is None or not t.nsec:
            continue
        good = [bool(t.has_sec(k)) for k in range(t.nsec)]
        try:
            imgs.append((good, bytes(t.get_img_track()), t.nsec))
        except Exception:
            pass
    if len(imgs) < 2:
        return []
    nsec = imgs[0][2]
    size = len(imgs[0][1]) // max(nsec, 1)
    weak = []
    for k in range(nsec):
        vals = {im[1][k * size:(k + 1) * size] for im in imgs if k < len(im[0]) and im[0][k]}
        if len(vals) > 1:
            weak.append(k)
    return weak


# --------------------------------------------------------------------------
# Protections
# --------------------------------------------------------------------------
def detect_protections(results: Dict[Tuple[int, int], object], fmt: Optional[str]) -> List[dict]:
    """Heuristiques à partir des TrackResult enrichis (sectors, weak, quality, nflux…)."""
    find: List[dict] = []

    def add(kind, where, text, schemes=""):
        find.append({"kind": kind, "where": where, "text": text, "schemes": schemes})

    rs = [r for r in results.values() if getattr(r, "nflux", 0)]
    if not rs:
        return find
    dens = [r.nflux for r in rs if r.status not in ("empty", "skipped")]
    med = statistics.median(dens) if dens else 0
    sizes = [s["n"] for r in rs for s in getattr(r, "sectors", []) if s.get("n") is not None]
    std_n = statistics.mode(sizes) if sizes else None
    nsecs = [len(getattr(r, "sectors", [])) for r in rs if getattr(r, "sectors", [])]
    std_ns = statistics.mode(nsecs) if nsecs else None
    peaks_ = [r.peak for r in rs if getattr(r, "peak", 0)]
    med_pk = statistics.median(peaks_) if peaks_ else 0
    amiga = bool(fmt and fmt.startswith("amiga"))

    for (c, h), r in sorted(results.items()):
        where = f"{c}.{h}"
        secs = getattr(r, "sectors", [])
        if secs:
            ids = [s["r"] for s in secs]
            dup = {x for x in ids if ids.count(x) > 1}
            if dup:
                add("ids", where, f"IDs de secteur dupliqués : {', '.join(map(str, sorted(dup)))}",
                    "Copylock ST, protections à secteurs fantômes")
            big = [s for s in secs if s["n"] is not None and std_n is not None and s["n"] != std_n]
            if big:
                desc = ", ".join(f"#{s['r']} N={s['n']}" for s in big[:6])
                schemes = "Speedlock, Hexagon (secteur 8 Ko)" if any(s["n"] >= 6 for s in big) else \
                    "format à tailles mixtes"
                add("size", where, f"Tailles de secteur non standard : {desc}", schemes)
            wrong = [s for s in secs if s["c"] is not None and s["id_ok"] and s["c"] != c]
            if wrong:
                add("cyl", where, "Numéros de piste falsifiés dans les en-têtes : " +
                    ", ".join(f"#{s['r']}→C{s['c']}" for s in wrong[:6]), "protections par faux ID")
            dcrc = [s for s in secs if s["id_ok"] and not s["data_ok"]]
            if dcrc and len(dcrc) < len(secs):
                add("crc", where, f"Erreur CRC données sur {len(dcrc)} secteur(s) d'une piste par "
                    "ailleurs lisible", "CRC volontairement faux (Speedlock, Alkatraz) ou défaut local")
            dele = [s for s in secs if s.get("deleted")]
            if dele:
                add("deleted", where, f"{len(dele)} secteur(s) marqués « supprimés » (DAM F8)",
                    "protection par Deleted Data Mark")
            if std_ns and len(secs) > std_ns:
                add("extra", where, f"{len(secs)} secteurs au lieu de {std_ns}", "piste surchargée")
        weak = getattr(r, "weak", [])
        if weak:
            add("weak", where, f"Secteur(s) faible(s) (contenu variable d'un tour à l'autre) : "
                f"{', '.join('#' + str(w) for w in weak)}", "Speedlock, Copylock, Macrodos/fuzzy bits")
        if med and r.nflux > med * 1.06 and r.status not in ("empty",):
            add("long", where, f"Piste dense / longue : {100 * (r.nflux / med - 1):+.0f} % de transitions",
                "piste longue (Copylock Amiga, Rainbow Arts, Rob Northen)")
        if med_pk and getattr(r, "peak", 0) and abs(r.peak / med_pk - 1) > 0.04:
            add("rate", where, f"Débit de cellule différent ({r.peak:.2f} µs contre {med_pk:.2f} µs)",
                "vitesse variable (Copylock, Speedlock « long track »)")
        if amiga and r.status in ("bad", "empty", "skipped") and r.nflux > med * 0.5:
            add("custom", where, "Piste avec signal mais non décodable en AmigaDOS",
                "loader maison / protection (Copylock, format de jeu propriétaire)")
        if c >= 80 and r.status in ("ok", "retried"):
            add("over80", where, "Données présentes au-delà de la piste 79", "pistes supplémentaires")
    return find


# --------------------------------------------------------------------------
# Rapport HTML / PDF
# --------------------------------------------------------------------------
def file_hashes(path: str) -> Dict[str, str]:
    try:
        with open(path, "rb") as f:
            d = f.read()
    except OSError:
        return {}
    return {"Taille": f"{len(d)} octets", "MD5": hashlib.md5(d).hexdigest(),
            "SHA-1": hashlib.sha1(d).hexdigest(), "CRC32": f"{__import__('zlib').crc32(d):08X}"}


def report_html(title: str, info: List[Tuple[str, str]], results: Dict, map_png: Optional[bytes],
                findings: List[dict], image_path: Optional[str] = None) -> str:
    css = ("body{font-family:Segoe UI,Arial,sans-serif;color:#222;margin:24px}"
           "h1{font-size:20px;margin:0 0 4px}h2{font-size:15px;margin:18px 0 6px;color:#2b4a8b}"
           "table{border-collapse:collapse;font-size:11px}td,th{border:1px solid #ccc;padding:2px 6px}"
           "th{background:#eef}.ok{color:#1a7f37}.bad{color:#c62828}.warn{color:#b26a00}"
           ".muted{color:#777;font-size:11px}")
    h = [f"<html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
         f"<style>{css}</style></head><body>",
         f"<h1>{html.escape(title)}</h1>",
         f"<div class='muted'>Floppy Studio — {time.strftime('%d/%m/%Y %H:%M')}</div>"]
    rows = list(info)
    if image_path:
        rows += [(f"Image · {k}", v) for k, v in file_hashes(image_path).items()]
    h.append("<h2>Résumé</h2><table>")
    for k, v in rows:
        h.append(f"<tr><th align='left'>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>")
    h.append("</table>")
    if map_png:
        b64 = base64.b64encode(map_png).decode()
        h.append(f"<h2>Carte</h2><img src='data:image/png;base64,{b64}' style='max-width:100%'>")
    h.append("<h2>Protections et anomalies</h2>")
    if findings:
        h.append("<table><tr><th>Piste</th><th>Constat</th><th>Schémas possibles</th></tr>")
        for f in findings:
            h.append(f"<tr><td>{f['where']}</td><td>{html.escape(f['text'])}</td>"
                     f"<td>{html.escape(f['schemes'])}</td></tr>")
        h.append("</table>")
    else:
        h.append("<p class='ok'>Aucune anomalie détectée.</p>")
    if results:
        h.append("<h2>Pistes</h2><table><tr><th>Piste</th><th>État</th><th>Secteurs</th>"
                 "<th>Relectures</th><th>tr/min</th><th>Qualité</th><th>Codage</th></tr>")
        for (c, hd), r in sorted(results.items()):
            cls = {"ok": "ok", "retried": "warn", "bad": "bad"}.get(r.status, "")
            q = getattr(r, "quality", 0)
            h.append(f"<tr><td>{c}.{hd}</td><td class='{cls}'>{r.status}</td>"
                     f"<td>{r.nsec - r.nbad}/{r.nsec}</td><td>{r.retries}</td>"
                     f"<td>{r.rpm:.1f}</td><td>{q:.0f} %</td>"
                     f"<td>{html.escape(getattr(r, 'encoding', '') or '')}</td></tr>")
        h.append("</table>")
    h.append("</body></html>")
    return "".join(h)


def save_report(path: str, html_text: str):
    if path.lower().endswith(".pdf"):
        from PySide6.QtGui import QPageSize, QPdfWriter, QTextDocument
        doc = QTextDocument()
        doc.setHtml(html_text)
        w = QPdfWriter(path)
        w.setPageSize(QPageSize(QPageSize.A4))
        w.setResolution(110)
        doc.setPageSize(w.pageLayout().paintRectPixels(w.resolution()).size().toSizeF())
        doc.print_(w)
    else:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html_text)
    return os.path.abspath(path)
