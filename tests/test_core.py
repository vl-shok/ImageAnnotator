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
from annotator.items import ArrowItem, CalloutItem, EllipseItem, LineItem, NumberItem, RectItem, TextItem  # noqa: E402
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


def test_magnifier(ed, tmp_path):
    from annotator.items import MagnifierItem
    from annotator.export import render_image
    from PySide6.QtGui import QPainter
    img = QImage(800, 600, QImage.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    p.fillRect(100, 100, 20, 20, QColor(255, 0, 0))
    p.end()
    ed.new_from_image(img)
    m = MagnifierItem()
    m.set_drag(QPointF(100, 100), QPointF(120, 120))
    ed.add_items([m])
    d = m.dst_rect().translated(m.pos())
    assert d.width() == 50 and d.left() > 120          # ×2.5, справа от области
    assert len(m.connector_lines()) == 2
    out = render_image(ed.doc)
    c = QColor(out.pixel(int(d.center().x()), int(d.center().y())))
    assert c.red() > 200 and c.green() < 60               # в виде — увеличенный красный квадрат
    m.begin_handle_drag(5)
    m.move_handle(5, m.dst_rect().center() + QPointF(0, 100))
    assert abs(m.dst_rect().translated(m.pos()).top() - d.top() - 100) < 1e-6
    ed.sel.set([m])
    ed.set_prop("shape", "circle")
    assert len(m.connector_lines()) == 2
    path = str(tmp_path / "m.iap")
    ed.save_project(path)
    e2 = Editor()
    e2.open_project(path)
    m2 = e2.doc.items()[0]
    assert m2.TYPE == "magnifier" and m2.dst_rect() == m.dst_rect()


def test_magnifier_center_handle_follows_mouse(ed):
    from annotator.items import MagnifierItem
    m = MagnifierItem()
    m.set_drag(QPointF(100, 100), QPointF(140, 130))
    ed.add_items([m])
    c0 = m.mapToScene(m.handles()[4])
    _drag_handle(m, 4, c0, c0 + QPointF(60, -25), steps=15)
    c1 = m.mapToScene(m.handles()[4])
    assert abs(c1.x() - c0.x() - 60) < 1e-6 and abs(c1.y() - c0.y() + 25) < 1e-6
    for idx in range(4):
        h0 = m.mapToScene(m.handles()[idx])
        _drag_handle(m, idx, h0, h0 + QPointF(7, 5), steps=10)
        h1 = m.mapToScene(m.handles()[idx])
        assert abs(h1.x() - h0.x() - 7) < 1e-6 and abs(h1.y() - h0.y() - 5) < 1e-6


def test_space_rotation_45(ed):
    import math
    from annotator.items.dimension import DimensionItem
    # линия: поворот вокруг своего центра, по часовой (+45) и обратно
    a = line((100, 100), (200, 100))
    ed.add_items([a])
    ed.sel.set([a])
    ed.rotate_selected(45)
    p0, p1 = a.scene_points()
    assert math.isclose(p0.x() + p1.x(), 300, abs_tol=1e-6) and math.isclose(p0.y() + p1.y(), 200, abs_tol=1e-6)
    assert p1.y() > p0.y()          # по часовой на экране: правый конец ушёл вниз
    ed.rotate_selected(-45)
    p0, p1 = a.scene_points()
    assert math.isclose(p0.x(), 100, abs_tol=1e-6) and math.isclose(p1.y(), 100, abs_tol=1e-6)
    ed.undo.undo()
    ed.undo.undo()
    # прямоугольник и текст: меняется свойство angle, центр на месте
    r = RectItem()
    r.set_drag(QPointF(10, 10), QPointF(110, 60))
    t = TextItem(); t.setPos(300, 300)
    ed.add_items([r]); ed.add_items([t])
    for it in (r, t):
        ed.sel.set([it])
        c = it.content_rect().center()
        for _ in range(5):
            ed.rotate_selected(45)
        assert it.props["angle"] == -135
        assert math.isclose(it.content_rect().center().x(), c.x(), abs_tol=1e-3)
    # размер
    d = DimensionItem()
    d.set_drag(QPointF(0, 0), QPointF(100, 0))
    ed.add_items([d]); ed.sel.set([d])
    ed.rotate_selected(-90)
    sa, sb = d.mapToScene(d.a), d.mapToScene(d.b)
    assert math.isclose(sa.x(), sb.x(), abs_tol=1e-6)



def test_break_gap_mark():
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QGraphicsScene
    from annotator.items.shapes import BreakItem
    for kind, _ in BreakItem.MARKS:
        sc = QGraphicsScene()
        b = BreakItem(props={"mark": kind, "gap": 40, "width": 6, "mark_alpha": 1.0})
        b.set_drag(QPointF(100, 20), QPointF(100, 180))
        sc.addItem(b)
        img = QImage(200, 200, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(255, 255, 255))
        p = QPainter(img)
        sc.render(p, QRectF(0, 0, 200, 200), QRectF(0, 0, 200, 200))
        p.end()
        inside = [QColor(img.pixel(x, y)) for x in range(86, 115) for y in range(60, 140)]
        tinted = sum(1 for c in inside if c.green() < 240)
        edge = QColor(img.pixel(100, 25))       # выступ черт — без подсветки
        assert edge.green() > 240
        assert (tinted > 0) == (kind != "none")


def _pasted(ed, color=QColor(200, 30, 30), w=100, h=50):
    from annotator.items import ImageItem
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(color)
    it = ImageItem(img)
    it.setPos(100, 100)
    ed.add_items([it])
    ed.set_active_layer(it.layer_id)
    return it


def test_image_free_stretch_and_rotate(ed):
    it = _pasted(ed)
    assert len(it.handles()) == 9          # 8 ручек рамки + поворот
    # сторона — свободное растяжение
    it.begin_handle_drag(3)
    it.move_handle(3, QPointF(200, 50))
    assert abs(it.rect.width() - 200) < 1e-6 and abs(it.rect.height() - 50) < 1e-6
    # угол — с пропорциями, Shift — свободно
    it.begin_handle_drag(4)
    it.move_handle(4, QPointF(400, 60))
    assert abs(it.rect.width() / it.rect.height() - 4.0) < 1e-6
    it.begin_handle_drag(4)
    it.move_handle(4, QPointF(300, 200), constrain=True)
    assert abs(it.rect.width() - 300) < 1e-6 and abs(it.rect.height() - 200) < 1e-6
    # поворот пробелом
    ed.sel.set([it])
    c = it.content_rect().center()
    ed.rotate_selected(45)
    assert it.props["angle"] == 45 and abs(it.content_rect().center().x() - c.x()) < 1e-3


def test_raster_ops_on_pasted_image(ed):
    from PySide6.QtCore import QRect
    it = _pasted(ed)
    ed.raster_sel = None
    ed.set_raster_selection(QRect(110, 110, 20, 20))
    t = ed.raster_target()
    assert t is not None and t[0] is it
    img = ed.raster_copy_image()
    assert img.width() == 20 and QColor(img.pixel(5, 5)).red() == 200
    ed.raster_fill(QColor(0, 0, 255))
    assert QColor(it.image.pixel(15, 15)).blue() == 255
    ed.undo.undo()
    assert QColor(it.image.pixel(15, 15)).red() == 200
    ed.raster_delete()
    assert QColor.fromRgba(it.image.pixel(15, 15)).alpha() == 0
    ed.raster_blur(3.0)
    # активный «Фон» — область берётся с фото
    ed.set_active_layer("bg")
    assert ed.raster_target()[0] is None


def test_callout_multiple_leaders(ed):
    c = CalloutItem({"text": "Общий комментарий"})
    c.setPos(200, 200)
    c.tip = QPointF(-50, 80)
    ed.add_items([c])
    # начало стрелки — по рамке
    b = c.box()
    idx_anchor = 1
    c.move_handle(idx_anchor, QPointF(b.right() + 30, b.top() + b.height() * 0.25))
    assert c.leaders[0][1][0] == 1.0
    ed.add_callout_leader(c, QPointF(500, 400))
    assert len(c.leaders) == 2 and len(c.handles()) == 15   # 2×(острие, начало) + 2 изгиба + 8 рамки + блок
    assert abs(c.mapToScene(c.leaders[1][0]).x() - 500) < 1e-6
    d = c.to_dict(full=True)
    c2 = CalloutItem()
    c2.apply_dict(d)
    assert len(c2.leaders) == 2 and c2.leaders[0][1] == c.leaders[0][1]
    # перемещение блока не двигает острия
    c.move_handle(14, QPointF(10, 10))
    assert abs(c.mapToScene(c.leaders[1][0]).x() - 500) < 1e-6
    ed.remove_callout_leader(c, 1)
    assert len(c.leaders) == 1
    ed.remove_callout_leader(c, 0)            # последний не удаляется
    assert len(c.leaders) == 1
    ed.undo.undo()
    assert len(c.leaders) == 2
    # старый формат (одна точка tip)
    c3 = CalloutItem()
    c3.geom_from_dict({"tip": [5, 6]})
    assert len(c3.leaders) == 1 and c3.tip == QPointF(5, 6)


def test_new_items_on_top(ed):
    a = line((0, 0), (100, 0))
    b = line((0, 10), (100, 10))
    ed.add_items([a])
    ed.add_items([b])
    c = line((0, 20), (100, 20))
    c.layer_id = a.layer_id          # как делают инструменты рисования
    ed.add_items([c])
    assert a.zValue() < b.zValue() < c.zValue()


def test_callout_ctrl_drag_new_leader(ed):
    from PySide6.QtCore import Qt
    from annotator.canvas import CanvasView
    from annotator.tools.base import ToolEvent
    from annotator.tools.draw_tools import make_tools
    view = CanvasView(ed)  # noqa: F841
    for tl in make_tools(ed):
        ed.register_tool(tl)
    ed.set_tool("select")
    c = CalloutItem({"text": "Комментарий"})
    c.setPos(200, 200)
    ed.add_items([c])
    b = c.mapToScene(c.box()).boundingRect()
    start = QPointF(b.right(), b.center().y())
    t = ed.tool
    t.press(ToolEvent(start, None, Qt.ControlModifier, Qt.LeftButton, Qt.LeftButton))
    t.move(ToolEvent(QPointF(600, 500), None, Qt.ControlModifier, Qt.NoButton, Qt.LeftButton))
    t.release(ToolEvent(QPointF(600, 500), None, Qt.ControlModifier, Qt.LeftButton, Qt.NoButton))
    assert len(c.leaders) == 2
    tip = c.mapToScene(c.leaders[1][0])
    assert abs(tip.x() - 600) < 1 and abs(tip.y() - 500) < 1
    assert c.leaders[1][1][0] == 1.0          # начало — на правой грани
    assert ed.undo.undoText() == "Добавить стрелку"
    # маркер в центре блока двигает только блок
    hs = c.handles()
    assert c.handle_kinds()[-1] == "move" and hs[-1] == c.box().center()
    c.move_handle(len(hs) - 1, c.box().center() + QPointF(30, 0))
    assert abs(c.mapToScene(c.leaders[1][0]).x() - 600) < 1e-6


def test_callout_anchor_snaps_and_edit_in_callout_tool(ed):
    from PySide6.QtCore import Qt
    from annotator.canvas import CanvasView
    from annotator.tools.base import ToolEvent
    from annotator.tools.draw_tools import make_tools
    view = CanvasView(ed)  # noqa: F841
    for tl in make_tools(ed):
        ed.register_tool(tl)
    c = CalloutItem({"text": "Комментарий"})
    c.setPos(200, 200)
    c.tip = QPointF(-100, 150)
    ed.add_items([c])
    ed.sel.set([c])
    ed.set_tool("callout")
    t = ed.tool
    b = c.box()
    anchor = c.mapToScene(c.handles()[1])
    # тянем ромб к почти-углу блока — должен прилипнуть ровно к углу
    near_corner = c.mapToScene(QPointF(b.right() - 2, b.bottom() + 1))
    t.press(ToolEvent(anchor, None, Qt.NoModifier, Qt.LeftButton, Qt.LeftButton))
    t.move(ToolEvent(near_corner, None, Qt.NoModifier, Qt.NoButton, Qt.LeftButton))
    t.release(ToolEvent(near_corner, None, Qt.NoModifier, Qt.LeftButton, Qt.NoButton))
    assert c.leaders[0][1] == (1.0, 1.0)
    assert len(ed.doc.items()) == 1          # новая выноска не создалась
    assert ed.tool.name == "callout"


def test_callout_tool_box_first_then_tip(ed):
    from PySide6.QtCore import Qt
    from annotator.canvas import CanvasView
    from annotator.tools.base import ToolEvent
    from annotator.tools.draw_tools import make_tools
    view = CanvasView(ed)  # noqa: F841
    for tl in make_tools(ed):
        ed.register_tool(tl)
    ed.ask_text = lambda initial, title="": "Проверить пайку"
    ed.set_tool("callout")
    t = ed.tool
    box_at, tip_at = QPointF(500, 150), QPointF(250, 420)
    t.press(ToolEvent(box_at, None, Qt.NoModifier, Qt.LeftButton, Qt.LeftButton))
    t.move(ToolEvent(tip_at, None, Qt.NoModifier, Qt.NoButton, Qt.LeftButton))
    t.release(ToolEvent(tip_at, None, Qt.NoModifier, Qt.LeftButton, Qt.NoButton))
    c = [i for i in ed.doc.items() if i.TYPE == "callout"][0]
    center = c.mapToScene(c.box().center())
    tip = c.mapToScene(c.tip)
    assert abs(center.x() - 500) < 1e-6 and abs(center.y() - 150) < 1e-6
    assert abs(tip.x() - 250) < 1e-6 and abs(tip.y() - 420) < 1e-6


def test_callout_leader_bend(ed):
    c = CalloutItem({"text": "Комментарий"})
    c.setPos(200, 200)
    c.tip = QPointF(-100, 150)
    ed.add_items([c])
    n = len(c.leaders)
    assert c.handle_kinds()[2 * n] == "bend"
    a, t = c.start_point(0), c.tip
    m = QPointF((a.x() + t.x()) / 2 + 30, (a.y() + t.y()) / 2 - 20)
    c.move_handle(2 * n, m)
    assert c.is_bent()
    assert abs(c.bend_mid(0).x() - m.x()) < 1e-6 and abs(c.bend_mid(0).y() - m.y()) < 1e-6
    # дуга проходит через ручку
    from annotator.items.base import quad_point
    q = quad_point(a, c.leader_ctrl(0), t, 0.5)
    assert abs(q.x() - m.x()) < 1e-6 and abs(q.y() - m.y()) < 1e-6
    # сохранение / загрузка
    c2 = CalloutItem()
    c2.apply_dict(c.to_dict(full=True))
    assert all(abs(x - y) < 1e-5 for b1, b2 in zip(c2.bends, c.bends) for x, y in zip(b1, b2))
    # изгиб следует за острием (хранится относительно указателя)
    c.tip = QPointF(-200, 300)
    assert c.is_bent()
    ed.straighten(c, 2 * n)
    assert not c.is_bent()
    ed.undo.undo()
    assert c.is_bent()
    # острие внутри блока — линии нет, ручка изгиба скрыта
    c.tip = c.box().center()
    assert c.handle_kinds()[2 * n] == "hidden"


def _tools_view(ed):
    from annotator.canvas import CanvasView
    from annotator.tools.draw_tools import make_tools
    view = CanvasView(ed)
    for tl in make_tools(ed):
        ed.register_tool(tl)
    return view


def _drag(t, a, b, mods=None):
    from PySide6.QtCore import Qt
    from annotator.tools.base import ToolEvent
    m = Qt.NoModifier if mods is None else mods
    t.press(ToolEvent(a, None, m, Qt.LeftButton, Qt.LeftButton))
    t.move(ToolEvent((a + b) / 2, None, m, Qt.NoButton, Qt.LeftButton))
    t.move(ToolEvent(b, None, m, Qt.NoButton, Qt.LeftButton))
    t.release(ToolEvent(b, None, m, Qt.LeftButton, Qt.NoButton))


def test_glued_line_follows_target(ed):
    _tools_view(ed)
    r = RectItem()
    r.set_drag(QPointF(100, 100), QPointF(200, 160))
    ed.add_items([r])
    corner = QPointF(200, 160)
    # рисуем линию от угла прямоугольника — начало приклеивается
    ed.set_tool("line")
    _drag(ed.tool, QPointF(201, 161), QPointF(400, 300))
    ln = [i for i in ed.doc.items() if i.TYPE == "line"][0]
    assert ln.mapToScene(ln.points[0]) == corner
    assert "s" in ln.glue and "e" not in ln.glue
    end_before = ln.mapToScene(ln.points[-1])
    # тащим прямоугольник — начало линии едет следом, конец на месте
    ed.set_tool("select")
    ed.sel.set([r])
    _drag(ed.tool, QPointF(130, 100), QPointF(160, 140))   # за контур (прямоугольник без заливки)
    assert ln.mapToScene(ln.points[0]) == corner + QPointF(30, 40)
    assert ln.mapToScene(ln.points[-1]) == end_before
    # растягивание прямоугольника за ручку — линия остаётся на своём углу
    ed.sel.set([r])
    _drag(ed.tool, QPointF(230, 200), QPointF(260, 220))     # правый нижний угол
    assert ln.mapToScene(ln.points[0]) == QPointF(260, 220)
    ed.undo.undo()
    # отмена — одним шагом возвращает и прямоугольник, и линию
    ed.undo.undo()
    assert ln.mapToScene(ln.points[0]) == corner
    # сдвиг стрелками и поворот цели тоже тянут линию
    ed.sel.set([r])
    ed.nudge(5, 0)
    assert ln.mapToScene(ln.points[0]) == corner + QPointF(5, 0)


def test_glued_handle_drag_moves_only_line(ed):
    _tools_view(ed)
    r = RectItem()
    r.set_drag(QPointF(100, 100), QPointF(200, 160))
    ed.add_items([r])
    ed.set_tool("arrow")
    _drag(ed.tool, QPointF(400, 300), QPointF(199, 159))
    ar = [i for i in ed.doc.items() if i.TYPE == "arrow"][0]
    assert "e" in ar.glue
    # тянем ручку конца стрелки в пустое место — двигается только стрелка, конец отклеивается
    ed.set_tool("select")
    ed.sel.set([ar])
    rect_state = r.state()
    tip = ar.mapToScene(ar.points[-1])
    _drag(ed.tool, tip, QPointF(600, 500))
    assert r.state() == rect_state
    assert "e" not in ar.glue
    # перетаскивание ручки на угол прямоугольника — снова приклеивается
    _drag(ed.tool, QPointF(600, 500), QPointF(101, 101))
    assert "e" in ar.glue
    ed.sel.set([r])
    ed.nudge(0, 10)
    assert ar.mapToScene(ar.points[-1]) == QPointF(100, 110)


def test_moving_line_alone_unglues(ed):
    _tools_view(ed)
    r = RectItem()
    r.set_drag(QPointF(100, 100), QPointF(200, 160))
    ed.add_items([r])
    ed.set_tool("line")
    _drag(ed.tool, QPointF(200, 160), QPointF(400, 300))
    ln = [i for i in ed.doc.items() if i.TYPE == "line"][0]
    assert ln.glue
    ed.sel.set([ln])
    ed.nudge(10, 0)
    assert not ln.glue
    ed.undo.undo()
    assert ln.glue
    # вместе с целью — остаётся приклеенной
    ed.sel.set([ln, r])
    ed.nudge(10, 0)
    assert ln.glue
    # копия линии без цели не приклеена, копия вместе с целью — приклеена к копии цели
    ed.sel.set([ln])
    ed.duplicate()
    assert not ed.sel.items[0].glue
    ed.sel.set([ln, r])
    ed.duplicate()
    new_ln = [i for i in ed.sel.items if i.TYPE == "line"][0]
    new_r = [i for i in ed.sel.items if i.TYPE == "rect"][0]
    assert new_ln.glue["s"]["uid"] == new_r.uid


def test_glued_callout_tip_and_chain(ed):
    _tools_view(ed)
    r = RectItem()
    r.set_drag(QPointF(100, 100), QPointF(200, 160))
    ed.add_items([r])
    # линия от угла прямоугольника, вторая линия — от конца первой (цепочка)
    ed.set_tool("line")
    _drag(ed.tool, QPointF(200, 160), QPointF(400, 300))
    _drag(ed.tool, QPointF(400, 300), QPointF(500, 100))
    l1, l2 = [i for i in ed.doc.items_sorted() if i.TYPE == "line"]
    assert l2.glue["s"]["uid"] == l1.uid
    ed.sel.set([r])
    ed.nudge(0, 20)
    # первая линия тянется за прямоугольником, её конец не двигается — вторая на месте
    assert l1.mapToScene(l1.points[0]) == QPointF(200, 180)
    assert l2.mapToScene(l2.points[0]) == QPointF(400, 300)
    # двигаем первую линию целиком — она отклеивается, вторая едет следом
    ed.sel.set([l1])
    ed.nudge(10, 0)
    assert l2.mapToScene(l2.points[0]) == QPointF(410, 300)
    # острие выноски, приклеенное к прямоугольнику
    c = CalloutItem({"text": "К"})
    c.setPos(400, 400)
    ed.add_items([c])
    ed.sel.set([c])
    ed.set_tool("select")
    tip = c.mapToScene(c.tip)
    _drag(ed.tool, tip, QPointF(101, 181))
    assert "t0" in c.glue
    ed.sel.set([r])
    ed.nudge(5, 0)
    assert c.mapToScene(c.tip) == QPointF(105, 180)


def test_guides_find_alignment(ed):
    sn = ed.snap
    a = line((100, 100), (200, 100))
    ed.add_items([a])
    tol = 6
    # точка почти на вертикали конца линии — выравнивается по x
    r = sn.find_guides(ed.doc, QPointF(202, 300), tol)
    assert r is not None and r[0] == QPointF(200, 300)
    assert QPointF(200, 100) in [g[0] for g in r[1]]   # направляющая идёт от конца линии
    # от опорной точки — под 45°
    r = sn.find_guides(ed.doc, QPointF(503, 498), tol, anchor=QPointF(400, 400))
    assert abs(r[0].x() - r[0].y()) < 1e-6
    # 45° от опорной точки и горизонталь конца линии — пересечение
    r = sn.find_guides(ed.doc, QPointF(302, 103), tol, anchor=QPointF(500, 300))
    assert abs(r[0].y() - 100) < 1e-6 and abs(r[0].x() - 300) < 1e-6 and len(r[1]) == 2
    # горизонталь с серединой линии
    r = sn.find_guides(ed.doc, QPointF(150 + 300, 104), tol)
    assert r[0].y() == 100
    # далеко от всех — нет
    assert sn.find_guides(ed.doc, QPointF(333, 277), tol) is None
    sn.guides = False
    assert sn.find_guides(ed.doc, QPointF(202, 300), tol) is None


def test_guides_when_drawing_and_moving(ed):
    from PySide6.QtCore import Qt
    from annotator.tools.base import ToolEvent
    _tools_view(ed)
    a = line((100, 100), (200, 100))
    ed.add_items([a])
    # рисуем линию: конец ставится на одну вертикаль с концом первой линии
    ed.set_tool("line")
    _drag(ed.tool, QPointF(400, 400), QPointF(203, 350))
    b = [i for i in ed.doc.items_sorted() if i.TYPE == "line"][-1]
    assert b.mapToScene(b.points[-1]).x() == 200
    # перемещаем текст: его верх встаёт на горизонталь линии
    t = TextItem({"text": "Метка", "bg": True})
    t.setPos(500, 300)
    ed.add_items([t])
    ed.set_tool("select")
    ed.sel.set([t])
    tr = t.content_rect()
    grab = tr.center()
    target = grab + QPointF(-20, 100 - tr.top() + 3)    # верх текста на 3 px ниже y=100
    _drag(ed.tool, grab, target)
    assert abs(t.content_rect().top() - 100) < 1e-6
    # полилиния: сегмент под 45° от предыдущей вершины
    ed.set_tool("polyline")
    tl = ed.tool
    for p in (QPointF(600, 500), QPointF(700, 403)):
        tl.press(ToolEvent(p, None, Qt.NoModifier, Qt.LeftButton, Qt.LeftButton))
        tl.release(ToolEvent(p, None, Qt.NoModifier, Qt.LeftButton, Qt.NoButton))
    tl.finish()
    pl = [i for i in ed.doc.items() if i.TYPE == "polyline"][0]
    p0, p1 = pl.scene_points()
    assert abs((p1.x() - p0.x()) + (p1.y() - p0.y())) < 1e-6


def _canvas_scene(ed):
    from annotator.items import DimensionItem, MagnifierItem
    ed.doc.background.setPixelColor(10, 20, QColor(255, 0, 0))
    ln = line((10, 20), (100, 20))
    ar = ArrowItem()
    ar.set_drag(QPointF(300, 300), QPointF(400, 350))
    rc = RectItem()
    rc.set_drag(QPointF(500, 100), QPointF(600, 160))
    tx = TextItem({"text": "Надпись"})
    tx.setPos(200, 400)
    co = CalloutItem({"text": "К"})
    co.setPos(600, 400)
    co.tip = QPointF(-100, 100)
    nm = NumberItem({"leader": True})
    nm.setPos(50, 500)
    nm.tip = QPointF(40, -60)
    dm = DimensionItem()
    dm.set_drag(QPointF(100, 200), QPointF(250, 200))
    mg = MagnifierItem()
    mg.set_drag(QPointF(400, 450), QPointF(440, 480))
    items = [ln, ar, rc, tx, co, nm, dm, mg]
    ed.add_items(items)
    return items


def _snapshot(items):
    return [round_state(i.state()) for i in items]


def round_state(d):
    import json
    s = json.dumps(d, sort_keys=True)
    import re
    return re.sub(r"-?\d+\.\d+", lambda m: f"{float(m.group()):.2f}".replace("-0.00", "0.00"), s)


def test_canvas_rotate_cw_maps_objects(ed):
    ln, ar, rc, tx, co, nm, dm, mg = _canvas_scene(ed)
    tx_c = tx.content_rect().center()
    co_tip = co.mapToScene(co.tip)
    ed.transform_canvas("cw")
    bg = ed.doc.background
    assert (bg.width(), bg.height()) == (600, 800)
    # пиксель (10, 20) → (600 - 20, 10) = (580, 10) (с учётом размера пикселя — 579)
    assert bg.pixelColor(579, 10) == QColor(255, 0, 0)
    a, b = ln.scene_points()
    assert (round(a.x()), round(a.y()), round(b.x()), round(b.y())) == (580, 10, 580, 100)
    # прямоугольник повёрнут вместе с фото, надпись — горизонтальна, но на новом месте
    assert rc.props["angle"] == 90
    assert tx.props["angle"] == 0
    c = tx.content_rect().center()
    assert abs(c.x() - (600 - tx_c.y())) < 1e-6 and abs(c.y() - tx_c.x()) < 1e-6
    t = co.mapToScene(co.tip)
    assert abs(t.x() - (600 - co_tip.y())) < 1e-6 and abs(t.y() - co_tip.x()) < 1e-6
    # лупа: область 30×40 (была 40×30)
    assert (round(mg.src.width()), round(mg.src.height())) == (30, 40)
    # одна отмена — всё как было
    ed.undo.undo()
    assert ed.doc.background.width() == 800
    a, b = ln.scene_points()
    assert (round(a.x()), round(a.y())) == (10, 20)
    assert rc.props["angle"] == 0


def test_canvas_four_turns_and_double_flip_are_identity(ed):
    items = _canvas_scene(ed)
    before = _snapshot(items)
    img = QImage(ed.doc.background)
    for _ in range(4):
        ed.transform_canvas("cw")
    assert _snapshot(items) == before
    assert ed.doc.background == img
    for op in ("fliph", "fliph", "flipv", "flipv", "ccw", "cw", "180", "180"):
        ed.transform_canvas(op)
    assert _snapshot(items) == before
    assert ed.doc.background == img


def test_canvas_flip_keeps_glue(ed):
    _tools_view(ed)
    r = RectItem()
    r.set_drag(QPointF(100, 100), QPointF(200, 160))
    ed.add_items([r])
    ed.set_tool("line")
    _drag(ed.tool, QPointF(200, 160), QPointF(400, 300))
    ln = [i for i in ed.doc.items() if i.TYPE == "line"][0]
    assert "s" in ln.glue
    ed.transform_canvas("fliph")
    assert ln.mapToScene(ln.points[0]) == QPointF(600, 160)
    # после отражения конец всё ещё приклеен к тому же углу прямоугольника
    ed.sel.set([r])
    ed.nudge(0, 10)
    assert ln.mapToScene(ln.points[0]) == QPointF(600, 170)


def test_pencil_brush_circle_follows_width(ed):
    from PySide6.QtCore import Qt
    from annotator import styles
    from annotator.tools.base import ToolEvent
    view = _tools_view(ed)
    ed.set_tool("freehand")
    t = ed.tool
    t.move(ToolEvent(QPointF(300, 300), None, Qt.NoModifier, Qt.NoButton, Qt.NoButton))
    assert t.hover == QPointF(300, 300) and not t.outside
    w0 = t.brush_width()
    # толщину меняют в панели «Новый объект: Карандаш»
    t.leave()
    assert t.outside
    w1 = w0 * 3
    styles.remember("freehand", "width", w1)
    ed.styleChanged.emit()
    assert not t.outside and abs(t.brush_width() - w1) < 0.51
    # во время рисования — толщина рисуемой линии
    t.press(ToolEvent(QPointF(300, 300), None, Qt.NoModifier, Qt.LeftButton, Qt.LeftButton))
    assert t.brush_width() == float(t.temp.props["width"])


def test_resistor_tool_and_item(ed):
    from annotator.items import ResistorItem
    _tools_view(ed)
    ed.set_tool("resistor")
    _drag(ed.tool, QPointF(100, 100), QPointF(220, 150))
    r = [i for i in ed.doc.items() if i.TYPE == "resistor"][0]
    assert r.horizontal()
    a, b = r.pads()
    assert abs(a.width() - 120 * r.props["pad_len"] / 100) < 1e-6 and a.left() == r.rect.left()
    assert abs(b.right() - r.rect.right()) < 1e-6
    # центры площадок — точки привязки
    centers = [p for p, k in r.snap_points() if k == "center"]
    assert r.mapToScene(a.center()) in [r.mapToScene(c) for c in centers]
    # текст внутри включается галочкой; ввод текста сам её включает
    assert not r.props["show_text"]
    ed.sel.set([r])
    ed.set_prop("text", "R12 10k")
    assert r.props["show_text"]
    ed.undo.undo()
    assert not r.props["show_text"] and r.props["text"] == "R1"
    # масштабирование ручкой (правый нижний угол) — площадки пересчитываются
    r.begin_handle_drag(4)
    r.move_handle(4, QPointF(r.rect.left() + 40, r.rect.top() + 160))
    assert not r.horizontal()
    a, b = r.pads()
    assert a.top() == r.rect.normalized().top() and abs(a.width() - r.rect.width()) < 1e-6
    # сохранение и загрузка
    r.set_prop("show_text", True)
    r2 = ResistorItem()
    r2.apply_dict(r.to_dict(full=True))
    assert r2.rect == r.rect and r2.props["show_text"]
    # поворот холста — резистор поворачивается вместе с фото
    ed.transform_canvas("cw")
    assert r.props["angle"] == 90


def _corner(item, hid):
    return item.mapToScene(item.handles()[item.HANDLE_IDS.index(hid)])


def _drag_shift_late(t, a, b):
    """Схватить маркер без Shift, потом зажать Shift и тянуть."""
    from PySide6.QtCore import Qt
    from annotator.tools.base import ToolEvent
    t.press(ToolEvent(a, None, Qt.NoModifier, Qt.LeftButton, Qt.LeftButton))
    t.move(ToolEvent((a + b) / 2, None, Qt.NoModifier, Qt.NoButton, Qt.LeftButton))
    t.move(ToolEvent(b, None, Qt.ShiftModifier, Qt.NoButton, Qt.LeftButton))
    t.release(ToolEvent(b, None, Qt.ShiftModifier, Qt.LeftButton, Qt.NoButton))


def test_rect_resize_shift_keeps_aspect_not_square(ed):
    from PySide6.QtCore import Qt
    _tools_view(ed)
    for cls in (RectItem, EllipseItem):
        it = cls(QRectF(0, 0, 200, 100))
        it.setPos(100, 100)
        ed.add_items([it])
        ed.set_tool("select")
        ed.sel.set([it])
        br = _corner(it, "br")
        _drag(ed.tool, br, br + QPointF(50, 10))             # без Shift — свободно
        assert (it.rect.width(), it.rect.height()) == (250, 110)
        ratio = it.rect.width() / it.rect.height()
        br = _corner(it, "br")
        _drag_shift_late(ed.tool, br, br + QPointF(80, 0))   # Shift во время — пропорции, не квадрат
        assert abs(it.rect.width() / it.rect.height() - ratio) < 1e-4
        assert abs(it.rect.width() - it.rect.height()) > 1
        b = _corner(it, "b")
        _drag_shift_late(ed.tool, b, b + QPointF(0, 30))     # нижняя сторона с Shift — тоже пропорционально
        assert abs(it.rect.width() / it.rect.height() - ratio) < 1e-4
        ed.doc.remove_item(it)


def test_resistor_aspect(ed):
    from PySide6.QtCore import Qt
    _tools_view(ed)
    # рисование с Shift — сразу 1:2 вдоль направления
    ed.set_tool("resistor")
    _drag(ed.tool, QPointF(100, 100), QPointF(260, 130), Qt.ShiftModifier)
    r = [i for i in ed.doc.items() if i.TYPE == "resistor"][0]
    assert (r.rect.width(), r.rect.height()) == (160, 80)
    _drag(ed.tool, QPointF(400, 100), QPointF(420, 300), Qt.ShiftModifier)
    rv = [i for i in ed.doc.items_sorted() if i.TYPE == "resistor"][-1]
    assert (rv.rect.width(), rv.rect.height()) == (100, 200)
    ed.set_tool("select")
    ed.sel.set([r])
    # угол без Shift — свободно; Shift, нажатый уже во время растягивания, — пропорции
    br = _corner(r, "br")
    _drag(ed.tool, br, br + QPointF(40, 0))
    assert abs(r.rect.width() - 200) < 1e-6 and abs(r.rect.height() - 80) < 1e-6
    tl0 = _corner(r, "tl")
    br = _corner(r, "br")
    _drag_shift_late(ed.tool, br, br + QPointF(100, 5))
    assert abs(r.rect.width() / r.rect.height() - 2.5) < 1e-6
    assert (_corner(r, "tl") - tl0).manhattanLength() < 1e-6
    # боковой маркер с Shift — ширина корпуса растёт пропорционально
    rr = _corner(r, "r")
    w0 = r.rect.width()
    _drag_shift_late(ed.tool, rr, rr + QPointF(60, 0))
    assert abs(r.rect.width() - (w0 + 60)) < 1e-6 and abs(r.rect.height() - (w0 + 60) / 2.5) < 1e-6
    # Shift, зажатый до захвата маркера, — объект двигается целиком, размер прежний
    size0 = (r.rect.width(), r.rect.height())
    tl0 = _corner(r, "tl")
    br = _corner(r, "br")
    _drag(ed.tool, br, br + QPointF(30, 20), Qt.ShiftModifier)
    assert (r.rect.width(), r.rect.height()) == size0
    moved = _corner(r, "tl") - tl0          # точка захвата могла притянуться привязкой — сдвиг примерно (30, 20)
    assert abs(moved.x() - 30) <= 12 and abs(moved.y() - 20) <= 12
    # кнопка «1 : 2»: длинная сторона и центр на месте, работает и у повёрнутого
    r.set_prop("angle", 30.0)
    c0 = r.mapToScene(r.rect.center())
    long0 = r.rect.width()
    ed.resistor_aspect([r])
    assert abs(r.aspect() - 2.0) < 1e-6 and abs(r.rect.width() - long0) < 1e-6
    c1 = r.mapToScene(r.rect.center())
    assert abs(c1.x() - c0.x()) < 1e-6 and abs(c1.y() - c0.y()) < 1e-6
    ed.undo.undo()
    assert abs(r.aspect() - 2.5) < 1e-6


def test_resistor_label_size(ed):
    from PySide6.QtGui import QFontMetricsF
    from annotator.items import ResistorItem
    r = ResistorItem(QRectF(0, 0, 200, 60), {"show_text": True, "text": "R1"})
    ed.add_items([r])
    # «Размер по корпусу»: буквы занимают ~70% ширины корпуса и не вылезают за поля
    f = r.label_font()
    t = QFontMetricsF(f).tightBoundingRect("R1")
    inner = r.body_inner()
    assert t.height() <= inner.height() * r.LABEL_FILL + 1 and t.height() >= inner.height() * r.LABEL_FILL - 2
    assert t.width() <= inner.width()
    # ручной размер — ровно как в свойствах, в том числе крупнее корпуса
    r.set_prop("auto_size", False)
    for size in (12, 30, 90):
        r.set_prop("size", size)
        assert r.label_font().pixelSize() == size


def test_line_spacing_text_callout_resistor(ed):
    from PySide6.QtGui import QFontMetricsF, QPainter
    from annotator.items import ResistorItem
    from annotator.items.text import make_font
    t = TextItem({"text": "Строка 1\nСтрока 2\nСтрока 3", "size": 20, "padding": 0})
    ed.add_items([t])
    fh = QFontMetricsF(make_font(t.props)).lineSpacing()
    h1 = t.box().height()
    t.set_prop("line_spacing", 2.0)
    h2 = t.box().height()
    assert abs((h2 - h1) - 2 * fh) < 1.5          # 3 строки: два интервала стали вдвое больше
    t.set_prop("line_spacing", 0.7)
    assert t.box().height() < h1
    # отрисовка (в т.ч. с переносом в заданной рамке) не падает
    img = QImage(400, 300, QImage.Format_ARGB32_Premultiplied)
    for it in (t, CalloutItem({"text": "А\nБ", "line_spacing": 1.6}),
               ResistorItem(QRectF(0, 0, 160, 80), {"show_text": True, "text": "R1\n10k", "line_spacing": 1.5})):
        p = QPainter(img)
        it.paint(p, None)
        p.end()
    t.set_prop("auto_size", False)
    t.set_prop("box_w", 60.0)
    p = QPainter(img)
    t.paint(p, None)
    p.end()
    assert "line_spacing" in [s.name for s in CalloutItem.PROPS]
    # резистор: две строки с бо́льшим интервалом — авторазмер шрифта меньше
    r = ResistorItem(QRectF(0, 0, 160, 80), {"show_text": True, "text": "R1\n10k"})
    s1 = r.label_font().pixelSize()
    r.set_prop("line_spacing", 1.8)
    assert r.label_font().pixelSize() < s1


def test_callout_box_resize(ed):
    _tools_view(ed)
    c = CalloutItem({"text": "Длинный комментарий к узлу"})
    c.setPos(200, 200)
    c.tip = QPointF(-120, 150)
    ed.add_items([c])
    tip0 = c.mapToScene(c.tip)
    b0 = c.mapToScene(c.box()).boundingRect()
    ed.set_tool("select")
    ed.sel.set([c])
    kinds = c.handle_kinds()
    i_br = 3 * len(c.leaders) + c.HANDLE_IDS.index("br")
    assert kinds[i_br] == "box" and kinds[-1] == "move"
    br = c.mapToScene(c.handles()[i_br])
    _drag(ed.tool, br, br + QPointF(120, 60))
    b1 = c.mapToScene(c.box()).boundingRect()
    assert abs(b1.width() - (b0.width() + 120)) < 0.6 and abs(b1.height() - (b0.height() + 60)) < 0.6
    assert (b1.topLeft() - b0.topLeft()).manhattanLength() < 1e-6     # левый верхний угол на месте
    assert c.mapToScene(c.tip) == tip0                                 # стрелка указывает туда же
    assert not c.props["auto_size"]
    # левая сторона: блок растёт влево, острие на месте
    i_l = 3 * len(c.leaders) + c.HANDLE_IDS.index("l")
    if c.handle_kinds()[i_l] == "box":
        l = c.mapToScene(c.handles()[i_l])
        _drag(ed.tool, l, l - QPointF(50, 0))
        assert abs(c.mapToScene(c.box()).boundingRect().left() - (b0.left() - 50)) < 0.6
        assert c.mapToScene(c.tip) == tip0
    # сужение — текст переносится, высота блока задана рамкой
    c2 = CalloutItem()
    c2.apply_dict(c.to_dict(full=True))
    assert c2.box().size() == c.box().size()
    # «Размер по тексту» — обратно к автоматическому размеру; отмена возвращает рамку
    ed.sel.set([c])
    ed.set_prop("auto_size", True)
    assert abs(c.box().width() - b0.width()) < 0.6
    ed.undo.undo()
    assert not c.props["auto_size"]


def test_polyline_drag_end_snaps_to_own_start(ed):
    from PySide6.QtCore import Qt
    from annotator.tools.base import ToolEvent
    _tools_view(ed)
    ed.set_tool("polyline")
    tl = ed.tool
    for p in (QPointF(100, 100), QPointF(300, 120), QPointF(320, 300), QPointF(150, 280)):
        tl.press(ToolEvent(p, None, Qt.NoModifier, Qt.LeftButton, Qt.LeftButton))
        tl.release(ToolEvent(p, None, Qt.NoModifier, Qt.LeftButton, Qt.NoButton))
    tl.finish()
    pl = [i for i in ed.doc.items() if i.TYPE == "polyline"][0]
    start = pl.scene_points()[0]
    end = pl.scene_points()[-1]
    # тянем конец к началу (чуть мимо) — магнит ставит его ровно в начало
    ed.set_tool("select")
    ed.sel.set([pl])
    _drag(ed.tool, end, start + QPointF(4, -3))
    assert pl.scene_points()[-1] == start
    # и средняя вершина прилипает к другой своей вершине
    mid_v = pl.scene_points()[1]
    _drag(ed.tool, mid_v, pl.scene_points()[2] + QPointF(3, 3))
    assert pl.scene_points()[1] == pl.scene_points()[2]


def test_ctrl_enter_finishes_text_editing(ed):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from annotator.ui.dialogs import TextDialog
    from annotator.ui.widgets import TextEditor

    def key(w, mods):
        QApplication.sendEvent(w, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, mods))

    # окно ввода: Enter — готово, Ctrl+Enter — готово и снять выделение, Shift+Enter — новая строка
    d = TextDialog(None, "R1")
    key(d.edit, Qt.ShiftModifier)
    assert d.result() == 0 and "\n" in d.text()
    key(d.edit, Qt.ControlModifier)
    assert d.result() == TextDialog.Accepted and d.release
    d2 = TextDialog(None, "R1")
    key(d2.edit, Qt.NoModifier)
    assert d2.result() == TextDialog.Accepted and not d2.release
    # поле «Текст» в свойствах: Ctrl+Enter — сигнал «закончить», без новой строки
    te = TextEditor()
    te.set_value("abc")
    got = []
    te.finished.connect(lambda: got.append(1))
    key(te, Qt.ControlModifier)
    assert got == [1] and te.toPlainText() == "abc"
    # закончить правку: выделение снято
    _tools_view(ed)
    t = TextItem({"text": "Т"})
    ed.add_items([t])
    assert ed.sel.items == [t]
    ed.release_focus()
    assert ed.sel.items == []


