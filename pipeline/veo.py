from __future__ import annotations

import argparse
import subprocess
import time
from pathlib import Path

from google.genai import types

from .compose import _ffmpeg_exe
from .utils import get_genai_client, print_step, short_hash, slugify, write_json


DEFAULT_MODEL = "veo-3.1-generate-preview"


MEDIEVAL_STORY_SEGMENTS = [
    (
        "A cinematic vertical fantasy film opening. Moonlit medieval kingdom of Eldermere, rain on slate roofs, "
        "a lone young knight named Rowan rides through a misty forest toward a ruined bell tower. Native audio: "
        "distant thunder, horse hooves, low orchestral strings. No subtitles or on-screen text."
    ),
    (
        "Inside the ruined bell tower, torchlight reveals an ancient stone door covered in glowing runes. Rowan "
        "places a bronze key into the lock. The tower bell moves by itself but makes no sound. Native audio: "
        "torch crackle, stone grinding, one whispered line from Rowan: 'The old stories were true.' No subtitles."
    ),
    (
        "A secret stair spirals down beneath the tower into a vast underground hall. Medieval banners hang in dust. "
        "At the center, a sleeping dragon made of black glass breathes faint blue fire. Camera glides forward, "
        "epic, moody, cinematic. Native audio: echoing footsteps, rumbling dragon breath. No text."
    ),
    (
        "Rowan finds Princess Elowen alive inside a crystal prison, suspended above a pool of silver water. She opens "
        "her eyes and silently points behind him. Reflections in the water show shadow soldiers approaching. Native "
        "audio: swelling strings, crystal hum, faint armor clatter. No subtitles."
    ),
    (
        "A chase through underground medieval catacombs. Rowan carries the bronze key while Elowen runs beside him. "
        "Shadow soldiers pour from archways, their helmets empty and glowing. Fast handheld cinematic motion. Native "
        "audio: running footsteps, metallic shrieks, pounding drums. No text."
    ),
    (
        "They burst into a forgotten royal chapel beneath the castle. A stained-glass window shows the same dragon "
        "crowned as king. Elowen realizes the dragon is her ancestor, cursed to guard the realm. Native audio: "
        "choral voices, storm rumble, Elowen whispers: 'It is not the monster. It is the seal.' No subtitles."
    ),
    (
        "The black-glass dragon awakens and rises behind them, enormous but sorrowful. Rowan raises the bronze key; "
        "it melts into golden light. The shadow soldiers kneel, then suddenly turn toward the castle above. Native "
        "audio: dragon roar, choir, cracking stone. No text."
    ),
    (
        "Cliffhanger ending. Dawn breaks over Eldermere Castle as its highest tower splits open, revealing a giant "
        "eye beneath the stones. Rowan, Elowen, and the dragon stare upward in horror. The camera rushes into the "
        "dark eye. Cut to black before the creature emerges. Native audio: deep heartbeat, gasp, abrupt silence. "
        "No subtitles or end card."
    ),
]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.veo",
        description="Generate and stitch a short Veo comparison video.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "prompt",
        nargs="?",
        default="A dark cinematic medieval cliffhanger story.",
        help="High-level story theme. The built-in medieval sequence is used unless --single-prompt is passed.",
    )
    parser.add_argument("--segments", type=int, default=8, help="Number of 8-second clips to generate.")
    parser.add_argument("--duration", type=int, default=8, help="Duration of each Veo clip in seconds.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Veo model id.")
    parser.add_argument("--resolution", default="720p", help="Veo resolution.")
    parser.add_argument("--aspect-ratio", default="9:16", help="Veo aspect ratio.")
    parser.add_argument("--output-dir", type=Path, default=Path("output/veo"), help="Output directory.")
    parser.add_argument("--poll-seconds", type=int, default=10, help="Polling interval.")
    parser.add_argument("--max-wait-minutes", type=int, default=20, help="Max wait for each clip.")
    parser.add_argument("--single-prompt", action="store_true", help="Use the prompt as-is for every segment.")
    return parser


