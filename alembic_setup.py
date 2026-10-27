"""
Alembic Migration Initializer for LawNexa.
"""
import os

ALEMBIC_INI = """[alembic]
script_location = alembic
sqlalchemy.url = %(DATABASE_URL)s

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =

[logger_alembic]
level = INFO
handlers =

[handler_console]
class = StreamHandler
args = (sys.stdout,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
"""

ENV_PY = """import os
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from database import Base, DATABASE_URL

config = context.config
config.set_main_option("DATABASE_URL", DATABASE_URL)

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
"""

def setup_alembic():
    if not os.path.exists("alembic.ini"):
        with open("alembic.ini", "w") as f:
            f.write(ALEMBIC_INI.strip())
    os.makedirs("alembic/versions", exist_ok=True)
    if not os.path.exists("alembic/env.py"):
        with open("alembic/env.py", "w") as f:
            f.write(ENV_PY.strip())
    print("Alembic setup complete.")

if __name__ == "__main__":
    setup_alembic()
