from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.clip_api import router as clip_router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(clip_router)
    return app


def _make_session_factory(*, clip=None, active_job=None, job_for_get=None):
    """构造一个 mock session_factory，默认：clip 存在 + 无活跃任务。

    改 30%: 加 active_job 控制活跃任务查询（execute → scalar_one_or_none）。
    """
    fake_session = MagicMock()
    fake_session.get = AsyncMock(side_effect=lambda model, ident: (
        clip if model.__name__ == "Clip" else (job_for_get if model.__name__ == "Job" else None)
    ))

    # execute 返回的对象 .scalar_one_or_none() = active_job（默认 None）
    fake_result = MagicMock()
    fake_result.scalar_one_or_none = MagicMock(return_value=active_job)
    fake_session.execute = AsyncMock(return_value=fake_result)

    fake_session.add = MagicMock()
    fake_session.commit = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)
    return lambda: MagicMock(return_value=fake_session)


@pytest.fixture
def client(monkeypatch):
    async def _fake_enqueue(*args, **kwargs):
        return "job-fake-123"

    monkeypatch.setattr("api.clip_api.enqueue_job", _fake_enqueue)

    mock_clip = MagicMock(id="C1")
    monkeypatch.setattr(
        "api.clip_api.get_session_factory",
        _make_session_factory(clip=mock_clip),
    )

    return TestClient(_make_app())


def test_regenerate_returns_202_with_job_id(client):
    resp = client.post(
        "/api/v1/clips/C1/regenerate",
        json={"new_prompt": "test prompt"},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body["job_id"] == "job-fake-123"
    assert body["clip_id"] == "C1"
    assert body["status"] == "queued"
    assert body["poll_url"] == "/api/v1/jobs/job-fake-123"


def test_regenerate_400_when_no_change_param(client):
    resp = client.post("/api/v1/clips/C1/regenerate", json={})

    assert resp.status_code == 400
    assert "at least one" in resp.json()["detail"]


def test_regenerate_404_when_clip_missing(monkeypatch):
    monkeypatch.setattr(
        "api.clip_api.get_session_factory",
        _make_session_factory(clip=None),
    )

    client = TestClient(_make_app())
    resp = client.post(
        "/api/v1/clips/NONEXIST/regenerate",
        json={"new_prompt": "x"},
    )

    assert resp.status_code == 404


def test_get_job_status_returns_progress(monkeypatch):
    mock_job = MagicMock(
        id="J1",
        job_type="regenerate_clip",
        status="running",
        progress=30,
        progress_stage="generating_video",
        result=None,
        error=None,
    )
    monkeypatch.setattr(
        "api.clip_api.get_session_factory",
        _make_session_factory(job_for_get=mock_job),
    )

    client = TestClient(_make_app())
    resp = client.get("/api/v1/jobs/J1")

    assert resp.status_code == 200
    body = resp.json()
    assert body["progress"] == 30
    assert body["progress_stage"] == "generating_video"
    assert body["status"] == "running"


def test_get_job_status_404_when_missing(monkeypatch):
    monkeypatch.setattr(
        "api.clip_api.get_session_factory",
        _make_session_factory(),
    )

    client = TestClient(_make_app())
    resp = client.get("/api/v1/jobs/NONEXIST")

    assert resp.status_code == 404


# ── 并发保护测试 ──


def test_regenerate_409_when_active_job_exists(monkeypatch):
    """同 clip 已有活跃任务 → 拒绝新请求 + 返回 existing job_id（防 race）。"""
    async def _fake_enqueue(*args, **kwargs):
        # 如果走到这一步说明并发保护失效
        raise AssertionError("enqueue_job should NOT be called when active job exists")

    monkeypatch.setattr("api.clip_api.enqueue_job", _fake_enqueue)

    mock_clip = MagicMock(id="C1")
    existing_job = MagicMock(
        id="job-existing-42",
        status="running",
        progress=30,
    )
    monkeypatch.setattr(
        "api.clip_api.get_session_factory",
        _make_session_factory(clip=mock_clip, active_job=existing_job),
    )

    client = TestClient(_make_app())
    resp = client.post(
        "/api/v1/clips/C1/regenerate",
        json={"new_prompt": "另一次尝试"},
    )

    assert resp.status_code == 409
    body = resp.json()
    detail = body["detail"]
    assert detail["error"] == "regenerate_already_running"
    assert detail["existing_job_id"] == "job-existing-42"
    assert detail["existing_status"] == "running"
    assert detail["existing_progress"] == 30
    assert detail["existing_poll_url"] == "/api/v1/jobs/job-existing-42"


def test_regenerate_passes_when_only_done_jobs_exist(monkeypatch):
    """只有 done/failed 状态的旧任务 → 不阻止新任务（活跃状态查询应只看 queued/running）。

    我们直接让 active_job=None（模拟"没有活跃任务，只有历史 done/failed 不入查询"）。
    """
    async def _fake_enqueue(*args, **kwargs):
        return "job-fake-new"

    monkeypatch.setattr("api.clip_api.enqueue_job", _fake_enqueue)

    mock_clip = MagicMock(id="C1")
    # active_job=None 表示查询过滤掉了 done/failed
    monkeypatch.setattr(
        "api.clip_api.get_session_factory",
        _make_session_factory(clip=mock_clip, active_job=None),
    )

    client = TestClient(_make_app())
    resp = client.post(
        "/api/v1/clips/C1/regenerate",
        json={"new_prompt": "新一次"},
    )

    assert resp.status_code == 202
    assert resp.json()["job_id"] == "job-fake-new"


def test_active_job_statuses_constant_only_includes_queued_and_running():
    """ACTIVE_JOB_STATUSES 必须只含 queued/running（done/failed 不算活跃）。"""
    from api.clip_api import ACTIVE_JOB_STATUSES
    assert set(ACTIVE_JOB_STATUSES) == {"queued", "running"}


def test_regenerate_writes_target_id_to_jobs_table(monkeypatch):
    """新任务入队时 jobs.target_id 必须 = clip_id（防并发查询的依据）。"""
    async def _fake_enqueue(*args, **kwargs):
        return "job-fake-tgt"

    monkeypatch.setattr("api.clip_api.enqueue_job", _fake_enqueue)

    captured_add = []
    mock_clip = MagicMock(id="C1")

    fake_session = MagicMock()
    fake_session.get = AsyncMock(return_value=mock_clip)
    fake_result = MagicMock()
    fake_result.scalar_one_or_none = MagicMock(return_value=None)
    fake_session.execute = AsyncMock(return_value=fake_result)
    fake_session.add = MagicMock(side_effect=lambda obj: captured_add.append(obj))
    fake_session.commit = AsyncMock()
    fake_session.__aenter__ = AsyncMock(return_value=fake_session)
    fake_session.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(
        "api.clip_api.get_session_factory",
        lambda: MagicMock(return_value=fake_session),
    )

    client = TestClient(_make_app())
    resp = client.post("/api/v1/clips/C1/regenerate", json={"new_prompt": "x"})
    assert resp.status_code == 202

    job_orm = next(o for o in captured_add if hasattr(o, "target_id"))
    assert job_orm.target_id == "C1"
    assert job_orm.id == "job-fake-tgt"
    assert job_orm.status == "queued"
    assert job_orm.job_type == "regenerate_clip"


def test_regenerate_payload_max_length_validation(client):
    resp = client.post(
        "/api/v1/clips/C1/regenerate",
        json={"new_prompt": "x" * 2001},
    )

    assert resp.status_code == 422
