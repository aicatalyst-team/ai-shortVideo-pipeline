"""R1.3 站位关系 schema 验收测试。"""

from dataclasses import is_dataclass
from typing import get_args, get_type_hints

import pytest

from layers.L2_creative.character_manager import Position


SUBJECT_POSITIONS = {
    "center", "front", "back",
    "left", "right",
    "left_front", "right_front", "left_back", "right_back",
}
CAMERA_DISTANCES = {
    "extreme_close", "close_up", "medium_close",
    "medium", "medium_wide", "wide", "extreme_wide",
    "over_shoulder",
}
CAMERA_ANGLES = {
    "eye_level", "low_angle", "high_angle", "dutch", "birds_eye", "worms_eye",
}


def test_position_is_dataclass():
    assert is_dataclass(Position)


def test_position_default_values():
    position = Position()
    assert position.subject_position == "center"
    assert position.camera_distance == "medium"
    assert position.camera_angle == "eye_level"


def test_position_explicit_values():
    position = Position(
        subject_position="left_front",
        camera_distance="close_up",
        camera_angle="low_angle",
    )
    assert position.subject_position == "left_front"
    assert position.camera_distance == "close_up"
    assert position.camera_angle == "low_angle"


def test_position_literal_annotations_cover_subject_positions():
    hints = get_type_hints(Position)
    assert set(get_args(hints["subject_position"])) == SUBJECT_POSITIONS


def test_position_literal_annotations_cover_camera_distances():
    hints = get_type_hints(Position)
    assert set(get_args(hints["camera_distance"])) == CAMERA_DISTANCES


def test_position_literal_annotations_cover_camera_angles():
    hints = get_type_hints(Position)
    assert set(get_args(hints["camera_angle"])) == CAMERA_ANGLES


@pytest.mark.parametrize("subject_position", sorted(SUBJECT_POSITIONS))
def test_all_subject_positions_can_be_assigned(subject_position):
    assert Position(subject_position=subject_position).subject_position == subject_position


@pytest.mark.parametrize("camera_distance", sorted(CAMERA_DISTANCES))
def test_all_camera_distances_can_be_assigned(camera_distance):
    assert Position(camera_distance=camera_distance).camera_distance == camera_distance


@pytest.mark.parametrize("camera_angle", sorted(CAMERA_ANGLES))
def test_all_camera_angles_can_be_assigned(camera_angle):
    assert Position(camera_angle=camera_angle).camera_angle == camera_angle


def test_dataclass_does_not_runtime_validate_literal_values():
    position = Position(
        subject_position="outside_frame",
        camera_distance="super_far",
        camera_angle="sideways",
    )
    assert position.subject_position == "outside_frame"
    assert position.camera_distance == "super_far"
    assert position.camera_angle == "sideways"
