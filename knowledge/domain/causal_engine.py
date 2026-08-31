"""Motor de avaliação de Cadeias Causais — COUS v3.1.

Avalia condition_expression contra desvios eletromecânicos recebidos do Firmware.
Suporta operadores: <, >, <=, >=, ==, !=, AND, OR, BETWEEN.
Referencia campos pelos nomes do payload electromechanical_signature.
"""

from __future__ import annotations

import operator
import re
from typing import Any


# Campos disponíveis para avaliação (nome → valor numérico)
def _extract_fields(deviations: dict[str, Any]) -> dict[str, float]:
    """Extrai campos numéricos relevantes do payload de assinatura + desvios."""
    fields: dict[str, float] = {}

    # Campos da assinatura
    for key in (
        "rpm_hall", "rpm_mpu", "bus_voltage_mv", "motor_current_ma",
        "electrical_power_mw", "omega_mrad_s", "armature_resistance_mohm",
        "bemf_electrical_mv", "bemf_model_mv", "bemf_residual_mv",
        "equivalent_resistance_mohm", "torque_uNm", "course_mm",
        "magnetic_field_uT", "corrected_magnetic_field_uT",
        "mechanical_power_mw", "mechanical_equivalent_load_permille",
        "locked_rotor_hypothesis", "mechanical_decoupling_hypothesis",
        "motor_nominal_overload_hypothesis", "source_overvoltage_hypothesis",
        "source_interruption_hypothesis", "source_sag_under_load_hypothesis",
    ):
        if key in deviations:
            try:
                fields[key] = float(deviations[key])
            except (TypeError, ValueError):
                pass

    # Campos de erro/desvio (sufixo _error_permille ou campos diretos)
    for key in (
        "bemf_error_permille", "equivalent_resistance_error_permille",
        "torque_error_permille", "current_error_permille",
        "rpm_cross_error_permille", "torque_load_permille",
        "efficiency_permille", "quality_permille",
        "duty_permille", "duty_high_permille", "duty_low_permille",
    ):
        if key in deviations:
            try:
                fields[key] = float(deviations[key])
            except (TypeError, ValueError):
                pass

    return fields


# ── Parser e avaliador de expressões ────────────────────────────────────

_TOKEN_RE = re.compile(
    r"""(-?\d+\.?\d*)|(>=|<=|!=|==|>|<)|(AND|OR)|([a-z_][a-z0-9_]*)""",
    re.IGNORECASE,
)

OP_MAP = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


def _is_isolated_keyword(expr: str, pos: int, keyword: str) -> bool:
    """Verifica se keyword na posição 'pos' é uma palavra isolada (não parte de um campo).

    Ex: 'error_permille' contém 'or' mas não é o operador OR.
    A keyword deve ser precedida e seguida por espaço ou borda.
    """
    if not expr[pos:].upper().startswith(keyword.upper()):
        return False
    before_ok = pos == 0 or expr[pos - 1] in (" ", "\t", "(")
    after_pos = pos + len(keyword)
    after_ok = after_pos >= len(expr) or expr[after_pos] in (" ", "\t", ")")
    return before_ok and after_ok


def evaluate_condition(expression: str, deviations: dict[str, Any]) -> bool:
    """Avalia uma condition_expression contra desvios recebidos.

    Exemplos:
        "bemf_error_permille < -150 AND equivalent_resistance_error_permille > 20"
        "torque_error_permille < -100 OR current_error_permille > 50"
        "rpm_hall > 6000 AND rpm_hall < 8000"
        "efficiency_permille < 700"

    Retorna True se a condição for satisfeita, False caso contrário.
    """
    if not expression or not expression.strip():
        return False

    fields = _extract_fields(deviations)
    if not fields:
        return False

    try:
        return _eval_expr(expression, fields)
    except Exception:
        return False


def _eval_expr(expr_str: str, fields: dict[str, float]) -> bool:
    """Avaliador recursivo simples: suporta AND, OR, comparações."""
    expr_str = expr_str.strip()

    # Remover parênteses externos
    while expr_str.startswith("(") and expr_str.endswith(")"):
        depth = 0
        balanced = True
        for i, ch in enumerate(expr_str):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if depth == 0 and i < len(expr_str) - 1:
                balanced = False
                break
        if balanced:
            expr_str = expr_str[1:-1].strip()
        else:
            break

    # Procurar OR no nível mais externo (apenas palavra isolada, não parte de campo)
    depth = 0
    for i, ch in enumerate(expr_str):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and _is_isolated_keyword(expr_str, i, "OR"):
            left = expr_str[:i].strip()
            right = expr_str[i + 2:].strip()
            return _eval_expr(left, fields) or _eval_expr(right, fields)

    # Procurar AND no nível mais externo (apenas palavra isolada, não parte de campo)
    depth = 0
    for i, ch in enumerate(expr_str):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and _is_isolated_keyword(expr_str, i, "AND"):
            left = expr_str[:i].strip()
            right = expr_str[i + 3:].strip()
            return _eval_expr(left, fields) and _eval_expr(right, fields)

    # Deve ser uma comparação simples: campo OP valor
    return _eval_comparison(expr_str, fields)


def _eval_comparison(comparison: str, fields: dict[str, float]) -> bool:
    """Avalia uma comparação simples: 'bemf_error_permille < -150'."""
    tokens = _TOKEN_RE.findall(comparison)
    # tokens são tuplas: (numero, operador, AND/OR, identificador)
    parts: list[str] = []
    for t in tokens:
        for p in t:
            if p:
                parts.append(p)
                break

    if len(parts) < 3:
        return False

    field_name = parts[0].lower()
    op_str = parts[1]
    try:
        value = float(parts[2])
    except ValueError:
        return False

    if field_name not in fields:
        return False

    op_func = OP_MAP.get(op_str)
    if op_func is None:
        return False

    return op_func(fields[field_name], value)


def find_matching_chains(
    deviations: dict[str, Any],
    chains: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Encontra todas as cadeias causais cujas condições são satisfeitas.

    Args:
        deviations: dicionário com os campos do payload (bemf_error_permille, etc.)
        chains: lista de dicionários com 'condition_expression', 'probable_cause', etc.

    Returns:
        Lista de cadeias que deram match, ordenadas por confidence descendente.
    """
    matches = []
    for chain in chains:
        condition = chain.get("condition_expression", "")
        if evaluate_condition(condition, deviations):
            matches.append(chain)
    matches.sort(key=lambda c: float(c.get("confidence", 0)), reverse=True)
    return matches
