"""Alembic migration test against an intentionally old SQLite schema."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PROJECT_ROOT = Path(__file__).resolve().parent


def _upgrade_to_head(db_path: Path) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}".replace("%", "%%"))
    command.upgrade(config, "head")


def test_old_schema_is_migrated_idempotently_without_losing_rows(tmp_path):
    db_path = tmp_path / "legacy.db"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE users ("
            "id INTEGER PRIMARY KEY, name VARCHAR(100) NOT NULL, email VARCHAR(150), "
            "role VARCHAR(50), is_active BOOLEAN, is_approved BOOLEAN, "
            "phone VARCHAR(20), address VARCHAR(255), city VARCHAR(100), area VARCHAR(100), "
            "specializations TEXT, license_number VARCHAR(100), bar_association VARCHAR(150), "
            "experience_years INTEGER, chamber_address VARCHAR(255))"
        )
        connection.exec_driver_sql(
            "INSERT INTO users (id, name, role, is_active, is_approved, city, license_number) "
            "VALUES (1, 'Existing Client', 'client', 1, 1, 'Karachi', NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO users (id, name, role, is_active, is_approved, phone, city, "
            "license_number, bar_association, experience_years, chamber_address) "
            "VALUES (2, 'Legacy Advocate', 'advocate', 1, 0, '03001234567', 'Karachi', "
            "'BC-123', 'Karachi Bar Association', 7, 'Chamber 11')"
        )
        connection.exec_driver_sql(
            "CREATE TABLE lawyers ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
            "name VARCHAR(150) NOT NULL, specialty VARCHAR(150), address VARCHAR(255), "
            "chamber_address VARCHAR(255), city VARCHAR(100), area VARCHAR(100), "
            "phone VARCHAR(20), law_card_url VARCHAR(500), is_verified BOOLEAN, "
            "lat FLOAT, lng FLOAT, license_number VARCHAR(100), "
            "bar_association VARCHAR(150), experience_years INTEGER)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE appointments (id INTEGER PRIMARY KEY, booking_date VARCHAR(50), time_slot VARCHAR(100))"
        )
        connection.exec_driver_sql(
            "INSERT INTO appointments (id, booking_date, time_slot) VALUES (1, '2026-10-30', '10:00')"
        )
    engine.dispose()

    _upgrade_to_head(db_path)
    _upgrade_to_head(db_path)  # Running the same migration twice is harmless.

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    assert "residential_address" in {c["name"] for c in inspector.get_columns("users")}
    assert "chamber_address" in {c["name"] for c in inspector.get_columns("lawyers")}
    assert "created_at" in {c["name"] for c in inspector.get_columns("appointments")}

    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT name FROM users WHERE id=1")
        ).scalar_one() == "Existing Client"
        created_at = connection.execute(
            text("SELECT created_at FROM appointments WHERE id=1")
        ).scalar_one()
        assert created_at is not None
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        assert revision == "20261029_0004"
        assert "payments" in inspector.get_table_names()
        assert "payment_ledger_entries" in inspector.get_table_names()
        # Legacy advocates get a directory profile, but not public verification.
        advocate = connection.execute(
            text("SELECT user_id, name, chamber_address, is_verified, address "
                 "FROM lawyers WHERE user_id=2")
        ).mappings().one()
        assert advocate["name"] == "Legacy Advocate"
        assert advocate["chamber_address"] == "Chamber 11"
        assert advocate["is_verified"] in (0, False)
        assert advocate["address"] is None  # do not leak private home address
    engine.dispose()
