from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .config import PipelineConfig
from .models import Caption, Element, Manifest, ManifestEntry, Scene, ScriptCue, Storyboard
from .raster import rasterize_svg_to_png
from .utils import read_json, short_hash, write_json


SAFE_LEFT = 0.08
SAFE_RIGHT = 0.86
SAFE_TOP = 0.07
SAFE_BOTTOM = 0.82


@dataclass(slots=True)
class InlineAsset:
    entry: ManifestEntry
    inner_svg: str
    view_box: str
    root_attrs: str = ""


def _clamp(value: float, lower: float, upper: float) -> float:
    if lower > upper:
        return (lower + upper) / 2
    return max(lower, min(upper, value))


def _ease_out(value: float) -> float:
    value = _clamp(value, 0.0, 1.0)
    return 1 - (1 - value) * (1 - value)


def _asset_inner(svg_text: str) -> tuple[str, str, str]:
    root = ET.fromstring(svg_text)
    view_box = root.attrib.get("viewBox", "0 0 1024 1024")
    ignored_attrs = {"xmlns", "width", "height", "viewBox", "viewbox"}
    attrs = []
    for name, value in root.attrib.items():
        local_name = name.rsplit("}", 1)[-1]
        if local_name in ignored_attrs:
            continue
        attrs.append(f'{html.escape(local_name)}="{html.escape(value)}"')
    inner = "".join(ET.tostring(child, encoding="unicode") for child in root)
    return inner, view_box, " ".join(attrs)


def _load_inline_assets(storyboard: Storyboard, config: PipelineConfig) -> dict[str, InlineAsset]:
    manifest = Manifest.model_validate_json(config.manifest_path.read_text(encoding="utf-8"))
    required_ids = {
        element.asset_id
        for scene in storyboard.scenes
        for element in scene.elements
        if element.asset_id is not None
    }
    assets: dict[str, InlineAsset] = {}
    for asset_id in required_ids:
        entry = manifest.by_id(asset_id)
        if not entry:
            raise RuntimeError(f"Storyboard references missing asset id {asset_id!r}")
        path = config.asset_dir / entry.filename
        if not path.exists():
            raise RuntimeError(f"Manifest references missing SVG file: {path}")
        inner, view_box, root_attrs = _asset_inner(path.read_text(encoding="utf-8"))
        assets[asset_id] = InlineAsset(entry=entry, inner_svg=inner, view_box=view_box, root_attrs=root_attrs)
    return assets


def _background_svg(scene: Scene, scene_index: int, width: int, height: int) -> str:
    if len(scene.background.gradient) >= 2:
        colors = scene.background.gradient
        if scene.background.gradient_direction == "horizontal":
            coords = 'x1="0" y1="0" x2="1" y2="0"'
        elif scene.background.gradient_direction == "diagonal":
            coords = 'x1="0" y1="0" x2="1" y2="1"'
        else:
            coords = 'x1="0" y1="0" x2="0" y2="1"'
        stops = []
        for index, color in enumerate(colors):
            offset = 0 if len(colors) == 1 else index / (len(colors) - 1)
            stops.append(f'<stop offset="{offset:.3f}" stop-color="{html.escape(color)}"/>')
        gradient_id = f"bg{scene_index}"
        return (
            f"<defs><linearGradient id=\"{gradient_id}\" {coords}>"
            f"{''.join(stops)}</linearGradient></defs>"
            f'<rect x="0" y="0" width="{width}" height="{height}" fill="url(#{gradient_id})"/>'
        )
    return f'<rect x="0" y="0" width="{width}" height="{height}" fill="{html.escape(scene.background.color)}"/>'


def _visible_progress(element: Element | Caption, scene: Scene, t_sec: float) -> tuple[bool, float]:
    if not element.timing.contains(t_sec, scene.duration_sec):
        return False, 0.0
    return True, element.timing.progress(t_sec, scene.duration_sec)


