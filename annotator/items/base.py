"""Базовый класс всех объектов-аннотаций.

Объект сам отвечает только за:
  * своё содержимое (paint),
  * геометрию (outline_path, handles, move_handle),
  * точки привязки (snap_points),
  * сериализацию (to_dict / apply_dict).

Выделение, ручки, hover и индикаторы привязки рисует CanvasView поверх сцены,
поэтому они никогда не попадают в экспорт.
"""
from __future__ import annotations

import copy
import math
import uuid

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPainterPathStroker, QPen, QPolygonF
from PySide6.QtWidgets import QGraphicsItem

from .. import styles


# текущий масштаб вида — нужен, чтобы ручка поворота была на постоянном экранном расстоянии
VIEW_SCALE = 1.0


def set_view_scale(k: float):
    global VIEW_SCALE
    VIEW_SCALE = max(1e-3, float(k))


def qcolor(hexstr: str, alpha: float = 1.0) -> QColor:
    c = QColor(hexstr)
    c.setAlphaF(max(0.0, min(1.0, float(alpha))))
    return c


def make_pen(color, width: float, style: str = "solid") -> QPen:
    pen = QPen(QColor(color) if not isinstance(color, QColor) else color)
    pen.setWidthF(max(0.1, float(width)))
    pen.setJoinStyle(Qt.RoundJoin)
    if style == "dash":
        pen.setCapStyle(Qt.FlatCap)
        pen.setDashPattern([4, 3])
    elif style == "dashdot":
        pen.setCapStyle(Qt.FlatCap)
        pen.setDashPattern([6, 3, 1, 3])
    elif style == "dot":
        pen.setCapStyle(Qt.RoundCap)
        pen.setDashPattern([0.01, 2.2])
    else:
        pen.setCapStyle(Qt.RoundCap)
    return pen


def arrow_head_size(width: float) -> tuple[float, float]:
    """(длина, полуширина) наконечника для линии заданной толщины."""
    hl = max(9.0, width * 4.0 + 5.0)
    return hl, hl * 0.42


def quad_point(p0, c, p1, t):
    a = (1 - t) * (1 - t)
    b = 2 * (1 - t) * t
    d = t * t
    return QPointF(a * p0.x() + b * c.x() + d * p1.x(), a * p0.y() + b * c.y() + d * p1.y())


def quad_sub(p0, c, p1, t0, t1):
    """Участок квадратичной кривой Безье между t0 и t1 → (начало, контрольная, конец)."""
    k0 = (1 - t0) * (1 - t1)
    k1 = (1 - t0) * t1 + t0 * (1 - t1)
    k2 = t0 * t1
    cc = QPointF(k0 * p0.x() + k1 * c.x() + k2 * p1.x(), k0 * p0.y() + k1 * c.y() + k2 * p1.y())
    return quad_point(p0, c, p1, t0), cc, quad_point(p0, c, p1, t1)


def quad_length(p0, c, p1, n=32):
    ln, prev = 0.0, p0
    for i in range(1, n + 1):
        q = quad_point(p0, c, p1, i / n)
        ln += math.hypot(q.x() - prev.x(), q.y() - prev.y())
        prev = q
    return ln


def cap_dims(width: float, size: float):
    """(длина, полуширина) наконечника; size=0 — автоматически по толщине линии."""
    if size and size > 0:
        return float(size), float(size) * 0.42
    return arrow_head_size(width)


def _arrow_head(tip, prev, hl, hw):
    dx, dy = tip.x() - prev.x(), tip.y() - prev.y()
    ln = math.hypot(dx, dy)
    if ln < 1e-6:
        return None, None
    ux, uy = dx / ln, dy / ln
    base = QPointF(tip.x() - ux * hl, tip.y() - uy * hl)
    nx, ny = -uy, ux
    poly = QPolygonF([tip, QPointF(base.x() + nx * hw, base.y() + ny * hw),
                      QPointF(base.x() - nx * hw, base.y() - ny * hw)])
    return poly, (ux, uy)


