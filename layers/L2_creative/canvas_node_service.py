"""Phase P Sprint P10：画布节点完整数据组 + cost_summary + dirty 传播消息。

为 Phase F 前端铺垫：每个 clip 节点必含的 7 类数据 + 整 storyboard 的成本汇总 +
dirty 传播的可解释消息（不光"标 dirty"，要说清"为什么"）。

不持久化任何额外字段（migration 010 已把 clips 表补齐）；本模块只组装数据 + 算成本。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# 与 enriched_clips dict / Clip ORM 的状态枚举（沿用 P4 + P8 既有命名）
ClipStatus = str  # "pending" | "in_progress" | "waiting_review" | "locked" | "dirty" | "cancelled" | "failed" | "done"

# 文案模板
_DIRTY_CASCADE_TEMPLATE = (
    "clip {triggered} 重生成 → clip {affected_str} 标 dirty，"
    "因为它们的首帧依赖 clip {triggered} 尾帧（chain_frames=True 链式生成）。"
)
_DIRTY_NO_CASCADE_TEMPLATE = (
    "clip {triggered} 重生成，无下游 clip 受影响（已是末段或链式断裂）。"
)


# ── 7 类画布节点数据组 ──────────────────────────────────────────


class ClipNodePreview(BaseModel):
    """画面预览组（首帧/视频/尾帧 URL）。"""

    first_frame_url: str = ""
    video_url: str = ""
    tail_frame_url: str = ""


class ClipNodeText(BaseModel):
    """文本上下文组。"""

    narration_segment: str = ""
    visual_prompt: str = ""
    kling_prompt: str = ""
    character_id: str | None = None
    environment_id: str | None = None


class ClipNodeTimeline(BaseModel):
    """时间轴信息组。"""

    target_video_sec: int = 0
    actual_video_sec: float = 0.0  # ffprobe 探出来的；不一定 = target
    est_tts_sec: float = 0.0       # P3 visual_planner 估算
    drift_sec: float = 0.0         # actual_video_sec - est_tts_sec（正=视频长）


class ClipNodeReview(BaseModel):
    """审核状态组。"""

    status: ClipStatus = "pending"
    regen_count: int = 0
    locked_at: str | None = None
    dirty_reason: str = ""
    last_hints: list[str] = Field(default_factory=list)


class ClipNodeOps(BaseModel):
    """操作入口组（FE 渲染按钮用）。"""

    can_continue: bool = True
    can_regenerate: bool = True
    can_replace_first_frame: bool = True
    can_replace_tail_frame: bool = True
    can_edit_prompt: bool = True
    can_cancel: bool = True


class ClipNodeCost(BaseModel):
    """单段成本组。"""

    clip_cny: float = 0.0
    regen_count: int = 0
    regen_total_cny: float = 0.0  # 历次重生成总成本（不含当前最新一次）
    cost_breakdown: dict[str, float] = Field(default_factory=dict)  # {"video": 0.5, "first_frame": 0.1, "tts": 0.01}
    risk_warning: str = ""  # "成本已超阈值" 等


class ClipNodeDependencies(BaseModel):
    """依赖关系组（dirty 传播图）。"""

    depends_on: list[int] = Field(default_factory=list)   # 上游 clip_seq 列表
    blocking_for: list[int] = Field(default_factory=list)  # 当前 clip 重生成会让哪些下游标 dirty
    chain_from_tail: bool = False  # 是否从前一段尾帧链式继承首帧


class ClipNodeData(BaseModel):
    """单个 clip 节点的完整 7 类数据组（Phase F 画布渲染输入）。"""

    clip_id: str
    seq: int
    preview: ClipNodePreview
    text: ClipNodeText
    timeline: ClipNodeTimeline
    review: ClipNodeReview
    ops: ClipNodeOps
    cost: ClipNodeCost
    dependencies: ClipNodeDependencies


# ── 整 storyboard 的成本汇总 ─────────────────────────────────────


class CostSummary(BaseModel):
    """整 storyboard 的成本汇总（顶栏显示）。"""

    clip_count: int = 0
    session_total_cny: float = 0.0      # 所有 clip 当前一次成本之和
    regen_total_cny: float = 0.0        # 所有 clip 重生成累计成本
    est_remaining_cny: float = 0.0      # 未生成 clip 的预估成本
    cost_per_clip_avg: float = 0.0
    warnings: list[str] = Field(default_factory=list)

    def to_feishu_line(self) -> str:
        return (
            f"💰 累计 ¥{self.session_total_cny:.2f}（{self.clip_count} 段）"
            f" · 重生成 ¥{self.regen_total_cny:.2f}"
            f" · 预计继续 ¥{self.est_remaining_cny:.2f}"
        )


# ── 构造器 ───────────────────────────────────────────────────────


def _safe_str(v: Any, default: str = "") -> str:
    """防御性 string 提取：非 str 类型（如 MagicMock）一律返回 default。"""
    return v if isinstance(v, str) else default


def _safe_dict(v: Any) -> dict:
    return v if isinstance(v, dict) else {}


def _safe_list(v: Any) -> list:
    return v if isinstance(v, list) else []


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def build_clip_node_data(clip_orm: Any, *, frame_assets: list | None = None) -> ClipNodeData:
    """从 Clip ORM 行 + 可选 FrameAsset 列表构造 ClipNodeData。

    参数：
      clip_orm: db.models.Clip 实例（含 P10 新增字段）
      frame_assets: 可选 FrameAsset 列表，用于补 first/tail URL 兜底
    """
    # 优先用 P10 新字段；fallback 到 frame_assets
    first_url = _safe_str(getattr(clip_orm, "first_frame_url", ""))
    tail_url = _safe_str(getattr(clip_orm, "tail_frame_url", ""))
    if not first_url and frame_assets:
        first_url = _pick_frame_url(frame_assets, clip_orm.id, kind="first")
    if not tail_url and frame_assets:
        tail_url = _pick_frame_url(frame_assets, clip_orm.id, kind="tail")

    # 时间轴：actual_video_sec 用 duration_ms（如果存在）/1000，否则用 duration_sec
    target = _safe_int(getattr(clip_orm, "duration_sec", 0))
    actual = _safe_float(getattr(clip_orm, "duration_ms", 0)) / 1000.0
    if actual <= 0:
        actual = float(target)
    # est_tts 来自 r_metadata 或重新算
    r_meta = _safe_dict(getattr(clip_orm, "r_metadata", None))
    narration = _safe_str(getattr(clip_orm, "narration_segment", ""))
    est_tts = _safe_float(r_meta.get("est_audio_sec", 0))
    if est_tts <= 0 and narration:
        from layers.L4_audio.visual_planner import estimate_narration_audio_sec
        est_tts = estimate_narration_audio_sec(narration)

    cost_breakdown = _safe_dict(getattr(clip_orm, "cost_breakdown", None))
    blocking_for = _safe_list(getattr(clip_orm, "blocking_for", None))
    depends_on = _safe_list(getattr(clip_orm, "depends_on", None))
    status = _safe_str(getattr(clip_orm, "status", "pending"), default="pending") or "pending"

    return ClipNodeData(
        clip_id=_safe_str(getattr(clip_orm, "id", ""), default="UNKNOWN"),
        seq=_safe_int(getattr(clip_orm, "seq", 0)),
        preview=ClipNodePreview(
            first_frame_url=first_url,
            video_url=_safe_str(getattr(clip_orm, "video_url", "")),
            tail_frame_url=tail_url,
        ),
        text=ClipNodeText(
            narration_segment=narration,
            visual_prompt=_safe_str(getattr(clip_orm, "prompt", "")),
            kling_prompt=_safe_str(getattr(clip_orm, "kling_prompt", "")),
            character_id=r_meta.get("character_id") if isinstance(r_meta.get("character_id"), str) else None,
            environment_id=r_meta.get("environment_id") if isinstance(r_meta.get("environment_id"), str) else None,
        ),
        timeline=ClipNodeTimeline(
            target_video_sec=target,
            actual_video_sec=round(actual, 2),
            est_tts_sec=round(est_tts, 2),
            drift_sec=round(actual - est_tts, 2),
        ),
        review=ClipNodeReview(
            status=status,
            regen_count=_safe_int(getattr(clip_orm, "regen_count", 0)),
            dirty_reason=_safe_str(getattr(clip_orm, "dirty_reason", "")),
            last_hints=[h for h in (r_meta.get("last_hints") or []) if isinstance(h, str)],
        ),
        ops=_default_ops_for_status(status),
        cost=ClipNodeCost(
            clip_cny=_safe_float(getattr(clip_orm, "cost_cny", 0)),
            regen_count=_safe_int(getattr(clip_orm, "regen_count", 0)),
            regen_total_cny=_safe_float(cost_breakdown.get("regen_total", 0)),
            cost_breakdown={k: _safe_float(v) for k, v in cost_breakdown.items() if k != "regen_total"},
            risk_warning=_cost_risk_warning(_safe_float(getattr(clip_orm, "cost_cny", 0))),
        ),
        dependencies=ClipNodeDependencies(
            depends_on=[int(x) for x in depends_on if isinstance(x, (int, float)) or (isinstance(x, str) and x.isdigit())],
            blocking_for=[int(x) for x in blocking_for if isinstance(x, (int, float)) or (isinstance(x, str) and x.isdigit())],
            chain_from_tail=bool(depends_on),
        ),
    )


def build_cost_summary(clips: list[Any], *, est_per_pending_clip_cny: float = 0.6) -> CostSummary:
    """统计 storyboard 整体成本。

    参数：
      clips: list[Clip ORM]（任意状态都接受）
      est_per_pending_clip_cny: pending 状态 clip 的预计成本（用于 est_remaining）
    """
    if not clips:
        return CostSummary()

    total = 0.0
    regen_total = 0.0
    pending_count = 0
    warnings: list[str] = []

    for c in clips:
        cost = _safe_float(getattr(c, "cost_cny", 0))
        total += cost
        breakdown = _safe_dict(getattr(c, "cost_breakdown", None))
        regen_total += _safe_float(breakdown.get("regen_total", 0))
        status = _safe_str(getattr(c, "status", "pending"), default="pending") or "pending"
        if status in ("pending", "dirty"):
            pending_count += 1

    est_remaining = pending_count * est_per_pending_clip_cny

    if total > 10.0:
        warnings.append(f"本视频累计成本 ¥{total:.2f} 已超 ¥10 阈值")
    if regen_total > total * 0.5 and total > 0:
        warnings.append(f"重生成成本占比 {regen_total / total * 100:.0f}% > 50%，考虑接受当前结果")

    avg = total / len(clips) if clips else 0.0
    return CostSummary(
        clip_count=len(clips),
        session_total_cny=round(total, 2),
        regen_total_cny=round(regen_total, 2),
        est_remaining_cny=round(est_remaining, 2),
        cost_per_clip_avg=round(avg, 2),
        warnings=warnings,
    )


def build_dirty_propagation_message(
    triggered_seq: int,
    total_clips: int,
    *,
    chain_frames: bool = True,
) -> tuple[str, list[int]]:
    """构造 dirty 传播的可解释消息。

    返回 (message, affected_seq_list)：
      - chain_frames=True 且非末段：affected = [triggered+1, ..., total]
      - 末段或不链式：affected = []
    """
    if not chain_frames or triggered_seq >= total_clips:
        return _DIRTY_NO_CASCADE_TEMPLATE.format(triggered=triggered_seq), []

    affected = list(range(triggered_seq + 1, total_clips + 1))
    affected_str = "/".join(str(x) for x in affected)
    msg = _DIRTY_CASCADE_TEMPLATE.format(triggered=triggered_seq, affected_str=affected_str)
    return msg, affected


def compute_blocking_for(clip_seq: int, total_clips: int, *, chain_frames: bool = True) -> list[int]:
    """计算当前 clip 重生成会影响的下游 clip seq 列表。

    末段返回 []。
    """
    if not chain_frames or clip_seq >= total_clips:
        return []
    return list(range(clip_seq + 1, total_clips + 1))


def compute_depends_on(clip_seq: int, *, chain_frames: bool = True) -> list[int]:
    """计算当前 clip 依赖的上游 clip seq（链式生成时 = [seq-1]）。"""
    if not chain_frames or clip_seq <= 1:
        return []
    return [clip_seq - 1]


# ── 私有 helpers ────────────────────────────────────────────────


def _pick_frame_url(frame_assets: list, clip_id: str, *, kind: str) -> str:
    """从 frame_assets 列表里找指定 clip + kind 的 URL。"""
    for fa in frame_assets:
        if getattr(fa, "clip_id", None) == clip_id and getattr(fa, "kind", "") == kind:
            return getattr(fa, "url", "") or ""
    return ""


def _default_ops_for_status(status: str) -> ClipNodeOps:
    """根据 clip 状态决定哪些操作按钮可用。"""
    if status == "locked":
        return ClipNodeOps(
            can_continue=False,
            can_regenerate=True,
            can_replace_first_frame=False,
            can_replace_tail_frame=False,
            can_edit_prompt=False,
            can_cancel=True,
        )
    if status in ("cancelled", "failed"):
        return ClipNodeOps(
            can_continue=False,
            can_regenerate=True,
            can_replace_first_frame=False,
            can_replace_tail_frame=False,
            can_edit_prompt=True,
            can_cancel=False,
        )
    # pending / in_progress / waiting_review / dirty / done 等
    return ClipNodeOps()  # 全部 True 默认


def _cost_risk_warning(clip_cny: float) -> str:
    """单段成本风险提示。"""
    if clip_cny > 2.0:
        return f"本段成本 ¥{clip_cny:.2f} 偏高（可灵 pro 模式或重生成多次）"
    return ""
