from __future__ import annotations

import urllib.error
import urllib.request
import time
from dataclasses import dataclass

from .assets import validate_svg
from .config import PipelineConfig
from .models import Manifest, ManifestEntry
from .utils import short_hash, slugify, write_json


LUCIDE_RAW_BASE = "https://raw.githubusercontent.com/lucide-icons/lucide/main/icons"
BOOTSTRAP_RAW_BASE = "https://raw.githubusercontent.com/twbs/icons/main/icons"
SVGREPO_SHOW_BASE = "https://www.svgrepo.com/show"


@dataclass(frozen=True, slots=True)
class CuratedIcon:
    slug: str
    label: str
    description: str
    tags: tuple[str, ...]
    provider: str = "lucide"
    remote_id: str = ""

    @property
    def url(self) -> str:
        if self.provider == "svgrepo":
            return f"{SVGREPO_SHOW_BASE}/{self.remote_id}/{self.slug}.svg"
        base = BOOTSTRAP_RAW_BASE if self.provider == "bootstrap" else LUCIDE_RAW_BASE
        return f"{base}/{self.slug}.svg"

    @property
    def license_name(self) -> str:
        if self.provider == "svgrepo":
            return "CC0"
        return "MIT" if self.provider == "bootstrap" else "ISC"


@dataclass(slots=True)
class SeedResult:
    downloaded: int = 0
    reused: int = 0
    failed: int = 0


