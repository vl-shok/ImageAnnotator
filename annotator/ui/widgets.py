"""Компактные редакторы свойств и вспомогательные виджеты."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFontComboBox, QGridLayout,
                               QHBoxLayout, QLabel, QMenu, QPlainTextEdit, QSizePolicy, QSlider, QSpinBox,
                               QToolButton, QVBoxLayout, QWidget, QWidgetAction)

from ..props import MIXED

PRESETS = ["#ff2020", "#ff8c00", "#ffd800", "#20c020", "#00b4ff", "#2050ff", "#c020ff", "#ff40a0",
           "#ffffff", "#c0c0c0", "#606060", "#000000"]
RECENT: list[str] = []
MIXED_TEXT = "Разные"


def swatch_icon(color: str | None, size=16) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    if color is None:
        p.fillRect(0, 0, size, size, QColor(90, 90, 90))
        p.setPen(QColor(200, 200, 200))
        p.drawLine(0, size, size, 0)
    else:
        p.fillRect(0, 0, size, size, QColor(color))
    p.setPen(QColor(20, 20, 20))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pm)


def remember_color(c: str):
    c = c.lower()
    if c in RECENT:
        RECENT.remove(c)
    RECENT.insert(0, c)
    del RECENT[8:]


class ColorButton(QToolButton):
    valueChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = "#ff0000"
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setPopupMode(QToolButton.InstantPopup)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setIconSize(QSize(16, 16))
        self.menu_ = QMenu(self)
        self.menu_.aboutToShow.connect(self._build_menu)
        self.setMenu(self.menu_)
        self.set_value(self._color)

    def set_value(self, v):
        if v is MIXED:
            self._color = None
            self.setIcon(swatch_icon(None))
            self.setText(MIXED_TEXT)
        else:
            self._color = QColor(v).name()
            self.setIcon(swatch_icon(self._color))
            self.setText(self._color.upper())

    def _build_menu(self):
        m = self.menu_
        m.clear()
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        def grid(colors, title=None):
            if title:
                lb = QLabel(title)
                lb.setStyleSheet("color:#9aa; font-size:8pt;")
                lay.addWidget(lb)
            g = QGridLayout()
            g.setSpacing(3)
            for i, c in enumerate(colors):
                b = QToolButton()
                b.setIcon(swatch_icon(c, 18))
                b.setIconSize(QSize(18, 18))
                b.setAutoRaise(True)
                b.setToolTip(c.upper())
                b.clicked.connect(lambda _=False, c=c: self._pick(c))
                g.addWidget(b, i // 6, i % 6)
            lay.addLayout(g)

        grid(PRESETS)
        if RECENT:
            grid(RECENT, "Последние")
        more = QToolButton()
        more.setText("Другой цвет…")
        more.setAutoRaise(True)
        more.clicked.connect(self._dialog)
        lay.addWidget(more)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(w)
        m.addAction(wa)

    def _pick(self, c):
        self.menu_.close()
        self.set_value(c)
        remember_color(c)
        self.valueChanged.emit(self._color)

    def _dialog(self):
        self.menu_.close()
        c = QColorDialog.getColor(QColor(self._color or "#ff0000"), self.window(), "Цвет")
        if c.isValid():
            self._pick(c.name())


class OpacityEditor(QWidget):
    valueChanged = Signal(object)
    committed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.label = QLabel("100%")
        self.label.setFixedWidth(46)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.slider.valueChanged.connect(self._changed)
        self.slider.sliderReleased.connect(self.committed)

    def set_value(self, v):
        self.slider.blockSignals(True)
        if v is MIXED:
            self.slider.setValue(100)
            self.label.setText(MIXED_TEXT)
        else:
            self.slider.setValue(int(round(float(v) * 100)))
            self.label.setText(f"{int(round(float(v) * 100))}%")
        self.slider.blockSignals(False)

    def _changed(self, val):
        self.label.setText(f"{val}%")
        self.valueChanged.emit(val / 100.0)


class NumberEditor(QWidget):
    valueChanged = Signal(object)
    committed = Signal()

    def __init__(self, spec, is_float, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.is_float = is_float
        self.spec = spec
        self.box = QDoubleSpinBox() if is_float else QSpinBox()
        if is_float:
            self.box.setDecimals(4 if (spec.step or 1) < 0.1 else 1)
            self.box.setSingleStep(spec.step or 0.5)
        if spec.special:
            # минимальное значение показывается словом (например, «авто»)
            self.box.setRange(spec.min, spec.max)
            self.box.setSpecialValueText(spec.special)
        else:
            self.box.setRange(spec.min - 1, spec.max)
            self.box.setSpecialValueText(MIXED_TEXT)
        self.box.setSuffix(spec.suffix)
        self.box.setKeyboardTracking(False)
        self.box.setAccelerated(True)
        lay.addWidget(self.box)
        self.box.valueChanged.connect(self._changed)
        self.box.editingFinished.connect(self.committed)

    def set_value(self, v):
        self.box.blockSignals(True)
        if v is MIXED:
            self.box.setValue(self.box.minimum())
        else:
            self.box.setValue(float(v) if self.is_float else int(v))
        self.box.blockSignals(False)

    def _changed(self, val):
        if val < self.spec.min:
            return
        self.valueChanged.emit(float(val) if self.is_float else int(val))


class ToggleEditor(QToolButton):
    """Кнопка-переключатель с буквой (Ж/К — жирный/курсив)."""
    valueChanged = Signal(object)
    compact = True

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        self.setObjectName("IconToggle")
        self.setCheckable(True)
        self.setText(spec.icon or spec.label[:1])
        f = self.font()
        f.setPointSizeF(11)
        if spec.name == "bold":
            f.setBold(True)
        if spec.name == "italic":
            f.setItalic(True)
            f.setFamily("Times New Roman")
        self.setFont(f)
        self.setFixedSize(30, 24)
        self.setToolTip(spec.tip or spec.label)
        self.clicked.connect(lambda: self.valueChanged.emit(self.isChecked()))

    def set_value(self, v):
        self.blockSignals(True)
        self.setChecked(bool(v) and v is not MIXED)
        self.setStyleSheet("QToolButton { border-style: dashed; }" if v is MIXED else "")
        self.blockSignals(False)


class AlignEditor(QWidget):
    """Три кнопки-иконки выравнивания (влево/центр/вправо или верх/центр/низ)."""
    valueChanged = Signal(object)
    compact = True

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        from .icons import icon
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.buttons = {}
        for value, label in spec.options:
            b = QToolButton()
            b.setObjectName("IconToggle")
            b.setCheckable(True)
            b.setIcon(icon((spec.icon or "al_") + value))
            b.setIconSize(QSize(16, 16))
            b.setFixedSize(28, 24)
            b.setToolTip(f"{spec.label}: {label}")
            if spec.icon:
                b.setFixedSize(30, 26)
                b.setIconSize(QSize(18, 18))
            b.clicked.connect((lambda v: (lambda: self._pick(v)))(value))
            lay.addWidget(b)
            self.buttons[value] = b
        lay.addStretch(1)

    def _pick(self, v):
        self.set_value(v)
        self.valueChanged.emit(v)

    def set_value(self, v):
        for k, b in self.buttons.items():
            b.setChecked(k == v)


def pair_row(main, second, second_width=88):
    """Два редактора в одной строке: тип конца + размер (или две кнопки Ж/К)."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    if getattr(main, "compact", False):
        lay.addWidget(main)
        if isinstance(second, AlignEditor):
            lay.addSpacing(10)
        lay.addWidget(second)
        lay.addStretch(1)
        return w
    lay.addWidget(main, 3)
    second.setMaximumWidth(second_width)
    lay.addWidget(second, 2)
    return w


