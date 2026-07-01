from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import DATA_DIR_NAME, MANIFEST_NAME
from .errors import ConfigError
from .paths import BASE_DIR, display_path


SEGMENT_FILENAMES = [
    Path(DATA_DIR_NAME) / "segments.json",
    Path(DATA_DIR_NAME) / "data.json",
    Path("segments.json"),
]
SEGMENT_PATTERNS = [
    f"{DATA_DIR_NAME}/*.json",
    f"{DATA_DIR_NAME}/*segments*.json",
    "*segments*.json",
]
REFERENCE_FILENAMES = [
    Path(DATA_DIR_NAME) / "reference.wav",
    Path(DATA_DIR_NAME) / "reference.mp3",
    Path(DATA_DIR_NAME) / "voice.wav",
    Path(DATA_DIR_NAME) / "voice.mp3",
    Path(DATA_DIR_NAME) / "speaker.wav",
    Path(DATA_DIR_NAME) / "speaker.mp3",
    Path("reference.wav"),
    Path("reference.mp3"),
    Path("voice.wav"),
    Path("voice.mp3"),
    Path("speaker.wav"),
    Path("speaker.mp3"),
]


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in {path}: {exc}") from exc


def has_segments_array(path: Path) -> bool:
    try:
        payload = load_json(path)
    except ConfigError:
        return False
    return isinstance(payload, dict) and isinstance(payload.get("segments"), list)


def is_example_file(path: Path) -> bool:
    name = path.name.lower()
    return ".example." in name or name.startswith("example.")


def detect_segment_json(base_dir: Path = BASE_DIR) -> Path:
    for filename in SEGMENT_FILENAMES:
        candidate = base_dir / filename
        if candidate.is_file():
            return candidate

    candidates: list[Path] = []
    seen: set[Path] = set()
    for pattern in SEGMENT_PATTERNS:
        for candidate in sorted(base_dir.glob(pattern)):
            if (
                not candidate.is_file()
                or candidate.name == MANIFEST_NAME
                or is_example_file(candidate)
            ):
                continue
            resolved = candidate.resolve()
            if resolved not in seen:
                candidates.append(candidate)
                seen.add(resolved)

    valid_candidates = [candidate for candidate in candidates if has_segments_array(candidate)]
    if valid_candidates:
        return valid_candidates[0]

    if candidates:
        matched = ", ".join(display_path(candidate) for candidate in candidates)
        raise ConfigError(
            "Found JSON files matching segment patterns, but none contain a "
            f"'segments' array: {matched}"
        )

    raise ConfigError(
        "No segment JSON file found. Fill data/segments.json, set "
        "LOCAL_TTS_SEGMENTS in .env, or pass --segments path/to/file.json."
    )


def detect_reference_audio(base_dir: Path = BASE_DIR) -> Path:
    for filename in REFERENCE_FILENAMES:
        candidate = base_dir / filename
        if candidate.is_file():
            return candidate

    expected = ", ".join(str(path) for path in REFERENCE_FILENAMES)
    raise ConfigError(
        "No reference voice file found. Add data/reference.wav or "
        f"data/reference.mp3, use one of {expected}, set LOCAL_TTS_REFERENCE "
        "in .env, or pass --reference path/to/reference.wav."
    )


def validate_reference_audio(path: Path) -> Path:
    if not path.is_file():
        raise ConfigError(f"Reference audio file does not exist: {path}")
    return path


def load_segments(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ConfigError(f"Segment JSON root must be an object: {path}")

    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ConfigError(f"No non-empty 'segments' array found in {path}")

    for index, segment in enumerate(segments, start=1):
        if not isinstance(segment, dict):
            raise ConfigError(f"Segment #{index} is not an object")

        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ConfigError(f"Segment #{index} has no text")

        audio_filename = segment.get("audio_filename")
        if not isinstance(audio_filename, str) or not audio_filename.strip():
            raise ConfigError(f"Segment #{index} has no audio_filename")

    return segments


def planned_audio_filename(audio_filename: str) -> Path:
    planned = Path(audio_filename)
    if planned.is_absolute() or ".." in planned.parts:
        raise ConfigError(f"Unsafe audio_filename outside output directory: {audio_filename}")

    if planned.suffix.lower() != ".mp3":
        planned = planned.with_suffix(".mp3")

    return planned


def planned_output_path(output_dir: Path, audio_filename: str) -> Path:
    return output_dir / planned_audio_filename(audio_filename)


def segment_label(segment: dict[str, Any], index: int) -> str:
    value = segment.get("id")
    if value is None or value == "":
        return f"segment_{index:04d}"
    return str(value)
