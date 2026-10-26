"""Floors with a red colour mask get the default tint, like greyscale ones.

The rule lives in the mod (it samples the texture); these tests pin the
documented contract the server promises callers.
"""

from __future__ import annotations

from battlemap_mcp import server


def test_place_pattern_documents_red_masks():
    doc = server.place_pattern.__doc__
    assert "red colour mask" in doc
    assert "texture_red_mask" in doc


def test_build_room_documents_default_floor_tint():
    doc = server.build_room.__doc__
    assert "floor_color" in doc and "red colour mask" in doc
