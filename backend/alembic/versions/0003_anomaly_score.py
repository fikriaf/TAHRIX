"""add anomaly_score column to investigation_cases

Revision ID: 0003_anomaly_score
Revises: 0002_telegram
Create Date: 2026-05-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_anomaly_score"
down_revision = "0002_telegram"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "investigation_cases",
        sa.Column("anomaly_score", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("investigation_cases", "anomaly_score")
