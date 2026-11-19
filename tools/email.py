"""Local mock email recorder. This module performs no network operations."""

from collections.abc import Mapping
import re
import sqlite3
from typing import Any
from uuid import uuid4

from database.connection import execute, fetch_one
from tools.common import ActionResult, ToolBase, ToolFailure, utc_now
from tools.schemas import EmailSendInput, MessageView, ToolResult


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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


class MockEmail(ToolBase):
    tool_name = "email"

    def simulate_send(
        self,
        raw_input: EmailSendInput | Mapping[str, Any],
    ) -> ToolResult[MessageView]:
        request, invalid = self.parse(EmailSendInput, raw_input)
        if invalid is not None:
            return self.result(invalid, MessageView)
        assert request is not None
        message_id = str(uuid4())
        created_at = utc_now()
        logical_action_key = f"{request.lead_id}:{request.purpose}"

        def action(connection: sqlite3.Connection, operation_id: str) -> ActionResult:
            lead = fetch_one(
                connection,
                "SELECT email FROM leads WHERE lead_id = ?",
                (request.lead_id,),
            )
            if lead is None:
                raise ToolFailure("NOT_FOUND", "Lead was not found.")
            destination = lead["email"]
            if not destination or not _EMAIL_PATTERN.fullmatch(destination.strip()):
                raise ToolFailure("INVALID_CONTACT", "Lead does not have a valid email address.")
            preference = fetch_one(
                connection,
                """
                SELECT email_allowed, opted_out_at
                FROM contact_preferences
                WHERE lead_id = ?
                """,
                (request.lead_id,),
            )
            if preference is None or preference["email_allowed"] != 1 or preference["opted_out_at"] is not None:
                raise ToolFailure("CONSENT_REQUIRED", "Email contact permission is missing or opted out.")

            prior = fetch_one(
                connection,
                """
                SELECT message_id
                FROM outbound_messages
                WHERE channel = ? AND logical_action_key = ?
                """,
                ("email", logical_action_key),
            )
            if prior is not None:
                raise ToolFailure("DUPLICATE_ACTION", "This logical email action was already recorded.")
            execute(
                connection,
                """
                INSERT INTO outbound_messages (
                    message_id, lead_id, channel, purpose, logical_action_key,
                    destination, subject, body, status, operation_id, created_at
                ) VALUES (?, ?, 'email', ?, ?, ?, ?, ?, 'simulated', ?, ?)
                """,
                (
                    message_id,
                    request.lead_id,
                    request.purpose,
                    logical_action_key,
                    destination.strip(),
                    request.subject,
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

