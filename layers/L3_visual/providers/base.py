from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ImageResult:
    url: str
    local_path: str | None = None
    width: int = 0
    height: int = 0
    model: str = ""
    clip_score: float | None = None
    clip_passed: bool = True
    clip_warning: str = ""


@dataclass
class VideoResult:
    url: str
    local_path: str | None = None
    duration_sec: float = 0
    task_id: str = ""
    model: str = ""
    clip_score: float | None = None
    clip_passed: bool = True
    clip_warning: str = ""


class ImageProvider(ABC):
    @abstractmethod
    async def text_to_image(
        self, prompt: str, negative_prompt: str = "", aspect_ratio: str = "9:16"
    ) -> ImageResult: ...


class VideoProvider(ABC):
    @abstractmethod
    async def image_to_video(
        self,
        image_path: str,
        prompt: str,
        duration_sec: int = 5,
        aspect_ratio: str = "9:16",
        model_name: str = "standard",
    ) -> VideoResult: ...
