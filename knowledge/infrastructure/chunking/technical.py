"""Initial technical-document chunking strategy."""

from __future__ import annotations


class TechnicalTextChunker:
    """Word-window chunker with overlap.

    This is intentionally conservative for phase 3. It is deterministic,
    handles long datasheets, and can later be replaced by a structure-aware
    Markdown/table chunker behind the same TextChunker port.
    """

    def __init__(
        self,
        *,
        chunk_size_tokens: int = 450,
        overlap_tokens: int = 80,
        min_chunk_chars: int = 120,
    ) -> None:
        self._chunk_size = max(1, chunk_size_tokens)
        self._overlap = max(0, min(overlap_tokens, self._chunk_size // 2))
        self._min_chunk_chars = min_chunk_chars

    def chunk(self, text: str) -> list[str]:
        words = text.split()
        if not words:
            return []

        if len(words) <= self._chunk_size:
            chunk = " ".join(words).strip()
            return [chunk] if len(chunk) >= self._min_chunk_chars else []

        step = max(1, self._chunk_size - self._overlap)
        chunks: list[str] = []
        for start in range(0, len(words), step):
            window = words[start : start + self._chunk_size]
            if not window:
                break
            chunk = " ".join(window).strip()
            if len(chunk) >= self._min_chunk_chars:
                chunks.append(chunk)
            if start + self._chunk_size >= len(words):
                break
        return chunks
