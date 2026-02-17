"""Tests for Celery game timer tasks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlmodel import Session

from hideandseek.models.game import Game
from hideandseek.models.location import LocationUpdate
from hideandseek.models.question import Question
from hideandseek.models.types import GameStatus, PlayerRole, QuestionStatus, QuestionType
from hideandseek.tasks.game_timers import auto_answer_question, transition_hiding_to_seeking
from tests.conftest import create_game, create_player


@pytest.fixture(autouse=True)
def _patch_engine(session: Session, monkeypatch: pytest.MonkeyPatch):
    """Point task functions at the test session's engine."""
    monkeypatch.setattr('hideandseek.tasks.game_timers.engine', session.get_bind())
    monkeypatch.setattr('hideandseek.tasks.push.engine', session.get_bind())


# ── transition_hiding_to_seeking ─────────────────────────────────────────────


def test_transition_hiding_to_seeking(session: Session):
    game = create_game(session, status=GameStatus.hiding)
    transition_hiding_to_seeking(str(game.id))
    session.expire_all()
    session.refresh(game)
    assert game.status == GameStatus.seeking
    assert game.seeking_started_at is not None


def test_transition_idempotent_when_already_seeking(session: Session):
    game = create_game(session, status=GameStatus.seeking)
    transition_hiding_to_seeking(str(game.id))
    session.expire_all()
    session.refresh(game)
    assert game.status == GameStatus.seeking


def test_transition_noop_when_finished(session: Session):
    game = create_game(session, status=GameStatus.finished, join_code=None)
    transition_hiding_to_seeking(str(game.id))
    session.expire_all()
    session.refresh(game)
    assert game.status == GameStatus.finished


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
        coordinates={'type': 'Point', 'coordinates': [0.0, 51.0]},
        timestamp=datetime.now(UTC),
    )
    session.add(lu)
    session.commit()

    question = Question(
        game_id=game.id,
        sequence=1,
        question_type=QuestionType.radar,
        status=QuestionStatus.answerable,
        parameters={'radius_m': 3000},
        asked_by=seeker.id,
        seeker_location_start={'type': 'Point', 'coordinates': [-0.1, 51.5]},
        answerable_at=datetime.now(UTC),
    )
    session.add(question)
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
