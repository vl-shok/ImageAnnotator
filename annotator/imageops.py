"""Растровые операции: слои коррекции (кривые, яркость/контраст, насыщенность),
гистограмма, правки выделенной области, размытие по Гауссу."""
from __future__ import annotations

import copy

import numpy as np
from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

# ---------------------------------------------------------------- color correction
IDENTITY_CURVE = [[0, 0], [255, 255]]
DEFAULT_COLOR = {"brightness": 0, "contrast": 0, "saturation": 100, "temperature": 0, "curves": None}


def default_curves():
    return {c: copy.deepcopy(IDENTITY_CURVE) for c in ("rgb", "r", "g", "b")}


def _curve_is_identity(pts) -> bool:
    return [list(map(int, q)) for q in pts] == IDENTITY_CURVE


def curves_is_identity(curves) -> bool:
    return not curves or all(_curve_is_identity(curves.get(c, IDENTITY_CURVE)) for c in ("rgb", "r", "g", "b"))


def color_is_identity(p: dict) -> bool:
    return (not p.get("brightness") and not p.get("contrast") and p.get("saturation", 100) == 100
            and not p.get("temperature") and curves_is_identity(p.get("curves")))


def color_to_adjustments(p: dict) -> list:
    """Параметры коррекции цвета → цепочка операций (кривые → яркость/контраст → насыщенность)."""
    out = []
    if not curves_is_identity(p.get("curves")):
        out.append({"kind": "curves", "visible": True, "params": p["curves"]})
    out.append({"kind": "bc", "visible": True,
                "params": {"brightness": p.get("brightness", 0), "contrast": p.get("contrast", 0)}})
    out.append({"kind": "hs", "visible": True,
                "params": {"saturation": p.get("saturation", 100), "temperature": p.get("temperature", 0)}})
    return out


def apply_color(img: QImage, p: dict) -> QImage:
    if img is None or img.isNull() or not p or color_is_identity(p):
        return img
    return apply_adjustments(img, color_to_adjustments(p))


def migrate_color(d: dict) -> dict:
    """Старые форматы проекта → единая коррекция цвета фона."""
    out = copy.deepcopy(DEFAULT_COLOR)
    if isinstance(d.get("color"), dict):
        out.update(d["color"])
        return out
    old = d.get("adjust")
    if isinstance(old, dict):  # формат 1
        out["brightness"] = old.get("brightness", 0)
        out["contrast"] = old.get("contrast", 0)
        out["temperature"] = old.get("temperature", 0)
        out["saturation"] = 0 if old.get("gray") else 100 + int(old.get("saturation", 0))
    for a in d.get("adjustments") or []:  # формат 2 (слои коррекции)
        if not a.get("visible", True):
            continue
        prm = a.get("params", {})
        if a.get("kind") == "curves":
            out["curves"] = copy.deepcopy(prm)
        elif a.get("kind") == "bc":
            out["brightness"] = prm.get("brightness", 0)
            out["contrast"] = prm.get("contrast", 0)
        elif a.get("kind") == "hs":
            out["saturation"] = prm.get("saturation", 100)
            out["temperature"] = prm.get("temperature", 0)
    return out


def adjustment_is_identity(adj: dict) -> bool:
    p = adj.get("params", {})
    k = adj.get("kind")
    if k == "bc":
        return not p.get("brightness") and not p.get("contrast")
    if k == "hs":
        return p.get("saturation", 100) == 100 and not p.get("temperature")
    if k == "curves":
        return curves_is_identity(p)
    return True


