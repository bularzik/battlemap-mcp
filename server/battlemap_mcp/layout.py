"""Where furniture goes when it lines a wall, rings a table or dresses a surface.

Three placements a model gets wrong by hand, each in a way the reply never
shows: a shelf left a hand's width off its wall, chairs set out on a perfect
grid around a table, and books stacked past the edge of a desk.

Orientation is an assumption, and every plan says which one it made. An
asset's `facing` is the direction its front points at rotation 0: \"down\" is
how Dungeondraft's own furniture is drawn (backrest or back panel at the top),
and is the default only because of that. Pack art varies, so a caller who sees
a shelf with its back to the room passes the facing that asset really has.

Pure functions; nothing here talks to the bridge or touches the map.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .placement import Box, Segment

FACINGS: dict[str, tuple[float, float]] = {
    "down": (0.0, 1.0),
    "up": (0.0, -1.0),
    "right": (1.0, 0.0),
    "left": (-1.0, 0.0),
}

# How far a wall may lie from the line the caller gave, and how far off
# parallel, before it is not the wall they meant.
WALL_DISTANCE_TOLERANCE = 96.0
WALL_ANGLE_TOLERANCE = 10.0

# Half a wall's thickness when the bridge reports no texture for it.
DEFAULT_WALL_HALF_THICKNESS = 32.0

# A portal's half width when the bridge gives neither a radius nor a texture.
DEFAULT_PORTAL_HALF_WIDTH = 128.0

MAX_ARRANGED = 40

# Chairs: small, deliberate irregularity. A set table is tidy; a perfectly
# even one reads as a grid.
CHAIR_ROTATION_JITTER = 3.0
CHAIR_SHIFT_JITTER = 6.0
# The shortest side, as a share of a seat's width, that still takes one seat.
END_SEAT_SHARE = 0.75

# Dressing: how far an item turns from the surface's own rotation.
DRESSING_ROTATION = 25.0
DRESSING_TRIES = 80


class LayoutError(ValueError):
    """A plan that cannot be made from what was given; the message says why."""


@dataclass(frozen=True)
class Art:
    """An asset's drawn area at the scale it will be placed at."""

    asset: str
    canvas: tuple[float, float]
    drawn: tuple[float, float, float, float]
    scale: float = 1.0

    @property
    def width(self) -> float:
        return self.drawn[2] * self.scale

    @property
    def height(self) -> float:
        return self.drawn[3] * self.scale

    @property
    def offset(self) -> tuple[float, float]:
        """The drawn centre's offset from the canvas centre, at rotation 0."""
        return (
            (self.drawn[0] + self.drawn[2] / 2.0 - self.canvas[0] / 2.0) * self.scale,
            (self.drawn[1] + self.drawn[3] / 2.0 - self.canvas[1] / 2.0) * self.scale,
        )

    def across(self, facing: str) -> float:
        """Extent across the direction the asset faces: along a wall, or a table edge."""
        return self.width if facing in ("down", "up") else self.height

    def depth(self, facing: str) -> float:
        """Extent in the direction the asset faces: out from the wall."""
        return self.height if facing in ("down", "up") else self.width


def art_from(asset: str, size: object, drawn: object, scale: float = 1.0) -> Art:
    """An Art from list_assets' `sizes` and `drawn` entries, refusing a missing one.

    There is no canvas fallback on purpose: a canvas-fitted plan is the defect
    this module exists to avoid.
    """
    if not isinstance(size, list | tuple) or len(size) < 2:
        raise LayoutError(f"no size reported for {asset}")
    if not isinstance(drawn, list | tuple) or len(drawn) < 4:
        raise LayoutError(f"no drawn area reported for {asset}")
    if float(drawn[2]) <= 0 or float(drawn[3]) <= 0:
        raise LayoutError(f"{asset} has no drawn pixels")
    return Art(
        asset=asset,
        canvas=(float(size[0]), float(size[1])),
        drawn=(float(drawn[0]), float(drawn[1]), float(drawn[2]), float(drawn[3])),
        scale=float(scale),
    )


