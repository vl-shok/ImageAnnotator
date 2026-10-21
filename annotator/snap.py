"""Привязки (Snap) к характерным точкам объектов и границам изображения."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF

from .geometry import dist, nearest_on_segment, rect_snap_points

SNAP_KINDS = [
    ("endpoint", "Конец"),
    ("midpoint", "Середина"),
    ("center", "Центр"),
    ("vertex", "Вершина"),
    ("edge", "Контур"),
]
SNAP_LABELS = dict(SNAP_KINDS)

GUIDE_ANGLES = (0, 45, 90, 135)   # направления от опорной точки (предыдущей точки линии)
MOVE_POINTS_MAX = 40              # при перемещении многих объектов выравнивается их общая рамка


class _Line:
    """Направляющая: прямая через p0 с единичным направлением (ux, uy); ref — точка, от которой она идёт."""
    __slots__ = ("x0", "y0", "ux", "uy", "ref")

    def __init__(self, p0: QPointF, ux: float, uy: float):
        self.x0, self.y0, self.ux, self.uy = p0.x(), p0.y(), ux, uy
        self.ref = QPointF(p0)

    def dist(self, p: QPointF) -> float:
        return abs((p.x() - self.x0) * self.uy - (p.y() - self.y0) * self.ux)

    def project(self, p: QPointF) -> QPointF:
        t = (p.x() - self.x0) * self.ux + (p.y() - self.y0) * self.uy
        return QPointF(self.x0 + self.ux * t, self.y0 + self.uy * t)

    def intersect(self, o: "_Line") -> QPointF | None:
        den = self.ux * o.uy - self.uy * o.ux
        if abs(den) < 0.1:
            return None   # параллельны
        t = ((o.x0 - self.x0) * o.uy - (o.y0 - self.y0) * o.ux) / den
        return QPointF(self.x0 + self.ux * t, self.y0 + self.uy * t)


class SnapManager:
    def __init__(self):
        self.enabled = True
        self.radius_px = 10
        self.kinds = {k for k, _ in SNAP_KINDS}
        self.to_image = True
        self.guides = True   # направляющие выравнивания (по горизонтали/вертикали с точками объектов, 45°)
        # объект, к точке которого привязались при последнем find: (объект, № точки или None, локальная точка)
        self.last_target = None

    def find(self, doc, pt: QPointF, tol: float, exclude=(), extra=None):
        """Возвращает (QPointF, kind) или None. tol — радиус в единицах сцены.
        extra — дополнительные точки сцены [(QPointF, kind)] (например, вершины строящейся полилинии).
        Объект, к которому привязались, запоминается в last_target (для приклеивания концов)."""
        self.last_target = None
        if not self.enabled or tol <= 0:
            return None
        exclude = set(id(e) for e in exclude)
        best, bd, target = None, tol, None
        for sp, kind in (extra or []):
            if kind in self.kinds:
                d = dist(sp, pt)
                if d <= bd:
                    best, bd = (QPointF(sp), kind), d
        candidates = []
        for it in doc.items():
            if id(it) in exclude or not it.isVisible():
                continue
            br = it.sceneBoundingRect().adjusted(-tol, -tol, tol, tol)
            if not br.contains(pt):
                continue
            candidates.append(it)
            for si, (lp, kind) in enumerate(it.snap_points()):
                if kind not in self.kinds:
                    continue
                sp = it.mapToScene(lp)
                d = dist(sp, pt)
                if d <= bd:
                    best, bd, target = (sp, kind), d, (it, si, QPointF(lp))
        canvas = doc.canvas_rect()
        if self.to_image and not canvas.isEmpty() and doc.bg_item.isVisible():
            for lp, kind in rect_snap_points(canvas):
                if kind not in self.kinds:
                    continue
                d = dist(lp, pt)
                if d < bd or (d == bd and best is None):   # при равенстве точка объекта важнее
                    best, bd, target = (QPointF(lp), kind), d, None
        if best is not None or "edge" not in self.kinds:
            self.last_target = target if best is not None else None
            return best
        # привязка к ближайшей точке контура
        for it in candidates:
            path = it.mapToScene(it.outline_path())
            for poly in path.toSubpathPolygons():
                for i in range(len(poly) - 1):
                    q = nearest_on_segment(pt, poly[i], poly[i + 1])
                    d = dist(q, pt)
                    if d <= bd:
                        best, bd, target = (q, "edge"), d, (it, None, it.mapFromScene(q))
        if best is None and self.to_image and not canvas.isEmpty() and doc.bg_item.isVisible():
            c = [canvas.topLeft(), canvas.topRight(), canvas.bottomRight(), canvas.bottomLeft()]
            for a, b in zip(c, c[1:] + c[:1]):
                q = nearest_on_segment(pt, a, b)
                d = dist(q, pt)
                if d <= bd:
                    best, bd = (q, "edge"), d
        self.last_target = target
        return best

    # ================================================================ направляющие выравнивания
    def guide_refs(self, doc, exclude=(), extra=None) -> list[QPointF]:
        """Точки сцены, с которыми выравниваемся: характерные точки объектов, фото, extra."""
        exclude = set(id(e) for e in exclude)
        refs = [QPointF(p) for p, _ in (extra or [])]
        for it in doc.items():
            if id(it) in exclude or not it.isVisible():
                continue
            refs += [it.mapToScene(lp) for lp, kind in it.snap_points() if kind != "edge"]
        canvas = doc.canvas_rect()
        if self.to_image and not canvas.isEmpty() and doc.bg_item.isVisible():
            refs += [QPointF(lp) for lp, _ in rect_snap_points(canvas)]
        return refs

    def find_guides(self, doc, pt: QPointF, tol: float, exclude=(), extra=None, anchor=None, refs=None):
        """Выравнивание точки pt: (новая точка, [(откуда, куда)] — отрезки направляющих) или None.
        Вертикаль/горизонталь через точки объектов, направления 0/45/90/135° от anchor;
        если подходят две направляющие — точка ставится на их пересечение."""
        if not (self.enabled and self.guides) or tol <= 0:
            return None
        pts = self.guide_refs(doc, exclude, extra) + list(refs or [])
        lines = []
        # ближайшая по x (и затем ближайшая вообще) точка — вертикаль; точки рядом с курсором не в счёт
        bv = min(((abs(r.x() - pt.x()), abs(r.y() - pt.y()), r) for r in pts
                  if abs(r.x() - pt.x()) < tol and abs(r.y() - pt.y()) > tol), key=lambda v: v[:2], default=None)
        bh = min(((abs(r.y() - pt.y()), abs(r.x() - pt.x()), r) for r in pts
                  if abs(r.y() - pt.y()) < tol and abs(r.x() - pt.x()) > tol), key=lambda v: v[:2], default=None)
        if bv is not None:
            lines.append(_Line(bv[2], 0.0, 1.0))
        if bh is not None:
            lines.append(_Line(bh[2], 1.0, 0.0))
        if anchor is not None and dist(anchor, pt) > tol * 2:
            for a in GUIDE_ANGLES:
                r = math.radians(a)
                ln = _Line(anchor, math.cos(r), math.sin(r))
                if ln.dist(pt) < tol:
                    lines.append(ln)
        lines = [ln for ln in lines if ln.dist(pt) < tol]
        if not lines:
            return None
        lines.sort(key=lambda ln: ln.dist(pt))
        first = lines[0]
        best = None
        for o in lines[1:]:
            x = first.intersect(o)
            if x is not None and dist(x, pt) <= tol * 1.5 and (best is None or dist(x, pt) < dist(best[0], pt)):
                best = (x, o)
        if best is not None:
            x, used = best[0], [first, best[1]]
        else:
            x, used = first.project(pt), [first]
        return x, [(ln.ref, QPointF(x)) for ln in used]

    def find_move_guides(self, doc, pts, delta: QPointF, tol: float, exclude=()):
        """Перемещение объектов: выровнять их точки pts (сцена, до сдвига) по горизонтали/вертикали
        с точками других объектов. Возвращает (поправленный сдвиг, [(откуда, куда)])."""
        if not (self.enabled and self.guides) or tol <= 0 or not pts:
            return QPointF(delta), []
        refs = self.guide_refs(doc, exclude)
        bx = by = None
        for p in pts:
            mx, my = p.x() + delta.x(), p.y() + delta.y()
            for r in refs:
                dx, dy = r.x() - mx, r.y() - my
                if abs(dx) < tol and (bx is None or abs(dx) < abs(bx[0])):
                    bx = (dx, r, p)
                if abs(dy) < tol and (by is None or abs(dy) < abs(by[0])):
                    by = (dy, r, p)
        d = QPointF(delta.x() + (bx[0] if bx else 0.0), delta.y() + (by[0] if by else 0.0))
        lines = []
        for b in (bx, by):
            if b is not None:
                lines.append((QPointF(b[1]), b[2] + d))
        return d, lines
