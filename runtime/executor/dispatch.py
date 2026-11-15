"""Bounded synchronous pipeline execution outside the ASGI event loop."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore
from typing import Callable, TypeVar

T = TypeVar('T')


class PipelineBusyError(RuntimeError):
    pass


class PipelineDispatcher:
    """One executing job plus one waiting job; cancelled work retains its slot.

    copy_context preserves tenant/agent identity for quotas, secrets and traces.
    Capacity is released by the actual concurrent future, never by the HTTP task.
    """
    def __init__(self):
        self._capacity = BoundedSemaphore(2)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='opentracy-pipeline')

    async def execute(self, function: Callable[..., T], *args) -> T:
        if not self._capacity.acquire(blocking=False):
            raise PipelineBusyError('analysis_busy')
        try:
            future = self._executor.submit(copy_context().run, function, *args)
        except BaseException:
            self._capacity.release()
            raise
        future.add_done_callback(lambda completed: self._capacity.release())
        wrapped = asyncio.wrap_future(future)
        # Retrieve exceptions even if the caller disconnects while the worker runs.
        wrapped.add_done_callback(lambda completed: None if completed.cancelled() else completed.exception())
        try:
            return await asyncio.shield(wrapped)
        except asyncio.CancelledError:
            # Queued work can be cancelled. A running sync call cannot; it keeps
            # capacity until it really finishes (including its existing timeout).
            future.cancel()
            raise

    def close(self):
        self._executor.shutdown(wait=True, cancel_futures=True)


pipeline_dispatcher = PipelineDispatcher()
