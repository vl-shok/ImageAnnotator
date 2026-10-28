"""Отметка «одобрено»: галочка в квадрате (или в круге), масштабируется и поворачивается."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen

from ..geometry import rect_snap_points
from ..props import OPACITY, PropSpec
from .base import qcolor
from .shapes import ANGLE, BoxItem

S_MARK = "Галочка"
FRAMES = [("box", "Квадрат"), ("circle", "Круг"), ("none", "Без рамки")]
# галочка в долях рамки: левый конец, нижняя точка, правый конец
CHECK = ((0.24, 0.53), (0.43, 0.72), (0.78, 0.30))


class CheckItem(BoxItem):
    TYPE = "check"
    TITLE = "Галочка"
    ROTATABLE = True
    DEFAULTS = {"color": "#1fa339", "frame": "box", "thickness": 12, "fill": True, "fill_color": "#ffffff",
                "fill_opacity": 0.85, "angle": 0.0, "opacity": 1.0}
    PROPS = [
        PropSpec("color", "Цвет", "color", S_MARK),
        PropSpec("frame", "Рамка", "enum", S_MARK, options=FRAMES),
        PropSpec("thickness", "Толщина", "int", S_MARK, min=3, max=30, suffix=" %"),
        PropSpec("fill", "Подложка", "bool", S_MARK),
        PropSpec("fill_color", "Цвет подложки", "color", S_MARK),
        PropSpec("fill_opacity", "Прозр. подложки", "opacity", S_MARK),
        ANGLE,
        OPACITY,
    ]

    def stroke(self) -> float:
        """Толщина линий — в процентах от меньшей стороны (при масштабировании галочка не «худеет»)."""
        r = self.rect.normalized()
        return max(1.0, min(r.width(), r.height()) * float(self.props.get("thickness", 12)) / 100.0)

    def frame_path(self) -> QPainterPath:
        r = self.rect.normalized()
        t = self.stroke()
        inner = r.adjusted(t / 2, t / 2, -t / 2, -t / 2)
        path = QPainterPath()
        if self.props.get("frame") == "circle":
            path.addEllipse(inner)
        else:
            rad = min(inner.width(), inner.height()) * 0.12
            path.addRoundedRect(inner, rad, rad)
        return path

    def check_path(self) -> QPainterPath:
        r = self.rect.normalized()
        pts = [QPointF(r.left() + fx * r.width(), r.top() + fy * r.height()) for fx, fy in CHECK]
        path = QPainterPath(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        return path

    def outline_path(self):
        path = QPainterPath()
        path.addRect(self.rect.normalized())
        return path

    def filled_hit(self):
        return True

    def snap_points(self):
        return rect_snap_points(self.rect.normalized())

    def paint(self, painter, option, widget=None):
        r = self.rect.normalized()
        if r.width() <= 0 or r.height() <= 0:
            return
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint_opacity(painter)
        p = self.props
        frame = p.get("frame", "box")
        t = self.stroke()
        if p.get("fill"):
            # подложка — по форме рамки (и без рамки тоже, чтобы галочку было видно на пёстром фоне)
            painter.fillPath(self.frame_path(), qcolor(p.get("fill_color", "#ffffff"), p.get("fill_opacity", 0.85)))
        pen = QPen(qcolor(p["color"]), t)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if frame != "none":
            fp = QPen(pen)
            fp.setWidthF(t * 0.7)
            painter.setPen(fp)
            painter.drawPath(self.frame_path())
            painter.setPen(pen)
        painter.drawPath(self.check_path())

    def describe(self):
        r = self.rect
        return f"{self.TITLE} {r.width():.0f}×{r.height():.0f}"

