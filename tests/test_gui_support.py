from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import local_tts.gui_support as gui_support
from local_tts.gui_support import (
    SegmentDraft,
    build_segments_payload,
    default_storage_dir,
    model_cache_ready,
)
from local_tts.paths import BASE_DIR


class GuiSupportTests(unittest.TestCase):
    def test_default_storage_dir_uses_repo_root_when_not_frozen(self) -> None:
        with patch.object(gui_support.sys, "frozen", False, create=True):
            self.assertEqual(default_storage_dir(), BASE_DIR)

    def test_default_storage_dir_uses_local_appdata_when_frozen_on_windows(self) -> None:
        custom_appdata = str(Path("/tmp/LocalAppData"))
        with (
            patch.object(gui_support.sys, "frozen", True, create=True),
            patch.object(gui_support.sys, "platform", "win32"),
            patch.dict("os.environ", {"LOCALAPPDATA": custom_appdata}, clear=False),
        ):
            self.assertEqual(default_storage_dir(), Path(custom_appdata) / "LocalTTS")

    def test_build_segments_payload_normalizes_text_and_defaults_names(self) -> None:
        payload = build_segments_payload(
            [
                SegmentDraft(text="  First line.\nSecond line  "),
                SegmentDraft(segment_id="intro", audio_filename="shots/opening", text=" Hello "),
            ]
        )

        self.assertEqual(
            payload["segments"],
            [
                {
                    "id": "segment_001",
                    "audio_filename": "segment_001.mp3",
                    "text": "First line. Second line",
                },
                {
                    "id": "intro",
                    "audio_filename": "shots/opening.mp3",
                    "text": "Hello",
                },
            ],
        )

    def test_build_segments_payload_skips_blank_rows(self) -> None:
        payload = build_segments_payload(
            [
                SegmentDraft(text=""),
                SegmentDraft(text="   "),
                SegmentDraft(text="Keep me"),
            ]
        )

        self.assertEqual(len(payload["segments"]), 1)
        self.assertEqual(payload["segments"][0]["text"], "Keep me")

    def test_build_segments_payload_can_start_from_specific_index(self) -> None:
        payload = build_segments_payload(
            [SegmentDraft(text="Generate just this row")],
            starting_index=5,
        )

        self.assertEqual(payload["segments"][0]["id"], "segment_005")
        self.assertEqual(payload["segments"][0]["audio_filename"], "segment_005.mp3")

    def test_model_cache_ready_requires_downloaded_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            self.assertFalse(model_cache_ready(cache_dir))

            snapshot_dir = cache_dir / "hub" / "models--ResembleAI--chatterbox" / "snapshots" / "abc123"
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / "config.json").write_text("{}", encoding="utf-8")

            self.assertTrue(model_cache_ready(cache_dir))


if __name__ == "__main__":
    unittest.main()
