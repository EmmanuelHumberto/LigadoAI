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
        numeric_values = [
            value
            for key, value in payload.items()
            if key not in {"type", "timestamp_us"} and isinstance(value, int | float)
        ]
        if not numeric_values:
            errors.append(
                {
                    "code": "missing_numeric_values",
                    "message": "snapshot must include at least one numeric measurement",
                }
            )
        return SnapshotValidationResult(approved=not errors, errors=errors)
