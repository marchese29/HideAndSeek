"""Tests for Celery game timer tasks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from shapely.geometry import Point
from sqlalchemy.orm import Session

from hideandseek.tasks.game_timers import auto_answer_question, transition_hiding_to_seeking
from hideandseek_models.game import Game
from hideandseek_models.game_map import GameMap
from hideandseek_models.location import LocationUpdate
from hideandseek_models.question import Question
from hideandseek_models.question_params import FeatureQuestionParams, RadarParams
from hideandseek_models.transit import Stop
from hideandseek_models.types import (
    FeatureCategory,
    GameStatus,
    PlayerRole,
    QuestionStatus,
    QuestionType,
    StationElectionStatus,
)
from tests.conftest import (
    create_game,
    create_game_map,
    create_game_map_feature,
    create_map_feature,
    create_player,
)


@pytest.fixture(autouse=True)
def _patch_engine(session: Session, monkeypatch: pytest.MonkeyPatch):
    """Point session_scope at the test session's engine."""
    monkeypatch.setattr('hideandseek_core.db.get_engine', lambda: session.get_bind())


# ── transition_hiding_to_seeking ─────────────────────────────────────────────


def test_transition_hiding_to_seeking(session: Session):
    """Without hider locations, transition sets ambiguous status."""
    game = create_game(session, status=GameStatus.hiding)
    transition_hiding_to_seeking(str(game.id))
    session.expire_all()
    session.refresh(game)
    assert game.status.is_seeking
    assert game.seeking_started_at is not None
    # No hider locations → ambiguous
    assert game.station_election_status == StationElectionStatus.ambiguous
    assert game.hider_station_id is None


def test_transition_preserves_early_election(session: Session):
    """If station was elected during hiding, transition leaves it alone."""
    game = create_game(
        session,
        status=GameStatus.hiding,
        station_election_status=StationElectionStatus.elected,
    )
    game_map = session.get(GameMap, game.map_id)
    assert game_map is not None
    stop = Stop(
        stable_id='early-elect',
        dataset_id=game_map.transit_dataset_id,
        name='Early Station',
        coordinates=Point(0.5, 0.5),
    )
    session.add(stop)
    session.commit()
    session.refresh(stop)
    game.hider_station_id = stop.id
    session.add(game)
    session.commit()

    transition_hiding_to_seeking(str(game.id))
    session.expire_all()
    session.refresh(game)
    assert game.status.is_seeking
    assert game.station_election_status == StationElectionStatus.elected
    assert game.hider_station_id == stop.id


def test_transition_idempotent_when_already_seeking(session: Session):
    game = create_game(session, status=GameStatus.seeking)
    transition_hiding_to_seeking(str(game.id))
    session.expire_all()
    session.refresh(game)
    assert game.status.is_seeking


def test_transition_noop_when_finished(session: Session):
    game = create_game(session, status=GameStatus.finished, join_code=None)
    transition_hiding_to_seeking(str(game.id))
    session.expire_all()
    session.refresh(game)
    assert game.status.is_finished


def test_transition_noop_for_missing_game(session: Session):
    transition_hiding_to_seeking(str(uuid.uuid4()))  # should not raise


# ── auto_answer_question ──────────────────────────────────────────────────────


def _create_answerable_question(session: Session) -> tuple[Game, Question]:
    """Create a seeking game with an answerable radar question and a hider with location."""
    game = create_game(session, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)

    # Add hider location
    lu = LocationUpdate(
        player_id=hider.id,
        game_id=game.id,
        coordinates=Point(0.0, 51.0),
        timestamp=datetime.now(UTC),
    )
    session.add(lu)
    session.commit()

    question = Question(
        game_id=game.id,
        sequence=1,
        question_type=QuestionType.radar,
        status=QuestionStatus.answerable,
        asked_by=seeker.id,
        seeker_location_start=Point(-0.1, 51.5),
        answerable_at=datetime.now(UTC),
    )
    session.add(question)
    session.flush()

    params = RadarParams(question_id=question.id, radius=3000)
    session.add(params)
    session.commit()
    session.refresh(question)
    return game, question


def test_auto_answer_question(session: Session):
    game, question = _create_answerable_question(session)
    auto_answer_question(str(question.id))
    session.expire_all()
    session.refresh(question)
    assert question.status == QuestionStatus.answered
    assert question.answered_at is not None
    assert question.answer == 'no'  # hider ~56 km from seeker, outside 3 km radar
    assert question.hider_location is not None


def test_auto_answer_idempotent_when_already_answered(session: Session):
    game, question = _create_answerable_question(session)
    # Answer it first
    auto_answer_question(str(question.id))
    # Run again — should be a no-op
    auto_answer_question(str(question.id))
    session.expire_all()
    session.refresh(question)
    assert question.status == QuestionStatus.answered


