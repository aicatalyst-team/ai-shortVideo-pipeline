"""
Phase 3 — ORM-backed state manager, replacing memory.py.

Preserves the same public interface so webhooks.py continues to work.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Feedback, OperatorStats, Plan, StyleProfile

PLAN_STATUS: dict[str, str] = {
    "scripted":         "✍️ 脚本完成",
    "pending_confirm":  "⏳ 等待你确认（费用/时长已评估）",
    "confirmed":        "✅ 已确认，提示词生成中",
    "prompted":         "🎨 提示词完成",
    "generating":       "🎬 可灵生成中",
    "video_done":       "✅ 视频完成",
    "captioned":        "💬 字幕叠加",
    "ready_to_publish": "📦 待发布",
    "published":        "📱 已发布",
    "dropped":          "🗑️ 已废弃",
}


class StateManager:
    """Async ORM state manager — drop-in replacement for MemoryManager."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Plan management ───────────────────────────────────────────────────────

    async def create_plan(self, mode: str, theme: str, reference: str = "", style_name: str = "") -> Plan:
        plan = Plan(
            id=uuid.uuid4().hex[:6].upper(),
            mode=mode,
            theme=theme,
            reference=reference[:500],
            style_name=style_name,
            status="scripted",
        )
        self.session.add(plan)
        await self.session.flush()
        return plan

    async def update_plan_status(self, plan_id: str, status: str, extra: str = "") -> bool:
        plan = await self.session.get(Plan, plan_id)
        if not plan:
            return False
        plan.status = status
        plan.updated_at = datetime.now()
        if extra:
            plan.notes = extra
        if status in ("published", "dropped"):
            plan.archived = True
        await self.session.flush()
        return True

    async def save_scripts(self, plan_id: str, scripts: str, prompts: str = "") -> None:
        plan = await self.session.get(Plan, plan_id)
        if not plan:
            return
        plan.scripts = scripts[:3000]
        if prompts:
            plan.prompts = prompts[:3000]
            plan.status = "prompted"
        plan.updated_at = datetime.now()
        await self.session.flush()

    async def save_evaluation(self, plan_id: str, scripts: str, evaluation: dict) -> None:
        plan = await self.session.get(Plan, plan_id)
        if not plan:
            return
        plan.scripts = scripts[:3000]
        plan.evaluation = evaluation
        plan.status = "pending_confirm"
        plan.updated_at = datetime.now()
        await self.session.flush()

    async def save_parsed_scripts(self, plan_id: str, scripts: list[dict]) -> None:
        plan = await self.session.get(Plan, plan_id)
        if not plan:
            return
        plan.parsed_scripts = scripts
        await self.session.flush()

    async def save_operation(self, plan_id: str, operation_raw: str, operation_list: list[dict]) -> None:
        plan = await self.session.get(Plan, plan_id)
        if not plan:
            return
        plan.operation_raw = operation_raw[:3000]
        plan.operation_list = operation_list
        await self.session.flush()

    async def get_pending_plan(self, plan_id: Optional[str] = None) -> Optional[Plan]:
        if plan_id:
            plan = await self.session.get(Plan, plan_id)
            return plan if plan and plan.status == "pending_confirm" else None
        stmt = (
            select(Plan)
            .where(Plan.status == "pending_confirm", Plan.archived == False)
            .order_by(Plan.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_script_by_choice(self, plan_id: Optional[str], choice: str) -> tuple[Optional[dict], Optional[dict]]:
        if plan_id:
            plan = await self.session.get(Plan, plan_id)
            if not plan or not plan.parsed_scripts:
                return None, None
        else:
            stmt = (
                select(Plan)
                .where(Plan.parsed_scripts.isnot(None), Plan.archived == False)
                .order_by(Plan.created_at.desc())
                .limit(1)
            )
            result = await self.session.execute(stmt)
            plan = result.scalar_one_or_none()
            if not plan:
                return None, None

        scripts = plan.parsed_scripts
        eval_plans = (plan.evaluation or {}).get("plans", [])

        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(scripts):
                eval_plan = eval_plans[idx] if idx < len(eval_plans) else {}
                return scripts[idx], eval_plan
        else:
            for i, s in enumerate(scripts):
                if choice in s.get("operator", ""):
                    eval_plan = eval_plans[i] if i < len(eval_plans) else {}
                    return s, eval_plan

        return None, None

    async def get_operation_entry(self, plan_id: Optional[str], operator: str, index: int = 0) -> dict:
        if plan_id:
            plan = await self.session.get(Plan, plan_id)
            plans = [plan] if plan else []
        else:
            stmt = (
                select(Plan)
                .where(Plan.operation_list.isnot(None), Plan.archived == False)
                .order_by(Plan.created_at.desc())
                .limit(5)
            )
            result = await self.session.execute(stmt)
            plans = list(result.scalars().all())

        for p in plans:
            ops = p.operation_list or []
            if not ops:
                continue
            for entry in ops:
                if operator and operator in str(entry.get("operator", "")):
                    return entry
            if 0 <= index < len(ops):
                return ops[index]
        return {}

    async def get_active_plans_text(self) -> str:
        stmt = (
            select(Plan)
            .where(Plan.archived == False)
            .order_by(Plan.created_at.desc())
            .limit(20)
        )
        result = await self.session.execute(stmt)
        plans = list(result.scalars().all())

        if not plans:
            return "当前没有进行中的计划。"

        lines = ["📋 进行中的视频计划：\n"]
        for p in plans:
            label = PLAN_STATUS.get(p.status, p.status)
            lines.append(
                f"[{p.id}] {label}\n"
                f"  模式：{p.mode} | 主题：{p.theme}\n"
                f"  创建：{p.created_at:%Y-%m-%d %H:%M} | 更新：{p.updated_at:%Y-%m-%d %H:%M}\n"
                + (f"  备注：{p.notes}\n" if p.notes else "")
            )
        return "\n".join(lines)

    # ── Feedback ──────────────────────────────────────────────────────────────

    async def add_feedback(
        self,
        positive: bool,
        comment: str = "",
        plan_id: Optional[str] = None,
        operators: Optional[list[str]] = None,
    ) -> str:
        fb = Feedback(
            plan_id=plan_id,
            positive=positive,
            comment=comment,
            operators=operators or [],
        )
        self.session.add(fb)

        for op_name in (operators or []):
            stmt = select(OperatorStats).where(OperatorStats.name == op_name)
            result = await self.session.execute(stmt)
            stat = result.scalar_one_or_none()
            if stat:
                if positive:
                    stat.approved += 1
                else:
                    stat.rejected += 1
            else:
                self.session.add(OperatorStats(
                    name=op_name,
                    approved=1 if positive else 0,
                    rejected=0 if positive else 1,
                ))

        if not positive and comment:
            await self._add_avoid(comment)

        await self.session.flush()
        emoji = "✅" if positive else "📝"
        return f"{emoji} 反馈已记录{'，已加入「不要做」列表' if not positive and comment else ''}"

    async def _add_avoid(self, pattern: str) -> None:
        stmt = select(StyleProfile).where(StyleProfile.key == "default")
        result = await self.session.execute(stmt)
        profile = result.scalar_one_or_none()
        if profile:
            avoid = profile.avoid or []
            if pattern not in avoid:
                avoid.append(pattern)
                profile.avoid = avoid
        await self.session.flush()

    # ── Style profile ─────────────────────────────────────────────────────────

    async def get_style_context(self) -> str:
        stmt = select(StyleProfile).where(StyleProfile.key == "default")
        result = await self.session.execute(stmt)
        profile = result.scalar_one_or_none()
        if not profile:
            return ""

        stats_stmt = select(OperatorStats).order_by(
            (OperatorStats.approved - OperatorStats.rejected).desc()
        )
        stats_result = await self.session.execute(stats_stmt)
        all_stats = list(stats_result.scalars().all())

        top = [s.name for s in all_stats if s.approved > 0][:3]
        avoid_ops = [s.name for s in all_stats if s.rejected > s.approved and s.rejected > 0]

        lines = [
            "=== 风格档案（必须遵守）===",
            f"核心概念：{profile.core_concept}",
            f"视觉风格：{profile.visual_style}",
            f"字幕风格：{profile.caption_style}",
            f"开场规则：{profile.hook_rule}",
            f"规格：{profile.video_spec}",
        ]
        if profile.avoid:
            lines.append(f"⚠️ 用户明确不要：{'、'.join(profile.avoid)}")
        if profile.user_notes:
            lines.append(f"📝 用户备注：{profile.user_notes}")
        if top:
            lines.append(f"✅ 表现好的干员（优先使用）：{'、'.join(top)}")
        if avoid_ops:
            lines.append(f"❌ 表现差的干员（尽量避免）：{'、'.join(avoid_ops)}")
        lines.append("=== 风格档案结束 ===")
        return "\n".join(lines)
