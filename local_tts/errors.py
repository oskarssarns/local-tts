from __future__ import annotations


class ConfigError(RuntimeError):
    """Raised for predictable user-fixable setup errors."""


class GenerationCancelledError(RuntimeError):
    """Raised when a queued or active generation job is cancelled."""
