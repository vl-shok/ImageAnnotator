"""Окно «Коррекция цвета» — для основного фото и для вставленных изображений.

Изменения видны сразу (предпросмотр), OK — записать в историю, Отмена — вернуть как было.
Коррекция неразрушающая: исходные пиксели не меняются, её можно сбросить в любой момент.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout)

from .. import imageops
from ..props import PropSpec
from .curves import CurvesEditor
from .histogram import HistogramWidget
from .widgets import Section, SliderEditor

SLIDERS = [("brightness", "Яркость", -100, 100, 0, ""),
           ("contrast", "Контраст", -100, 100, 0, ""),
           ("saturation", "Насыщенность", 0, 200, 100, "%"),
           ("temperature", "Температура", -100, 100, 0, "")]


class ColorDialog(QDialog):
    def __init__(self, parent, title, params: dict, source_image, on_preview):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.source = source_image
        self.on_preview = on_preview
        self.initial = copy.deepcopy(imageops.DEFAULT_COLOR)
        self.initial.update(copy.deepcopy(params or {}))
        self.params = copy.deepcopy(self.initial)

        lay = QVBoxLayout(self)
        lay.setSpacing(6)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        self.sliders = {}
        for r, (key, label, lo, hi, dflt, suf) in enumerate(SLIDERS):
            w = SliderEditor(PropSpec(key, label, "slider", min=lo, max=hi, suffix=suf), default=dflt)
            w.set_value(self.params.get(key, dflt))
            w.valueChanged.connect((lambda k: (lambda v: self._set(k, v)))(key))
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(w, r, 1)
            self.sliders[key] = w
        lay.addLayout(grid)
        note = QLabel("Насыщенность 0% — чёрно-белое. Двойной клик по числу — сброс ползунка.")
        note.setObjectName("PanelSub")
        lay.addWidget(note)

        sec = Section("Кривые")
        self.curves = CurvesEditor()
        self.curves.set_curves(self.params.get("curves"))
        self.curves.set_histogram(source_image)
        self.curves.changed.connect(lambda c: self._set("curves", None if imageops.curves_is_identity(c) else c))
        sec.add_row("", self.curves)
        lay.addWidget(sec)

        sec = Section("Гистограмма результата")
        self.hist = HistogramWidget()
        sec.add_row("", self.hist)
        lay.addWidget(sec)

        row = QHBoxLayout()
        reset = QPushButton("Сбросить всё")
        reset.setToolTip("Вернуть исходные цвета")
        reset.clicked.connect(self.reset)
        row.addWidget(reset)
        row.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Применить")
        bb.button(QDialogButtonBox.Cancel).setText("Отмена")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        row.addWidget(bb)
        lay.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._preview)
        self._hist_timer = QTimer(self)
        self._hist_timer.setSingleShot(True)
        self._hist_timer.setInterval(300)
        self._hist_timer.timeout.connect(self._update_hist)
        self.resize(380, 640)
        self._update_hist()

    def _set(self, key, value):
        self.params[key] = copy.deepcopy(value)
        self._timer.start()

    def _preview(self):
        self.on_preview(copy.deepcopy(self.params))
        self._hist_timer.start()

    def _update_hist(self):
        try:
            self.hist.set_image(imageops.apply_color(self.source, self.params) if self.source is not None else None)
        except Exception:
            pass

    def reset(self):
        self.params = copy.deepcopy(imageops.DEFAULT_COLOR)
        for key, w in self.sliders.items():
            w.set_value(self.params[key])
        self.curves.set_curves(None)
        self._preview()

    def result_params(self):
        p = copy.deepcopy(self.params)
        if imageops.curves_is_identity(p.get("curves")):
            p["curves"] = None
        return p

    def done(self, r):
        self._timer.stop()
        if r != QDialog.Accepted:
            self.on_preview(copy.deepcopy(self.initial))
        else:
            self.on_preview(self.result_params())
        super().done(r)
