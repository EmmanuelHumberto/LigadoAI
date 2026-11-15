from pathlib import Path
from types import SimpleNamespace
import asyncio
import pytest
from fastapi import HTTPException
from runtime import server


def agent_state(tmp_path, monkeypatch, isolated):
    release = tmp_path / "release"
    release.mkdir()
    agent = (tmp_path / "state" / "agent") if isolated else release / "agent"
    (agent / "pipeline").mkdir(parents=True)
    (agent / "prompts").mkdir()
    (agent / "pipeline" / "generate.yaml").write_text("knobs:\n  prompt: ../prompts/system.md\n")
    (agent / "prompts" / "system.md").write_text("Synthetic prompt")
    if isolated:
        (release / "agent").symlink_to(agent, target_is_directory=True)
    monkeypatch.setattr(server, "_PROJECT_ROOT_AGENT", release)
    monkeypatch.setattr(server, "_AGENT_DIR", release / "agent")
    monkeypatch.setitem(server._state, "cfg", SimpleNamespace(version="test", description="Synthetic agent"))
    return agent


@pytest.mark.parametrize("isolated", [False, True])
def test_config_endpoint_preserves_logical_prompt_path(tmp_path, monkeypatch, isolated):
    agent_state(tmp_path, monkeypatch, isolated)
    result = asyncio.run(server.get_agent_config())
    assert result.system_prompt.path == "agent/prompts/system.md"
    assert result.system_prompt.content == "Synthetic prompt"


def test_prompt_cannot_escape_via_sibling_with_same_prefix(tmp_path, monkeypatch):
    agent = agent_state(tmp_path, monkeypatch, True)
    sibling = agent.parent / "agent-other"
    sibling.mkdir()
    secret = sibling / "system.md"
    secret.write_text("Must not be read")
    (agent / "pipeline" / "generate.yaml").write_text("knobs:\n  prompt: ../../agent-other/system.md\n")
    with pytest.raises(HTTPException) as error:
        asyncio.run(server.get_agent_config())
    assert error.value.status_code == 400


def test_prompt_cannot_escape_via_symlink(tmp_path, monkeypatch):
    agent = agent_state(tmp_path, monkeypatch, True)
    outside = tmp_path / "outside.md"
    outside.write_text("Outside agent")
    (agent / "prompts" / "system.md").unlink()
    (agent / "prompts" / "system.md").symlink_to(outside)
    with pytest.raises(HTTPException) as error:
        server._prompt_relative_path(server._resolve_prompt_path())
    assert error.value.status_code == 400


def test_edit_prompt_uses_state_and_stable_audit_path(tmp_path, monkeypatch):
    from importlib import import_module
    promote = import_module("harness.executor.promote")
    agent = agent_state(tmp_path, monkeypatch, True)
    recorded = {}
    def record(write, **metadata):
        recorded.update(metadata)
        write()
        return SimpleNamespace(version="v2", id="synthetic", parent_version="v1")
    monkeypatch.setattr(promote, "record_manual_change", record)
    result = asyncio.run(server.update_prompt(server.PromptUpdateRequest(content="Updated synthetic prompt")))
    assert result.path == "agent/prompts/system.md"
    assert (agent / "prompts" / "system.md").read_text() == "Updated synthetic prompt"
    assert recorded["mutations_desc"] == ["agent/prompts/system.md (manual)"]
