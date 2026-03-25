"""add replay feedback workflow items

Revision ID: b91e4f2c7a11
Revises: 8a7c1d2e9f30
Create Date: 2026-03-26 00:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b91e4f2c7a11'
down_revision = '8a7c1d2e9f30'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'replay_research_feedback_workflow_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('report_name', sa.String(length=255), nullable=False),
        sa.Column('trade_date', sa.String(length=32), nullable=False),
        sa.Column('symbol', sa.String(length=32), nullable=False),
        sa.Column('review_scope', sa.String(length=64), nullable=False),
        sa.Column('feedback_path', sa.Text(), nullable=False),
        sa.Column('latest_feedback_created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('latest_reviewer', sa.String(length=64), nullable=False),
        sa.Column('latest_review_status', sa.String(length=32), nullable=False),
        sa.Column('latest_primary_tag', sa.String(length=128), nullable=False),
        sa.Column('latest_tags', sa.JSON(), nullable=True),
        sa.Column('latest_research_verdict', sa.String(length=128), nullable=False),
        sa.Column('latest_notes', sa.Text(), nullable=False),
        sa.Column('assignee', sa.String(length=64), nullable=True),
        sa.Column('workflow_status', sa.String(length=32), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_name', 'trade_date', 'symbol', 'review_scope', name='uq_replay_feedback_workflow_item'),
    )
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_report_name'), 'replay_research_feedback_workflow_items', ['report_name'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_trade_date'), 'replay_research_feedback_workflow_items', ['trade_date'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_symbol'), 'replay_research_feedback_workflow_items', ['symbol'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_review_scope'), 'replay_research_feedback_workflow_items', ['review_scope'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_latest_feedback_created_at'), 'replay_research_feedback_workflow_items', ['latest_feedback_created_at'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_latest_reviewer'), 'replay_research_feedback_workflow_items', ['latest_reviewer'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_latest_review_status'), 'replay_research_feedback_workflow_items', ['latest_review_status'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_latest_primary_tag'), 'replay_research_feedback_workflow_items', ['latest_primary_tag'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_latest_research_verdict'), 'replay_research_feedback_workflow_items', ['latest_research_verdict'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_assignee'), 'replay_research_feedback_workflow_items', ['assignee'], unique=False)
    op.create_index(op.f('ix_replay_research_feedback_workflow_items_workflow_status'), 'replay_research_feedback_workflow_items', ['workflow_status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_workflow_status'), table_name='replay_research_feedback_workflow_items')
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_assignee'), table_name='replay_research_feedback_workflow_items')
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_latest_research_verdict'), table_name='replay_research_feedback_workflow_items')
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_latest_primary_tag'), table_name='replay_research_feedback_workflow_items')
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_latest_review_status'), table_name='replay_research_feedback_workflow_items')
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_latest_reviewer'), table_name='replay_research_feedback_workflow_items')
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_latest_feedback_created_at'), table_name='replay_research_feedback_workflow_items')
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_review_scope'), table_name='replay_research_feedback_workflow_items')
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_symbol'), table_name='replay_research_feedback_workflow_items')
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_trade_date'), table_name='replay_research_feedback_workflow_items')
    op.drop_index(op.f('ix_replay_research_feedback_workflow_items_report_name'), table_name='replay_research_feedback_workflow_items')
    op.drop_table('replay_research_feedback_workflow_items')