CURATED_LUCIDE_ICONS: tuple[CuratedIcon, ...] = (
    CuratedIcon("sun", "sun", "Sun icon for heat, light, daytime, or energy.", ("sun", "light", "heat", "day")),
    CuratedIcon("cloud", "cloud", "Cloud icon for weather, sky, vapor, or storage.", ("cloud", "weather", "sky", "vapor")),
    CuratedIcon("cloud-rain", "rain cloud", "Rain cloud icon for rainfall and weather scenes.", ("rain", "cloud", "water", "weather")),
    CuratedIcon("droplet", "water droplet", "Water droplet icon for liquid, rain, hydration, or condensation.", ("water", "drop", "droplet", "rain")),
    CuratedIcon("droplets", "water droplets", "Multiple droplets icon for rain, water, or splash visuals.", ("water", "drops", "rain", "splash")),
    CuratedIcon("audio-waveform", "waveform", "Waveform lines for sound, signal, rhythm, or motion.", ("wave", "sound", "signal", "motion")),
    CuratedIcon("wind", "wind", "Wind lines for air movement, weather, or speed.", ("wind", "air", "weather", "motion")),
    CuratedIcon("snowflake", "snowflake", "Snowflake icon for cold, winter, ice, or freezing.", ("snow", "ice", "cold", "winter")),
    CuratedIcon("leaf", "leaf", "Leaf icon for plants, nature, growth, or sustainability.", ("leaf", "plant", "nature", "growth")),
    CuratedIcon("tree-pine", "tree", "Tree icon for forests, ecology, outdoors, or growth.", ("tree", "forest", "nature", "plant")),
    CuratedIcon("flame", "flame", "Flame icon for fire, heat, energy, or danger.", ("fire", "flame", "heat", "energy")),
    CuratedIcon("zap", "lightning bolt", "Lightning bolt icon for electricity, power, speed, or energy.", ("electricity", "power", "energy", "bolt")),
    CuratedIcon("battery", "battery", "Battery icon for stored energy, charging, or power.", ("battery", "energy", "power", "charge")),
    CuratedIcon("recycle", "recycle", "Recycle icon for sustainability, reuse, and circular systems.", ("recycle", "reuse", "sustainability", "cycle")),
    CuratedIcon("globe", "globe", "Globe icon for Earth, world, geography, or climate.", ("earth", "world", "globe", "planet")),
    CuratedIcon("map", "map", "Map icon for geography, routes, or location.", ("map", "location", "geography", "route")),
    CuratedIcon("compass", "compass", "Compass icon for direction, navigation, or exploration.", ("compass", "direction", "navigation", "explore")),
    CuratedIcon("rocket", "rocket", "Rocket icon for space, launch, growth, or acceleration.", ("rocket", "space", "launch", "growth")),
    CuratedIcon("atom", "atom", "Atom icon for science, chemistry, physics, or particles.", ("atom", "science", "physics", "chemistry")),
    CuratedIcon("dna", "dna", "DNA icon for biology, genetics, cells, or life science.", ("dna", "biology", "genetics", "science")),
    CuratedIcon("microscope", "microscope", "Microscope icon for science, research, and discovery.", ("microscope", "science", "research", "biology")),
    CuratedIcon("flask-conical", "flask", "Conical flask icon for chemistry, experiments, and labs.", ("flask", "chemistry", "lab", "experiment")),
    CuratedIcon("brain", "brain", "Brain icon for learning, ideas, memory, or thinking.", ("brain", "learning", "mind", "idea")),
    CuratedIcon("lightbulb", "lightbulb", "Lightbulb icon for ideas, learning, and insight.", ("idea", "lightbulb", "insight", "learning")),
    CuratedIcon("book-open", "open book", "Open book icon for education, reading, and learning.", ("book", "education", "reading", "learning")),
    CuratedIcon("graduation-cap", "graduation cap", "Graduation cap icon for school, lessons, and achievement.", ("school", "education", "lesson", "learning")),
    CuratedIcon("calculator", "calculator", "Calculator icon for math, finance, and numbers.", ("math", "calculator", "numbers", "finance")),
    CuratedIcon("chart-line", "line chart", "Line chart icon for trends, data, and growth.", ("chart", "data", "trend", "growth")),
    CuratedIcon("chart-no-axes-column", "bar chart", "Bar chart icon for data comparison and statistics.", ("chart", "data", "bar", "statistics")),
    CuratedIcon("circle-dollar-sign", "dollar sign", "Dollar sign icon for money, finance, and economics.", ("money", "finance", "dollar", "economics")),
    CuratedIcon("piggy-bank", "piggy bank", "Piggy bank icon for saving money and budgeting.", ("money", "saving", "budget", "finance")),
    CuratedIcon("shield-check", "shield check", "Shield check icon for safety, security, and trust.", ("safety", "security", "shield", "trust")),
    CuratedIcon("lock-keyhole", "lock", "Lock icon for privacy, security, and protected data.", ("lock", "privacy", "security", "data")),
    CuratedIcon("wifi", "wifi", "Wi-Fi icon for networks, signal, and connectivity.", ("wifi", "network", "signal", "internet")),
    CuratedIcon("smartphone", "smartphone", "Smartphone icon for mobile devices and apps.", ("phone", "mobile", "smartphone", "app")),
    CuratedIcon("monitor", "computer monitor", "Monitor icon for computers, screens, and dashboards.", ("computer", "monitor", "screen", "technology")),
    CuratedIcon("cpu", "cpu chip", "CPU chip icon for computing, processors, and AI.", ("cpu", "chip", "computer", "ai")),
    CuratedIcon("database", "database", "Database icon for storage, records, and information.", ("database", "data", "storage", "records")),
    CuratedIcon("server", "server", "Server icon for backend systems, hosting, and infrastructure.", ("server", "hosting", "backend", "infrastructure")),
    CuratedIcon("factory", "factory", "Factory icon for industry, manufacturing, or production.", ("factory", "industry", "manufacturing", "production")),
    CuratedIcon("car", "car", "Car icon for transportation, roads, and travel.", ("car", "transport", "road", "travel")),
    CuratedIcon("bus", "bus", "Bus icon for public transit and transportation.", ("bus", "transport", "transit", "travel")),
    CuratedIcon("plane", "plane", "Plane icon for flight, travel, and global movement.", ("plane", "flight", "travel", "air")),
    CuratedIcon("bike", "bike", "Bike icon for cycling, transport, and healthy movement.", ("bike", "cycling", "transport", "movement")),
    CuratedIcon("house", "home", "Home icon for houses, shelter, and daily life.", ("home", "house", "shelter", "life")),
    CuratedIcon("heart-pulse", "heart pulse", "Heart pulse icon for health, fitness, and care.", ("heart", "health", "pulse", "care")),
    CuratedIcon("activity", "activity", "Activity waveform icon for metrics, motion, and health.", ("activity", "motion", "metrics", "health")),
    CuratedIcon("sparkles", "sparkles", "Sparkles icon for magic, emphasis, fun, or highlights.", ("sparkle", "magic", "fun", "highlight")),
    CuratedIcon("circle", "circle", "Simple circle icon for placeholders, dots, and abstract diagrams.", ("circle", "dot", "simple", "diagram")),
    CuratedIcon("arrow-right", "right arrow", "Right arrow icon for flow, next steps, and direction.", ("arrow", "right", "direction", "flow")),
    CuratedIcon("refresh-cw", "cycle arrows", "Circular arrows for cycles, refresh, reuse, or loops.", ("cycle", "arrow", "loop", "refresh")),
)


