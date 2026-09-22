"""Deterministic, wall-clock-bounded polling helpers for the test suite.

These live in a normal module rather than ``conftest.py`` because there are two
conftest files (``tests/conftest.py`` and ``tests/postgres/conftest.py``) and
importing ``conftest`` resolves ambiguously between them.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def poll_until[T](
    probe: Callable[[], Awaitable[T | None]],
    *,
    description: str,
    timeout_seconds: float = 30.0,
    interval_seconds: float = 0.01,
) -> T:
    """Poll ``probe`` until it returns a non-``None`` value, bounded by wall-clock time.

    Iteration-count loops express their timeout as ``count x interval``, so the real
    budget shrinks on a loaded CI runner and a correct test can fail with a timeout
    that says nothing about the behaviour under test. Bounding the wait by elapsed
    time keeps the same budget on any machine, while still returning as soon as the
    probe observes what it is waiting for.

    Raises ``TimeoutError`` when the deadline passes, so the caller decides how to
    report the failure.
    """

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    while True:
        value = await probe()
        if value is not None:
            return value
        if loop.time() >= deadline:
            raise TimeoutError(f"Timed out after {timeout_seconds:g}s waiting for {description}.")
        await asyncio.sleep(interval_seconds)
