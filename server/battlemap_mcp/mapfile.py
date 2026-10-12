"""A map file is JSON whose values hold Godot literals as strings:
`Vector2( x, y )`, `PoolVector2Array( ... )`, `PoolByteArray( ... )`. This
module reads only what a summary needs and never writes.

What it is for, measured on real maps:

Terrain weights are `splat` and `splat2`: raw RGBA bytes at 4 pixels per
tile, one channel per slot (slots 1-4, then 5-8). A 48x27 map's splat is
48*4 * 27*4 * 4 = 82,944 bytes, which is what Snow Pass holds.
"""

from __future__ import annotations

import json
import os
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .floorplan import portal_role, vtt_closed

PACK_PATH = re.compile(r"res://packs/([A-Za-z0-9]+)/")
NUMBER = re.compile(r"-?\d+(?:\.\d+)?(?:e-?\d+)?")
# Lists are cut to this many entries; counts stay whole.
TOP = 25


class MapFileError(ValueError):
    """The file is not a Dungeondraft map this module can read."""


def load(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MapFileError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise MapFileError(f"{path.name} is not a Dungeondraft map (not valid JSON)") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("world"), dict):
        raise MapFileError(f"{path.name} has no 'world'; is it a .dungeondraft_map?")
    return raw


def _numbers(literal: Any) -> list[float]:
    """The numbers inside a Godot literal such as `Vector2( 1, 2 )`."""
    if isinstance(literal, int | float) and not isinstance(literal, bool):
        return [float(literal)]
    if not isinstance(literal, str) or "(" not in literal:
        return []
    return [float(n) for n in NUMBER.findall(literal.split("(", 1)[1])]


def _bytes(literal: Any) -> bytes:
    if not isinstance(literal, str) or "(" not in literal:
        return b""
    return bytes(int(n) & 0xFF for n in re.findall(r"\d+", literal.split("(", 1)[1]))


def _scale(value: Any) -> float:
    numbers = _numbers(value)
    return round(max(numbers), 3) if numbers else 1.0


def _texture(element: Any) -> str:
    return str(element.get("texture", "")) if isinstance(element, dict) else ""


def _list(level: dict, key: str) -> list[dict]:
    value = level.get(key)
    return [e for e in value if isinstance(e, dict)] if isinstance(value, list) else []


def _levels(world: dict) -> list[tuple[str, dict]]:
    levels = world.get("levels")
    if isinstance(levels, dict):
        return [(str(k), v) for k, v in levels.items() if isinstance(v, dict)]
    if isinstance(levels, list):
        return [(str(i), v) for i, v in enumerate(levels) if isinstance(v, dict)]
    return []


def _wall_portals(level: dict) -> list[dict]:
    found: list[dict] = []
    for wall in _list(level, "walls"):
        mounted = wall.get("portals")
        if isinstance(mounted, list):
            found.extend(p for p in mounted if isinstance(p, dict))
    return found


def _layers(items: list[dict]) -> list[int]:
    return sorted({int(i["layer"]) for i in items if isinstance(i.get("layer"), int | float)})


def _terrain(level: dict, width: int, height: int) -> dict[str, Any] | None:
    terrain = level.get("terrain")
    if not isinstance(terrain, dict) or str(terrain.get("enabled")).lower() == "false":
        return None
    sums = [0] * 8
    expected = width * 4 * height * 4 * 4
    for offset, key in ((0, "splat"), (4, "splat2")):
        data = _bytes(terrain.get(key))
        if len(data) != expected:
            continue
        for channel in range(4):
            sums[offset + channel] = sum(data[channel::4])
    total = sum(sums)
    slots = []
    for index in range(8):
        texture = terrain.get(f"texture_{index + 1}")
        if not texture and not sums[index]:
            continue
        slots.append(
            {
                "slot": index,
                "texture": texture,
                "share": round(sums[index] / total, 3) if total else 0.0,
            }
        )
    return {"expand_slots": str(terrain.get("expand_slots")).lower() == "true", "slots": slots}


def _materials(level: dict) -> list[dict]:
    materials = level.get("materials")
    rows = []
    if isinstance(materials, dict):
        for layer, entries in materials.items():
            for entry in entries if isinstance(entries, list) else []:
                if not isinstance(entry, dict):
                    continue
                bitmap = _bytes(entry.get("bitmap"))
                rows.append(
                    {
                        "layer": int(layer) if str(layer).lstrip("-").isdigit() else layer,
                        "texture": _texture(entry),
                        "coverage": round(sum(1 for b in bitmap if b) / len(bitmap), 3)
                        if bitmap
                        else None,
                    }
                )
    return rows


