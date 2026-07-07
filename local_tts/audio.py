from __future__ import annotations

import gc
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from .constants import MULTILINGUAL_T3_MODEL
from .errors import ConfigError, GenerationCancelledError
from .paths import BASE_DIR


SegmentProgressCallback = Callable[[str, int | None, int | None], None]
CancelCallback = Callable[[], bool]


def find_binary(name: str) -> str | None:
    binary = shutil.which(name)
    if binary:
        return binary

    suffix = ".exe" if os.name == "nt" else ""
    executable_name = name if name.endswith(suffix) else f"{name}{suffix}"
    candidate_dirs = [BASE_DIR]

    if getattr(sys, "frozen", False):
        candidate_dirs.insert(0, Path(sys.executable).resolve().parent)

    for directory in candidate_dirs:
        candidate = directory / executable_name
        if candidate.is_file():
            return str(candidate)

    return None


def configure_model_cache(model_cache: Path) -> None:
    model_cache.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(model_cache)
    os.environ["HF_HUB_CACHE"] = str(model_cache / "hub")


def ensure_ffmpeg() -> str:
    ffmpeg = find_binary("ffmpeg")
    if ffmpeg:
        return ffmpeg

    raise ConfigError(
        "ffmpeg is required for MP3 conversion but was not found on PATH. "
        "Install it with your OS package manager, for example: "
        "sudo apt install ffmpeg, brew install ffmpeg, or choco install ffmpeg."
    )


def ensure_ffplay() -> str:
    ffplay = find_binary("ffplay")
    if ffplay:
        return ffplay

    raise ConfigError(
        "ffplay is required for inline audio playback but was not found on PATH. "
        "Install ffmpeg with ffplay support, or use a build that includes ffplay."
    )


def start_audio_playback(ffplay: str, audio_path: Path) -> subprocess.Popen:
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    return subprocess.Popen(
        [
            ffplay,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "error",
            str(audio_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
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
    ffprobe = find_binary("ffprobe")
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


def raise_if_cancelled(cancel_callback: CancelCallback | None) -> None:
    if cancel_callback is not None and cancel_callback():
        raise GenerationCancelledError("Generation cancelled.")


def emit_segment_progress(
    progress_callback: SegmentProgressCallback | None,
    stage: str,
    current: int | None = None,
    total: int | None = None,
) -> None:
    if progress_callback is None:
        return
    progress_callback(stage, current, total)


def iterate_sampling_steps(
    iterable,
    *,
    total: int | None,
    progress_callback: SegmentProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> Iterator[Any]:
    emit_segment_progress(progress_callback, "sampling", 0, total)
    for index, item in enumerate(iterable, start=1):
        raise_if_cancelled(cancel_callback)
        yield item
        emit_segment_progress(progress_callback, "sampling", index, total)
        raise_if_cancelled(cancel_callback)


@contextmanager
def patch_sampling_progress(
    progress_callback: SegmentProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> Iterator[None]:
    if progress_callback is None and cancel_callback is None:
        yield
        return

    try:
        import chatterbox.models.t3.t3 as t3_module
    except ImportError:
        yield
        return

    original_tqdm = t3_module.tqdm

    def instrumented_tqdm(iterable, *args, **kwargs):
        wrapped = original_tqdm(iterable, *args, **kwargs)
        total = kwargs.get("total")
        if total is None:
            total = getattr(wrapped, "total", None)
        if total is None:
            try:
                total = len(iterable)
            except TypeError:
                total = None
        return iterate_sampling_steps(
            wrapped,
            total=total,
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        )

    t3_module.tqdm = instrumented_tqdm
    try:
        yield
    finally:
        t3_module.tqdm = original_tqdm


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
    progress_callback: SegmentProgressCallback | None = None,
    cancel_callback: CancelCallback | None = None,
) -> float | None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_wav = output_path.with_name(f"{output_path.stem}.tmp.wav")
    temp_mp3 = output_path.with_suffix(output_path.suffix + ".part")

    try:
        raise_if_cancelled(cancel_callback)
        emit_segment_progress(progress_callback, "conditioning")
        with patch_sampling_progress(
            progress_callback=progress_callback,
            cancel_callback=cancel_callback,
        ):
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

        raise_if_cancelled(cancel_callback)
        duration_seconds = waveform_duration_seconds(wav, int(model.sr))
        emit_segment_progress(progress_callback, "encoding")
        save_wav(temp_wav, wav, int(model.sr))
        raise_if_cancelled(cancel_callback)
        emit_segment_progress(progress_callback, "finalizing")
        convert_wav_to_mp3(ffmpeg, temp_wav, temp_mp3, bitrate)
        temp_mp3.replace(output_path)
        emit_segment_progress(progress_callback, "done", 1, 1)
        return duration_seconds
    finally:
        for path in (temp_wav, temp_mp3):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass
