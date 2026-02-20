from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from geoalchemy2 import load_spatialite
from shapely.geometry import Point, Polygon
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import hideandseek.models  # noqa: F401 — registers all tables on metadata
from hideandseek.db import _session_var, get_session
from hideandseek.main import app
from hideandseek.models.game import Game, Player
from hideandseek.models.game_map import GameMap
from hideandseek.models.inventory import InventorySlot
from hideandseek.models.map_feature import GameMapFeature, MapFeature
from hideandseek.models.transit import TransitDataset
from hideandseek.models.types import FeatureCategory, GameStatus, MapSize, SlotType


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    sa.event.listen(engine, 'connect', load_spatialite)  # type: ignore[attr-defined]
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        token = _session_var.set(session)
        try:
            yield session
        finally:
            _session_var.reset(token)


@pytest.fixture
def client(session: Session) -> Generator[TestClient, None, None]:
    async def _override_get_session() -> AsyncGenerator[Session, None]:
        token = _session_var.set(session)
        try:
            yield session
            session.commit()
        finally:
            _session_var.reset(token)

    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# ── Factory functions ─────────────────────────────────────────────────────────

_DEFAULT_INVENTORY_TEMPLATE: dict[str, Any] = {
    'radars': [{'distance_m': 3000}, {'distance_m': 5000}, {'distance_m': None}],
    'thermometers': [{'distance_m': 500}, {'distance_m': None}],
}


def create_transit_dataset(session: Session, **overrides: Any) -> TransitDataset:
    defaults: dict[str, Any] = {
        'name': 'Test Transit',
        'region': 'Test Region',
    }
    defaults.update(overrides)
    ds = TransitDataset(**defaults)
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


def create_game_map(session: Session, **overrides: Any) -> GameMap:
    if 'transit_dataset_id' not in overrides:
        ds = create_transit_dataset(session)
        overrides['transit_dataset_id'] = ds.id
    defaults: dict[str, Any] = {
        'name': 'Test Map',
        'size': MapSize.medium,
        'boundary': Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
        'districts': [],
        'district_classes': [],
        'default_inventory': _DEFAULT_INVENTORY_TEMPLATE,
    }
    defaults.update(overrides)
    gm = GameMap(**defaults)
    session.add(gm)
    session.commit()
    session.refresh(gm)
    return gm


def create_game(session: Session, **overrides: Any) -> Game:
    if 'map_id' not in overrides:
        gm = create_game_map(session)
        overrides['map_id'] = gm.id
    inventory_template = overrides.pop('inventory_template', _DEFAULT_INVENTORY_TEMPLATE)
    defaults: dict[str, Any] = {
        'host_client_id': uuid.uuid4(),
        'join_code': overrides.pop('join_code', uuid.uuid4().hex[:4].upper()),
        'status': GameStatus.lobby,
        'timing': {
            'hiding_time_min': 30,
            'location_question_delay_min': 5,
            'move_hide_time_min': 15,
            'rest_periods': [],
        },
    }
    defaults.update(overrides)
    game = Game(**defaults)
    session.add(game)
    session.commit()
    session.refresh(game)

    # Create InventorySlot rows from the template
    _create_inventory_slots(session, game.id, inventory_template)

    return game


def _create_inventory_slots(session: Session, game_id: uuid.UUID, template: dict[str, Any]) -> None:
    """Create InventorySlot rows from a default_inventory template."""
    for slot_type_str in ('radars', 'thermometers'):
        slot_type = SlotType.radar if slot_type_str == 'radars' else SlotType.thermometer
        for idx, slot_data in enumerate(template.get(slot_type_str, [])):
            slot = InventorySlot(
                game_id=game_id,
                slot_type=slot_type,
                slot_index=idx,
                distance_m=slot_data.get('distance_m'),
            )
            session.add(slot)
    session.commit()


def create_inventory_slot(
    session: Session,
    game_id: uuid.UUID,
    slot_type: SlotType = SlotType.radar,
    slot_index: int = 0,
    distance_m: int | None = 3000,
    **overrides: Any,
) -> InventorySlot:
    """Create a single InventorySlot for testing."""
    defaults: dict[str, Any] = {
        'game_id': game_id,
        'slot_type': slot_type,
        'slot_index': slot_index,
        'distance_m': distance_m,
    }
    defaults.update(overrides)
    slot = InventorySlot(**defaults)
    session.add(slot)
    session.commit()
    session.refresh(slot)
    return slot


def create_player(session: Session, game_id: uuid.UUID, **overrides: Any) -> Player:
    defaults: dict[str, Any] = {
        'game_id': game_id,
        'client_id': uuid.uuid4(),
        'name': 'Test Player',
        'color': '#FF5733',
        'role': None,
    }
    defaults.update(overrides)
    player = Player(**defaults)
    session.add(player)
    session.commit()
    session.refresh(player)
    return player


def create_map_feature(session: Session, **overrides: Any) -> MapFeature:
    defaults: dict[str, Any] = {
        'category': FeatureCategory.hospital,
        'stable_id': f'test-feature-{uuid.uuid4().hex[:8]}',
        'name': 'Test Hospital',
        'geometry': Point(0.5, 0.5),
    }
    defaults.update(overrides)
    feature = MapFeature(**defaults)
    session.add(feature)
    session.commit()
    session.refresh(feature)
    return feature


def create_game_map_feature(
    session: Session, game_map_id: uuid.UUID, map_feature_id: uuid.UUID
) -> GameMapFeature:
    link = GameMapFeature(game_map_id=game_map_id, map_feature_id=map_feature_id)
    session.add(link)
    session.commit()
    session.refresh(link)
    return link
