from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .constants import MODEL_NAME
from .paths import BASE_DIR
from .segments import normalize_text_for_tts, planned_audio_filename


WINDOWS_LOCAL_APPDATA = Path.home() / "AppData" / "Local"
MACOS_APP_SUPPORT = Path.home() / "Library" / "Application Support"
LINUX_SHARE_DIR = Path.home() / ".local" / "share"


@dataclass(frozen=True)
class SegmentDraft:
    text: str
    segment_id: str = ""
    audio_filename: str = ""


def default_storage_dir() -> Path:
    if not getattr(sys, "frozen", False):
        return BASE_DIR

    if sys.platform == "win32":
        base_dir = Path(os.environ.get("LOCALAPPDATA", WINDOWS_LOCAL_APPDATA))
        return base_dir / "LocalTTS"

    if sys.platform == "darwin":
        return MACOS_APP_SUPPORT / "LocalTTS"

    base_dir = Path(os.environ.get("XDG_DATA_HOME", LINUX_SHARE_DIR))
    return base_dir / "local-tts"


def model_cache_ready(model_cache: Path) -> bool:
    model_dir = model_cache / "hub" / "models--ResembleAI--chatterbox"
    if not model_dir.exists():
        return False

    snapshots_dir = model_dir / "snapshots"
    if snapshots_dir.exists():
        for candidate in snapshots_dir.rglob("*"):
            if candidate.is_file():
                return True

    for candidate in model_dir.rglob("*"):
        if candidate.is_file():
            return True

    return False


def build_segments_payload(
    drafts: Sequence[SegmentDraft],
    *,
    starting_index: int = 1,
) -> dict[str, list[dict[str, str]]]:
    segments: list[dict[str, str]] = []

    for index, draft in enumerate(drafts, start=starting_index):
        text = normalize_text_for_tts(draft.text)
        if not text:
            continue

        segment_id = draft.segment_id.strip() or f"segment_{index:03d}"
        raw_audio_filename = draft.audio_filename.strip() or f"{segment_id}.mp3"
        audio_filename = str(planned_audio_filename(raw_audio_filename))
        segments.append(
            {
                "id": segment_id,
                "audio_filename": audio_filename,
                "text": text,
            }
        )

    return {
        "metadata": {
            "generator": "local-tts-gui",
            "model": MODEL_NAME,
        },
        "segments": segments,
    }


def write_segments_payload(path: Path, payload: dict[str, list[dict[str, str]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
