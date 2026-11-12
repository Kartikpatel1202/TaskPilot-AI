"""user preferences (Settings page)

Revision ID: 0002_user_preferences
Revises: 0001_initial
Create Date: 2026-11-12 16:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_user_preferences"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column("owner_key", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("owner_key", name=op.f("pk_user_preferences")),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