CURATED_BOOTSTRAP_ICONS: tuple[CuratedIcon, ...] = (
    CuratedIcon("emoji-smile", "happy face", "Smiling face icon for friendly characters.", ("face", "smile", "happy", "character"), "bootstrap"),
    CuratedIcon("emoji-laughing", "laughing face", "Laughing face icon for jokes, fun, and playful reactions.", ("face", "laugh", "fun", "character"), "bootstrap"),
    CuratedIcon("emoji-surprise", "surprised face", "Surprised face icon for sudden reveals or wow moments.", ("face", "surprise", "wow", "character"), "bootstrap"),
    CuratedIcon("emoji-sunglasses", "cool face", "Cool face icon for confident or stylish reactions.", ("face", "cool", "sunglasses", "character"), "bootstrap"),
    CuratedIcon("emoji-heart-eyes", "excited face", "Excited face icon for delight, discovery, or big enthusiasm.", ("face", "excited", "heart", "character"), "bootstrap"),
    CuratedIcon("emoji-wink", "winking face", "Winking face icon for playful asides or friendly jokes.", ("face", "wink", "playful", "character"), "bootstrap"),
    CuratedIcon("person", "person", "Simple person icon for human characters.", ("person", "human", "character", "people"), "bootstrap"),
    CuratedIcon("person-standing", "standing person", "Standing person icon for presenter or character scenes.", ("person", "standing", "human", "character"), "bootstrap"),
    CuratedIcon("person-arms-up", "excited person", "Person with raised arms for excitement, success, or celebration.", ("person", "excited", "celebrate", "human"), "bootstrap"),
    CuratedIcon("person-raised-hand", "person raising hand", "Person raising hand for questions, answers, or participation.", ("person", "hand", "question", "human"), "bootstrap"),
    CuratedIcon("person-walking", "walking person", "Walking person icon for motion, travel, or journeys.", ("person", "walking", "movement", "human"), "bootstrap"),
    CuratedIcon("universal-access", "person circle", "Person in a circle for simple full-body character composition.", ("person", "circle", "human", "character"), "bootstrap"),
)


