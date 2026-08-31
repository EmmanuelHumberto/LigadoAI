"""Testes unitários para o Sistema Formal de Confiança — COUS v3.0."""

import pytest
from knowledge.domain.confidence import (
    DomainWeights,
    build_breakdown,
    compute_confidence,
    compute_consistency_score,
    compute_document_score,
    compute_evidence_score,
    compute_history_score,
    interpret_confidence,
    can_auto_diagnose,
    can_be_primary_hypothesis,
    can_be_consolidated,
)
from knowledge.domain.cous_models import ConfidenceBreakdown


class TestEvidenceScore:
    def test_empty_returns_zero(self):
        assert compute_evidence_score(0, 0, 0) == 0.0

    def test_all_strong_saturates(self):
        score = compute_evidence_score(n_strong=10, n_max=5)
        assert score == 1.0

    def test_mixed_weights(self):
        # (3*1.0 + 2*0.6 + 1*0.3) / 5 = (3 + 1.2 + 0.3) / 5 = 4.5/5 = 0.9
        score = compute_evidence_score(n_strong=3, n_moderate=2, n_weak=1, n_max=5)
        assert score == pytest.approx(0.9)

    def test_capped_at_one(self):
        score = compute_evidence_score(n_strong=10, n_moderate=5, n_max=3)
        assert score == 1.0


class TestDocumentScore:
    def test_empty_authorities_returns_zero(self):
        assert compute_document_score([]) == 0.0

    def test_max_authority(self):
        assert compute_document_score(["alta"]) == 1.0
        assert compute_document_score(["média"]) == 0.6
        assert compute_document_score(["baixa"]) == 0.3

    def test_returns_maximum(self):
        assert compute_document_score(["baixa", "alta", "média"]) == 1.0


class TestHistoryScore:
    def test_no_cases_returns_zero(self):
        assert compute_history_score(0, 0) == 0.0

    def test_all_confirmed(self):
        # 10 / (10 + 0 + 1) = 10/11 ≈ 0.909
        score = compute_history_score(confirmed_similar=10)
        assert score == pytest.approx(10 / 11)

    def test_refutations_reduce_score(self):
        score1 = compute_history_score(confirmed_similar=5, refuted_similar=0)
        score2 = compute_history_score(confirmed_similar=5, refuted_similar=5)
        assert score2 < score1


class TestConsistencyScore:
    def test_no_contradictions_returns_one(self):
        assert compute_consistency_score(0, 10) == 1.0

    def test_contradictions_reduce_score(self):
        score = compute_consistency_score(open_contradictions=2, total_evidences=8)
        # 1 - (2 / 9) = 1 - 0.222... = 0.777...
        assert score == pytest.approx(1 - 2 / 9)


class TestCompositeConfidence:
    def test_default_weights(self):
        breakdown = ConfidenceBreakdown(0.5, 0.8, 0.6, 0.9)
        c = compute_confidence(breakdown)
        # 0.40*0.5 + 0.25*0.8 + 0.25*0.6 + 0.10*0.9
        expected = 0.20 + 0.20 + 0.15 + 0.09
        assert c == pytest.approx(expected)

    def test_custom_weights(self):
        weights = DomainWeights(0.25, 0.25, 0.25, 0.25)
        breakdown = ConfidenceBreakdown(0.8, 0.8, 0.8, 0.8)
        c = compute_confidence(breakdown, weights)
        assert c == pytest.approx(0.8)

    def test_clamped_to_zero_one(self):
        breakdown = ConfidenceBreakdown(2.0, 0, 0, 0)
        c = compute_confidence(breakdown)
        assert 0.0 <= c <= 1.0


class TestDomainWeights:
    def test_weights_must_sum_to_one(self):
        DomainWeights(0.40, 0.25, 0.25, 0.10)  # ok

    def test_invalid_weights_raise(self):
        with pytest.raises(ValueError, match="Pesos devem somar"):
            DomainWeights(0.5, 0.5, 0.5, 0.5)

    def test_for_domain_fallback(self):
        w = DomainWeights.for_domain("unknown_domain")
        assert w.w_evidence == 0.40


class TestInterpretation:
    def test_scale(self):
        assert interpret_confidence(0.10) == "especulativo"
        assert interpret_confidence(0.30) == "fraco"
        assert interpret_confidence(0.50) == "moderado"
        assert interpret_confidence(0.70) == "robusto"
        assert interpret_confidence(0.90) == "consolidado"

    def test_thresholds(self):
        assert not can_auto_diagnose(0.15)
        assert can_auto_diagnose(0.25)
        assert not can_be_primary_hypothesis(0.50)
        assert can_be_primary_hypothesis(0.65)
        assert not can_be_consolidated(0.70)
        assert can_be_consolidated(0.85)


class TestBuildBreakdown:
    def test_full_breakdown(self):
        bd = build_breakdown(
            n_strong=3, n_moderate=2, n_weak=1,
            authorities=["alta", "média"],
            confirmed_similar=8, refuted_similar=2,
            open_contradictions=1, total_evidences=10,
        )
        assert 0 <= bd.evidence_score <= 1
        assert bd.document_score == 1.0  # max("alta", "média")
        assert 0 <= bd.history_score <= 1
        assert 0 <= bd.consistency_score <= 1
