"""Посадочное место компонента (вид сверху): резистор — корпус с двумя контактными площадками."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QPainter

from ..geometry import rect_snap_points
from ..props import LINE_STYLES, OPACITY, PropSpec
from .base import make_pen, qcolor
from .shapes import ANGLE, BoxItem
from .text import DEFAULT_FONT, make_font

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
                "show_text": False, "text": "R1", "font": DEFAULT_FONT, "auto_size": True, "size": 18, "bold": True,
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
        w, h = self._text_size(font, text)
        k = min(avail_w / max(w, 1e-6), avail_h / max(h, 1e-6))
        font.setPixelSize(max(1, int(100 * k)))
        return font

    @staticmethod
    def _text_size(font, text):
        fm = QFontMetricsF(font)
        if "\n" in text:
            r = fm.boundingRect(QRectF(0, 0, 1e6, 1e6), int(Qt.AlignCenter), text)
        else:
            r = fm.tightBoundingRect(text)
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
            painter.drawText(QRectF(-big / 2, -big / 2, big, big), int(Qt.AlignCenter), text)
        else:
            # центр по самим буквам (без пустого места строки над и под ними)
            t = fm.tightBoundingRect(text)
            painter.drawText(QPointF(-t.center().x(), -t.center().y()), text)
        painter.restore()

    def describe(self):
        t = (self.props.get("text") or "").replace("\n", " ") if self.props.get("show_text") else ""
        r = self.rect
        return f"{self.TITLE}{': ' + t[:16] if t else ''} {r.width():.0f}×{r.height():.0f}"
