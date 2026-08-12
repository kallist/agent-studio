from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from app.knowledge.service import KnowledgeService

logger = logging.getLogger(__name__)


class LocalIngestionWorker:
    """Bounded in-process queue adapter; replaceable by a durable broker later."""

    def __init__(self, service: KnowledgeService, worker_count: int = 1) -> None:
        self._service = service
        self._worker_count = max(1, worker_count)
        self._queue: asyncio.Queue[UUID | None] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._run(), name=f"knowledge-ingestion-{index}")
            for index in range(self._worker_count)
        ]
        for job_id in await self._service.recover_jobs():
            self.enqueue(job_id)

    def enqueue(self, job_id: UUID) -> None:
        self._queue.put_nowait(job_id)

    async def stop(self) -> None:
        for _ in self._tasks:
            self._queue.put_nowait(None)
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                if job_id is None:
                    return
                try:
                    await self._service.process_job(job_id)
                except Exception:
                    logger.exception("Knowledge ingestion job %s failed", job_id)
            finally:
                self._queue.task_done()
