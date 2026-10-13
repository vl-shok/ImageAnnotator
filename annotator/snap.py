"""Привязки (Snap) к характерным точкам объектов и границам изображения."""
from __future__ import annotations

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


class SnapManager:
    def __init__(self):
        self.enabled = True
        self.radius_px = 10
        self.kinds = {k for k, _ in SNAP_KINDS}
        self.to_image = True

    def find(self, doc, pt: QPointF, tol: float, exclude=(), extra=None):
        """Возвращает (QPointF, kind) или None. tol — радиус в единицах сцены.
        extra — дополнительные точки сцены [(QPointF, kind)] (например, вершины строящейся полилинии)."""
        if not self.enabled or tol <= 0:
            return None
        exclude = set(id(e) for e in exclude)
        best, bd = None, tol
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
            for lp, kind in it.snap_points():
                if kind not in self.kinds:
                    continue
                sp = it.mapToScene(lp)
                d = dist(sp, pt)
                if d <= bd:
                    best, bd = (sp, kind), d
        canvas = doc.canvas_rect()
        if self.to_image and not canvas.isEmpty() and doc.bg_item.isVisible():
            for lp, kind in rect_snap_points(canvas):
                if kind not in self.kinds:
                    continue
                d = dist(lp, pt)
                if d <= bd:
                    best, bd = (QPointF(lp), kind), d
        if best is not None or "edge" not in self.kinds:
            return best
        # привязка к ближайшей точке контура
        for it in candidates:
            path = it.mapToScene(it.outline_path())
            for poly in path.toSubpathPolygons():
                for i in range(len(poly) - 1):
                    q = nearest_on_segment(pt, poly[i], poly[i + 1])
                    d = dist(q, pt)
                    if d <= bd:
                        best, bd = (q, "edge"), d
        if best is None and self.to_image and not canvas.isEmpty() and doc.bg_item.isVisible():
            c = [canvas.topLeft(), canvas.topRight(), canvas.bottomRight(), canvas.bottomLeft()]
            for a, b in zip(c, c[1:] + c[:1]):
                q = nearest_on_segment(pt, a, b)
                d = dist(q, pt)
                if d <= bd:
                    best, bd = (q, "edge"), d
        return best
