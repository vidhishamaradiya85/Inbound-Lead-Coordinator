"""Tests for the local SQLite mock tools.

All database state in this module is isolated to pytest's temporary directory.
The tests intentionally include an overlapping-slot booking assertion; the
current implementation is expected to fail that test until overlap prevention
is implemented.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from tools.authorization import create_agent_context
from decimal import Decimal
import sqlite3

import pytest

from config.settings import AppSettings, DatabaseSettings, SafetySettings
from database.connection import (
    CALENDAR_BOOKING_GUARDS_MIGRATION_ID,
    CALENDAR_RESOURCE_MIGRATION_ID,
    _apply_calendar_resource_migration,
    initialize_database,
    open_connection,
)
from tools.calendar import MockCalendar
from tools.common import ActionResult, run_operation
from tools.crm import MockCRM
from tools.email import MockEmail
from tools.schemas import LeadCreateInput
from tools.sms import MockSMS


def db(tmp_path):
    """Open and initialize a fresh SQLite database for each test."""
    settings = DatabaseSettings(sqlite_path=tmp_path / "tools-test.sqlite3")
    connection = open_connection(settings)
    initialize_database(connection)
    try:
        yield connection
    finally:
        connection.close()


def settings():
    # Persistent controls are set separately in each test database. The
    # configured limit is deliberately generous unless a test overrides it.
    return AppSettings(
        safety=SafetySettings(
            max_tool_retries=2,
            tool_timeout_seconds=2.0,
            spending_limit_usd_per_run="10.00",
        )
    )


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


def _request(run_id="run-test-001", key="request-key-001", **values):
    return {"run_id": run_id, "idempotency_key": key, **values}


def _lead_input(lead_id="LEAD-001", **overrides):
    values = {
        "lead_id": lead_id,
        "source": "website",
        "name": "Avery Example",
        "email": "avery@example.test",
        "phone": "+1 202 555 0147",
        "raw_message": "Please schedule a heat pump inspection.",
        "service_requested": "heat pump inspection",
        "service_area_id": "DEMO-NORTH",
    }
    values.update(overrides)
    return values


def _create_lead(crm, lead_id="LEAD-001", key="create-lead-001", **overrides):
    result = crm.create_lead(_request(key=key, **_lead_input(lead_id, **overrides)))
    assert result.success, result.error
    return result.data


def _future_slot(
    db,
    slot_id,
    starts_at,
    ends_at,
    *,
    resource_id="MOCK-TECH-001",
    area="DEMO-NORTH",
    service="heat pump inspection",
):
    db.execute(
        """INSERT INTO calendar_slots
           (slot_id, service_area_id, service_requested, starts_at, ends_at, resource_id, is_active)
           VALUES (?, ?, ?, ?, ?, ?, 1)""",
        (slot_id, area, service, starts_at, ends_at, resource_id),
    )


def _future_times(offset_minutes=30, duration_minutes=30):
    start = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=offset_minutes)
    end = start + timedelta(minutes=duration_minutes)
    return (
        start.isoformat(timespec="seconds").replace("+00:00", "Z"),
        end.isoformat(timespec="seconds").replace("+00:00", "Z"),
    )


def test_database_initialization_and_repeat_initialization(db):
    expected = {
        "leads",
        "calendar_slots",
        "contact_preferences",
        "tool_operations",
        "appointments",
        "outbound_messages",
        "system_controls",
        "spending_ledger",
    }
    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert expected <= tables
    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM system_controls").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM calendar_slots").fetchone()[0] == 8
    assert db.execute("SELECT COUNT(*) FROM calendar_resources").fetchone()[0] == 2
    assert db.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (CALENDAR_RESOURCE_MIGRATION_ID,),
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (CALENDAR_BOOKING_GUARDS_MIGRATION_ID,),
    ).fetchone()[0] == 1

    initialize_database(db)
    assert db.execute("SELECT COUNT(*) FROM system_controls").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM calendar_slots").fetchone()[0] == 8
    assert db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 2


def test_default_kill_switch_blocks_create_without_creating_lead(db, settings):
    result = MockCRM(db, settings).create_lead(
        _request(key="blocked-create-001", **_lead_input())
    )
    assert not result.success
    assert result.error.code == "KILL_SWITCH_ACTIVE"
    assert db.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0


def test_enabling_kill_switch_allows_mock_write(enabled_tools):
    lead = _create_lead(enabled_tools["crm"])
    assert lead.lead_id == "LEAD-001"


def test_crm_create_retrieve_and_status_transitions(enabled_tools):
    crm = enabled_tools["crm"]
    created = _create_lead(crm)
    retrieved = crm.retrieve_lead(
        _request(key="retrieve-lead-001", lead_id="LEAD-001"),
        access_context=create_agent_context({"LEAD-001"}),
    )
    assert retrieved.success
    assert retrieved.data == created

    changed = crm.update_status(
        _request(
            key="status-change-001",
            lead_id="LEAD-001",
            expected_current_status="new",
            new_status="in_progress",
        ),
        access_context=create_agent_context({"LEAD-001"}),
    )
    assert changed.success
    assert changed.data.lead_status == "in_progress"

    qualified = crm.update_status(
        _request(
            key="status-change-002",
            lead_id="LEAD-001",
            expected_current_status="in_progress",
            new_status="qualified",
        ),
        access_context=create_agent_context({"LEAD-001"}),
    )
    assert qualified.success
    assert qualified.data.lead_status == "qualified"


@pytest.mark.parametrize(
    ("expected", "new", "error_code"),
    [
        ("new", "mock_booked", "INVALID_TRANSITION"),
        ("in_progress", "qualified", "CONFLICT"),
    ],
)
def test_crm_rejects_invalid_or_stale_status_changes(
    enabled_tools, expected, new, error_code
):
    crm = enabled_tools["crm"]
    _create_lead(crm)
    result = crm.update_status(
        _request(
            key=f"bad-transition-{expected}-{new}",
            lead_id="LEAD-001",
            expected_current_status=expected,
            new_status=new,
        ),
        access_context=create_agent_context({"LEAD-001"}),
    )
    assert not result.success
    assert result.error.code == error_code


def test_crm_duplicate_detection_normalizes_email_and_phone(enabled_tools):
    crm = enabled_tools["crm"]
    _create_lead(crm)
    _create_lead(
        crm,
        "LEAD-002",
        "create-lead-002",
        email=" AVERY@EXAMPLE.TEST ",
        phone="12025550147",
    )
    result = crm.detect_duplicates(
        _request(
            key="duplicate-check-001",
            lead_id="LEAD-002",
        ),
        access_context=create_agent_context({"LEAD-002"}),
    )
    assert result.success
    assert result.data.matches[0].lead_id == "LEAD-001"
    assert result.data.matches[0].matched_on == ["email", "phone"]


def test_calendar_availability_booking_and_same_slot_double_booking(
    db, enabled_tools
):
    calendar = enabled_tools["calendar"]
    crm = enabled_tools["crm"]
    _create_lead(crm)
    start, end = _future_times()
    _future_slot(db, "TEST-SLOT-001", start, end)

    availability = calendar.check_availability(
        _request(
            key="availability-001",
            service_area_id="DEMO-NORTH",
            service_requested="heat pump inspection",
            from_at=start,
            until_at=end,
        )
    )
    assert availability.success
    assert [slot.slot_id for slot in availability.data.slots] == ["TEST-SLOT-001"]

    booked = calendar.create_appointment(
        _request(key="book-slot-001", lead_id="LEAD-001", slot_id="TEST-SLOT-001")
    )
    assert booked.success
    assert booked.data.status == "booked"

    second = _create_lead(crm, "LEAD-002", "create-lead-002")
    assert second.lead_id == "LEAD-002"
    duplicate_booking = calendar.create_appointment(
        _request(key="book-slot-002", lead_id="LEAD-002", slot_id="TEST-SLOT-001")
    )
    assert not duplicate_booking.success
    assert duplicate_booking.error.code == "SLOT_UNAVAILABLE"
    assert db.execute(
        "SELECT COUNT(*) FROM appointments WHERE slot_id = 'TEST-SLOT-001' AND status = 'booked'"
    ).fetchone()[0] == 1


def test_calendar_rejects_overlapping_slots_for_same_resource(db, enabled_tools):
    crm = enabled_tools["crm"]
    calendar = enabled_tools["calendar"]
    _create_lead(crm)
    _create_lead(crm, "LEAD-002", "create-lead-002")
    start, end = _future_times(duration_minutes=60)
    overlap_start = (
        datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    overlap_end = (
        datetime.fromisoformat(end.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    _future_slot(db, "OVERLAP-SLOT-001", start, end, resource_id="MOCK-TECH-001")
    _future_slot(db, "OVERLAP-SLOT-002", overlap_start, overlap_end, resource_id="MOCK-TECH-001")

    first = calendar.create_appointment(
        _request(key="overlap-book-001", lead_id="LEAD-001", slot_id="OVERLAP-SLOT-001")
    )
    assert first.success
    now_unavailable = calendar.check_availability(
        _request(
            key="overlap-availability-001",
            service_area_id="DEMO-NORTH",
            service_requested="heat pump inspection",
            from_at=overlap_start,
            until_at=overlap_end,
        )
    )
    assert now_unavailable.success
    assert "OVERLAP-SLOT-002" not in [slot.slot_id for slot in now_unavailable.data.slots]
    second = calendar.create_appointment(
        _request(key="overlap-book-002", lead_id="LEAD-002", slot_id="OVERLAP-SLOT-002")
    )
    assert not second.success
    assert second.error.code == "SLOT_UNAVAILABLE"


def test_database_trigger_blocks_same_resource_overlap_without_tool_path(db, enabled_tools):
    _create_lead(enabled_tools["crm"])
    start, end = _future_times(duration_minutes=60)
    overlap_start = (
        datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    overlap_end = (
        datetime.fromisoformat(end.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    _future_slot(db, "TRIGGER-OVERLAP-001", start, end)
    _future_slot(db, "TRIGGER-OVERLAP-002", overlap_start, overlap_end)
    for operation_id, key in (("DIRECT-OP-001", "direct-key-001"), ("DIRECT-OP-002", "direct-key-002")):
        db.execute(
            """INSERT INTO tool_operations
               (operation_id, tool_name, operation_name, idempotency_key,
                request_hash, status, created_at)
               VALUES (?, 'direct', 'booking', ?, ?, 'started', ?)""",
            (operation_id, key, "c" * 64, start),
        )
    db.execute(
        """INSERT INTO appointments
           (appointment_id, lead_id, slot_id, resource_id, operation_id, status, created_at)
           VALUES ('DIRECT-APPT-001', 'LEAD-001', 'TRIGGER-OVERLAP-001',
                   'MOCK-TECH-001', 'DIRECT-OP-001', 'booked', ?)""",
        (start,),
    )
    with pytest.raises(sqlite3.IntegrityError, match="overlapping active appointment"):
        db.execute(
            """INSERT INTO appointments
               (appointment_id, lead_id, slot_id, resource_id, operation_id, status, created_at)
               VALUES ('DIRECT-APPT-002', 'LEAD-001', 'TRIGGER-OVERLAP-002',
                       'MOCK-TECH-001', 'DIRECT-OP-002', 'booked', ?)""",
            (start,),
        )


@pytest.mark.parametrize("violation", ["inactive_slot", "service_mismatch", "area_mismatch"])
def test_database_trigger_enforces_slot_and_lead_eligibility(db, enabled_tools, violation):
    _create_lead(enabled_tools["crm"])
    start, end = _future_times()
    area = "DEMO-NORTH"
    service = "heat pump inspection"
    resource_id = "MOCK-TECH-001"
    if violation == "inactive_slot":
        slot_id = "DIRECT-INACTIVE-SLOT"
        _future_slot(db, slot_id, start, end)
        db.execute("UPDATE calendar_slots SET is_active = 0 WHERE slot_id = ?", (slot_id,))
    elif violation == "service_mismatch":
        slot_id = "DIRECT-SERVICE-MISMATCH"
        service = "drain clearing"
        resource_id = "MOCK-TECH-002"  # This resource supports the slot service.
        _future_slot(db, slot_id, start, end, service=service, resource_id=resource_id)
    else:
        slot_id = "DIRECT-AREA-MISMATCH"
        area = "DEMO-SOUTH"
        _future_slot(db, slot_id, start, end, area=area)

    db.execute(
        """INSERT INTO tool_operations
           (operation_id, tool_name, operation_name, idempotency_key,
            request_hash, status, created_at)
           VALUES (?, 'direct', 'eligibility', ?, ?, 'started', ?)""",
        (f"ELIGIBILITY-OP-{violation}", f"eligibility-key-{violation}", "d" * 64, start),
    )
    with pytest.raises(sqlite3.IntegrityError, match="incompatible calendar booking"):
        db.execute(
            """INSERT INTO appointments
               (appointment_id, lead_id, slot_id, resource_id, operation_id, status, created_at)
               VALUES (?, 'LEAD-001', ?, ?, ?, 'booked', ?)""",
            (f"ELIGIBILITY-APPT-{violation}", slot_id, resource_id, f"ELIGIBILITY-OP-{violation}", start),
        )


def test_calendar_allows_overlapping_slots_for_different_resources(db, enabled_tools):
    crm = enabled_tools["crm"]
    calendar = enabled_tools["calendar"]
    _create_lead(crm)
    _create_lead(crm, "LEAD-002", "create-lead-002")
    start, end = _future_times(duration_minutes=60)
    overlap_start = (
        datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    overlap_end = (
        datetime.fromisoformat(end.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    _future_slot(db, "DIFFERENT-RESOURCE-001", start, end, resource_id="MOCK-TECH-001")
    _future_slot(db, "DIFFERENT-RESOURCE-002", overlap_start, overlap_end, resource_id="MOCK-TECH-002")

    first = calendar.create_appointment(
        _request(key="different-resource-001", lead_id="LEAD-001", slot_id="DIFFERENT-RESOURCE-001")
    )
    second = calendar.create_appointment(
        _request(key="different-resource-002", lead_id="LEAD-002", slot_id="DIFFERENT-RESOURCE-002")
    )
    assert first.success
    assert second.success


def test_calendar_allows_non_overlapping_slots_for_same_resource(db, enabled_tools):
    crm = enabled_tools["crm"]
    calendar = enabled_tools["calendar"]
    _create_lead(crm)
    _create_lead(crm, "LEAD-002", "create-lead-002")
    start, end = _future_times(duration_minutes=30)
    later_start = (
        datetime.fromisoformat(end.replace("Z", "+00:00")) + timedelta(minutes=15)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    later_end = (
        datetime.fromisoformat(later_start.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    _future_slot(db, "SAME-RESOURCE-NONOVERLAP-001", start, end)
    _future_slot(db, "SAME-RESOURCE-NONOVERLAP-002", later_start, later_end)
    first = calendar.create_appointment(
        _request(key="same-resource-nonoverlap-001", lead_id="LEAD-001", slot_id="SAME-RESOURCE-NONOVERLAP-001")
    )
    second = calendar.create_appointment(
        _request(key="same-resource-nonoverlap-002", lead_id="LEAD-002", slot_id="SAME-RESOURCE-NONOVERLAP-002")
    )
    assert first.success
    assert second.success


def test_unassigned_slot_is_not_bookable(db, enabled_tools):
    _create_lead(enabled_tools["crm"])
    start, end = _future_times()
    _future_slot(db, "UNASSIGNED-SLOT-001", start, end, resource_id=None)
    result = enabled_tools["calendar"].create_appointment(
        _request(key="unassigned-slot-001", lead_id="LEAD-001", slot_id="UNASSIGNED-SLOT-001")
    )
    assert not result.success
    assert result.error.code == "SLOT_UNAVAILABLE"


def test_database_rejects_noncanonical_slot_timestamps(db):
    with pytest.raises(sqlite3.IntegrityError):
        _future_slot(
            db,
            "BAD-TIMESTAMP-SLOT",
            "2027-99-99T99:99:99Z",
            "2028-01-01T00:00:00Z",
        )
    start, end = _future_times()
    _future_slot(db, "TIMESTAMP-UPDATE-SLOT", start, end)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "UPDATE calendar_slots SET starts_at = ? WHERE slot_id = ?",
            ("2027-01-01T10:00:00+00:00", "TIMESTAMP-UPDATE-SLOT"),
        )


def test_malformed_stored_slot_timestamp_returns_structured_error(db, enabled_tools):
    _create_lead(enabled_tools["crm"])
    start, end = _future_times()
    _future_slot(db, "MALFORMED-STORED-TIME", start, end)
    db.execute("DROP TRIGGER trg_calendar_slot_timestamp_update")
    db.execute("PRAGMA ignore_check_constraints = ON")
    db.execute(
        "UPDATE calendar_slots SET starts_at = ? WHERE slot_id = ?",
        ("2027-99-99T99:99:99Z", "MALFORMED-STORED-TIME"),
    )
    result = enabled_tools["calendar"].create_appointment(
        _request(key="malformed-stored-time-001", lead_id="LEAD-001", slot_id="MALFORMED-STORED-TIME")
    )
    assert not result.success
    assert result.error.code == "SLOT_UNAVAILABLE"
    assert "timestamp" in result.error.message.lower()


def test_availability_excludes_past_slots(db, enabled_tools):
    _create_lead(enabled_tools["crm"])
    _future_slot(
        db,
        "PAST-SLOT-001",
        "2000-01-01T10:00:00Z",
        "2000-01-01T10:30:00Z",
    )
    result = enabled_tools["calendar"].check_availability(
        _request(
            key="past-availability-001",
            service_area_id="DEMO-NORTH",
            service_requested="heat pump inspection",
            from_at="1999-12-31T00:00:00Z",
            until_at="2000-01-02T00:00:00Z",
        )
    )
    assert result.success
    assert "PAST-SLOT-001" not in [slot.slot_id for slot in result.data.slots]
    booking = enabled_tools["calendar"].create_appointment(
        _request(key="past-booking-001", lead_id="LEAD-001", slot_id="PAST-SLOT-001")
    )
    assert not booking.success
    assert booking.error.code == "SLOT_UNAVAILABLE"


def test_incompatible_service_is_not_bookable(db, enabled_tools):
    _create_lead(
        enabled_tools["crm"],
        service_requested="drain clearing",
        service_area_id="DEMO-NORTH",
    )
    start, end = _future_times()
    _future_slot(
        db,
        "INCOMPATIBLE-SLOT-001",
        start,
        end,
        service="drain clearing",
        resource_id="MOCK-TECH-001",
    )
    result = enabled_tools["calendar"].create_appointment(
        _request(key="incompatible-service-001", lead_id="LEAD-001", slot_id="INCOMPATIBLE-SLOT-001")
    )
    assert not result.success
    assert result.error.code == "SLOT_UNAVAILABLE"


@pytest.mark.parametrize(
    "column",
    ["resource_id", "starts_at", "ends_at", "service_requested", "service_area_id", "is_active"],
)
def test_active_booking_prevents_changing_slot_assignment_or_details(db, enabled_tools, column):
    _create_lead(enabled_tools["crm"])
    start, end = _future_times()
    _future_slot(db, "IMMUTABLE-SLOT-001", start, end)
    booked = enabled_tools["calendar"].create_appointment(
        _request(key="immutable-booking-001", lead_id="LEAD-001", slot_id="IMMUTABLE-SLOT-001")
    )
    assert booked.success
    updates = {
        "resource_id": "MOCK-TECH-002",
        "starts_at": "2027-02-01T10:00:00Z",
        "ends_at": "2027-02-01T10:30:00Z",
        "service_requested": "drain clearing",
        "service_area_id": "DEMO-SOUTH",
        "is_active": 0,
    }
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            f"UPDATE calendar_slots SET {column} = ? WHERE slot_id = ?",
            (updates[column], "IMMUTABLE-SLOT-001"),
        )


@pytest.mark.parametrize("channel", ["sms", "email"])
def test_message_simulation_requires_channel_specific_consent(
    db, enabled_tools, channel
):
    crm = enabled_tools["crm"]
    _create_lead(crm)
    db.execute(
        "UPDATE contact_preferences SET sms_allowed = ?, email_allowed = ? WHERE lead_id = ?",
        (1 if channel == "sms" else 0, 1 if channel == "email" else 0, "LEAD-001"),
    )
    if channel == "sms":
        result = enabled_tools["sms"].simulate_send(
            _request(
                key="sms-send-001",
                lead_id="LEAD-001",
                purpose="estimate_confirmation",
                body="Your estimate request is confirmed.",
            )
        )
    else:
        result = enabled_tools["email"].simulate_send(
            _request(
                key="email-send-001",
                lead_id="LEAD-001",
                purpose="estimate_confirmation",
                subject="Estimate request received",
                body="Your estimate request is confirmed.",
            )
        )
    assert result.success
    assert result.data.channel == channel
    assert result.data.status == "simulated"
    assert db.execute("SELECT COUNT(*) FROM outbound_messages").fetchone()[0] == 1


@pytest.mark.parametrize("channel", ["sms", "email"])
def test_consent_does_not_cross_channels(db, enabled_tools, channel):
    crm = enabled_tools["crm"]
    _create_lead(crm)
    if channel == "sms":
        db.execute("UPDATE contact_preferences SET email_allowed = 1 WHERE lead_id = 'LEAD-001'")
        result = enabled_tools["sms"].simulate_send(
            _request(key="sms-no-consent-001", lead_id="LEAD-001", purpose="lead_follow_up_1", body="Checking in.")
        )
    else:
        db.execute("UPDATE contact_preferences SET sms_allowed = 1 WHERE lead_id = 'LEAD-001'")
        result = enabled_tools["email"].simulate_send(
            _request(key="email-no-consent-001", lead_id="LEAD-001", purpose="lead_follow_up_1", subject="Checking in", body="Checking in.")
        )
    assert not result.success
    assert result.error.code == "CONSENT_REQUIRED"
    assert db.execute("SELECT COUNT(*) FROM outbound_messages").fetchone()[0] == 0


@pytest.mark.parametrize("channel", ["sms", "email"])
def test_opt_out_blocks_message_even_when_channel_consent_is_enabled(
    db, enabled_tools, channel
):
    _create_lead(enabled_tools["crm"])
    db.execute(
        "UPDATE contact_preferences SET sms_allowed = 1, email_allowed = 1, "
        "opted_out_at = '2026-01-01T00:00:00Z' WHERE lead_id = 'LEAD-001'"
    )
    if channel == "sms":
        result = enabled_tools["sms"].simulate_send(
            _request(key="sms-optout-001", lead_id="LEAD-001", purpose="lead_follow_up_1", body="Checking in.")
        )
    else:
        result = enabled_tools["email"].simulate_send(
            _request(key="email-optout-001", lead_id="LEAD-001", purpose="lead_follow_up_1", subject="Checking in", body="Checking in.")
        )
    assert not result.success
    assert result.error.code == "CONSENT_REQUIRED"
    assert db.execute("SELECT COUNT(*) FROM outbound_messages").fetchone()[0] == 0


def test_idempotent_create_replays_and_conflicting_key_is_rejected(enabled_tools):
    crm = enabled_tools["crm"]
    payload = _request(key="stable-create-001", **_lead_input())
    first = crm.create_lead(payload)
    replay = crm.create_lead(payload)
    assert first.success and replay.success
    assert replay.replayed
    assert replay.operation_id == first.operation_id
    assert replay.data == first.data

    changed = dict(payload, raw_message="A different request under the same key.")
    conflict = crm.create_lead(changed)
    assert not conflict.success
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"
    assert conflict.replayed
    assert enabled_tools["crm"].connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1


def test_message_logical_action_cannot_be_repeated_with_new_idempotency_key(
    db, enabled_tools
):
    _create_lead(enabled_tools["crm"])
    db.execute("UPDATE contact_preferences SET sms_allowed = 1 WHERE lead_id = 'LEAD-001'")
    sms = enabled_tools["sms"]
    first = sms.simulate_send(
        _request(key="sms-logical-001", lead_id="LEAD-001", purpose="lead_follow_up_1", body="First copy.")
    )
    second = sms.simulate_send(
        _request(key="sms-logical-002", lead_id="LEAD-001", purpose="lead_follow_up_1", body="Second copy.")
    )
    assert first.success
    assert not second.success
    assert second.error.code == "DUPLICATE_ACTION"
    assert db.execute("SELECT COUNT(*) FROM outbound_messages").fetchone()[0] == 1


def test_run_operation_enforces_spending_limit_before_action(db, settings):
    db.execute(
        "UPDATE system_controls SET kill_switch_active = 0, "
        "spending_limit_micros = 1000000 WHERE control_id = 1"
    )
    limited_settings = settings.model_copy(
        update={
            "safety": settings.safety.model_copy(
                update={"spending_limit_usd_per_run": Decimal("1.00")}
            )
        }
    )
    request = LeadCreateInput.model_validate(
        _request(key="spend-limit-001", **_lead_input())
    )
    called = False

    def action(connection, operation_id):
        nonlocal called
        called = True
        return ActionResult({"ok": True}, None)

    outcome = run_operation(
        db,
        request,
        tool_name="test",
        operation_name="costed_action",
        mutating=True,
        action=action,
        replay=lambda connection, resource_id: {"ok": True},
        settings=limited_settings,
        estimated_cost_micros=1000001,
    )
    assert not outcome.success
    assert outcome.error.code == "SPENDING_LIMIT_EXCEEDED"
    assert not called
    assert db.execute("SELECT COUNT(*) FROM spending_ledger").fetchone()[0] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        _request(key="invalid-source-001", **_lead_input(source="unknown")),
        _request(key="invalid-blank-001", **_lead_input(raw_message="  ")),
        _request(key="invalid-extra-001", **_lead_input(unexpected="field")),
    ],
)
def test_crm_validation_errors_are_structured_and_do_not_mutate(enabled_tools, db, payload):
    result = enabled_tools["crm"].create_lead(payload)
    assert not result.success
    assert result.error.code == "VALIDATION_ERROR"
    assert not result.error.retryable
    assert result.data is None
    assert db.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0


def test_transient_lock_retries_are_bounded(db, settings, monkeypatch):
    settings = settings.model_copy(
        update={"safety": settings.safety.model_copy(update={"max_tool_retries": 2, "tool_timeout_seconds": 10.0})}
    )
    db.execute("UPDATE system_controls SET kill_switch_active = 0 WHERE control_id = 1")
    request = LeadCreateInput.model_validate(_request(key="retry-test-001", **_lead_input()))
    calls = 0

    def action(connection, operation_id):
        nonlocal calls
        calls += 1
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("tools.common.time.monotonic", lambda: 0.0)
    monkeypatch.setattr("tools.common.time.sleep", lambda delay: None)
    monkeypatch.setattr("tools.common.random.uniform", lambda low, high: 0.0)
    outcome = run_operation(
        db,
        request,
        tool_name="test",
        operation_name="retry_action",
        mutating=True,
        action=action,
        replay=lambda connection, resource_id: None,
        settings=settings,
    )
    assert not outcome.success
    assert outcome.error.code == "RETRY_EXHAUSTED"
    assert outcome.error.retryable
    assert calls == 3  # Initial attempt plus two configured retries.


def test_transient_lock_obeys_operation_deadline(db, settings, monkeypatch):
    db.execute("UPDATE system_controls SET kill_switch_active = 0 WHERE control_id = 1")
    request = LeadCreateInput.model_validate(_request(key="timeout-test-001", **_lead_input()))

    def action(connection, operation_id):
        raise sqlite3.OperationalError("database is busy")

    times = iter([0.0, 2.0])
    monkeypatch.setattr("tools.common.time.monotonic", lambda: next(times))
    outcome = run_operation(
        db,
        request,
        tool_name="test",
        operation_name="timeout_action",
        mutating=True,
        action=action,
        replay=lambda connection, resource_id: None,
        settings=settings,
    )
    assert not outcome.success
    assert outcome.error.code == "TIMEOUT"
    assert outcome.error.retryable


def test_operational_schema_excludes_evaluator_tables(db):
    tables = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "evaluation_cases" not in tables
    assert "evaluation_labels" not in tables
    assert not any(name.startswith("evaluator_") for name in tables)


def _legacy_database(tmp_path):
    """Build a small pre-resource database matching the previous calendar shape."""
    connection = open_connection(
        DatabaseSettings(sqlite_path=tmp_path / "legacy-tools.sqlite3")
    )
    connection.executescript(
        """CREATE TABLE leads (
               lead_id TEXT PRIMARY KEY NOT NULL,
               source TEXT NOT NULL,
               name TEXT,
               email TEXT,
               phone TEXT,
               raw_message TEXT NOT NULL,
               service_requested TEXT,
               address_text TEXT,
               service_area_id TEXT,
               created_at TEXT NOT NULL,
               lead_status TEXT NOT NULL DEFAULT 'new',
               qualification_status TEXT NOT NULL DEFAULT 'not_evaluated',
               qualification_score REAL,
               qualification_reason TEXT,
               service_area_eligible INTEGER,
               detected_risk_flags_json TEXT NOT NULL DEFAULT '[]',
               escalation_reason TEXT,
               detected_duplicate_of_lead_id TEXT REFERENCES leads(lead_id)
           );
           CREATE TABLE calendar_slots (
               slot_id TEXT PRIMARY KEY NOT NULL,
               service_area_id TEXT NOT NULL,
               service_requested TEXT NOT NULL,
               starts_at TEXT NOT NULL,
               ends_at TEXT NOT NULL,
               is_active INTEGER NOT NULL DEFAULT 1,
               UNIQUE (service_area_id, service_requested, starts_at)
           );
           CREATE TABLE tool_operations (
               operation_id TEXT PRIMARY KEY NOT NULL,
               tool_name TEXT NOT NULL,
               operation_name TEXT NOT NULL,
               idempotency_key TEXT NOT NULL,
               request_hash TEXT NOT NULL,
               status TEXT NOT NULL,
               result_code TEXT,
               resource_id TEXT,
               created_at TEXT NOT NULL,
               completed_at TEXT,
               UNIQUE (tool_name, operation_name, idempotency_key)
           );
           CREATE TABLE appointments (
               appointment_id TEXT PRIMARY KEY NOT NULL,
               lead_id TEXT NOT NULL REFERENCES leads(lead_id),
               slot_id TEXT NOT NULL REFERENCES calendar_slots(slot_id),
               operation_id TEXT NOT NULL UNIQUE REFERENCES tool_operations(operation_id),
               status TEXT NOT NULL DEFAULT 'booked',
               created_at TEXT NOT NULL,
               cancelled_at TEXT
           );"""
    )
    return connection


def test_existing_database_migrates_and_flags_unknown_active_booking(tmp_path):
    connection = _legacy_database(tmp_path)
    start, end = _future_times(duration_minutes=60)
    connection.execute(
        """INSERT INTO leads (lead_id, source, raw_message, service_requested,
           service_area_id, created_at) VALUES ('LEGACY-LEAD', 'website', 'Legacy request',
           'heat pump inspection', 'DEMO-NORTH', ?)""",
        (start,),
    )
    connection.execute(
        """INSERT INTO calendar_slots
           (slot_id, service_area_id, service_requested, starts_at, ends_at)
           VALUES ('LEGACY-SLOT', 'DEMO-NORTH', 'heat pump inspection', ?, ?)""",
        (start, end),
    )
    connection.execute(
        """INSERT INTO tool_operations
           (operation_id, tool_name, operation_name, idempotency_key,
            request_hash, status, created_at)
           VALUES ('LEGACY-OP', 'calendar', 'create_appointment',
                   'legacy-key-001', ?, 'succeeded', ?)""",
        ("b" * 64, start),
    )
    connection.execute(
        """INSERT INTO appointments
           (appointment_id, lead_id, slot_id, operation_id, status, created_at)
           VALUES ('LEGACY-APPT', 'LEGACY-LEAD', 'LEGACY-SLOT', 'LEGACY-OP', 'booked', ?)""",
        (start,),
    )

    initialize_database(connection)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(calendar_slots)")}
    appointment_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(appointments)")
    }
    assert "resource_id" in columns
    assert "resource_id" in appointment_columns
    assert connection.execute(
        "SELECT resource_id FROM appointments WHERE appointment_id = 'LEGACY-APPT'"
    ).fetchone()[0] is None
    flag = connection.execute(
        "SELECT reason FROM calendar_reconciliation_flags "
        "WHERE entity_type = 'appointment' AND entity_id = 'LEGACY-APPT'"
    ).fetchone()
    assert flag is not None
    assert "unknown" in flag[0].lower()
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.execute(
        "UPDATE system_controls SET kill_switch_active = 0, spending_limit_micros = 10000000 WHERE control_id = 1"
    )

    crm = MockCRM(connection, AppSettings())
    created = crm.create_lead(
        _request(
            key="new-after-migration-001",
            **_lead_input("NEW-LEAD", raw_message="Another heat pump inspection request."),
        )
    )
    assert created.success
    overlap_start = (
        datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(minutes=15)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    overlap_end = (
        datetime.fromisoformat(overlap_start.replace("Z", "+00:00")) + timedelta(minutes=30)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    _future_slot(connection, "POST-MIGRATION-OVERLAP", overlap_start, overlap_end)
    result = MockCalendar(connection, AppSettings()).create_appointment(
        _request(
            key="post-migration-overlap-001",
            lead_id="NEW-LEAD",
            slot_id="POST-MIGRATION-OVERLAP",
        )
    )
    assert not result.success
    assert result.error.code == "SLOT_UNAVAILABLE"
    connection.close()


def test_existing_database_migration_is_repeatable(tmp_path):
    connection = _legacy_database(tmp_path)
    initialize_database(connection)
    initialize_database(connection)
    assert connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (CALENDAR_RESOURCE_MIGRATION_ID,),
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE migration_id = ?",
        (CALENDAR_BOOKING_GUARDS_MIGRATION_ID,),
    ).fetchone()[0] == 1
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()


@pytest.mark.parametrize("partial_state", ["slot_column", "appointment_column", "version_only", "columns_without_version"])
def test_partial_resource_migration_state_fails_closed(tmp_path, partial_state):
    connection = _legacy_database(tmp_path)
    if partial_state in {"slot_column", "columns_without_version"}:
        connection.execute("ALTER TABLE calendar_slots ADD COLUMN resource_id TEXT")
    if partial_state in {"appointment_column", "columns_without_version"}:
        connection.execute("ALTER TABLE appointments ADD COLUMN resource_id TEXT")
    if partial_state == "version_only":
        connection.execute("CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        connection.execute(
            "INSERT INTO schema_migrations (migration_id, applied_at) VALUES (?, '2026-01-01T00:00:00Z')",
            (CALENDAR_RESOURCE_MIGRATION_ID,),
        )
    with pytest.raises(RuntimeError, match="inconsistent|incomplete"):
        initialize_database(connection)
    connection.close()


def test_full_initialization_failure_rolls_back_migration_and_schema(tmp_path, monkeypatch):
    connection = _legacy_database(tmp_path)
    monkeypatch.setattr(
        "database.connection._read_runtime_schema",
        lambda: """CREATE TABLE transient_schema_step (id INTEGER);
THIS IS INVALID SQL;
""",
    )
    with pytest.raises(sqlite3.OperationalError):
        initialize_database(connection)

    slot_columns = {row["name"] for row in connection.execute("PRAGMA table_info(calendar_slots)")}
    appointment_columns = {
        row["name"] for row in connection.execute("PRAGMA table_info(appointments)")
    }
    assert "resource_id" not in slot_columns
    assert "resource_id" not in appointment_columns
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'calendar_resources'"
    ).fetchone() is None
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'transient_schema_step'"
    ).fetchone() is None
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone() is None
    connection.close()


def test_calendar_resource_migration_failure_rolls_back_all_ddl(tmp_path):
    connection = _legacy_database(tmp_path)
    with pytest.raises(sqlite3.OperationalError):
        _apply_calendar_resource_migration(
            connection,
            """CREATE TABLE migration_probe (id INTEGER);
               ALTER TABLE calendar_slots ADD COLUMN resource_id TEXT;
               THIS IS INVALID SQL;""",
        )
    slot_columns = {row["name"] for row in connection.execute("PRAGMA table_info(calendar_slots)")}
    assert "resource_id" not in slot_columns
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'migration_probe'"
    ).fetchone() is None
    assert connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone() is None
    connection.close()

