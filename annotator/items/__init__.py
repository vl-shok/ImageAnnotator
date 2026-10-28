"""Реестр типов объектов-аннотаций."""
from __future__ import annotations

from .base import AnnotationItem
from .image import BackgroundItem, ImageItem
from .shapes import (ArrowItem, EllipseItem, FreehandItem, LineItem, PolygonItem,
                     PolylineItem, RectItem)
from .dimension import DimensionItem
from .magnifier import MagnifierItem
from .component import ResistorItem
from .mark import CheckItem
from .shapes import BreakItem
from .text import CalloutItem, NumberItem, TextItem

ITEM_CLASSES = [TextItem, LineItem, ArrowItem, CalloutItem, NumberItem, RectItem, EllipseItem,
                PolylineItem, PolygonItem, FreehandItem, ImageItem, BreakItem, DimensionItem, MagnifierItem,
                ResistorItem, CheckItem]
REGISTRY = {c.TYPE: c for c in ITEM_CLASSES}


def create_from_dict(d: dict, keep_id: bool = True) -> AnnotationItem:
    cls = REGISTRY[d["type"]]
    item = cls()
    item.apply_dict(d, keep_id=keep_id)
    return item


__all__ = ["AnnotationItem", "BackgroundItem", "ImageItem", "ArrowItem", "EllipseItem",
           "FreehandItem", "LineItem", "PolygonItem", "PolylineItem", "RectItem", "CalloutItem",
           "NumberItem", "TextItem", "BreakItem", "DimensionItem", "MagnifierItem", "ResistorItem", "CheckItem", "ITEM_CLASSES", "REGISTRY", "create_from_dict"]