def _element_svg(element: Element, scene: Scene, t_sec: float, assets: dict[str, InlineAsset], config: PipelineConfig) -> str:
    visible, progress = _visible_progress(element, scene, t_sec)
    if not visible:
        return ""
    if not element.asset_id or element.asset_id not in assets:
        return ""

    width_px = element.size.width * config.width
    height_px = element.size.height * config.height
    min_x = SAFE_LEFT + element.size.width / 2
    max_x = SAFE_RIGHT - element.size.width / 2
    min_y = SAFE_TOP + element.size.height / 2
    max_y = SAFE_BOTTOM - element.size.height / 2
    center_x = _clamp(element.position.x, min_x, max_x) * config.width
    center_y = _clamp(element.position.y, min_y, max_y) * config.height

    opacity = 1.0
    scale = 1.0
    y_offset = 0.0
    eased = _ease_out(progress)
    if element.animation == "fade":
        opacity = min(1.0, progress * 4.0)
    elif element.animation == "slide":
        y_offset = (1.0 - eased) * config.height * 0.08
        opacity = min(1.0, progress * 3.0)
    elif element.animation == "scale":
        scale = 0.78 + 0.22 * eased
        opacity = min(1.0, progress * 3.0)

    draw_w = width_px * scale
    draw_h = height_px * scale
    x = center_x - draw_w / 2
    y = center_y - draw_h / 2 + y_offset
    asset = assets[element.asset_id]
    return (
        f'<g opacity="{opacity:.3f}">'
        f'<svg x="{x:.2f}" y="{y:.2f}" width="{draw_w:.2f}" height="{draw_h:.2f}" '
        f'viewBox="{html.escape(asset.view_box)}" overflow="visible" color="#ffffff" {asset.root_attrs}>'
        f"{asset.inner_svg}</svg></g>"
    )


def _wrap_caption(text: str, max_chars: int = 26) -> list[str]:
    words = re.split(r"\s+", text.strip())
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:4]


def _caption_box_svg(
    text: str,
    position: object,
    opacity: float,
    config: PipelineConfig,
    *,
    font_size: int = 54,
    max_chars: int = 26,
    fill: str = "#000000",
    fill_opacity: float = 0.58,
    font_family: str = "Arial, Helvetica, sans-serif",
) -> str:
    lines = _wrap_caption(text, max_chars=max_chars)
    line_height = int(font_size * 1.22)
    max_line = max((len(line) for line in lines), default=1)
    box_w = _clamp(max_line * font_size * 0.55 + 96, 360, 920)
    box_h = len(lines) * line_height + 46
    center_x = _clamp(
        position.x,
        SAFE_LEFT + box_w / config.width / 2,
        SAFE_RIGHT - box_w / config.width / 2,
    )
    center_y = _clamp(
        position.y,
        SAFE_TOP + box_h / config.height / 2,
        SAFE_BOTTOM - box_h / config.height / 2,
    )
    x = center_x * config.width - box_w / 2
    y = center_y * config.height - box_h / 2
    tspans = []
    start_y = y + 34 + font_size
    for index, line in enumerate(lines):
        tspans.append(
            f'<tspan x="{center_x * config.width:.2f}" y="{start_y + index * line_height:.2f}">'
            f"{html.escape(line)}</tspan>"
        )
    return (
        f'<g opacity="{opacity:.3f}">'
        f'<rect x="{x:.2f}" y="{y:.2f}" width="{box_w:.2f}" height="{box_h:.2f}" '
        f'rx="18" fill="{fill}" fill-opacity="{fill_opacity:.2f}"/>'
        f'<text text-anchor="middle" font-family="{font_family}" font-size="{font_size}" '
        'font-weight="700" fill="#ffffff">'
        f"{''.join(tspans)}</text></g>"
    )


def _caption_svg(caption: Caption, scene: Scene, t_sec: float, config: PipelineConfig) -> str:
    visible, progress = _visible_progress(caption, scene, t_sec)
    if not visible:
        return ""
    opacity = min(1.0, progress * 5.0)
    return _caption_box_svg(
        caption.text,
        caption.position,
        opacity,
        config,
        font_size=44,
        max_chars=32,
        fill="#102033",
        fill_opacity=0.72,
        font_family="Consolas, Menlo, Arial, Helvetica, sans-serif",
    )


