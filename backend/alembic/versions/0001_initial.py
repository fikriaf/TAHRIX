"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255)),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="analyst"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("tier", sa.String(32), nullable=False, server_default="free"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)

    op.create_table(
        "investigation_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("case_number", sa.String(32), nullable=False, unique=True),
        sa.Column("input_address", sa.String(80), nullable=False),
        sa.Column("input_chain", sa.String(16), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("risk_score", sa.Float()),
        sa.Column("risk_grade", sa.String(16)),
        sa.Column("gnn_score", sa.Float()),
        sa.Column("anomaly_codes", postgresql.JSON()),
        sa.Column("sanctions_hit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("summary", sa.Text()),
        sa.Column("iterations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float()),
        sa.Column("ipfs_cid", sa.String(80)),
        sa.Column("report_sha256", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("analyst_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_investigation_cases_input_address", "investigation_cases",
                    ["input_address"])
    op.create_index("ix_investigation_cases_status", "investigation_cases", ["status"])
    op.create_index("ix_cases_status_created", "investigation_cases", ["status", "created_at"])

    op.create_table(
        "case_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("investigation_cases.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("tool", sa.String(64)),
        sa.Column("payload", postgresql.JSON()),
        sa.Column("result", postgresql.JSON()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_type", sa.String(16), nullable=False, server_default="user"),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64)),
        sa.Column("resource_id", sa.String(80)),
        sa.Column("ip_address", sa.String(45)),
        sa.Column("metadata", postgresql.JSON()),
    )
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])

    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("external_id", sa.String(120), nullable=False),
        sa.Column("address", sa.String(80), nullable=False),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("investigation_cases.id", ondelete="SET NULL")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_webhook_subscriptions_address",
                    "webhook_subscriptions", ["address"])
    op.create_index("ix_webhook_subscriptions_external_id",
                    "webhook_subscriptions", ["external_id"])


def downgrade() -> None:
    op.drop_table("webhook_subscriptions")
    op.drop_table("audit_log")
    op.drop_table("case_events")
    op.drop_table("investigation_cases")
    op.drop_table("api_keys")
    op.drop_table("users")
