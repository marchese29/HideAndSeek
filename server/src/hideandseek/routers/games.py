"""Game lifecycle endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from shapely.geometry import Point

from hideandseek.broadcast import GameStartedEvent, PlayerUpdatedEvent, emit
from hideandseek.celery_app import app as celery_app
from hideandseek.conventions import resolve_base_question_delay_min, resolve_hiding_time_min
from hideandseek.db import session_dependency
from hideandseek.dependencies import (
    get_client_id,
    get_game,
    get_hider_in_game,
    get_player_in_game,
    get_seeker_in_game,
)
from hideandseek.logic.endgame import (
    compute_hiding_zone_for_station,
    effective_hiding_zone_radius_m,
    get_candidate_stations,
)
from hideandseek.logic.lobby import create_game_with_host, validate_color_available
from hideandseek.logic.lobby import join_game as lobby_join_game
from hideandseek.logic.lobby import remove_player as lobby_remove_player
from hideandseek.logic.station import validate_station_election
from hideandseek.models.game import Game, Player
from hideandseek.models.types import GameStatus, PlayerRole, PushEventType, StationElectionStatus
from hideandseek.queries.device_tokens import upsert_device_token
from hideandseek.queries.effective_map import get_effective_map_data
from hideandseek.queries.games import (
    find_game_by_join_code,
    get_player,
    set_hider_station,
    update_game_status,
)
from hideandseek.queries.location import create_location_update
from hideandseek.queries.maps import get_map
from hideandseek.queries.questions import get_inventory_slots
from hideandseek.queries.stops import get_stops_near_point, validate_stop_playable
from hideandseek.schemas.request import (
    CreateGameRequest,
    ElectStationRequest,
    JoinGameRequest,
    PlayerUpdate,
    RemovePlayerRequest,
)
from hideandseek.schemas.response import (
    EffectiveMapResponse,
    GameResponse,
    HiderStationResponse,
    HidingZoneResponse,
    InventoryResponse,
    JoinGameResponse,
    NearbyStationResponse,
    PlayerResponse,
    StopResponse,
)
from hideandseek.tasks.game_timers import transition_hiding_to_seeking
from hideandseek.tasks.push import send_push

router = APIRouter(prefix='/games', tags=['games'], dependencies=[Depends(session_dependency)])


@router.post('', response_model=JoinGameResponse, status_code=201)
def create_game(
    body: CreateGameRequest,
    client_id: uuid.UUID = Depends(get_client_id),
) -> JoinGameResponse:
    """Create a new game on a map. The host is automatically added as the first player."""
    game_map = get_map(body.map_id)
    if not game_map:
        raise HTTPException(status_code=404, detail='Map not found.')

    if body.device_token:
        upsert_device_token(
            client_id=client_id,
            token=body.device_token,
            environment=body.device_token_environment,
        )

    hiding_time = resolve_hiding_time_min(
        request_override=body.hiding_time_min,
        map_default=game_map.default_hiding_time_min,
        size=game_map.size,
    )
    question_delay = resolve_base_question_delay_min(
        request_override=body.base_question_delay_min,
        map_default=game_map.default_base_question_delay_min,
    )

    game, player = create_game_with_host(
        body,
        game_map=game_map,
        host_client_id=client_id,
        hiding_time_min=hiding_time,
        base_question_delay_min=question_delay,
    )
    return JoinGameResponse(game=GameResponse.from_model(game), player_id=player.id)


@router.post('/join', response_model=JoinGameResponse, status_code=201)
def join_game(
    body: JoinGameRequest,
    client_id: uuid.UUID = Depends(get_client_id),
) -> JoinGameResponse:
    """Join a game by its join code."""
    game = find_game_by_join_code(body.join_code)
    if not game:
        raise HTTPException(status_code=404, detail='Invalid join code.')
    if not game.status.is_lobby:
        raise HTTPException(status_code=409, detail='Game is not in lobby.')

    if body.device_token:
        upsert_device_token(
            client_id=client_id,
            token=body.device_token,
            environment=body.device_token_environment,
        )

    try:
        player = lobby_join_game(body, game, client_id=client_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return JoinGameResponse(
        game=GameResponse.from_model(game),
        player_id=player.id,
    )


@router.get('/{game_id}', response_model=GameResponse)
def get_game_state(
    game: Game = Depends(get_game),
) -> GameResponse:
    """Fetch current game state."""
    return GameResponse.from_model(game)


@router.get('/{game_id}/inventory', response_model=InventoryResponse)
def get_inventory(
    game: Game = Depends(get_game),
) -> InventoryResponse:
    """Current question inventory — all slots grouped by type."""
    slots = get_inventory_slots(game)
    return InventoryResponse.from_slots(slots)


@router.patch(
    '/{game_id}/players/{player_id}',
    response_model=PlayerResponse,
)
def patch_player(
    player_id: uuid.UUID,
    body: PlayerUpdate,
    game: Game = Depends(get_game),
    client_id: uuid.UUID = Depends(get_client_id),
) -> PlayerResponse:
    """Update a player's role, name, color, or device token."""
    player = get_player(player_id)
    if not player or player.game_id != game.id:
        raise HTTPException(status_code=404, detail='Player not found in this game.')
    if player.client_id != client_id:
        raise HTTPException(status_code=403, detail='You can only update your own player.')

    updates = body.model_dump(exclude_unset=True)
    if 'name' in updates:
        player.name = updates['name']
    if 'color' in updates:
        try:
            validate_color_available(game, player, updates['color'])
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        player.color = updates['color']
    if 'role' in updates:
        player.role = updates['role']
    if updates.get('device_token'):
        upsert_device_token(
            client_id=client_id,
            token=updates['device_token'],
            environment=body.device_token_environment,
        )
    if game.status.is_lobby:
        emit(PlayerUpdatedEvent(game=game, player=player))
    return PlayerResponse.from_model(player)


