"""Инструмент выбора (Pointer): выделение, перемещение, редактирование ручек.

Поведение:
  * клик — выбрать объект, Ctrl+клик — добавить/убрать;
  * рамка слева направо — выбрать объекты, целиком попавшие в рамку (window),
    справа налево — все, что пересекает рамку (crossing);
  * перетаскивание объекта — перемещение всего выделения (Shift — по горизонтали/вертикали);
  * перетаскивание ручки — изменение геометрии (Shift — угол 0/45/90°);
  * Shift, зажатый ДО начала перетаскивания ручки, — перемещение всего
    выделения за эту точку (точка захвата привязывается к Snap).
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt

from ..geometry import constrain_axis
from .base import Tool, ToolEvent

DRAG_THRESHOLD = 3  # px экрана


class SelectTool(Tool):
    name = "select"
    title = "Выбор"
    shortcut = "V"
    cursor = Qt.ArrowCursor
    show_snap = False

    def __init__(self, editor):
        super().__init__(editor)
        self.pending_leader = None   # выноска, к которой добавляется стрелка (ждём щелчка)
        self._reset()

    def _reset(self):
        self.state = None        # None | pending | move | handle | rubber
        self.press_pos = None
        self.grab = None         # точка захвата (сцена)
        self.from_handle = False
        self.items = []
        self.orig_pos = {}
        self.before = None
        self.h_item = None
        self.h_idx = -1
        self.click_item = None
        self.h_text = None

    def busy(self):
        return self.state is not None

    def hint(self):
        return ("Клик — выбрать, Ctrl+клик — добавить, рамка ←/→ — пересечение/окно, Shift+ручка — двигать за точку, "
                "Alt+ручка — от центра, «+» — добавить вершину, двойной клик по вершине — удалить, "
                "средняя ручка линии/стрелки — изгиб, Ctrl+тянуть от рамки выноски — новая стрелка")

    # ------------------------------------------------------------------
    def press(self, e: ToolEvent):
        if e.button != Qt.LeftButton:
            return
        v, sel = self.view, self.ed.sel
        self._reset()
        if self.pending_leader is not None:
            item, self.pending_leader = self.pending_leader, None
            v.viewport().setCursor(self.cursor)
            v.snap_hit = None
            if self.doc.contains(item):
                self.ed.add_callout_leader(item, v.snap(e.pos, exclude=[item]))
                v.snap_hit = None
            return
        self.press_pos = QPointF(e.pos)
        if e.ctrl:
            co = self._callout_border_at(e.pos)
            if co is not None:
                # Ctrl + тянуть от рамки выноски — новая стрелка
                self.before = [co.state()]
                lp = co.mapFromScene(e.pos)
                co.add_leader(lp, co._border_param(lp, False))
                if not sel.contains(co):
                    sel.set([co])
                self.h_item, self.h_idx = co, 2 * (len(co.leaders) - 1)
                co.begin_handle_drag(self.h_idx)
                self.h_text = "Добавить стрелку"
                self.state = "handle"
                return
        h = v.hit_handle(e.pos)
        if h is not None:
            item, idx = h
            kinds = item.handle_kinds()
            kind = kinds[idx] if idx < len(kinds) else "point"
            if e.alt and kind in ("tip", "anchor") and item.TYPE == "callout":
                n = idx // 2
                self.ed.remove_callout_leader(item, n) if kind == "tip" else self.ed.reset_callout_start(item, n)
                return
            if e.alt and kind == "vertex" and item.TYPE in ("polyline", "polygon"):
                self.ed.delete_vertex(item, idx)
                self.state = None
                return
            if e.alt and kind == "bend":
                self.ed.straighten(item)
                self.state = None
                return
            if e.shift:
                # перемещение всего выделения за характерную точку
                self.items = [i for i in sel.items if sel.is_movable(i)]
                self.grab = item.mapToScene(item.handles()[idx])
                self.from_handle = True
                self.state = "pending"
            else:
                self.before = [item.state()]
                new_idx = item.begin_handle_drag(idx)
                self.h_item, self.h_idx = item, (idx if new_idx is None else new_idx)
                self.state = "handle"
            return
        it = v.hit_item(e.pos)
        if it is not None:
            if e.ctrl:
                sel.toggle(it)
                return
            if not sel.contains(it):
                sel.set([it])
            else:
                self.click_item = it
            self.items = [i for i in sel.items if sel.is_movable(i)]
            self.grab = QPointF(e.pos)
            self.state = "pending"
            return
        if not e.ctrl:
            sel.clear()
        self.state = "rubber"

    def move(self, e: ToolEvent):
        v = self.view
        if self.pending_leader is not None:
            v.snap(e.pos, exclude=[self.pending_leader])
            v.viewport().update()
            return
        if self.state is None:
            v.update_hover(e.pos)
            if e.ctrl and self._callout_border_at(e.pos) is not None:
                v.viewport().setCursor(Qt.CrossCursor)
            return
        if self.state == "pending":
            if self.screen_dist(e.pos, self.press_pos) < DRAG_THRESHOLD or not self.items:
                return
            self.state = "move"
            self.before = [i.state() for i in self.items]
            self.orig_pos = {i: QPointF(i.pos()) for i in self.items}
            v.viewport().setCursor(Qt.ClosedHandCursor if not self.from_handle else Qt.SizeAllCursor)
        if self.state == "move":
            target = self.grab + (e.pos - self.press_pos)
            if e.shift and not self.from_handle:
                target = constrain_axis(self.grab, target)
                v.snap_hit = None
            else:
                target = v.snap(target, exclude=self.items)
            delta = target - self.grab
            for i in self.items:
                i.setPos(self.orig_pos[i] + delta)
            self.doc.itemsModified.emit()
        elif self.state == "handle":
            item = self.h_item
            p = v.snap(e.pos, exclude=[item], extra=item.handle_snap_extra(self.h_idx))
            item.move_handle(self.h_idx, item.mapFromScene(p), constrain=e.shift, symmetric=e.alt)
            self.doc.itemsModified.emit()
        elif self.state == "rubber":
            if self.screen_dist(e.pos, self.press_pos) >= DRAG_THRESHOLD:
                crossing = e.pos.x() < self.press_pos.x()
                v.rubber = (QRectF(self.press_pos, e.pos).normalized(), crossing)
                v.viewport().update()

    def release(self, e: ToolEvent):
        if e.button != Qt.LeftButton:
            return
        v, sel = self.view, self.ed.sel
        st = self.state
        if st == "move":
            self.ed.record_items(self.items, self.before, "Перемещение")
        elif st == "handle":
            self.ed.record_items([self.h_item], self.before, getattr(self, "h_text", None) or "Изменение формы")
        elif st == "pending" and self.click_item is not None and not e.ctrl:
            # клик по уже выбранному объекту в группе выделения — выбрать только его
            if len(sel.items) > 1 and not self.click_item.group_id:
                sel.set([self.click_item])
        elif st == "rubber" and v.rubber is not None:
            rect, crossing = v.rubber
            found = []
            for it in self.doc.items_sorted():
                if not sel.is_selectable(it):
                    continue
                if crossing:
                    if it.intersects_rect(rect) or rect.contains(it.content_rect()):
                        found.append(it)
                elif rect.contains(it.content_rect()):
                    found.append(it)
            if e.ctrl:
                sel.add(found)
            else:
                sel.set(found)
        v.rubber = None
        v.snap_hit = None
        self._reset()
        v.update_hover(e.pos)
        v.viewport().update()

    def double_click(self, e: ToolEvent):
        h = self.view.hit_handle(e.pos)
        if h is not None:
            item, idx = h
            kinds = item.handle_kinds()
            kind = kinds[idx] if idx < len(kinds) else ""
            if kind == "vertex" and item.TYPE in ("polyline", "polygon"):
                self.ed.delete_vertex(item, idx)
                return
            if kind == "bend":
                self.ed.straighten(item)
                return
            if kind in ("tip", "anchor") and item.TYPE == "callout":
                n = idx // 2
                self.ed.remove_callout_leader(item, n) if kind == "tip" else self.ed.reset_callout_start(item, n)
                return
        it = self.view.hit_item(e.pos)
        if it is not None:
            self.ed.edit_item(it)

    def _callout_border_at(self, pos):
        """Выноска, рамка которой под курсором (с допуском в несколько экранных пикселей)."""
        tol = 7 / max(1e-6, self.view.scale_factor())
        for it in reversed(self.doc.items_sorted()):
            if it.TYPE != "callout" or not self.ed.sel.is_movable(it):
                continue
            lp = it.mapFromScene(pos)
            b = it.box()
            if b.adjusted(-tol, -tol, tol, tol).contains(lp) and not b.adjusted(tol, tol, -tol, -tol).contains(lp):
                return it
        return None

    def action_bar(self):
        if self.pending_leader is not None:
            return ("Щёлкните, куда должна указывать новая стрелка", [("✕  Отмена", self.cancel)])
        return None

    def cancel(self):
        if self.pending_leader is not None:
            self.pending_leader = None
            if self.view:
                self.view.viewport().setCursor(self.cursor)
                self.view.snap_hit = None
                self.view.viewport().update()
            return True
        if self.state is None:
            return False
        if self.state == "move" and self.before:
            for i, st in zip(self.items, self.before):
                i.apply_dict(st)
        elif self.state == "handle" and self.before:
            self.h_item.apply_dict(self.before[0])
        self.doc.relayer()
        if self.view:
            self.view.rubber = None
            self.view.snap_hit = None
            self.view.viewport().update()
        self._reset()
        return True