def _photo(tmp_path, name, color=(200, 60, 60)):
    img = QImage(400, 300, QImage.Format_RGB32)
    img.fill(QColor(*color))
    path = str(tmp_path / name)
    img.save(path)
    return path


def test_projects_independent_undo_selection_duplicate(ed, tmp_path):
    import os
    a = ed.project
    ed.add_items([line((0, 0), (100, 0))])
    la = ed.doc.items()[0]
    b = ed.new_project()
    ed.new_from_image(QImage(_photo(tmp_path, "b.png")), str(tmp_path / "b.png"))
    lb = line((10, 10), (50, 50))
    ed.add_items([lb])
    assert ed.project is b and ed.doc is b.doc and ed.undo is b.undo
    # своя история: отмена в b не трогает a
    ed.undo.undo()
    assert not b.doc.contains(lb) and a.doc.contains(la)
    ed.undo.redo()
    # своё выделение, возвращается при переключении
    ed.sel.set([lb])
    ed.switch_project(a)
    assert ed.sel.items == [] or ed.sel.items == [la]
    ed.sel.set([la])
    ed.switch_project(b)
    assert ed.sel.items == [lb]
    # копия — независимый несохранённый проект справа
    c = ed.duplicate_project(b)
    assert ed.projects.index(c) == ed.projects.index(b) + 1 and ed.project is c
    assert c.display_name() == "b (копия)" and c.is_modified() and c.doc.project_path is None
    assert len(c.doc.items()) == len(b.doc.items())
    c.doc.items()[0].moveBy(100, 0)
    assert lb.pos() != c.doc.items()[0].pos()
    assert ed.duplicate_project(b).display_name() == "b (копия) 2"
    # порядок и закрытие; последний закрытый — заменяется пустым
    ed.move_project(c, 0)
    assert ed.projects[0] is c
    for p in list(ed.projects):
        ed.close_project(p)
    assert len(ed.projects) == 1 and ed.project.is_pristine()
    del os


