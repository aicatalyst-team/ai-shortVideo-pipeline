"""Phase P P10 单测：画布节点 7 类数据 + cost_summary + dirty 传播消息。"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from layers.L2_creative.canvas_node_service import (
    ClipNodeData,
    CostSummary,
    build_clip_node_data,
    build_cost_summary,
    build_dirty_propagation_message,
    compute_blocking_for,
    compute_depends_on,
)


@dataclass
class FakeClip:
    """模拟 Clip ORM 实例，避开真 DB。"""

    id: str = "C001"
    seq: int = 1
    prompt: str = "test prompt"
    kling_prompt: str = "test kling prompt"
    narration_segment: str = "测试旁白"
    duration_sec: int = 5
    duration_ms: int = 5040
    video_url: str = "https://example.com/v.mp4"
    status: str = "pending"
    cost_cny: float = 0.61
    first_frame_url: str = ""
    tail_frame_url: str = ""
    cost_breakdown: dict | None = None
    regen_count: int = 0
    dirty_reason: str = ""
    blocking_for: list | None = None
    depends_on: list | None = None
    r_metadata: dict | None = None


@dataclass
class FakeFrame:
    clip_id: str
    kind: str
    url: str
    width: int = 720
    height: int = 1280


# ── 7 类数据组 ──────────────────────────────────────────────────


def test_build_clip_node_basic_pending_clip():
    clip = FakeClip()
    node = build_clip_node_data(clip)
    assert isinstance(node, ClipNodeData)
    assert node.clip_id == "C001"
    assert node.seq == 1
    assert node.preview.video_url == "https://example.com/v.mp4"
    assert node.review.status == "pending"
    assert node.ops.can_continue is True
    assert node.ops.can_regenerate is True


def test_build_clip_node_with_p10_first_tail_urls_takes_priority_over_frame_assets():
    clip = FakeClip(first_frame_url="p10/first.png", tail_frame_url="p10/tail.png")
    frames = [
        FakeFrame(clip_id="C001", kind="first", url="frame_asset/first.png"),
        FakeFrame(clip_id="C001", kind="tail", url="frame_asset/tail.png"),
    ]
    node = build_clip_node_data(clip, frame_assets=frames)
    assert node.preview.first_frame_url == "p10/first.png"
    assert node.preview.tail_frame_url == "p10/tail.png"


def test_build_clip_node_falls_back_to_frame_assets_when_p10_fields_empty():
    clip = FakeClip()  # first_frame_url="" tail_frame_url=""
    frames = [
        FakeFrame(clip_id="C001", kind="first", url="frame_asset/first.png"),
        FakeFrame(clip_id="C001", kind="tail", url="frame_asset/tail.png"),
    ]
    node = build_clip_node_data(clip, frame_assets=frames)
    assert node.preview.first_frame_url == "frame_asset/first.png"
    assert node.preview.tail_frame_url == "frame_asset/tail.png"


def test_build_clip_node_timeline_computes_drift_correctly():
    # duration_ms=10000 (10s), narration 35 字 → est_tts ≈ 35/7.5 = 4.67s
    clip = FakeClip(duration_sec=10, duration_ms=10000, narration_segment="一" * 35)
    node = build_clip_node_data(clip)
    assert node.timeline.target_video_sec == 10
    assert node.timeline.actual_video_sec == 10.0
    # est_tts 来自 visual_planner.estimate_narration_audio_sec
    assert node.timeline.est_tts_sec == round(35 / 7.5, 2)
    assert node.timeline.drift_sec == round(10.0 - 35 / 7.5, 2)


def test_build_clip_node_drift_uses_r_metadata_est_audio_when_available():
    clip = FakeClip(r_metadata={"est_audio_sec": 4.27}, narration_segment="a" * 100)
    node = build_clip_node_data(clip)
    # 优先用 r_metadata，不重新算
    assert node.timeline.est_tts_sec == 4.27


def test_build_clip_node_review_includes_status_and_dirty_reason():
    clip = FakeClip(status="dirty", dirty_reason="人物近 + 不要文字", regen_count=2)
    node = build_clip_node_data(clip)
    assert node.review.status == "dirty"
    assert node.review.dirty_reason == "人物近 + 不要文字"
    assert node.review.regen_count == 2


def test_build_clip_node_review_includes_last_hints_from_r_metadata():
    clip = FakeClip(r_metadata={"last_hints": ["closer_shot", "no_text"]})
    node = build_clip_node_data(clip)
    assert node.review.last_hints == ["closer_shot", "no_text"]


def test_build_clip_node_ops_locked_status_disables_some_buttons():
    clip = FakeClip(status="locked")
    node = build_clip_node_data(clip)
    assert node.ops.can_continue is False
    assert node.ops.can_regenerate is True   # locked 仍可重生（强制重做）
    assert node.ops.can_replace_first_frame is False
    assert node.ops.can_replace_tail_frame is False
    assert node.ops.can_edit_prompt is False
    assert node.ops.can_cancel is True


def test_build_clip_node_ops_cancelled_disables_continue():
    clip = FakeClip(status="cancelled")
    node = build_clip_node_data(clip)
    assert node.ops.can_continue is False
    assert node.ops.can_regenerate is True
    assert node.ops.can_cancel is False


def test_build_clip_node_cost_extracts_breakdown_and_regen_total():
    clip = FakeClip(
        cost_cny=0.61,
        cost_breakdown={"video": 0.5, "first_frame": 0.1, "tts": 0.01, "regen_total": 1.22},
        regen_count=2,
    )
    node = build_clip_node_data(clip)
    assert node.cost.clip_cny == 0.61
    assert node.cost.regen_count == 2
    assert node.cost.regen_total_cny == 1.22
    assert "regen_total" not in node.cost.cost_breakdown
    assert node.cost.cost_breakdown == {"video": 0.5, "first_frame": 0.1, "tts": 0.01}


def test_build_clip_node_cost_risk_warning_for_high_cost():
    clip = FakeClip(cost_cny=2.5)
    node = build_clip_node_data(clip)
    assert "偏高" in node.cost.risk_warning


def test_build_clip_node_dependencies():
    clip = FakeClip(seq=3, depends_on=[2], blocking_for=[4, 5])
    node = build_clip_node_data(clip)
    assert node.dependencies.depends_on == [2]
    assert node.dependencies.blocking_for == [4, 5]
    assert node.dependencies.chain_from_tail is True


def test_build_clip_node_no_dependencies_means_no_chain():
    clip = FakeClip(seq=1, depends_on=None, blocking_for=None)
    node = build_clip_node_data(clip)
    assert node.dependencies.depends_on == []
    assert node.dependencies.blocking_for == []
    assert node.dependencies.chain_from_tail is False


def test_build_clip_node_includes_character_environment_from_r_metadata():
    clip = FakeClip(r_metadata={"character_id": "su_wan", "environment_id": "coffee_shop"})
    node = build_clip_node_data(clip)
    assert node.text.character_id == "su_wan"
    assert node.text.environment_id == "coffee_shop"


# ── CostSummary ─────────────────────────────────────────────────


def test_cost_summary_empty_clips():
    summary = build_cost_summary([])
    assert summary.clip_count == 0
    assert summary.session_total_cny == 0.0


def test_cost_summary_aggregates_all_clips():
    clips = [
        FakeClip(id="C1", seq=1, cost_cny=0.6, status="done"),
        FakeClip(id="C2", seq=2, cost_cny=0.7, status="done"),
        FakeClip(id="C3", seq=3, cost_cny=0.0, status="pending"),
    ]
    summary = build_cost_summary(clips)
    assert summary.clip_count == 3
    assert summary.session_total_cny == 1.3
    assert summary.est_remaining_cny == 0.6  # 1 pending × 0.6
    assert summary.cost_per_clip_avg == round(1.3 / 3, 2)


def test_cost_summary_warns_when_total_above_threshold():
    clips = [FakeClip(id=f"C{i}", seq=i, cost_cny=1.2, status="done") for i in range(1, 10)]
    summary = build_cost_summary(clips)
    # 9 × 1.2 = 10.8 > 10
    assert summary.session_total_cny == 10.8
    assert any("超" in w for w in summary.warnings)


def test_cost_summary_warns_when_regen_ratio_high():
    clips = [
        FakeClip(id="C1", seq=1, cost_cny=1.0, cost_breakdown={"regen_total": 0.8}, status="done"),
    ]
    summary = build_cost_summary(clips)
    assert summary.regen_total_cny == 0.8
    # 0.8 / 1.0 = 80% > 50%
    assert any("重生成成本占比" in w for w in summary.warnings)


def test_cost_summary_feishu_format():
    clips = [FakeClip(id="C1", seq=1, cost_cny=0.6, status="done")]
    summary = build_cost_summary(clips)
    line = summary.to_feishu_line()
    assert "💰" in line
    assert "0.6" in line
    assert "1 段" in line


# ── dirty 传播消息 ──────────────────────────────────────────────


def test_dirty_propagation_middle_clip_cascades_to_tail():
    msg, affected = build_dirty_propagation_message(triggered_seq=3, total_clips=5)
    assert "clip 3" in msg
    assert "4/5" in msg
    assert "依赖" in msg
    assert affected == [4, 5]


def test_dirty_propagation_last_clip_no_cascade():
    msg, affected = build_dirty_propagation_message(triggered_seq=5, total_clips=5)
    assert "无下游" in msg
    assert affected == []


def test_dirty_propagation_chain_disabled_no_cascade():
    msg, affected = build_dirty_propagation_message(triggered_seq=2, total_clips=5, chain_frames=False)
    assert "无下游" in msg
    assert affected == []


def test_compute_blocking_for_middle():
    assert compute_blocking_for(2, 5) == [3, 4, 5]


def test_compute_blocking_for_last():
    assert compute_blocking_for(5, 5) == []


def test_compute_blocking_for_chain_disabled():
    assert compute_blocking_for(2, 5, chain_frames=False) == []


def test_compute_depends_on_middle():
    assert compute_depends_on(3) == [2]


def test_compute_depends_on_first():
    assert compute_depends_on(1) == []


def test_compute_depends_on_chain_disabled():
    assert compute_depends_on(3, chain_frames=False) == []
