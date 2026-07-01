#!/usr/bin/env python3
"""CLI entrypoint for local Chatterbox text-to-speech generation."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from local_tts.config import parse_args
from local_tts.errors import ConfigError
from local_tts.generator import generate_segments


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return generate_segments(parse_args(argv))
    except ConfigError as exc:
        print(f"setup error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