def rotation_to_face(facing: str, direction: tuple[float, float]) -> float:
    """Degrees that turn an asset drawn facing `facing` to face `direction`."""
    fx, fy = FACINGS[facing]
    degrees = math.degrees(math.atan2(direction[1], direction[0]) - math.atan2(fy, fx))
    degrees = (degrees + 180.0) % 360.0 - 180.0
    return 180.0 if degrees == -180.0 else degrees


def _rotate(dx: float, dy: float, degrees: float) -> tuple[float, float]:
    theta = math.radians(degrees)
    return dx * math.cos(theta) - dy * math.sin(theta), dx * math.sin(theta) + dy * math.cos(theta)


def placement(art: Art, drawn_x: float, drawn_y: float, rotation: float) -> dict:
    """place_objects arguments that put the art's DRAWN centre at (drawn_x, drawn_y).

    Dungeondraft positions an object by its canvas centre, which the drawn
    centre is offset from; that offset turns with the object.
    """
    ox, oy = _rotate(*art.offset, rotation)
    return {
        "asset": art.asset,
        "x": round(drawn_x - ox, 2),
        "y": round(drawn_y - oy, 2),
        "rotation": round(rotation, 2),
        "scale": art.scale,
    }


def drawn_box(art: Art, entry: dict) -> Box:
    """Where a planned entry's drawn area lands: the inverse of `placement`."""
    ox, oy = _rotate(*art.offset, entry["rotation"])
    return Box(
        cx=entry["x"] + ox,
        cy=entry["y"] + oy,
        half_w=art.width / 2.0,
        half_h=art.height / 2.0,
        rotation_deg=entry["rotation"],
    )


def sequence(arts: list[Art], count: int) -> list[Art]:
    """The assets in the order given, repeated to `count`."""
    return [arts[index % len(arts)] for index in range(count)]


# --- along a wall -------------------------------------------------------------


@dataclass(frozen=True)
class WallChoice:
    segment: Segment
    index: int  # which segment of its wall
    distance: float
    others: tuple[int, ...]  # other walls within tolerance: a double wall


def _length(segment: Segment) -> float:
    return math.hypot(segment.x1 - segment.x0, segment.y1 - segment.y0)


def _unit(segment: Segment) -> tuple[float, float]:
    length = _length(segment)
    return (segment.x1 - segment.x0) / length, (segment.y1 - segment.y0) / length


def _project(segment: Segment, x: float, y: float) -> tuple[float, float]:
    """(distance along the segment from its start, signed distance off its line)."""
    ux, uy = _unit(segment)
    dx, dy = x - segment.x0, y - segment.y0
    return dx * ux + dy * uy, dx * -uy + dy * ux


def wall_segments(walls: list[dict]) -> list[tuple[Segment, int]]:
    """Each wall's segments with their index along the wall, the loop's closing one included."""
    out: list[tuple[Segment, int]] = []
    for wall in walls:
        points = wall.get("points") or []
        wall_id = int(wall.get("id", -1))
        pairs = list(zip(points, points[1:], strict=False))
        if wall.get("loop") and len(points) > 2:
            pairs.append((points[-1], points[0]))
        for index, ((x0, y0), (x1, y1)) in enumerate(pairs):
            segment = Segment(float(x0), float(y0), float(x1), float(y1), wall_id)
            if _length(segment) > 0:
                out.append((segment, index))
    return out


