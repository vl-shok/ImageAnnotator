"""Текст, выноска (Callout) и нумерованный маркер."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QTextLayout, QTextOption

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


def line_spacing(props) -> float:
    """Межстрочный интервал (множитель высоты строки; 1.0 — как обычно)."""
    try:
        return max(0.3, float(props.get("line_spacing", 1.0) or 1.0))
    except (TypeError, ValueError):
        return 1.0


def _text_lines(text: str, font: QFont, wrap_w: float | None):
    """Строки текста (с переносом по словам, если задана ширина): [(QTextLayout, QTextLine)]."""
    out = []
    for para in text.split("\n"):
        tl = QTextLayout(para.replace("\t", "    "), font)
        opt = QTextOption()
        opt.setWrapMode(QTextOption.WordWrap if wrap_w else QTextOption.NoWrap)
        tl.setTextOption(opt)
        tl.beginLayout()
        while True:
            ln = tl.createLine()
            if not ln.isValid():
                break
            ln.setLineWidth(wrap_w if wrap_w else 1e6)
            ln.setPosition(QPointF(0, 0))
        tl.endLayout()
        out += [(tl, tl.lineAt(i)) for i in range(tl.lineCount())]
    return out


def text_block_size(text: str, font: QFont, spacing: float, wrap_w: float | None = None):
    """(ширина, высота) многострочного текста с межстрочным интервалом spacing."""
    fm = QFontMetricsF(font)
    lines = _text_lines(text, font, wrap_w)
    w = max((ln.naturalTextWidth() for _, ln in lines), default=0.0)
    h = fm.height() + fm.lineSpacing() * spacing * (max(1, len(lines)) - 1)   # 1.0 — как у Qt
    return w, h


def draw_text_block(painter: QPainter, rect: QRectF, flags, text: str, font: QFont, spacing: float):
    """Как painter.drawText(rect, flags, text), но с межстрочным интервалом spacing."""
    flags = int(flags)
    if abs(spacing - 1.0) < 1e-6:
        painter.drawText(rect, flags, text)
        return
    fm = QFontMetricsF(font)
    wrap_w = rect.width() if flags & int(Qt.TextWordWrap) else None
    lines = _text_lines(text, font, wrap_w)
    step = fm.lineSpacing() * spacing
    total = fm.height() + step * (max(1, len(lines)) - 1)
    if flags & int(Qt.AlignBottom):
        y = rect.bottom() - total
    elif flags & int(Qt.AlignVCenter):
        y = rect.center().y() - total / 2
    else:
        y = rect.top()
    painter.setFont(font)
    for i, (_, ln) in enumerate(lines):
        lw = ln.naturalTextWidth()
        if flags & int(Qt.AlignRight):
            x = rect.right() - lw
        elif flags & int(Qt.AlignHCenter):
            x = rect.center().x() - lw / 2
        else:
            x = rect.left()
        ln.draw(painter, QPointF(x, y + i * step))


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
    sp = line_spacing(props)
    if abs(sp - 1.0) < 1e-6:
        br = fm.boundingRect(QRectF(0, 0, 1e6, 1e6), int(Qt.AlignLeft | Qt.AlignTop | Qt.TextExpandTabs), text)
        bw, bh = br.width(), br.height()
    else:
        bw, bh = text_block_size(text, font, sp)
    w = bw + (fm.averageCharWidth() * 0.3 if props.get("italic") else 0) + 1
    h = max(bh, fm.height())
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
    draw_text_block(painter, trect, flags, props.get("text", ""), font, line_spacing(props))


# =====================================================================
class TextItem(AnnotationItem):
    """Текст. pos() — левый верхний угол блока; поворот — вокруг центра блока.
    Размер блока — автоматически по тексту или задан вручную (ручки по краям рамки)."""
    HANDLE_IDS = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
    TYPE = "text"
    TITLE = "Текст"
    ROT_HANDLE_PX = 26
    DEFAULTS = {"text": "ТЕКСТ", "font": DEFAULT_FONT, "size": 24, "bold": True, "italic": False, "line_spacing": 1.0,
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
    DEFAULTS = {"text": "Комментарий", "font": DEFAULT_FONT, "size": 18, "bold": False, "italic": False, "line_spacing": 1.0,
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
        # указатели: [точка указания (локально), начало на рамке (fx, fy) или None — авто]
        self.leaders = [[QPointF(tip) if tip is not None else QPointF(-40, 60), None]]
        # изгиб каждого указателя: середина дуги (u, v) в системе «начало → острие»
        # (u — вдоль, v — поперёк, в долях длины) или None — прямая
        self.bends: list[tuple[float, float] | None] = [None]
        self._layout = None

    # первый указатель — для совместимости
    @property
    def tip(self) -> QPointF:
        return self.leaders[0][0]

    @tip.setter
    def tip(self, p: QPointF):
        self.leaders[0][0] = QPointF(p)

    def geom_to_dict(self, full=False):
        out = []
        for t, st in self.leaders:
            out.append([round(t.x(), 3), round(t.y(), 3)] + ([round(st[0], 4), round(st[1], 4)] if st else []))
        d = {"tip": out[0][:2], "leaders": out}
        if any(b is not None for b in self.bends):
            d["bends"] = [[round(b[0], 6), round(b[1], 6)] if b is not None else None for b in self.bends]
        return d

    def geom_from_dict(self, d):
        lst = d.get("leaders")
        if not lst:
            t = d.get("tip", [-40, 60])
            lst = [[t[0], t[1]]]
        self.leaders = [[QPointF(float(v[0]), float(v[1])),
                         (float(v[2]), float(v[3])) if len(v) >= 4 else None] for v in lst]
        bends = list(d.get("bends") or [])
        bends += [None] * (len(self.leaders) - len(bends))
        self.bends = [(float(b[0]), float(b[1])) if b else None for b in bends[:len(self.leaders)]]
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
        for ld in self.leaders:
            ld[0] = f(ld[0])
        return True

    # --------------------------------------------------------- указатели
    def start_point(self, i: int) -> QPointF | None:
        """Начало i-го указателя на рамке блока (None — точка внутри блока, линии нет)."""
        b = self.box()
        tip, st = self.leaders[i]
        if b.contains(tip):
            return None
        if st is not None:
            return QPointF(b.left() + st[0] * b.width(), b.top() + st[1] * b.height())
        c = b.center()
        cands = [QPointF(c.x(), b.top()), QPointF(b.right(), c.y()),
                 QPointF(c.x(), b.bottom()), QPointF(b.left(), c.y())]
        return min(cands, key=lambda q: dist(q, tip))

    def anchor(self) -> QPointF | None:
        return self.start_point(0)

    def bend_mid(self, i: int) -> QPointF | None:
        """Середина i-го указателя (ручка изгиба) или None, если линии нет."""
        a = self.start_point(i)
        if a is None:
            return None
        t = self.leaders[i][0]
        bend = self.bends[i]
        if bend is None:
            return QPointF((a.x() + t.x()) / 2, (a.y() + t.y()) / 2)
        dx, dy = t.x() - a.x(), t.y() - a.y()
        u, v = bend
        return QPointF(a.x() + u * dx - v * dy, a.y() + u * dy + v * dx)

    def leader_ctrl(self, i: int) -> QPointF | None:
        """Контрольная точка дуги i-го указателя (None — прямая)."""
        if self.bends[i] is None:
            return None
        a, m = self.start_point(i), self.bend_mid(i)
        if a is None:
            return None
        t = self.leaders[i][0]
        return QPointF(2 * m.x() - (a.x() + t.x()) / 2, 2 * m.y() - (a.y() + t.y()) / 2)

    def segments(self):
        """[(начало, острие, контрольная точка или None)] — только видимые указатели."""
        out = []
        for i, (tip, _) in enumerate(self.leaders):
            a = self.start_point(i)
            if a is not None:
                out.append((a, tip, self.leader_ctrl(i)))
        return out

    def bend_leader(self, i: int, m: QPointF):
        """Изогнуть i-й указатель так, чтобы дуга проходила через m."""
        a = self.start_point(i)
        if a is None:
            return
        t = self.leaders[i][0]
        dx, dy = t.x() - a.x(), t.y() - a.y()
        ln2 = dx * dx + dy * dy
        self.prepareGeometryChange()
        if ln2 < 1e-9 or dist(m, QPointF((a.x() + t.x()) / 2, (a.y() + t.y()) / 2)) < 0.75:
            self.bends[i] = None   # почти прямая — считаем прямой
        else:
            rx, ry = m.x() - a.x(), m.y() - a.y()
            self.bends[i] = ((rx * dx + ry * dy) / ln2, (ry * dx - rx * dy) / ln2)
        self.update()

    def is_bent(self) -> bool:
        return any(b is not None for b in self.bends)

    def straighten(self, handle_idx=None):
        """Выпрямить указатель ручки изгиба handle_idx (None — все)."""
        self.prepareGeometryChange()
        n = len(self.leaders)
        if handle_idx is not None and 2 * n <= handle_idx < 3 * n:
            self.bends[handle_idx - 2 * n] = None
        else:
            self.bends = [None] * n
        self.update()

    def add_leader(self, tip: QPointF, start=None):
        self.prepareGeometryChange()
        self.leaders.append([QPointF(tip), start])
        self.bends.append(None)
        self.update()

    def remove_leader(self, i: int) -> bool:
        if len(self.leaders) <= 1 or not 0 <= i < len(self.leaders):
            return False
        self.prepareGeometryChange()
        del self.leaders[i]
        del self.bends[i]
        # приклеенные острия: номера следующих указателей сдвигаются
        glue = {}
        for k, g in self.glue.items():
            j = int(k[1:])
            if j != i:
                glue[f"t{j - 1 if j > i else j}"] = g
        self.glue = glue
        self.update()
        return True

    def reset_start(self, i: int):
        if 0 <= i < len(self.leaders):
            self.leaders[i][1] = None
            self.update()

    def _border_param(self, p: QPointF, snap_mid: bool):
        """Ближайшая к p точка рамки как (fx, fy)."""
        b = self.box()
        if b.width() <= 0 or b.height() <= 0:
            return None
        fx = min(1.0, max(0.0, (p.x() - b.left()) / b.width()))
        fy = min(1.0, max(0.0, (p.y() - b.top()) / b.height()))
        # расстояния до сторон в пикселях
        d = {"l": fx * b.width(), "r": (1 - fx) * b.width(), "t": fy * b.height(), "b": (1 - fy) * b.height()}
        side = min(d, key=d.get)
        if side in ("l", "r"):
            fx = 0.0 if side == "l" else 1.0
            if snap_mid:
                fy = min((0.0, 0.5, 1.0), key=lambda v: abs(v - fy))
        else:
            fy = 0.0 if side == "t" else 1.0
            if snap_mid:
                fx = min((0.0, 0.5, 1.0), key=lambda v: abs(v - fx))
        return (round(fx, 4), round(fy, 4))

    def leader_path(self):
        p = QPainterPath()
        for a, t, c in self.segments():
            p.moveTo(a)
            if c is None:
                p.lineTo(t)
            else:
                p.quadTo(c, t)
        return p

    def outline_path(self):
        p = QPainterPath()
        p.addRect(self.box())
        p.addPath(self.leader_path())
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

    # ручки: [острие 1, начало 1, острие 2, начало 2, …, изгиб 1, изгиб 2, …, блок]
    def handles(self):
        hs = []
        for i, (tip, _) in enumerate(self.leaders):
            hs.append(QPointF(tip))
            a = self.start_point(i)
            hs.append(a if a is not None else QPointF(tip))
        for i, (tip, _) in enumerate(self.leaders):
            m = self.bend_mid(i)
            hs.append(m if m is not None else QPointF(tip))
        hs.append(self.box().center())     # маркер перемещения блока (стрелки остаются на месте)
        return hs

    def handle_kinds(self):
        n = len(self.leaders)
        # у указателя без линии (острие внутри блока) ручки изгиба нет
        bends = ["bend" if self.start_point(i) is not None else "hidden" for i in range(n)]
        return ["tip", "anchor"] * n + bends + ["move"]

    def leader_index(self, idx):
        """(номер указателя, 'tip' | 'anchor' | 'bend') для индекса ручки или None (блок)."""
        n = len(self.leaders)
        if idx < 2 * n:
            return idx // 2, ("tip" if idx % 2 == 0 else "anchor")
        if idx < 3 * n:
            return idx - 2 * n, "bend"
        return None

    def handle_snap_extra(self, idx):
        li = self.leader_index(idx)
        if li is None or li[1] != "anchor":
            return None
        # начало стрелки — к углам и серединам сторон своего блока
        return [(self.mapToScene(p), k) for p, k in rect_snap_points(self.box()) if k != "center"]

    def handle_cursor(self, idx):
        li = self.leader_index(idx)
        if li is None:
            return Qt.SizeAllCursor
        if li[1] == "bend":
            return Qt.SizeAllCursor
        return Qt.CrossCursor if li[1] == "tip" else Qt.PointingHandCursor

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        self.prepareGeometryChange()
        li = self.leader_index(idx)
        if li is None:
            # двигаем только текстовый блок (центр — под курсор), точки указания остаются на месте
            d = p - self.box().center()
            self.setPos(self.pos() + d)
            for ld in self.leaders:
                ld[0] = ld[0] - d
        elif li[1] == "tip":
            self.leaders[li[0]][0] = QPointF(p)
        elif li[1] == "bend":
            self.bend_leader(li[0], p)
        else:
            self.leaders[li[0]][1] = self._border_param(p, constrain)
        self.update()

    # приклеивание: «t0», «t1», … — острия указателей
    def glue_ends(self):
        return {f"t{i}": QPointF(t) for i, (t, _) in enumerate(self.leaders)}

    def set_glue_end(self, key, p):
        i = int(key[1:])
        if 0 <= i < len(self.leaders):
            self.prepareGeometryChange()
            self.leaders[i][0] = QPointF(p)
            self.update()

    def handle_glue_key(self, idx):
        li = self.leader_index(idx)
        return f"t{li[0]}" if li is not None and li[1] == "tip" else None

    def handle_anchor(self, idx):
        li = self.leader_index(idx)
        if li is None or li[1] != "tip":
            return None
        return self.start_point(li[0]) or self.box().center()

    def snap_points(self):
        return [(QPointF(t), "endpoint") for t, _ in self.leaders] + rect_snap_points(self.box())

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        self.paint_opacity(painter)
        box, trect, flags, font = self.layout()
        lc = self.props["line_color"]
        lw = float(self.props["line_width"])
        for a, t, c in self.segments():
            draw_line_with_caps(painter, [a, t], lc, lw, "solid", "none", self.props.get("tip", "arrow"),
                                end_size=self.props.get("tip_size", 0), ctrl=c)
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

    # приклеивание: «t» — острие указателя
    def glue_ends(self):
        return {"t": QPointF(self.tip)} if self.has_leader() else {}

    def set_glue_end(self, key, p):
        if key == "t" and self.tip is not None:
            self.prepareGeometryChange()
            self.tip = QPointF(p)
            self.update()

    def handle_glue_key(self, idx):
        return "t" if idx == 1 and self.has_leader() else None

    def handle_anchor(self, idx):
        return QPointF(0, 0) if idx == 1 else None

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
