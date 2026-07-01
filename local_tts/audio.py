from __future__ import annotations

import gc
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .constants import MULTILINGUAL_T3_MODEL
from .errors import ConfigError


def configure_model_cache(model_cache: Path) -> None:
    model_cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(model_cache)
    os.environ["HF_HUB_CACHE"] = str(model_cache / "hub")


def ensure_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    raise ConfigError(
        "ffmpeg is required for MP3 conversion but was not found on PATH. "
        "Install it with your OS package manager, for example: "
        "sudo apt install ffmpeg, brew install ffmpeg, or choco install ffmpeg."
    )


def select_device(requested: str) -> str:
    try:
        import torch
    except ImportError as exc:
        raise ConfigError(
            "PyTorch is required for generation. Install dependencies with "
            "pip install -r requirements.txt."
        ) from exc

    if requested == "auto":
        if torch.cuda.is_available():
            return "cuda"
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        return "cpu"

    if requested == "cuda" and not torch.cuda.is_available():
        raise ConfigError("CUDA was requested with --device cuda, but torch.cuda is not available.")

    if requested == "mps":
        mps_backend = getattr(torch.backends, "mps", None)
        if mps_backend is None or not mps_backend.is_available():
            raise ConfigError("MPS was requested with --device mps, but torch MPS is not available.")

    return requested


def load_chatterbox_model(multilingual: bool, device: str) -> Any:
    try:
        if multilingual:
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            return ChatterboxMultilingualTTS.from_pretrained(
                device=device,
                t3_model=MULTILINGUAL_T3_MODEL,
            )

        from chatterbox.tts import ChatterboxTTS

        return ChatterboxTTS.from_pretrained(device=device)
    except ImportError as exc:
        raise ConfigError(
            "Chatterbox is not installed. Install dependencies with "
            "pip install -r requirements.txt."
        ) from exc


def waveform_duration_seconds(wav: Any, sample_rate: int) -> float | None:
    shape = getattr(wav, "shape", None)
    if not shape or sample_rate <= 0:
        return None

    sample_count = int(shape[-1])
    return round(sample_count / float(sample_rate), 3)


def probe_duration_seconds(path: Path) -> float | None:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None

    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    try:
        return round(float(result.stdout.strip()), 3)
    except ValueError:
        return None


def save_wav(path: Path, wav: Any, sample_rate: int) -> None:
    try:
        import torchaudio
    except ImportError as exc:
        raise ConfigError(
            "torchaudio is required to save temporary WAV files. Install dependencies with "
            "pip install -r requirements.txt."
        ) from exc

    torchaudio.save(str(path), wav, sample_rate, format="wav")


def convert_wav_to_mp3(ffmpeg: str, wav_path: Path, mp3_path: Path, bitrate: str) -> None:
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(wav_path),
            "-ar",
            "44100",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-f",
            "mp3",
            str(mp3_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown ffmpeg error"
        raise RuntimeError(f"ffmpeg failed: {message}")


def cleanup_device_memory(device: str) -> None:
    gc.collect()
    if device != "cuda":
        return

    try:
        import torch

        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()
    except Exception:
        pass


def generate_one_segment(
    *,
    model: Any,
    segment: dict[str, Any],
    output_path: Path,
    reference_audio: Path,
    multilingual: bool,
    language_id: str,
    exaggeration: float,
    cfg_weight: float,
    ffmpeg: str,
    bitrate: str,
) -> float | None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_wav = output_path.with_name(f"{output_path.stem}.tmp.wav")
    temp_mp3 = output_path.with_suffix(output_path.suffix + ".part")

    try:
        if multilingual:
            wav = model.generate(
                segment["text"],
                language_id=language_id,
                audio_prompt_path=str(reference_audio),
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
            )
        else:
            wav = model.generate(
                segment["text"],
                audio_prompt_path=str(reference_audio),
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
            )

        duration_seconds = waveform_duration_seconds(wav, int(model.sr))
        save_wav(temp_wav, wav, int(model.sr))
        convert_wav_to_mp3(ffmpeg, temp_wav, temp_mp3, bitrate)
        temp_mp3.replace(output_path)
        return duration_seconds
    finally:
        for path in (temp_wav, temp_mp3):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
