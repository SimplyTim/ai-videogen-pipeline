from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from .assets import resolve_assets
from .audio import generate_audio_track
from .compose import compose_video
from .config import PipelineConfig
from .open_source_assets import seed_open_source_assets
from .plan import build_storyboard
from .render import render_frames
from .utils import GeminiBudget, print_step, short_hash, slugify, write_json


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline",
        description="Generate a 1080x1920 short-form video from one prompt.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("prompt", help="Text prompt describing the desired short video.")
    parser.add_argument("--config", type=Path, help="Optional JSON config file.")
    parser.add_argument("--length", type=float, help="Target length in seconds. Hard cap: 60.")
    parser.add_argument("--voice", help="Gemini prebuilt TTS voice name.")
    parser.add_argument("--style", help="TTS style instruction prepended to every scene narration.")
    parser.add_argument("--fps", type=int, help="Frames per second.")
    parser.add_argument("--output-dir", type=Path, help="Directory for final MP4 and storyboard JSON.")
    parser.add_argument("--cache-dir", type=Path, help="Directory for cached plans, audio, and frames.")
    parser.add_argument("--no-captions", action="store_true", help="Do not render storyboard captions.")
    parser.add_argument("--music", action="store_true", help="Mix the first local track found in assets/music at low volume.")
    parser.add_argument("--planning-model", help="Gemini model for storyboard planning and first-pass SVG generation.")
    parser.add_argument("--svg-retry-model", help="Gemini model used after SVG validation failures.")
    parser.add_argument("--tts-model", help="Primary Gemini TTS model.")
    parser.add_argument("--tts-fallback-model", help="Fallback Gemini TTS model.")
    parser.add_argument("--skip-open-source-assets", action="store_true", help="Do not seed curated Lucide SVG assets.")
    parser.add_argument(
        "--generate-missing-assets",
        action="store_true",
        help="Allow Gemini SVG generation if no open-source/local asset matches.",
    )
    parser.add_argument("--max-gemini-calls", type=int, help="Hard cap on Gemini API calls for this run.")
    parser.add_argument("--max-scenes", type=int, help="Maximum storyboard scenes.")
    parser.add_argument("--max-elements-per-scene", type=int, help="Maximum SVG elements per scene.")
    parser.add_argument("--max-captions-per-scene", type=int, help="Maximum captions per scene.")
    parser.add_argument(
        "--visual-domain",
        choices=["auto", "general", "math-cs"],
        help="Planner visual style. Use math-cs for diagram-heavy math and computer science explainers.",
    )
    parser.add_argument("--debug", action="store_true", help="Print a traceback on failure.")
    return parser


def _load_config(args: argparse.Namespace) -> PipelineConfig:
    config = PipelineConfig.from_file(args.config) if args.config else PipelineConfig()
    if args.length is not None:
        config.target_length_sec = args.length
    if args.voice:
        config.voice = args.voice
    if args.style:
        config.style = args.style
    if args.fps is not None:
        config.fps = args.fps
    if args.output_dir is not None:
        config.output_dir = args.output_dir
    if args.cache_dir is not None:
        config.cache_dir = args.cache_dir
    if args.no_captions:
        config.add_captions = False
    if args.music:
        config.add_music = True
    if args.planning_model:
        config.planning_model = args.planning_model
    if args.svg_retry_model:
        config.svg_retry_model = args.svg_retry_model
    if args.tts_model:
        config.tts_model = args.tts_model
    if args.tts_fallback_model:
        config.tts_fallback_model = args.tts_fallback_model
    if args.skip_open_source_assets:
        config.seed_open_source_assets = False
    if args.generate_missing_assets:
        config.allow_gemini_svg_generation = True
    if args.max_gemini_calls is not None:
        config.max_gemini_calls = args.max_gemini_calls
    if args.max_scenes is not None:
        config.max_scenes = args.max_scenes
    if args.max_elements_per_scene is not None:
        config.max_elements_per_scene = args.max_elements_per_scene
    if args.max_captions_per_scene is not None:
        config.max_captions_per_scene = args.max_captions_per_scene
    if args.visual_domain is not None:
        config.visual_domain = args.visual_domain
    config.validate()
    config.ensure_dirs()
    return config


def run(prompt: str, config: PipelineConfig) -> Path:
    job_id = short_hash(config.job_hash_payload(prompt), 12)
    output_slug = f"{slugify(prompt)}-{job_id}"
    budget = GeminiBudget(config.max_gemini_calls)

    if config.seed_open_source_assets:
        print_step("Seeding open-source SVG assets")
        result = seed_open_source_assets(config)
        print_step(
            f"SVG assets ready: {result.reused} reused, {result.downloaded} downloaded, {result.failed} skipped"
        )

    print_step("Planning storyboard")
    storyboard = build_storyboard(prompt, config, budget)

    print_step("Resolving SVG assets")
    storyboard = resolve_assets(storyboard, config, budget)

    print_step("Generating narration audio")
    narration_wav = generate_audio_track(storyboard, config, job_id, budget)

    print_step("Rendering SVG frames")
    frames_dir = render_frames(storyboard, config, job_id)

    print_step("Compositing MP4")
    output_path = compose_video(storyboard, frames_dir, narration_wav, config, output_slug)

    storyboard_path = config.output_dir / f"{output_slug}.storyboard.json"
    storyboard.refresh_script_srt()
    write_json(storyboard_path, storyboard.model_dump(mode="json"))
    print_step(f"Wrote {output_path}")
    print_step(f"Wrote {storyboard_path}")
    return output_path


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        config = _load_config(args)
        output_path = run(args.prompt, config)
        print(output_path)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI prints clear failures.
        print_step(f"ERROR: {exc}")
        if args.debug:
            traceback.print_exc()
        return 1