def _water_bodies(node: Any) -> int:
    if isinstance(node, dict):
        own = 1 if "deep_color" in node else 0
        return own + sum(_water_bodies(v) for v in node.values())
    if isinstance(node, list):
        return sum(_water_bodies(v) for v in node)
    return 0


def _objects(level: dict) -> list[dict]:
    by_texture: dict[str, list[dict]] = defaultdict(list)
    for obj in _list(level, "objects"):
        by_texture[_texture(obj)].append(obj)
    rows = []
    for texture, items in sorted(by_texture.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        scales = [_scale(o.get("scale")) for o in items]
        rows.append(
            {
                "texture": texture,
                "count": len(items),
                "scale": {
                    "min": min(scales),
                    "median": round(statistics.median(scales), 3),
                    "max": max(scales),
                },
                "layers": _layers(items),
            }
        )
    return rows


def _paths(level: dict) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for path in _list(level, "paths"):
        grouped[_texture(path)].append(path)
    return [
        {
            "texture": texture,
            "count": len(items),
            "widths": sorted({round(float(p.get("width", 1) or 1), 3) for p in items}),
            "layers": _layers(items),
        }
        for texture, items in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]


def _portals(level: dict) -> dict[str, Any]:
    portals = _wall_portals(level) + _list(level, "portals")
    roles = Counter(portal_role(_texture(p)) for p in portals)
    reversed_ = sum(
        1
        for p in portals
        if portal_role(_texture(p)) != "opening"
        and isinstance(p.get("closed"), bool)
        and p["closed"] != vtt_closed(_texture(p))
    )
    return {
        "count": len(portals),
        "doors": roles["door"],
        "windows": roles["window"],
        "openings": roles["opening"],
        "vtt_reversed": reversed_,
    }


def _lights(level: dict) -> dict[str, Any]:
    lights = _list(level, "lights")
    ranges = [float(x["range"]) for x in lights if isinstance(x.get("range"), int | float)]
    return {
        "count": len(lights),
        "range": {"min": min(ranges), "max": max(ranges)} if ranges else None,
        "textures": dict(Counter(_texture(x) for x in lights).most_common(TOP)),
    }


def _pack_use(raw: dict) -> Counter:
    """How many textures in the world point into each pack, by pack id."""
    found: Counter = Counter()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str) and "res://packs/" in node:
            for pack_id in PACK_PATH.findall(node):
                found[pack_id] += 1

    walk(raw.get("world"))
    return found


# A plain local absolute path, never with a second separator after the first
# and never with a NUL. On Windows it needs its drive letter: a rooted path
# without one (a backslash-rooted path, or a macOS map's slash-rooted one) resolves against
# the working directory's drive, which can itself be a \\host\share.
_LOCAL_PATH = re.compile(
    r"[A-Za-z]:[\\/](?![\\/])[^\x00]*" if os.name == "nt" else r"/(?!/)[^\\\x00]*"
)


def _local_path(path: str) -> bool:
    """Whether a path a map names may be checked on disk.

    A map can come from anyone, and on Windows merely checking a UNC path
    connects to its host and offers the user's NTLM credentials. Windows
    reads many spellings as UNC (`\\\\h`, `//h`, `/\\h`, `\\\\?\\UNC\\h`), so
    only the plain local form is allowed; anything else is reported unchecked.
    """
    return _LOCAL_PATH.fullmatch(path) is not None


