"""Validador de integridade do Knowledge Graph — COUS v3.0.

Detecta:
- Ciclos (detecção de grafo direcionado)
- Auto-relações (source == target)
- Inconsistências de domínio (aresta entre KUs de domínios diferentes)
- Relações conflitantes (refuta + corrobora simultâneas)
- KUs órfãs (sem arestas de entrada ou saída)
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class GraphValidationResult:
    valid: bool
    cycles_detected: int = 0
    self_relations_detected: int = 0
    domain_mismatches: int = 0
    conflicting_relations: int = 0
    orphan_nodes: int = 0
    details: list[str] = field(default_factory=list)


def validate_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> GraphValidationResult:
    """Valida integridade estrutural do Knowledge Graph.

    Args:
        nodes: lista de dicionários com 'id', 'title', 'knowledge_level'
        edges: lista de dicionários com 'source_ku_id', 'target_ku_id',
               'relation_type', 'confidence'

    Returns:
        GraphValidationResult com todas as violações detectadas.
    """
    details: list[str] = []
    node_ids = {n["id"] for n in nodes}

    # 1. Auto-relações
    self_rels = 0
    for e in edges:
        if e["source_ku_id"] == e["target_ku_id"]:
            self_rels += 1
            details.append(f"Self-relation: {e['source_ku_id']} -> {e['target_ku_id']} ({e.get('relation_type', '?')})")

    # 2. Inconsistências de domínio
    # (já filtrado por domain_id na consulta — mas verificamos nós fonte)
    domain_mismatches = 0
    for e in edges:
        if e["source_ku_id"] not in node_ids:
            domain_mismatches += 1
            details.append(f"Source node not in domain: {e['source_ku_id']}")
        if e["target_ku_id"] not in node_ids:
            domain_mismatches += 1
            details.append(f"Target node not in domain: {e['target_ku_id']}")

    # 3. Detecção de ciclos (DFS com coloração)
    cycles = _detect_cycles(nodes, edges)
    if cycles:
        for cycle in cycles[:5]:  # Reportar até 5 ciclos
            cycle_str = " → ".join(str(n) for n in cycle)
            details.append(f"Cycle detected: {cycle_str}")

    # 4. Relações conflitantes (refuta + corrobora entre mesmos nós)
    conflicting = _detect_conflicting_relations(edges)
    for conflict in conflicting[:5]:
        details.append(
            f"Conflicting relations: {conflict[0]} -> {conflict[1]}: "
            f"{conflict[2]} e {conflict[3]}"
        )

    # 5. Nós órfãos (sem arestas)
    nodes_with_edges: set[UUID] = set()
    for e in edges:
        nodes_with_edges.add(e["source_ku_id"])
        nodes_with_edges.add(e["target_ku_id"])
    orphans = node_ids - nodes_with_edges
    for orphan_id in list(orphans)[:10]:
        orphan_node = next((n for n in nodes if n["id"] == orphan_id), None)
        title = orphan_node["title"] if orphan_node else "?"
        details.append(f"Orphan node (no relations): {title} ({orphan_id})")

    valid = (
        self_rels == 0
        and len(cycles) == 0
        and len(conflicting) == 0
        and domain_mismatches == 0
    )

    return GraphValidationResult(
        valid=valid,
        cycles_detected=len(cycles),
        self_relations_detected=self_rels,
        domain_mismatches=domain_mismatches,
        conflicting_relations=len(conflicting),
        orphan_nodes=len(orphans),
        details=details,
    )


def _detect_cycles(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> list[list[UUID]]:
    """Detecta ciclos no grafo direcionado usando DFS com coloração.

    WHITE (0): não visitado
    GRAY (1): em processamento (no stack atual)
    BLACK (2): completamente processado
    """
    # Construir lista de adjacência (ignorar self-relations)
    adj: dict[UUID, list[UUID]] = defaultdict(list)
    node_ids = {n["id"] for n in nodes}
    for e in edges:
        src = e["source_ku_id"]
        tgt = e["target_ku_id"]
        if src == tgt:
            continue  # Self-relations não formam ciclos significativos
        if src in node_ids and tgt in node_ids:
            adj[src].append(tgt)

    color: dict[UUID, int] = {nid: 0 for nid in node_ids}
    parent: dict[UUID, UUID | None] = {nid: None for nid in node_ids}
    cycles: list[list[UUID]] = []

    def dfs(u: UUID) -> None:
        color[u] = 1  # GRAY
        for v in adj.get(u, []):
            if color.get(v) == 1:  # Back edge → ciclo
                cycle: list[UUID] = [v, u]
                curr = parent.get(u)
                while curr is not None and curr != v:
                    cycle.append(curr)
                    curr = parent.get(curr)
                cycle.append(v)
                cycle.reverse()
                cycles.append(cycle)
            elif color.get(v) == 0:  # WHITE
                parent[v] = u
                dfs(v)
        color[u] = 2  # BLACK

    for nid in node_ids:
        if color[nid] == 0:
            dfs(nid)

    return cycles


def _detect_conflicting_relations(
    edges: list[dict[str, Any]],
) -> list[tuple[UUID, UUID, str, str]]:
    """Detecta pares de relações conflitantes entre os mesmos nós.

    Ex: (A refuta B) e (A corrobora B) são conflitantes.
    """
    # Agrupar relações por par (source, target)
    pairs: dict[tuple[UUID, UUID], set[str]] = defaultdict(set)
    for e in edges:
        key = (e["source_ku_id"], e["target_ku_id"])
        pairs[key].add(e.get("relation_type", "?"))

    conflicts: list[tuple[UUID, UUID, str, str]] = []
    conflicting_pairs = {
        frozenset({"refuta", "corrobora"}),
        frozenset({"refuta", "complementa"}),
        frozenset({"refuta", "especializa"}),
        frozenset({"refuta", "generaliza"}),
        frozenset({"substitui", "corrobora"}),
    }

    for (src, tgt), rels in pairs.items():
        for pair in conflicting_pairs:
            if pair.issubset(rels):
                rel_list = list(rels)
                conflicts.append((src, tgt, rel_list[0], rel_list[1]))

    return conflicts


def compute_graph_metrics(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calcula métricas estruturais do grafo.

    Returns:
        Dict com: node_count, edge_count, density, avg_degree,
        components, max_depth, level_distribution
    """
    node_count = len(nodes)
    edge_count = len(edges)

    # Densidade: |E| / (|V| * (|V|-1)) para grafo direcionado
    max_edges = node_count * (node_count - 1) if node_count > 1 else 1
    density = edge_count / max_edges

    # Grau médio
    degrees: dict[UUID, int] = defaultdict(int)
    for e in edges:
        degrees[e["source_ku_id"]] += 1
        degrees[e["target_ku_id"]] += 1
    avg_degree = sum(degrees.values()) / max(node_count, 1)

    # Distribuição por nível
    level_dist: dict[str, int] = defaultdict(int)
    for n in nodes:
        level_dist[str(n.get("knowledge_level", "?"))] += 1

    return {
        "node_count": node_count,
        "edge_count": edge_count,
        "density": round(density, 4),
        "avg_degree": round(avg_degree, 2),
        "level_distribution": dict(level_dist),
    }
