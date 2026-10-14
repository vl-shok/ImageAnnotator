"""Команды Undo/Redo (QUndoStack).

Принцип: действие выполняется, затем в стек кладётся команда с состояниями
«до» и «после». redo() просто применяет «после» (идемпотентно).
"""
from __future__ import annotations

import copy

from PySide6.QtGui import QUndoCommand


class StateCmd(QUndoCommand):
    """Изменение состояния (геометрия, свойства, слой, z, lock...) набора объектов."""

    def __init__(self, doc, items, before, after, text="Изменение", merge_key=None):
        super().__init__(text)
        self.doc = doc
        self.items = list(items)
        self.before = before
        self.after = after
        self.merge_key = merge_key

    def _apply(self, states):
        for it, st in zip(self.items, states):
            it.apply_dict(st)
        self.doc.relayer()
        self.doc.itemsModified.emit()

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)

    def id(self):
        return 1 if self.merge_key is not None else -1

    def mergeWith(self, other):
        if getattr(other, "merge_key", None) is None or other.merge_key != self.merge_key:
            return False
        if [i.uid for i in other.items] != [i.uid for i in self.items]:
            return False
        self.after = other.after
        return True


class AddCmd(QUndoCommand):
    def __init__(self, doc, items, text="Добавить"):
        super().__init__(text)
        self.doc = doc
        self.items = list(items)

    def redo(self):
        for it in self.items:
            self.doc.add_item(it, emit=False)
        self.doc.relayer()
        self.doc.itemsChanged.emit()

    def undo(self):
        for it in self.items:
            self.doc.remove_item(it, emit=False)
        self.doc.itemsChanged.emit()


class RemoveCmd(AddCmd):
    def __init__(self, doc, items, text="Удалить"):
        super().__init__(doc, items, text)

    def redo(self):
        AddCmd.undo(self)

    def undo(self):
        AddCmd.redo(self)


class LayersCmd(QUndoCommand):
    def __init__(self, doc, before, after, text="Слои", merge_key=None):
        super().__init__(text)
        self.doc = doc
        self.before = before
        self.after = after
        self.merge_key = merge_key

    def redo(self):
        self.doc.restore_layers(self.after)

    def undo(self):
        self.doc.restore_layers(self.before)

    def id(self):
        return 2 if self.merge_key is not None else -1

    def mergeWith(self, other):
        if getattr(other, "merge_key", None) is None or other.merge_key != self.merge_key:
            return False
        self.after = other.after
        return True


class RasterCmd(QUndoCommand):
    """Изменение исходного растрового изображения."""

    def __init__(self, doc, before, after, text="Изображение"):
        super().__init__(text)
        self.doc = doc
        self.before = before  # (QImage, source)
        self.after = after

    def redo(self):
        self.doc.set_background(*self.after)

    def undo(self):
        self.doc.set_background(*self.before)


class AdjustCmd(QUndoCommand):
    def __init__(self, doc, before, after, text="Коррекция изображения", merge_key=None):
        super().__init__(text)
        self.doc = doc
        self.before = copy.deepcopy(before)
        self.after = copy.deepcopy(after)
        self.merge_key = merge_key

    def redo(self):
        self.doc.set_color(self.after)

    def undo(self):
        self.doc.set_color(self.before)

    def id(self):
        return 3 if self.merge_key is not None else -1

    def mergeWith(self, other):
        if not isinstance(other, AdjustCmd) or other.merge_key != self.merge_key:
            return False
        self.after = other.after
        return True


class ItemImageCmd(QUndoCommand):
    """Изменение пикселей вставленного изображения (ImageItem.image)."""

    def __init__(self, doc, item, before, after, text="Изображение"):
        super().__init__(text)
        self.doc = doc
        self.item = item
        self.before = before
        self.after = after

    def redo(self):
        self.item.set_image(self.after)
        self.doc.itemsChanged.emit()

    def undo(self):
        self.item.set_image(self.before)
        self.doc.itemsChanged.emit()
