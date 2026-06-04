"""Phase 6 集成测试：规模化 + 数据闭环（首批实现）"""

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestWebhooksPhase6:
    def test_help_text_has_batch_commands(self):
        from api.webhooks import HELP_TEXT

        assert "批量 5" in HELP_TEXT
        assert "定时 3" in HELP_TEXT
        assert "定时关" in HELP_TEXT
        assert "触发定时" in HELP_TEXT
        assert "数据 <视频ID>" in HELP_TEXT
        assert "爆了 <视频ID>" in HELP_TEXT

    def test_run_auto_video_job_exists(self):
        from api.webhooks import run_auto_video_job
        import inspect

        assert inspect.iscoroutinefunction(run_auto_video_job)

    def test_metrics_parser_exists(self):
        from api.webhooks import _parse_metrics_payload

        video_id, metrics = _parse_metrics_payload("VID123 播放量=12000 完播率=35% 互动率=7% 点赞=100 评论=20 分享=5")
        assert video_id == "VID123"
        assert metrics["views"] == 12000
        assert metrics["completion_rate"] == 0.35
        assert metrics["engagement_rate"] == 0.07


class TestSchedulerPhase6:
    def test_worker_functions_registered(self):
        from core.scheduler import WorkerSettings

        fn_names = {fn.__name__ for fn in WorkerSettings.functions}
        assert "task_generate_video" in fn_names
        assert "task_fetch_trending" in fn_names
        assert "task_daily_batch" in fn_names

    def test_cron_jobs_configured(self):
        from core.scheduler import WorkerSettings

        assert getattr(WorkerSettings, "cron_jobs", None), "Phase 6 应配置每日自动任务"

    def test_runtime_helpers_exist(self):
        from core.scheduler import runtime_get, runtime_set
        import inspect

        assert inspect.iscoroutinefunction(runtime_get)
        assert inspect.iscoroutinefunction(runtime_set)


class TestCreativePhase6:
    def test_variant_generator_exists(self):
        from layers.L2_creative.variant_generator import generate_variants, format_variants
        import inspect

        assert inspect.iscoroutinefunction(generate_variants)
        assert callable(format_variants)

    def test_structure_library_exists(self):
        from layers.L2_creative.structure_library import build_structure_library, summarize_structure_library
        import inspect

        assert inspect.iscoroutinefunction(build_structure_library)
        assert callable(summarize_structure_library)


class TestModelsPhase6:
    def test_video_models_exist(self):
        from db.models import VideoRecord, VideoMetric

        assert VideoRecord.__tablename__ == "video_records"
        assert VideoMetric.__tablename__ == "video_metrics"


class TestPhase6Files:
    @pytest.mark.parametrize(
        "path_str",
        [
            "api/webhooks.py",
            "core/scheduler.py",
            "layers/L2_creative/variant_generator.py",
            "layers/L2_creative/structure_library.py",
        ],
    )
    def test_phase6_files_exist(self, path_str):
        path = Path(__file__).resolve().parent.parent / path_str
        assert path.exists(), f"缺少文件: {path}"