def test_project_rename_and_quick_png_path(ed, tmp_path):
    import os
    photo = _photo(tmp_path, "achh.png")
    ed.project_for_open()
    ed.open_image(photo)
    p = ed.project
    assert p.display_name() == "achh"
    # PNG рядом с фото, но не поверх самого фото
    assert ed.quick_png_path(p) == os.path.join(str(tmp_path), "achh_annotated.png")
    # несохранённый — меняется имя (и имя PNG)
    assert ed.rename_project(p, "C12 220n") is None
    assert p.display_name() == "C12 220n"
    assert ed.quick_png_path(p) == os.path.join(str(tmp_path), "C12 220n.png")
    assert ed.rename_project(p, "bad/name") is not None
    # сохранённый — переименовывается и файл .iap
    prj = str(tmp_path / "C12 220n.iap")
    ed.save_project(prj)
    assert ed.rename_project(p, "C12 330n") is None
    assert not os.path.exists(prj) and os.path.exists(str(tmp_path / "C12 330n.iap"))
    assert p.doc.project_path.endswith("C12 330n.iap") and p.display_name() == "C12 330n"
    # повторное открытие того же файла находит этот проект
    assert ed.find_project(str(tmp_path / "C12 330n.iap")) is p
    # проект без файла и без фото — PNG некуда положить без вопроса
    q = ed.new_project()
    ed.new_blank(100, 100, QColor("white"))
    assert ed.quick_png_path(q) is None


