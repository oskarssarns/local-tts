from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from local_tts.audio import iterate_sampling_steps, start_audio_playback
from local_tts.errors import GenerationCancelledError


class AudioProgressTests(unittest.TestCase):
    def test_iterate_sampling_steps_reports_progress(self) -> None:
        events: list[tuple[str, int | None, int | None]] = []

        values = list(
            iterate_sampling_steps(
                [10, 20, 30],
                total=3,
                progress_callback=lambda stage, current, total: events.append((stage, current, total)),
            )
        )

        self.assertEqual(values, [10, 20, 30])
        self.assertEqual(
            events,
            [
                ("sampling", 0, 3),
                ("sampling", 1, 3),
                ("sampling", 2, 3),
                ("sampling", 3, 3),
            ],
        )

    def test_iterate_sampling_steps_can_cancel(self) -> None:
        seen: list[int] = []
        cancel_after_first_step = {"value": False}

        iterator = iterate_sampling_steps(
            [1, 2, 3],
            total=3,
            cancel_callback=lambda: cancel_after_first_step["value"],
        )

        first_value = next(iterator)
        seen.append(first_value)
        cancel_after_first_step["value"] = True

        with self.assertRaises(GenerationCancelledError):
            next(iterator)

        self.assertEqual(seen, [1])

    def test_start_audio_playback_invokes_ffplay(self) -> None:
        with patch("local_tts.audio.subprocess.Popen") as popen:
            start_audio_playback("/usr/bin/ffplay", Path("/tmp/example.mp3"))

        popen.assert_called_once()
        args, kwargs = popen.call_args
        self.assertEqual(
            args[0],
            [
                "/usr/bin/ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "error",
                "/tmp/example.mp3",
            ],
        )


if __name__ == "__main__":
    unittest.main()
