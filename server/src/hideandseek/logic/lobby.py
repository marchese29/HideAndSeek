"""Lobby orchestration — game creation, join, color assignment, player removal."""

from __future__ import annotations

import uuid

from hideandseek.broadcast import HostChangedEvent, PlayerJoinedEvent, PlayerLeftEvent, emit
from hideandseek.models.game import Game, Player
from hideandseek.models.game_map import GameMap
from hideandseek.models.types import MAX_PLAYERS, GameStatus, PlayerColor
from hideandseek.queries.games import add_player, delete_player, update_game_status
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
    player = add_player(game, client_id=client_id, name=body.name, color=color, role=body.role)
    emit(PlayerJoinedEvent(game=game, player=player))
    return player


def remove_player(
    game: Game,
    player: Player,
    *,
    client_id: uuid.UUID,
    new_host_id: uuid.UUID | None = None,
) -> None:
    """Remove a player from a lobby game.

    All validation is here — routers catch and remap to HTTP codes.
    Raises:
        PermissionError: caller is neither the player nor the host (→ 403).
        ValueError: game not in lobby, new_host_id missing/invalid (→ 422).
    """
    if not game.status.is_lobby:
        msg = 'Players can only be removed during lobby.'
        raise ValueError(msg)

    is_self = player.client_id == client_id
    is_host = client_id == game.host_client_id

    if not is_self and not is_host:
        msg = 'Only the player or the host can remove a player.'
        raise PermissionError(msg)

    target_is_host = player.client_id == game.host_client_id
    removed_player_id = player.id

    if target_is_host:
        # Host is leaving
        if len(game.players) == 1:
            # Only player — dissolve game
            update_game_status(game, GameStatus.dissolved)
            delete_player(player)
            return

        # Others remain — must transfer host
        if new_host_id is None:
            msg = 'new_host_id is required when the host leaves and other players remain.'
            raise ValueError(msg)
        new_host = _find_player_in_game(game, new_host_id)
        if new_host is None or new_host.id == player.id:
            msg = 'new_host_id must be another player in this game.'
            raise ValueError(msg)
        game.host_client_id = new_host.client_id
        delete_player(player)
        emit(PlayerLeftEvent(game=game, player_id=removed_player_id))
        emit(HostChangedEvent(game=game, new_host_player_id=new_host.id))
        return

    # Non-host removal (self-leave or host-kick)
    delete_player(player)
    emit(PlayerLeftEvent(game=game, player_id=removed_player_id))


def _find_player_in_game(game: Game, player_id: uuid.UUID) -> Player | None:
    """Find a player in a game's loaded player list."""
    for p in game.players:
        if p.id == player_id:
            return p
    return None
