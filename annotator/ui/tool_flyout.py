"""Кнопка панели инструментов с несколькими инструментами: щелчок — текущий, долгое нажатие — выбор из списка."""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QMenu, QToolButton


class ToolFlyout(QToolButton):
    """Показывает последний выбранный инструмент группы; удерживайте кнопку — появится список.
    Треугольник в правом нижнем углу подсказывает, что вариантов несколько."""

    def __init__(self, actions, parent=None):
        super().__init__(parent)
        self.group_actions = list(actions)
        menu = QMenu(self)
        menu.addActions(self.group_actions)
        self.setMenu(menu)
        self.setPopupMode(QToolButton.DelayedPopup)
        self.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        self.show_action(self.group_actions[0])

    def show_action(self, a):
        if a not in self.group_actions:
            return
        self.setDefaultAction(a)
        names = ", ".join(x.text().split(" (")[0].lower() for x in self.group_actions)
        self.setToolTip(f"{a.toolTip()}\nУдерживайте — выбор: {names}")

    def paintEvent(self, ev):
        super().paintEvent(ev)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(200, 205, 212))
        w, h = self.width(), self.height()
        p.drawPolygon(QPolygonF([QPointF(w - 2, h - 8), QPointF(w - 2, h - 2), QPointF(w - 8, h - 2)]))
        p.end()
