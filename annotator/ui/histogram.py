"""Компактная гистограмма изображения."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from .. import imageops


class HistogramWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = None
        self.setMinimumHeight(64)
        self.setMaximumHeight(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_image(self, img):
        try:
            self.data = imageops.histogram(img) if img is not None else None
        except Exception:  # гистограмма не критична
            self.data = None
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.fillRect(r, QColor(24, 26, 30))
        p.setPen(QColor(60, 64, 72))
        p.drawRect(r)
        if not self.data:
            p.setPen(QColor(110, 115, 125))
            p.drawText(r, Qt.AlignCenter, "нет изображения")
            return
        w, h = r.width(), r.height() - 2
        cols = [QColor(255, 70, 70, 150), QColor(70, 220, 90, 150), QColor(80, 140, 255, 150)]
        for hist, col in zip(self.data[:3], cols):
            path = QPainterPath(QPointF(r.left(), r.bottom()))
            for i, v in enumerate(hist):
                path.lineTo(r.left() + i * w / 255.0, r.bottom() - v * h)
            path.lineTo(r.right(), r.bottom())
            p.setPen(QPen(col, 1))
            c2 = QColor(col)
            c2.setAlpha(40)
            p.setBrush(c2)
            p.drawPath(path)
        luma = self.data[3]
        path = QPainterPath(QPointF(r.left(), r.bottom() - luma[0] * h))
        for i, v in enumerate(luma):
            path.lineTo(r.left() + i * w / 255.0, r.bottom() - v * h)
        p.setPen(QPen(QColor(230, 230, 230, 200), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