def _script_cue_svg(cue: ScriptCue, t_sec: float, config: PipelineConfig) -> str:
    if not (cue.start_sec <= t_sec <= cue.end_sec):
        return ""
    local_duration = max(0.1, cue.duration_sec)
    progress = _clamp((t_sec - cue.start_sec) / local_duration, 0.0, 1.0)
    opacity = min(1.0, progress * 5.0)
    fade_out = _clamp((cue.end_sec - t_sec) / 0.25, 0.0, 1.0)
    opacity = min(opacity, fade_out)
    return _caption_box_svg(cue.text, cue.position, opacity, config)


def frame_svg(scene: Scene, scene_index: int, t_sec: float, assets: dict[str, InlineAsset], config: PipelineConfig) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{config.width}" height="{config.height}" '
        f'viewBox="0 0 {config.width} {config.height}">',
        _background_svg(scene, scene_index, config.width, config.height),
    ]
    parts.extend(_element_svg(element, scene, t_sec, assets, config) for element in scene.elements)
    if config.add_captions:
        if scene.script_cues:
            spoken_caption_text = {cue.text.strip().lower() for cue in scene.script_cues}
            parts.extend(
                _caption_svg(caption, scene, t_sec, config)
                for caption in scene.captions
                if caption.text.strip().lower() not in spoken_caption_text
            )
            parts.extend(_script_cue_svg(cue, t_sec, config) for cue in scene.script_cues)
        else:
            parts.extend(_caption_svg(caption, scene, t_sec, config) for caption in scene.captions)
    parts.append("</svg>")
    return "".join(parts)


def _expected_frame_count(storyboard: Storyboard, config: PipelineConfig) -> int:
    return sum(max(1, int(round(scene.duration_sec * config.fps))) for scene in storyboard.scenes)


def _render_cache_meta(storyboard: Storyboard, assets: dict[str, InlineAsset], config: PipelineConfig) -> dict[str, object]:
    asset_hashes = {}
    for asset_id, asset in assets.items():
        path = config.asset_dir / asset.entry.filename
        asset_hashes[asset_id] = short_hash(path.read_bytes(), 16)
    return {
        "storyboard": storyboard.model_dump(mode="json"),
        "asset_hashes": asset_hashes,
        "fps": config.fps,
        "width": config.width,
        "height": config.height,
        "captions": config.add_captions,
        "frame_count": _expected_frame_count(storyboard, config),
    }


def render_frames(storyboard: Storyboard, config: PipelineConfig, job_id: str) -> Path:
    assets = _load_inline_assets(storyboard, config)
    frames_dir = config.cache_dir / "frames" / job_id
    frames_dir.mkdir(parents=True, exist_ok=True)
    meta_path = frames_dir / "_render.json"
    expected_count = _expected_frame_count(storyboard, config)
    meta = _render_cache_meta(storyboard, assets, config)
    existing_meta = read_json(meta_path, None)
    existing_frames = list(frames_dir.glob("frame_*.png"))
    if existing_meta == meta and len(existing_frames) == expected_count:
        return frames_dir

    for path in existing_frames:
        path.unlink()

    frame_index = 1
    for scene_index, scene in enumerate(storyboard.scenes):
        scene_frame_count = max(1, int(round(scene.duration_sec * config.fps)))
        for scene_frame in range(scene_frame_count):
            t_sec = min(scene.duration_sec, (scene_frame + 0.5) / config.fps)
            svg_text = frame_svg(scene, scene_index, t_sec, assets, config)
            output_png = frames_dir / f"frame_{frame_index:06d}.png"
            rasterize_svg_to_png(svg_text, output_png, config.width, config.height)
            frame_index += 1

    if frame_index - 1 != expected_count:
        raise RuntimeError(
            f"Rendered {frame_index - 1} frames, expected {expected_count} frames. This should not happen."
        )
    write_json(meta_path, meta)
    return frames_dir
