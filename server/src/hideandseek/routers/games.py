"""Game lifecycle endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from hideandseek.celery_app import app as celery_app
from hideandseek.db import get_session
from hideandseek.dependencies import get_client_id, get_game, get_hider_in_game, get_seeker_in_game
from hideandseek.logic import get_candidate_stations
from hideandseek.models.game import Game, Player
from hideandseek.models.types import GameStatus, PlayerRole, PushEventType
from hideandseek.queries.device_tokens import upsert_device_token
from hideandseek.queries.effective_map import get_effective_map_data
from hideandseek.queries.features import get_map_feature_categories
from hideandseek.queries.games import (
    add_player,
    find_game_by_join_code,
    get_player,
    update_game_status,
)
from hideandseek.queries.games import (
    create_game as query_create_game,
)
from hideandseek.queries.games import (
    update_player as query_update_player,
)
from hideandseek.queries.maps import get_map
from hideandseek.schemas.request import CreateGameRequest, JoinGameRequest, PlayerUpdate
from hideandseek.schemas.response import (
    EffectiveMapResponse,
    GameResponse,
    HiderStationResponse,
    JoinGameResponse,
    PlayerResponse,
    StopResponse,
)
from hideandseek.tasks.game_timers import transition_hiding_to_seeking
from hideandseek.tasks.push import send_push

router = APIRouter(prefix='/games', tags=['games'], dependencies=[Depends(get_session)])

# States from which a game can be ended.
_ACTIVE_STATES = {GameStatus.hiding, GameStatus.seeking}


def _game_categories(game: Game) -> list[str]:
    """Distinct category names available on a game's map."""
    cats = get_map_feature_categories(game_map_id=game.map_id)
    return sorted({str(c) for c, _ in cats})


@router.post('', response_model=GameResponse, status_code=201)
def create_game(
    body: CreateGameRequest,
    client_id: uuid.UUID = Depends(get_client_id),
) -> GameResponse:
    """Create a new game on a map."""
    game_map = get_map(body.map_id)
    if not game_map:
        raise HTTPException(status_code=404, detail='Map not found.')

    if body.device_token:
        upsert_device_token(
            client_id=client_id,
            token=body.device_token,
            environment=body.device_token_environment,
        )

    game = query_create_game(
        map_id=game_map.id,
        host_client_id=client_id,
        timing={},  # TODO: copy from map default_timing when the field exists
        default_inventory=game_map.default_inventory,
        convention=game_map.convention,
        size=game_map.size,
        excluded_stop_ids=body.excluded_stop_ids,
        excluded_route_ids=body.excluded_route_ids,
    )
    return GameResponse.from_model(game, categories=_game_categories(game))


@router.post('/join', response_model=JoinGameResponse, status_code=201)
def join_game(
    body: JoinGameRequest,
    client_id: uuid.UUID = Depends(get_client_id),
) -> JoinGameResponse:
    """Join a game by its join code."""
    game = find_game_by_join_code(body.join_code)
    if not game:
        raise HTTPException(status_code=404, detail='Invalid join code.')
    if game.status != GameStatus.lobby:
        raise HTTPException(status_code=409, detail='Game is not in lobby.')

    upsert_device_token(
        client_id=client_id,
        token=body.device_token,
        environment=body.device_token_environment,
    )

    player = add_player(
        game,
        client_id=client_id,
        name=body.name,
        color=body.color,
    )
    return JoinGameResponse(
        game=GameResponse.from_model(game, categories=_game_categories(game)),
        player_id=player.id,
    )


@router.get('/{game_id}', response_model=GameResponse)
def get_game_state(
    game: Game = Depends(get_game),
) -> GameResponse:
    """Fetch current game state."""
    return GameResponse.from_model(game, categories=_game_categories(game))


@router.patch(
    '/{game_id}/players/{player_id}',
    response_model=PlayerResponse,
)
def patch_player(
    player_id: uuid.UUID,
    body: PlayerUpdate,
    game: Game = Depends(get_game),
) -> PlayerResponse:
    """Update a player's role, name, or color."""
    player = get_player(player_id)
    if not player or player.game_id != game.id:
        raise HTTPException(status_code=404, detail='Player not found in this game.')

    player = query_update_player(player, body.model_dump(exclude_unset=True))
    return PlayerResponse.from_model(player)


@router.post('/{game_id}/start', response_model=GameResponse)
def start_game(
    game: Game = Depends(get_game),
) -> GameResponse:
    """Transition the game from lobby to hiding."""
    if game.status != GameStatus.lobby:
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
    hiding_minutes = game.timing.get('hiding_time_min', 30)
    transition_hiding_to_seeking.apply_async(  # type: ignore[attr-defined]
        args=[str(game.id)],
        countdown=hiding_minutes * 60,
        task_id=f'hiding_timer:{game.id}',
    )

    # Push: game started
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.game_started,
        alert='Game on! The hiding phase has begun.',
    )

    return GameResponse.from_model(game, categories=_game_categories(game))


@router.post('/{game_id}/end', response_model=GameResponse)
def end_game(
    game: Game = Depends(get_game),
) -> GameResponse:
    """Transition the game to finished."""
    if game.status not in _ACTIVE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f'Cannot end game in {game.status} state.',
        )

    # Revoke pending hiding timer if it exists
    if not celery_app.conf.task_always_eager:
        celery_app.control.revoke(f'hiding_timer:{game.id}', terminate=False)

    game = update_game_status(game, GameStatus.finished, clear_join_code=True)
    return GameResponse.from_model(game, categories=_game_categories(game))


@router.get('/{game_id}/hider-station', response_model=HiderStationResponse)
def get_hider_station(
    game: Game = Depends(get_game),
    _player: Player = Depends(get_hider_in_game),
) -> HiderStationResponse:
    """The hider's assigned station during seeking."""
    if game.status != GameStatus.seeking:
        raise HTTPException(
            status_code=409, detail='Hider station is only available during seeking.'
        )
    if game.hider_station_id is None:
        raise HTTPException(status_code=404, detail='Hider station not yet assigned.')
    return HiderStationResponse(hider_station_id=game.hider_station_id)


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
    if game.status != GameStatus.seeking:
        raise HTTPException(
            status_code=409, detail='Candidate stations are only available during seeking.'
        )

    stops = get_candidate_stations(game, offset, limit)
    return [StopResponse.from_model(s) for s in stops]