def test_auto_answer_noop_for_missing_question(session: Session):
    auto_answer_question(str(uuid.uuid4()))  # should not raise


def test_auto_answer_matching_question(session: Session):
    """Auto-answer resolves hider feature and compares to seeker's."""
    gm = create_game_map(session)
    hosp_a = create_map_feature(
        session,
        stable_id='hosp_a',
        name='Hospital A',
        shape=Point(-0.1, 51.5),
    )
    hosp_b = create_map_feature(
        session,
        stable_id='hosp_b',
        name='Hospital B',
        shape=Point(0.0, 51.0),
    )
    create_game_map_feature(session, gm.id, hosp_a.id)
    create_game_map_feature(session, gm.id, hosp_b.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)

    lu = LocationUpdate(
        player_id=hider.id,
        game_id=game.id,
        coordinates=Point(0.001, 51.001),
        timestamp=datetime.now(UTC),
    )
    session.add(lu)
    session.commit()

    question = Question(
        game_id=game.id,
        sequence=1,
        question_type=QuestionType.matching,
        status=QuestionStatus.answerable,
        asked_by=seeker.id,
        seeker_location_start=Point(-0.1, 51.5),
        answerable_at=datetime.now(UTC),
    )
    session.add(question)
    session.flush()

    fp = FeatureQuestionParams(
        question_id=question.id,
        category=FeatureCategory.hospital,
        source='map_data',
        seeker_feature_id='hosp_a',
        seeker_feature_name='Hospital A',
        seeker_distance=100.0,
    )
    session.add(fp)
    session.commit()
    session.refresh(question)

    auto_answer_question(str(question.id))
    session.expire_all()
    session.refresh(question)
    session.refresh(fp)
    assert question.status == QuestionStatus.answered
    assert question.answer == 'no'  # different hospitals
    assert fp.hider_feature_id == 'hosp_b'


def test_auto_answer_measuring_question(session: Session):
    """Auto-answer computes distance comparison."""
    gm = create_game_map(session)
    hosp = create_map_feature(
        session,
        stable_id='hosp_1',
        name='Hospital',
        shape=Point(-0.1, 51.5),
    )
    create_game_map_feature(session, gm.id, hosp.id)

    game = create_game(session, map_id=gm.id, status=GameStatus.seeking)
    hider = create_player(session, game.id, name='Hider', role=PlayerRole.hider)
    seeker = create_player(session, game.id, name='Seeker', role=PlayerRole.seeker)

    # Hider far from the hospital
    lu = LocationUpdate(
        player_id=hider.id,
        game_id=game.id,
        coordinates=Point(0.5, 52.0),
        timestamp=datetime.now(UTC),
    )
    session.add(lu)
    session.commit()

    question = Question(
        game_id=game.id,
        sequence=1,
        question_type=QuestionType.measuring,
        status=QuestionStatus.answerable,
        asked_by=seeker.id,
        seeker_location_start=Point(-0.1001, 51.5001),
        answerable_at=datetime.now(UTC),
    )
    session.add(question)
    session.flush()

    fp = FeatureQuestionParams(
        question_id=question.id,
        category=FeatureCategory.hospital,
        source='map_data',
        seeker_feature_id='hosp_1',
        seeker_feature_name='Hospital',
        seeker_distance=50.0,
    )
    session.add(fp)
    session.commit()
    session.refresh(question)

    auto_answer_question(str(question.id))
    session.expire_all()
    session.refresh(question)
    assert question.status == QuestionStatus.answered
    assert question.answer == 'closer'  # seeker 50m vs hider far away


# ── scheduled veto via auto_answer ────────────────────────────────────────────


def test_auto_answer_executes_scheduled_veto(session: Session):
    """When scheduled_veto is set, auto-answer vetoes instead of computing an answer."""
    game, question = _create_answerable_question(session)
    question.scheduled_veto = True
    session.add(question)
    session.commit()

    auto_answer_question(str(question.id))
    session.expire_all()
    session.refresh(question)
    assert question.status == QuestionStatus.vetoed
    assert question.answered_at is not None
    assert question.answer is None
    assert question.hider_location is None


def test_auto_answer_without_scheduled_veto_still_answers(session: Session):
    """Without the flag, auto-answer computes an answer as normal."""
    game, question = _create_answerable_question(session)
    assert question.scheduled_veto is False

    auto_answer_question(str(question.id))
    session.expire_all()
    session.refresh(question)
    assert question.status == QuestionStatus.answered
    assert question.answer is not None
