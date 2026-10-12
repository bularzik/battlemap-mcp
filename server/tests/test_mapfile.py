"""The maps are built here in the shape Dungeondraft 1.2 saves, so no real map
has to be checked in.
"""

from __future__ import annotations

import json

import pytest

from battlemap_mcp import mapfile, server

PACK = "res://packs/AbC123/textures"


def _splat(width, height, rgba):
    """A splat literal: RGBA bytes at 4 pixels per tile, every pixel alike."""
    return "PoolByteArray( " + ", ".join(map(str, list(rgba) * (width * 4 * height * 4))) + " )"


def _map(**level_overrides):
    level = {
        "label": "Ground",
        "environment": {"baked_lighting": True, "ambient_light": "ff808080"},
        "walls": [
            {
                "points": "PoolVector2Array( 0, 0, 512, 0 )",
                "texture": "res://textures/walls/stone.png",
                "loop": False,
                "portals": [
                    {"texture": "res://textures/portals/door_01.png", "closed": False},
                    {"texture": "res://textures/portals/window_02.png", "closed": False},
                ],
            }
        ],
        "portals": [],
        "objects": [
            {"texture": f"{PACK}/objects/tree.png", "scale": "Vector2( 2, 2 )", "layer": 300},
            {"texture": f"{PACK}/objects/tree.png", "scale": "Vector2( 2.2, 2.2 )", "layer": 300},
            {
                "texture": "res://textures/objects/rock.png",
                "scale": "Vector2( 1, 1 )",
                "layer": 100,
            },
            {"texture": "res://packs/Gone99/textures/objects/log.png", "scale": "Vector2( 1, 1 )"},
        ],
        "paths": [
            {"texture": f"{PACK}/paths/cliff.png", "width": 256, "layer": 200},
            {"texture": "res://textures/paths/lip.png", "width": 308, "layer": 100},
        ],
        "lights": [{"range": 9, "texture": "res://textures/lights/soft.png"}],
        "terrain": {
            "enabled": "True",
            "expand_slots": "False",
            "texture_1": "res://textures/terrain/terrain_snow.png",
            "texture_2": "res://textures/terrain/terrain_gravel.png",
            "splat": _splat(2, 1, (192, 64, 0, 0)),
        },
        "materials": {
            "-400": [
                {
                    "texture": "res://textures/materials/ice_tile.png",
                    "bitmap": "PoolByteArray( 1, 0, 0, 1 )",
                }
            ]
        },
        "water": {"tree": {"children": [{"deep_color": "ff000000"}]}},
        "patterns": [],
        "texts": [],
    }
    level.update(level_overrides)
    return {
        "header": {
            "creation_build": "1.2.0.1",
            "asset_manifest": [
                {"id": "AbC123", "name": "Forest Pack", "version": "1"},
                {"id": "Miss42", "name": "Missing Pack", "version": "2"},
            ],
            "editor_state": {"trace_image": {"image": "/nowhere/trace-x-1x1.jpg"}},
        },
        "world": {"width": 2, "height": 1, "levels": {"0": level}},
    }


INSTALLED = {"AbC123": "Forest Pack"}


def test_packs_installed_missing_and_not_included():
    s = mapfile.summarise(_map(), INSTALLED)
    by_name = {p["name"]: p for p in s["packs"]}
    assert by_name["Forest Pack"]["installed"] and by_name["Forest Pack"]["elements_using_it"] == 3
    assert s["packs_missing"] == ["Missing Pack"]
    # A texture from a pack the header does not include is dropped on load.
    assert s["packs_used_but_not_included"] == {"Gone99": 1}
    text = " ".join(s["warnings"])
    assert "Missing Pack" in text and "Gone99" in text and "its trace image" in text


def test_what_a_render_cannot_show():
    (level,) = mapfile.summarise(_map(), INSTALLED)["levels"]
    assert level["counts"]["water_bodies"] == 1
    assert level["ambient_light"] == "ff808080"
    shares = {s["texture"].split("/")[-1]: s["share"] for s in level["terrain"]["slots"]}
    assert shares == {"terrain_snow.png": 0.75, "terrain_gravel.png": 0.25}
    assert level["materials"] == [
        {"layer": -400, "texture": "res://textures/materials/ice_tile.png", "coverage": 0.5}
    ]
    cliff, lip = level["paths"]
    assert (cliff["widths"], cliff["layers"], lip["widths"]) == ([256.0], [200], [308.0])
    tree = level["objects"][0]
    assert tree["count"] == 2 and tree["scale"] == {"min": 2.0, "median": 2.1, "max": 2.2}
    assert level["lights"]["range"] == {"min": 9.0, "max": 9.0}


def test_reversed_doors_and_windows_are_counted():
    """Runtime behavior and validation."""
    s = mapfile.summarise(_map(), INSTALLED)
    portals = s["levels"][0]["portals"]
    assert (portals["doors"], portals["windows"], portals["vtt_reversed"]) == (1, 1, 1)
    assert any("act as the other" in w for w in s["warnings"])


def test_a_splat_of_the_wrong_size_is_not_misread():
    raw = _map()
    raw["world"]["levels"]["0"]["terrain"]["splat"] = "PoolByteArray( 1, 2, 3 )"
    slots = mapfile.summarise(raw, INSTALLED)["levels"][0]["terrain"]["slots"]
    assert all(slot["share"] == 0.0 for slot in slots)


