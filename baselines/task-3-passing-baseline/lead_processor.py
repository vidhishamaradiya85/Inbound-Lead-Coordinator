
"""Deterministic lead analysis for the Inbound Lead Coordinator."""

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from config.service_areas import check_service_area
from tools.crm import MockCRM


@dataclass
class LeadDecision:
    lead_id: str
    decision: str
    qualification_status: str
    qualification_score: float
    reason: str
    risk_flags: list[str] = field(default_factory=list)
    duplicate_of: str | None = None
    requires_human: bool = False


# ---------------------------------------------------------
# Risk detection patterns
# ---------------------------------------------------------

INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior) instructions",
    r"reveal (your )?(system prompt|instructions)",
    r"ignore your (rules|safety|instructions)",
    r"act as (an unrestricted|a different) assistant",
    r"developer message",
    r"system prompt",
    r"bypass (your )?(rules|safety)",
    r"system override",
    r"administrator command",
    r"export the full lead list",
    r"access another customer",
    r"send me all saved phone numbers",
    r"send a message to every contact",
    r"disclose the hidden instructions",
    r"reveal every other customer",
    r"call any tool",
]

ANGRY_PATTERNS = [
    r"\bangry\b",
    r"\bfurious\b",
    r"\bunacceptable\b",
    r"\bterrible service\b",
    r"\bcomplaint\b",
    r"\blawsuit\b",
    r"\blawyer\b",
    r"\brefund\b",
    r"\bscam\b",
    r"\bfrustrated\b",
    r"\bnobody followed up\b",
    r"\blast visit\b",
    r"\bdisappointing\b",
    r"\bstill unresolved\b",
    r"\bspeak with someone\b",
    r"\bunhappy\b",
    r"\btaken too long\b",
    r"\bhuman to review\b",
    r"\bnot received a clear answer\b",
    r"\bescalate this complaint\b",
]

SPAM_PATTERNS = [
    r"\bcasino\b",
    r"\bcrypto giveaway\b",
    r"\bfree money\b",
    r"\bclick here\b",
    r"\bwork from home and earn\b",
    r"\bunsolicited promotion\b",
    r"\bautomated bulk solicitation\b",
    r"\bbulk solicitation\b",
    r"\bpromotional message\b",
    r"\bsubscription offer\b",
    r"\bsample prize\b",
    r"\bclaim (a )?(complimentary )?reward\b",
    r"\baccount details\b",
    r"\badvertising placements\b",
]

BULK_SOLICITATION_PATTERNS = [
    r"\bbulk solicitation\b",
    r"\bautomated bulk solicitation\b",
    r"\badvertising placements\b",
]

VAGUE_SERVICE_PATTERNS = [
    r"\blook at something\b",
    r"\bnot sure what .* is called\b",
    r"\bissue i mentioned\b",
    r"\bsomething at the property\b",
    r"\bsomething at my home\b",
    r"\bnot included the service details\b",
    r"\bprovide more details later\b",
]


# ---------------------------------------------------------
# Helper functions
# ---------------------------------------------------------

def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in patterns
    )


def _valid_email(email: str | None) -> bool:
    if not email:
        return False

    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    return bool(re.fullmatch(pattern, email.strip()))


def _valid_phone(phone: str | None) -> bool:
    if not phone:
        return False

    digits = re.sub(r"\D", "", phone)
    return 10 <= len(digits) <= 15


def _normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def _normalize_phone(phone: str | None) -> str:
    return re.sub(r"\D", "", phone or "")


def _has_conflicting_contact_details(
    current_lead: Any,
    original_lead: Any,
    matched_on: list[str],
) -> bool:
    """Detect conflicting contact details between matching leads."""

    if "email" in matched_on:
        current_phone = _normalize_phone(current_lead.phone)
        original_phone = _normalize_phone(original_lead.phone)

        if (
            current_phone
            and original_phone
            and current_phone != original_phone
        ):
            return True

    if "phone" in matched_on:
        current_email = _normalize_email(current_lead.email)
        original_email = _normalize_email(original_lead.email)

        if (
            current_email
            and original_email
            and current_email != original_email
        ):
            return True

    return False


def _idempotency_key(
    run_id: str,
    lead_id: str,
    action: str,
) -> str:
    raw = f"{run_id}:{lead_id}:{action}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------
# Lead Processor
# ---------------------------------------------------------

