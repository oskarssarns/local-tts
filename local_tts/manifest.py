from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import MANIFEST_NAME
from .paths import display_path


def manifest_entry(
    *,
    segment: dict[str, Any],
    output_dir: Path,
    output_path: Path,
    status: str,
    model: str,
    reference_audio: Path,
    device: str,
    bytes_count: int = 0,
    duration_seconds: float | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    try:
        audio_filename = output_path.relative_to(output_dir).as_posix()
    except ValueError:
        audio_filename = output_path.name

    entry: dict[str, Any] = {
        "id": segment.get("id"),
        "slide": segment.get("slide"),
        "title": segment.get("title"),
        "audio_filename": audio_filename,
        "status": status,
        "bytes": bytes_count,
        "model": model,
        "reference_audio": display_path(reference_audio),
        "device": device,
    }
    if duration_seconds is not None:
        entry["duration_seconds"] = duration_seconds
    if error_message:
        entry["error"] = error_message
    return entry


def write_manifest(output_dir: Path, manifest: list[dict[str, Any]]) -> None:
    manifest_path = output_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"manifest -> {display_path(manifest_path)}")
