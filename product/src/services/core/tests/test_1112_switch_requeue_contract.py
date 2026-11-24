"""R5：被抢占的任务排到插队者后面，并在轮到自己时自动接力。

用户口径：等待中的任务点「开始」等于插队，被插队的那条排到等待区第一个，
插队的人跑完它自己继续，不需要再点一次开始。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from app.workflows.queue import LocalJobQueue


class _FakeJob:
    def __init__(self, job_id: str, state: str = "queued") -> None:
        self.id = job_id
        self.state = SimpleNamespace(value=state)
        self.queue_position: int | None = None


class _FakeStore:
    def __init__(self, job_ids: list[str]) -> None:
        self.jobs = {job_id: _FakeJob(job_id) for job_id in job_ids}

    def get_job(self, job_id: str) -> _FakeJob:
        return self.jobs[job_id]

    def save_job(self, job: _FakeJob) -> None:
        self.jobs[job.id] = job


def test_preempted_job_resumes_after_the_job_that_jumped_ahead():
    store = _FakeStore(["A", "B", "C"])
    order: list[str] = []
    revived: list[str] = []
    started = threading.Event()
    release = threading.Event()

    def runner(job_id: str, _transcript) -> None:
        order.append(job_id)
        if job_id == "A":
            started.set()
            release.wait(5)

    queue = LocalJobQueue(store, lambda: 1, revive_provider=revived.append)
    worker = threading.Thread(target=queue.submit, args=("A", None, runner), daemon=True)
    worker.start()
    assert started.wait(5), "首条任务没有开始"

    # 用户对 B 点「开始」：B 插到队首，A 让出执行权并排到 B 后面。
    queue.submit("B", None, runner)
    queue.submit("C", None, runner)
    store.jobs["A"].state = SimpleNamespace(value="paused")
    queue.move_to_front("B")
    queue.requeue("A", index=1)
    assert queue.snapshot()["job_ids"] == ["B", "A", "C"], "被抢占者应排在插队者之后"

    release.set()
    worker.join(10)
    assert not worker.is_alive(), "队列没有推进完"
    assert order == ["A", "B", "A", "C"], f"接力顺序不对：{order}"
    assert "A" in revived, "被抢占的任务没有被唤醒，需要用户再点一次开始"


def test_requeue_does_not_duplicate_an_already_waiting_job():
    store = _FakeStore(["A", "B"])
    queue = LocalJobQueue(store, lambda: 1)

    queue.requeue("B", index=0)
    queue.requeue("B", index=1)
    assert queue.snapshot()["job_ids"] == ["B"], "同一任务不应在等待区出现两次"
