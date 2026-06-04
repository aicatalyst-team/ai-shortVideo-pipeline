"""Sprint 3 lightweight memory maintenance.

This module extracts small, reviewable lessons from accumulated video metrics.
It never edits the handwritten memory section automatically. New AI-proposed
rules are sent to Feishu for human approval, then appended to the approved
section only after an explicit command.
"""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import get_settings
from core.parsers import parse_json_array
from integrations.llm_client import call_deepseek

log = logging.getLogger(__name__)

HANDWRITTEN_MARKER = "<!-- HANDWRITTEN_PERMANENT_END -->"
AI_MARKER = "<!-- AI_APPROVED_APPEND_ONLY -->"
MIN_VERTICAL_RECORDS = 8
MIN_GLOBAL_RECORDS = 30
MIN_DAYS_BETWEEN_RUNS = 5


@dataclass
class MemoryProposal:
    id: str
    style_name: str
    insight: str
    evidence: str
    prompt_rule: str
    confidence: float = 0.5


@dataclass
class DreamingResult:
    triggered: bool
    reason: str
    proposals: list[MemoryProposal] = field(default_factory=list)


def memory_path() -> Path:
    return Path(get_settings().data_dir).parent / "config" / "LONG_TERM_MEMORY.md"


def ensure_long_term_memory(path: Path | None = None) -> Path:
    path = path or memory_path()
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# myAiVideos Long-Term Memory\n\n"
        "## Handwritten Permanent Rules\n\n"
        "1. 解说类短视频优先做图文混剪，不追求复杂电影叙事。\n"
        "2. 前 3 秒必须给出冲突、悬念、数字或强情绪，不铺垫背景。\n"
        "3. 每条视频只讲一个核心观点，避免在 30 秒内塞多个主题。\n"
        "4. 热搜解说要先交代为什么值得看，再解释发生了什么。\n"
        "5. 知识科普要用生活例子开场，再给结论和解释。\n"
        "6. 情感故事要少讲大道理，多给具体场景和细节。\n"
        "7. 奇闻趣事要保留悬念，但不能牺牲事实清晰度。\n"
        "8. 社会观察要敢于提出判断，但避免空泛站队。\n"
        "9. 字幕必须服务信息节奏，不要遮挡主体和关键画面。\n"
        "10. 任何自动提炼的规律都必须先过人工审核，再进入生成 prompt。\n\n"
        f"{HANDWRITTEN_MARKER}\n\n"
        "## AI Approved Append-Only Rules\n\n"
        f"{AI_MARKER}\n",
        encoding="utf-8",
    )
    return path


def read_generation_memory(max_chars: int = 1800) -> str:
    path = ensure_long_term_memory()
    text = path.read_text(encoding="utf-8")
    return text[:max_chars]


async def _load_metric_summary(session: AsyncSession) -> tuple[int, list[dict]]:
    from db.models import VideoMetric, VideoRecord

    total_stmt = select(func.count(VideoRecord.id))
    total = int((await session.execute(total_stmt)).scalar() or 0)
    stmt = (
        select(
            VideoRecord.style_name,
            func.count(VideoRecord.id).label("videos"),
            func.avg(VideoMetric.completion_rate).label("avg_completion"),
            func.avg(VideoMetric.engagement_rate).label("avg_engagement"),
            func.avg(VideoMetric.views).label("avg_views"),
        )
        .join(VideoMetric, VideoMetric.video_id == VideoRecord.id)
        .group_by(VideoRecord.style_name)
    )
    rows = (await session.execute(stmt)).all()
    summary = [
        {
            "style_name": row.style_name or "unknown",
            "videos": int(row.videos or 0),
            "avg_completion": float(row.avg_completion or 0),
            "avg_engagement": float(row.avg_engagement or 0),
            "avg_views": float(row.avg_views or 0),
        }
        for row in rows
    ]
    return total, summary


async def propose_memory_updates(
    session: AsyncSession,
    *,
    force: bool = False,
    now: datetime | None = None,
) -> DreamingResult:
    now = now or datetime.now(timezone.utc)
    total, summary = await _load_metric_summary(session)
    eligible = [item for item in summary if item["videos"] >= MIN_VERTICAL_RECORDS]

    if not force:
        if total < MIN_GLOBAL_RECORDS:
            return DreamingResult(False, f"样本不足：全局 {total}/{MIN_GLOBAL_RECORDS}")
        if not eligible:
            return DreamingResult(False, f"样本不足：没有垂类达到 {MIN_VERTICAL_RECORDS} 条")

    if not summary:
        return DreamingResult(False, "暂无视频表现数据")

    system = (
        "你是短视频运营复盘助手。基于统计数据，提炼最多 3 条可执行规律。"
        "必须保守，不要编造具体案例。输出 JSON 数组，每条包含："
        "style_name, insight, evidence, prompt_rule, confidence。"
    )
    user = "表现统计：\n" + json.dumps(summary, ensure_ascii=False, indent=2)
    raw = await call_deepseek(system, user, temperature=0.3)
    items = parse_json_array(raw)
    proposals: list[MemoryProposal] = []
    for item in items[:3]:
        if not isinstance(item, dict):
            continue
        insight = str(item.get("insight", "")).strip()
        prompt_rule = str(item.get("prompt_rule", "")).strip()
        if not insight or not prompt_rule:
            continue
        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        proposals.append(
            MemoryProposal(
                id=uuid.uuid4().hex[:8].upper(),
                style_name=str(item.get("style_name", "global")).strip() or "global",
                insight=insight,
                evidence=str(item.get("evidence", "")).strip(),
                prompt_rule=prompt_rule,
                confidence=max(0.0, min(1.0, confidence)),
            )
        )

    if not proposals:
        return DreamingResult(False, "模型未提炼出可用规律")
    return DreamingResult(True, "已生成待审核记忆提案", proposals)


def format_memory_proposals(proposals: list[MemoryProposal]) -> str:
    lines = ["记忆提炼待审核："]
    for idx, item in enumerate(proposals, start=1):
        lines.append(
            f"{idx}. [{item.id}] {item.style_name} 置信度 {item.confidence:.2f}\n"
            f"   规律：{item.insight}\n"
            f"   证据：{item.evidence or '无'}\n"
            f"   注入：{item.prompt_rule}"
        )
    lines.append("\n通过：记忆通过 <ID>；丢弃：不回复即可。")
    return "\n".join(lines)


def append_approved_memory(proposal: MemoryProposal, path: Path | None = None) -> None:
    path = ensure_long_term_memory(path)
    text = path.read_text(encoding="utf-8")
    if AI_MARKER not in text:
        text = text.rstrip() + f"\n\n## AI Approved Append-Only Rules\n\n{AI_MARKER}\n"
    entry = (
        f"\n- {datetime.now(timezone.utc).date()} [{proposal.style_name}] "
        f"{proposal.prompt_rule} "
        f"(evidence: {proposal.evidence or proposal.insight}; confidence={proposal.confidence:.2f})"
    )
    path.write_text(text.rstrip() + entry + "\n", encoding="utf-8")
