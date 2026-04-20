"""Lobby orchestration — game creation, join, color assignment, player removal."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import structlog

from hideandseek_core.queries.games import add_player, delete_player, update_game_status
from hideandseek_core.queries.games import create_game as query_create_game
from hideandseek_core.queries.location import delete_player_locations
from hideandseek_models.game import Game, Player
from hideandseek_models.game_map import GameMap
from hideandseek_models.types import (
    MAX_PLAYERS,
    EndReason,
    GameStatus,
    MapSize,
    PlayerColor,
    PlayerRole,
)

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RemovalResult:
    """What happened when a player was removed."""

    removed_player_id: uuid.UUID
    game_dissolved: bool
    new_host_id: uuid.UUID | None  # set when host was transferred
    dissolution_reason: str | None = None  # e.g. "no_hiders_remaining"


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


def swap_color(game: Game, player: Player, color: PlayerColor) -> None:
    """Assign a new color to a player. Raises ValueError if taken by another player."""
    if player.color == color:
        return
    validate_color_available(game, player, color)
    old_color = player.color
    player.color = color
    logger.info(
        'color_swapped',
        game_id=str(game.id),
        player_id=str(player.id),
        old_color=old_color.value,
        new_color=color.value,
    )


def create_game_with_host(
    *,
    name: str,
    game_map: GameMap,
    secret_hash: str,
    hiding_time_min: int,
    base_question_delay_min: int,
    size: MapSize,
    excluded_stop_ids: list[uuid.UUID],
    excluded_route_ids: list[uuid.UUID],
) -> tuple[Game, Player]:
    """Create a game and its host player with an auto-assigned color.

    Pre-generates the host player's UUID so both the game and the player
    can be created with a consistent host_player_id in one pass.
    """
    host_player_id = uuid.uuid4()
    game = query_create_game(
        game_map=game_map,
        host_player_id=host_player_id,
        hiding_time_min=hiding_time_min,
        base_question_delay_min=base_question_delay_min,
        default_inventory=game_map.default_inventory,
        convention=game_map.convention,
        size=size,
        excluded_stop_ids=excluded_stop_ids,
        excluded_route_ids=excluded_route_ids,
    )
    color = assign_color(game)
    player = add_player(
        game,
        player_id=host_player_id,
        name=name,
        color=color,
        secret_hash=secret_hash,
    )
    logger.info(
        'game_created',
        game_id=str(game.id),
        map_id=str(game_map.id),
        size=size.value,
        host_player_id=str(host_player_id),
    )
    return game, player


def join_game(
    game: Game,
    *,
    name: str,
    role: PlayerRole | None = None,
    secret_hash: str,
) -> Player:
    """Join a game with an auto-assigned color. Enforces player cap."""
    if len(game.players) >= MAX_PLAYERS:
        msg = 'Game is full (12 players max).'
        raise ValueError(msg)
    color = assign_color(game)
    player = add_player(game, name=name, color=color, role=role, secret_hash=secret_hash)
    logger.info(
        'player_joined',
        game_id=str(game.id),
        player_id=str(player.id),
        color=color.value,
        role=role.value if role is not None else None,
    )
    return player


def remove_player(
    game: Game,
    player: Player,
    *,
    caller_player_id: uuid.UUID,
    new_host_id: uuid.UUID | None = None,
) -> RemovalResult:
    """Remove a player from a game (lobby or active play).

    Returns a RemovalResult describing what happened — the caller decides
    which events to emit.

    Raises:
        PermissionError: caller is neither the player nor the host (→ 403).
        ValueError: game finished/dissolved, new_host_id missing/invalid (→ 422).
    """
    if not (game.status.is_lobby or game.status.is_active):
        msg = 'Players can only leave during lobby or active play.'
        raise ValueError(msg)

    is_self = player.id == caller_player_id
    is_host = caller_player_id == game.host_player_id

    if not is_self and not is_host:
        msg = 'Only the player or the host can remove a player.'
        raise PermissionError(msg)

    target_is_host = player.id == game.host_player_id
    removed_player_id = player.id
    game_id_str = str(game.id)
    player_id_str = str(player.id)
    phase = game.status.value

    # Clean up location history for active games
    if game.status.is_active:
        delete_player_locations(player, game)

    # Sole player — dissolve regardless of phase
    if len(game.players) == 1:
        game.end_reason = EndReason.dissolved
        update_game_status(game, GameStatus.dissolved)
        delete_player(player)
        logger.info(
            'player_removed',
            game_id=game_id_str,
            player_id=player_id_str,
            reason='last_player',
            dissolved=True,
        )
        logger.info(
            'game_dissolved',
            game_id=game_id_str,
            reason='last_player',
            phase=phase,
        )
        return RemovalResult(
            removed_player_id=removed_player_id,
            game_dissolved=True,
            new_host_id=None,
            dissolution_reason='last_player',
        )

    # Team-empty check — last hider or last seeker leaving dissolves the game
    if game.status.is_active and player.role is not None:
        same_role_remaining = [
            p for p in game.players if p.role == player.role and p.id != player.id
        ]
        if not same_role_remaining:
            game.end_reason = EndReason.dissolved
            update_game_status(game, GameStatus.dissolved)
            delete_player(player)
            reason = f'no_{player.role.value}s_remaining'
            logger.info(
                'player_removed',
                game_id=game_id_str,
                player_id=player_id_str,
                reason=reason,
                dissolved=True,
            )
            logger.info(
                'game_dissolved',
                game_id=game_id_str,
                reason=reason,
                phase=phase,
            )
            return RemovalResult(
                removed_player_id=removed_player_id,
                game_dissolved=True,
                new_host_id=None,
                dissolution_reason=reason,
            )

    # Host leaving with others remaining — must transfer host
    if target_is_host:
        if new_host_id is None:
            msg = 'new_host_id is required when the host leaves and other players remain.'
            raise ValueError(msg)
        new_host = _find_player_in_game(game, new_host_id)
        if new_host is None or new_host.id == player.id:
            msg = 'new_host_id must be another player in this game.'
            raise ValueError(msg)
        old_host_id = game.host_player_id
        game.host_player_id = new_host.id
        delete_player(player)
        logger.info(
            'player_removed',
            game_id=game_id_str,
            player_id=player_id_str,
            reason='host_transfer',
            new_host_id=str(new_host.id),
        )
        logger.info(
            'host_transferred',
            game_id=game_id_str,
            old_host_id=str(old_host_id),
            new_host_id=str(new_host.id),
        )
        return RemovalResult(
            removed_player_id=removed_player_id,
            game_dissolved=False,
            new_host_id=new_host.id,
        )

    # Non-host removal (self-leave or host-kick)
    delete_player(player)
    logger.info(
        'player_removed',
        game_id=game_id_str,
        player_id=player_id_str,
        reason='self_leave' if is_self else 'host_kick',
    )
    return RemovalResult(
        removed_player_id=removed_player_id,
        game_dissolved=False,
        new_host_id=None,
    )


def _find_player_in_game(game: Game, player_id: uuid.UUID) -> Player | None:
    """Find a player in a game's loaded player list."""
    for p in game.players:
        if p.id == player_id:
            return p
    return None
