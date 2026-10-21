"""Базовый класс инструмента."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt


class ToolEvent:
    def __init__(self, pos: QPointF, view_pos, modifiers, button=Qt.NoButton, buttons=Qt.NoButton):
        self.pos = QPointF(pos)
        self.view_pos = view_pos
        self.shift = bool(modifiers & Qt.ShiftModifier)
        self.ctrl = bool(modifiers & Qt.ControlModifier)
        self.alt = bool(modifiers & Qt.AltModifier)
        self.button = button
        self.buttons = buttons

    @property
    def left_down(self):
        return bool(self.buttons & Qt.LeftButton)


class Tool:
    name = ""
    title = ""
    shortcut = ""
    cursor = Qt.CrossCursor
    show_snap = True  # показывать индикатор привязки при наведении
    creation = False  # инструмент создания объектов (ПКМ — завершить и перейти к «Выбору»)

    def __init__(self, editor):
        self.ed = editor

    @property
    def view(self):
        return self.ed.view

    @property
    def doc(self):
        return self.ed.doc

    def activate(self):
        if self.view:
            self.view.viewport().setCursor(self.cursor)

    def deactivate(self):
        self.cancel()
        if self.view:
            self.view.snap_hit = None
            self.view.viewport().update()

    def press(self, e: ToolEvent):
        pass

    def move(self, e: ToolEvent):
        if self.show_snap and self.view:
            self.view.snap(e.pos)

    def release(self, e: ToolEvent):
        pass

    def double_click(self, e: ToolEvent):
        pass

    def key(self, ev) -> bool:
        return False

    def cancel(self) -> bool:
        """Отменить незавершённую операцию. True — если было что отменять."""
        return False

    def finish(self) -> bool:
        return False

    def busy(self) -> bool:
        return False

    def hint(self) -> str:
        return ""

    def action_bar(self):
        """Панель «Применить / Отменить» над холстом: None или (текст, [(подпись, функция), ...])."""
        return None

    def leave(self):
        """Курсор ушёл с холста."""
        pass

    def draw_overlay(self, painter, view):
        """Дополнительная служебная графика инструмента (не попадает в экспорт)."""
        pass

    # helpers
    def screen_dist(self, a: QPointF, b: QPointF) -> float:
        s = self.view.scale_factor() if self.view else 1.0
        return ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5 * s
