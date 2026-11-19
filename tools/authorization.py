
"""Trusted authorization contexts for internal CRM operations."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CRMAccessContext:
    principal: str
    permissions: frozenset[str]
    allowed_lead_ids: frozenset[str]

    def can_read_lead(self, lead_id: str) -> bool:
        return (
            "lead:read:assigned" in self.permissions
            and lead_id in self.allowed_lead_ids
        )

    def can_detect_duplicates(self) -> bool:
        return "lead:duplicate:search" in self.permissions


def create_agent_context(
    allowed_lead_ids: set[str],
) -> CRMAccessContext:
    """Create a restricted context for trusted internal agent operations."""

    return CRMAccessContext(
        principal="inbound-lead-agent",
        permissions=frozenset({
            "lead:read:assigned",
            "lead:duplicate:search",
        }),
        allowed_lead_ids=frozenset(allowed_lead_ids),
    )
