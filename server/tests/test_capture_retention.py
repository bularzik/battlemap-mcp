"""Retention may remove only capture files this server names."""

import io
import os

from PIL import Image

from battlemap_mcp import server


def image_bytes():
    output = io.BytesIO()
    Image.new("RGB", (8, 8), "green").save(output, format="PNG")
    return output.getvalue()


def capture(root, name, timestamp):
    path = root / name
    path.write_bytes(b"capture")
    os.utime(path, ns=(timestamp, timestamp))
    return path


def test_pruning_keeps_the_newest_generated_captures_and_preserves_user_files(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    oldest = capture(tmp_path, f"screenshot-{'a' * 32}.png", 1_000_000_000)
    retained = capture(tmp_path, f"export-{'b' * 32}.webp", 2_000_000_000)
    newest = capture(tmp_path, "asset_preview.png", 3_000_000_000)
    user_file = capture(tmp_path, "holiday.png", 4_000_000_000)
    near_match = capture(tmp_path, f"screenshot-{'c' * 32}.jpg", 5_000_000_000)
    user_dir = tmp_path / f"export-{'d' * 32}.png"
    user_dir.mkdir()

    assert server._prune_captures(keep=2) == 1

    assert not oldest.exists()
    assert retained.exists()
    assert newest.exists()
    assert user_file.exists()
    assert near_match.exists()
    assert user_dir.is_dir()


def test_clear_captures_removes_only_generated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    screenshot = capture(tmp_path, f"screenshot-{'a' * 32}.png", 1)
    export = capture(tmp_path, f"export-{'b' * 32}.jpeg", 2)
    preview = capture(tmp_path, "asset_preview.png", 3)
    user_file = capture(tmp_path, "notes.png", 4)

    assert server.clear_captures()["cleared"] == 3

    assert not screenshot.exists()
    assert not export.exists()
    assert not preview.exists()
    assert user_file.exists()


def test_clear_captures_preserves_a_capture_shaped_symlink(
    tmp_path, monkeypatch, create_file_symlink_or_skip
):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    target = tmp_path / "notes.png"
    target.write_bytes(b"user content")
    link = tmp_path / f"screenshot-{'a' * 32}.png"
    create_file_symlink_or_skip(link, target)

    assert server.clear_captures()["cleared"] == 0

    assert link.is_symlink()
    assert target.read_bytes() == b"user content"


def test_a_successful_screenshot_triggers_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    calls = []

    def request(command, **params):
        path = tmp_path / params["name"]
        path.write_bytes(image_bytes())
        return {"path": str(path)}

    monkeypatch.setattr(server.bridge, "request", request)
    monkeypatch.setattr(server, "_prune_captures", lambda: calls.append(True) or 0)

    server.screenshot()

    assert calls == [True]


def test_successful_preview_and_export_trigger_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    calls = []
    preview = tmp_path / "asset_preview.png"
    export = tmp_path / f"export-{'a' * 32}.png"
    preview.write_bytes(image_bytes())
    export.write_bytes(image_bytes())
    monkeypatch.setattr(server, "_prune_captures", lambda: calls.append(True) or 0)
    monkeypatch.setattr(server.bridge, "request", lambda command, **params: {"path": str(preview)})

    server.preview_assets(["textures/objects/x.png"])
    server._export_image(
        {"state": "completed", "operation_id": "export-1", "path": str(export), "format": "png"}
    )

    assert calls == [True, True]


def test_traces_keep_the_newest_three_and_leave_captures_alone(tmp_path, monkeypatch):
    """Runtime behavior and validation."""
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    traces = [capture(tmp_path, f"trace-{i:016x}.png", 1_000_000_000 + i) for i in range(4)] + [
        capture(tmp_path, "trace-region-832x832.jpg", 2_000_000_000)
    ]
    screenshot = capture(tmp_path, f"screenshot-{'a' * 32}.png", 500)
    lookalike = capture(tmp_path, "trace-notes.txt", 400)

    assert server._prune_traces() == 2
    assert [p.exists() for p in traces] == [False, False, True, True, True]
    assert screenshot.exists() and lookalike.exists()
    # Capture retention never counts or removes a trace.
    assert server._prune_captures(keep=0) == 1
    assert traces[-1].exists()


def test_trace_retention_leaves_a_trace_shaped_symlink(
    tmp_path, monkeypatch, create_file_symlink_or_skip
):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    traces = [capture(tmp_path, f"trace-{i:016x}.png", 1_000_000_000 + i) for i in range(4)]
    screenshot = capture(tmp_path, f"screenshot-{'a' * 32}.png", 500)
    link = tmp_path / "trace-linked-1x1.jpg"
    create_file_symlink_or_skip(link, screenshot)

    assert server._prune_traces() == 1
    assert [p.exists() for p in traces] == [False, True, True, True]
    assert screenshot.exists() and link.is_symlink()


def test_clear_captures_keeps_the_newest_trace(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_capture_root", lambda: tmp_path)
    old = capture(tmp_path, "trace-old-map-10x10.jpg", 1_000_000_000)
    current = capture(tmp_path, "trace-new-map-10x10.jpg", 2_000_000_000)
    shot = capture(tmp_path, f"screenshot-{'a' * 32}.png", 3_000_000_000)
    assert server.clear_captures() == {
        "cleared": 1,
        "traces_cleared": 1,
        "kept_trace": current.name,
    }
    assert current.exists() and not old.exists() and not shot.exists()


def test_a_reused_short_path_trace_counts_as_newest(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("BATTLEMAP_MCP_CAPTURE_DIR", str(out))
    folder = tmp_path
    while len(str(folder)) < server.TRACE_PATH_LIMIT + 10:
        folder = folder / ("d" * 40)
    folder.mkdir(parents=True)
    image = folder / "plan.png"
    image.write_bytes(image_bytes())
    first, _ = server._short_trace_path(str(image))
    os.utime(first, ns=(1, 1))
    for i in range(3):
        capture(out, f"trace-{i:016x}.png", 1_000_000_000 + i)
    again, _ = server._short_trace_path(str(image))
    assert again == first and os.path.exists(first)