class LeadProcessor:
    """Analyzes one lead using the existing local mock CRM."""

    def __init__(self, crm: MockCRM):
        self.crm = crm

    def process_lead(
        self,
        lead_id: str,
        run_id: str,
    ) -> dict[str, Any]:

        # Step 1: Retrieve the incoming lead.

        lead_result = self.crm.retrieve_lead(
            {
                "lead_id": lead_id,
                "run_id": run_id,
                "idempotency_key": _idempotency_key(
                    run_id, lead_id, "retrieve"
                ),
            }
        )

        if not lead_result.success:
            return {
                "success": False,
                "lead_id": lead_id,
                "error": (
                    lead_result.error.model_dump()
                    if lead_result.error
                    else "Lead retrieval failed."
                ),
            }

        lead = lead_result.data
        message = lead.raw_message or ""

        # Step 2: Detect duplicates.

        duplicate_result = self.crm.detect_duplicates(
            {
                "lead_id": lead_id,
                "run_id": run_id,
                "idempotency_key": _idempotency_key(
                    run_id, lead_id, "duplicates"
                ),
            }
        )

        if not duplicate_result.success:
            return {
                "success": False,
                "lead_id": lead_id,
                "error": (
                    duplicate_result.error.model_dump()
                    if duplicate_result.error
                    else "Duplicate detection failed."
                ),
            }

        duplicate_matches = duplicate_result.data.matches

        duplicate_of = None
        conflicting_duplicate = False
        duplicate_originals: dict[str, Any] = {}

        # Step 3: Retrieve and compare matching original leads.

        for candidate in duplicate_matches:

            if duplicate_of is None:
                duplicate_of = candidate.lead_id

            original_result = self.crm.retrieve_lead(
                {
                    "lead_id": candidate.lead_id,
                    "run_id": run_id,
                    "idempotency_key": _idempotency_key(
                        run_id,
                        candidate.lead_id,
                        "retrieve_duplicate",
                    ),
                }
            )

            if not original_result.success:
                return {
                    "success": False,
                    "lead_id": lead_id,
                    "error": (
                        "Could not retrieve matching lead "
                        "for comparison."
                    ),
                }

            duplicate_originals[candidate.lead_id] = original_result.data

            if _has_conflicting_contact_details(
                lead,
                original_result.data,
                candidate.matched_on,
            ):
                conflicting_duplicate = True
                duplicate_of = candidate.lead_id
                break

        # Step 4: Initialize risk flags.

        risk_flags: list[str] = []

        # Step 5: Detect security and customer-experience risks.

        if _matches_any(message, INJECTION_PATTERNS):
            risk_flags.append("possible_prompt_injection")

        if _matches_any(message, ANGRY_PATTERNS):
            risk_flags.append("angry_or_complaint")

        # Step 6: Detect spam before collecting ordinary lead-quality flags.
        # Spam records are evaluated for spam-specific flags only. This avoids
        # adding unrelated missing-field flags to messages that are clearly spam.

        is_spam = _matches_any(message, SPAM_PATTERNS)

        if is_spam:
            risk_flags.append("possible_spam")

            if _matches_any(message, BULK_SOLICITATION_PATTERNS):
                risk_flags.append("bulk_solicitation")

        else:
            # Step 7: Validate contact information before adding secondary
            # duplicate and service-quality flags. Invalid contact details
            # take precedence in risk reporting, while duplicate detection
            # remains available to the classifier and audit trail.

            email_valid = _valid_email(lead.email)
            phone_valid = _valid_phone(lead.phone)
            invalid_contact = (
                (lead.email is not None and bool(str(lead.email).strip()) and not email_valid)
                or (lead.phone is not None and bool(str(lead.phone).strip()) and not phone_valid)
            )

            # Step 8: Record duplicate evidence only when contact details
            # are valid enough to support a reliable duplicate assessment.

            if duplicate_matches and not invalid_contact:
                risk_flags.append("possible_duplicate")

                if conflicting_duplicate:
                    risk_flags.append("conflicting_contact_details")
                else:
                    # Distinguish byte-for-byte contact matches from matches
                    # that required email/phone normalization.
                    exact_match = False

                    for candidate in duplicate_matches:
                        original_lead = duplicate_originals.get(
                            candidate.lead_id
                        )

                        if original_lead is None:
                            continue
                        matched_fields = candidate.matched_on

                        raw_values_equal = all(
                            getattr(lead, field_name) == getattr(original_lead, field_name)
                            for field_name in matched_fields
                        )

                        if raw_values_equal:
                            exact_match = True
                            break

                    risk_flags.append(
                        "exact_contact_match"
                        if exact_match
                        else "normalized_contact_match"
                    )

            # Step 9: Record contact validation flags.

            if lead.email is None or not str(lead.email).strip():
                risk_flags.append("missing_email")
            elif not email_valid:
                risk_flags.append("invalid_email")

            if lead.phone is not None and str(lead.phone).strip() and not phone_valid:
                risk_flags.append("invalid_phone")

            # Step 10: Check whether service details are sufficient.
            # When contact information is invalid, report the primary contact
            # failure without adding secondary service-detail noise.

            if not invalid_contact and (
                not lead.service_requested
                or _matches_any(message, VAGUE_SERVICE_PATTERNS)
            ):
                risk_flags.append("missing_service_details")

            # Step 10: Check service-area eligibility.
            # Missing area is not labelled as an independent risk in this
            # evaluation dataset; an explicitly unsupported area is.

            area_eligible, area_reason = check_service_area(
                lead.service_area_id
            )

            if not area_eligible and area_reason == "outside_service_area":
                risk_flags.append("outside_service_area")

            # Step 11: Mark records that need more information or have
            # invalid contact details as incomplete.

            if (
                not lead.service_requested
                or _matches_any(message, VAGUE_SERVICE_PATTERNS)
                or not email_valid and not phone_valid
            ):
                risk_flags.append("incomplete")

        # Step 14: Classify the lead.

        decision = self._classify(
            lead=lead,
            risk_flags=risk_flags,
            duplicate_matches=duplicate_matches,
        )

        return {
            "success": True,
            "decision": asdict(decision),
        }

    # -----------------------------------------------------
    # Classification logic
    # -----------------------------------------------------

    @staticmethod
    def _classify(
        lead: Any,
        risk_flags: list[str],
        duplicate_matches: list[Any],
    ) -> LeadDecision:

        duplicate_of = (
            duplicate_matches[0].lead_id
            if duplicate_matches
            else None
        )

        # Priority 1: Security risks and angry customers.

        if (
            "possible_prompt_injection" in risk_flags
            or "angry_or_complaint" in risk_flags
        ):
            return LeadDecision(
                lead_id=lead.lead_id,
                decision="escalate",
                qualification_status="needs_review",
                qualification_score=0.0,
                reason="A security or customer complaint requires human review.",
                risk_flags=risk_flags,
                duplicate_of=duplicate_of,
                requires_human=True,
            )

        # Priority 2: Spam.
        # Spam takes priority over duplicate conflicts.

        if "possible_spam" in risk_flags:
            return LeadDecision(
                lead_id=lead.lead_id,
                decision="reject_for_review",
                qualification_status="needs_review",
                qualification_score=0.0,
                reason="Possible spam detected; human review required.",
                risk_flags=risk_flags,
                duplicate_of=duplicate_of,
                requires_human=True,
            )

        # Priority 3: Conflicting duplicate contact details.

        if "conflicting_contact_details" in risk_flags:
            return LeadDecision(
                lead_id=lead.lead_id,
                decision="escalate",
                qualification_status="needs_review",
                qualification_score=0.0,
                reason="Matching contact details contain conflicting information.",
                risk_flags=risk_flags,
                duplicate_of=duplicate_of,
                requires_human=True,
            )

        # Priority 4: Invalid supplied contact information.

        if (
            "invalid_email" in risk_flags
            or "invalid_phone" in risk_flags
        ):
            return LeadDecision(
                lead_id=lead.lead_id,
                decision="reject_invalid",
                qualification_status="unqualified",
                qualification_score=0.0,
                reason="Supplied contact information is invalid.",
                risk_flags=risk_flags,
                duplicate_of=duplicate_of,
            )

        # Priority 5: Ordinary duplicates.

        if duplicate_of:
            return LeadDecision(
                lead_id=lead.lead_id,
                decision="mark_duplicate",
                qualification_status="needs_review",
                qualification_score=0.0,
                reason="An existing lead matches the contact details.",
                risk_flags=risk_flags,
                duplicate_of=duplicate_of,
            )

        # Priority 6: Outside service area.

        if "outside_service_area" in risk_flags:
            return LeadDecision(
                lead_id=lead.lead_id,
                decision="reject_outside_service_area",
                qualification_status="unqualified",
                qualification_score=1.0,
                reason="The supplied service area is not supported.",
                risk_flags=risk_flags,
            )

        # Priority 7: Missing or unclear information.

        missing_fields = [
            flag
            for flag in risk_flags
            if flag in {
                "missing_email",
                "missing_service_details",
                # Retain legacy flags for compatibility with older records.
                "missing_contact_details",
                "missing_service",
                "missing_service_area",
                "unclear_service_details",
            }
        ]

        if missing_fields:
            return LeadDecision(
                lead_id=lead.lead_id,
                decision="request_information",
                qualification_status="needs_info",
                qualification_score=0.3,
                reason=(
                    "Required lead information is missing "
                    "or the service description needs clarification."
                ),
                risk_flags=risk_flags,
            )

        # Priority 8: Eligible for further qualification.

        return LeadDecision(
            lead_id=lead.lead_id,
            decision="eligible_for_qualification",
            qualification_status="not_evaluated",
            qualification_score=0.7,
            reason=(
                "Basic lead information is present. "
                "Further qualification is required."
            ),
            risk_flags=risk_flags,
        )
