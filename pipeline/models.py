from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AnimationName = Literal["fade", "slide", "scale", "none"]
GradientDirection = Literal["vertical", "horizontal", "diagonal"]


class Timing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_sec: float = Field(default=0.0, ge=0)
    duration_sec: float | None = Field(default=None, gt=0)

    def contains(self, t_sec: float, scene_duration_sec: float) -> bool:
        duration = self.duration_sec if self.duration_sec is not None else scene_duration_sec
        return self.start_sec <= t_sec <= self.start_sec + duration

    def progress(self, t_sec: float, scene_duration_sec: float) -> float:
        duration = self.duration_sec if self.duration_sec is not None else scene_duration_sec
        if duration <= 0:
            return 1.0
        return max(0.0, min(1.0, (t_sec - self.start_sec) / duration))


class Position(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0, le=1, description="Normalized horizontal center from left to right.")
    y: float = Field(ge=0, le=1, description="Normalized vertical center from top to bottom.")


class Size(BaseModel):
    model_config = ConfigDict(extra="forbid")

    width: float = Field(gt=0, le=1, description="Normalized width relative to 1080px canvas.")
    height: float = Field(gt=0, le=1, description="Normalized height relative to 1920px canvas.")


class Background(BaseModel):
    model_config = ConfigDict(extra="forbid")

    color: str = Field(default="#0b1020", description="CSS hex color.")
    gradient: list[str] = Field(default_factory=list, description="Optional list of CSS hex colors.")
    gradient_direction: GradientDirection = "vertical"

    @field_validator("gradient")
    @classmethod
    def limit_gradient(cls, value: list[str]) -> list[str]:
        return value[:4]


class Element(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_query: str = Field(min_length=2)
    description: str = Field(min_length=2)
    position: Position
    size: Size
    animation: AnimationName = "none"
    timing: Timing = Field(default_factory=Timing)
    asset_id: str | None = None


class Caption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=180)
    position: Position
    timing: Timing = Field(default_factory=Timing)


class ScriptCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=1)
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=220)
    position: Position = Field(default_factory=lambda: Position(x=0.5, y=0.74))

    @model_validator(mode="after")
    def validate_span(self) -> "ScriptCue":
        if self.end_sec <= self.start_sec:
            self.end_sec = self.start_sec + 0.1
        return self

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    def as_srt_block(self) -> str:
        return f"{self.index}\n{_srt_timestamp(self.start_sec)} --> {_srt_timestamp(self.end_sec)}\n{self.text}"


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_sec: float = Field(gt=0)
    narration_text: str = Field(default="")
    background: Background = Field(default_factory=Background)
    script_cues: list[ScriptCue] = Field(
        default_factory=list,
        description="Authoritative SRT-style narration and caption cues, relative to this scene.",
    )
    script_srt: str = Field(default="", description="SRT-formatted version of script_cues for this scene.")
    elements: list[Element] = Field(default_factory=list)
    captions: list[Caption] = Field(default_factory=list)
    actual_audio_duration_sec: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def normalize_child_timings(self) -> "Scene":
        if self.script_cues:
            self.script_cues.sort(key=lambda cue: cue.start_sec)
            for index, cue in enumerate(self.script_cues, 1):
                cue.index = index
                if cue.start_sec > self.duration_sec:
                    cue.start_sec = max(0.0, self.duration_sec - 0.1)
                if cue.end_sec > self.duration_sec:
                    cue.end_sec = self.duration_sec
                if cue.end_sec <= cue.start_sec:
                    cue.end_sec = min(self.duration_sec, cue.start_sec + 0.1)
            self.narration_text = " ".join(cue.text.strip() for cue in self.script_cues).strip()
        elif self.narration_text:
            self.script_cues = [
                ScriptCue(index=1, start_sec=0.0, end_sec=self.duration_sec, text=self.narration_text)
            ]

        if not self.narration_text.strip():
            raise ValueError("Scene must include narration_text or script_cues")

        for item in [*self.elements, *self.captions]:
            if item.timing.duration_sec is None:
                item.timing.duration_sec = max(0.1, self.duration_sec - item.timing.start_sec)
            if item.timing.start_sec > self.duration_sec:
                item.timing.start_sec = 0.0
                item.timing.duration_sec = self.duration_sec
            elif item.timing.start_sec + (item.timing.duration_sec or 0) > self.duration_sec:
                item.timing.duration_sec = max(0.1, self.duration_sec - item.timing.start_sec)
        self.refresh_script_srt()
        return self

    def refresh_script_srt(self) -> None:
        self.script_srt = "\n\n".join(cue.as_srt_block() for cue in self.script_cues)


