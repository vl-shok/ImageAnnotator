"""Инструмент «Обрезка» (K).

* без выделения — работает с холстом: рамку можно сжать (обрезка) или вытянуть за пределы
  фото — холст увеличится (новое место заливается цветом холста);
* если выбрано одно вставленное изображение — обрезает его (неразрушающе);
* тянуть маркеры — менять рамку (Shift — сохранить пропорции, Alt — от центра);
* внутри рамки — перемещать её, снаружи — нарисовать новую;
* Enter / двойной клик — применить, Esc / ПКМ — выйти без изменений.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen

from ..geometry import dist
from .base import Tool, ToolEvent

HIDS = ("tl", "t", "tr", "r", "br", "b", "bl", "l")
CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor,
           "bl": Qt.SizeBDiagCursor, "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
           "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor}


class CropTool(Tool):
    name = "crop"
    title = "Обрезка / размер холста"
    shortcut = "K"
    cursor = Qt.CrossCursor
    show_snap = False

    def __init__(self, editor):
        super().__init__(editor)
        self.frame: QRectF | None = None
        self.target_item = None
        self.state = None
        self._r0 = None
        self._hid = None
        self._p0 = None

    def hint(self):
        return ("Тяните маркеры (за край фото — увеличить холст), Shift — пропорции, Alt — от центра; "
                "Enter / двойной клик — применить, Esc / ПКМ — выйти")

    # ------------------------------------------------------------------
    def activate(self):
        super().activate()
        sel = self.ed.sel.items
        self.target_item = sel[0] if (len(sel) == 1 and sel[0].TYPE == "image" and not sel[0].locked) else None
        self.reset_frame()

    def deactivate(self):
        self.state = None
        self.frame = None
        self.target_item = None
        if self.view:
            self.view.viewport().update()

    def reset_frame(self):
        if self.target_item is not None:
            self.frame = QRectF(self.target_item.content_rect())
        else:
            r = self.doc.canvas_rect()
            self.frame = QRectF(r) if not r.isEmpty() else None
        self.state = None
        self._changed()

    def _changed(self):
        if self.view:
            self.view.viewport().update()
        self.ed.cropChanged.emit()

    # ------------------------------------------------------------------ geometry
    def _handle_points(self):
        r = self.frame
        c = r.center()
        return [r.topLeft(), QPointF(c.x(), r.top()), r.topRight(), QPointF(r.right(), c.y()),
                r.bottomRight(), QPointF(c.x(), r.bottom()), r.bottomLeft(), QPointF(r.left(), c.y())]

    def _hit_handle(self, pt):
        if self.frame is None:
            return None
        tol = self.view.px(9)
        best, bd = None, tol
        for hid, hp in zip(HIDS, self._handle_points()):
            d = dist(hp, pt)
            if d <= bd:
                best, bd = hid, d
        return best

    def _snap_edges(self, r: QRectF) -> QRectF:
        """Притягивать стороны рамки к краям фото (удобно вернуть исходный размер)."""
        canvas = self.doc.canvas_rect()
        if canvas.isEmpty() or not self.ed.snap.enabled:
            return r
        tol = self.view.px(8)
        l, t, rr, b = r.left(), r.top(), r.right(), r.bottom()
        for attr, val in (("l", l), ("r", rr)):
            for edge in (canvas.left(), canvas.right()):
                if abs(val - edge) <= tol:
                    if attr == "l":
                        l = edge
                    else:
                        rr = edge
        for attr, val in (("t", t), ("b", b)):
            for edge in (canvas.top(), canvas.bottom()):
                if abs(val - edge) <= tol:
                    if attr == "t":
                        t = edge
                    else:
                        b = edge
        return QRectF(QPointF(l, t), QPointF(rr, b))

    def _resize(self, p: QPointF, keep_aspect: bool, symmetric: bool) -> QRectF:
        r0, hid = self._r0, self._hid
        if symmetric:
            c = r0.center()
            hw, hh = r0.width() / 2, r0.height() / 2
            if "l" in hid or "r" in hid:
                hw = abs(p.x() - c.x())
            if "t" in hid or "b" in hid:
                hh = abs(p.y() - c.y())
            if keep_aspect and len(hid) == 2 and r0.height() > 0:
                ratio = r0.width() / r0.height()
                hh = max(hh, hw / ratio)
                hw = hh * ratio
            return QRectF(c.x() - hw, c.y() - hh, 2 * hw, 2 * hh)
        left, top, right, bottom = r0.left(), r0.top(), r0.right(), r0.bottom()
        if "l" in hid:
            left = p.x()
        if "r" in hid:
            right = p.x()
        if "t" in hid:
            top = p.y()
        if "b" in hid:
            bottom = p.y()
        r = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()
        if keep_aspect and len(hid) == 2 and r0.height() > 0:
            ratio = r0.width() / r0.height()
            ax = r0.right() if "l" in hid else r0.left()
            ay = r0.bottom() if "t" in hid else r0.top()
            w, h = r.width(), r.height()
            if w / max(h, 1e-6) > ratio:
                h = w / ratio
            else:
                w = h * ratio
            sx = -1 if p.x() < ax else 1
            sy = -1 if p.y() < ay else 1
            r = QRectF(QPointF(ax, ay), QPointF(ax + sx * w, ay + sy * h)).normalized()
        return r

    def _finalize(self, r: QRectF) -> QRectF:
        if self.target_item is not None:
            r = r.intersected(self.target_item.content_rect())
        else:
            r = self._snap_edges(r)
            r = QRectF(round(r.left()), round(r.top()), round(r.width()), round(r.height()))
        return r

    # ------------------------------------------------------------------ events
    def press(self, e: ToolEvent):
        if e.button != Qt.LeftButton or self.frame is None:
            return
        hid = self._hit_handle(e.pos)
        if hid is not None:
            self.state, self._hid, self._r0 = "handle", hid, QRectF(self.frame)
        elif self.frame.contains(e.pos):
            self.state, self._p0, self._r0 = "move", QPointF(e.pos), QRectF(self.frame)
        else:
            self.state, self._p0 = "new", QPointF(e.pos)

    def move(self, e: ToolEvent):
        if self.frame is None:
            return
        if self.state is None:
            hid = self._hit_handle(e.pos)
            if hid:
                self.view.viewport().setCursor(CURSORS[hid])
            elif self.frame.contains(e.pos):
                self.view.viewport().setCursor(Qt.SizeAllCursor)
            else:
                self.view.viewport().setCursor(Qt.CrossCursor)
            return
        if self.state == "handle":
            self.frame = self._finalize(self._resize(e.pos, e.shift, e.alt))
        elif self.state == "move":
            d = e.pos - self._p0
            self.frame = self._finalize(self._r0.translated(d.x(), d.y()))
        elif self.state == "new":
            if self.screen_dist(e.pos, self._p0) > 3:
                self.frame = self._finalize(QRectF(self._p0, e.pos).normalized())
        self._changed()

    def release(self, e: ToolEvent):
        self.state = None

    def double_click(self, e: ToolEvent):
        self.finish()

    def busy(self):
        return False

    def cancel(self):
        if self.state is not None:
            self.state = None
            if self._r0 is not None:
                self.frame = QRectF(self._r0)
            self._changed()
            return True
        return False

    def finish(self):
        if self.frame is None or self.frame.width() < 1 or self.frame.height() < 1:
            return False
        if self.target_item is not None:
            if self.frame != self.target_item.content_rect():
                self.ed.crop_image_item(self.target_item, self.frame)
        else:
            self.ed.crop_canvas_to(self.frame)
        self.ed.set_tool("select")
        return True

    def action_bar(self):
        if self.frame is None:
            return None
        what = "изображения" if self.target_item is not None else "холста"
        return (f"Обрезка {what}",
                [("✓  Применить", self.finish), ("⟲  Сбросить рамку", self.reset_frame),
                 ("✕  Отменить", lambda: self.ed.set_tool("select"))])

    # ------------------------------------------------------------------ overlay
    def draw_overlay(self, painter, view):
        if self.frame is None:
            return
        r = self.frame
        painter.save()
        vis = view.mapToScene(view.viewport().rect()).boundingRect().united(r).adjusted(-10, -10, 10, 10)
        path = QPainterPath()
        path.addRect(vis)
        hole = QPainterPath()
        hole.addRect(r)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, 120))
        painter.drawPath(path.subtracted(hole))
        # новое место холста (за пределами фото) — штриховка
        canvas = self.doc.canvas_rect()
        if self.target_item is None and not canvas.isEmpty() and not canvas.contains(r):
            extra = QPainterPath()
            extra.addRect(r)
            cp = QPainterPath()
            cp.addRect(canvas)
            painter.setBrush(QColor(self.doc.canvas_color))
            painter.setOpacity(0.55)
            painter.drawPath(extra.subtracted(cp))
            painter.setOpacity(1.0)
        pen = QPen(QColor(255, 255, 255), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(r)
        thin = QPen(QColor(255, 255, 255, 90), 1)
        thin.setCosmetic(True)
        painter.setPen(thin)
        for k in (1, 2):
            x = r.left() + r.width() * k / 3
            y = r.top() + r.height() * k / 3
            painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
        s = view.px(9)
        hp = QPen(QColor(20, 20, 20), 1)
        hp.setCosmetic(True)
        painter.setPen(hp)
        painter.setBrush(QColor(255, 255, 255))
        for pt in self._handle_points():
            painter.drawRect(QRectF(pt.x() - s / 2, pt.y() - s / 2, s, s))
        # размер
        vp = view.mapFromScene(r.bottomRight())
        painter.resetTransform()
        f = QFont(view.font())
        f.setPointSizeF(9)
        painter.setFont(f)
        label = f"{r.width():.0f} × {r.height():.0f}"
        tr = painter.fontMetrics().boundingRect(label)
        box = QRectF(vp.x() - tr.width() - 14, vp.y() + 6, tr.width() + 10, tr.height() + 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 20, 20, 210))
        painter.drawRoundedRect(box, 3, 3)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(box, Qt.AlignCenter, label)
        painter.restore()
