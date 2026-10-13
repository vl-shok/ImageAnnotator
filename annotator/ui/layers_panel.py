"""Панель слоёв в стиле Photoshop.

* слои сверху вниз, у каждого: «глаз» (видимость), «замок», миниатюра, имя, число объектов;
* объекты слоя — вложенный список (можно свернуть);
* активный слой выделен — новые объекты попадают в него;
* перетаскивание слоёв мышью меняет порядок, перетаскивание объектов — переносит их
  в другой слой / меняет Z-порядок;
* Alt+клик по «глазу» — показать только этот слой (повторно — показать все);
* двойной клик по имени слоя — переименовать;
* непрозрачность активного слоя — ползунок сверху.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QLabel, QMenu, QStyleOptionGraphicsItem, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from .icons import icon, small_icon
from .widgets import OpacityEditor

ROLE = Qt.UserRole
TYPE_ICON = {"text": "text", "line": "line", "arrow": "arrow", "callout": "callout", "number": "number",
             "rect": "rect", "ellipse": "ellipse", "polyline": "polyline", "polygon": "polygon",
             "freehand": "freehand", "image": "image", "break": "break", "dimension": "dimension"}
THUMB = QSize(40, 28)
EYE_CANVAS = QSize(22, 28)


class LayerTree(QTreeWidget):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        # Колонки: слой — [глаз][замок][▾][миниатюра+имя]; объект — [ ][глаз][замок][значок+имя]
        # (у объектов «глаз» и «замок» сдвинуты вправо — сразу видно, что объект внутри слоя)
        self.setColumnCount(4)
        self.setHeaderHidden(True)
        for c, w in ((0, 26), (1, 26), (2, 24)):
            self.setColumnWidth(c, w)
        self.setIndentation(0)
        self.setRootIsDecorated(False)
        self.setIconSize(THUMB)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setUniformRowHeights(False)
        self.setExpandsOnDoubleClick(False)

    def mousePressEvent(self, ev):
        it = self.itemAt(ev.position().toPoint())
        col = self.columnAt(int(ev.position().x()))
        role = self.panel.cell_role(it, col) if it is not None else None
        if role and ev.button() == Qt.LeftButton:
            self.panel.toggle_cell(it, role, bool(ev.modifiers() & Qt.AltModifier))
            return
        super().mousePressEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        it = self.itemAt(ev.position().toPoint())
        col = self.columnAt(int(ev.position().x()))
        if it is not None and self.panel.cell_role(it, col):
            return
        if it is not None:
            self.panel.double_clicked(it)
            return
        super().mouseDoubleClickEvent(ev)

    def dropEvent(self, ev):
        target = self.itemAt(ev.position().toPoint())
        pos = self.dropIndicatorPosition()
        dragged = self.selectedItems()
        ev.setDropAction(Qt.IgnoreAction)
        ev.accept()
        if target is not None and dragged:
            QTimer.singleShot(0, lambda: self.panel.handle_drop(dragged, target, pos))


class LayersPanel(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.ed = editor
        self.doc = editor.doc
        self._updating = False
        self._collapsed: set[str] = set()
        self._thumbs: dict[str, QIcon] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        top = QWidget()
        tl = QHBoxLayout(top)
        tl.setContentsMargins(6, 4, 6, 2)
        tl.setSpacing(6)
        lb = QLabel("Непрозр.:")
        lb.setObjectName("PropLabel")
        tl.addWidget(lb)
        self.opacity = OpacityEditor()
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.opacity.committed.connect(editor.bump_session)
        tl.addWidget(self.opacity, 1)
        lay.addWidget(top)

        self.tree = LayerTree(self)
        lay.addWidget(self.tree, 1)

        bar = QWidget()
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(4, 2, 4, 4)
        bl.setSpacing(2)
        self.buttons = {}
        for name, ic, tip, fn in (
            ("add", "layer_add", "Новый слой  (Ctrl+Shift+N)", self.add_layer),
            ("dup", "layer_dup", "Дублировать слой", lambda: self._on_active(self.ed.duplicate_layer)),
            ("up", "up", "Слой выше", lambda: self._on_active(lambda l: self.ed.move_layer(l, +1))),
            ("down", "down", "Слой ниже", lambda: self._on_active(lambda l: self.ed.move_layer(l, -1))),
            ("merge", "merge", "Объединить с нижним слоем", lambda: self._on_active(self.ed.merge_down)),
            ("del", "layer_del", "Удалить слой (вместе с объектами)", lambda: self._on_active(self.ed.delete_layer)),
        ):
            b = QToolButton()
            b.setIcon(icon(ic))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.setAutoRaise(True)
            b.clicked.connect(fn)
            bl.addWidget(b)
            self.buttons[name] = b
        bl.addStretch(1)
        lay.addWidget(bar)

        self.tree.itemSelectionChanged.connect(self._tree_selection)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.customContextMenuRequested.connect(self._context_menu)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self.refresh)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(350)
        self._thumb_timer.timeout.connect(self._update_thumbs)

        self.doc.layersChanged.connect(self._timer.start)
        self.doc.itemsChanged.connect(self._timer.start)
        self.doc.itemsModified.connect(self._thumb_timer.start)
        self.doc.backgroundChanged.connect(self._thumb_timer.start)
        self.ed.sel.changed.connect(self._sync_selection)
        self.refresh()

    # ------------------------------------------------------------------ build
    def refresh(self):
        self._updating = True
        tree = self.tree
        scroll = tree.verticalScrollBar().value()
        tree.clear()
        active = self.doc.active_layer_id
        bold = QFont(self.font())
        bold.setBold(True)
        grey = QBrush(QColor(120, 125, 135))
        for layer in reversed(self.doc.layers):
            li = QTreeWidgetItem()
            li.setData(0, ROLE, ("layer", layer.id))
            li.setIcon(0, small_icon("eye" if layer.visible else "eye_off", 15, EYE_CANVAS))
            li.setIcon(1, small_icon("lock" if layer.locked else "unlock", 13, EYE_CANVAS))
            li.setToolTip(0, "Видимость слоя (Alt+клик — только этот слой)")
            li.setToolTip(1, "Блокировка слоя")
            items = self.doc.items_in_layer(layer.id)
            if items:
                li.setText(2, "▸" if layer.id in self._collapsed else "▾")
                li.setToolTip(2, "Свернуть / развернуть")
                li.setTextAlignment(2, Qt.AlignCenter)
            count = f"   ({len(items)})" if not layer.is_bg else ""
            op = f"  {int(layer.opacity * 100)}%" if layer.opacity < 0.999 else ""
            li.setText(3, f"{layer.name}{count}{op}")
            li.setIcon(3, self._thumbs.get(layer.id, QIcon()))
            flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
            if not layer.is_bg:
                flags |= Qt.ItemIsEditable | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled
            li.setFlags(flags)
            li.setSizeHint(3, QSize(10, THUMB.height() + 6))
            li.setFont(3, bold)
            for c in range(4):
                li.setBackground(c, QBrush(QColor(45, 85, 130) if layer.id == active else QColor(52, 55, 61)))
            if not layer.visible:
                li.setForeground(3, grey)
            tree.addTopLevelItem(li)
            for it in reversed(items):
                ci = QTreeWidgetItem(li)
                ci.setData(0, ROLE, ("item", it.uid))
                ci.setIcon(1, small_icon("eye" if it.obj_visible else "eye_off", 15, EYE_CANVAS))
                ci.setIcon(2, small_icon("lock" if it.locked else "unlock", 13, EYE_CANVAS))
                ci.setToolTip(1, "Видимость объекта")
                ci.setToolTip(2, "Блокировка объекта")
                txt = it.describe()
                if it.group_id:
                    txt = "⛓ " + txt
                ci.setText(3, txt)
                ci.setIcon(3, icon(TYPE_ICON.get(it.TYPE, "rect")))
                ci.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
                if not it.obj_visible or not layer.visible:
                    ci.setForeground(3, grey)
            li.setExpanded(layer.id not in self._collapsed)
        tree.verticalScrollBar().setValue(scroll)
        self._updating = False
        self._sync_selection()
        self._update_controls()
        self._thumb_timer.start()

    def _update_controls(self):
        layer = self.doc.active_layer()
        self.opacity.set_value(layer.opacity if layer else 1.0)
        is_bg = layer is None or layer.is_bg
        idx = self.doc.layer_index(self.doc.active_layer_id)
        self.buttons["del"].setEnabled(not is_bg)
        self.buttons["dup"].setEnabled(not is_bg)
        self.buttons["up"].setEnabled(not is_bg and idx < len(self.doc.layers) - 1)
        self.buttons["down"].setEnabled(not is_bg and idx > 1)
        self.buttons["merge"].setEnabled(not is_bg and idx > 1)

    def _find_row(self, kind, key):
        for i in range(self.tree.topLevelItemCount()):
            li = self.tree.topLevelItem(i)
            if kind == "layer" and li.data(0, ROLE)[1] == key:
                return li
            for j in range(li.childCount()):
                ci = li.child(j)
                if ci.data(0, ROLE)[1] == key:
                    return ci
        return None

    def _sync_selection(self):
        if self._updating:
            return
        self._updating = True
        self.tree.clearSelection()
        for it in self.ed.sel.items:
            row = self._find_row("item", it.uid)
            if row is not None:
                row.setSelected(True)
        if self.ed.sel.items:
            row = self._find_row("item", self.ed.sel.items[-1].uid)
            if row is not None:
                self.tree.scrollToItem(row)
        self._updating = False

    # ------------------------------------------------------------------ thumbnails
    def _update_thumbs(self):
        rect = self.doc.export_rect()
        if rect.isEmpty():
            return
        for layer in self.doc.layers:
            pm = QPixmap(THUMB)
            pm.fill(QColor(70, 72, 78))
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            k = min(THUMB.width() / rect.width(), THUMB.height() / rect.height())
            ox = (THUMB.width() - rect.width() * k) / 2
            oy = (THUMB.height() - rect.height() * k) / 2
            area = QRectF(ox, oy, rect.width() * k, rect.height() * k)
            p.fillRect(area, QColor(235, 235, 235) if not layer.is_bg else QColor(40, 40, 40))
            if layer.is_bg:
                if self.doc.display_image is not None:
                    p.drawImage(area, self.doc.display_image)
            else:
                opt = QStyleOptionGraphicsItem()
                for it in self.doc.items_in_layer(layer.id):
                    if not it.obj_visible:
                        continue
                    p.save()
                    t = QTransform()
                    t.translate(ox, oy)
                    t.scale(k, k)
                    t.translate(-rect.left(), -rect.top())
                    p.setTransform(it.sceneTransform() * t)
                    try:
                        it.paint(p, opt, None)
                    except Exception:
                        pass
                    p.restore()
            p.setPen(QColor(20, 20, 20))
            p.setBrush(Qt.NoBrush)
            p.drawRect(pm.rect().adjusted(0, 0, -1, -1))
            p.end()
            self._thumbs[layer.id] = QIcon(pm)
        self._updating = True
        for i in range(self.tree.topLevelItemCount()):
            li = self.tree.topLevelItem(i)
            lid = li.data(0, ROLE)[1]
            if lid in self._thumbs:
                li.setIcon(3, self._thumbs[lid])
        self._updating = False

    # ------------------------------------------------------------------ actions
    def _layer_of_row(self, row):
        kind, key = row.data(0, ROLE)
        if kind == "layer":
            return key
        it = self.doc.find(key)
        return it.layer_id if it else None

    def cell_role(self, row, col):
        kind = row.data(0, ROLE)[0]
        if kind == "layer":
            return {0: "eye", 1: "lock", 2: "expand"}.get(col)
        return {1: "eye", 2: "lock"}.get(col)

    def toggle_cell(self, row, role, alt):
        kind, key = row.data(0, ROLE)
        if role == "expand":
            if row.childCount():
                if key in self._collapsed:
                    self._collapsed.discard(key)
                else:
                    self._collapsed.add(key)
                self._timer.start()
            return
        if kind == "layer":
            layer = self.doc.layer(key)
            if layer is None:
                return
            if role == "eye":
                if alt:
                    self.ed.solo_layer(key)
                else:
                    self.ed.set_layer_attr(key, "visible", not layer.visible)
            else:
                self.ed.set_layer_attr(key, "locked", not layer.locked)
        else:
            it = self.doc.find(key)
            if it is None:
                return
            if role == "eye":
                self.ed.change_items([it], lambda: setattr(it, "obj_visible", not it.obj_visible), "Видимость")
            else:
                self.ed.change_items([it], lambda: setattr(it, "locked", not it.locked), "Блокировка")
            self.doc.itemsChanged.emit()

    def double_clicked(self, row):
        kind, key = row.data(0, ROLE)
        if kind == "layer":
            if not self.doc.layer(key).is_bg:
                layer = self.doc.layer(key)
                self._updating = True
                row.setText(3, layer.name)
                self._updating = False
                self.tree.editItem(row, 3)
        else:
            it = self.doc.find(key)
            if it is not None:
                self.ed.edit_item(it)

    def _item_changed(self, row, col):
        if self._updating or col != 3:
            return
        kind, key = row.data(0, ROLE)
        if kind == "layer":
            name = row.text(3).strip()
            layer = self.doc.layer(key)
            if layer is not None and name and name != layer.name:
                self.ed.rename_layer(key, name)
            else:
                self._timer.start()

    def _tree_selection(self):
        if self._updating:
            return
        rows = self.tree.selectedItems()
        objs = []
        layer_clicked = None
        for r in rows:
            kind, key = r.data(0, ROLE)
            if kind == "item":
                it = self.doc.find(key)
                if it is not None:
                    objs.append(it)
            else:
                layer_clicked = key
        self._updating = True
        if objs:
            self.ed.set_active_layer(objs[-1].layer_id)
            self.ed.sel.set(objs)
        elif layer_clicked:
            self.ed.set_active_layer(layer_clicked)
            self.ed.sel.clear()
        self._updating = False
        self._update_controls()

    def _on_active(self, fn):
        lid = self.doc.active_layer_id
        if lid:
            fn(lid)

    def add_layer(self):
        self.ed.add_layer()

    def _opacity_changed(self, v):
        lid = self.doc.active_layer_id
        if lid:
            self.ed.set_layer_attr(lid, "opacity", v, merge=True)

    def handle_drop(self, dragged, target, pos):
        tkind, tkey = target.data(0, ROLE)
        kinds = {d.data(0, ROLE)[0] for d in dragged}
        if kinds == {"layer"} and len(dragged) == 1:
            lid = dragged[0].data(0, ROLE)[1]
            tlid = self._layer_of_row(target)
            if tlid is None or tlid == lid:
                return
            order = [l.id for l in self.doc.layers]
            order.remove(lid)
            ti = order.index(tlid)
            new_index = ti + 1 if pos == QAbstractItemView.AboveItem else ti
            self.ed.move_layer_to(lid, max(1, new_index))
            return
        if "item" in kinds:
            items = [self.doc.find(d.data(0, ROLE)[1]) for d in dragged if d.data(0, ROLE)[0] == "item"]
            items = [i for i in items if i is not None]
            tlid = self._layer_of_row(target)
            layer = self.doc.layer(tlid)
            if layer is None or layer.is_bg or not items:
                return
            if tkind == "layer":
                index = 0
            else:
                top_down = [i for i in reversed(self.doc.items_in_layer(tlid)) if i not in items]
                titem = self.doc.find(tkey)
                if titem in top_down:
                    index = top_down.index(titem) + (1 if pos == QAbstractItemView.BelowItem else 0)
                else:
                    index = 0
            self.ed.move_to_layer(items, tlid, index)

    def _context_menu(self, pt):
        row = self.tree.itemAt(pt)
        m = QMenu(self)
        if row is None:
            m.addAction("Новый слой", self.add_layer)
        else:
            kind, key = row.data(0, ROLE)
            if kind == "layer":
                layer = self.doc.layer(key)
                self.ed.set_active_layer(key)
                if not layer.is_bg:
                    m.addAction("Переименовать", lambda: self.double_clicked(row))
                    m.addAction("Дублировать слой", lambda: self.ed.duplicate_layer(key))
                    m.addAction("Объединить с нижним", lambda: self.ed.merge_down(key))
                    m.addAction("Выделить объекты слоя", lambda: self.ed.select_layer_objects(key))
                    m.addSeparator()
                m.addAction("Показать только этот слой", lambda: self.ed.solo_layer(key))
                m.addAction("Скрыть" if layer.visible else "Показать",
                            lambda: self.ed.set_layer_attr(key, "visible", not layer.visible))
                m.addAction("Разблокировать" if layer.locked else "Заблокировать",
                            lambda: self.ed.set_layer_attr(key, "locked", not layer.locked))
                if not layer.is_bg:
                    m.addSeparator()
                    m.addAction("Новый слой", self.add_layer)
                    m.addAction("Удалить слой", lambda: self.ed.delete_layer(key))
            else:
                sub = m.addMenu("Перенести в слой")
                for l in reversed(self.doc.annotation_layers()):
                    sub.addAction(l.name, (lambda lid: (lambda: self.ed.move_to_layer(self.ed.sel.items, lid)))(l.id))
                if len(self.ed.sel.items) > 1:
                    m.addAction("Сгруппировать  (Ctrl+G)", self.ed.group)
                if any(i.group_id for i in self.ed.sel.items):
                    m.addAction("Разгруппировать  (Ctrl+Shift+G)", self.ed.ungroup)
                m.addAction("Заблокировать / разблокировать", self.ed.toggle_lock)
                m.addSeparator()
                m.addAction("Удалить", self.ed.delete_selected)
        m.exec(self.tree.viewport().mapToGlobal(pt))
