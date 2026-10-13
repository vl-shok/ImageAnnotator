"""Тесты логики (без GUI-взаимодействия). Запуск: python -m pytest tests"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from PySide6.QtCore import QPointF, QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from annotator.editor import Editor  # noqa: E402
from annotator.items import ArrowItem, LineItem, RectItem, TextItem, NumberItem, CalloutItem  # noqa: E402
from annotator.props import MIXED  # noqa: E402
from annotator.ui.properties import common_specs, common_value  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def ed():
    from annotator import styles
    styles.reset()
    e = Editor()
    img = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(20, 80, 40))
    e.new_from_image(img)
    return e


def line(p0, p1, **props):
    it = LineItem(props=props)
    it.set_drag(QPointF(*p0), QPointF(*p1))
    return it


def test_add_undo_redo(ed):
    a = line((0, 0), (100, 0))
    ed.add_items([a])
    assert ed.doc.items() == [a]
    ed.undo.undo()
    assert ed.doc.items() == []
    ed.undo.redo()
    assert ed.doc.items() == [a]


def test_prop_change_and_merge(ed):
    a, b = line((0, 0), (10, 0)), line((0, 10), (10, 10))
    ed.add_items([a, b])
    ed.sel.set([a, b])
    w0 = a.props["width"]
    ed.set_prop("width", 5.0)
    ed.set_prop("width", 7.0)  # должно слиться с предыдущим
    assert a.props["width"] == 7.0 and b.props["width"] == 7.0
    ed.undo.undo()
    assert a.props["width"] == w0
    # новый объект наследует последний стиль
    assert line((0, 0), (1, 1)).props["width"] == 7.0


def test_common_props_mixed(ed):
    a, b = line((0, 0), (10, 0), color="#ff0000"), line((0, 5), (10, 5), color="#00ff00")
    t = TextItem()
    specs = {s.name for s in common_specs([a, b])}
    assert {"color", "width", "style"} <= specs
    assert common_value([a, b], lambda i: i.props["color"]) is MIXED
    mixed = {s.name for s in common_specs([a, t])}
    assert "width" not in mixed and "opacity" in mixed


def test_serialization_roundtrip(ed, tmp_path):
    a = line((10, 10), (200, 50), end_cap="arrow")
    r = RectItem()
    r.set_drag(QPointF(5, 5), QPointF(60, 40))
    t = TextItem({"text": "REMOVE"})
    t.setPos(300, 300)
    n = NumberItem({"number": 7, "leader": True}, tip=QPointF(40, 40))
    c = CalloutItem({"text": "Заменить"}, tip=QPointF(-50, 80))
    ed.add_items([a, r, t, n, c])
    lay = ed.add_layer("Второй")
    ed.move_to_layer([r], lay.id)
    ed.sel.set([a, t])
    ed.group()
    path = str(tmp_path / "p.iap")
    ed.save_project(path)
    e2 = Editor()
    e2.open_project(path)
    d1 = sorted((i.to_dict() for i in ed.doc.items()), key=lambda d: d["id"])
    d2 = sorted((i.to_dict() for i in e2.doc.items()), key=lambda d: d["id"])
    assert d1 == d2
    assert [l.name for l in e2.doc.layers] == [l.name for l in ed.doc.layers]
    assert e2.doc.background.size() == ed.doc.background.size()


def test_selection_filter_and_locked_layer(ed):
    a = line((0, 0), (100, 0))
    t = TextItem()
    ed.add_items([a, t])
    ed.sel.filter.allowed.discard("text")
    ed.sel.select_all()
    assert ed.sel.items == [a]
    ed.sel.filter.set_all(True)
    ed.set_layer_attr(a.layer_id, "locked", True)
    ed.sel.select_all()
    assert ed.sel.items == []


def test_snap_endpoint_and_mid(ed):
    a = line((100, 100), (300, 100))
    ed.add_items([a])
    res = ed.snap.find(ed.doc, QPointF(103, 102), 10)
    assert res[1] == "endpoint" and res[0] == QPointF(100, 100)
    res = ed.snap.find(ed.doc, QPointF(199, 104), 10)
    assert res[1] == "midpoint"
    ed.snap.kinds = {"edge"}
    res = ed.snap.find(ed.doc, QPointF(150, 104), 10)
    assert res[1] == "edge" and abs(res[0].y() - 100) < 1e-6


def test_zorder(ed):
    a, b, c = line((0, 0), (1, 1)), line((0, 0), (2, 2)), line((0, 0), (3, 3))
    ed.add_items([a, b, c])
    order = lambda: [i for i in ed.doc.items_in_layer(a.layer_id)]  # noqa
    assert order() == [a, b, c]
    ed.sel.set([a])
    ed.reorder("front")
    assert order() == [b, c, a]
    ed.reorder("backward")
    assert order() == [b, a, c]
    ed.undo.undo()
    assert order() == [b, c, a]
    assert a.zValue() > c.zValue()


def test_layers_order_and_delete(ed):
    a = line((0, 0), (10, 10))
    ed.add_items([a])
    l2 = ed.add_layer()
    b = line((0, 0), (5, 5))
    ed.add_items([b])
    assert b.layer_id == l2.id
    assert b.zValue() > a.zValue()
    ed.move_layer(l2.id, -1)
    assert b.zValue() < a.zValue()
    ed.delete_layer(l2.id)
    assert b not in ed.doc.items() and ed.doc.layer(l2.id) is None
    ed.undo.undo()
    assert b in ed.doc.items() and ed.doc.layer(l2.id) is not None


def test_hidden_layer_not_exported(ed):
    from annotator.export import render_image
    r = RectItem(props={"fill": True, "fill_color": "#ff0000", "fill_opacity": 1.0, "width": 0.5})
    r.set_drag(QPointF(100, 100), QPointF(200, 200))
    ed.add_items([r])
    img = render_image(ed.doc)
    assert QColor(img.pixel(150, 150)).red() > 200
    ed.set_layer_attr(r.layer_id, "visible", False)
    img = render_image(ed.doc)
    assert QColor(img.pixel(150, 150)).red() < 100
    assert img.width() == 800 and img.height() == 600


def test_handles_and_constrain(ed):
    a = line((0, 0), (100, 0))
    ed.add_items([a])
    a.move_handle(1, QPointF(100, 7), constrain=True)
    assert abs(a.points[1].y()) < 1e-6
    a.move_handle(1, QPointF(100, 95), constrain=True)
    p = a.points[1]
    assert abs(p.x() - p.y()) < 1e-6


def test_group_selects_together(ed):
    a, b = line((0, 0), (1, 1)), line((5, 5), (6, 6))
    ed.add_items([a, b])
    ed.sel.set([a, b])
    ed.group()
    ed.sel.set([a])
    assert set(ed.sel.items) == {a, b}
    ed.ungroup()
    ed.sel.set([a])
    assert ed.sel.items == [a]


def test_canvas_resize_moves_items(ed):
    a = line((10, 10), (20, 20))
    ed.add_items([a])
    ed.resize_canvas(100, 50, 0, 0, QColor("white"))
    assert ed.doc.background.width() == 900 and ed.doc.background.height() == 650
    assert a.pos() == QPointF(110, 60)
    ed.undo.undo()
    assert ed.doc.background.width() == 800 and a.pos() == QPointF(10, 10)


def test_arrow_and_hit(ed):
    ar = ArrowItem()
    ar.set_drag(QPointF(0, 0), QPointF(200, 0))
    ed.add_items([ar])
    assert ar.hit(QPointF(190, 0), 2)
    assert not ar.hit(QPointF(100, 60), 2)


def test_copy_paste(ed):
    a = line((0, 0), (50, 0))
    ed.add_items([a])
    ed.sel.set([a])
    ed.copy()
    ed.paste()
    assert len(ed.doc.items()) == 2
    b = [i for i in ed.doc.items() if i is not a][0]
    assert b.uid != a.uid and b.pos() == a.pos() + QPointF(20, 20)


def test_color_nondestructive(ed):
    from annotator import imageops
    before = ed.doc.background.pixel(5, 5)
    old = dict(ed.doc.color)
    new = dict(old, brightness=50)
    ed.doc.set_color(new)
    ed.set_background_color(old, new)
    assert ed.doc.background.pixel(5, 5) == before
    assert ed.doc.display_image.pixel(5, 5) != before
    ed.undo.undo()
    ed.doc._update_display_now()
    assert ed.doc.display_image.pixel(5, 5) == before
    ed.undo.redo()
    ed.reset_background_color()
    ed.doc._update_display_now()
    assert ed.doc.color == imageops.DEFAULT_COLOR

def test_style_scale_with_image_size(ed):
    from annotator import styles
    img = QImage(4000, 3000, QImage.Format_ARGB32_Premultiplied)
    ed.new_from_image(img)
    assert styles.scale() == 2.5
    assert ArrowItem().props["width"] == 17.5


def test_curves_lut_and_saturation_zero_is_gray(ed):
    from annotator import imageops
    lut = imageops.curve_lut([[0, 0], [255, 255]])
    assert list(lut[:5]) == [0, 1, 2, 3, 4]
    lut = imageops.curve_lut([[0, 0], [128, 200], [255, 255]])
    assert lut[128] == 200 and all(lut[i] <= lut[i + 1] for i in range(255))
    img = QImage(4, 4, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(200, 50, 30))
    out = imageops.apply_adjustments(img, [{"kind": "hs", "visible": True, "params": {"saturation": 0, "temperature": 0}}])
    c = QColor(out.pixel(1, 1))
    assert c.red() == c.green() == c.blue()


def test_old_project_color_migrates():
    from annotator import imageops
    v1 = imageops.migrate_color({"adjust": {"brightness": 10, "contrast": 0, "saturation": 0, "temperature": 0,
                                            "gray": True}})
    assert v1["brightness"] == 10 and v1["saturation"] == 0
    v2 = imageops.migrate_color({"adjustments": [
        {"kind": "curves", "visible": True, "params": {"rgb": [[0, 0], [128, 200], [255, 255]]}},
        {"kind": "hs", "visible": True, "params": {"saturation": 40, "temperature": 5}}]})
    assert v2["saturation"] == 40 and v2["curves"]["rgb"][1] == [128, 200]

def test_crop_canvas_expand_and_shrink(ed):
    a = line((10, 10), (20, 20))
    ed.add_items([a])
    ed.crop_canvas_to(QRectF(-50, -20, 950, 640))
    assert ed.doc.background.width() == 950 and ed.doc.background.height() == 640
    assert a.pos() == QPointF(60, 30)
    ed.crop_canvas_to(QRectF(100, 100, 200, 100))
    assert ed.doc.background.width() == 200
    ed.undo.undo()
    ed.undo.undo()
    assert ed.doc.background.width() == 800 and a.pos() == QPointF(10, 10)


def test_image_item_crop_and_adjust(ed):
    from annotator.items import ImageItem
    img = QImage(100, 50, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(200, 0, 0))
    it = ImageItem(img)
    it.setPos(10, 10)
    ed.add_items([it])
    ed.crop_image_item(it, QRectF(30, 20, 40, 20))
    assert it.rect.width() == 40 and it.src == QRectF(20, 10, 40, 20) and it.pos() == QPointF(30, 20)
    ed.sel.set([it])
    ed.set_prop("saturation", 0)
    pm = it.pixmap().toImage()
    c = QColor(pm.pixel(5, 5))
    assert c.red() == c.green() == c.blue()
    ed.undo.undo()
    ed.undo.undo()
    assert it.rect.width() == 100


def test_polyline_vertices(ed):
    from annotator.items import PolylineItem
    pl = PolylineItem()
    pl.set_scene_points([QPointF(0, 0), QPointF(100, 0), QPointF(100, 100)])
    ed.add_items([pl])
    kinds = pl.handle_kinds()
    assert kinds.count("vertex") == 3 and kinds.count("insert") == 2
    new = pl.begin_handle_drag(3)  # «+» на первом сегменте
    assert new == 1 and len(pl.points) == 4 and pl.points[1] == QPointF(50, 0)
    ed.delete_vertex(pl, 1)
    assert len(pl.points) == 3
    ed.delete_vertex(pl, 0)
    ed.delete_vertex(pl, 0)
    assert len(pl.points) == 2  # минимум


def test_rect_rotation_roundtrip(ed, tmp_path):
    r = RectItem()
    r.set_drag(QPointF(100, 100), QPointF(300, 200))
    ed.add_items([r])
    ed.sel.set([r])
    ed.set_prop("angle", 30.0)
    c = r.mapToScene(r.rect.center())
    assert abs(c.x() - 200) < 1e-6 and abs(c.y() - 150) < 1e-6
    corners = [r.mapToScene(p) for p in (r.rect.topLeft(), r.rect.bottomRight())]
    path = str(tmp_path / "r.iap")
    ed.save_project(path)
    e2 = Editor()
    e2.open_project(path)
    r2 = e2.doc.items()[0]
    c2 = [r2.mapToScene(p) for p in (r2.rect.topLeft(), r2.rect.bottomRight())]
    for p, q in zip(corners, c2):
        assert abs(p.x() - q.x()) < 1e-6 and abs(p.y() - q.y()) < 1e-6
    # ресайз повёрнутого прямоугольника: противоположный угол остаётся на месте
    fixed = r.mapToScene(r.rect.topLeft())
    r.begin_handle_drag(4)
    r.move_handle(4, r.rect.bottomRight() + QPointF(50, 20))
    fixed2 = r.mapToScene(r.rect.topLeft())
    assert abs(fixed.x() - fixed2.x()) < 1e-6 and abs(fixed.y() - fixed2.y()) < 1e-6


def test_ellipse_from_center_and_symmetric(ed):
    from annotator.items import EllipseItem
    e = EllipseItem()
    e.set_drag(QPointF(200, 200), QPointF(250, 230))
    c = e.mapToScene(e.rect.center())
    assert c == QPointF(200, 200) and e.rect.width() == 100 and e.rect.height() == 60
    e.begin_handle_drag(3)  # правая сторона, Alt — симметрично
    e.move_handle(3, QPointF(e.rect.right() + 20, e.rect.center().y()), symmetric=True)
    assert e.rect.width() == 140 and e.mapToScene(e.rect.center()) == QPointF(200, 200)


def test_group_remove_member(ed):
    a, b, c = line((0, 0), (1, 1)), line((5, 5), (6, 6)), line((9, 9), (8, 8))
    ed.add_items([a, b, c])
    ed.sel.set([a, b, c])
    ed.group()
    ed.remove_from_groups([a])
    assert a.group_id is None and b.group_id and b.group_id == c.group_id
    ed.remove_from_groups([b])
    assert c.group_id is None  # группа из одного объекта распущена


def test_blur_region(ed):
    from PySide6.QtCore import QRect
    img = QImage(100, 100, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0))
    from PySide6.QtGui import QPainter
    p = QPainter(img)
    p.fillRect(50, 0, 50, 100, QColor(255, 255, 255))
    p.end()
    ed.new_from_image(img)
    ed.set_raster_selection(QRect(30, 30, 40, 40))
    ed.raster_blur(4)
    v = QColor(ed.doc.background.pixel(50, 50)).red()
    assert 60 < v < 200
    assert QColor(ed.doc.background.pixel(10, 10)).red() == 0


def test_dimension_and_break(ed, tmp_path):
    from annotator.items import BreakItem, DimensionItem
    d = DimensionItem()
    d.set_drag(QPointF(100, 100), QPointF(300, 100))
    br = BreakItem()
    br.set_drag(QPointF(50, 50), QPointF(50, 90))
    ed.add_items([d, br])
    assert d.value_text() == "200 мм" and d.t == 0.5
    d.move_handle(2, QPointF(50, -40))  # локальные координаты
    assert abs(d.t - 0.25) < 1e-6 and abs(abs(d.offset) - 40) < 1e-6
    br.move_handle(2, QPointF(30, 20))
    assert abs(br.props["gap"] - 60) < 1e-6
    ed.sel.set([d])
    ed.set_prop("arrows", "in")
    path = str(tmp_path / "d.iap")
    ed.save_project(path)
    e2 = Editor()
    e2.open_project(path)
    d2 = [i for i in e2.doc.items() if i.TYPE == "dimension"][0]
    assert d2.props["arrows"] == "in" and abs(d2.t - 0.25) < 1e-6


def test_line_bend(ed):
    ln = line((0, 0), (100, 0))
    ed.add_items([ln])
    assert ln.handle_kinds() == ["vertex", "vertex", "bend"]
    ln.move_handle(2, QPointF(50, -40))
    assert ln.ctrl is not None and abs(ln.curve_mid().y() + 40) < 1e-6
    ed.straighten(ln)
    assert ln.ctrl is None


def test_dimension_label_far(ed):
    from annotator.items import DimensionItem
    d = DimensionItem()
    d.set_drag(QPointF(0, 0), QPointF(10, 0))
    d.move_handle(2, QPointF(300, -20))
    assert abs(d.t - 30) < 1e-6 and d.label_point().x() == 300


def test_text_rotation_border_roundtrip(ed, tmp_path):
    t = TextItem({"text": "REMOVE", "border": True})
    t.setPos(100, 100)
    ed.add_items([t])
    c0 = t.mapToScene(t.box().center())
    ed.sel.set([t])
    ed.set_prop("angle", 90.0)
    c1 = t.mapToScene(t.box().center())
    assert abs(c0.x() - c1.x()) < 1e-6 and abs(c0.y() - c1.y()) < 1e-6
    assert t.handle_kinds() == ["box"] * 8 + ["rot"]
    corner = t.mapToScene(t.box().topLeft())
    path = str(tmp_path / "t.iap")
    ed.save_project(path)
    e2 = Editor()
    e2.open_project(path)
    t2 = e2.doc.items()[0]
    c2 = t2.mapToScene(t2.box().topLeft())
    assert abs(c2.x() - corner.x()) < 1e-6 and abs(c2.y() - corner.y()) < 1e-6
    assert t2.props["border"] is True and t2.rotation() == 90


def test_text_free_box_and_align(ed):
    t = TextItem({"text": "REMOVE"})
    t.setPos(100, 100)
    ed.add_items([t])
    assert t.props["align"] == "center" and t.props["valign"] == "middle"
    tl = t.mapToScene(t.box().topLeft())
    t.begin_handle_drag(4)  # правый нижний угол
    t.move_handle(4, QPointF(300, 150))
    assert t.props["auto_size"] is False and t.box().width() == 300 and t.box().height() == 150
    tl2 = t.mapToScene(t.box().topLeft())
    assert abs(tl.x() - tl2.x()) < 1e-6 and abs(tl.y() - tl2.y()) < 1e-6
    # левая сторона: правая остаётся на месте
    right = t.mapToScene(t.box().topRight())
    t.begin_handle_drag(7)
    t.move_handle(7, QPointF(-50, 75))
    assert t.box().width() == 350
    r2 = t.mapToScene(t.box().topRight())
    assert abs(right.x() - r2.x()) < 1e-6
    t.set_prop("auto_size", True)
    assert t.box().width() < 200


def _drag_handle(item, idx, start_scene, end_scene, steps=12, alt=False):
    """Имитация перетаскивания ручки мышью: на каждом шаге точка мыши переводится
    в ТЕКУЩИЕ локальные координаты объекта (как делает SelectTool)."""
    item.begin_handle_drag(idx)
    for k in range(1, steps + 1):
        sp = start_scene + (end_scene - start_scene) * (k / steps)
        item.move_handle(idx, item.mapFromScene(sp), symmetric=alt)


def test_text_resize_all_handles_follow_mouse(ed):
    for angle in (0.0, 30.0):
        for idx in range(8):
            t = TextItem({"text": "REMOVE"})
            t.setPos(200, 200)
            ed.add_items([t])
            t.begin_handle_drag(4)
            t.move_handle(4, QPointF(200, 100))
            t.set_prop("angle", angle)
            h0 = t.mapToScene(t.handles()[idx])
            d = QPointF(37, 23)
            _drag_handle(t, idx, h0, h0 + d)
            h1 = t.mapToScene(t.handles()[idx])
            # ручка должна оказаться там же, где мышь (по осям, которые она двигает)
            hid = t.HANDLE_IDS[idx]
            moved = h1 - h0
            # проверка в системе координат объекта
            import math
            a = math.radians(angle)
            ux, uy = math.cos(a), math.sin(a)
            dl = (d.x() * ux + d.y() * uy, -d.x() * uy + d.y() * ux)
            ml = (moved.x() * ux + moved.y() * uy, -moved.x() * uy + moved.y() * ux)
            if "l" in hid or "r" in hid:
                assert abs(ml[0] - dl[0]) < 0.05, (angle, hid, ml, dl)
            if "t" in hid or "b" in hid:
                assert abs(ml[1] - dl[1]) < 0.05, (angle, hid, ml, dl)


def test_rotated_rect_resize_all_handles_follow_mouse(ed):
    import math
    for idx in range(8):
        r = RectItem()
        r.set_drag(QPointF(100, 100), QPointF(300, 220))
        ed.add_items([r])
        ed.sel.set([r])
        ed.set_prop("angle", 25.0)
        h0 = r.mapToScene(r.handles()[idx])
        d = QPointF(-31, 17)
        _drag_handle(r, idx, h0, h0 + d)
        h1 = r.mapToScene(r.handles()[idx])
        a = math.radians(25.0)
        ux, uy = math.cos(a), math.sin(a)
        dl = (d.x() * ux + d.y() * uy, -d.x() * uy + d.y() * ux)
        mv = h1 - h0
        ml = (mv.x() * ux + mv.y() * uy, -mv.x() * uy + mv.y() * ux)
        hid = r.HANDLE_IDS[idx]
        if "l" in hid or "r" in hid:
            assert abs(ml[0] - dl[0]) < 0.05, (hid, ml, dl)
        if "t" in hid or "b" in hid:
            assert abs(ml[1] - dl[1]) < 0.05, (hid, ml, dl)
