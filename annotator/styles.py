"""Запоминание последнего использованного стиля для каждого типа объекта.

Когда пользователь меняет свойства объекта (цвет, толщину...), новое значение
становится значением по умолчанию для следующих объектов этого типа.
"""
from __future__ import annotations

import copy

# type -> {prop: value}
_STYLE: dict[str, dict] = {}

# свойства, которые не являются «стилем» и не запоминаются
NON_STYLE = {"text", "number", "angle", "brightness", "contrast", "saturation", "temperature", "curves",
             "label_side"}

# Размерные свойства хранятся «для фото ~1600 px» и масштабируются под размер
# текущего изображения, чтобы стрелки/текст были одинаково заметны на любом фото.
SIZE_PROPS = {"width", "head", "size", "line_width", "padding", "border_width", "start_size", "end_size",
              "tip_size", "gap", "arrow_size"}
_SCALE = 1.0


def set_scale_for_image(w: int, h: int):
    global _SCALE
    k = max(w, h) / 1600.0 if w and h else 1.0
    _SCALE = round(max(0.5, min(8.0, k)) * 4) / 4


def scale() -> float:
    return _SCALE


def _scaled(name, value, k):
    if name not in SIZE_PROPS or not isinstance(value, (int, float)) or isinstance(value, bool):
        return value
    v = value * k
    return int(round(v)) if isinstance(value, int) else round(v * 2) / 2


def defaults_for(cls_or_item) -> dict:
    base = copy.deepcopy(cls_or_item.DEFAULTS)
    base.update(copy.deepcopy(_STYLE.get(cls_or_item.TYPE, {})))
    if _SCALE != 1.0:
        base = {k: _scaled(k, v, _SCALE) for k, v in base.items()}
    return base


def remember(type_name: str, name: str, value):
    if name in NON_STYLE:
        return
    if name in SIZE_PROPS and isinstance(value, (int, float)) and _SCALE != 1.0:
        value = value / _SCALE
    _STYLE.setdefault(type_name, {})[name] = copy.deepcopy(value)


def all_styles() -> dict:
    return copy.deepcopy(_STYLE)


def load_styles(data: dict | None):
    _STYLE.clear()
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, dict):
                # старые версии хранили «авто» (0) для размеров наконечников — убираем
                _STYLE[k] = {kk: vv for kk, vv in v.items()
                             if not (kk in ("start_size", "end_size", "tip_size", "arrow_size") and not vv)}


def reset(type_name: str | None = None):
    if type_name is None:
        _STYLE.clear()
    else:
        _STYLE.pop(type_name, None)
