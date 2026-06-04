from __future__ import annotations

import pytest
from pydantic import ValidationError

from layers.L2_creative.schemas import SceneShot, Storyboard


def valid_shot_dict(
    scene_no: int = 1,
    duration: float = 5.0,
    character_id: str = "su_wan",
    camera_distance: str = "medium",
) -> dict:
    return {
        "scene_no": scene_no,
        "narration_segment": "咖啡价格突然上涨，很多人还没意识到影响。",
        "estimated_duration_sec": duration,
        "character_id": character_id,
        "environment_id": "coffee_shop",
        "time_of_day": "morning",
        "subject_action": "looking at a receipt beside a coffee cup",
        "subject_emotion": "surprised",
        "wardrobe_choice": "casual",
        "key_props": ["coffee cup", "receipt"],
        "position": {
            "subject_position": "center",
            "camera_distance": camera_distance,
            "camera_angle": "eye_level",
        },
        "camera_movement": "push_in",
        "lighting_mood": "warm",
        "composition": "rule_of_thirds",
    }


# R2.2 改 30%: 5+ shots 时需要多样化镜头景别（schema 硬约束）
_DISTANCE_POOL = ["medium", "close_up", "wide", "medium_close", "medium_wide", "extreme_close"]


def diverse_shots(n: int, start: int = 1, duration: float = 5.0) -> list[dict]:
    """造 n 个 shots，camera_distance 轮换满足多样性约束。"""
    return [
        valid_shot_dict(
            scene_no=start + i,
            duration=duration,
            camera_distance=_DISTANCE_POOL[i % len(_DISTANCE_POOL)],
        )
        for i in range(n)
    ]


def valid_storyboard_dict(shots: list[dict] | None = None, total_duration_sec: float = 10.0) -> dict:
    return {
        "plan_id": "P001",
        "title": "咖啡涨价",
        "theme": "咖啡涨价影响年轻人",
        "style_name": "hot_news_commentary",
        "main_character_id": "su_wan",
        "total_duration_sec": total_duration_sec,
        "shots": shots
        if shots is not None
        else [
            valid_shot_dict(scene_no=1, duration=5),
            valid_shot_dict(scene_no=2, duration=5),
        ],
    }


@pytest.mark.parametrize(
    ("mutation", "case_name"),
    [
        (lambda data: data.pop("scene_no"), "missing_scene_no"),
        (lambda data: data.update(scene_no=0), "scene_no_zero"),
        (lambda data: data.update(narration_segment=""), "empty_narration"),
        (lambda data: data.update(narration_segment="字" * 201), "narration_too_long"),
        (lambda data: data.update(estimated_duration_sec=0), "duration_zero"),
        (lambda data: data.update(estimated_duration_sec=20), "duration_too_long"),
        (lambda data: data.update(character_id="not_exist"), "unknown_character"),
        (lambda data: data.update(environment_id="not_exist"), "unknown_environment"),
        (lambda data: data.update(wardrobe_choice="custom", outfit_override=""), "custom_without_outfit"),
        (lambda data: data.update(wardrobe_choice="casual", outfit_override="红色连衣裙"), "non_custom_with_outfit"),
        (lambda data: data.update(extra_field=1), "extra_field_forbidden"),
        # R2.1 改 30%: voice_type 必须是 narration/dialogue/ambient/silent 之一
        (lambda data: data.update(voice_type="singing"), "invalid_voice_type"),
    ],
)
def test_scene_shot_rejects_invalid_payloads(mutation, case_name):
    data = valid_shot_dict()
    mutation(data)

    with pytest.raises(ValidationError), pytest.MonkeyPatch.context():
        SceneShot(**data)


def test_scene_shot_accepts_complete_valid_payload_with_default_position():
    shot = SceneShot(**valid_shot_dict())

    assert shot.scene_no == 1
    assert shot.character_id == "su_wan"
    assert shot.environment_id == "coffee_shop"
    assert shot.position.subject_position == "center"
    assert shot.position.camera_distance == "medium"
    assert shot.position.camera_angle == "eye_level"


def test_scene_shot_default_voice_type_is_narration():
    """R2.1 改 30%: voice_type 默认 narration（短视频解说类首选）。"""
    shot = SceneShot(**valid_shot_dict())
    assert shot.voice_type == "narration"


def test_scene_shot_accepts_dialogue_voice_type():
    """R2.1 改 30%: dialogue 类型用于角色台词（未来接 HeyGen 对口型）。"""
    data = valid_shot_dict()
    data["voice_type"] = "dialogue"
    shot = SceneShot(**data)
    assert shot.voice_type == "dialogue"


def test_scene_shot_accepts_position_dict():
    data = valid_shot_dict()
    data["position"] = {
        "subject_position": "center",
        "camera_distance": "medium",
        "camera_angle": "eye_level",
    }

    shot = SceneShot(**data)

    assert shot.position.subject_position == "center"
    assert shot.position.camera_distance == "medium"
    assert shot.position.camera_angle == "eye_level"


