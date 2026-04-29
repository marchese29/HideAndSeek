"""Tests for the game-timer pause primitive (core.logic.pause).

Covers ref-counted pause/resume semantics, deadline shift correctness on full
resume, and the "shifted deadline >= now()" invariant from the design doc.
The reconciler-skip side (paused_at IS NULL filter) lives in
test_timers_reconciler.py.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from shapely.geometry import Point
from sqlalchemy.orm import Session

from hideandseek_core.broadcast.events import GameTimerPausedEvent, GameTimerResumedEvent
from hideandseek_core.db import _session_var
from hideandseek_core.logic.pause import pause_game, resume_game
from hideandseek_models.game import Game
from hideandseek_models.question import Question
from hideandseek_models.question_params import RadarParams
from hideandseek_models.types import (
    GameStatus,
    PauseReason,
    PlayerRole,
    QuestionStatus,
    QuestionType,
)
from tests.conftest import create_game, create_player

# These tests fail until HideAndSeek-7ep migrates datetime columns to timestamptz.
# Today the columns are TIMESTAMP WITHOUT TIME ZONE, so DB-loaded datetimes are naive
# and `now(UTC) - paused_at` raises TypeError. Un-skip when 7ep ships.
TIMESTAMPTZ_SKIP = pytest.mark.skip(reason='blocked on HideAndSeek-7ep (timestamptz migration)')


@pytest.fixture(autouse=True)
def _set_session(session: Session):
    token = _session_var.set(session)
    try:
        yield
    finally:
        _session_var.reset(token)


@pytest.fixture
def captured_events(monkeypatch: pytest.MonkeyPatch) -> list:
    events: list = []
    monkeypatch.setattr(
        'hideandseek_core.logic.pause.emit_gameplay',
        lambda event: events.append(event),
    )
    return events


def _seeking_game(session: Session, **overrides: object) -> Game:
    """Build a seeking-phase game suitable for pause tests."""
    defaults: dict[str, object] = {
        'status': GameStatus.seeking,
        'hiding_time_min': 60,
        'hiding_started_at': datetime.now(UTC) - timedelta(minutes=70),
        'hiding_ends_at': datetime.now(UTC) - timedelta(minutes=10),
        'seeking_started_at': datetime.now(UTC) - timedelta(minutes=10),
    }
    defaults.update(overrides)
    game = create_game(session, **defaults)
    session.flush()
    return game


def _add_answerable_question(
    session: Session,
    game: Game,
    *,
    deadline_at: datetime,
    status: QuestionStatus = QuestionStatus.answerable,
) -> Question:
    seeker = create_player(session, game.id, name='S', role=PlayerRole.seeker)
    q = Question(
        game_id=game.id,
        sequence=1,
        question_type=QuestionType.radar,
        status=status,
        asked_by=seeker.id,
        seeker_location_start=Point(0.0, 0.0),
        answerable_at=deadline_at - timedelta(minutes=1),
        deadline_at=deadline_at,
    )
    session.add(q)
    session.flush()
    session.add(RadarParams(question_id=q.id, radius=1000))
    session.flush()
    session.refresh(q)
    return q


# ── pause_game — set semantics + event ───────────────────────────────────────


def test_pause_from_unpaused_stamps_paused_at_and_emits_event(
    session: Session, captured_events: list
):
    game = _seeking_game(session)
    before = datetime.now(UTC)
    pause_game(game, PauseReason.host)
    after = datetime.now(UTC)

    assert game.active_pause_reasons == [PauseReason.host]
    assert game.paused_at is not None
    assert before <= game.paused_at <= after
    assert len(captured_events) == 1
    event = captured_events[0]
    assert isinstance(event, GameTimerPausedEvent)
    assert event.paused_at == game.paused_at
    assert event.active_pause_reasons == [PauseReason.host]


def test_pause_idempotent_on_repeat_reason(session: Session, captured_events: list):
    game = _seeking_game(session)
    pause_game(game, PauseReason.host)
    paused_at_first = game.paused_at
    pause_game(game, PauseReason.host)

    assert game.active_pause_reasons == [PauseReason.host]
    assert game.paused_at == paused_at_first
    assert len(captured_events) == 1


def test_pause_adds_second_reason_keeps_paused_at(session: Session, captured_events: list):
    game = _seeking_game(session)
    pause_game(game, PauseReason.host)
    original_paused_at = game.paused_at
    pause_game(game, PauseReason.photo_question_open)

    assert game.paused_at == original_paused_at
    assert game.active_pause_reasons == [PauseReason.host, PauseReason.photo_question_open]
    assert len(captured_events) == 2
    second = captured_events[1]
    assert isinstance(second, GameTimerPausedEvent)
    assert second.paused_at == original_paused_at
    assert second.active_pause_reasons == [
        PauseReason.host,
        PauseReason.photo_question_open,
    ]


# ── resume_game — set semantics + event ──────────────────────────────────────


def test_resume_unknown_reason_is_noop(session: Session, captured_events: list):
    game = _seeking_game(session)
    pause_game(game, PauseReason.host)
    captured_events.clear()
    snapshot_paused_at = game.paused_at
    snapshot_reasons = list(game.active_pause_reasons)

    resume_game(game, PauseReason.rest_period)

    assert game.paused_at == snapshot_paused_at
    assert list(game.active_pause_reasons) == snapshot_reasons
    assert captured_events == []


@TIMESTAMPTZ_SKIP
def test_resume_one_of_two_reasons_keeps_paused(session: Session, captured_events: list):
    deadline = datetime.now(UTC) + timedelta(minutes=5)
    game = _seeking_game(session, hiding_ends_at=deadline)
    pause_game(game, PauseReason.host)
    pause_game(game, PauseReason.photo_question_open)
    original_paused_at = game.paused_at
    captured_events.clear()

    resume_game(game, PauseReason.host)

    assert game.active_pause_reasons == [PauseReason.photo_question_open]
    assert game.paused_at == original_paused_at
    assert game.hiding_ends_at == deadline  # NOT shifted
    assert len(captured_events) == 1
    assert isinstance(captured_events[0], GameTimerPausedEvent)
    assert captured_events[0].active_pause_reasons == [PauseReason.photo_question_open]


def test_resume_last_reason_clears_paused_at_and_emits_resumed(
    session: Session, captured_events: list
):
    game = _seeking_game(session)
    pause_game(game, PauseReason.host)
    captured_events.clear()

    resume_game(game, PauseReason.host)

    assert game.paused_at is None
    assert game.active_pause_reasons == []
    assert len(captured_events) == 1
    assert isinstance(captured_events[0], GameTimerResumedEvent)


# ── Deadline shift correctness on full resume ────────────────────────────────


def _assert_close(actual: datetime | None, expected: datetime, *, tol_sec: float = 2.0) -> None:
    assert actual is not None
    assert abs((actual - expected).total_seconds()) <= tol_sec, (actual, expected)


@TIMESTAMPTZ_SKIP
def test_resume_shifts_hiding_ends_at(session: Session, captured_events: list):
    original_deadline = datetime.now(UTC) + timedelta(minutes=10)
    game = _seeking_game(session, hiding_ends_at=original_deadline)
    pause_at = datetime.now(UTC) - timedelta(minutes=3)
    game.paused_at = pause_at
    game.active_pause_reasons = [PauseReason.host]
    session.flush()

    before_resume = datetime.now(UTC)
    resume_game(game, PauseReason.host)
    delta = datetime.now(UTC) - pause_at

    _assert_close(game.hiding_ends_at, original_deadline + delta)
    # Sanity vs measured-now bounds
    expected_lo = original_deadline + (before_resume - pause_at)
    assert game.hiding_ends_at is not None
    assert game.hiding_ends_at >= expected_lo - timedelta(seconds=1)


def test_resume_leaves_null_hiding_ends_at_alone(session: Session, captured_events: list):
    game = _seeking_game(session, hiding_ends_at=None)
    game.paused_at = datetime.now(UTC) - timedelta(minutes=2)
    game.active_pause_reasons = [PauseReason.host]
    session.flush()

    resume_game(game, PauseReason.host)

    assert game.hiding_ends_at is None


@TIMESTAMPTZ_SKIP
def test_resume_shifts_found_claim_expires_at(session: Session, captured_events: list):
    found_at = datetime.now(UTC) - timedelta(seconds=30)
    expires_at = found_at + timedelta(seconds=120)
    game = _seeking_game(
        session,
        found_claim_at=found_at,
        found_claim_expires_at=expires_at,
    )
    pause_at = datetime.now(UTC) - timedelta(minutes=2)
    game.paused_at = pause_at
    game.active_pause_reasons = [PauseReason.host]
    session.flush()

    resume_game(game, PauseReason.host)
    delta = datetime.now(UTC) - pause_at

    _assert_close(game.found_claim_expires_at, expires_at + delta)


@TIMESTAMPTZ_SKIP
def test_resume_shifts_open_question_deadline_at(session: Session, captured_events: list):
    game = _seeking_game(session)
    original_deadline = datetime.now(UTC) + timedelta(minutes=5)
    q = _add_answerable_question(session, game, deadline_at=original_deadline)

    pause_at = datetime.now(UTC) - timedelta(minutes=2)
    game.paused_at = pause_at
    game.active_pause_reasons = [PauseReason.host]
    session.flush()

    resume_game(game, PauseReason.host)
    delta = datetime.now(UTC) - pause_at

    session.refresh(q)
    _assert_close(q.deadline_at, original_deadline + delta)

    resumed = next(e for e in captured_events if isinstance(e, GameTimerResumedEvent))
    assert q.id in resumed.question_deadlines
    _assert_close(resumed.question_deadlines[q.id], original_deadline + delta)


@TIMESTAMPTZ_SKIP
def test_resume_does_not_shift_terminal_question_deadline_at(
    session: Session, captured_events: list
):
    game = _seeking_game(session)
    original_deadline = datetime.now(UTC) + timedelta(minutes=5)
    q = _add_answerable_question(
        session, game, deadline_at=original_deadline, status=QuestionStatus.answered
    )

    pause_at = datetime.now(UTC) - timedelta(minutes=2)
    game.paused_at = pause_at
    game.active_pause_reasons = [PauseReason.host]
    session.flush()

    resume_game(game, PauseReason.host)

    session.refresh(q)
    assert q.deadline_at == original_deadline
    resumed = next(e for e in captured_events if isinstance(e, GameTimerResumedEvent))
    assert q.id not in resumed.question_deadlines


def test_resume_increments_seeking_pause_accumulated_sec(session: Session, captured_events: list):
    game = _seeking_game(session)
    assert game.seeking_pause_accumulated_sec == 0

    # First pause/resume: ~120s
    pause_at = datetime.now(UTC) - timedelta(seconds=120)
    game.paused_at = pause_at
    game.active_pause_reasons = [PauseReason.host]
    session.flush()
    resume_game(game, PauseReason.host)

    first_total = game.seeking_pause_accumulated_sec
    assert 118 <= first_total <= 125

    # Second pause/resume: ~60s — adds onto previous
    pause_at_2 = datetime.now(UTC) - timedelta(seconds=60)
    game.paused_at = pause_at_2
    game.active_pause_reasons = [PauseReason.host]
    session.flush()
    resume_game(game, PauseReason.host)

    assert game.seeking_pause_accumulated_sec >= first_total + 58
    assert game.seeking_pause_accumulated_sec <= first_total + 65


# ── Multi-reason ref-count accounting ────────────────────────────────────────


@TIMESTAMPTZ_SKIP
def test_double_acquire_same_reason_no_double_shift_on_release(
    session: Session, captured_events: list
):
    original_deadline = datetime.now(UTC) + timedelta(minutes=10)
    game = _seeking_game(session, hiding_ends_at=original_deadline)

    pause_game(game, PauseReason.host)
    pause_game(game, PauseReason.host)  # idempotent — no double-add
    pause_at = game.paused_at
    assert pause_at is not None

    resume_game(game, PauseReason.host)

    assert game.active_pause_reasons == []
    assert game.paused_at is None
    delta = datetime.now(UTC) - pause_at
    _assert_close(game.hiding_ends_at, original_deadline + delta)


@TIMESTAMPTZ_SKIP
def test_two_reasons_one_release_keeps_paused_at_set(session: Session, captured_events: list):
    original_deadline = datetime.now(UTC) + timedelta(minutes=10)
    game = _seeking_game(session, hiding_ends_at=original_deadline)

    pause_game(game, PauseReason.host)
    original_paused_at = game.paused_at
    assert original_paused_at is not None

    pause_game(game, PauseReason.photo_question_open)
    resume_game(game, PauseReason.host)

    assert game.paused_at == original_paused_at  # still anchored at first pause
    assert game.active_pause_reasons == [PauseReason.photo_question_open]
    assert game.hiding_ends_at == original_deadline  # not yet shifted

    resume_game(game, PauseReason.photo_question_open)

    assert game.paused_at is None
    delta = datetime.now(UTC) - original_paused_at
    _assert_close(game.hiding_ends_at, original_deadline + delta)


# ── Invariant: shifted deadlines >= now() at commit ──────────────────────────


@TIMESTAMPTZ_SKIP
def test_shifted_deadline_at_least_now_after_resume(session: Session, captured_events: list):
    """Per design: even a paused-while-overdue deadline shifts to >= now()."""
    pause_at = datetime.now(UTC) - timedelta(minutes=5)
    # Deadline would have fired 4 minutes ago if not paused.
    original_deadline = pause_at + timedelta(minutes=1)
    game = _seeking_game(session, hiding_ends_at=original_deadline)
    game.paused_at = pause_at
    game.active_pause_reasons = [PauseReason.host]
    session.flush()

    resume_game(game, PauseReason.host)

    assert game.hiding_ends_at is not None
    assert game.hiding_ends_at >= datetime.now(UTC) - timedelta(seconds=1)
