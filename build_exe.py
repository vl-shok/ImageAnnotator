"""Сборка ImageAnnotator.exe (Windows) с помощью PyInstaller.

Запуск:  python build_exe.py          — один файл dist/ImageAnnotator.exe
         python build_exe.py --dir    — папка dist/ImageAnnotator/ (запускается быстрее)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# модули Qt, которые программе не нужны — не включаем, чтобы exe был меньше
EXCLUDE = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
    "PySide6.Qt3DRender", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth",
    "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtSvgWidgets", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtTextToSpeech", "PySide6.QtSpatialAudio", "PySide6.QtGraphs", "PySide6.QtHttpServer",
    "PySide6.QtWebSockets", "PySide6.QtNfc", "PySide6.QtStateMachine", "PySide6.QtConcurrent",
    "tkinter", "unittest", "pytest", "matplotlib", "scipy", "pandas", "IPython",
]


def make_icon(path):
    from PySide6.QtWidgets import QApplication
    from annotator.ui.icons import app_icon
    app = QApplication.instance() or QApplication([])
    pm = app_icon().pixmap(256, 256)
    pm.toImage().scaled(256, 256).save(path, "ICO")
    return os.path.exists(path)


def main():
    import PyInstaller.__main__
    onedir = "--dir" in sys.argv
    build = os.path.join(HERE, "build")
    os.makedirs(build, exist_ok=True)
    ico = os.path.join(build, "ImageAnnotator.ico")
    args = [
        os.path.join(HERE, "main.py"),
        "--name", "ImageAnnotator",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", build,
        "--specpath", build,
        "--paths", HERE,
        "--onedir" if onedir else "--onefile",
    ]
    if make_icon(ico):
        args += ["--icon", ico]
    # плагины Qt (платформа Windows, стили, форматы картинок, печать) — добавляем явно,
    # иначе exe может не запуститься: «no Qt platform plugin could be initialized»
    import PySide6
    plugins = os.path.join(os.path.dirname(PySide6.__file__), "plugins")
    for sub in ("platforms", "styles", "imageformats", "iconengines", "printsupport"):
        src = os.path.join(plugins, sub)
        if os.path.isdir(src):
            args += ["--add-binary", f"{src}{os.pathsep}PySide6/plugins/{sub}"]
    for m in EXCLUDE:
        args += ["--exclude-module", m]
    PyInstaller.__main__.run(args)


if __name__ == "__main__":
    main()
