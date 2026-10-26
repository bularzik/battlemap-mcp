"""Geometry for build_room's shared walls.

When a new room's edge lies on an existing wall, drawing the room's own wall
there doubles the wall, and a door later mounts on only one of the two: in a
Universal VTT export the other still crosses the doorway. So the covered parts
of the boundary are left out and the rest is drawn as open runs.
"""

from __future__ import annotations

import itertools
import math

Point = tuple[float, float]
Segment = tuple[Point, Point]


def segments_of(walls: list[dict]) -> list[Segment]:
    """Segments of list_elements walls (with points); a loop adds its closing edge."""
    out: list[Segment] = []
    for wall in walls:
        pts = [(float(p[0]), float(p[1])) for p in wall.get("points") or []]
        pairs = list(itertools.pairwise(pts))
        if wall.get("loop") and len(pts) > 2:
            pairs.append((pts[-1], pts[0]))
        out.extend(pairs)
    return out


def _covered(a: Point, b: Point, existing: list[Segment], tol: float) -> list[tuple[float, float]]:
    """Merged (start, end) distances along a->b that collinear segments cover."""
    length = math.dist(a, b)
    if length <= tol:
        return []
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    spans = []
    for p, q in existing:
        # Both ends must lie on the edge's line, within tol.
        if any(abs((pt[0] - a[0]) * uy - (pt[1] - a[1]) * ux) > tol for pt in (p, q)):
            continue
        tp = (p[0] - a[0]) * ux + (p[1] - a[1]) * uy
        tq = (q[0] - a[0]) * ux + (q[1] - a[1]) * uy
        lo, hi = max(min(tp, tq), 0.0), min(max(tp, tq), length)
        if hi - lo > tol:
            spans.append((lo, hi))
    merged: list[list[float]] = []
    for lo, hi in sorted(spans):
        if merged and lo <= merged[-1][1] + tol:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    # An interval ending within tol of a corner ends at the corner.
    return [(0.0 if lo <= tol else lo, length if hi >= length - tol else hi) for lo, hi in merged]


def _at(a: Point, b: Point, t: float, length: float) -> Point:
    if t <= 0.0:
        return a
    if t >= length:
        return b
    f = t / length
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


def split_boundary(
    points: list[list[float]], existing: list[Segment], tol: float = 1.0
) -> tuple[list[list[list[float]]], list[list[list[float]]]]:
    """Split a closed room boundary into open wall runs around already-walled parts.

    Returns (runs, shared), both as [x, y] lists. With nothing covered,
    runs == [points]: draw the room as one loop, as before.
    """
    poly = [(float(p[0]), float(p[1])) for p in points]
    n = len(poly)
    shared: list[Segment] = []
    # Uncovered pieces in boundary order: (start, end, starts at a corner, ends at a corner).
    pieces: list[tuple[Point, Point, bool, bool]] = []
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        length = math.dist(a, b)
        t = 0.0
        for lo, hi in _covered(a, b, existing, tol):
            if lo - t > tol:
                pieces.append((_at(a, b, t, length), _at(a, b, lo, length), t == 0.0, False))
            shared.append((_at(a, b, lo, length), _at(a, b, hi, length)))
            t = hi
        if length - t > tol:
            pieces.append((_at(a, b, t, length), b, t == 0.0, True))
    if not shared:
        return [[list(p) for p in points]], []

    runs: list[list[Point]] = []
    prev_ends_at_corner = False
    for start, end, starts_at_corner, ends_at_corner in pieces:
        if prev_ends_at_corner and starts_at_corner and runs[-1][-1] == start:
            runs[-1].append(end)  # the run turns a corner of the room
        else:
            runs.append([start, end])
        prev_ends_at_corner = ends_at_corner
    # The last run may continue into the first through the boundary's first corner.
    if len(runs) > 1 and pieces[0][2] and pieces[-1][3] and runs[-1][-1] == runs[0][0]:
        runs[0] = runs.pop() + runs[0][1:]
    as_lists = [[list(p) for p in run] for run in runs]
    return as_lists, [[list(a), list(b)] for a, b in shared]
