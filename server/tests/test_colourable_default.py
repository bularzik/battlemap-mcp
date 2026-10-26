"""Colourable objects placed without a colour get Dungeondraft's default.

The mod picks the colour, because only it knows an asset's mask before placing.
The server forwards `color` only when the caller gives one and documents the
default; these tests pin that contract.
"""

from __future__ import annotations

import pytest

from battlemap_mcp import server

DEFAULT = "#6b3834"


@pytest.fixture
def sent(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def request(command, **params):
        calls.append((command, params))
        if command == "place_objects":
            return {
                "objects": [{"id": 1, "position": [0, 0], "color_defaulted": True}],
                "ids": [1],
                "color_defaulted": 1,
            }
        return {"id": 1, "position": [0, 0], "color": DEFAULT, "color_defaulted": True}

    monkeypatch.setattr(server.bridge, "request", request)
    monkeypatch.setattr(server, "_SCATTERED", set())
    return calls


def test_list_assets_documents_the_default():
    assert DEFAULT in server.list_assets.__doc__


@pytest.mark.parametrize("tool", [server.place_object, server.place_objects])
def test_docs_promise_the_default(tool):
    doc = tool.__doc__
    assert DEFAULT in doc
    assert "color_defaulted" in doc


def test_explicit_colour_unchanged(sent):
    server.place_object("res://a.png", x=0, y=0, color="#123456")
    [(_, params)] = [c for c in sent if c[0] == "place_object"]
    assert params["color"] == "#123456"


def test_no_colour_is_added_by_the_server(sent):
    result = server.place_object("res://a.png", x=0, y=0)
    [(_, params)] = [c for c in sent if c[0] == "place_object"]
    assert "color" not in params
    assert result["color_defaulted"] is True
