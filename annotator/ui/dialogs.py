"""Небольшие диалоги."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QCursor
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QSpinBox, QVBoxLayout)

from .widgets import ColorButton


class _TextEdit(QPlainTextEdit):
    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not (e.modifiers() & Qt.ShiftModifier):
            self.dlg.accept()
            return
        super().keyPressEvent(e)


class TextDialog(QDialog):
    def __init__(self, parent, initial="", title="Текст"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.edit = _TextEdit(self)
        self.edit.setPlainText(initial)
        self.edit.selectAll()
        self.edit.setMinimumSize(320, 90)
        lay.addWidget(self.edit)
        hint = QLabel("Enter — готово,  Shift+Enter — новая строка,  Esc — отмена")
        hint.setObjectName("PanelSub")
        lay.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.adjustSize()
        pos = QCursor.pos()
        self.move(pos.x() + 12, pos.y() + 12)

    def text(self):
        return self.edit.toPlainText()


def ask_text(parent, initial="", title="Текст"):
    d = TextDialog(parent, initial, title)
    if d.exec() == QDialog.Accepted:
        return d.text()
    return None


class CanvasDialog(QDialog):
    """Увеличение/уменьшение холста по сторонам."""

    def __init__(self, parent, size, color="#ffffff"):
        super().__init__(parent)
        self.setWindowTitle("Размер холста")
        self.w0, self.h0 = size
        lay = QVBoxLayout(self)
        info = QLabel(f"Текущий размер: {self.w0} × {self.h0} px.\n"
                      "Добавьте место по сторонам (отрицательное значение — обрезать).")
        lay.addWidget(info)
        g = QGridLayout()
        self.sp = {}
        for i, (k, label) in enumerate((("top", "Сверху"), ("bottom", "Снизу"), ("left", "Слева"), ("right", "Справа"))):
            s = QSpinBox()
            s.setRange(-20000, 20000)
            s.setSuffix(" px")
            s.valueChanged.connect(self._upd)
            self.sp[k] = s
            g.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            g.addWidget(s, i // 2, (i % 2) * 2 + 1)
        lay.addLayout(g)
        quick = QHBoxLayout()
        for text, side, frac in (("+30% справа", "right", 0.3), ("+30% снизу", "bottom", 0.3),
                                 ("+50% справа", "right", 0.5)):
            b = QPushButton(text)
            b.clicked.connect((lambda s, f: (lambda: self.sp[s].setValue(int((self.w0 if s in ('left', 'right') else self.h0) * f))))(side, frac))
            quick.addWidget(b)
        lay.addLayout(quick)
        row = QHBoxLayout()
        row.addWidget(QLabel("Цвет нового места:"))
        self.color = ColorButton()
        self.color.set_value(color)
        row.addWidget(self.color, 1)
        lay.addLayout(row)
        self.result_lbl = QLabel()
        lay.addWidget(self.result_lbl)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._upd()

    def _upd(self):
        v = self.values()
        self.result_lbl.setText(f"Новый размер: {self.w0 + v[0] + v[2]} × {self.h0 + v[1] + v[3]} px")

    def values(self):
        return (self.sp["left"].value(), self.sp["top"].value(), self.sp["right"].value(), self.sp["bottom"].value())

    def qcolor(self):
        return QColor(self.color._color or "#ffffff")


class NewDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Новый холст")
        lay = QGridLayout(self)
        self.w = QSpinBox()
        self.w.setRange(16, 20000)
        self.w.setValue(1920)
        self.w.setSuffix(" px")
        self.h = QSpinBox()
        self.h.setRange(16, 20000)
        self.h.setValue(1080)
        self.h.setSuffix(" px")
        self.color = ColorButton()
        self.color.set_value("#ffffff")
        lay.addWidget(QLabel("Ширина"), 0, 0)
        lay.addWidget(self.w, 0, 1)
        lay.addWidget(QLabel("Высота"), 1, 0)
        lay.addWidget(self.h, 1, 1)
        lay.addWidget(QLabel("Цвет"), 2, 0)
        lay.addWidget(self.color, 2, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb, 3, 0, 1, 2)


class BlurDialog(QDialog):
    """Размытие по Гауссу выделенной области с живым предпросмотром."""

    def __init__(self, parent, editor):
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QSlider
        self.ed = editor
        self.setWindowTitle("Размытие по Гауссу")
        self.orig = (editor.doc.background, editor.doc.bg_source)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        row.addWidget(QLabel("Радиус:"))
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 100)
        self.slider.setValue(8)
        self.val = QLabel("8 px")
        self.val.setFixedWidth(50)
        row.addWidget(self.slider, 1)
        row.addWidget(self.val)
        lay.addLayout(row)
        self.prev = QLabel("Предпросмотр на фото")
        self.prev.setObjectName("PanelSub")
        lay.addWidget(self.prev)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(120)
        self.timer.timeout.connect(self._preview)
        self.slider.valueChanged.connect(lambda v: (self.val.setText(f"{v} px"), self.timer.start()))
        self.resize(360, 120)
        self._preview()

    def sigma(self):
        return self.slider.value() / 2.0

    def _preview(self):
        from .. import imageops
        r = self.ed._sel_rect()
        if r is None:
            return
        self.ed.doc.set_background(imageops.blur_rect(self.orig[0], r, self.sigma()), self.orig[1])

    def done(self, r):
        self.timer.stop()
        self.ed.doc.set_background(*self.orig)
        if r == QDialog.Accepted:
            self.ed.raster_blur(self.sigma(), original=self.orig[0])
        super().done(r)


class GroupManagerDialog(QDialog):
    """Список групп и их объектов. Снимите галочку и нажмите OK — объект выйдет из группы."""

    def __init__(self, parent, editor):
        super().__init__(parent)
        from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
        self.ed = editor
        self.setWindowTitle("Менеджер групп")
        lay = QVBoxLayout(self)
        info = QLabel("Снимите галочку у объекта и нажмите OK — объект будет исключён из группы.\n"
                      "Группа, в которой остался один объект, распускается.")
        info.setObjectName("PanelSub")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Группа / объект", "Слой"])
        self.tree.setColumnWidth(0, 300)
        lay.addWidget(self.tree, 1)
        self._rows = []
        for n, (gid, items) in enumerate(editor.groups().items(), 1):
            g = QTreeWidgetItem([f"Группа {n}  ({len(items)} объект.)", ""])
            g.setData(0, Qt.UserRole, gid)
            f = g.font(0)
            f.setBold(True)
            g.setFont(0, f)
            self.tree.addTopLevelItem(g)
            for it in items:
                layer = editor.doc.layer(it.layer_id)
                c = QTreeWidgetItem([it.describe(), layer.name if layer else ""])
                c.setFlags(c.flags() | Qt.ItemIsUserCheckable)
                c.setCheckState(0, Qt.Checked)
                g.addChild(c)
                self._rows.append((c, it))
            g.setExpanded(True)
        self.tree.itemDoubleClicked.connect(self._select)
        row = QHBoxLayout()
        sel = QPushButton("Выделить на холсте")
        sel.clicked.connect(lambda: self._select(self.tree.currentItem()))
        ung = QPushButton("Распустить группу")
        ung.clicked.connect(self._dissolve)
        row.addWidget(sel)
        row.addWidget(ung)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(480, 420)

    def _group_of(self, row):
        if row is None:
            return None
        if row.parent() is not None:
            row = row.parent()
        return row

    def _select(self, row, *_):
        g = self._group_of(row)
        if g is None:
            return
        gid = g.data(0, Qt.UserRole)
        self.ed.sel.set([i for i in self.ed.doc.items() if i.group_id == gid])

    def _dissolve(self):
        g = self._group_of(self.tree.currentItem())
        if g is None:
            return
        for k in range(g.childCount()):
            g.child(k).setCheckState(0, Qt.Unchecked)

    def accept(self):
        out = [it for row, it in self._rows if row.checkState(0) != Qt.Checked]
        if out:
            self.ed.remove_from_groups(out)
        super().accept()