def curve_lut(points) -> np.ndarray:
    """Монотонная кубическая интерполяция (Fritsch–Carlson) → LUT на 256 значений."""
    pts = sorted((float(x), float(y)) for x, y in points)
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    # убрать дубли по x
    keep = np.concatenate([[True], np.diff(xs) > 1e-6])
    xs, ys = xs[keep], ys[keep]
    grid = np.arange(256, dtype=np.float64)
    if len(xs) == 1:
        return np.clip(np.full(256, ys[0]), 0, 255).astype(np.uint8)
    if len(xs) == 2:
        out = np.interp(grid, xs, ys)
        return np.clip(np.round(out), 0, 255).astype(np.uint8)
    h = np.diff(xs)
    d = np.diff(ys) / h
    m = np.zeros(len(xs))
    m[0], m[-1] = d[0], d[-1]
    for i in range(1, len(xs) - 1):
        if d[i - 1] * d[i] <= 0:
            m[i] = 0
        else:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
    out = np.empty(256)
    idx = np.clip(np.searchsorted(xs, grid) - 1, 0, len(xs) - 2)
    x0, x1 = xs[idx], xs[idx + 1]
    y0, y1 = ys[idx], ys[idx + 1]
    hh = x1 - x0
    t = np.clip((grid - x0) / hh, 0, 1)
    t2, t3 = t * t, t * t * t
    out = ((2 * t3 - 3 * t2 + 1) * y0 + (t3 - 2 * t2 + t) * hh * m[idx]
           + (-2 * t3 + 3 * t2) * y1 + (t3 - t2) * hh * m[idx + 1])
    out[grid < xs[0]] = ys[0]
    out[grid > xs[-1]] = ys[-1]
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def _apply_one(rgb: np.ndarray, adj: dict) -> np.ndarray:
    """rgb: uint8 (h, w, 3) → uint8."""
    k = adj.get("kind")
    p = adj.get("params", {})
    if k == "curves":
        master = curve_lut(p.get("rgb", IDENTITY_CURVE))
        out = np.empty_like(rgb)
        for ci, c in enumerate(("r", "g", "b")):
            lut = master[curve_lut(p.get(c, IDENTITY_CURVE))]
            out[..., ci] = lut[rgb[..., ci]]
        return out
    f = rgb.astype(np.float32)
    if k == "bc":
        b = float(p.get("brightness", 0))
        c = float(p.get("contrast", 0))
        if b:
            f += b * 2.55
        if c:
            cc = max(-254.0, min(254.0, c * 2.55))
            fac = (259.0 * (cc + 255.0)) / (255.0 * (259.0 - cc))
            f = fac * (f - 128.0) + 128.0
    elif k == "hs":
        t = float(p.get("temperature", 0))
        s = float(p.get("saturation", 100)) / 100.0
        if t:
            f[..., 0] *= 1.0 + t / 300.0
            f[..., 2] *= 1.0 - t / 300.0
        if s != 1.0:
            luma = f[..., 0] * 0.299 + f[..., 1] * 0.587 + f[..., 2] * 0.114
            f = luma[..., None] + (f - luma[..., None]) * s
    return np.clip(f, 0, 255).astype(np.uint8)


def apply_adjustments(img: QImage, adjustments) -> QImage:
    active = [a for a in (adjustments or []) if a.get("visible", True) and not adjustment_is_identity(a)]
    if img is None or img.isNull() or not active:
        return img
    a = to_rgba_array(img)
    rgb = a[..., :3]
    for adj in active:
        rgb = _apply_one(rgb, adj)
    a[..., :3] = rgb
    return from_rgba_array(a)


# ---------------------------------------------------------------- numpy <-> QImage
def to_rgba_array(img: QImage) -> np.ndarray:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8, count=img.sizeInBytes())
    return buf.reshape(h, bpl)[:, : w * 4].reshape(h, w, 4).copy()


def from_rgba_array(arr: np.ndarray) -> QImage:
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w = arr.shape[:2]
    img = QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888)
    return img.copy()


def histogram(img: QImage, max_pixels: int = 400_000):
    """Возвращает (r, g, b, luma) — массивы по 256 значений, нормированные к 1."""
    if img is None or img.isNull():
        return None
    a = to_rgba_array(img)
    step = max(1, int((a.shape[0] * a.shape[1] / max_pixels) ** 0.5))
    a = a[::step, ::step]
    out = []
    for ch in range(3):
        out.append(np.bincount(a[..., ch].ravel(), minlength=256)[:256].astype(np.float64))
    luma = (a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114).astype(np.uint8)
    out.append(np.bincount(luma.ravel(), minlength=256)[:256].astype(np.float64))
    m = max(float(np.percentile(np.concatenate(out), 99.5)), 1.0)
    return [np.minimum(h / m, 1.0) for h in out]


