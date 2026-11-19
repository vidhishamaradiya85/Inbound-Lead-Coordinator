"""Local mock SMS recorder. This module performs no network operations."""

from collections.abc import Mapping
import re
import sqlite3
from typing import Any
from uuid import uuid4

from database.connection import execute, fetch_one
from tools.common import ActionResult, ToolBase, ToolFailure, utc_now
from tools.schemas import MessageView, SmsSendInput, ToolResult


def _message(connection: sqlite3.Connection, message_id: str) -> dict[str, Any]:
    row = fetch_one(
        connection,
        """
        SELECT message_id, lead_id, channel, purpose, status, created_at
        FROM outbound_messages
        WHERE message_id = ?
        """,
        (message_id,),
    )
    if row is None:
        raise ToolFailure("NOT_FOUND", "Mock message record was not found.")
    return {
        "message_id": row["message_id"],
        "lead_id": row["lead_id"],
        "channel": row["channel"],
        "purpose": row["purpose"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def _valid_phone(value: str | None) -> bool:
    digits = re.sub(r"\D", "", value or "")
    return 8 <= len(digits) <= 15


class MockSMS(ToolBase):
    tool_name = "sms"

    def simulate_send(
        self,
        raw_input: SmsSendInput | Mapping[str, Any],
    ) -> ToolResult[MessageView]:
        request, invalid = self.parse(SmsSendInput, raw_input)
        if invalid is not None:
            return self.result(invalid, MessageView)
        assert request is not None
        message_id = str(uuid4())
        created_at = utc_now()
        logical_action_key = f"{request.lead_id}:{request.purpose}"

        def action(connection: sqlite3.Connection, operation_id: str) -> ActionResult:
            lead = fetch_one(
                connection,
                "SELECT phone FROM leads WHERE lead_id = ?",
                (request.lead_id,),
            )
            if lead is None:
                raise ToolFailure("NOT_FOUND", "Lead was not found.")
            destination = lead["phone"]
            if not _valid_phone(destination):
                raise ToolFailure("INVALID_CONTACT", "Lead does not have a valid phone number.")
            preference = fetch_one(
                connection,
                """
                SELECT sms_allowed, opted_out_at
                FROM contact_preferences
                WHERE lead_id = ?
                """,
                (request.lead_id,),
            )
            if preference is None or preference["sms_allowed"] != 1 or preference["opted_out_at"] is not None:
                raise ToolFailure("CONSENT_REQUIRED", "SMS contact permission is missing or opted out.")

            prior = fetch_one(
                connection,
                """
                SELECT message_id
                FROM outbound_messages
                WHERE channel = ? AND logical_action_key = ?
                """,
                ("sms", logical_action_key),
            )
            if prior is not None:
                raise ToolFailure("DUPLICATE_ACTION", "This logical SMS action was already recorded.")
            execute(
                connection,
                """
                INSERT INTO outbound_messages (
                    message_id, lead_id, channel, purpose, logical_action_key,
                    destination, subject, body, status, operation_id, created_at
                ) VALUES (?, ?, 'sms', ?, ?, ?, NULL, ?, 'simulated', ?, ?)
                """,
                (
                    message_id,
                    request.lead_id,
                    request.purpose,
                    logical_action_key,
                    destination,
                    request.body,
                    operation_id,
                    created_at,
                ),
            )
            return ActionResult(_message(connection, message_id), message_id)

        def replay(connection: sqlite3.Connection, resource_id: str | None) -> Any:
            if resource_id is None:
                raise ToolFailure("DATABASE_ERROR", "Stored mock message reference is unavailable.")
            return _message(connection, resource_id)

        outcome = self.execute(
            request,
            operation_name="simulate_send",
            mutating=True,
            action=action,
            replay=replay,
        )
        return self.result(outcome, MessageView)

