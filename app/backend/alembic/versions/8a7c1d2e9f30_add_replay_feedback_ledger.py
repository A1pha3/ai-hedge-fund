"""add_replay_feedback_ledger

Revision ID: 8a7c1d2e9f30
Revises: d5e78f9a1b2c
Create Date: 2026-03-25 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8a7c1d2e9f30'
down_revision: Union[str, None] = 'd5e78f9a1b2c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'replay_research_feedback_ledger',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_name', sa.String(length=255), nullable=False),
        sa.Column('trade_date', sa.String(length=32), nullable=False),
        sa.Column('feedback_path', sa.Text(), nullable=False),
        sa.Column('run_id', sa.String(length=255), nullable=False),
        sa.Column('artifact_version', sa.String(length=32), nullable=False),
        sa.Column('label_version', sa.String(length=32), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('review_scope', sa.String(length=64), nullable=False),
        sa.Column('reviewer', sa.String(length=64), nullable=False),
        sa.Column('review_status', sa.String(length=32), nullable=False),
        sa.Column('primary_tag', sa.String(length=128), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('research_verdict', sa.String(length=128), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_name', 'trade_date', 'symbol', 'reviewer', 'primary_tag', 'created_at', name='uq_replay_feedback_ledger_record'),
    )
    op.create_index(op.f('ix_replay_research_feedback_ledger_id'), 'replay_research_feedback_ledger', ['id'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_ledger_report_name'), 'replay_research_feedback_ledger', ['report_name'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_ledger_trade_date'), 'replay_research_feedback_ledger', ['trade_date'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_ledger_symbol'), 'replay_research_feedback_ledger', ['symbol'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_ledger_reviewer'), 'replay_research_feedback_ledger', ['reviewer'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_ledger_review_status'), 'replay_research_feedback_ledger', ['review_status'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_ledger_primary_tag'), 'replay_research_feedback_ledger', ['primary_tag'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_ledger_research_verdict'), 'replay_research_feedback_ledger', ['research_verdict'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_ledger_created_at'), 'replay_research_feedback_ledger', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_replay_research_feedback_ledger_created_at'), table_name='replay_research_feedback_ledger')
    op.drop_index(op.f('ix_replay_research_feedback_ledger_research_verdict'), table_name='replay_research_feedback_ledger')
    op.drop_index(op.f('ix_replay_research_feedback_ledger_primary_tag'), table_name='replay_research_feedback_ledger')
    op.drop_index(op.f('ix_replay_research_feedback_ledger_review_status'), table_name='replay_research_feedback_ledger')
    op.drop_index(op.f('ix_replay_research_feedback_ledger_reviewer'), table_name='replay_research_feedback_ledger')
    op.drop_index(op.f('ix_replay_research_feedback_ledger_symbol'), table_name='replay_research_feedback_ledger')
    op.drop_index(op.f('ix_replay_research_feedback_ledger_trade_date'), table_name='replay_research_feedback_ledger')
    op.drop_index(op.f('ix_replay_research_feedback_ledger_report_name'), table_name='replay_research_feedback_ledger')
    op.drop_index(op.f('ix_replay_research_feedback_ledger_id'), table_name='replay_research_feedback_ledger')
    op.drop_table('replay_research_feedback_ledger')
