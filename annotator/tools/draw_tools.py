"""Инструменты создания объектов.

Единое поведение: после создания объект выделяется (свойства сразу видны справа),
инструмент остаётся активным. Esc — отменить текущую операцию, повторный Esc —
вернуться к инструменту выбора.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt

from ..geometry import constrain_angle, dist
from ..items import (ArrowItem, BreakItem, CalloutItem, DimensionItem, MagnifierItem, EllipseItem, FreehandItem, LineItem, NumberItem,
                     PolygonItem, PolylineItem, RectItem, TextItem)
from .base import Tool, ToolEvent

MIN_SIZE_PX = 4


class _TempMixin:
    def _start_temp(self, item):
        item.layer_id = self.doc.target_layer_id()
        item.setZValue(1e9)
        self.doc.scene.addItem(item)
        self.temp = item

    def _drop_temp(self):
        if getattr(self, "temp", None) is not None:
            if self.temp.scene() is not None and not self.doc.contains(self.temp):
                self.temp.scene().removeItem(self.temp)
        self.temp = None

    def _commit_temp(self, text):
        item = self.temp
        self.temp = None
        self.ed.add_items([item], text)
        return item


# =====================================================================
class TwoPointTool(Tool, _TempMixin):
    """Линия, стрелка, прямоугольник, эллипс. Работает и «тянуть», и «клик-клик»."""
    creation = True

    def __init__(self, editor, cls, name, title, shortcut, box=False):
        super().__init__(editor)
        self.cls, self.name, self.title, self.shortcut, self.box = cls, name, title, shortcut, box
        self.temp = None
        self.p0 = None
        self.click_mode = False

    def busy(self):
        return self.temp is not None

    def hint(self):
        if self.box:
            centre = "Alt — от угла" if getattr(self.cls, "CREATE_FROM_CENTER", False) else "Alt — от центра"
            return f"Тяните мышью (или клик–клик). Shift — квадрат/круг, {centre}. ПКМ — к «Выбору»"
        return "Тяните мышью (или клик–клик). Shift — угол 0/45/90°. Esc — отмена"

    def press(self, e: ToolEvent):
        if e.button != Qt.LeftButton:
            return
        if self.temp is not None and self.click_mode:
            self._update(e)
            self._finish()
            return
        self.p0 = self.view.snap(e.pos)
        self._start_temp(self.cls())
        self.temp.set_drag(self.p0, self.p0)
        self.click_mode = False

    def _update(self, e):
        p1 = self.view.snap(e.pos, exclude=[self.temp])
        self.temp.set_drag(self.p0, p1, constrain=e.shift, center=e.alt)

    def move(self, e: ToolEvent):
        if self.temp is None:
            return super().move(e)
        self._update(e)

    def release(self, e: ToolEvent):
        if e.button != Qt.LeftButton or self.temp is None or self.click_mode:
            return
        if self.screen_dist(e.pos, self.p0) < MIN_SIZE_PX:
            self.click_mode = True  # ждём второй клик
            return
        self._update(e)
        self._finish()

    def _finish(self):
        item = self.temp
        r = item.mapToScene(item.outline_path().boundingRect()).boundingRect()
        if max(r.width(), r.height()) * self.view.scale_factor() < MIN_SIZE_PX:
            self._drop_temp()
        else:
            self._commit_temp(self.title)
        self.click_mode = False
        self.view.snap_hit = None

    def cancel(self):
        if self.temp is None:
            return False
        self._drop_temp()
        self.click_mode = False
        return True

    def action_bar(self):
        if self.temp is not None and self.click_mode:
            return (f"{self.title}: укажите вторую точку", [("✕  Отменить", self.cancel)])
        return None


# =====================================================================
class PolyTool(Tool, _TempMixin):
    creation = True
    def __init__(self, editor, cls, name, title, shortcut):
        super().__init__(editor)
        self.cls, self.name, self.title, self.shortcut = cls, name, title, shortcut
        self.temp = None
        self.pts: list[QPointF] = []

    def busy(self):
        return self.temp is not None

    def hint(self):
        return ("Клик — вершина, Enter/двойной клик/ПКМ — завершить, Backspace — убрать точку, "
                "Shift — 0/45/90°, Esc — отмена")

    def _floating(self, e):
        own = [(q, "vertex") for q in self.pts]  # привязка к уже поставленным вершинам (замкнуть контур)
        p = self.view.snap(e.pos, exclude=[self.temp], extra=own)
        if e.shift and self.pts:
            p = constrain_angle(self.pts[-1], p)
        return p

    def press(self, e: ToolEvent):
        if e.button != Qt.LeftButton:
            return
        if self.temp is None:
            p = self.view.snap(e.pos)
            self.pts = [p]
            self._start_temp(self.cls())
            self.temp.set_scene_points([p, p])
            return
        p = self._floating(e)
        if self.pts and dist(p, self.pts[-1]) * self.view.scale_factor() < 2:
            return
        self.pts.append(p)
        self.temp.set_scene_points(self.pts + [p])

    def move(self, e: ToolEvent):
        if self.temp is None:
            return super().move(e)
        self.temp.set_scene_points(self.pts + [self._floating(e)])

    def double_click(self, e: ToolEvent):
        if self.temp is not None:
            self.finish()

    def key(self, ev):
        if self.temp is None:
            return False
        if ev.key() == Qt.Key_Backspace:
            if len(self.pts) > 1:
                self.pts.pop()
                self.temp.set_scene_points(self.pts + [self.pts[-1]])
            else:
                self.cancel()
            return True
        return False

    def finish(self):
        if self.temp is None:
            return False
        pts = list(self.pts)
        # убрать совпадающие подряд точки
        clean = []
        for p in pts:
            if not clean or dist(p, clean[-1]) > 1e-6:
                clean.append(p)
        if len(clean) < self.cls.MIN_POINTS:
            self._drop_temp()
            self.pts = []
            return True
        self.temp.set_scene_points(clean)
        self._commit_temp(self.title)
        self.pts = []
        self.view.snap_hit = None
        return True

    def cancel(self):
        if self.temp is None:
            return False
        self._drop_temp()
        self.pts = []
        return True

    def action_bar(self):
        if self.temp is None:
            return None
        return (f"{self.title}: вершин {len(self.pts)}",
                [("✓  Готово", self.finish), ("↶  Убрать точку", self._undo_point), ("✕  Отменить", self.cancel)])

    def _undo_point(self):
        if self.temp is None:
            return
        if len(self.pts) > 1:
            self.pts.pop()
            self.temp.set_scene_points(self.pts + [self.pts[-1]])
        else:
            self.cancel()


# =====================================================================
class FreehandTool(Tool, _TempMixin):
    creation = True
    name = "freehand"
    title = "Карандаш"
    shortcut = "F"
    show_snap = False

    def __init__(self, editor):
        super().__init__(editor)
        self.temp = None

    def busy(self):
        return self.temp is not None

    def hint(self):
        return "Рисуйте с зажатой левой кнопкой. Отпустите возле начала — контур замкнётся (магнит)"

    def _near_start(self, pos):
        it = self.temp
        if it is None or len(it.points) < 6:
            return None
        start = it.mapToScene(it.points[0])
        # магнит срабатывает, только когда линия уже «ушла» от начала
        far = max(((it.mapToScene(q) - start).manhattanLength() for q in it.points), default=0)
        tol = self.view.px(max(12, self.ed.snap.radius_px * 1.5))
        if far > tol * 3 and (pos - start).manhattanLength() <= tol * 1.4:
            return start
        return None

    def press(self, e):
        if e.button != Qt.LeftButton:
            return
        self._start_temp(FreehandItem())
        self.temp.set_scene_points([e.pos])

    def move(self, e):
        if self.temp is not None and e.left_down:
            self.temp.add_point(e.pos, 1.5 / self.view.scale_factor())
            st = self._near_start(e.pos)
            self.view.snap_hit = (st, "endpoint") if st is not None else None
            self.view.viewport().update()

    def release(self, e):
        if self.temp is None or e.button != Qt.LeftButton:
            return
        if len(self.temp.points) < 2:
            self._drop_temp()
            return
        if self._near_start(e.pos) is not None:
            self.temp.close_contour()
        self.view.snap_hit = None
        self._commit_temp(self.title)

    def cancel(self):
        if self.temp is None:
            return False
        self._drop_temp()
        return True


# =====================================================================
class TextTool(Tool):
    creation = True
    name = "text"
    title = "Текст"
    shortcut = "T"
    cursor = Qt.IBeamCursor

    def hint(self):
        return "Клик — новый текст, клик по тексту — редактировать"

    def press(self, e):
        if e.button != Qt.LeftButton:
            return
        it = self.view.hit_item(e.pos)
        if isinstance(it, (TextItem, CalloutItem)):
            self.ed.edit_item(it)
            return
        p = self.view.snap(e.pos)
        txt = self.ed.ask_text("", "Новый текст")
        self.view.snap_hit = None
        if not txt:
            return
        item = TextItem({"text": txt})
        item.layer_id = self.doc.target_layer_id()
        item.setPos(p)
        self.ed.add_items([item], self.title)


# =====================================================================
class CalloutTool(Tool, _TempMixin):
    creation = True
    name = "callout"
    title = "Выноска"
    shortcut = "C"

    def __init__(self, editor):
        super().__init__(editor)
        self.temp = None
        self.p0 = None

    def busy(self):
        return self.temp is not None

    def hint(self):
        return "Нажмите на объект и тяните к месту текста, отпустите — введите комментарий"

    def press(self, e):
        if e.button != Qt.LeftButton:
            return
        self.p0 = self.view.snap(e.pos)
        item = CalloutItem({"text": "…"})
        self._start_temp(item)
        self._place(self.p0 + QPointF(40, -50))

    def _place(self, p1: QPointF):
        it = self.temp
        it.prepareGeometryChange()
        box = it.box()
        x = p1.x() if p1.x() >= self.p0.x() else p1.x() - box.width()
        pos = QPointF(x, p1.y() - box.height() / 2)
        it.setPos(pos)
        it.tip = self.p0 - pos
        it.update()

    def move(self, e):
        if self.temp is None:
            return super().move(e)
        if e.left_down:
            self._place(e.pos)

    def release(self, e):
        if self.temp is None or e.button != Qt.LeftButton:
            return
        p1 = e.pos if self.screen_dist(e.pos, self.p0) > MIN_SIZE_PX * 3 else self.p0 + QPointF(
            60 / self.view.scale_factor(), -60 / self.view.scale_factor())
        self._place(p1)
        anchor_right = p1.x() >= self.p0.x()
        txt = self.ed.ask_text("", "Текст выноски")
        self.view.snap_hit = None
        if not txt:
            self._drop_temp()
            return
        self.temp.set_prop("text", txt)
        # после смены текста ширина блока изменилась — поправим положение
        if not anchor_right:
            self._place(p1)
        self._commit_temp(self.title)

    def cancel(self):
        if self.temp is None:
            return False
        self._drop_temp()
        return True


# =====================================================================
class NumberTool(Tool, _TempMixin):
    creation = True
    name = "number"
    title = "Нумерация"
    shortcut = "N"

    def __init__(self, editor):
        super().__init__(editor)
        self.temp = None
        self.p0 = None

    def busy(self):
        return self.temp is not None

    def hint(self):
        n = self.doc.next_number()
        return f"Клик — маркер №{n}; нажать на объект и тянуть — маркер с указателем"

    def press(self, e):
        if e.button != Qt.LeftButton:
            return
        self.p0 = self.view.snap(e.pos)
        self._start_temp(NumberItem({"number": self.doc.next_number()}))
        self.temp.setPos(self.p0)

    def move(self, e):
        if self.temp is None:
            return super().move(e)
        if e.left_down and self.screen_dist(e.pos, self.p0) > MIN_SIZE_PX * 3:
            it = self.temp
            it.prepareGeometryChange()
            it.props["leader"] = True
            it.setPos(e.pos)
            it.tip = self.p0 - e.pos
            it.update()

    def release(self, e):
        if self.temp is None or e.button != Qt.LeftButton:
            return
        self._commit_temp(self.title)
        self.view.snap_hit = None

    def cancel(self):
        if self.temp is None:
            return False
        self._drop_temp()
        return True


# =====================================================================
class RasterSelectTool(Tool):
    name = "raster"
    title = "Выделение области изображения"
    shortcut = "M"
    show_snap = False

    def __init__(self, editor):
        super().__init__(editor)
        self.p0 = None

    def busy(self):
        return self.p0 is not None

    def hint(self):
        return ("Выделите область фото. Ctrl+C — копировать, Ctrl+X — вырезать, Del — очистить, "
                "меню «Изображение» — заливка, прозрачность, обрезка, «в объект»")

    def _clamp(self, p: QPointF):
        r = self.doc.canvas_rect()
        x = min(max(round(p.x()), int(r.left())), int(r.right()))
        y = min(max(round(p.y()), int(r.top())), int(r.bottom()))
        return QPointF(x, y)

    def press(self, e):
        if e.button != Qt.LeftButton or self.doc.background is None:
            return
        self.p0 = self._clamp(e.pos)
        self.ed.set_raster_selection(None)

    def move(self, e):
        if self.p0 is None:
            return
        p1 = self._clamp(e.pos)
        r = QRectF(self.p0, p1).normalized()
        self.ed.set_raster_selection(QRect(int(r.x()), int(r.y()), int(r.width()), int(r.height())))

    def release(self, e):
        if self.p0 is None:
            return
        self.move(e)
        r = self.ed.raster_sel
        if r is not None and (r.width() < 2 or r.height() < 2):
            self.ed.set_raster_selection(None)
        self.p0 = None

    def cancel(self):
        if self.p0 is not None or self.ed.raster_sel is not None:
            self.p0 = None
            self.ed.set_raster_selection(None)
            return True
        return False

    def action_bar(self):
        r = self.ed.raster_sel
        if r is None or self.p0 is not None:
            return None
        return (f"Область {r.width()}×{r.height()} — ПКМ: копировать, размыть, залить…",
                [("В объект", self.ed.raster_to_object), ("✕  Снять выделение", self.cancel)])


def make_tools(editor):
    from .crop_tool import CropTool
    from .select_tool import SelectTool
    return [
        SelectTool(editor),
        RasterSelectTool(editor),
        CropTool(editor),
        TwoPointTool(editor, ArrowItem, "arrow", "Стрелка", "A"),
        TwoPointTool(editor, LineItem, "line", "Линия", "L"),
        TwoPointTool(editor, DimensionItem, "dimension", "Размер (расстояние)", "D"),
        TwoPointTool(editor, BreakItem, "break", "Разрыв цепи", "B"),
        TwoPointTool(editor, MagnifierItem, "magnifier", "Выносной вид (лупа)", "Z", box=True),
        TextTool(editor),
        CalloutTool(editor),
        NumberTool(editor),
        TwoPointTool(editor, RectItem, "rect", "Прямоугольник", "R", box=True),
        TwoPointTool(editor, EllipseItem, "ellipse", "Эллипс", "E", box=True),
        PolyTool(editor, PolylineItem, "polyline", "Полилиния", "P"),
        PolyTool(editor, PolygonItem, "polygon", "Полигон", "G"),
        FreehandTool(editor),
    ]
