"""set_trace_image offset_x/offset_y: move the trace image to line its grid up."""

from __future__ import annotations

import math

import pytest

from battlemap_mcp import server
from battlemap_mcp.errors import ValidationError


@pytest.fixture
def sent(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def request(command, **params):
        calls.append((command, params))
        return {"position": [0, 0]}

    monkeypatch.setattr(server.bridge, "request", request)
    return calls


def trace_params(sent):
    [(command, params)] = sent
    assert command == "set_trace_image"
    return params


def test_offset_is_sent_in_woxels(sent):
    server.set_trace_image(offset_x=-94.7, offset_y=66.6)
    params = trace_params(sent)
    assert params["offset_x"] == -94.7
    assert params["offset_y"] == 66.6


def test_offset_omitted_when_not_given(sent):
    server.set_trace_image(scale=2.0)
    params = trace_params(sent)
    assert "offset_x" not in params and "offset_y" not in params


def test_offset_alone_is_accepted(sent):
    server.set_trace_image(offset_x=10.0)
    assert trace_params(sent) == {"offset_x": 10.0}


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_offset_must_be_finite(sent, bad):
    with pytest.raises(ValidationError):
        server.set_trace_image(offset_y=bad)
    assert sent == []
