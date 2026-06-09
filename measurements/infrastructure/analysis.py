"""Simple measurement diagnostics."""

from __future__ import annotations

from collections import Counter

from measurements.domain import MeasurementSession, MeasurementSnapshot, SnapshotValidationStatus


class BasicMeasurementAnalyzer:
    def diagnose(
        self,
        session: MeasurementSession,
        snapshots: list[MeasurementSnapshot],
    ) -> dict:
        type_counts = Counter(snapshot.type for snapshot in snapshots)
        valid = [
            snapshot for snapshot in snapshots if snapshot.status == SnapshotValidationStatus.VALID
        ]
        invalid = [
            snapshot
            for snapshot in snapshots
            if snapshot.status == SnapshotValidationStatus.INVALID
        ]
        approved = bool(valid) and not invalid
        if not valid:
            summary = "Nenhum snapshot valido foi coletado."
        elif invalid:
            summary = "Coleta possui snapshots invalidos; revisar captura antes do laudo final."
        else:
            summary = "Coleta valida para analise tecnica inicial."
        return {
            "approved": approved,
            "summary": summary,
            "total_snapshots": len(snapshots),
            "valid_snapshots": len(valid),
            "invalid_snapshots": len(invalid),
            "type_counts": dict(type_counts),
            "header": {
                "fabricante": session.header.fabricante,
                "modelo": session.header.modelo,
                "numero_serie": session.header.numero_serie,
                "tipo_maquina": session.header.tipo_maquina,
                "tipo_motor": session.header.tipo_motor,
                "sistema_transmissao": session.header.sistema_transmissao,
                "curso_nominal_mm": session.header.curso_nominal_mm,
                "curso_min_mm": session.header.curso_min_mm,
                "curso_max_mm": session.header.curso_max_mm,
                "tipo_coleta": session.header.tipo_coleta,
                "peca_substituida": session.header.peca_substituida,
                "tecnico": session.header.tecnico,
                "porta_serial": session.header.porta_serial,
                "baudrate": session.header.baudrate,
                "duracao_seg": session.header.duracao_seg,
                "verticais": list(session.header.verticais),
            },
        }
