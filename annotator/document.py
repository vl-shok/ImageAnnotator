"""Документ: фон (растр), слои, объекты-аннотации, сериализация."""
from __future__ import annotations

import base64
import copy
import uuid

from PySide6.QtCore import QObject, QRectF, QTimer, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QGraphicsScene

from . import imageops
from .items import AnnotationItem, BackgroundItem, create_from_dict
from .items.image import image_from_b64, image_to_b64

FORMAT_VERSION = 3
PROJECT_EXT = ".iap"
BG_LAYER_ID = "bg"


class Layer:
    def __init__(self, lid=None, name="Слой", visible=True, locked=False, opacity=1.0, is_bg=False):
        self.id = lid or uuid.uuid4().hex[:8]
        self.name = name
        self.visible = visible
        self.locked = locked
        self.opacity = opacity
        self.is_bg = is_bg

    def to_dict(self):
        return {"id": self.id, "name": self.name, "visible": self.visible, "locked": self.locked,
                "opacity": self.opacity, "is_bg": self.is_bg}

    @classmethod
    def from_dict(cls, d):
        return cls(d["id"], d.get("name", "Слой"), d.get("visible", True), d.get("locked", False),
                   float(d.get("opacity", 1.0)), d.get("is_bg", False))


class Document(QObject):
    itemsChanged = Signal()      # добавление/удаление/порядок/слои объектов
    itemsModified = Signal()     # изменились свойства/геометрия объектов
    layersChanged = Signal()
    backgroundChanged = Signal()
    adjustChanged = Signal()

    def __init__(self):
        super().__init__()
        from .items.magnifier import MagnifierItem
        MagnifierItem.source_provider = staticmethod(lambda: self.display_image)
        self.scene = QGraphicsScene()
        self.scene.setItemIndexMethod(QGraphicsScene.NoIndex)
        self.bg_item = BackgroundItem()
        self.scene.addItem(self.bg_item)
        self._items: list[AnnotationItem] = []
        self._adj_timer = QTimer(self)
        self._adj_timer.setSingleShot(True)
        self._adj_timer.setInterval(60)
        self._adj_timer.timeout.connect(self._update_display_now)
        self.reset()

    # ================================================================ basic
    def reset(self):
        for it in list(self._items):
            self.scene.removeItem(it)
        self._items.clear()
        self.background: QImage | None = None
        self.bg_source: tuple[bytes, str] | None = None
        self.display_image: QImage | None = None
        self.color = copy.deepcopy(imageops.DEFAULT_COLOR)  # коррекция цвета фона (неразрушающая)
        self.canvas_color = "#ffffff"
        self.project_path: str | None = None
        self.image_path: str | None = None
        self.layers: list[Layer] = [Layer(BG_LAYER_ID, "Фон", is_bg=True), Layer(name="Слой 1")]
        self.active_layer_id = self.layers[1].id
        self.bg_item.set_image(None)
        self._update_scene_rect()
        self.layersChanged.emit()
        self.itemsChanged.emit()
        self.backgroundChanged.emit()

    def is_empty(self) -> bool:
        return self.background is None and not self._items

    def canvas_rect(self) -> QRectF:
        if self.background is None:
            return QRectF()
        return QRectF(0, 0, self.background.width(), self.background.height())

    def export_rect(self) -> QRectF:
        r = self.canvas_rect()
        if r.isEmpty():
            r = QRectF()
            for it in self._items:
                if it.isVisible():
                    r = r.united(it.sceneBoundingRect())
        return r

    def _update_scene_rect(self):
        r = self.canvas_rect()
        if r.isEmpty():
            r = QRectF(0, 0, 1600, 1000)
        m = max(r.width(), r.height()) * 3 + 2000
        self.scene.setSceneRect(r.adjusted(-m, -m, m, m))

    # ================================================================ background
    def set_background(self, img: QImage | None, source: tuple[bytes, str] | None = None):
        if img is not None and img.format() not in (QImage.Format_ARGB32_Premultiplied, QImage.Format_ARGB32,
                                                     QImage.Format_RGB32):
            img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self.background = img
        self.bg_source = source
        self._update_display_now()
        self._update_scene_rect()
        self.backgroundChanged.emit()

    def set_color(self, params: dict, immediate=False):
        self.color = copy.deepcopy(params)
        if immediate:
            self._update_display_now()
        else:
            self._adj_timer.start()
        self.adjustChanged.emit()

    def _update_display_now(self):
        if self.background is None:
            self.display_image = None
        else:
            self.display_image = imageops.apply_color(self.background, self.color)
        self.bg_item.set_image(self.display_image)
        for it in self._items:
            if it.TYPE == "magnifier":
                it.update()
        self.backgroundChanged.emit()

    # ================================================================ layers
    def layer(self, lid) -> Layer | None:
        for l in self.layers:
            if l.id == lid:
                return l
        return None

    def layer_index(self, lid) -> int:
        for i, l in enumerate(self.layers):
            if l.id == lid:
                return i
        return -1

    def bg_layer(self) -> Layer:
        return self.layers[0]

    def annotation_layers(self) -> list[Layer]:
        return [l for l in self.layers if not l.is_bg]

    def active_layer(self) -> Layer | None:
        return self.layer(self.active_layer_id)

    def target_layer_id(self) -> str:
        """Слой, в который попадут новые объекты."""
        l = self.active_layer()
        if l is not None and not l.is_bg:
            return l.id
        ann = self.annotation_layers()
        if not ann:
            nl = Layer(name="Слой 1")
            self.layers.append(nl)
            self.layersChanged.emit()
            ann = [nl]
        return ann[-1].id

    def layer_is_editable(self, lid) -> bool:
        l = self.layer(lid)
        return l is not None and l.visible and not l.locked

    def capture_layers(self) -> dict:
        return {
            "layers": [l.to_dict() for l in self.layers],
            "active": self.active_layer_id,
            "items": {it.uid: (it.layer_id, it.z_local, it.obj_visible, it.locked) for it in self._items},
        }

    def restore_layers(self, st: dict):
        self.layers = [Layer.from_dict(d) for d in st["layers"]]
        self.active_layer_id = st["active"]
        for it in self._items:
            if it.uid in st["items"]:
                it.layer_id, it.z_local, it.obj_visible, it.locked = st["items"][it.uid]
        self.relayer()
        self.layersChanged.emit()
        self.itemsChanged.emit()

    def relayer(self):
        """Пересчитать Z, видимость и прозрачность согласно слоям."""
        known = {l.id for l in self.layers}
        for it in self._items:
            if it.layer_id not in known or it.layer_id == BG_LAYER_ID:
                it.layer_id = self.target_layer_id()
        for li, layer in enumerate(self.layers):
            if layer.is_bg:
                self.bg_item.setVisible(layer.visible)
                self.bg_item.setOpacity(layer.opacity)
                self.bg_item.setZValue(li * 100000 - 1)
                continue
            items = sorted((i for i in self._items if i.layer_id == layer.id), key=lambda i: i.z_local)
            for rank, it in enumerate(items):
                it.z_local = float(rank)
                it.setZValue(li * 100000 + rank)
                it.setVisible(layer.visible and it.obj_visible)
                it.setOpacity(layer.opacity)

    # ================================================================ items
    def items(self) -> list[AnnotationItem]:
        return list(self._items)

    def items_in_layer(self, lid) -> list[AnnotationItem]:
        return sorted((i for i in self._items if i.layer_id == lid), key=lambda i: i.z_local)

    def find(self, uid) -> AnnotationItem | None:
        for it in self._items:
            if it.uid == uid:
                return it
        return None

    def contains(self, item) -> bool:
        return item in self._items

    def add_item(self, item: AnnotationItem, emit=True):
        if item in self._items:
            return
        if item.layer_id is None or self.layer(item.layer_id) is None or item.layer_id == BG_LAYER_ID:
            item.layer_id = self.target_layer_id()
            item.z_local = 1e9  # наверх слоя
        if item.scene() is not self.scene:
            if item.scene() is not None:
                item.scene().removeItem(item)
            self.scene.addItem(item)
        self._items.append(item)
        self.relayer()
        if emit:
            self.itemsChanged.emit()

    def remove_item(self, item: AnnotationItem, emit=True):
        if item not in self._items:
            return
        self._items.remove(item)
        if item.scene() is self.scene:
            self.scene.removeItem(item)
        if emit:
            self.itemsChanged.emit()

    def next_number(self) -> int:
        nums = [int(i.props.get("number", 0)) for i in self._items if i.TYPE == "number"]
        return (max(nums) + 1) if nums else 1

    # ================================================================ serialization
    def to_dict(self) -> dict:
        bg = None
        if self.background is not None:
            if self.bg_source is not None:
                data, fmt = self.bg_source
            else:
                data, fmt = base64.b64decode(image_to_b64(self.background, "PNG")), "png"
            bg = {"format": fmt, "data": base64.b64encode(data).decode("ascii"),
                  "width": self.background.width(), "height": self.background.height()}
        return {
            "app": "ImageAnnotator",
            "format_version": FORMAT_VERSION,
            "image_path": self.image_path,
            "background": bg,
            "canvas_color": self.canvas_color,
            "color": copy.deepcopy(self.color),
            "layers": [l.to_dict() for l in self.layers],
            "active_layer": self.active_layer_id,
            "items": [it.to_dict(full=True) for it in self.items_sorted()],
        }

    def items_sorted(self):
        return sorted(self._items, key=lambda i: (self.layer_index(i.layer_id), i.z_local))

    def load_dict(self, d: dict):
        ver = int(d.get("format_version", 1))
        if ver > FORMAT_VERSION:
            raise ValueError(f"Проект создан более новой версией программы (формат {ver}).")
        self.reset()
        bg = d.get("background")
        if bg:
            raw = base64.b64decode(bg["data"])
            img = QImage()
            img.loadFromData(raw)
            self.set_background(img, (raw, bg.get("format", "png")))
        self.image_path = d.get("image_path")
        self.canvas_color = d.get("canvas_color", "#ffffff")
        layers = [Layer.from_dict(x) for x in d.get("layers", [])]
        if not layers or not layers[0].is_bg:
            layers.insert(0, Layer(BG_LAYER_ID, "Фон", is_bg=True))
        self.layers = layers
        self.active_layer_id = d.get("active_layer") or layers[-1].id
        for idict in d.get("items", []):
            try:
                it = create_from_dict(idict)
            except KeyError:
                continue  # неизвестный тип объекта — пропускаем
            self.add_item(it, emit=False)
        self.set_color(imageops.migrate_color(d), immediate=True)
        self.relayer()
        self.layersChanged.emit()
        self.itemsChanged.emit()
