"""Размер (расстояние): две стрелки друг против друга между точками A и B, выносные линии и
надпись со значением. Маркер надписи можно тянуть: вдоль — положение текста, поперёк —
отступ размерной линии от измеряемых точек."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QTransform

from ..geometry import constrain_angle, mid
from ..props import OPACITY, PropSpec
from .base import AnnotationItem, cap_dims, draw_line_with_caps, make_pen, qcolor

ARROWS = [("out", "Наружу  ←→"), ("in", "Внутрь  →←")]
LABEL_SIDES = [("normal", "Над линией / справа"), ("flip", "Под линией / слева")]
S_DIM = "Размер"
S_LBL = "Надпись"


class DimensionItem(AnnotationItem):
    TYPE = "dimension"
    TITLE = "Размер"
    DEFAULTS = {"color": "#ff2020", "width": 2.0, "arrow_size": 14.0, "arrows": "out", "opacity": 1.0,
                "size": 20, "text": "", "unit": "мм", "scale": 1.0, "decimals": 0,
                "bg": True, "bg_color": "#ffffff", "text_color": "#ff2020", "label_side": "normal"}
    PROPS = [
        PropSpec("color", "Цвет линий", "color", S_DIM),
        PropSpec("width", "Толщина", "float", S_DIM, min=0.5, max=40, step=0.5, suffix=" px"),
        PropSpec("arrows", "Стрелки", "enum", S_DIM, options=ARROWS,
                 pair=PropSpec("arrow_size", "Размер", "float", min=1, max=300, step=1, suffix=" px")),
        PropSpec("text", "Свой текст", "text", S_LBL),
        PropSpec("label_side", "Надпись", "enum", S_LBL, options=LABEL_SIDES),
        PropSpec("unit", "Единицы", "enum", S_LBL, options=[("px", "px"), ("мм", "мм"), ("см", "см"),
                                                            ("м", "м"), ("in", "in"), ("", "без единиц")]),
        PropSpec("scale", "Единиц в 1 px", "float", S_LBL, min=0.0001, max=100000, step=0.01),
        PropSpec("decimals", "Знаков после ,", "int", S_LBL, min=0, max=4),
        PropSpec("size", "Размер текста", "int", S_LBL, min=4, max=400, suffix=" px"),
        PropSpec("text_color", "Цвет текста", "color", S_LBL),
        PropSpec("bg", "Подложка", "bool", S_LBL),
        PropSpec("bg_color", "Цвет подложки", "color", S_LBL),
        OPACITY,
    ]

    def __init__(self, props=None):
        super().__init__(props)
        self.a = QPointF(0, 0)
        self.b = QPointF(0, 0)
        self.offset = 0.0     # отступ размерной линии (перпендикулярно AB)
        self.t = 0.5          # положение надписи вдоль линии (0 — у A, 1 — у B)

    # ------------------------------------------------------------------ serialization
    def geom_to_dict(self, full=False):
        return {"a": [round(self.a.x(), 3), round(self.a.y(), 3)], "b": [round(self.b.x(), 3), round(self.b.y(), 3)],
                "offset": round(self.offset, 3), "t": round(self.t, 4)}

    def geom_from_dict(self, d):
        self.a = QPointF(*map(float, d.get("a", [0, 0])))
        self.b = QPointF(*map(float, d.get("b", [0, 0])))
        self.offset = float(d.get("offset", 0))
        self.t = float(d.get("t", 0.5))

    def rotate_geometry(self, f):
        self.prepareGeometryChange()
        self.a, self.b = f(self.a), f(self.b)
        return True

    # ------------------------------------------------------------------ geometry
    def set_drag(self, p0, p1, constrain=False, center=False):
        self.prepareGeometryChange()
        if constrain:
            p1 = constrain_angle(p0, p1)
        self.setPos(p0)
        self.a = QPointF(0, 0)
        self.b = p1 - p0
        self.t = 0.5
        self.update()

    def frame(self):
        d = self.b - self.a
        ln = math.hypot(d.x(), d.y())
        if ln < 1e-6:
            return None
        u = QPointF(d.x() / ln, d.y() / ln)
        n = QPointF(-u.y(), u.x())
        return ln, u, n

    def dim_points(self):
        f = self.frame()
        if f is None:
            return QPointF(self.a), QPointF(self.b)
        _, _, n = f
        return self.a + n * self.offset, self.b + n * self.offset

    def label_point(self):
        f = self.frame()
        a2, b2 = self.dim_points()
        if f is None:
            return a2
        ln, u, _ = f
        return a2 + u * (ln * self.t)

    def value_text(self):
        if (self.props.get("text") or "").strip():
            return self.props["text"]
        f = self.frame()
        ln = f[0] if f else 0.0
        v = ln * float(self.props.get("scale", 1.0) or 1.0)
        dec = int(self.props.get("decimals", 0))
        txt = f"{v:.{dec}f}".replace(".", ",")
        unit = self.props.get("unit", "мм")
        return f"{txt} {unit}".strip()

    def font(self):
        f = QFont("Segoe UI")
        f.setPixelSize(max(4, int(self.props.get("size", 20))))
        f.setBold(True)
        return f

    def label_geometry(self):
        """(центр надписи, угол в градусах, прямоугольник текста в локальных координатах надписи)."""
        f = self.frame()
        p = self.label_point()
        ang = 0.0
        n = QPointF(0, -1)
        if f is not None:
            _, u, n = f
            ang = math.degrees(math.atan2(u.y(), u.x()))
            if ang > 90 or ang <= -90:   # текст не вверх ногами
                ang += 180
                n = QPointF(-n.x(), -n.y())
            # надпись над линией (по «экранному» верху для повёрнутой системы)
            up = QPointF(math.sin(math.radians(ang)), -math.cos(math.radians(ang)))
            n = up
            if self.props.get("label_side") == "flip":
                # с другой стороны: под линией; у почти вертикальной — слева, читается снизу вверх
                # (верх букв — от линии, как на чертежах)
                n = QPointF(-n.x(), -n.y())
                if abs(ang) > 80:
                    ang -= 180
        fm = QFontMetricsF(self.font())
        txt = self.value_text()
        w = fm.horizontalAdvance(txt) + 8
        h = fm.height() + 2
        gap = float(self.props.get("width", 2)) + 2
        c = p + n * (h / 2 + gap)
        return c, ang, QRectF(-w / 2, -h / 2, w, h)

    def label_polygon(self):
        c, ang, r = self.label_geometry()
        t = QTransform()
        t.translate(c.x(), c.y())
        t.rotate(ang)
        return t.map(_rect_poly(r))

    def _lines_path(self):
        path = QPainterPath()
        f = self.frame()
        a2, b2 = self.dim_points()
        path.moveTo(a2)
        path.lineTo(b2)
        if f is not None and abs(self.offset) > 0.5:
            _, _, n = f
            s = 1 if self.offset > 0 else -1
            ext = n * (s * (float(self.props.get("width", 2)) * 2 + 6))
            for p, q in ((self.a, a2), (self.b, b2)):
                path.moveTo(p + n * (s * 3))
                path.lineTo(q + ext)
        lp = self.label_point()
        if self.t < 0:
            path.moveTo(a2)
            path.lineTo(lp)
        elif self.t > 1:
            path.moveTo(b2)
            path.lineTo(lp)
        return path

    def outline_path(self):
        path = self._lines_path()
        path.addPolygon(self.label_polygon())
        path.closeSubpath()
        return path

    def hit(self, scene_pt, tol):
        p = self.mapFromScene(scene_pt)
        if self.label_polygon().containsPoint(p, Qt.OddEvenFill):
            return True
        st = QPainterPathStroker()
        st.setWidth(float(self.props.get("width", 2)) + 2 * tol)
        return st.createStroke(self._lines_path()).contains(p)

    def margin(self):
        hl, _ = cap_dims(float(self.props.get("width", 2)), float(self.props.get("arrow_size") or 14))
        return hl * 3.4 + float(self.props.get("width", 2)) * 2 + 6

    def handles(self):
        return [QPointF(self.a), QPointF(self.b), self.label_point()]

    def handle_kinds(self):
        return ["vertex", "vertex", "label"]

    def handle_cursor(self, idx):
        return Qt.CrossCursor if idx < 2 else Qt.SizeAllCursor

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        self.prepareGeometryChange()
        if idx == 0:
            self.a = constrain_angle(self.b, p) if constrain else QPointF(p)
        elif idx == 1:
            self.b = constrain_angle(self.a, p) if constrain else QPointF(p)
        else:
            f = self.frame()
            if f is not None:
                ln, u, n = f
                rel = p - self.a
                t = (rel.x() * u.x() + rel.y() * u.y()) / ln
                if abs(t - 0.5) < 0.03:
                    t = 0.5
                self.t = t  # без ограничений: надпись можно отвести сколь угодно далеко
                self.offset = 0.0 if constrain else rel.x() * n.x() + rel.y() * n.y()
        self.update()

    # приклеивание: «a», «b» — измеряемые точки
    def glue_ends(self):
        return {"a": QPointF(self.a), "b": QPointF(self.b)}

    def set_glue_end(self, key, p):
        self.prepareGeometryChange()
        if key == "a":
            self.a = QPointF(p)
        elif key == "b":
            self.b = QPointF(p)
        self.update()

    def flip_label(self):
        """Надпись — на другую сторону размерной линии."""
        self.set_prop("label_side", "normal" if self.props.get("label_side") == "flip" else "flip")

    def handle_glue_key(self, idx):
        return {0: "a", 1: "b"}.get(idx)

    def handle_anchor(self, idx):
        return {0: QPointF(self.b), 1: QPointF(self.a)}.get(idx)

    def creation_glue_keys(self):
        return ("a", "b")

    def snap_points(self):
        a2, b2 = self.dim_points()
        out = [(QPointF(self.a), "endpoint"), (QPointF(self.b), "endpoint"), (mid(a2, b2), "midpoint")]
        if abs(self.offset) > 0.5:
            out += [(a2, "vertex"), (b2, "vertex")]
        return out

    # ------------------------------------------------------------------ paint
    def paint(self, painter, option, widget=None):
        f = self.frame()
        if f is None:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        self.paint_opacity(painter)
        col = self.props["color"]
        w = float(self.props.get("width", 2))
        a2, b2 = self.dim_points()
        _, _, n = f
        # выносные линии
        if abs(self.offset) > 0.5:
            s = 1 if self.offset > 0 else -1
            ext = n * (s * (w * 2 + 6))
            painter.setPen(make_pen(col, max(0.5, w * 0.7)))
            for p, q in ((self.a, a2), (self.b, b2)):
                painter.drawLine(p + n * (s * 3), q + ext)
        size = float(self.props.get("arrow_size") or 14)
        if self.props.get("arrows", "out") == "in":
            # стрелки снаружи, острия смотрят на выносные линии: →|  |←
            u = f[1]
            hl, _ = cap_dims(w, size)
            ext = hl * 2.2
            painter.setPen(make_pen(col, w))
            painter.drawLine(a2, b2)
            draw_line_with_caps(painter, [a2 - u * ext, a2], col, w, "solid", "none", "arrow", end_size=size)
            draw_line_with_caps(painter, [b2 + u * ext, b2], col, w, "solid", "none", "arrow", end_size=size)
        else:
            # острия на концах размерной линии: |←  →|
            draw_line_with_caps(painter, [a2, b2], col, w, "solid", "arrow", "arrow", start_size=size, end_size=size)
        lp = self.label_point()
        if self.t < 0 or self.t > 1:
            painter.setPen(make_pen(col, w))
            painter.drawLine(a2 if self.t < 0 else b2, lp)
        # надпись
        c, ang, r = self.label_geometry()
        painter.save()
        painter.translate(c)
        painter.rotate(ang)
        if self.props.get("bg"):
            painter.setPen(Qt.NoPen)
            painter.setBrush(qcolor(self.props.get("bg_color", "#ffffff"), 0.85))
            painter.drawRoundedRect(r, 3, 3)
        painter.setFont(self.font())
        painter.setPen(QColor(self.props.get("text_color", col)))
        painter.drawText(r, int(Qt.AlignCenter), self.value_text())
        painter.restore()

    def describe(self):
        return f"{self.TITLE}: {self.value_text()}"


def _rect_poly(r: QRectF):
    from PySide6.QtGui import QPolygonF
    return QPolygonF([r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()])
