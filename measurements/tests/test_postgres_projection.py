"""Tests for normalized projection of firmware correlation frames."""

from measurements.infrastructure.postgres.repository import _correlation_projection


def test_correlation_projection_preserves_explainable_relations():
    frame = {
        "type": "electromechanical_correlation_frame",
        "version": 4,
        "valid": True,
        "profile": {"id": "motor-2014", "label": "EC 2014"},
        "closure": {"electrical": {}, "motor": {}},
        "relations": [
            {
                "id": "locked_rotor_hypothesis",
                "layer": 3,
                "assessment": 3,
                "observed": 900,
                "reference": 800,
                "residual": 100,
                "error_permille": 125,
                "confidence_permille": 860,
                "source_channels": "mpu,power,motor_nominal_current",
                "limitation": "requires independent confirmation",
                "valid": True,
            }
        ],
    }

    projection = _correlation_projection(frame)

    assert projection is not None
    assert projection["profile_label"] == "EC 2014"
    assert projection["relations"] == [
        {
            "relation_id": "locked_rotor_hypothesis",
            "layer": 3,
            "assessment": 3,
            "observed": 900,
            "reference": 800,
            "residual": 100,
            "error_permille": 125,
            "confidence_permille": 860,
            "source_channels": "mpu,power,motor_nominal_current",
            "limitation": "requires independent confirmation",
            "valid": True,
        }
    ]
