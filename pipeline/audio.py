from __future__ import annotations

import re
import wave
from pathlib import Path

from .config import PipelineConfig
from .models import Scene, Storyboard
from .utils import GeminiBudget, decode_possible_base64, get_genai_client, retry, short_hash


DEFAULT_TTS_RATE = 24000
DEFAULT_TTS_CHANNELS = 1
DEFAULT_TTS_SAMPLE_WIDTH = 2


def _audio_cache_path(scene: Scene, config: PipelineConfig) -> Path:
    return _text_audio_cache_path(scene.narration_text, "scene", config)


def _text_audio_cache_path(text: str, scope: str, config: PipelineConfig) -> Path:
    key = short_hash(
        {
            "stage": "tts",
            "scope": scope,
            "text": text,
            "voice": config.voice,
            "style": config.style,
            "language_code": config.language_code,
            "model": config.tts_model,
            "fallback_model": config.tts_fallback_model,
            "max_narration_chars_per_scene": config.max_narration_chars_per_scene,
        },
        16,
    )
    return config.cache_dir / "audio" / f"{key}.wav"


def _extract_inline_audio(response: object) -> tuple[bytes, str]:
    parts = []
    direct_parts = getattr(response, "parts", None)
    if direct_parts:
        parts.extend(direct_parts)
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        if content is not None:
            parts.extend(getattr(content, "parts", []) or [])

    for part in parts:
        inline_data = getattr(part, "inline_data", None)
        if inline_data is None:
            continue
        data = getattr(inline_data, "data", None)
        if data is None:
            continue
        mime_type = getattr(inline_data, "mime_type", "") or ""
        return decode_possible_base64(data), mime_type
    raise RuntimeError("Gemini TTS response did not contain inline audio data")


def _pcm_rate_from_mime(mime_type: str) -> int:
    match = re.search(r"rate=(\d+)", mime_type)
    return int(match.group(1)) if match else DEFAULT_TTS_RATE


def _write_wav(path: Path, audio_bytes: bytes, mime_type: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if audio_bytes.startswith(b"RIFF") or "wav" in mime_type.lower():
        path.write_bytes(audio_bytes)
        return
    rate = _pcm_rate_from_mime(mime_type)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(DEFAULT_TTS_CHANNELS)
        wav.setsampwidth(DEFAULT_TTS_SAMPLE_WIDTH)
        wav.setframerate(rate)
        wav.writeframes(audio_bytes)


def wav_duration_sec(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        frames = wav.getnframes()
        rate = wav.getframerate()
        return frames / float(rate)


def _call_tts_text(
    text: str,
    config: PipelineConfig,
    client: object,
    model: str,
    budget: GeminiBudget | None,
) -> tuple[bytes, str]:
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai is not installed. Run `pip install -r requirements.txt`.") from exc

    prompt = f"{config.style}\n{text.strip()}"
    if len(prompt) > config.max_narration_chars_per_scene + len(config.style) + 2:
        prompt = prompt[: config.max_narration_chars_per_scene + len(config.style) + 2]
    if budget:
        budget.claim(f"TTS for scene with {model}")
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                language_code=config.language_code,
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.voice)
                ),
            ),
        ),
    )
    return _extract_inline_audio(response)


def generate_scene_audio(
    scene: Scene,
    config: PipelineConfig,
    client: object | None = None,
    budget: GeminiBudget | None = None,
) -> Path:
    return generate_text_audio(scene.narration_text, "scene", config, client, budget)


def generate_text_audio(
    text: str,
    scope: str,
    config: PipelineConfig,
    client: object | None = None,
    budget: GeminiBudget | None = None,
) -> Path:
    wav_path = _text_audio_cache_path(text, scope, config)
    if wav_path.exists():
        return wav_path
    if client is None:
        client = get_genai_client()

    models = [config.tts_model]
    if config.tts_fallback_model and config.tts_fallback_model not in models:
        models.append(config.tts_fallback_model)

    last_error: Exception | None = None
    for model in models:
        try:
            audio_bytes, mime_type = retry(
                lambda: _call_tts_text(text, config, client, model, budget),
                attempts=2,
                base_delay_sec=1.0,
            )
            _write_wav(wav_path, audio_bytes, mime_type)
            return wav_path
        except Exception as exc:  # noqa: BLE001 - try fallback model before failing loudly.
            last_error = exc
    raise RuntimeError(f"Gemini TTS failed for text {text[:60]!r}: {last_error}")


