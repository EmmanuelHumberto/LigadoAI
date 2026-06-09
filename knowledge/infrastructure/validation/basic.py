"""Basic content validation for early knowledge ingestion."""

from __future__ import annotations

import re
from collections import Counter

from knowledge.domain import ConvertedDocument, ValidationResult

_REPORT_MARKERS = {
    "CLIENTE:",
    "EQUIPAMENTO:",
    "MARCA:",
    "MODELO:",
    "DEFEITO",
    "DIAGNOSTICO",
    "DIAGNÓSTICO",
    "OBSERVACOES",
    "OBSERVAÇÕES",
}


class BasicContentValidator:
    def __init__(
        self,
        *,
        min_chars: int = 40,
        min_words: int = 8,
        min_unique_words: int = 6,
        min_printable_ratio: float = 0.95,
        min_alpha_ratio: float = 0.25,
        max_top_word_ratio: float = 0.35,
    ) -> None:
        self._min_chars = min_chars
        self._min_words = min_words
        self._min_unique_words = min_unique_words
        self._min_printable_ratio = min_printable_ratio
        self._min_alpha_ratio = min_alpha_ratio
        self._max_top_word_ratio = max_top_word_ratio

    async def validate(self, document: ConvertedDocument) -> ValidationResult:
        text = document.text.strip()
        errors: list[dict] = []
        if len(text) < self._min_chars:
            errors.append(
                {
                    "code": "content_too_short",
                    "message": f"content has fewer than {self._min_chars} characters",
                }
            )
        if "\ufffd" in text:
            errors.append(
                {
                    "code": "encoding_replacement_char",
                    "message": "content contains Unicode replacement characters",
                }
            )
        stats = _quality_stats(text)
        if stats["word_count"] < self._min_words:
            errors.append(
                {
                    "code": "too_few_words",
                    "message": f"content has fewer than {self._min_words} words",
                    "stats": stats,
                }
            )
        if stats["unique_word_count"] < self._min_unique_words:
            errors.append(
                {
                    "code": "too_few_unique_words",
                    "message": (
                        "content has fewer than "
                        f"{self._min_unique_words} unique words"
                    ),
                    "stats": stats,
                }
            )
        if stats["printable_ratio"] < self._min_printable_ratio:
            errors.append(
                {
                    "code": "low_printable_ratio",
                    "message": "content contains too many non-printable characters",
                    "stats": stats,
                }
            )
        if stats["alpha_ratio"] < self._min_alpha_ratio:
            errors.append(
                {
                    "code": "low_alpha_ratio",
                    "message": "content has too little natural-language text",
                    "stats": stats,
                }
            )
        if stats["top_word_ratio"] > self._max_top_word_ratio:
            errors.append(
                {
                    "code": "excessive_repetition",
                    "message": "content appears to be excessively repetitive",
                    "stats": stats,
                }
            )
        if _looks_like_report(document) and stats["report_marker_count"] < 3:
            errors.append(
                {
                    "code": "missing_report_structure",
                    "message": "report-like DOCX lacks required structured fields",
                    "stats": stats,
                }
            )
        if errors:
            return ValidationResult(approved=False, status="failed", errors=errors)
        return ValidationResult(approved=True)


def _quality_stats(text: str) -> dict:
    length = max(len(text), 1)
    printable_count = sum(1 for char in text if char.isprintable() or char in "\n\t")
    alpha_count = sum(1 for char in text if char.isalpha())
    words = [
        word.lower()
        for word in re.findall(r"[\wÀ-ÿ]{3,}", text, flags=re.UNICODE)
        if not word.isdigit()
    ]
    counts = Counter(words)
    top_count = counts.most_common(1)[0][1] if counts else 0
    upper = text.upper()
    return {
        "char_count": len(text),
        "word_count": len(words),
        "unique_word_count": len(counts),
        "printable_ratio": round(printable_count / length, 4),
        "alpha_ratio": round(alpha_count / length, 4),
        "top_word_ratio": round(top_count / max(len(words), 1), 4),
        "report_marker_count": sum(1 for marker in _REPORT_MARKERS if marker in upper),
    }


def _looks_like_report(document: ConvertedDocument) -> bool:
    if document.metadata.get("detected_type") != "docx":
        return False
    source_name = str(document.metadata.get("source_name") or "")
    if re.fullmatch(r"\d+\.md", source_name, flags=re.IGNORECASE):
        return True
    upper = document.text.upper()
    return "CLIENTE:" in upper or "DEFEITO" in upper
