"""Геометрические объекты: линия, стрелка, полилиния, полигон, карандаш, прямоугольник, эллипс."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPolygonF

from ..geometry import constrain_angle, mid, rect_snap_points, square_rect
from ..props import CAP_STYLES, OPACITY, S_ENDS, PropSpec, cap_size, fill_props, line_props
from .base import (AnnotationItem, arrow_head_size, draw_line_with_caps, make_pen, qcolor, quad_length,
                   quad_point)


# =====================================================================
class PathItem(AnnotationItem):
    """Объект, заданный списком точек (локальные координаты)."""
    CLOSED = False
    MIN_POINTS = 2

    def __init__(self, points=None, props=None):
        super().__init__(props)
        self.points: list[QPointF] = [QPointF(p) for p in (points or [])]

    # serialization
    def geom_to_dict(self, full=False):
        return {"points": [[round(p.x(), 3), round(p.y(), 3)] for p in self.points]}

    def geom_from_dict(self, d):
        self.points = [QPointF(float(x), float(y)) for x, y in d.get("points", [])]

    # creation helper (две точки в координатах сцены)
    def set_drag(self, p0: QPointF, p1: QPointF, constrain=False, center=False):
        self.prepareGeometryChange()
        if constrain:
            p1 = constrain_angle(p0, p1)
        self.setPos(p0)
        self.points = [QPointF(0, 0), p1 - p0]
        self.update()

    def set_scene_points(self, pts):
        self.prepareGeometryChange()
        if not pts:
            self.points = []
            return
        o = pts[0]
        self.setPos(o)
        self.points = [p - o for p in pts]
        self.update()

    def scene_points(self):
        return [self.mapToScene(p) for p in self.points]

    def outline_path(self):
        path = QPainterPath()
        if not self.points:
            return path
        path.moveTo(self.points[0])
        for p in self.points[1:]:
            path.lineTo(p)
        if self.CLOSED and len(self.points) > 2:
            path.closeSubpath()
        return path

    EDIT_VERTICES = False  # ручки «+» на серединах сегментов для добавления вершин

    def segments(self):
        n = len(self.points)
        segs = [(i, i + 1) for i in range(n - 1)]
        if self.CLOSED and n > 2:
            segs.append((n - 1, 0))
        return segs

    def handles(self):
        hs = list(self.points)
        if self.EDIT_VERTICES:
            hs += [mid(self.points[a], self.points[b]) for a, b in self.segments()]
        return hs

    def handle_kinds(self):
        kinds = ["vertex"] * len(self.points)
        if self.EDIT_VERTICES:
            kinds += ["insert"] * len(self.segments())
        return kinds

    def handle_cursor(self, idx):
        return Qt.CrossCursor

    def begin_handle_drag(self, idx):
        n = len(self.points)
        if idx >= n and self.EDIT_VERTICES:
            segs = self.segments()
            k = idx - n
            if k < len(segs):
                a, b = segs[k]
                return self.insert_vertex(a + 1, mid(self.points[a], self.points[b]))
        return None

    def insert_vertex(self, index, p: QPointF) -> int:
        self.prepareGeometryChange()
        self.points.insert(index, QPointF(p))
        self.update()
        return index

    def remove_vertex(self, idx):
        if len(self.points) <= self.MIN_POINTS or not (0 <= idx < len(self.points)):
            return
        self.prepareGeometryChange()
        self.points.pop(idx)
        self.update()

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        if not (0 <= idx < len(self.points)):
            return
        self.prepareGeometryChange()
        if constrain and len(self.points) > 1:
            if idx > 0:
                ref = self.points[idx - 1]
            elif self.CLOSED:
                ref = self.points[-1]
            else:
                ref = self.points[1]
            p = constrain_angle(ref, p)
        self.points[idx] = QPointF(p)
        self.update()

    def snap_points(self):
        pts = self.points
        out = []
        n = len(pts)
        for i, p in enumerate(pts):
            if not self.CLOSED and (i == 0 or i == n - 1):
                out.append((p, "endpoint"))
            else:
                out.append((p, "vertex"))
        segs = list(zip(pts, pts[1:]))
        if self.CLOSED and n > 2:
            segs.append((pts[-1], pts[0]))
        for a, b in segs:
            out.append((mid(a, b), "midpoint"))
        return out

    def margin(self):
        w = float(self.props.get("width", 2))
        caps = (self.props.get("start_cap"), self.props.get("end_cap"))
        extra = arrow_head_size(w)[0] if ("arrow" in caps or "dot" in caps) else 0
        return w * 2 + extra + 4


# =====================================================================
class BendMixin:
    """Изгиб двухточечного объекта: ручка в середине тянет линию в дугу (квадратичная кривая),
    начало и конец остаются на месте. self.ctrl — контрольная точка (локально) или None."""
    BENDABLE = True

    def bend_enabled(self):
        return self.BENDABLE and len(self.points) == 2

    def curve_mid(self) -> QPointF:
        p0, p1 = self.points[0], self.points[-1]
        if self.ctrl is None:
            return mid(p0, p1)
        return quad_point(p0, self.ctrl, p1, 0.5)

    def straighten(self):
        self.prepareGeometryChange()
        self.ctrl = None
        self.update()

    def _bend_to(self, m: QPointF):
        p0, p1 = self.points[0], self.points[-1]
        c = QPointF(2 * m.x() - 0.5 * (p0.x() + p1.x()), 2 * m.y() - 0.5 * (p0.y() + p1.y()))
        self.prepareGeometryChange()
        # почти прямая — считаем прямой
        self.ctrl = None if math.hypot(*(m - mid(p0, p1)).toTuple()) < 0.75 else c
        self.update()

    def _bend_geom(self, d):
        if self.bend_enabled() and self.ctrl is not None:
            d["ctrl"] = [round(self.ctrl.x(), 3), round(self.ctrl.y(), 3)]
        return d

    def _bend_from(self, d):
        c = d.get("ctrl")
        self.ctrl = QPointF(float(c[0]), float(c[1])) if c else None

    def _bend_handles(self, hs, kinds):
        if self.bend_enabled():
            hs.append(self.curve_mid())
            kinds.append("bend")
        return hs, kinds

    def _move_endpoint_keep_bend(self, idx, new_p):
        """При перемещении конца изогнутой линии контрольная точка смещается наполовину."""
        if self.ctrl is not None and 0 <= idx < len(self.points):
            old = self.points[idx]
            self.ctrl = self.ctrl + (new_p - old) * 0.5


class LineItem(BendMixin, PathItem):
    TYPE = "line"
    TITLE = "Линия"
    DEFAULTS = {"color": "#ff2020", "width": 3.0, "style": "solid", "opacity": 1.0,
                "start_cap": "none", "end_cap": "none", "start_size": 14.0, "end_size": 14.0}
    PROPS = line_props() + [
        PropSpec("start_cap", "Начало", "enum", S_ENDS, options=CAP_STYLES, pair=cap_size("start_size")),
        PropSpec("end_cap", "Конец", "enum", S_ENDS, options=CAP_STYLES, pair=cap_size("end_size")),
        OPACITY,
    ]

    def __init__(self, points=None, props=None):
        super().__init__(points, props)
        self.ctrl = None

    def geom_to_dict(self, full=False):
        return self._bend_geom(super().geom_to_dict(full))

    def geom_from_dict(self, d):
        super().geom_from_dict(d)
        self._bend_from(d)

    def set_drag(self, p0, p1, constrain=False, center=False):
        self.ctrl = None
        super().set_drag(p0, p1, constrain, center)

    def set_scene_points(self, pts):
        self.ctrl = None
        super().set_scene_points(pts)

    def outline_path(self):
        if self.bend_enabled() and self.ctrl is not None:
            path = QPainterPath(self.points[0])
            path.quadTo(self.ctrl, self.points[1])
            return path
        return super().outline_path()

    def handles(self):
        hs, _ = self._bend_handles(super().handles(), super().handle_kinds())
        return hs

    def handle_kinds(self):
        _, k = self._bend_handles(super().handles(), super().handle_kinds())
        return k

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        if self.bend_enabled() and idx == len(self.points):
            self._bend_to(p)
            return
        old = QPointF(self.points[idx]) if 0 <= idx < len(self.points) else None
        super().move_handle(idx, p, constrain, symmetric)
        if old is not None and self.ctrl is not None:
            self.ctrl = self.ctrl + (self.points[idx] - old) * 0.5

    def snap_points(self):
        if self.bend_enabled() and self.ctrl is not None:
            return [(self.points[0], "endpoint"), (self.points[1], "endpoint"), (self.curve_mid(), "midpoint")]
        return super().snap_points()

    def margin(self):
        w = float(self.props.get("width", 2))
        sizes = [float(self.props.get("start_size") or 0), float(self.props.get("end_size") or 0)]
        return w * 2 + max([arrow_head_size(w)[0]] + sizes) + 4

    def paint(self, painter: QPainter, option, widget=None):
        if len(self.points) < 2:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint_opacity(painter)
        p = self.props
        draw_line_with_caps(painter, self.points, p["color"], p["width"], p["style"], p["start_cap"], p["end_cap"],
                            start_size=p.get("start_size", 0), end_size=p.get("end_size", 0),
                            ctrl=self.ctrl if self.bend_enabled() else None)

    def describe(self):
        if len(self.points) >= 2:
            ln = math.hypot(*(self.points[-1] - self.points[0]).toTuple())
            return f"{self.TITLE} {ln:.0f} px" + (" (дуга)" if self.ctrl is not None else "")
        return self.TITLE


class PolylineItem(LineItem):
    TYPE = "polyline"
    TITLE = "Полилиния"
    EDIT_VERTICES = True
    BENDABLE = False

    def describe(self):
        return f"{self.TITLE} ({len(self.points)} т.)"


class PolygonItem(PathItem):
    TYPE = "polygon"
    TITLE = "Полигон"
    CLOSED = True
    MIN_POINTS = 3
    EDIT_VERTICES = True
    DEFAULTS = {"color": "#ff2020", "width": 3.0, "style": "solid", "opacity": 1.0,
                "fill": False, "fill_color": "#ffd800", "fill_opacity": 0.3}
    PROPS = line_props() + fill_props() + [OPACITY]

    def filled_hit(self):
        return bool(self.props.get("fill"))

    def paint(self, painter, option, widget=None):
        if len(self.points) < 2:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint_opacity(painter)
        path = self.outline_path()
        if self.props.get("fill") and len(self.points) > 2:
            painter.fillPath(path, qcolor(self.props["fill_color"], self.props["fill_opacity"]))
        painter.setPen(make_pen(self.props["color"], self.props["width"], self.props["style"]))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def describe(self):
        return f"{self.TITLE} ({len(self.points)} т.)"


class FreehandItem(PathItem):
    """Карандаш. Если отпустить мышь возле начала линии — контур замыкается (можно залить)."""
    TYPE = "freehand"
    TITLE = "Карандаш"
    DEFAULTS = {"color": "#ff2020", "width": 4.0, "opacity": 1.0,
                "fill": False, "fill_color": "#ffd800", "fill_opacity": 0.3}
    PROPS = line_props(with_style=False) + fill_props() + [OPACITY]

    def __init__(self, points=None, props=None):
        super().__init__(points, props)
        self.closed = False

    def geom_to_dict(self, full=False):
        d = super().geom_to_dict(full)
        if self.closed:
            d["closed"] = True
        return d

    def geom_from_dict(self, d):
        super().geom_from_dict(d)
        self.closed = bool(d.get("closed"))

    def handles(self):
        return []

    def handle_kinds(self):
        return []

    def add_point(self, scene_pt: QPointF, min_step: float):
        lp = self.mapFromScene(scene_pt)
        if self.points and math.hypot(*(lp - self.points[-1]).toTuple()) < min_step:
            return
        self.prepareGeometryChange()
        self.points.append(lp)
        self.update()

    def close_contour(self):
        self.prepareGeometryChange()
        self.closed = True
        if len(self.points) > 2:
            self.points[-1] = QPointF(self.points[0])
        self.update()

    def outline_path(self):
        pts = self.points
        path = QPainterPath()
        if not pts:
            return path
        path.moveTo(pts[0])
        if len(pts) < 3:
            for p in pts[1:]:
                path.lineTo(p)
            return path
        for i in range(1, len(pts) - 1):
            path.quadTo(pts[i], mid(pts[i], pts[i + 1]))
        path.lineTo(pts[-1])
        if self.closed:
            path.closeSubpath()
        return path

    def filled_hit(self):
        return self.closed and bool(self.props.get("fill"))

    def snap_points(self):
        if not self.points:
            return []
        return [(self.points[0], "endpoint"), (self.points[-1], "endpoint")]

    def paint(self, painter, option, widget=None):
        if not self.points:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint_opacity(painter)
        if self.closed and self.props.get("fill"):
            painter.fillPath(self.outline_path(), qcolor(self.props["fill_color"], self.props["fill_opacity"]))
        pen = make_pen(self.props["color"], self.props["width"])
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if len(self.points) == 1:
            painter.drawPoint(self.points[0])
        else:
            painter.drawPath(self.outline_path())

    def describe(self):
        return self.TITLE + (" (замкнут)" if self.closed else "")


# =====================================================================
class ArrowItem(BendMixin, PathItem):
    """Инженерная стрелка в стиле FastStone Capture: сужающееся древко + крупный наконечник.
    Ручка в середине позволяет изогнуть стрелку дугой."""
    TYPE = "arrow"
    TITLE = "Стрелка"
    DEFAULTS = {"color": "#ff2020", "width": 7.0, "head": 26.0, "opacity": 1.0,
                "shadow": True, "outline": False, "outline_color": "#ffffff"}
    PROPS = [
        PropSpec("color", "Цвет", "color", "Стрелка"),
        PropSpec("width", "Ширина", "float", "Стрелка", min=1, max=80, step=0.5, suffix=" px"),
        PropSpec("head", "Наконечник", "float", "Стрелка", min=4, max=300, step=1, suffix=" px"),
        PropSpec("shadow", "Тень", "bool", "Стрелка"),
        PropSpec("outline", "Обводка", "bool", "Стрелка"),
        PropSpec("outline_color", "Цвет обводки", "color", "Стрелка"),
        OPACITY,
    ]

    def __init__(self, points=None, props=None):
        super().__init__(points, props)
        self.ctrl = None

    def geom_to_dict(self, full=False):
        return self._bend_geom(super().geom_to_dict(full))

    def geom_from_dict(self, d):
        super().geom_from_dict(d)
        self._bend_from(d)

    def set_drag(self, p0, p1, constrain=False, center=False):
        self.ctrl = None
        super().set_drag(p0, p1, constrain, center)

    def handles(self):
        return self._bend_handles(list(self.points), ["vertex"] * len(self.points))[0]

    def handle_kinds(self):
        return self._bend_handles(list(self.points), ["vertex"] * len(self.points))[1]

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        if self.bend_enabled() and idx == len(self.points):
            self._bend_to(p)
            return
        old = QPointF(self.points[idx]) if 0 <= idx < len(self.points) else None
        super().move_handle(idx, p, constrain, symmetric)
        if old is not None and self.ctrl is not None:
            self.ctrl = self.ctrl + (self.points[idx] - old) * 0.5

    def _dims(self, ln):
        w = float(self.props["width"])
        head = float(self.props["head"])
        hl = min(head, ln * 0.75)
        hw = max(head * 0.5, w * 0.9)
        if hl < head:
            hw *= hl / head
        return w, hl, hw

    def arrow_polygon(self) -> QPolygonF:
        if len(self.points) < 2:
            return QPolygonF()
        tail, tip = self.points[0], self.points[-1]
        if self.ctrl is not None:
            return self._curved_polygon(tail, self.ctrl, tip)
        dx, dy = tip.x() - tail.x(), tip.y() - tail.y()
        ln = math.hypot(dx, dy)
        if ln < 1e-6:
            return QPolygonF()
        ux, uy = dx / ln, dy / ln
        nx, ny = -uy, ux
        w, hl, hw = self._dims(ln)
        base = QPointF(tip.x() - ux * hl, tip.y() - uy * hl)
        tw = max(0.6, w * 0.22)  # хвост тоньше
        bw = w * 0.5

        def P(pt, k):
            return QPointF(pt.x() + nx * k, pt.y() + ny * k)

        # основание наконечника слегка отодвинуто назад — «стреловидная» форма
        back = QPointF(base.x() - ux * hl * 0.12, base.y() - uy * hl * 0.12)
        return QPolygonF([P(tail, tw), P(base, bw), P(back, hw),
                          tip, P(back, -hw), P(base, -bw), P(tail, -tw)])

    def _curved_polygon(self, p0, c, p1) -> QPolygonF:
        total = quad_length(p0, c, p1, 48)
        if total < 1e-6:
            return QPolygonF()
        w, hl, hw = self._dims(total)
        tb = max(0.0, 1.0 - hl / total)          # основание наконечника на кривой
        n = 40
        left, right = [], []
        tw, bw = max(0.6, w * 0.22), w * 0.5
        for i in range(n + 1):
            t = tb * i / n
            q = quad_point(p0, c, p1, t)
            # касательная
            dx = 2 * (1 - t) * (c.x() - p0.x()) + 2 * t * (p1.x() - c.x())
            dy = 2 * (1 - t) * (c.y() - p0.y()) + 2 * t * (p1.y() - c.y())
            ln = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / ln, dx / ln
            k = tw + (bw - tw) * (i / n)
            left.append(QPointF(q.x() + nx * k, q.y() + ny * k))
            right.append(QPointF(q.x() - nx * k, q.y() - ny * k))
        base = quad_point(p0, c, p1, tb)
        dx, dy = p1.x() - base.x(), p1.y() - base.y()
        ln = math.hypot(dx, dy) or 1.0
        ux, uy = dx / ln, dy / ln
        nx, ny = -uy, ux
        back = QPointF(base.x() - ux * hl * 0.12, base.y() - uy * hl * 0.12)
        head = [QPointF(back.x() + nx * hw, back.y() + ny * hw), QPointF(p1),
                QPointF(back.x() - nx * hw, back.y() - ny * hw)]
        return QPolygonF(left + head + list(reversed(right)))

    def outline_path(self):
        path = QPainterPath()
        poly = self.arrow_polygon()
        if poly.isEmpty():
            if self.points:
                path.moveTo(self.points[0])
                for p in self.points[1:]:
                    path.lineTo(p)
            return path
        path.addPolygon(poly)
        path.closeSubpath()
        return path

    def filled_hit(self):
        return True

    def hit_width(self):
        return 2.0

    def margin(self):
        return float(self.props.get("head", 20)) * 0.6 + 10

    def snap_points(self):
        if len(self.points) < 2:
            return []
        return [(self.points[0], "endpoint"), (self.points[-1], "endpoint"), (self.curve_mid(), "midpoint")]

    def paint(self, painter, option, widget=None):
        poly = self.arrow_polygon()
        if poly.isEmpty():
            return
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint_opacity(painter)
        if self.props.get("shadow"):
            off = max(2.0, float(self.props["width"]) * 0.35)
            painter.save()
            painter.translate(off, off)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(0, 0, 0, 90))
            painter.drawPolygon(poly)
            painter.restore()
        if self.props.get("outline"):
            pen = make_pen(self.props.get("outline_color", "#ffffff"), max(1.5, float(self.props["width"]) * 0.3))
        else:
            pen = Qt.NoPen
        painter.setPen(pen)
        painter.setBrush(QColor(self.props["color"]))
        painter.drawPolygon(poly)

    def describe(self):
        return self.TITLE + (" (дуга)" if self.ctrl is not None else "")


# =====================================================================
class BreakItem(PathItem):
    """«Разрыв цепи»: две параллельные черты поперёк линии. Ось задаётся двумя точками
    (направление и длина черт), «Зазор» — расстояние между чертами. Можно залить зазор,
    чтобы «стереть» линию под разрывом."""
    TYPE = "break"
    TITLE = "Разрыв"
    DEFAULTS = {"color": "#ff2020", "width": 3.0, "gap": 10.0, "opacity": 1.0,
                "fill_gap": False, "fill_color": "#ffffff"}
    PROPS = [
        PropSpec("color", "Цвет", "color", "Разрыв"),
        PropSpec("width", "Толщина", "float", "Разрыв", min=0.5, max=60, step=0.5, suffix=" px"),
        PropSpec("gap", "Зазор", "float", "Разрыв", min=1, max=400, step=1, suffix=" px"),
        PropSpec("fill_gap", "Залить зазор", "bool", "Разрыв"),
        PropSpec("fill_color", "Цвет заливки", "color", "Разрыв"),
        OPACITY,
    ]

    def marks(self):
        if len(self.points) < 2:
            return None
        a, b = self.points[0], self.points[-1]
        dx, dy = b.x() - a.x(), b.y() - a.y()
        ln = math.hypot(dx, dy)
        if ln < 1e-6:
            return None
        nx, ny = -dy / ln, dx / ln
        g = float(self.props.get("gap", 10)) / 2
        o = QPointF(nx * g, ny * g)
        return (a + o, b + o), (a - o, b - o)

    def outline_path(self):
        path = QPainterPath()
        m = self.marks()
        if m is None:
            if self.points:
                path.moveTo(self.points[0])
            return path
        (a1, b1), (a2, b2) = m
        path.addPolygon(QPolygonF([a1, b1, b2, a2]))
        path.closeSubpath()
        return path

    def filled_hit(self):
        return True

    def margin(self):
        return float(self.props.get("width", 3)) * 2 + float(self.props.get("gap", 10)) + 4

    # ручки: концы оси + маркер зазора (середина одной из черт)
    def handles(self):
        m = self.marks()
        if m is None:
            return list(self.points)
        (a1, b1), (a2, b2) = m
        m1, m2 = mid(a1, b1), mid(a2, b2)
        # маркер — на черте, которая правее на экране (при равенстве — ниже)
        s1, s2 = self.mapToScene(m1), self.mapToScene(m2)
        right = m2 if (s2.x(), s2.y()) > (s1.x(), s1.y()) else m1
        return [QPointF(self.points[0]), QPointF(self.points[-1]), right]

    def handle_kinds(self):
        return ["vertex", "vertex", "gap"][:len(self.handles())]

    def handle_cursor(self, idx):
        return Qt.SizeAllCursor if idx == 2 else Qt.CrossCursor

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        if idx < 2:
            return super().move_handle(idx, p, constrain, symmetric)
        a, b = self.points[0], self.points[-1]
        dx, dy = b.x() - a.x(), b.y() - a.y()
        ln = math.hypot(dx, dy)
        if ln < 1e-6:
            return
        nx, ny = -dy / ln, dx / ln
        c = mid(a, b)
        d = abs((p.x() - c.x()) * nx + (p.y() - c.y()) * ny)
        self.set_prop("gap", round(max(1.0, 2 * d), 1))

    def snap_points(self):
        m = self.marks()
        if m is None:
            return []
        (a1, b1), (a2, b2) = m
        return [(a1, "endpoint"), (b1, "endpoint"), (a2, "endpoint"), (b2, "endpoint"),
                (mid(self.points[0], self.points[-1]), "center")]

    def paint(self, painter, option, widget=None):
        m = self.marks()
        if m is None:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint_opacity(painter)
        (a1, b1), (a2, b2) = m
        if self.props.get("fill_gap"):
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(self.props.get("fill_color", "#ffffff")))
            painter.drawPolygon(QPolygonF([a1, b1, b2, a2]))
        pen = make_pen(self.props["color"], self.props["width"])
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.drawLine(a1, b1)
        painter.drawLine(a2, b2)


# =====================================================================
class BoxItem(AnnotationItem):
    """Объект, заданный прямоугольником (локальные координаты).

    ROTATABLE — у объекта есть свойство «angle» и ручка поворота над верхней стороной.
    Поворот выполняется вокруг центра прямоугольника.
    """
    HANDLE_IDS = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
    ROTATABLE = False
    CREATE_FROM_CENTER = False
    ROT_HANDLE_PX = 26

    def __init__(self, rect: QRectF | None = None, props=None):
        super().__init__(props)
        self.rect = QRectF(rect) if rect else QRectF(0, 0, 0, 0)
        self._drag_rect = None
        self._drag_anchor = None

    def geom_to_dict(self, full=False):
        r = self.rect
        return {"rect": [round(r.x(), 3), round(r.y(), 3), round(r.width(), 3), round(r.height(), 3)]}

    def geom_from_dict(self, d):
        x, y, w, h = d.get("rect", [0, 0, 0, 0])
        self.rect = QRectF(float(x), float(y), float(w), float(h))

    # --------------------------------------------------------- rotation
    def angle(self) -> float:
        return float(self.props.get("angle", 0) or 0) if self.ROTATABLE else 0.0

    def apply_rotation(self):
        """Повернуть вокруг центра, сохранив положение центра на сцене."""
        if not self.ROTATABLE:
            return
        c_local = self.rect.center()
        before = self.mapToScene(c_local)
        self.setTransformOriginPoint(c_local)
        self.setRotation(self.angle())
        after = self.mapToScene(c_local)
        if before != after:
            self.setPos(self.pos() + (before - after))

    def props_changed(self):
        self.apply_rotation()

    def apply_dict(self, d, keep_id=True):
        super().apply_dict(d, keep_id)
        if self.ROTATABLE:
            # сохранённая позиция соответствует origin = центр и текущему углу
            self.setTransformOriginPoint(self.rect.center())
            self.setRotation(self.angle())
            pos = d.get("pos", [0, 0])
            self.setPos(float(pos[0]), float(pos[1]))

    # --------------------------------------------------------- creation
    def set_drag(self, p0, p1, constrain=False, center=False):
        """Создание перетаскиванием. center=True — от центра (p0 — центр)."""
        self.prepareGeometryChange()
        from_center = self.CREATE_FROM_CENTER != bool(center)
        if from_center:
            dx, dy = abs(p1.x() - p0.x()), abs(p1.y() - p0.y())
            if constrain:
                dx = dy = max(dx, dy)
            r = QRectF(p0.x() - dx, p0.y() - dy, 2 * dx, 2 * dy)
        else:
            r = square_rect(p0, p1) if constrain else QRectF(p0, p1).normalized()
        self.setRotation(0)
        self.setTransformOriginPoint(QPointF(0, 0))
        self.setPos(r.topLeft())
        self.rect = QRectF(0, 0, r.width(), r.height())
        self.apply_rotation()
        self.update()

    # --------------------------------------------------------- handles
    def handle_points(self, r: QRectF):
        c = r.center()
        return [r.topLeft(), QPointF(c.x(), r.top()), r.topRight(), QPointF(r.right(), c.y()),
                r.bottomRight(), QPointF(c.x(), r.bottom()), r.bottomLeft(), QPointF(r.left(), c.y())]

    def rot_handle_point(self):
        r = self.rect
        return QPointF(r.center().x(), r.top() - self.ROT_HANDLE_PX / _view_scale())

    def handles(self):
        hs = self.handle_points(self.rect)
        if self.ROTATABLE:
            hs.append(self.rot_handle_point())
        return hs

    def handle_kinds(self):
        return ["box"] * len(self.HANDLE_IDS) + (["rot"] if self.ROTATABLE else [])

    def handle_cursor(self, idx):
        if idx >= len(self.HANDLE_IDS):
            return Qt.PointingHandCursor
        hid = self.HANDLE_IDS[idx]
        diag = {"tl": 135, "br": 135, "tr": 45, "bl": 45, "t": 90, "b": 90, "l": 0, "r": 0}[hid]
        a = (diag - self.angle()) % 180
        if a < 22.5 or a >= 157.5:
            return Qt.SizeHorCursor
        if a < 67.5:
            return Qt.SizeBDiagCursor
        if a < 112.5:
            return Qt.SizeVerCursor
        return Qt.SizeFDiagCursor

    def _fixed_point(self, r0: QRectF, hid: str, symmetric: bool) -> QPointF:
        if symmetric:
            return r0.center()
        x = r0.center().x() if hid in ("t", "b") else (r0.right() if "l" in hid else r0.left())
        y = r0.center().y() if hid in ("l", "r") else (r0.bottom() if "t" in hid else r0.top())
        return QPointF(x, y)

    def begin_handle_drag(self, idx):
        self._drag_rect = QRectF(self.rect)
        self._drag_anchor = None
        return None

    def _resize_from(self, r0: QRectF, hid: str, p: QPointF, constrain: bool, keep_aspect: bool,
                     symmetric: bool = False):
        if symmetric:
            c = r0.center()
            hw, hh = r0.width() / 2, r0.height() / 2
            if "l" in hid or "r" in hid:
                hw = abs(p.x() - c.x())
            if "t" in hid or "b" in hid:
                hh = abs(p.y() - c.y())
            if len(hid) == 2 and (keep_aspect or constrain) and r0.width() > 0 and r0.height() > 0:
                ratio = 1.0 if constrain and not keep_aspect else r0.width() / r0.height()
                if hw / max(hh, 1e-6) > ratio:
                    hh = hw / ratio
                else:
                    hw = hh * ratio
            return QRectF(c.x() - hw, c.y() - hh, 2 * hw, 2 * hh)
        left, top, right, bottom = r0.left(), r0.top(), r0.right(), r0.bottom()
        if "l" in hid:
            left = p.x()
        if "r" in hid:
            right = p.x()
        if "t" in hid:
            top = p.y()
        if "b" in hid:
            bottom = p.y()
        if keep_aspect and len(hid) == 2 and r0.width() > 0 and r0.height() > 0:
            ax = r0.right() if "l" in hid else r0.left()
            ay = r0.bottom() if "t" in hid else r0.top()
            w, h = abs(p.x() - ax), abs(p.y() - ay)
            ratio = r0.width() / r0.height()
            if w / max(h, 1e-6) > ratio:
                h = w / ratio
            else:
                w = h * ratio
            sx = -1 if p.x() < ax else 1
            sy = -1 if p.y() < ay else 1
            return QRectF(QPointF(ax, ay), QPointF(ax + sx * w, ay + sy * h)).normalized()
        if constrain and len(hid) == 2:
            ax = r0.right() if "l" in hid else r0.left()
            ay = r0.bottom() if "t" in hid else r0.top()
            return square_rect(QPointF(ax, ay), p)
        return QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()

    def _apply_rect(self, new_rect: QRectF, fixed_local: QPointF, fixed_scene: QPointF):
        """Установить прямоугольник так, чтобы неподвижная точка осталась на месте (с учётом поворота)."""
        self.prepareGeometryChange()
        self.rect = new_rect
        if self.ROTATABLE:
            self.setTransformOriginPoint(new_rect.center())
            self.setRotation(self.angle())
            now = self.mapToScene(fixed_local)
            self.setPos(self.pos() + (fixed_scene - now))
        self.update()

    def _rotate_to(self, p_local: QPointF, constrain: bool):
        c = self.mapToScene(self.rect.center())
        ps = self.mapToScene(p_local)
        a = math.degrees(math.atan2(ps.y() - c.y(), ps.x() - c.x())) + 90.0
        if constrain:
            a = round(a / 15.0) * 15.0
        a = (a + 180.0) % 360.0 - 180.0
        self.prepareGeometryChange()
        self.props["angle"] = round(a, 2)
        self.apply_rotation()
        self.update()

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        if idx >= len(self.HANDLE_IDS):
            self._rotate_to(p, constrain)
            return
        r0 = self._drag_rect or self.rect
        hid = self.HANDLE_IDS[idx]
        fixed_local = self._fixed_point(r0, hid, symmetric)
        if self._drag_anchor is None or self._drag_anchor[0] != (hid, symmetric):
            self._drag_anchor = ((hid, symmetric), self.mapToScene(fixed_local))
        new = self._resize_from(r0, hid, p, constrain, keep_aspect=False, symmetric=symmetric)
        self._apply_rect(new, fixed_local, self._drag_anchor[1])

    def outline_path(self):
        path = QPainterPath()
        path.addRect(self.rect)
        return path

    def snap_points(self):
        return rect_snap_points(self.rect)

    def describe(self):
        a = self.angle()
        return f"{self.TITLE} {self.rect.width():.0f}×{self.rect.height():.0f}" + (f", {a:g}°" if a else "")


def _view_scale():
    from . import base
    return base.VIEW_SCALE


ANGLE = PropSpec("angle", "Угол поворота", "float", "Геометрия", min=-180, max=180, step=1, suffix="°")


class RectItem(BoxItem):
    TYPE = "rect"
    TITLE = "Прямоугольник"
    ROTATABLE = True
    DEFAULTS = {"color": "#ff2020", "width": 3.0, "style": "solid", "opacity": 1.0,
                "fill": False, "fill_color": "#ffd800", "fill_opacity": 0.3, "radius": 0, "angle": 0.0}
    PROPS = line_props() + [PropSpec("radius", "Скругление", "int", "Линия", min=0, max=500, suffix=" px")] \
        + fill_props() + [ANGLE, OPACITY]

    def outline_path(self):
        path = QPainterPath()
        rad = float(self.props.get("radius", 0) or 0)
        if rad > 0:
            path.addRoundedRect(self.rect, rad, rad)
        else:
            path.addRect(self.rect)
        return path

    def filled_hit(self):
        return bool(self.props.get("fill"))

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint_opacity(painter)
        path = self.outline_path()
        if self.props.get("fill"):
            painter.fillPath(path, qcolor(self.props["fill_color"], self.props["fill_opacity"]))
        if float(self.props["width"]) > 0:
            pen = make_pen(self.props["color"], self.props["width"], self.props["style"])
            pen.setJoinStyle(Qt.MiterJoin if not self.props.get("radius") else Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)


class EllipseItem(RectItem):
    TYPE = "ellipse"
    TITLE = "Эллипс"
    CREATE_FROM_CENTER = True
    DEFAULTS = {"color": "#ff2020", "width": 3.0, "style": "solid", "opacity": 1.0,
                "fill": False, "fill_color": "#ffd800", "fill_opacity": 0.3, "angle": 0.0}
    PROPS = line_props() + fill_props() + [ANGLE, OPACITY]

    def outline_path(self):
        path = QPainterPath()
        path.addEllipse(self.rect)
        return path

    def snap_points(self):
        r = self.rect
        c = r.center()
        return [(c, "center"),
                (QPointF(c.x(), r.top()), "edge"), (QPointF(r.right(), c.y()), "edge"),
                (QPointF(c.x(), r.bottom()), "edge"), (QPointF(r.left(), c.y()), "edge")]
