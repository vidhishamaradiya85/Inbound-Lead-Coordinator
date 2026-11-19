"""Strict Pydantic v2 schemas for the local mock tools."""

from typing import Annotated, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


LeadSource = Literal["website", "phone", "sms", "referral"]
LeadStatus = Literal[
    "new",
    "in_progress",
    "qualified",
    "rejected",
    "duplicate",
    "escalated",
    "needs_info",
    "mock_booked",
]
MessagePurpose = Literal[
    "estimate_confirmation",
    "lead_follow_up_1",
    "lead_follow_up_2",
]
ErrorCode = Literal[
    "VALIDATION_ERROR",
    "NOT_FOUND",
    "FORBIDDEN",
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
]

LeadID = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$"),
]
RunID = Annotated[
    str,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"),
]
IdempotencyKey = Annotated[
    str,
    StringConstraints(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
]
OpaqueID = Annotated[
    str,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ToolRequest(StrictModel):
    # These identifiers are supplied by the trusted orchestrator, not copied
    # from customer messages.
    run_id: RunID
    idempotency_key: IdempotencyKey


class LeadCreateInput(ToolRequest):
    lead_id: LeadID
    source: LeadSource
    name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)
    raw_message: str = Field(min_length=1, max_length=10000)
    service_requested: str | None = Field(default=None, max_length=200)
    address_text: str | None = Field(default=None, max_length=500)
    service_area_id: str | None = Field(default=None, max_length=64)

    @field_validator("raw_message")
    @classmethod
    def raw_message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("raw_message must contain non-whitespace text")
        return value


class LeadGetInput(ToolRequest):
    lead_id: LeadID


class LeadStatusUpdateInput(ToolRequest):
    lead_id: LeadID
    expected_current_status: LeadStatus
    new_status: LeadStatus


class DuplicateDetectionInput(ToolRequest):
    lead_id: LeadID | None = None
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def require_a_contact_lookup_value(self) -> "DuplicateDetectionInput":
        if self.lead_id is None and self.email is None and self.phone is None:
            raise ValueError("lead_id, email, or phone is required")
        return self


class CalendarAvailabilityInput(ToolRequest):
    service_area_id: str = Field(min_length=1, max_length=64)
    service_requested: str = Field(min_length=1, max_length=200)
    from_at: str = Field(min_length=20, max_length=40)
    until_at: str = Field(min_length=20, max_length=40)

    @field_validator("from_at", "until_at")
    @classmethod
    def timestamp_must_be_timezone_aware_iso8601(cls, value: str) -> str:
        from datetime import datetime

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def range_must_be_increasing(self) -> "CalendarAvailabilityInput":
        from datetime import datetime

        start = datetime.fromisoformat(self.from_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(self.until_at.replace("Z", "+00:00"))
        if end <= start:
            raise ValueError("until_at must be later than from_at")
        return self


class AppointmentCreateInput(ToolRequest):
    lead_id: LeadID
    slot_id: OpaqueID


class SmsSendInput(ToolRequest):
    lead_id: LeadID
    purpose: MessagePurpose
    body: str = Field(min_length=1, max_length=1600)

    @field_validator("body")
    @classmethod
    def body_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body must contain non-whitespace text")
        return value


class EmailSendInput(ToolRequest):
    lead_id: LeadID
    purpose: MessagePurpose
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=20000)

    @field_validator("subject", "body")
    @classmethod
    def message_fields_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message field must contain non-whitespace text")
        return value


class LeadView(StrictModel):
    lead_id: LeadID
    source: LeadSource
    name: str | None
    email: str | None
    phone: str | None
    raw_message: str
    service_requested: str | None
    address_text: str | None
    service_area_id: str | None
    created_at: str
    lead_status: LeadStatus
    qualification_status: Literal[
        "not_evaluated", "qualified", "unqualified", "needs_review", "needs_info"
    ]
    qualification_score: float | None
    qualification_reason: str | None
    service_area_eligible: bool | None
    detected_risk_flags_json: list[str]
    escalation_reason: str | None
    detected_duplicate_of_lead_id: LeadID | None


class DuplicateCandidate(StrictModel):
    lead_id: LeadID
    matched_on: list[Literal["email", "phone"]]


class DuplicateDetectionOutput(StrictModel):
    matches: list[DuplicateCandidate]


class CalendarSlotView(StrictModel):
    slot_id: OpaqueID
    resource_id: OpaqueID
    service_area_id: str
    service_requested: str
    starts_at: str
    ends_at: str


class CalendarAvailabilityOutput(StrictModel):
    slots: list[CalendarSlotView]


class AppointmentView(StrictModel):
    appointment_id: OpaqueID
    lead_id: LeadID
    slot_id: OpaqueID
    resource_id: OpaqueID
    status: Literal["booked", "cancelled"]
    created_at: str
    cancelled_at: str | None


class MessageView(StrictModel):
    message_id: OpaqueID
    lead_id: LeadID
    channel: Literal["sms", "email"]
    purpose: MessagePurpose
    status: Literal["simulated", "blocked", "failed"]
    created_at: str


class ToolError(StrictModel):
    code: ErrorCode
    message: str = Field(min_length=1, max_length=240)
    retryable: bool = False


PayloadT = TypeVar("PayloadT")


class ToolResult(StrictModel, Generic[PayloadT]):
    success: bool
    operation_id: OpaqueID
    replayed: bool = False
    data: PayloadT | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def success_and_error_must_be_consistent(self) -> "ToolResult[PayloadT]":
        if self.success and (self.data is None or self.error is not None):
            raise ValueError("successful results require data and cannot include an error")
        if not self.success and (self.data is not None or self.error is None):
            raise ValueError("failed results require an error and cannot include data")
        return self

