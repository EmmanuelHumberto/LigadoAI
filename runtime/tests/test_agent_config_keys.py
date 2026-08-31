from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_agent_config_reports_deepseek_key(monkeypatch):
    from runtime import server

    monkeypatch.setitem(
        server._state,
        "cfg",
        SimpleNamespace(version="test", description="test"),
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key-long-enough")

    result = await server.get_agent_config()

    deepseek = next(key for key in result.keys if key.name == "DeepSeek")
    assert deepseek.env_var == "DEEPSEEK_API_KEY"
    assert deepseek.set is True
    assert deepseek.mask is not None
    assert "deepseek-test-key-long-enough" not in deepseek.mask
