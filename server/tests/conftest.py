from __future__ import annotations

import uuid
from collections.abc import Generator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import hideandseek.models  # noqa: F401 — registers all tables on metadata
from hideandseek.db import get_session
from hideandseek.main import app
from hideandseek.models.game import Game, Player
from hideandseek.models.game_map import GameMap
from hideandseek.models.transit import TransitDataset
from hideandseek.models.types import GameStatus, MapSize


@pytest.fixture
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def client(session: Session) -> Generator[TestClient, None, None]:
    def _override_get_session() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# ── Factory functions ─────────────────────────────────────────────────────────


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
        'boundary': {'type': 'Polygon', 'coordinates': [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        'districts': [],
        'district_classes': [],
        'default_inventory': {
            'radars': [{'distance_m': 3000}, {'distance_m': 5000}, {'distance_m': None}],
            'thermometers': [{'distance_m': 500}, {'distance_m': None}],
        },
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
        'inventory': {
            'radars': [{'distance_m': 3000}, {'distance_m': 5000}, {'distance_m': None}],
            'thermometers': [{'distance_m': 500}, {'distance_m': None}],
        },
    }
    defaults.update(overrides)
    game = Game(**defaults)
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


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
