"""Shared utility functions."""

from __future__ import annotations

from pathlib import Path


def find_server_root() -> Path:
    """Walk up from this package to find the directory containing pyproject.toml."""
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / 'pyproject.toml').exists():
            return current
        current = current.parent
    msg = 'Could not find server root (no pyproject.toml in parent directories)'
    raise RuntimeError(msg)