@router.delete('/{game_id}/players/{player_id}', status_code=204)
def remove_player(
    player_id: uuid.UUID,
    body: RemovePlayerRequest | None = None,
    game: Game = Depends(get_game),
    client_id: uuid.UUID = Depends(get_client_id),
) -> None:
    """Remove a player from the lobby. Self-leave or host-kick."""
    player = get_player(player_id)
    if not player or player.game_id != game.id:
        raise HTTPException(status_code=404, detail='Player not found in this game.')

    try:
        lobby_remove_player(
            game,
            player,
            client_id=client_id,
            new_host_id=body.new_host_id if body else None,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post('/{game_id}/start', response_model=GameResponse)
def start_game(
    game: Game = Depends(get_game),
    client_id: uuid.UUID = Depends(get_client_id),
) -> GameResponse:
    """Transition the game from lobby to hiding. Host-only."""
    if client_id != game.host_client_id:
        raise HTTPException(status_code=403, detail='Only the host can start the game.')
    if not game.status.is_lobby:
        raise HTTPException(status_code=409, detail='Game is not in lobby.')

    roles = [p.role for p in game.players]
    if not roles:
        raise HTTPException(status_code=409, detail='No players in game.')
    if any(r is None for r in roles):
        raise HTTPException(status_code=409, detail='Not all players have assigned roles.')
    if PlayerRole.hider not in roles:
        raise HTTPException(status_code=409, detail='At least one hider is required.')
    if PlayerRole.seeker not in roles:
        raise HTTPException(status_code=409, detail='At least one seeker is required.')

    game = update_game_status(game, GameStatus.hiding)

    # Schedule hiding→seeking transition
    hiding_minutes = game.hiding_time_min
    transition_hiding_to_seeking.apply_async(  # type: ignore[attr-defined]
        args=[str(game.id)],
        countdown=hiding_minutes * 60,
        task_id=f'hiding_timer:{game.id}',
    )

    emit(GameStartedEvent(game=game))

    return GameResponse.from_model(game)


@router.post('/{game_id}/end', response_model=GameResponse)
def end_game(
    game: Game = Depends(get_game),
) -> GameResponse:
    """Transition the game to finished."""
    if not game.status.is_active:
        raise HTTPException(
            status_code=409,
            detail=f'Cannot end game in {game.status} state.',
        )

    # Revoke pending hiding timer if it exists
    if not celery_app.conf.task_always_eager:
        celery_app.control.revoke(f'hiding_timer:{game.id}', terminate=False)

    game = update_game_status(game, GameStatus.finished)
    return GameResponse.from_model(game)


@router.get('/{game_id}/hider-station', response_model=HiderStationResponse)
def get_hider_station(
    game: Game = Depends(get_game),
    _player: Player = Depends(get_hider_in_game),
) -> HiderStationResponse:
    """The hider's station and election status. Available during hiding and seeking."""
    if not game.status.is_active:
        raise HTTPException(
            status_code=409, detail='Hider station is only available during hiding or seeking.'
        )
    return HiderStationResponse(
        hider_station_id=game.hider_station_id,
        station_election_status=game.station_election_status,
    )


@router.post('/{game_id}/hider-station', response_model=HidingZoneResponse)
def elect_hider_station(
    body: ElectStationRequest,
    game: Game = Depends(get_game),
    player: Player = Depends(get_hider_in_game),
) -> HidingZoneResponse:
    """Elect a station as the hider's hiding zone anchor. Permanent."""
    not_hiding = not game.status.is_hiding
    not_ambiguous = game.station_election_status != StationElectionStatus.ambiguous
    if not_hiding and not_ambiguous:
        raise HTTPException(
            status_code=409,
            detail='Station election is only allowed during hiding or when ambiguous.',
        )
    if game.hider_station_id is not None:
        raise HTTPException(status_code=409, detail='Station has already been elected.')

    # Store caller's location update
    coords = Point(body.location.coordinates[0], body.location.coordinates[1])
    create_location_update(
        player=player,
        game=game,
        coordinates=coords,
        timestamp=datetime.now(UTC),
    )

    try:
        stop = validate_station_election(game, body.station_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    set_hider_station(game, stop, StationElectionStatus.elected)
    zone = compute_hiding_zone_for_station(game, stop)

    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.station_elected,
        role_filter='hider',
        alert=f'Station locked in: {stop.name}',
    )

    return HidingZoneResponse.from_geometry(zone)


@router.get('/{game_id}/nearby-stations', response_model=list[NearbyStationResponse])
def get_nearby_stations(
    lat: float = Query(description='Latitude of the query point.'),
    lng: float = Query(description='Longitude of the query point.'),
    game: Game = Depends(get_game),
    _player: Player = Depends(get_player_in_game),
) -> list[NearbyStationResponse]:
    """Playable stops within hiding zone radius of a point, with hiding zone polygons."""
    radius_m = effective_hiding_zone_radius_m(game)
    location = Point(lng, lat)
    stops = get_stops_near_point(game, location, radius_m)

    return [
        NearbyStationResponse.from_stop_and_zone(
            s,
            compute_hiding_zone_for_station(game, s),
        )
        for s in stops
    ]


@router.get('/{game_id}/hiding-zone', response_model=HidingZoneResponse)
def get_hiding_zone(
    station_id: uuid.UUID = Query(description='Stop ID to compute the hiding zone for.'),
    game: Game = Depends(get_game),
    _player: Player = Depends(get_player_in_game),
) -> HidingZoneResponse:
    """Hiding zone polygon for a given station."""
    stop = validate_stop_playable(game, station_id)
    if not stop:
        raise HTTPException(status_code=404, detail='Station not found or not playable.')

    zone = compute_hiding_zone_for_station(game, stop)
    return HidingZoneResponse.from_geometry(zone)


@router.get('/{game_id}/map', response_model=EffectiveMapResponse)
def get_effective_map(
    game: Game = Depends(get_game),
) -> EffectiveMapResponse:
    """Effective map with transit data and exclusions applied."""
    data = get_effective_map_data(game)
    return EffectiveMapResponse.from_effective_map_data(data)


@router.get('/{game_id}/candidate-stations', response_model=list[StopResponse])
def list_candidate_stations(
    offset: int = Query(default=0, ge=0, description='Pagination offset.'),
    limit: int = Query(default=50, ge=1, le=200, description='Pagination limit.'),
    game: Game = Depends(get_game),
    _player: Player = Depends(get_seeker_in_game),
) -> list[StopResponse]:
    """Playable stops whose hiding zone circle is not fully covered by exclusion zones."""
    if not game.status.is_seeking:
        raise HTTPException(
            status_code=409, detail='Candidate stations are only available during seeking.'
        )

    stops = get_candidate_stations(game, offset, limit)
    return [StopResponse.from_model(s) for s in stops]
