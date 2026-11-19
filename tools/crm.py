"""Local SQLite mock CRM operations."""

import json
import re
import sqlite3
from collections.abc import Mapping
from typing import Any
from tools.authorization import CRMAccessContext

from database.connection import execute, fetch_all, fetch_one
from tools.common import ActionResult, ToolBase, ToolFailure, OperationOutcome
from tools.schemas import (
    DuplicateCandidate,
    DuplicateDetectionInput,
    DuplicateDetectionOutput,
    LeadCreateInput,
    LeadGetInput,
    LeadID,
    LeadSource,
    LeadStatus,
    LeadStatusUpdateInput,
    LeadView,
    ToolRequest,
    ToolResult,
)


def _lead_view(row: sqlite3.Row) -> dict[str, Any]:
    risk_flags = json.loads(row["detected_risk_flags_json"])
    return {
        "lead_id": row["lead_id"],
        "source": row["source"],
        "name": row["name"],
        "email": row["email"],
        "phone": row["phone"],
        "raw_message": row["raw_message"],
        "service_requested": row["service_requested"],
        "address_text": row["address_text"],
        "service_area_id": row["service_area_id"],
        "created_at": row["created_at"],
        "lead_status": row["lead_status"],
        "qualification_status": row["qualification_status"],
        "qualification_score": row["qualification_score"],
        "qualification_reason": row["qualification_reason"],
        "service_area_eligible": (
            None if row["service_area_eligible"] is None else bool(row["service_area_eligible"])
        ),
        "detected_risk_flags_json": risk_flags,
        "escalation_reason": row["escalation_reason"],
        "detected_duplicate_of_lead_id": row["detected_duplicate_of_lead_id"],
    }


def _get_lead(connection: sqlite3.Connection, lead_id: str) -> dict[str, Any]:
    row = fetch_one(
        connection,
        "SELECT * FROM leads WHERE lead_id = ?",
        (lead_id,),
    )
    if row is None:
        raise ToolFailure("NOT_FOUND", "Lead was not found.")
    return _lead_view(row)


def _normalize_email(value: str | None) -> str | None:
    return value.strip().casefold() if value and value.strip() else None


def _normalize_phone(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return digits or None


def _find_duplicates(
    connection: sqlite3.Connection,
    *,
    exclude_lead_id: str | None,
    email: str | None,
    phone: str | None,
) -> dict[str, Any]:
    normalized_email = _normalize_email(email)
    normalized_phone = _normalize_phone(phone)
    rows = fetch_all(
        connection,
        """
        SELECT lead_id, email, phone
        FROM leads
        WHERE (? IS NULL OR lead_id <> ?)
        """,
        (exclude_lead_id, exclude_lead_id),
    )
    matches: list[dict[str, Any]] = []
    for row in rows:
        fields: list[str] = []
        if normalized_email and normalized_email == _normalize_email(row["email"]):
            fields.append("email")
        if normalized_phone and normalized_phone == _normalize_phone(row["phone"]):
            fields.append("phone")
        if fields:
            matches.append({"lead_id": row["lead_id"], "matched_on": fields})
    matches.sort(key=lambda match: match["lead_id"])
    return {"matches": matches}


_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "new": {"in_progress", "qualified", "rejected", "duplicate", "escalated", "needs_info"},
    "in_progress": {"qualified", "rejected", "duplicate", "escalated", "needs_info"},
    "needs_info": {"in_progress", "qualified", "rejected", "escalated"},
    "qualified": {"mock_booked", "escalated"},
    "mock_booked": {"escalated"},
    "rejected": set(),
    "duplicate": set(),
    "escalated": set(),
}


