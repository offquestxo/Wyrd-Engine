"""In-process event bus feeding the SSE stream (/api/events).

Phase 2 publishes run lifecycle and log events here; Phase 1 publishes system events
(config saved, provider tested, keys reloaded).
"""

from __future__ import annotations

import asyncio
import itertools
from collections import deque
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel


class Event(BaseModel):
    id: int
    type: str  # e.g. "system", "provider.tested", "config.saved", later "run.log"
    ts: datetime
    data: dict[str, Any]


class EventBus:
    def __init__(self, history: int = 50, queue_size: int = 200) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._history: deque[Event] = deque(maxlen=history)
        self._ids = itertools.count(1)
        self._queue_size = queue_size

    def publish(self, type_: str, **data: Any) -> Event:
        event = Event(id=next(self._ids), type=type_, ts=datetime.now(UTC), data=data)
        self._history.append(event)
        for queue in list(self._subscribers):
            if queue.full():  # slow client: drop its oldest event rather than block
                queue.get_nowait()
            queue.put_nowait(event)
        return event

    def recent(self, after_id: int = 0) -> list[Event]:
        return [e for e in self._history if e.id > after_id]

    async def subscribe(self, after_id: int = 0) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        try:
            for event in self.recent(after_id):
                yield event
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


bus = EventBus()