class EnumEditor(QComboBox):
    valueChanged = Signal(object)

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self._fill(False)
        self.currentIndexChanged.connect(self._changed)

    def _fill(self, mixed):
        self.blockSignals(True)
        self.clear()
        if mixed:
            self.addItem(MIXED_TEXT, MIXED)
        for v, label in self.spec.options:
            self.addItem(label, v)
        self.blockSignals(False)

    def set_value(self, v):
        self._fill(v is MIXED)
        self.blockSignals(True)
        if v is not MIXED:
            i = self.findData(v)
            self.setCurrentIndex(max(0, i))
        self.blockSignals(False)

    def _changed(self, i):
        d = self.itemData(i)
        if d is MIXED:
            return
        if self.itemData(0) is MIXED:
            self._fill(False)
            self.blockSignals(True)
            self.setCurrentIndex(max(0, self.findData(d)))
            self.blockSignals(False)
        self.valueChanged.emit(d)


class BoolEditor(QCheckBox):
    valueChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.clicked.connect(self._clicked)

    def set_value(self, v):
        self.blockSignals(True)
        if v is MIXED:
            self.setTristate(True)
            self.setCheckState(Qt.PartiallyChecked)
        else:
            self.setTristate(False)
            self.setChecked(bool(v))
        self.blockSignals(False)

    def _clicked(self):
        if self.isTristate():
            self.setTristate(False)
            self.setChecked(True)
        self.valueChanged.emit(self.isChecked())


class TextEditor(QPlainTextEdit):
    valueChanged = Signal(object)
    committed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)
        self.setTabChangesFocus(True)
        self.textChanged.connect(self._changed)
        self._block = False

    def set_value(self, v):
        if self.hasFocus() and v is not MIXED and v == self.toPlainText():
            return
        self._block = True
        self.setPlaceholderText(MIXED_TEXT if v is MIXED else "")
        self.setPlainText("" if v is MIXED else str(v))
        self._block = False

    def _changed(self):
        if not self._block:
            self.valueChanged.emit(self.toPlainText())

    def focusOutEvent(self, e):
        self.committed.emit()
        super().focusOutEvent(e)


