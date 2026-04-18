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
from geojson_pydantic import Point as GeoJSONPoint
from sqlalchemy.orm import Session

from hideandseek.broadcast.emit import emit
from hideandseek.broadcast.events import (
    GameStartedEvent,
    HostChangedEvent,
    PlayerJoinedEvent,
    PlayerLeftEvent,
    PlayerUpdatedEvent,
)
from hideandseek_core.broadcast.emit import (
    emit_gameplay,
    hider_channel,
    lobby_channel,
    publish_sse,
    seeker_channel,
)
from hideandseek_core.broadcast.events import PlayerLocationEvent
from hideandseek_models.types import GameplayEventType, LobbyEventType, PlayerColor, PlayerRole
from tests.conftest import create_game, create_player


@pytest.fixture
def fake_sync_redis() -> fakeredis.FakeRedis:
    server = fakeredis.FakeServer()
    return fakeredis.FakeRedis(server=server)


@pytest.fixture
def _patch_sync_redis(fake_sync_redis: fakeredis.FakeRedis) -> Generator[None, None, None]:
    with patch('hideandseek_core.broadcast.emit.get_sync_redis', return_value=fake_sync_redis):
        yield


@pytest.fixture
def _patch_no_redis() -> Generator[None, None, None]:
    with patch('hideandseek_core.broadcast.emit.get_sync_redis', return_value=None):
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
        pubsub.subscribe(lobby_channel(game.id).pubsub)

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
        pubsub.subscribe(lobby_channel(game.id).pubsub)

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
        pubsub.subscribe(lobby_channel(game.id).pubsub)

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
        pubsub.subscribe(lobby_channel(game.id).pubsub)

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
    def test_publishes_sse_best_effort(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(lobby_channel(game.id).pubsub)

        emit(GameStartedEvent(game=game))

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
    def test_swallows_error_when_redis_unavailable(self, session: Session) -> None:
        """game_started SSE is best-effort — no exception when Redis is down.

        Push is now the router's responsibility (not emit's).
        """
        game = create_game(session)
        # Should not raise — SSE failure is logged and swallowed
        emit(GameStartedEvent(game=game))


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
        coordinates=GeoJSONPoint(type='Point', coordinates=[lng, lat]),  # type: ignore[arg-type]
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
        assert data['player_id'] == str(event.player_id)
        assert data['name'] == 'Bob'
        assert data['color'] == 'blue'
        assert data['role'] == 'seeker'
        assert data['coordinates'] == {'type': 'Point', 'coordinates': [1.5, 52.0]}
        assert data['timestamp'] == '2026-02-11T10:00:00Z'


class TestEmitGameplayLocationRedisUnavailable:
    @pytest.mark.usefixtures('_patch_no_redis')
    def test_raises_when_redis_unavailable(self, session: Session) -> None:
        game = create_game(session)
        with pytest.raises(RuntimeError, match='Redis unavailable'):
            emit_gameplay(_location_event(game.id))


# ── Per-channel sequence numbering ──────────────────────────────────────────


def _seq_counter(redis: fakeredis.FakeRedis, key: str) -> int:
    """Read a sync fakeredis counter, normalizing bytes/None/int responses."""
    value: Any = redis.get(key)
    if value is None:
        return 0
    if isinstance(value, bytes):
        return int(value.decode())
    return int(value)


class TestSequenceNumbering:
    """Every publish attaches a monotonic per-channel sequence number."""

    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_lobby_sequence_increments_per_emit(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)
        player = create_player(session, game.id, name='Alice')

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(lobby_channel(game.id).pubsub)

        emit(PlayerJoinedEvent(game=game, player=player))
        emit(PlayerUpdatedEvent(game=game, player=player))
        emit(PlayerLeftEvent(game=game, player_id=player.id))

        messages = []
        for _ in range(20):
            msg = pubsub.get_message()
            if msg is None:
                break
            if msg['type'] == 'message':
                messages.append(json.loads(msg['data']))

        assert [m['sequence'] for m in messages] == [1, 2, 3]
        # Counter is also readable directly
        assert _seq_counter(fake_sync_redis, lobby_channel(game.id).seq) == 3

    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_hider_and_seeker_channels_have_independent_sequences(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)
        hider_ch = hider_channel(game.id)
        seeker_ch = seeker_channel(game.id)

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(hider_ch.pubsub, seeker_ch.pubsub)

        # Hider-only event (goes only to hider channel)
        emit_gameplay(_location_event(game.id, role=PlayerRole.hider))
        # Seeker event (goes to both channels)
        emit_gameplay(_location_event(game.id, role=PlayerRole.seeker))

        msgs = _drain_channel_messages(pubsub, [hider_ch.pubsub, seeker_ch.pubsub])
        # Hider got two events (its own + the seeker-broadcast one)
        assert [m['sequence'] for m in msgs[hider_ch.pubsub]] == [1, 2]
        # Seeker got only the seeker event — its own sequence starts at 1
        assert [m['sequence'] for m in msgs[seeker_ch.pubsub]] == [1]
        assert _seq_counter(fake_sync_redis, hider_ch.seq) == 2
        assert _seq_counter(fake_sync_redis, seeker_ch.seq) == 1

    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_envelope_carries_sequence_event_and_data(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        game = create_game(session)
        player = create_player(session, game.id, name='Alice')

        pubsub = fake_sync_redis.pubsub()
        pubsub.subscribe(lobby_channel(game.id).pubsub)

        emit(PlayerJoinedEvent(game=game, player=player))

        envelope: dict | None = None
        for _ in range(10):
            msg = pubsub.get_message()
            if msg and msg['type'] == 'message':
                envelope = json.loads(msg['data'])
                break
        assert envelope is not None
        assert envelope.keys() == {'sequence', 'event', 'data'}
        assert envelope['sequence'] == 1
        assert envelope['event'] == LobbyEventType.player_joined
        assert envelope['data']['name'] == 'Alice'

    @pytest.mark.usefixtures('_patch_sync_redis')
    def test_invalid_event_type_rejected(
        self, session: Session, fake_sync_redis: fakeredis.FakeRedis
    ) -> None:
        """publish_sse validates event_type against a strict allowlist."""
        game = create_game(session)
        channel = lobby_channel(game.id)
        with pytest.raises(ValueError, match='invalid SSE event_type'):
            publish_sse(channel, 'bad event"; DROP TABLE', {}, required=True)


# ── Forwarding filter ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_forward_messages_filters_pre_snapshot_and_sets_id() -> None:
    """_forward_messages drops events with seq <= snap_seq and yields id: seq frames."""
    from hideandseek.broadcast.subscribe import _forward_messages  # noqa: PLC0415

    redis = fakeredis.FakeAsyncRedis()
    pubsub = redis.pubsub()
    channel = 'test-channel'
    await pubsub.subscribe(channel)

    # Three events, like those the Lua script would publish.
    for i in (1, 2, 3):
        envelope = {'sequence': i, 'event': 'test_event', 'data': {'n': i}}
        await redis.publish(channel, json.dumps(envelope))

    frames: list[dict] = []
    # snap_seq=2 — client already reflects events 1 and 2 in its snapshot.
    async for frame in _forward_messages(pubsub, snap_seq=2):
        frames.append(frame)
        if len(frames) >= 1:
            break

    assert len(frames) == 1
    assert frames[0]['event'] == 'test_event'
    assert frames[0]['id'] == '3'
    assert json.loads(frames[0]['data']) == {'n': 3}

    await pubsub.aclose()
    await redis.aclose()
