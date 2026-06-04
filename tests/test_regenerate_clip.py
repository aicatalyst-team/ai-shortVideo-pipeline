from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.models import Base, Clip, FrameAsset, Storyboard
from layers.L3_visual.providers.base import VideoResult
from layers.L3_visual.regenerate import ClipNotFoundError, regenerate_clip


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[Storyboard.__table__, Clip.__table__, FrameAsset.__table__])
    sync_factory = sessionmaker(engine, expire_on_commit=False)

    class _AsyncSessionWrapper:
        def __init__(self):
            self._session = sync_factory()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            self._session.close()
            return False

        async def execute(self, statement):
            return self._session.execute(statement)

        async def get(self, model, ident):
            return self._session.get(model, ident)

        async def commit(self):
            self._session.commit()

        def add(self, obj):
            self._session.add(obj)

        def add_all(self, objs):
            self._session.add_all(objs)

    class _Factory:
        bind = engine

        def __call__(self):
            return _AsyncSessionWrapper()

    return _Factory()


def _shot_metadata(scene_no: int = 1, duration: float = 5.0) -> dict:
    return {
        "scene_no": scene_no,
        "narration_segment": f"narration {scene_no}",
        "estimated_duration_sec": duration,
        "character_id": "su_wan",
        "environment_id": "coffee_shop",
        "time_of_day": "morning",
        "subject_action": "looking at receipt",
        "subject_emotion": "surprised",
        "lighting_mood": "warm",
    }


async def _seed_storyboard(factory, *, with_metadata: bool = True):
    async with factory() as session:
        sb = Storyboard(
            id="SB001",
            plan_id="P001",
            title="storyboard",
            theme="theme",
            style_name="hot_news_commentary",
            status="ready",
        )
        clips = [
            Clip(
                id=f"C{i}",
                storyboard_id="SB001",
                seq=i,
                prompt=f"prompt {i}",
                kling_prompt=f"kling {i}",
                narration_segment=f"narration {i}",
                duration_sec=5,
                video_url=f"http://old/{i}.mp4",
                status="ready",
                version=1,
                r_metadata=_shot_metadata(i) if with_metadata else None,
            )
            for i in range(1, 6)
        ]
        session.add(sb)
        session.add_all(clips)
        await session.commit()


def _patch_style(monkeypatch):
    monkeypatch.setattr("layers.L3_visual.regenerate.get_template", lambda _name: SimpleNamespace(name="stub-style"))


def _patch_generate(monkeypatch, *, url="http://new/video.mp4", local_path="C:/tmp/generated.mp4", model="kling-v1"):
    async def _fake_generate_clip(**kwargs):
        return VideoResult(url=url, local_path=local_path, duration_sec=5, task_id="T1", model=model)

    monkeypatch.setattr("layers.L3_visual.regenerate.generate_clip", _fake_generate_clip)


def _patch_extract(monkeypatch, tmp_path: Path, *, tail_name="tail.png"):
    def _fake_extract(_video_path: str, output_path: str) -> str:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"tail")
        return str(p if tail_name == "tail.png" else tmp_path / tail_name)

    monkeypatch.setattr("layers.L3_visual.regenerate.extract_last_frame", _fake_extract)


@pytest.mark.anyio
async def test_regenerate_prompt_only_bumps_version(session_factory, monkeypatch, tmp_path):
    await _seed_storyboard(session_factory)
    _patch_style(monkeypatch)
    captured = {}

    async def _fake_generate_clip(**kwargs):
        captured.update(kwargs)
        return VideoResult(url="http://new/video-1.mp4", local_path=str(tmp_path / "video.mp4"), model="kling-v1")

    monkeypatch.setattr("layers.L3_visual.regenerate.generate_clip", _fake_generate_clip)
    _patch_extract(monkeypatch, tmp_path)

    result = await regenerate_clip("C1", new_prompt="new prompt", session_factory=session_factory)

    assert result.new_version == 2
    assert result.new_video_url == "http://new/video-1.mp4"
    assert captured["image_prompt"] == "new prompt"
    assert captured["kling_prompt"] == "kling 1"

    async with session_factory() as session:
        clip = await session.get(Clip, "C1")
        assert clip.version == 2
        assert clip.prompt == "new prompt"
        assert clip.status == "ready"


