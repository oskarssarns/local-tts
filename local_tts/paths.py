from __future__ import annotations

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]


def resolve_repo_path(path: Path | str) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return (BASE_DIR / path).resolve()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR))
    except ValueError:
        return str(path)
