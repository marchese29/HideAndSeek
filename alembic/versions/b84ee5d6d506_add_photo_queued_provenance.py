"""add photo queued provenance

Adds `queued_at` / `queued_by` columns to `photo_question_params` so the hider
SSE snapshot can rehydrate the queued-state banner after reconnect (the queued
photo currently lives only on `photo_object_key`, with no provenance).

Revision ID: b84ee5d6d506
Revises: 022e24f069e7
Create Date: 2026-04-27 06:58:51.576269

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b84ee5d6d506'
down_revision: Union[str, Sequence[str], None] = '022e24f069e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('photo_question_params', sa.Column('queued_at', sa.DateTime(), nullable=True))
    op.add_column('photo_question_params', sa.Column('queued_by', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'photo_question_params_queued_by_fkey',
        'photo_question_params',
        'player',
        ['queued_by'],
        ['id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'photo_question_params_queued_by_fkey', 'photo_question_params', type_='foreignkey'
    )
    op.drop_column('photo_question_params', 'queued_by')
    op.drop_column('photo_question_params', 'queued_at')
