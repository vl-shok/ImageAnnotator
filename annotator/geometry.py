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
