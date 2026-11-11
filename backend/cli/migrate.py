"""One-shot schema migration and runtime grants; never run per API worker."""
from pathlib import Path

from alembic import command
from alembic.config import Config

from common.database import engine


def main():
    command.upgrade(Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head")
    grants = Path(__file__).resolve().parents[2] / "database/runtime_grants.sql"
    with engine.begin() as connection:
        connection.exec_driver_sql(grants.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
