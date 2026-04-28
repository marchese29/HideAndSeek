"""game timer pause: pause primitive + future-deadline columns

Adds:
- Game.paused_at, Game.active_pause_reasons (JSON, default []),
  Game.seeking_pause_accumulated_sec (int, default 0).
- Game.hiding_ends_at, Game.found_claim_expires_at, Question.deadline_at.

Backfills in-flight games / questions so the deadline columns are populated
before later cycles switch reads to them. PauseReason values store as VARCHAR
via Base.type_annotation_map -- no native enum type created.

Revision ID: b4d5b840b4b0
Revises: b84ee5d6d506
Create Date: 2026-04-28 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b4d5b840b4b0'
down_revision: Union[str, Sequence[str], None] = 'b84ee5d6d506'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Pause primitive on Game.
    op.add_column('game', sa.Column('paused_at', sa.DateTime(), nullable=True))
    op.add_column(
        'game',
        sa.Column(
            'active_pause_reasons',
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        'game',
        sa.Column(
            'seeking_pause_accumulated_sec',
            sa.Integer(),
            nullable=False,
            server_default=sa.text('0'),
        ),
    )

    # Future-deadline columns.
    op.add_column('game', sa.Column('hiding_ends_at', sa.DateTime(), nullable=True))
    op.add_column('game', sa.Column('found_claim_expires_at', sa.DateTime(), nullable=True))
    op.add_column('question', sa.Column('deadline_at', sa.DateTime(), nullable=True))

    # Backfill in-flight hiding-phase games.
    op.execute(
        'UPDATE game '
        'SET hiding_ends_at = hiding_started_at '
        "    + (hiding_time_min * interval '1 minute') "
        "WHERE status = 'hiding' AND hiding_started_at IS NOT NULL"
    )

    # Backfill any active found-claim. FOUND_CLAIM_TIMEOUT_SECONDS = 120 in
    # core/logic/endgame.py.
    op.execute(
        'UPDATE game '
        "SET found_claim_expires_at = found_claim_at + interval '120 seconds' "
        'WHERE found_claim_at IS NOT NULL'
    )

    # Backfill answerable non-photo questions only -- photo questions use
    # effective_photo_submit_min (different window) that this cycle does not
    # migrate; their deadline column lands with the photo follow-on.
    op.execute(
        'UPDATE question SET deadline_at = '
        "    question.answerable_at + (game.base_question_delay_min * interval '1 minute') "
        'FROM game '
        'WHERE question.game_id = game.id '
        "  AND question.status = 'answerable' "
        "  AND question.question_type != 'photo' "
        '  AND question.answerable_at IS NOT NULL'
    )

    # Drop server_defaults -- model owns defaults at the application layer.
    op.alter_column('game', 'active_pause_reasons', server_default=None)
    op.alter_column('game', 'seeking_pause_accumulated_sec', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('question', 'deadline_at')
    op.drop_column('game', 'found_claim_expires_at')
    op.drop_column('game', 'hiding_ends_at')
    op.drop_column('game', 'seeking_pause_accumulated_sec')
    op.drop_column('game', 'active_pause_reasons')
    op.drop_column('game', 'paused_at')
