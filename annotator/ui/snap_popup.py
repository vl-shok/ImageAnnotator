"""Всплывающая панель «Привязки и фильтр выделения» (кнопка на верхней панели)."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMenu, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget,
                               QWidgetAction)

from ..snap import SNAP_KINDS
from .icons import icon
from .widgets import ToggleGrid


def _title(text):
    lb = QLabel(text.upper())
    lb.setStyleSheet("color:#9fb4cc; font-size:8pt; font-weight:bold; padding-top:4px;")
    return lb


class SnapPanel(QWidget):
    """mode: "snap" — привязки, "filter" — фильтр выделения."""

    def __init__(self, editor, mode="snap", parent=None):
        super().__init__(parent)
        self.ed = editor
        sn = editor.snap
        flt = editor.sel.filter
        self.setMinimumWidth(330)
        self.mode = mode
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(4)
        self.master = self.kinds = self.allb = self.types = None
        if mode == "snap":
            self._build_snap(lay, sn)
        else:
            self._build_filter(lay, flt)
        self._sync()

    def _build_snap(self, lay, sn):
        lay.addWidget(_title("Привязки"))
        self.master = QToolButton()
        self.master.setObjectName("ToggleMaster")
        self.master.setCheckable(True)
        self.master.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.master.toggled.connect(self._master)
        lay.addWidget(self.master)
        self.kinds = ToggleGrid(SNAP_KINDS + [("image", "Края фото")], columns=3)
        for k, _ in SNAP_KINDS:
            self.kinds.set_checked(k, k in sn.kinds)
        self.kinds.set_checked("image", sn.to_image)
        self.kinds.toggled.connect(self._kind)
        lay.addWidget(self.kinds)
        row = QHBoxLayout()
        row.addWidget(QLabel("Радиус захвата:"))
        rad = QSpinBox()
        rad.setRange(3, 40)
        rad.setSuffix(" px")
        rad.setValue(sn.radius_px)
        rad.valueChanged.connect(lambda v: setattr(sn, "radius_px", v))
        row.addWidget(rad)
        row.addStretch(1)
        lay.addLayout(row)

    def _build_filter(self, lay, flt):
        lay.addWidget(_title("Фильтр выделения"))
        self.allb = QToolButton()
        self.allb.setObjectName("ToggleMaster")
        self.allb.setCheckable(True)
        self.allb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.allb.toggled.connect(self._all)
        lay.addWidget(self.allb)
        self.types = ToggleGrid(flt.TYPES, columns=3)
        for t, _ in flt.TYPES:
            self.types.set_checked(t, t in flt.allowed)
        self.types.toggled.connect(self._type)
        lay.addWidget(self.types)

    def _sync(self):
        sn = self.ed.snap
        if self.master is not None:
            self.master.blockSignals(True)
            self.master.setChecked(sn.enabled)
            self.master.setText("Привязки включены  (Shift+S)" if sn.enabled else "Привязки выключены  (Shift+S)")
            self.master.blockSignals(False)
            self.kinds.setEnabled(sn.enabled)
        if self.allb is None:
            return
        flt = self.ed.sel.filter
        on = len(flt.allowed) == len(flt.TYPES)
        self.allb.blockSignals(True)
        self.allb.setChecked(on)
        self.allb.setText("Все типы — вкл" if on else ("Все типы — выкл" if not flt.allowed else "Включить все типы"))
        self.allb.blockSignals(False)

    def _master(self, on):
        self.ed.snap.enabled = on
        self.ed.snapChanged.emit()
        self._sync()

    def _kind(self, k, on):
        sn = self.ed.snap
        if k == "image":
            sn.to_image = on
        elif on:
            sn.kinds.add(k)
        else:
            sn.kinds.discard(k)

    def _type(self, t, on):
        flt = self.ed.sel.filter
        if on:
            flt.allowed.add(t)
        else:
            flt.allowed.discard(t)
        self.ed.sel.set([i for i in self.ed.sel.items if flt.allows(i)])
        self._sync()
        self.ed.filterChanged.emit()

    def _all(self, on):
        flt = self.ed.sel.filter
        flt.set_all(on)
        for t, _ in flt.TYPES:
            self.types.set_checked(t, on)
        if not on:
            self.ed.sel.clear()
        self._sync()
        self.ed.filterChanged.emit()


class SnapButton(QToolButton):
    """Кнопка на панели: клик открывает панель привязок и фильтра выделения."""

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.ed = editor
        self.setIcon(icon("snap"))
        self.setText("Привязки")
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setToolTip("Привязки и фильтр выделения")
        self.setPopupMode(QToolButton.InstantPopup)
        self.setCheckable(True)
        self.menu_ = QMenu(self)
        self.menu_.aboutToShow.connect(self._build)
        self.setMenu(self.menu_)
        editor.snapChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.setChecked(self.ed.snap.enabled)

    def _build(self):
        self.menu_.clear()
        wa = QWidgetAction(self.menu_)
        wa.setDefaultWidget(SnapPanel(self.ed, "snap"))
        self.menu_.addAction(wa)


class FilterButton(QToolButton):
    """Кнопка «Фильтр»: какие типы объектов можно выделять."""

    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.ed = editor
        self.setIcon(icon("filter"))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setToolTip("Фильтр выделения: какие объекты можно выделять")
        self.setPopupMode(QToolButton.InstantPopup)
        self.setCheckable(True)
        self.menu_ = QMenu(self)
        self.menu_.aboutToShow.connect(self._build)
        self.setMenu(self.menu_)
        editor.filterChanged.connect(self.refresh)
        self.refresh()

    def refresh(self):
        flt = self.ed.sel.filter
        full = len(flt.allowed) == len(flt.TYPES)
        self.setText("Фильтр" if full else f"Фильтр ({len(flt.allowed)}/{len(flt.TYPES)})")
        # подсвечен, когда фильтр что-то ограничивает
        self.setChecked(not full)

    def _build(self):
        self.menu_.clear()
        wa = QWidgetAction(self.menu_)
        wa.setDefaultWidget(SnapPanel(self.ed, "filter"))
        self.menu_.addAction(wa)
