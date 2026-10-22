"""Editor — контроллер: все редактирующие операции над документом проходят здесь
(с поддержкой Undo/Redo). UI (окно, панели, инструменты) вызывает методы Editor.
"""
from __future__ import annotations

import copy
import json
import os
import uuid

from PySide6.QtCore import QMimeData, QObject, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QTransform, QUndoGroup, QUndoStack

from . import imageops, styles
from .commands import AddCmd, AdjustCmd, ItemImageCmd, LayersCmd, RasterCmd, RemoveCmd, StateCmd
from .document import BG_LAYER_ID, PROJECT_EXT, Document, Layer
from .geometry import dist
from .items import ImageItem, create_from_dict
from .selection import SelectionManager
from .snap import SnapManager

MIME_ITEMS = "application/x-imageannotator-items"


class Project:
    """Открытый проект: свой документ, своя история отмены, выделение и вид холста."""

    def __init__(self, editor, name: str | None = None):
        self.doc = Document()
        self.undo = QUndoStack(editor)
        self.undo.setUndoLimit(300)
        self.name = name              # имя, заданное пользователем (для несохранённого проекта)
        self.unsaved_copy = False     # копия, которую ещё ни разу не сохраняли
        self.sel_items: list = []
        self.view_state = None        # (QTransform, центр) — масштаб и положение холста
        self.thumb = None             # миниатюра (QImage) для ленты
        self.thumb_dirty = True

    def display_name(self) -> str:
        if self.doc.project_path:
            return os.path.splitext(os.path.basename(self.doc.project_path))[0]
        if self.name:
            return self.name
        if self.doc.image_path:
            return os.path.splitext(os.path.basename(self.doc.image_path))[0]
        return "Без имени"

    def is_modified(self) -> bool:
        if self.doc.is_empty():
            return False
        return self.unsaved_copy or not self.undo.isClean()

    def is_pristine(self) -> bool:
        """Пустой нетронутый проект — его можно занять под открываемый файл."""
        return self.doc.is_empty() and self.undo.count() == 0 and not self.name
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")


