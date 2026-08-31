import asyncio
import json

from runtime.cognition import mcp_server
from runtime.mcp.client import call_tool, list_tools_for_agent


def test_default_agent_discovers_read_only_cous_facts_tools():
    names = {
        tool.qualified_name
        for tool in list_tools_for_agent("_default", force_refresh=True)
    }

    assert "cous_facts__count_service_orders" in names
    assert "cous_facts__list_service_orders" in names
    assert "cous_facts__get_service_order" in names
    assert "cous_facts__get_knowledge_document" in names
    assert "cous_facts__search_database" in names
    assert "cous_facts__database_inventory" in names
    assert "cous_facts__get_measurement_session" in names
    assert "cous_facts__get_diagnosis" in names
    assert "cous_facts__get_capture_evidence" in names


def test_count_service_orders_returns_database_facts(monkeypatch):
    async def fake_fetchrow(query, *args):
        assert "knowledge_documents" in query
        assert args == ("",)
        return {
            "document_count": 55,
            "distinct_order_count": 53,
            "missing_number_count": 1,
            "duplicate_number_count": 1,
        }

    monkeypatch.setattr(mcp_server, "_fetchrow", fake_fetchrow)

    result = json.loads(asyncio.run(mcp_server.invoke_tool("count_service_orders")))

    assert result["document_count"] == 55
    assert result["distinct_order_count"] == 53
    assert result["duplicate_number_count"] == 1


def test_count_service_orders_filters_without_listing_documents(monkeypatch):
    async def fake_fetchrow(query, *args):
        assert "string_agg" in query
        assert "ORDEM DE SERVI" in query
        assert args == ("DKLAB",)
        return {
            "query": "DKLAB",
            "document_count": 18,
            "distinct_order_count": 17,
            "missing_number_count": 0,
            "duplicate_number_count": 1,
        }

    monkeypatch.setattr(mcp_server, "_fetchrow", fake_fetchrow)

    result = json.loads(
        asyncio.run(
            mcp_server.invoke_tool("count_service_orders", {"query": "DKLAB"})
        )
    )

    assert result["document_count"] == 18
    assert result["distinct_order_count"] == 17


def test_get_service_order_returns_ordered_indexed_text(monkeypatch):
    async def fake_fetchrow(query, *args):
        assert "string_agg(kc.text" in query
        assert args == ("1119",)
        return {
            "id": "1484a62d-3854-45e5-8318-f19163987739",
            "service_order_number": "1119",
            "title": "Ordem de Servico 1119",
            "chunk_count": 3,
            "indexed_text": "cabecalho\nensaio\nobservacoes",
        }

    monkeypatch.setattr(mcp_server, "_fetchrow", fake_fetchrow)

    result = json.loads(
        asyncio.run(
            mcp_server.invoke_tool(
                "get_service_order", {"service_order_number": "1119"}
            )
        )
    )

    assert result["found"] is True
    assert result["document"]["service_order_number"] == "1119"
    assert result["document"]["indexed_text"].startswith("cabecalho")
    assert result["document"]["text_truncated"] is False


def test_search_database_uses_only_requested_scopes(monkeypatch):
    calls = []

    async def fake_fetch(query, *args):
        calls.append((query, args))
        if "FROM knowledge_documents" in query:
            return [{"scope": "knowledge", "label": "OS 1119"}]
        if "FROM measurement_sessions" in query:
            return [{"scope": "measurements", "label": "med_1119"}]
        raise AssertionError("unexpected scope")

    monkeypatch.setattr(mcp_server, "_fetch", fake_fetch)

    result = json.loads(
        asyncio.run(
            mcp_server.invoke_tool(
                "search_database",
                {
                    "query": "1119",
                    "scopes": ["knowledge", "measurements"],
                    "limit": 5,
                },
            )
        )
    )

    assert result["searched_scopes"] == ["knowledge", "measurements"]
    assert result["count"] == 2
    assert len(calls) == 2


def test_measurement_lookup_accepts_cous_source_session_id(monkeypatch):
    async def fake_fetchrow(query, *args):
        assert "source_session_id = $1" in query
        assert args == ("med_20260707_004430_98fbcc",)
        return {
            "id": "59989e63-89d4-467f-906a-6741e32c9284",
            "source_session_id": "med_20260707_004430_98fbcc",
            "capture_session_id": None,
        }

    monkeypatch.setattr(mcp_server, "_fetchrow", fake_fetchrow)

    result = json.loads(
        asyncio.run(
            mcp_server.invoke_tool(
                "get_measurement_session",
                {"identifier": "med_20260707_004430_98fbcc"},
            )
        )
    )

    assert result["found"] is True
    assert result["session"]["source_session_id"] == "med_20260707_004430_98fbcc"


def test_diagnosis_lookup_derives_completed_at_from_existing_column(monkeypatch):
    async def fake_fetchrow(query, *args):
        assert "CASE WHEN status = 'completed' THEN last_attempt_at" in query
        assert args == ("841f752d-a853-4f1e-8ddd-68ece7be0d98", "")
        return {"correlation_id": args[0], "status": "completed"}

    monkeypatch.setattr(mcp_server, "_fetchrow", fake_fetchrow)

    result = json.loads(
        asyncio.run(
            mcp_server.invoke_tool(
                "get_diagnosis",
                {"correlation_id": "841f752d-a853-4f1e-8ddd-68ece7be0d98"},
            )
        )
    )

    assert result["found"] is True
    assert result["diagnosis"]["status"] == "completed"


def test_capture_evidence_exposes_persisted_firmware_modes(monkeypatch):
    async def fake_fetch(query, *args):
        if "FROM electromechanical_signatures_default" in query:
            return [{"id": 7, "timestamp_us": 1_000_000, "valid": True}]
        if "FROM electromechanical_correlation_relations" in query:
            return [
                {
                    "snapshot_id": "frame-1",
                    "timestamp_us": 1_000_000,
                    "relation_index": 0,
                    "relation_id": "motor_nominal_overload_hypothesis",
                    "layer": 3,
                    "assessment": 2,
                    "observed": 470,
                    "reference": 400,
                    "residual": 70,
                    "error_permille": 175,
                    "confidence_permille": 820,
                    "source_channels": "power,motor_nominal_current",
                    "limitation": "current and torque are not independent",
                    "valid": True,
                }
            ]
        raise AssertionError("unexpected query")

    monkeypatch.setattr(mcp_server, "_fetch", fake_fetch)

    result = json.loads(
        asyncio.run(
            mcp_server.invoke_tool(
                "get_capture_evidence",
                {"capture_session_id": "00000000-0000-0000-0000-0000000000c1"},
            )
        )
    )

    assert result["relation_count"] == 1
    assert result["diagnostic_modes"][0]["id"] == (
        "motor_nominal_overload_hypothesis"
    )
    assert result["diagnostic_modes"][0]["assessment"] == "suspect"


def test_internal_tool_can_run_inside_existing_event_loop(monkeypatch):
    async def fake_invoke(name, arguments):
        return json.dumps({"name": name, "arguments": arguments})

    monkeypatch.setattr(mcp_server, "invoke_tool", fake_invoke)

    async def call_from_runtime_loop():
        return call_tool(
            "_default",
            "cous_facts__get_measurement_session",
            {"identifier": "med_test"},
        )

    result = json.loads(asyncio.run(call_from_runtime_loop()))

    assert result["name"] == "get_measurement_session"
    assert result["arguments"] == {"identifier": "med_test"}