class Storyboard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=80)
    prompt: str = Field(default="")
    target_length_sec: float = Field(gt=0, le=60)
    script_srt: str = Field(default="", description="SRT-formatted narration/caption script for the whole video.")
    scenes: list[Scene] = Field(min_length=1)

    @model_validator(mode="after")
    def refresh_script(self) -> "Storyboard":
        self.refresh_script_srt()
        return self

    @property
    def total_duration_sec(self) -> float:
        return sum(scene.duration_sec for scene in self.scenes)

    def rescale_to(self, target_length_sec: float) -> None:
        current = self.total_duration_sec
        if current <= 0:
            raise ValueError("Storyboard has zero total duration")
        factor = target_length_sec / current
        for scene in self.scenes:
            old_duration = scene.duration_sec
            scene.duration_sec = max(0.25, scene.duration_sec * factor)
            for item in [*scene.elements, *scene.captions]:
                item.timing.start_sec *= factor
                if item.timing.duration_sec is not None:
                    item.timing.duration_sec *= factor
                if old_duration > 0 and item.timing.start_sec > scene.duration_sec:
                    item.timing.start_sec = 0.0
                    item.timing.duration_sec = scene.duration_sec
            for cue in scene.script_cues:
                cue.start_sec *= factor
                cue.end_sec *= factor
        delta = target_length_sec - self.total_duration_sec
        last_scene = self.scenes[-1]
        last_scene.duration_sec = max(0.25, last_scene.duration_sec + delta)
        for item in [*last_scene.elements, *last_scene.captions]:
            if item.timing.start_sec >= last_scene.duration_sec:
                item.timing.start_sec = 0.0
            if (
                item.timing.duration_sec is None
                or item.timing.start_sec + item.timing.duration_sec > last_scene.duration_sec
            ):
                item.timing.duration_sec = max(0.1, last_scene.duration_sec - item.timing.start_sec)
        for cue in last_scene.script_cues:
            cue.end_sec = min(cue.end_sec, last_scene.duration_sec)
            if cue.start_sec >= cue.end_sec:
                cue.start_sec = max(0.0, cue.end_sec - 0.1)
        self.target_length_sec = target_length_sec
        for scene in self.scenes:
            scene.refresh_script_srt()
        self.refresh_script_srt()

    def apply_audio_durations(self, durations_sec: list[float]) -> None:
        if len(durations_sec) != len(self.scenes):
            raise ValueError("Audio duration count does not match scene count")
        for scene, duration in zip(self.scenes, durations_sec, strict=True):
            previous = scene.duration_sec
            scene.actual_audio_duration_sec = duration
            scene.duration_sec = max(0.05, duration)
            if previous > 0:
                factor = scene.duration_sec / previous
                for item in [*scene.elements, *scene.captions]:
                    item.timing.start_sec *= factor
                    if item.timing.duration_sec is not None:
                        item.timing.duration_sec *= factor
                for cue in scene.script_cues:
                    cue.start_sec *= factor
                    cue.end_sec *= factor
            scene.refresh_script_srt()
        self.refresh_script_srt()

    def refresh_script_srt(self) -> None:
        blocks: list[str] = []
        offset = 0.0
        index = 1
        for scene in self.scenes:
            for cue in scene.script_cues:
                blocks.append(
                    f"{index}\n"
                    f"{_srt_timestamp(offset + cue.start_sec)} --> {_srt_timestamp(offset + cue.end_sec)}\n"
                    f"{cue.text}"
                )
                index += 1
            offset += scene.duration_sec
        self.script_srt = "\n\n".join(blocks)


def _srt_timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hours, remainder = divmod(millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


class ManifestEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    filename: str
    label: str
    description: str
    tags: list[str] = Field(default_factory=list)
    viewBox: str = "0 0 1024 1024"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source_prompt: str


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assets: list[ManifestEntry] = Field(default_factory=list)

    def by_id(self, asset_id: str) -> ManifestEntry | None:
        for entry in self.assets:
            if entry.id == asset_id:
                return entry
        return None