# ---------------------------------------------------------------- region ops
def ensure_argb(img: QImage) -> QImage:
    if img.format() != QImage.Format_ARGB32_Premultiplied:
        return img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    return img.copy()


def fill_rect(img: QImage, rect: QRect, color: QColor) -> QImage:
    out = ensure_argb(img)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_Source)
    p.fillRect(rect, color)
    p.end()
    return out


def set_rect_opacity(img: QImage, rect: QRect, opacity: float) -> QImage:
    a = to_rgba_array(img)
    r = rect.intersected(QRect(0, 0, img.width(), img.height()))
    if r.isEmpty():
        return img
    ys, xs = slice(r.top(), r.bottom() + 1), slice(r.left(), r.right() + 1)
    a[ys, xs, 3] = np.clip(a[ys, xs, 3].astype(np.float32) * opacity, 0, 255).astype(np.uint8)
    return from_rgba_array(a).convertToFormat(QImage.Format_ARGB32_Premultiplied)


def _box_blur_axis(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    if r <= 0:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    p = np.pad(a, pad, mode="edge")
    c = np.cumsum(p, axis=axis, dtype=np.float64)
    n = a.shape[axis]
    hi = np.take(c, np.arange(2 * r + 1, 2 * r + 1 + n), axis=axis)
    lo = np.take(c, np.arange(0, n), axis=axis)
    return (hi - lo) / (2 * r + 1)


def gaussian_blur_array(a: np.ndarray, sigma: float) -> np.ndarray:
    """Приближение Гаусса тремя проходами box-blur (быстро, без scipy)."""
    if sigma <= 0.3:
        return a
    n = 3
    w_ideal = (12 * sigma * sigma / n + 1) ** 0.5
    wl = int(w_ideal)
    if wl % 2 == 0:
        wl -= 1
    wu = wl + 2
    m = round((12 * sigma * sigma - n * wl * wl - 4 * n * wl - 3 * n) / (-4 * wl - 4))
    f = a.astype(np.float64)
    for i in range(n):
        w = wl if i < m else wu
        r = max(0, (w - 1) // 2)
        f = _box_blur_axis(f, r, 0)
        f = _box_blur_axis(f, r, 1)
    return np.clip(np.round(f), 0, 255).astype(np.uint8)


def blur_rect(img: QImage, rect: QRect, sigma: float) -> QImage:
    """Размытие по Гауссу внутри области (края области берут пиксели снаружи — без «рамки»)."""
    W, H = img.width(), img.height()
    r = rect.intersected(QRect(0, 0, W, H))
    if r.isEmpty() or sigma <= 0.3:
        return img
    margin = int(sigma * 3) + 2
    ext = r.adjusted(-margin, -margin, margin, margin).intersected(QRect(0, 0, W, H))
    src = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    a = to_rgba_array(src)
    sub = a[ext.top(): ext.bottom() + 1, ext.left(): ext.right() + 1]
    bl = gaussian_blur_array(sub, sigma)
    oy, ox = r.top() - ext.top(), r.left() - ext.left()
    a[r.top(): r.bottom() + 1, r.left(): r.right() + 1] = bl[oy: oy + r.height(), ox: ox + r.width()]
    return from_rgba_array(a).convertToFormat(QImage.Format_ARGB32_Premultiplied)


def expand_canvas(img: QImage, left: int, top: int, right: int, bottom: int, color: QColor) -> QImage:
    w = max(1, img.width() + left + right)
    h = max(1, img.height() + top + bottom)
    out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    out.fill(color)
    p = QPainter(out)
    p.setCompositionMode(QPainter.CompositionMode_Source)
    p.drawImage(left, top, img)
    p.end()
    return out
