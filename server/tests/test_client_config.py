"""Tests for supported local MCP client registration commands."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest


def test_claude_repeat_setup_keeps_matching_registration_without_cli(monkeypatch, tmp_path):
    import json

    from battlemap_mcp import client_config

    registry = tmp_path / ".claude.json"
    launcher = tmp_path / "Café companion.exe"
    registry.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "battlemap": {
                        "type": "stdio",
                        "command": str(launcher),
                        "args": [],
                        "env": {"LOCAL": "keep"},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    original = registry.read_bytes()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(client_config.shutil, "which", lambda _: None)
    result = client_config.register_client("claude-code", launcher)
    assert result.registered
    assert registry.read_bytes() == original
    result = client_config.register_client("claude-code", tmp_path / "different.exe")
    assert not result.registered
    assert registry.read_bytes() == original


def test_claude_failure_names_the_entry_already_registered(monkeypatch, tmp_path):
    """`claude mcp add` refuses an existing name; setup must say which entry."""
    import json

    from battlemap_mcp import client_config

    old = tmp_path / "Old Companion" / "battlemap-mcp.exe"
    (tmp_path / ".claude.json").write_text(
        json.dumps({"mcpServers": {"battlemap": {"type": "stdio", "command": str(old)}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(client_config.shutil, "which", lambda command: f"/usr/bin/{command}")

    def refuse(*_args, **_kwargs):
        return SimpleNamespace(returncode=1, stdout="", stderr="already exists in user config")

    result = client_config.register_client("claude-code", tmp_path / "new.exe", refuse)
    assert not result.registered
    assert result.existing_command == str(old)


def test_claude_failure_without_an_entry_reports_none(monkeypatch, tmp_path):
    from battlemap_mcp import client_config

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(client_config.shutil, "which", lambda command: f"/usr/bin/{command}")
    result = client_config.register_client(
        "claude-code",
        tmp_path / "new.exe",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout="", stderr="other failure"),
    )
    assert not result.registered
    assert result.existing_command is None


def test_registration_commands_use_supported_user_scoped_cli_vectors():
    """Client setup must use CLIs rather than editing client settings files."""
    from battlemap_mcp.client_config import registration_argv

    executable = Path("/opt/bin/battlemap-mcp")
    executable_text = str(executable)

    assert registration_argv("claude-code", executable) == [
        "claude",
        "mcp",
        "add",
        "--scope",
        "user",
        "battlemap",
        "--",
        executable_text,
    ]
    assert registration_argv("codex", executable) == [
        "codex",
        "mcp",
        "add",
        "battlemap",
        "--",
        executable_text,
    ]


def test_client_none_skips_registration_without_invoking_a_runner():
    """Users opting out of setup do not trigger any client-side command."""
    from battlemap_mcp.client_config import register_client

    calls: list[object] = []
    result = register_client("none", Path("/opt/bin/battlemap-mcp"), lambda *args, **kwargs: calls)

    assert result.registered is False
    assert result.manual_command is None
    assert calls == []


def test_missing_client_returns_a_manual_command_without_running_it(monkeypatch):
    """A bridge install remains useful when the target client CLI is absent."""
    from battlemap_mcp import client_config

    calls: list[object] = []
    monkeypatch.setattr(client_config.shutil, "which", lambda command: None)

    executable = Path("/opt/bin/battlemap-mcp")
    result = client_config.register_client("codex", executable, lambda *args, **kwargs: calls)

    assert result.registered is False
    assert result.manual_command == [
        "codex",
        "mcp",
        "add",
        "battlemap",
        "--",
        str(executable),
    ]
    assert calls == []


def test_unlaunchable_client_returns_a_manual_command_without_crashing(monkeypatch):
    """A stale Windows launcher must not abort bridge or skill installation."""
    from battlemap_mcp import client_config

    executable = Path("C:/Program Files/Dungeondraft MCP/battlemap-mcp.exe")
    monkeypatch.setattr(client_config.shutil, "which", lambda command: r"C:\\broken\\codex.cmd")

    def runner(*_args, **_kwargs):
        raise FileNotFoundError("stale launcher")

    result = client_config.register_client("codex", executable, runner)

    assert result.registered is False
    assert result.client_cli_available is False
    assert result.manual_command == [
        "codex",
        "mcp",
        "add",
        "battlemap",
        "--",
        str(executable),
    ]


def test_registration_invokes_a_client_cli_without_a_shell(monkeypatch):
    """Setup passes an argv vector to the supported client executable."""
    from battlemap_mcp import client_config

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(client_config.shutil, "which", lambda command: f"/usr/bin/{command}")

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="registered", stderr="")

    executable = Path("/opt/bin/battlemap-mcp")
    result = client_config.register_client("claude-code", executable, runner)

    assert result.registered is True
    assert calls == [
        (
            (
                [
                    "/usr/bin/claude",
                    "mcp",
                    "add",
                    "--scope",
                    "user",
                    "battlemap",
                    "--",
                    str(executable),
                ],
            ),
            {"capture_output": True, "check": False, "shell": False, "text": True},
        )
    ]


def test_registration_uses_the_resolved_windows_cmd_launcher(monkeypatch):
    from battlemap_mcp import client_config

    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    resolved = r"C:\Program Files\Codex\codex.cmd"
    monkeypatch.setattr(client_config.shutil, "which", lambda command: resolved)

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="registered", stderr="")

    result = client_config.register_client("codex", Path("C:/Program Files/DD/server.exe"), runner)

    assert result.registered is True
    assert calls[0][0][0][0] == resolved
    assert calls[0][1]["shell"] is False


def test_registries_distinguish_code_and_desktop_without_exposing_secrets(tmp_path):
    from battlemap_mcp.client_config import inspect_registration

    code = tmp_path / "code.json"
    desktop = tmp_path / "desktop.json"
    code.write_text(
        '{"mcpServers": {"battlemap": {"command": "/server", "env": {"TOKEN": "secret-token"}}}}'
    )
    desktop.write_text('{"mcpServers": {}, "preferences": {"secret": "private"}}')
    assert inspect_registration(code) == "registered (connection not tested)"
    assert inspect_registration(desktop) == "not registered"
    assert inspect_registration(tmp_path / "absent") == "not registered (config missing)"
    desktop.write_text('{"secret-token":')
    assert inspect_registration(desktop) == "cannot inspect config"


@pytest.mark.parametrize(
    "malformed",
    [
        "[]",
        '{"mcpServers": []}',
        '{"mcpServers": {"battlemap": null}}',
        '{"mcpServers": {"battlemap": {"command": ""}}}',
    ],
)
def test_registry_inspection_reports_invalid_shapes(tmp_path, malformed):
    from battlemap_mcp.client_config import inspect_registration

    path = tmp_path / "config.json"
    path.write_text(malformed)
    assert "invalid" in inspect_registration(path)


def test_claude_registry_platform_paths(monkeypatch, tmp_path):
    from battlemap_mcp import client_config

    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(client_config.sys, "platform", "darwin")
    paths = client_config.claude_registry_paths()
    assert paths["Claude Code (user scope)"] == tmp_path / ".claude.json"
    assert paths["Claude Desktop (chat)"] == (
        tmp_path / "Library/Application Support/Claude/claude_desktop_config.json"
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "alternate"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setattr(client_config.sys, "platform", "win32")
    paths = client_config.claude_registry_paths()
    assert paths["Claude Code (user scope)"] == tmp_path / "alternate" / ".claude.json"
    assert paths["Claude Desktop (chat)"] == tmp_path / "roaming/Claude/claude_desktop_config.json"


@pytest.mark.parametrize(
    "location",
    [
        "uv/archive-v0/abc/bin/server",
        "uv/tools-v1/abc/Scripts/server.exe",
        "custom-cache/abc/server",
    ],
)
def test_transient_launcher_is_rejected(monkeypatch, tmp_path, location):
    from battlemap_mcp import client_config

    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "custom-cache"))
    with pytest.raises(ValueError, match="uv tool install"):
        client_config.registration_argv("codex", tmp_path / location)


def _opencode(monkeypatch, tmp_path, *, on_path=True):
    from battlemap_mcp import client_config

    home = tmp_path / "home"
    (home / ".config" / "opencode").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setattr(
        client_config.shutil, "which", lambda name: "/bin/opencode" if on_path else None
    )
    return client_config, home / ".config" / "opencode" / "opencode.json"


MCP_ADD_HELP = "opencode mcp add [name]\n  --global  add to the global config\n"


class _Run:
    """Each step is a return code, or (code, stdout) for the help probe."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        step = self.steps.pop(0)
        code, out = step if isinstance(step, tuple) else (step, "")
        return type("Done", (), {"returncode": code, "stdout": out, "stderr": ""})()


