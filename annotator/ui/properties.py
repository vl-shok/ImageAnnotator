"""Контекстная панель свойств (справа).

A: ничего не выбрано — документ, стиль нового объекта, привязки, фильтр выделения, коррекция фото.
B: один объект — его свойства.
C: несколько объектов — только общие свойства; различающиеся значения показываются как «Разные».
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QSizePolicy, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSlider, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from .. import styles
from ..items import REGISTRY
from ..props import MIXED
from ..snap import SNAP_KINDS
from .histogram import HistogramWidget
from ..props import PropSpec
from .curves import CurvesEditor
from .widgets import ColorButton, Section, SliderEditor, ToggleGrid, make_editor, pair_row


def common_specs(items):
    first = items[0].prop_specs()
    out = []
    for spec in first:
        ok = True
        for it in items[1:]:
            if not any(s.name == spec.name and s.kind == spec.kind for s in it.prop_specs()):
                ok = False
                break
        if ok:
            out.append(spec)
    return out


def common_value(items, getter):
    vals = [getter(i) for i in items]
    v0 = vals[0]
    for v in vals[1:]:
        if v != v0:
            return MIXED
    return v0


class PropertiesPanel(QScrollArea):
    def __init__(self, editor, actions, parent=None):
        super().__init__(parent)
        self.ed = editor
        self.actions = actions  # dict имя -> QAction (для кнопок порядка/выравнивания)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumWidth(270)
        self._editors = []
        self._adjust = {}
        self._hist = None
        self._layer_combo = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(30)
        self._refresh_timer.timeout.connect(self.refresh_values)
        self._hist_timer = QTimer(self)
        self._hist_timer.setSingleShot(True)
        self._hist_timer.setInterval(250)
        self._hist_timer.timeout.connect(self._update_hist)
        editor.sel.changed.connect(self.rebuild)
        editor.toolChanged.connect(lambda *_: self.rebuild() if not editor.sel.items else None)
        editor.doc.itemsModified.connect(self._refresh_timer.start)
        editor.doc.itemsChanged.connect(self._refresh_timer.start)
        editor.doc.layersChanged.connect(self._refresh_layers)
        editor.doc.backgroundChanged.connect(self._on_bg)
        editor.doc.adjustChanged.connect(self._refresh_adjust)
        editor.snapChanged.connect(self._refresh_snap)
        editor.cropChanged.connect(self.update_crop_info)
        self.rebuild()

    # ------------------------------------------------------------------
    def rebuild(self):
        old = self.takeWidget()
        w = QWidget()
        w.setObjectName("PropsRoot")
        self.lay = QVBoxLayout(w)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(1)
        self._editors = []
        self._adjust = {}
        self._hist = None
        self._layer_combo = None
        self._snap_widgets = None
        self._doc_info = None
        self._adj_editor = None
        self._crop_info = None
        items = self.ed.sel.items
        if items:
            self._build_objects(items)
        else:
            self._build_document()
        self.lay.addStretch(1)
        self.setWidget(w)
        if old is not None:
            old.deleteLater()

    def _title(self, text, sub=None):
        lb = QLabel(text)
        lb.setObjectName("PanelTitle")
        self.lay.addWidget(lb)
        if sub:
            s = QLabel(sub)
            s.setObjectName("PanelSub")
            s.setWordWrap(True)
            self.lay.addWidget(s)

    # ------------------------------------------------------------------ objects
    def _build_objects(self, items):
        types = {i.TYPE for i in items}
        if len(items) == 1:
            self._title(items[0].TITLE, "Заблокирован — Ctrl+L, чтобы изменить" if items[0].locked else None)
        else:
            names = ", ".join(sorted(REGISTRY[t].TITLE for t in types))
            self._title(f"Выбрано: {len(items)}", names)
        specs = common_specs(items)
        sections = {}
        for spec in specs:
            sname = spec.section if len(types) == 1 else "Общие свойства"
            sec = sections.get(sname)
            if sec is None:
                sec = Section(sname)
                sections[sname] = sec
                self.lay.addWidget(sec)
            ed = make_editor(spec)
            if spec.kind == "curves":
                ed.image_provider = (lambda it: (lambda: it.image))(items[0])
            getter = (lambda name: (lambda it: it.props.get(name)))(spec.name)
            ed.set_value(common_value(items, getter))
            ed.valueChanged.connect((lambda name: (lambda v: self.ed.set_prop(name, v)))(spec.name))
            if hasattr(ed, "committed"):
                ed.committed.connect(self.ed.bump_session)
            self._editors.append((ed, getter))
            row = ed
            if spec.pair is not None and all(spec.pair.name in i.props for i in items):
                ped = make_editor(spec.pair)
                pget = (lambda name: (lambda it: it.props.get(name)))(spec.pair.name)
                ped.set_value(common_value(items, pget))
                ped.valueChanged.connect((lambda name: (lambda v: self.ed.set_prop(name, v)))(spec.pair.name))
                if hasattr(ped, "committed"):
                    ped.committed.connect(self.ed.bump_session)
                ped.setToolTip("Размер наконечника")
                self._editors.append((ped, pget))
                row = pair_row(ed, ped)
            sec.add_row(spec.label, row)
        if all(i.locked for i in items):
            for sec_w in sections.values():
                sec_w.body.setEnabled(False)
        bent = [i for i in items if getattr(i, "ctrl", None) is not None]
        if bent:
            sec = Section("Изгиб")
            self.lay.addWidget(sec)
            b = QToolButton()
            b.setText("Выпрямить")
            b.setToolTip("Убрать изгиб (или двойной клик по средней ручке)")
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda: [self.ed.straighten(i) for i in bent])
            sec.add_row("", b)
        if len(items) == 1 and items[0].TYPE == "image":
            it = items[0]
            sec = sections.get("Изображение") or Section("Изображение")
            sec.add_row("Обрезка", self._buttons([("Обрезать (K)", "tool_crop")] +
                                                ([("Вернуть всё", "image_uncrop")] if it.is_cropped() else [])))

        sec = Section("Объект")
        self.lay.addWidget(sec)
        combo = QComboBox()
        self._layer_combo = combo
        self._fill_layer_combo()
        combo.activated.connect(lambda i: self.ed.set_common("layer", combo.itemData(i)))
        sec.add_row("Слой", combo)
        lock = QCheckBox("Заблокирован")
        lockv = common_value(items, lambda i: i.locked)
        lock.setTristate(lockv is MIXED)
        lock.setCheckState(Qt.PartiallyChecked if lockv is MIXED else (Qt.Checked if lockv else Qt.Unchecked))
        lock.clicked.connect(lambda: self.ed.set_common("locked", lock.checkState() != Qt.Unchecked))
        sec.add_row("", lock)
        self._lock_cb = lock
        sec.add_row("Порядок", self._buttons([("Наверх", "front"), ("Выше", "forward"),
                                              ("Ниже", "backward"), ("Вниз", "back")]))
        if len(items) > 1:
            sec.add_row("Группа", self._buttons([("Сгруппировать", "group"), ("Разгруппировать", "ungroup")]))
            sec2 = Section("Выравнивание")
            self.lay.addWidget(sec2)
            sec2.add_row("", self._buttons([("⇤ Лево", "align_left"), ("↔ Центр", "align_hcenter"),
                                            ("Право ⇥", "align_right")]))
            sec2.add_row("", self._buttons([("⤒ Верх", "align_top"), ("↕ Центр", "align_vcenter"),
                                            ("Низ ⤓", "align_bottom")]))
        elif items[0].group_id:
            sec.add_row("Группа", self._buttons([("Разгруппировать", "ungroup"), ("Менеджер групп…", "groups")]))

    def _buttons(self, spec):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        for text, act in spec:
            b = QToolButton()
            b.setText(text)
            a = self.actions.get(act)
            if a is not None:
                b.setToolTip(f"{a.text().replace('&', '')}  {a.shortcut().toString()}".strip())
                b.clicked.connect(a.trigger)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            lay.addWidget(b, 1)
        return w

    def _fill_layer_combo(self):
        combo = self._layer_combo
        if combo is None:
            return
        combo.blockSignals(True)
        combo.clear()
        for l in reversed(self.ed.doc.annotation_layers()):
            combo.addItem(l.name, l.id)
        items = self.ed.sel.items
        if items:
            v = common_value(items, lambda i: i.layer_id)
            if v is MIXED:
                combo.insertItem(0, "Разные", None)
                combo.setCurrentIndex(0)
            else:
                combo.setCurrentIndex(max(0, combo.findData(v)))
        combo.blockSignals(False)

    def _refresh_layers(self):
        if self._layer_combo is not None:
            self._fill_layer_combo()

    def refresh_values(self):
        items = self.ed.sel.items
        if not items:
            return
        fw = QApplication.focusWidget()
        for ed, getter in self._editors:
            if fw is not None and (fw is ed or ed.isAncestorOf(fw)):
                continue
            ed.set_value(common_value(items, getter))
        self._fill_layer_combo()

    # ------------------------------------------------------------------ document
    def _build_document(self):
        doc = self.ed.doc
        tool = self.ed.tool
        cls = REGISTRY.get(tool.name) if tool is not None else None
        if tool is not None and tool.name == "crop":
            self._build_crop()
        elif cls is not None:
            self._title(f"Новый объект: {cls.TITLE}", "Эти настройки будут использованы для следующих объектов")
            sec = Section("Стиль")
            self.lay.addWidget(sec)
            defaults = styles.defaults_for(cls)
            for spec in cls.PROPS:
                if spec.name in styles.NON_STYLE:
                    continue
                ed = make_editor(spec)
                ed.set_value(defaults.get(spec.name))
                ed.valueChanged.connect((lambda t, n: (lambda v: styles.remember(t, n, v)))(cls.TYPE, spec.name))
                row = ed
                if spec.pair is not None:
                    ped = make_editor(spec.pair)
                    ped.set_value(defaults.get(spec.pair.name, 0))
                    ped.valueChanged.connect(
                        (lambda t, n: (lambda v: styles.remember(t, n, v)))(cls.TYPE, spec.pair.name))
                    row = pair_row(ed, ped)
                sec.add_row(spec.label, row)
        else:
            self._build_doc_info()

    def _build_doc_info(self):
        self._title("Документ")
        sec = Section("Документ")
        self.lay.addWidget(sec)
        self._doc_info = QLabel()
        self._doc_info.setWordWrap(True)
        self._doc_info.setObjectName("PanelSub")
        sec.add_row("", self._doc_info)
        self._update_doc_info()

    def _build_crop(self):
        tool = self.ed.tool
        target = "изображения" if getattr(tool, "target_item", None) is not None else "холста"
        self._title(f"Обрезка {target}",
                    "Тяните маркеры рамки. За пределы фото — холст увеличится. "
                    "Внутри рамки — переместить её, снаружи — нарисовать новую. "
                    "Применить / отменить — панель над холстом или Enter / Esc.")
        if getattr(tool, "target_item", None) is None:
            sec = Section("Обрезка")
            self.lay.addWidget(sec)
            col = ColorButton()
            col.set_value(self.ed.doc.canvas_color)
            col.valueChanged.connect(lambda c: setattr(self.ed.doc, "canvas_color", c))
            sec.add_row("Цвет нового места", col)
        self.update_crop_info()

    def update_crop_info(self):
        lbl = getattr(self, "_crop_info", None)
        tool = self.ed.tool
        try:
            if lbl is None or tool is None or tool.name != "crop" or tool.frame is None:
                return
            r = tool.frame
            lbl.setText(f"{r.width():.0f} × {r.height():.0f} px")
        except RuntimeError:
            self._crop_info = None

    def _update_doc_info(self):
        if self._doc_info is None:
            return
        doc = self.ed.doc
        if doc.background is None:
            self._doc_info.setText("Нет изображения")
            return
        name = os.path.basename(doc.project_path or doc.image_path or "") or "без имени"
        self._doc_info.setText(f"{name}\n{doc.background.width()} × {doc.background.height()} px, "
                               f"объектов: {len(doc.items())}")

    def _set_snap_enabled(self, on):
        self.ed.snap.enabled = on
        self.ed.snapChanged.emit()

    def _set_kind(self, k, on):
        if k == "image":
            self.ed.snap.to_image = on
        elif on:
            self.ed.snap.kinds.add(k)
        else:
            self.ed.snap.kinds.discard(k)

    def _refresh_snap(self):
        if self._snap_widgets is not None:
            master, grid = self._snap_widgets
            try:
                master.blockSignals(True)
                master.setChecked(self.ed.snap.enabled)
                master.blockSignals(False)
                grid.setEnabled(self.ed.snap.enabled)
            except RuntimeError:
                self._snap_widgets = None

    def _refresh_adjust(self):
        self._hist_timer.start()

    def _on_bg(self):
        self._update_doc_info()
        self._hist_timer.start()

    def _update_hist(self):
        if self._hist is not None:
            try:
                self._hist.set_image(self.ed.doc.display_image)
            except RuntimeError:
                self._hist = None