class MockCRM(ToolBase):
    tool_name = "crm"

    def create_lead(
        self,
        raw_input: LeadCreateInput | Mapping[str, Any],
    ) -> ToolResult[LeadView]:
        request, invalid = self.parse(LeadCreateInput, raw_input)
        if invalid is not None:
            return self.result(invalid, LeadView)
        assert request is not None

        from tools.common import utc_now

        created_at = utc_now()

        def action(connection: sqlite3.Connection, operation_id: str) -> ActionResult:
            execute(
                connection,
                """
                INSERT INTO leads (
                    lead_id, source, name, email, phone, raw_message,
                    service_requested, address_text, service_area_id, created_at,
                    lead_status, qualification_status, detected_risk_flags_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', 'not_evaluated', '[]')
                """,
                (
                    request.lead_id,
                    request.source,
                    request.name,
                    request.email,
                    request.phone,
                    request.raw_message,
                    request.service_requested,
                    request.address_text,
                    request.service_area_id,
                    created_at,
                ),
            )
            execute(
                connection,
                """
                INSERT OR IGNORE INTO contact_preferences (
                    lead_id, sms_allowed, email_allowed, updated_at
                ) VALUES (?, 0, 0, ?)
                """,
                (request.lead_id, created_at),
            )
            return ActionResult(_get_lead(connection, request.lead_id), request.lead_id)

        def replay(connection: sqlite3.Connection, resource_id: str | None) -> Any:
            if resource_id is None:
                raise ToolFailure("DATABASE_ERROR", "Stored operation reference is unavailable.")
            return _get_lead(connection, resource_id)

        outcome = self.execute(
            request,
            operation_name="create_lead",
            mutating=True,
            action=action,
            replay=replay,
        )
        return self.result(outcome, LeadView)

    def retrieve_lead(
        self,
        raw_input: LeadGetInput | Mapping[str, Any],
        *,
        access_context: CRMAccessContext | None = None,
    ) -> ToolResult[LeadView]:
        request, invalid = self.parse(LeadGetInput, raw_input)

        if invalid is not None:
            return self.result(invalid, LeadView)

        assert request is not None

        def authorize(lead_id: str) -> None:
            if access_context is None or not access_context.can_read_lead(lead_id):
                raise ToolFailure(
                    "FORBIDDEN",
                    "You are not authorized to access this lead.",
                )

        def action(connection: sqlite3.Connection, operation_id: str) -> ActionResult:
            authorize(request.lead_id)
            return ActionResult(
                _get_lead(connection, request.lead_id),
                request.lead_id,
            )

        def replay(connection: sqlite3.Connection, resource_id: str | None) -> Any:
            if resource_id is None:
                raise ToolFailure(
                    "DATABASE_ERROR",
                    "Stored operation reference is unavailable.",
                )

            authorize(resource_id)
            return _get_lead(connection, resource_id)

        outcome = self.execute(
            request,
            operation_name="retrieve_lead",
            mutating=False,
            action=action,
            replay=replay,
        )

        return self.result(outcome, LeadView)

    
    def update_status(
        self,
        raw_input: LeadStatusUpdateInput | Mapping[str, Any],
        *,
        access_context: CRMAccessContext | None = None,
    ) -> ToolResult[LeadView]:
        request, invalid = self.parse(LeadStatusUpdateInput, raw_input)

        if invalid is not None:
            return self.result(invalid, LeadView)

        assert request is not None

        def authorize(lead_id: str) -> None:
            if access_context is None or not access_context.can_read_lead(lead_id):
                raise ToolFailure(
                    "FORBIDDEN",
                    "You are not authorized to modify this lead.",
                )

        def action(connection: sqlite3.Connection, operation_id: str) -> ActionResult:
            authorize(request.lead_id)

            current = fetch_one(
                connection,
                "SELECT lead_status FROM leads WHERE lead_id = ?",
                (request.lead_id,),
            )

            if current is None:
                raise ToolFailure("NOT_FOUND", "Lead was not found.")

            if current["lead_status"] != request.expected_current_status:
                raise ToolFailure("CONFLICT", "Lead status changed before this update.")

            if request.new_status not in _ALLOWED_TRANSITIONS[current["lead_status"]]:
                raise ToolFailure(
                    "INVALID_TRANSITION",
                    "The requested lead status transition is not allowed.",
                )

            cursor = execute(
                connection,
                """
                UPDATE leads
                SET lead_status = ?
                WHERE lead_id = ? AND lead_status = ?
                """,
                (
                    request.new_status,
                    request.lead_id,
                    request.expected_current_status,
                ),
            )

            if cursor.rowcount != 1:
                raise ToolFailure("CONFLICT", "Lead status changed before this update.")

            return ActionResult(
                _get_lead(connection, request.lead_id),
                request.lead_id,
            )

        def replay(connection: sqlite3.Connection, resource_id: str | None) -> Any:
            if resource_id is None:
                raise ToolFailure(
                    "DATABASE_ERROR",
                    "Stored operation reference is unavailable.",
                )

            authorize(resource_id)
            return _get_lead(connection, resource_id)

        outcome = self.execute(
            request,
            operation_name="update_status",
            mutating=True,
            action=action,
            replay=replay,
        )

        return self.result(outcome, LeadView)


    
    def detect_duplicates(
        self,
        raw_input: DuplicateDetectionInput | Mapping[str, Any],
        *,
        access_context: CRMAccessContext | None = None,
    ) -> ToolResult[DuplicateDetectionOutput]:
        request, invalid = self.parse(DuplicateDetectionInput, raw_input)

        if invalid is not None:
            return self.result(invalid, DuplicateDetectionOutput)

        assert request is not None

        def authorize() -> None:
            if (
                access_context is None
                or not access_context.can_detect_duplicates()
            ):
                raise ToolFailure(
                    "FORBIDDEN",
                    "You are not authorized to detect duplicate leads.",
                )

            if request.lead_id is not None and not access_context.can_read_lead(
                request.lead_id
            ):
                raise ToolFailure(
                    "FORBIDDEN",
                    "You are not authorized to access this lead.",
                )

        def search(connection: sqlite3.Connection) -> dict[str, Any]:
            authorize()

            email = request.email
            phone = request.phone

            if request.lead_id is not None:
                row = fetch_one(
                    connection,
                    "SELECT email, phone FROM leads WHERE lead_id = ?",
                    (request.lead_id,),
                )

                if row is None:
                    raise ToolFailure("NOT_FOUND", "Lead was not found.")

                email = email if email is not None else row["email"]
                phone = phone if phone is not None else row["phone"]

            return _find_duplicates(
                connection,
                exclude_lead_id=request.lead_id,
                email=email,
                phone=phone,
            )

        def action(
            connection: sqlite3.Connection,
            operation_id: str,
        ) -> ActionResult:
            return ActionResult(search(connection), request.lead_id)

        def replay(
            connection: sqlite3.Connection,
            resource_id: str | None,
        ) -> Any:
            return search(connection)

        outcome = self.execute(
            request,
            operation_name="detect_duplicates",
            mutating=False,
            action=action,
            replay=replay,
        )

        return self.result(outcome, DuplicateDetectionOutput)


