from __future__ import annotations

import sys
from typing import Any

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


def generate_segments(config: RunConfig) -> int:
    model_cache = resolve_repo_path(config.model_cache)
    model_label = MODEL_NAME
    if config.multilingual:
        model_label = f"{MODEL_NAME} multilingual {MULTILINGUAL_T3_MODEL}"

    if config.download_model:
        if config.env_file:
            print(f"Settings file: {display_path(config.env_file)}")
        print(f"Model cache: {display_path(model_cache)}")
        print(f"Model: {model_label}")
        configure_model_cache(model_cache)
        device = select_device(config.device)
        print(f"Device: {device}")
        print("Downloading/loading Chatterbox model...")
        load_chatterbox_model(config.multilingual, device)
        cleanup_device_memory(device)
        print(f"Model ready in {display_path(model_cache)}")
        return 0

    segments_path = resolve_repo_path(config.segments) if config.segments else detect_segment_json()
    reference_audio = (
        validate_reference_audio(resolve_repo_path(config.reference))
        if config.reference
        else detect_reference_audio()
    )
    output_dir = resolve_repo_path(config.output_dir)

    segments = load_segments(segments_path)

    if config.env_file:
        print(f"Settings file: {display_path(config.env_file)}")
    print(f"Segments JSON: {display_path(segments_path)}")
    print(f"Reference audio: {display_path(reference_audio)}")
    print(f"Output directory: {display_path(output_dir)}")
    print(f"Model cache: {display_path(model_cache)}")
    print(f"Segments: {len(segments)}")
    print(f"Model: {model_label}")
    print(f"Exaggeration: {config.exaggeration}")
    print(f"CFG weight: {config.cfg_weight}")

    if config.dry_run:
        print("Dry run: skipping ffmpeg check, dependency imports, model download, and inference.")
        print_plan(segments=segments, output_dir=output_dir, force=config.force)
        return 0

    ffmpeg = ensure_ffmpeg()
    device = select_device(config.device)
    configure_model_cache(model_cache)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Device: {device}")
    print("Loading Chatterbox model...")
    model = load_chatterbox_model(config.multilingual, device)

    manifest: list[dict[str, Any]] = []
    failures = 0

    for index, segment in enumerate(segments, start=1):
        output_path = planned_output_path(output_dir, segment["audio_filename"])
        label = segment_label(segment, index)

        if output_path.exists() and output_path.stat().st_size > 0 and not config.force:
            bytes_count = output_path.stat().st_size
            duration_seconds = probe_duration_seconds(output_path)
            print(f"skip {label} -> {display_path(output_path)}")
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
            continue

        print(f"generate {label} -> {display_path(output_path)}")
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
        except Exception as exc:  # Keep the manifest useful across long batches.
            failures += 1
            print(f"failed {label}: {exc}", file=sys.stderr)
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
        finally:
            cleanup_device_memory(device)

    write_manifest(output_dir, manifest)
    return 1 if failures else 0
