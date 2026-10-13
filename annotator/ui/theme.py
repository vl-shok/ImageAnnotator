"""Тёмная компактная тема в духе инженерных CAD-программ."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

QSS = """
QMainWindow, QDockWidget { background: #2b2d31; }
QToolBar { background: #2f3136; border: none; spacing: 1px; padding: 2px; }
QToolBar#Tools { border-right: 1px solid #1e1f22; }
QToolBar QToolButton { border: 1px solid transparent; border-radius: 3px; padding: 3px; margin: 0px; }
QToolBar QToolButton:hover { background: #3c4048; border-color: #4a4f59; }
QToolBar QToolButton:checked { background: #1f5f9e; border-color: #3d8de0; }
QDockWidget::title { background: #25272b; padding: 4px 6px; color: #c8ccd4; }
QLabel#PanelTitle { background: #25272b; color: #e8eaee; font-weight: bold; padding: 6px 8px; font-size: 10pt; }
QLabel#PanelSub { color: #8f96a3; padding: 2px 8px 4px 8px; font-size: 8pt; }
QLabel#PropLabel { color: #b4bac5; }
QToolButton#SectionHeader { background: #33363c; border: none; border-top: 1px solid #3d4047;
    color: #9fb4cc; font-size: 8pt; font-weight: bold; padding: 4px 4px; text-align: left; }
QToolButton#SectionHeader:hover { background: #3a3e45; }
QWidget#PropsRoot { background: #2b2d31; }
QScrollArea { border: none; background: #2b2d31; }
QTreeWidget { background: #26282c; border: none; alternate-background-color: #2a2c30; }
QTreeWidget::item { padding: 1px 0px; }
QTreeWidget::item:selected { background: #2f6db3; color: white; }
QStatusBar { background: #1f2124; color: #b8bec8; }
QStatusBar QLabel { padding: 0px 6px; }
QStatusBar QToolButton { border: 1px solid #444; border-radius: 2px; padding: 1px 6px; color: #9aa; }
QStatusBar QToolButton:checked { background: #5a4a10; border-color: #c9a227; color: #ffd84a; }
QSpinBox, QDoubleSpinBox, QComboBox, QFontComboBox, QPlainTextEdit, QLineEdit {
    background: #1f2124; border: 1px solid #44474e; border-radius: 2px; padding: 1px 3px; min-height: 18px; }
QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QLineEdit:focus { border-color: #3d8de0; }
QToolButton { padding: 2px 6px; }
QSlider::groove:horizontal { height: 4px; background: #1c1d20; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #3d8de0; border-radius: 2px; }
QSlider::handle:horizontal { background: #d8dce3; width: 10px; margin: -5px 0; border-radius: 5px; }
QMenu { background: #2f3136; border: 1px solid #1e1f22; }
QMenu::item { padding: 4px 22px 4px 22px; }
QMenu::item:selected { background: #2f6db3; }
QMenu::separator { height: 1px; background: #444; margin: 3px 6px; }
QSplitter::handle { background: #1e1f22; }
QToolButton#Toggle { background: #34373d; border: 1px solid #44474e; border-radius: 2px; color: #9ba1ab;
    padding: 3px 4px; font-size: 8pt; }
QToolButton#Toggle:hover { border-color: #5a90c8; }
QToolButton#Toggle:checked { background: #1f6fbf; border-color: #4aa3ff; color: #ffffff; }
QToolButton#ToggleMaster { background: #34373d; border: 1px solid #44474e; border-radius: 2px; color: #9ba1ab;
    padding: 4px 8px; font-weight: bold; }
QToolButton#ToggleMaster:checked { background: #1f6fbf; border-color: #4aa3ff; color: #ffffff; }
"""


def apply_theme(app: QApplication):
    app.setStyle(QStyleFactory.create("Fusion"))
    pal = QPalette()
    base = QColor(43, 45, 49)
    pal.setColor(QPalette.Window, base)
    pal.setColor(QPalette.WindowText, QColor(220, 223, 228))
    pal.setColor(QPalette.Base, QColor(31, 33, 36))
    pal.setColor(QPalette.AlternateBase, QColor(40, 42, 46))
    pal.setColor(QPalette.ToolTipBase, QColor(30, 30, 30))
    pal.setColor(QPalette.ToolTipText, QColor(230, 230, 230))
    pal.setColor(QPalette.Text, QColor(220, 223, 228))
    pal.setColor(QPalette.Button, QColor(55, 58, 64))
    pal.setColor(QPalette.ButtonText, QColor(220, 223, 228))
    pal.setColor(QPalette.BrightText, QColor(255, 80, 80))
    pal.setColor(QPalette.Highlight, QColor(47, 109, 179))
    pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    pal.setColor(QPalette.Link, QColor(90, 170, 255))
    pal.setColor(QPalette.PlaceholderText, QColor(130, 135, 145))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(115, 118, 125))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
