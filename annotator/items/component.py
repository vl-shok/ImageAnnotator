"""Посадочное место компонента (вид сверху): резистор — корпус с двумя контактными площадками."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPolygonF, QTransform

from ..geometry import rect_snap_points
from ..props import LINE_SPACING, LINE_STYLES, OPACITY, S_TEXT, PropSpec
from .base import make_pen, qcolor
from .shapes import ANGLE, BoxItem, PathItem
from .text import DEFAULT_FONT, draw_text_block, line_spacing, make_font, text_block_size

S_BODY = "Корпус"
S_PADS = "Выводы"
S_LABEL = "Надпись"


class ResistorItem(BoxItem):
    """Резистор сверху: прямоугольник корпуса, на концах длинной стороны — площадки (обкладки).
    Масштабируется ручками, поворачивается; по галочке «Текст внутри» — надпись между площадками."""
    TYPE = "resistor"
    TITLE = "Резистор"
    ROTATABLE = True
    DEFAULTS = {"color": "#ff2020", "width": 2.5, "style": "solid",
                "fill": True, "fill_color": "#ffd800", "fill_opacity": 0.25,
                "pad_len": 22, "pad_color": "#ff2020", "pad_opacity": 0.55,
                "show_text": False, "text": "R1", "font": DEFAULT_FONT, "auto_size": True, "size": 18, "bold": True, "line_spacing": 1.0,
                "text_color": "#ff2020", "angle": 0.0, "opacity": 1.0}
    PROPS = [
        PropSpec("color", "Цвет контура", "color", S_BODY),
        PropSpec("width", "Толщина", "float", S_BODY, min=0, max=100, step=0.5, suffix=" px"),
        PropSpec("style", "Стиль", "enum", S_BODY, options=LINE_STYLES),
        PropSpec("fill", "Заливка корпуса", "bool", S_BODY),
        PropSpec("fill_color", "Цвет заливки", "color", S_BODY),
        PropSpec("fill_opacity", "Прозр. заливки", "opacity", S_BODY),
        PropSpec("pad_len", "Длина вывода", "int", S_PADS, min=5, max=45, suffix=" %"),
        PropSpec("pad_color", "Цвет выводов", "color", S_PADS),
        PropSpec("pad_opacity", "Прозр. выводов", "opacity", S_PADS),
        PropSpec("show_text", "Текст внутри", "bool", S_LABEL),
        PropSpec("text", "Текст", "text", S_LABEL),
        PropSpec("font", "Шрифт", "font", S_LABEL),
        PropSpec("auto_size", "Размер по корпусу", "bool", S_LABEL),
        PropSpec("size", "Размер", "int", S_LABEL, min=4, max=600, suffix=" px"),
        PropSpec("text_color", "Цвет текста", "color", S_LABEL),
        PropSpec("bold", "Жирный", "bool", S_LABEL),
        PropSpec("line_spacing", "Межстрочный", "float", S_LABEL, min=0.5, max=3.0, step=0.1, suffix="×"),
        ANGLE,
        OPACITY,
    ]

    ASPECT = 2.0          # типичный корпус: длина = 2 × ширина
    def set_drag(self, p0, p1, constrain=False, center=False):
        """Рисование: Shift — сразу пропорции 1:2 (вдоль направления, куда тянут)."""
        if constrain:
            dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
            if abs(dx) >= abs(dy):
                w = abs(dx)
                h = w / self.ASPECT
            else:
                h = abs(dy)
                w = h / self.ASPECT
            p1 = QPointF(p0.x() + (w if dx >= 0 else -w), p0.y() + (h if dy >= 0 else -h))
        super().set_drag(p0, p1, False, center)

    def set_aspect(self, aspect: float | None = None):
        """Привести к соотношению сторон 1:aspect (длинная сторона и центр сохраняются)."""
        k = float(aspect or self.ASPECT)
        r = self.rect.normalized()
        long_side = max(r.width(), r.height())
        if long_side <= 0:
            return
        w, h = (long_side, long_side / k) if self.horizontal() else (long_side / k, long_side)
        c = r.center()
        anchor = self.mapToScene(c)
        self._apply_rect(QRectF(c.x() - w / 2, c.y() - h / 2, w, h), c, anchor)
        self.update()

    def aspect(self) -> float:
        r = self.rect.normalized()
        short = min(r.width(), r.height())
        return max(r.width(), r.height()) / short if short > 0 else 0.0

    def set_prop(self, name, value):
        super().set_prop(name, value)
        if name == "text" and value and not self.props.get("show_text"):
            self.props["show_text"] = True   # ввели текст (двойной клик) — сразу показать его
            self.update()
        if name == "size" and self.props.get("auto_size"):
            self.props["auto_size"] = False  # задали размер вручную — автоподбор больше не мешает
            self.update()

    # ------------------------------------------------------------------ геометрия
    def horizontal(self) -> bool:
        """Площадки — на концах длинной стороны."""
        r = self.rect.normalized()
        return r.width() >= r.height()

    def pads(self) -> tuple[QRectF, QRectF]:
        r = self.rect.normalized()
        k = max(0.0, min(45.0, float(self.props.get("pad_len", 22)))) / 100.0
        if self.horizontal():
            ln = r.width() * k
            return QRectF(r.left(), r.top(), ln, r.height()), QRectF(r.right() - ln, r.top(), ln, r.height())
        ln = r.height() * k
        return QRectF(r.left(), r.top(), r.width(), ln), QRectF(r.left(), r.bottom() - ln, r.width(), ln)

    def body_inner(self) -> QRectF:
        """Корпус между площадками — место для надписи."""
        a, b = self.pads()
        r = self.rect.normalized()
        if self.horizontal():
            return QRectF(a.right(), r.top(), b.left() - a.right(), r.height())
        return QRectF(r.left(), a.bottom(), r.width(), b.top() - a.bottom())

    def filled_hit(self):
        return True

    def snap_points(self):
        a, b = self.pads()
        # центры площадок — удобно вести к ним линии и стрелки
        return rect_snap_points(self.rect.normalized()) + [(a.center(), "center"), (b.center(), "center")]

    # ------------------------------------------------------------------ отрисовка
    def paint(self, painter, option, widget=None):
        r = self.rect.normalized()
        if r.width() <= 0 or r.height() <= 0:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        self.paint_opacity(painter)
        p = self.props
        pa, pb = self.pads()
        if p.get("fill"):
            painter.fillRect(self.body_inner(), qcolor(p["fill_color"], p["fill_opacity"]))
        pad_brush = qcolor(p.get("pad_color", p["color"]), p.get("pad_opacity", 0.55))
        painter.fillRect(pa, pad_brush)
        painter.fillRect(pb, pad_brush)
        w = float(p.get("width", 0) or 0)
        if w > 0:
            pen = make_pen(p["color"], w, p.get("style", "solid"))
            pen.setJoinStyle(Qt.MiterJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r)
            # границы площадок
            if self.horizontal():
                painter.drawLine(QPointF(pa.right(), r.top()), QPointF(pa.right(), r.bottom()))
                painter.drawLine(QPointF(pb.left(), r.top()), QPointF(pb.left(), r.bottom()))
            else:
                painter.drawLine(QPointF(r.left(), pa.bottom()), QPointF(r.right(), pa.bottom()))
                painter.drawLine(QPointF(r.left(), pb.top()), QPointF(r.right(), pb.top()))
        if p.get("show_text") and (p.get("text") or "").strip():
            self._paint_label(painter)

    LABEL_FILL = 0.7      # авторазмер: высота букв — до 70% ширины корпуса
    LABEL_MARGIN = 0.06   # поля от площадок и краёв (доля короткой стороны корпуса)

    def label_font(self):
        """Шрифт надписи: ручной размер — как в свойствах; «Размер по корпусу» — буквы по габариту
        (точные габариты глифов, а не высота строки) между площадками с небольшими полями."""
        p = self.props
        font = make_font(p)
        text = p.get("text", "")
        if not p.get("auto_size", True):
            return font
        inner = self.body_inner()
        along, across = (inner.width(), inner.height()) if self.horizontal() else (inner.height(), inner.width())
        m = min(along, across) * self.LABEL_MARGIN
        avail_w, avail_h = along - 2 * m, across * self.LABEL_FILL
        if avail_w <= 1 or avail_h <= 1:
            return None
        font.setPixelSize(100)
        w, h = self._text_size(font, text, line_spacing(p))
        k = min(avail_w / max(w, 1e-6), avail_h / max(h, 1e-6))
        font.setPixelSize(max(1, int(100 * k)))
        return font

    @staticmethod
    def _text_size(font, text, spacing=1.0):
        if "\n" in text:
            return text_block_size(text, font, spacing)
        r = QFontMetricsF(font).tightBoundingRect(text)
        return r.width(), r.height()

    def _paint_label(self, painter):
        p = self.props
        font = self.label_font()
        if font is None:
            return
        text = p.get("text", "")
        painter.save()
        painter.translate(self.body_inner().center())
        if not self.horizontal():
            painter.rotate(-90)      # вдоль корпуса
        painter.setFont(font)
        painter.setPen(QColor(p.get("text_color", "#ff2020")))
        fm = QFontMetricsF(font)
        if "\n" in text:
            big = 1e5
            draw_text_block(painter, QRectF(-big / 2, -big / 2, big, big), Qt.AlignCenter, text, font,
                            line_spacing(p))
        else:
            # центр по самим буквам (без пустого места строки над и под ними)
            t = fm.tightBoundingRect(text)
            painter.drawText(QPointF(-t.center().x(), -t.center().y()), text)
        painter.restore()

    def describe(self):
        t = (self.props.get("text") or "").replace("\n", " ") if self.props.get("show_text") else ""
        r = self.rect
        return f"{self.TITLE}{': ' + t[:16] if t else ''} {r.width():.0f}×{r.height():.0f}"


S_BOX3D = "Корпус"


class Box3DItem(PathItem):
    """3D-элемент — имитация компонента на фото. Основание — параллелограмм (4 точки: A, B, C, D по кругу),
    рисуется как прямоугольник; ручка на стороне сдвигает сторону (Shift — только вдоль неё: перекос),
    ручка в углу растягивает, сохраняя перекос. Высота и её направление — в свойствах (0 — плоский).
    Верхняя грань = основание + вектор высоты; видны грани, обращённые к зрителю.
    Надпись лежит на верхней грани (в той же проекции, что и грань)."""
    TYPE = "box3d"
    TITLE = "3D-элемент"
    CLOSED = True
    MIN_POINTS = 4
    DEFAULTS = {"color": "#101010", "width": 1.5, "style": "solid", "opacity": 1.0,
                "fill_color": "#363636", "fill_opacity": 1.0, "shade": 40,
                "height": 0, "height_angle": -90.0,
                "show_text": True, "text": "U1", "font": DEFAULT_FONT, "auto_size": True, "size": 18, "bold": True,
                "italic": False, "text_color": "#e6e6e6", "line_spacing": 1.0}
    PROPS = [
        PropSpec("height", "Высота", "int", S_BOX3D, min=0, max=2000, suffix=" px"),
        PropSpec("height_angle", "Направление высоты", "float", S_BOX3D, min=-180, max=180, step=5, suffix="°"),
        PropSpec("fill_color", "Цвет корпуса", "color", S_BOX3D),
        PropSpec("fill_opacity", "Непрозр. корпуса", "opacity", S_BOX3D),
        PropSpec("shade", "Тень граней", "int", S_BOX3D, min=0, max=90, suffix=" %"),
        PropSpec("color", "Цвет контура", "color", S_BOX3D),
        PropSpec("width", "Толщина контура", "float", S_BOX3D, min=0, max=50, step=0.5, suffix=" px"),
        PropSpec("show_text", "Надпись сверху", "bool", S_TEXT),
        PropSpec("text", "Текст", "text", S_TEXT),
        PropSpec("font", "Шрифт", "font", S_TEXT),
        PropSpec("auto_size", "Размер по грани", "bool", S_TEXT),
        PropSpec("size", "Размер", "int", S_TEXT, min=4, max=600, suffix=" px"),
        PropSpec("text_color", "Цвет текста", "color", S_TEXT),
        PropSpec("bold", "Начертание", "toggle", S_TEXT, icon="B", tip="Жирный",
                 pair=PropSpec("italic", "Курсив", "toggle", icon="I", tip="Курсив")),
        LINE_SPACING,
        OPACITY,
    ]
    LABEL_FILL = (0.86, 0.62)     # «Размер по грани»: доля длины и ширины грани под буквы

    def __init__(self, points=None, props=None):
        super().__init__(points, props)
        self._drag0 = None

    # ------------------------------------------------------------------ создание и данные
    def set_drag(self, p0: QPointF, p1: QPointF, constrain=False, center=False):
        """Рисование — как прямоугольник (Shift — квадрат, Alt — от центра)."""
        dx, dy = p1.x() - p0.x(), p1.y() - p0.y()
        if constrain:
            m = max(abs(dx), abs(dy))
            dx, dy = math.copysign(m, dx or 1), math.copysign(m, dy or 1)
        if center:
            r = QRectF(p0.x() - abs(dx), p0.y() - abs(dy), 2 * abs(dx), 2 * abs(dy))
        else:
            r = QRectF(p0, QPointF(p0.x() + dx, p0.y() + dy)).normalized()
        self.set_scene_points([r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()])

    def rotate_geometry(self, f):
        o = self.points[0] if self.points else QPointF(0, 0)
        a = math.radians(float(self.props.get("height_angle", -90) or 0))
        tip = f(o + QPointF(math.cos(a), math.sin(a))) - f(o)   # направление высоты — вместе с основанием
        super().rotate_geometry(f)
        na = round(math.degrees(math.atan2(tip.y(), tip.x())), 3)
        self.props["height_angle"] = 180.0 if na == -180.0 else na
        return True

    def set_prop(self, name, value):
        super().set_prop(name, value)
        if name == "text" and (value or "").strip() and not self.props.get("show_text"):
            self.props["show_text"] = True
            self.update()
        if name == "size" and self.props.get("auto_size"):
            self.props["auto_size"] = False  # задали размер вручную — «Размер по грани» выключается
            self.update()

    # ------------------------------------------------------------------ геометрия
    def ext(self) -> QPointF:
        h = float(self.props.get("height", 0) or 0)
        a = math.radians(float(self.props.get("height_angle", -90) or 0))
        return QPointF(h * math.cos(a), h * math.sin(a))

    def center(self) -> QPointF:
        n = len(self.points) or 1
        return QPointF(sum(p.x() for p in self.points) / n, sum(p.y() for p in self.points) / n)

    def top_points(self) -> list[QPointF]:
        v = self.ext()
        return [p + v for p in self.points]

    def side_faces(self) -> list[tuple[QPolygonF, float]]:
        """Видимые боковые грани в порядке отрисовки (дальние раньше): (многоугольник, «прямота» 0..1)."""
        pts = self.points
        v = self.ext()
        ln = math.hypot(v.x(), v.y())
        if len(pts) < 3 or ln < 0.5:
            return []
        ux, uy = v.x() / ln, v.y() / ln
        area = sum(pts[i].x() * pts[(i + 1) % len(pts)].y() - pts[(i + 1) % len(pts)].x() * pts[i].y()
                   for i in range(len(pts)))
        s = 1.0 if area >= 0 else -1.0
        out = []
        for i in range(len(pts)):
            p, q = pts[i], pts[(i + 1) % len(pts)]
            dx, dy = q.x() - p.x(), q.y() - p.y()
            el = math.hypot(dx, dy)
            if el < 1e-9:
                continue
            nx, ny = s * dy / el, -s * dx / el            # внешняя нормаль стороны основания
            facing = -(nx * ux + ny * uy)                  # грань смотрит против высоты — к зрителю
            if facing > 0.02:                              # почти «ребром» — грань в волосок не рисуем
                m = (p + q) / 2
                out.append((m.x() * ux + m.y() * uy, QPolygonF([p, q, q + v, p + v]), facing))
        out.sort(key=lambda t: -t[0])
        return [(poly, f) for _, poly, f in out]

    def outline_path(self):
        path = QPainterPath()
        if len(self.points) < 3:
            return path
        for poly in [QPolygonF(self.points), QPolygonF(self.top_points())] + [f for f, _ in self.side_faces()]:
            part = QPainterPath()
            part.addPolygon(poly)
            part.closeSubpath()
            path = path.united(part)
        return path

    def filled_hit(self):
        return True

    def snap_points(self):
        pts = self.points
        out = [(QPointF(p), "corner") for p in pts]
        out += [((pts[i] + pts[(i + 1) % len(pts)]) / 2, "midpoint") for i in range(len(pts))]
        if self.ext() != QPointF(0, 0):
            out += [(p, "corner") for p in self.top_points()]
        out.append((self.center() + self.ext(), "center"))
        return out

    # ------------------------------------------------------------------ ручки: 4 угла + 4 стороны + высота
    HEIGHT_HANDLE = 8
    HEIGHT_HANDLE_MIN_PX = 18     # у плоского элемента маркер высоты чуть в стороне от центра (экранные px)

    def height_handle_pos(self) -> QPointF:
        """Маркер высоты — центр верхней грани; у плоского — немного в сторону направления высоты."""
        v = self.ext()
        from . import base
        k = base.VIEW_SCALE or 1.0
        if math.hypot(v.x(), v.y()) * k < self.HEIGHT_HANDLE_MIN_PX:
            a = math.radians(float(self.props.get("height_angle", -90) or 0))
            d = self.HEIGHT_HANDLE_MIN_PX / k
            v = QPointF(d * math.cos(a), d * math.sin(a))
        return self.center() + v

    def handles(self):
        pts = self.points
        if len(pts) != 4:
            return list(pts)
        return list(pts) + [(pts[i] + pts[(i + 1) % 4]) / 2 for i in range(4)] + [self.height_handle_pos()]

    def handle_kinds(self):
        if len(self.points) != 4:
            return ["corner"] * len(self.points)
        return ["corner"] * 4 + ["edge"] * 4 + ["height"]

    def handle_cursor(self, idx):
        if idx == self.HEIGHT_HANDLE:
            return Qt.SizeVerCursor
        return Qt.SizeAllCursor if idx >= 4 else Qt.CrossCursor

    def set_height_to(self, p: QPointF, keep_direction=False):
        """Маркер высоты перетащили в p (локально): высота = расстояние от центра основания,
        направление — туда же (keep_direction — только высота, вдоль прежнего направления)."""
        c = self.center()
        d = p - c
        if keep_direction:
            a = math.radians(float(self.props.get("height_angle", -90) or 0))
            h = max(0.0, d.x() * math.cos(a) + d.y() * math.sin(a))
        else:
            h = math.hypot(d.x(), d.y())
            if h >= 0.5:
                a = math.degrees(math.atan2(d.y(), d.x()))
                near = round(a / 15.0) * 15.0
                if abs(a - near) <= 3.0:                    # мягкая привязка к −90°, −45°, … (рука дрожит)
                    a = near
                a = 180.0 if a == -180.0 else a
                self.props["height_angle"] = round(a, 1)
        self.prepareGeometryChange()
        self.props["height"] = int(round(h))
        self.update()

    def begin_handle_drag(self, idx):
        self._drag0 = [QPointF(p) for p in self.points]
        return None

    def handle_anchor(self, idx):
        pts = self._drag0 or self.points
        if len(pts) != 4:
            return None
        if idx == self.HEIGHT_HANDLE:
            return self.center()                            # направляющие 0/45/90° от центра основания
        if idx < 4:
            return QPointF(pts[(idx + 2) % 4])              # противоположный угол
        return (pts[idx - 4] + pts[(idx - 3) % 4]) / 2      # где была середина стороны

    def handle_snap_extra(self, idx):
        return None

    def move_handle(self, idx, p, constrain=False, symmetric=False):
        if len(self.points) != 4:
            return
        if idx == self.HEIGHT_HANDLE:
            self.set_height_to(p, keep_direction=constrain)   # Shift — только высота
            return
        pts = [QPointF(q) for q in (self._drag0 or self.points)]
        self.prepareGeometryChange()
        if idx >= 4:
            # сторона k: сдвигаются оба её конца, противоположная сторона на месте -> параллелограмм
            k = idx - 4
            a, b = pts[k], pts[(k + 1) % 4]
            d = p - (a + b) / 2
            if constrain:                                   # только вдоль стороны — чистый перекос
                ex, ey = b.x() - a.x(), b.y() - a.y()
                el2 = ex * ex + ey * ey
                if el2 > 1e-12:
                    t = (d.x() * ex + d.y() * ey) / el2
                    d = QPointF(ex * t, ey * t)
            pts[k] = a + d
            pts[(k + 1) % 4] = b + d
        else:
            # угол: противоположный угол на месте, стороны сохраняют направления (перекос не меняется)
            o = pts[(idx + 2) % 4]
            n1, n2 = pts[(idx + 1) % 4], pts[(idx + 3) % 4]
            u, w = n1 - o, n2 - o
            det = u.x() * w.y() - u.y() * w.x()
            if abs(det) < 1e-9:
                return
            r = p - o
            ka = (r.x() * w.y() - r.y() * w.x()) / det
            kb = (u.x() * r.y() - u.y() * r.x()) / det
            if constrain:                                   # Shift — пропорционально
                m = max(abs(ka), abs(kb))
                ka, kb = math.copysign(m, ka), math.copysign(m, kb)
            pts[(idx + 1) % 4] = o + u * ka
            pts[(idx + 3) % 4] = o + w * kb
            pts[idx] = o + u * ka + w * kb
        self.points = pts
        self.update()

    # ------------------------------------------------------------------ надпись на верхней грани
    def label_frame(self):
        """(QTransform, длина, ширина): система координат верхней грани — центр грани в (0, 0),
        ось X — вдоль длинной стороны слева направо, ось Y — вдоль другой стороны «вниз»."""
        pts = self.top_points()
        if len(pts) != 4:
            return None
        e1, e2 = pts[1] - pts[0], pts[3] - pts[0]
        l1, l2 = math.hypot(e1.x(), e1.y()), math.hypot(e2.x(), e2.y())
        if l1 < 1e-6 or l2 < 1e-6:
            return None
        (ex, lx), (ey, ly) = ((e1, l1), (e2, l2)) if l1 >= l2 else ((e2, l2), (e1, l1))
        xh, yh = ex / lx, ey / ly
        if xh.x() < -1e-9 or (abs(xh.x()) <= 1e-9 and xh.y() > 0):
            xh = -xh                                         # читается слева направо (или снизу вверх)
        if xh.x() * yh.y() - xh.y() * yh.x() < 0:
            yh = -yh                                         # не зеркально
        c = sum(pts, QPointF(0, 0)) / 4
        return QTransform(xh.x(), xh.y(), yh.x(), yh.y(), c.x(), c.y()), lx, ly

    def label_font(self, length, width):
        p = self.props
        font = make_font(p)
        if not p.get("auto_size", True):
            return font
        font.setPixelSize(100)
        text = p.get("text", "")
        if "\n" in text:
            w, h = text_block_size(text, font, line_spacing(p))
        else:
            r = QFontMetricsF(font).tightBoundingRect(text)
            w, h = r.width(), r.height()
        k = min(length * self.LABEL_FILL[0] / max(w, 1e-6), width * self.LABEL_FILL[1] / max(h, 1e-6))
        font.setPixelSize(max(1, int(100 * k)))
        return font

    def _paint_label(self, painter):
        p = self.props
        fr = self.label_frame()
        if fr is None:
            return
        tf, length, width = fr
        font = self.label_font(length, width)
        text = p.get("text", "")
        painter.save()
        painter.setTransform(tf, True)
        painter.setFont(font)
        painter.setPen(QColor(p.get("text_color", "#e6e6e6")))
        if "\n" in text:
            draw_text_block(painter, QRectF(-length / 2, -width / 2, length, width), Qt.AlignCenter, text, font,
                            line_spacing(p))
        else:
            t = QFontMetricsF(font).tightBoundingRect(text)  # центр по самим буквам
            painter.drawText(QPointF(-t.center().x(), -t.center().y()), text)
        painter.restore()

    # ------------------------------------------------------------------ отрисовка
    def paint(self, painter, option, widget=None):
        if len(self.points) < 3:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        self.paint_opacity(painter)
        p = self.props
        top = qcolor(p.get("fill_color", "#363636"), p.get("fill_opacity", 1.0))
        shade = max(0.0, min(0.9, float(p.get("shade", 40) or 0) / 100.0))
        w = float(p.get("width", 0) or 0)
        pen = make_pen(p["color"], w, p.get("style", "solid")) if w > 0 else Qt.NoPen
        if w > 0:
            pen.setJoinStyle(Qt.MiterJoin)
        painter.setPen(pen)
        for poly, facing in self.side_faces():
            k = 1.0 - shade * (0.55 + 0.45 * facing)      # грань, обращённая прямо к зрителю, — темнее
            col = QColor(top)
            col.setRgbF(col.redF() * k, col.greenF() * k, col.blueF() * k, col.alphaF())
            painter.setBrush(col)
            painter.drawPolygon(poly)
        painter.setBrush(top)
        painter.drawPolygon(QPolygonF(self.top_points()))
        if p.get("show_text") and (p.get("text") or "").strip():
            self._paint_label(painter)

    def describe(self):
        t = (self.props.get("text") or "").replace("\n", " ") if self.props.get("show_text") else ""
        h = float(self.props.get("height", 0) or 0)
        return f"{self.TITLE}{': ' + t[:16] if t else ''}" + (f", высота {h:g}" if h else "")
