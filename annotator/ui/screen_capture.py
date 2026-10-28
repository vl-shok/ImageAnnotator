"""Снимок экрана: область (мышью), окно (под курсором) или весь экран.

Экран «замораживается» снимком, поверх показывается затемнённый оверлей; выделенная часть — без затемнения.
В режиме «Область» простой щелчок (без протягивания) снимает окно под курсором.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

ACCENT = QColor(0, 150, 255)
CLICK_PX = 4          # меньше — это щелчок, а не выделение области


# ---------------------------------------------------------------- окна Windows (физические пиксели)
def _win_api():
    import ctypes
    from ctypes import wintypes
    return ctypes, wintypes


def monitor_origin_under_cursor() -> QPoint | None:
    """Левый верхний угол монитора под курсором в физических пикселях (Windows)."""
    if sys.platform != "win32":
        return None
    ctypes, wintypes = _win_api()

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]
    user32 = ctypes.windll.user32
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
    mon = user32.MonitorFromPoint(pt, 2)            # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return None
    return QPoint(mi.rcMonitor.left, mi.rcMonitor.top)


def top_level_windows() -> list[QRect]:
    """Видимые окна других программ сверху вниз (по Z-порядку), прямоугольники в физических пикселях."""
    if sys.platform != "win32":
        return []
    ctypes, wintypes = _win_api()
    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    H = wintypes.HWND
    for fn, args in ((user32.IsWindowVisible, [H]), (user32.IsIconic, [H]),
                     (user32.GetWindowThreadProcessId, [H, ctypes.POINTER(wintypes.DWORD)]),
                     (user32.GetWindowTextLengthW, [H]), (user32.GetWindowRect, [H, ctypes.POINTER(wintypes.RECT)]),
                     (dwm.DwmGetWindowAttribute, [H, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD])):
        fn.argtypes = args
    me = os.getpid()
    out = []

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == me:
            return True
        cloaked = wintypes.DWORD()
        dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))   # DWMWA_CLOAKED
        if cloaked.value:
            return True
        r = wintypes.RECT()
        if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:        # рамка без тени
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        rect = QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)
        if rect.width() > 40 and rect.height() > 30 and user32.GetWindowTextLengthW(hwnd) > 0:
            out.append(rect)
        return True

    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(visit)
    user32.EnumWindows(proc, 0)
    return out


def windows_on_image(image_size, origin: QPoint | None) -> list[QRect]:
    """Окна в координатах снимка монитора (пиксели снимка)."""
    if origin is None:
        return []
    bounds = QRect(QPoint(0, 0), image_size)
    out = []
    for r in top_level_windows():
        rr = r.translated(-origin).intersected(bounds)
        if rr.width() > 10 and rr.height() > 10:
            out.append(rr)
    return out


# ---------------------------------------------------------------- оверлей выбора
class CaptureOverlay(QWidget):
    """Полноэкранный оверлей на одном мониторе: показывает замороженный снимок, выбирает область/окно."""
    finished = Signal(object)        # QImage или None (отмена)

    def __init__(self, screen, pixmap: QPixmap, mode: str, windows: list[QRect]):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.pix = pixmap
        self.dpr = pixmap.devicePixelRatio() or 1.0
        self.mode = mode                 # "region" | "window"
        self.windows = windows           # прямоугольники окон в пикселях снимка, сверху вниз
        self.press = None                # точка нажатия (логические координаты оверлея)
        self.cur = None
        self.hover_win = None
        self._done = False
        if screen is not None:
            self.setScreen(screen)
            self.setGeometry(screen.geometry())

    # ------------------------------------------------------------ координаты
    def to_img(self, p) -> QPoint:
        return QPoint(round(p.x() * self.dpr), round(p.y() * self.dpr))

    def to_view(self, r: QRect) -> QRectF:
        return QRectF(r.x() / self.dpr, r.y() / self.dpr, r.width() / self.dpr, r.height() / self.dpr)

    def window_at(self, p) -> QRect | None:
        ip = self.to_img(p)
        for r in self.windows:
            if r.contains(ip):
                return r
        return None

    def selection_img(self) -> QRect | None:
        """Текущий выбор в пикселях снимка."""
        if self.press is not None and self.cur is not None and \
                (self.cur - self.press).manhattanLength() >= CLICK_PX:
            a, b = self.to_img(self.press), self.to_img(self.cur)
            r = QRect(min(a.x(), b.x()), min(a.y(), b.y()), abs(b.x() - a.x()), abs(b.y() - a.y()))
            return r.intersected(QRect(QPoint(0, 0), self.pix.size()))
        return self.hover_win

    # ------------------------------------------------------------ события
    def mousePressEvent(self, ev):
        if ev.button() == Qt.RightButton:
            self._finish(None)
            return
        if ev.button() == Qt.LeftButton:
            self.press = self.cur = ev.position().toPoint()
            self.update()

    def mouseMoveEvent(self, ev):
        self.cur = ev.position().toPoint()
        if self.press is None:
            self.hover_win = self.window_at(self.cur)
        self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton or self.press is None:
            return
        self.cur = ev.position().toPoint()
        dragged = (self.cur - self.press).manhattanLength() >= CLICK_PX
        if self.mode == "region" and dragged:
            r = self.selection_img()
        else:
            r = self.window_at(self.cur)       # щелчок — окно под курсором
        self.press = None
        if r is not None and r.width() > 1 and r.height() > 1:
            self._finish(self.pix.copy(r).toImage())
        else:
            self.update()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self._finish(None)
            return
        super().keyPressEvent(ev)

    def _finish(self, img):
        if self._done:
            return
        self._done = True
        self.finished.emit(img)      # сначала вернуть главное окно, потом закрыть оверлей
        self.close()

    # ------------------------------------------------------------ отрисовка
    def paintEvent(self, ev):
        p = QPainter(self)
        p.drawPixmap(self.rect(), self.pix)
        sel = self.selection_img()
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if sel is not None:
            vr = self.to_view(sel)
            p.drawPixmap(vr, self.pix, QRectF(sel))
            pen = QPen(ACCENT, 2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(vr.adjusted(1, 1, -1, -1))
            label = f"{sel.width()} × {sel.height()}"
            f = QFont(self.font())
            f.setPointSizeF(10)
            p.setFont(f)
            tw = p.fontMetrics().horizontalAdvance(label) + 12
            tr = QRectF(vr.left(), vr.top() - 24 if vr.top() > 26 else vr.bottom() + 4, tw, 20)
            p.fillRect(tr, QColor(0, 0, 0, 180))
            p.setPen(QColor(255, 255, 255))
            p.drawText(tr, Qt.AlignCenter, label)
        hint = ("Выделите область мышью (щелчок — окно под курсором).  Esc или ПКМ — отмена"
                if self.mode == "region" else "Щёлкните по окну.  Esc или ПКМ — отмена")
        f = QFont(self.font())
        f.setPointSizeF(11)
        p.setFont(f)
        w = p.fontMetrics().horizontalAdvance(hint) + 28
        hr = QRectF((self.width() - w) / 2, 14, w, 30)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 22, 26, 220))
        p.drawRoundedRect(hr, 6, 6)
        p.setPen(QColor(235, 238, 242))
        p.drawText(hr, Qt.AlignCenter, hint)
        p.end()

    def start(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()


def grab_screen_under_cursor():
    """(экран, снимок экрана под курсором в физических пикселях)."""
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    return screen, screen.grabWindow(0)


def image_of(pixmap: QPixmap) -> QImage:
    return pixmap.toImage().convertToFormat(QImage.Format_ARGB32_Premultiplied)
