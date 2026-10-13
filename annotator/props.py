"""Описание редактируемых свойств объектов (для панели свойств)."""
from __future__ import annotations


class _Mixed:
    """Маркер «разные значения» при множественном выделении."""

    def __repr__(self):
        return "MIXED"

    def __bool__(self):
        return False


MIXED = _Mixed()


class PropSpec:
    """kind: color | opacity | int | float | enum | bool | text | font"""

    def __init__(self, name, label, kind, section="Общие", **kw):
        self.name = name
        self.label = label
        self.kind = kind
        self.section = section
        self.min = kw.get("min", 0)
        self.max = kw.get("max", 1000)
        self.step = kw.get("step", 1)
        self.options = kw.get("options", [])  # [(value, label)]
        self.suffix = kw.get("suffix", "")
        self.pair = kw.get("pair")          # второй редактор в той же строке (например, размер наконечника)
        self.special = kw.get("special")    # текст для минимального значения (например, «авто»)

    def key(self):
        return (self.name, self.kind)


LINE_STYLES = [("solid", "Сплошная"), ("dash", "Штрих"), ("dashdot", "Штрих-пунктир"), ("dot", "Точки")]
CAP_STYLES = [("none", "Нет"), ("arrow", "Стрелка"), ("dot", "Точка")]




def cap_size(name):
    return PropSpec(name, "Размер", "float", min=1, max=400, step=1, suffix=" px")


ALIGNS = [("left", "Влево"), ("center", "По центру"), ("right", "Вправо")]

S_LINE = "Линия"
S_FILL = "Заливка"
S_TEXT = "Текст"
S_BG = "Подложка"
S_ENDS = "Концы"
S_LEADER = "Указатель"
S_COMMON = "Общие"


def line_props(with_style=True):
    out = [
        PropSpec("color", "Цвет", "color", S_LINE),
        PropSpec("width", "Толщина", "float", S_LINE, min=0.5, max=100, step=0.5, suffix=" px"),
    ]
    if with_style:
        out.append(PropSpec("style", "Стиль", "enum", S_LINE, options=LINE_STYLES))
    return out


def fill_props():
    return [
        PropSpec("fill", "Заливка", "bool", S_FILL),
        PropSpec("fill_color", "Цвет заливки", "color", S_FILL),
        PropSpec("fill_opacity", "Прозр. заливки", "opacity", S_FILL),
    ]


def text_props(with_text=True):
    out = []
    if with_text:
        out.append(PropSpec("text", "Текст", "text", S_TEXT))
    out += [
        PropSpec("font", "Шрифт", "font", S_TEXT),
        PropSpec("size", "Размер", "int", S_TEXT, min=4, max=600, suffix=" px"),
        PropSpec("color", "Цвет", "color", S_TEXT),
        PropSpec("bold", "Жирный", "bool", S_TEXT),
        PropSpec("italic", "Курсив", "bool", S_TEXT),
        PropSpec("align", "Выравнивание", "enum", S_TEXT, options=ALIGNS),
        PropSpec("bg", "Подложка", "bool", S_BG),
        PropSpec("bg_color", "Цвет подложки", "color", S_BG),
        PropSpec("bg_opacity", "Прозр. подложки", "opacity", S_BG),
        PropSpec("padding", "Отступ", "int", S_BG, min=0, max=100, suffix=" px"),
    ]
    return out


OPACITY = PropSpec("opacity", "Непрозрачность", "opacity", S_COMMON)
