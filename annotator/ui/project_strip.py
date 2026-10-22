"""Лента открытых проектов над холстом — вкладки, под которыми выезжают миниатюры.

* щелчок по вкладке — перейти к проекту; колесо над лентой — листать (от себя — следующий справа);
* перетаскивание вкладки — поменять порядок; «×» на вкладке — закрыть проект;
* двойной щелчок по имени — переименовать (у сохранённого проекта — и файл .iap);
* «+» (и файлы, брошенные на ленту) — открыть фото/проекты;
* ПКМ — быстрый PNG, дублировать, переименовать, закрыть и т.д.;
* без закрепления видны только вкладки, миниатюры выезжают при наведении (поверх холста).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLineEdit, QMenu, QScrollArea, QSizePolicy, QToolButton,
                               QWidget)

from .icons import icon

ACCENT = QColor(0, 150, 255)
CANVAS_BG = QColor(38, 40, 44)     # фон холста — активная вкладка «сливается» с ним
TAB_W = 150
TAB_H = 28
THUMB_H = 80
TAB_GAP = 2
PAD = 4
CLOSE = 16                          # кнопка «×» на вкладке
DRAG_PX = 6
THUMB_SCALE = 2                     # миниатюры рисуются с запасом — чётче на HiDPI


def render_thumb(doc, w: int, h: int) -> QImage | None:
    rect = doc.export_rect()
    if rect.isEmpty():
        return None
    k = min(w / rect.width(), h / rect.height())
    tw, th = max(1, int(rect.width() * k)), max(1, int(rect.height() * k))
    img = QImage(tw, th, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(doc.canvas_color or "#ffffff"))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
    doc.scene.render(p, QRectF(0, 0, tw, th), rect)
    p.end()
    return img


def _tab_path(r: QRectF, rad=6.0) -> QPainterPath:
    """Вкладка: скруглённый верх, прямой низ."""
    p = QPainterPath()
    p.moveTo(r.bottomLeft())
    p.lineTo(r.left(), r.top() + rad)
    p.quadTo(r.left(), r.top(), r.left() + rad, r.top())
    p.lineTo(r.right() - rad, r.top())
    p.quadTo(r.right(), r.top(), r.right(), r.top() + rad)
    p.lineTo(r.bottomRight())
    p.closeSubpath()
    return p


class _Content(QWidget):
    """Сами вкладки и миниатюры (рисуются вручную)."""

    def __init__(self, strip):
        super().__init__()
        self.strip = strip
        self.ed = strip.ed
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self._press = None        # (проект, точка нажатия)
        self._drag = None         # перетаскиваемый проект
        self._drop_index = None
        self._hover = None
        self._hover_close = None  # проект, над «×» которого мышь
        self._editor = None       # (QLineEdit, проект) — переименование

    # ------------------------------------------------------------ geometry
    def expanded(self) -> bool:
        return self.strip.is_expanded()

    def tile_rects(self):
        """[(проект, прямоугольник столбца: вкладка + миниатюра)] и прямоугольник «+»."""
        out = []
        x = PAD
        h = TAB_H + (THUMB_H + PAD * 2 if self.expanded() else 0)
        for p in self.ed.projects:
            out.append((p, QRect(x, PAD, TAB_W, h)))
            x += TAB_W + TAB_GAP
        plus = QRect(x + 2, PAD + 2, TAB_H - 4, TAB_H - 4)
        return out, plus

    @staticmethod
    def tab_rect(r: QRect) -> QRect:
        return QRect(r.left(), r.top(), r.width(), TAB_H)

    @staticmethod
    def thumb_rect(r: QRect) -> QRect:
        return QRect(r.left() + 2, r.top() + TAB_H + PAD, r.width() - 4, THUMB_H)

    @staticmethod
    def close_rect(r: QRect) -> QRect:
        t = QRect(r.left(), r.top(), r.width(), TAB_H)
        return QRect(t.right() - CLOSE - 6, t.center().y() - CLOSE // 2 + 1, CLOSE, CLOSE)

    def name_rect(self, r: QRect) -> QRect:
        t = self.tab_rect(r)
        return QRect(t.left() + 8, t.top() + 1, t.width() - 8 - CLOSE - 10, t.height() - 1)

    def content_size(self) -> QSize:
        tiles, plus = self.tile_rects()
        h = PAD + TAB_H + (THUMB_H + PAD * 2 if self.expanded() else 0)
        return QSize(plus.right() + PAD * 2, h)

    def sizeHint(self):
        return self.content_size()

    def relayout(self):
        self.setFixedSize(self.content_size())
        self.update()

    def project_at(self, pos: QPoint):
        tiles, plus = self.tile_rects()
        for p, r in tiles:
            if self.tab_rect(r).contains(pos) or (self.expanded() and self.thumb_rect(r).contains(pos)):
                return p, r
        if plus.contains(pos):
            return "plus", plus
        return None, None

    def drop_index_at(self, x: int) -> int:
        tiles, _ = self.tile_rects()
        for i, (_, r) in enumerate(tiles):
            if x < r.center().x():
                return i
        return len(tiles)

    # ------------------------------------------------------------ paint
    def paintEvent(self, ev):
        fg = self.palette().windowText().color()
        dim = QColor(fg)
        dim.setAlpha(160)
        line = QColor(fg)          # рамки и заливки — от цвета текста темы (видны и в светлой, и в тёмной)
        line.setAlpha(60)
        tab_bg, tab_hover = QColor(fg), QColor(fg)
        tab_bg.setAlpha(18)
        tab_hover.setAlpha(36)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tiles, plus = self.tile_rects()
        # линия под вкладками (прерывается под активной)
        y = PAD + TAB_H - 0.5
        p.setPen(QPen(line, 1))
        p.drawLine(QPointF(0, y), QPointF(self.width(), y))
        for proj, r in tiles:
            active = proj is self.ed.project
            hover = proj is self._hover
            tr = QRectF(self.tab_rect(r)).adjusted(0.5, 0.5, -0.5, 0)
            path = _tab_path(tr)
            p.setPen(Qt.NoPen)
            p.fillPath(path, CANVAS_BG if active else (tab_hover if hover else tab_bg))
            if active:
                p.setPen(QPen(ACCENT, 2))
                p.drawLine(QPointF(tr.left() + 5, tr.top() + 1), QPointF(tr.right() - 5, tr.top() + 1))
            else:
                p.setPen(QPen(line, 1))
                p.drawPath(path)
            # имя
            nr = self.name_rect(r)
            name = proj.display_name() + (" *" if proj.is_modified() else "")
            f = QFont(self.font())
            f.setBold(active)
            p.setFont(f)
            p.setPen(QColor(235, 238, 242) if active else dim)
            p.drawText(nr, Qt.AlignVCenter | Qt.AlignLeft, QFontMetrics(f).elidedText(name, Qt.ElideMiddle, nr.width()))
            # «×» — на активной и под мышью
            if active or hover:
                cr = QRectF(self.close_rect(r))
                if self._hover_close is proj:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(255, 255, 255, 50) if active else tab_hover)
                    p.drawEllipse(cr)
                    p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(235, 238, 242) if active else dim, 1.4))
                k = 4
                c = cr.center()
                p.drawLine(QPointF(c.x() - k, c.y() - k), QPointF(c.x() + k, c.y() + k))
                p.drawLine(QPointF(c.x() - k, c.y() + k), QPointF(c.x() + k, c.y() - k))
            # миниатюра
            if self.expanded():
                th = self.thumb_rect(r)
                p.fillRect(th, QColor(0, 0, 0, 50))
                img = self.strip.thumb(proj)
                if img is not None:
                    k = min(th.width() / img.width(), th.height() / img.height())
                    w, h = img.width() * k, img.height() * k
                    p.drawImage(QRectF(th.center().x() - w / 2, th.center().y() - h / 2, w, h), img)
                else:
                    p.setPen(dim)
                    p.drawText(th, Qt.AlignCenter, "пусто")
                p.setPen(QPen(ACCENT if active else (QColor(120, 200, 255, 200) if hover else line),
                              2 if active else 1))
                p.drawRect(QRectF(th).adjusted(0.5, 0.5, -0.5, -0.5))
        # «+» — открыть
        hp = self._hover == "plus"
        p.setPen(Qt.NoPen)
        p.setBrush(tab_hover if hp else Qt.NoBrush)
        p.drawRoundedRect(QRectF(plus), 4, 4)
        c = QPointF(plus.center())
        p.setPen(QPen(fg if hp else dim, 1.8))
        p.drawLine(QPointF(c.x() - 6, c.y()), QPointF(c.x() + 6, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - 6), QPointF(c.x(), c.y() + 6))
        # куда встанет перетаскиваемая вкладка
        if self._drop_index is not None:
            if self._drop_index < len(tiles):
                x = tiles[self._drop_index][1].left() - TAB_GAP / 2
            else:
                x = (tiles[-1][1].right() + TAB_GAP / 2) if tiles else PAD
            p.setPen(QPen(ACCENT, 3))
            p.drawLine(QPointF(x, 3), QPointF(x, self.height() - 3))
        p.end()

    # ------------------------------------------------------------ mouse
    def mousePressEvent(self, ev):
        if self._editor is not None:
            self._finish_rename(True)
        pos = ev.position().toPoint()
        proj, r = self.project_at(pos)
        if ev.button() == Qt.LeftButton:
            if proj == "plus":
                self.strip.cb.open_dialog()
                return
            if proj is not None and self.close_rect(r).contains(pos) and \
                    (proj is self.ed.project or proj is self._hover):
                self.strip.cb.close_project(proj)
                return
            if proj is not None:
                self._press = (proj, pos)
        elif ev.button() == Qt.MiddleButton and proj is not None and proj != "plus":
            self.strip.cb.close_project(proj)          # средняя кнопка — закрыть, как в браузере
        elif ev.button() == Qt.RightButton:
            self.strip.context_menu(proj if proj != "plus" else None, ev.globalPosition().toPoint())

    def mouseMoveEvent(self, ev):
        pos = ev.position().toPoint()
        if self._press is not None and ev.buttons() & Qt.LeftButton:
            if self._drag is None and (pos - self._press[1]).manhattanLength() > DRAG_PX:
                self._drag = self._press[0]
                self.setCursor(Qt.ClosedHandCursor)
            if self._drag is not None:
                self._drop_index = self.drop_index_at(pos.x())
                self.strip.scroll.ensureVisible(pos.x(), pos.y(), 40, 0)
                self.update()
                return
        proj, r = self.project_at(pos)
        over_close = proj if (proj not in (None, "plus") and self.close_rect(r).contains(pos)) else None
        if proj is not self._hover or over_close is not self._hover_close:
            self._hover, self._hover_close = proj, over_close
            self.update()
        if over_close is not None:
            self.setToolTip("Закрыть проект (или средняя кнопка мыши)")
        elif proj is not None and proj != "plus":
            self.setToolTip(self._tooltip(proj))
        elif proj == "plus":
            self.setToolTip("Открыть фото или проекты (можно несколько)")
        else:
            self.setToolTip("")

    def _tooltip(self, proj):
        d = proj.doc
        path = d.project_path or d.image_path or "не сохранён"
        return f"{proj.display_name()}\n{path}"

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        if self._drag is not None:
            proj, idx = self._drag, self._drop_index
            old = self.ed.projects.index(proj)
            if idx is not None:
                if idx > old:
                    idx -= 1
                if idx != old:
                    self.ed.move_project(proj, idx)
        elif self._press is not None:
            self.strip.cb.switch_to(self._press[0])
        self._press = self._drag = self._drop_index = None
        self.unsetCursor()
        self.update()

    def mouseDoubleClickEvent(self, ev):
        pos = ev.position().toPoint()
        proj, r = self.project_at(pos)
        if proj is None or proj == "plus":
            return
        if self.name_rect(r).contains(pos):
            self.start_rename(proj)

    def leaveEvent(self, ev):
        if self._hover is not None or self._hover_close is not None:
            self._hover = self._hover_close = None
            self.update()

    def wheelEvent(self, ev):
        d = ev.angleDelta().y() or ev.angleDelta().x()
        if d:
            self.strip.cb.step_project(1 if d > 0 else -1)   # колесо от себя — следующий (правее)
        ev.accept()

    # ------------------------------------------------------------ rename
    def start_rename(self, proj):
        self.strip.hold(True)
        tiles, _ = self.tile_rects()
        r = next((rr for p, rr in tiles if p is proj), None)
        if r is None:
            self.strip.hold(False)
            return
        self.strip.scroll.ensureVisible(r.center().x(), TAB_H // 2, TAB_W // 2 + TAB_GAP, 0)
        ed = QLineEdit(proj.display_name(), self)
        ed.setGeometry(self.name_rect(r).adjusted(-4, 3, 0, -3))
        ed.selectAll()
        ed.returnPressed.connect(lambda: self._finish_rename(True))
        ed.installEventFilter(self)
        ed.show()
        ed.setFocus()
        self._editor = (ed, proj)

    def eventFilter(self, obj, ev):
        if self._editor is not None and obj is self._editor[0]:
            if ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key_Escape:
                self._finish_rename(False)
                return True
            if ev.type() == ev.Type.FocusOut:
                QTimer.singleShot(0, lambda: self._finish_rename(True))
        return super().eventFilter(obj, ev)

    def _finish_rename(self, accept: bool):
        if self._editor is None:
            return
        ed, proj = self._editor
        self._editor = None
        text = ed.text()
        ed.hide()
        ed.deleteLater()
        self.strip.hold(False)
        if accept:
            self.strip.cb.rename(proj, text)
        self.update()

    # ------------------------------------------------------------ drop files
    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.toLocalFile()]
        if paths:
            self.strip.cb.open_paths(paths)
            ev.acceptProposedAction()


class ProjectStrip(QFrame):
    """Лента проектов. cb — объект окна с действиями (open_dialog, open_paths, switch_to, step_project,
    rename, quick_png, quick_png_all, duplicate, close_project, close_others, close_right, save_project,
    save_project_as, reveal)."""
    heightChanged = Signal()
    pinnedChanged = Signal(bool)

    def __init__(self, editor, cb, parent=None):
        super().__init__(parent)
        self.setObjectName("ProjectStrip")
        self.ed = editor
        self.cb = cb
        self.pinned = False
        self._hover = False
        self._hold = 0
        self._thumbs: dict[int, QImage] = {}
        self.setAutoFillBackground(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.content = _Content(self)
        self.scroll = QScrollArea()
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidget(self.content)
        self.scroll.setWidgetResizable(False)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.scroll, 1)
        self.scroll.viewport().installEventFilter(self)   # колесо и на пустом месте ленты листает проекты
        self.pin = QToolButton()
        self.pin.setCheckable(True)
        self.pin.setAutoRaise(True)
        self.pin.setIcon(icon("pin"))
        self.pin.setIconSize(QSize(16, 16))
        self.pin.setFixedSize(TAB_H, TAB_H)
        self.pin.setToolTip("Закрепить ленту проектов (всегда показывать миниатюры)")
        self.pin.toggled.connect(self.set_pinned)
        lay.addWidget(self.pin, 0, Qt.AlignTop)
        self._collapse_timer = QTimer(self)
        self._collapse_timer.setSingleShot(True)
        self._collapse_timer.setInterval(350)
        self._collapse_timer.timeout.connect(self._collapse_now)
        self._thumb_timer = QTimer(self)
        self._thumb_timer.setSingleShot(True)
        self._thumb_timer.setInterval(400)
        self._thumb_timer.timeout.connect(self.content.update)
        editor.projectsChanged.connect(self._projects_changed)
        editor.projectSwitched.connect(self._switched)
        for sig in (editor.docItemsModified, editor.docItemsChanged, editor.docBackgroundChanged):
            sig.connect(self._thumb_timer.start)
        self.relayout()

    def eventFilter(self, obj, ev):
        if obj is self.scroll.viewport() and ev.type() == ev.Type.Wheel:
            self.content.wheelEvent(ev)
            return True
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------ state
    def is_expanded(self) -> bool:
        return self.pinned or self._hover or self._hold > 0

    def set_pinned(self, on: bool):
        on = bool(on)
        if self.pin.isChecked() != on:
            self.pin.setChecked(on)
            return
        self.pinned = on
        self.pin.setToolTip("Открепить ленту (миниатюры — только при наведении)" if on else
                            "Закрепить ленту проектов (всегда показывать миниатюры)")
        self.relayout()
        self.pinnedChanged.emit(on)

    def hold(self, on: bool):
        """Держать как есть (переименование, меню) — не сворачивать."""
        self._hold = max(0, self._hold + (1 if on else -1))
        if self._hold == 0 and not self.underMouse():
            self._hover = False
        self.relayout()

    def _scrollbar_h(self) -> int:
        """Полоса прокрутки — только если вкладки не помещаются."""
        if self.content.width() <= max(1, self.width() - self.pin.width()):
            return 0
        return self.scroll.horizontalScrollBar().sizeHint().height() + 1

    def collapsed_height(self) -> int:
        return PAD + TAB_H + self._scrollbar_h()

    def expanded_height(self) -> int:
        return PAD + TAB_H + THUMB_H + PAD * 2 + self._scrollbar_h()

    def current_height(self) -> int:
        return self.expanded_height() if self.is_expanded() else self.collapsed_height()

    def reserved_height(self) -> int:
        """Сколько места лента занимает над холстом (миниатюры без закрепления — поверх холста)."""
        return self.expanded_height() if self.pinned else self.collapsed_height()

    def relayout(self):
        self.content.relayout()
        self.heightChanged.emit()
        QTimer.singleShot(0, self.ensure_current_visible)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if ev.oldSize().width() != ev.size().width():
            QTimer.singleShot(0, self.heightChanged.emit)   # полоса прокрутки могла появиться/исчезнуть

    # ------------------------------------------------------------ hover expand
    def enterEvent(self, ev):
        self._collapse_timer.stop()
        if not self._hover:
            self._hover = True
            if not self.pinned:
                self.relayout()
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        if not self.pinned:
            self._collapse_timer.start()
        super().leaveEvent(ev)

    def _collapse_now(self):
        if self.underMouse() or self._hold > 0:
            return
        if self._hover:
            self._hover = False
            if not self.pinned:
                self.relayout()

    # ------------------------------------------------------------ projects
    def _projects_changed(self):
        alive = {id(p) for p in self.ed.projects}
        self._thumbs = {k: v for k, v in self._thumbs.items() if k in alive}
        self.content.relayout()
        self.heightChanged.emit()
        QTimer.singleShot(0, self.ensure_current_visible)

    def _switched(self):
        self.content.update()
        QTimer.singleShot(0, self.ensure_current_visible)

    def ensure_current_visible(self):
        tiles, _ = self.content.tile_rects()
        for p, r in tiles:
            if p is self.ed.project:
                self.scroll.ensureVisible(r.center().x(), TAB_H // 2, r.width() // 2 + TAB_GAP, 0)
                break

    def thumb(self, proj) -> QImage | None:
        img = self._thumbs.get(id(proj))
        if img is None or proj.thumb_dirty:
            img = render_thumb(proj.doc, TAB_W * THUMB_SCALE, THUMB_H * THUMB_SCALE)
            proj.thumb_dirty = False
            if img is not None:
                self._thumbs[id(proj)] = img
            else:
                self._thumbs.pop(id(proj), None)
        return img

    # ------------------------------------------------------------ menu
    def context_menu(self, proj, gpos):
        cb = self.cb
        m = QMenu(self)
        if proj is not None:
            m.addAction(icon("export"), "Быстрый PNG", lambda: cb.quick_png(proj))
            m.addAction(icon("layer_dup"), "Дублировать", lambda: cb.duplicate(proj))
            m.addAction("Переименовать", lambda: self.content.start_rename(proj))
            m.addAction("Закрыть", lambda: cb.close_project(proj))
            m.addSeparator()
            m.addAction(icon("save"), "Сохранить проект", lambda: cb.save_project(proj))
            m.addAction("Сохранить проект как…", lambda: cb.save_project_as(proj))
            m.addSeparator()
        m.addAction("Быстрый PNG всех", cb.quick_png_all)
        if proj is not None:
            many = len(self.ed.projects) > 1
            a = m.addAction("Закрыть остальные", lambda: cb.close_others(proj))
            a.setEnabled(many)
            i = self.ed.projects.index(proj)
            a = m.addAction("Закрыть справа", lambda: cb.close_right(proj))
            a.setEnabled(i < len(self.ed.projects) - 1)
            m.addSeparator()
            a = m.addAction("Показать в папке", lambda: cb.reveal(proj))
            a.setEnabled(bool(proj.doc.project_path or proj.doc.image_path))
        else:
            m.addSeparator()
            m.addAction(icon("open"), "Открыть…", cb.open_dialog)
        self.hold(True)
        m.exec(gpos)
        self.hold(False)
