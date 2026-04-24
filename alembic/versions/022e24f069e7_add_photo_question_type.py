"""Add photo question type

Adds:
- Enum values: questiontype.photo, questionstatus.submitted (ALTER TYPE, autocommit).
- Table: photo_question_params (one-to-one with question).
- Columns: game.photo_submit_min, game.photo_review_sec,
  game_map.default_photo_submit_min, game_map.default_photo_review_sec,
  inventory_slot.photo_subject.

PhotoSubject / PhotoReviewDecision are stored as VARCHAR (matching
Base.type_annotation_map={StrEnum: String}). No new Postgres ENUM types
are created — the existing native enums (questiontype, questionstatus)
stay as native enums and are extended in place.

Existing dev deployments should reseed the GameMap default_inventory JSON
(via scripts/seed_seattle_map.py) to include the new 'photos' key.

Revision ID: 022e24f069e7
Revises: c8f7386a37e9
Create Date: 2026-04-24 10:55:32.382474

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '022e24f069e7'
down_revision: Union[str, Sequence[str], None] = 'c8f7386a37e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TYPE ... ADD VALUE can't run inside the outer migration transaction.
    # autocommit_block commits the outer tx, runs in AUTOCOMMIT, then resumes.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE questiontype ADD VALUE IF NOT EXISTS 'photo'")
        op.execute("ALTER TYPE questionstatus ADD VALUE IF NOT EXISTS 'submitted'")

    op.create_table(
        'photo_question_params',
        sa.Column('question_id', sa.Uuid(), nullable=False),
        sa.Column('subject', sa.String(), nullable=False),
        sa.Column('photo_object_key', sa.String(), nullable=True),
        sa.Column('is_null_answer', sa.Boolean(), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('submitted_by', sa.Uuid(), nullable=True),
        sa.Column('review_decision', sa.String(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('reviewed_by', sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(['question_id'], ['question.id']),
        sa.ForeignKeyConstraint(['submitted_by'], ['player.id']),
        sa.ForeignKeyConstraint(['reviewed_by'], ['player.id']),
        sa.PrimaryKeyConstraint('question_id'),
    )
    op.add_column('game', sa.Column('photo_submit_min', sa.Integer(), nullable=True))
    op.add_column('game', sa.Column('photo_review_sec', sa.Integer(), nullable=True))
    op.add_column('game_map', sa.Column('default_photo_submit_min', sa.Integer(), nullable=True))
    op.add_column('game_map', sa.Column('default_photo_review_sec', sa.Integer(), nullable=True))
    op.add_column('inventory_slot', sa.Column('photo_subject', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('inventory_slot', 'photo_subject')
    op.drop_column('game_map', 'default_photo_review_sec')
    op.drop_column('game_map', 'default_photo_submit_min')
    op.drop_column('game', 'photo_review_sec')
    op.drop_column('game', 'photo_submit_min')
    op.drop_table('photo_question_params')
    # Postgres does not support ALTER TYPE ... DROP VALUE. Leaving
    # 'photo' / 'submitted' in place on downgrade is the accepted trade-off —
    # harmless if unused.