def test_opencode_registers_globally_through_mcp_add(monkeypatch, tmp_path):
    client_config, _ = _opencode(monkeypatch, tmp_path)
    run = _Run((0, MCP_ADD_HELP), 0)
    result = client_config.register_opencode(tmp_path / "companion", runner=run)
    assert result.registered
    assert run.calls == [
        ["/bin/opencode", "mcp", "add", "--help"],
        [
            "/bin/opencode",
            "mcp",
            "add",
            "--global",
            "battlemap",
            "--",
            str(tmp_path / "companion"),
        ],
    ]


def test_opencode_1_has_no_mcp_add(monkeypatch, tmp_path):
    client_config, _ = _opencode(monkeypatch, tmp_path)
    run = _Run(1)
    result = client_config.register_opencode(tmp_path / "companion", runner=run)
    assert not result.registered and result.client_cli_available
    assert result.manual_command is None and len(run.calls) == 1


def test_an_mcp_add_without_global_is_not_run(monkeypatch, tmp_path):
    """OpenCode 1.19.0 (the newest public build on 2026-10-11) has `mcp add`
    but no --global: setup ran it, it failed, and the reply told the user to
    run that same failing command by hand."""
    client_config, _ = _opencode(monkeypatch, tmp_path)
    run = _Run((0, "opencode mcp add [name]\n  --url  URL for a remote MCP server\n"))
    result = client_config.register_opencode(tmp_path / "companion", runner=run)
    assert not result.registered and result.client_cli_available
    assert result.manual_command is None and len(run.calls) == 1


def test_opencode_is_not_run_on_a_config_with_comments(monkeypatch, tmp_path):
    """`mcp add` replaces silently; an entry hidden by JSONC must not be replaced."""
    client_config, config = _opencode(monkeypatch, tmp_path)
    config.write_text('{\n  // mine\n  "mcp": {"battlemap": {"command": ["x"]}}\n}')
    run = _Run()
    result = client_config.register_opencode(tmp_path / "companion", runner=run)
    assert not result.registered and run.calls == []


def test_opencode_not_on_path(monkeypatch, tmp_path):
    client_config, _ = _opencode(monkeypatch, tmp_path, on_path=False)
    result = client_config.register_opencode(tmp_path / "companion", runner=_Run())
    assert not result.registered and not result.client_cli_available
