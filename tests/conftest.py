import pytest

from config.settings import AppSettings, DatabaseSettings, SafetySettings
from database.connection import initialize_database, open_connection
from tools.calendar import MockCalendar
from tools.crm import MockCRM
from tools.email import MockEmail
from tools.sms import MockSMS


@pytest.fixture
def db(tmp_path):
    """Open and initialize a fresh SQLite database for each test."""
    settings = DatabaseSettings(sqlite_path=tmp_path / "tools-test.sqlite3")
    connection = open_connection(settings)
    initialize_database(connection)

    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def settings():
    return AppSettings(
        safety=SafetySettings(
            max_tool_retries=2,
            tool_timeout_seconds=2.0,
            spending_limit_usd_per_run="10.00",
        )
    )


@pytest.fixture
def enabled_tools(db, settings):
    db.execute(
        "UPDATE system_controls SET kill_switch_active = 0, "
        "spending_limit_micros = 10000000 WHERE control_id = 1"
    )

    return {
        "crm": MockCRM(db, settings),
        "calendar": MockCalendar(db, settings),
        "sms": MockSMS(db, settings),
        "email": MockEmail(db, settings),
    }