def test_storyboard_rejects_non_continuous_scene_numbers():
    shots = [
        valid_shot_dict(scene_no=1, duration=5),
        valid_shot_dict(scene_no=2, duration=5),
        valid_shot_dict(scene_no=4, duration=5),
    ]

    with pytest.raises(ValidationError):
        Storyboard(**valid_storyboard_dict(shots=shots, total_duration_sec=15))


def test_storyboard_rejects_duration_mismatch_over_two_seconds():
    shots = [
        valid_shot_dict(scene_no=1, duration=5),
        valid_shot_dict(scene_no=2, duration=5),
        valid_shot_dict(scene_no=3, duration=5),
    ]

    with pytest.raises(ValidationError):
        Storyboard(**valid_storyboard_dict(shots=shots, total_duration_sec=30))


def test_storyboard_rejects_main_character_absent_from_shots():
    shots = [
        valid_shot_dict(scene_no=1, duration=5, character_id="lin_yue"),
        valid_shot_dict(scene_no=2, duration=5, character_id="lin_yue"),
    ]

    with pytest.raises(ValidationError):
        Storyboard(**valid_storyboard_dict(shots=shots, total_duration_sec=10))


def test_storyboard_rejects_empty_shots():
    with pytest.raises(ValidationError):
        Storyboard(**valid_storyboard_dict(shots=[], total_duration_sec=5))


def test_storyboard_rejects_more_than_ten_shots():
    """R2.1 改 30%: max_length 从 12 收紧到 10（短视频信息密度高于电影感）。"""
    shots = diverse_shots(11)  # 11 shots，max_length 先拦截，多样性也满足

    with pytest.raises(ValidationError):
        Storyboard(**valid_storyboard_dict(shots=shots, total_duration_sec=55))


def test_storyboard_accepts_exactly_ten_shots():
    """R2.1 改 30%: 边界正向 — 10 shots 应当成功（多样化 camera_distance）。"""
    shots = diverse_shots(10)
    board = Storyboard(**valid_storyboard_dict(shots=shots, total_duration_sec=50))
    assert len(board.shots) == 10


# ─── R2.2 改 30%: 镜头多样性硬约束测试 ───


def test_storyboard_rejects_low_diversity_camera_distance_at_five_shots():
    """R2.2 改 30%: 5 shots 全 medium → schema 直接拒绝（防止 LLM 偷懒）。"""
    shots = [valid_shot_dict(scene_no=i + 1, duration=5, camera_distance="medium") for i in range(5)]

    with pytest.raises(ValidationError, match="景别过于单一"):
        Storyboard(**valid_storyboard_dict(shots=shots, total_duration_sec=25))


def test_storyboard_accepts_diverse_camera_distance_at_five_shots():
    """R2.2 改 30%: 5 shots 用 2 种景别 → 满足最低多样性，通过。"""
    shots = [
        valid_shot_dict(scene_no=1, duration=5, camera_distance="medium"),
        valid_shot_dict(scene_no=2, duration=5, camera_distance="close_up"),
        valid_shot_dict(scene_no=3, duration=5, camera_distance="medium"),
        valid_shot_dict(scene_no=4, duration=5, camera_distance="close_up"),
        valid_shot_dict(scene_no=5, duration=5, camera_distance="medium"),
    ]
    board = Storyboard(**valid_storyboard_dict(shots=shots, total_duration_sec=25))
    assert len(board.shots) == 5


def test_storyboard_rejects_only_two_distances_at_eight_shots():
    """R2.2 改 30%: 8+ shots 升级要求 3 种景别。"""
    shots = []
    for i in range(8):
        distance = "medium" if i % 2 == 0 else "close_up"
        shots.append(valid_shot_dict(scene_no=i + 1, duration=5, camera_distance=distance))

    with pytest.raises(ValidationError, match="景别过于单一"):
        Storyboard(**valid_storyboard_dict(shots=shots, total_duration_sec=40))


def test_storyboard_accepts_three_distances_at_eight_shots():
    """R2.2 改 30%: 8 shots 用 3 种景别 → 通过。"""
    shots = diverse_shots(8)  # 6 种景别轮换
    board = Storyboard(**valid_storyboard_dict(shots=shots, total_duration_sec=40))
    assert len(board.shots) == 8


def test_storyboard_skips_diversity_check_for_short_videos():
    """R2.2 改 30%: <5 shots 不卡多样性（短片给 LLM 灵活度）。"""
    # 4 shots 全 medium → 应当通过
    shots = [valid_shot_dict(scene_no=i + 1, duration=5, camera_distance="medium") for i in range(4)]
    board = Storyboard(**valid_storyboard_dict(shots=shots, total_duration_sec=20))
    assert len(board.shots) == 4


def test_storyboard_accepts_complete_valid_payload_with_two_shots():
    board = Storyboard(**valid_storyboard_dict())

    assert board.plan_id == "P001"
    assert board.main_character_id == "su_wan"
    assert len(board.shots) == 2
    assert board.total_duration_sec == 10


def test_storyboard_model_dump_round_trips_through_model_validate():
    board = Storyboard(**valid_storyboard_dict())
    dumped = board.model_dump()

    restored = Storyboard.model_validate(dumped)

    assert restored == board
