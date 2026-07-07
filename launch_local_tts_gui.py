#!/usr/bin/env python3
"""Desktop GUI entrypoint for local TTS generation."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from local_tts.gui import launch_gui
    except ImportError as exc:
        print(
            "GUI dependencies are missing. Install tkinter for your Python build "
            "(for example `sudo apt install python3-tk` on Debian/Ubuntu).",
            file=sys.stderr,
        )
        print(str(exc), file=sys.stderr)
        return 2

    launch_gui()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
