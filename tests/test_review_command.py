from __future__ import annotations

from layers.L2_creative.review_command import ReviewCommand, parse_review_command


def test_parse_empty_returns_unknown():
    assert parse_review_command("").action == "unknown"


def test_parse_continue_chinese_alias():
    cmd = parse_review_command("确认片段")
    assert cmd.action == "continue"
    assert cmd.is_actionable


def test_parse_continue_numeric():
    assert parse_review_command("1").action == "continue"


def test_parse_regenerate_with_chinese_colon():
    cmd = parse_review_command("2.重新生成：人物近一点")
    assert cmd.action == "regenerate"
    assert cmd.raw_note == "人物近一点"


def test_parse_regenerate_without_note():
    cmd = parse_review_command("2.重新生成")
    assert cmd.action == "regenerate"
    assert cmd.raw_note == ""


def test_parse_regenerate_without_note_is_actionable_true():
    assert parse_review_command("2").is_actionable


def test_parse_cancel_with_note():
    cmd = parse_review_command("3.取消: 主题不合适")
    assert cmd.action == "cancel"
    assert cmd.raw_note == "主题不合适"


def test_parse_unknown_returns_action_unknown_not_actionable():
    cmd = parse_review_command("随便说一句")
    assert cmd.action == "unknown"
    assert not cmd.is_actionable


def test_extract_hint_closer_shot():
    cmd = parse_review_command("2.重新生成: 镜头近一点")
    assert cmd.hints == ["closer_shot"]


def test_extract_hint_no_text():
    cmd = parse_review_command("2.重新生成: 不要文字")
    assert cmd.hints == ["no_text"]


def test_extract_multiple_hints_combined_with_plus():
    cmd = parse_review_command("2.重新生成: 人物近 + 不要文字")
    assert cmd.hints == ["closer_shot", "no_text"]
    assert cmd.structured_notes == []


def test_extract_hints_keeps_unknown_in_structured_notes():
    cmd = parse_review_command("2.重新生成: 人物近 + 加一点雨水")
    assert cmd.hints == ["closer_shot"]
    assert cmd.structured_notes == ["加一点雨水"]


def test_extract_hints_dedupes_same_keyword():
    cmd = parse_review_command("2.重新生成: 人物近 + 镜头近 + 拉近")
    assert cmd.hints == ["closer_shot"]


def test_review_command_pydantic_serializable():
    cmd = parse_review_command("2.重新生成: 不要文字")
    dumped = cmd.model_dump()
    assert dumped["action"] == "regenerate"
    assert dumped["hints"] == ["no_text"]


def test_parse_handles_full_width_punctuation():
    cmd = parse_review_command("重新生成：人物近，去掉文字")
    assert cmd.action == "regenerate"
    assert "closer_shot" in cmd.hints
    assert "no_text" in cmd.hints


def test_review_command_is_actionable_property_false_for_unknown():
    assert not ReviewCommand(action="unknown").is_actionable
