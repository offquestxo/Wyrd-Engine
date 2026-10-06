"""Parallel batch scoring across every usable provider (owner request, Phase 3 follow-up).

Instead of trying providers one after another, each usable provider in the `score_items`
route becomes a *lane* with its own worker(s), batch size, and rate limiter (rpm/tpm from
providers.yaml, seeded with the last minute of real usage). Lanes pull batches from a shared
queue; a failed batch goes back on the queue for any lane to retry. A lane drops out when its
credentials are blocked, it keeps failing, or its daily quota is nearly used. `last_resort`
lanes (OpenRouter: 50 free requests/day) only take work once every other lane has dropped out.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from apps.api import prompts
from apps.api.config import ModelConfig, ParallelConfig, RouteStep
from apps.api.providers.base import ProviderError
from apps.api.providers.router import estimate_tokens
from apps.api.providers.schemas import ItemScore, ItemToScore, ScoreBatch

if TYPE_CHECKING:
    from apps.api.providers.router import Router

SCORE_OUTPUT_TOKENS_PER_ITEM = 120


@dataclass
class BatchResult:
    provider: str
    model: str
    items: list[ItemToScore]
    scores: list[ItemScore]
    seconds: float
    hedge: bool = False  # a duplicate of a slow batch that finished first


class RateWindow:
    """Sliding 60-second window of (time, tokens) for one provider/model."""

    def __init__(
        self,
        rpm: int | None,
        tpm: int | None,
        safety: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rpm = int(rpm * safety) if rpm else None
        self.tpm = int(tpm * safety) if tpm else None
        self._events: deque[tuple[float, int]] = deque()
        self._clock = clock

    def seed(self, ages_and_tokens: Sequence[tuple[float, int]]) -> None:
        now = self._clock()
        for age, tokens in sorted(ages_and_tokens, reverse=True):
            self._events.append((now - age, tokens))

    def _trim(self) -> None:
        cutoff = self._clock() - 60
        while self._events and self._events[0][0] <= cutoff:
            self._events.popleft()

    def wait_for(self, tokens: int) -> float:
        """Seconds until a request of `tokens` fits in both limits (0 = send now)."""
        self._trim()
        now = self._clock()
        waits = [0.0]
        if self.rpm is not None and len(self._events) + 1 > self.rpm:
            waits.append(self._events[len(self._events) - self.rpm][0] + 60 - now)
        if self.tpm is not None:
            total = sum(t for _, t in self._events) + tokens
            for ts, t in self._events:  # oldest first: wait until enough tokens age out
                if total <= self.tpm:
                    break
                total -= t
                waits.append(ts + 60 - now)
        return max(waits)

    def add(self, tokens: int) -> None:
        self._events.append((self._clock(), tokens))


@dataclass
class Lane:
    step: RouteStep
    model: ModelConfig
    window: RateWindow
    batch_tokens: int
    last_resort: bool
    failures: int = 0
    retired: str | None = None  # reason, once dropped

    @property
    def label(self) -> str:
        return f"{self.step.provider}/{self.model.id}"


@dataclass(eq=False)
class Flight:
    """A batch currently being scored."""

    lane: Lane
    batch: list[ItemToScore]
    started: float
    hedged: bool = False
    task: asyncio.Future[ScoreBatch] | None = None


@dataclass
class ParallelOutcome:
    scores: dict[str, ItemScore]  # item id → score
    scored_by: dict[str, str]  # item id → "provider/model"
    unscored: list[ItemToScore]
    batches: list[BatchResult] = field(default_factory=list)
    lane_errors: list[str] = field(default_factory=list)
    seconds: float = 0.0


class ParallelScorer:
    def __init__(
        self,
        router: Router,
        cfg: ParallelConfig,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.router = router
        self.cfg = cfg
        self._sleep = sleep or asyncio.sleep

    # ------------------------------------------------------------------ setup
    def _lanes(self) -> list[Lane]:
        lanes: list[Lane] = []
        now = datetime.now(UTC)
        for step in self.router._route("score_items"):  # skips unconfigured/blocked providers
            model = self.router.config.model(step.provider, step.model)
            if self._daily_exhausted(step, model):
                continue
            window = RateWindow(model.limits.rpm, model.limits.tpm, self.cfg.safety_ratio)
            if self.router.usage is not None:
                recent = self.router.usage.recent(
                    step.provider, model.id, now - timedelta(minutes=1)
                )
                window.seed([((now - ts).total_seconds(), tok) for ts, tok in recent])
            budget = model.max_request_tokens or self.cfg.default_batch_tokens
            if window.tpm:
                budget = min(budget, window.tpm)
            lanes.append(Lane(step, model, window, budget, step.provider in self.cfg.last_resort))
        return lanes

    def _daily_exhausted(self, step: RouteStep, model: ModelConfig) -> bool:
        usage = self.router.usage
        if usage is None or not (model.limits.rpd or model.limits.tpd):
            return False
        reqs, tokens, _ = usage.totals(
            step.provider, model.id, datetime.now(UTC) - timedelta(days=1)
        )
        lim = model.limits
        return bool((lim.rpd and reqs >= lim.rpd * 0.98) or (lim.tpd and tokens >= lim.tpd * 0.98))

    # ------------------------------------------------------------------ run
    async def score(
        self,
        items: Sequence[ItemToScore],
        series_hint: str = "",
        on_batch: Callable[[BatchResult], None] | None = None,
        on_lane_drop: Callable[[str, str], None] | None = None,
    ) -> ParallelOutcome:
        start = time.monotonic()
        lanes = self._lanes()
        queue: deque[ItemToScore] = deque(items)
        attempts: dict[str, int] = {i.id: 0 for i in items}
        outcome = ParallelOutcome(scores={}, scored_by={}, unscored=[])
        if not items:
            return outcome
        if not lanes:
            outcome.unscored = list(items)
            outcome.lane_errors.append("no usable providers for score_items")
            return outcome

        overhead = estimate_tokens(
            prompts.render(
                "scout_scoring",
                output_schema=json.dumps(ScoreBatch.model_json_schema()),
                series_hint=series_hint,
            )
        )
        changed = asyncio.Event()
        inflight: list[Flight] = []
        total = len(items)
        given_up: set[str] = set()

        def settled() -> bool:
            return len(outcome.scores) + len(given_up) >= total

        def cost(item: ItemToScore) -> int:
            return estimate_tokens(item.model_dump_json()) + SCORE_OUTPUT_TOKENS_PER_ITEM

        def primaries_alive() -> bool:
            return any(not lane.last_resort and lane.retired is None for lane in lanes)

        def take(lane: Lane) -> tuple[list[ItemToScore], int]:
            batch: list[ItemToScore] = []
            used = overhead
            while queue and (not batch or used + cost(queue[0]) <= lane.batch_tokens):
                item = queue.popleft()
                if item.id in outcome.scores or item.id in given_up:
                    continue  # already scored by a hedge copy
                batch.append(item)
                used += cost(item)
            return batch, used

        def retire(lane: Lane, reason: str) -> None:
            if lane.retired is None:
                lane.retired = reason
                outcome.lane_errors.append(f"{lane.label}: {reason}")
                if on_lane_drop:
                    on_lane_drop(lane.label, reason)
            changed.set()

        def hedge_candidate(lane: Lane) -> Flight | None:
            """A slow in-flight batch on another lane that this idle lane could duplicate."""
            now = time.monotonic()
            for flight in inflight:
                if (
                    flight.lane is not lane
                    and not flight.hedged
                    and now - flight.started >= self.cfg.hedge_after_s
                    and any(i.id not in outcome.scores for i in flight.batch)
                ):
                    return flight
            return None

        def give_up(item: ItemToScore) -> None:
            if item.id not in outcome.scores and item.id not in given_up:
                given_up.add(item.id)
                outcome.unscored.append(item)

        async def send(
            lane: Lane, batch: list[ItemToScore], est: int, hedge_of: Flight | None
        ) -> None:
            lane.window.add(est)
            flight = Flight(lane, batch, time.monotonic())
            if hedge_of is not None:
                hedge_of.hedged = True
                flight.hedged = True
            flight.task = asyncio.ensure_future(
                self.router._json_task(
                    "score_items",
                    "scout_scoring",
                    [i.model_dump() for i in batch],
                    ScoreBatch,
                    prompt_vars={"series_hint": series_hint},
                    route=[lane.step],
                )
            )
            inflight.append(flight)
            try:
                batch_out = await flight.task
            except asyncio.CancelledError:
                if flight.task.cancelled():
                    return  # superseded: everything it held was scored elsewhere
                raise
            except ProviderError as e:
                if hedge_of is None:  # a failed hedge copy changes nothing
                    for item in reversed(batch):
                        if item.id in outcome.scores:
                            continue
                        attempts[item.id] += 1
                        if attempts[item.id] < self.cfg.max_item_attempts:
                            queue.appendleft(item)
                        else:
                            give_up(item)
                lane.failures += 1
                if getattr(e, "block", False):
                    retire(lane, f"blocked: {e}")
                elif lane.failures >= self.cfg.max_failures_per_lane:
                    retire(lane, f"{lane.failures} failures in a row; last: {e}")
                return
            finally:
                inflight.remove(flight)
                changed.set()
            lane.failures = 0
            wanted = {i.id for i in batch}
            got = {sc.id: sc for sc in batch_out.scores if sc.id in wanted}
            new = [sc for sid, sc in got.items() if sid not in outcome.scores]
            for item in batch:
                if item.id in got:
                    if item.id not in outcome.scores:
                        outcome.scores[item.id] = got[item.id]
                        outcome.scored_by[item.id] = lane.label
                elif item.id not in outcome.scores and hedge_of is None:
                    attempts[item.id] += 1  # the model skipped it: retry elsewhere
                    if attempts[item.id] < self.cfg.max_item_attempts:
                        queue.append(item)
                    else:
                        give_up(item)
            result = BatchResult(
                lane.step.provider,
                lane.model.id,
                batch,
                new,
                round(time.monotonic() - flight.started, 1),
                hedge=hedge_of is not None,
            )
            outcome.batches.append(result)
            if on_batch and new:
                on_batch(result)
            if settled():  # cancel slower duplicates still running
                for other in list(inflight):
                    if other.task is not None:
                        other.task.cancel()

        async def worker(lane: Lane) -> None:
            while lane.retired is None and not settled():
                if lane.last_resort and primaries_alive():
                    changed.clear()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(changed.wait(), timeout=1.0)
                    continue
                if not queue:
                    if not inflight:
                        return
                    candidate = hedge_candidate(lane)
                    if candidate is not None:
                        pending = [i for i in candidate.batch if i.id not in outcome.scores]
                        est = overhead + sum(cost(i) for i in pending)
                        if lane.window.wait_for(est) == 0 and est <= lane.batch_tokens * 1.5:
                            await send(lane, pending, est, hedge_of=candidate)
                            continue
                    changed.clear()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(changed.wait(), timeout=1.0)
                    continue
                est_first = overhead + cost(queue[0])
                wait = lane.window.wait_for(min(lane.batch_tokens, est_first * 4))
                if wait > 0:
                    await self._sleep(min(wait, 2.0))  # re-check often; others may take the work
                    continue
                batch, est = take(lane)
                if batch:
                    await send(lane, batch, est, hedge_of=None)

        workers = [
            worker(lane)
            for lane in lanes
            for _ in range(max(1, self.cfg.workers.get(lane.step.provider, 1)))
        ]
        await asyncio.gather(*workers)
        for item in queue:
            give_up(item)
        outcome.seconds = round(time.monotonic() - start, 1)
        return outcome
