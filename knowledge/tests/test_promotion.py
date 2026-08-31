"""Testes unitários para o Motor de Promoção/Rebaixamento — COUS v3.0."""

from datetime import UTC, datetime, timedelta

import pytest
from knowledge.domain.cous_models import KnowledgeLevel, KnowledgeUnit, Domain
from knowledge.domain.promotion import check_promotion, check_demotion, PromotionResult
from uuid import uuid4


@pytest.fixture
def experimental_ku():
    return KnowledgeUnit(
        domain_id=uuid4(),
        title="Test KU",
        statement="Test statement",
        knowledge_level=KnowledgeLevel.EXPERIMENTAL,
    )


@pytest.fixture
def observed_ku():
    return KnowledgeUnit(
        domain_id=uuid4(),
        title="Test KU",
        statement="Test statement",
        knowledge_level=KnowledgeLevel.OBSERVED,
    )


@pytest.fixture
def confirmed_ku():
    return KnowledgeUnit(
        domain_id=uuid4(),
        title="Test KU",
        statement="Test statement",
        knowledge_level=KnowledgeLevel.CONFIRMED,
        created_at=datetime.now(UTC) - timedelta(days=200),
    )


class TestPromotion:
    def test_experimental_to_observed_with_enough_cases(self, experimental_ku):
        result = check_promotion(
            experimental_ku,
            target=KnowledgeLevel.OBSERVED,
            confirmed_source_count=5,
            has_open_contradictions=False,
        )
        assert result.allowed
        assert result.target_level == KnowledgeLevel.OBSERVED

    def test_experimental_to_observed_insufficient_cases(self, experimental_ku):
        result = check_promotion(
            experimental_ku,
            target=KnowledgeLevel.OBSERVED,
            confirmed_source_count=2,
        )
        assert not result.allowed
        assert "≥ 3" in result.reason

    def test_experimental_to_observed_with_contradictions_blocked(self, experimental_ku):
        result = check_promotion(
            experimental_ku,
            target=KnowledgeLevel.OBSERVED,
            confirmed_source_count=5,
            has_open_contradictions=True,
        )
        assert not result.allowed
        assert "Contradição" in result.reason

    def test_observed_to_confirmed(self, observed_ku):
        result = check_promotion(
            observed_ku,
            target=KnowledgeLevel.CONFIRMED,
            confirmed_source_count=15,
            has_human_validation=True,
            has_open_contradictions=False,
        )
        assert result.allowed

    def test_observed_to_confirmed_no_human_validation(self, observed_ku):
        result = check_promotion(
            observed_ku,
            target=KnowledgeLevel.CONFIRMED,
            confirmed_source_count=15,
            has_human_validation=False,
        )
        assert not result.allowed
        assert "humana" in result.reason.lower()

    def test_confirmed_to_consolidated(self, confirmed_ku):
        result = check_promotion(
            confirmed_ku,
            target=KnowledgeLevel.CONSOLIDATED,
            has_open_contradictions=False,
            has_specialist_review=True,
        )
        assert result.allowed

    def test_confirmed_to_consolidated_too_young(self):
        young_ku = KnowledgeUnit(
            domain_id=uuid4(),
            title="Young KU",
            statement="statement",
            knowledge_level=KnowledgeLevel.CONFIRMED,
            created_at=datetime.now(UTC) - timedelta(days=30),
        )
        result = check_promotion(
            young_ku,
            target=KnowledgeLevel.CONSOLIDATED,
            has_specialist_review=True,
        )
        assert not result.allowed
        assert "meses" in result.reason.lower()

    def test_invalid_transition(self, experimental_ku):
        result = check_promotion(
            experimental_ku,
            target=KnowledgeLevel.CONSOLIDATED,
        )
        assert not result.allowed
        assert "não é permitida" in result.reason.lower()


class TestDemotion:
    def test_experimental_cannot_be_demoted(self, experimental_ku):
        result = check_demotion(experimental_ku, has_new_refutation=True)
        assert not result.allowed

    def test_observed_demoted_to_experimental(self, observed_ku):
        result = check_demotion(observed_ku, has_new_refutation=True)
        assert result.allowed
        assert result.target_level == KnowledgeLevel.EXPERIMENTAL

    def test_confirmed_demoted_to_observed(self, confirmed_ku):
        result = check_demotion(confirmed_ku, has_open_contradictions=True)
        assert result.allowed
        assert result.target_level == KnowledgeLevel.OBSERVED

    def test_no_demotion_without_condition(self, observed_ku):
        result = check_demotion(observed_ku)
        assert not result.allowed