def _segment_prompts(prompt: str, count: int, single_prompt: bool) -> list[str]:
    if single_prompt:
        return [prompt] * count
    prompts = MEDIEVAL_STORY_SEGMENTS[:count]
    if count > len(prompts):
        prompts.extend([MEDIEVAL_STORY_SEGMENTS[-1]] * (count - len(prompts)))
    return [
        f"{segment}\n\nOverall story brief: {prompt}\nKeep the look consistent: medieval fantasy, realistic cinematic lighting, vertical phone video, dramatic but not graphic."
        for segment in prompts
    ]


def _generate_clip(
    prompt: str,
    output_path: Path,
    *,
    model: str,
    duration: int,
    resolution: str,
    aspect_ratio: str,
    poll_seconds: int,
    max_wait_minutes: int,
) -> Path:
    if output_path.exists() and output_path.stat().st_size > 0:
        print_step(f"Reusing Veo clip {output_path.name}")
        return output_path

    client = get_genai_client()
    operation = client.models.generate_videos(
        model=model,
        prompt=prompt,
        config=types.GenerateVideosConfig(
            number_of_videos=1,
            duration_seconds=duration,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
        ),
    )

    deadline = time.monotonic() + max_wait_minutes * 60
    while not operation.done:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Timed out waiting for Veo operation {operation.name}")
        print_step(f"Waiting for Veo operation {operation.name}")
        time.sleep(poll_seconds)
        operation = client.operations.get(operation)

    if not operation.response or not operation.response.generated_videos:
        raise RuntimeError(f"Veo operation completed without a generated video: {operation}")

    generated_video = operation.response.generated_videos[0]
    client.files.download(file=generated_video.video)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generated_video.video.save(str(output_path))
    return output_path


def _concat_clips(clips: list[Path], output_path: Path) -> Path:
    ffmpeg = _ffmpeg_exe()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_path = output_path.with_suffix(".concat.txt")
    lines = []
    for clip in clips:
        safe_path = clip.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{safe_path}'")
    list_path.write_text("\n".join(lines), encoding="utf-8")

    copy_args = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        str(output_path),
    ]
    proc = subprocess.run(copy_args, text=True, capture_output=True, check=False)
    if proc.returncode == 0:
        return output_path

    reencode_args = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-vf",
        "scale=1080:1920:force_original_aspect_ratio=disable,setsar=1,format=yuv420p",
        "-r",
        "30",
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
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    proc = subprocess.run(reencode_args, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "ffmpeg concat failed")
    return output_path


def run(args: argparse.Namespace) -> Path:
    prompts = _segment_prompts(args.prompt, args.segments, args.single_prompt)
    job_id = short_hash(
        {
            "prompt": args.prompt,
            "prompts": prompts,
            "model": args.model,
            "duration": args.duration,
            "resolution": args.resolution,
            "aspect_ratio": args.aspect_ratio,
        },
        12,
    )
    job_dir = args.output_dir / f"{slugify(args.prompt, 48)}-{job_id}"
    job_dir.mkdir(parents=True, exist_ok=True)
    write_json(job_dir / "veo_prompts.json", {"model": args.model, "prompts": prompts})

    clips: list[Path] = []
    for index, segment_prompt in enumerate(prompts, 1):
        print_step(f"Generating Veo clip {index}/{len(prompts)}")
        clip_path = job_dir / f"clip_{index:02d}.mp4"
        clips.append(
            _generate_clip(
                segment_prompt,
                clip_path,
                model=args.model,
                duration=args.duration,
                resolution=args.resolution,
                aspect_ratio=args.aspect_ratio,
                poll_seconds=args.poll_seconds,
                max_wait_minutes=args.max_wait_minutes,
            )
        )

    output_path = job_dir / "medieval_cliffhanger_veo.mp4"
    print_step("Concatenating Veo clips")
    return _concat_clips(clips, output_path)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
        print(output)
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI prints a concise failure.
        print_step(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
