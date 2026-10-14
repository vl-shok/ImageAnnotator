"""CanvasView — рабочая область.

* навигация в стиле Altium: ПКМ+движение — панорама, СКМ+движение вверх/вниз — масштаб,
  колесо — масштаб относительно курсора, короткий клик ПКМ — контекстное меню;
* централизованный hit-testing (ручки → объекты), hover, индикаторы привязки;
* все служебные элементы (ручки, рамки, подсветка, привязки) рисуются в drawForeground
  и поэтому никогда не попадают в экспорт.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QFrame, QGraphicsView

from .geometry import dist
from .items import AnnotationItem
from .items import base as items_base
from .snap import SNAP_LABELS
from .tools.base import ToolEvent

ACCENT = QColor(0, 150, 255)
HOVER = QColor(120, 200, 255, 150)
HANDLE_PX = 7
HANDLE_HIT_PX = 7
SNAP_COLOR = QColor(255, 210, 0)


def _checker_brush():
    pm = QPixmap(16, 16)
    pm.fill(QColor(255, 255, 255))
    p = QPainter(pm)
    p.fillRect(0, 0, 8, 8, QColor(205, 205, 205))
    p.fillRect(8, 8, 8, 8, QColor(205, 205, 205))
    p.end()
    return QBrush(pm)


class ActionBar(QFrame):
    """Плавающая панель «Применить / Отменить» над холстом."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("ActionBar")
        self.setStyleSheet(
            "QFrame#ActionBar { background: rgba(32,34,38,235); border: 1px solid #4a90d9; border-radius: 6px; }"
            "QLabel { color: #e6e9ee; padding: 0 6px; }"
            "QToolButton { background: #3a3e45; border: 1px solid #555a63; border-radius: 4px; color: #fff;"
            " padding: 4px 10px; }"
            "QToolButton:hover { background: #2f6db3; border-color: #4aa3ff; }")
        from PySide6.QtWidgets import QHBoxLayout, QLabel
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(8, 4, 6, 4)
        self.lay.setSpacing(4)
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.lay.addWidget(self.label, 0, Qt.AlignVCenter)
        self._buttons = []
        self._key = None
        self.hide()

    def set_content(self, content):
        if content is None:
            self._key = None
            self.hide()
            return
        text, actions = content
        key = tuple(a[0] for a in actions)  # кнопки пересоздаются только при смене набора
        self.label.setText(text)
        if key != self._key:
            from PySide6.QtWidgets import QToolButton
            for b in self._buttons:
                self.lay.removeWidget(b)
                b.hide()
                b.deleteLater()
            self._buttons = []
            for label, fn in actions:
                b = QToolButton()
                b.setText(label)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(fn)
                self.lay.addWidget(b)
                self._buttons.append(b)
            self._key = key
        self.label.adjustSize()
        self.adjustSize()
        par = self.parentWidget()
        self.move(max(4, (par.width() - self.width()) // 2), 8)
        self.show()
        self.raise_()


class CanvasView(QGraphicsView):
    cursorMoved = Signal(QPointF)
    zoomChanged = Signal(float)
    contextMenuRequested = Signal(QPoint, QPointF)
    filesDropped = Signal(list, QPointF)

    def __init__(self, editor, parent=None):
        super().__init__(editor.doc.scene, parent)
        self.ed = editor
        editor.view = self
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QFrame.NoFrame)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setDragMode(QGraphicsView.NoDrag)
        self.hover_item = None
        self.hover_handle = None
        self.snap_hit = None
        self.rubber = None
        self._pan = None
        self._zoomdrag = None
        self._right_press = None
        self._last = None  # (scene_pos, view_pos, buttons)
        self._checker = _checker_brush()
        self._ants = 0
        self._ants_timer = QTimer(self)
        self._ants_timer.setInterval(150)
        self._ants_timer.timeout.connect(self._tick_ants)
        editor.rasterSelectionChanged.connect(self._on_raster_sel)
        self.action_bar = ActionBar(self)
        self._bar_timer = QTimer(self)
        self._bar_timer.setSingleShot(True)
        self._bar_timer.setInterval(0)
        self._bar_timer.timeout.connect(self.update_action_bar)
        editor.toolChanged.connect(lambda *_: self._bar_timer.start())
        editor.cropChanged.connect(self._bar_timer.start)
        editor.rasterSelectionChanged.connect(self._bar_timer.start)
        editor.sel.changed.connect(self.viewport().update)
        editor.doc.itemsModified.connect(self.viewport().update)
        editor.doc.itemsChanged.connect(self._on_items_changed)

    # ================================================================ geometry helpers
    def scale_factor(self) -> float:
        return self.transform().m11() or 1.0

    def px(self, n: float) -> float:
        """n экранных пикселей в единицах сцены."""
        return n / self.scale_factor()

    def snap(self, pt: QPointF, exclude=(), extra=None) -> QPointF:
        res = self.ed.snap.find(self.ed.doc, pt, self.px(self.ed.snap.radius_px), exclude, extra)
        if res != self.snap_hit:
            self.snap_hit = res
            self.viewport().update()
        return QPointF(res[0]) if res else QPointF(pt)

    def hit_handle(self, pt: QPointF):
        sel = self.ed.sel
        tol = self.px(HANDLE_HIT_PX)
        best, bd = None, tol
        for it in reversed(sel.items):
            if not sel.is_movable(it):
                continue
            for idx, h in enumerate(it.handles()):
                d = dist(it.mapToScene(h), pt)
                if d <= bd:
                    best, bd = (it, idx), d
        return best

    def hit_item(self, pt: QPointF):
        sel = self.ed.sel
        tol = self.px(4)
        area = QRectF(pt.x() - tol, pt.y() - tol, 2 * tol, 2 * tol)
        for it in self.scene().items(area, Qt.IntersectsItemBoundingRect, Qt.DescendingOrder):
            if isinstance(it, AnnotationItem) and sel.is_selectable(it) and it.hit(pt, tol):
                return it
        return None

    def update_hover(self, pt: QPointF):
        h = self.hit_handle(pt)
        it = None if h else self.hit_item(pt)
        if h != self.hover_handle or it is not self.hover_item:
            self.hover_handle, self.hover_item = h, it
            self.viewport().update()
        tool = self.ed.tool
        if tool is not None and tool.name == "select":
            if h:
                self.viewport().setCursor(h[0].handle_cursor(h[1]))
            elif it is not None:
                self.viewport().setCursor(Qt.SizeAllCursor if self.ed.sel.is_movable(it) else Qt.ArrowCursor)
            else:
                self.viewport().setCursor(Qt.ArrowCursor)

    def _on_items_changed(self):
        if self.hover_item is not None and not self.ed.doc.contains(self.hover_item):
            self.hover_item = None
        self.hover_handle = None
        self.viewport().update()

    # ================================================================ zoom / pan
    def zoom_at(self, factor: float, view_pos: QPoint):
        old = self.mapToScene(view_pos)
        cur = self.scale_factor()
        new = max(0.02, min(64.0, cur * factor))
        f = new / cur
        if abs(f - 1) < 1e-9:
            return
        self.scale(f, f)
        items_base.set_view_scale(new)
        moved = self.mapFromScene(old)
        d = moved - view_pos
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() + d.x())
        self.verticalScrollBar().setValue(self.verticalScrollBar().value() + d.y())
        self.zoomChanged.emit(new)

    def set_zoom(self, z: float):
        self.zoom_at(z / self.scale_factor(), self.viewport().rect().center())

    def fit(self):
        r = self.ed.doc.export_rect()
        if r.isEmpty():
            r = QRectF(0, 0, 1600, 1000)
        vp = self.viewport().rect()
        if vp.width() < 10 or vp.height() < 10:
            return
        k = min(vp.width() / r.width(), vp.height() / r.height()) * 0.96
        self.resetTransform()
        self.scale(k, k)
        items_base.set_view_scale(k)
        self.centerOn(r.center())
        self.zoomChanged.emit(k)

    def actual_size(self):
        c = self.mapToScene(self.viewport().rect().center())
        self.resetTransform()
        items_base.set_view_scale(1.0)
        self.centerOn(c)
        self.zoomChanged.emit(1.0)

    def visible_center(self) -> QPointF:
        return self.mapToScene(self.viewport().rect().center())

    # ================================================================ events
    def _tool_event(self, ev, button=Qt.NoButton):
        pos = self.mapToScene(ev.position().toPoint())
        return ToolEvent(pos, ev.position().toPoint(), ev.modifiers(), button, ev.buttons())

    def mousePressEvent(self, ev):
        self.setFocus()
        b = ev.button()
        if b == Qt.RightButton:
            self._right_press = ev.position().toPoint()
            self._pan = (ev.position().toPoint(), self.horizontalScrollBar().value(), self.verticalScrollBar().value())
            return
        if b == Qt.MiddleButton:
            self._zoomdrag = (ev.position().toPoint(), ev.position().toPoint().y())
            self.viewport().setCursor(Qt.SizeVerCursor)
            return
        if b == Qt.LeftButton and self.ed.tool is not None:
            self.ed.tool.press(self._tool_event(ev, b))
            self.viewport().update()

    def mouseMoveEvent(self, ev):
        vp = ev.position().toPoint()
        if self._pan is not None:
            start, h, v = self._pan
            d = vp - start
            if self._right_press is not None and (abs(d.x()) + abs(d.y())) > 4:
                self._right_press = None
                self.viewport().setCursor(Qt.ClosedHandCursor)
            self.horizontalScrollBar().setValue(h - d.x())
            self.verticalScrollBar().setValue(v - d.y())
            return
        if self._zoomdrag is not None:
            anchor, lasty = self._zoomdrag
            dy = vp.y() - lasty
            self._zoomdrag = (anchor, vp.y())
            self.zoom_at(math.exp(-dy * 0.01), anchor)
            return
        e = self._tool_event(ev)
        self._last = e
        if self.ed.tool is not None:
            self.ed.tool.move(e)
        self.cursorMoved.emit(e.pos)

    def mouseReleaseEvent(self, ev):
        b = ev.button()
        if b == Qt.RightButton:
            self._pan = None
            if self.ed.tool is not None:
                self.viewport().setCursor(self.ed.tool.cursor)
            if self._right_press is not None:
                self._right_press = None
                # короткий клик ПКМ в инструменте рисования: завершить/отменить построение
                # и перейти к инструменту «Выбор» (созданный объект остаётся выделенным)
                tool = self.ed.tool
                spos = self.mapToScene(ev.position().toPoint())
                # выделение области: ПКМ внутри выделения — меню действий, иначе — выход в «Выбор»
                in_area = (tool is not None and tool.name == "raster" and self.ed.raster_sel is not None
                           and QRectF(self.ed.raster_sel).contains(spos))
                if tool is not None and (tool.creation or tool.name == "crop" or
                                         (tool.name == "raster" and not in_area)):
                    if tool.busy() and not tool.finish():
                        tool.cancel()
                    self.ed.set_tool("select")
                    self.snap_hit = None
                    self.viewport().update()
                    return
                self.contextMenuRequested.emit(ev.globalPosition().toPoint(), self.mapToScene(ev.position().toPoint()))
            return
        if b == Qt.MiddleButton:
            self._zoomdrag = None
            if self.ed.tool is not None:
                self.viewport().setCursor(self.ed.tool.cursor)
            return
        if b == Qt.LeftButton and self.ed.tool is not None:
            self.ed.tool.release(self._tool_event(ev, b))
            self.viewport().update()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.ed.tool is not None:
            self.ed.tool.double_click(self._tool_event(ev, Qt.LeftButton))
            self.viewport().update()
            return
        if ev.button() == Qt.MiddleButton:
            self.fit()

    def wheelEvent(self, ev):
        dy = ev.angleDelta().y()
        if ev.modifiers() & Qt.ShiftModifier:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - dy)
            return
        if dy:
            self.zoom_at(1.0015 ** dy, ev.position().toPoint())

    def leaveEvent(self, ev):
        self.hover_item = None
        self.hover_handle = None
        if self.ed.tool is not None and not self.ed.tool.busy():
            self.snap_hit = None
        self.viewport().update()
        super().leaveEvent(ev)

    def _redispatch(self):
        if self._last is not None and self.ed.tool is not None:
            from PySide6.QtWidgets import QApplication
            mods = QApplication.keyboardModifiers()
            e = ToolEvent(self._last.pos, self._last.view_pos, mods, Qt.NoButton,
                          QApplication.mouseButtons())
            self.ed.tool.move(e)
            self.viewport().update()

    def keyPressEvent(self, ev):
        self._bar_timer.start()
        tool = self.ed.tool
        k = ev.key()
        if tool is not None and tool.key(ev):
            self.viewport().update()
            return
        if k == Qt.Key_Escape:
            self.escape()
            return
        if k in (Qt.Key_Return, Qt.Key_Enter):
            if tool is not None:
                tool.finish()
            self.viewport().update()
            return
        if k == Qt.Key_Shift:
            self._redispatch()
        if k == Qt.Key_Space and self.ed.sel.items and not ev.isAutoRepeat():
            self.ed.rotate_selected(-45.0 if ev.modifiers() & Qt.ShiftModifier else 45.0)
            self.viewport().update()
            return
        if k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down) and self.ed.sel.items:
            step = 10 if ev.modifiers() & Qt.ShiftModifier else 1
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0)
            self.ed.nudge(dx, dy)
            return
        super().keyPressEvent(ev)

    def escape(self):
        """Esc: отменить текущую операцию → снять выделение → вернуться к инструменту выбора."""
        tool = self.ed.tool
        if tool is not None and tool.cancel():
            pass
        elif tool is not None and tool.name != "select":
            self.ed.set_tool("select")
        elif self.ed.sel.items:
            self.ed.sel.clear()
        self.snap_hit = None
        self._bar_timer.start()
        self.viewport().update()

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key_Shift:
            self._redispatch()
        super().keyReleaseEvent(ev)

    # drag & drop файлов
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() or ev.mimeData().hasImage():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        pos = self.mapToScene(ev.position().toPoint())
        if paths:
            self.filesDropped.emit(paths, pos)
            ev.acceptProposedAction()
        elif ev.mimeData().hasImage():
            from PySide6.QtGui import QImage
            self.ed.insert_image(QImage(ev.mimeData().imageData()), pos)
            ev.acceptProposedAction()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._bar_timer.start()

    def update_action_bar(self):
        tool = self.ed.tool
        try:
            content = tool.action_bar() if tool is not None else None
        except Exception:
            content = None
        self.action_bar.set_content(content)

    def viewportEvent(self, ev):
        res = super().viewportEvent(ev)
        from PySide6.QtCore import QEvent
        if ev.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseButtonDblClick,
                         QEvent.KeyPress):
            self._bar_timer.start()
        return res

    # ================================================================ painting
    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QColor(38, 40, 44))
        doc = self.ed.doc
        canvas = doc.canvas_rect()
        if canvas.isEmpty():
            return
        painter.save()
        painter.setPen(Qt.NoPen)
        sh = self.px(6)
        painter.fillRect(canvas.translated(sh, sh), QColor(0, 0, 0, 90))
        # «шахматка» видна там, где фон прозрачен или слой фона скрыт
        painter.fillRect(canvas, self._checker)
        painter.restore()

    def drawForeground(self, painter: QPainter, rect: QRectF):
        doc, sel = self.ed.doc, self.ed.sel
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        canvas = doc.canvas_rect()
        if canvas.isEmpty() and not doc.items():
            self._draw_hint(painter)
            painter.restore()
            return

        # hover
        if self.hover_item is not None and not sel.contains(self.hover_item) and self.hover_item.isVisible():
            pen = QPen(HOVER, 3)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(self.hover_item.mapToScene(self.hover_item.outline_path()))

        # selection
        cropping = self.ed.tool is not None and self.ed.tool.name == "crop"
        for it in ([] if cropping else sel.items):
            if not it.isVisible():
                continue
            locked = it.locked
            col = QColor(255, 90, 90) if locked else ACCENT
            r = it.content_rect().adjusted(-self.px(3), -self.px(3), self.px(3), self.px(3))
            pen = QPen(col, 1, Qt.DashLine)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r)
            pen2 = QPen(QColor(col.red(), col.green(), col.blue(), 120), 1)
            pen2.setCosmetic(True)
            painter.setPen(pen2)
            painter.drawPath(it.mapToScene(it.outline_path()))
            if not locked and sel.is_movable(it):
                kinds = it.handle_kinds()
                hs = it.handles()
                if "rot" in kinds:
                    ri = kinds.index("rot")
                    br = it.outline_path().boundingRect()
                    top = it.mapToScene(QPointF(br.center().x(), br.top()))
                    pen = QPen(ACCENT, 1)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.drawLine(top, it.mapToScene(hs[ri]))
                for idx, h in enumerate(hs):
                    sp = it.mapToScene(h)
                    hov = self.hover_handle == (it, idx)
                    self._draw_handle(painter, sp, hov, kinds[idx] if idx < len(kinds) else "point")

        # служебная графика инструмента (обрезка и т.п.)
        if self.ed.tool is not None:
            self.ed.tool.draw_overlay(painter, self)

        # rubber band
        if self.rubber is not None:
            r, crossing = self.rubber
            if crossing:
                pen = QPen(QColor(80, 220, 120), 1, Qt.DashLine)
                fill = QColor(80, 220, 120, 35)
            else:
                pen = QPen(ACCENT, 1)
                fill = QColor(0, 150, 255, 35)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(fill)
            painter.drawRect(r)

        # raster selection (marching ants)
        rs = self.ed.raster_sel
        if rs is not None:
            rr = QRectF(rs)
            p1 = QPen(QColor(255, 255, 255), 1)
            p1.setCosmetic(True)
            painter.setPen(p1)
            painter.setBrush(QColor(0, 120, 255, 25))
            painter.drawRect(rr)
            p2 = QPen(QColor(0, 0, 0), 1, Qt.CustomDashLine)
            p2.setDashPattern([4, 4])
            p2.setDashOffset(self._ants)
            p2.setCosmetic(True)
            painter.setPen(p2)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rr)

        # snap indicator
        if self.snap_hit is not None:
            self._draw_snap(painter, *self.snap_hit)
        painter.restore()

    def _draw_handle(self, painter, sp: QPointF, hover: bool, kind="point"):
        if kind == "insert":
            s = self.px(7 if hover else 5)
            r = QRectF(sp.x() - s / 2, sp.y() - s / 2, s, s)
            pen = QPen(QColor(255, 255, 255, 220) if hover else QColor(255, 255, 255, 140), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 140, 0) if hover else QColor(0, 120, 220, 150))
            painter.drawRect(r)
            k = s * 0.3
            painter.drawLine(QPointF(sp.x() - k, sp.y()), QPointF(sp.x() + k, sp.y()))
            painter.drawLine(QPointF(sp.x(), sp.y() - k), QPointF(sp.x(), sp.y() + k))
            return
        if kind == "rot":
            s = self.px(HANDLE_PX + (3 if hover else 1)) / 2
            pen = QPen(QColor(20, 20, 20), 1)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QColor(255, 140, 0) if hover else QColor(120, 220, 255))
            painter.drawEllipse(sp, s, s)
            return
        s = self.px(HANDLE_PX + (3 if hover else 0))
        r = QRectF(sp.x() - s / 2, sp.y() - s / 2, s, s)
        pen = QPen(QColor(20, 20, 20) if not hover else QColor(255, 255, 255), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QColor(255, 140, 0) if hover else QColor(255, 255, 255))
        painter.drawRect(r)

    def _draw_snap(self, painter, p: QPointF, kind: str):
        s = self.px(6)
        pen = QPen(SNAP_COLOR, 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if kind == "endpoint":
            painter.drawRect(QRectF(p.x() - s, p.y() - s, 2 * s, 2 * s))
        elif kind == "midpoint":
            painter.drawPolygon(QPolygonF([QPointF(p.x(), p.y() - s * 1.2), QPointF(p.x() + s * 1.1, p.y() + s * 0.8),
                                           QPointF(p.x() - s * 1.1, p.y() + s * 0.8)]))
        elif kind == "center":
            painter.drawEllipse(p, s, s)
            painter.drawLine(QPointF(p.x() - s * 1.5, p.y()), QPointF(p.x() + s * 1.5, p.y()))
            painter.drawLine(QPointF(p.x(), p.y() - s * 1.5), QPointF(p.x(), p.y() + s * 1.5))
        elif kind == "vertex":
            painter.drawPolygon(QPolygonF([QPointF(p.x(), p.y() - s * 1.3), QPointF(p.x() + s * 1.3, p.y()),
                                           QPointF(p.x(), p.y() + s * 1.3), QPointF(p.x() - s * 1.3, p.y())]))
        else:
            painter.drawLine(QPointF(p.x() - s, p.y() - s), QPointF(p.x() + s, p.y() + s))
            painter.drawLine(QPointF(p.x() - s, p.y() + s), QPointF(p.x() + s, p.y() - s))
        # подпись в экранных координатах
        vp = self.mapFromScene(p)
        painter.save()
        painter.resetTransform()
        f = QFont(self.font())
        f.setPointSizeF(8)
        painter.setFont(f)
        label = SNAP_LABELS.get(kind, kind)
        tr = painter.fontMetrics().boundingRect(label)
        box = QRectF(vp.x() + 10, vp.y() + 8, tr.width() + 8, tr.height() + 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(20, 20, 20, 200))
        painter.drawRoundedRect(box, 3, 3)
        painter.setPen(SNAP_COLOR)
        painter.drawText(box, Qt.AlignCenter, label)
        painter.restore()

    def _draw_hint(self, painter):
        painter.save()
        painter.resetTransform()
        r = QRectF(self.viewport().rect())
        f = QFont(self.font())
        f.setPointSizeF(13)
        painter.setFont(f)
        painter.setPen(QColor(170, 175, 185))
        painter.drawText(r, Qt.AlignCenter,
                         "Откройте фото  (Ctrl+O)\n\nили перетащите файл сюда,\n"
                         "или вставьте снимок из буфера  (Ctrl+V)")
        painter.restore()

    def _on_raster_sel(self):
        if self.ed.raster_sel is not None:
            self._ants_timer.start()
        else:
            self._ants_timer.stop()
        self.viewport().update()

    def _tick_ants(self):
        self._ants = (self._ants + 1) % 8
        self.viewport().update()
