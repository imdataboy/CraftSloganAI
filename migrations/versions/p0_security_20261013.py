"""Add ownership and encrypted OAuth storage without assigning legacy records.

Revision ID: p0_security_20261013
Revises: 3d33747b84ae
"""

import sqlalchemy as sa
from alembic import op

revision = "p0_security_20261013"
down_revision = "3d33747b84ae"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("emails", "slogans", "images", "linkedin_posts"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(f"fk_{table}_user_id", "users", ["user_id"], ["id"])
            batch.create_index(f"ix_{table}_user_id", ["user_id"])
    with op.batch_alter_table("images") as batch:
        batch.add_column(
            sa.Column("is_generated", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("sha256", sa.String(64), nullable=True))
    with op.batch_alter_table("linkedin_posts") as batch:
        batch.add_column(sa.Column("linkedin_post_id", sa.String(), nullable=True))
    op.create_table(
        "oauth_credentials",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("encrypted_token", sa.Text(), nullable=False),
        sa.UniqueConstraint("user_id", "provider"),
    )
    op.create_index("ix_oauth_credentials_user_id", "oauth_credentials", ["user_id"])
    op.create_table(
        "oauth_states",
        sa.Column("state_hash", sa.String(64), primary_key=True),
        sa.Column("browser_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_oauth_states_user_id", "oauth_states", ["user_id"])


def downgrade():
    # Dropping ownership would restore the original cross-user exposure and lose tokens.
    raise RuntimeError(
        "Security migration downgrade is intentionally disabled. Restore a reviewed backup instead."
    )
