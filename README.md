# AI Videogen Pipeline

Command-line pipeline that turns one prompt into a finished short-form vertical video for YouTube Shorts, Instagram Reels, or TikTok.

The pipeline composes visuals from reusable local SVG assets. The SVG asset library now includes a math/computer-science layer from Tabler Icons, so diagram-heavy explainers about algorithms, calculus, graphs, data structures, systems, and code work much better than character stories. Narration is generated with Google Gemini TTS. The final output is an MP4 at `1080x1920`, `30fps` by default, H.264 video plus AAC audio.

## Project Structure

```text
pipeline/
  cli.py       # CLI orchestration
  models.py    # Pydantic storyboard and manifest schema
  plan.py      # Gemini JSON storyboard planning
  assets.py    # SVG library lookup, generation, validation
  open_source_assets.py
               # Curated Lucide, Bootstrap, Tabler, and SVG Repo seeding
  audio.py     # Gemini TTS WAV generation and duration reconciliation
  render.py    # SVG timeline rendering to PNG frames
  compose.py   # ffmpeg frame/audio muxing to MP4
assets/
  manifest.json
  THIRD_PARTY_NOTICES.md
  svg/         # reusable SVG assets, seeded from Lucide by default
  music/       # optional local background music
cache/         # generated plans, audio, and frames
output/        # final MP4 and storyboard JSON
```

## Requirements

- Python 3.11+
- `GEMINI_API_KEY` environment variable
- `requirements.txt` includes venv-local fallbacks for ffmpeg (`imageio-ffmpeg`) and SVG rasterization (`resvg-cli`).
- System `ffmpeg` and `resvg` on `PATH` are also supported and preferred when present. If neither `resvg` nor `resvg-cli` is available, the pipeline falls back to `cairosvg`; on Windows, CairoSVG also needs the native Cairo DLL available.

Install Python dependencies.

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Bash on macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Bash on Windows, such as Git Bash:

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Set your Gemini API key.

You can put it in a local `.env` file:

```text
GEMINI_API_KEY=your-api-key
```

`.env` is ignored by git. Values already set in your shell take precedence over `.env`.

Or set it for the current shell.

PowerShell:

```powershell
$env:GEMINI_API_KEY="your-api-key"
```

Bash:

```bash
export GEMINI_API_KEY="your-api-key"
```

## Example

PowerShell:

```powershell
python -m pipeline "explain the water cycle in a fun way" --length 20
```

Bash:

```bash
python -m pipeline "explain the water cycle in a fun way" --length 20
```

The command writes:

- `output/<slug>.mp4`
- `output/<slug>.storyboard.json`

## Math And Computer Science Explainers

For symbolic topics, force the planner into the math/CS visual domain. It will prefer formulas, axes, graphs, code blocks, data structures, flow arrows, databases, networks, stacks, queues, and algorithm diagrams. Spoken subtitles still come from `script_cues`; extra on-screen formula/callout labels are rendered separately so captions stay synced to narration.

PowerShell:

```powershell
python -m pipeline "explain binary search with a sorted array and big O notation" --length 30 --visual-domain math-cs
```

Bash:

```bash
python -m pipeline "explain binary search with a sorted array and big O notation" --length 30 --visual-domain math-cs
```

## Common Options

```text
--length 20                    Target duration in seconds, hard cap 60
--voice Puck                   Gemini prebuilt TTS voice
--style "Say..."               Style instruction prepended to each narration chunk
--fps 30                       Output frame rate
--no-captions                  Disable rendered captions
--music                        Mix the first local audio file found in assets/music
--output-dir output            Final MP4/storyboard directory
--cache-dir cache              Cache directory
--skip-open-source-assets      Do not seed curated Lucide SVG assets
--generate-missing-assets      Allow Gemini SVG generation when no SVG matches
--max-gemini-calls 12          Hard cap on Gemini API calls for one run
--max-scenes 6                 Maximum storyboard scenes
--max-elements-per-scene 3     Maximum visual elements per scene
--visual-domain math-cs        Prefer math/CS diagrams and symbols
```

You can also pass `--config config.json`. Config keys match `PipelineConfig` fields in `pipeline/config.py`.

## Caching And Reuse

Reruns are idempotent:

- Storyboard plans are cached by prompt, target length, model, and caption setting.
- Scene narration WAVs are cached by text, voice, style, language, and TTS model.
- SVG frames are cached by the resolved storyboard, render settings, and SVG asset hashes.
- Existing SVG assets in `assets/svg/` are reused through `assets/manifest.json`.
- Curated Lucide, Bootstrap Icons, Tabler math/CS icons, and SVG Repo SVGs are seeded automatically when missing.
- Gemini SVG generation is disabled by default. Use `--generate-missing-assets` if you want the old fallback behavior.

The SVG library is intentionally local and human-readable. Each manifest entry includes:

```json
{
  "id": "svg_...",
  "filename": "water-drop-1234abcd.svg",
  "label": "water drop",
  "description": "A friendly blue droplet character",
  "tags": ["blue", "droplet", "water"],
  "viewBox": "0 0 1024 1024",
  "created_at": "...",
  "source_prompt": "..."
}
```

Seeded Lucide, Bootstrap Icons, Tabler Icons, and SVG Repo files are covered by `assets/THIRD_PARTY_NOTICES.md`.
The repo includes the initial curated seed set, so normal reruns reuse local files. If those files are deleted, the seeder downloads them again from the configured open-source providers.

## Gemini Resource Use

The default run is designed to keep Gemini usage small:

- Planning is one cached JSON request, with a compact prompt and a list of available SVG labels.
- SVG generation is not used unless `--generate-missing-assets` is passed.
- TTS is chunked per scene and cached by narration text, voice, style, language, and model.
- Storyboards are capped by `--max-scenes`, `--max-elements-per-scene`, and `--max-captions-per-scene`.
- `--max-gemini-calls` enforces a hard per-run call budget across planning, TTS, and optional SVG generation.

## Model Defaults

- Planning: `gemini-3.5-flash`
- Optional first-pass SVG generation: `gemini-3.5-flash`
- SVG validation retry fallback: `gemini-3.1-pro-preview`
- TTS primary: `gemini-2.5-flash-preview-tts`
- TTS fallback: disabled by default; set `--tts-fallback-model gemini-2.5-pro-preview-tts` if your key has Pro TTS quota

Google currently documents the Gemini 2.5 preview TTS model ids in the Gemini speech generation guide.

Google references:

- Gemini speech generation: <https://ai.google.dev/gemini-api/docs/speech-generation>
- Google Gen AI SDK: <https://github.com/googleapis/python-genai>

## Notes

Gemini TTS is speech-only, so background music must be a local file in `assets/music/` and enabled with `--music`.