def test_project_strip_wheel_and_overlay(tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint, QSettings, Qt
    from PySide6.QtGui import QWheelEvent
    from annotator import mainwindow, styles
    # настройки окна — во временный файл, не в реестр пользователя
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(mainwindow, "QSettings", lambda *a: QSettings(ini, QSettings.IniFormat))
    styles.reset()
    w = mainwindow.MainWindow()
    w.resize(1000, 700)
    w.show()
    w.strip.set_pinned(False)
    w.open_paths([_photo(tmp_path, f"p{i}.png", (40 * i, 100, 150)) for i in range(4)])
    ed = w.ed
    # открыли несколько — активный первый (левый) из них
    assert len(ed.projects) == 4 and ed.project is ed.projects[0]
    cont = w.strip.content

    def wheel(dy):
        QApplication.sendEvent(cont, QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, dy),
                                                 Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False))
    wheel(120)                        # колесо от себя — следующий справа
    assert ed.project is ed.projects[1]
    wheel(-120)
    wheel(-120)                       # на первом — дальше не листает
    assert ed.project is ed.projects[0]
    # лента — над холстом; миниатюры без закрепления — поверх холста (холст не меняет размер)
    QApplication.processEvents()
    assert w.strip.y() == 0 and w.view.y() == w.strip.collapsed_height()
    vh = w.view.height()
    w.strip._hover = True
    w.strip.relayout()
    QApplication.processEvents()
    assert w.view.height() == vh and w.strip.height() > w.strip.collapsed_height()
    # закреплённая — место под холстом
    w.strip.set_pinned(True)
    QApplication.processEvents()
    assert w.view.height() < vh
    for p in ed.projects:
        p.undo.setClean()
    w.close()


