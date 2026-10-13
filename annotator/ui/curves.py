"""Редактор «Кривые» в стиле Photoshop: гистограмма под кривой, точки добавляются кликом,
перетаскиваются мышью, удаляются двойным кликом/ПКМ или вытаскиванием за пределы поля."""
from __future__ import annotations

import copy

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from .. import imageops

CHANNELS = [("rgb", "RGB"), ("r", "Красный"), ("g", "Зелёный"), ("b", "Синий")]
CH_COLOR = {"rgb": QColor(235, 235, 235), "r": QColor(255, 90, 90), "g": QColor(90, 220, 110), "b": QColor(100, 150, 255)}
HIST_INDEX = {"rgb": 3, "r": 0, "g": 1, "b": 2}


def default_curves():
    return imageops.default_curves()


class CurvesWidget(QWidget):
    changed = Signal(dict)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.curves = default_curves()
        self.channel = "rgb"
        self.hist = None
        self._drag = None
        self._hover = None
        self.setMouseTracking(True)
        self.setMinimumSize(150, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def sizeHint(self):
        return QSize(256, 256)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return w

    # ------------------------------------------------------------------ data
    def set_curves(self, curves):
        self.curves = copy.deepcopy(curves) if curves else default_curves()
        for c, _ in CHANNELS:
            self.curves.setdefault(c, copy.deepcopy(imageops.IDENTITY_CURVE))
        self.update()

    def set_channel(self, ch):
        self.channel = ch
        self.update()

    def set_histogram(self, hist):
        self.hist = hist
        self.update()

    def points(self):
        return self.curves[self.channel]

    # ------------------------------------------------------------------ geometry
    def area(self) -> QRectF:
        s = min(self.width(), self.height()) - 10
        return QRectF(5, 5, s, s)

    def to_screen(self, x, y) -> QPointF:
        a = self.area()
        return QPointF(a.left() + x / 255.0 * a.width(), a.bottom() - y / 255.0 * a.height())

    def to_value(self, p: QPointF):
        a = self.area()
        x = (p.x() - a.left()) / a.width() * 255.0
        y = (a.bottom() - p.y()) / a.height() * 255.0
        return x, y

    def _find(self, pos, tol=8):
        for i, (x, y) in enumerate(self.points()):
            sp = self.to_screen(x, y)
            if abs(sp.x() - pos.x()) <= tol and abs(sp.y() - pos.y()) <= tol:
                return i
        return None

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, ev):
        pos = ev.position()
        i = self._find(pos)
        pts = self.points()
        if ev.button() == Qt.RightButton:
            if i is not None and 0 < i < len(pts) - 1:
                pts.pop(i)
                self._emit(True)
            return
        if ev.button() != Qt.LeftButton:
            return
        if i is None:
            x, y = self.to_value(pos)
            x = min(254.0, max(1.0, x))
            y = min(255.0, max(0.0, y))
            pts.append([round(x), round(y)])
            pts.sort(key=lambda q: q[0])
            i = next(k for k, q in enumerate(pts) if q[0] == round(x) and q[1] == round(y))
            self._emit(False)
        self._drag = i

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is None:
            h = self._find(pos)
            if h != self._hover:
                self._hover = h
                self.update()
            return
        pts = self.points()
        i = self._drag
        x, y = self.to_value(pos)
        a = self.area()
        far = not a.adjusted(-30, -30, 30, 30).contains(pos)
        if far and 0 < i < len(pts) - 1:
            pts.pop(i)
            self._drag = None
            self._emit(False)
            return
        lo = pts[i - 1][0] + 1 if i > 0 else 0
        hi = pts[i + 1][0] - 1 if i < len(pts) - 1 else 255
        pts[i] = [int(round(min(hi, max(lo, x)))), int(round(min(255, max(0, y))))]
        self._emit(False)

    def mouseReleaseEvent(self, ev):
        if self._drag is not None:
            self._drag = None
            self.finished.emit()

    def mouseDoubleClickEvent(self, ev):
        i = self._find(ev.position())
        pts = self.points()
        if i is not None and 0 < i < len(pts) - 1:
            pts.pop(i)
            self._emit(True)

    def _emit(self, finished):
        self.update()
        self.changed.emit(copy.deepcopy(self.curves))
        if finished:
            self.finished.emit()

    # ------------------------------------------------------------------ paint
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        a = self.area()
        p.fillRect(a, QColor(24, 26, 30))
        # гистограмма
        if self.hist:
            h = self.hist[HIST_INDEX[self.channel]]
            path = QPainterPath(QPointF(a.left(), a.bottom()))
            for i, v in enumerate(h):
                path.lineTo(a.left() + i / 255.0 * a.width(), a.bottom() - v * a.height() * 0.9)
            path.lineTo(a.right(), a.bottom())
            c = QColor(CH_COLOR[self.channel])
            c.setAlpha(55)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawPath(path)
        # сетка
        p.setPen(QPen(QColor(70, 74, 82), 1))
        for k in range(1, 4):
            x = a.left() + a.width() * k / 4
            y = a.top() + a.height() * k / 4
            p.drawLine(QPointF(x, a.top()), QPointF(x, a.bottom()))
            p.drawLine(QPointF(a.left(), y), QPointF(a.right(), y))
        p.setPen(QPen(QColor(90, 94, 102), 1, Qt.DashLine))
        p.drawLine(a.bottomLeft(), a.topRight())
        p.setPen(QPen(QColor(80, 84, 92), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(a)
        # кривые других каналов — бледно
        for ch, _ in CHANNELS:
            if ch == self.channel or imageops._curve_is_identity(self.curves.get(ch, imageops.IDENTITY_CURVE)):
                continue
            self._draw_curve(p, ch, 70)
        self._draw_curve(p, self.channel, 255)
        # точки
        for i, (x, y) in enumerate(self.points()):
            sp = self.to_screen(x, y)
            hl = i == self._hover or i == self._drag
            p.setPen(QPen(QColor(20, 20, 20), 1))
            p.setBrush(QColor(255, 140, 0) if hl else QColor(240, 240, 240))
            p.drawRect(QRectF(sp.x() - 4, sp.y() - 4, 8, 8))
        if self._drag is not None:
            x, y = self.points()[self._drag]
            p.setPen(QColor(220, 220, 220))
            p.drawText(QRectF(a.left() + 6, a.top() + 4, 160, 16), Qt.AlignLeft, f"Вход {x}  →  Выход {y}")

    def _draw_curve(self, p, ch, alpha):
        lut = imageops.curve_lut(self.curves.get(ch, imageops.IDENTITY_CURVE))
        path = QPainterPath(self.to_screen(0, float(lut[0])))
        for x in range(1, 256):
            path.lineTo(self.to_screen(x, float(lut[x])))
        c = QColor(CH_COLOR[ch])
        c.setAlpha(alpha)
        p.setPen(QPen(c, 2 if alpha == 255 else 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


class CurvesEditor(QWidget):
    """Кривые + выбор канала + сброс."""
    changed = Signal(dict)
    finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(QLabel("Канал:"))
        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        for c, label in CHANNELS:
            self.combo.addItem(label, c)
        top.addWidget(self.combo, 1)
        self.reset_btn = QToolButton()
        self.reset_btn.setText("Сброс")
        self.reset_btn.setToolTip("Сбросить кривую текущего канала")
        top.addWidget(self.reset_btn)
        lay.addLayout(top)
        self.curve = CurvesWidget()
        lay.addWidget(self.curve)
        hint = QLabel("Клик — точка, тянуть — изменить, двойной клик / ПКМ / утащить за край — удалить")
        hint.setObjectName("PanelSub")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.combo.currentIndexChanged.connect(lambda i: self.curve.set_channel(self.combo.itemData(i)))
        self.curve.changed.connect(self.changed)
        self.curve.finished.connect(self.finished)
        self.reset_btn.clicked.connect(self._reset)

    def _reset(self):
        self.curve.curves[self.curve.channel] = copy.deepcopy(imageops.IDENTITY_CURVE)
        self.curve._emit(True)

    def set_curves(self, c):
        self.curve.set_curves(c)

    def set_histogram(self, img):
        try:
            self.curve.set_histogram(imageops.histogram(img) if img is not None else None)
        except Exception:
            self.curve.set_histogram(None)


class CurvesDialog(QDialog):
    """Кривые для вставленного изображения (применяются сразу, Отмена — вернуть как было)."""

    def __init__(self, parent, curves, image, on_change):
        super().__init__(parent)
        self.setWindowTitle("Кривые")
        lay = QVBoxLayout(self)
        self.ed = CurvesEditor()
        self.ed.set_curves(curves)
        self.ed.set_histogram(image)
        self.ed.changed.connect(on_change)
        lay.addWidget(self.ed)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(340, 420)
