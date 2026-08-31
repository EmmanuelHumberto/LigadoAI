"""Testes para o Validador de Knowledge Graph — COUS v3.0."""

import pytest
from uuid import uuid4
from knowledge.domain.graph_validator import validate_graph, compute_graph_metrics


@pytest.fixture
def empty_graph():
    return [], []


@pytest.fixture
def simple_graph():
    n1, n2, n3 = uuid4(), uuid4(), uuid4()
    nodes = [
        {"id": n1, "title": "KU A", "knowledge_level": "confirmed"},
        {"id": n2, "title": "KU B", "knowledge_level": "observed"},
        {"id": n3, "title": "KU C", "knowledge_level": "experimental"},
    ]
    edges = [
        {"source_ku_id": n1, "target_ku_id": n2, "relation_type": "especializa", "confidence": 0.9},
        {"source_ku_id": n2, "target_ku_id": n3, "relation_type": "corrobora", "confidence": 0.7},
    ]
    return nodes, edges


@pytest.fixture
def graph_with_cycle():
    n1, n2, n3 = uuid4(), uuid4(), uuid4()
    nodes = [
        {"id": n1, "title": "A", "knowledge_level": "confirmed"},
        {"id": n2, "title": "B", "knowledge_level": "observed"},
        {"id": n3, "title": "C", "knowledge_level": "experimental"},
    ]
    edges = [
        {"source_ku_id": n1, "target_ku_id": n2, "relation_type": "especializa"},
        {"source_ku_id": n2, "target_ku_id": n3, "relation_type": "corrobora"},
        {"source_ku_id": n3, "target_ku_id": n1, "relation_type": "generaliza"},  # ciclo
    ]
    return nodes, edges


@pytest.fixture
def graph_with_conflict():
    n1, n2 = uuid4(), uuid4()
    nodes = [
        {"id": n1, "title": "A", "knowledge_level": "confirmed"},
        {"id": n2, "title": "B", "knowledge_level": "observed"},
    ]
    edges = [
        {"source_ku_id": n1, "target_ku_id": n2, "relation_type": "refuta"},
        {"source_ku_id": n1, "target_ku_id": n2, "relation_type": "corrobora"},
    ]
    return nodes, edges


class TestValidateGraph:
    def test_empty_graph_is_valid(self, empty_graph):
        nodes, edges = empty_graph
        result = validate_graph(nodes, edges)
        assert result.valid
        assert result.cycles_detected == 0

    def test_simple_graph_is_valid(self, simple_graph):
        nodes, edges = simple_graph
        result = validate_graph(nodes, edges)
        assert result.valid
        assert result.cycles_detected == 0
        assert result.self_relations_detected == 0
        assert result.orphan_nodes == 0

    def test_detects_cycle(self, graph_with_cycle):
        nodes, edges = graph_with_cycle
        result = validate_graph(nodes, edges)
        assert not result.valid
        assert result.cycles_detected == 1

    def test_detects_self_relation(self):
        n1 = uuid4()
        nodes = [{"id": n1, "title": "A", "knowledge_level": "experimental"}]
        edges = [{"source_ku_id": n1, "target_ku_id": n1, "relation_type": "corrobora"}]
        result = validate_graph(nodes, edges)
        assert result.self_relations_detected == 1

    def test_detects_conflicting_relations(self, graph_with_conflict):
        nodes, edges = graph_with_conflict
        result = validate_graph(nodes, edges)
        assert result.conflicting_relations == 1

    def test_detects_orphan(self):
        n1, n2 = uuid4(), uuid4()
        nodes = [
            {"id": n1, "title": "A", "knowledge_level": "confirmed"},
            {"id": n2, "title": "B - orphan", "knowledge_level": "experimental"},
        ]
        edges = [
            {"source_ku_id": n1, "target_ku_id": n1, "relation_type": "especializa"},
        ]
        result = validate_graph(nodes, edges)
        assert result.orphan_nodes == 1
        assert not result.valid  # self-relation + orphan


class TestGraphMetrics:
    def test_empty_metrics(self):
        nodes, edges = [], []
        m = compute_graph_metrics(nodes, edges)
        assert m["node_count"] == 0
        assert m["edge_count"] == 0

    def test_simple_metrics(self, simple_graph):
        nodes, edges = simple_graph
        m = compute_graph_metrics(nodes, edges)
        assert m["node_count"] == 3
        assert m["edge_count"] == 2
        assert 0 < m["density"] < 1
        assert "confirmed" in m["level_distribution"]
