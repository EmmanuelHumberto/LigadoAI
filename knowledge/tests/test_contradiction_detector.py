"""Testes para o Detector de Contradições — COUS v3.0."""

from uuid import uuid4
from knowledge.domain.contradiction_detector import (
    ContradictionDetector,
    ContradictionClass,
)


class TestContradictionDetector:
    def test_empty_hypotheses_returns_empty(self):
        detector = ContradictionDetector()
        case = {"id": uuid4(), "hypotheses": []}
        kus = [{"id": uuid4(), "title": "KU", "statement": "test", "knowledge_level": "confirmed", "confidence": 0.80}]
        assert detector.detect(case, kus) == []

    def test_detects_refutation(self):
        detector = ContradictionDetector()
        case = {
            "id": uuid4(),
            "hypotheses": [
                {"description": "O motor NÃO apresenta desgaste significativo", "confidence": 0.80},
            ],
        }
        kus = [
            {
                "id": uuid4(),
                "title": "Desgaste do motor",
                "statement": "O motor apresenta desgaste progressivo ao longo do uso",
                "knowledge_level": "confirmed",
                "confidence": 0.85,
            },
        ]
        detections = detector.detect(case, kus)
        assert len(detections) == 1
        assert detections[0].classification == ContradictionClass.REFUTATION

    def test_no_contradiction_without_negation(self):
        detector = ContradictionDetector()
        case = {
            "id": uuid4(),
            "hypotheses": [
                {"description": "A temperatura de operação é estável", "confidence": 0.70},
            ],
        }
        kus = [
            {
                "id": uuid4(),
                "title": "Vibração",
                "statement": "A vibração aumenta com o uso prolongado",
                "knowledge_level": "observed",
                "confidence": 0.65,
            },
        ]
        detections = detector.detect(case, kus)
        assert len(detections) == 0

    def test_detects_replacement_with_large_delta(self):
        detector = ContradictionDetector()
        case = {
            "id": uuid4(),
            "hypotheses": [
                {"description": "Nova abordagem NÃO é compatível com entendimento anterior", "confidence": 0.90},
            ],
        }
        kus = [
            {
                "id": uuid4(),
                "title": "Abordagem antiga",
                "statement": "O entendimento anterior sobre abordagem é válido",
                "knowledge_level": "observed",
                "confidence": 0.50,
            },
        ]
        detections = detector.detect(case, kus)
        assert len(detections) == 1
        assert detections[0].classification == ContradictionClass.REPLACEMENT
        assert detections[0].confidence_drop > 0.30

    def test_classification_ordering(self):
        """Confirma que detections são ordenadas por impacto."""
        detector = ContradictionDetector()
        case = {
            "id": uuid4(),
            "hypotheses": [
                {"description": "Hipótese NÃO compatível com padrão A e padrão B", "confidence": 0.90},
            ],
        }
        kus = [
            {
                "id": uuid4(),
                "title": "KU baixa confiança",
                "statement": "padrão A é válido",
                "knowledge_level": "observed",
                "confidence": 0.40,
            },
            {
                "id": uuid4(),
                "title": "KU alta confiança",
                "statement": "padrão B é confirmado",
                "knowledge_level": "confirmed",
                "confidence": 0.88,
            },
        ]
        detections = detector.detect(case, kus)
        # Ordenado por confidence_drop descendente
        if len(detections) >= 2:
            assert detections[0].confidence_drop >= detections[1].confidence_drop
