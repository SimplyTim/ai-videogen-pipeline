from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PipelineConfig:
    target_length_sec: float = 20.0
    fps: int = 30
    width: int = 1080
    height: int = 1920
    output_dir: Path = Path("output")
    cache_dir: Path = Path("cache")
    asset_dir: Path = Path("assets/svg")
    manifest_path: Path = Path("assets/manifest.json")
    music_dir: Path = Path("assets/music")
    add_captions: bool = True
    add_music: bool = False
    voice: str = "Puck"
    style: str = "Say in a bright, clear, energetic short-form video narrator voice:"
    language_code: str = "en-US"
    planning_model: str = "gemini-3.5-flash"
    svg_retry_model: str = "gemini-3.1-pro-preview"
    tts_model: str = "gemini-3.1-flash-tts-preview"
    tts_fallback_model: str = "gemini-3.1-flash-tts"
    seed_open_source_assets: bool = True
    allow_gemini_svg_generation: bool = False
    max_gemini_calls: int = 12
    max_prompt_chars: int = 1500
    max_scenes: int = 6
    max_elements_per_scene: int = 3
    max_captions_per_scene: int = 2
    max_narration_chars_per_scene: int = 500
    max_asset_labels_in_prompt: int = 80
    target_words_per_second: float = 2.0

    @classmethod
    def from_file(cls, path: Path) -> "PipelineConfig":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Config file must contain a JSON object: {path}")
        fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in fields:
                raise ValueError(f"Unknown config key {key!r} in {path}")
            if key.endswith("_dir") or key.endswith("_path"):
                kwargs[key] = Path(value)
            else:
                kwargs[key] = value
        return cls(**kwargs)

    def ensure_dirs(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.asset_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.music_dir.mkdir(parents=True, exist_ok=True)

    def validate(self) -> None:
        if self.target_length_sec <= 0:
            raise ValueError("--length must be greater than 0")
        if self.target_length_sec > 60:
            raise ValueError("--length has a hard cap of 60 seconds")
        if self.fps <= 0:
            raise ValueError("--fps must be greater than 0")
        if self.width != 1080 or self.height != 1920:
            raise ValueError("This pipeline currently enforces 1080x1920 output")
        if self.max_gemini_calls < 1:
            raise ValueError("--max-gemini-calls must be at least 1")
        if self.max_scenes < 1:
            raise ValueError("--max-scenes must be at least 1")
        if self.max_elements_per_scene < 0:
            raise ValueError("--max-elements-per-scene cannot be negative")
        if self.max_captions_per_scene < 0:
            raise ValueError("--max-captions-per-scene cannot be negative")
        if self.target_words_per_second <= 0:
            raise ValueError("target_words_per_second must be greater than 0")

    def job_hash_payload(self, prompt: str) -> dict[str, Any]:
        return {
            "prompt": prompt,
            "target_length_sec": round(float(self.target_length_sec), 3),
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "captions": self.add_captions,
            "voice": self.voice,
            "style": self.style,
            "language_code": self.language_code,
            "planning_model": self.planning_model,
            "tts_model": self.tts_model,
            "allow_gemini_svg_generation": self.allow_gemini_svg_generation,
            "max_scenes": self.max_scenes,
            "max_elements_per_scene": self.max_elements_per_scene,
            "max_captions_per_scene": self.max_captions_per_scene,
            "target_words_per_second": self.target_words_per_second,
        }
