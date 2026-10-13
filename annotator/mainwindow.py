"""Главное окно: только сборка интерфейса и связывание действий с Editor."""
from __future__ import annotations

import copy
import json
import os

from PySide6.QtCore import QPointF, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QGuiApplication, QImage, QKeySequence
from PySide6.QtWidgets import (QDialog, QDockWidget, QFileDialog, QInputDialog, QLabel, QMainWindow, QMenu,
                               QMessageBox, QSplitter, QToolBar, QToolButton, QWidget)

from . import export, styles
from .canvas import CanvasView
from .document import PROJECT_EXT
from .editor import IMAGE_EXTS, Editor
from .tools.draw_tools import make_tools
from .ui import widgets
from .ui.dialogs import NewDialog, ask_text
from .ui.icons import app_icon, icon
from .ui.layers_panel import LayersPanel
from .ui.properties import PropertiesPanel

APP_NAME = "ImageAnnotator"
VERSION = "1.0"
IMG_FILTER = "Изображения (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)"
PRJ_FILTER = f"Проект ImageAnnotator (*{PROJECT_EXT})"

HOTKEYS = [
    ("Инструменты", ""),
    ("V", "Выбор"), ("M", "Выделение области фото"), ("K", "Обрезка / размер холста (и вставленного изображения)"), ("A", "Стрелка"), ("L", "Линия"), ("T", "Текст"),
    ("C", "Выноска"), ("N", "Нумерация"), ("R", "Прямоугольник"), ("E", "Эллипс"), ("P", "Полилиния"),
    ("G", "Полигон"), ("F", "Карандаш"), ("D", "Размер (расстояние)"), ("B", "Разрыв цепи"),
    ("Z", "Выносной вид (лупа): выделите область — рядом появится увеличение"),
    ("Навигация", ""),
    ("Колесо мыши", "Масштаб относительно курсора"), ("ПКМ + движение", "Панорама"),
    ("СКМ + движение вверх/вниз", "Масштаб"), ("Ctrl+0 / двойной клик СКМ", "Вписать"), ("Ctrl+1", "100%"),
    ("Редактирование", ""),
    ("Shift (рисование)", "Угол 0/45/90°, квадрат/круг"),
    ("Shift + тянуть ручку", "Переместить объект(ы) за эту точку"),
    ("Shift (перемещение)", "Только по горизонтали/вертикали"),
    ("Стрелки / Shift+стрелки", "Сдвиг на 1 / 10 px"),
    ("Рамка слева→направо", "Выбрать объекты целиком внутри"),
    ("Рамка справа→налево", "Выбрать всё, что пересекает рамку"),
    ("Enter / двойной клик", "Завершить полилинию / полигон"), ("Esc", "Отмена / инструмент выбора"),
    ("Короткий клик ПКМ", "Контекстное меню; при рисовании — завершить и перейти к «Выбору»"),
    ("Alt + тянуть ручку", "Масштаб относительно центра"),
    ("Ручка ● над прямоугольником", "Поворот (Shift — шаг 15°)"),
    ("Ручка «+» на сегменте", "Добавить вершину полилинии/полигона"),
    ("Средняя ручка линии/стрелки", "Изогнуть дугой (двойной клик — выпрямить)"),
    ("Карандаш: отпустить у начала", "Замкнуть контур"),
    ("Размер: маркер надписи", "Вдоль — положение текста, поперёк — отступ"),
    ("Двойной клик / ПКМ по вершине", "Удалить вершину (или Alt+клик)"), ("Ctrl+M", "Коррекция цвета"),
    ("Ctrl+Alt+G", "Менеджер групп"), ("Shift+S", "Привязка вкл/выкл"),
    ("Ctrl+D", "Дублировать"), ("Ctrl+G / Ctrl+Shift+G", "Группировать / разгруппировать"),
    ("Ctrl+L", "Заблокировать объект"), ("Ctrl+] / Ctrl+[", "Выше / ниже (Shift — наверх/вниз)"),
    ("Ctrl+Shift+C", "Копировать результат как картинку"),
    ("Ctrl+E", "Экспорт PNG/JPG/PDF"),
]


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(app_icon())
        self.settings = QSettings(APP_NAME, APP_NAME)
        self.ed = Editor()
        self.ed.ask_text = lambda initial="", title="Текст": ask_text(self, initial, title)
        self.view = CanvasView(self.ed)
        self.setCentralWidget(self.view)
        for t in make_tools(self.ed):
            self.ed.register_tool(t)
        self.acts: dict[str, QAction] = {}
        self._build_actions()
        self._build_menus()
        self._build_toolbars()
        self._build_docks()
        self._build_statusbar()
        self._connect()
        self._load_settings()
        self.ed.set_tool("select")
        self._update_title()
        self._update_actions()

    # ================================================================ actions
    def _act(self, key, text, slot=None, shortcut=None, ic=None, checkable=False, tip=None):
        a = QAction(text, self)
        if shortcut:
            if isinstance(shortcut, (list, tuple)):
                a.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                a.setShortcut(QKeySequence(shortcut))
        if ic:
            a.setIcon(icon(ic))
        if checkable:
            a.setCheckable(True)
        if slot:
            a.triggered.connect(slot)
        sc = a.shortcut().toString(QKeySequence.NativeText)
        a.setToolTip(f"{tip or text.replace('&', '').replace('…', '')}" + (f"  ({sc})" if sc else ""))
        a.setShortcutContext(Qt.WindowShortcut)
        self.addAction(a)
        self.acts[key] = a
        return a

    def _build_actions(self):
        ed = self.ed
        A = self._act
        A("new", "Новый холст…", self.new_blank, "Ctrl+N")
        A("open", "Открыть…", self.open_dialog, "Ctrl+O", "open", tip="Открыть фото или проект")
        A("save", "Сохранить проект", self.save, "Ctrl+S", "save")
        A("saveas", "Сохранить проект как…", self.save_as, "Ctrl+Shift+S")
        A("export", "Экспорт PNG / JPG / PDF…", self.export_dialog, "Ctrl+E", "export")
        A("export_quick", "Быстрый экспорт PNG рядом с фото", self.export_quick, "Ctrl+Shift+E")
        A("copy_result", "Копировать результат как картинку", self.copy_result, "Ctrl+Shift+C", "copy",
          tip="Копировать всё изображение с пометками в буфер (PNG) — вставить в письмо/мессенджер")
        A("print", "Печать…", lambda: export.print_doc(ed.doc, self), "Ctrl+P")
        A("quit", "Выход", self.close, "Ctrl+Q")

        self.acts["undo"] = a = ed.undo.createUndoAction(self, "Отменить")
        a.setShortcuts([QKeySequence("Ctrl+Z")])
        a.setIcon(icon("undo"))
        self.addAction(a)
        self.acts["redo"] = a = ed.undo.createRedoAction(self, "Повторить")
        a.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        a.setIcon(icon("redo"))
        self.addAction(a)
        A("cut", "Вырезать", ed.cut, "Ctrl+X")
        A("copy", "Копировать", ed.copy, "Ctrl+C")
        A("paste", "Вставить", self.paste, "Ctrl+V")
        A("duplicate", "Дублировать", ed.duplicate, "Ctrl+D")
        A("delete", "Удалить", self.delete, "Delete")
        A("select_all", "Выделить всё", ed.sel.select_all, "Ctrl+A")
        A("deselect", "Снять выделение", ed.sel.clear, "Ctrl+Shift+A")
        A("insert_image", "Вставить изображение из файла…", self.insert_image_dialog, "Ctrl+Shift+I", "image",
          tip="Вставить изображение (например, фото правильного компонента)")

        A("fit", "Вписать в окно", self.view.fit, ["Ctrl+0", "Home"], "fit")
        A("actual", "Масштаб 100%", self.view.actual_size, "Ctrl+1", "actual")
        A("zoom_in", "Увеличить", lambda: self.view.zoom_at(1.25, self.view.viewport().rect().center()),
          ["Ctrl+=", "Ctrl++"])
        A("zoom_out", "Уменьшить", lambda: self.view.zoom_at(0.8, self.view.viewport().rect().center()), "Ctrl+-")
        A("snap", "Привязка", self.toggle_snap, "Shift+S", "snap", checkable=True)

        A("front", "На передний план", lambda: ed.reorder("front"), "Ctrl+Shift+]")
        A("forward", "Выше", lambda: ed.reorder("forward"), "Ctrl+]")
        A("backward", "Ниже", lambda: ed.reorder("backward"), "Ctrl+[")
        A("back", "На задний план", lambda: ed.reorder("back"), "Ctrl+Shift+[")
        A("group", "Сгруппировать", ed.group, "Ctrl+G")
        A("ungroup", "Разгруппировать", ed.ungroup, "Ctrl+Shift+G")
        A("lock", "Заблокировать / разблокировать", ed.toggle_lock, "Ctrl+L")
        for k, t in (("left", "По левому краю"), ("hcenter", "По центру (гориз.)"), ("right", "По правому краю"),
                     ("top", "По верхнему краю"), ("vcenter", "По центру (верт.)"), ("bottom", "По нижнему краю")):
            A(f"align_{k}", t, (lambda m: (lambda: ed.align(m)))(k))

        A("layer_new", "Новый слой", lambda: ed.add_layer(), "Ctrl+Shift+N", "layer_add")
        A("raster_obj", "Область → объект (копия поверх фото)", ed.raster_to_object)
        A("raster_fill", "Залить область цветом…", self.raster_fill)
        A("raster_opacity", "Прозрачность области…", self.raster_opacity)
        A("raster_crop", "Обрезать по выделенной области", ed.crop_to_selection)
        A("raster_blur", "Размытие по Гауссу…", self.raster_blur)
        A("color", "Коррекция цвета…", lambda: self.color_correction(), "Ctrl+M", "adjust",
          tip="Коррекция цвета фото (или выбранного изображения)")
        A("color_reset", "Сбросить коррекцию цвета фото", ed.reset_background_color)
        A("image_uncrop", "Вернуть обрезанное изображение", self.image_uncrop)
        A("groups", "Менеджер групп…", self.group_manager, "Ctrl+Alt+G", "group")
        A("hotkeys", "Горячие клавиши", self.show_hotkeys, "F1")
        A("escape", "Отмена операции", self.view.escape, "Esc")
        A("about", "О программе", self.about)

        # инструменты
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        icons = {"select": "select", "raster": "raster", "crop": "crop", "dimension": "dimension", "break": "break", "magnifier": "magnifier", "arrow": "arrow", "line": "line", "text": "text",
                 "callout": "callout", "number": "number", "rect": "rect", "ellipse": "ellipse",
                 "polyline": "polyline", "polygon": "polygon", "freehand": "freehand"}
        for name, tool in ed.tools.items():
            a = A(f"tool_{name}", tool.title, (lambda n: (lambda: ed.set_tool(n)))(name), tool.shortcut,
                  icons.get(name), checkable=True)
            self.tool_group.addAction(a)

    def _build_menus(self):
        mb = self.menuBar()
        a = self.acts
        m = mb.addMenu("&Файл")
        for k in ("new", "open"):
            m.addAction(a[k])
        self.recent_menu = m.addMenu("Последние файлы")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        for k in ("save", "saveas"):
            m.addAction(a[k])
        m.addSeparator()
        for k in ("export", "export_quick", "copy_result", "print"):
            m.addAction(a[k])
        m.addSeparator()
        m.addAction(a["quit"])

        m = mb.addMenu("&Правка")
        for k in ("undo", "redo", None, "cut", "copy", "paste", "duplicate", "delete", None, "select_all",
                  "deselect", None, "insert_image"):
            m.addSeparator() if k is None else m.addAction(a[k])

        m = mb.addMenu("&Вид")
        for k in ("fit", "actual", "zoom_in", "zoom_out", None, "snap"):
            m.addSeparator() if k is None else m.addAction(a[k])
        self.view_menu = m

        m = mb.addMenu("&Объект")
        for k in ("front", "forward", "backward", "back", None, "group", "ungroup", "lock"):
            m.addSeparator() if k is None else m.addAction(a[k])
        al = m.addMenu("Выровнять")
        for k in ("left", "hcenter", "right", "top", "vcenter", "bottom"):
            al.addAction(a[f"align_{k}"])
        self.move_layer_menu = m.addMenu("Перенести в слой")
        self.move_layer_menu.aboutToShow.connect(lambda: self._fill_layer_menu(self.move_layer_menu))

        m = mb.addMenu("&Инструменты")
        for name in self.ed.tools:
            m.addAction(a[f"tool_{name}"])
        m.addSeparator()
        m.addAction(a["groups"])

        m = mb.addMenu("Изо&бражение")
        m.addAction(a["tool_crop"])
        m.addAction(a["color"])
        m.addAction(a["color_reset"])
        m.addSeparator()
        for k in ("raster_obj", "raster_fill", "raster_opacity", "raster_blur", "raster_crop", None, "image_uncrop"):
            m.addSeparator() if k is None else m.addAction(a[k])

        m = mb.addMenu("С&правка")
        m.addAction(a["hotkeys"])
        m.addAction(a["about"])

    def _build_toolbars(self):
        tb = QToolBar("Инструменты")
        tb.setObjectName("Tools")
        tb.setMovable(False)
        tb.setIconSize(QSize(22, 22))
        tb.setOrientation(Qt.Vertical)
        self.addToolBar(Qt.LeftToolBarArea, tb)
        order = ["select", "raster", "crop", None, "arrow", "line", "text", "callout", "number", None,
                 "rect", "ellipse", "polyline", "polygon", "freehand", None, "dimension", "break", "magnifier"]
        for n in order:
            if n is None:
                tb.addSeparator()
            else:
                tb.addAction(self.acts[f"tool_{n}"])
        tb.addSeparator()
        tb.addAction(self.acts["insert_image"])

        top = QToolBar("Файл")
        top.setObjectName("Top")
        top.setMovable(False)
        top.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.TopToolBarArea, top)
        for k in ("open", "save", "export", "copy_result", None, "undo", "redo", None, "fit", "actual", None):
            top.addSeparator() if k is None else top.addAction(self.acts[k])
        from .ui.snap_popup import SnapButton
        self.snap_popup_btn = SnapButton(self.ed)
        top.addWidget(self.snap_popup_btn)
        from .ui.snap_popup import FilterButton
        self.filter_btn = FilterButton(self.ed)
        top.addWidget(self.filter_btn)

    def _build_docks(self):
        dock = QDockWidget("Свойства и слои", self)
        dock.setObjectName("RightDock")
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        split = QSplitter(Qt.Vertical)
        self.props = PropertiesPanel(self.ed, self.acts)
        self.layers = LayersPanel(self.ed)
        lw = QWidget()
        from PySide6.QtWidgets import QVBoxLayout
        ll = QVBoxLayout(lw)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(0)
        t = QLabel("Слои")
        t.setObjectName("PanelTitle")
        ll.addWidget(t)
        ll.addWidget(self.layers, 1)
        split.addWidget(self.props)
        split.addWidget(lw)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 2)
        split.setChildrenCollapsible(False)
        self.split = split
        dock.setWidget(split)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)
        self.view_menu.addSeparator()
        self.view_menu.addAction(dock.toggleViewAction())
        self.resizeDocks([dock], [330], Qt.Horizontal)

    def _build_statusbar(self):
        sb = self.statusBar()
        self.hint_lbl = QLabel()
        self.hint_lbl.setMinimumWidth(100)
        sb.addWidget(self.hint_lbl, 1)
        self.pos_lbl = QLabel("—")
        self.size_lbl = QLabel("—")
        self.zoom_lbl = QLabel("100%")
        for w in (self.pos_lbl, self.size_lbl, self.zoom_lbl):
            sb.addPermanentWidget(w)

    def _connect(self):
        ed = self.ed
        ed.toolChanged.connect(self._on_tool)
        ed.message.connect(lambda m: self.statusBar().showMessage(m, 3000))
        ed.undo.cleanChanged.connect(lambda *_: self._update_title())
        ed.undo.indexChanged.connect(lambda *_: self._update_title())
        ed.sel.changed.connect(self._update_actions)
        ed.rasterSelectionChanged.connect(self._update_actions)
        ed.doc.backgroundChanged.connect(self._update_size)
        ed.snapChanged.connect(lambda: self.acts["snap"].setChecked(ed.snap.enabled))
        self.view.cursorMoved.connect(lambda p: self.pos_lbl.setText(f"X {p.x():.0f}  Y {p.y():.0f}"))
        self.view.zoomChanged.connect(lambda z: self.zoom_lbl.setText(f"{z * 100:.0f}%"))
        self.view.contextMenuRequested.connect(self.context_menu)
        self.view.filesDropped.connect(self.files_dropped)
        self.acts["snap"].setChecked(ed.snap.enabled)

    # ================================================================ state / ui updates
    def _on_tool(self, name):
        a = self.acts.get(f"tool_{name}")
        if a and not a.isChecked():
            a.setChecked(True)
        tool = self.ed.tool
        self.hint_lbl.setText(f"{tool.title}:  {tool.hint()}" if tool.hint() else tool.title)
        self._update_actions()

    def _update_actions(self):
        sel = bool(self.ed.sel.items)
        many = len(self.ed.sel.items) > 1
        raster = self.ed.raster_sel is not None
        for k in ("duplicate", "front", "forward", "backward", "back", "lock"):
            self.acts[k].setEnabled(sel)
        for k in ("cut", "copy", "delete"):
            self.acts[k].setEnabled(sel or raster)
        self.acts["group"].setEnabled(many)
        self.acts["ungroup"].setEnabled(any(i.group_id for i in self.ed.sel.items))
        for k in ("left", "hcenter", "right", "top", "vcenter", "bottom"):
            self.acts[f"align_{k}"].setEnabled(many)
        for k in ("raster_obj", "raster_fill", "raster_opacity", "raster_crop"):
            self.acts[k].setEnabled(raster)
        if self.ed.tool is not None and self.ed.tool.name == "number":
            self.hint_lbl.setText(f"{self.ed.tool.title}:  {self.ed.tool.hint()}")

    def _update_size(self):
        bg = self.ed.doc.background
        self.size_lbl.setText(f"{bg.width()} × {bg.height()} px" if bg is not None else "—")
        self._update_title()

    def _update_title(self):
        doc = self.ed.doc
        name = os.path.basename(doc.project_path or doc.image_path or "") or "Без имени"
        try:
            dirty = "*" if not self.ed.undo.isClean() else ""
        except RuntimeError:  # при закрытии приложения
            return
        self.setWindowTitle(f"{name}{dirty} — {APP_NAME}")

    def toggle_snap(self):
        self.ed.snap.enabled = self.acts["snap"].isChecked()
        self.ed.snapChanged.emit()
        self.statusBar().showMessage("Привязка " + ("включена" if self.ed.snap.enabled else "выключена"), 2000)

    # ================================================================ files
    def maybe_save(self) -> bool:
        if self.ed.undo.isClean() or self.ed.doc.is_empty():
            return True
        r = QMessageBox.question(self, APP_NAME, "Сохранить изменения в проекте?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def _last_dir(self):
        return self.settings.value("last_dir", os.path.expanduser("~"))

    def open_dialog(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Открыть", self._last_dir(),
            f"Фото и проекты (*{PROJECT_EXT} *.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;{IMG_FILTER};;{PRJ_FILTER};;Все файлы (*)")
        if path:
            self.open_path(path)

    def open_path(self, path) -> bool:
        try:
            if path.lower().endswith(PROJECT_EXT):
                self.ed.open_project(path)
            else:
                if not self.ed.open_image(path):
                    QMessageBox.warning(self, APP_NAME, f"Не удалось открыть изображение:\n{path}")
                    return False
        except Exception as e:  # noqa
            QMessageBox.critical(self, APP_NAME, f"Ошибка открытия файла:\n{e}")
            return False
        self.settings.setValue("last_dir", os.path.dirname(path))
        self._add_recent(path)
        self._update_title()
        self._update_size()
        QTimer.singleShot(0, self.view.fit)
        return True

    def new_blank(self):
        if not self.maybe_save():
            return
        d = NewDialog(self)
        if d.exec() == QDialog.Accepted:
            self.ed.new_blank(d.w.value(), d.h.value(), QColor(d.color._color or "#ffffff"))
            self._update_title()

    def save(self) -> bool:
        if self.ed.doc.is_empty():
            return True
        if not self.ed.doc.project_path:
            return self.save_as()
        try:
            self.ed.save_project(self.ed.doc.project_path)
        except Exception as e:  # noqa
            QMessageBox.critical(self, APP_NAME, f"Не удалось сохранить проект:\n{e}")
            return False
        self.statusBar().showMessage("Проект сохранён", 2500)
        self._update_title()
        return True

    def _default_base(self):
        doc = self.ed.doc
        src = doc.project_path or doc.image_path
        if src:
            return os.path.splitext(src)[0]
        return os.path.join(self._last_dir(), "annotated")

    def save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить проект", self._default_base() + PROJECT_EXT, PRJ_FILTER)
        if not path:
            return False
        if not path.lower().endswith(PROJECT_EXT):
            path += PROJECT_EXT
        self.ed.doc.project_path = path
        ok = self.save()
        if ok:
            self._add_recent(path)
        return ok

    def export_dialog(self):
        if self.ed.doc.export_rect().isEmpty():
            return
        last_fmt = self.settings.value("export_fmt", "png")
        base = self._default_base()
        if base.endswith("_annotated"):
            base = base[: -len("_annotated")]
        path, flt = QFileDialog.getSaveFileName(
            self, "Экспорт", f"{base}_annotated.{last_fmt}",
            "PNG (*.png);;JPEG (*.jpg *.jpeg);;PDF (*.pdf)",
            {"png": "PNG (*.png)", "jpg": "JPEG (*.jpg *.jpeg)", "pdf": "PDF (*.pdf)"}.get(last_fmt, "PNG (*.png)"))
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += {"PNG": ".png", "JPEG": ".jpg", "PDF": ".pdf"}.get(flt.split()[0], ".png")
        self._do_export(path)

    def _do_export(self, path):
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        if export.export_file(self.ed.doc, path):
            self.settings.setValue("export_fmt", "jpg" if ext == "jpeg" else ext)
            self.statusBar().showMessage(f"Экспортировано: {path}", 5000)
        else:
            QMessageBox.warning(self, APP_NAME, f"Не удалось экспортировать:\n{path}")

    def export_quick(self):
        if self.ed.doc.export_rect().isEmpty():
            return
        base = self._default_base()
        if base.endswith("_annotated"):
            base = base[: -len("_annotated")]
        path = base + "_annotated.png"
        self._do_export(path)

    def copy_result(self):
        img = export.render_image(self.ed.doc)
        if img is not None:
            from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            buf.close()
            md = QMimeData()
            md.setImageData(img)          # обычный bitmap — понимают все программы
            md.setData("image/png", ba)   # PNG без потерь — для программ, которые его берут
            md.setData("PNG", ba)
            QGuiApplication.clipboard().setMimeData(md)
            self.statusBar().showMessage("Результат скопирован в буфер обмена — можно вставить в письмо/мессенджер", 4000)

    def insert_image_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Вставить изображение", self._last_dir(), IMG_FILTER)
        if path:
            img = QImage(path)
            if img.isNull():
                QMessageBox.warning(self, APP_NAME, "Не удалось открыть изображение")
                return
            if self.ed.doc.background is None:
                self.open_path(path)
            else:
                self.ed.insert_image(img)
                self.ed.set_tool("select")

    def files_dropped(self, paths, pos: QPointF):
        p = paths[0]
        low = p.lower()
        if low.endswith(PROJECT_EXT) or (self.ed.doc.background is None and low.endswith(IMAGE_EXTS)):
            if self.maybe_save():
                self.open_path(p)
            return
        for q in paths:
            if q.lower().endswith(IMAGE_EXTS):
                self.ed.insert_image(QImage(q), pos)
                pos = pos + QPointF(30, 30)
        self.ed.set_tool("select")

    def paste(self):
        vp = self.view.mapFromGlobal(self.cursor().pos())
        at = self.view.mapToScene(vp) if self.view.viewport().rect().contains(vp) else None
        self.ed.paste(at)
        self._update_title()
        self._update_size()

    def delete(self):
        if self.ed.raster_mode():
            self.ed.raster_delete()
        else:
            self.ed.delete_selected()

    # ================================================================ image menu
    def raster_blur(self):
        if self.ed._sel_rect() is None:
            return
        from .ui.dialogs import BlurDialog
        BlurDialog(self, self.ed).exec()

    def color_correction(self, item=None):
        from .ui.color_dialog import ColorDialog
        ed = self.ed
        if item is None and len(ed.sel.items) == 1 and ed.sel.items[0].TYPE == "image":
            item = ed.sel.items[0]
        if item is not None:
            if item.locked:
                self.statusBar().showMessage("Изображение заблокировано (Ctrl+L)", 3000)
                return
            before = item.color_params()

            def preview(p):
                item.props.update(p)
                item.update()
            dlg = ColorDialog(self, "Коррекция цвета — изображение", before, item.image, preview)
            if dlg.exec() == QDialog.Accepted:
                after = dlg.result_params()
                item.props.update(before)
                ed.set_item_color(item, before, after)
                ed.doc.itemsModified.emit()
                ed.sel.changed.emit()  # обновить подпись кнопки в свойствах
            return
        if ed.doc.background is None:
            return
        before = copy.deepcopy(ed.doc.color)
        dlg = ColorDialog(self, "Коррекция цвета — фото", before, ed.doc.background,
                          lambda p: ed.doc.set_color(p))
        if dlg.exec() == QDialog.Accepted:
            ed.set_background_color(before, dlg.result_params())

    def image_uncrop(self):
        items = [i for i in self.ed.sel.items if i.TYPE == "image" and i.is_cropped()]
        for it in items:
            self.ed.change_items([it], it.reset_crop, "Вернуть обрезку")
        self.ed.doc.itemsChanged.emit()
        self.ed.sel.changed.emit()

    def group_manager(self):
        from .ui.dialogs import GroupManagerDialog
        if not self.ed.groups():
            QMessageBox.information(self, APP_NAME, "В документе нет групп.\n"
                                    "Выделите несколько объектов и нажмите Ctrl+G, чтобы сгруппировать.")
            return
        GroupManagerDialog(self, self.ed).exec()

    def raster_fill(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(self.ed.doc.canvas_color), self, "Цвет заливки")
        if c.isValid():
            self.ed.raster_fill(c)

    def raster_opacity(self):
        v, ok = QInputDialog.getInt(self, "Прозрачность области", "Непрозрачность, %:", 50, 0, 100)
        if ok:
            self.ed.raster_opacity(v / 100.0)

    # ================================================================ menus
    def _fill_layer_menu(self, m: QMenu):
        m.clear()
        for l in reversed(self.ed.doc.annotation_layers()):
            a = m.addAction(l.name, (lambda lid: (lambda: self.ed.move_to_layer(self.ed.sel.items, lid)))(l.id))
            a.setEnabled(bool(self.ed.sel.items))
        m.addSeparator()
        m.addAction("Новый слой и перенести",
                    lambda: (self.ed.undo.beginMacro("Новый слой"),
                             self.ed.move_to_layer(self.ed.sel.items, self.ed.add_layer().id) if self.ed.sel.items else None,
                             self.ed.undo.endMacro()))

    def context_menu(self, gpos, spos):
        ed = self.ed
        h = self.view.hit_handle(spos)
        if h is not None:
            item, idx = h
            kinds = item.handle_kinds()
            kind = kinds[idx] if idx < len(kinds) else ""
            if kind == "vertex" and item.TYPE in ("polyline", "polygon"):
                m = QMenu(self)
                m.addAction("Удалить вершину", lambda: ed.delete_vertex(item, idx))
                m.exec(gpos)
                return
            if kind == "bend":
                m = QMenu(self)
                m.addAction("Выпрямить", lambda: ed.straighten(item))
                m.exec(gpos)
                return
        if ed.tool is not None and ed.tool.name == "raster" and ed.raster_sel is not None:
            m = QMenu(self)
            for k in ("copy", "cut", "delete", None, "raster_obj", "raster_fill", "raster_opacity", "raster_blur",
                      None, "raster_crop"):
                m.addSeparator() if k is None else m.addAction(self.acts[k])
            m.exec(gpos)
            return
        it = self.view.hit_item(spos)
        if it is not None and not ed.sel.contains(it):
            ed.sel.set([it])
        m = QMenu(self)
        if ed.sel.items:
            if len(ed.sel.items) == 1 and ("text" in ed.sel.items[0].props or ed.sel.items[0].TYPE == "number"):
                m.addAction("Редактировать текст…", lambda: ed.edit_item(ed.sel.items[0]))
                m.addSeparator()
            for k in ("cut", "copy", "paste", "duplicate", "delete"):
                m.addAction(self.acts[k])
            m.addSeparator()
            order = m.addMenu("Порядок")
            for k in ("front", "forward", "backward", "back"):
                order.addAction(self.acts[k])
            al = m.addMenu("Выровнять")
            for k in ("left", "hcenter", "right", "top", "vcenter", "bottom"):
                al.addAction(self.acts[f"align_{k}"])
            lm = m.addMenu("Перенести в слой")
            self._fill_layer_menu(lm)
            m.addAction(self.acts["group"])
            m.addAction(self.acts["ungroup"])
            m.addAction(self.acts["lock"])
            if len(ed.sel.items) == 1 and ed.sel.items[0].TYPE == "image":
                m.addSeparator()
                m.addAction("Коррекция цвета изображения…", lambda: self.color_correction(ed.sel.items[0]))
        else:
            if ed.doc.background is not None:
                m.addAction("Коррекция цвета фото…", lambda: self.color_correction(None))
                m.addSeparator()
            for k in ("paste", "select_all", None, "insert_image", None, "fit", "actual", None, "copy_result",
                      "export"):
                m.addSeparator() if k is None else m.addAction(self.acts[k])
        m.exec(gpos)

    def _fill_recent(self):
        self.recent_menu.clear()
        rec = self.settings.value("recent", [], type=list) or []
        for p in rec:
            self.recent_menu.addAction(p, (lambda q: (lambda: self.maybe_save() and self.open_path(q)))(p))
        if not rec:
            a = self.recent_menu.addAction("(пусто)")
            a.setEnabled(False)

    def _add_recent(self, path):
        rec = self.settings.value("recent", [], type=list) or []
        rec = [p for p in rec if p != path]
        rec.insert(0, path)
        self.settings.setValue("recent", rec[:10])

    def show_hotkeys(self):
        rows = []
        for k, v in HOTKEYS:
            if not v:
                rows.append(f"<tr><td colspan=2 style='padding-top:8px'><b>{k}</b></td></tr>")
            else:
                rows.append(f"<tr><td style='padding-right:16px;color:#9fc4ff'>{k}</td><td>{v}</td></tr>")
        box = QMessageBox(self)
        box.setWindowTitle("Горячие клавиши")
        box.setText("<table>" + "".join(rows) + "</table>")
        box.exec()

    def about(self):
        QMessageBox.about(self, APP_NAME,
                          f"<b>{APP_NAME} {VERSION}</b><br>Инженерный редактор пометок на фотографиях плат и изделий."
                          "<br><br>Аннотации хранятся отдельно от фото и остаются редактируемыми в проекте (*.iap).")

    # ================================================================ settings
    def _load_settings(self):
        s = self.settings
        geo = s.value("geometry")
        self.first_run = geo is None
        if geo is not None:
            self.restoreGeometry(geo)
        else:
            self.resize(1400, 880)
        st = s.value("state")
        if st is not None:
            self.restoreState(st)
        sp = s.value("split_v2")
        if sp is not None:
            self.split.restoreState(sp)
        else:
            # по умолчанию свойствам — ~72% высоты, слоям — остальное
            QTimer.singleShot(0, self._default_split)
        try:
            styles.load_styles(json.loads(s.value("styles", "{}")))
        except Exception:
            pass
        widgets.RECENT[:] = s.value("recent_colors", [], type=list) or []
        sn = self.ed.snap
        sn.enabled = s.value("snap_enabled", True, type=bool)
        sn.radius_px = int(s.value("snap_radius", 10))
        kinds = s.value("snap_kinds", None, type=list)
        if kinds:
            sn.kinds = set(kinds)
        self.ed.snapChanged.emit()

    def _default_split(self):
        h = max(400, self.split.height())
        self.split.setSizes([int(h * 0.72), int(h * 0.28)])

    def _save_settings(self):
        s = self.settings
        s.setValue("geometry", self.saveGeometry())
        s.setValue("state", self.saveState())
        s.setValue("split_v2", self.split.saveState())
        s.setValue("styles", json.dumps(styles.all_styles()))
        s.setValue("recent_colors", widgets.RECENT)
        s.setValue("snap_enabled", self.ed.snap.enabled)
        s.setValue("snap_radius", self.ed.snap.radius_px)
        s.setValue("snap_kinds", sorted(self.ed.snap.kinds))

    def closeEvent(self, ev):
        if not self.maybe_save():
            ev.ignore()
            return
        self._save_settings()
        ev.accept()

    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(0, self.view.fit)
