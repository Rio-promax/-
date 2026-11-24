"""Small persistent-aware queue for one-at-a-time local analysis jobs.

The database keeps the processing state machine (``acquiring`` through
``indexing``) because it is also used by recovery and diagnostics.  This
queue owns the user-facing execution order: at most one job is active and
waiting jobs have one authoritative order.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable


@dataclass(slots=True)
class _QueueItem:
    job_id: str
    transcript: Any
    priority: int
    sequence: int


class LocalJobQueue:
    """Keep local work ordered while allowing the API to remain synchronous in tests.

    ``priority`` remains on the compatibility surface for old stored jobs and
    old API clients, but it never participates in scheduling.  New work is
    FIFO and user reordering is explicit.
    """

    def __init__(
        self,
        store,
        limit_provider: Callable[[], int] | None = None,
        revive_provider: Callable[[str], None] | None = None,
    ) -> None:
        self.store = store
        self.limit_provider = limit_provider or (lambda: 1)
        # A job that yielded the worker keeps ``paused`` until its turn comes;
        # ``revive_provider`` puts it back into a runnable state right before
        # the runner starts, so the yield still continues automatically.
        self.revive_provider = revive_provider
        self._lock = RLock()
        self._active: str | None = None
        self._pending: list[_QueueItem] = []
        self._sequence = 0

    def submit(
        self,
        job_id: str,
        transcript: Any,
        runner: Callable[[str, Any], None],
        *,
        priority: int = 0,
    ) -> None:
        stored = self.store.get_job(job_id)
        stored_state = getattr(getattr(stored, "state", None), "value", getattr(stored, "state", None))
        if stored_state is not None and stored_state != "queued":
            return
        item = _QueueItem(job_id, transcript, priority, self._sequence)
        run_now = False
        with self._lock:
            self._sequence += 1
            if job_id == self._active or any(
                pending.job_id == job_id for pending in self._pending
            ):
                return
            if self._active is None:
                self._active = job_id
                run_now = True
            else:
                self._pending.append(item)
                self._save_positions()
        if run_now:
            self._run(item, runner)

    def active_job_id(self) -> str | None:
        with self._lock:
            return self._active

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "active": 1 if self._active else 0,
                "active_job_id": self._active,
                "queued": len(self._pending),
                "concurrency_limit": 1,
                "job_ids": [item.job_id for item in self._pending],
                "items": [
                    {
                        "job_id": item.job_id,
                        # Compatibility only.  The UI and scheduler do not use it.
                        "priority": item.priority,
                        "queue_position": position,
                    }
                    for position, item in enumerate(self._pending, start=1)
                ],
            }

    def move_to_front(self, job_id: str) -> dict[str, object]:
        """Move one waiting job to the front and persist the resulting order."""

        with self._lock:
            index = next(
                (index for index, item in enumerate(self._pending) if item.job_id == job_id),
                None,
            )
            if index is not None and index > 0:
                item = self._pending.pop(index)
                self._pending.insert(0, item)
                self._save_positions()
            return self.snapshot()

    def requeue(self, job_id: str, index: int = 0) -> dict[str, object]:
        """Put a job that yielded the worker back into the waiting line.

        The item keeps its stored state until the queue reaches it; the revive
        callback turns it back into a runnable job right before it starts.
        """

        with self._lock:
            if any(item.job_id == job_id for item in self._pending):
                return self.snapshot()
            item = _QueueItem(job_id, None, 0, self._sequence)
            self._sequence += 1
            bounded = max(0, min(int(index), len(self._pending)))
            self._pending.insert(bounded, item)
            self._save_positions()
            return self.snapshot()

    def move(self, job_id: str, target_index: int) -> dict[str, object]:
        """Move one waiting item; callers send only the changed item."""

        with self._lock:
            index = next(
                (index for index, item in enumerate(self._pending) if item.job_id == job_id),
                None,
            )
            if index is None:
                return self.snapshot()
            item = self._pending.pop(index)
            bounded = max(0, min(int(target_index), len(self._pending)))
            self._pending.insert(bounded, item)
            self._save_positions()
            return self.snapshot()

    def reorder(self, job_ids: list[str]) -> dict[str, object]:
        """Compatibility endpoint for old clients; new UI uses :meth:`move`."""

        with self._lock:
            by_id = {item.job_id: item for item in self._pending}
            ordered: list[_QueueItem] = []
            seen: set[str] = set()
            for job_id in job_ids:
                item = by_id.get(job_id)
                if item is None or job_id in seen:
                    continue
                ordered.append(item)
                seen.add(job_id)
            ordered.extend(item for item in self._pending if item.job_id not in seen)
            self._pending = ordered
            self._save_positions()
            return self.snapshot()

    def set_priority(self, job_id: str, priority: int) -> dict[str, object]:
        """Keep the legacy field writable without changing queue order."""

        with self._lock:
            item = next((candidate for candidate in self._pending if candidate.job_id == job_id), None)
            if item is not None:
                item.priority = priority
                self._save_positions()
            return self.snapshot()

    def start_waiting(
        self,
        job_id: str,
        runner: Callable[[str, Any], None],
    ) -> bool:
        """Run a specific waiting item immediately when there is no active job."""

        with self._lock:
            if self._active is not None:
                return False
            index = next(
                (index for index, item in enumerate(self._pending) if item.job_id == job_id),
                None,
            )
            if index is None:
                return False
            item = self._pending.pop(index)
            stored = self.store.get_job(item.job_id)
            stored_state = getattr(getattr(stored, "state", None), "value", getattr(stored, "state", None))
            if stored_state is not None and stored_state != "queued":
                self._save_positions()
                return False
            self._active = item.job_id
            stored.queue_position = None
            self.store.save_job(stored)
            self._save_positions()
        self._run(item, runner)
        return True

    def remove(self, job_id: str) -> None:
        """Remove a waiting item after cancellation or deletion."""

        with self._lock:
            self._pending = [item for item in self._pending if item.job_id != job_id]
            self._save_positions()

    def _save_positions(self) -> None:
        for position, item in enumerate(self._pending, start=1):
            job = self.store.get_job(item.job_id)
            if job.queue_position != position:
                job.queue_position = position
                self.store.save_job(job)

    def _run(self, item: _QueueItem, runner: Callable[[str, Any], None]) -> None:
        # 11-18c R1：原来是 ``finally`` 里递归调用自身，串行长队列会按任务数叠栈。
        while True:
            next_item: _QueueItem | None = None
            failure: BaseException | None = None
            try:
                runner(item.job_id, item.transcript)
            except BaseException as error:  # noqa: BLE001 - 后续任务仍要继续排空
                failure = error
            finally:
                with self._lock:
                    current = self.store.get_job(item.job_id)
                    self._active = None
                    if self._pending:
                        next_item = self._pending.pop(0)
                        self._active = next_item.job_id
                        next_job = self.store.get_job(next_item.job_id)
                        next_job.queue_position = None
                        self.store.save_job(next_job)
                    self._save_positions()
            if next_item is not None:
                if self.revive_provider is not None:
                    self.revive_provider(next_item.job_id)
                item = next_item
                continue
            if failure is not None:
                raise failure
            return
