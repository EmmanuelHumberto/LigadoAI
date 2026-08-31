"""Semantic interpretation of COUS electromechanical diagnosis evidence."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any

CORRELATION_TYPE = "electromechanical_correlation_frame"
CORRELATION_VERSION = 4
MAX_CONFIRMATION_GAP_US = 5_000_000

_ASSESSMENT_NAMES = {
    0: "observation",
    1: "consistent",
    2: "suspect",
    3: "critical",
    4: "indeterminate",
}


@dataclass(frozen=True)
class ModeDefinition:
    label: str
    quantity: str
    unit: str
    knowledge_terms: tuple[str, ...]


MODE_DEFINITIONS: dict[str, ModeDefinition] = {
    "locked_rotor_hypothesis": ModeDefinition(
        label="Rotor travado",
        quantity="corrente",
        unit="mA",
        knowledge_terms=(
            "rotor travado",
            "motor travado",
            "stall",
            "corrente de bloqueio",
            "corrente de stall",
        ),
    ),
    "mechanical_decoupling_hypothesis": ModeDefinition(
        label="Desacoplamento mecanico",
        quantity="corrente",
        unit="mA",
        knowledge_terms=(
            "desacoplamento mecanico",
            "eixo quebrado",
            "came solto",
            "stroke solto",
            "giro em falso",
        ),
    ),
    "motor_nominal_overload_hypothesis": ModeDefinition(
        label="Sobrecarga do motor",
        quantity="corrente",
        unit="mA",
        knowledge_terms=(
            "sobrecarga do motor",
            "corrente nominal",
            "sobrecorrente",
            "motor sobrecarregado",
        ),
    ),
    "source_overvoltage_hypothesis": ModeDefinition(
        label="Sobretensao da fonte",
        quantity="tensao",
        unit="mV",
        knowledge_terms=(
            "sobretensao",
            "tensao acima da nominal",
            "overvoltage",
        ),
    ),
    "source_interruption_hypothesis": ModeDefinition(
        label="Interrupcao da fonte",
        quantity="tensao minima",
        unit="mV",
        knowledge_terms=(
            "interrupcao da fonte",
            "interrupcao de tensao",
            "queda a zero",
            "dropout",
        ),
    ),
    "source_sag_under_load_hypothesis": ModeDefinition(
        label="Queda de tensao sob carga",
        quantity="variacao de tensao",
        unit="mV",
        knowledge_terms=(
            "queda de tensao sob carga",
            "afundamento de tensao",
            "voltage sag",
            "fonte nao sustenta carga",
        ),
    ),
}

MODE_DESCRIPTIONS = {
    "locked_rotor_hypothesis": (
        "Rotacao ausente com corrente igual ou superior a duas vezes a nominal."
    ),
    "mechanical_decoupling_hypothesis": (
        "Motor proximo da curva em vazio, com FCEM alta e sem transferencia da carga."
    ),
    "motor_nominal_overload_hypothesis": (
        "Corrente proxima ou superior a nominal, ou sistema energizado sem movimento."
    ),
    "source_overvoltage_hypothesis": (
        "Tensao aplicada superior a tensao nominal do perfil selecionado."
    ),
    "source_interruption_hypothesis": (
        "Envelope eletrico com queda sustentada proxima de zero durante uma janela energizada."
    ),
    "source_sag_under_load_hypothesis": (
        "Aumento de corrente acompanhado por queda sustentada de tensao entre janelas."
    ),
}


@dataclass(frozen=True)
class FirmwareModeEvidence:
    mode_id: str
    label: str
    description: str
    assessment: str
    confidence: float
    persistent: bool
    active_now: bool
    active_frames: int
    max_consecutive_frames: int
    observed: float | None
    reference: float | None
    residual: float | None
    source_channels: str
    limitation: str
    evidence_strength: str
    evidence_confidence: float

    @property
    def definition(self) -> ModeDefinition:
        return MODE_DEFINITIONS[self.mode_id]


def extract_firmware_modes(
    evidences: list[dict[str, Any]],
) -> list[FirmwareModeEvidence]:
    """Extract known active suspect/critical modes from correlation evidence."""
    selected: dict[str, FirmwareModeEvidence] = {}
    for evidence in evidences:
        if evidence.get("type") != CORRELATION_TYPE:
            continue
        modes = evidence.get("diagnostic_modes")
        if not isinstance(modes, list):
            continue
        for raw in modes:
            mode = _parse_mode(raw, evidence)
            if mode is None:
                continue
            previous = selected.get(mode.mode_id)
            if previous is None or _mode_priority(mode) > _mode_priority(previous):
                selected[mode.mode_id] = mode
    return sorted(selected.values(), key=_mode_priority, reverse=True)


def summarize_persisted_relations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild the firmware temporal mode summary from normalized relation rows."""
    frames: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        relation_id = str(row.get("relation_id") or "")
        if relation_id not in MODE_DEFINITIONS:
            continue
        timestamp_us = _integer(row.get("timestamp_us"))
        snapshot_id = str(row.get("snapshot_id") or timestamp_us)
        frames.setdefault((snapshot_id, timestamp_us), {})[relation_id] = dict(row)

    states: dict[str, dict[str, Any]] = {
        mode_id: {
            "id": mode_id,
            "label": definition.label,
            "description": MODE_DESCRIPTIONS[mode_id],
            "observed_frames": 0,
            "active_frames": 0,
            "current_streak": 0,
            "max_consecutive_frames": 0,
            "active_now": False,
            "max_assessment": 1,
            "confidence_values": [],
            "latest": None,
            "latest_active": None,
            "last_active_timestamp_us": None,
        }
        for mode_id, definition in MODE_DEFINITIONS.items()
    }

    for (_, timestamp_us), relations in sorted(frames.items(), key=lambda item: item[0][1]):
        for mode_id, state in states.items():
            relation = relations.get(mode_id)
            valid = bool(relation and relation.get("valid") is True)
            assessment = _assessment_integer(relation.get("assessment")) if valid else None
            active = assessment in {2, 3}
            state["active_now"] = active
            if not valid:
                state["current_streak"] = 0
                state["last_active_timestamp_us"] = None
                continue
            state["observed_frames"] += 1
            state["latest"] = relation
            if not active:
                state["current_streak"] = 0
                state["last_active_timestamp_us"] = None
                continue
            previous_timestamp_us = state["last_active_timestamp_us"]
            continuous = (
                previous_timestamp_us is not None
                and timestamp_us >= previous_timestamp_us
                and timestamp_us - previous_timestamp_us <= MAX_CONFIRMATION_GAP_US
            )
            confidence = _permille_integer(relation.get("confidence_permille"))
            state["confidence_values"].append(confidence)
            state["latest_active"] = relation
            state["active_frames"] += 1
            state["current_streak"] = state["current_streak"] + 1 if continuous else 1
            state["last_active_timestamp_us"] = timestamp_us
            state["max_consecutive_frames"] = max(
                state["max_consecutive_frames"],
                state["current_streak"],
            )
            state["max_assessment"] = max(state["max_assessment"], assessment)

    summaries: list[dict[str, Any]] = []
    for state in states.values():
        if not state["observed_frames"]:
            continue
        latest = state.pop("latest_active") or state.pop("latest") or {}
        state.pop("latest", None)
        confidence_values = state.pop("confidence_values")
        state.pop("current_streak")
        state.pop("last_active_timestamp_us")
        max_assessment = state.pop("max_assessment")
        state["assessment"] = _ASSESSMENT_NAMES[max_assessment]
        state["confidence_permille_max"] = max(confidence_values, default=0)
        state["confidence_permille_avg"] = (
            int(sum(confidence_values) / len(confidence_values))
            if confidence_values
            else 0
        )
        state["persistent"] = state["max_consecutive_frames"] >= 2
        for key in ("observed", "reference", "residual"):
            state[key] = latest.get(key)
        state["source_channels"] = latest.get("source_channels") or ""
        state["limitation"] = latest.get("limitation") or ""
        summaries.append(state)
    return summaries