class FontEditor(QFontComboBox):
    valueChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.currentFontChanged.connect(lambda f: self.valueChanged.emit(f.family()))

    def set_value(self, v):
        self.blockSignals(True)
        if v is MIXED:
            self.setEditText(MIXED_TEXT)
        else:
            self.setCurrentFont(QFont(v))
        self.blockSignals(False)


class SliderEditor(QWidget):
    """Ползунок для целых значений (коррекция): двойной клик по числу — значение по умолчанию."""
    valueChanged = Signal(object)
    committed = Signal()

    def __init__(self, spec, default=0, parent=None):
        super().__init__(parent)
        self.default = default
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(int(spec.min), int(spec.max))
        self.suffix = spec.suffix
        self.label = QLabel("0")
        self.label.setFixedWidth(42)
        self.label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.label.setToolTip("Двойной клик — сброс")
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.label)
        self.slider.valueChanged.connect(self._changed)
        self.slider.sliderReleased.connect(self.committed)
        self.label.mouseDoubleClickEvent = lambda e: (self.slider.setValue(int(self.default)), self.committed.emit())

    def set_value(self, v):
        self.slider.blockSignals(True)
        if v is MIXED:
            self.label.setText(MIXED_TEXT)
        else:
            self.slider.setValue(int(v))
            self.label.setText(f"{int(v)}{self.suffix}")
        self.slider.blockSignals(False)

    def _changed(self, v):
        self.label.setText(f"{v}{self.suffix}")
        self.valueChanged.emit(int(v))


class CurvesButton(QToolButton):
    """Кнопка «Кривые…» для свойства-кривой объекта."""
    valueChanged = Signal(object)
    committed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = None
        self.image_provider = lambda: None
        self.setText("Кривые…")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.clicked.connect(self._open)

    def set_value(self, v):
        self._value = None if v is MIXED else v
        active = bool(v) and v is not MIXED
        self.setText("Кривые… (изменены)" if active else "Кривые…")

    def _open(self):
        from .curves import CurvesDialog
        orig = self._value
        self.committed.emit()
        dlg = CurvesDialog(self.window(), orig, self.image_provider(), lambda c: self.valueChanged.emit(c))
        if dlg.exec() != QDialog.Accepted:
            self.valueChanged.emit(orig)
        self.committed.emit()


class ToggleGrid(QWidget):
    """Сетка кнопок-переключателей в стиле Altium (активная — голубая)."""
    toggled = Signal(str, bool)

    def __init__(self, items, columns=3, parent=None):
        super().__init__(parent)
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(3)
        self.buttons = {}
        for i, (key, label) in enumerate(items):
            b = QToolButton()
            b.setObjectName("Toggle")
            b.setText(label)
            b.setCheckable(True)
            b.setToolTip(label)
            b.setMinimumWidth(20)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            b.toggled.connect((lambda k: (lambda on: self.toggled.emit(k, on)))(key))
            g.addWidget(b, i // columns, i % columns)
            self.buttons[key] = b

    def set_checked(self, key, on):
        b = self.buttons[key]
        b.blockSignals(True)
        b.setChecked(on)
        b.blockSignals(False)


def make_editor(spec):
    k = spec.kind
    if k == "toggle":
        return ToggleEditor(spec)
    if k == "align":
        return AlignEditor(spec)
    if k == "slider":
        return SliderEditor(spec, default=100 if spec.name == "saturation" else 0)
    if k == "curves":
        return CurvesButton()
    if k == "color":
        return ColorButton()
    if k == "opacity":
        return OpacityEditor()
    if k == "int":
        return NumberEditor(spec, False)
    if k == "float":
        return NumberEditor(spec, True)
    if k == "enum":
        return EnumEditor(spec)
    if k == "bool":
        return BoolEditor()
    if k == "text":
        return TextEditor()
    if k == "font":
        return FontEditor()
    raise ValueError(k)


class Section(QWidget):
    """Сворачиваемая секция панели свойств."""
    collapsed_state: dict = {}

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.header = QToolButton()
        self.header.setObjectName("SectionHeader")
        self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.header.setCheckable(True)
        self.header.setChecked(not Section.collapsed_state.get(title, False))
        self.header.setArrowType(Qt.DownArrow if self.header.isChecked() else Qt.RightArrow)
        self.header.setText(title.upper())
        self.header.toggled.connect(self._toggle)
        lay.addWidget(self.header)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(8, 4, 6, 6)
        self.grid.setHorizontalSpacing(8)
        self.grid.setVerticalSpacing(4)
        self.grid.setColumnStretch(1, 1)
        lay.addWidget(self.body)
        self.body.setVisible(self.header.isChecked())

    def _toggle(self, on):
        self.header.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(on)
        Section.collapsed_state[self.title] = not on

    def add_row(self, label, widget):
        r = self.grid.rowCount()
        if label:
            lb = QLabel(label)
            lb.setObjectName("PropLabel")
            self.grid.addWidget(lb, r, 0, Qt.AlignLeft | Qt.AlignVCenter)
            self.grid.addWidget(widget, r, 1)
        else:
            self.grid.addWidget(widget, r, 0, 1, 2)
        return widget
