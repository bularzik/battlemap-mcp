"""arrange_objects' layout maths, over synthetic walls, tables and surfaces."""

from __future__ import annotations

import math
import random

import pytest

from battlemap_mcp import layout
from battlemap_mcp.errors import ValidationError
from battlemap_mcp.placement import Box, Segment

# Drawn on 409x169 of a 512x256 canvas, offset up: FA's Shelf_Wood_Light_C.
SHELF = layout.Art("shelf.webp", (512.0, 256.0), (52.0, 44.0, 409.0, 169.0))
CHAIR = layout.Art("chair.webp", (256.0, 256.0), (62.0, 52.0, 132.0, 155.0))
BOOK = layout.Art("book.png", (116.0, 98.0), (0.0, 0.0, 116.0, 98.0))

ROOM = {
    "id": 7,
    "loop": True,
    "points": [[0, 0], [2304, 0], [2304, 1536], [0, 1536]],
    "texture_size": [1024, 67],
}


def test_art_refuses_a_missing_drawn_area_rather_than_using_the_canvas():
    with pytest.raises(layout.LayoutError, match="drawn"):
        layout.art_from("x.png", [256, 256], None)
    with pytest.raises(layout.LayoutError, match="no drawn pixels"):
        layout.art_from("x.png", [256, 256], [0, 0, 0, 10])


def test_placement_puts_the_drawn_centre_where_asked_at_any_rotation():
    for rotation in (0.0, 90.0, -90.0, 180.0, 33.0):
        entry = layout.placement(SHELF, 1000.0, 500.0, rotation)
        box = layout.drawn_box(SHELF, entry)
        assert box.cx == pytest.approx(1000.0, abs=0.01)
        assert box.cy == pytest.approx(500.0, abs=0.01)
    # At rotation 0 the canvas centre sits below the drawn one: art drawn high.
    assert layout.placement(SHELF, 1000.0, 500.0, 0.0)["y"] == pytest.approx(500.0 - 0.5)


@pytest.mark.parametrize(
    ("facing", "direction", "rotation"),
    [
        ("down", (0, 1), 0.0),
        ("down", (1, 0), -90.0),
        ("down", (-1, 0), 90.0),
        ("down", (0, -1), 180.0),
        ("up", (0, -1), 0.0),
        ("right", (0, 1), 90.0),
    ],
)
def test_rotation_turns_the_front_to_the_direction(facing, direction, rotation):
    assert layout.rotation_to_face(facing, direction) == pytest.approx(rotation)


def test_choose_wall_reports_a_double_wall():
    neighbour = {
        "id": 8,
        "loop": True,
        "points": [[2304, 0], [3304, 0], [3304, 1536], [2304, 1536]],
    }
    choice = layout.choose_wall([ROOM, neighbour], [[2300, 200], [2300, 1300]])
    assert choice.segment.wall_id == 7
    assert choice.others == (8,)
    chosen = layout.choose_wall([ROOM, neighbour], [[2300, 200], [2300, 1300]], wall_id=8)
    assert chosen.segment.wall_id == 8 and chosen.others == (7,)


def test_choose_wall_refuses_a_line_far_from_any_wall_or_crossing_it():
    with pytest.raises(layout.LayoutError, match="no wall"):
        layout.choose_wall([ROOM], [[500, 700], [1500, 700]])
    with pytest.raises(layout.LayoutError, match="no wall"):
        layout.choose_wall([ROOM], [[100, 0], [100, 1400]])  # perpendicular to the top wall
    with pytest.raises(layout.LayoutError, match="wall 99"):
        layout.choose_wall([ROOM], [[0, 0], [2304, 0]], wall_id=99)


