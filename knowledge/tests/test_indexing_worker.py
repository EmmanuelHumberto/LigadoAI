import asyncio
import zipfile

from knowledge.application import CreateKnowledgeJob, CreateKnowledgeJobCommand, IndexKnowledgeJob
from knowledge.domain import JobStatus, KnowledgeMetadata
from knowledge.infrastructure.chunking import TechnicalTextChunker
from knowledge.infrastructure.conversion import LocalTextDocumentConverter
from knowledge.infrastructure.embeddings import DeterministicFakeEmbeddingProvider
from knowledge.infrastructure.memory import (
    InMemoryKnowledgeJobRepository,
    InMemoryKnowledgeQueue,
    InMemoryKnowledgeRepository,
)
from knowledge.infrastructure.validation import BasicContentValidator


def test_index_worker_indexes_markdown_document(tmp_path):
    asyncio.run(_test_index_worker_indexes_markdown_document(tmp_path))


async def _test_index_worker_indexes_markdown_document(tmp_path):
    source = tmp_path / "faulhaber-2616.md"
    source.write_text(
        "# Faulhaber 2616\n\n"
        "Brushless technical datasheet for motor 2616. "
        "Nominal voltage, torque, current and speed values are documented. "
        "This content is long enough to pass validation and create chunks.",
        encoding="utf-8",
    )
    jobs = InMemoryKnowledgeJobRepository()
    queue = InMemoryKnowledgeQueue()
    repository = InMemoryKnowledgeRepository()
    create_job = CreateKnowledgeJob(jobs, queue)
    job = await create_job.execute(
        CreateKnowledgeJobCommand(
            source_uri=str(source),
            content_hash="seed",
            metadata=KnowledgeMetadata(
                manufacturer="Faulhaber",
                model="2616",
                category="brushless",
                document_type="datasheet",
            ),
        )
    )
    worker = IndexKnowledgeJob(
        jobs=jobs,
        repository=repository,
        converter=LocalTextDocumentConverter(),
        validator=BasicContentValidator(min_chars=40),
        chunker=TechnicalTextChunker(chunk_size_tokens=40, overlap_tokens=5, min_chunk_chars=20),
        embedder=DeterministicFakeEmbeddingProvider(),
    )

    completed = await worker.process(job.id)
    status = await repository.get_status()
    document = await repository.get_document(completed.document_id)

    assert completed.status == JobStatus.INDEXED
    assert completed.progress_total >= 1
    assert document is not None
    assert document.manufacturer == "Faulhaber"
    assert document.model == "2616"
    assert status.index_status == "ready"
    assert status.document_count == 1
    assert status.chunk_count >= 1
    assert status.corpus_version == 1


def test_index_worker_marks_validation_failure(tmp_path):
    asyncio.run(_test_index_worker_marks_validation_failure(tmp_path))


async def _test_index_worker_marks_validation_failure(tmp_path):
    source = tmp_path / "empty.md"
    source.write_text("# Bad\n\nshort", encoding="utf-8")
    jobs = InMemoryKnowledgeJobRepository()
    queue = InMemoryKnowledgeQueue()
    repository = InMemoryKnowledgeRepository()
    create_job = CreateKnowledgeJob(jobs, queue)
    job = await create_job.execute(
        CreateKnowledgeJobCommand(
            source_uri=str(source),
            content_hash="seed",
        )
    )
    worker = IndexKnowledgeJob(
        jobs=jobs,
        repository=repository,
        converter=LocalTextDocumentConverter(),
        validator=BasicContentValidator(min_chars=40),
        chunker=TechnicalTextChunker(min_chunk_chars=20),
        embedder=DeterministicFakeEmbeddingProvider(),
    )

    completed = await worker.process(job.id)
    status = await repository.get_status()

    assert completed.status == JobStatus.FAILED
    assert completed.error_details["code"] == "validation_failed"
    assert status.document_count == 0


def test_index_worker_indexes_docx_renamed_as_markdown(tmp_path):
    asyncio.run(_test_index_worker_indexes_docx_renamed_as_markdown(tmp_path))


async def _test_index_worker_indexes_docx_renamed_as_markdown(tmp_path):
    source = tmp_path / "6.md"
    _write_docx(
        source,
        [
            "Cliente: Exemplo Tattoo",
            "Fabricante: Faulhaber",
            "Modelo: 2224 SR",
            "Defeito: motor sem torque e aquecimento.",
            "Analise: desgaste de escovas e contaminacao interna.",
            "Servico proposto: limpeza, revisao mecanica e teste em bancada.",
        ],
    )
    jobs = InMemoryKnowledgeJobRepository()
    queue = InMemoryKnowledgeQueue()
    repository = InMemoryKnowledgeRepository()
    create_job = CreateKnowledgeJob(jobs, queue)
    job = await create_job.execute(
        CreateKnowledgeJobCommand(
            source_uri=str(source),
            content_hash="seed",
            metadata=KnowledgeMetadata(document_type="laudo"),
        )
    )
    worker = IndexKnowledgeJob(
        jobs=jobs,
        repository=repository,
        converter=LocalTextDocumentConverter(),
        validator=BasicContentValidator(min_chars=40),
        chunker=TechnicalTextChunker(chunk_size_tokens=80, overlap_tokens=5, min_chunk_chars=20),
        embedder=DeterministicFakeEmbeddingProvider(),
    )

    completed = await worker.process(job.id)
    document = await repository.get_document(completed.document_id)

    assert completed.status == JobStatus.INDEXED
    assert document is not None
    assert document.metadata["detected_type"] == "docx"
    assert document.title == "Cliente: Exemplo Tattoo"


def _write_docx(path, paragraphs: list[str]) -> None:
    body = "".join(
        f"<w:p><w:r><w:t>{paragraph}</w:t></w:r></w:p>"
        for paragraph in paragraphs
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
