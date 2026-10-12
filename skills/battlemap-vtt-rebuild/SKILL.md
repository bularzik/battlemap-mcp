---
name: battlemap-vtt-rebuild
description: Use when rebuilding a Dungeondraft map from a Universal VTT export (.dd2vtt), a rendered image of a map with its walls, doors and lights, when the original .dungeondraft_map is missing.
---

# Rebuild a map from a Universal VTT export

A `.dd2vtt` holds a rendered image of the map plus its walls, doors and
windows, lights and ambient light. It does not record which assets, terrain,
paths or layers drew that image. `import_dd2vtt` rebuilds everything the file
does record, exactly. Everything else is reconstructed by looking: the image
becomes a trace under the map, and you rebuild the art on top of it.

If the user still has the original `.dungeondraft_map`, open that instead. A
rebuild only approximates the art. Run `inspect_map_file` on it first: it
names packs the map uses that are not installed, whose art would be missing.

## 1. Preflight and packs first

Call `ping` and `get_status`. Then read the export with
`import_dd2vtt(path)`. Without `confirm` it changes nothing and reports the
region's size in `tiles`, what it would create and how many sight blockers it
found.

**Choose asset packs before importing.** A map's packs are fixed when it is
created, so a rebuild that later needs a pack starts again in a copy. Look at
the trace image, or ask the user what the map was built with. Check
Dungeondraft's own library first (`list_assets`, `preview_assets`): much
published art is built from it, and if it matches, keep the map you have and
include no packs. Otherwise run `search_pack_contents` for the distinctive
pieces you can see (a well, a fallen log, a cliff edge), and `preview_assets`
to compare candidates with the image; a pack the map lacks can still be
previewed. Then make the working map with `prepare_map_with_packs` and only
the packs the art needs.

Build on a new map. Doors mount on the nearest wall, so existing walls would
capture them.

## 2. Import the structure

Show the user the preview, then call `import_dd2vtt(path, confirm=true)`,
adding `resize=true` if the map is not the export's size. Walls, doors and
windows, lights and ambient light are now exact. A region export lands at the
map's origin with everything outside the region left out.

The export has no door/window field: a VTT treats `closed: true` as an
openable door and `false` as a window, so the import uses `portal_asset` for
closed portals and `window_asset` for open ones, keeping `closed` as written.
A source map that had them reversed comes in reversed. Fit the whole map in
view (`fit_elements`), take a `screenshot`, and compare each portal with the
trace. Replace a wrong one by deleting it and calling `add_portal` with the
right asset and no `closed`, then run `validate_floorplan`: its
`vtt_reversed_portals` lists any door still open or window still closed.

`checkpoint` and save before the art pass: `rollback_checkpoint("import_dd2vtt")`
undoes the import itself, not what you build on it.

## 3. Rebuild the art over the trace

Work from the ground up. The export's image is your reference for taste, so
instead of the [build loop](../_shared/build-loop.md)'s region-at-a-time
dressing, you can work in whole-map passes, one kind of thing per pass,
checking each against the image.

1. **Ground.** Match the terrain mix you see with `fill_region` and
   `paint_terrain`. Textured ground, such as gravel, pebbles, rocky soil or
   leaf litter, is a terrain slot, not hundreds of small objects. Fill rates
   add up and a blend reads like a threshold, not a slider: raise a slot in
   small steps and look after each. A flat-coloured area with no shoreline,
   ripples or depth gradient is usually a material (`paint_material`: ice,
   mud, lava, a stone floor), not water. Real water shows a lighter shallow
   edge.
2. **Paths and edges.** Cliffs and walls of rock are often two paths stacked:
   a dark face path over a lighter lip path that shows along its edge. Draw
   both, the lip on the lower layer, when the image shows a two-tone edge.
   Without a matching pair, a single cliff path plus a shadow path offset
   toward the low side is the closest stand-in; say so in your report.
3. **One scale number for the whole map.** Find one clearly isolated object,
   such as a tree or a boulder. Place a candidate at scale 1 on it, read its
   `opaque_bounds` with `get_element`, and find the scale that matches the
   trace. Most maps use one scale number throughout, often well above 1, and
   it is the NUMBER that repeats, not the size: variants of one asset differ
   in native size (one pine is four times another's pixels), and the original
   placed them all at about the same scale. Use that number for every variant
   rather than fitting each to the trace. Fitting each canopy separately
   splits one large tree into a cluster of small ones.
4. **Sight blockers.** `import_dd2vtt` returns `blockers`: each outline's
   `center`, `rotation`, `length` and `width` in woxels; `rotation` is the
   long axis's angle from +x, 0-180. Each one is a boulder, pillar or similar
   solid object. Place one on each with `place_objects` at that position,
   turned so the asset's own long side follows that axis (add 90 for art that
   is taller than it is wide), scaled so its `opaque_bounds` covers the
   outline, with `block_light: true`. These are the
   objects whose positions the export records exactly, so match them first.
5. **Everything else.** Trees, furniture and scatter, matched by eye. Use
   `scatter_objects` for incidental detail rather than placing it piece by
   piece.
6. **Layers.** Things that sit under a cliff or bridge go on low layers
   (-400 or so). Snow, canopy and overhangs go high. Check a doubtful object
   with the trace hidden.

## 4. Verify against the source

The trace includes the original's baked lighting, so judge colour and light
without it. Every few regions:

- `export_map` at the export's pixels-per-grid (or a fraction of it) and
  compare it with the source image side by side. Exports leave the trace
  out; for a `screenshot`, hide it first with `set_trace_image(opacity=0)`;
- if a map built from the same source exists (an earlier version, a sibling
  region), `inspect_map_file(your_map, compare_to=that_map)` compares terrain
  shares, materials, paths and object scales without opening it;
- name the differences that matter at the table: a wrong material, a missing
  blocker, a tree mass broken into pieces. Fix at most three at a time, then
  look again, as the [visual review](../battlemap-visual-review/SKILL.md)
  describes.

Finish with `set_trace_image(clear=true)` before the final `save_map`. The
trace path saves with the map and is broken on anyone else's machine.

## What to tell the user

Say what came back exactly (walls, doors, lights) and what was rebuilt by eye
(the art), with the packs you used. Name any part of the image you could not
match, rather than covering it with something close.
