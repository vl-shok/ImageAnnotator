"""ImageAnnotator — инженерный редактор пометок на фотографиях.

Запуск:  python main.py [фото или проект.iap]
"""
import os
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from annotator.mainwindow import APP_NAME, MainWindow  # noqa: E402
from annotator.ui.theme import apply_theme  # noqa: E402


def _excepthook(etype, value, tb):
    msg = "".join(traceback.format_exception(etype, value, tb))
    sys.stderr.write(msg)
    try:
        log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "error.log")
        with open(log, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass
    app = QApplication.instance()
    if app is not None:
        QMessageBox.critical(None, APP_NAME, f"Внутренняя ошибка (записана в error.log):\n\n{value}")


def main():
    sys.excepthook = _excepthook
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    apply_theme(app)
    w = MainWindow()
    w.showMaximized() if w.first_run else w.show()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        w.open_path(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
