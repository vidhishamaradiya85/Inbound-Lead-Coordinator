"""Shared validation, idempotency, safety, and SQLite retry helpers."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import random
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from config.settings import AppSettings, load_settings
from database.connection import execute, fetch_one, transaction
from tools.schemas import ErrorCode, ToolError, ToolRequest, ToolResult


RequestT = TypeVar("RequestT", bound=ToolRequest)
PayloadT = TypeVar("PayloadT", bound=BaseModel)


@dataclass(frozen=True)
class OperationOutcome:
    success: bool
    operation_id: str
    data: Any = None
    error: ToolError | None = None
    replayed: bool = False


@dataclass(frozen=True)
class ActionResult:
    data: Any
    resource_id: str | None


class ToolFailure(Exception):
    def __init__(self, code: ErrorCode, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_input(
    model_type: type[RequestT],
    raw_input: RequestT | Mapping[str, Any],
) -> tuple[RequestT | None, OperationOutcome | None]:
    try:
        request = raw_input if isinstance(raw_input, model_type) else model_type.model_validate(raw_input)
        return request, None
    except ValidationError:
        # Do not include raw values or Pydantic input context; these may contain PII.
        return None, OperationOutcome(
            success=False,
            operation_id=str(uuid4()),
            error=ToolError(
                code="VALIDATION_ERROR",
                message="Tool input did not match the required schema.",
                retryable=False,
            ),
        )


def make_result(
    outcome: OperationOutcome,
    payload_type: type[PayloadT],
) -> ToolResult[PayloadT]:
    if not outcome.success:
        return ToolResult[PayloadT](
            success=False,
            operation_id=outcome.operation_id,
            replayed=outcome.replayed,
            error=outcome.error,
        )
    payload = payload_type.model_validate(outcome.data)
    return ToolResult[PayloadT](
        success=True,
        operation_id=outcome.operation_id,
        replayed=outcome.replayed,
        data=payload,
    )


def _request_digest(request: ToolRequest) -> str:
    canonical = json.dumps(
        request.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_result_code(value: str | None) -> ErrorCode:
    known_codes = {
        "VALIDATION_ERROR",
        "NOT_FOUND",
        "CONFLICT",
        "INVALID_TRANSITION",
        "SLOT_UNAVAILABLE",
        "CONSENT_REQUIRED",
        "INVALID_CONTACT",
        "DUPLICATE_ACTION",
        "KILL_SWITCH_ACTIVE",
        "KILL_SWITCH_UNAVAILABLE",
        "SPENDING_LIMIT_EXCEEDED",
        "IDEMPOTENCY_CONFLICT",
        "OPERATION_IN_PROGRESS",
        "TIMEOUT",
        "RETRY_EXHAUSTED",
        "DATABASE_ERROR",
        "INTERNAL_ERROR",
    }
    if value in known_codes:
        return value  # type: ignore[return-value]
    return "DATABASE_ERROR"


def _failure(
    operation_id: str,
    code: ErrorCode,
    message: str,
    *,
    retryable: bool = False,
    replayed: bool = False,
) -> OperationOutcome:
    return OperationOutcome(
        success=False,
        operation_id=operation_id,
        error=ToolError(code=code, message=message, retryable=retryable),
        replayed=replayed,
    )


def _effective_run_limit_micros(settings: AppSettings, persisted_limit_micros: int) -> int:
    configured = settings.safety.spending_limit_usd_per_run
    configured_micros = int(configured * Decimal("1000000"))
    return min(configured_micros, persisted_limit_micros)


def _run_spend_micros(connection: sqlite3.Connection, run_id: str) -> int:
    row = fetch_one(
        connection,
        """
        SELECT COALESCE(
            SUM(
                CASE
                    WHEN entry_type IN ('reservation', 'charge') THEN amount_micros
                    ELSE -amount_micros
                END
            ),
            0
        ) AS spent_micros
        FROM spending_ledger
        WHERE run_id = ?
        """,
        (run_id,),
    )
    return max(0, int(row["spent_micros"] if row is not None else 0))


def _is_transient_sqlite_error(error: sqlite3.OperationalError) -> bool:
    message = str(error).lower()
    return "locked" in message or "busy" in message


def _record_transient_failure(
    connection: sqlite3.Connection,
    *,
    operation_id: str,
    tool_name: str,
    operation_name: str,
    request: ToolRequest,
    request_hash: str,
    code: ErrorCode,
) -> None:
    """Best-effort trace record after a transient error exhausted its retries."""

    try:
        with transaction(connection):
            execute(
                connection,
                """
                INSERT OR IGNORE INTO tool_operations (
                    operation_id, tool_name, operation_name, idempotency_key,
                    request_hash, status, result_code, created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, 'failed', ?, ?, ?)
                """,
                (
                    operation_id,
                    tool_name,
                    operation_name,
                    request.idempotency_key,
                    request_hash,
                    code,
                    utc_now(),
                    utc_now(),
                ),
            )
    except sqlite3.Error:
        # The database may remain locked; the caller still receives a safe result.
        return


def run_operation(
    connection: sqlite3.Connection,
    request: ToolRequest,
    *,
    tool_name: str,
    operation_name: str,
    mutating: bool,
    action: Callable[[sqlite3.Connection, str], ActionResult],
    replay: Callable[[sqlite3.Connection, str | None], Any],
    settings: AppSettings | None = None,
    estimated_cost_micros: int = 0,
) -> OperationOutcome:
    """Run one idempotent operation with a safety gate and bounded SQLite retries."""

    active_settings = settings or load_settings()
    operation_id = str(uuid4())
    request_hash = _request_digest(request)
    deadline = time.monotonic() + active_settings.safety.tool_timeout_seconds
    retries = active_settings.safety.max_tool_retries
    attempt = 0

    while True:
        try:
            with transaction(connection, immediate=True):
                existing = fetch_one(
                    connection,
                    """
                    SELECT operation_id, request_hash, status, result_code, resource_id
                    FROM tool_operations
                    WHERE tool_name = ? AND operation_name = ? AND idempotency_key = ?
                    """,
                    (tool_name, operation_name, request.idempotency_key),
                )
                if existing is not None:
                    if existing["request_hash"] != request_hash:
                        return _failure(
                            existing["operation_id"],
                            "IDEMPOTENCY_CONFLICT",
                            "The idempotency key was already used with different input.",
                            replayed=True,
                        )
                    if existing["status"] == "failed":
                        code = _safe_result_code(existing["result_code"])
                        return _failure(
                            existing["operation_id"],
                            code,
                            "The original operation failed; use a new authorized request to try again.",
                            replayed=True,
                        )
                    if existing["status"] == "started":
                        return _failure(
                            existing["operation_id"],
                            "OPERATION_IN_PROGRESS",
                            "The operation is already in progress.",
                            retryable=True,
                            replayed=True,
                        )
                    try:
                        replayed_data = replay(connection, existing["resource_id"])
                    except ToolFailure as failure:
                        return _failure(
                            existing["operation_id"],
                            failure.code,
                            failure.message,
                            retryable=failure.retryable,
                            replayed=True,
                        )
                    return OperationOutcome(
                        success=True,
                        operation_id=existing["operation_id"],
                        data=replayed_data,
                        replayed=True,
                    )

                execute(
                    connection,
                    """
                    INSERT INTO tool_operations (
                        operation_id, tool_name, operation_name, idempotency_key,
                        request_hash, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, 'started', ?)
                    """,
                    (
                        operation_id,
                        tool_name,
                        operation_name,
                        request.idempotency_key,
                        request_hash,
                        utc_now(),
                    ),
                )

                def fail_in_transaction(
                    code: ErrorCode,
                    message: str,
                    *,
                    retryable: bool = False,
                ) -> OperationOutcome:
                    execute(
                        connection,
                        """
                        UPDATE tool_operations
                        SET status = 'failed', result_code = ?, completed_at = ?
                        WHERE operation_id = ?
                        """,
                        (code, utc_now(), operation_id),
                    )
                    return _failure(
                        operation_id,
                        code,
                        message,
                        retryable=retryable,
                    )

                if mutating:
                    controls = fetch_one(
                        connection,
                        """
                        SELECT kill_switch_active, spending_limit_micros
                        FROM system_controls
                        WHERE control_id = ?
                        """,
                        (1,),
                    )
                    if controls is None:
                        return fail_in_transaction(
                            "KILL_SWITCH_UNAVAILABLE",
                            "Persistent safety controls are unavailable; the action was blocked.",
                        )
                    if controls["kill_switch_active"] != 0:
                        return fail_in_transaction(
                            "KILL_SWITCH_ACTIVE",
                            "The persistent kill switch is active; the action was blocked.",
                        )
                    if estimated_cost_micros < 0:
                        return fail_in_transaction(
                            "INTERNAL_ERROR",
                            "The operation cost estimate is invalid.",
                        )
                    limit_micros = _effective_run_limit_micros(
                        active_settings,
                        int(controls["spending_limit_micros"]),
                    )
                    spent_micros = _run_spend_micros(connection, request.run_id)
                    if spent_micros + estimated_cost_micros > limit_micros:
                        return fail_in_transaction(
                            "SPENDING_LIMIT_EXCEEDED",
                            "The configured spending limit would be exceeded; the action was blocked.",
                        )

                try:
                    action_result = action(connection, operation_id)
                except ToolFailure as failure:
                    return fail_in_transaction(
                        failure.code,
                        failure.message,
                        retryable=failure.retryable,
                    )
                except sqlite3.IntegrityError:
                    return fail_in_transaction(
                        "CONFLICT",
                        "The operation conflicts with existing database state.",
                    )

                if mutating:
                    execute(
                        connection,
                        """
                        INSERT INTO spending_ledger (
                            run_id, operation_id, entry_type, amount_micros, created_at
                        ) VALUES (?, ?, 'charge', ?, ?)
                        """,
                        (
                            request.run_id,
                            operation_id,
                            estimated_cost_micros,
                            utc_now(),
                        ),
                    )

                execute(
                    connection,
                    """
                    UPDATE tool_operations
                    SET status = 'succeeded', result_code = 'OK',
                        resource_id = ?, completed_at = ?
                    WHERE operation_id = ?
                    """,
                    (action_result.resource_id, utc_now(), operation_id),
                )
                return OperationOutcome(
                    success=True,
                    operation_id=operation_id,
                    data=action_result.data,
                )
        except sqlite3.OperationalError as error:
            if not _is_transient_sqlite_error(error):
                _record_transient_failure(
                    connection,
                    operation_id=operation_id,
                    tool_name=tool_name,
                    operation_name=operation_name,
                    request=request,
                    request_hash=request_hash,
                    code="DATABASE_ERROR",
                )
                return _failure(
                    operation_id,
                    "DATABASE_ERROR",
                    "The local database operation failed.",
                )

            attempt += 1
            now = time.monotonic()
            if now >= deadline:
                _record_transient_failure(
                    connection,
                    operation_id=operation_id,
                    tool_name=tool_name,
                    operation_name=operation_name,
                    request=request,
                    request_hash=request_hash,
                    code="TIMEOUT",
                )
                return _failure(
                    operation_id,
                    "TIMEOUT",
                    "The local database operation exceeded its time limit.",
                    retryable=True,
                )
            if attempt > retries:
                _record_transient_failure(
                    connection,
                    operation_id=operation_id,
                    tool_name=tool_name,
                    operation_name=operation_name,
                    request=request,
                    request_hash=request_hash,
                    code="RETRY_EXHAUSTED",
                )
                return _failure(
                    operation_id,
                    "RETRY_EXHAUSTED",
                    "Transient database contention persisted after bounded retries.",
                    retryable=True,
                )
            delay = min(0.025 * (2 ** (attempt - 1)) + random.uniform(0.0, 0.025), deadline - now)
            if delay > 0:
                time.sleep(delay)
        except sqlite3.Error:
            _record_transient_failure(
                connection,
                operation_id=operation_id,
                tool_name=tool_name,
                operation_name=operation_name,
                request=request,
                request_hash=request_hash,
                code="DATABASE_ERROR",
            )
            return _failure(
                operation_id,
                "DATABASE_ERROR",
                "The local database operation failed.",
            )


class ToolBase:
    """Base class for tools that share a runtime SQLite connection."""

    tool_name = "tool"

    def __init__(
        self,
        connection: sqlite3.Connection,
        settings: AppSettings | None = None,
    ) -> None:
        self.connection = connection
        self.settings = settings or load_settings()

    def parse(self, model_type: type[RequestT], raw_input: RequestT | Mapping[str, Any]):
        return validate_input(model_type, raw_input)

    def execute(
        self,
        request: ToolRequest,
        *,
        operation_name: str,
        mutating: bool,
        action: Callable[[sqlite3.Connection, str], ActionResult],
        replay: Callable[[sqlite3.Connection, str | None], Any],
        estimated_cost_micros: int = 0,
    ) -> OperationOutcome:
        return run_operation(
            self.connection,
            request,
            tool_name=self.tool_name,
            operation_name=operation_name,
            mutating=mutating,
            action=action,
            replay=replay,
            settings=self.settings,
            estimated_cost_micros=estimated_cost_micros,
        )

    @staticmethod
    def result(
        outcome: OperationOutcome,
        payload_type: type[PayloadT],
    ) -> ToolResult[PayloadT]:
        from tools.common import make_result

        return make_result(outcome, payload_type)