def test_inward_normal_from_the_loop_or_from_toward():
    top = layout.choose_wall([ROOM], [[0, 0], [2304, 0]]).segment
    assert layout.inward_normal(top, ROOM, None, 100.0) == pytest.approx((0.0, 1.0))
    left = layout.choose_wall([ROOM], [[0, 100], [0, 1400]]).segment
    assert layout.inward_normal(left, ROOM, None, 100.0) == pytest.approx((1.0, 0.0))
    open_run = {"id": 3, "points": [[0, 0], [1000, 0]]}
    segment = layout.choose_wall([open_run], [[0, 0], [1000, 0]]).segment
    with pytest.raises(layout.LayoutError, match="toward"):
        layout.inward_normal(segment, open_run, None, 100.0)
    assert layout.inward_normal(segment, open_run, [500, -300], 100.0) == pytest.approx((0.0, -1.0))


def test_free_intervals_clear_corners_and_this_walls_doors_only():
    top = layout.choose_wall([ROOM], [[0, 0], [2304, 0]]).segment
    door = {"id": 40, "wall_id": 7, "position": [1000, 0], "radius": 64}
    other = {"id": 41, "wall_id": 99, "position": [1500, 0], "radius": 64}
    far = {"id": 42, "wall_id": 7, "position": [1000, 1536], "radius": 64}
    intervals, kept = layout.free_intervals(
        top, [[0, 0], [2304, 0]], [door, other, far], half_thickness=33.5, margin=32.0
    )
    assert kept == [40]
    assert intervals == [(65.5, 904.0), (1096.0, 2238.5)]


def test_pack_row_spreads_or_centres_and_skips_what_does_not_fit():
    spread = layout.pack_row([(0.0, 1000.0)], [200.0, 200.0], gap=None, fill=False)
    assert [round(s) for _, s in spread] == [300, 700]
    centred = layout.pack_row([(0.0, 1000.0)], [200.0, 200.0], gap=0.0, fill=False)
    assert [round(s) for _, s in centred] == [400, 600]
    # The first stretch is too short for anything; both go to the second.
    split = layout.pack_row([(0.0, 100.0), (200.0, 700.0)], [200.0, 200.0], gap=0, fill=False)
    assert [index for index, _ in split] == [0, 1]
    assert all(s > 200 for _, s in split)
    filled = layout.pack_row([(0.0, 1000.0)], [300.0], gap=None, fill=True)
    assert len(filled) == 3


def test_along_wall_backs_each_drawn_area_against_the_wall_face():
    top = layout.choose_wall([ROOM], [[0, 0], [2304, 0]]).segment
    intervals, _ = layout.free_intervals(
        top, [[0, 0], [2304, 0]], [], half_thickness=33.5, margin=32
    )
    entries, skipped = layout.plan_along_wall(
        [SHELF], top, (0.0, 1.0), intervals, count=3, facing="down", half_thickness=33.5, gap=None
    )
    assert skipped == 0 and len(entries) == 3
    for entry in entries:
        box = layout.drawn_box(SHELF, entry)
        assert entry["rotation"] == 0.0
        assert box.cy - box.half_h == pytest.approx(33.5, abs=0.01)  # flush, not canvas-flush
    left = layout.choose_wall([ROOM], [[0, 100], [0, 1400]]).segment
    intervals, _ = layout.free_intervals(
        left, [[0, 0], [0, 1536]], [], half_thickness=33.5, margin=32
    )
    entries, _ = layout.plan_along_wall(
        [SHELF], left, (1.0, 0.0), intervals, count=1, facing="down", half_thickness=33.5, gap=0
    )
    box = layout.drawn_box(SHELF, entries[0])
    assert entries[0]["rotation"] == pytest.approx(-90.0)
    assert min(x for x, _ in box.corners()) == pytest.approx(33.5, abs=0.01)


def test_along_wall_reports_what_did_not_fit():
    segment = Segment(0, 0, 600, 0, 1)
    entries, skipped = layout.plan_along_wall(
        [SHELF],
        segment,
        (0.0, 1.0),
        [(0.0, 600.0)],
        count=3,
        facing="down",
        half_thickness=10,
        gap=None,
    )
    assert len(entries) == 1 and skipped == 2


