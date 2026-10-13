"""Текст, выноска (Callout) и нумерованный маркер."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from ..geometry import dist, rect_snap_points
from ..props import CAP_STYLES, OPACITY, S_LEADER, PropSpec, cap_size, text_props
from .base import AnnotationItem, draw_line_with_caps, make_pen, qcolor

DEFAULT_FONT = "Segoe UI"

ALIGN_FLAGS = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}


def make_font(props) -> QFont:
    f = QFont(props.get("font") or DEFAULT_FONT)
    f.setPixelSize(max(1, int(props.get("size", 20))))
    f.setBold(bool(props.get("bold")))
    f.setItalic(bool(props.get("italic")))
    return f


VALIGN_FLAGS = {"top": Qt.AlignTop, "middle": Qt.AlignVCenter, "bottom": Qt.AlignBottom}


def layout_text(props, fixed=None):
    """Возвращает (box, text_rect, flags, font) в локальных координатах (box начинается в 0,0).
    fixed=(w, h) — размер блока задан пользователем (текст переносится по словам)."""
    font = make_font(props)
    fm = QFontMetricsF(font)
    text = props.get("text", "") or " "
    pad = float(props.get("padding", 4))
    flags = (ALIGN_FLAGS.get(props.get("align", "left"), Qt.AlignLeft)
             | VALIGN_FLAGS.get(props.get("valign", "top"), Qt.AlignTop) | Qt.TextExpandTabs)
    if fixed is not None:
        box = QRectF(0, 0, max(4.0, fixed[0]), max(4.0, fixed[1]))
        return box, box.adjusted(pad, pad, -pad, -pad), flags | Qt.TextWordWrap, font
    br = fm.boundingRect(QRectF(0, 0, 1e6, 1e6), int(Qt.AlignLeft | Qt.AlignTop | Qt.TextExpandTabs), text)
    w = br.width() + (fm.averageCharWidth() * 0.3 if props.get("italic") else 0) + 1
    h = max(br.height(), fm.height())
    box = QRectF(0, 0, w + 2 * pad, h + 2 * pad)
    return box, box.adjusted(pad, pad, -pad, -pad), flags, font


def paint_text_box(painter: QPainter, props, box, trect, flags, font, border_color=None, border_w=0.0):
    if props.get("bg"):
        painter.setPen(Qt.NoPen)
        painter.setBrush(qcolor(props.get("bg_color", "#ffffff"), props.get("bg_opacity", 0.8)))
        painter.drawRoundedRect(box, 3, 3)
    if border_color and border_w > 0:
        painter.setPen(make_pen(border_color, border_w))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(box, 3, 3)
    painter.setFont(font)
    painter.setPen(QColor(props.get("color", "#000000")))
    painter.drawText(trect, int(flags), props.get("text", ""))


# =====================================================================
class TextItem(AnnotationItem):
    """Текст. pos() — левый верхний угол блока; поворот — вокруг центра блока.
    Размер блока — автоматически по тексту или задан вручную (ручки по краям рамки)."""
    HANDLE_IDS = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
    TYPE = "text"
    TITLE = "Текст"
    ROT_HANDLE_PX = 26
    DEFAULTS = {"text": "ТЕКСТ", "font": DEFAULT_FONT, "size": 24, "bold": True, "italic": False,
                "color": "#ff2020", "align": "center", "valign": "middle", "bg": True, "bg_color": "#ffffff",
                "bg_opacity": 0.8, "padding": 4, "border": False, "border_color": "#ff2020",
                "border_width": 2.0, "angle": 0.0, "auto_size": True, "box_w": 0.0, "box_h": 0.0,
                "opacity": 1.0}
    PROPS = text_props(valign=True) + [
        PropSpec("auto_size", "Размер по тексту", "bool", "Рамка"),
        PropSpec("border", "Рамка", "bool", "Рамка"),
        PropSpec("border_color", "Цвет рамки", "color", "Рамка"),
        PropSpec("border_width", "Толщина рамки", "float", "Рамка", min=0.5, max=50, step=0.5, suffix=" px"),
        PropSpec("angle", "Угол поворота", "float", "Геометрия", min=-180, max=180, step=1, suffix="°"),
        OPACITY,
    ]

    def __init__(self, props=None):
        super().__init__(props)
        self._layout = None
        self._drag = None

    # --------------------------------------------------------- rotation
    def angle(self):
        return float(self.props.get("angle", 0) or 0)

    def rotation_pivot(self):
        return self.box().center()

    def apply_rotation(self):
        """Повернуть вокруг центра блока, сохранив положение центра на сцене."""
        c = self.box().center()
        before = self.mapToScene(c)
        self.setTransformOriginPoint(c)
        self.setRotation(self.angle())
        after = self.mapToScene(c)
        if before != after:
            self.setPos(self.pos() + (before - after))

    def props_changed(self):
        self._layout = None
        self.apply_rotation()

    def apply_dict(self, d, keep_id=True):
        super().apply_dict(d, keep_id)
        self._layout = None
        self.setTransformOriginPoint(self.box().center())
        self.setRotation(self.angle())
        pos = d.get("pos", [0, 0])
        self.setPos(float(pos[0]), float(pos[1]))

    def fixed_size(self):
        p = self.props
        if p.get("auto_size", True) or not p.get("box_w") or not p.get("box_h"):
            return None
        return float(p["box_w"]), float(p["box_h"])

    def layout(self):
        if self._layout is None:
            self._layout = layout_text(self.props, self.fixed_size())
        return self._layout

    def box(self) -> QRectF:
        return self.layout()[0]

    def outline_path(self):
        p = QPainterPath()
        p.addRect(self.box())
        return p

    def filled_hit(self):
        return True

    def hit_width(self):
        return 1.0

    def margin(self):
        return 4 + (float(self.props.get("border_width", 2)) if self.props.get("border") else 0)

    def handles(self):
        from . import base
        b = self.box()
        c = b.center()
        hs = [b.topLeft(), QPointF(c.x(), b.top()), b.topRight(), QPointF(b.right(), c.y()),
              b.bottomRight(), QPointF(c.x(), b.bottom()), b.bottomLeft(), QPointF(b.left(), c.y())]
        hs.append(QPointF(c.x(), b.top() - self.ROT_HANDLE_PX / base.VIEW_SCALE))
        return hs

    def handle_kinds(self):
        return ["box"] * 8 + ["rot"]

    def handle_cursor(self, idx):
        if idx == 8:
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

    def begin_handle_drag(self, idx):
        self._drag = QRectF(self.box())
        self._drag_anchor = None
        # система координат на момент начала перетаскивания: во время перетаскивания pos()
        # смещается, поэтому точку мыши пересчитываем в исходную систему
        self._drag_tf = self.sceneTransform()
        self._drag_inv = self._drag_tf.inverted()[0]
        return None

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        if idx == 8:
            # поворот: угол от центра блока к курсору (Shift — шаг 15°)
            c = self.mapToScene(self.box().center())
            ps = self.mapToScene(p)
            a = math.degrees(math.atan2(ps.y() - c.y(), ps.x() - c.x())) + 90.0
            if constrain:
                a = round(a / 15.0) * 15.0
            a = (a + 180.0) % 360.0 - 180.0
            self.set_prop("angle", round(a, 2))
            return
        # ручки рамки — свободно меняем ширину/высоту блока (Alt — от центра)
        r0 = self._drag if isinstance(self._drag, QRectF) else QRectF(self.box())
        if getattr(self, "_drag_inv", None) is not None:
            p = self._drag_inv.map(self.mapToScene(p))
        hid = self.HANDLE_IDS[idx]
        if symmetric:
            fixed_local = r0.center()
        else:
            fx = r0.center().x() if hid in ("t", "b") else (r0.right() if "l" in hid else r0.left())
            fy = r0.center().y() if hid in ("l", "r") else (r0.bottom() if "t" in hid else r0.top())
            fixed_local = QPointF(fx, fy)
        if getattr(self, "_drag_anchor", None) is None or self._drag_anchor[0] != (hid, symmetric):
            tf = getattr(self, "_drag_tf", None)
            self._drag_anchor = ((hid, symmetric), tf.map(fixed_local) if tf is not None else self.mapToScene(fixed_local))
        fixed_scene = self._drag_anchor[1]
        if symmetric:
            c = r0.center()
            hw, hh = r0.width() / 2, r0.height() / 2
            if "l" in hid or "r" in hid:
                hw = abs(p.x() - c.x())
            if "t" in hid or "b" in hid:
                hh = abs(p.y() - c.y())
            new = QRectF(c.x() - hw, c.y() - hh, 2 * hw, 2 * hh)
        else:
            l, t_, r, b = r0.left(), r0.top(), r0.right(), r0.bottom()
            if "l" in hid:
                l = p.x()
            if "r" in hid:
                r = p.x()
            if "t" in hid:
                t_ = p.y()
            if "b" in hid:
                b = p.y()
            new = QRectF(QPointF(l, t_), QPointF(r, b)).normalized()
        w, h = max(10.0, new.width()), max(10.0, new.height())
        self.prepareGeometryChange()
        self.props["auto_size"] = False
        self.props["box_w"] = round(w, 2)
        self.props["box_h"] = round(h, 2)
        self._layout = None
        # неподвижная точка в новых локальных координатах (блок всегда начинается в 0,0)
        fixed_new = fixed_local - new.topLeft()
        self.setTransformOriginPoint(self.box().center())
        self.setRotation(self.angle())
        self.setPos(self.pos() + (fixed_scene - self.mapToScene(fixed_new)))
        self.update()

    def set_prop(self, name, value):
        if name == "auto_size" and not value and not self.props.get("box_w"):
            b = self.box()  # «зафиксировать» текущий размер
            self.props["box_w"], self.props["box_h"] = round(b.width(), 2), round(b.height(), 2)
        super().set_prop(name, value)

    def snap_points(self):
        return rect_snap_points(self.box())

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        self.paint_opacity(painter)
        box, trect, flags, font = self.layout()
        bc = self.props.get("border_color") if self.props.get("border") else None
        paint_text_box(painter, self.props, box, trect, flags, font,
                       border_color=bc, border_w=float(self.props.get("border_width", 2)))

    def describe(self):
        t = (self.props.get("text") or "").replace("\n", " ")
        a = self.angle()
        return f"Текст: {t[:24]}" + ("…" if len(t) > 24 else "") + (f", {a:g}°" if a else "")


# =====================================================================
class CalloutItem(AnnotationItem):
    """Выноска: текстовый блок + линия-указатель + стрелка/точка на объекте.

    pos() — левый верхний угол текстового блока, self.tip — точка указания (локально).
    """
    TYPE = "callout"
    TITLE = "Выноска"
    DEFAULTS = {"text": "Комментарий", "font": DEFAULT_FONT, "size": 18, "bold": False, "italic": False,
                "color": "#000000", "align": "left", "bg": True, "bg_color": "#fff7c2",
                "bg_opacity": 0.95, "padding": 6, "opacity": 1.0,
                "line_color": "#ff2020", "line_width": 2.5, "tip": "arrow", "tip_size": 14.0, "border": True}
    PROPS = text_props() + [
        PropSpec("line_color", "Цвет линии", "color", S_LEADER),
        PropSpec("line_width", "Толщина", "float", S_LEADER, min=0.5, max=40, step=0.5, suffix=" px"),
        PropSpec("tip", "Наконечник", "enum", S_LEADER, options=CAP_STYLES, pair=cap_size("tip_size")),
        PropSpec("border", "Рамка блока", "bool", S_LEADER),
        OPACITY,
    ]

    def __init__(self, props=None, tip: QPointF | None = None):
        super().__init__(props)
        self.tip = QPointF(tip) if tip is not None else QPointF(-40, 60)
        self._layout = None

    def geom_to_dict(self, full=False):
        return {"tip": [round(self.tip.x(), 3), round(self.tip.y(), 3)]}

    def geom_from_dict(self, d):
        t = d.get("tip", [-40, 60])
        self.tip = QPointF(float(t[0]), float(t[1]))
        self._layout = None

    def props_changed(self):
        self._layout = None

    def layout(self):
        if self._layout is None:
            self._layout = layout_text(self.props)
        return self._layout

    def box(self):
        return self.layout()[0]

    def rotation_pivot(self):
        return self.box().center()

    def rotate_geometry(self, f):
        self.prepareGeometryChange()
        self.tip = f(self.tip)
        return True

    def anchor(self) -> QPointF | None:
        b = self.box()
        if b.contains(self.tip):
            return None
        c = b.center()
        cands = [QPointF(c.x(), b.top()), QPointF(b.right(), c.y()),
                 QPointF(c.x(), b.bottom()), QPointF(b.left(), c.y())]
        return min(cands, key=lambda q: dist(q, self.tip))

    def leader_path(self):
        p = QPainterPath()
        a = self.anchor()
        if a is not None:
            p.moveTo(a)
            p.lineTo(self.tip)
        return p

    def outline_path(self):
        p = QPainterPath()
        p.addRect(self.box())
        a = self.anchor()
        if a is not None:
            p.moveTo(a)
            p.lineTo(self.tip)
        return p

    def hit(self, scene_pt, tol):
        lp = self.mapFromScene(scene_pt)
        if self.box().adjusted(-tol, -tol, tol, tol).contains(lp):
            return True
        from PySide6.QtGui import QPainterPathStroker
        st = QPainterPathStroker()
        st.setWidth(float(self.props["line_width"]) + 2 * tol)
        return st.createStroke(self.leader_path()).contains(lp)

    def filled_hit(self):
        return True

    def hit_width(self):
        return float(self.props.get("line_width", 2))

    def margin(self):
        return float(self.props.get("line_width", 2)) * 6 + 12 + float(self.props.get("tip_size") or 0)

    def handles(self):
        return [QPointF(self.tip), QPointF(0, 0)]

    def handle_cursor(self, idx):
        return Qt.CrossCursor if idx == 0 else Qt.SizeAllCursor

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        self.prepareGeometryChange()
        if idx == 0:
            self.tip = QPointF(p)
        else:
            # двигаем только текстовый блок, точка указания остаётся на месте
            self.setPos(self.pos() + p)
            self.tip = self.tip - p
        self.update()

    def snap_points(self):
        return [(QPointF(self.tip), "endpoint")] + rect_snap_points(self.box())

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        self.paint_opacity(painter)
        box, trect, flags, font = self.layout()
        a = self.anchor()
        lc = self.props["line_color"]
        lw = float(self.props["line_width"])
        if a is not None:
            draw_line_with_caps(painter, [a, self.tip], lc, lw, "solid", "none", self.props.get("tip", "arrow"),
                                end_size=self.props.get("tip_size", 0))
        paint_text_box(painter, self.props, box, trect, flags, font,
                       border_color=lc if self.props.get("border") else None, border_w=lw)

    def describe(self):
        t = (self.props.get("text") or "").replace("\n", " ")
        return f"Выноска: {t[:20]}" + ("…" if len(t) > 20 else "")


# =====================================================================
class NumberItem(AnnotationItem):
    """Нумерованный маркер (кружок с номером) с необязательной линией-указателем.

    pos() — центр кружка, self.tip — точка указания (локально).
    """
    TYPE = "number"
    TITLE = "Номер"
    DEFAULTS = {"number": 1, "size": 32, "color": "#ff2020", "text_color": "#ffffff",
                "ring": True, "leader": False, "line_width": 2.5, "tip": "arrow", "tip_size": 14.0,
                "opacity": 1.0}
    PROPS = [
        PropSpec("number", "Номер", "int", "Маркер", min=0, max=9999),
        PropSpec("size", "Диаметр", "int", "Маркер", min=8, max=400, suffix=" px"),
        PropSpec("color", "Цвет", "color", "Маркер"),
        PropSpec("text_color", "Цвет цифры", "color", "Маркер"),
        PropSpec("ring", "Белый ободок", "bool", "Маркер"),
        PropSpec("leader", "Указатель", "bool", S_LEADER),
        PropSpec("line_width", "Толщина", "float", S_LEADER, min=0.5, max=40, step=0.5, suffix=" px"),
        PropSpec("tip", "Наконечник", "enum", S_LEADER, options=CAP_STYLES, pair=cap_size("tip_size")),
        OPACITY,
    ]

    def __init__(self, props=None, tip: QPointF | None = None):
        super().__init__(props)
        self.tip = QPointF(tip) if tip is not None else None

    def geom_to_dict(self, full=False):
        return {"tip": [round(self.tip.x(), 3), round(self.tip.y(), 3)] if self.tip is not None else None}

    def geom_from_dict(self, d):
        t = d.get("tip")
        self.tip = QPointF(float(t[0]), float(t[1])) if t else None

    def props_changed(self):
        if self.props.get("leader") and self.tip is None:
            s = float(self.props["size"])
            self.tip = QPointF(s * 1.8, s * 1.4)

    def radius(self):
        return float(self.props.get("size", 32)) / 2

    def rotation_pivot(self):
        return QPointF(0, 0)

    def rotate_geometry(self, f):
        self.prepareGeometryChange()
        if self.tip is not None:
            self.tip = f(self.tip)
        return True

    def has_leader(self):
        return bool(self.props.get("leader")) and self.tip is not None

    def leader_points(self):
        if not self.has_leader():
            return None
        r = self.radius()
        d = dist(QPointF(0, 0), self.tip)
        if d <= r + 1:
            return None
        start = QPointF(self.tip.x() / d * r, self.tip.y() / d * r)
        return start, QPointF(self.tip)

    def outline_path(self):
        p = QPainterPath()
        r = self.radius()
        p.addEllipse(QPointF(0, 0), r, r)
        lp = self.leader_points()
        if lp:
            p.moveTo(lp[0])
            p.lineTo(lp[1])
        return p

    def filled_hit(self):
        return True

    def hit_width(self):
        return float(self.props.get("line_width", 2))

    def margin(self):
        return float(self.props.get("line_width", 2)) * 6 + 10 + float(self.props.get("tip_size") or 0)

    def handles(self):
        if self.has_leader():
            return [QPointF(0, 0), QPointF(self.tip)]
        return []

    def handle_cursor(self, idx):
        return Qt.SizeAllCursor if idx == 0 else Qt.CrossCursor

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        self.prepareGeometryChange()
        if idx == 1:
            self.tip = QPointF(p)
        else:
            self.setPos(self.pos() + p)
            if self.tip is not None:
                self.tip = self.tip - p
        self.update()

    def snap_points(self):
        r = self.radius()
        out = [(QPointF(0, 0), "center"), (QPointF(0, -r), "edge"), (QPointF(r, 0), "edge"),
               (QPointF(0, r), "edge"), (QPointF(-r, 0), "edge")]
        if self.has_leader():
            out.append((QPointF(self.tip), "endpoint"))
        return out

    def content_rect(self):
        r = self.radius()
        return self.mapToScene(QRectF(-r, -r, 2 * r, 2 * r)).boundingRect()

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        self.paint_opacity(painter)
        r = self.radius()
        color = self.props["color"]
        lp = self.leader_points()
        if lp:
            draw_line_with_caps(painter, list(lp), color, float(self.props["line_width"]), "solid",
                                "none", self.props.get("tip", "arrow"), end_size=self.props.get("tip_size", 0))
        if self.props.get("ring"):
            painter.setPen(QPen(QColor("#ffffff"), max(1.5, r * 0.12)))
        else:
            painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(0, 0), r, r)
        txt = str(self.props.get("number", 1))
        k = 1.15 if len(txt) == 1 else (0.95 if len(txt) == 2 else 0.75)
        f = QFont(DEFAULT_FONT)
        f.setBold(True)
        f.setPixelSize(max(4, int(r * k)))
        painter.setFont(f)
        painter.setPen(QColor(self.props.get("text_color", "#ffffff")))
        painter.drawText(QRectF(-r, -r, 2 * r, 2 * r), int(Qt.AlignCenter), txt)

    def describe(self):
        return f"№ {self.props.get('number')}"
