"""11-18c R1/R3：启动挂起与「继续」幂等。

启动挂起的口径来自用户裁定：重启之后并不默认全量跑，上一次关闭就停了，
这一次要用户手动点「继续」。因此跨会话遗留的非终态任务（含上次正在跑、
被关掉打断的那条）一律转 paused，保留断点。

不碰 ``product/local/knowledge.db``：全部用临时 sqlite 文件库。
"""

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.api.main import _hold_interrupted_jobs, create_app
from app.domain.jobs import JobState
from app.domain.models import AnalysisSettings


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(f"sqlite:///{tmp_path / 'hold.db'}"))


def _add_job(client: TestClient, state: JobState, *, lease_minutes: float | None = None):
    """建一条指定状态的任务，不经过队列，避免测试里真的跑分析。"""

    store = client.app.state.store
    content = client.post(
        "/api/v1/contents",
        json={"kind": "article", "title": f"挂起样本 {state.value}", "platform": "web"},
    ).json()
    _run, job = store.create_analysis_run(content["id"], AnalysisSettings(model="test-model"))
    job.state = state
    if lease_minutes is not None:
        job.lease_until = datetime.now(UTC) + timedelta(minutes=lease_minutes)
    store.save_job(job)
    return job


def test_startup_hold_pauses_every_interrupted_job(tmp_path) -> None:
    """排队中 / 运行中（含 lease 未过期）/ 已被打断的，全部转已暂停。"""

    client = _client(tmp_path)
    queued = _add_job(client, JobState.QUEUED)
    running = _add_job(client, JobState.TRANSCRIBING, lease_minutes=30)
    already_paused = _add_job(client, JobState.PAUSED)
    completed = _add_job(client, JobState.COMPLETED)

    store = client.app.state.store
    assert _hold_interrupted_jobs(store) == 2, "只挂起两条非终态且非 paused 的任务"

    for job in (queued, running):
        held = store.get_job(job.id)
        assert held.state is JobState.PAUSED, "11-18c R1：重启后一律停住"
        assert held.queue_position is None, "11-18c R1：挂起后不占队列位次"
        assert held.worker_id is None and held.lease_until is None, "transition(PAUSED) 自带清租约"
        assert "resume_checkpoint" in held.metadata, "11-18c R1：必须保留断点"
        assert store.get_analysis_run(held.analysis_run_id).status == "paused", \
            "11-18c R1：run.status 同步为 paused，否则「继续」状态不一致"

    assert store.get_job(already_paused.id).state is JobState.PAUSED, \
        "已是 paused 的不重复转移（PAUSED→PAUSED 在转移表里非法）"
    assert store.get_job(completed.id).state is JobState.COMPLETED, "终态不得被挂起"

    snapshot = client.app.state.job_queue.snapshot()
    assert snapshot["active"] == 0 and snapshot["queued"] == 0, "11-18c R1：一条都不进队列"


def test_startup_hold_is_one_shot(tmp_path) -> None:
    """第二次执行不再变动任何任务，可以安全重跑。"""

    client = _client(tmp_path)
    _add_job(client, JobState.QUEUED)
    store = client.app.state.store

    assert _hold_interrupted_jobs(store) == 1
    assert _hold_interrupted_jobs(store) == 0


def test_resume_rejects_completed_job(tmp_path) -> None:
    """11-18c R3：queued 幂等只放行排队中，已完成仍 409。"""

    client = _client(tmp_path)
    completed = _add_job(client, JobState.COMPLETED)

    response = client.post(f"/api/v1/jobs/{completed.id}/resume")

    assert response.status_code == 409
    assert response.json()["detail"] == "job_not_paused"