def test_around_a_rectangular_table_seats_by_side_length_and_faces_it():
    table = Box(1000.0, 1000.0, 195.0, 101.5, 0.0)
    entries, skipped = layout.plan_around(
        table,
        [CHAIR],
        6,
        shape="rect",
        facing="down",
        clearance=0.0,
        jitter=False,
        rng=random.Random(1),
    )
    assert skipped == 0 and len(entries) == 6
    boxes = [layout.drawn_box(CHAIR, entry) for entry in entries]
    above = [b for b in boxes if b.cy < table.cy - table.half_h]
    assert len(above) == 2  # two on each long side, one at each end
    for box, entry in zip(boxes, entries, strict=True):
        # Each seat's front points at the table centre.
        theta = math.radians(entry["rotation"])
        front = (-math.sin(theta), math.cos(theta))  # (0, 1) turned by the rotation
        to_table = (table.cx - box.cx, table.cy - box.cy)
        assert front[0] * to_table[0] + front[1] * to_table[1] > 0
        assert table.distance_to(box.cx, box.cy) > 0  # not on the table


def test_around_an_end_narrower_than_a_chair_still_takes_one():
    table = Box(0.0, 0.0, 195.0, 101.5, 0.0)
    wide = layout.Art("armchair.png", (256.0, 256.0), (20.0, 32.0, 216.0, 191.0))
    entries, skipped = layout.plan_around(
        table,
        [wide],
        4,
        shape="rect",
        facing="down",
        clearance=0.0,
        jitter=False,
        rng=random.Random(1),
    )
    assert (len(entries), skipped) == (4, 0)


def test_around_a_round_table_rings_it_evenly_with_jitter_kept_small():
    table = Box(0.0, 0.0, 133.0, 133.0, 0.0)
    plain, _ = layout.plan_around(
        table,
        [CHAIR],
        5,
        shape="round",
        facing="down",
        clearance=0.0,
        jitter=False,
        rng=random.Random(1),
    )
    jittered, _ = layout.plan_around(
        table,
        [CHAIR],
        5,
        shape="round",
        facing="down",
        clearance=0.0,
        jitter=True,
        rng=random.Random(1),
    )
    for one, two in zip(plain, jittered, strict=True):
        assert abs(one["rotation"] - two["rotation"]) <= layout.CHAIR_ROTATION_JITTER + 1e-6
        assert math.hypot(one["x"] - two["x"], one["y"] - two["y"]) <= 2 * layout.CHAIR_SHIFT_JITTER
    assert plain[0]["rotation"] == pytest.approx(0.0)  # the first seat, at the top, faces down


def test_table_shape_comes_from_the_name():
    assert layout.table_shape("res://x/round_table_01.png") == "round"
    assert layout.table_shape("res://x/Table_Rectangle_H.webp") == "rect"


def test_on_surface_keeps_items_inside_and_apart():
    desk = Box(500.0, 500.0, 197.0, 101.5, 20.0)
    entries, skipped = layout.plan_on_surface(desk, [BOOK], 2, margin=12.0, rng=random.Random(3))
    assert skipped == 0
    boxes = [layout.drawn_box(BOOK, entry) for entry in entries]
    for box in boxes:
        for x, y in box.corners():
            assert desk.distance_to(x, y) == 0.0
    assert not layout._overlaps(boxes[0], boxes[1])


def test_on_surface_reports_items_with_no_room():
    tiny = Box(0.0, 0.0, 70.0, 60.0, 0.0)
    entries, skipped = layout.plan_on_surface(tiny, [BOOK], 3, margin=4.0, rng=random.Random(3))
    assert len(entries) == 1 and skipped == 2
    with pytest.raises(layout.LayoutError, match="too small"):
        layout.plan_on_surface(tiny, [BOOK], 1, margin=80.0, rng=random.Random(3))


