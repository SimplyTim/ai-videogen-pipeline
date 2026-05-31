from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .config import PipelineConfig
from .models import Storyboard
from .open_source_assets import available_asset_labels
from .utils import GeminiBudget, extract_json_text, get_genai_client, read_json, retry, short_hash, write_json


SYSTEM_INSTRUCTION = """You create strict JSON storyboards for 9:16 short-form educational videos.
Plan only SVG-shape-friendly visuals: icons, diagrams, formulas, arrows, charts, callouts, code/data diagrams, and abstract backgrounds.
Use normalized positions where x/y are center points from 0 to 1. Keep important content away from bottom 15% and the right edge.
Use concise narration that can be spoken naturally within each scene duration.
Return valid JSON only."""


MATH_CS_TERMS = {
    "algorithm",
    "api",
    "binary",
    "calculus",
    "code",
    "computer",
    "complexity",
    "database",
    "data",
    "derivative",
    "function",
    "graph",
    "integral",
    "logic",
    "machine learning",
    "math",
    "matrix",
    "network",
    "proof",
    "programming",
    "recursion",
    "server",
    "sorting",
    "statistics",
    "tree",
    "vector",
}


def _cache_path(prompt: str, config: PipelineConfig) -> Path:
    key = short_hash(
        {
            "stage": "plan",
            "prompt": prompt,
            "target_length_sec": config.target_length_sec,
            "model": config.planning_model,
            "captions": config.add_captions,
            "max_scenes": config.max_scenes,
            "max_elements_per_scene": config.max_elements_per_scene,
            "max_captions_per_scene": config.max_captions_per_scene,
            "max_narration_chars_per_scene": config.max_narration_chars_per_scene,
            "target_words_per_second": config.target_words_per_second,
            "visual_domain": config.visual_domain,
            "schema_version": 3,
        }
    )
    return config.cache_dir / "plans" / f"{key}.json"


def _schema() -> dict[str, Any]:
    schema = Storyboard.model_json_schema()
    schema.pop("title", None)
    return schema


def _postprocess_storyboard(storyboard: Storyboard, config: PipelineConfig) -> Storyboard:
    storyboard.scenes = storyboard.scenes[: config.max_scenes]
    for scene in storyboard.scenes:
        scene.script_cues = scene.script_cues[: config.max_captions_per_scene]
        scene.narration_text = scene.narration_text.strip()[: config.max_narration_chars_per_scene]
        if scene.script_cues:
            scene.narration_text = " ".join(cue.text.strip() for cue in scene.script_cues).strip()
        scene.elements = scene.elements[: config.max_elements_per_scene]
        scene.captions = scene.captions[: config.max_captions_per_scene] if config.add_captions else []
    if abs(storyboard.total_duration_sec - config.target_length_sec) > 0.05:
        storyboard.rescale_to(config.target_length_sec)
    return storyboard


def _parse_storyboard(raw_text: str, prompt: str, config: PipelineConfig) -> Storyboard:
    json_text = extract_json_text(raw_text)
    storyboard = Storyboard.model_validate_json(json_text)
    storyboard.prompt = prompt
    storyboard.target_length_sec = config.target_length_sec
    return _postprocess_storyboard(storyboard, config)


def _compact_prompt(prompt: str, config: PipelineConfig) -> str:
    text = " ".join(prompt.split())
    if len(text) <= config.max_prompt_chars:
        return text
    return text[: config.max_prompt_chars].rsplit(" ", 1)[0] + " [truncated]"


def _is_math_cs_prompt(prompt: str, config: PipelineConfig) -> bool:
    if config.visual_domain == "math-cs":
        return True
    if config.visual_domain == "general":
        return False
    prompt_lc = prompt.lower()
    return any(term in prompt_lc for term in MATH_CS_TERMS)