def test_copy_paste_style(ed):
    src = TextItem({"text": "Источник", "color": "#00ff00", "size": 40, "bold": False, "italic": True,
                    "bg_color": "#000000", "line_spacing": 1.5, "angle": 30.0})
    src.set_prop("auto_size", False)
    a = TextItem({"text": "A"})
    b = TextItem({"text": "B"})
    r = RectItem()
    r.set_drag(QPointF(0, 0), QPointF(50, 50))
    ed.add_items([src, a, b, r])
    ed.copy_style(src)
    # вставка — во все выбранные объекты того же типа; прямоугольник не трогаем
    ed.sel.set([a, b, r])
    assert ed.style_targets() == [a, b]
    r_before = r.state()
    ed.paste_style()
    for t in (a, b):
        for k in ("color", "size", "bold", "italic", "bg_color", "line_spacing"):
            assert t.props[k] == src.props[k], k
        # содержимое, поворот и размер рамки — свои
        assert t.props["angle"] == 0 and t.props["auto_size"] is True
    assert a.props["text"] == "A" and b.props["text"] == "B"
    assert r.state() == r_before
    # одна отмена
    ed.undo.undo()
    assert a.props["color"] != "#00ff00" and b.props["size"] != 40
    # стиль переносится и в другой проект
    ed.new_project()
    c = TextItem({"text": "C"})
    ed.add_items([c])
    ed.sel.set([c])
    ed.paste_style()
    assert c.props["color"] == "#00ff00" and c.props["text"] == "C"
    # заблокированный — не меняется
    d = TextItem({"text": "D"})
    ed.add_items([d])
    d.locked = True
    assert ed.style_targets([d]) == []
