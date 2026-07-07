from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable

from .audio import (
    cleanup_device_memory,
    configure_model_cache,
    ensure_ffmpeg,
    generate_one_segment,
    load_chatterbox_model,
    probe_duration_seconds,
    select_device,
)
from .config import RunConfig
from .constants import MODEL_NAME, MULTILINGUAL_T3_MODEL
from .manifest import manifest_entry, write_manifest
from .paths import display_path, resolve_repo_path
from .segments import (
    detect_reference_audio,
    detect_segment_json,
    load_segments,
    planned_output_path,
    segment_label,
    validate_reference_audio,
)


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    message: str
    current: int | None = None
    total: int | None = None
    status: str = "info"


ProgressCallback = Callable[[ProgressEvent], None]
LogCallback = Callable[[str], None]


def emit_progress(
    callback: ProgressCallback | None,
    *,
    stage: str,
    message: str,
    current: int | None = None,
    total: int | None = None,
    status: str = "info",
) -> None:
    if callback is None:
        return
    callback(
        ProgressEvent(
            stage=stage,
            message=message,
            current=current,
            total=total,
            status=status,
        )
    )


def stdout_log(message: str) -> None:
    print(message)


def stderr_log(message: str) -> None:
    print(message, file=sys.stderr)


def print_plan(
    *,
    segments: list[dict[str, Any]],
    output_dir,
    force: bool,
) -> None:
    for index, segment in enumerate(segments, start=1):
        output_path = planned_output_path(output_dir, segment["audio_filename"])
        label = segment_label(segment, index)
        if output_path.exists() and output_path.stat().st_size > 0 and not force:
            action = "would skip existing"
        else:
            action = "would generate"
        print(f"{action} {label} -> {display_path(output_path)}")


