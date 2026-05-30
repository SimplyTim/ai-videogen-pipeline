from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar


T = TypeVar("T")


def slugify(text: str, max_len: int = 56) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len].strip("-") or "video")


def short_hash(value: Any, length: int = 12) -> str:
    if isinstance(value, bytes):
        payload = value
    elif isinstance(value, str):
        payload = value.encode("utf-8")
    else:
        payload = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def strip_markdown_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def extract_json_text(text: str) -> str:
    cleaned = strip_markdown_fences(text)
    start = min((idx for idx in [cleaned.find("{"), cleaned.find("[")] if idx >= 0), default=-1)
    if start < 0:
        return cleaned
    end_obj = cleaned.rfind("}")
    end_arr = cleaned.rfind("]")
    end = max(end_obj, end_arr)
    if end <= start:
        return cleaned
    return cleaned[start : end + 1]


def require_command(name: str, install_hint: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Missing required command {name!r}. {install_hint}")
    return path


def run_command(args: list[str], *, cwd: Path | None = None) -> None:
    process = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if process.returncode != 0:
        command = " ".join(args)
        stderr = process.stderr.strip() or process.stdout.strip()
        raise RuntimeError(f"Command failed ({process.returncode}): {command}\n{stderr}")


def retry(operation: Callable[[], T], *, attempts: int = 3, base_delay_sec: float = 1.0) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001 - this wraps SDK/network errors with context.
            last_error = exc
            if attempt == attempts:
                break
            sleep = base_delay_sec * (2 ** (attempt - 1)) + random.uniform(0, 0.25)
            time.sleep(sleep)
    assert last_error is not None
    raise last_error


def get_genai_client() -> Any:
    load_dotenv_file(Path(".env"))
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Export it before running the pipeline.")
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError("google-genai is not installed. Run `pip install -r requirements.txt`.") from exc
    return genai.Client(api_key=api_key)


def load_dotenv_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def decode_possible_base64(data: bytes | str) -> bytes:
    if isinstance(data, bytes):
        return data
    try:
        return base64.b64decode(data)
    except Exception:
        return data.encode("utf-8")


def print_step(message: str) -> None:
    print(f"[pipeline] {message}", file=sys.stderr)


class GeminiBudget:
    def __init__(self, max_calls: int):
        self.max_calls = max_calls
        self.used = 0

    def claim(self, label: str) -> None:
        if self.used + 1 > self.max_calls:
            raise RuntimeError(
                f"Gemini call budget exceeded before {label}. "
                f"Used {self.used}/{self.max_calls}; increase --max-gemini-calls if needed."
            )
        self.used += 1
