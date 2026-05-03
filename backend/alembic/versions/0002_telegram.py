"""telegram subscriptions & link tokens

Revision ID: 0002_telegram
Revises: 0001_initial
Create Date: 2026-05-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_telegram"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"),
                  nullable=False, unique=True),
        sa.Column("chat_id", sa.String(64), nullable=False),
        sa.Column("telegram_user_id", sa.String(64)),
        sa.Column("telegram_username", sa.String(120)),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("linked_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_telegram_subscriptions_user_id",
        "telegram_subscriptions", ["user_id"],
    )
    op.create_index(
        "ix_telegram_subscriptions_chat_id",
        "telegram_subscriptions", ["chat_id"],
    )

    op.create_table(
        "telegram_link_tokens",
        sa.Column("token", sa.String(64), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_telegram_link_tokens_user_id",
        "telegram_link_tokens", ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_telegram_link_tokens_user_id", table_name="telegram_link_tokens")
    op.drop_table("telegram_link_tokens")
    op.drop_index("ix_telegram_subscriptions_chat_id", table_name="telegram_subscriptions")
    op.drop_index("ix_telegram_subscriptions_user_id", table_name="telegram_subscriptions")
    op.drop_table("telegram_subscriptions")