def summarise(
    raw: dict, installed: dict[str, str] | None, path: Path | None = None
) -> dict[str, Any]:
    """The summary of a parsed map; `installed` maps pack id to pack name, or
    is None when the installed packs are unknown (each pack's `installed` is
    then None and none is reported missing)."""
    header: dict[str, Any] = raw["header"] if isinstance(raw.get("header"), dict) else {}
    world = raw["world"]
    width, height = int(world.get("width") or 0), int(world.get("height") or 0)
    manifest = [p for p in header.get("asset_manifest") or [] if isinstance(p, dict)]
    use = _pack_use(raw)
    included = {str(p.get("id")) for p in manifest}
    packs: list[dict[str, Any]] = [
        {
            "id": p.get("id"),
            "name": p.get("name"),
            "version": p.get("version"),
            "installed": None if installed is None else str(p.get("id")) in installed,
            "elements_using_it": use.get(str(p.get("id")), 0),
        }
        for p in manifest
    ]
    missing: list[dict[str, Any]] = [p for p in packs if p["installed"] is False]
    not_included = {pid: n for pid, n in use.items() if pid not in included}
    editor: dict[str, Any] = (
        header["editor_state"] if isinstance(header.get("editor_state"), dict) else {}
    )
    trace: dict[str, Any] = (
        editor["trace_image"] if isinstance(editor.get("trace_image"), dict) else {}
    )
    trace_path = trace.get("image") if isinstance(trace.get("image"), str) else ""

    levels: list[dict[str, Any]] = []
    for level_id, level in _levels(world):
        objects = _objects(level)
        levels.append(
            {
                "id": level_id,
                "label": level.get("label"),
                "counts": {
                    "objects": len(_list(level, "objects")),
                    "walls": len(_list(level, "walls")),
                    "portals": len(_wall_portals(level)) + len(_list(level, "portals")),
                    "lights": len(_list(level, "lights")),
                    "paths": len(_list(level, "paths")),
                    "patterns": len(_list(level, "patterns")),
                    "texts": len(_list(level, "texts")),
                    "water_bodies": _water_bodies(level.get("water")),
                },
                "ambient_light": (level.get("environment") or {}).get("ambient_light")
                if isinstance(level.get("environment"), dict)
                else None,
                "terrain": _terrain(level, width, height),
                "materials": _materials(level),
                "paths": _paths(level)[:TOP],
                "objects": objects[:TOP],
                "object_kinds": len(objects),
                "portals": _portals(level),
                "lights": _lights(level),
            }
        )

    warnings = []
    if missing:
        warnings.append(
            "packs this map uses are not installed; their "
            f"{sum(int(p['elements_using_it']) for p in missing)} element(s) will be missing: "
            + ", ".join(str(p["name"]) for p in missing)
        )
    if not_included:
        warnings.append(
            "elements use packs the map does not include and are dropped when it is "
            f"opened: {sum(not_included.values())} from {', '.join(sorted(not_included))}"
        )
    reversed_total = sum(int(level["portals"]["vtt_reversed"]) for level in levels)
    if reversed_total:
        warnings.append(
            f"{reversed_total} door(s) or window(s) will act as the other in a VTT export "
            "(a door left open or a window closed)"
        )
    if trace_path and not _local_path(trace_path):
        warnings.append(f"its trace image is not a local path (not checked): {trace_path}")
    elif trace_path and not Path(trace_path).exists():
        warnings.append(f"its trace image is missing: {trace_path}")

    return {
        "file": str(path) if path else None,
        "built_with": header.get("creation_build"),
        "size_tiles": [width, height],
        "level_count": len(levels),
        "packs": packs,
        "packs_missing": [p["name"] for p in missing],
        "packs_used_but_not_included": not_included,
        "trace_image": trace_path or None,
        "levels": levels,
        "warnings": warnings,
    }


def compare(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    """What changed from `first` to `second`, level by level, from two summaries."""
    out_levels = []
    by_id = {level["id"]: level for level in second["levels"]}
    for level in first["levels"]:
        other = by_id.get(level["id"])
        if other is None:
            out_levels.append({"id": level["id"], "missing_in_second": True})
            continue
        counts = {
            k: other["counts"].get(k, 0) - v
            for k, v in level["counts"].items()
            if other["counts"].get(k, 0) != v
        }
        mine = {o["texture"]: o for o in level["objects"]}
        theirs = {o["texture"]: o for o in other["objects"]}
        terrain_a = {s["texture"]: s["share"] for s in (level["terrain"] or {}).get("slots", [])}
        terrain_b = {s["texture"]: s["share"] for s in (other["terrain"] or {}).get("slots", [])}
        out_levels.append(
            {
                "id": level["id"],
                "count_changes": counts,
                "objects_only_in_first": sorted(set(mine) - set(theirs))[:TOP],
                "objects_only_in_second": sorted(set(theirs) - set(mine))[:TOP],
                "scale_changes": [
                    {
                        "texture": t,
                        "first": mine[t]["scale"]["median"],
                        "second": theirs[t]["scale"]["median"],
                    }
                    for t in sorted(set(mine) & set(theirs))
                    if mine[t]["scale"]["median"] != theirs[t]["scale"]["median"]
                ][:TOP],
                "terrain_share_changes": {
                    t: round(terrain_b.get(t, 0.0) - terrain_a.get(t, 0.0), 3)
                    for t in sorted(set(terrain_a) | set(terrain_b))
                    if abs(terrain_b.get(t, 0.0) - terrain_a.get(t, 0.0)) >= 0.01
                },
                "paths_only_in_first": sorted(
                    {p["texture"] for p in level["paths"]} - {p["texture"] for p in other["paths"]}
                ),
                "paths_only_in_second": sorted(
                    {p["texture"] for p in other["paths"]} - {p["texture"] for p in level["paths"]}
                ),
            }
        )
    return {
        "size_tiles": [first["size_tiles"], second["size_tiles"]],
        "packs_only_in_first": sorted(
            {p["name"] for p in first["packs"]} - {p["name"] for p in second["packs"]}
        ),
        "packs_only_in_second": sorted(
            {p["name"] for p in second["packs"]} - {p["name"] for p in first["packs"]}
        ),
        "levels": out_levels,
    }
