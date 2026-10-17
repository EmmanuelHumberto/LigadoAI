"""Worker de diagnóstico — COUS v3.1 — processamento real via pipeline."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any
from uuid import UUID, uuid4

import httpx

from knowledge.domain.confidence import DomainWeights, build_breakdown, compute_confidence, can_be_primary_hypothesis
from knowledge.domain.cous_models import ConfidenceBreakdown
from runtime.diagnosis.electromechanical import (
    MODE_DEFINITIONS,
    CORRELATION_TIMELINE_QUERY,
    decode_systemos_timeline,
    FirmwareModeEvidence,
    build_persisted_correlation_evidence,
    correlation_contract_state,
    extract_causal_metrics,
    extract_firmware_modes,
    format_mode_description,
    matching_causal_chains,
    matching_knowledge_units,
    reported_context_supports_mode,
)

logger = logging.getLogger("diagnosis.worker")


class DiagnosisWorker:
    """Worker que processa a fila de diagnóstico e gera hipóteses reais.

    Fluxo:
    1. Consome diagnosis_queue (FOR UPDATE SKIP LOCKED)
    2. Para cada item, coleta evidências da captura
    3. Busca documentos relevantes (RAG)
    4. Consulta Knowledge Graph por KUs similares
    5. Calcula confidence_breakdown para cada hipótese
    6. Envia callback ao Cous com resultado
    """

    def __init__(
        self,
        repository,          # CousKnowledgeRepository
        http_client: httpx.AsyncClient,
        poll_interval: float = 5.0,
        max_retries: int = 3,
        diagnosis_timeout: float = 30.0,
    ) -> None:
        self._repo = repository
        self._http = http_client
        self._poll_interval = poll_interval
        self._max_retries = max_retries
        self._diagnosis_timeout = diagnosis_timeout
        self._running = False
        self._task: asyncio.Task | None = None
        self._weights = DomainWeights()

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("DiagnosisWorker v3.1 iniciado (poll=%.1fs, retries=%d)",
                     self._poll_interval, self._max_retries)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("DiagnosisWorker parado")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._process_pending()
                await self._process_callback_outbox()
            except Exception:
                logger.exception("Erro no loop do DiagnosisWorker")
            await asyncio.sleep(self._poll_interval)

    async def _process_pending(self) -> None:
        async with self._repo._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE diagnosis_queue
                SET status = 'processing', attempts = attempts + 1,
                    last_attempt_at = NOW()
                WHERE id IN (
                    SELECT id FROM diagnosis_queue
                    WHERE status = 'pending'
                    ORDER BY queued_at ASC
                    LIMIT 5
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING *
                """
            )

        for row in rows:
            asyncio.create_task(self._process_one(row))

    async def _process_one(self, row: Any) -> None:
        item_id = row["id"]
        capture_session_id = row["capture_session_id"]
        instance_id = row["instance_id"]

        backoff = 1.0
        last_error: str | None = None

        result: dict[str, Any] | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                result = await self._run_diagnosis(
                    item_id,
                    capture_session_id,
                    instance_id,
                    queued_evidence_set=self._row_json(row, "evidence_set", []),
                    queued_context=self._row_json(row, "context", {}),
                )
                break
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning("Diagnóstico %s falhou (tentativa %d/%d): %s",
                               item_id, attempt, self._max_retries, last_error)
                if attempt < self._max_retries:
                    await asyncio.sleep(backoff)
                    backoff *= 2

        if result is not None:
            await self._mark_completed(item_id, result)
            return

        failure_error = last_error or "max retries exceeded"
        failure_result = {
            "correlation_id": str(item_id),
            "capture_session_id": str(capture_session_id),
            "trace_id": str(uuid4()),
            "duration_ms": 0,
            "hypotheses": [],
            "explanation": None,
            "error": failure_error,
        }
        await self._mark_failed(item_id, failure_error, failure_result)

    async def _process_callback_outbox(self) -> None:
        async with self._repo._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                UPDATE diagnosis_queue
                SET callback_status = 'processing',
                    callback_attempts = callback_attempts + 1,
                    callback_last_attempt_at = NOW()
                WHERE id IN (
                    SELECT id
                    FROM diagnosis_queue
                    WHERE callback_status IN ('pending', 'failed')
                      AND result_payload IS NOT NULL
                      AND (
                          callback_next_attempt_at IS NULL
                          OR callback_next_attempt_at <= NOW()
                      )
                    ORDER BY queued_at ASC
                    LIMIT 5
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, result_payload
                """
            )

        for row in rows:
            item_id = row["id"]
            result = self._row_json(row, "result_payload", {})
            try:
                await self._send_callback(item_id, result)
            except Exception as exc:
                await self._mark_callback_failed(
                    item_id,
                    f"{type(exc).__name__}: {exc}",
                )
            else:
                await self._mark_callback_delivered(item_id)

    async def _run_diagnosis(
        self,
        item_id: UUID,
        capture_session_id: UUID,
        instance_id: UUID,
        queued_evidence_set: list[dict[str, Any]] | None = None,
        queued_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Executa o diagnóstico real: busca documentos, consulta KG, gera hipóteses."""

        # 1. Usar evidências enviadas pelo Cous e complementar com evidências da captura no banco
        evidences = self._normalize_queued_evidences(queued_evidence_set or [])
        evidences.extend(await self._collect_evidences(capture_session_id))

        # 2. Buscar KnowledgeUnits similares no Knowledge Graph
        similar_kus = await self._find_similar_kus(instance_id)

        # 3. Buscar cadeias causais aplicáveis (com matching de condições)
        # Extrair desvios das evidências para avaliação
        deviations = {}
        for ev in evidences:
            if ev.get("type") == "deviation":
                deviations.update(
                    {
                        k: v
                        for k, v in ev.items()
                        if k not in ("type", "strength") and v is not None
                    }
                )
            elif ev.get("type") == "electromechanical_signature":
                deviations.update(
                    {
                        k: v
                        for k, v in ev.items()
                        if k not in ("type", "strength") and v is not None
                    }
                )
        deviations.update(extract_causal_metrics(evidences))
        causal_chains = await self._find_causal_chains(
            instance_id,
            deviations if deviations else None,
        )

        # 4. Gerar hipóteses com confidence_breakdown
        hypotheses = await self._generate_hypotheses(evidences, similar_kus, causal_chains)

        # 5. Montar explicação
        explanation = await self._build_explanation(hypotheses, evidences)

        return {
            "correlation_id": str(item_id),
            "capture_session_id": str(capture_session_id),
            "trace_id": str(uuid4()),
            "duration_ms": 0,
            "hypotheses": hypotheses,
            "explanation": explanation,
            "evidences_used": len(evidences),
            "kus_consulted": len(similar_kus),
            "causal_chains_used": len(causal_chains),
            "context": queued_context or {},
        }

    def _row_json(self, row: Any, key: str, fallback: Any) -> Any:
        try:
            raw = row[key]
        except (KeyError, TypeError):
            return fallback
        if raw is None:
            return fallback
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return fallback
        return raw

    def _normalize_queued_evidences(
        self,
        evidence_set: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Converte EvidenceItemSchema do Cous para o formato usado pelo worker."""
        normalized: list[dict[str, Any]] = []
        for item in evidence_set:
            if not isinstance(item, dict):
                continue
            data = item.get("data") if isinstance(item.get("data"), dict) else {}
            if item.get("evidence_type") == "systemos_correlation_timeline":
                evidence = decode_systemos_timeline(data)
                if item.get("source_reference"):
                    evidence["source_reference"] = item["source_reference"]
                normalized.append(evidence)
                continue
            evidence = dict(data)
            evidence["type"] = (
                evidence.get("type")
                or item.get("evidence_type")
                or "queued_evidence"
            )
            evidence["strength"] = item.get("evidence_strength") or "weak"
            evidence["confidence"] = item.get("confidence", evidence.get("confidence"))
            if item.get("source_reference"):
                evidence["source_reference"] = item["source_reference"]
            normalized.append(evidence)
        return normalized

    async def _collect_evidences(self, capture_session_id: UUID) -> list[dict[str, Any]]:
        """Coleta evidências físicas da sessão de captura."""
        evidences = []
        async with self._repo._pool.acquire() as conn:
            # Buscar assinaturas eletromecânicas
            sig_rows = await conn.fetch(
                """
                SELECT * FROM electromechanical_signatures_default
                WHERE capture_session_id = $1
                LIMIT 100
                """,
                capture_session_id,
            )
            for row in sig_rows:
                evidence_strength = "strong" if row.get("valid") else "weak"
                evidences.append({
                    "type": "electromechanical_signature",
                    "strength": evidence_strength,
                    "rpm": float(row["rpm"]) if row.get("rpm") else None,
                    "bemf_v": float(row["bemf_v"]) if row.get("bemf_v") else None,
                    "torque_load_permille": (
                        float(row["torque_load_permille"])
                        if row.get("torque_load_permille")
                        else None
                    ),
                    "winding_resistance_mohm": (
                        float(row["winding_resistance_mohm"])
                        if row.get("winding_resistance_mohm") is not None
                        else None
                    ),
                })

            # Buscar desvios
            dev_rows = await conn.fetch(
                """
                SELECT sd.* FROM signature_deviations sd
                JOIN electromechanical_signatures_default es ON es.id = sd.signature_id
                WHERE es.capture_session_id = $1
                LIMIT 100
                """,
                capture_session_id,
            )
            for row in dev_rows:
                evidences.append({
                    "type": "deviation",
                    "strength": "strong",
                    "bemf_error_permille": (
                        float(row["bemf_error_permille"])
                        if row.get("bemf_error_permille")
                        else None
                    ),
                    "winding_resistance_error_permille": (
                        float(row["winding_resistance_error_permille"])
                        if row.get("winding_resistance_error_permille") is not None
                        else None
                    ),
                    "rpm_error_permille": (
                        float(row["rpm_error_permille"])
                        if row.get("rpm_error_permille") is not None
                        else None
                    ),
                    "electrical_power_error_permille": (
                        float(row["electrical_power_error_permille"])
                        if row.get("electrical_power_error_permille") is not None
                        else None
                    ),
                    "torque_error_permille": (
                        float(row["torque_error_permille"])
                        if row.get("torque_error_permille")
                        else None
                    ),
                })

            relation_rows = await conn.fetch(
                CORRELATION_TIMELINE_QUERY, capture_session_id, 5000,
            )
            correlation = build_persisted_correlation_evidence(
                [dict(row) for row in relation_rows]
            )
            if correlation is not None:
                evidences.append(correlation)

        return evidences

    async def _find_similar_kus(self, instance_id: UUID) -> list[dict[str, Any]]:
        """Busca KnowledgeUnits similares no Knowledge Graph."""
        async with self._repo._pool.acquire() as conn:
            # Buscar KUs do mesmo domínio, ordenadas por confiança
            rows = await conn.fetch(
                """
                SELECT ku.id, ku.title, ku.statement, ku.knowledge_level, ku.confidence
                FROM knowledge_units ku
                JOIN entities e ON e.domain_id = ku.domain_id
                JOIN instances i ON i.entity_id = e.id
                WHERE i.id = $1
                  AND ku.knowledge_level IN ('confirmed', 'consolidated')
                ORDER BY ku.confidence DESC
                LIMIT 100
                """,
                instance_id,
            )
            return [dict(r) for r in rows]

    async def _find_causal_chains(
        self, instance_id: UUID, deviations: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Busca cadeias causais e avalia condições contra desvios reais.

        Usa o motor de avaliação (causal_engine) para matching semântico:
        condition_expression como 'bemf_error_permille < -150 AND ...'
        é avaliada contra os valores reais dos desvios.
        """
        async with self._repo._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT cc.*
                FROM causal_chains cc
                JOIN entities e ON e.domain_id = cc.domain_id
                JOIN instances i ON i.entity_id = e.id
                WHERE i.id = $1
                  AND cc.confidence > 0.3
                ORDER BY cc.confidence DESC
                LIMIT 20
                """,
                instance_id,
            )
            all_chains = [dict(r) for r in rows]

        if not all_chains:
            return []

        # Se temos desvios, filtrar por matching de condições
        if deviations:
            from knowledge.domain.causal_engine import find_matching_chains
            matched = find_matching_chains(deviations, all_chains)
            return matched[:5]  # top 5 matches

        # Sem desvios, retornar todas (fallback)
        return all_chains[:5]

    async def _generate_hypotheses(
        self,
        evidences: list[dict[str, Any]],
        similar_kus: list[dict[str, Any]],
        causal_chains: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Gera hipóteses com confidence_breakdown a partir de evidências e KUs."""

        correlation_state = correlation_contract_state(evidences)
        modes = extract_firmware_modes(evidences)
        if modes:
            reported_context = self._reported_service_order_context(evidences)
            hypotheses = self._generate_firmware_mode_hypotheses(
                modes,
                similar_kus,
                causal_chains,
                reported_context=reported_context,
            )
            hypotheses.sort(key=lambda item: item["confidence"], reverse=True)
            for hypothesis in hypotheses:
                hypothesis["is_primary"] = can_be_primary_hypothesis(hypothesis["confidence"])
                if hypothesis["is_primary"]:
                    break
            return hypotheses
        if correlation_state != "absent":
            return [
                self._generate_correlation_status_hypothesis(
                    evidences,
                    invalid=correlation_state == "invalid",
                )
            ]

        hypotheses = []
        scored_evidences = [
            item
            for item in evidences
            if item.get("type") != "service_order_context"
            and item.get("valid") is not False
        ]
        if not scored_evidences:
            return []
        n_strong = sum(
            1 for item in scored_evidences if item.get("strength") == "strong"
        )
        n_moderate = sum(
            1 for item in scored_evidences if item.get("strength") == "moderate"
        )
        n_weak = sum(
            1 for item in scored_evidences if item.get("strength") == "weak"
        )

        confirmed_count = sum(
            1
            for ku in similar_kus
            if ku.get("knowledge_level") in ("confirmed", "consolidated")
        )

        for ku in similar_kus[:5]:  # Top 5 KUs
            if self._is_generic_test_ku(ku) or self._is_firmware_mode_ku(ku):
                continue
            # Calcular confidence_breakdown
            breakdown = build_breakdown(
                n_strong=n_strong,
                n_moderate=n_moderate,
                n_weak=n_weak,
                authorities=[ku.get("authority", "média")],
                confirmed_similar=confirmed_count,
                open_contradictions=0,
                total_evidences=len(scored_evidences),
            )
            confidence = compute_confidence(breakdown, self._weights)

            hypotheses.append({
                "hypothesis_id": str(uuid4()),
                "description": ku.get("statement", ku.get("title", "")),
                "confidence": round(confidence, 4),
                "confidence_breakdown": breakdown.as_dict(),
                "is_primary": False,
                "causal_chain_id": str(causal_chains[0]["id"]) if causal_chains else None,
                "source_ku_id": str(ku.get("id")),
            })

        if not hypotheses:
            hypotheses.extend(self._generate_telemetry_hypotheses(evidences))

        # Ordenar por confiança
        hypotheses.sort(key=lambda h: h["confidence"], reverse=True)

        # Exatamente uma hipótese pode ser primária.
        for hypothesis in hypotheses:
            hypothesis["is_primary"] = False
        if hypotheses and can_be_primary_hypothesis(hypotheses[0]["confidence"]):
            hypotheses[0]["is_primary"] = True

        return hypotheses

    def _generate_correlation_status_hypothesis(
        self,
        evidences: list[dict[str, Any]],
        *,
        invalid: bool,
    ) -> dict[str, Any]:
        correlation = next(
            (
                item
                for item in evidences
                if item.get("type") == "electromechanical_correlation_frame"
            ),
            {},
        )
        evidence_confidence = self._bounded_confidence(correlation.get("confidence"))
        if invalid:
            description = (
                "Correlacao eletromecanica v3 inconclusiva: resumo de modos "
                "ausente ou invalido"
            )
            consistency = 0.0
            confidence = min(evidence_confidence, 0.2)
            diagnostic_kind = "invalid_correlation_evidence"
            limitations = [
                "OpenTracy nao recebeu diagnostic_modes em formato interpretavel."
            ]
        else:
            description = (
                "Nenhum modo de falha suspeito ou critico foi publicado pelo "
                "firmware nesta captura"
            )
            consistency = 1.0
            confidence = 0.4 * evidence_confidence + 0.1 * consistency
            diagnostic_kind = "no_active_firmware_mode"
            limitations = [
                "Ausencia de modo ativo nao confirma ausencia de defeito fora do modelo."
            ]
        breakdown = ConfidenceBreakdown(
            evidence_score=evidence_confidence,
            document_score=0.0,
            history_score=0.0,
            consistency_score=consistency,
        )
        return {
            "hypothesis_id": str(uuid4()),
            "description": description,
            "confidence": round(confidence, 4),
            "confidence_breakdown": breakdown.as_dict(),
            "is_primary": False,
            "causal_chain_id": None,
            "source": "firmware_mode_correlation",
            "diagnostic_kind": diagnostic_kind,
            "firmware_assessment": "indeterminate" if invalid else "consistent",
            "persistent": False,
            "active_now": False,
            "active_frames": 0,
            "source_channels": "",
            "limitations": limitations,
            "corroborating_knowledge_units": [],
        }

    def _bounded_confidence(self, value: object) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    def _generate_firmware_mode_hypotheses(
        self,
        modes: list[FirmwareModeEvidence],
        similar_kus: list[dict[str, Any]],
        causal_chains: list[dict[str, Any]],
        *,
        reported_context: str = "",
    ) -> list[dict[str, Any]]:
        hypotheses: list[dict[str, Any]] = []
        for mode in modes:
            matching_kus = matching_knowledge_units(mode, similar_kus)
            matching_chains = matching_causal_chains(mode, causal_chains)
            evidence_score = max(mode.confidence, mode.evidence_confidence)
            document_score = max(
                (self._authority_score(item.get("authority")) for item in matching_kus),
                default=0.0,
            )
            confirmed = sum(
                item.get("knowledge_level") in {"confirmed", "consolidated"}
                for item in matching_kus
            )
            context_corroborates = reported_context_supports_mode(
                mode,
                reported_context,
            )
            history_score = confirmed / (confirmed + 1) if confirmed else 0.0
            consistency_score = (
                1.0
                if mode.persistent and mode.active_now
                else 0.8
                if mode.persistent
                else 0.6
                if context_corroborates
                else 0.5
            )
            breakdown = ConfidenceBreakdown(
                evidence_score=evidence_score,
                document_score=document_score,
                history_score=history_score,
                consistency_score=consistency_score,
            )
            confidence = compute_confidence(breakdown, self._weights)
            hypotheses.append(
                {
                    "hypothesis_id": str(uuid4()),
                    "description": format_mode_description(
                        mode,
                        corroborating_documents=len(matching_kus),
                        corroborating_chains=len(matching_chains),
                    ),
                    "confidence": round(confidence, 4),
                    "confidence_breakdown": breakdown.as_dict(),
                    "is_primary": False,
                    "causal_chain_id": (
                        str(matching_chains[0]["id"]) if matching_chains else None
                    ),
                    "source": "firmware_mode_correlation",
                    "diagnostic_kind": mode.mode_id,
                    "firmware_assessment": mode.assessment,
                    "persistent": mode.persistent,
                    "active_now": mode.active_now,
                    "active_frames": mode.active_frames,
                    "source_channels": mode.source_channels,
                    "limitations": [mode.limitation] if mode.limitation else [],
                    "reported_context_corroboration": context_corroborates,
                    "corroborating_knowledge_units": [
                        str(item["id"]) for item in matching_kus if item.get("id")
                    ],
                }
            )
        return hypotheses

    def _reported_service_order_context(
        self,
        evidences: list[dict[str, Any]],
    ) -> str:
        return " ".join(
            str(item.get("observations") or "")
            for item in evidences
            if item.get("type") == "service_order_context"
        ).strip()

    def _authority_score(self, value: object) -> float:
        normalized = str(value or "").strip().lower()
        return {"alta": 1.0, "média": 0.6, "media": 0.6, "baixa": 0.3}.get(
            normalized,
            0.0,
        )

    def _is_generic_test_ku(self, ku: dict[str, Any]) -> bool:
        text = " ".join(
            str(ku.get(key) or "").lower()
            for key in ("title", "statement", "description")
        )
        generic_terms = (
            "teste bem-sucedido",
            "teste bem sucedido",
            "smoke",
            "hello world",
        )
        return any(term in text for term in generic_terms)

    def _is_firmware_mode_ku(self, ku: dict[str, Any]) -> bool:
        """Mode KUs only corroborate a mode explicitly published by firmware."""
        text = " ".join(
            str(ku.get(key) or "").lower()
            for key in ("title", "statement", "description")
        )
        return any(mode_id in text for mode_id in MODE_DEFINITIONS)

    def _generate_telemetry_hypotheses(
        self,
        evidences: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        metrics = self._merge_evidence_metrics(evidences)
        observed_fields = {
            "bus_voltage_mv_avg", "motor_current_ma_avg", "current_ma_avg",
            "electrical_power_mw_avg", "power_mw_avg", "rpm_mpu_avg", "rpm_hall_avg",
            "latest_observation_hall_rpm_inferred", "hall_rpm_inferred",
            "rms_norm_mg_avg", "vibration_rms_mg_avg", "peak_norm_mg_avg",
            "vibration_peak_mg_avg", "bemf_error_permille_avg",
            "winding_resistance_error_permille_avg", "equivalent_resistance_error_permille_avg",
        }
        # References and collection metadata do not establish an observed condition.
        if not observed_fields.intersection(metrics):
            return []
        voltage_mv = self._metric(metrics, "bus_voltage_mv_avg")
        current_ma = abs(self._metric(metrics, "motor_current_ma_avg")) or abs(
            self._metric(metrics, "current_ma_avg")
        )
        power_mw = self._metric(metrics, "electrical_power_mw_avg") or self._metric(
            metrics, "power_mw_avg"
        )
        nominal_voltage_mv = self._metric(metrics, "nominal_voltage_mv_avg")
        nominal_current_ma = self._metric(metrics, "nominal_current_ma_avg")
        rpm_motor = self._metric(metrics, "rpm_mpu_avg")
        rpm_cycle = (
            self._metric(metrics, "rpm_hall_avg")
            or self._metric(metrics, "latest_observation_hall_rpm_inferred")
            or self._metric(metrics, "hall_rpm_inferred")
        )
        cycle_error = (
            abs(rpm_motor - rpm_cycle) * 1000.0 / rpm_motor
            if rpm_motor > 0 and rpm_cycle > 0
            else 0.0
        )
        efficiency = self._efficiency_permille(metrics)
        vibration_rms = self._metric(metrics, "rms_norm_mg_avg") or self._metric(
            metrics, "vibration_rms_mg_avg"
        )
        vibration_peak = self._metric(metrics, "peak_norm_mg_avg") or self._metric(
            metrics, "vibration_peak_mg_avg"
        )
        bemf_error = abs(self._metric(metrics, "bemf_error_permille_avg"))
        resistance_error = abs(
            self._metric(metrics, "winding_resistance_error_permille_avg")
            or self._metric(metrics, "equivalent_resistance_error_permille_avg")
        )

        description = "Assinatura eletromecânica compatível com operação normal"
        confidence = 0.56
        diagnostic_kind = "normal_signature"
        reasons: list[str] = []

        if bemf_error >= 200 or resistance_error >= 250:
            description = "Desvio no modelo elétrico do motor"
            confidence = 0.64
            diagnostic_kind = "electrical_model_deviation"
            if bemf_error:
                reasons.append(f"erro BEMF {bemf_error:.0f}‰")
            if resistance_error:
                reasons.append(f"erro de resistência da bobina {resistance_error:.0f}‰")
        elif cycle_error >= 120:
            description = "Divergência entre rotação do motor e ciclo mecânico"
            confidence = 0.63
            diagnostic_kind = "cycle_speed_mismatch"
            reasons.append(f"RPM do motor {rpm_motor:.0f}")
            reasons.append(f"cadência equivalente Hall {rpm_cycle:.0f}")
            reasons.append(f"diferença {cycle_error:.0f}‰")
        elif vibration_rms >= 700 or vibration_peak >= 1200:
            description = "Vibração elevada correlacionada à rotação"
            confidence = 0.64
            diagnostic_kind = "high_vibration"
            reasons.append(f"RMS médio {vibration_rms:.0f} mg")
            if vibration_peak:
                reasons.append(f"pico médio {vibration_peak:.0f} mg")
        elif efficiency and efficiency < 700:
            description = "Baixa eficiência eletromecânica estimada no motor"
            confidence = 0.60
            diagnostic_kind = "low_efficiency"
            reasons.append(f"eficiência média {self._format_percent_permille(efficiency)}")
        elif nominal_voltage_mv > 0 and voltage_mv > nominal_voltage_mv:
            description = "Tensão acima da referência informada do motor"
            confidence = 0.62
            diagnostic_kind = "voltage_above_informed_reference"
            reasons.append(f"tensão média {voltage_mv:.0f} mV")
            reasons.append(f"referência {nominal_voltage_mv:.0f} mV")
        elif nominal_current_ma > 0 and current_ma >= nominal_current_ma:
            description = "Corrente no limite ou acima da referência informada"
            confidence = 0.61
            diagnostic_kind = "current_at_informed_limit"
            reasons.append(f"corrente média {current_ma:.0f} mA")
            reasons.append(f"referência {nominal_current_ma:.0f} mA")
        else:
            if voltage_mv:
                reasons.append(f"tensão média {voltage_mv:.0f} mV")
            if current_ma:
                reasons.append(f"corrente média {current_ma:.0f} mA")
            if power_mw:
                reasons.append(f"potência média {power_mw:.0f} mW")
            if rpm_motor:
                reasons.append(f"RPM do motor {rpm_motor:.0f}")
            if vibration_rms:
                reasons.append(f"vibração RMS média {vibration_rms:.0f} mg")

        if bemf_error >= 120 and diagnostic_kind != "electrical_model_deviation":
            reasons.append(f"erro BEMF {bemf_error:.0f}‰")
        if resistance_error >= 200 and diagnostic_kind != "electrical_model_deviation":
            reasons.append(f"erro de resistência equivalente {resistance_error:.0f}‰")

        if reasons:
            description = f"{description}: {', '.join(reasons[:4])}"

        return [
            {
                "hypothesis_id": str(uuid4()),
                "description": description,
                "confidence": confidence,
                "confidence_breakdown": {
                    "evidence_score": min(len(evidences) / 5.0, 1.0),
                    "document_score": 0.0,
                    "history_score": 0.0,
                    "consistency_score": 0.7,
                },
                "is_primary": can_be_primary_hypothesis(confidence),
                "causal_chain_id": None,
                "source": "telemetry_fallback",
                "diagnostic_kind": diagnostic_kind,
            }
        ]

    def _merge_evidence_metrics(self, evidences: list[dict[str, Any]]) -> dict[str, float]:
        metrics: dict[str, float] = {}
        def collect(mapping: dict[str, Any], prefix: str = "") -> None:
            if mapping.get("valid") is False:
                return
            for key, value in mapping.items():
                qualified_key = f"{prefix}_{key}" if prefix else key
                if isinstance(value, bool) or not isinstance(value, int | float):
                    if isinstance(value, dict):
                        collect(value, qualified_key)
                    continue
                metrics.setdefault(key, float(value))
                metrics[qualified_key] = float(value)

        for evidence in evidences:
            collect(evidence)
        return metrics

    def _metric(self, metrics: dict[str, float], key: str) -> float:
        value = metrics.get(key)
        if value is None and key.endswith("_avg"):
            value = metrics.get(key[:-4])
        return float(value or 0.0)

    def _ratio_permille(self, numerator: float, denominator: float) -> float:
        if numerator <= 0 or denominator <= 0:
            return 0.0
        return (numerator * 1000.0) / denominator

    def _efficiency_permille(self, metrics: dict[str, float]) -> float:
        mechanical_power = self._metric(metrics, "mechanical_power_mw_avg")
        electrical_power = self._metric(metrics, "electrical_power_mw_avg") or self._metric(
            metrics, "power_mw_avg"
        )
        computed = self._ratio_permille(mechanical_power, electrical_power)
        return computed or self._metric(metrics, "efficiency_permille_avg")

    def _format_percent_permille(self, value: float) -> str:
        return f"{value / 10.0:.1f}%"

    async def _build_explanation(
        self,
        hypotheses: list[dict[str, Any]],
        evidences: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Constrói explicação narrativa a partir da hipótese principal."""
        primary = next((h for h in hypotheses if h.get("is_primary")), None)
        if not primary and hypotheses:
            primary = hypotheses[0]
        if not primary:
            return None

        narrative = self._build_firmware_mode_explanation(primary)
        if narrative is None:
            narrative = self._build_telemetry_explanation(primary, evidences)
        if narrative is None:
            evidence_types = set(e.get("type", "?") for e in evidences)
            narrative = (
                "Hipótese inferida a partir da consistência entre as evidências "
                f"disponíveis ({', '.join(sorted(evidence_types))}). "
                f"Conclusão principal: {primary['description']} "
                f"(confiança: {primary['confidence']:.0%})"
            )
        service_order = next(
            (
                item
                for item in evidences
                if item.get("type") == "service_order_context"
            ),
            None,
        )
        if service_order:
            order_number = str(service_order.get("service_order_number") or "?")
            observations = str(service_order.get("observations") or "").strip()
            if observations:
                narrative += (
                    f" Contexto informado no cabecalho da OS {order_number}: "
                    f"{observations}. Esse relato foi usado apenas como corroboracao "
                    "contextual e nao como evidencia fisica independente."
                )
        knowledge_units_applied: list[str] = []
        for hypothesis in hypotheses:
            if hypothesis.get("source_ku_id"):
                knowledge_units_applied.append(str(hypothesis["source_ku_id"]))
            knowledge_units_applied.extend(
                str(item)
                for item in hypothesis.get("corroborating_knowledge_units") or []
            )
        knowledge_units_applied = list(dict.fromkeys(knowledge_units_applied))
        return {
            "narrative": narrative,
            "narrative_type": "technical",
            "evidence_ids": [],
            "knowledge_units_applied": knowledge_units_applied,
            "confidence": primary["confidence"],
        }

    def _build_firmware_mode_explanation(
        self,
        primary: dict[str, Any],
    ) -> str | None:
        if primary.get("source") != "firmware_mode_correlation":
            return None
        diagnostic_kind = str(primary.get("diagnostic_kind") or "")
        limitations = [
            str(item)
            for item in primary.get("limitations") or []
            if str(item).strip()
        ]
        if diagnostic_kind == "invalid_correlation_evidence":
            limitation = f" {limitations[0]}" if limitations else ""
            return (
                f"{primary.get('description')}.{limitation} O OpenTracy nao aplicou "
                "a heuristica legada para evitar uma classificacao normal indevida."
            )
        if diagnostic_kind == "no_active_firmware_mode":
            limitation = f" {limitations[0]}" if limitations else ""
            return (
                f"{primary.get('description')}.{limitation} O OpenTracy preservou "
                "o resultado consistente do firmware sem transforma-lo em prova de "
                "ausencia de falha."
            )
        state = (
            "persistiu em janelas consecutivas"
            if primary.get("persistent")
            else "ocorreu de forma transitoria"
        )
        current = (
            "permanece ativa no ultimo frame"
            if primary.get("active_now")
            else "nao permanece ativa no ultimo frame"
        )
        documents = primary.get("corroborating_knowledge_units") or []
        documentary = (
            f"O OpenTracy encontrou {len(documents)} unidade(s) de conhecimento "
            "corroborante(s)."
            if documents
            else (
                "O OpenTracy nao encontrou unidade de conhecimento especifica que "
                "corrobore este modo; a confianca permanece limitada a evidencia fisica."
            )
        )
        sources = str(primary.get("source_channels") or "nao declarados")
        limitation = (
            f" Limitacao declarada pelo firmware: {limitations[0]}."
            if limitations
            else ""
        )
        return (
            "O OpenTracy interpretou a relacao causal publicada pelo firmware como "
            f"{primary.get('description')}. A hipotese {state} e {current}. "
            f"Canais usados pelo firmware: {sources}. {documentary}{limitation} "
            "O resultado continua sendo uma hipotese tecnica e requer confirmacao "
            "por inspecao ou ensaio independente."
        )

    def _build_telemetry_explanation(
        self,
        primary: dict[str, Any],
        evidences: list[dict[str, Any]],
    ) -> str | None:
        metrics = self._merge_evidence_metrics(evidences)
        voltage_mv = self._metric(metrics, "bus_voltage_mv_avg")
        current_ma = abs(self._metric(metrics, "motor_current_ma_avg")) or abs(
            self._metric(metrics, "current_ma_avg")
        )
        electrical_power = self._metric(metrics, "electrical_power_mw_avg") or self._metric(
            metrics, "power_mw_avg"
        )
        rpm_motor = self._metric(metrics, "rpm_mpu_avg")
        rpm_cycle = (
            self._metric(metrics, "rpm_hall_avg")
            or self._metric(metrics, "latest_observation_hall_rpm_inferred")
            or self._metric(metrics, "hall_rpm_inferred")
        )
        torque = self._metric(metrics, "torque_uNm_avg")
        mechanical_power = self._metric(metrics, "mechanical_power_mw_avg")
        efficiency = self._efficiency_permille(metrics)
        resistance_error = abs(
            self._metric(metrics, "winding_resistance_error_permille_avg")
            or self._metric(metrics, "equivalent_resistance_error_permille_avg")
        )
        bemf_error = abs(self._metric(metrics, "bemf_error_permille_avg"))
        vibration_rms = self._metric(metrics, "rms_norm_mg_avg") or self._metric(
            metrics, "vibration_rms_mg_avg"
        )
        vibration_peak = self._metric(metrics, "peak_norm_mg_avg") or self._metric(
            metrics, "vibration_peak_mg_avg"
        )

        if not any(
            (
                voltage_mv,
                current_ma,
                electrical_power,
                rpm_motor,
                rpm_cycle,
                vibration_rms,
                vibration_peak,
                bemf_error,
                resistance_error,
            )
        ):
            return None

        parts: list[str] = []
        electrical = []
        if voltage_mv:
            electrical.append(f"tensão média {voltage_mv:.0f} mV")
        if current_ma:
            electrical.append(f"corrente média {current_ma:.0f} mA")
        if electrical_power:
            electrical.append(f"potência elétrica {electrical_power:.0f} mW")
        if electrical:
            parts.append("O ponto elétrico observado foi: " + ", ".join(electrical) + ".")

        motor = []
        if rpm_motor:
            motor.append(f"rotação MPU {rpm_motor:.0f} RPM")
        if rpm_cycle:
            motor.append(f"cadência equivalente Hall {rpm_cycle:.0f} RPM")
        if torque:
            motor.append(f"torque inferido da corrente {torque:.0f} uNm")
        if mechanical_power:
            motor.append(f"potência mecânica estimada {mechanical_power:.0f} mW")
        if efficiency:
            motor.append(f"eficiência estimada {self._format_percent_permille(efficiency)}")
        if motor:
            parts.append("O modelo do motor e o ciclo informaram: " + ", ".join(motor) + ".")

        residuals = []
        if resistance_error >= 120:
            residuals.append(f"erro de resistência equivalente {resistance_error:.0f}‰")
        if bemf_error >= 120:
            residuals.append(f"erro BEMF {bemf_error:.0f}‰")
        if vibration_rms >= 700:
            residuals.append(f"vibração RMS {vibration_rms:.0f} mg")
        if vibration_peak >= 1200:
            residuals.append(f"pico de vibração {vibration_peak:.0f} mg")
        if residuals:
            parts.append(
                "Os resíduos que aumentaram a cautela da hipótese foram: "
                + ", ".join(residuals[:4])
                + "."
            )

        parts.append(
            "Curso e massa são tratados apenas como parâmetros informados do direct "
            "drive. Força, torque requerido, perdas de transmissão e carga de "
            "cartucho não participam desta hipótese porque o modelo mecânico está "
            "indisponível."
        )
        parts.append(
            f"Por isso a hipótese principal é: {primary['description']} "
            f"(confiança: {primary['confidence']:.0%})."
        )
        return " ".join(parts)

    async def _send_callback(self, item_id: UUID, result: dict[str, Any]) -> None:
        """Envia callback ao Cous com o resultado do diagnóstico."""
        # Buscar callback_endpoint dos metadados do item
        async with self._repo._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT callback_endpoint FROM diagnosis_queue WHERE id = $1", item_id
            )

        callback_url = "http://localhost:8000/cous/diagnosis/callback"
        if row is not None:
            try:
                callback_url = row["callback_endpoint"] or callback_url
            except (KeyError, TypeError):
                pass
        try:
            response = await self._http.post(
                callback_url,
                json={
                    "schema_version": "3.0",
                    "correlation_id": result["correlation_id"],
                    "capture_session_id": result["capture_session_id"],
                    "trace_id": result["trace_id"],
                    "duration_ms": result.get("duration_ms", 0),
                    "hypotheses": result.get("hypotheses", []),
                    "explanation": result.get("explanation"),
                    "error": result.get("error"),
                },
                timeout=10.0,
            )
            response.raise_for_status()
            logger.info("Callback enviado para %s: correlation_id=%s, hypotheses=%d",
                         callback_url, result["correlation_id"], len(result.get("hypotheses", [])))
        except Exception as e:
            logger.warning("Falha ao enviar callback para %s: %s", callback_url, e)
            raise

    async def _mark_completed(self, item_id: UUID, result: dict[str, Any]) -> None:
        async with self._repo._pool.acquire() as conn:
            await conn.execute(
                """UPDATE diagnosis_queue
                   SET status = 'completed',
                       result_payload = $2::jsonb,
                       error_message = NULL,
                       last_attempt_at = NOW(),
                       callback_status = CASE WHEN request_payload->>'delivery_mode' = 'polling' THEN 'not_required' ELSE 'pending' END,
                       callback_next_attempt_at = NOW(),
                       callback_error = NULL
                   WHERE id = $1""",
                item_id,
                json.dumps(result, default=str),
            )
        logger.info("Diagnóstico concluído: %s", item_id)

    async def _mark_failed(
        self,
        item_id: UUID,
        error: str,
        result: dict[str, Any],
    ) -> None:
        async with self._repo._pool.acquire() as conn:
            await conn.execute(
                """UPDATE diagnosis_queue
                   SET status = 'failed',
                       error_message = $2,
                       result_payload = $3::jsonb,
                       last_attempt_at = NOW(),
                       callback_status = CASE WHEN request_payload->>'delivery_mode' = 'polling' THEN 'not_required' ELSE 'pending' END,
                       callback_next_attempt_at = NOW(),
                       callback_error = NULL
                   WHERE id = $1""",
                item_id,
                error[:500],
                json.dumps(result, default=str),
            )
        logger.error("Diagnóstico falhou: %s — %s", item_id, error)

    async def _mark_callback_delivered(self, item_id: UUID) -> None:
        async with self._repo._pool.acquire() as conn:
            await conn.execute(
                """UPDATE diagnosis_queue
                   SET callback_status = 'delivered',
                       callback_next_attempt_at = NULL,
                       callback_error = NULL
                   WHERE id = $1""",
                item_id,
            )

    async def _mark_callback_failed(self, item_id: UUID, error: str) -> None:
        async with self._repo._pool.acquire() as conn:
            await conn.execute(
                """UPDATE diagnosis_queue
                   SET callback_status = 'failed',
                       callback_error = $2,
                       callback_next_attempt_at = NOW() + make_interval(
                           secs => LEAST(
                               300,
                               power(2, LEAST(callback_attempts, 8))::INTEGER
                           )
                       )
                   WHERE id = $1""",
                item_id,
                error[:500],
            )
        logger.warning("Callback pendente para diagnostico %s: %s", item_id, error)
