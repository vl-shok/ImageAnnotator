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
from ..snap import MOVE_POINTS_MAX
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
        self.h_refs = None       # свои точки объекта (вершины) для направляющих при перетаскивании ручки
        self.move_pts = []       # характерные точки перемещаемых объектов (сцена, до сдвига)
        self.followers = []      # объекты с концами, приклеенными к изменяемым (едут следом)
        self.f_before = []

    def busy(self):
        return self.state is not None

    def hint(self):
        return ("Клик — выбрать, Ctrl+клик — добавить, рамка ←/→ — пересечение/окно, Shift+ручка — двигать за точку, "
                "Alt+ручка — от центра, «+» — добавить вершину, двойной клик по вершине — удалить, "
                "средняя ручка линии/стрелки/указателя выноски — изгиб, Ctrl+тянуть от рамки выноски — новая стрелка")

    # ------------------------------------------------------------------
    def press(self, e: ToolEvent):
        if e.button != Qt.LeftButton:
            return
        v, sel = self.view, self.ed.sel
        self._reset()
        v.snap_target = None
        if self.pending_leader is not None:
            item, self.pending_leader = self.pending_leader, None
            v.viewport().setCursor(self.cursor)
            v.snap_hit = None
            if self.doc.contains(item):
                self.ed.add_callout_leader(item, v.snap(e.pos, exclude=[item]), self.ed.glue_spec())
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
                self._start_followers([co])
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
                self.ed.straighten(item, idx)
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
                self._start_followers([item])
                self.h_refs = self._own_refs(item, self.h_idx)
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
            self._start_followers(self.items)
            self.move_pts = self._move_points(self.items)
            v.viewport().setCursor(Qt.ClosedHandCursor if not self.from_handle else Qt.SizeAllCursor)
        if self.state == "move":
            target = self.grab + (e.pos - self.press_pos)
            guides = []
            if e.shift and not self.from_handle:
                target = constrain_axis(self.grab, target)
                v.snap_hit = None
                delta = target - self.grab
            else:
                target = v.snap(target, exclude=self.items + self.followers, guides=False)
                delta = target - self.grab
                if v.snap_hit is None and not self.from_handle and not v.snap_disabled():
                    # точка захвата никуда не привязалась — выравниваем объекты по направляющим
                    delta, guides = self.ed.snap.find_move_guides(self.doc, self.move_pts, delta, v.guide_tol(),
                                                                  exclude=self.items + self.followers)
                    v.show_guides(guides)
            for i in self.items:
                i.setPos(self.orig_pos[i] + delta)
            self.ed.apply_glue(self.followers)
            self.doc.itemsModified.emit()
        elif self.state == "handle":
            item = self.h_item
            anchor = item.handle_anchor(self.h_idx)
            p = v.snap(e.pos, exclude=[item] + self.followers, extra=item.handle_snap_extra(self.h_idx),
                       anchor=item.mapToScene(anchor) if anchor is not None else None, refs=self.h_refs)
            item.move_handle(self.h_idx, item.mapFromScene(p), constrain=e.shift, symmetric=e.alt)
            self.ed.apply_glue(self.followers)
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
            self.ed.unglue_detached(self.items)
            self.ed.record_items(self.items + self.followers, self.before + self.f_before, "Перемещение")
        elif st == "handle":
            # конец, отпущенный на точке привязки другого объекта, приклеивается к нему (иначе — отклеивается)
            self.ed.set_glue(self.h_item, self.h_item.handle_glue_key(self.h_idx), self.ed.glue_spec())
            self.ed.record_items([self.h_item] + self.followers, self.before + self.f_before,
                                 getattr(self, "h_text", None) or "Изменение формы")
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
                self.ed.straighten(item, idx)
                return
            if kind in ("tip", "anchor") and item.TYPE == "callout":
                n = idx // 2
                self.ed.remove_callout_leader(item, n) if kind == "tip" else self.ed.reset_callout_start(item, n)
                return
        it = self.view.hit_item(e.pos)
        if it is not None:
            self.ed.edit_item(it)

    @staticmethod
    def _move_points(items):
        """Точки, которые выравниваются при перемещении: характерные точки объектов
        (у многих объектов — углы, середины сторон и центр общей рамки)."""
        from ..geometry import rect_snap_points
        pts = [it.mapToScene(p) for it in items for p, k in it.snap_points() if k != "edge"]
        if len(pts) > MOVE_POINTS_MAX or not pts:
            r = QRectF()
            for it in items:
                r = r.united(it.content_rect())
            pts = [p for p, _ in rect_snap_points(r)]
        return pts

    @staticmethod
    def _own_refs(item, idx):
        """Свои вершины/концы объекта (сцена) для выравнивания перетаскиваемой ручки — кроме неё самой.
        Середины не берём: они сдвигаются вместе с ручкой."""
        hs = item.handles()
        # только у объектов из вершин: у прямоугольника и т.п. «свои» точки едут вместе с ручкой
        if not hasattr(item, "points") or not (0 <= idx < len(hs)):
            return None
        h = hs[idx]
        return [item.mapToScene(p) for p, k in item.snap_points()
                if k in ("endpoint", "vertex") and abs(p.x() - h.x()) + abs(p.y() - h.y()) > 1e-6]

    def _start_followers(self, items):
        self.followers = self.ed.glue_followers(items)
        self.f_before = [i.state() for i in self.followers]

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
        for i, st in zip(self.followers, self.f_before):
            i.apply_dict(st)
        self.doc.relayer()
        if self.view:
            self.view.rubber = None
            self.view.snap_hit = None
            self.view.viewport().update()
        self._reset()
        return True
