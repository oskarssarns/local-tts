from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .errors import ConfigError
from .paths import resolve_repo_path


DEFAULT_ENV_FILE = Path(".env")
DEVICE_CHOICES = {"auto", "cuda", "mps", "cpu"}


@dataclass(frozen=True)
class RunConfig:
    segments: Path | None
    reference: Path | None
    output_dir: Path
    force: bool
    dry_run: bool
    device: str
    multilingual: bool
    language_id: str
    exaggeration: float
    cfg_weight: float
    bitrate: str
    env_file: Path | None = None


def strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ConfigError(f"Invalid env line {line_number} in {path}: expected KEY=value")

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            raise ConfigError(f"Invalid env line {line_number} in {path}: empty key")
        values[key] = strip_optional_quotes(value.strip())

    return values


def parse_bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false, got: {value}")


def parse_float(value: str, name: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got: {value}") from exc


def env_defaults(env: dict[str, str]) -> dict[str, object]:
    defaults: dict[str, object] = {}
    path_keys = {
        "LOCAL_TTS_SEGMENTS": "segments",
        "LOCAL_TTS_REFERENCE": "reference",
        "LOCAL_TTS_OUTPUT_DIR": "output_dir",
    }
    bool_keys = {
        "LOCAL_TTS_FORCE": "force",
        "LOCAL_TTS_DRY_RUN": "dry_run",
        "LOCAL_TTS_MULTILINGUAL": "multilingual",
    }
    float_keys = {
        "LOCAL_TTS_EXAGGERATION": "exaggeration",
        "LOCAL_TTS_CFG_WEIGHT": "cfg_weight",
    }
    str_keys = {
        "LOCAL_TTS_LANGUAGE_ID": "language_id",
        "LOCAL_TTS_BITRATE": "bitrate",
    }

    for env_key, config_key in path_keys.items():
        if env_key in env and env[env_key]:
            defaults[config_key] = Path(env[env_key])

    for env_key, config_key in bool_keys.items():
        if env_key in env and env[env_key]:
            defaults[config_key] = parse_bool(env[env_key], env_key)

    for env_key, config_key in float_keys.items():
        if env_key in env and env[env_key]:
            defaults[config_key] = parse_float(env[env_key], env_key)

    for env_key, config_key in str_keys.items():
        if env_key in env and env[env_key]:
            defaults[config_key] = env[env_key]

    if "LOCAL_TTS_DEVICE" in env and env["LOCAL_TTS_DEVICE"]:
        device = env["LOCAL_TTS_DEVICE"]
        if device not in DEVICE_CHOICES:
            expected = ", ".join(sorted(DEVICE_CHOICES))
            raise ConfigError(f"LOCAL_TTS_DEVICE must be one of {expected}, got: {device}")
        defaults["device"] = device

    return defaults


def load_env_defaults(env_file: Path, use_env: bool) -> tuple[dict[str, object], Path | None]:
    if not use_env:
        return {}, None

    resolved = resolve_repo_path(env_file)
    if not resolved.is_file():
        return {}, None

    return env_defaults(read_env_file(resolved)), resolved


def parse_args(argv: Sequence[str] | None = None) -> RunConfig:
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Path to a non-secret settings env file. Defaults to .env.",
    )
    pre_parser.add_argument("--no-env", action="store_true", help="Ignore env-file settings.")
    pre_args, _ = pre_parser.parse_known_args(argv)

    defaults, loaded_env_file = load_env_defaults(pre_args.env_file, not pre_args.no_env)

    parser = argparse.ArgumentParser(
        parents=[pre_parser],
        description="Generate local Chatterbox voice-cloned MP3s from text segment JSON.",
    )
    parser.add_argument(
        "--segments",
        type=Path,
        default=defaults.get("segments"),
        help="Path to a segments JSON file. Defaults to LOCAL_TTS_SEGMENTS or data/segments.json.",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=defaults.get("reference"),
        help="Path to reference voice audio. Defaults to LOCAL_TTS_REFERENCE or data/reference.*.",
    )
    parser.add_argument("--output-dir", type=Path, default=defaults.get("output_dir", Path("output")))
    parser.add_argument(
        "--force",
        action=argparse.BooleanOptionalAction,
        default=defaults.get("force", False),
        help="Regenerate existing MP3 files.",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=defaults.get("dry_run", False),
        help="Validate inputs and print planned outputs without model inference.",
    )
    parser.add_argument(
        "--device",
        choices=sorted(DEVICE_CHOICES),
        default=defaults.get("device", "auto"),
        help="Inference device. Auto prefers CUDA, then MPS, then CPU.",
    )
    parser.add_argument(
        "--multilingual",
        action=argparse.BooleanOptionalAction,
        default=defaults.get("multilingual", False),
        help="Use ChatterboxMultilingualTTS with the v3 multilingual checkpoint.",
    )
    parser.add_argument(
        "--language-id",
        default=defaults.get("language_id", "en"),
        help="Language ID for multilingual mode.",
    )
    parser.add_argument(
        "--exaggeration",
        type=float,
        default=defaults.get("exaggeration", 0.35),
        help="Chatterbox expressiveness. Lower values favor stable narration.",
    )
    parser.add_argument(
        "--cfg-weight",
        type=float,
        default=defaults.get("cfg_weight", 0.3),
        help="Chatterbox CFG weight. Lower values can improve pacing for fast references.",
    )
    parser.add_argument(
        "--bitrate",
        default=defaults.get("bitrate", "192k"),
        help="MP3 bitrate passed to ffmpeg, for example 128k or 192k.",
    )

    args = parser.parse_args(argv)
    return RunConfig(
        segments=args.segments,
        reference=args.reference,
        output_dir=args.output_dir,
        force=args.force,
        dry_run=args.dry_run,
        device=args.device,
        multilingual=args.multilingual,
        language_id=args.language_id,
        exaggeration=args.exaggeration,
        cfg_weight=args.cfg_weight,
        bitrate=args.bitrate,
        env_file=None if args.no_env else loaded_env_file,
    )