def generate_segments(
    config: RunConfig,
    *,
    progress_callback: ProgressCallback | None = None,
    logger: LogCallback | None = None,
    error_logger: LogCallback | None = None,
) -> int:
    logger = logger or stdout_log
    error_logger = error_logger or stderr_log
    model_cache = resolve_repo_path(config.model_cache)
    model_label = MODEL_NAME
    if config.multilingual:
        model_label = f"{MODEL_NAME} multilingual {MULTILINGUAL_T3_MODEL}"

    if config.download_model:
        if config.env_file:
            logger(f"Settings file: {display_path(config.env_file)}")
        logger(f"Model cache: {display_path(model_cache)}")
        logger(f"Model: {model_label}")
        emit_progress(
            progress_callback,
            stage="model",
            message="Preparing model cache...",
            status="working",
        )
        configure_model_cache(model_cache)
        device = select_device(config.device)
        logger(f"Device: {device}")
        logger("Downloading/loading Chatterbox model...")
        emit_progress(
            progress_callback,
            stage="model",
            message="Downloading/loading model...",
            status="working",
        )
        load_chatterbox_model(config.multilingual, device)
        cleanup_device_memory(device)
        logger(f"Model ready in {display_path(model_cache)}")
        emit_progress(
            progress_callback,
            stage="model",
            message=f"Model ready in {display_path(model_cache)}",
            status="success",
        )
        return 0

    segments_path = resolve_repo_path(config.segments) if config.segments else detect_segment_json()
    reference_audio = (
        validate_reference_audio(resolve_repo_path(config.reference))
        if config.reference
        else detect_reference_audio()
    )
    output_dir = resolve_repo_path(config.output_dir)

    segments = load_segments(segments_path)
    total_segments = len(segments)

    if config.env_file:
        logger(f"Settings file: {display_path(config.env_file)}")
    logger(f"Segments JSON: {display_path(segments_path)}")
    logger(f"Reference audio: {display_path(reference_audio)}")
    logger(f"Output directory: {display_path(output_dir)}")
    logger(f"Model cache: {display_path(model_cache)}")
    logger(f"Segments: {total_segments}")
    logger(f"Model: {model_label}")
    logger(f"Exaggeration: {config.exaggeration}")
    logger(f"CFG weight: {config.cfg_weight}")

    if config.dry_run:
        logger("Dry run: skipping ffmpeg check, dependency imports, model download, and inference.")
        print_plan(segments=segments, output_dir=output_dir, force=config.force)
        return 0

    emit_progress(
        progress_callback,
        stage="generation",
        message="Checking ffmpeg and selecting device...",
        current=0,
        total=total_segments,
        status="working",
    )
    ffmpeg = ensure_ffmpeg()
    device = select_device(config.device)
    configure_model_cache(model_cache)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger(f"Device: {device}")
    logger("Loading Chatterbox model...")
    emit_progress(
        progress_callback,
        stage="generation",
        message="Loading model...",
        current=0,
        total=total_segments,
        status="working",
    )
    model = load_chatterbox_model(config.multilingual, device)

    manifest: list[dict[str, Any]] = []
    failures = 0

    for index, segment in enumerate(segments, start=1):
        output_path = planned_output_path(output_dir, segment["audio_filename"])
        label = segment_label(segment, index)

        if output_path.exists() and output_path.stat().st_size > 0 and not config.force:
            bytes_count = output_path.stat().st_size
            duration_seconds = probe_duration_seconds(output_path)
            logger(f"skip {label} -> {display_path(output_path)}")
            manifest.append(
                manifest_entry(
                    segment=segment,
                    output_dir=output_dir,
                    output_path=output_path,
                    status="skipped_existing",
                    bytes_count=bytes_count,
                    duration_seconds=duration_seconds,
                    model=model_label,
                    reference_audio=reference_audio,
                    device=device,
                )
            )
            emit_progress(
                progress_callback,
                stage="generation",
                message=f"Skipped {label}",
                current=index,
                total=total_segments,
                status="success",
            )
            continue

        logger(f"generate {label} -> {display_path(output_path)}")
        emit_progress(
            progress_callback,
            stage="generation",
            message=f"Generating {label}...",
            current=index - 1,
            total=total_segments,
            status="working",
        )
        try:
            duration_seconds = generate_one_segment(
                model=model,
                segment=segment,
                output_path=output_path,
                reference_audio=reference_audio,
                multilingual=config.multilingual,
                language_id=config.language_id,
                exaggeration=config.exaggeration,
                cfg_weight=config.cfg_weight,
                ffmpeg=ffmpeg,
                bitrate=config.bitrate,
            )
            bytes_count = output_path.stat().st_size
            manifest.append(
                manifest_entry(
                    segment=segment,
                    output_dir=output_dir,
                    output_path=output_path,
                    status="generated",
                    bytes_count=bytes_count,
                    duration_seconds=duration_seconds,
                    model=model_label,
                    reference_audio=reference_audio,
                    device=device,
                )
            )
            emit_progress(
                progress_callback,
                stage="generation",
                message=f"Generated {label}",
                current=index,
                total=total_segments,
                status="success",
            )
        except Exception as exc:  # Keep the manifest useful across long batches.
            failures += 1
            error_logger(f"failed {label}: {exc}")
            manifest.append(
                manifest_entry(
                    segment=segment,
                    output_dir=output_dir,
                    output_path=output_path,
                    status="failed",
                    bytes_count=0,
                    model=model_label,
                    reference_audio=reference_audio,
                    device=device,
                    error_message=str(exc),
                )
            )
            emit_progress(
                progress_callback,
                stage="generation",
                message=f"Failed {label}",
                current=index,
                total=total_segments,
                status="error",
            )
        finally:
            cleanup_device_memory(device)

    write_manifest(output_dir, manifest)
    emit_progress(
        progress_callback,
        stage="generation",
        message="Generation complete." if failures == 0 else "Generation finished with failures.",
        current=total_segments,
        total=total_segments,
        status="success" if failures == 0 else "error",
    )
    return 1 if failures else 0