@pytest.mark.anyio
async def test_regenerate_first_frame_only_success(session_factory, monkeypatch, tmp_path):
    await _seed_storyboard(session_factory)
    _patch_style(monkeypatch)
    captured = {}

    async def _fake_generate_clip(**kwargs):
        captured.update(kwargs)
        return VideoResult(url="http://new/video-2.mp4", local_path=str(tmp_path / "video.mp4"), model="kling-v1")

    monkeypatch.setattr("layers.L3_visual.regenerate.generate_clip", _fake_generate_clip)
    _patch_extract(monkeypatch, tmp_path)

    result = await regenerate_clip(
        "C1",
        new_first_frame_url="http://example.com/frame.png",
        session_factory=session_factory,
    )

    assert result.new_version == 2
    assert captured["first_frame_path"] == "http://example.com/frame.png"


@pytest.mark.anyio
async def test_regenerate_requires_at_least_one_change(session_factory):
    with pytest.raises(ValueError, match="至少需要一个变更参数"):
        await regenerate_clip("C1", session_factory=session_factory)


@pytest.mark.anyio
async def test_regenerate_missing_clip_raises(session_factory):
    with pytest.raises(ClipNotFoundError):
        await regenerate_clip("NOPE", new_prompt="x", session_factory=session_factory)


@pytest.mark.anyio
async def test_regenerate_fallbacks_when_r_metadata_missing(session_factory, monkeypatch, tmp_path, caplog):
    await _seed_storyboard(session_factory, with_metadata=False)
    _patch_style(monkeypatch)
    captured = {}

    async def _fake_generate_clip(**kwargs):
        captured.update(kwargs)
        return VideoResult(url="http://new/video-3.mp4", local_path=str(tmp_path / "video.mp4"), model="kling-v1")

    monkeypatch.setattr("layers.L3_visual.regenerate.generate_clip", _fake_generate_clip)
    _patch_extract(monkeypatch, tmp_path)

    result = await regenerate_clip("C1", new_kling_prompt="override kling", session_factory=session_factory)

    assert result.new_version == 2
    assert captured["image_prompt"] == "prompt 1"
    assert captured["kling_prompt"] == "override kling"
    assert "missing r_metadata" in caplog.text


@pytest.mark.anyio
async def test_regenerate_marks_later_clips_dirty(session_factory, monkeypatch, tmp_path):
    await _seed_storyboard(session_factory)
    _patch_style(monkeypatch)
    _patch_generate(monkeypatch, url="http://new/video-4.mp4", local_path=str(tmp_path / "video.mp4"))
    _patch_extract(monkeypatch, tmp_path)

    result = await regenerate_clip("C2", new_prompt="new prompt 2", session_factory=session_factory)

    assert result.dirty_clip_ids == ["C3", "C4", "C5"]

    async with session_factory() as session:
        rows = await session.execute(select(Clip).where(Clip.storyboard_id == "SB001").order_by(Clip.seq))
        clips = rows.scalars().all()
        assert clips[1].status == "ready"
        assert [c.status for c in clips[2:]] == ["dirty", "dirty", "dirty"]


@pytest.mark.anyio
async def test_regenerate_failure_marks_clip_failed_without_bump(session_factory, monkeypatch):
    await _seed_storyboard(session_factory)
    _patch_style(monkeypatch)

    async def _boom(**_kwargs):
        raise RuntimeError("provider failed")

    monkeypatch.setattr("layers.L3_visual.regenerate.generate_clip", _boom)

    with pytest.raises(RuntimeError, match="provider failed"):
        await regenerate_clip("C1", new_prompt="broken", session_factory=session_factory)

    async with session_factory() as session:
        clip = await session.get(Clip, "C1")
        assert clip.status == "failed"
        assert clip.version == 1


@pytest.mark.anyio
async def test_regenerate_archives_old_video_into_frame_assets(session_factory, monkeypatch, tmp_path):
    await _seed_storyboard(session_factory)
    _patch_style(monkeypatch)
    _patch_generate(monkeypatch, url="http://new/video-5.mp4", local_path=str(tmp_path / "video.mp4"))
    _patch_extract(monkeypatch, tmp_path)

    await regenerate_clip("C1", new_prompt="new prompt", session_factory=session_factory)

    async with session_factory() as session:
        rows = await session.execute(select(FrameAsset).where(FrameAsset.clip_id == "C1").order_by(FrameAsset.kind))
        assets = rows.scalars().all()
        kinds = [a.kind for a in assets]
        assert "archived_video" in kinds
        assert "tail_frame" in kinds
        archived = next(a for a in assets if a.kind == "archived_video")
        assert archived.url == "http://old/1.mp4"


# ── 原首帧自动 fallback 测试 ──


async def _seed_first_frame(factory, clip_id: str, url: str = "http://orig/first.png"):
    """给 clip 灌一张 kind='first' 的原首帧资产。"""
    async with factory() as session:
        session.add(
            FrameAsset(
                clip_id=clip_id,
                kind="first",
                url=url,
                source="generated",
            )
        )
        await session.commit()


@pytest.mark.anyio
async def test_regenerate_prompt_only_reuses_existing_first_frame(session_factory, monkeypatch, tmp_path):
    """改 30%：用户只改 prompt 不传新首帧 → 必须从 frame_assets 读原首帧 → 画面与原段连续。

    痛点：早期版本漏了这块，导致 generate_clip 重新文生图 → 单段重生成画面断开。
    """
    await _seed_storyboard(session_factory)
    await _seed_first_frame(session_factory, "C2", url="http://orig/c2_first.png")
    _patch_style(monkeypatch)

    captured = {}

    async def _fake_generate_clip(**kwargs):
        captured.update(kwargs)
        return VideoResult(url="http://new/v6.mp4", local_path=str(tmp_path / "v6.mp4"), model="kling-v1")

    monkeypatch.setattr("layers.L3_visual.regenerate.generate_clip", _fake_generate_clip)
    _patch_extract(monkeypatch, tmp_path)

    # 只改 prompt，不传 first_frame
    await regenerate_clip("C2", new_prompt="new prompt 2", session_factory=session_factory)

    # 核心断言：原首帧被读出来并传给 generate_clip
    assert captured["first_frame_path"] == "http://orig/c2_first.png", \
        "改 30% 主张：first_frame_path 必须自动从 frame_assets fallback"


@pytest.mark.anyio
async def test_regenerate_no_existing_first_frame_logs_warning(session_factory, monkeypatch, tmp_path, caplog):
    """改 30%：frame_assets 没有原首帧时，generate_clip 用 None（重新文生图）+ 日志警告。"""
    await _seed_storyboard(session_factory)
    # 故意不灌 first_frame
    _patch_style(monkeypatch)

    captured = {}

    async def _fake_generate_clip(**kwargs):
        captured.update(kwargs)
        return VideoResult(url="http://new/v7.mp4", local_path=str(tmp_path / "v7.mp4"), model="kling-v1")

    monkeypatch.setattr("layers.L3_visual.regenerate.generate_clip", _fake_generate_clip)
    _patch_extract(monkeypatch, tmp_path)

    import logging
    with caplog.at_level(logging.WARNING):
        await regenerate_clip("C1", new_prompt="new prompt", session_factory=session_factory)

    assert captured["first_frame_path"] is None
    assert "no existing first_frame" in caplog.text


@pytest.mark.anyio
async def test_regenerate_explicit_first_frame_overrides_existing(session_factory, monkeypatch, tmp_path):
    """改 30%：用户显式传 new_first_frame_url 时，优先用入参（不查 frame_assets）。"""
    await _seed_storyboard(session_factory)
    await _seed_first_frame(session_factory, "C1", url="http://orig/should_not_use.png")
    _patch_style(monkeypatch)

    captured = {}

    async def _fake_generate_clip(**kwargs):
        captured.update(kwargs)
        return VideoResult(url="http://new/v8.mp4", local_path=str(tmp_path / "v8.mp4"), model="kling-v1")

    monkeypatch.setattr("layers.L3_visual.regenerate.generate_clip", _fake_generate_clip)
    _patch_extract(monkeypatch, tmp_path)

    await regenerate_clip(
        "C1",
        new_first_frame_url="http://user/uploaded.png",  # 用户上传的新首帧
        session_factory=session_factory,
    )

    # 用户传入优先，不使用 frame_assets 里的旧首帧
    assert captured["first_frame_path"] == "http://user/uploaded.png"
