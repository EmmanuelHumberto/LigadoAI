"""Tests for firmware mode flags in causal expressions."""

from knowledge.domain.causal_engine import evaluate_condition


def test_causal_engine_accepts_published_failure_mode_flags():
    assert evaluate_condition(
        "locked_rotor_hypothesis >= 1",
        {"locked_rotor_hypothesis": 1},
    )
    assert not evaluate_condition(
        "locked_rotor_hypothesis >= 1",
        {"locked_rotor_hypothesis": 0},
    )