CURATED_SVGREPO_ICONS: tuple[CuratedIcon, ...] = (
    CuratedIcon("raindrop", "colorful raindrop", "Colorful raindrop illustration for a friendly water character.", ("water", "raindrop", "drop", "color", "character"), "svgrepo", "78833"),
    CuratedIcon("water-drop", "water drop character", "Large water-drop illustration for a main droplet character.", ("water", "drop", "droplet", "character", "blue"), "svgrepo", "120133"),
    CuratedIcon("raindrops", "falling raindrops", "Cluster of falling raindrops for rainy scenes.", ("rain", "raindrops", "weather", "water"), "svgrepo", "162559"),
    CuratedIcon("cloud-sun", "colorful cloud sun", "Cloud and sun illustration for evaporation and warm weather scenes.", ("cloud", "sun", "weather", "evaporation", "sky"), "svgrepo", "520646"),
    CuratedIcon("sun-cloud-and-rain", "sun cloud rain scene", "Weather scene with sun, cloud, and rain.", ("sun", "cloud", "rain", "weather", "cycle"), "svgrepo", "97828"),
    CuratedIcon("cloud-sun-rain", "colorful cloud sun rain", "Colorful cloud, sun, and rain icon for water-cycle transitions.", ("cloud", "sun", "rain", "weather", "color"), "svgrepo", "351900"),
    CuratedIcon("umbrella-rain", "rain umbrella", "Umbrella in the rain for precipitation scenes.", ("umbrella", "rain", "weather", "precipitation"), "svgrepo", "194895"),
    CuratedIcon("ocean-wave", "ocean wave", "Ocean wave illustration for water collection scenes.", ("ocean", "wave", "water", "sea"), "svgrepo", "7483856"),
    CuratedIcon("mountain-river", "mountain river", "Mountain river illustration for runoff and flowing water.", ("river", "mountain", "water", "landscape", "runoff"), "svgrepo", "224055"),
    CuratedIcon("water", "water splash", "Water splash illustration for oceans, lakes, or collection.", ("water", "splash", "liquid", "blue"), "svgrepo", "297151"),
    CuratedIcon("happy-kids", "happy kids illustration", "Happy kids illustration for playful educational videos.", ("kids", "happy", "people", "education", "fun"), "svgrepo", "1992"),
    CuratedIcon("happy-kid-playground", "playful kid illustration", "Playful kid illustration for friendly explainer scenes.", ("kid", "playful", "person", "education", "fun"), "svgrepo", "418280"),
)


def _download_text(url: str, timeout_sec: float = 15.0) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ai-videogen-pipeline/0.1",
            "Accept": "image/svg+xml,text/html;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout_sec) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset)


def _find_existing(manifest: Manifest, icon: CuratedIcon, asset_dir) -> ManifestEntry | None:
    for entry in manifest.assets:
        if entry.label.lower() != icon.label.lower():
            continue
        if (asset_dir / entry.filename).exists():
            return entry
    return None


def seed_open_source_assets(config: PipelineConfig) -> SeedResult:
    config.ensure_dirs()
    if not config.manifest_path.exists():
        manifest = Manifest()
    else:
        manifest = Manifest.model_validate_json(config.manifest_path.read_text(encoding="utf-8"))

    result = SeedResult()
    for icon in [*CURATED_LUCIDE_ICONS, *CURATED_BOOTSTRAP_ICONS, *CURATED_SVGREPO_ICONS]:
        if _find_existing(manifest, icon, config.asset_dir):
            result.reused += 1
            continue

        try:
            if icon.provider == "svgrepo":
                time.sleep(0.25)
            svg_text = _download_text(icon.url)
            validation = validate_svg(
                svg_text,
                rasterize=False,
                require_square=icon.provider != "svgrepo",
                require_origin=icon.provider != "svgrepo",
                allow_style=icon.provider == "svgrepo",
            )
        except (OSError, urllib.error.URLError, ValueError) as exc:
            result.failed += 1
            continue

        asset_id = f"{icon.provider}_{icon.slug}_{short_hash(svg_text, 8)}"
        filename = f"{icon.provider}-{slugify(icon.slug, 48)}.svg"
        (config.asset_dir / filename).write_text(svg_text, encoding="utf-8")
        manifest.assets.append(
            ManifestEntry(
                id=asset_id,
                filename=filename,
                label=icon.label,
                description=icon.description,
                tags=sorted(set(icon.tags)),
                viewBox=validation.view_box,
                source_prompt=(
                    f"Open-source {icon.provider.title()} SVG icon downloaded from {icon.url}; "
                    f"license: {icon.license_name}."
                ),
            )
        )
        result.downloaded += 1

    write_json(config.manifest_path, manifest.model_dump(mode="json"))
    return result


def available_asset_labels(config: PipelineConfig, limit: int) -> list[str]:
    if not config.manifest_path.exists():
        return []
    manifest = Manifest.model_validate_json(config.manifest_path.read_text(encoding="utf-8"))
    labels = [entry.label for entry in manifest.assets if (config.asset_dir / entry.filename).exists()]
    return labels[:limit]
