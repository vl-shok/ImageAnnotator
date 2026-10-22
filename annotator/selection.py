"""Выделение объектов и фильтр выделения."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from .items import ITEM_CLASSES


_SHORT = {"rect": "Прямоуг.", "image": "Картинка", "polyline": "Полилиния", "break": "Разрыв", "magnifier": "Лупа"}


class SelectionFilter:
    TYPES = [(c.TYPE, _SHORT.get(c.TYPE, c.TITLE)) for c in ITEM_CLASSES]

    def __init__(self):
        self.allowed = {t for t, _ in self.TYPES}

    def allows(self, item) -> bool:
        return item.TYPE in self.allowed

    def set_all(self, on: bool):
        self.allowed = {t for t, _ in self.TYPES} if on else set()


class SelectionManager(QObject):
    changed = Signal()

    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.items: list = []
        self.filter = SelectionFilter()

    def set_doc(self, doc, items=()):
        """Переключиться на другой документ (проект) с его выделением."""
        self.doc = doc
        self.items = [i for i in items if doc.contains(i)]
        self.changed.emit()

    # ------------------------------------------------------------
    def is_selectable(self, it) -> bool:
        if not self.doc.contains(it) or not it.isVisible():
            return False
        if not self.filter.allows(it):
            return False
        layer = self.doc.layer(it.layer_id)
        return layer is not None and not layer.locked

    def is_movable(self, it) -> bool:
        return self.is_selectable(it) and not it.locked

    def _expand(self, items):
        out = []
        groups = {i.group_id for i in items if i.group_id}
        for i in items:
            if i not in out:
                out.append(i)
        if groups:
            for i in self.doc.items():
                if i.group_id in groups and i not in out and self.is_selectable(i):
                    out.append(i)
        return out

    def prune(self):
        keep = [i for i in self.items if self.doc.contains(i) and i.isVisible()]
        if keep != self.items:
            self.items = keep
            self.changed.emit()

    # ------------------------------------------------------------
    def set(self, items):
        items = self._expand([i for i in items if self.is_selectable(i)])
        if items != self.items:
            self.items = items
            self.changed.emit()

    def add(self, items):
        self.set(self.items + [i for i in items if i not in self.items])

    def toggle(self, item):
        group = self._expand([item])
        if item in self.items:
            self.set([i for i in self.items if i not in group])
        else:
            self.add(group)

    def clear(self):
        if self.items:
            self.items = []
            self.changed.emit()

    def select_all(self):
        self.set([i for i in self.doc.items_sorted() if self.is_selectable(i)])

    def contains(self, item) -> bool:
        return item in self.items

    def __bool__(self):
        return bool(self.items)

    def __len__(self):
        return len(self.items)
