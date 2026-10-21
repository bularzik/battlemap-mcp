"""A file check once reported a two-day-old bridge \"healthy\" because it looked in
a folder Dungeondraft never loads. Only the running bridge can say what it
loaded, so it hashes the source it was compiled from and the server compares.
"""

import hashlib
import json
from pathlib import Path

from battlemap_mcp import installer, server


def _reply(sha):
    return {"pong": True, "protocol": 23, "bridge_sha256": sha, "bridge_path": "/mods/b.gd"}


def test_the_package_hash_is_the_file_text_without_carriage_returns():
    """What the bridge hashes: the source Dungeondraft compiled, minus its header.

    Dungeondraft prepends `var Global = {}\\nvar Script=null` to every mod before
    compiling it, so the running source is the file plus that. The bridge strips
    it; what is left is the file's text, which is what this must hash.
    """
    script = Path(str(installer.payload_root())) / "scripts" / "tools" / "mcp_bridge.gd"
    text = script.read_bytes().decode("utf-8").replace("\r", "")
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert server._package_bridge_sha256() == expected


def test_a_running_bridge_that_matches_is_current(monkeypatch):
    sha = server._package_bridge_sha256()
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **p: _reply(sha))
    reply = server.ping()
    assert reply["bridge_current"] is True
    assert "bridge_note" not in reply


def test_a_different_running_bridge_is_flagged(monkeypatch):
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **p: _reply("0" * 64))
    reply = server.ping()
    assert reply["bridge_current"] is False
    assert "Restart Dungeondraft" in reply["bridge_note"]


def test_a_bridge_too_old_to_say_is_unknown_not_stale(monkeypatch):
    """Not knowing and knowing it is stale are different answers."""
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **p: {"pong": True, "protocol": 23})
    assert server.ping()["bridge_current"] is None


def test_ping_names_both_versions_when_they_agree(monkeypatch):
    """Runtime behavior and validation."""
    reply = {"pong": True, "protocol": 25, "bridge_version": server.__version__}
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **p: dict(reply))
    result = server.ping()
    assert result["bridge_version"] == result["companion_version"] == server.__version__
    assert "version_note" not in result


def test_ping_names_a_version_mismatch(monkeypatch):
    reply = {"pong": True, "protocol": 25, "bridge_version": "0.9.0"}
    monkeypatch.setattr(server.bridge, "request", lambda cmd, **p: dict(reply))
    result = server.ping()
    assert "0.9.0" in result["version_note"]
    assert server.__version__ in result["version_note"]


def test_an_old_bridge_reports_no_version_and_no_mismatch(monkeypatch):
    for reply in ({"pong": True, "protocol": 25}, {"pong": True, "bridge_version": ""}):
        monkeypatch.setattr(server.bridge, "request", lambda cmd, r=reply, **p: dict(r))
        result = server.ping()
        assert "bridge_version" not in result
        assert "version_note" not in result
        assert result["companion_version"] == server.__version__


def test_the_shipped_bridge_manifest_carries_the_companion_version():
    """The mod reports its .ddmod version, so a release must keep the two equal."""
    manifest = Path(str(installer.payload_root())) / "mcp_bridge.ddmod"
    assert json.loads(manifest.read_text())["version"] == server.__version__
