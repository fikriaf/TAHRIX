"""Add wallet_address to users table."""

from alembic import op
import sqlalchemy as sa

revision = '0005_add_wallet_address'
down_revision = '0004_address_labels'
branch = None
depends_on = None

def upgrade() -> None:
    op.add_column('users', sa.Column('wallet_address', sa.String(64), nullable=True, unique=True, index=True))

def downgrade() -> None:
    op.drop_column('users', 'wallet_address')