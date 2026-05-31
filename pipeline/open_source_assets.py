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
TABLER_RAW_BASE = "https://raw.githubusercontent.com/tabler/tabler-icons/main/icons/outline"
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
        if self.provider == "bootstrap":
            base = BOOTSTRAP_RAW_BASE
        elif self.provider == "tabler":
            base = TABLER_RAW_BASE
        else:
            base = LUCIDE_RAW_BASE
        return f"{base}/{self.slug}.svg"

    @property
    def license_name(self) -> str:
        if self.provider == "svgrepo":
            return "CC0"
        if self.provider in {"bootstrap", "tabler"}:
            return "MIT"
        return "ISC"


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


CURATED_TABLER_MATH_CS_ICONS: tuple[CuratedIcon, ...] = (
    CuratedIcon("math-symbols", "math symbols", "Core math symbols for equations and notation callouts.", ("math", "symbols", "operator", "education"), "tabler"),
    CuratedIcon("math", "math notation", "General math notation icon for lesson introductions.", ("math", "notation", "education"), "tabler"),
    CuratedIcon("math-function", "function curve", "Function graph icon for f(x), transformations, and mappings.", ("math", "function", "graph", "curve"), "tabler"),
    CuratedIcon("math-function-y", "y function", "Y equals function icon for coordinate graph explanations.", ("math", "function", "y", "graph"), "tabler"),
    CuratedIcon("function", "function symbol", "Function symbol for reusable function and mapping visuals.", ("math", "function", "symbol"), "tabler"),
    CuratedIcon("math-integral", "integral symbol", "Integral symbol for calculus and accumulation visuals.", ("math", "calculus", "integral"), "tabler"),
    CuratedIcon("math-integrals", "multiple integrals", "Multiple integral symbols for advanced calculus visuals.", ("math", "calculus", "integral"), "tabler"),
    CuratedIcon("math-pi", "pi symbol", "Pi symbol for circles, radians, and constants.", ("math", "pi", "constant", "geometry"), "tabler"),
    CuratedIcon("math-avg", "average symbol", "Average symbol for statistics and mean value lessons.", ("math", "statistics", "average", "data"), "tabler"),
    CuratedIcon("math-max-min", "max min symbol", "Max/min symbol for optimization and bounds.", ("math", "optimization", "minimum", "maximum"), "tabler"),
    CuratedIcon("math-sin", "sine function", "Sine function icon for trigonometry and waves.", ("math", "trigonometry", "sine", "wave"), "tabler"),
    CuratedIcon("math-cos", "cosine function", "Cosine function icon for trigonometry and periodic motion.", ("math", "trigonometry", "cosine", "wave"), "tabler"),
    CuratedIcon("math-x-plus-y", "x plus y", "Algebraic x plus y expression for addition examples.", ("math", "algebra", "addition"), "tabler"),
    CuratedIcon("math-x-minus-y", "x minus y", "Algebraic x minus y expression for subtraction examples.", ("math", "algebra", "subtraction"), "tabler"),
    CuratedIcon("math-x-divide-y", "x divided by y", "Algebraic division expression for ratios and fractions.", ("math", "algebra", "division", "ratio"), "tabler"),
    CuratedIcon("math-equal-greater", "greater or equal", "Greater-than-or-equal symbol for inequalities.", ("math", "inequality", "operator"), "tabler"),
    CuratedIcon("math-equal-lower", "less or equal", "Less-than-or-equal symbol for inequalities.", ("math", "inequality", "operator"), "tabler"),
    CuratedIcon("math-not", "not operator", "Not operator for logic, negation, and inequalities.", ("math", "logic", "operator"), "tabler"),
    CuratedIcon("infinity", "infinity symbol", "Infinity symbol for limits, loops, and unbounded growth.", ("math", "infinity", "limit", "loop"), "tabler"),
    CuratedIcon("lambda", "lambda symbol", "Lambda symbol for functions, calculus, and functional programming.", ("math", "lambda", "function", "cs"), "tabler"),
    CuratedIcon("delta", "delta symbol", "Delta symbol for change, differences, and gradients.", ("math", "delta", "change", "calculus"), "tabler"),
    CuratedIcon("omega", "omega symbol", "Omega symbol for asymptotic bounds and constants.", ("math", "omega", "complexity", "cs"), "tabler"),
    CuratedIcon("abacus", "abacus", "Abacus icon for arithmetic and number sense.", ("math", "arithmetic", "numbers", "education"), "tabler"),
    CuratedIcon("calculator", "calculator", "Calculator icon for numeric computation.", ("math", "calculator", "numbers"), "tabler"),
    CuratedIcon("percentage", "percentage symbol", "Percentage symbol for rates, proportions, and statistics.", ("math", "percentage", "ratio", "statistics"), "tabler"),
    CuratedIcon("plus-minus", "plus minus", "Plus-minus operator for uncertainty and positive/negative cases.", ("math", "operator", "plus", "minus"), "tabler"),
    CuratedIcon("equal", "equals sign", "Equals sign for equations and comparisons.", ("math", "equals", "equation", "operator"), "tabler"),
    CuratedIcon("equal-not", "not equal sign", "Not-equal sign for comparisons and logic.", ("math", "not-equal", "operator", "logic"), "tabler"),
    CuratedIcon("divide", "division sign", "Division sign for ratios and fractions.", ("math", "division", "operator"), "tabler"),
    CuratedIcon("axis-x", "axis x", "X-axis icon for coordinate planes and graphs.", ("math", "axis", "graph", "x"), "tabler"),
    CuratedIcon("axis-y", "axis y", "Y-axis icon for coordinate planes and graphs.", ("math", "axis", "graph", "y"), "tabler"),
    CuratedIcon("graph", "graph network", "Graph/network icon for nodes, edges, and relationships.", ("math", "graph", "network", "cs"), "tabler"),
    CuratedIcon("chart-line", "line chart", "Line chart icon for functions, trends, and time series.", ("math", "chart", "data", "line"), "tabler"),
    CuratedIcon("chart-bar", "bar chart", "Bar chart icon for comparisons and histograms.", ("math", "chart", "data", "bar"), "tabler"),
    CuratedIcon("chart-scatter", "scatter plot", "Scatter plot icon for datasets and correlation.", ("math", "chart", "data", "scatter"), "tabler"),
    CuratedIcon("chart-histogram", "histogram", "Histogram icon for distributions and frequency bins.", ("math", "statistics", "data", "histogram"), "tabler"),
    CuratedIcon("chart-treemap", "treemap chart", "Treemap icon for nested proportions and partitions.", ("math", "chart", "data", "tree"), "tabler"),
    CuratedIcon("matrix", "matrix", "Matrix icon for linear algebra and grids of numbers.", ("math", "matrix", "linear-algebra", "data"), "tabler"),
    CuratedIcon("vector", "vector", "Vector icon for geometry, direction, and linear algebra.", ("math", "vector", "geometry"), "tabler"),
    CuratedIcon("angle", "angle", "Angle icon for geometry and trigonometry.", ("math", "geometry", "angle"), "tabler"),
    CuratedIcon("triangle", "triangle", "Triangle icon for geometry and visual grouping.", ("math", "geometry", "shape"), "tabler"),
    CuratedIcon("circle", "circle", "Circle icon for geometry, nodes, and simple diagrams.", ("math", "geometry", "shape", "node"), "tabler"),
    CuratedIcon("square", "square", "Square icon for geometry, matrices, and grid diagrams.", ("math", "geometry", "shape", "grid"), "tabler"),
    CuratedIcon("braces", "code braces", "Curly braces for code blocks, sets, and object literals.", ("cs", "code", "sets", "syntax"), "tabler"),
    CuratedIcon("brackets", "brackets", "Brackets for arrays, intervals, and syntax examples.", ("cs", "math", "syntax", "array"), "tabler"),
    CuratedIcon("brackets-angle", "angle brackets", "Angle brackets for generics, HTML, and comparisons.", ("cs", "code", "syntax", "html"), "tabler"),
    CuratedIcon("code", "code", "Code icon for programming lessons.", ("cs", "code", "programming"), "tabler"),
    CuratedIcon("codeblock", "code block", "Code block icon for snippets and pseudocode.", ("cs", "code", "snippet", "programming"), "tabler"),
    CuratedIcon("code-variable", "code variable", "Variable icon for code examples and state changes.", ("cs", "code", "variable"), "tabler"),
    CuratedIcon("terminal", "terminal", "Terminal icon for command-line and shell examples.", ("cs", "terminal", "command-line", "code"), "tabler"),
    CuratedIcon("source-code", "source code", "Source code icon for files and implementation details.", ("cs", "source", "code", "file"), "tabler"),
    CuratedIcon("api", "api", "API icon for interfaces and service boundaries.", ("cs", "api", "interface", "service"), "tabler"),
    CuratedIcon("binary", "binary digits", "Binary digits icon for bits, encoding, and low-level computing.", ("cs", "binary", "bits", "data"), "tabler"),
    CuratedIcon("binary-tree", "binary tree", "Binary tree icon for tree structures and recursion.", ("cs", "tree", "binary", "algorithm"), "tabler"),
    CuratedIcon("binary-tree-2", "binary tree nodes", "Alternative binary tree icon for search trees and heaps.", ("cs", "tree", "binary", "nodes"), "tabler"),
    CuratedIcon("git-branch", "logic branch", "Branching icon for decisions, conditionals, and version history.", ("cs", "branch", "logic", "algorithm"), "tabler"),
    CuratedIcon("hierarchy", "hierarchy", "Hierarchy icon for trees, inheritance, and nested structures.", ("cs", "hierarchy", "tree", "structure"), "tabler"),
    CuratedIcon("sitemap", "sitemap", "Sitemap icon for graphs, trees, and system structure.", ("cs", "graph", "tree", "structure"), "tabler"),
    CuratedIcon("subtask", "subtask flow", "Subtask flow icon for decomposition and recursive subproblems.", ("cs", "algorithm", "flow", "decomposition"), "tabler"),
    CuratedIcon("schema", "schema", "Schema icon for structured data and database models.", ("cs", "data", "schema", "database"), "tabler"),
    CuratedIcon("database", "database", "Database icon for storage, tables, and queries.", ("cs", "database", "data", "storage"), "tabler"),
    CuratedIcon("server", "server", "Server icon for backend systems and request flow.", ("cs", "server", "backend", "network"), "tabler"),
    CuratedIcon("serverless", "serverless", "Serverless icon for cloud functions and managed compute.", ("cs", "serverless", "cloud", "backend"), "tabler"),
    CuratedIcon("network", "network", "Network icon for connections, protocols, and distributed systems.", ("cs", "network", "distributed", "systems"), "tabler"),
    CuratedIcon("router", "router", "Router icon for packets, networks, and internet paths.", ("cs", "network", "router", "internet"), "tabler"),
    CuratedIcon("cpu", "cpu chip", "CPU chip icon for processors, architecture, and computation.", ("cs", "cpu", "processor", "hardware"), "tabler"),
    CuratedIcon("cloud-computing", "cloud computing", "Cloud computing icon for hosted infrastructure.", ("cs", "cloud", "computing", "network"), "tabler"),
    CuratedIcon("stack", "stack", "Stack icon for LIFO data structures and call stacks.", ("cs", "stack", "data-structure", "algorithm"), "tabler"),
    CuratedIcon("stack-push", "stack push", "Stack push icon for adding items to a stack.", ("cs", "stack", "push", "data-structure"), "tabler"),
    CuratedIcon("stack-pop", "stack pop", "Stack pop icon for removing items from a stack.", ("cs", "stack", "pop", "data-structure"), "tabler"),
    CuratedIcon("queue-pop-in", "queue enqueue", "Queue enqueue icon for FIFO data structure lessons.", ("cs", "queue", "enqueue", "data-structure"), "tabler"),
    CuratedIcon("queue-pop-out", "queue dequeue", "Queue dequeue icon for FIFO data structure lessons.", ("cs", "queue", "dequeue", "data-structure"), "tabler"),
    CuratedIcon("sort-ascending", "sort ascending", "Sort ascending icon for sorting algorithms.", ("cs", "sort", "algorithm", "order"), "tabler"),
    CuratedIcon("sort-descending", "sort descending", "Sort descending icon for sorting algorithms.", ("cs", "sort", "algorithm", "order"), "tabler"),
    CuratedIcon("arrows-sort", "sort arrows", "Bidirectional sort arrows for comparing and swapping.", ("cs", "sort", "algorithm", "arrows"), "tabler"),
    CuratedIcon("hash", "hash symbol", "Hash icon for hashing, maps, and identifiers.", ("cs", "hash", "map", "identifier"), "tabler"),
    CuratedIcon("key", "key", "Key icon for key-value pairs, encryption, and access.", ("cs", "key", "map", "security"), "tabler"),
    CuratedIcon("lock", "lock", "Lock icon for security, privacy, and encryption.", ("cs", "security", "lock", "encryption"), "tabler"),
    CuratedIcon("bug", "bug", "Bug icon for debugging and software defects.", ("cs", "debugging", "bug", "code"), "tabler"),
    CuratedIcon("robot", "robot", "Robot icon for AI, agents, and automation.", ("cs", "ai", "robot", "automation"), "tabler"),
    CuratedIcon("brain", "brain", "Brain icon for learning, neural networks, and reasoning.", ("cs", "ai", "brain", "learning"), "tabler"),
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
    CuratedIcon("medieval-castle", "medieval castle", "Medieval castle illustration for fantasy kingdom scenes.", ("medieval", "castle", "kingdom", "fortress", "fantasy"), "svgrepo", "444137"),
    CuratedIcon("medieval-knight", "medieval knight", "Armored medieval knight illustration for heroic story scenes.", ("medieval", "knight", "hero", "armor", "fantasy"), "svgrepo", "444141"),
    CuratedIcon("knight", "young knight", "Knight figure for quest, courage, and adventure scenes.", ("knight", "hero", "quest", "sword", "fantasy"), "svgrepo", "162875"),
    CuratedIcon("knight-helmet", "knight helmet", "Knight helmet icon for armor, identity, and dramatic close-ups.", ("helmet", "knight", "armor", "medieval"), "svgrepo", "307023"),
    CuratedIcon("dragon", "dragon", "Dragon illustration for fantasy threats, ancient curses, and cliffhangers.", ("dragon", "fantasy", "monster", "curse", "fire"), "svgrepo", "403214"),
    CuratedIcon("dragonside", "dragon silhouette", "Side-view dragon silhouette for ominous fantasy scenes.", ("dragon", "silhouette", "fantasy", "shadow"), "svgrepo", "400187"),
    CuratedIcon("sword", "sword", "Sword icon for quests, danger, and heroic reveals.", ("sword", "weapon", "quest", "knight"), "svgrepo", "66502"),
    CuratedIcon("excalibur-sword", "glowing sword", "Legendary sword illustration for magic and royal destiny.", ("sword", "excalibur", "magic", "legend"), "svgrepo", "254373"),
    CuratedIcon("shield-with-crown", "royal shield", "Shield with crown for kingdom, royal guard, and ancient seal scenes.", ("shield", "crown", "royal", "seal", "kingdom"), "svgrepo", "50129"),
    CuratedIcon("crown", "crown", "Crown icon for royal bloodlines, princesses, and throne-room scenes.", ("crown", "royal", "kingdom", "princess"), "svgrepo", "30829"),
    CuratedIcon("princess", "hidden princess", "Princess illustration for hidden heir and rescue story beats.", ("princess", "royal", "heir", "character"), "svgrepo", "508393"),
    CuratedIcon("crystal", "magic crystal", "Crystal illustration for spells, prisons, and glowing magical objects.", ("crystal", "magic", "spell", "prison"), "svgrepo", "373532"),
    CuratedIcon("crystals", "crystal cluster", "Cluster of crystals for caves, magic halls, and enchanted prisons.", ("crystal", "cluster", "magic", "cave"), "svgrepo", "499101"),
    CuratedIcon("door-open", "open stone door", "Open door icon for secret passages and dramatic reveals.", ("door", "open", "secret", "passage"), "svgrepo", "351965"),
    CuratedIcon("dungeon", "dungeon", "Dungeon icon for underground chambers and castle catacombs.", ("dungeon", "castle", "underground", "chamber"), "svgrepo", "351978"),
    CuratedIcon("eye", "giant eye", "Eye icon for ominous cliffhanger reveals and hidden monsters.", ("eye", "monster", "cliffhanger", "watching"), "svgrepo", "344769"),
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
    for icon in [
        *CURATED_LUCIDE_ICONS,
        *CURATED_BOOTSTRAP_ICONS,
        *CURATED_TABLER_MATH_CS_ICONS,
        *CURATED_SVGREPO_ICONS,
    ]:
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


def available_asset_labels(config: PipelineConfig, limit: int, preferred_tags: tuple[str, ...] = ()) -> list[str]:
    if not config.manifest_path.exists():
        return []
    manifest = Manifest.model_validate_json(config.manifest_path.read_text(encoding="utf-8"))
    entries = [entry for entry in manifest.assets if (config.asset_dir / entry.filename).exists()]
    if preferred_tags:
        preferred = {tag.lower() for tag in preferred_tags}

        def score(entry: ManifestEntry) -> int:
            entry_tags = {tag.lower() for tag in entry.tags}
            entry_text = f"{entry.label} {entry.description}".lower()
            return sum(1 for tag in preferred if tag in entry_tags or tag in entry_text)

        entries.sort(key=score, reverse=True)
    return [entry.label for entry in entries[:limit]]