def choose_wall(
    walls: list[dict],
    along: list[list[float]],
    wall_id: int | None = None,
    *,
    distance_tolerance: float = WALL_DISTANCE_TOLERANCE,
    angle_tolerance: float = WALL_ANGLE_TOLERANCE,
) -> WallChoice:
    """The wall segment the line `along` runs beside.

    A segment qualifies when it is within `angle_tolerance` of parallel, and
    the line's midpoint lies within `distance_tolerance` of it, both across and
    past its ends. Every other wall that also qualifies is reported in
    `others`: two build_room rooms sharing an edge each own a wall along it,
    and a door cuts only one of them.
    """
    (ax, ay), (bx, by) = along[0], along[1]
    if math.hypot(bx - ax, by - ay) == 0:
        raise LayoutError("along must be two different points")
    line_angle = math.degrees(math.atan2(by - ay, bx - ax))
    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
    found: list[tuple[float, Segment, int]] = []
    for segment, index in wall_segments(walls):
        seg_angle = math.degrees(math.atan2(segment.y1 - segment.y0, segment.x1 - segment.x0))
        off_parallel = abs((line_angle - seg_angle + 90.0) % 180.0 - 90.0)
        if off_parallel > angle_tolerance:
            continue
        s, across = _project(segment, mx, my)
        past_end = max(0.0, -s, s - _length(segment))
        if abs(across) > distance_tolerance or past_end > distance_tolerance:
            continue
        found.append((math.hypot(across, past_end), segment, index))
    if wall_id is not None:
        mine = [entry for entry in found if entry[1].wall_id == wall_id]
        if not mine:
            raise LayoutError(
                f"wall {wall_id} has no segment within {distance_tolerance:g} woxels of "
                "`along` and parallel to it"
            )
        chosen = min(mine, key=lambda entry: entry[0])
    elif found:
        chosen = min(found, key=lambda entry: entry[0])
    else:
        raise LayoutError(
            f"no wall runs within {distance_tolerance:g} woxels of `along` and within "
            f"{angle_tolerance:g} degrees of parallel to it; read the walls with "
            "list_elements(kind='walls', include_points=True)"
        )
    others = tuple(sorted({entry[1].wall_id for entry in found} - {chosen[1].wall_id}))
    return WallChoice(chosen[1], chosen[2], chosen[0], others)


def _inside(x: float, y: float, points: list) -> bool:
    inside = False
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=False):
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            inside = not inside
    return inside


def inward_normal(
    segment: Segment, wall: dict, toward: list[float] | None, probe: float
) -> tuple[float, float]:
    """The unit normal pointing from the wall into the room.

    From `toward` when given; otherwise, for a looped wall, whichever side of
    the segment's middle lies inside the loop. An open run of wall has no
    inside, so it needs `toward`.
    """
    ux, uy = _unit(segment)
    left = (uy, -ux)  # rotate the direction a quarter-turn anticlockwise (y down)
    if toward is not None:
        _, across = _project(segment, float(toward[0]), float(toward[1]))
        if across == 0:
            raise LayoutError("`toward` lies on the wall's line; give a point inside the room")
        return (-left[0], -left[1]) if across > 0 else left
    points = wall.get("points") or []
    if wall.get("loop") and len(points) > 2:
        mx, my = (segment.x0 + segment.x1) / 2.0, (segment.y0 + segment.y1) / 2.0
        if _inside(mx + left[0] * probe, my + left[1] * probe, points):
            return left
        return -left[0], -left[1]
    raise LayoutError(
        f"wall {segment.wall_id} is an open run with no inside; pass `toward`, a point "
        "on the side the objects go"
    )


def portal_half_width(portal: dict) -> float:
    if portal.get("radius"):
        return float(portal["radius"])
    size = portal.get("texture_size")
    if size and float(size[0]) > 0:
        return float(size[0]) * abs(float(portal.get("scale") or 1.0)) / 2.0
    return DEFAULT_PORTAL_HALF_WIDTH


