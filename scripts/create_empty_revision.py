import datetime
from pathlib import Path

here = Path(__file__).resolve().parents[1]
versions_dir = here / "alembic" / "versions"
versions_dir.mkdir(parents=True, exist_ok=True)

rev_id = datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S")
filename = versions_dir / f"{rev_id}_initial_models.py"
content = f'''"""initial models (empty autogen placeholder)

Revision ID: {rev_id}
Revises:
Create Date: {datetime.datetime.utcnow().isoformat()}

"""
# revision identifiers, used by Alembic.
revision = '{rev_id}'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Autogenerate detected no schema changes (placeholder)
    pass


def downgrade() -> None:
    pass

'''

with open(filename, "w", encoding="utf-8") as f:
    f.write(content)

print("Wrote empty revision:", filename)
