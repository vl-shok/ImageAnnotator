"""Иконки, нарисованные кодом (без внешних файлов)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

FG = QColor(222, 226, 233)
RED = QColor(255, 80, 70)
ACC = QColor(70, 170, 255)
_cache: dict = {}


def _pen(c=FG, w=4.0):
    p = QPen(c, w)
    p.setCapStyle(Qt.RoundCap)
    p.setJoinStyle(Qt.RoundJoin)
    return p


def _draw(name, p: QPainter):
    p.setPen(_pen())
    p.setBrush(Qt.NoBrush)
    if name == "select":
        poly = QPolygonF([QPointF(18, 8), QPointF(18, 50), QPointF(28, 40), QPointF(36, 56),
                          QPointF(43, 53), QPointF(35, 37), QPointF(49, 37)])
        p.setBrush(FG)
        p.setPen(_pen(QColor(30, 30, 30), 2))
        p.drawPolygon(poly)
    elif name == "raster":
        pen = _pen(FG, 3.5)
        pen.setDashPattern([2, 1.6])
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.drawRect(QRectF(10, 14, 44, 36))
    elif name == "arrow":
        p.setPen(Qt.NoPen)
        p.setBrush(RED)
        p.drawPolygon(QPolygonF([QPointF(10, 54), QPointF(38, 30), QPointF(32, 24), QPointF(54, 10),
                                 QPointF(42, 34), QPointF(36, 28), QPointF(13, 57)]))
    elif name.startswith("al_"):
        p.setPen(_pen(FG, 5))
        kind = name[3:]
        if kind in ("left", "center", "right"):
            for y, w in ((14, 44), (26, 30), (38, 44), (50, 26)):
                x = {"left": 10, "center": 32 - w / 2, "right": 54 - w}[kind]
                p.drawLine(QPointF(x, y), QPointF(x + w, y))
        else:
            p.setPen(_pen(QColor(120, 125, 135), 3))
            p.drawRect(QRectF(8, 8, 48, 48))
            p.setPen(_pen(FG, 5))
            y0 = {"top": 18, "middle": 28, "bottom": 38}[kind]
            for k, w in enumerate((32, 22)):
                p.drawLine(QPointF(32 - w / 2, y0 + k * 10), QPointF(32 + w / 2, y0 + k * 10))
    elif name == "filter":
        p.setBrush(QColor(FG.red(), FG.green(), FG.blue(), 60))
        p.drawPolygon(QPolygonF([QPointF(8, 10), QPointF(56, 10), QPointF(38, 32), QPointF(38, 54),
                                 QPointF(26, 46), QPointF(26, 32)]))
    elif name == "copy":
        p.drawRoundedRect(QRectF(20, 6, 34, 40), 3, 3)
        p.setBrush(QColor(43, 45, 49))
        p.drawRoundedRect(QRectF(8, 18, 34, 40), 3, 3)
        p.setPen(_pen(ACC, 3))
        p.drawPolygon(QPolygonF([QPointF(14, 50), QPointF(22, 38), QPointF(28, 46), QPointF(32, 42), QPointF(38, 50)]))
    elif name == "break":
        p.setPen(_pen(FG, 3))
        p.drawLine(QPointF(4, 40), QPointF(22, 34))
        p.drawLine(QPointF(42, 30), QPointF(60, 24))
        p.setPen(_pen(RED, 4.5))
        p.drawLine(QPointF(20, 50), QPointF(30, 14))
        p.drawLine(QPointF(34, 50), QPointF(44, 14))
    elif name == "dimension":
        p.setPen(_pen(FG, 3))
        p.drawLine(QPointF(8, 14), QPointF(8, 52))
        p.drawLine(QPointF(56, 14), QPointF(56, 52))
        p.drawLine(QPointF(12, 40), QPointF(52, 40))
        p.setBrush(FG)
        p.drawPolygon(QPolygonF([QPointF(10, 40), QPointF(20, 35), QPointF(20, 45)]))
        p.drawPolygon(QPolygonF([QPointF(54, 40), QPointF(44, 35), QPointF(44, 45)]))
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(17)
        p.setFont(f)
        p.drawText(QRectF(0, 12, 64, 22), Qt.AlignCenter, "25")
    elif name == "crop":
        p.setPen(_pen(FG, 5))
        p.drawPolyline(QPolygonF([QPointF(16, 4), QPointF(16, 48), QPointF(60, 48)]))
        p.drawPolyline(QPolygonF([QPointF(4, 16), QPointF(48, 16), QPointF(48, 60)]))
    elif name == "curves":
        p.drawRect(QRectF(8, 8, 48, 48))
        path = QPainterPath(QPointF(8, 56))
        path.cubicTo(QPointF(30, 50), QPointF(34, 14), QPointF(56, 8))
        p.setPen(_pen(ACC, 4))
        p.drawPath(path)
    elif name == "adjust":
        p.drawEllipse(QRectF(8, 8, 48, 48))
        p.setBrush(FG)
        path = QPainterPath(QPointF(32, 8))
        path.arcTo(QRectF(8, 8, 48, 48), 90, 180)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "line":
        p.setPen(_pen(FG, 4.5))
        p.drawLine(QPointF(10, 54), QPointF(54, 10))
        p.setBrush(FG)
        p.drawEllipse(QPointF(10, 54), 3, 3)
        p.drawEllipse(QPointF(54, 10), 3, 3)
    elif name == "text":
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(46)
        p.setFont(f)
        p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, "T")
    elif name == "callout":
        path = QPainterPath()
        path.addRoundedRect(QRectF(16, 8, 42, 28), 5, 5)
        p.drawPath(path)
        p.setPen(_pen(RED, 3.5))
        p.drawLine(QPointF(24, 36), QPointF(8, 56))
        p.setBrush(RED)
        p.drawEllipse(QPointF(8, 56), 3.5, 3.5)
        p.setPen(_pen(FG, 3))
        p.drawLine(QPointF(24, 18), QPointF(50, 18))
        p.drawLine(QPointF(24, 26), QPointF(42, 26))
    elif name == "number":
        p.setPen(_pen(QColor(255, 255, 255), 3))
        p.setBrush(RED)
        p.drawEllipse(QPointF(32, 32), 22, 22)
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(28)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, "1")
    elif name == "rect":
        p.drawRect(QRectF(10, 16, 44, 32))
    elif name == "ellipse":
        p.drawEllipse(QRectF(8, 14, 48, 36))
    elif name == "polyline":
        p.drawPolyline(QPolygonF([QPointF(8, 50), QPointF(22, 18), QPointF(40, 42), QPointF(56, 12)]))
        p.setBrush(FG)
        for q in (QPointF(8, 50), QPointF(22, 18), QPointF(40, 42), QPointF(56, 12)):
            p.drawEllipse(q, 2.5, 2.5)
    elif name == "polygon":
        p.setBrush(QColor(255, 216, 0, 70))
        p.drawPolygon(QPolygonF([QPointF(12, 50), QPointF(18, 14), QPointF(46, 10), QPointF(56, 40), QPointF(34, 56)]))
    elif name == "freehand":
        path = QPainterPath(QPointF(8, 44))
        path.cubicTo(QPointF(18, 10), QPointF(28, 60), QPointF(38, 26))
        path.cubicTo(QPointF(44, 12), QPointF(52, 30), QPointF(57, 22))
        p.drawPath(path)
    elif name == "image":
        p.drawRoundedRect(QRectF(8, 12, 48, 40), 4, 4)
        p.setBrush(FG)
        p.setPen(Qt.NoPen)
        p.drawPolygon(QPolygonF([QPointF(12, 48), QPointF(26, 30), QPointF(36, 42), QPointF(42, 36), QPointF(52, 48)]))
        p.drawEllipse(QPointF(43, 22), 4.5, 4.5)
    elif name == "open":
        p.drawPolyline(QPolygonF([QPointF(8, 50), QPointF(8, 14), QPointF(24, 14), QPointF(29, 20), QPointF(52, 20),
                                  QPointF(52, 28)]))
        p.drawPolygon(QPolygonF([QPointF(8, 50), QPointF(16, 28), QPointF(58, 28), QPointF(50, 50)]))
    elif name == "save":
        p.drawRoundedRect(QRectF(10, 10, 44, 44), 4, 4)
        p.drawRect(QRectF(20, 10, 22, 14))
        p.drawRect(QRectF(18, 34, 28, 20))
    elif name == "export":
        p.drawRoundedRect(QRectF(8, 18, 36, 38), 3, 3)
        p.setPen(_pen(ACC, 4.5))
        p.drawLine(QPointF(30, 34), QPointF(56, 8))
        p.drawPolyline(QPolygonF([QPointF(40, 8), QPointF(56, 8), QPointF(56, 24)]))
    elif name in ("undo", "redo"):
        if name == "redo":
            p.translate(64, 0)
            p.scale(-1, 1)
        path = QPainterPath(QPointF(16, 26))
        path.cubicTo(QPointF(30, 12), QPointF(56, 16), QPointF(52, 42))
        p.drawPath(path)
        p.drawPolyline(QPolygonF([QPointF(14, 12), QPointF(14, 28), QPointF(30, 28)]))
    elif name == "fit":
        for (x, y, dx, dy) in ((8, 8, 1, 1), (56, 8, -1, 1), (56, 56, -1, -1), (8, 56, 1, -1)):
            p.drawLine(QPointF(x, y), QPointF(x + dx * 14, y))
            p.drawLine(QPointF(x, y), QPointF(x, y + dy * 14))
        p.drawRect(QRectF(22, 22, 20, 20))
    elif name == "actual":
        f = QFont("Segoe UI")
        f.setBold(True)
        f.setPixelSize(24)
        p.setFont(f)
        p.drawText(QRectF(0, 0, 64, 64), Qt.AlignCenter, "1:1")
    elif name == "eye":
        path = QPainterPath(QPointF(6, 32))
        path.quadTo(QPointF(32, 4), QPointF(58, 32))
        path.quadTo(QPointF(32, 60), QPointF(6, 32))
        p.drawPath(path)
        p.setBrush(FG)
        p.drawEllipse(QPointF(32, 32), 8, 8)
    elif name == "eye_off":
        p.setPen(_pen(QColor(110, 115, 125), 4))
        path = QPainterPath(QPointF(6, 32))
        path.quadTo(QPointF(32, 4), QPointF(58, 32))
        path.quadTo(QPointF(32, 60), QPointF(6, 32))
        p.drawPath(path)
        p.drawLine(QPointF(10, 54), QPointF(54, 10))
    elif name == "lock":
        p.setPen(_pen(QColor(255, 190, 80), 4))
        p.drawArc(QRectF(20, 8, 24, 30), 0, 180 * 16)
        p.drawLine(QPointF(20, 23), QPointF(20, 30))
        p.drawLine(QPointF(44, 23), QPointF(44, 30))
        p.setBrush(QColor(255, 190, 80))
        p.drawRoundedRect(QRectF(14, 30, 36, 26), 3, 3)
    elif name == "unlock":
        p.setPen(_pen(QColor(90, 95, 105), 3))
        p.drawArc(QRectF(20, 8, 24, 30), 0, 180 * 16)
        p.drawLine(QPointF(44, 23), QPointF(44, 30))
        p.drawRoundedRect(QRectF(14, 30, 36, 26), 3, 3)
    elif name == "layer_add":
        _layers(p)
        p.setPen(_pen(ACC, 5))
        p.drawLine(QPointF(50, 38), QPointF(50, 62))
        p.drawLine(QPointF(38, 50), QPointF(62, 50))
    elif name == "layer_del":
        _layers(p)
        p.setPen(_pen(RED, 5))
        p.drawLine(QPointF(40, 40), QPointF(60, 60))
        p.drawLine(QPointF(60, 40), QPointF(40, 60))
    elif name == "layer_dup":
        p.drawRect(QRectF(8, 8, 34, 34))
        p.drawRect(QRectF(22, 22, 34, 34))
    elif name == "up":
        p.drawPolyline(QPolygonF([QPointF(14, 40), QPointF(32, 20), QPointF(50, 40)]))
    elif name == "down":
        p.drawPolyline(QPolygonF([QPointF(14, 24), QPointF(32, 44), QPointF(50, 24)]))
    elif name == "merge":
        p.drawLine(QPointF(32, 8), QPointF(32, 40))
        p.drawPolyline(QPolygonF([QPointF(20, 28), QPointF(32, 40), QPointF(44, 28)]))
        p.drawLine(QPointF(10, 52), QPointF(54, 52))
    elif name == "snap":
        p.drawLine(QPointF(10, 54), QPointF(40, 24))
        p.setPen(_pen(QColor(255, 210, 0), 4))
        p.drawRect(QRectF(34, 10, 20, 20))
    elif name == "layers":
        _layers(p)
    elif name == "group":
        p.drawRect(QRectF(8, 8, 26, 26))
        p.drawEllipse(QRectF(28, 28, 28, 28))


def _layers(p):
    p.setBrush(QColor(60, 64, 72))
    for dy in (24, 12, 0):
        p.drawPolygon(QPolygonF([QPointF(4, 22 + dy), QPointF(26, 12 + dy), QPointF(48, 22 + dy), QPointF(26, 32 + dy)]))


def icon(name: str) -> QIcon:
    if name in _cache:
        return _cache[name]
    ic = QIcon()
    for size in (64,):
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.scale(size / 64, size / 64)
        _draw(name, p)
        p.end()
        ic.addPixmap(pm)
    _cache[name] = ic
    return ic


def small_icon(name: str, size: int = 15, canvas: QSize = QSize(40, 28)) -> QIcon:
    """Иконка name, нарисованная уменьшенной по центру холста canvas
    (для колонок дерева, где общий размер иконок задан миниатюрами)."""
    key = (name, size, canvas.width(), canvas.height())
    if key in _cache:
        return _cache[key]
    pm = QPixmap(canvas)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.translate((canvas.width() - size) / 2, (canvas.height() - size) / 2)
    p.scale(size / 64, size / 64)
    _draw(name, p)
    p.end()
    ic = QIcon(pm)
    _cache[key] = ic
    return ic


def app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(28, 90, 60))
    p.setPen(QPen(QColor(200, 170, 60), 3))
    p.drawRoundedRect(QRectF(4, 4, 56, 56), 8, 8)
    p.setPen(QPen(QColor(200, 170, 60), 2.5))
    for x in (16, 28, 40):
        p.drawLine(QPointF(x, 46), QPointF(x, 54))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 70, 60))
    p.drawPolygon(QPolygonF([QPointF(14, 40), QPointF(36, 22), QPointF(31, 17), QPointF(50, 10),
                             QPointF(43, 29), QPointF(38, 24), QPointF(17, 44)]))
    p.end()
    return QIcon(pm)
