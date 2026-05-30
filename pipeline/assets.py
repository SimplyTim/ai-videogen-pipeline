from __future__ import annotations

import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .config import PipelineConfig
from .models import Element, Manifest, ManifestEntry, Storyboard
from .raster import rasterize_svg_to_png
from .utils import GeminiBudget, get_genai_client, retry, short_hash, slugify, strip_markdown_fences, write_json


ALLOWED_SVG_TAGS = {
    "svg",
    "g",
    "defs",
    "style",
    "clipPath",
    "mask",
    "linearGradient",
    "radialGradient",
    "stop",
    "rect",
    "circle",
    "ellipse",
    "path",
    "polygon",
    "polyline",
    "line",
    "title",
    "desc",
}
FORBIDDEN_ATTR_RE = re.compile(r"(^on[a-z]+$|href$)", re.IGNORECASE)
TOKEN_RE = re.compile(r"[a-z0-9]{2,}")


@dataclass(slots=True)
class SvgValidationResult:
    view_box: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _tokens(text: str) -> set[str]:
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "that",
        "this",
        "icon",
        "asset",
        "simple",
        "shape",
    }
    return {token for token in TOKEN_RE.findall(text.lower()) if token not in stopwords}


def _extract_svg(raw_text: str) -> str:
    cleaned = strip_markdown_fences(raw_text)
    match = re.search(r"<svg\b.*?</svg>", cleaned, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        raise ValueError("Gemini response did not contain a complete <svg>...</svg> document")
    svg = match.group(0).strip()
    if "xmlns=" not in svg[:200]:
        svg = svg.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return svg


def validate_svg(
    svg_text: str,
    *,
    rasterize: bool = True,
    require_square: bool = True,
    require_origin: bool = True,
    allow_style: bool = False,
) -> SvgValidationResult:
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise ValueError(f"SVG XML parse failed: {exc}") from exc

    if _local_name(root.tag) != "svg":
        raise ValueError("SVG root must be <svg>")

    view_box = root.attrib.get("viewBox")
    if not view_box:
        raise ValueError("SVG must include a square viewBox")

    try:
        x, y, width, height = [float(part) for part in re.split(r"[\s,]+", view_box.strip()) if part]
    except ValueError as exc:
        raise ValueError(f"Invalid SVG viewBox: {view_box!r}") from exc
    if width <= 0 or height <= 0:
        raise ValueError("SVG viewBox width and height must be positive")
    if require_square and abs(width - height) > 0.01:
        raise ValueError("SVG viewBox must be square")
    if require_origin and (x != 0 or y != 0):
        raise ValueError("SVG viewBox must start at 0 0")

    for node in root.iter():
        tag = _local_name(node.tag)
        if tag not in ALLOWED_SVG_TAGS:
            raise ValueError(f"SVG tag <{tag}> is not allowed for reusable assets")
        if tag == "style" and not allow_style:
            raise ValueError("SVG <style> tags are not allowed for generated assets")
        for attr_name, attr_value in node.attrib.items():
            attr = _local_name(attr_name)
            if FORBIDDEN_ATTR_RE.search(attr):
                raise ValueError(f"SVG attribute {attr!r} is not allowed")
            if isinstance(attr_value, str) and re.search(r"(https?:|data:|javascript:)", attr_value, re.IGNORECASE):
                raise ValueError("SVG assets may not reference external or embedded resources")

    if rasterize:
        with tempfile.TemporaryDirectory(prefix="asset-validate-") as tmp:
            rasterize_svg_to_png(svg_text, Path(tmp) / "asset.png", 256, 256)

    return SvgValidationResult(view_box=view_box)


class AssetLibrary:
    def __init__(self, config: PipelineConfig):
        self.config = config
        self.config.ensure_dirs()
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> Manifest:
        if not self.config.manifest_path.exists():
            manifest = Manifest()
            write_json(self.config.manifest_path, manifest.model_dump(mode="json"))
            return manifest
        return Manifest.model_validate_json(self.config.manifest_path.read_text(encoding="utf-8"))

    def save(self) -> None:
        write_json(self.config.manifest_path, self.manifest.model_dump(mode="json"))

    def find_match(self, element: Element) -> ManifestEntry | None:
        query_text = f"{element.asset_query} {element.description}"
        query_tokens = _tokens(query_text)
        best_entry: ManifestEntry | None = None
        best_score = 0.0
        for entry in self.manifest.assets:
            entry_text = f"{entry.label} {entry.description} {' '.join(entry.tags)}"
            entry_tokens = _tokens(entry_text)
            if not entry_tokens:
                continue
            exact_label = element.asset_query.strip().lower() == entry.label.strip().lower()
            overlap = len(query_tokens & entry_tokens)
            score = overlap / max(1, len(query_tokens))
            if exact_label:
                score += 1.0
            if any(tag.lower() in element.asset_query.lower() for tag in entry.tags):
                score += 0.15
            if score > best_score:
                best_score = score
                best_entry = entry
        if best_entry and (best_score >= 0.42 or element.asset_query.lower() in best_entry.label.lower()):
            path = self.config.asset_dir / best_entry.filename
            if path.exists():
                return best_entry
        return None

    def add_asset(self, svg_text: str, element: Element, source_prompt: str) -> ManifestEntry:
        validation = validate_svg(svg_text, rasterize=True)
        asset_id = f"svg_{short_hash(svg_text, 16)}"
        label = element.asset_query.strip()[:80] or "generated asset"
        filename = f"{slugify(label, 42)}-{asset_id[-8:]}.svg"
        path = self.config.asset_dir / filename

        if not path.exists():
            path.write_text(svg_text, encoding="utf-8")

        existing = self.manifest.by_id(asset_id)
        if existing:
            return existing

        tags = sorted((_tokens(label) | _tokens(element.description)) - {"generated"})[:12]
        entry = ManifestEntry(
            id=asset_id,
            filename=filename,
            label=label,
            description=element.description.strip()[:240],
            tags=tags,
            viewBox=validation.view_box,
            source_prompt=source_prompt,
        )
        self.manifest.assets.append(entry)
        self.save()
        return entry


def _asset_prompt(element: Element) -> str:
    return f"""Generate one standalone SVG asset for a reusable short-form video library.

Asset label: {element.asset_query}
Asset description: {element.description}

Rules:
- Return only SVG markup, no markdown.
- Transparent background.
- Square viewBox exactly "0 0 1024 1024".
- Use only simple SVG shapes: rect, circle, ellipse, line, polyline, polygon, path, g, defs, linearGradient, radialGradient, stop.
- Do not use external images, scripts, CSS files, animation tags, filters, masks, clip paths, or text.
- Make the asset bold and legible at small sizes."""


def generate_svg_asset(
    element: Element,
    config: PipelineConfig,
    client: object | None = None,
    budget: GeminiBudget | None = None,
) -> str:
    if client is None:
        client = get_genai_client()
    try:
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai is not installed. Run `pip install -r requirements.txt`.") from exc

    prompt = _asset_prompt(element)
    models = [config.planning_model, config.svg_retry_model]
    last_error: Exception | None = None
    for model in models:
        for attempt in range(1, 3):
            repair_note = "" if not last_error else f"\nPrevious SVG failed validation: {last_error}\nFix it."
            response = retry(
                lambda: _call_svg_model(client, model, prompt + repair_note, types, budget),
                attempts=3,
                base_delay_sec=1.25,
            )
            text = getattr(response, "text", None)
            if not text:
                last_error = RuntimeError("Gemini returned an empty SVG response")
                continue
            try:
                svg_text = _extract_svg(text)
                validate_svg(svg_text, rasterize=True)
                return svg_text
            except Exception as exc:  # noqa: BLE001 - validation error becomes retry context.
                last_error = exc
                if attempt == 2:
                    break
    raise RuntimeError(f"Could not generate a valid SVG for {element.asset_query!r}: {last_error}")


def _call_svg_model(
    client: object,
    model: str,
    contents: str,
    types: object,
    budget: GeminiBudget | None,
) -> object:
    if budget:
        budget.claim(f"SVG generation with {model}")
    return client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(temperature=0.25),
    )


def resolve_assets(storyboard: Storyboard, config: PipelineConfig, budget: GeminiBudget | None = None) -> Storyboard:
    library = AssetLibrary(config)
    client: object | None = None
    missing: list[str] = []

    for scene in storyboard.scenes:
        for element in scene.elements:
            if element.asset_id and library.manifest.by_id(element.asset_id):
                continue
            match = library.find_match(element)
            if match:
                element.asset_id = match.id
                continue
            if not config.allow_gemini_svg_generation:
                missing.append(element.asset_query)
                continue
            if client is None:
                client = get_genai_client()
            svg_text = generate_svg_asset(element, config, client, budget)
            entry = library.add_asset(svg_text, element, _asset_prompt(element))
            element.asset_id = entry.id

    library.save()
    if missing:
        sample_labels = ", ".join(entry.label for entry in library.manifest.assets[:20])
        raise RuntimeError(
            "No reusable SVG asset matched these storyboard asset queries: "
            f"{', '.join(sorted(set(missing)))}. "
            "Open-source assets are seeded by default; add a matching SVG to assets/svg plus manifest, "
            "or rerun with --generate-missing-assets to allow Gemini SVG generation. "
            f"Available labels include: {sample_labels}"
        )
    return storyboard