def test_dressing_layer_is_above_the_surface_and_1100_only_with_the_patch():
    assert layout.dressing_layer(100, None, False) == 200
    assert layout.dressing_layer(800, None, False) == 900
    assert layout.dressing_layer(900, None, True) == 1100
    with pytest.raises(layout.LayoutError, match="top layer"):
        layout.dressing_layer(900, None, False)
    with pytest.raises(layout.LayoutError, match="top layer"):
        layout.dressing_layer(1100, None, True)
    with pytest.raises(layout.LayoutError, match="not above"):
        layout.dressing_layer(300, 300, True)
    with pytest.raises(layout.LayoutError, match="Unofficial Patch"):
        layout.dressing_layer(300, 1100, False)


def test_orientation_note_for_art_deeper_than_wide():
    tall = layout.Art("rack.png", (100.0, 300.0), (0.0, 0.0, 100.0, 300.0))
    assert layout.orientation_notes([tall], "down", "along_wall")
    assert not layout.orientation_notes([tall], "left", "along_wall")
    assert not layout.orientation_notes([SHELF], "down", "along_wall")
    assert not layout.orientation_notes([tall], "down", "around")


# --- the tool, over a fake bridge -----------------------------------------------


class FakeBridge:
    def __init__(self, *, sizes=True):
        self.calls: list[tuple[str, dict]] = []
        self.sizes = sizes

    def request(self, command, **params):
        self.calls.append((command, params))
        if command == "list_assets":
            paths = params["only"]
            if not self.sizes:
                return {"assets": paths, "sizes": None, "drawn": None}
            return {
                "assets": paths,
                "sizes": [list(SHELF.canvas)] * len(paths),
                "drawn": [list(SHELF.drawn)] * len(paths),
            }
        if command == "list_elements":
            if params["kind"] == "walls":
                return {"elements": [ROOM], "total": 1}
            return {"elements": [], "total": 0}
        if command == "place_objects":
            objects = params["objects"]
            return {
                "objects": [{"id": 100 + i} for i in range(len(objects))],
                "ids": [100 + i for i in range(len(objects))],
            }
        raise AssertionError(f"unexpected {command}")


def test_tool_places_one_batch_and_reports_the_wall(monkeypatch):
    from battlemap_mcp import server

    fake = FakeBridge()
    monkeypatch.setattr(server, "bridge", fake)
    result = server.arrange_objects(
        mode="along_wall", assets=["shelf.webp"], along=[[0, 0], [2304, 0]], count=2
    )
    placing = [c for c in fake.calls if c[0] == "place_objects"]
    assert len(placing) == 1 and len(placing[0][1]["objects"]) == 2
    assert result["ids"] == [100, 101] and result["wall"]["id"] == 7
    assert result["wall"]["half_thickness"] == 33.5


def test_tool_dry_run_places_nothing(monkeypatch):
    from battlemap_mcp import server

    fake = FakeBridge()
    monkeypatch.setattr(server, "bridge", fake)
    result = server.arrange_objects(
        mode="along_wall", assets=["shelf.webp"], along=[[0, 0], [2304, 0]], dry_run=True
    )
    assert result["dry_run"] and result["objects"]
    assert not [c for c in fake.calls if c[0] == "place_objects"]


def test_tool_refuses_without_drawn_sizes(monkeypatch):
    from battlemap_mcp import server

    monkeypatch.setattr(server, "bridge", FakeBridge(sizes=False))
    with pytest.raises(ValidationError, match="never\\s+the canvas"):
        server.arrange_objects(mode="along_wall", assets=["shelf.webp"], along=[[0, 0], [9, 0]])


def test_tool_turns_layout_errors_into_validation_errors(monkeypatch):
    from battlemap_mcp import server

    monkeypatch.setattr(server, "bridge", FakeBridge())
    with pytest.raises(ValidationError, match="No changes were made"):
        server.arrange_objects(
            mode="along_wall", assets=["shelf.webp"], along=[[900, 700], [1500, 700]]
        )
    with pytest.raises(ValidationError, match="target_id"):
        server.arrange_objects(mode="around", assets=["shelf.webp"])
