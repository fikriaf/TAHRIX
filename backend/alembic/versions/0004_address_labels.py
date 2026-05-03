"""0004_address_labels — analyst-submitted address intelligence labels

Revision ID: 0004_address_labels
Revises: 0003_anomaly_score
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_address_labels"
down_revision = "0003_anomaly_score"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "address_labels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("address", sa.String(80), nullable=False),
        sa.Column("chain", sa.String(16), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("chronology", sa.Text(), nullable=True),
        sa.Column("poc_filename", sa.String(255), nullable=True),
        sa.Column("poc_content", sa.Text(), nullable=True),
        sa.Column("poc_mimetype", sa.String(120), nullable=True),
        sa.Column("audit_verdict", sa.String(32), nullable=True),
        sa.Column("audit_confidence", sa.Float(), nullable=True),
        sa.Column("audit_summary", sa.Text(), nullable=True),
        sa.Column("audit_flags", sa.JSON(), nullable=True),
        sa.Column("audited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("case_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("investigation_cases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_labels_address", "address_labels", ["address"])
    op.create_index("ix_labels_address_chain", "address_labels", ["address", "chain"])


def downgrade() -> None:
    op.drop_index("ix_labels_address_chain", "address_labels")
    op.drop_index("ix_labels_address", "address_labels")
    op.drop_table("address_labels")