def free_intervals(
    segment: Segment,
    along: list[list[float]],
    portals: list[dict],
    *,
    half_thickness: float,
    margin: float,
) -> tuple[list[tuple[float, float]], list[int]]:
    """Stretches of the segment, in woxels from its start, that objects may use.

    The span `along` covers, clipped to the segment, less `margin` plus the
    crossing wall's half thickness at each corner, and less every portal on
    this wall widened by `margin`. Returns the stretches and the portals kept
    clear.
    """
    length = _length(segment)
    s_a, _ = _project(segment, *map(float, along[0]))
    s_b, _ = _project(segment, *map(float, along[1]))
    corner = half_thickness + margin
    start = max(min(s_a, s_b), corner)
    end = min(max(s_a, s_b), length - corner)
    blocked: list[tuple[float, float]] = []
    kept_clear: list[int] = []
    for portal in portals:
        position = portal.get("position")
        if not position:
            continue
        s, across = _project(segment, float(position[0]), float(position[1]))
        half = portal_half_width(portal)
        on_this_wall = portal.get("wall_id") in (None, segment.wall_id)
        if not on_this_wall or abs(across) > half_thickness + margin:
            continue
        if s + half < 0 or s - half > length:
            continue
        blocked.append((s - half - margin, s + half + margin))
        kept_clear.append(int(portal.get("id", -1)))
    intervals = [(start, end)] if end > start else []
    for b0, b1 in sorted(blocked):
        cut: list[tuple[float, float]] = []
        for i0, i1 in intervals:
            if b1 <= i0 or b0 >= i1:
                cut.append((i0, i1))
                continue
            if b0 > i0:
                cut.append((i0, b0))
            if b1 < i1:
                cut.append((b1, i1))
        intervals = cut
    return intervals, kept_clear


def pack_row(
    intervals: list[tuple[float, float]],
    widths: list[float],
    *,
    gap: float | None,
    fill: bool,
) -> list[tuple[int, float]]:
    """(item index, centre distance along the wall) for each item that fits.

    Items keep their order and go into the stretches in turn. With `gap`, each
    stretch's row is that far apart and centred; without, the spare room is
    shared evenly around the items. `fill` repeats the widths until nothing
    more fits, up to MAX_ARRANGED.
    """
    minimum = gap or 0.0
    placed: list[tuple[int, float]] = []
    item = 0
    total = MAX_ARRANGED if fill else len(widths)

    def width_of(index: int) -> float:
        return widths[index % len(widths)]

    for start, end in intervals:
        if item >= total:
            break
        length = end - start
        members: list[int] = []
        used = 0.0
        while item < total:
            need = width_of(item) + (minimum if members else 0.0)
            if used + need > length + 1e-6:
                break
            used += need
            members.append(item)
            item += 1
        if not members:
            continue
        widths_here = [width_of(index) for index in members]
        if gap is not None:
            spacing = gap
            cursor = start + (length - sum(widths_here) - gap * (len(members) - 1)) / 2.0
        else:
            spacing = (length - sum(widths_here)) / (len(members) + 1)
            cursor = start + spacing
        for index, width in zip(members, widths_here, strict=True):
            placed.append((index, cursor + width / 2.0))
            cursor += width + spacing
    return placed


def plan_along_wall(
    arts: list[Art],
    segment: Segment,
    normal: tuple[float, float],
    intervals: list[tuple[float, float]],
    *,
    count: int | None,
    facing: str,
    half_thickness: float,
    gap: float | None,
    offset: float = 0.0,
) -> tuple[list[dict], int]:
    """Entries backed flush against the wall's face, fronts into the room.

    Returns the entries and how many asked-for items did not fit.
    """
    order = sequence(arts, count) if count else list(arts)
    widths = [art.across(facing) for art in order]
    slots = pack_row(intervals, widths, gap=gap, fill=count is None)
    ux, uy = _unit(segment)
    rotation = rotation_to_face(facing, normal)
    entries: list[dict] = []
    for index, s in slots:
        art = order[index % len(order)]
        out = half_thickness + offset + art.depth(facing) / 2.0
        x = segment.x0 + ux * s + normal[0] * out
        y = segment.y0 + uy * s + normal[1] * out
        entries.append(placement(art, x, y, rotation))
    skipped = (count - len(entries)) if count else 0
    return entries, skipped


# --- around a table -----------------------------------------------------------


def table_shape(asset: str) -> str:
    """'round' for an asset named round or circular, else 'rect'.

    The drawn area cannot tell a round table from a square one, so the name
    decides; a square table seats the same four either way.
    """
    name = asset.rsplit("/", 1)[-1].lower()
    return "round" if ("round" in name or "circ" in name) else "rect"


