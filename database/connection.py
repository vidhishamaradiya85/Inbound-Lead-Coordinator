"""SQLite connection, transaction, and runtime initialization helpers.

Importing this module does not open a database or create any files. The
connection and initialization functions are intended for explicit runtime use.
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from config.settings import DatabaseSettings, load_settings


MockResource = tuple[str, str, int, str]
MockResourceService = tuple[str, str]
MockSlot = tuple[str, str, str, str, str, str, int]

CALENDAR_RESOURCE_MIGRATION_ID = "0002_calendar_resources"
CALENDAR_BOOKING_GUARDS_MIGRATION_ID = "0003_calendar_booking_guards"

# Fixed fictional UTC slots keep the local demonstration deterministic.
MOCK_CALENDAR_RESOURCES: tuple[MockResource, ...] = (
    ("MOCK-TECH-001", "Mock Technician 1", 1, "2026-11-19T00:00:00Z"),
    ("MOCK-TECH-002", "Mock Technician 2", 1, "2026-11-19T00:00:00Z"),
)

MOCK_RESOURCE_SERVICES: tuple[MockResourceService, ...] = (
    ("MOCK-TECH-001", "heat pump inspection"),
    ("MOCK-TECH-001", "water heater repair"),
    ("MOCK-TECH-001", "kitchen faucet repair"),
    ("MOCK-TECH-001", "roof leak inspection"),
    ("MOCK-TECH-002", "heat pump inspection"),
    ("MOCK-TECH-002", "boiler maintenance"),
    ("MOCK-TECH-002", "air conditioner tune-up"),
    ("MOCK-TECH-002", "drain clearing"),
)

MOCK_CALENDAR_SLOTS: tuple[MockSlot, ...] = (
    ("MOCK-SLOT-001", "DEMO-NORTH", "heat pump inspection", "2027-01-05T15:00:00Z", "2027-01-05T15:30:00Z", "MOCK-TECH-001", 1),
    ("MOCK-SLOT-002", "DEMO-NORTH", "heat pump inspection", "2027-01-05T16:00:00Z", "2027-01-05T16:30:00Z", "MOCK-TECH-002", 1),
    ("MOCK-SLOT-003", "DEMO-NORTH", "water heater repair", "2027-01-06T14:00:00Z", "2027-01-06T15:00:00Z", "MOCK-TECH-001", 1),
    ("MOCK-SLOT-004", "DEMO-NORTH", "kitchen faucet repair", "2027-01-06T16:00:00Z", "2027-01-06T16:30:00Z", "MOCK-TECH-001", 1),
    ("MOCK-SLOT-005", "DEMO-SOUTH", "boiler maintenance", "2027-01-07T15:00:00Z", "2027-01-07T16:00:00Z", "MOCK-TECH-002", 1),
    ("MOCK-SLOT-006", "DEMO-SOUTH", "air conditioner tune-up", "2027-01-08T14:00:00Z", "2027-01-08T15:00:00Z", "MOCK-TECH-002", 1),
    ("MOCK-SLOT-007", "DEMO-NORTH", "roof leak inspection", "2027-01-09T13:00:00Z", "2027-01-09T14:00:00Z", "MOCK-TECH-001", 1),
    ("MOCK-SLOT-008", "DEMO-SOUTH", "drain clearing", "2027-01-09T16:00:00Z", "2027-01-09T16:30:00Z", "MOCK-TECH-002", 1),
)


def open_connection(settings: DatabaseSettings | None = None) -> sqlite3.Connection:
    """Open a runtime SQLite connection with foreign keys and configured timeout.

    Calling this function creates the database file when it does not exist.
    This module does not call it during import or project setup.
    """

    database_settings = settings or load_settings().database
    if not database_settings.foreign_keys_enabled:
        raise ValueError("SQLite foreign-key enforcement must remain enabled")

    connection = sqlite3.connect(
        str(database_settings.sqlite_path),
        timeout=database_settings.busy_timeout_ms / 1000,
        isolation_level=None,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    foreign_keys_enabled = connection.execute("PRAGMA foreign_keys").fetchone()
    if foreign_keys_enabled is None or foreign_keys_enabled[0] != 1:
        connection.close()
        raise RuntimeError("SQLite foreign-key enforcement could not be enabled")

    return connection


@contextmanager
def transaction(
    connection: sqlite3.Connection,
    *,
    immediate: bool = True,
) -> Iterator[sqlite3.Connection]:
    """Run a transaction and reliably commit or roll back its work.

    Nested transactions are rejected; callers should keep transaction scope
    explicit and short. `BEGIN IMMEDIATE` reserves the write transaction early.
    """

    if connection.in_transaction:
        raise RuntimeError("Nested transactions are not supported")

    connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield connection
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    else:
        try:
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise


def execute(
    connection: sqlite3.Connection,
    statement: str,
    parameters: Sequence[Any] | Mapping[str, Any],
) -> sqlite3.Cursor:
    """Execute a static SQL statement with bound values supplied separately."""

    return connection.execute(statement, parameters)


def executemany(
    connection: sqlite3.Connection,
    statement: str,
    parameter_rows: Iterable[Sequence[Any] | Mapping[str, Any]],
) -> sqlite3.Cursor:
    """Execute a static SQL statement for multiple parameter rows."""

    return connection.executemany(statement, parameter_rows)


def fetch_one(
    connection: sqlite3.Connection,
    statement: str,
    parameters: Sequence[Any] | Mapping[str, Any],
) -> sqlite3.Row | None:
    """Fetch one row using a parameterized query."""

    return execute(connection, statement, parameters).fetchone()


def fetch_all(
    connection: sqlite3.Connection,
    statement: str,
    parameters: Sequence[Any] | Mapping[str, Any],
) -> list[sqlite3.Row]:
    """Fetch all rows using a parameterized query."""

    return execute(connection, statement, parameters).fetchall()


def initialize_database(connection: sqlite3.Connection) -> None:
    """Apply the operational schema and seed initial controls and mock slots.

    This function acts only on the connection supplied by the caller. It does
    not open a database connection itself. Seed values use bound parameters.
    """

    if connection.in_transaction:
        raise RuntimeError("Database initialization cannot run inside an existing transaction")
    connection.execute("PRAGMA foreign_keys = ON")
    fk_state = connection.execute("PRAGMA foreign_keys").fetchone()
    if fk_state is None or fk_state[0] != 1:
        raise RuntimeError("SQLite foreign-key enforcement must be enabled for initialization")

    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    with transaction(connection):
        _prepare_calendar_migrations(connection)
        _execute_sql_script(connection, _read_runtime_schema())
        _apply_script_migration_in_transaction(
            connection,
            CALENDAR_BOOKING_GUARDS_MIGRATION_ID,
            _read_calendar_booking_guards_migration(),
            normalize_legacy_slots=True,
        )
        execute(
            connection,
            "INSERT OR IGNORE INTO schema_migrations (migration_id, applied_at) VALUES (?, ?)",
            (CALENDAR_RESOURCE_MIGRATION_ID, now),
        )
        execute(
            connection,
            """
            INSERT OR IGNORE INTO system_controls (
                control_id,
                kill_switch_active,
                kill_switch_activated_at,
                kill_switch_changed_by,
                kill_switch_reason,
                spending_limit_micros,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 1, now, "system", "Initial fail-safe state", 0, now),
        )
        executemany(
            connection,
            """INSERT OR IGNORE INTO calendar_resources
               (resource_id, display_name, is_active, created_at) VALUES (?, ?, ?, ?)""",
            MOCK_CALENDAR_RESOURCES,
        )
        executemany(
            connection,
            """INSERT OR IGNORE INTO calendar_resource_services
               (resource_id, service_requested) VALUES (?, ?)""",
            MOCK_RESOURCE_SERVICES,
        )
        executemany(
            connection,
            """
            INSERT OR IGNORE INTO calendar_slots (
                slot_id,
                service_area_id,
                service_requested,
                starts_at,
                ends_at,
                resource_id,
                is_active
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            MOCK_CALENDAR_SLOTS,
        )
        # Upgrade pre-existing seeded slots only when no active booking depends
        # on their prior unknown assignment.
        executemany(
            connection,
            """UPDATE calendar_slots
               SET resource_id = ?
               WHERE slot_id = ? AND resource_id IS NULL
                 AND NOT EXISTS (
                     SELECT 1 FROM appointments
                     WHERE appointments.slot_id = calendar_slots.slot_id
                       AND appointments.status = 'booked'
                 )""",
            [(slot[5], slot[0]) for slot in MOCK_CALENDAR_SLOTS],
        )
        execute(
            connection,
            """INSERT OR IGNORE INTO calendar_reconciliation_flags
               (entity_type, entity_id, reason, created_at)
               SELECT 'appointment', appointment_id,
                      'Legacy active appointment has unknown technician/resource assignment', ?
               FROM appointments WHERE status = 'booked' AND resource_id IS NULL""",
            (now,),
        )


def _read_runtime_schema() -> str:
    return Path(__file__).with_name("runtime_schema.sql").read_text(encoding="utf-8")


def _read_calendar_booking_guards_migration() -> str:
    migration_path = Path(__file__).parent / "migrations" / "0003_calendar_booking_guards.sql"
    return migration_path.read_text(encoding="utf-8")


def _execute_sql_script(connection: sqlite3.Connection, sql_script: str) -> None:
    """Execute a SQL script statement-by-statement without implicit commits."""
    pending = ""
    for line in sql_script.splitlines(keepends=True):
        pending += line
        if sqlite3.complete_statement(pending):
            statement = pending.strip()
            pending = ""
            if statement:
                connection.execute(statement)
    if pending.strip():
        raise ValueError("SQL script contains an incomplete statement")


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return fetch_one(
        connection,
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ) is not None


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    # table is selected from fixed internal names, never caller input.
    return {row["name"] for row in fetch_all(connection, f"PRAGMA table_info({table})", ())}


def _applied_migrations(connection: sqlite3.Connection) -> set[str]:
    if not _table_exists(connection, "schema_migrations"):
        return set()
    return {
        row["migration_id"]
        for row in fetch_all(connection, "SELECT migration_id FROM schema_migrations", ())
    }


def _prepare_calendar_migrations(connection: sqlite3.Connection) -> None:
    has_slots = _table_exists(connection, "calendar_slots")
    has_appointments = _table_exists(connection, "appointments")
    if not has_slots and not has_appointments:
        return
    if has_slots != has_appointments:
        raise RuntimeError("Calendar schema is incomplete; refusing a partial migration")

    slot_has_resource = "resource_id" in _table_columns(connection, "calendar_slots")
    appointment_has_resource = "resource_id" in _table_columns(connection, "appointments")
    applied = _applied_migrations(connection)
    has_v2 = CALENDAR_RESOURCE_MIGRATION_ID in applied

    if not slot_has_resource and not appointment_has_resource and not has_v2:
        _apply_script_migration_in_transaction(
            connection,
            CALENDAR_RESOURCE_MIGRATION_ID,
            _read_calendar_resource_migration(),
            normalize_legacy_slots=True,
        )
        return

    if slot_has_resource and appointment_has_resource and has_v2:
        return

    raise RuntimeError(
        "Calendar resource migration state is inconsistent; "
        "both resource columns and migration 0002 must agree"
    )


def _read_calendar_resource_migration() -> str:
    migration_path = Path(__file__).parent / "migrations" / "0002_calendar_resources.sql"
    return migration_path.read_text(encoding="utf-8")


def _apply_script_migration_in_transaction(
    connection: sqlite3.Connection,
    migration_id: str,
    migration_sql: str,
    *,
    normalize_legacy_slots: bool = False,
) -> None:
    if not _table_exists(connection, "schema_migrations"):
        connection.execute(
            """CREATE TABLE schema_migrations (
                   migration_id TEXT PRIMARY KEY NOT NULL,
                   applied_at TEXT NOT NULL
               )"""
        )
    if migration_id in _applied_migrations(connection):
        return
    if normalize_legacy_slots:
        connection.execute("DROP TRIGGER IF EXISTS trg_calendar_slot_assignment_immutable_while_booked")
        connection.execute("DROP TRIGGER IF EXISTS trg_calendar_slot_timestamp_update")
        _normalize_existing_slot_timestamps(connection)
    _execute_sql_script(connection, migration_sql)
    applied_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    execute(
        connection,
        "INSERT INTO schema_migrations (migration_id, applied_at) VALUES (?, ?)",
        (migration_id, applied_at),
    )


def _apply_calendar_resource_migration(
    connection: sqlite3.Connection,
    migration_sql: str | None = None,
) -> None:
    """Atomically add resource assignments to an existing operational database."""
    if migration_sql is None:
        migration_sql = _read_calendar_resource_migration()
    with transaction(connection):
        _apply_script_migration_in_transaction(
            connection,
            CALENDAR_RESOURCE_MIGRATION_ID,
            migration_sql,
            normalize_legacy_slots=True,
        )


def _normalize_existing_slot_timestamps(connection: sqlite3.Connection) -> None:
    """Canonicalize legacy slot instants before text-based overlap triggers rely on ordering."""
    rows = fetch_all(
        connection,
        "SELECT slot_id, starts_at, ends_at FROM calendar_slots",
        (),
    )
    for row in rows:
        normalized: list[str] = []
        for value in (row["starts_at"], row["ends_at"]):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("Legacy calendar slot timestamps must include a timezone")
            precision = "microseconds" if parsed.microsecond else "seconds"
            normalized.append(
                parsed.astimezone(timezone.utc)
                .isoformat(timespec=precision)
                .replace("+00:00", "Z")
            )
        execute(
            connection,
            "UPDATE calendar_slots SET starts_at = ?, ends_at = ? WHERE slot_id = ?",
            (normalized[0], normalized[1], row["slot_id"]),
        )
