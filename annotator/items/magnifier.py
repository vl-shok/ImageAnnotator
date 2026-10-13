"""Выносной вид (лупа): выделенная область фото показывается рядом в увеличенном виде,
а линии-выноски показывают, откуда взято увеличение.

pos() — общий сдвиг объекта; self.src — область-источник (локально), self.dst — левый верхний
угол увеличенного вида (локально). Размер вида = размер области × «Увеличение».
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker

from ..geometry import rect_snap_points
from ..props import LINE_STYLES, OPACITY, PropSpec
from .base import AnnotationItem, make_pen

SHAPES = [("rect", "Прямоугольник"), ("circle", "Круг")]
S_MAG = "Выносной вид"


def _hull(points):
    """Выпуклая оболочка (монотонная цепь). points: [(x, y, tag)]."""
    pts = sorted(set(points), key=lambda p: (p[0], p[1]))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


class MagnifierItem(AnnotationItem):
    TYPE = "magnifier"
    TITLE = "Выносной вид"
    source_provider = staticmethod(lambda: None)   # задаётся документом: изображение фото
    DEFAULTS = {"zoom": 2.5, "shape": "rect", "color": "#ff2020", "width": 2.5, "style": "solid",
                "connectors": True, "line_style": "dash", "opacity": 1.0}
    PROPS = [
        PropSpec("zoom", "Увеличение", "float", S_MAG, min=1.1, max=20, step=0.5, suffix="×"),
        PropSpec("shape", "Форма", "align", S_MAG, options=SHAPES, icon="shp_"),
        PropSpec("color", "Цвет рамок", "color", S_MAG),
        PropSpec("width", "Толщина", "float", S_MAG, min=0.5, max=40, step=0.5, suffix=" px"),
        PropSpec("connectors", "Линии-выноски", "bool", S_MAG),
        PropSpec("line_style", "Стиль линий", "enum", S_MAG, options=LINE_STYLES),
        OPACITY,
    ]

    def __init__(self, props=None):
        super().__init__(props)
        self.src = QRectF(0, 0, 0, 0)
        self.dst = QPointF(0, 0)
        self._drag = None

    # ------------------------------------------------------------------ serialization
    def geom_to_dict(self, full=False):
        s = self.src
        return {"src": [round(s.x(), 3), round(s.y(), 3), round(s.width(), 3), round(s.height(), 3)],
                "dst": [round(self.dst.x(), 3), round(self.dst.y(), 3)]}

    def geom_from_dict(self, d):
        x, y, w, h = d.get("src", [0, 0, 0, 0])
        self.src = QRectF(float(x), float(y), float(w), float(h))
        dx, dy = d.get("dst", [0, 0])
        self.dst = QPointF(float(dx), float(dy))

    # ------------------------------------------------------------------ geometry
    def zoom(self):
        return max(1.0, float(self.props.get("zoom", 2.5)))

    def circle(self):
        return self.props.get("shape") == "circle"

    def src_rect(self) -> QRectF:
        r = QRectF(self.src)
        if self.circle():
            s = max(r.width(), r.height())
            c = r.center()
            r = QRectF(c.x() - s / 2, c.y() - s / 2, s, s)
        return r

    def dst_rect(self) -> QRectF:
        s = self.src_rect()
        k = self.zoom()
        return QRectF(self.dst.x(), self.dst.y(), s.width() * k, s.height() * k)

    def _shape_path(self, r: QRectF) -> QPainterPath:
        p = QPainterPath()
        if self.circle():
            p.addEllipse(r)
        else:
            p.addRect(r)
        return p

    def set_drag(self, p0, p1, constrain=False, center=False):
        """Создание: тянем область-источник; увеличенный вид ставится рядом автоматически."""
        self.prepareGeometryChange()
        r = QRectF(p0, p1).normalized()
        if constrain or self.circle():
            s = max(r.width(), r.height())
            sx = 1 if p1.x() >= p0.x() else -1
            sy = 1 if p1.y() >= p0.y() else -1
            r = QRectF(p0, QPointF(p0.x() + sx * s, p0.y() + sy * s)).normalized()
        self.setPos(r.topLeft())
        self.src = QRectF(0, 0, r.width(), r.height())
        self.auto_place()
        self.update()

    def auto_place(self):
        """Поставить увеличенный вид справа (или слева, если справа не помещается)."""
        s = self.src_rect()
        k = self.zoom()
        w, h = s.width() * k, s.height() * k
        gap = max(30.0, s.width() * 0.6)
        y = s.center().y() - h / 2
        x = s.right() + gap
        img = self.source_provider()
        if img is not None and not img.isNull():
            scene_x = self.pos().x() + x
            if scene_x + w > img.width() and self.pos().x() + s.left() - gap - w >= 0:
                x = s.left() - gap - w
            sy = self.pos().y() + y
            if sy < 0:
                y -= sy
            elif sy + h > img.height():
                y -= (sy + h - img.height())
        self.dst = QPointF(x, y)

    def connector_lines(self):
        a, b = self.src_rect(), self.dst_rect()
        if a.isEmpty() or b.isEmpty() or a.intersects(b):
            return []
        if self.circle():
            c1, c2 = a.center(), b.center()
            r1, r2 = a.width() / 2, b.width() / 2
            dx, dy = c2.x() - c1.x(), c2.y() - c1.y()
            d = math.hypot(dx, dy)
            if d <= abs(r2 - r1) + 1e-6:
                return []
            th = math.atan2(dy, dx)
            al = math.acos(max(-1.0, min(1.0, (r1 - r2) / d)))
            out = []
            for sgn in (1, -1):
                ang = th + sgn * al
                out.append((QPointF(c1.x() + r1 * math.cos(ang), c1.y() + r1 * math.sin(ang)),
                            QPointF(c2.x() + r2 * math.cos(ang), c2.y() + r2 * math.sin(ang))))
            return out
        pts = [(p.x(), p.y(), 0) for p in (a.topLeft(), a.topRight(), a.bottomRight(), a.bottomLeft())]
        pts += [(p.x(), p.y(), 1) for p in (b.topLeft(), b.topRight(), b.bottomRight(), b.bottomLeft())]
        hull = _hull(pts)
        out = []
        for i in range(len(hull)):
            p, q = hull[i], hull[(i + 1) % len(hull)]
            if p[2] != q[2]:
                out.append((QPointF(p[0], p[1]), QPointF(q[0], q[1])))
        return out

    def outline_path(self):
        path = self._shape_path(self.src_rect())
        path.addPath(self._shape_path(self.dst_rect()))
        if self.props.get("connectors", True):
            for a, b in self.connector_lines():
                path.moveTo(a)
                path.lineTo(b)
        return path

    def hit(self, scene_pt, tol):
        p = self.mapFromScene(scene_pt)
        if self._shape_path(self.dst_rect()).contains(p):
            return True
        st = QPainterPathStroker()
        st.setWidth(float(self.props.get("width", 2)) + 2 * tol)
        return st.createStroke(self.outline_path()).contains(p)

    def filled_hit(self):
        return False

    def margin(self):
        return float(self.props.get("width", 2)) * 2 + 4

    # ------------------------------------------------------------------ handles
    # 0-3 углы области, 4 — центр области (сдвинуть только её),
    # 5 — центр вида (сдвинуть только вид), 6 — правый нижний угол вида (увеличение)
    def handles(self):
        s, d = self.src_rect(), self.dst_rect()
        return [s.topLeft(), s.topRight(), s.bottomRight(), s.bottomLeft(), s.center(), d.center(), d.bottomRight()]

    def handle_kinds(self):
        return ["box", "box", "box", "box", "point", "point", "box"]

    def handle_cursor(self, idx):
        if idx in (4, 5):
            return Qt.SizeAllCursor
        return Qt.SizeFDiagCursor if idx in (0, 2, 6) else Qt.SizeBDiagCursor

    def begin_handle_drag(self, idx):
        self._drag = (QRectF(self.src_rect()), QPointF(self.dst), self.zoom(), QRectF(self.dst_rect()),
                      QRectF(self.src))
        return None

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        if self._drag is None:
            self.begin_handle_drag(idx)
        s0, d0, z0, dr0, raw0 = self._drag
        self.prepareGeometryChange()
        if idx < 4:
            opp = [s0.bottomRight(), s0.bottomLeft(), s0.topLeft(), s0.topRight()][idx]
            r = QRectF(opp, p).normalized()
            if self.circle() or constrain:
                sz = max(r.width(), r.height())
                sx = 1 if p.x() >= opp.x() else -1
                sy = 1 if p.y() >= opp.y() else -1
                r = QRectF(opp, QPointF(opp.x() + sx * sz, opp.y() + sy * sz)).normalized()
            if r.width() >= 4 and r.height() >= 4:
                self.src = r
                # вид остаётся на месте (центр), размер меняется вместе с областью
                c = dr0.center()
                k = self.zoom()
                sr = self.src_rect()
                self.dst = QPointF(c.x() - sr.width() * k / 2, c.y() - sr.height() * k / 2)
        elif idx == 4:
            # сдвиг считается от положения на момент нажатия (а не накапливается)
            c = s0.center()
            self.src = QRectF(raw0).translated(p.x() - c.x(), p.y() - c.y())
        elif idx == 5:
            c = dr0.center()
            self.dst = QPointF(d0.x() + p.x() - c.x(), d0.y() + p.y() - c.y())
        else:
            if s0.width() > 0:
                z = max(1.1, min(20.0, (p.x() - dr0.left()) / s0.width()))
                self.props["zoom"] = round(z, 2)
        self.update()

    def snap_points(self):
        return rect_snap_points(self.src_rect()) + rect_snap_points(self.dst_rect())

    def props_changed(self):
        self.update()

    # ------------------------------------------------------------------ paint
    def paint(self, painter, option, widget=None):
        s, d = self.src_rect(), self.dst_rect()
        if s.isEmpty():
            return
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        self.paint_opacity(painter)
        col = self.props.get("color", "#ff2020")
        w = float(self.props.get("width", 2.5))
        if self.props.get("connectors", True):
            painter.setPen(make_pen(col, max(0.5, w * 0.7), self.props.get("line_style", "dash")))
            for a, b in self.connector_lines():
                painter.drawLine(a, b)
        # увеличенное изображение
        img = self.source_provider()
        dpath = self._shape_path(d)
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawPath(dpath)
        if img is not None and not img.isNull():
            painter.setClipPath(dpath)
            src_scene = s.translated(self.pos())
            painter.drawImage(d, img, src_scene)
        painter.restore()
        painter.setPen(make_pen(col, w))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self._shape_path(s))
        painter.setPen(make_pen(col, w * 1.3))
        painter.drawPath(dpath)

    def describe(self):
        return f"{self.TITLE} ×{self.zoom():g}"
