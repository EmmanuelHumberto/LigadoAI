"""Snapshot validation rules for TMA_DATA payloads."""

from __future__ import annotations

from typing import Any

from measurements.domain import SnapshotValidationResult

_TYPE_ALIASES = {
    "hall": "hall",
    "hall_snapshot": "hall",
    "power": "power",
    "power_snapshot": "power",
    "vibration": "vibration",
    "vibration_snapshot": "vibration",
    "course": "course",
    "course_snapshot": "course",
    "electromechanical_observation_frame": "electromechanical_observation_frame",
    "electromechanical_correlation_frame": "electromechanical_correlation_frame",
}

_AGGREGATE_VERSIONS = {
    "electromechanical_observation_frame": 3,
    "electromechanical_correlation_frame": 4,
}


class BasicSnapshotValidator:
    def normalize_type(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        return _TYPE_ALIASES.get(raw, raw)

    def validate(self, payload: dict[str, Any]) -> SnapshotValidationResult:
        errors: list[dict[str, Any]] = []
        raw_type = str(payload.get("type") or "").strip().lower()
        snapshot_type = self.normalize_type(raw_type)
        if not snapshot_type:
            errors.append({"code": "missing_type", "message": "snapshot type is required"})
        elif snapshot_type not in _TYPE_ALIASES.values():
            errors.append(
                {
                    "code": "unknown_type",
                    "message": f"unsupported snapshot type: {raw_type}",
                }
            )
        timestamp = payload.get("timestamp_us")
        if timestamp is not None and not isinstance(timestamp, int):
            errors.append(
                {
                    "code": "invalid_timestamp",
                    "message": "timestamp_us must be an integer when present",
                }
            )
        if snapshot_type in _AGGREGATE_VERSIONS:
            errors.extend(self._validate_aggregate(snapshot_type, payload))
        else:
            numeric_values = [
                value
                for key, value in payload.items()
                if key not in {"type", "timestamp_us"}
                and isinstance(value, int | float)
                and not isinstance(value, bool)
            ]
            if not numeric_values:
                errors.append(
                    {
                        "code": "missing_numeric_values",
                        "message": "snapshot must include at least one numeric measurement",
                    }
                )
        return SnapshotValidationResult(approved=not errors, errors=errors)

    def _validate_aggregate(
        self,
        snapshot_type: str,
        payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        errors: list[dict[str, Any]] = []
        expected_version = _AGGREGATE_VERSIONS[snapshot_type]
        version = payload.get("version")
        if version != expected_version:
            errors.append(
                {
                    "code": "unsupported_contract_version",
                    "message": (
                        f"{snapshot_type} requires version {expected_version}; "
                        f"received {version!r}"
                    ),
                }
            )

        if not isinstance(payload.get("valid"), bool):
            errors.append(
                {"code": "invalid_valid_flag", "message": "valid must be a boolean"}
            )

        if snapshot_type == "electromechanical_observation_frame":
            required_mappings = ("channels", "hall", "power", "vibration")
            required_lists: tuple[str, ...] = ()
        else:
            required_mappings = ("profile", "physical_signature", "closure")
            required_lists = ("axes", "relations")

        for field in required_mappings:
            if not isinstance(payload.get(field), dict):
                errors.append(
                    {
                        "code": "invalid_aggregate_field",
                        "field": field,
                        "message": f"{field} must be an object",
                    }
                )
        for field in required_lists:
            if not isinstance(payload.get(field), list):
                errors.append(
                    {
                        "code": "invalid_aggregate_field",
                        "field": field,
                        "message": f"{field} must be an array",
                    }
                )

        if snapshot_type == "electromechanical_correlation_frame":
            relation_count = payload.get("relation_count")
            relations = payload.get("relations")
            if not isinstance(relation_count, int) or isinstance(relation_count, bool):
                errors.append(
                    {
                        "code": "invalid_relation_count",
                        "message": "relation_count must be an integer",
                    }
                )
            elif isinstance(relations, list) and relation_count != len(relations):
                errors.append(
                    {
                        "code": "relation_count_mismatch",
                        "message": "relation_count must match relations length",
                    }
                )
        return errors
