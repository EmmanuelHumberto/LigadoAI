from techniques.prompt_strategies.impl import _load_system_prompt, _render_user_message, _SYSTEMOS_PREFIX
from techniques.rag.impl import _is_inventory_request
from runtime.protocols import Document


def test_systemos_prompt_is_loaded_from_file(tmp_path):
    prompt = tmp_path / "systemos.md"
    prompt.write_text("Contrato especifico da organizacao")
    assert _load_system_prompt(str(prompt), fallback="fallback") == "Contrato especifico da organizacao"
    assert _load_system_prompt(str(tmp_path / "missing.md"), fallback="fallback") == "fallback"


def test_systemos_instructions_do_not_trigger_inventory():
    assert not _is_inventory_request(_SYSTEMOS_PREFIX + "V1 Integre todos os componentes; nao produza inventario")
    assert _is_inventory_request("liste todos os motores")


def test_systemos_context_ignores_catalog():
    docs = [Document(content="CATALOGO GLOBAL",score=100,metadata={"variant":"catalog"}),
            Document(content="MANUAL PERTINENTE",score=1)]
    rendered = _render_user_message(docs, _SYSTEMOS_PREFIX + "V1")
    assert "CATALOGO GLOBAL" not in rendered
    assert "MANUAL PERTINENTE" in rendered


def test_direct_uses_configured_systemos_prompt(monkeypatch, tmp_path):
    from techniques.prompt_strategies.impl import _Direct
    from runtime.protocols import Context, RoutingDecision
    import techniques.prompt_strategies.impl as impl
    prompt = tmp_path / "custom.md"
    prompt.write_text("Contrato especifico testado")
    captured = {}
    def run(**kwargs):
        captured.update(kwargs)
        return '{"achados":[],"incoerencias":[],"confianca":null}', None, []
    monkeypatch.setattr(impl, "_run_ollama", run)
    ctx = Context(request=_SYSTEMOS_PREFIX + "V1")
    ctx.routing = RoutingDecision(model="ollama/qwen3.5:4b", reason="test")
    _Direct({"systemos_prompt":str(prompt)}).execute(ctx)
    assert captured["system"] == "Contrato especifico testado"
    assert captured["structured_output"] is True
