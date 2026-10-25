"""Widgets graphiques : carte des pistes (grille / disque), histogramme de flux, courbe RPM."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLayout, QSizePolicy, QToolTip,
                               QVBoxLayout, QWidget)

from . import theme as T
from .i18n import tr
from .engine import HIST_BINS, HIST_STEP_US, TrackResult


def card(title: Optional[str] = None) -> Tuple[QFrame, QVBoxLayout]:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
    if title:
        l = QLabel(title)
        l.setObjectName("h2")
        lay.addWidget(l)
    return f, lay


class StatTile(QWidget):
    def __init__(self, label: str, value: str = "—"):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.val = QLabel(value)
        self.val.setObjectName("stat")
        lbl = QLabel(label)
        lbl.setObjectName("statlbl")
        v.addWidget(self.val)
        v.addWidget(lbl)

    def set(self, s: str, color: Optional[str] = None):
        self.val.setText(s)
        self.val.setStyleSheet(f"color:{color};" if color else "")


# --------------------------------------------------------------------------
class TrackMap(QWidget):
    """Carte des pistes. Deux vues : grille (cylindres × faces, secteurs empilés)
    ou disque (anneaux concentriques, secteurs en arcs)."""

    track_clicked = Signal(int, int)

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.mode = "grid"
        self.health = False
        self.cyls, self.heads = 80, 2
        self.planned: set = set()
        self.results: Dict[Tuple[int, int], TrackResult] = {}
        self.current: Optional[Tuple[int, int]] = None
        self.selected: Optional[Tuple[int, int]] = None
        self.default_nsec = 0
        self._pulse = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(60)

    # API
    def reset(self, cyls: int, heads_used: List[int], nsec: int = 0, planned=None):
        self.cyls = max(1, cyls)
        self.results.clear()
        self.current = None
        self.default_nsec = nsec
        if planned is None:
            planned = {(c, h) for c in range(cyls) for h in heads_used}
        self.planned = set(planned)
        self.update()

    def set_mode(self, mode: str):
        self.mode = mode
        self.update()

    def set_health(self, on: bool):
        self.health = on
        self.update()

    @staticmethod
    def health_color(q: float) -> QColor:
        if q <= 0:
            return QColor(T.STATUS["empty"])
        # 80 % → rouge, 90 % → orange, 98 % → vert
        t = max(0.0, min(1.0, (q - 80) / 18))
        if t < 0.5:
            a, b, k = QColor("#f0524f"), QColor("#e3a73b"), t * 2
        else:
            a, b, k = QColor("#e3a73b"), QColor("#34c47c"), (t - 0.5) * 2
        return QColor(int(a.red() + (b.red() - a.red()) * k), int(a.green() + (b.green() - a.green()) * k),
                      int(a.blue() + (b.blue() - a.blue()) * k))

    def set_current(self, c: int, h: int):
        if c >= self.cyls:
            self.cyls = c + 1
        self.current = (c, h)
        self.update()

    def set_result(self, r: TrackResult):
        if r.cyl >= self.cyls:
            self.cyls = r.cyl + 1
        self.results[r.cyl, r.head] = r
        if self.current == (r.cyl, r.head):
            self.current = None
        self.update()

    def clear_current(self):
        self.current = None
        self.update()

    def _tick(self):
        if self.current is not None:
            self._pulse = (self._pulse + 0.12) % (2 * math.pi)
            self.update()

    # Géométrie grille
    def _grid_geom(self):
        lm, rm, tm, bm = 46, 10, 22, 8
        gap = 14
        w = self.width() - lm - rm
        h = (self.height() - tm - bm - gap) / 2
        cw = w / self.cyls
        return lm, tm, cw, h, gap

    def _disk_geom(self):
        w, h = self.width(), self.height()
        size = min((w - 30) / 2, h - 30)
        r_out = size / 2
        r_in = r_out * 0.28
        cy = h / 2 + 6
        cxs = [w / 4 + 5, 3 * w / 4 - 5]
        return cxs, cy, r_out, r_in

    def _hit(self, pos) -> Optional[Tuple[int, int, Optional[int]]]:
        x, y = pos.x(), pos.y()
        if self.mode == "grid":
            lm, tm, cw, hh, gap = self._grid_geom()
            if x < lm:
                return None
            c = int((x - lm) / cw)
            if not 0 <= c < self.cyls:
                return None
            for h in range(2):
                top = tm + h * (hh + gap)
                if top <= y < top + hh:
                    r = self.results.get((c, h))
                    n = r.nsec if r and r.nsec else self.default_nsec
                    s = int((y - top) / hh * n) if n else None
                    return c, h, s
            return None
        cxs, cy, ro, ri = self._disk_geom()
        for h, cx in enumerate(cxs):
            dx, dy = x - cx, y - cy
            d = math.hypot(dx, dy)
            if ri <= d <= ro:
                c = int((ro - d) / (ro - ri) * self.cyls)
                c = min(c, self.cyls - 1)
                r = self.results.get((c, h))
                n = r.nsec if r and r.nsec else self.default_nsec
                ang = (math.degrees(math.atan2(dx, -dy)) + 360) % 360
                s = int(ang / 360 * n) if n else None
                return c, h, s
        return None

    def mouseMoveEvent(self, e):
        hit = self._hit(e.position())
        if hit is None:
            QToolTip.hideText()
            return
        c, h, s = hit
        r = self.results.get((c, h))
        lines = [f"<b>Cylindre {c} · face {h}</b>"]
        if r is None:
            lines.append("Non lue" if (c, h) in self.planned else "Hors sélection")
        else:
            lines.append(T.STATUS_LABEL.get(r.status, r.status))
            if r.nsec:
                lines.append(f"Secteurs : {r.nsec - r.nbad}/{r.nsec}")
                if s is not None and s < len(r.good):
                    lines.append(f"Secteur #{s} : {'OK' if r.good[s] else 'ILLISIBLE'}")
            if r.retries:
                lines.append(f"Relectures : {r.retries}")
            if r.rpm:
                lines.append(f"{r.rpm:.1f} tr/min")
            if r.quality:
                lines.append(f"Qualité du signal : {r.quality:.1f} % (gigue {r.jitter:.1f} %)")
            if r.weak:
                lines.append(f"Secteurs faibles : {r.weak}")
        QToolTip.showText(e.globalPosition().toPoint(), "<br>".join(lines), self)

    def mousePressEvent(self, e):
        hit = self._hit(e.position())
        if hit:
            self.selected = (hit[0], hit[1])
            self.update()
            self.track_clicked.emit(hit[0], hit[1])

    # Couleurs
    def _cell_colors(self, c, h) -> Tuple[str, List[QColor]]:
        r = self.results.get((c, h))
        if r is None:
            if (c, h) in self.planned:
                return "pending", []
            return "absent", []
        if self.health and r.quality > 0:
            col = self.health_color(r.quality)
            n = max(r.nsec, 1)
            weak = set(r.weak)
            return r.status, [QColor("#a970ff") if i in weak else col for i in range(n)]
        if r.nsec and r.good:
            base = "retried" if r.status == "retried" else "ok"
            return r.status, [T.qc(base) if g else T.qc("bad") for g in r.good]
        return r.status, []

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.mode == "grid":
            self._paint_grid(p)
        else:
            self._paint_disk(p)

    def _paint_grid(self, p: QPainter):
        lm, tm, cw, hh, gap = self._grid_geom()
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(QColor(T.MUTED))
        step = 10 if cw * 10 > 26 else 20
        for c in range(0, self.cyls, step):
            p.drawText(QRectF(lm + c * cw - 10, 2, 30, 16), Qt.AlignLeft | Qt.AlignVCenter, str(c))
        for h in range(2):
            top = tm + h * (hh + gap)
            p.setPen(QColor(T.MUTED))
            p.drawText(QRectF(0, top, lm - 8, hh), Qt.AlignRight | Qt.AlignVCenter, tr(f"Face {h}"))
            pad = 1.0 if cw > 5 else 0.5
            for c in range(self.cyls):
                x = lm + c * cw
                rect = QRectF(x + pad, top, max(cw - 2 * pad, 1), hh)
                st, secs = self._cell_colors(c, h)
                p.setPen(Qt.NoPen)
                if secs:
                    n = len(secs)
                    sh = hh / n
                    for i, col in enumerate(secs):
                        p.setBrush(col)
                        p.drawRect(QRectF(rect.x(), top + i * sh + (0.4 if sh > 3 else 0),
                                          rect.width(), max(sh - (0.8 if sh > 3 else 0), 0.6)))
                else:
                    p.setBrush(T.qc(st))
                    p.drawRoundedRect(rect, 2, 2)
                if self.current == (c, h):
                    a = 0.45 + 0.55 * (0.5 + 0.5 * math.sin(self._pulse))
                    col = QColor(T.ACCENT)
                    col.setAlphaF(a)
                    p.setBrush(col)
                    p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 2, 2)
                if self.selected == (c, h):
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QPen(QColor("white"), 1.5))
                    p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 2, 2)

    def _paint_disk(self, p: QPainter):
        cxs, cy, ro, ri = self._disk_geom()
        if ro < 20:
            return
        rw = (ro - ri) / self.cyls
        f = QFont(self.font())
        f.setPointSizeF(9)
        p.setFont(f)
        for h, cx in enumerate(cxs):
            # fond
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.DEEP))
            p.drawEllipse(QPointF(cx, cy), ro + 4, ro + 4)
            for c in range(self.cyls):
                r_outer = ro - c * rw
                r_mid = r_outer - rw / 2
                st, secs = self._cell_colors(c, h)
                width = max(rw - (0.35 if rw > 2.5 else 0), 0.6)
                if secs:
                    n = len(secs)
                    span = 360 / n
                    for i, col in enumerate(secs):
                        self._arc(p, cx, cy, r_mid, width, i * span + 0.6, span - 1.2, col)
                else:
                    self._arc(p, cx, cy, r_mid, width, 0, 360, T.qc(st))
                if self.current == (c, h):
                    col = QColor(T.ACCENT)
                    col.setAlphaF(0.5 + 0.5 * math.sin(self._pulse) ** 2)
                    self._arc(p, cx, cy, r_mid, max(width, 2), 0, 360, col)
                if self.selected == (c, h):
                    self._arc(p, cx, cy, r_mid, max(width, 1.5), 0, 360, QColor("white"))
            # moyeu
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(T.RING))
            p.drawEllipse(QPointF(cx, cy), ri - 3, ri - 3)
            p.setBrush(QColor(T.BG))
            p.drawEllipse(QPointF(cx, cy), ri * 0.35, ri * 0.35)
            p.setPen(QColor(T.MUTED))
            p.drawText(QRectF(cx - 60, cy - ro - 22, 120, 16), Qt.AlignCenter, tr(f"Face {h}"))

    @staticmethod
    def _arc(p: QPainter, cx, cy, r, width, start_deg, span_deg, col: QColor):
        pen = QPen(col, width)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        # 0° en haut, sens horaire
        p.drawArc(rect, int((90 - start_deg) * 16), int(-span_deg * 16))


class FlowLayout(QLayout):
    """Disposition qui passe à la ligne quand la largeur manque (barres de boutons, légendes)."""

    def __init__(self, parent=None, hspacing: int = 8, vspacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._h, self._v = hspacing, vspacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def addStretch(self, *_a):      # compatibilité avec QHBoxLayout
        pass

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            if it.widget() is not None and not it.widget().isVisible() and it.widget().isHidden():
                continue
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line = r.x(), r.y(), 0
        for it in self._items:
            w = it.widget()
            if w is not None and w.isHidden():
                continue
            sh = it.sizeHint()
            nx = x + sh.width() + self._h
            if nx - self._h > r.right() + 1 and line > 0:
                x, y = r.x(), y + line + self._v
                nx, line = x + sh.width() + self._h, 0
            if not test:
                it.setGeometry(QRect(QPoint(x, y), sh))
            x, line = nx, max(line, sh.height())
        return y + line - rect.y() + m.bottom()


class FlowBar(QWidget):
    """Barre de widgets qui passe à la ligne (hauteur adaptée à la largeur)."""

    def __init__(self, hspacing: int = 8, vspacing: int = 6):
        super().__init__()
        self.flow = FlowLayout(self, hspacing, vspacing)
        sp = self.sizePolicy()
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)

    def addWidget(self, w):
        self.flow.addWidget(w)

    def addStretch(self, *_a):
        pass

    def resizeEvent(self, e):
        _fit_flow_height(self)
        super().resizeEvent(e)

    def event(self, e):
        r = super().event(e)
        if e.type() in (e.Type.LayoutRequest, e.Type.Show):
            _fit_flow_height(self)
        return r


def _fit_flow_height(w: QWidget):
    """Hauteur minimale = hauteur réelle des lignes pour la largeur courante (évite les chevauchements)."""
    lay = w.layout()
    if lay is None or not w.isVisible() or w.width() < 150:
        return
    h = lay.heightForWidth(w.width())
    if h > 0 and w.minimumHeight() != h:
        w.setMinimumHeight(h)


class Legend(QWidget):
    def __init__(self, keys: List[str]):
        super().__init__()
        lay = FlowLayout(self, 14, 4)
        sp = self.sizePolicy()
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.items = {}
        for k in keys:
            w = QWidget()
            l = QHBoxLayout(w)
            l.setContentsMargins(0, 0, 0, 0)
            l.setSpacing(5)
            sw = QLabel()
            sw.setFixedSize(10, 10)
            sw.setStyleSheet(f"background:{T.STATUS[k]}; border-radius:2px;")
            t = QLabel(T.STATUS_LABEL[k])
            t.setObjectName("muted")
            l.addWidget(sw)
            l.addWidget(t)
            lay.addWidget(w)
            self.items[k] = w

    def resizeEvent(self, e):
        _fit_flow_height(self)
        super().resizeEvent(e)


# --------------------------------------------------------------------------
class FluxHistogram(QWidget):
    """Histogramme des intervalles de flux (µs), échelle log optionnelle."""

    def __init__(self):
        super().__init__()
        self.hist: List[int] = []
        self.setMinimumHeight(60)
        self.title = ""

    def set_hist(self, hist: List[int], title: str = ""):
        self.hist = hist or []
        self.title = title
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        lm, rm, tm, bm = 8, 8, 18, 20
        w, h = self.width() - lm - rm, self.height() - tm - bm
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(QColor(T.MUTED))
        p.drawText(QRectF(lm, 0, w, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   tr(self.title or "Histogramme des intervalles de flux"))
        # repères µs
        max_us = HIST_BINS * HIST_STEP_US
        step = 2 if w / (max_us / 2) >= 44 else (4 if w / (max_us / 4) >= 44 else 8)
        for us in range(step, int(max_us), step):
            x = lm + us / max_us * w
            p.setPen(QPen(QColor(T.BORDER), 1, Qt.DashLine))
            p.drawLine(QPointF(x, tm), QPointF(x, tm + h))
            p.setPen(QColor(T.MUTED))
            p.drawText(QRectF(x - 22, tm + h + 2, 44, 16), Qt.AlignCenter, f"{us} µs")
        if not self.hist or max(self.hist) == 0:
            p.drawText(QRectF(lm, tm, w, h), Qt.AlignCenter | Qt.TextWordWrap,
                       tr("Cliquez une piste lue pour voir son flux"))
            return
        mx = math.log1p(max(self.hist))
        bw = w / len(self.hist)
        path = QPainterPath(QPointF(lm, tm + h))
        for i, v in enumerate(self.hist):
            y = tm + h - (math.log1p(v) / mx) * h
            path.lineTo(QPointF(lm + i * bw, y))
            path.lineTo(QPointF(lm + (i + 1) * bw, y))
        path.lineTo(QPointF(lm + w, tm + h))
        path.closeSubpath()
        col = QColor(T.ACCENT)
        col.setAlphaF(0.35)
        p.setPen(QPen(QColor(T.ACCENT), 1.2))
        p.setBrush(col)
        p.drawPath(path)


class RpmChart(QWidget):
    def __init__(self, fixed: Optional[Tuple[float, float, float]] = None, maxlen: int = 0):
        super().__init__()
        self.fixed = fixed          # (bas, référence, haut) : sinon axe tr/min automatique
        self.maxlen = maxlen
        self.vals: List[float] = []
        self.setMinimumHeight(120)

    def clear(self):
        self.vals = []
        self.update()

    def add(self, v: float):
        self.vals.append(v)
        if self.maxlen and len(self.vals) > self.maxlen:
            self.vals = self.vals[-self.maxlen:]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        lm, rm, tm, bm = 54, 10, 10, 18
        w, h = self.width() - lm - rm, self.height() - tm - bm
        f = QFont(self.font())
        f.setPointSizeF(8)
        p.setFont(f)
        if not self.vals:
            p.setPen(QColor(T.MUTED))
            p.drawText(self.rect(), Qt.AlignCenter, tr("Aucune mesure"))
            return
        if self.fixed:
            lo, nominal, hi = self.fixed
            lo, hi = min(lo, min(self.vals)), max(hi, max(self.vals))
        else:
            nominal = 360 if sum(self.vals) / len(self.vals) > 330 else 300
            lo = min(min(self.vals), nominal - 3)
            hi = max(max(self.vals), nominal + 3)
        def Y(v):
            return tm + h - (v - lo) / (hi - lo) * h
        for v in (lo, nominal, hi):
            p.setPen(QPen(QColor(T.BORDER), 1, Qt.DashLine))
            p.drawLine(QPointF(lm, Y(v)), QPointF(lm + w, Y(v)))
            p.setPen(QColor(T.MUTED))
            p.drawText(QRectF(0, Y(v) - 8, lm - 6, 16), Qt.AlignRight | Qt.AlignVCenter, f"{v:.1f}")
        n = max(len(self.vals) - 1, 1)
        path = QPainterPath(QPointF(lm, Y(self.vals[0])))
        for i, v in enumerate(self.vals):
            path.lineTo(QPointF(lm + i / n * w, Y(v)))
        p.setPen(QPen(QColor(T.ACCENT), 2))
        p.drawPath(path)
        p.setBrush(QColor(T.ACCENT))
        for i, v in enumerate(self.vals):
            p.drawEllipse(QPointF(lm + i / n * w, Y(v)), 2.5, 2.5)
