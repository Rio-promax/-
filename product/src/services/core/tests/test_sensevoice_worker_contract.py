from __future__ import annotations

import json
from pathlib import Path
from queue import Empty
from types import SimpleNamespace

import pytest

from app.adapters.asr import local as local_asr


class _Stdin:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, value: str) -> None:
        self.writes.append(value)

    def flush(self) -> None:
        return

    def close(self) -> None:
        return


class _Process:
    pid = 100
    returncode = None

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


class _Events:
    def __init__(self, stdin: _Stdin, event: dict[str, object], empty_count: int) -> None:
        self.stdin = stdin
        self.event = event
        self.empty_count = empty_count
        self.calls = 0

    def get(self, timeout=None):
        self.calls += 1
        if self.calls <= self.empty_count:
            raise Empty
        if self.event.get("event") == "batch_result":
            request = json.loads(self.stdin.writes[-1])
            return {
                **self.event,
                "request_id": request["request_id"],
                "items": [
                    {
                        **item,
                        "request_id": request["request_id"],
                    }
                    for item in self.event["items"]
                ],
            }
        return self.event


def _worker(
    *,
    event: dict[str, object],
    empty_count: int = 0,
    timeout: float = 0.01,
) -> tuple[local_asr.SenseVoiceWorker, _Stdin, _Events]:
    worker = local_asr.SenseVoiceWorker(
        Path("model"),
        segment_timeout_seconds=timeout,
    )
    stdin = _Stdin()
    events = _Events(stdin, event, empty_count)
    worker._stdin = stdin
    worker._events = events
    worker._process = _Process()
    worker._ready = True
    return worker, stdin, events


class _StickyArgtypeFunction:
    """Model a WinDLL function whose ctypes signature persists between calls."""

    def __init__(self, callback):
        self._callback = callback
        self._argtypes = None
        self.restype = None

    @property
    def argtypes(self):
        return self._argtypes

    @argtypes.setter
    def argtypes(self, value):
        if self._argtypes is not None and value != self._argtypes:
            raise TypeError("ctypes function received a different structure type")
        self._argtypes = value

    def __call__(self, *args):
        return self._callback(*args)


def _fake_windows_windll() -> SimpleNamespace:
    def process_first(_snapshot, entry):
        entry._obj.th32ProcessID = 101
        entry._obj.th32ParentProcessID = 100
        return 1

    def process_next(_snapshot, _entry):
        return 0

    def get_memory(_process, counters, _size):
        counters._obj.working_set_size = 8 * 1024 * 1024
        return 1

    def get_times(_process, _creation, _exit, kernel, user):
        kernel._obj.low = 10_000_000
        kernel._obj.high = 0
        user._obj.low = 5_000_000
        user._obj.high = 0
        return 1

    kernel32 = SimpleNamespace(
        CreateToolhelp32Snapshot=_StickyArgtypeFunction(lambda *_args: 1),
        Process32FirstW=_StickyArgtypeFunction(process_first),
        Process32NextW=_StickyArgtypeFunction(process_next),
        OpenProcess=_StickyArgtypeFunction(lambda *_args: 1),
        GetProcessTimes=_StickyArgtypeFunction(get_times),
        CloseHandle=_StickyArgtypeFunction(lambda *_args: 1),
    )
    psapi = SimpleNamespace(
        GetProcessMemoryInfo=_StickyArgtypeFunction(get_memory),
    )
    return SimpleNamespace(kernel32=kernel32, psapi=psapi)


def test_windows_process_tree_can_be_sampled_repeatedly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local_asr, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        local_asr.ctypes,
        "windll",
        _fake_windows_windll(),
        raising=False,
    )

    assert local_asr._windows_process_tree(100) == (100, 101)
    assert local_asr._windows_process_tree(100) == (100, 101)


