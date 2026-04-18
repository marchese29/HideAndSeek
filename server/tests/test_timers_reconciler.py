"""Tests for the reconciler's overdue-timer queries (core.logic.timers)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from shapely.geometry import Point
from sqlalchemy.orm import Session

from hideandseek_core.db import _session_var
from hideandseek_core.logic.timers import (
    find_overdue_answerable_questions,
    find_overdue_found_claims,
    find_overdue_hiding_games,
)
from hideandseek_models.question import Question
from hideandseek_models.question_params import RadarParams
from hideandseek_models.types import GameStatus, PlayerRole, QuestionStatus, QuestionType
from tests.conftest import create_game, create_player


@pytest.fixture(autouse=True)
def _set_session(session: Session):
    """Bind the test session to the ContextVar so query functions use it."""
    token = _session_var.set(session)
    try:
        yield
    finally:
        _session_var.reset(token)


# ── find_overdue_hiding_games ────────────────────────────────────────────────


def test_overdue_hiding_game_returned(session: Session):
    game = create_game(
        session,
        status=GameStatus.hiding,
        hiding_time_min=1,
        hiding_started_at=datetime.now(UTC) - timedelta(minutes=2),
    )
    session.commit()
    assert game.id in find_overdue_hiding_games()


def test_hiding_game_not_yet_due_skipped(session: Session):
    game = create_game(
        session,
        status=GameStatus.hiding,
        hiding_time_min=10,
        hiding_started_at=datetime.now(UTC),
    )
    session.commit()
    assert game.id not in find_overdue_hiding_games()


def test_finished_game_skipped(session: Session):
    """Early-ended game: reconciler naturally skips instead of needing revoke()."""
    game = create_game(
        session,
        status=GameStatus.finished,
        join_code=None,
        hiding_time_min=1,
        hiding_started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    session.commit()
    assert game.id not in find_overdue_hiding_games()


def test_seeking_game_skipped(session: Session):
    game = create_game(
        session,
        status=GameStatus.seeking,
        hiding_time_min=1,
        hiding_started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    session.commit()
    assert game.id not in find_overdue_hiding_games()


# ── find_overdue_answerable_questions ────────────────────────────────────────


def _make_answerable_question(
    session: Session, *, game_status: GameStatus, answerable_at: datetime
) -> Question:
    game = create_game(session, status=game_status, base_question_delay_min=1)
    seeker = create_player(session, game.id, name='S', role=PlayerRole.seeker)
    question = Question(
        game_id=game.id,
        sequence=1,
        question_type=QuestionType.radar,
        status=QuestionStatus.answerable,
        asked_by=seeker.id,
        seeker_location_start=Point(0.0, 0.0),
        answerable_at=answerable_at,
    )
    session.add(question)
    session.flush()
    session.add(RadarParams(question_id=question.id, radius=1000))
    session.commit()
    session.refresh(question)
    return question


def test_overdue_answerable_question_returned(session: Session):
    question = _make_answerable_question(
        session,
        game_status=GameStatus.seeking,
        answerable_at=datetime.now(UTC) - timedelta(minutes=2),
    )
    assert question.id in find_overdue_answerable_questions()


def test_answerable_question_not_yet_due_skipped(session: Session):
    question = _make_answerable_question(
        session,
        game_status=GameStatus.seeking,
        answerable_at=datetime.now(UTC),
    )
    assert question.id not in find_overdue_answerable_questions()


def test_answerable_question_in_finished_game_skipped(session: Session):
    """End-of-game naturally cancels the auto-answer without an explicit revoke."""
    question = _make_answerable_question(
        session,
        game_status=GameStatus.finished,
        answerable_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    assert question.id not in find_overdue_answerable_questions()


def test_already_answered_question_skipped(session: Session):
    question = _make_answerable_question(
        session,
        game_status=GameStatus.seeking,
        answerable_at=datetime.now(UTC) - timedelta(minutes=2),
    )
    question.status = QuestionStatus.answered
    session.commit()
    assert question.id not in find_overdue_answerable_questions()


# ── find_overdue_found_claims ────────────────────────────────────────────────


def test_overdue_found_claim_returned(session: Session):
    game = create_game(
        session,
        status=GameStatus.seeking,
        found_claim_at=datetime.now(UTC) - timedelta(seconds=121),
    )
    session.commit()
    assert game.id in find_overdue_found_claims()


def test_fresh_found_claim_skipped(session: Session):
    game = create_game(
        session,
        status=GameStatus.seeking,
        found_claim_at=datetime.now(UTC),
    )
    session.commit()
    assert game.id not in find_overdue_found_claims()


def test_no_found_claim_skipped(session: Session):
    game = create_game(session, status=GameStatus.seeking, found_claim_at=None)
    session.commit()
    assert game.id not in find_overdue_found_claims()


def test_found_claim_on_finished_game_skipped(session: Session):
    """Hider confirm/reject clears found_claim_at, but even if it didn't, status gate skips."""
    game = create_game(
        session,
        status=GameStatus.finished,
        join_code=None,
        found_claim_at=datetime.now(UTC) - timedelta(seconds=300),
    )
    session.commit()
    assert game.id not in find_overdue_found_claims()
