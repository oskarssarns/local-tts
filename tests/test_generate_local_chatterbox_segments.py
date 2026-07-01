from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from local_tts.errors import ConfigError
from local_tts.segments import (
    detect_reference_audio,
    detect_segment_json,
    load_segments,
    planned_output_path,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "generate_local_chatterbox_segments.py"


def write_segments(path: Path, segments: list[dict[str, object]] | None = None) -> None:
    payload = {
        "metadata": {
            "title": "Example project",
            "language": "en",
        },
        "segments": segments
        or [
            {
                "id": "intro",
                "slide": 1,
                "title": "Intro",
                "text": "Welcome to the lecture.",
                "audio_filename": "intro.wav",
            }
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


class LocalChatterboxSegmentTests(unittest.TestCase):
    def test_load_segments_validates_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lecture_segments.json"
            write_segments(path)

            segments = load_segments(path)

            self.assertEqual(segments[0]["id"], "intro")
            self.assertEqual(segments[0]["audio_filename"], "intro.wav")

    def test_load_segments_rejects_missing_audio_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lecture_segments.json"
            write_segments(
                path,
                [
                    {
                        "text": "This segment has no output name.",
                    }
                ],
            )

            with self.assertRaises(ConfigError):
                load_segments(path)

    def test_detect_reference_audio_uses_priority_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            (base_dir / "voice.mp3").write_bytes(b"voice")
            (base_dir / "reference.mp3").write_bytes(b"reference")

            detected = detect_reference_audio(base_dir)

            self.assertEqual(detected.name, "reference.mp3")

    def test_detect_reference_audio_prefers_data_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            data_dir = base_dir / "data"
            data_dir.mkdir()
            (base_dir / "reference.mp3").write_bytes(b"root")
            (data_dir / "reference.mp3").write_bytes(b"data")

            detected = detect_reference_audio(base_dir)

            self.assertEqual(detected, data_dir / "reference.mp3")

    def test_detect_segment_json_prefers_data_segments_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            data_dir = base_dir / "data"
            data_dir.mkdir()
            write_segments(base_dir / "lecture_segments.json")
            write_segments(data_dir / "segments.json")

            detected = detect_segment_json(base_dir)

            self.assertEqual(detected, data_dir / "segments.json")

    def test_detect_segment_json_ignores_example_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            data_dir = base_dir / "data"
            data_dir.mkdir()
            write_segments(data_dir / "segments.example.json")

            with self.assertRaises(ConfigError):
                detect_segment_json(base_dir)

    def test_detect_segment_json_finds_valid_pattern_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            write_segments(base_dir / "lecture_segments.json")

            detected = detect_segment_json(base_dir)

            self.assertEqual(detected.name, "lecture_segments.json")

    def test_planned_output_path_replaces_extension_and_blocks_traversal(self) -> None:
        output_dir = Path("/tmp/output")

        self.assertEqual(
            planned_output_path(output_dir, "segment.wav"),
            output_dir / "segment.mp3",
        )
        self.assertEqual(
            planned_output_path(output_dir, "nested/segment"),
            output_dir / "nested/segment.mp3",
        )

        with self.assertRaises(ConfigError):
            planned_output_path(output_dir, "../segment.mp3")

    def test_dry_run_subprocess_does_not_require_model_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            segments_path = base_dir / "lecture_segments.json"
            reference_path = base_dir / "reference.wav"
            write_segments(segments_path)
            reference_path.write_bytes(b"not real audio")

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--dry-run",
                    "--segments",
                    str(segments_path),
                    "--reference",
                    str(reference_path),
                    "--output-dir",
                    str(base_dir / "output"),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Dry run:", result.stdout)
            self.assertIn("would generate intro", result.stdout)
            self.assertFalse((base_dir / "output").exists())

    def test_subprocess_reads_non_secret_env_file_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            segments_path = base_dir / "segments.json"
            reference_path = base_dir / "reference.wav"
            env_path = base_dir / "settings.env"
            write_segments(segments_path)
            reference_path.write_bytes(b"not real audio")
            env_path.write_text(
                "\n".join(
                    [
                        f"LOCAL_TTS_SEGMENTS={segments_path}",
                        f"LOCAL_TTS_REFERENCE={reference_path}",
                        f"LOCAL_TTS_OUTPUT_DIR={base_dir / 'output'}",
                        "LOCAL_TTS_DRY_RUN=true",
                        "LOCAL_TTS_DEVICE=cpu",
                    ]
                ),
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--env-file",
                    str(env_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(f"Settings file: {env_path}", result.stdout)
            self.assertIn("Dry run:", result.stdout)
            self.assertIn("would generate intro", result.stdout)
            self.assertFalse((base_dir / "output").exists())


if __name__ == "__main__":
    unittest.main()
