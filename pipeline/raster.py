from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from .utils import run_command


class RasterizationError(RuntimeError):
    pass


def rasterize_svg_to_png(svg_text: str, output_png: Path, width: int, height: int) -> None:
    output_png.parent.mkdir(parents=True, exist_ok=True)
    resvg = shutil.which("resvg")
    if not resvg:
        local_resvg = Path(sys.executable).parent / ("resvg.exe" if sys.platform == "win32" else "resvg")
        if local_resvg.exists():
            resvg = str(local_resvg)

    with tempfile.TemporaryDirectory(prefix="svg-video-") as tmp:
        svg_path = Path(tmp) / "frame.svg"
        svg_path.write_text(svg_text, encoding="utf-8")

        if resvg:
            try:
                run_command(
                    [
                        resvg,
                        "--width",
                        str(width),
                        "--height",
                        str(height),
                        str(svg_path),
                        str(output_png),
                    ]
                )
                return
            except Exception:
                # Fall through to cairosvg; resvg is preferred but not always installed with the same CLI flags.
                pass

        try:
            import cairosvg
        except Exception as exc:  # noqa: BLE001 - cairosvg can fail if native Cairo is missing.
            raise RasterizationError(
                "No SVG rasterizer is available. Install `resvg`, or install `cairosvg` plus the native Cairo library."
            ) from exc

        try:
            cairosvg.svg2png(
                bytestring=svg_text.encode("utf-8"),
                write_to=str(output_png),
                output_width=width,
                output_height=height,
            )
        except Exception as exc:  # noqa: BLE001 - wraps rasterizer details for callers.
            raise RasterizationError(f"Failed to rasterize SVG: {exc}") from exc