def concat_wavs(inputs: list[Path], output_path: Path) -> Path:
    if not inputs:
        raise ValueError("No WAV files to concatenate")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(inputs[0]), "rb") as first:
        params = first.getparams()
        frames = [first.readframes(first.getnframes())]
    for path in inputs[1:]:
        with wave.open(str(path), "rb") as wav:
            if wav.getparams()[:3] != params[:3]:
                raise RuntimeError(
                    f"Cannot concatenate WAV files with different params: {inputs[0]} and {path}"
                )
            frames.append(wav.readframes(wav.getnframes()))
    with wave.open(str(output_path), "wb") as out:
        out.setparams(params)
        for chunk in frames:
            out.writeframes(chunk)
    return output_path


def _scale_visual_timings(scene: Scene, old_duration: float, new_duration: float) -> None:
    if old_duration <= 0:
        return
    factor = new_duration / old_duration
    for item in [*scene.elements, *scene.captions]:
        item.timing.start_sec *= factor
        if item.timing.duration_sec is not None:
            item.timing.duration_sec *= factor


def generate_audio_track(
    storyboard: Storyboard,
    config: PipelineConfig,
    job_id: str,
    budget: GeminiBudget | None = None,
) -> Path:
    client: object | None = None
    scene_paths: list[Path] = []

    for scene_index, scene in enumerate(storyboard.scenes, 1):
        old_duration = scene.duration_sec

        if scene.script_cues:
            cue_paths: list[Path] = []
            cue_durations: list[float] = []
            for cue in scene.script_cues:
                scope = f"scene-{scene_index}-cue-{cue.index}"
                path = _text_audio_cache_path(cue.text, scope, config)
                if not path.exists() and client is None:
                    client = get_genai_client()
                path = generate_text_audio(cue.text, scope, config, client, budget)
                cue_paths.append(path)
                cue_durations.append(wav_duration_sec(path))

            cursor = 0.0
            for cue, duration in zip(scene.script_cues, cue_durations, strict=True):
                cue.start_sec = cursor
                cue.end_sec = cursor + duration
                cursor = cue.end_sec

            scene.narration_text = " ".join(cue.text.strip() for cue in scene.script_cues).strip()
            scene.actual_audio_duration_sec = max(0.05, cursor)
            scene.duration_sec = max(0.05, cursor)
            scene.refresh_script_srt()
            _scale_visual_timings(scene, old_duration, scene.duration_sec)

            scene_path = config.cache_dir / "audio" / f"{job_id}-scene-{scene_index:02d}.wav"
            path = concat_wavs(cue_paths, scene_path)
            scene_paths.append(path)
            continue

        path = _audio_cache_path(scene, config)
        if not path.exists() and client is None:
            client = get_genai_client()
        path = generate_scene_audio(scene, config, client, budget)
        scene_paths.append(path)
        duration = wav_duration_sec(path)
        scene.actual_audio_duration_sec = duration
        scene.duration_sec = max(0.05, duration)
        scene.refresh_script_srt()
        _scale_visual_timings(scene, old_duration, scene.duration_sec)

    narration_path = config.cache_dir / "audio" / f"{job_id}-narration.wav"
    storyboard.refresh_script_srt()
    return concat_wavs(scene_paths, narration_path)


def find_music_track(config: PipelineConfig) -> Path | None:
    if not config.add_music:
        return None
    exts = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}
    for path in sorted(config.music_dir.glob("*")):
        if path.is_file() and path.suffix.lower() in exts:
            return path
    return None
