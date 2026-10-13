"""Editor — контроллер: все редактирующие операции над документом проходят здесь
(с поддержкой Undo/Redo). UI (окно, панели, инструменты) вызывает методы Editor.
"""
from __future__ import annotations

import copy
import json
import os
import uuid

from PySide6.QtCore import QMimeData, QObject, QPointF, QRect, QRectF, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QUndoStack

from . import imageops, styles
from .commands import AddCmd, AdjustCmd, LayersCmd, RasterCmd, RemoveCmd, StateCmd
from .document import BG_LAYER_ID, Document, Layer
from .items import ImageItem, create_from_dict
from .selection import SelectionManager
from .snap import SnapManager

MIME_ITEMS = "application/x-imageannotator-items"
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")


class Editor(QObject):
    toolChanged = Signal(str)
    message = Signal(str)
    rasterSelectionChanged = Signal()
    snapChanged = Signal()
    cropChanged = Signal()
    filterChanged = Signal()

    def __init__(self):
        super().__init__()
        self.doc = Document()
        self.sel = SelectionManager(self.doc)
        self.snap = SnapManager()
        self.undo = QUndoStack(self)
        self.undo.setUndoLimit(300)
        self.view = None          # CanvasView, устанавливается окном
        self.tools = {}
        self.tool = None
        self.session = 0          # для слияния последовательных правок свойства
        self.raster_sel: QRect | None = None
        self.ask_text = lambda initial, title="Текст": None  # переопределяется UI
        self.paste_offset = 0
        self.sel.changed.connect(self.bump_session)
        self.doc.backgroundChanged.connect(self._update_style_scale)

    def _update_style_scale(self):
        bg = self.doc.background
        styles.set_scale_for_image(bg.width(), bg.height()) if bg is not None else styles.set_scale_for_image(0, 0)

    # ================================================================ helpers
    def bump_session(self):
        self.session += 1

    def push(self, cmd):
        self.undo.push(cmd)

    def change_items(self, items, fn, text="Изменение", merge_key=None):
        items = list(items)
        if not items:
            return
        before = [i.state() for i in items]
        fn()
        after = [i.state() for i in items]
        if before == after:
            return
        self.push(StateCmd(self.doc, items, before, after, text, merge_key))

    def record_items(self, items, before, text="Изменение"):
        """Состояния «до» уже сняты, изменения сделаны (например, перетаскиванием)."""
        items = list(items)
        after = [i.state() for i in items]
        if before != after:
            self.push(StateCmd(self.doc, items, before, after, text))

    def change_layers(self, fn, text="Слои", merge_key=None):
        before = self.doc.capture_layers()
        res = fn()
        after = self.doc.capture_layers()
        if before != after:
            self.push(LayersCmd(self.doc, before, after, text, merge_key))
        else:
            self.doc.layersChanged.emit()
        return res

    def add_items(self, items, text="Добавить", select=True):
        items = list(items)
        if not items:
            return
        self.push(AddCmd(self.doc, items, text))
        if select:
            self.sel.set(items)

    # ================================================================ tools
    def register_tool(self, tool):
        self.tools[tool.name] = tool

    def set_tool(self, name):
        if self.tool is not None and self.tool.name == name:
            return
        if self.tool is not None:
            self.tool.deactivate()
        self.tool = self.tools[name]
        self.tool.activate()
        if name != "raster":
            self.set_raster_selection(None)
        self.toolChanged.emit(name)

    def set_raster_selection(self, r: QRect | None):
        self.raster_sel = r
        self.rasterSelectionChanged.emit()
        if self.view:
            self.view.viewport().update()

    def raster_mode(self) -> bool:
        return self.tool is not None and self.tool.name == "raster" and self.raster_sel is not None

    # ================================================================ properties
    def set_prop(self, name, value):
        items = [i for i in self.sel.items if name in i.props and not i.locked]
        if not items:
            return

        def fn():
            for i in items:
                i.set_prop(name, value)
        self.change_items(items, fn, "Свойство", merge_key=("prop", name, self.session))
        for t in {i.TYPE for i in items}:
            styles.remember(t, name, value)

    def set_common(self, name, value):
        """Общие атрибуты: layer / locked / visible."""
        items = list(self.sel.items)
        if name == "layer":
            self.move_to_layer(items, value)
            return

        def fn():
            for i in items:
                if name == "locked":
                    i.locked = bool(value)
                elif name == "visible":
                    i.obj_visible = bool(value)
        self.change_items(items, fn, "Свойство")
        self.doc.itemsChanged.emit()

    # ================================================================ object ops
    def edit_item(self, item):
        """Двойной клик: правка текста / номера."""
        if item.locked:
            self.message.emit("Объект заблокирован (Ctrl+L — разблокировать)")
            return
        if "text" in item.props:
            txt = self.ask_text(item.props.get("text", ""), "Редактировать текст")
            if txt is not None and txt != item.props.get("text"):
                self.change_items([item], lambda: item.set_prop("text", txt), "Текст")
        elif item.TYPE == "number":
            txt = self.ask_text(str(item.props.get("number", 1)), "Номер маркера")
            if txt is not None and txt.strip().isdigit():
                n = int(txt.strip())
                self.change_items([item], lambda: item.set_prop("number", n), "Номер")

    def delete_selected(self):
        items = [i for i in self.sel.items if not i.locked]
        if items:
            self.sel.clear()
            self.push(RemoveCmd(self.doc, items, "Удалить"))

    def _items_to_mime(self, items) -> QMimeData:
        data = [i.to_dict(full=True) for i in sorted(items, key=lambda i: (self.doc.layer_index(i.layer_id), i.z_local))]
        md = QMimeData()
        md.setData(MIME_ITEMS, json.dumps(data).encode("utf-8"))
        return md

    def copy(self):
        if self.raster_mode():
            return self.raster_copy()
        if not self.sel.items:
            return
        QGuiApplication.clipboard().setMimeData(self._items_to_mime(self.sel.items))
        self.paste_offset = 0
        self.message.emit(f"Скопировано объектов: {len(self.sel.items)}")

    def cut(self):
        if self.raster_mode():
            return self.raster_cut()
        if not self.sel.items:
            return
        self.copy()
        self.delete_selected()

    def _instantiate(self, dicts, offset: QPointF):
        items = []
        group_map = {}
        layer_id = self.doc.target_layer_id()
        for d in dicts:
            d = dict(d)
            d["id"] = None
            if d.get("group"):
                d["group"] = group_map.setdefault(d["group"], uuid.uuid4().hex[:8])
            it = create_from_dict(d, keep_id=False)
            it.setPos(it.pos() + offset)
            if self.doc.layer(it.layer_id) is None or it.layer_id == BG_LAYER_ID:
                it.layer_id = layer_id
            it.z_local = 1e9 + len(items)
            items.append(it)
        return items

    def paste(self, at: QPointF | None = None):
        md = QGuiApplication.clipboard().mimeData()
        if md is None:
            return
        if md.hasFormat(MIME_ITEMS):
            dicts = json.loads(bytes(md.data(MIME_ITEMS)).decode("utf-8"))
            self.paste_offset += 20
            items = self._instantiate(dicts, QPointF(self.paste_offset, self.paste_offset))
            self.add_items(items, "Вставить")
            return
        img = None
        if md.hasImage():
            img = QImage(md.imageData())
        elif md.hasUrls():
            for u in md.urls():
                p = u.toLocalFile()
                if p.lower().endswith(IMAGE_EXTS):
                    img = QImage(p)
                    break
        if img is not None and not img.isNull():
            if self.doc.background is None:
                self.new_from_image(img)
            else:
                self.insert_image(img, at)

    def duplicate(self):
        if not self.sel.items:
            return
        dicts = [i.to_dict(full=True) for i in self.sel.items]
        items = self._instantiate(dicts, QPointF(20, 20))
        self.add_items(items, "Дублировать")

    def nudge(self, dx, dy):
        items = [i for i in self.sel.items if self.sel.is_movable(i)]
        if not items:
            return

        def fn():
            for i in items:
                i.moveBy(dx, dy)
        self.change_items(items, fn, "Сдвиг", merge_key=("nudge", self.session))

    def toggle_lock(self):
        items = list(self.sel.items)
        if not items:
            return
        new = not all(i.locked for i in items)

        def fn():
            for i in items:
                i.locked = new
        self.change_items(items, fn, "Блокировка")
        self.doc.itemsChanged.emit()

    # ------------------------------------------------------------ z-order
    def reorder(self, mode):
        """mode: front | back | forward | backward (внутри слоя)."""
        items = list(self.sel.items)
        if not items:
            return
        layers = {i.layer_id for i in items}
        all_aff = [i for i in self.doc.items() if i.layer_id in layers]

        def fn():
            for lid in layers:
                seq = self.doc.items_in_layer(lid)
                chosen = [i for i in seq if i in items]
                if mode == "front":
                    seq = [i for i in seq if i not in chosen] + chosen
                elif mode == "back":
                    seq = chosen + [i for i in seq if i not in chosen]
                elif mode == "forward":
                    for idx in range(len(seq) - 2, -1, -1):
                        if seq[idx] in chosen and seq[idx + 1] not in chosen:
                            seq[idx], seq[idx + 1] = seq[idx + 1], seq[idx]
                elif mode == "backward":
                    for idx in range(1, len(seq)):
                        if seq[idx] in chosen and seq[idx - 1] not in chosen:
                            seq[idx], seq[idx - 1] = seq[idx - 1], seq[idx]
                for z, it in enumerate(seq):
                    it.z_local = float(z)
            self.doc.relayer()
        self.change_items(all_aff, fn, "Порядок")
        self.doc.itemsChanged.emit()

    # ------------------------------------------------------------ groups
    def group(self):
        items = list(self.sel.items)
        if len(items) < 2:
            return
        gid = uuid.uuid4().hex[:8]

        def fn():
            for i in items:
                i.group_id = gid
        self.change_items(items, fn, "Группировать")
        self.message.emit(f"Сгруппировано объектов: {len(items)}")

    def ungroup(self):
        items = [i for i in self.sel.items if i.group_id]
        if not items:
            return

        def fn():
            for i in items:
                i.group_id = None
        self.change_items(items, fn, "Разгруппировать")

    # ------------------------------------------------------------ align
    def align(self, mode):
        items = [i for i in self.sel.items if self.sel.is_movable(i)]
        if len(items) < 2:
            return
        # группа выравнивается как единое целое
        units = {}
        for i in items:
            units.setdefault(i.group_id or i.uid, []).append(i)
        rects = {}
        for k, its in units.items():
            r = QRectF()
            for i in its:
                r = r.united(i.content_rect())
            rects[k] = r
        total = QRectF()
        for r in rects.values():
            total = total.united(r)

        def fn():
            for k, its in units.items():
                r = rects[k]
                dx = dy = 0.0
                if mode == "left":
                    dx = total.left() - r.left()
                elif mode == "right":
                    dx = total.right() - r.right()
                elif mode == "hcenter":
                    dx = total.center().x() - r.center().x()
                elif mode == "top":
                    dy = total.top() - r.top()
                elif mode == "bottom":
                    dy = total.bottom() - r.bottom()
                elif mode == "vcenter":
                    dy = total.center().y() - r.center().y()
                for i in its:
                    i.moveBy(dx, dy)
        self.change_items(items, fn, "Выравнивание")

    # ================================================================ layers
    def move_to_layer(self, items, lid, index=None):
        """Перенести объекты в слой. index — позиция сверху вниз внутри слоя (None = наверх)."""
        items = [i for i in items if self.doc.contains(i)]
        target = self.doc.layer(lid)
        if not items or target is None or target.is_bg:
            return

        def fn():
            seq = [i for i in self.doc.items_in_layer(lid) if i not in items]
            # seq — снизу вверх; index считается сверху вниз (как в панели)
            moving = sorted(items, key=lambda i: (self.doc.layer_index(i.layer_id), i.z_local))
            if index is None:
                pos = len(seq)
            else:
                pos = max(0, min(len(seq), len(seq) - index))
            seq[pos:pos] = moving
            for i in moving:
                i.layer_id = lid
            for z, it in enumerate(seq):
                it.z_local = float(z)
            self.doc.relayer()
        self.change_layers(fn, "Перенос в слой")

    def set_active_layer(self, lid):
        if self.doc.layer(lid) is not None and lid != self.doc.active_layer_id:
            self.doc.active_layer_id = lid
            self.doc.layersChanged.emit()

    def add_layer(self, name=None):
        def fn():
            ann = self.doc.annotation_layers()
            nm = name or f"Слой {len(ann) + 1}"
            existing = {l.name for l in self.doc.layers}
            n = len(ann) + 1
            while nm in existing:
                n += 1
                nm = f"Слой {n}"
            layer = Layer(name=nm)
            idx = self.doc.layer_index(self.doc.active_layer_id)
            self.doc.layers.insert(max(1, idx + 1), layer)
            self.doc.active_layer_id = layer.id
            return layer
        return self.change_layers(fn, "Новый слой")

    def delete_layer(self, lid):
        layer = self.doc.layer(lid)
        if layer is None or layer.is_bg:
            return
        items = self.doc.items_in_layer(lid)
        self.undo.beginMacro("Удалить слой")
        self.sel.set([i for i in self.sel.items if i not in items])
        if items:
            self.push(RemoveCmd(self.doc, items))

        def fn():
            idx = self.doc.layer_index(lid)
            self.doc.layers.remove(layer)
            if self.doc.active_layer_id == lid:
                ann = self.doc.annotation_layers()
                if ann:
                    self.doc.active_layer_id = self.doc.layers[max(1, min(idx, len(self.doc.layers) - 1))].id
                else:
                    self.doc.active_layer_id = BG_LAYER_ID
        self.change_layers(fn, "Удалить слой")
        self.undo.endMacro()

    def rename_layer(self, lid, name):
        layer = self.doc.layer(lid)
        if layer is None or not name.strip() or name == layer.name:
            return

        def fn():
            layer.name = name.strip()
        self.change_layers(fn, "Переименовать слой")

    def set_layer_attr(self, lid, attr, value, merge=False):
        layer = self.doc.layer(lid)
        if layer is None:
            return

        def fn():
            setattr(layer, attr, value)
            self.doc.relayer()
        self.change_layers(fn, "Слой", merge_key=("layer", lid, attr, self.session) if merge else None)
        if attr in ("visible", "locked"):
            self.sel._prune()
            if attr == "locked" and value:
                self.sel.set([i for i in self.sel.items if i.layer_id != lid])

    def solo_layer(self, lid):
        """Alt+клик по «глазу»: показать только этот слой (повторно — показать все)."""
        others = [l for l in self.doc.layers if l.id != lid]
        only = all(not l.visible for l in others) and self.doc.layer(lid).visible

        def fn():
            for l in self.doc.layers:
                l.visible = True if only else (l.id == lid)
            self.doc.relayer()
        self.change_layers(fn, "Видимость слоёв")
        self.sel._prune()

    def move_layer(self, lid, delta):
        idx = self.doc.layer_index(lid)
        new = idx + delta
        if idx <= 0 or new < 1 or new >= len(self.doc.layers):
            return
        self.move_layer_to(lid, new)

    def move_layer_to(self, lid, new_index):
        idx = self.doc.layer_index(lid)
        if idx <= 0:
            return
        new_index = max(1, min(len(self.doc.layers) - 1, new_index))
        if new_index == idx:
            return

        def fn():
            layer = self.doc.layers.pop(idx)
            self.doc.layers.insert(new_index, layer)
            self.doc.relayer()
        self.change_layers(fn, "Порядок слоёв")

    def merge_down(self, lid):
        idx = self.doc.layer_index(lid)
        if idx <= 1:
            self.message.emit("Ниже нет слоя аннотаций для объединения")
            return
        below = self.doc.layers[idx - 1]
        layer = self.doc.layers[idx]

        def fn():
            base = len(self.doc.items_in_layer(below.id))
            for k, it in enumerate(self.doc.items_in_layer(lid)):
                it.layer_id = below.id
                it.z_local = float(base + k)
            self.doc.layers.remove(layer)
            self.doc.active_layer_id = below.id
            self.doc.relayer()
        self.change_layers(fn, "Объединить слои")

    def duplicate_layer(self, lid):
        layer = self.doc.layer(lid)
        if layer is None or layer.is_bg:
            return
        self.undo.beginMacro("Дублировать слой")
        new = self.add_layer(layer.name + " копия")
        dicts = [i.to_dict(full=True) for i in self.doc.items_in_layer(lid)]
        items = self._instantiate(dicts, QPointF(0, 0))
        for k, it in enumerate(items):
            it.layer_id = new.id
            it.z_local = float(k)
        if items:
            self.push(AddCmd(self.doc, items, "Дублировать слой"))
        self.undo.endMacro()

    def select_layer_objects(self, lid):
        self.sel.set(self.doc.items_in_layer(lid))

    # ================================================================ images / documents
    def new_from_image(self, img: QImage, path=None, source=None):
        self.sel.clear()
        self.set_raster_selection(None)
        self.doc.reset()
        self.doc.set_background(img, source)
        self.doc.image_path = path
        self.undo.clear()
        if self.view:
            self.view.fit()

    def new_blank(self, w, h, color: QColor):
        img = QImage(int(w), int(h), QImage.Format_ARGB32_Premultiplied)
        img.fill(color)
        self.new_from_image(img)
        self.doc.canvas_color = color.name()

    def open_image(self, path) -> bool:
        with open(path, "rb") as f:
            raw = f.read()
        img = QImage()
        if not img.loadFromData(raw):
            return False
        fmt = os.path.splitext(path)[1].lower().lstrip(".") or "png"
        self.new_from_image(img, path, (raw, fmt))
        self.undo.setClean()
        return True

    def open_project(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.sel.clear()
        self.set_raster_selection(None)
        self.doc.load_dict(data)
        self.doc.project_path = path
        self.undo.clear()
        self.undo.setClean()
        if self.view:
            self.view.fit()

    def save_project(self, path):
        data = self.doc.to_dict()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        self.doc.project_path = path
        self.undo.setClean()

    def insert_image(self, img: QImage, at: QPointF | None = None):
        if img is None or img.isNull():
            return
        item = ImageItem(img.convertToFormat(QImage.Format_ARGB32_Premultiplied))
        canvas = self.doc.canvas_rect()
        if not canvas.isEmpty():
            maxw, maxh = canvas.width() * 0.45, canvas.height() * 0.45
            k = min(1.0, maxw / max(1, img.width()), maxh / max(1, img.height()))
            item.rect = QRectF(0, 0, img.width() * k, img.height() * k)
        if at is None:
            at = self.view.visible_center() if self.view else canvas.center()
        item.setPos(at - item.rect.center())
        self.add_items([item], "Вставить изображение")

    # ================================================================ raster ops
    def _raster_change(self, new_img, text, keep_source=False):
        before = (self.doc.background, self.doc.bg_source)
        after = (new_img, self.doc.bg_source if keep_source else None)
        self.push(RasterCmd(self.doc, before, after, text))

    def _sel_rect(self) -> QRect | None:
        if self.raster_sel is None or self.doc.background is None:
            return None
        r = self.raster_sel.intersected(QRect(0, 0, self.doc.background.width(), self.doc.background.height()))
        return None if r.isEmpty() else r

    def raster_copy(self):
        r = self._sel_rect()
        if r is None:
            return
        QGuiApplication.clipboard().setImage(self.doc.display_image.copy(r))
        self.message.emit(f"Скопирована область {r.width()}×{r.height()}")

    def raster_delete(self):
        r = self._sel_rect()
        if r is None:
            return
        self._raster_change(imageops.fill_rect(self.doc.background, r, QColor(self.doc.canvas_color)), "Очистить область")

    def raster_cut(self):
        self.raster_copy()
        self.raster_delete()

    def raster_fill(self, color: QColor):
        r = self._sel_rect()
        if r is None:
            return
        self._raster_change(imageops.fill_rect(self.doc.background, r, color), "Заливка области")

    def raster_opacity(self, value: float):
        r = self._sel_rect()
        if r is None:
            return
        self._raster_change(imageops.set_rect_opacity(self.doc.background, r, value), "Прозрачность области")

    def raster_to_object(self):
        """Скопировать выделенную область в новый объект-изображение (на месте)."""
        r = self._sel_rect()
        if r is None:
            return
        img = self.doc.display_image.copy(r)
        item = ImageItem(img)
        item.setPos(QPointF(r.topLeft()))
        self.add_items([item], "Область → объект")
        self.set_tool("select")

    def crop_to_selection(self):
        r = self._sel_rect()
        if r is None:
            return
        self._resize_canvas(-r.left(), -r.top(), r.right() - self.doc.background.width() + 1,
                            r.bottom() - self.doc.background.height() + 1, QColor(self.doc.canvas_color), "Обрезать")
        self.set_raster_selection(None)

    def resize_canvas(self, left, top, right, bottom, color: QColor):
        self._resize_canvas(left, top, right, bottom, color, "Размер холста")

    def _resize_canvas(self, left, top, right, bottom, color, text):
        if self.doc.background is None:
            return
        img = imageops.expand_canvas(self.doc.background, left, top, right, bottom, color)
        items = self.doc.items()
        self.undo.beginMacro(text)
        self._raster_change(img, text)
        if items and (left or top):
            def fn():
                for i in items:
                    i.moveBy(left, top)
            self.change_items(items, fn, text)
        self.undo.endMacro()
        if self.view:
            self.view.fit()

    # ================================================================ color correction
    def set_background_color(self, before: dict, after: dict):
        """Записать в историю коррекцию цвета фона (изменение уже показано предпросмотром)."""
        self.doc.set_color(after, immediate=True)
        if before != after:
            self.push(AdjustCmd(self.doc, before, after, "Коррекция цвета фото"))

    def set_item_color(self, item, before: dict, after: dict):
        if before == after:
            return
        b = item.state()
        b["props"].update(copy.deepcopy(before))
        item.props.update(copy.deepcopy(after))
        item.update()
        self.push(StateCmd(self.doc, [item], [b], [item.state()], "Коррекция цвета изображения"))

    def reset_background_color(self):
        self.set_background_color(copy.deepcopy(self.doc.color), copy.deepcopy(imageops.DEFAULT_COLOR))

    # ================================================================ raster: blur
    def raster_blur_preview(self, sigma):
        """Вернуть изображение с размытой областью (без записи в историю)."""
        r = self._sel_rect()
        if r is None:
            return None
        return imageops.blur_rect(self.doc.background, r, sigma)

    def raster_blur(self, sigma, original=None):
        r = self._sel_rect()
        if r is None:
            return
        src = original if original is not None else self.doc.background
        out = imageops.blur_rect(src, r, sigma)
        before = (src, self.doc.bg_source)
        self.push(RasterCmd(self.doc, before, (out, None), "Размытие по Гауссу"))

    # ================================================================ crop / canvas
    def crop_canvas_to(self, rect: QRectF, color: QColor | None = None):
        """Обрезать/расширить холст до прямоугольника rect (координаты сцены)."""
        bg = self.doc.background
        if bg is None:
            return
        x0, y0 = int(round(rect.left())), int(round(rect.top()))
        x1, y1 = int(round(rect.right())), int(round(rect.bottom()))
        if x1 - x0 < 1 or y1 - y0 < 1:
            return
        left, top = -x0, -y0
        right, bottom = x1 - bg.width(), y1 - bg.height()
        if not any((left, top, right, bottom)):
            return
        self._resize_canvas(left, top, right, bottom, color or QColor(self.doc.canvas_color),
                            "Обрезка / размер холста")

    def crop_image_item(self, item, scene_rect: QRectF):
        if item.TYPE != "image":
            return
        self.change_items([item], lambda: item.crop_to_scene_rect(scene_rect), "Обрезка изображения")
        self.doc.itemsChanged.emit()
        self.sel.changed.emit()

    # ================================================================ vertices
    def delete_vertex(self, item, idx):
        if not hasattr(item, "points") or item.TYPE not in ("polyline", "polygon"):
            return
        if len(item.points) <= item.MIN_POINTS:
            self.message.emit(f"Минимум вершин: {item.MIN_POINTS}")
            return
        self.change_items([item], lambda: item.remove_vertex(idx), "Удалить вершину")

    def straighten(self, item):
        if getattr(item, "ctrl", None) is None:
            return
        self.change_items([item], item.straighten, "Выпрямить")

    # ================================================================ groups
    def groups(self) -> dict:
        out = {}
        for it in self.doc.items_sorted():
            if it.group_id:
                out.setdefault(it.group_id, []).append(it)
        return out

    def remove_from_groups(self, items):
        """Убрать объекты из их групп; группы из одного объекта распускаются."""
        items = [i for i in items if i.group_id]
        if not items:
            return
        affected = set(i.group_id for i in items)
        members = [i for i in self.doc.items() if i.group_id in affected]

        def fn():
            for i in items:
                i.group_id = None
            for gid in affected:
                rest = [i for i in members if i.group_id == gid]
                if len(rest) < 2:
                    for i in rest:
                        i.group_id = None
        self.change_items(members, fn, "Изменение групп")
        self.doc.itemsChanged.emit()
