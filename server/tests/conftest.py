from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
import warnings
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from shapely.geometry import Point, Polygon
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from testcontainers.postgres import PostgresContainer

import hideandseek.db as db_module
from hideandseek.db import _session_var, session_dependency
from hideandseek.main import app
from hideandseek.models.base import Base
from hideandseek.models.game import Game, Player
from hideandseek.models.game_map import GameMap
from hideandseek.models.inventory import InventorySlot
from hideandseek.models.location import LocationUpdate
from hideandseek.models.map_feature import GameMapFeature, MapFeature
from hideandseek.models.question import Question
from hideandseek.models.transit import Stop, TransitDataset
from hideandseek.models.types import (
    MATCHING_CATEGORIES,
    MEASURING_CATEGORIES,
    FeatureCategory,
    GameStatus,
    MapSize,
    PlayerColor,
    QuestionStatus,
    QuestionType,
    category_key,
)
from hideandseek.queries.features import get_map_feature_categories

TEST_SECRET = 'test-secret-for-unit-tests'
TEST_SECRET_HASH = hashlib.sha256(TEST_SECRET.encode()).hexdigest()


def pytest_configure() -> None:
    """Auto-detect Docker socket and configure testcontainers.

    Runs before test collection. Uses ``docker context inspect`` to find the
    active Docker socket, handling colima and other non-default setups.
    Disables Ryuk only when the socket is non-default (Ryuk can't mount
    non-standard socket paths inside its container).
    """
    if os.environ.get('DOCKER_HOST'):
        return

    try:
        result = subprocess.run(
            ['docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        host = result.stdout.strip()
        if result.returncode == 0 and host:
            os.environ['DOCKER_HOST'] = host
            # Non-default sockets (e.g., colima) can't be mounted into Ryuk
            if host != 'unix:///var/run/docker.sock':
                os.environ.setdefault('TESTCONTAINERS_RYUK_DISABLED', 'true')
            return
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    warnings.warn(
        'Could not detect Docker socket. Set DOCKER_HOST if tests fail to connect.',
        stacklevel=1,
    )


@pytest.fixture(scope='session')
def _pg_engine() -> Generator[sa.Engine, None, None]:
    with PostgresContainer('postgis/postgis:16-3.4-alpine') as pg:
        url = pg.get_connection_url().replace('psycopg2', 'psycopg')
        # Set DATABASE_URL so the app lifespan's create_db_and_tables() works
        db_module.DATABASE_URL = url
        db_module.get_engine.cache_clear()
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(sa.text('CREATE EXTENSION IF NOT EXISTS postgis'))
            conn.commit()
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


@pytest.fixture
def session(_pg_engine: sa.Engine) -> Generator[Session, None, None]:
    connection = _pg_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    token = _session_var.set(sess)
    try:
        yield sess
    finally:
        _session_var.reset(token)
        sess.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(session: Session) -> Generator[TestClient, None, None]:
    async def _override_get_session() -> AsyncGenerator[Session, None]:
        token = _session_var.set(session)
        try:
            yield session
            session.flush()
        finally:
            _session_var.reset(token)

    app.dependency_overrides[session_dependency] = _override_get_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


# ── Factory functions ─────────────────────────────────────────────────────────

_DEFAULT_INVENTORY_TEMPLATE: dict[str, Any] = {
    'radars': [{'distance': 3000}, {'distance': 5000}, {'distance': None}],
    'thermometers': [{'distance': 500}, {'distance': None}],
}


def create_transit_dataset(session: Session, **overrides: Any) -> TransitDataset:
    defaults: dict[str, Any] = {
        'name': 'Test Transit',
        'region': 'Test Region',
    }
    defaults.update(overrides)
    ds = TransitDataset(**defaults)
    session.add(ds)
    session.flush()
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
    session.flush()
    session.refresh(gm)
    return gm


def create_game(session: Session, **overrides: Any) -> Game:
    if 'map_id' not in overrides:
        gm = create_game_map(session)
        overrides['map_id'] = gm.id
    inventory_template = overrides.pop('inventory_template', _DEFAULT_INVENTORY_TEMPLATE)
    host_player_id = overrides.pop('host_player_id', uuid.uuid4())
    defaults: dict[str, Any] = {
        'host_player_id': host_player_id,
        'join_code': overrides.pop('join_code', uuid.uuid4().hex[:4].upper()),
        'status': GameStatus.lobby,
        'hiding_time_min': 60,
        'base_question_delay_min': 5,
    }
    defaults.update(overrides)
    game = Game(**defaults)
    session.add(game)
    session.flush()
    session.refresh(game)

    # Create host player (matches real app behavior — POST /games always creates host as player)
    host_player = Player(
        id=host_player_id,
        game_id=game.id,
        name='Host',
        color=PlayerColor.red,
        secret_hash=TEST_SECRET_HASH,
    )
    session.add(host_player)
    session.flush()

    # Create InventorySlot rows from the template + map features
    _create_inventory_slots(session, game, inventory_template)

    return game


def _create_inventory_slots(session: Session, game: Game, template: dict[str, Any]) -> None:
    """Create InventorySlot rows from a default_inventory template and map features."""
    # Radar and thermometer slots from template
    for type_key, question_type in (
        ('radars', QuestionType.radar),
        ('thermometers', QuestionType.thermometer),
    ):
        for idx, slot_data in enumerate(template.get(type_key, [])):
            slot = InventorySlot(
                game_id=game.id,
                question_type=question_type,
                slot_index=idx,
                distance=slot_data.get('distance'),
            )
            session.add(slot)

    # Matching and measuring slots from map feature categories
    map_cats = get_map_feature_categories(game_map=game.game_map)
    sorted_cats = sorted(map_cats, key=lambda pair: category_key(pair[0], pair[1]))

    for question_type, type_categories in (
        (QuestionType.matching, MATCHING_CATEGORIES),
        (QuestionType.measuring, MEASURING_CATEGORIES),
    ):
        idx = 0
        for cat, cls in sorted_cats:
            if cat not in type_categories:
                continue
            slot = InventorySlot(
                game_id=game.id,
                question_type=question_type,
                slot_index=idx,
                category=cat,
                feature_class=cls,
            )
            session.add(slot)
            idx += 1

    session.flush()


def create_inventory_slot(
    session: Session,
    game_id: uuid.UUID,
    question_type: QuestionType = QuestionType.radar,
    slot_index: int = 0,
    distance: float | None = 3000,
    **overrides: Any,
) -> InventorySlot:
    """Create a single InventorySlot for testing."""
    defaults: dict[str, Any] = {
        'game_id': game_id,
        'question_type': question_type,
        'slot_index': slot_index,
        'distance': distance,
    }
    defaults.update(overrides)
    slot = InventorySlot(**defaults)
    session.add(slot)
    session.flush()
    session.refresh(slot)
    return slot


def create_player(session: Session, game_id: uuid.UUID, **overrides: Any) -> Player:
    if 'color' not in overrides:
        existing = session.scalars(select(Player).where(Player.game_id == game_id)).all()
        overrides['color'] = list(PlayerColor)[len(existing)]
    defaults: dict[str, Any] = {
        'game_id': game_id,
        'name': 'Test Player',
        'role': None,
        'secret_hash': TEST_SECRET_HASH,
    }
    defaults.update(overrides)
    player = Player(**defaults)
    session.add(player)
    session.flush()
    session.refresh(player)
    return player


def create_map_feature(session: Session, **overrides: Any) -> MapFeature:
    defaults: dict[str, Any] = {
        'category': FeatureCategory.hospital,
        'stable_id': f'test-feature-{uuid.uuid4().hex[:8]}',
        'name': 'Test Hospital',
        'shape': Point(0.5, 0.5),
    }
    defaults.update(overrides)
    feature = MapFeature(**defaults)
    session.add(feature)
    session.flush()
    session.refresh(feature)
    return feature


def create_game_map_feature(
    session: Session, game_map_id: uuid.UUID, map_feature_id: uuid.UUID
) -> GameMapFeature:
    link = GameMapFeature(game_map_id=game_map_id, map_feature_id=map_feature_id)
    session.add(link)
    session.flush()
    session.refresh(link)
    return link


def create_question(session: Session, game_id: uuid.UUID, **overrides: Any) -> Question:
    """Create a Question for testing. Defaults to an answered radar question."""
    defaults: dict[str, Any] = {
        'game_id': game_id,
        'sequence': 1,
        'question_type': QuestionType.radar,
        'status': QuestionStatus.answered,
        'asked_by': overrides.pop('asked_by', uuid.uuid4()),
        'seeker_location_start': Point(0.5, 0.5),
        'ask_count': 1,
        'slot_index': 0,
    }
    defaults.update(overrides)
    q = Question(**defaults)
    session.add(q)
    session.flush()
    session.refresh(q)
    return q


def create_location_update(
    session: Session, player_id: uuid.UUID, game_id: uuid.UUID, **overrides: Any
) -> LocationUpdate:
    """Create a LocationUpdate for testing."""
    defaults: dict[str, Any] = {
        'player_id': player_id,
        'game_id': game_id,
        'coordinates': Point(0.5, 0.5),
    }
    defaults.update(overrides)
    lu = LocationUpdate(**defaults)
    session.add(lu)
    session.flush()
    session.refresh(lu)
    return lu


def create_stop(session: Session, dataset_id: uuid.UUID, **overrides: Any) -> Stop:
    """Create a Stop for testing."""
    defaults: dict[str, Any] = {
        'dataset_id': dataset_id,
        'stable_id': f'stop-{uuid.uuid4().hex[:8]}',
        'name': 'Test Stop',
        'coordinates': Point(0.5, 0.5),
    }
    defaults.update(overrides)
    stop = Stop(**defaults)
    session.add(stop)
    session.flush()
    session.refresh(stop)
    return stop
