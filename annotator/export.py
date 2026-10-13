"""Экспорт в PNG/JPG/PDF и печать. Служебные элементы (ручки, hover, привязки)
рисуются только во view и в экспорт не попадают. Разрешение — исходное."""
from __future__ import annotations

from PySide6.QtCore import QMarginsF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter


def render_image(doc, transparent=False) -> QImage | None:
    rect = doc.export_rect()
    if rect.isEmpty():
        return None
    w, h = int(round(rect.width())), int(round(rect.height()))
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent if transparent else QColor(doc.canvas_color or "#ffffff"))
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
    doc.scene.render(p, QRectF(0, 0, w, h), rect)
    p.end()
    return img


def export_file(doc, path: str, jpg_quality=92) -> bool:
    low = path.lower()
    if low.endswith(".pdf"):
        return export_pdf(doc, path)
    if low.endswith((".jpg", ".jpeg")):
        img = render_image(doc, transparent=False)
        if img is None:
            return False
        return img.convertToFormat(QImage.Format_RGB888).save(path, "JPG", jpg_quality)
    img = render_image(doc, transparent=True)
    if img is None:
        return False
    return img.save(path, "PNG")


def _draw_fit(painter, img: QImage, target: QRectF):
    k = min(target.width() / img.width(), target.height() / img.height())
    w, h = img.width() * k, img.height() * k
    r = QRectF(target.left() + (target.width() - w) / 2, target.top() + (target.height() - h) / 2, w, h)
    painter.drawImage(r, img)


def export_pdf(doc, path: str) -> bool:
    img = render_image(doc)
    if img is None:
        return False
    wr = QPdfWriter(path)
    wr.setResolution(300)
    landscape = img.width() >= img.height()
    wr.setPageLayout(QPageLayout(QPageSize(QPageSize.A4),
                                 QPageLayout.Landscape if landscape else QPageLayout.Portrait,
                                 QMarginsF(8, 8, 8, 8), QPageLayout.Millimeter))
    wr.setTitle("ImageAnnotator export")
    p = QPainter(wr)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    _draw_fit(p, img, QRectF(p.viewport()))
    p.end()
    return True


def print_doc(doc, parent=None):
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
    img = render_image(doc)
    if img is None:
        return
    printer = QPrinter(QPrinter.HighResolution)
    printer.setPageOrientation(QPageLayout.Landscape if img.width() >= img.height() else QPageLayout.Portrait)

    def paint(pr):
        p = QPainter(pr)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        page = QRectF(pr.pageLayout().paintRectPixels(pr.resolution()))
        page.moveTo(0, 0)
        _draw_fit(p, img, page)
        p.end()

    dlg = QPrintPreviewDialog(printer, parent)
    dlg.setWindowTitle("Печать — предпросмотр")
    dlg.paintRequested.connect(paint)
    dlg.resize(1000, 750)
    dlg.exec()
