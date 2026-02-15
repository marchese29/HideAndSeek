"""Game lifecycle endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from hideandseek.db import get_session
from hideandseek.dependencies import get_client_id, get_game, get_push_service
from hideandseek.models.game import Game
from hideandseek.models.types import GameStatus, PlayerRole, PushEventType
from hideandseek.push import PushService
from hideandseek.queries.device_tokens import get_device_tokens_for_game, upsert_device_token
from hideandseek.queries.effective_map import get_effective_map_data
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
    JoinGameResponse,
    PlayerResponse,
)

router = APIRouter(prefix='/games', tags=['games'], dependencies=[Depends(get_session)])

# States from which a game can be ended.
_ACTIVE_STATES = {GameStatus.hiding, GameStatus.seeking, GameStatus.endgame}


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
        inventory=game_map.default_inventory,
    )
    return GameResponse.from_model(game)


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
    return JoinGameResponse(game=GameResponse.from_model(game), player_id=player.id)


@router.get('/{game_id}', response_model=GameResponse)
def get_game_state(
    game: Game = Depends(get_game),
) -> GameResponse:
    """Fetch current game state."""
    return GameResponse.from_model(game)


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
    background_tasks: BackgroundTasks,
    game: Game = Depends(get_game),
    push: PushService = Depends(get_push_service),
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

    tokens = get_device_tokens_for_game(game.id)
    game = update_game_status(game, GameStatus.hiding)

    background_tasks.add_task(
        push.send_to_tokens,
        tokens,
        game.id,
        PushEventType.game_started,
        alert='Game on! The hiding phase has begun.',
    )

    return GameResponse.from_model(game)


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

    game = update_game_status(game, GameStatus.finished, clear_join_code=True)
    return GameResponse.from_model(game)


@router.get('/{game_id}/map', response_model=EffectiveMapResponse)
def get_effective_map(
    game: Game = Depends(get_game),
) -> EffectiveMapResponse:
    """Effective map with transit data and exclusions applied."""
    data = get_effective_map_data(game)
    return EffectiveMapResponse.from_effective_map_data(data)
