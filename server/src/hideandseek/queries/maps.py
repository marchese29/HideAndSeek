"""Map queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from hideandseek.db import db_read
from hideandseek.models.game_map import GameMap
from hideandseek.models.transit import TransitDataset


@db_read
def list_maps(session: Session, *, offset: int = 0, limit: int = 100) -> list[tuple[GameMap, str]]:
    """Return maps with their region, paginated by offset/limit."""
    stmt = (
        select(GameMap, TransitDataset.region)
        .join(TransitDataset, GameMap.transit_dataset_id == TransitDataset.id)
        .offset(offset)
        .limit(limit)
    )
    return [row._tuple() for row in session.execute(stmt)]


@db_read
def get_map(session: Session, map_id: uuid.UUID) -> GameMap | None:
    """Return a single map by ID, or None."""
    return session.get(GameMap, map_id)