def test_worker_memory_and_cpu_sampling_can_be_called_repeatedly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, _stdin, _events = _worker(
        event={"event": "result", "text": "采样", "language": "zh"},
    )
    monkeypatch.setattr(local_asr, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        local_asr.ctypes,
        "windll",
        _fake_windows_windll(),
        raising=False,
    )

    try:
        assert worker.memory_rss_mb() == pytest.approx(16.0)
        assert worker.memory_rss_mb() == pytest.approx(16.0)
        assert worker.cpu_time_seconds() == pytest.approx(3.0)
        assert worker.cpu_time_seconds() == pytest.approx(3.0)
    finally:
        worker.close()


@pytest.mark.parametrize("batch", [False, True])
def test_worker_cpu_progress_extends_single_and_batch_deadline(
    monkeypatch: pytest.MonkeyPatch,
    batch: bool,
) -> None:
    if batch:
        worker, _stdin, _events = _worker(
            event={
                "event": "batch_result",
                "items": [
                    {"ordinal": 0, "text": "第一片", "language": "zh"},
                    {"ordinal": 1, "text": "第二片", "language": "zh"},
                ],
            },
            empty_count=80,
        )
    else:
        worker, _stdin, _events = _worker(
            event={"event": "result", "text": "长片仍在计算", "language": "zh"},
            empty_count=80,
        )
    ticks = iter([0.0, *[index / 100.0 for index in range(1, 120)]])
    monkeypatch.setattr(worker, "cpu_time_seconds", lambda: next(ticks, 2.0))

    try:
        if batch:
            result = worker.transcribe_batch([Path("a.wav"), Path("b.wav")])
            assert [item[0] for item in result] == ["第一片", "第二片"]
        else:
            assert worker.transcribe(Path("a.wav"))[0] == "长片仍在计算"
    finally:
        worker.close()


@pytest.mark.parametrize("batch", [False, True])
def test_worker_rebuilds_only_after_real_no_progress(
    monkeypatch: pytest.MonkeyPatch,
    batch: bool,
) -> None:
    event = (
        {
            "event": "batch_result",
            "items": [
                {"ordinal": 0, "text": "不会返回", "language": "zh"},
                {"ordinal": 1, "text": "不会返回", "language": "zh"},
            ],
        }
        if batch
        else {"event": "result", "text": "不会返回", "language": "zh"}
    )
    worker, _stdin, _events = _worker(event=event, empty_count=100000)
    monkeypatch.setattr(worker, "cpu_time_seconds", lambda: 0.0)

    try:
        with pytest.raises(TimeoutError):
            if batch:
                worker.transcribe_batch([Path("a.wav"), Path("b.wav")])
            else:
                worker.transcribe(Path("a.wav"))
    finally:
        worker.close()


def test_worker_rejects_duplicate_and_out_of_order_batch_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker, _stdin, _events = _worker(
        event={
            "event": "batch_result",
            "items": [
                {"ordinal": 0, "text": "第一片", "language": "zh"},
                {"ordinal": 0, "text": "重复片", "language": "zh"},
            ],
        },
        timeout=0.2,
    )
    monkeypatch.setattr(worker, "cpu_time_seconds", lambda: None)
    try:
        with pytest.raises(local_asr.LocalAsrError, match="缺失、重复或乱序"):
            worker.transcribe_batch([Path("a.wav"), Path("b.wav")])
        assert worker.last_batch_integrity == {
            "missing_segments": 1,
            "duplicate_segments": 1,
            "out_of_order_segments": 1,
            "status": "invalid",
        }
    finally:
        worker.close()


def test_sensevoice_runtime_does_not_use_environment_or_desktop_python(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_runtime = tmp_path / "fake-python.exe"
    fake_runtime.write_bytes(b"fake")
    monkeypatch.setenv("SENSEVOICE_RUNTIME_PYTHON", str(fake_runtime))
    resolved = local_asr._external_sensevoice_python()
    assert resolved != fake_runtime
