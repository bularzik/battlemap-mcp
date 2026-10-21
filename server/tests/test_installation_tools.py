"""Tests for installer actions exposed on the MCP surface."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


def test_install_tool_returns_a_write_free_preview_by_default(monkeypatch, tmp_path):
    """Tool callers must explicitly opt in before the bridge directory is created."""
    from battlemap_mcp import server

    mods_dir = tmp_path / "mods"
    monkeypatch.setattr(server.installer, "default_state_dir", lambda: tmp_path / "state")

    preview = server.install_dungeondraft_bridge(str(mods_dir))

    assert preview["changed"] is False
    assert preview["destination"] == str(mods_dir / "battlemap-mcp-bridge")
    assert not mods_dir.exists()


def test_inspection_separates_historical_log_from_static_files(monkeypatch, tmp_path):
    from battlemap_mcp import server

    dd = tmp_path / "Dungeondraft"
    logs = dd / "logs"
    logs.mkdir(parents=True)
    (logs / "session.log").write_text(
        "Battlemap MCP Bridge mod found in /old/mods/mcp_bridge.ddmod\n"
        "[mcp-bridge] listening on 127.0.0.1:8787 (protocol v23)\n"
    )
    monkeypatch.setattr(server.installer, "dungeondraft_data_dir", lambda: dd)
    monkeypatch.setattr(server.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(server.installer, "candidate_mods_dirs", lambda: [tmp_path / "mods"])

    def forbidden_live_check():
        raise AssertionError("default inspection must not authenticate or contact the bridge")

    monkeypatch.setattr(server.installer, "live_bridge_identity", forbidden_live_check)
    report = server.inspect_dungeondraft_installation()
    assert report["status"] == "missing"
    assert report["latest_log"]["mod_path"] == "/old/mods/mcp_bridge.ddmod"
    assert report["latest_log"]["protocol"] == 23
    assert report["latest_log"]["live_verified"] is False


def test_inspection_opt_in_reports_authenticated_location(monkeypatch, tmp_path):
    from battlemap_mcp import server

    monkeypatch.setattr(server.installer, "dungeondraft_data_dir", lambda: tmp_path)
    monkeypatch.setattr(server.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(server.installer, "candidate_mods_dirs", lambda: [tmp_path / "mods"])
    monkeypatch.setattr(
        server.installer,
        "live_bridge_identity",
        lambda: server.installer.LiveIdentity(
            "current",
            "Matches",
            bridge_root=str(tmp_path / "executing"),
            process_id=123,
        ),
    )
    report = server.inspect_dungeondraft_installation(live=True)
    assert report["live_identity"]["bridge_root"] == str(tmp_path / "executing")
    assert report["live_identity"]["process_id"] == 123
    assert report["latest_log"]["live_verified"] is False


def test_the_tool_replaces_an_installed_bridge_only_when_asked(monkeypatch, tmp_path):
    """An extension or plugin user updates the mod through this tool: there is
    no Connect file or CLI for them to pass --force with."""
    from battlemap_mcp import server

    mods_dir = tmp_path / "mods"
    state = tmp_path / "state"
    monkeypatch.setattr(server.installer, "default_state_dir", lambda: state)
    first = server.install_dungeondraft_bridge(str(mods_dir), confirm=True)
    assert first["changed"] is True
    bridge = mods_dir / "battlemap-mcp-bridge"
    marker = bridge / "old-version.txt"
    marker.write_text("1.1.1")

    preview = server.install_dungeondraft_bridge(str(mods_dir))
    assert preview["requires_force"] is True and "replace=true" in preview["note"]
    refused = server.install_dungeondraft_bridge(str(mods_dir), confirm=True)
    assert "conflict" in refused and marker.exists()

    replaced = server.install_dungeondraft_bridge(str(mods_dir), confirm=True, replace=True)
    assert replaced["changed"] is True
    assert not marker.exists()
    backup = Path(replaced["backup_destination"])
    assert state in backup.parents
    assert (backup / "old-version.txt").read_text() == "1.1.1"
    assert not any(p.name.startswith("battlemap-mcp-bridge.backup") for p in mods_dir.iterdir())


def test_inspection_finds_a_bridge_under_a_development_name(monkeypatch, tmp_path):
    """The 1.2.0 release diagnosis said the bridge was not in the configured
    folder when it was there under the development folder name."""
    from shutil import copytree

    from battlemap_mcp import server

    loaded = tmp_path / "mods"
    fallback = tmp_path / "default-mods"
    copytree(Path(str(server.installer.payload_root())), loaded / "dev-named-bridge")
    copytree(Path(str(server.installer.payload_root())), fallback / "old-bridge")
    monkeypatch.setattr(server.installer, "dungeondraft_data_dir", lambda: tmp_path / "dd")
    monkeypatch.setattr(server.installer, "default_state_dir", lambda: tmp_path / "state")
    monkeypatch.setattr(server.installer, "candidate_mods_dirs", lambda: [loaded, fallback])

    report = server.inspect_dungeondraft_installation()
    assert report["status"] == "healthy"
    assert report["destination"] == str(loaded / "dev-named-bridge")
    assert report["other_copies"] == [
        {"destination": str(fallback / "old-bridge"), "status": "healthy"}
    ]


def _fork_copy(mods_dir: Path, name: str) -> Path:
    """A bridge under another folder name: an old install, or a fork with our mod id."""
    from shutil import copytree

    from battlemap_mcp import server

    copy = mods_dir / name
    copytree(Path(str(server.installer.payload_root())), copy)
    (copy / "fork-marker.txt").write_text(name)
    return copy


def test_other_bridge_copies_are_previewed_then_moved_out_on_request(monkeypatch, tmp_path):
    """Runtime behavior and validation."""
    from battlemap_mcp import server

    mods_dir = tmp_path / "mods"
    state = tmp_path / "state"
    monkeypatch.setattr(server.installer, "default_state_dir", lambda: state)
    old = _fork_copy(mods_dir, "Battlemap MCP Bridge fork")

    preview = server.install_dungeondraft_bridge(str(mods_dir))
    assert preview["other_copies"] == [str(old)]
    target = Path(preview["other_copy_backups"][str(old)])
    assert state in target.parents
    assert "move_other_copies=true" in preview["other_copies_note"]
    assert old.exists() and not target.exists()

    kept = server.install_dungeondraft_bridge(str(mods_dir), confirm=True)
    assert kept["changed"] is True and old.exists()
    assert kept["other_copies"] == [str(old)]

    moved = server.install_dungeondraft_bridge(
        str(mods_dir), confirm=True, replace=True, move_other_copies=True
    )
    assert moved["changed"] is True
    backup = Path(moved["moved_copies"][str(old)])
    assert not old.exists()
    assert (backup / "fork-marker.txt").read_text() == "Battlemap MCP Bridge fork"
    assert state in backup.parents
    assert server.installer.bridge_copies(mods_dir) == [mods_dir / "battlemap-mcp-bridge"]


def test_a_linked_bridge_copy_is_refused_before_anything_moves(monkeypatch, tmp_path):
    """Following a link would back up, then delete, the folder it points to."""
    import pytest

    from battlemap_mcp import server

    mods_dir = tmp_path / "mods"
    monkeypatch.setattr(server.installer, "default_state_dir", lambda: tmp_path / "state")
    real = _fork_copy(tmp_path / "elsewhere", "checkout")
    mods_dir.mkdir()
    link = mods_dir / "dev-bridge"
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")

    refused = server.install_dungeondraft_bridge(
        str(mods_dir), confirm=True, move_other_copies=True
    )
    assert "links" in refused["conflict"]
    assert link.is_symlink() and (real / "fork-marker.txt").exists()
    assert not (mods_dir / "battlemap-mcp-bridge").exists()


def test_a_failed_install_puts_moved_copies_back(monkeypatch, tmp_path):
    from battlemap_mcp import installer

    mods_dir = tmp_path / "mods"
    old = _fork_copy(mods_dir, "old-bridge")
    now = datetime(2026, 10, 20, tzinfo=UTC)
    plan = installer.plan_install(mods_dir, now, state_dir=tmp_path / "state")

    def boom(_plan):
        raise OSError("disk full")

    monkeypatch.setattr(installer, "_record_install", boom)
    try:
        installer.apply_install(plan, force=False, move_other_copies=True)
    except OSError:
        pass
    else:
        raise AssertionError("expected the install to fail")
    assert (old / "fork-marker.txt").read_text() == "old-bridge"
    assert not (mods_dir / "battlemap-mcp-bridge").exists()
    assert not any(installer._state_backups_dir(plan).glob("old-bridge.backup-*"))