def _domain_prompt(math_cs: bool) -> str:
    if not math_cs:
        return (
            "- Prefer diagrammatic educational visuals over story scenes.\n"
            "- Element asset_query values should be reusable library labels like 'water droplet', 'sun', 'cycle arrows', "
            "'line chart', or 'calculator'.\n"
        )
    return (
        "- This is a math/computer-science explainer. Avoid character-driven story scenes.\n"
        "- Use clean board-style visuals: formulas, axes, graphs, flow arrows, code blocks, binary trees, databases, "
        "servers, networks, stacks, queues, matrices, and logic/operator symbols.\n"
        "- Use captions for optional formula labels or diagram callouts, not for spoken subtitles. Spoken subtitles come "
        "from script_cues and must exactly match narration.\n"
        "- Choose asset_query labels from the math/CS library whenever possible, such as 'math symbols', 'function curve', "
        "'integral symbol', 'pi symbol', 'axis x', 'axis y', 'graph network', 'binary tree', 'code block', "
        "'database', 'server', 'stack', 'queue', 'matrix', 'logic branch', 'sort ascending', or 'algorithm flow'.\n"
    )


def build_storyboard(prompt: str, config: PipelineConfig, budget: GeminiBudget | None = None) -> Storyboard:
    cache_path = _cache_path(prompt, config)
    if cache_path.exists():
        cached = Storyboard.model_validate(read_json(cache_path, {}))
        cached.prompt = prompt
        if abs(cached.total_duration_sec - config.target_length_sec) > 0.2:
            cached.rescale_to(config.target_length_sec)
        return _postprocess_storyboard(cached, config)

    client = get_genai_client()
    compact_prompt = _compact_prompt(prompt, config)
    math_cs = _is_math_cs_prompt(prompt, config)
    preferred_tags = (
        "math",
        "cs",
        "computer-science",
        "algorithm",
        "data",
        "code",
        "function",
        "graph",
        "operator",
        "calculus",
        "tree",
        "database",
        "network",
    ) if math_cs else ()
    labels = available_asset_labels(config, config.max_asset_labels_in_prompt, preferred_tags=preferred_tags)
    target_words = max(8, int(config.target_length_sec * config.target_words_per_second))
    label_hint = ""
    if labels:
        label_hint = (
            "\nUse these existing asset_query labels exactly; when no perfect asset exists, choose the closest label: "
            + ", ".join(labels)
            + "."
        )

    user_prompt = (
        f"Create a storyboard for a {config.target_length_sec:.1f}s vertical short video.\n"
        f"User prompt: {compact_prompt}\n\n"
        "Constraints:\n"
        f"- 3 to {config.max_scenes} scenes, with total scene duration matching the target length.\n"
        "- Each scene needs background, SVG-ready elements, and script_cues.\n"
        "- script_cues are the authoritative caption + narration script, SRT-style, relative to the scene.\n"
        "- narration_text must exactly equal that scene's script_cues text joined with spaces.\n"
        f"- Total narration across all script_cues must be about {target_words} words or fewer.\n"
        "- Keep each script cue short: one spoken sentence or phrase.\n"
        "- Captions rendered on screen come from script_cues, so cue text must match spoken narration exactly.\n"
        f"- Use at most {config.max_elements_per_scene} elements per scene.\n"
        f"- Use at most {config.max_captions_per_scene} script_cues per scene.\n"
        f"- Use at most {config.max_captions_per_scene} optional formula/callout captions per scene.\n"
        f"- Keep narration_text under {config.max_narration_chars_per_scene} characters per scene.\n"
        f"{_domain_prompt(math_cs)}"
        "- Avoid photorealistic requests; describe clean, legible SVG-friendly shapes.\n"
        "- Every visual element timing should describe what is on screen during that cue or scene."
        f"{label_hint}"
    )

    last_validation_error: str | None = None

    def call_model() -> Storyboard:
        nonlocal last_validation_error
        try:
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("google-genai is not installed. Run `pip install -r requirements.txt`.") from exc

        contents = user_prompt
        if last_validation_error:
            contents += (
                "\n\nYour previous JSON failed validation. Fix the JSON so it matches the response schema. "
                f"Validation error: {last_validation_error}"
            )

        if budget:
            budget.claim("storyboard planning")
        response = client.models.generate_content(
            model=config.planning_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_json_schema=_schema(),
                temperature=0.25,
            ),
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini planner returned an empty response")
        try:
            return _parse_storyboard(text, prompt, config)
        except ValidationError as exc:
            last_validation_error = str(exc)
            raise

    storyboard = retry(call_model, attempts=3, base_delay_sec=1.5)
    write_json(cache_path, storyboard.model_dump(mode="json"))
    return storyboard
