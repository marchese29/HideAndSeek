"""Map queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from hideandseek.db import get_session
from hideandseek_models.game_map import GameMap
from hideandseek_models.transit import TransitDataset


def list_maps(*, offset: int = 0, limit: int = 100) -> list[tuple[GameMap, str]]:
    """Return maps with their region, paginated by offset/limit."""
    session = get_session()
    stmt = (
        select(GameMap, TransitDataset.region)
        .join(TransitDataset, GameMap.transit_dataset_id == TransitDataset.id)
        .offset(offset)
        .limit(limit)
    )
    return [row._tuple() for row in session.execute(stmt)]


def get_map(map_id: uuid.UUID) -> GameMap | None:
    """Return a single map by ID, or None."""
    session = get_session()
    return session.get(GameMap, map_id)
