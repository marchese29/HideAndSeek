"""Lobby orchestration — game creation, join, color assignment."""

from __future__ import annotations

import uuid

from hideandseek.models.game import Game, Player
from hideandseek.models.game_map import GameMap
from hideandseek.models.types import MAX_PLAYERS, PlayerColor
from hideandseek.queries.games import add_player
from hideandseek.queries.games import create_game as query_create_game
from hideandseek.schemas.request import CreateGameRequest, JoinGameRequest


def assign_color(game: Game) -> PlayerColor:
    """Return the first unused PlayerColor for a game."""
    used = {p.color for p in game.players}
    for color in PlayerColor:
        if color not in used:
            return color
    msg = 'All colors are taken.'
    raise ValueError(msg)


def validate_color_available(game: Game, player: Player, color: PlayerColor) -> None:
    """Raise ValueError if color is taken by another player."""
    for p in game.players:
        if p.id != player.id and p.color == color:
            msg = f'Color {color} is already taken.'
            raise ValueError(msg)


def create_game_with_host(
    body: CreateGameRequest,
    *,
    game_map: GameMap,
    host_client_id: uuid.UUID,
    hiding_time_min: int,
    base_question_delay_min: int,
) -> tuple[Game, Player]:
    """Create a game and its host player with an auto-assigned color."""
    game = query_create_game(
        game_map=game_map,
        host_client_id=host_client_id,
        hiding_time_min=hiding_time_min,
        base_question_delay_min=base_question_delay_min,
        default_inventory=game_map.default_inventory,
        convention=game_map.convention,
        size=game_map.size,
        excluded_stop_ids=body.excluded_stop_ids,
        excluded_route_ids=body.excluded_route_ids,
    )
    color = assign_color(game)
    player = add_player(game, client_id=host_client_id, name=body.name, color=color)
    return game, player


def join_game(
    body: JoinGameRequest,
    game: Game,
    *,
    client_id: uuid.UUID,
) -> Player:
    """Join a game with an auto-assigned color. Enforces player cap."""
    if len(game.players) >= MAX_PLAYERS:
        msg = 'Game is full (12 players max).'
        raise ValueError(msg)
    color = assign_color(game)
    return add_player(game, client_id=client_id, name=body.name, color=color, role=body.role)
