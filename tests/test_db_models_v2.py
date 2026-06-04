from __future__ import annotations

from sqlalchemy.orm import class_mapper


def _columns(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


def _mapper_attrs(model) -> set[str]:
    return {p.key for p in class_mapper(model).attrs}


def test_storyboard_model_imports():
    from db.models import Storyboard

    assert Storyboard.__tablename__ == "storyboards"
    cols = _columns(Storyboard)
    expected = {
        "id",
        "plan_id",
        "title",
        "theme",
        "style_name",
        "status",
        "metadata",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"
    assert "storyboard_metadata" in _mapper_attrs(Storyboard)


def test_clip_model_imports():
    from db.models import Clip

    assert Clip.__tablename__ == "clips"
    cols = _columns(Clip)
    expected = {
        "id",
        "storyboard_id",
        "seq",
        "node_id",
        "prompt",
        "kling_prompt",
        "narration_segment",
        "duration_sec",
        "video_url",
        "status",
        "model",
        "cost_cny",
        "duration_ms",
        "version",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_frame_asset_model_imports():
    from db.models import FrameAsset

    assert FrameAsset.__tablename__ == "frame_assets"
    cols = _columns(FrameAsset)
    expected = {
        "id",
        "clip_id",
        "node_id",
        "kind",
        "url",
        "sha256",
        "width",
        "height",
        "source",
        "metadata",
        "created_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"
    assert "asset_metadata" in _mapper_attrs(FrameAsset)


def test_canvas_project_model_imports():
    from db.models import CanvasProject

    assert CanvasProject.__tablename__ == "canvas_projects"
    cols = _columns(CanvasProject)
    expected = {
        "id",
        "owner_id",
        "title",
        "status",
        "storyboard_id",
        "viewport",
        "metadata",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"
    assert "project_metadata" in _mapper_attrs(CanvasProject)


def test_canvas_node_model_imports():
    from db.models import CanvasNode

    assert CanvasNode.__tablename__ == "canvas_nodes"
    cols = _columns(CanvasNode)
    expected = {
        "id",
        "project_id",
        "type",
        "title",
        "position",
        "size",
        "data",
        "status",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_canvas_edge_model_imports():
    from db.models import CanvasEdge

    assert CanvasEdge.__tablename__ == "canvas_edges"
    cols = _columns(CanvasEdge)
    expected = {
        "id",
        "project_id",
        "source_node_id",
        "target_node_id",
        "type",
        "data",
        "status",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_creator_memory_model_imports():
    from db.models import CreatorMemory

    assert CreatorMemory.__tablename__ == "creator_memories"
    cols = _columns(CreatorMemory)
    expected = {
        "id",
        "owner_id",
        "scope",
        "style_name",
        "type",
        "content",
        "prompt_rule",
        "evidence",
        "confidence",
        "status",
        "source_ref",
        "created_at",
        "approved_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_skill_models_import():
    from db.models import CreativeSkill, Skill, SkillRun, SkillVersion

    assert Skill.__tablename__ == "skills"
    assert CreativeSkill.__tablename__ == "creative_skills"
    assert SkillVersion.__tablename__ == "skill_versions"
    assert SkillRun.__tablename__ == "skill_runs"
    assert {"owner_id", "name", "visibility", "status"}.issubset(_columns(Skill))
    assert {
        "id",
        "name",
        "description",
        "default_intensity",
        "shot_template_key",
        "prompt_director_config_key",
        "created_at",
    }.issubset(_columns(CreativeSkill))
    assert {"skill_id", "version", "input_schema", "output_schema", "definition"}.issubset(
        _columns(SkillVersion)
    )
    assert {"skill_version_id", "project_id", "node_id", "input", "output"}.issubset(
        _columns(SkillRun)
    )


def test_llm_call_model_imports():
    from db.models import LlmCall

    assert LlmCall.__tablename__ == "llm_calls"
    cols = _columns(LlmCall)
    expected = {
        "id",
        "tenant_id",
        "project_id",
        "node_id",
        "skill_run_id",
        "biz_type",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cost_cny",
        "latency_ms",
        "status",
        "trace_id",
        "created_at",
    }
    assert expected.issubset(cols), f"missing: {expected - cols}"


def test_generation_session_models_import():
    from db.models import ClipReviewEvent, GenerationSession

    assert GenerationSession.__tablename__ == "generation_sessions"
    assert ClipReviewEvent.__tablename__ == "clip_review_events"
    session_cols = _columns(GenerationSession)
    event_cols = _columns(ClipReviewEvent)
    assert {
        "id",
        "chat_id",
        "skill_id",
        "theme",
        "status",
        "locked_character_id",
        "locked_scene_id",
        "locked_storyboard_id",
        "plan_id",
        "final_score",
        "created_at",
        "updated_at",
    }.issubset(session_cols)
    assert {
        "id",
        "session_id",
        "stage",
        "decision",
        "clip_index",
        "comment",
        "hints",
        "metadata",
        "created_at",
    }.issubset(event_cols)
    assert "event_metadata" in _mapper_attrs(ClipReviewEvent)


def test_fail_record_model_import():
    from db.models import FailRecord

    assert FailRecord.__tablename__ == "fail_records"
    cols = _columns(FailRecord)
    assert {
        "id",
        "session_id",
        "stage",
        "error_code",
        "error_message",
        "suggestion",
        "metadata",
        "created_at",
    }.issubset(cols)
    assert "event_metadata" in _mapper_attrs(FailRecord)


def test_storyboard_has_clips_relationship():
    from db.models import Clip, Storyboard

    assert Storyboard.clips is not None
    assert Clip.storyboard is not None


def test_clip_has_frame_assets_relationship():
    from db.models import Clip, FrameAsset

    assert Clip.frame_assets is not None
    assert FrameAsset.clip is not None


def test_canvas_project_has_node_and_edge_relationships():
    from db.models import CanvasEdge, CanvasNode, CanvasProject

    assert CanvasProject.nodes is not None
    assert CanvasProject.edges is not None
    assert CanvasNode.project is not None
    assert CanvasEdge.project is not None


def test_skill_has_versions_relationship():
    from db.models import Skill, SkillVersion

    assert Skill.versions is not None
    assert SkillVersion.skill is not None


def test_legacy_plan_evaluation_field_preserved():
    """Compatibility rule: old Plan.evaluation JSONB must stay in place."""
    from db.models import Plan

    assert "evaluation" in _columns(Plan), "Plan.evaluation cannot be removed"


def test_short_id_generation():
    from db.models import _short_id

    a = _short_id()
    b = _short_id()
    assert len(a) == 16
    assert len(b) == 16
    assert a != b
    assert a == a.upper()


# ── （migration 004）: r_metadata + fallback_chain ──


def test_clip_has_r_metadata_jsonb():
    """R2.1 SceneShot Pydantic dump 落库字段。"""
    from db.models import Clip

    assert "r_metadata" in _columns(Clip), "clips.r_metadata（ schema dump）必须存在"


def test_llm_call_has_fallback_chain_jsonb():
    """W6 LlmRouter failover 链路追溯。面试场景对应实现。"""
    from db.models import LlmCall

    assert "fallback_chain" in _columns(LlmCall), "llm_calls.fallback_chain（多模型 failover 链路）必须存在"


def test_migration_004_file_exists():
    """004 迁移文件应当存在且 down_revision='003'。"""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    mig_path = repo_root / "db" / "migrations" / "versions" / "004_phase_r_metadata.py"
    assert mig_path.exists(), "004_phase_r_metadata.py 缺失"

    content = mig_path.read_text(encoding="utf-8")
    assert 'revision: str = "004"' in content
    assert 'down_revision: Union[str, None] = "003"' in content
    assert "add_column" in content
    assert "r_metadata" in content
    assert "fallback_chain" in content
