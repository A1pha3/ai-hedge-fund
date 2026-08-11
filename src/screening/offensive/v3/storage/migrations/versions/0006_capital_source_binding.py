"""Causal capital source bindings.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-10

Plan 08 Task 7. Adds one nullable column to ``reserves``:

- ``source_binding_json``: canonical JSON of the causal
  ``CapitalSourceBinding`` (mode/artifact kind/id/hash) that produced the
  reserve. NULL for legacy and non-Trial reserves; the official shadow
  adapter always writes it.

Economic events need no new column: they already persist the canonical
payload JSON, and the binding is carried inside
``CapitalCommandPayload.source_binding``.

The column is additive and nullable, so existing rows are preserved
byte-for-byte. The revision is idempotent by inspection: a fresh
``upgrade head`` run finds the column already present through the evolved
``build_metadata()`` and only verifies it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {
        column["name"] for column in inspector.get_columns("reserves")
    }
    if "source_binding_json" not in existing:
        op.add_column(
            "reserves",
            sa.Column("source_binding_json", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {
        column["name"] for column in inspector.get_columns("reserves")
    }
    if "source_binding_json" in existing:
        op.drop_column("reserves", "source_binding_json")
