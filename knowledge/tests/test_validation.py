import asyncio

from knowledge.domain import ConvertedDocument
from knowledge.infrastructure.validation import BasicContentValidator


def test_validator_accepts_structured_docx_report():
    asyncio.run(_test_validator_accepts_structured_docx_report())


async def _test_validator_accepts_structured_docx_report():
    document = ConvertedDocument(
        source_uri="/tmp/2.md",
        text=(
            "CLIENTE: Wesley de Oliveira de Jesus\n"
            "EQUIPAMENTO: Dermografo\n"
            "MARCA: Dermocamp\n"
            "MODELO: Sharp 300 Pro\n"
            "DEFEITO RELATADO: Maquina nao liga\n"
            "DIAGNOSTICO TECNICO: conector danificado e consumo elevado.\n"
            "SERVICO PROPOSTO: limpeza, regulagem, lubrificacao e teste em bancada."
        ),
        metadata={"detected_type": "docx", "source_name": "2.md"},
    )

    result = await BasicContentValidator().validate(document)

    assert result.approved is True


def test_validator_rejects_repetitive_garbage():
    asyncio.run(_test_validator_rejects_repetitive_garbage())


async def _test_validator_rejects_repetitive_garbage():
    document = ConvertedDocument(
        source_uri="/tmp/bad.md",
        text="erro " * 200,
        metadata={"detected_type": "docx", "source_name": "2.md"},
    )

    result = await BasicContentValidator().validate(document)

    assert result.approved is False
    codes = {error["code"] for error in result.errors}
    assert "excessive_repetition" in codes
    assert "missing_report_structure" in codes


def test_validator_rejects_symbol_noise():
    asyncio.run(_test_validator_rejects_symbol_noise())


async def _test_validator_rejects_symbol_noise():
    document = ConvertedDocument(
        source_uri="/tmp/noise.md",
        text=("### !!! ??? 12345 \x00\x01 " * 80),
        metadata={"detected_type": "text", "source_name": "noise.md"},
    )

    result = await BasicContentValidator().validate(document)

    assert result.approved is False
    codes = {error["code"] for error in result.errors}
    assert "low_printable_ratio" in codes
    assert "low_alpha_ratio" in codes
