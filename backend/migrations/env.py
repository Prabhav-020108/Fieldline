import os
import sys
from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context

# backend/migrations/env.py runs with sys.path[0] pointing at the alembic
# executable's own folder, not this project -- add backend/ explicitly so
# `import models` / `import settings` below actually resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Base  # noqa: E402
from settings import settings  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Deliberately NOT using config.set_main_option("sqlalchemy.url", ...).
# alembic.ini is parsed with Python's ConfigParser, which treats any "%"
# in a value as the start of its OWN %-interpolation syntax -- a password
# containing a literal "%" (common in Supabase-generated passwords)
# makes set_main_option() raise "invalid interpolation syntax" before a
# single migration runs. Configuring the engine directly below sidesteps
# ConfigParser entirely, so this works for any password, encoded or not.
DATABASE_URL = settings.database_url


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()