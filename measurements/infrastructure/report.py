"""Markdown report rendering for measurement sessions."""

from __future__ import annotations

from measurements.domain import MeasurementSession


class MarkdownMeasurementReportRenderer:
    def render(self, session: MeasurementSession, diagnostic: dict) -> str:
        header = session.header
        type_counts = diagnostic.get("type_counts") or {}
        count_lines = [
            f"- {name}: {count}"
            for name, count in sorted(type_counts.items())
        ] or ["- Nenhum snapshot registrado"]
        return "\n".join(
            [
                f"# Laudo tecnico - {header.fabricante or '-'} {header.modelo or '-'}",
                "",
                f"- Sessao: `{session.id}`",
                "",
                "## Identificacao",
                "",
                f"- Fabricante: {header.fabricante or '-'}",
                f"- Modelo: {header.modelo or '-'}",
                f"- Numero de serie: {header.numero_serie or '-'}",
                f"- Tipo de maquina: {header.tipo_maquina or '-'}",
                f"- Tipo de motor: {header.tipo_motor or '-'}",
                f"- Sistema de transmissao: {header.sistema_transmissao or '-'}",
                "",
                "## Configuracao da coleta",
                "",
                f"- Tipo de coleta: {header.tipo_coleta}",
                f"- Peca substituida: {header.peca_substituida or '-'}",
                f"- Curso nominal: {_format_mm(header.curso_nominal_mm)}",
                f"- Curso minimo: {_format_mm(header.curso_min_mm)}",
                f"- Curso maximo: {_format_mm(header.curso_max_mm)}",
                f"- Tecnico: {header.tecnico or '-'}",
                f"- Porta serial: {header.porta_serial or '-'}",
                f"- Baudrate: {header.baudrate}",
                f"- Duracao: {header.duracao_seg}s",
                f"- TMA_DATA selecionados: {_format_verticals(header.verticais)}",
                "",
                "## Amostras coletadas",
                "",
                *count_lines,
                "",
                "## Resultado",
                "",
                f"- Aprovado: {'sim' if diagnostic.get('approved') else 'nao'}",
                f"- Resumo: {diagnostic.get('summary') or '-'}",
                f"- Snapshots validos: {diagnostic.get('valid_snapshots', 0)}",
                f"- Snapshots invalidos: {diagnostic.get('invalid_snapshots', 0)}",
                "",
                "## Observacoes",
                "",
                header.observacoes or "-",
            ]
        )


def _format_mm(value: float | None) -> str:
    return "-" if value is None else f"{value} mm"


def _format_verticals(values: list[str]) -> str:
    return ", ".join(values) if values else "hall, power, course, vibration"
