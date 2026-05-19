from alembic.config import Config
from alembic import command
import os

here = os.path.dirname(os.path.dirname(__file__))
alembic_cfg = Config(os.path.join(here, "alembic.ini"))
alembic_cfg.set_main_option("script_location", "alembic")

print("Alembic current revision:")
command.current(alembic_cfg)
