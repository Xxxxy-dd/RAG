from alembic.config import Config
from alembic import command
import os

here = os.path.dirname(os.path.dirname(__file__))
alembic_cfg = Config(os.path.join(here, "alembic.ini"))

# Ensure alembic uses current working directory
alembic_cfg.set_main_option("script_location", "alembic")

print("Generating autogenerate revision...")
command.revision(alembic_cfg, message="initial models", autogenerate=True)
print("Revision generated.")