def test_comparing_a_rebuild_with_its_original():
    original = mapfile.summarise(_map(), INSTALLED)
    rebuilt_raw = _map(
        objects=[
            {"texture": f"{PACK}/objects/tree.png", "scale": "Vector2( 1, 1 )"},
            {"texture": "res://textures/objects/bush.png", "scale": "Vector2( 1, 1 )"},
        ],
        materials={},
    )
    rebuilt_raw["world"]["levels"]["0"]["terrain"]["splat"] = _splat(2, 1, (128, 128, 0, 0))
    diff = mapfile.compare(original, mapfile.summarise(rebuilt_raw, INSTALLED))
    (level,) = diff["levels"]
    assert level["count_changes"] == {"objects": -2}
    assert level["objects_only_in_second"] == ["res://textures/objects/bush.png"]
    assert f"{PACK}/objects/tree.png" in [c["texture"] for c in level["scale_changes"]]
    assert level["terrain_share_changes"] == {
        "res://textures/terrain/terrain_gravel.png": 0.25,
        "res://textures/terrain/terrain_snow.png": -0.25,
    }


def test_not_a_map_is_a_validation_error(tmp_path, monkeypatch):
    monkeypatch.setattr(server.pack_contents, "discover", lambda folder: {"packs": {}})
    notes = tmp_path / "notes.dungeondraft_map"
    notes.write_text("{not json")
    with pytest.raises(server.ValidationError, match="not a Dungeondraft map"):
        server.inspect_map_file(str(notes))
    notes.write_text(json.dumps({"header": {}}))
    with pytest.raises(server.ValidationError, match="no 'world'"):
        server.inspect_map_file(str(notes))


def test_the_tool_reads_both_maps_and_never_the_bridge(tmp_path, monkeypatch):
    class Pack:
        info = {"name": "Forest Pack"}

    monkeypatch.setattr(server.pack_contents, "assets_directory", lambda: tmp_path)
    monkeypatch.setattr(
        server.pack_contents, "discover", lambda folder: {"packs": {"AbC123": Pack()}}
    )
    monkeypatch.setattr(
        server.bridge, "request", lambda *a, **k: pytest.fail("inspection needs no bridge")
    )
    first, second = tmp_path / "a.dungeondraft_map", tmp_path / "b.dungeondraft_map"
    first.write_text(json.dumps(_map()))
    second.write_text(json.dumps(_map(lights=[])))
    result = server.inspect_map_file(str(first), compare_to=str(second))
    assert result["packs_missing"] == ["Missing Pack"]
    assert result["comparison"]["levels"][0]["count_changes"] == {"lights": -1}


def test_a_machine_without_a_pack_folder_still_gets_a_summary(tmp_path, monkeypatch):
    """1.3 on a fresh Linux install: with no asset folder in config.ini the
    whole inspection failed, though only the installed check needs it."""

    def no_folder():
        raise server.ValidationError("Dungeondraft has no asset pack folder set")

    monkeypatch.setattr(server.pack_contents, "assets_directory", no_folder)
    target = tmp_path / "a.dungeondraft_map"
    target.write_text(json.dumps(_map()))
    result = server.inspect_map_file(str(target))
    assert [p["installed"] for p in result["packs"]] == [None, None]
    assert result["packs_missing"] == []
    assert result["levels"][0]["counts"]["lights"] == 1
    assert any("no asset pack folder" in w for w in result["warnings"]), result["warnings"]


def test_get_terrain_passes_render_and_at_to_the_bridge(monkeypatch):
    """The bridge's render diagnostic was unreachable from the MCP tool."""
    sent = []
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **kw: sent.append(kw) or {})
    server.get_terrain(samples=4)
    server.get_terrain(samples=4, render=True, at=[100, 200])
    assert "render" not in sent[0]
    assert sent[1]["render"] is True and sent[1]["at"] == [100, 200]


@pytest.mark.parametrize(
    "image",
    [
        r"\\attacker\share\t.jpg",
        "//attacker/share/t.jpg",
        r"/\attacker\share\t.jpg",
        r"\\?\UNC\attacker\share\t.jpg",
        r"\\.\UNC\attacker\share\t.jpg",
        r" \\attacker\share\t.jpg",
        "file://attacker/share/t.jpg",
        "relative/t.jpg",
        "C:t.jpg",
        r"\Users\t.jpg",
        "C:\\ok\x00.jpg",
    ],
)
def test_a_non_local_trace_path_is_reported_never_opened(image, monkeypatch):
    """A map someone sent can name a UNC trace path; on Windows, checking that
    it exists connects to the host and offers the user's NTLM credentials.
    Only a plain local absolute path is checked; every other form is listed."""
    touched = []
    monkeypatch.setattr(mapfile.Path, "exists", lambda self: touched.append(self) or False)
    raw = _map()
    raw["header"]["editor_state"] = {"trace_image": {"image": image}}
    summary = mapfile.summarise(raw, {})
    assert touched == []
    assert summary["trace_image"] == image
    assert any("not a local path" in w and "not checked" in w for w in summary["warnings"])


def test_a_local_trace_path_is_still_checked(tmp_path):
    raw = _map()
    present = tmp_path / "trace.jpg"
    present.write_bytes(b"x")
    for image, missing in ((str(present), False), (str(tmp_path / "gone.jpg"), True)):
        raw["header"]["editor_state"] = {"trace_image": {"image": image}}
        warnings = mapfile.summarise(raw, {})["warnings"]
        assert any("trace image is missing" in w for w in warnings) is missing, warnings
