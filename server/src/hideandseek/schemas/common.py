"""Shared schema types used across both requests and responses."""

from __future__ import annotations

from fastapi import Query

DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 500


def pagination_params(
    offset: int = Query(default=0, ge=0, description='Number of items to skip.'),
    limit: int = Query(
        default=DEFAULT_PAGE_LIMIT,
        ge=1,
        le=MAX_PAGE_LIMIT,
        description='Maximum number of items to return.',
    ),
) -> tuple[int, int]:
    """Dependency that extracts and validates offset/limit query params."""
    return offset, limit
