"""Tests for the broadcast module — emit + subscribe."""

from __future__ import annotations

import json
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import fakeredis
import pytest
from sqlalchemy.orm import Session

from hideandseek.broadcast.emit import _lobby_channel, emit, emit_gameplay
from hideandseek.broadcast.events import (
    GameStartedEvent,
    HostChangedEvent,
    PlayerJoinedEvent,
    PlayerLeftEvent,
    PlayerLocationEvent,
    PlayerUpdatedEvent,
)
from hideandseek.models.types import GameplayEventType, LobbyEventType, PlayerColor, PlayerRole
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


# ── Gameplay location events ────────────────────────────────────────────────


def _location_event(
    game_id: uuid.UUID,
    *,
    role: PlayerRole = PlayerRole.hider,
    name: str = 'Alice',
    color: PlayerColor = PlayerColor.red,
    lng: float = -0.141,
    lat: float = 51.515,
    timestamp: datetime | None = None,
) -> PlayerLocationEvent:
    return PlayerLocationEvent(
        game_id=game_id,
        player_id=uuid.uuid4(),
        name=name,
        color=color,
        role=role,
        coordinates={'type': 'Point', 'coordinates': [lng, lat]},
        timestamp=timestamp or datetime(2026, 2, 11, 10, 0, 0, tzinfo=UTC),
    )


def _drain_channel_messages(pubsub: Any, channels: list[str]) -> dict[str, list[dict]]:
    """Drain all pending messages from a pubsub, grouped by channel."""
    result: dict[str, list[dict]] = {ch: [] for ch in channels}
    for _ in range(50):
        msg = pubsub.get_message()
        if msg is None:
            break
        if msg['type'] != 'message':
            continue
        ch = msg['channel']
        if isinstance(ch, bytes):
            ch = ch.decode()
        if ch in result:
            result[ch].append(json.loads(msg['data']))
    return result


class TestEmitGameplayHiderLocation:
    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_hider_location_on_hider_channel_only(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)
        hider_ch = f'game:{game.id}:hider-events'
        seeker_ch = f'game:{game.id}:seeker-events'

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(hider_ch, seeker_ch)

        emit_gameplay(_location_event(game.id, role=PlayerRole.hider, name='HiderAlice'))

        msgs = _drain_channel_messages(pubsub, [hider_ch, seeker_ch])
        assert len(msgs[hider_ch]) == 1
        assert msgs[hider_ch][0]['event'] == GameplayEventType.player_location
        assert msgs[hider_ch][0]['data']['name'] == 'HiderAlice'
        assert msgs[seeker_ch] == []


class TestEmitGameplaySeekerLocation:
    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_seeker_location_on_both_channels(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)
        hider_ch = f'game:{game.id}:hider-events'
        seeker_ch = f'game:{game.id}:seeker-events'

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(hider_ch, seeker_ch)

        emit_gameplay(_location_event(game.id, role=PlayerRole.seeker, name='SeekerBob'))

        msgs = _drain_channel_messages(pubsub, [hider_ch, seeker_ch])
        assert len(msgs[hider_ch]) == 1
        assert len(msgs[seeker_ch]) == 1
        # Both channels get the same data
        for ch_msgs in [msgs[hider_ch], msgs[seeker_ch]]:
            assert ch_msgs[0]['event'] == GameplayEventType.player_location
            data = ch_msgs[0]['data']
            assert data['name'] == 'SeekerBob'
            assert data['role'] == PlayerRole.seeker
            assert data['coordinates'] == {'type': 'Point', 'coordinates': [-0.141, 51.515]}

    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_location_data_shape(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        """Verify the event data matches the GamePlayer schema shape."""
        game = create_game(session)
        hider_ch = f'game:{game.id}:hider-events'

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(hider_ch)

        event = _location_event(
            game.id,
            role=PlayerRole.seeker,
            name='Bob',
            color=PlayerColor.blue,
            lng=1.5,
            lat=52.0,
        )
        emit_gameplay(event)

        msgs = _drain_channel_messages(pubsub, [hider_ch])
        data = msgs[hider_ch][0]['data']
        assert data['id'] == str(event.player_id)
        assert data['name'] == 'Bob'
        assert data['color'] == 'blue'
        assert data['role'] == 'seeker'
        assert data['coordinates'] == {'type': 'Point', 'coordinates': [1.5, 52.0]}
        assert data['timestamp'] == '2026-02-11T10:00:00+00:00'


class TestEmitGameplayLocationRedisUnavailable:
    @pytest.mark.usefixtures('_patch_no_redis')
    def test_raises_when_redis_unavailable(self, session: Session) -> None:
        game = create_game(session)
        with pytest.raises(RuntimeError, match='Redis unavailable'):
            emit_gameplay(_location_event(game.id))
