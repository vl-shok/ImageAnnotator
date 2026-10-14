"""Вставленное изображение (объект) и фоновое изображение документа."""
from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QGraphicsItem

from ..props import OPACITY, PropSpec
from .base import make_pen
from .shapes import ANGLE, BoxItem


def image_to_b64(img: QImage, fmt: str = "PNG") -> str:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, fmt)
    buf.close()
    return base64.b64encode(bytes(ba)).decode("ascii")


def image_from_b64(data: str) -> QImage:
    img = QImage()
    img.loadFromData(base64.b64decode(data))
    return img


ADJ_PROPS = ("brightness", "contrast", "saturation", "temperature", "curves")


class ImageItem(BoxItem):
    """Вставленное изображение. Поддерживает неразрушающие коррекцию и обрезку (src)."""
    TYPE = "image"
    TITLE = "Изображение"
    ROTATABLE = True
    SHIFT_FREES = True
    DEFAULTS = {"angle": 0.0, "keep_ratio": True, "opacity": 1.0, "border": False, "border_color": "#ff2020", "border_width": 2.0,
                "brightness": 0, "contrast": 0, "saturation": 100, "temperature": 0, "curves": None}
    PROPS = [
        ANGLE,
        PropSpec("keep_ratio", "Сохранять пропорции (углы)", "bool", "Изображение"),
        PropSpec("border", "Рамка", "bool", "Изображение"),
        PropSpec("border_color", "Цвет рамки", "color", "Изображение"),
        PropSpec("border_width", "Толщина рамки", "float", "Изображение", min=0.5, max=50, step=0.5, suffix=" px"),
        OPACITY,
    ]
    # коррекция цвета (brightness/contrast/saturation/temperature/curves) — в окне «Коррекция цвета…»

    def __init__(self, image: QImage | None = None, rect: QRectF | None = None, props=None):
        if image is not None and rect is None:
            rect = QRectF(0, 0, image.width(), image.height())
        super().__init__(rect, props)
        self.image = image if image is not None else QImage()
        self.src = QRectF(0, 0, self.image.width(), self.image.height())
        self._pix = None
        self._pix_key = None

    # --------------------------------------------------------- display
    def color_params(self) -> dict:
        return {k: self.props.get(k) for k in ("brightness", "contrast", "saturation", "temperature", "curves")}

    def pixmap(self):
        key = repr([self.props.get(k) for k in ADJ_PROPS])
        if (self._pix is None or self._pix_key != key) and not self.image.isNull():
            from ..imageops import apply_color
            self._pix = QPixmap.fromImage(apply_color(self.image, self.color_params()))
            self._pix_key = key
        return self._pix

    def props_changed(self):
        self.update()

    # --------------------------------------------------------- serialization
    def geom_to_dict(self, full=False):
        d = super().geom_to_dict(full)
        s = self.src
        d["src"] = [round(s.x(), 3), round(s.y(), 3), round(s.width(), 3), round(s.height(), 3)]
        if full:
            d["image"] = image_to_b64(self.image)
        return d

    def geom_from_dict(self, d):
        super().geom_from_dict(d)
        if d.get("image"):
            self.image = image_from_b64(d["image"])
            self._pix = None
        if d.get("src"):
            x, y, w, h = d["src"]
            self.src = QRectF(float(x), float(y), float(w), float(h))
        else:
            self.src = QRectF(0, 0, self.image.width(), self.image.height())

    # --------------------------------------------------------- crop
    def crop_to_scene_rect(self, scene_rect: QRectF):
        """Неразрушающая обрезка: видимая часть = пересечение с scene_rect."""
        r = self.rect
        local = self.mapFromScene(scene_rect).boundingRect().intersected(r)
        if local.width() < 1 or local.height() < 1 or r.width() <= 0 or r.height() <= 0:
            return
        sx = self.src.width() / r.width()
        sy = self.src.height() / r.height()
        self.src = QRectF(self.src.x() + (local.x() - r.x()) * sx,
                          self.src.y() + (local.y() - r.y()) * sy,
                          local.width() * sx, local.height() * sy)
        anchor = self.mapToScene(local.topLeft())
        self._apply_rect(QRectF(0, 0, local.width(), local.height()), QPointF(0, 0), anchor)

    def reset_crop(self):
        """Вернуть полное изображение, сохранив текущий масштаб и поворот."""
        if self.src.width() <= 0 or self.src.height() <= 0:
            return
        r = self.rect
        kx = r.width() / self.src.width()
        ky = r.height() / self.src.height()
        new = QRectF(r.x() - self.src.x() * kx, r.y() - self.src.y() * ky,
                     self.image.width() * kx, self.image.height() * ky)
        self.src = QRectF(0, 0, self.image.width(), self.image.height())
        anchor = self.mapToScene(r.topLeft())
        self._apply_rect(QRectF(0, 0, new.width(), new.height()), r.topLeft() - new.topLeft(), anchor)

    def is_cropped(self):
        return self.src != QRectF(0, 0, self.image.width(), self.image.height())

    # --------------------------------------------------------- handles
    def keep_aspect_for(self, hid, constrain):
        """Углы — с сохранением пропорций (если включено), Shift — наоборот; стороны — свободно."""
        if len(hid) != 2:
            return False
        return bool(self.props.get("keep_ratio", True)) != bool(constrain)

    # --------------------------------------------------------- raster
    def pixel_rect(self, scene_rect: QRectF):
        """Область изображения (пиксели self.image) и локальный прямоугольник под scene_rect."""
        r = self.rect
        if r.width() <= 0 or r.height() <= 0 or self.image.isNull():
            return None, None
        local = self.mapFromScene(QRectF(scene_rect)).boundingRect().intersected(r)
        if local.width() < 1 or local.height() < 1:
            return None, None
        sx = self.src.width() / r.width()
        sy = self.src.height() / r.height()
        px = QRectF(self.src.x() + (local.x() - r.x()) * sx, self.src.y() + (local.y() - r.y()) * sy,
                    local.width() * sx, local.height() * sy).toAlignedRect()
        px = px.intersected(self.image.rect())
        if px.isEmpty():
            return None, None
        return px, local

    def set_image(self, img: QImage):
        self.image = img
        self._pix = None
        self.update()

    def filled_hit(self):
        return True

    def hit_width(self):
        return 1.0

    def margin(self):
        return float(self.props.get("border_width", 2)) + 2

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.Antialiasing)
        self.paint_opacity(painter)
        pm = self.pixmap()
        if pm is not None:
            painter.drawPixmap(self.rect, pm, self.src)
        if self.props.get("border"):
            pen = make_pen(self.props["border_color"], self.props["border_width"])
            pen.setJoinStyle(Qt.MiterJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.rect)

    def describe(self):
        return f"Изображение {self.image.width()}×{self.image.height()}" + (" (обрезано)" if self.is_cropped() else "")


class BackgroundItem(QGraphicsItem):
    """Исходная фотография (растровый слой). Не является аннотацией."""

    def __init__(self):
        super().__init__()
        self._pix: QPixmap | None = None
        self.setZValue(-1)

    def set_image(self, img: QImage | None):
        self.prepareGeometryChange()
        self._pix = QPixmap.fromImage(img) if img is not None and not img.isNull() else None
        self.update()

    def boundingRect(self):
        if self._pix is None:
            return QRectF()
        return QRectF(0, 0, self._pix.width(), self._pix.height())

    def paint(self, painter, option, widget=None):
        if self._pix is not None:
            painter.drawPixmap(QPointF(0, 0), self._pix)
