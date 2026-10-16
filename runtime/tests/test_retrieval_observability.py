"""Retrieval health survives execution without exposing arbitrary context state."""
from types import SimpleNamespace
import pytest
from runtime.executor.pipeline import PipelineExecutor

@pytest.mark.parametrize("retrieval", [
    {"status": "unavailable", "reason": "timeout", "documents": 0},
    {"status": "empty", "documents": 0},
    {"status": "ok", "documents": 1},
])
def test_trace_records_retrieval_health_without_private_state(retrieval):
    class Stage:
        def execute(self, ctx):
            ctx.state["retrieval"] = {**retrieval, "private": "not for trace"}
            ctx.state["secret"] = "not for trace"
            return ctx
    pipeline = SimpleNamespace(
        config=SimpleNamespace(version="test", pipeline=[
            SimpleNamespace(stage="retrieve", technique="rag", variant="dense")]),
        stages=[Stage()],
    )
    _, record = PipelineExecutor(pipeline).run("test")
    assert record.to_dict()["metadata"] == {"retrieval": retrieval}
    assert record.success


def test_pipeline_without_retrieval_preserves_empty_metadata():
    pipeline = SimpleNamespace(config=SimpleNamespace(version="test", pipeline=[]), stages=[])
    _, record = PipelineExecutor(pipeline).run("test")
    assert record.metadata == {}
