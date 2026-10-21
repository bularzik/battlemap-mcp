"""A crop keeps the tiles in a window and Dungeondraft moves everything by the
trimmed amount. What lies wholly outside the window would sit off the map
afterwards, so crop_map deletes it; what crosses the window's edge is kept and
reported, because cutting a wall or path at the edge is not done here.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

WOXELS_PER_TILE = 256

# Kinds list_elements can enumerate, and how each one's extent is read.
POINT_KINDS = ("walls", "paths", "roofs")
POSITION_KINDS = ("lights", "texts", "portals")
BOUNDS_KINDS = ("objects",)
KINDS = BOUNDS_KINDS + POINT_KINDS + POSITION_KINDS

Rect = tuple[float, float, float, float]  # x0, y0, x1, y1 in woxels


def window_woxels(rect: Sequence[int]) -> Rect:
    """A tile window [x, y, w, h] as woxel edges."""
    x, y, w, h = rect
    return (
        x * WOXELS_PER_TILE,
        y * WOXELS_PER_TILE,
        (x + w) * WOXELS_PER_TILE,
        (y + h) * WOXELS_PER_TILE,
    )


def _inside(point: Sequence[float], window: Rect) -> bool:
    x0, y0, x1, y1 = window
    return x0 <= point[0] <= x1 and y0 <= point[1] <= y1


def _segment_meets(a: Sequence[float], b: Sequence[float], window: Rect) -> bool:
    """Whether segment a-b touches the window (Liang-Barsky clipping)."""
    x0, y0, x1, y1 = window
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _place_points(points: Sequence[Sequence[float]], loop: bool, window: Rect) -> str:
    if not points:
        return "inside"
    inside = [_inside(p, window) for p in points]
    if all(inside):
        return "inside"
    if any(inside):
        return "crossing"
    pairs = list(zip(points, points[1:], strict=False))
    if loop and len(points) > 2:
        pairs.append((points[-1], points[0]))
    if any(_segment_meets(a, b, window) for a, b in pairs):
        return "crossing"
    if len(points) > 2 and loop:
        # A closed shape can surround the window without touching it.
        x0, y0, x1, y1 = window
        if _contains(points, ((x0 + x1) / 2, (y0 + y1) / 2)):
            return "crossing"
    return "outside"


def _contains(polygon: Sequence[Sequence[float]], point: Sequence[float]) -> bool:
    inside = False
    px, py = point
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j][0], polygon[j][1]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _place_box(box: Sequence[float], window: Rect) -> str:
    bx0, by0, bx1, by1 = box
    x0, y0, x1, y1 = window
    if bx0 >= x0 and by0 >= y0 and bx1 <= x1 and by1 <= y1:
        return "inside"
    if bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1:
        return "outside"
    return "crossing"


def is_cave_wall(element: dict[str, Any]) -> bool:
    """Cave borders are rebuilt from the cave floor; a crop never edits them."""
    return "/caves/" in str(element.get("asset", ""))


def place(kind: str, element: dict[str, Any], window: Rect) -> str:
    """'inside', 'outside' or 'crossing' for one list_elements entry."""
    if kind in BOUNDS_KINDS:
        box = element.get("bounds")
        if box and len(box) == 4:
            return _place_box(box, window)
    if kind in POINT_KINDS:
        return _place_points(element.get("points") or [], bool(element.get("loop")), window)
    position = element.get("position") or [0, 0]
    return "inside" if _inside(position, window) else "outside"


def classify(
    elements: dict[str, Iterable[dict[str, Any]]], window: Rect
) -> dict[str, dict[str, list[int]]]:
    """Ids of what lies wholly outside the window and what crosses its edge, per kind.

    A wall's portals go with the wall: a portal is listed on its own only when
    its wall stays.
    """
    outside: dict[str, list[int]] = {}
    crossing: dict[str, list[int]] = {}
    dropped_walls: set[int] = set()
    portals: list[dict[str, Any]] = []
    for kind, entries in elements.items():
        for element in entries:
            if kind == "walls" and is_cave_wall(element):
                continue
            if kind == "portals":
                portals.append(element)
                continue
            where = place(kind, element, window)
            if where == "outside":
                outside.setdefault(kind, []).append(int(element["id"]))
                if kind == "walls":
                    dropped_walls.add(int(element["id"]))
            elif where == "crossing":
                crossing.setdefault(kind, []).append(int(element["id"]))
    for portal in portals:
        if portal.get("wall_id") in dropped_walls:
            continue
        if place("portals", portal, window) == "outside":
            outside.setdefault("portals", []).append(int(portal["id"]))
    return {"outside": outside, "crossing": crossing}