class Editor(QObject):
    toolChanged = Signal(str)
    message = Signal(str)
    rasterSelectionChanged = Signal()
    snapChanged = Signal()
    cropChanged = Signal()
    filterChanged = Signal()
    styleChanged = Signal()       # изменён стиль для новых объектов (например, толщина карандаша)
    # сигналы текущего документа (при переключении проекта панели остаются подключены к редактору)
    docItemsChanged = Signal()
    docItemsModified = Signal()
    docLayersChanged = Signal()
    docBackgroundChanged = Signal()
    docAdjustChanged = Signal()
    projectsChanged = Signal()        # состав, порядок, имена, отметки «изменён»
    projectSwitched = Signal()        # активным стал другой проект

    def __init__(self):
        super().__init__()
        self.undo_group = QUndoGroup(self)
        self.projects: list[Project] = []
        self.project: Project | None = None
        self.view = None          # CanvasView, устанавливается окном
        self.tool = None
        first = self._make_project()
        self.projects.append(first)
        self.project, self.doc, self.undo = first, first.doc, first.undo
        self.undo_group.setActiveStack(self.undo)
        self.sel = SelectionManager(self.doc)
        self.snap = SnapManager()
        self.tools = {}
        self.tool = None
        self.session = 0          # для слияния последовательных правок свойства
        self.raster_sel: QRect | None = None
        self.ask_text = lambda initial, title="Текст": None  # переопределяется UI
        self.paste_offset = 0
        self.sel.changed.connect(self.bump_session)
        self.docItemsChanged.connect(self.sel.prune)
        self.docBackgroundChanged.connect(self._update_style_scale)
        self.undo_group.cleanChanged.connect(lambda *_: self.projectsChanged.emit())

    # ================================================================ projects
    def _make_project(self, name=None) -> Project:
        p = Project(self, name)
        self.undo_group.addStack(p.undo)
        d = p.doc
        for sig, fwd in ((d.itemsChanged, self.docItemsChanged), (d.itemsModified, self.docItemsModified),
                         (d.layersChanged, self.docLayersChanged), (d.backgroundChanged, self.docBackgroundChanged),
                         (d.adjustChanged, self.docAdjustChanged)):
            sig.connect((lambda doc, f: (lambda *_: f.emit() if doc is self.doc else None))(d, fwd))
        for sig in (d.itemsChanged, d.itemsModified, d.backgroundChanged, d.layersChanged, d.adjustChanged):
            sig.connect((lambda pr: (lambda *_: setattr(pr, "thumb_dirty", True)))(p))
        return p

    def new_project(self, index=None, name=None, switch=True) -> Project:
        p = self._make_project(name)
        self.projects.insert(len(self.projects) if index is None else index, p)
        if switch:
            self.switch_project(p)
        self.projectsChanged.emit()
        return p

    def project_for_open(self) -> Project:
        """Куда открыть файл: текущий пустой проект или новый (справа от текущего)."""
        if self.project is not None and self.project.is_pristine():
            return self.project
        return self.new_project(self.projects.index(self.project) + 1)

    def find_project(self, path) -> Project | None:
        """Уже открытый проект с этим файлом (.iap или фото без проекта)."""
        key = os.path.normcase(os.path.abspath(path))
        for p in self.projects:
            f = p.doc.project_path or (None if p.unsaved_copy or p.name else p.doc.image_path)
            if f and os.path.normcase(os.path.abspath(f)) == key:
                return p
        return None

    def switch_project(self, p: Project):
        if p is self.project or p not in self.projects:
            return
        old = self.project
        if self.tool is not None:
            self.tool.cancel()
        self.set_raster_selection(None)
        if old is not None and self.view is not None:
            old.view_state = self.view.view_state()
        if old is not None:
            old.sel_items = list(self.sel.items)
        self.project, self.doc, self.undo = p, p.doc, p.undo
        self.undo_group.setActiveStack(p.undo)
        self.session += 1
        if self.view is not None:
            self.view.set_document(p.doc, p.view_state)
        self.sel.set_doc(p.doc, p.sel_items)
        self._update_style_scale()
        self.projectSwitched.emit()
        for f in (self.docBackgroundChanged, self.docLayersChanged, self.docItemsChanged, self.docAdjustChanged):
            f.emit()
        self.projectsChanged.emit()

    def close_project(self, p: Project):
        """Закрыть проект (без вопросов — спрашивает окно). Последний заменяется пустым."""
        if p not in self.projects:
            return
        if p is self.project:
            i = self.projects.index(p)
            others = [q for q in self.projects if q is not p]
            if others:
                nxt = others[min(i, len(others) - 1)]
            else:
                nxt = self._make_project()
                self.projects.append(nxt)
            self.switch_project(nxt)
        self.projects.remove(p)
        self.undo_group.removeStack(p.undo)
        self.projectsChanged.emit()

    def move_project(self, p: Project, index: int):
        if p not in self.projects:
            return
        self.projects.remove(p)
        self.projects.insert(max(0, min(index, len(self.projects))), p)
        self.projectsChanged.emit()

    def unique_name(self, base: str) -> str:
        names = {q.display_name().lower() for q in self.projects}
        if base.lower() not in names:
            return base
        k = 2
        while f"{base} {k}".lower() in names:
            k += 1
        return f"{base} {k}"

    def duplicate_project(self, p: Project | None = None) -> Project:
        """Копия проекта — новый несохранённый проект справа от исходного."""
        p = p or self.project
        q = self._make_project(self.unique_name(f"{p.display_name()} (копия)"))
        q.doc.load_dict(p.doc.to_dict())
        q.doc.project_path = None
        q.doc.image_path = p.doc.image_path
        q.unsaved_copy = True
        q.view_state = self.view.view_state() if (self.view is not None and p is self.project) else p.view_state
        self.projects.insert(self.projects.index(p) + 1, q)
        self.switch_project(q)
        self.projectsChanged.emit()
        return q

    def rename_project(self, p: Project, new_name: str) -> str | None:
        """Переименовать проект; у сохранённого переименовывается и файл .iap.
        Возвращает текст ошибки или None."""
        new_name = (new_name or "").strip()
        if not new_name or any(c in '<>:"/\\|?*' for c in new_name):
            return "Недопустимое имя"
        if new_name == p.display_name():
            return None
        old = p.doc.project_path
        if old:
            new = os.path.join(os.path.dirname(old), new_name + PROJECT_EXT)
            if os.path.normcase(new) != os.path.normcase(old) and os.path.exists(new):
                return f"Файл уже существует:\n{new}"
            try:
                os.replace(old, new)
            except OSError as e:
                return f"Не удалось переименовать файл:\n{e}"
            p.doc.project_path = new
            p.name = None
        else:
            p.name = new_name
        self.projectsChanged.emit()
        return None

    def quick_png_path(self, p: Project | None = None) -> str | None:
        """Быстрый PNG: имя как в ленте, рядом с проектом (иначе — рядом с фото).
        Исходное фото не перезаписывается никогда. None — некуда (нет ни проекта, ни фото на диске)."""
        p = p or self.project
        d = p.doc
        folder = os.path.dirname(d.project_path or d.image_path or "")
        if not folder:
            return None
        path = os.path.join(folder, p.display_name() + ".png")
        if d.image_path and os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(d.image_path)):
            path = os.path.join(folder, p.display_name() + "_annotated.png")
        return path

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
        followers = self.glue_followers(items)   # приклеенные концы едут вслед за изменёнными объектами
        items += followers
        before = [i.state() for i in items]
        fn()
        self.apply_glue(followers)
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
        for k, it in enumerate(items):     # новые объекты — поверх существующих в своём слое
            if it.z_local < 1e9:
                it.z_local = 1e9 + k
        self.push(AddCmd(self.doc, items, text))
        if select:
            self.sel.set(items)

    # ================================================================ glue (приклеенные концы)
    def glue_spec(self) -> dict | None:
        """Приклеивание к объекту под последней привязкой холста (None — привязки к объекту нет)."""
        t = self.view.snap_target if self.view is not None else None
        if t is None:
            return None
        item, idx, lp = t
        if not self.doc.contains(item):
            return None
        kind = item.snap_points()[idx][1] if idx is not None else "edge"
        return {"uid": item.uid, "i": idx, "k": kind, "p": [round(lp.x(), 3), round(lp.y(), 3)]}

    @staticmethod
    def set_glue(item, key, spec):
        if key is None:
            return
        if spec is not None and spec["uid"] != item.uid:
            item.glue[key] = spec
        else:
            item.glue.pop(key, None)

    def glue_point(self, spec) -> QPointF | None:
        """Текущая точка сцены, к которой приклеен конец (None — объект удалён)."""
        target = self.doc.find(spec.get("uid"))
        if target is None:
            return None
        i = spec.get("i")
        if i is not None:
            sps = target.snap_points()
            if i < len(sps) and sps[i][1] == spec.get("k"):
                return target.mapToScene(sps[i][0])
        x, y = spec.get("p", (0, 0))
        return target.mapToScene(QPointF(x, y))

    def glue_followers(self, items) -> list:
        """Объекты, концы которых (прямо или по цепочке) приклеены к items, — в порядке обновления."""
        seen = {i.uid for i in items}
        frontier, out = set(seen), []
        while frontier:
            nxt = set()
            for it in self.doc.items():
                if it.uid in seen or not it.glue or it.locked:
                    continue
                if any(g.get("uid") in frontier for g in it.glue.values()):
                    out.append(it)
                    seen.add(it.uid)
                    nxt.add(it.uid)
            frontier = nxt
        return out

    def apply_glue(self, followers):
        for it in followers:
            ends = it.glue_ends()
            for key, spec in it.glue.items():
                if key not in ends:
                    continue
                p = self.glue_point(spec)
                if p is not None:
                    lp = it.mapFromScene(p)
                    if lp != ends[key]:
                        it.set_glue_end(key, lp)

    @staticmethod
    def unglue_detached(items):
        """Объекты сдвинули сами по себе — концы, приклеенные к объектам вне items, отклеиваются."""
        uids = {i.uid for i in items}
        for it in items:
            if it.glue:
                it.glue = {k: g for k, g in it.glue.items() if g.get("uid") in uids}

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
        self.styleChanged.emit()

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

    def release_focus(self):
        """Закончить правку: снять выделение, фокус — на холст (Ctrl+Enter в тексте)."""
        self.sel.clear()
        if self.view is not None:
            self.view.setFocus()

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
        id_map = {}
        for d in dicts:
            d = dict(d)
            old_id = d.get("id")
            d["id"] = None
            if d.get("group"):
                d["group"] = group_map.setdefault(d["group"], uuid.uuid4().hex[:8])
            it = create_from_dict(d, keep_id=False)
            it.setPos(it.pos() + offset)
            if self.doc.layer(it.layer_id) is None or it.layer_id == BG_LAYER_ID:
                it.layer_id = layer_id
            it.z_local = 1e9 + len(items)
            items.append(it)
            if old_id:
                id_map[old_id] = it.uid
        # приклеенные концы остаются приклеенными только к вставленным вместе с ними объектам
        for it in items:
            if it.glue:
                it.glue = {k: dict(g, uid=id_map[g["uid"]]) for k, g in it.glue.items() if g.get("uid") in id_map}
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
            self.unglue_detached(items)
        self.change_items(items, fn, "Сдвиг", merge_key=("nudge", self.session))

    def rotate_selected(self, deg=45.0):
        """Пробел / Shift+пробел: повернуть выделенное на ±45°.
        Один объект — вокруг своего центра, несколько — вокруг общего центра."""
        movable = [i for i in self.sel.items if self.sel.is_movable(i)]
        items = [i for i in movable if i.can_rotate()]
        if len(items) < len(movable):
            self.message.emit("Лупа не поворачивается пробелом")
        if not items:
            return
        center = None
        if len(items) > 1:
            key = (tuple(i.uid for i in items), self.undo.index())
            cached = getattr(self, "_rot_center", None)
            if cached and cached[0] == key:
                center = cached[1]      # серия нажатий — центр не «плывёт»
            else:
                r = items[0].content_rect()
                for i in items[1:]:
                    r = r.united(i.content_rect())
                center = r.center()

        def fn():
            for i in items:
                i.rotate_step(deg, center)
            self.unglue_detached(items)
        self.change_items(items, fn, f"Поворот {deg:+g}°")
        if center is not None:
            self._rot_center = ((tuple(i.uid for i in items), self.undo.index()), center)

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
            self.unglue_detached(items)
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
            self.sel.prune()
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
        self.sel.prune()

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
        self.project.unsaved_copy = False
        self.project.name = None
        self.undo.setClean()
        self.projectsChanged.emit()

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

    def raster_target(self):
        """Что редактирует выделение области: (ImageItem | None, пиксельный QRect, локальный QRectF | None).
        Если активен слой с объектами и под выделением есть вставленное изображение этого слоя —
        работаем с ним (верхним), иначе — с фото (фоном)."""
        if self.raster_sel is None:
            return None
        lid = self.doc.active_layer_id
        layer = self.doc.layer(lid)
        pools = []
        if layer is not None and not layer.is_bg:   # активен «Фон» — всегда работаем с фото
            if layer.visible:
                pools.append([i for i in self.doc.items() if i.layer_id == lid])
            pools.append(list(self.sel.items))   # или выделенное изображение с другого слоя
        for pool in pools:
            best = None
            for i in pool:
                if i.TYPE != "image" or not i.isVisible():
                    continue
                px, local = i.pixel_rect(QRectF(self.raster_sel))
                if px is not None and (best is None or i.zValue() > best[0].zValue()):
                    best = (i, px, local)
            if best is not None:
                return best
        r = self._sel_rect()
        return (None, r, None) if r is not None else None

    def _item_image_change(self, item, new_img, text):
        if item.locked:
            self.message.emit("Изображение заблокировано (Ctrl+L — разблокировать)")
            return
        self.push(ItemImageCmd(self.doc, item, item.image, new_img, text))

    def _raster_apply(self, fn, text):
        """fn(QImage, QRect) -> QImage — к фону или к вставленному изображению."""
        t = self.raster_target()
        if t is None:
            return
        item, r, _ = t
        if item is None:
            self._raster_change(fn(self.doc.background, r), text)
        else:
            self._item_image_change(item, fn(item.image, r), text)

    def raster_copy_image(self) -> QImage | None:
        t = self.raster_target()
        if t is None:
            return None
        item, r, local = t
        if item is None:
            return self.doc.display_image.copy(r)
        img = imageops.apply_color(item.image, item.color_params()).copy(r)
        w, h = max(1, round(local.width())), max(1, round(local.height()))
        if (w, h) != (img.width(), img.height()):
            img = img.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return img

    def raster_copy(self):
        img = self.raster_copy_image()
        if img is None:
            return
        QGuiApplication.clipboard().setImage(img)
        self.message.emit(f"Скопирована область {img.width()}×{img.height()}")

    def raster_delete(self):
        t = self.raster_target()
        if t is None:
            return
        if t[0] is None:
            self._raster_change(imageops.fill_rect(self.doc.background, t[1], QColor(self.doc.canvas_color)),
                                "Очистить область")
        else:   # во вставленном изображении — прозрачная «дыра»
            self._item_image_change(t[0], imageops.set_rect_opacity(t[0].image, t[1], 0.0), "Очистить область")

    def raster_cut(self):
        self.raster_copy()
        self.raster_delete()

    def raster_fill(self, color: QColor):
        self._raster_apply(lambda img, r: imageops.fill_rect(img, r, color), "Заливка области")

    def raster_opacity(self, value: float):
        self._raster_apply(lambda img, r: imageops.set_rect_opacity(img, r, value), "Прозрачность области")

    def raster_to_object(self):
        """Скопировать выделенную область в новый объект-изображение (на месте)."""
        t = self.raster_target()
        if t is None:
            return
        item, r, local = t
        if item is None:
            new = ImageItem(self.doc.display_image.copy(r))
            new.setPos(QPointF(r.topLeft()))
        else:
            new = ImageItem(item.image.copy(r))
            for k in ("brightness", "contrast", "saturation", "temperature", "curves", "keep_ratio"):
                new.props[k] = copy.deepcopy(item.props.get(k))
            new.layer_id = item.layer_id
            new.rect = QRectF(0, 0, local.width(), local.height())
            new.props["angle"] = item.angle()
            new.setPos(item.mapToScene(local.topLeft()))
            new.setTransformOriginPoint(new.rect.center())
            new.setRotation(new.angle())
            new.setPos(new.pos() + (item.mapToScene(local.topLeft()) - new.mapToScene(QPointF(0, 0))))
        self.add_items([new], "Область → объект")
        self.set_tool("select")

    def crop_to_selection(self):
        t = self.raster_target()
        if t is not None and t[0] is not None:
            self.crop_image_item(t[0], QRectF(self.raster_sel))
            self.set_raster_selection(None)
            return
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

    # ================================================================ поворот / отражение холста
    TRANSFORMS = {
        "cw": "Повернуть холст на 90° по часовой",
        "ccw": "Повернуть холст на 90° против часовой",
        "180": "Повернуть холст на 180°",
        "fliph": "Отразить холст по горизонтали",
        "flipv": "Отразить холст по вертикали",
    }
    UPRIGHT_TYPES = ("text", "callout", "number")   # при повороте холста надписи остаются горизонтальными

    def transform_canvas(self, op: str):
        """Повернуть / отразить фото вместе со всеми объектами (op — ключ TRANSFORMS)."""
        bg = self.doc.background
        if bg is None or op not in self.TRANSFORMS:
            return
        w, h = bg.width(), bg.height()
        if op == "cw":
            deg, img = 90.0, bg.transformed(QTransform().rotate(90))
            F = lambda p: QPointF(h - p.y(), p.x())  # noqa: E731
        elif op == "ccw":
            deg, img = -90.0, bg.transformed(QTransform().rotate(-90))
            F = lambda p: QPointF(p.y(), w - p.x())  # noqa: E731
        elif op == "180":
            deg, img = 180.0, bg.transformed(QTransform().rotate(180))
            F = lambda p: QPointF(w - p.x(), h - p.y())  # noqa: E731
        elif op == "fliph":
            deg, img = 0.0, bg.flipped(Qt.Horizontal)
            F = lambda p: QPointF(w - p.x(), p.y())  # noqa: E731
        else:
            deg, img = 0.0, bg.flipped(Qt.Vertical)
            F = lambda p: QPointF(p.x(), h - p.y())  # noqa: E731
        text = self.TRANSFORMS[op]
        items = self.doc.items()
        self.set_raster_selection(None)
        self.undo.beginMacro(text)
        self._raster_change(img, text)
        if items:
            def fn():
                for it in items:
                    self._transform_item(it, F, deg, op)
                self._refresh_glue(items)
            self.change_items(items, fn, text)
        self.undo.endMacro()
        if self.view:
            self.view.fit()

    @staticmethod
    def _transform_item(it, F, deg, op):
        mirror = op in ("fliph", "flipv")
        if it.TYPE == "magnifier":
            # область и увеличенный вид — прямоугольники, при повороте на 90° они остаются прямоугольниками
            def mapped(r):
                return QRectF(F(it.mapToScene(r.topLeft())), F(it.mapToScene(r.bottomRight()))).normalized()
            src, dst = mapped(it.src), mapped(it.dst_rect())
            it.prepareGeometryChange()
            it.setPos(src.topLeft())
            it.src = QRectF(0, 0, src.width(), src.height())
            it.dst = dst.topLeft() - src.topLeft()
            it.update()
            return
        piv = it.rotation_pivot()
        c = it.mapToScene(piv)
        if it.uses_angle():
            a = float(it.props.get("angle", 0) or 0)
            if mirror:
                a = -a
            elif it.TYPE not in Editor.UPRIGHT_TYPES:
                a += deg
            a = (a + 180.0) % 360.0 - 180.0
            if a == -180.0:
                a = 180.0
            if a != float(it.props.get("angle", 0) or 0):
                it.set_prop("angle", round(a, 3))
            it.setPos(it.pos() + (F(c) - it.mapToScene(piv)))
            return
        # объекты из точек: каждая точка — туда, где она теперь на фото; у надписей (блок не поворачивается)
        # в новое место переносится центр, у остальных — начало координат объекта
        old = QPointF(it.pos())
        new = old + (F(c) - c) if it.TYPE in Editor.UPRIGHT_TYPES else F(old)
        it.setPos(new)
        it.rotate_geometry(lambda lp: F(lp + old) - new)
        if it.TYPE == "dimension" and mirror:
            it.offset = -it.offset            # размерная линия — с той же стороны, что и была на фото
        if it.TYPE == "callout":
            for ld in it.leaders:            # начало стрелки на рамке
                st = ld[1]
                if st is None:
                    continue
                if op == "fliph":
                    ld[1] = (round(1.0 - st[0], 4), st[1])
                elif op == "flipv":
                    ld[1] = (st[0], round(1.0 - st[1], 4))
                else:
                    ld[1] = None                 # блок не поворачивается — сторона выбирается заново
            if mirror:
                it.bends = [(b[0], -b[1]) if b is not None else None for b in it.bends]
        it.update()

    def _refresh_glue(self, items):
        """После поворота/отражения: пересчитать, к какой точке объекта-цели приклеен каждый конец
        (у надписей, которые остались горизонтальными, точки сместились)."""
        for it in items:
            if not it.glue:
                continue
            ends = it.glue_ends()
            for key, spec in list(it.glue.items()):
                target = self.doc.find(spec.get("uid"))
                if target is None or key not in ends:
                    continue
                end = it.mapToScene(ends[key])
                new = None
                for i, (lp, kind) in enumerate(target.snap_points()):
                    if kind != "edge" and dist(target.mapToScene(lp), end) < 1e-3:
                        new = {"uid": target.uid, "i": i, "k": kind, "p": [round(lp.x(), 3), round(lp.y(), 3)]}
                        break
                if new is None:
                    lp = target.mapFromScene(end)
                    new = {"uid": target.uid, "i": None, "k": "edge", "p": [round(lp.x(), 3), round(lp.y(), 3)]}
                it.glue[key] = new

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
    def raster_blur_begin(self):
        """Для окна размытия: (цель, исходное изображение, область) или None."""
        t = self.raster_target()
        if t is None:
            return None
        item, r, _ = t
        return item, (item.image if item is not None else self.doc.background), r

    def raster_blur_show(self, target, img):
        item = target[0]
        if item is None:
            self.doc.set_background(img, self.doc.bg_source)
        else:
            item.set_image(img)

    def raster_blur(self, sigma, target=None):
        target = target or self.raster_blur_begin()
        if target is None:
            return
        item, src, r = target
        out = imageops.blur_rect(src, r, sigma)
        if item is None:
            self.push(RasterCmd(self.doc, (src, self.doc.bg_source), (out, None), "Размытие по Гауссу"))
        else:
            self._item_image_change(item, out, "Размытие по Гауссу")

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

    def resistor_aspect(self, items):
        """Резистор: вернуть соотношение сторон 1:2 (длинная сторона и центр сохраняются)."""
        res = [i for i in items if i.TYPE == "resistor" and not i.locked]
        if res:
            self.change_items(res, lambda: [i.set_aspect() for i in res], "Соотношение сторон 1:2")

    # ================================================================ vertices
    def delete_vertex(self, item, idx):
        if not hasattr(item, "points") or item.TYPE not in ("polyline", "polygon"):
            return
        if len(item.points) <= item.MIN_POINTS:
            self.message.emit(f"Минимум вершин: {item.MIN_POINTS}")
            return
        self.change_items([item], lambda: item.remove_vertex(idx), "Удалить вершину")

    # ------------------------------------------------------------ указатели выноски
    def add_callout_leader(self, item, tip_scene: QPointF, glue=None):
        if item.TYPE != "callout" or item.locked:
            return

        def fn():
            item.add_leader(item.mapFromScene(tip_scene))
            self.set_glue(item, f"t{len(item.leaders) - 1}", glue)
        self.change_items([item], fn, "Добавить указатель")
        self.sel.changed.emit()

    def remove_callout_leader(self, item, i):
        if item.TYPE != "callout":
            return
        if len(item.leaders) <= 1:
            self.message.emit("У выноски должен остаться хотя бы один указатель")
            return
        self.change_items([item], lambda: item.remove_leader(i), "Удалить указатель")
        self.sel.changed.emit()

    def reset_callout_start(self, item, i):
        if item.TYPE == "callout":
            self.change_items([item], lambda: item.reset_start(i), "Начало указателя — авто")

    def begin_add_leader(self, item):
        """Режим «щёлкните, куда указать» для новой стрелки выноски."""
        self.set_tool("select")
        self.sel.set([item])
        self.tool.pending_leader = item
        if self.view:
            self.view.viewport().setCursor(Qt.CrossCursor)
            self.view.update_action_bar()
        self.message.emit("Щёлкните, куда должна указывать новая стрелка (Esc — отмена)")

    def straighten(self, item, handle_idx=None):
        """Убрать изгиб. handle_idx — ручка изгиба (у выноски — свой указатель), None — весь объект."""
        if not item.is_bent():
            return
        self.change_items([item], lambda: item.straighten(handle_idx), "Выпрямить")

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
