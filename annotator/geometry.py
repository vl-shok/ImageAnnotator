"""Небольшие геометрические утилиты."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF


def dist(a: QPointF, b: QPointF) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def mid(a: QPointF, b: QPointF) -> QPointF:
    return QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)


def constrain_angle(origin: QPointF, p: QPointF, step_deg: float = 45.0) -> QPointF:
    """Привязать направление origin->p к 0/45/90... градусам."""
    dx, dy = p.x() - origin.x(), p.y() - origin.y()
    if dx == 0 and dy == 0:
        return QPointF(p)
    step = math.radians(step_deg)
    ang = math.atan2(dy, dx)
    a = round(ang / step) * step
    ux, uy = math.cos(a), math.sin(a)
    t = dx * ux + dy * uy
    return QPointF(origin.x() + ux * t, origin.y() + uy * t)


def constrain_axis(origin: QPointF, p: QPointF) -> QPointF:
    """Ограничить перемещение горизонталью или вертикалью."""
    dx, dy = p.x() - origin.x(), p.y() - origin.y()
    if abs(dx) >= abs(dy):
        return QPointF(p.x(), origin.y())
    return QPointF(origin.x(), p.y())


def square_rect(anchor: QPointF, p: QPointF) -> QRectF:
    dx, dy = p.x() - anchor.x(), p.y() - anchor.y()
    s = max(abs(dx), abs(dy))
    return QRectF(anchor, QPointF(anchor.x() + math.copysign(s, dx or 1), anchor.y() + math.copysign(s, dy or 1))).normalized()


def nearest_on_segment(p: QPointF, a: QPointF, b: QPointF) -> QPointF:
    ax, ay, bx, by = a.x(), a.y(), b.x(), b.y()
    vx, vy = bx - ax, by - ay
    l2 = vx * vx + vy * vy
    if l2 == 0:
        return QPointF(a)
    t = ((p.x() - ax) * vx + (p.y() - ay) * vy) / l2
    t = max(0.0, min(1.0, t))
    return QPointF(ax + vx * t, ay + vy * t)


def rect_snap_points(r: QRectF):
    """Углы, середины сторон и центр прямоугольника (локальные точки)."""
    pts = [
        (r.topLeft(), "vertex"), (r.topRight(), "vertex"),
        (r.bottomRight(), "vertex"), (r.bottomLeft(), "vertex"),
        (QPointF(r.center().x(), r.top()), "midpoint"),
        (QPointF(r.right(), r.center().y()), "midpoint"),
        (QPointF(r.center().x(), r.bottom()), "midpoint"),
        (QPointF(r.left(), r.center().y()), "midpoint"),
        (r.center(), "center"),
    ]
    return pts


# ---------------------------------------------------------------- маркеры рамки (tl, t, tr, r, br, b, bl, l)
def box_fixed_point(r0: QRectF, hid: str, symmetric: bool = False) -> QPointF:
    """Точка рамки, которая остаётся на месте при перетаскивании маркера hid (Alt — центр)."""
    if symmetric:
        return r0.center()
    x = r0.center().x() if hid in ("t", "b") else (r0.right() if "l" in hid else r0.left())
    y = r0.center().y() if hid in ("l", "r") else (r0.bottom() if "t" in hid else r0.top())
    return QPointF(x, y)


def resize_box(r0: QRectF, hid: str, p: QPointF, symmetric: bool = False) -> QRectF:
    """Новая рамка, когда маркер hid перетащили в p (свободно; symmetric — от центра)."""
    if symmetric:
        c = r0.center()
        hw, hh = r0.width() / 2, r0.height() / 2
        if "l" in hid or "r" in hid:
            hw = abs(p.x() - c.x())
        if "t" in hid or "b" in hid:
            hh = abs(p.y() - c.y())
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
    return QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()


def handle_angle(center: QPointF, p: QPointF, constrain: bool = False) -> float:
    """Угол поворота по круглому маркеру над объектом: от центра к курсору (constrain — шаг 15°)."""
    a = math.degrees(math.atan2(p.y() - center.y(), p.x() - center.x())) + 90.0
    if constrain:
        a = round(a / 15.0) * 15.0
    return round((a + 180.0) % 360.0 - 180.0, 2)
