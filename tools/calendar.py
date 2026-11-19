"""Local SQLite mock calendar operations."""

from collections.abc import Mapping
from datetime import datetime, timezone
import sqlite3
from typing import Any
from uuid import uuid4

from database.connection import execute, fetch_all, fetch_one
from tools.common import ActionResult, ToolBase, ToolFailure, utc_now
from tools.schemas import (
    AppointmentCreateInput,
    AppointmentView,
    CalendarAvailabilityInput,
    CalendarAvailabilityOutput,
    CalendarSlotView,
    ToolResult,
)


def _as_utc_iso(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_canonical_utc(value: str) -> datetime:
    """Parse only the fixed-width UTC form used by overlap comparisons."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ToolFailure("SLOT_UNAVAILABLE", "Stored calendar slot has an invalid timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ToolFailure("SLOT_UNAVAILABLE", "Stored calendar slot timestamp is not timezone-aware.")
    canonical = parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    if value != canonical:
        raise ToolFailure("SLOT_UNAVAILABLE", "Stored calendar slot timestamp is not canonical UTC.")
    return parsed.astimezone(timezone.utc)


def _availability(
    connection: sqlite3.Connection,
    request: CalendarAvailabilityInput,
) -> dict[str, Any]:
    rows = fetch_all(
        connection,
        """
        SELECT s.slot_id, s.resource_id, s.service_area_id, s.service_requested,
               s.starts_at, s.ends_at
        FROM calendar_slots AS s
        JOIN calendar_resources AS r
          ON r.resource_id = s.resource_id AND r.is_active = 1
        JOIN calendar_resource_services AS rs
          ON rs.resource_id = s.resource_id
         AND rs.service_requested = s.service_requested
        LEFT JOIN appointments AS a
            ON a.slot_id = s.slot_id AND a.status = 'booked'
        WHERE s.service_area_id = ?
          AND s.service_requested = ?
          AND s.is_active = 1
          AND s.starts_at >= ?
          AND s.ends_at <= ?
          AND s.starts_at > ?
          AND a.appointment_id IS NULL
          AND NOT EXISTS (
              SELECT 1
              FROM appointments AS active_appointment
              JOIN calendar_slots AS booked_slot
                ON booked_slot.slot_id = active_appointment.slot_id
              WHERE active_appointment.status = 'booked'
                AND (
                    active_appointment.resource_id IS NULL
                    OR active_appointment.resource_id = s.resource_id
                )
                AND s.starts_at < booked_slot.ends_at
                AND booked_slot.starts_at < s.ends_at
          )
        ORDER BY s.starts_at, s.slot_id
        """,
        (
            request.service_area_id,
            request.service_requested,
            _as_utc_iso(request.from_at),
            _as_utc_iso(request.until_at),
            utc_now(),
        ),
    )
    for row in rows:
        starts_at = _parse_canonical_utc(row["starts_at"])
        ends_at = _parse_canonical_utc(row["ends_at"])
        if ends_at <= starts_at:
            raise ToolFailure("SLOT_UNAVAILABLE", "Stored calendar slot has an invalid time range.")
    return {
        "slots": [
            {
                "slot_id": row["slot_id"],
                "resource_id": row["resource_id"],
                "service_area_id": row["service_area_id"],
                "service_requested": row["service_requested"],
                "starts_at": row["starts_at"],
                "ends_at": row["ends_at"],
            }
            for row in rows
        ]
    }


def _appointment(connection: sqlite3.Connection, appointment_id: str) -> dict[str, Any]:
    row = fetch_one(
        connection,
        """
        SELECT appointment_id, lead_id, slot_id, resource_id, status, created_at, cancelled_at
        FROM appointments
        WHERE appointment_id = ?
        """,
        (appointment_id,),
    )
    if row is None:
        raise ToolFailure("NOT_FOUND", "Appointment was not found.")
    return {
        "appointment_id": row["appointment_id"],
        "lead_id": row["lead_id"],
        "slot_id": row["slot_id"],
        "resource_id": row["resource_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "cancelled_at": row["cancelled_at"],
    }


class MockCalendar(ToolBase):
    tool_name = "calendar"

    def check_availability(
        self,
        raw_input: CalendarAvailabilityInput | Mapping[str, Any],
    ) -> ToolResult[CalendarAvailabilityOutput]:
        request, invalid = self.parse(CalendarAvailabilityInput, raw_input)
        if invalid is not None:
            return self.result(invalid, CalendarAvailabilityOutput)
        assert request is not None

        def action(connection: sqlite3.Connection, operation_id: str) -> ActionResult:
            return ActionResult(_availability(connection, request), None)

        def replay(connection: sqlite3.Connection, resource_id: str | None) -> Any:
            return _availability(connection, request)

        outcome = self.execute(
            request,
            operation_name="check_availability",
            mutating=False,
            action=action,
            replay=replay,
        )
        return self.result(outcome, CalendarAvailabilityOutput)

    def create_appointment(
        self,
        raw_input: AppointmentCreateInput | Mapping[str, Any],
    ) -> ToolResult[AppointmentView]:
        request, invalid = self.parse(AppointmentCreateInput, raw_input)
        if invalid is not None:
            return self.result(invalid, AppointmentView)
        assert request is not None
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        appointment_id = str(uuid4())

        def action(connection: sqlite3.Connection, operation_id: str) -> ActionResult:
            lead = fetch_one(
                connection,
                "SELECT service_area_id, service_requested FROM leads WHERE lead_id = ?",
                (request.lead_id,),
            )
            if lead is None:
                raise ToolFailure("NOT_FOUND", "Lead was not found.")
            slot = fetch_one(
                connection,
                """
                SELECT service_area_id, service_requested, starts_at, ends_at,
                       resource_id, is_active
                FROM calendar_slots
                WHERE slot_id = ?
                """,
                (request.slot_id,),
            )
            if slot is None or slot["is_active"] != 1:
                raise ToolFailure("SLOT_UNAVAILABLE", "The requested mock slot is unavailable.")
            if (
                lead["service_area_id"] != slot["service_area_id"]
                or lead["service_requested"] != slot["service_requested"]
            ):
                raise ToolFailure("SLOT_UNAVAILABLE", "The mock slot does not match this lead's service and area.")
            if slot["resource_id"] is None:
                raise ToolFailure("SLOT_UNAVAILABLE", "The mock slot has no assigned technician/resource.")
            resource = fetch_one(
                connection,
                """SELECT r.is_active
                   FROM calendar_resources AS r
                   JOIN calendar_resource_services AS rs
                     ON rs.resource_id = r.resource_id
                    AND rs.service_requested = ?
                   WHERE r.resource_id = ?""",
                (slot["service_requested"], slot["resource_id"]),
            )
            if resource is None or resource["is_active"] != 1:
                raise ToolFailure(
                    "SLOT_UNAVAILABLE",
                    "The assigned technician/resource is inactive or incompatible with this service.",
                )
            try:
                starts_at = _parse_canonical_utc(slot["starts_at"])
                ends_at = _parse_canonical_utc(slot["ends_at"])
            except ToolFailure:
                raise
            if ends_at <= starts_at:
                raise ToolFailure("SLOT_UNAVAILABLE", "The stored mock slot has an invalid time range.")
            if starts_at <= datetime.now(timezone.utc):
                raise ToolFailure("SLOT_UNAVAILABLE", "The requested mock slot is no longer in the future.")
            overlaps = fetch_all(
                connection,
                """SELECT a.appointment_id, a.resource_id
                   FROM appointments AS a
                   JOIN calendar_slots AS existing_slot ON existing_slot.slot_id = a.slot_id
                   WHERE a.status = 'booked'
                     AND (a.resource_id IS NULL OR a.resource_id = ?)
                     AND ? < existing_slot.ends_at
                     AND existing_slot.starts_at < ?""",
                (slot["resource_id"], slot["ends_at"], slot["starts_at"]),
            )
            if overlaps:
                now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                for existing in overlaps:
                    if existing["resource_id"] is None:
                        execute(
                            connection,
                            """INSERT OR IGNORE INTO calendar_reconciliation_flags
                               (entity_type, entity_id, reason, created_at)
                               VALUES ('appointment', ?, ?, ?)""",
                            (
                                existing["appointment_id"],
                                "Legacy active appointment with unknown resource overlaps a requested booking",
                                now,
                            ),
                        )
                raise ToolFailure(
                    "SLOT_UNAVAILABLE",
                    "The requested mock slot overlaps an active appointment for this resource or an unreconciled legacy booking.",
                )
            try:
                execute(
                    connection,
                    """
                    INSERT INTO appointments (
                        appointment_id, lead_id, slot_id, resource_id, operation_id, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'booked', ?)
                    """,
                    (
                        appointment_id,
                        request.lead_id,
                        request.slot_id,
                        slot["resource_id"],
                        operation_id,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError as error:
                database_message = str(error)
                if database_message == "overlapping active appointment":
                    raise ToolFailure(
                        "SLOT_UNAVAILABLE",
                        "The requested mock slot overlaps an active appointment for this resource.",
                    ) from error
                if database_message == "UNIQUE constraint failed: appointments.slot_id":
                    raise ToolFailure(
                        "SLOT_UNAVAILABLE",
                        "The requested mock slot is already booked.",
                    ) from error
                raise
            return ActionResult(_appointment(connection, appointment_id), appointment_id)

        def replay(connection: sqlite3.Connection, resource_id: str | None) -> Any:
            if resource_id is None:
                raise ToolFailure("DATABASE_ERROR", "Stored appointment reference is unavailable.")
            return _appointment(connection, resource_id)

        outcome = self.execute(
            request,
            operation_name="create_appointment",
            mutating=True,
            action=action,
            replay=replay,
        )
        return self.result(outcome, AppointmentView)

