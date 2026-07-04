"""add invite revocation and role columns

Revision ID: a1b2c3d4e5f6
Revises: d5e78f9a1b2c
Create Date: 2026-06-06 10:00:00.000000

Adds revoked_at, revoked_by, role_to_assign columns to invitation_codes table
to support invite revocation and role assignment on redeem.

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "d5e78f9a1b2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add revoked_at column if it doesn't exist
    with op.batch_alter_table("invitation_codes", schema=None) as batch_op:
        batch_op.add_column(sa.Column("revoked_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("revoked_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("role_to_assign", sa.String(20), nullable=True))
        batch_op.create_foreign_key("fk_invitation_codes_revoked_by_users", "users", ["revoked_by"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("invitation_codes", schema=None) as batch_op:
        batch_op.drop_constraint("fk_invitation_codes_revoked_by_users", type_="foreignkey")
        batch_op.drop_column("role_to_assign")
        batch_op.drop_column("revoked_by")
        batch_op.drop_column("revoked_at")