def draw_line_with_caps(painter, pts, color, width, style, start_cap, end_cap, closed=False,
                        start_size=0.0, end_size=0.0, ctrl=None):
    """Рисует ломаную (или изогнутую линию с контрольной точкой ctrl) с наконечниками на концах."""
    if len(pts) < 2:
        return
    pts = [QPointF(p) for p in pts]
    width = float(width)
    heads, dots = [], []
    curved = ctrl is not None and len(pts) == 2
    if curved:
        p0, c, p1 = pts[0], QPointF(ctrl), pts[1]
        total = max(quad_length(p0, c, p1), 1e-6)
        t0, t1 = 0.0, 1.0
        for cap, size, is_end in ((start_cap, start_size, False), (end_cap, end_size, True)):
            hl, hw = cap_dims(width, size)
            if cap == "arrow":
                tip = p1 if is_end else p0
                cut = min(hl * 0.8, total * 0.45)
                tt = 1 - cut / total if is_end else cut / total
                base_pt = quad_point(p0, c, p1, 1 - hl / total if is_end else hl / total)
                poly, _ = _arrow_head(tip, base_pt, hl, hw)
                if poly is not None:
                    heads.append(poly)
                if is_end:
                    t1 = tt
                else:
                    t0 = tt
            elif cap == "dot":
                r = hl / 2 if size else max(3.0, width * 1.6)
                dots.append((p1 if is_end else p0, r))
        a, cc, b = quad_sub(p0, c, p1, t0, t1)
        path = QPainterPath(a)
        path.quadTo(cc, b)
    else:
        if not closed:
            for cap, size, i_end, i_prev in ((start_cap, start_size, 0, 1), (end_cap, end_size, -1, -2)):
                hl, hw = cap_dims(width, size)
                if cap == "arrow":
                    tip, prev = pts[i_end], pts[i_prev]
                    poly, u = _arrow_head(tip, prev, hl, hw)
                    if poly is None:
                        continue
                    heads.append(poly)
                    ln = math.hypot(tip.x() - prev.x(), tip.y() - prev.y())
                    cut = min(hl * 0.8, ln * 0.9)
                    pts[i_end] = QPointF(tip.x() - u[0] * cut, tip.y() - u[1] * cut)
                elif cap == "dot":
                    r = hl / 2 if size else max(3.0, width * 1.6)
                    dots.append((pts[i_end], r))
        path = QPainterPath(pts[0])
        for p in pts[1:]:
            path.lineTo(p)
        if closed:
            path.closeSubpath()
    painter.setPen(make_pen(color, width, style))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(color))
    for h in heads:
        painter.drawPolygon(h)
    for p, r in dots:
        painter.drawEllipse(p, r, r)


