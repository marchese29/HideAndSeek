"""Database query functions. Return SQLModel objects — callers handle transformation."""

from __future__ import annotations

import random
import string
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, col, select

from hideandseek.models.game import Game, Player
from hideandseek.models.game_map import GameMap
from hideandseek.models.location import LocationUpdate
from hideandseek.models.question import Question
from hideandseek.models.transit import Route, RouteStop, Stop, TransitDataset
from hideandseek.models.types import GameStatus, PlayerRole, QuestionStatus, QuestionType

# ── Maps ──────────────────────────────────────────────────────────────────────


def list_maps(session: Session, *, offset: int = 0, limit: int = 100) -> list[tuple[GameMap, str]]:
    """Return maps with their region, paginated by offset/limit."""
    stmt = (
        select(GameMap, TransitDataset.region)
        .join(TransitDataset, GameMap.transit_dataset_id == TransitDataset.id)  # type: ignore[arg-type]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all())


def get_map(session: Session, map_id: uuid.UUID) -> GameMap | None:
    """Return a single map by ID, or None."""
    return session.get(GameMap, map_id)


# ── Games ─────────────────────────────────────────────────────────────────────


def generate_join_code(session: Session, *, length: int = 4, max_attempts: int = 10) -> str:
    """Generate a unique random alphanumeric join code."""
    for _ in range(max_attempts):
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        existing = session.exec(select(Game).where(Game.join_code == code)).first()
        if not existing:
            return code
    msg = f'Failed to generate unique join code after {max_attempts} attempts'
    raise RuntimeError(msg)


def create_game(
    session: Session,
    *,
    map_id: uuid.UUID,
    host_client_id: uuid.UUID,
    timing: dict,
    inventory: dict,
) -> Game:
    """Create a game with a generated join code, commit, and return it."""
    game = Game(
        map_id=map_id,
        host_client_id=host_client_id,
        join_code=generate_join_code(session),
        timing=timing,
        inventory=inventory,
    )
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


def find_game_by_join_code(session: Session, join_code: str) -> Game | None:
    """Find a game by its join code."""
    return session.exec(select(Game).where(Game.join_code == join_code.upper())).first()


def add_player(
    session: Session,
    *,
    client_id: uuid.UUID,
    game_id: uuid.UUID,
    name: str,
    color: str,
) -> Player:
    """Create a player in a game, commit, and return it."""
    player = Player(client_id=client_id, game_id=game_id, name=name, color=color)
    session.add(player)
    session.commit()
    session.refresh(player)
    return player


def get_player(session: Session, player_id: uuid.UUID) -> Player | None:
    """Return a single player by ID."""
    return session.get(Player, player_id)


def update_player(session: Session, player: Player, updates: dict) -> Player:
    """Apply partial updates to a player, commit, and return it."""
    for key, value in updates.items():
        setattr(player, key, value)
    session.add(player)
    session.commit()
    session.refresh(player)
    return player


def update_game_status(
    session: Session, game: Game, status: GameStatus, *, clear_join_code: bool = False
) -> Game:
    """Update a game's status (and optionally clear join_code), commit, and return it."""
    game.status = status
    if clear_join_code:
        game.join_code = None
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


# ── Effective map ─────────────────────────────────────────────────────────────


@dataclass
class RouteWithStops:
    """A route paired with its ordered stop IDs (after exclusion filtering)."""

    route: Route
    stop_ids: list[uuid.UUID]


@dataclass
class EffectiveMapData:
    """Resolved map + transit data with exclusions applied."""

    game_map: GameMap
    stops: list[Stop]
    routes: list[RouteWithStops]


def get_effective_map_data(session: Session, game: Game) -> EffectiveMapData:
    """Load map + transit data, filtering by exclusions."""
    game_map = session.get(GameMap, game.map_id)
    assert game_map is not None

    excluded_stop_set = set(str(sid) for sid in game_map.excluded_stop_ids)
    excluded_route_set = set(str(rid) for rid in game_map.excluded_route_ids)

    # Load stops, excluding excluded ones
    all_stops = list(
        session.exec(
            select(Stop).where(
                Stop.dataset_id == game_map.transit_dataset_id,
                ~col(Stop.id).in_(excluded_stop_set) if excluded_stop_set else True,  # type: ignore[arg-type]
            )
        ).all()
    )
    stop_id_set = {s.id for s in all_stops}

    # Load routes with their ordered stop IDs
    all_routes = session.exec(
        select(Route).where(
            Route.dataset_id == game_map.transit_dataset_id,
            ~col(Route.id).in_(excluded_route_set) if excluded_route_set else True,  # type: ignore[arg-type]
        )
    ).all()

    routes_with_stops: list[RouteWithStops] = []
    for route in all_routes:
        route_stops = session.exec(
            select(RouteStop).where(RouteStop.route_id == route.id).order_by(RouteStop.sequence)  # type: ignore[arg-type]
        ).all()
        stop_ids = [rs.stop_id for rs in route_stops if rs.stop_id in stop_id_set]
        routes_with_stops.append(RouteWithStops(route=route, stop_ids=stop_ids))

    return EffectiveMapData(game_map=game_map, stops=all_stops, routes=routes_with_stops)


# ── Location ─────────────────────────────────────────────────────────────────


def create_location_update(
    session: Session,
    *,
    player_id: uuid.UUID,
    game_id: uuid.UUID,
    coordinates: dict,
    timestamp: datetime,
) -> LocationUpdate:
    """Store a location update, commit, and return it."""
    lu = LocationUpdate(
        player_id=player_id,
        game_id=game_id,
        coordinates=coordinates,
        timestamp=timestamp,
    )
    session.add(lu)
    session.commit()
    session.refresh(lu)
    return lu


@dataclass
class VisiblePlayerData:
    """A player's latest location, ready for response transformation."""

    player: Player
    coordinates: dict
    timestamp: datetime


def get_visible_players(session: Session, game: Game, caller: Player) -> list[VisiblePlayerData]:
    """Return the latest location of each player visible to the caller.

    Both hiders and seekers see all seekers (except themselves).
    Hiders are never visible during active gameplay.
    """
    # Subquery: latest location update per player in this game
    latest_sq = (
        select(
            LocationUpdate.player_id,
            func.max(LocationUpdate.id).label('max_id'),
        )
        .where(LocationUpdate.game_id == game.id)
        .group_by(LocationUpdate.player_id)  # type: ignore[arg-type]
        .subquery()
    )

    stmt = (
        select(LocationUpdate, Player)
        .join(latest_sq, LocationUpdate.id == latest_sq.c.max_id)  # type: ignore[arg-type]
        .join(Player, LocationUpdate.player_id == Player.id)  # type: ignore[arg-type]
        .where(
            Player.role == PlayerRole.seeker,
            Player.id != caller.id,
        )
    )

    results: list[VisiblePlayerData] = []
    for lu, player in session.exec(stmt).all():
        results.append(
            VisiblePlayerData(
                player=player,
                coordinates=lu.coordinates,
                timestamp=lu.timestamp,
            )
        )
    return results


def get_location_history(session: Session, game_id: uuid.UUID) -> list[LocationUpdate]:
    """Return all location updates for a game, chronologically."""
    return list(
        session.exec(
            select(LocationUpdate)
            .where(LocationUpdate.game_id == game_id)
            .order_by(LocationUpdate.id)  # type: ignore[arg-type]
        ).all()
    )


# ── Questions ────────────────────────────────────────────────────────────────


def has_unanswered_question(session: Session, game_id: uuid.UUID) -> bool:
    """Return True if the game has any question not yet in 'answered' status."""
    return (
        session.exec(
            select(Question.id).where(
                Question.game_id == game_id,
                Question.status != QuestionStatus.answered,
            )
        ).first()
        is not None
    )


def get_question_count(session: Session, game_id: uuid.UUID) -> int:
    """Return the number of questions asked in a game (for sequencing)."""
    return len(session.exec(select(Question.id).where(Question.game_id == game_id)).all())


def create_question(
    session: Session,
    *,
    game_id: uuid.UUID,
    sequence: int,
    question_type: QuestionType,
    status: QuestionStatus,
    parameters: dict,
    asked_by: uuid.UUID,
    seeker_location_start: dict,
) -> Question:
    """Create a question, commit, and return it."""
    q = Question(
        game_id=game_id,
        sequence=sequence,
        question_type=question_type,
        status=status,
        parameters=parameters,
        asked_by=asked_by,
        seeker_location_start=seeker_location_start,
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return q


def get_question(session: Session, question_id: uuid.UUID) -> Question | None:
    """Return a single question by ID."""
    return session.get(Question, question_id)


def list_questions(session: Session, game_id: uuid.UUID) -> list[Question]:
    """Return all questions for a game, chronologically."""
    return list(
        session.exec(
            select(Question).where(Question.game_id == game_id).order_by(Question.sequence)  # type: ignore[arg-type]
        ).all()
    )


def update_question(session: Session, question: Question, updates: dict) -> Question:
    """Apply updates to a question, commit, and return it."""
    for key, value in updates.items():
        setattr(question, key, value)
    session.add(question)
    session.commit()
    session.refresh(question)
    return question


def update_game_inventory(session: Session, game: Game, inventory: dict) -> Game:
    """Update a game's inventory, commit, and return it."""
    game.inventory = inventory
    session.add(game)
    session.commit()
    session.refresh(game)
    return game


def get_latest_location_for_player(
    session: Session, player_id: uuid.UUID, game_id: uuid.UUID
) -> LocationUpdate | None:
    """Return the most recent location update for a player in a game."""
    return session.exec(
        select(LocationUpdate)
        .where(
            LocationUpdate.player_id == player_id,
            LocationUpdate.game_id == game_id,
        )
        .order_by(LocationUpdate.id.desc())  # type: ignore[union-attr]
        .limit(1)
    ).first()


def get_avg_seeker_location(session: Session, game: Game) -> dict | None:
    """Compute the average position of all seekers based on their latest reports.

    Returns a GeoJSON Point dict or None if no seeker locations exist.
    """
    seekers = [p for p in game.players if p.role == PlayerRole.seeker]
    if not seekers:
        return None

    lngs: list[float] = []
    lats: list[float] = []
    for seeker in seekers:
        lu = get_latest_location_for_player(session, seeker.id, game.id)
        if lu:
            coords = lu.coordinates.get('coordinates', [])
            if len(coords) >= 2:
                lngs.append(coords[0])
                lats.append(coords[1])

    if not lngs:
        return None

    return {
        'type': 'Point',
        'coordinates': [sum(lngs) / len(lngs), sum(lats) / len(lats)],
    }
