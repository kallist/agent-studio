from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.evaluation.service import EvaluationService

logger = logging.getLogger(__name__)


class LocalEvaluationWorker:
    """Single-process bounded worker for deterministic offline evaluation."""

    def __init__(self, service: EvaluationService, worker_count: int = 1) -> None:
        self._service = service
        self._worker_count = max(1, worker_count)
        self._queue: asyncio.Queue[UUID | None] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._run(), name=f"evaluation-{index}")
            for index in range(self._worker_count)
        ]
        for run_id in await self._service.recover_runs():
            self.enqueue(run_id)

    def enqueue(self, run_id: UUID) -> None:
        self._queue.put_nowait(run_id)

    async def stop(self) -> None:
        for _ in self._tasks:
            self._queue.put_nowait(None)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run(self) -> None:
        while True:
            run_id = await self._queue.get()
            try:
                if run_id is None:
                    return
                try:
                    await self._service.process_run(run_id)
                except Exception:
                    logger.exception("Evaluation run %s failed", run_id)
            finally:
                self._queue.task_done()
