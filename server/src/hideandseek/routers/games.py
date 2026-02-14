"""Game lifecycle endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from hideandseek.db import get_session
from hideandseek.dependencies import get_client_id, get_game
from hideandseek.models.game import Game
from hideandseek.models.types import GameStatus, PlayerRole
from hideandseek.queries import (
    add_player,
    find_game_by_join_code,
    get_effective_map_data,
    get_map,
    get_player,
    update_game_status,
)
from hideandseek.queries import (
    create_game as query_create_game,
)
from hideandseek.queries import (
    update_player as query_update_player,
)
from hideandseek.schemas.request import CreateGameRequest, JoinGameRequest, PlayerUpdate
from hideandseek.schemas.response import (
    EffectiveMapResponse,
    GameResponse,
    JoinGameResponse,
    PlayerResponse,
)

router = APIRouter(prefix='/games', tags=['games'])

# States from which a game can be ended.
_ACTIVE_STATES = {GameStatus.hiding, GameStatus.seeking, GameStatus.endgame}


@router.post('', response_model=GameResponse, status_code=201)
def create_game(
    body: CreateGameRequest,
    client_id: uuid.UUID = Depends(get_client_id),
    session: Session = Depends(get_session),
) -> GameResponse:
    """Create a new game on a map."""
    game_map = get_map(session, body.map_id)
    if not game_map:
        raise HTTPException(status_code=404, detail='Map not found.')

    game = query_create_game(
        session,
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
    session: Session = Depends(get_session),
) -> JoinGameResponse:
    """Join a game by its join code."""
    game = find_game_by_join_code(session, body.join_code)
    if not game:
        raise HTTPException(status_code=404, detail='Invalid join code.')
    if game.status != GameStatus.lobby:
        raise HTTPException(status_code=409, detail='Game is not in lobby.')

    player = add_player(
        session,
        client_id=client_id,
        game_id=game.id,
        name=body.name,
        color=body.color,
    )
    session.refresh(game)
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
    session: Session = Depends(get_session),
) -> PlayerResponse:
    """Update a player's role, name, or color."""
    player = get_player(session, player_id)
    if not player or player.game_id != game.id:
        raise HTTPException(status_code=404, detail='Player not found in this game.')

    player = query_update_player(session, player, body.model_dump(exclude_unset=True))
    return PlayerResponse.from_model(player)


@router.post('/{game_id}/start', response_model=GameResponse)
def start_game(
    game: Game = Depends(get_game),
    session: Session = Depends(get_session),
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

    game = update_game_status(session, game, GameStatus.hiding)
    return GameResponse.from_model(game)


@router.post('/{game_id}/end', response_model=GameResponse)
def end_game(
    game: Game = Depends(get_game),
    session: Session = Depends(get_session),
) -> GameResponse:
    """Transition the game to finished."""
    if game.status not in _ACTIVE_STATES:
        raise HTTPException(
            status_code=409,
            detail=f'Cannot end game in {game.status} state.',
        )

    game = update_game_status(session, game, GameStatus.finished, clear_join_code=True)
    return GameResponse.from_model(game)


@router.get('/{game_id}/map', response_model=EffectiveMapResponse)
def get_effective_map(
    game: Game = Depends(get_game),
    session: Session = Depends(get_session),
) -> EffectiveMapResponse:
    """Effective map with transit data and exclusions applied."""
    data = get_effective_map_data(session, game)
    return EffectiveMapResponse.from_effective_map_data(data)
