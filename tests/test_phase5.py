"""Phase 5 集成测试：算法博弈层（Hook + 节奏 + 质量关卡 + 首评）"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VERTICALS = [
    "hot_news_commentary",
    "knowledge_explainer",
    "emotional_story",
    "curiosity_facts",
    "social_insight",
]

SAMPLE_NARRATION = (
    "你知道为什么中国有 14 亿人，但真正实现财务自由的不到 0.1% 吗？"
    "今天我们来聊一个让很多人不舒服的真相。"
    "大多数人从小被告诉要努力读书、好好工作。"
    "但没有人告诉你，努力工作和财富积累之间，其实有一条巨大的鸿沟。"
    "这条鸿沟叫做——资产思维。"
    "普通人用时间换钱，有钱人用钱生钱。"
    "当你明白这个逻辑，你会重新审视自己每天在做什么。"
)


# ── hook_engine ──

class TestHookEngine:
    def test_module_imports(self):
        from layers.L2_creative.hook_engine import (
            generate_hook_variants, format_hook_variants,
            HOOK_TYPES, HOOK_EXAMPLES, VERTICAL_HOOK_PRIORITY,
            HookVariant, HookResult,
        )

    def test_hook_types_defined(self):
        from layers.L2_creative.hook_engine import HOOK_TYPES
        required = {"suspense", "reversal", "data", "empathy", "conflict"}
        assert required.issubset(set(HOOK_TYPES.keys()))

    def test_hook_examples_defined(self):
        from layers.L2_creative.hook_engine import HOOK_EXAMPLES, HOOK_TYPES
        for t in HOOK_TYPES:
            assert t in HOOK_EXAMPLES, f"缺少 Hook 示例: {t}"

    def test_vertical_hook_priority_covers_all(self):
        from layers.L2_creative.hook_engine import VERTICAL_HOOK_PRIORITY
        for v in VERTICALS:
            assert v in VERTICAL_HOOK_PRIORITY, f"垂类 {v} 无 Hook 优先级配置"
            assert len(VERTICAL_HOOK_PRIORITY[v]) >= 3

    def test_format_hook_variants(self):
        from layers.L2_creative.hook_engine import HookVariant, HookResult, format_hook_variants
        result = HookResult(
            variants=[
                HookVariant("data", "数据冲击型", "14亿人只有0.1%实现财务自由", "数字冲击"),
                HookVariant("conflict", "冲突对立型", "努力工作其实是最低效的致富方式", "制造对立"),
                HookVariant("suspense", "悬念型", "有一个秘密，学校永远不会教你", "制造好奇"),
            ],
            recommended="data",
        )
        msg = format_hook_variants(result)
        assert "Hook 变体" in msg
        assert "数据冲击型" in msg
        assert "⭐ 推荐" in msg


# ── rhythm_engine ──

class TestRhythmEngine:
    def test_module_imports(self):
        from layers.L2_creative.rhythm_engine import (
            annotate_rhythm, format_rhythm_plan,
            AttentionPoint, RhythmPlan, POINT_TYPE_DESC,
        )

    def test_point_types_defined(self):
        from layers.L2_creative.rhythm_engine import POINT_TYPE_DESC
        required = {"cut", "sfx", "caption_zoom", "bgm_swell", "pause"}
        assert required.issubset(set(POINT_TYPE_DESC.keys()))

    def test_rhythm_plan_points_per_interval(self):
        from layers.L2_creative.rhythm_engine import RhythmPlan, AttentionPoint
        plan = RhythmPlan(
            total_duration_sec=20,
            attention_points=[
                AttentionPoint(3.0, "cut", 5, "Hook结束", "你知道吗"),
                AttentionPoint(8.0, "caption_zoom", 4, "关键数据", "14亿人"),
                AttentionPoint(15.0, "sfx", 3, "情绪点", ""),
            ],
            density_score=1.5,
        )
        buckets = plan.points_per_interval(5.0)
        assert len(buckets) >= 3
        assert len(buckets[0]) == 1  # 3.0s 在第0区间
        assert len(buckets[1]) == 1  # 8.0s 在第1区间

    def test_format_rhythm_plan(self):
        from layers.L2_creative.rhythm_engine import RhythmPlan, AttentionPoint, format_rhythm_plan
        plan = RhythmPlan(
            total_duration_sec=25,
            attention_points=[
                AttentionPoint(3.0, "cut", 5, "切换配图", ""),
                AttentionPoint(10.0, "caption_zoom", 4, "关键词放大", ""),
            ],
            density_score=0.8,
        )
        msg = format_rhythm_plan(plan)
        assert "节奏标注" in msg
        assert "偏稀" in msg  # density 0.8 < 2


# ── rhythm_editor ──

class TestRhythmEditor:
    def test_module_imports(self):
        from layers.L5_postprod.rhythm_editor import (
            apply_rhythm, get_cut_timestamps,
            RhythmEditResult, _map_sfx_type,
        )

    def test_map_sfx_type(self):
        from layers.L5_postprod.rhythm_editor import _map_sfx_type
        assert _map_sfx_type("冲击感强烈的画面", 5) == "impact"
        assert _map_sfx_type("温馨情感场景", 3) == "soft_chime"
        assert _map_sfx_type("悬念未知内容", 4) == "suspense_sting"
        assert _map_sfx_type("结尾落点", 3) == "ending_chime"

    def test_get_cut_timestamps(self):
        from layers.L5_postprod.rhythm_editor import get_cut_timestamps
        from layers.L2_creative.rhythm_engine import RhythmPlan, AttentionPoint
        plan = RhythmPlan(
            total_duration_sec=20,
            attention_points=[
                AttentionPoint(3.0, "cut", 5, "切换", ""),
                AttentionPoint(8.0, "sfx", 3, "音效", ""),
                AttentionPoint(15.0, "cut", 4, "再次切换", ""),
            ],
        )
        cuts = get_cut_timestamps(plan)
        assert cuts == [3.0, 15.0]


# ── quality_gate ──

class TestQualityGate:
    def test_module_imports(self):
        from layers.L7_optimization.quality_gate import (
            score_content, score_video_file, format_quality_report,
            QualityScore, PASS_THRESHOLD,
        )

    def test_pass_threshold_is_70(self):
        from layers.L7_optimization.quality_gate import PASS_THRESHOLD
        assert PASS_THRESHOLD == 70

    def test_score_video_file_missing(self):
        from layers.L7_optimization.quality_gate import score_video_file
        result = score_video_file("/nonexistent/video.mp4", "hot_news_commentary")
        assert result.get("file_exists") == 0

    def test_format_quality_report_pass(self):
        from layers.L7_optimization.quality_gate import QualityScore, format_quality_report
        score = QualityScore(
            total=82.0,
            passed=True,
            dimensions={"hook_score": 85, "content_score": 80, "structure_score": 80,
                        "visual_score": 80, "viral_score": 75},
            issues=[],
            suggestions=[],
        )
        msg = format_quality_report(score)
        assert "✅" in msg
        assert "82" in msg

    def test_format_quality_report_fail(self):
        from layers.L7_optimization.quality_gate import QualityScore, format_quality_report
        score = QualityScore(
            total=58.0,
            passed=False,
            dimensions={"hook_score": 50, "content_score": 60, "structure_score": 55,
                        "visual_score": 65, "viral_score": 50},
            issues=["解说稿AI味过重"],
            suggestions=["增加更多口语化表达"],
        )
        msg = format_quality_report(score)
        assert "❌" in msg
        assert "AI味" in msg


# ── comment_engine ──

class TestCommentEngine:
    def test_module_imports(self):
        from layers.L2_creative.comment_engine import (
            generate_comments, format_comment_plan,
            CommentVariant, CommentPlan, VERTICAL_COMMENT_STRATEGY,
        )

    def test_strategy_covers_all_verticals(self):
        from layers.L2_creative.comment_engine import VERTICAL_COMMENT_STRATEGY
        for v in VERTICALS:
            assert v in VERTICAL_COMMENT_STRATEGY, f"垂类 {v} 无首评策略"

    def test_format_comment_plan(self):
        from layers.L2_creative.comment_engine import CommentVariant, CommentPlan, format_comment_plan
        plan = CommentPlan(
            first_comments=[
                CommentVariant("同意的扣1，不同意的扣2", "controversy", "high"),
                CommentVariant("说出了多少人的心声", "empathy", "medium"),
                CommentVariant("你们身边有这种情况吗？", "question", "high"),
            ],
            pinned_suggestion="同意的扣1，不同意的扣2",
            posting_tip="发布后1小时内积极互动",
        )
        msg = format_comment_plan(plan)
        assert "首评话术" in msg
        assert "建议置顶" in msg
        assert "运营小贴士" in msg


# ── webhooks.py Phase 5 集成 ──

class TestWebhooksPhase5:
    def test_phase5_imports_in_confirm(self):
        """验证 webhooks.py 中 Phase 5 模块的 import 路径正确。"""
        from layers.L2_creative.hook_engine import generate_hook_variants
        from layers.L2_creative.rhythm_engine import annotate_rhythm
        from layers.L5_postprod.rhythm_editor import apply_rhythm
        from layers.L7_optimization.quality_gate import score_content
        from layers.L2_creative.comment_engine import generate_comments

    def test_phase5_handle_confirm_exists(self):
        from api.webhooks import _handle_confirm
        import inspect
        assert inspect.iscoroutinefunction(_handle_confirm)
