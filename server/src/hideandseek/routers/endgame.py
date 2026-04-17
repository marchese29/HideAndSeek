"""Endgame endpoints — exclusion view, candidate stations, and two-party found-claim flow."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query

from hideandseek.dependencies import (
    get_game,
    get_hider_in_game,
    get_seeker_in_game,
)
from hideandseek.schemas.response import EndgameExclusionsResponse
from hideandseek.validators import (
    validate_endgame_station,
    validate_found_claim,
    validate_found_decision,
)
from hideandseek_core.broadcast.emit import emit_gameplay
from hideandseek_core.broadcast.events import (
    FoundClaimEvent,
    FoundClaimRejectedEvent,
    GameEndedEvent,
)
from hideandseek_core.db import session_dependency
from hideandseek_core.logic.endgame import (
    confirm_found_claim,
    get_endgame_exclusions,
    record_found_claim,
    reject_found_claim,
)
from hideandseek_core.queries.questions import get_active_question
from hideandseek_models.game import Game, Player
from hideandseek_models.types import PushEventType
from hideandseek_worker.celery_app import app as celery_app
from hideandseek_worker.tasks.game_timers import auto_dismiss_found_claim
from hideandseek_worker.tasks.push import send_push

FOUND_CLAIM_TIMEOUT_SECONDS = 120

router = APIRouter(
    prefix='/games/{game_id}', tags=['endgame'], dependencies=[Depends(session_dependency)]
)


@router.get('/endgame-exclusions', response_model=EndgameExclusionsResponse)
def endgame_exclusions(
    station_id: uuid.UUID = Query(description='Stop ID to center the hiding zone on.'),
    after_question: int = Query(
        default=0, description='Only include questions with sequence > this value.'
    ),
    game: Game = Depends(get_game),
    _player: Player = Depends(get_seeker_in_game),
) -> EndgameExclusionsResponse:
    """Endgame exclusion view: per-question exclusions intersected with a hiding zone circle."""
    if not game.status.is_seeking:
        raise HTTPException(
            status_code=409, detail='Endgame view is only available during seeking.'
        )

    stop = validate_endgame_station(station_id, game)
    result = get_endgame_exclusions(game, stop, after_question)
    return EndgameExclusionsResponse.from_result(result)


@router.post('/found', status_code=204)
def claim_found(
    game: Game = Depends(get_game),
    seeker: Player = Depends(get_seeker_in_game),
) -> None:
    """Seeker claims to have found the hiders. Opens a 2-minute hider decision window."""
    validate_found_claim(game, seeker)
    record_found_claim(game, seeker)

    if not celery_app.conf.task_always_eager:
        auto_dismiss_found_claim.apply_async(  # type: ignore[attr-defined]
            args=[str(game.id)],
            countdown=FOUND_CLAIM_TIMEOUT_SECONDS,
            task_id=f'found_claim:{game.id}',
        )

    emit_gameplay(FoundClaimEvent(game_id=game.id, seeker_player_id=seeker.id))
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.found_claim,
        role_filter='hider',
        alert='A seeker says they found you! Confirm or reject.',
    )


@router.post('/found/confirm', status_code=204)
def confirm_found(
    game: Game = Depends(get_game),
    _hider: Player = Depends(get_hider_in_game),
) -> None:
    """Hider confirms the found claim. Ends the game with end_reason=found."""
    validate_found_decision(game)

    if not celery_app.conf.task_always_eager:
        celery_app.control.revoke(f'found_claim:{game.id}', terminate=False)
        celery_app.control.revoke(f'hiding_timer:{game.id}', terminate=False)
        active = get_active_question(game)
        if active:
            celery_app.control.revoke(f'answer_deadline:{active.id}', terminate=False)

    confirm_found_claim(game)
    emit_gameplay(GameEndedEvent(game_id=game.id))
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.game_ended,
        alert='The seekers found the hiders!',
    )


@router.post('/found/reject', status_code=204)
def reject_found(
    game: Game = Depends(get_game),
    _hider: Player = Depends(get_hider_in_game),
) -> None:
    """Hider rejects the found claim. Clears claim state; game continues."""
    validate_found_decision(game)

    if not celery_app.conf.task_always_eager:
        celery_app.control.revoke(f'found_claim:{game.id}', terminate=False)

    reject_found_claim(game)
    emit_gameplay(FoundClaimRejectedEvent(game_id=game.id))
    send_push.delay(  # type: ignore[attr-defined]
        str(game.id),
        PushEventType.found_claim_rejected,
        role_filter='seeker',
        alert='The hiders rejected the found claim.',
    )