def build_persisted_correlation_evidence(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not rows:
        return None
    modes = summarize_persisted_relations(rows)
    frame_count = len(
        {
            (str(row.get("snapshot_id") or ""), _integer(row.get("timestamp_us")))
            for row in rows
        }
    )
    active_modes = [mode for mode in modes if mode["active_frames"] > 0]
    max_confidence = max(
        (mode["confidence_permille_max"] for mode in active_modes),
        default=0,
    )
    persistent = any(mode["persistent"] for mode in active_modes)
    if persistent:
        strength = "strong" if max_confidence >= 800 else "moderate"
    elif active_modes:
        strength = "weak"
    else:
        strength = "moderate" if frame_count >= 2 else "weak"
    valid_ratio = sum(row.get("valid") is True for row in rows) / len(rows)
    return {
        "type": CORRELATION_TYPE,
        "version": CORRELATION_VERSION,
        "count": frame_count,
        "valid_ratio": valid_ratio,
        "strength": strength,
        "confidence": max_confidence / 1000.0 if active_modes else valid_ratio,
        "diagnostic_modes": modes,
        "source_reference": "opentracy:electromechanical_correlation_relations",
    }


def correlation_contract_state(evidences: list[dict[str, Any]]) -> str:
    """Return absent, valid or invalid for the COUS correlation evidence."""
    correlations = [
        evidence
        for evidence in evidences
        if evidence.get("type") == CORRELATION_TYPE
    ]
    if not correlations:
        return "absent"
    if any(not isinstance(evidence.get("diagnostic_modes"), list) for evidence in correlations):
        return "invalid"
    return "valid"


def matching_knowledge_units(
    mode: FirmwareModeEvidence,
    knowledge_units: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matches = [
        item
        for item in knowledge_units
        if _matches_terms(_knowledge_text(item), mode.definition.knowledge_terms)
    ]
    matches.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
    return matches


def matching_causal_chains(
    mode: FirmwareModeEvidence,
    causal_chains: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    matches = [
        item
        for item in causal_chains
        if _matches_terms(_causal_text(item), mode.definition.knowledge_terms)
    ]
    matches.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
    return matches


def reported_context_supports_mode(
    mode: FirmwareModeEvidence,
    context: str,
) -> bool:
    """Treat an OS report as weak corroboration, never as physical evidence."""
    return bool(context.strip()) and _matches_terms(
        context,
        mode.definition.knowledge_terms,
    )


def extract_causal_metrics(evidences: list[dict[str, Any]]) -> dict[str, Any]:
    """Expose selected closure fields to the existing causal expression engine."""
    metrics: dict[str, Any] = {}
    for evidence in evidences:
        if evidence.get("type") != CORRELATION_TYPE:
            continue
        closure = evidence.get("closure")
        if not isinstance(closure, dict):
            continue
        for section in ("electrical", "motor", "transmission", "cartridge"):
            values = closure.get(section)
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                if isinstance(value, bool) or not isinstance(value, int | float):
                    continue
                metrics[key] = value
        modes = evidence.get("diagnostic_modes")
        if isinstance(modes, list):
            for mode in modes:
                if not isinstance(mode, dict):
                    continue
                mode_id = str(mode.get("id") or "")
                if mode_id not in MODE_DEFINITIONS:
                    continue
                assessment = str(mode.get("assessment") or "").lower()
                active_frames = _integer(mode.get("active_frames"))
                metrics[mode_id] = (
                    1
                    if assessment in {"suspect", "critical"} and active_frames > 0
                    else 0
                )
    return metrics


def format_mode_description(
    mode: FirmwareModeEvidence,
    *,
    corroborating_documents: int,
    corroborating_chains: int,
) -> str:
    temporal = (
        f"persistente por {mode.max_consecutive_frames} frames consecutivos"
        if mode.persistent
        else f"transitoria em {mode.active_frames} frame(s)"
    )
    current = (
        "ativa no frame mais recente"
        if mode.active_now
        else "nao ativa no frame mais recente"
    )
    relation = ""
    if mode.observed is not None and mode.reference is not None:
        relation = (
            f"; {mode.definition.quantity} observada {mode.observed:g} "
            f"{mode.definition.unit}, referencia {mode.reference:g} "
            f"{mode.definition.unit}"
        )
    corroboration = (
        f"; corroboracao OpenTracy: {corroborating_documents} unidade(s) de "
        f"conhecimento e {corroborating_chains} cadeia(s) causal(is)"
    )
    return f"{mode.label}: hipotese {temporal}, {current}{relation}{corroboration}"


def _parse_mode(
    raw: object,
    evidence: dict[str, Any],
) -> FirmwareModeEvidence | None:
    if not isinstance(raw, dict):
        return None
    mode_id = str(raw.get("id") or "")
    if mode_id not in MODE_DEFINITIONS:
        return None
    assessment = str(raw.get("assessment") or "").lower()
    active_frames = _integer(raw.get("active_frames"))
    if assessment not in {"suspect", "critical"} or active_frames <= 0:
        return None
    definition = MODE_DEFINITIONS[mode_id]
    declared_confidence = _permille_confidence(raw.get("confidence_permille_max"))
    evidence_confidence = _confidence(evidence.get("confidence"))
    return FirmwareModeEvidence(
        mode_id=mode_id,
        label=str(raw.get("label") or definition.label),
        description=str(raw.get("description") or ""),
        assessment=assessment,
        confidence=declared_confidence,
        persistent=raw.get("persistent") is True,
        active_now=raw.get("active_now") is True,
        active_frames=active_frames,
        max_consecutive_frames=_integer(raw.get("max_consecutive_frames")),
        observed=_number(raw.get("observed")),
        reference=_number(raw.get("reference")),
        residual=_number(raw.get("residual")),
        source_channels=str(raw.get("source_channels") or ""),
        limitation=str(raw.get("limitation") or ""),
        evidence_strength=str(evidence.get("strength") or "weak"),
        evidence_confidence=evidence_confidence,
    )


def _mode_priority(mode: FirmwareModeEvidence) -> tuple[int, int, float]:
    return (
        1 if mode.assessment == "critical" else 0,
        1 if mode.persistent else 0,
        mode.confidence,
    )


def _matches_terms(text: str, terms: tuple[str, ...]) -> bool:
    normalized = _normalize(text)
    return any(_normalize(term) in normalized for term in terms)


def _knowledge_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("title", "statement", "description", "tags")
    )


def _causal_text(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in (
            "title",
            "probable_cause",
            "expected_consequence",
            "condition_expression",
        )
    )


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.lower())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def _integer(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _permille_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value) / 1000.0))
    except (TypeError, ValueError):
        return 0.0


def _assessment_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        assessment = int(value)
    except (TypeError, ValueError):
        return None
    return assessment if assessment in _ASSESSMENT_NAMES else None


def _permille_integer(value: object) -> int:
    try:
        return max(0, min(1000, int(value)))
    except (TypeError, ValueError):
        return 0
