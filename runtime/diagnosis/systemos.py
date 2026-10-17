"""Live read-only SystemOS diagnosis, independent of indexed service orders/captures."""
from __future__ import annotations

import json
import os
from collections.abc import Awaitable, Callable
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from runtime.diagnosis.routes import _bearer_auth_dependency
from runtime.diagnosis.worker import DiagnosisWorker


class SystemOsDiagnosisRequest(BaseModel):
    order: str = Field(pattern=r"^(?:[0-9]{1,12}|[a-fA-F0-9]{8}-(?:[a-fA-F0-9]{4}-){3}[a-fA-F0-9]{12})$")


async def analyze_context(envelope: dict, generate: Callable[[str], Awaitable[dict]]) -> dict:
    snapshot = envelope.get("snapshot", {})
    if envelope.get("schemaVersion") != 1 or snapshot.get("schemaVersion") != 1:
        raise ValueError("Unsupported SystemOS contract")
    scope = snapshot.get("scope", {})
    if scope.get("source_system") != "systemos":
        raise ValueError("Invalid source")
    UUID(scope["organization_id"])
    UUID(scope["service_order_id"])
    evidence_set = envelope.get("evidenceSet")
    if not isinstance(evidence_set, list):
        raise ValueError("Missing temporal evidence contract")
    # Only pure normalizing/scoring methods are used. No capture or OS is inserted.
    worker = DiagnosisWorker(None, None)
    evidences = worker._normalize_queued_evidences(evidence_set)
    hypotheses = await worker._generate_hypotheses(evidences, [], [])
    prompt = envelope.get("prompt")
    if not isinstance(prompt, str) or not prompt.startswith("TAREFA_SYSTEMOS_ANALISE_TECNICA_"):
        raise ValueError("Missing SystemOS narrative contract")
    # Fail explicitly rather than truncate data into an apparently complete conclusion.
    if len(prompt.encode("utf-8")) > 32000:
        raise ValueError("Narrative exceeds conservative input budget; no text discarded")
    response = await generate(prompt)
    if response.get("success") is not True:
        raise RuntimeError("Model generation failed")
    text = str(response.get("response") or "").strip()
    if text.startswith("```json") and text.endswith("```"):
        text = text[7:-3].strip()
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("Model output is not an object")
    return {"source": "systemos_live", "scope": scope, "order": snapshot["numeroOS"],
            "snapshot_hash": envelope["snapshotHash"], "consulted_at": envelope["consultadoEm"],
            "trace_id": response.get("trace_id"), "model": response.get("model"), "conclusion": "",
            "hypotheses": hypotheses, "rejected_paragraphs": 0, "_model_output": raw,
            "limitations": ["Consulta dos registros salvos; rascunhos nao salvos nao foram incluidos.",
                             "Anexos: somente metadados; fotos e PDFs nao foram interpretados.",
                             "Pontuacoes V4 heuristicas sem corroboracao adicional do grafo nesta consulta direta.",
                             "Texto sugerido para revisao humana; nao aplicado a OS."]}


def create_systemos_router(generate, *, http_client=None) -> APIRouter:
    # Fail closed, including when old installations have no V3 token configured.
    async def authenticate(authorization: str = Header("")):
        token = os.environ.get("OPENTRACY_COUS_V3_AUTH_TOKEN") or os.environ.get("OPENTRACY_KNOWLEDGE_AUTH_TOKEN")
        if not token:
            raise HTTPException(503, "Direct diagnosis authentication not configured")
        await _bearer_auth_dependency(token)(authorization)

    router = APIRouter(prefix="/v3/systemos", dependencies=[Depends(authenticate)])

    @router.post("/diagnosis")
    async def diagnosis(payload: SystemOsDiagnosisRequest):
        base = os.environ.get("OPENTRACY_SYSTEMOS_URL", "").rstrip("/")
        key = os.environ.get("OPENTRACY_SYSTEMOS_READ_KEY", "")
        organization = os.environ.get("OPENTRACY_SYSTEMOS_ORGANIZATION_ID", "")
        if not base or len(key) < 32 or not organization:
            raise HTTPException(503, "SystemOS read-only connection not configured")
        async def fetch(client):
            response = await client.get(f"{base}/integracoes/cognicao/ordens/{payload.order}",
                                        headers={"x-cognitive-read-key": key}, timeout=30, follow_redirects=False)
            if response.status_code == 404:
                raise HTTPException(404, "OS nao encontrada no SystemOS")
            if response.status_code != 200:
                raise HTTPException(502, f"SystemOS read failed (HTTP {response.status_code})")
            if len(response.content) > 512 * 1024:
                raise HTTPException(413, "SystemOS context too large; no data discarded")
            envelope = response.json()
            snapshot = envelope.get("snapshot", {})
            if snapshot.get("scope", {}).get("organization_id") != organization:
                raise HTTPException(409, "SystemOS organization mismatch")
            if payload.order.isdigit():
                matches = str(snapshot.get("numeroOS")) == str(int(payload.order))
            else:
                matches = snapshot.get("scope", {}).get("service_order_id", "").lower() == payload.order.lower()
            if not matches:
                raise HTTPException(409, "SystemOS order mismatch")
            return envelope
        try:
            if http_client is not None:
                envelope = await fetch(http_client)
            else:
                async with httpx.AsyncClient() as client:
                    envelope = await fetch(client)
            result = await analyze_context(envelope, generate)
            # Reuse SystemOS semantic validation and recheck source freshness before
            # showing text. This POST validates only; it never saves the suggestion.
            async def validate(client):
                response = await client.post(f"{base}/integracoes/cognicao/ordens/{payload.order}/validar",
                    headers={"x-cognitive-read-key": key},
                    json={"snapshotHash": result["snapshot_hash"], "resultado": result.pop("_model_output")},
                    timeout=30, follow_redirects=False)
                if response.status_code == 409:
                    raise HTTPException(409, "A OS mudou durante a analise; consulte novamente")
                if response.status_code not in (200, 201):
                    raise HTTPException(502, "SystemOS could not validate the conclusion")
                checked = response.json()
                result["conclusion"] = checked["conclusao"]
                result["rejected_paragraphs"] = checked["trechosDescartados"]
                result["inconsistencies"] = checked["incoerencias"]
            if http_client is not None:
                await validate(http_client)
            else:
                async with httpx.AsyncClient() as client:
                    await validate(client)
            return result
        except HTTPException:
            raise
        except httpx.RequestError:
            raise HTTPException(503, "SystemOS connection unavailable") from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(502, "Invalid or oversized diagnosis response; no conclusion applied") from None
        except RuntimeError:
            raise HTTPException(502, "Model did not complete the technical analysis") from None
    return router