def _seats_per_side(count: int, sides: list[float], capacity: list[int]) -> list[int]:
    """Seats per side in proportion to its length, within what each side holds."""
    total = sum(sides)
    shares = [count * side / total for side in sides]
    seats = [min(int(share), cap) for share, cap in zip(shares, capacity, strict=True)]
    order = sorted(range(len(sides)), key=lambda i: (-(shares[i] - int(shares[i])), -sides[i]))
    while sum(seats) < count:
        progressed = False
        for i in order:
            if sum(seats) >= count:
                break
            if seats[i] < capacity[i]:
                seats[i] += 1
                progressed = True
        if not progressed:
            break
    return seats


def plan_around(
    table: Box,
    arts: list[Art],
    count: int,
    *,
    shape: str,
    facing: str,
    clearance: float,
    jitter: bool,
    rng: random.Random,
) -> tuple[list[dict], int]:
    """Seats around a table's drawn area, each facing it.

    `clearance` is the gap from the table's drawn edge to the seat's; negative
    tucks the seat under. Returns the entries and how many seats did not fit
    (a rectangular side holds as many as fit edge to edge).
    """
    order = sequence(arts, count)
    entries: list[dict] = []

    def add(art: Art, local_x: float, local_y: float, inward: tuple[float, float]) -> None:
        if jitter:
            local_x += rng.uniform(-CHAIR_SHIFT_JITTER, CHAIR_SHIFT_JITTER)
            local_y += rng.uniform(-CHAIR_SHIFT_JITTER, CHAIR_SHIFT_JITTER)
        wx, wy = _rotate(local_x, local_y, table.rotation_deg)
        world_inward = _rotate(*inward, table.rotation_deg)
        rotation = rotation_to_face(facing, world_inward)
        if jitter:
            rotation += rng.uniform(-CHAIR_ROTATION_JITTER, CHAIR_ROTATION_JITTER)
        entries.append(placement(art, table.cx + wx, table.cy + wy, rotation))

    if shape == "round":
        for index, art in enumerate(order):
            angle = math.radians(-90.0 + 360.0 * index / count)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            # The ellipse's radius in this direction, so an oval seats evenly too.
            radius = (table.half_w * table.half_h) / math.hypot(
                table.half_h * cos_a, table.half_w * sin_a
            )
            out = radius + clearance + art.depth(facing) / 2.0
            add(art, cos_a * out, sin_a * out, (-cos_a, -sin_a))
        return entries, 0

    # top, bottom, left, right in the table's own frame: (length, outward normal)
    sides = [
        (2 * table.half_w, (0.0, -1.0)),
        (2 * table.half_w, (0.0, 1.0)),
        (2 * table.half_h, (-1.0, 0.0)),
        (2 * table.half_h, (1.0, 0.0)),
    ]
    widest = max(art.across(facing) for art in order)
    # Seats fit edge to edge; a table's end still takes one seat a little wider
    # than itself, as a set table does.
    capacity = [
        max(int(length // widest), 1 if length >= END_SEAT_SHARE * widest else 0)
        for length, _ in sides
    ]
    seats = _seats_per_side(count, [length for length, _ in sides], capacity)
    item = 0
    for (length, (nx, ny)), seated in zip(sides, seats, strict=True):
        tangent = (-ny, nx)
        half_normal = table.half_h if ny else table.half_w
        for slot in range(seated):
            art = order[item]
            item += 1
            along = -length / 2.0 + length * (slot + 0.5) / seated
            out = half_normal + clearance + art.depth(facing) / 2.0
            add(art, tangent[0] * along + nx * out, tangent[1] * along + ny * out, (-nx, -ny))
    return entries, count - item


# --- on a surface -------------------------------------------------------------


def _overlaps(one: Box, two: Box) -> bool:
    """Separating-axis test for two oriented boxes."""
    corners_one, corners_two = one.corners(), two.corners()
    for box in (one, two):
        for degrees in (box.rotation_deg, box.rotation_deg + 90.0):
            ax, ay = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
            p1 = [x * ax + y * ay for x, y in corners_one]
            p2 = [x * ax + y * ay for x, y in corners_two]
            if max(p1) <= min(p2) or max(p2) <= min(p1):
                return False
    return True


def plan_on_surface(
    surface: Box,
    arts: list[Art],
    count: int,
    *,
    margin: float,
    rng: random.Random,
    turn: float = DRESSING_ROTATION,
) -> tuple[list[dict], int]:
    """Items set inside a surface's drawn area, not overlapping each other.

    Every corner of each item's drawn area stays at least `margin` inside the
    surface's. Returns the entries and how many items found no room.
    """
    inner_w = surface.half_w - margin
    inner_h = surface.half_h - margin
    if inner_w <= 0 or inner_h <= 0:
        raise LayoutError(f"the surface is too small for a {margin:g}-woxel margin")
    entries: list[dict] = []
    boxes: list[Box] = []
    for art in sequence(arts, count):
        for attempt in range(DRESSING_TRIES):
            # Turn less on each retry: on a tight surface only a straight item fits.
            reach = turn * (1.0 - attempt / (DRESSING_TRIES - 1))
            local_turn = rng.uniform(-reach, reach)
            # Centres only where the turned item stays inside.
            cos_t, sin_t = (
                abs(math.cos(math.radians(local_turn))),
                abs(math.sin(math.radians(local_turn))),
            )
            room_x = inner_w - (art.width * cos_t + art.height * sin_t) / 2.0
            room_y = inner_h - (art.width * sin_t + art.height * cos_t) / 2.0
            if room_x < 0 or room_y < 0:
                continue
            local_x = rng.uniform(-room_x, room_x)
            local_y = rng.uniform(-room_y, room_y)
            candidate = Box(local_x, local_y, art.width / 2.0, art.height / 2.0, local_turn)
            if any(abs(x) > inner_w or abs(y) > inner_h for x, y in candidate.corners()):
                continue
            if any(_overlaps(candidate, other) for other in boxes):
                continue
            boxes.append(candidate)
            wx, wy = _rotate(local_x, local_y, surface.rotation_deg)
            rotation = surface.rotation_deg + local_turn
            entries.append(placement(art, surface.cx + wx, surface.cy + wy, rotation))
            break
    return entries, count - len(entries)


def dressing_layer(surface_layer: int, requested: int | None, patch_loaded: bool) -> int:
    """The layer dressing goes on: above the surface, never on it.

    One layer up by default. 900 is the top vanilla layer, so dressing for a
    surface there goes to 1100 (Above Lights) only while the Unofficial Patch
    is loaded, and is refused otherwise.
    """
    if requested is not None:
        if requested <= surface_layer:
            raise LayoutError(
                f"layer {requested} is not above the surface's layer {surface_layer}; "
                "dressing on or under its surface is hidden by it"
            )
        if requested == 1100 and not patch_loaded:
            raise LayoutError("layer 1100 exists only while the Unofficial Patch is loaded")
        return requested
    if surface_layer < 900:
        return surface_layer + 100
    if surface_layer < 1100 and patch_loaded:
        return 1100
    raise LayoutError(
        f"the surface is on layer {surface_layer}, the top layer this map has; "
        "move it down a layer with modify_object first"
    )


def orientation_notes(arts: list[Art], facing: str, mode: str) -> list[str]:
    """Advice when an asset's shape suggests the facing assumption is wrong.

    A shelf or bench is wider than it is deep. One drawn deeper than wide in
    the assumed facing is likely drawn side-on.
    """
    if mode != "along_wall":
        return []
    notes = []
    for art in {art.asset: art for art in arts}.values():
        if art.depth(facing) > 1.3 * art.across(facing):
            notes.append(
                f"{art.asset.rsplit('/', 1)[-1]} is drawn deeper than wide when facing "
                f"{facing}, so it may be drawn side-on; look, and pass the facing it has"
            )
    return notes
