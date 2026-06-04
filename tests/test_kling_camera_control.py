"""部署日真修：可灵 camera_control 旧→新 type 映射单测。

测目标：normalize_camera_control 把所有旧 type 正确映射到可灵 v2+ 接受的
simple+config 六轴 / None，覆盖配置文件里实际出现的所有 type。
"""
from __future__ import annotations

import pytest

from layers.L3_visual.providers.kling_v3 import (
    KLING_V2_NATIVE_TYPES,
    normalize_camera_control,
)


# ── 旧 type → 期望新结构 ───────────────────────────────────────────


def test_push_in_maps_to_simple_positive_zoom():
    out = normalize_camera_control({"type": "push_in", "config": {"zoom": 6}})
    assert out == {"type": "simple", "config": {"zoom": 6.0}}


def test_pull_out_maps_to_simple_negative_zoom():
    out = normalize_camera_control({"type": "pull_out", "config": {"zoom": 4}})
    assert out == {"type": "simple", "config": {"zoom": -4.0}}


def test_pan_left_maps_to_simple_negative_horizontal():
    out = normalize_camera_control({"type": "pan_left", "config": {"horizontal": 3}})
    assert out == {"type": "simple", "config": {"horizontal": -3.0}}


def test_pan_right_maps_to_simple_positive_horizontal():
    out = normalize_camera_control({"type": "pan_right", "config": {"horizontal": 2}})
    assert out == {"type": "simple", "config": {"horizontal": 2.0}}


def test_tilt_up_maps_to_simple_positive_vertical():
    out = normalize_camera_control({"type": "tilt_up", "config": {"vertical": 5}})
    assert out == {"type": "simple", "config": {"vertical": 5.0}}


def test_tilt_down_maps_to_simple_negative_vertical():
    out = normalize_camera_control({"type": "tilt_down", "config": {"vertical": 4}})
    assert out == {"type": "simple", "config": {"vertical": -4.0}}


def test_orbit_maps_to_pan_plus_horizontal():
    out = normalize_camera_control({"type": "orbit", "config": {"zoom": 3}})
    assert out == {"type": "simple", "config": {"pan": 3.0, "horizontal": 3.0}}


def test_static_returns_none():
    """static = 不传 camera_control（可灵默认就是固定机位）"""
    assert normalize_camera_control({"type": "static"}) is None


# ── 透传 / 兜底 ────────────────────────────────────────────────────


def test_native_simple_passthrough():
    src = {"type": "simple", "config": {"zoom": 5, "pan": 2}}
    assert normalize_camera_control(src) == src


def test_native_down_back_passthrough():
    src = {"type": "down_back"}
    assert normalize_camera_control(src) == src


@pytest.mark.parametrize("native", sorted(KLING_V2_NATIVE_TYPES))
def test_all_native_types_passthrough(native):
    src = {"type": native}
    assert normalize_camera_control(src) == src


def test_none_returns_none():
    assert normalize_camera_control(None) is None


def test_empty_dict_returns_none():
    assert normalize_camera_control({}) is None


def test_unknown_type_returns_none(caplog):
    out = normalize_camera_control({"type": "warp_drive", "config": {"zoom": 5}})
    assert out is None


# ── 边界 / 数据卫生 ──────────────────────────────────────────────


def test_push_in_without_config_uses_default():
    out = normalize_camera_control({"type": "push_in"})
    assert out == {"type": "simple", "config": {"zoom": 5.0}}


def test_push_in_clamps_to_max_10():
    out = normalize_camera_control({"type": "push_in", "config": {"zoom": 99}})
    assert out == {"type": "simple", "config": {"zoom": 10.0}}


def test_push_in_with_string_zoom_falls_back_to_default():
    out = normalize_camera_control({"type": "push_in", "config": {"zoom": "bad"}})
    assert out == {"type": "simple", "config": {"zoom": 5.0}}


def test_pull_out_negative_zoom_value_still_resolves_to_negative():
    """旧 config zoom 已经是负值时，pull_out 仍保证输出为负"""
    out = normalize_camera_control({"type": "pull_out", "config": {"zoom": -7}})
    assert out == {"type": "simple", "config": {"zoom": -7.0}}


def test_pan_left_with_pan_key_instead_of_horizontal():
    """旧 yaml 可能用 pan 字段名"""
    out = normalize_camera_control({"type": "pan_left", "config": {"pan": 4}})
    assert out == {"type": "simple", "config": {"horizontal": -4.0}}


# ── 真实 yaml 模板覆盖（防止某个 shot template 漏改）───────────────


@pytest.mark.parametrize(
    "yaml_camera_control",
    [
        # 来自 config/shot_templates/*.yaml 的真实样本
        {"type": "push_in", "config": {"horizontal": 0, "vertical": 0, "zoom": 6}},
        {"type": "push_in", "config": {"horizontal": 0, "vertical": -1, "zoom": 5}},
        {"type": "push_in", "config": {"horizontal": 0, "vertical": 0, "zoom": 7}},
        {"type": "push_in", "config": {"horizontal": 0, "vertical": 0, "zoom": 4}},
        {"type": "push_in", "config": {"horizontal": -2, "vertical": 0, "zoom": 4}},
        {"type": "push_in", "config": {"horizontal": 0, "vertical": 0, "zoom": 5}},
        {"type": "push_in", "config": {"horizontal": 2, "vertical": 0, "zoom": 5}},
    ],
)
def test_real_yaml_samples_map_successfully(yaml_camera_control):
    out = normalize_camera_control(yaml_camera_control)
    assert out is not None
    assert out["type"] == "simple"
    assert "zoom" in out["config"]
    assert out["config"]["zoom"] > 0  # push_in 必须是正 zoom
