"""${message}

Revision ID: ${rev_id}
Revises: ${down_revision if down_revision else ''}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '${rev_id}'
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else 'pass'}


def downgrade() -> None:
    ${downgrades if downgrades else 'pass'}