class AnnotationItem(QGraphicsItem):
    TYPE = "object"
    TITLE = "Объект"
    PROPS: list = []
    DEFAULTS: dict = {"opacity": 1.0}

    def __init__(self, props: dict | None = None):
        super().__init__()
        self.uid = uuid.uuid4().hex[:12]
        self.props = styles.defaults_for(self)
        if props:
            self.props.update(copy.deepcopy(props))
        self.layer_id: str | None = None
        self.z_local: float = 0.0
        self.locked = False
        self.obj_visible = True
        self.group_id: str | None = None

    # ---------------------------------------------------------- serialization
    def geom_to_dict(self, full: bool = False) -> dict:
        return {}

    def geom_from_dict(self, d: dict):
        pass

    def to_dict(self, full: bool = False) -> dict:
        return {
            "type": self.TYPE,
            "id": self.uid,
            "layer": self.layer_id,
            "z": self.z_local,
            "locked": self.locked,
            "visible": self.obj_visible,
            "group": self.group_id,
            "pos": [self.pos().x(), self.pos().y()],
            "props": copy.deepcopy(self.props),
            "geom": self.geom_to_dict(full),
        }

    def state(self) -> dict:
        """Состояние для Undo (без тяжёлых данных)."""
        return self.to_dict(full=False)

    def apply_dict(self, d: dict, keep_id: bool = True):
        self.prepareGeometryChange()
        if keep_id and d.get("id"):
            self.uid = d["id"]
        self.layer_id = d.get("layer", self.layer_id)
        self.z_local = float(d.get("z", self.z_local))
        self.locked = bool(d.get("locked", False))
        self.obj_visible = bool(d.get("visible", True))
        self.group_id = d.get("group")
        props = copy.deepcopy(self.DEFAULTS)
        props.update(copy.deepcopy(d.get("props", {})))
        self.props = props
        self.geom_from_dict(d.get("geom", {}))
        pos = d.get("pos", [0, 0])
        self.setPos(float(pos[0]), float(pos[1]))
        self.props_changed()
        self.update()

    # ---------------------------------------------------------- properties
    def prop_specs(self):
        return list(self.PROPS)

    def set_prop(self, name, value):
        self.prepareGeometryChange()
        self.props[name] = value
        self.props_changed()
        self.update()

    def props_changed(self):
        pass

    # ---------------------------------------------------------- geometry
    def outline_path(self) -> QPainterPath:
        return QPainterPath()

    def filled_hit(self) -> bool:
        return False

    def hit_width(self) -> float:
        return float(self.props.get("width", 2.0))

    def margin(self) -> float:
        return self.hit_width() * 2 + 4

    def boundingRect(self) -> QRectF:
        m = self.margin()
        return self.outline_path().boundingRect().adjusted(-m, -m, m, m)

    def shape(self) -> QPainterPath:
        st = QPainterPathStroker()
        st.setWidth(max(4.0, self.hit_width()))
        path = st.createStroke(self.outline_path())
        if self.filled_hit():
            path = path.united(self.outline_path())
        return path

    def content_rect(self) -> QRectF:
        """Габарит содержимого в координатах сцены (для выравнивания, рамки выделения)."""
        r = self.outline_path().boundingRect()
        return self.mapToScene(r).boundingRect()

    def hit(self, scene_pt: QPointF, tol: float) -> bool:
        p = self.mapFromScene(scene_pt)
        path = self.outline_path()
        if self.filled_hit() and path.contains(p):
            return True
        st = QPainterPathStroker()
        st.setWidth(self.hit_width() + 2 * tol)
        st.setCapStyle(Qt.RoundCap)
        st.setJoinStyle(Qt.RoundJoin)
        return st.createStroke(path).contains(p)

    def intersects_rect(self, scene_rect: QRectF) -> bool:
        path = self.mapToScene(self.shape())
        return path.intersects(scene_rect)

    # handles: точки в локальных координатах
    def handles(self) -> list[QPointF]:
        return []

    def handle_kinds(self) -> list[str]:
        """Тип каждой ручки: box | vertex | insert (добавить вершину) | rot (поворот) | point."""
        return ["point"] * len(self.handles())

    def handle_cursor(self, idx: int):
        return Qt.SizeAllCursor

    def begin_handle_drag(self, idx: int):
        """Вызывается перед перетаскиванием ручки. Может вернуть новый индекс ручки
        (например, после вставки вершины)."""
        return None

    def move_handle(self, idx: int, p: QPointF, constrain: bool = False, symmetric: bool = False):
        pass

    def snap_points(self) -> list[tuple[QPointF, str]]:
        return []

    # ---------------------------------------------------------- misc
    def describe(self) -> str:
        return self.TITLE

    def has_text(self) -> bool:
        return "text" in self.props

    def paint_opacity(self, painter):
        painter.setOpacity(painter.opacity() * float(self.props.get("opacity", 1.0)))

    def clone(self):
        from . import create_from_dict
        d = self.to_dict(full=True)
        d["id"] = None
        it = create_from_dict(d, keep_id=False)
        return it
