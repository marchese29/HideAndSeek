"""Tests for the broadcast module — emit + subscribe."""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from unittest.mock import patch

import fakeredis
import pytest
from sqlalchemy.orm import Session

from hideandseek.broadcast.emit import _lobby_channel, emit
from hideandseek.broadcast.events import (
    GameStartedEvent,
    HostChangedEvent,
    PlayerJoinedEvent,
    PlayerLeftEvent,
    PlayerUpdatedEvent,
)
from hideandseek.models.types import LobbyEventType
from tests.conftest import create_game, create_player


@pytest.fixture
def fake_sync_redis() -> fakeredis.FakeRedis:
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server)


@pytest.fixture
def _patch_sync_redis(fake_sync_redis: fakeredis.FakeRedis) -> Generator[None, None, None]:
    with patch('hideandseek.broadcast.emit.get_sync_redis', return_value=fake_sync_redis):
        yield


@pytest.fixture
def _patch_no_redis() -> Generator[None, None, None]:
    with patch('hideandseek.broadcast.emit.get_sync_redis', return_value=None):
        yield


class TestEmitPlayerJoined:
    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_publishes_to_correct_channel(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)
        player = create_player(session, game.id, name='Alice')

        # Subscribe before emit
        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(_lobby_channel(game.id))

        emit(PlayerJoinedEvent(game=game, player=player))

        # Drain subscribe confirmation + actual message
        messages = []
        for _ in range(10):
            msg = pubsub.get_message()
            if msg is None:
                break
            if msg['type'] == 'message':
                messages.append(msg)

        assert len(messages) == 1
        parsed = json.loads(messages[0]['data'])
        assert parsed['event'] == LobbyEventType.player_joined
        assert parsed['data']['id'] == str(player.id)
        assert parsed['data']['name'] == 'Alice'

    @pytest.mark.usefixtures('_patch_no_redis')
    def test_raises_when_redis_unavailable(self, session: Session) -> None:
        game = create_game(session)
        player = create_player(session, game.id)
        with pytest.raises(RuntimeError, match='Redis unavailable'):
            emit(PlayerJoinedEvent(game=game, player=player))


class TestEmitPlayerUpdated:
    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_publishes_player_data(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)
        player = create_player(session, game.id, name='Bob')

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(_lobby_channel(game.id))

        emit(PlayerUpdatedEvent(game=game, player=player))

        messages = []
        for _ in range(10):
            msg = pubsub.get_message()
            if msg is None:
                break
            if msg['type'] == 'message':
                messages.append(msg)

        assert len(messages) == 1
        parsed = json.loads(messages[0]['data'])
        assert parsed['event'] == LobbyEventType.player_updated
        assert parsed['data']['name'] == 'Bob'


class TestEmitPlayerLeft:
    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_publishes_player_id(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)
        player_id = uuid.uuid4()

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(_lobby_channel(game.id))

        emit(PlayerLeftEvent(game=game, player_id=player_id))

        messages = []
        for _ in range(10):
            msg = pubsub.get_message()
            if msg is None:
                break
            if msg['type'] == 'message':
                messages.append(msg)

        assert len(messages) == 1
        parsed = json.loads(messages[0]['data'])
        assert parsed['event'] == LobbyEventType.player_left
        assert parsed['data']['player_id'] == str(player_id)


class TestEmitHostChanged:
    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_publishes_new_host(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)
        new_host_id = uuid.uuid4()

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(_lobby_channel(game.id))

        emit(HostChangedEvent(game=game, new_host_player_id=new_host_id))

        messages = []
        for _ in range(10):
            msg = pubsub.get_message()
            if msg is None:
                break
            if msg['type'] == 'message':
                messages.append(msg)

        assert len(messages) == 1
        parsed = json.loads(messages[0]['data'])
        assert parsed['event'] == LobbyEventType.host_changed
        assert parsed['data']['new_host_player_id'] == str(new_host_id)


class TestEmitGameStarted:
    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_publishes_sse_and_push(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(_lobby_channel(game.id))

        with patch('hideandseek.tasks.push.send_push') as mock_push:
            emit(GameStartedEvent(game=game))
            mock_push.delay.assert_called_once()

        messages = []
        for _ in range(10):
            msg = pubsub.get_message()
            if msg is None:
                break
            if msg['type'] == 'message':
                messages.append(msg)

        assert len(messages) == 1
        parsed = json.loads(messages[0]['data'])
        assert parsed['event'] == LobbyEventType.game_started
        assert 'host_player_id' in parsed['data']

    @pytest.mark.usefixtures('_patch_no_redis')
    def test_still_sends_push_when_redis_unavailable(self, session: Session) -> None:
        """game_started is dual-channel — push should still fire even if Redis is down."""
        game = create_game(session)
        with patch('hideandseek.tasks.push.send_push') as mock_push:
            emit(GameStartedEvent(game=game))
            mock_push.delay.assert_called_once()
