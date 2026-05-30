from __future__ import annotations

from pathlib import Path

from .audio import find_music_track
from .config import PipelineConfig
from .models import Storyboard
from .utils import print_step, require_command, run_command, short_hash, write_json


def _ffmpeg_exe() -> str:
    try:
        return require_command("ffmpeg", "Install ffmpeg and make sure it is on PATH.")
    except RuntimeError:
        try:
            import imageio_ffmpeg
        except ImportError as exc:
            raise RuntimeError(
                "Missing ffmpeg. Install ffmpeg on PATH or install Python dependency `imageio-ffmpeg`."
            ) from exc
        return imageio_ffmpeg.get_ffmpeg_exe()


def _compose_meta(
    storyboard: Storyboard,
    frames_dir: Path,
    narration_wav: Path,
    music_track: Path | None,
    config: PipelineConfig,
) -> dict[str, object]:
    frame_meta = frames_dir / "_render.json"
    return {
        "storyboard": storyboard.model_dump(mode="json"),
        "render_meta_hash": short_hash(frame_meta.read_bytes(), 16) if frame_meta.exists() else None,
        "narration_hash": short_hash(narration_wav.read_bytes(), 16),
        "music_hash": short_hash(music_track.read_bytes(), 16) if music_track else None,
        "fps": config.fps,
        "width": config.width,
        "height": config.height,
    }


def compose_video(
    storyboard: Storyboard,
    frames_dir: Path,
    narration_wav: Path,
    config: PipelineConfig,
    output_slug: str,
) -> Path:
    ffmpeg = _ffmpeg_exe()
    output_path = config.output_dir / f"{output_slug}.mp4"
    meta_path = config.output_dir / f"{output_slug}.compose.json"
    music_track = find_music_track(config)
    if config.add_music and music_track is None:
        print_step(f"No local music file found in {config.music_dir}; continuing with narration only.")

    meta = _compose_meta(storyboard, frames_dir, narration_wav, music_track, config)
    if output_path.exists() and meta_path.exists():
        try:
            import json

            if json.loads(meta_path.read_text(encoding="utf-8")) == meta:
                return output_path
        except Exception:
            pass

    frame_pattern = str(frames_dir / "frame_%06d.png")
    vf = f"scale={config.width}:{config.height}:force_original_aspect_ratio=disable,setsar=1,format=yuv420p"
    duration = max(0.05, storyboard.total_duration_sec)

    args = [
        ffmpeg,
        "-y",
        "-framerate",
        str(config.fps),
        "-i",
        frame_pattern,
        "-i",
        str(narration_wav),
    ]

    if music_track:
        args.extend(["-stream_loop", "-1", "-i", str(music_track)])
        args.extend(
            [
                "-filter_complex",
                (
                    f"[2:a]volume=0.12,atrim=0:{duration:.3f},asetpts=PTS-STARTPTS[m];"
                    "[1:a][m]amix=inputs=2:duration=first:dropout_transition=1[a]"
                ),
                "-map",
                "0:v:0",
                "-map",
                "[a]",
            ]
        )
    else:
        args.extend(["-map", "0:v:0", "-map", "1:a:0"])

    args.extend(
        [
            "-vf",
            vf,
            "-r",
            str(config.fps),
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-t",
            f"{duration:.3f}",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )

    run_command(args)
    write_json(meta_path, meta)
    return output_path
