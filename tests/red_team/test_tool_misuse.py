import pytest
from pydantic import ValidationError

from tools.schemas import LeadCreateInput


def test_crm_rejects_unauthorized_extra_tool_arguments():
    payload = {
        "run_id": "red-team-tool-001",
        "idempotency_key": "tool-smuggling-001",
        "lead_id": "ATTACK-TOOL-001",
        "source": "website",
        "name": "Unauthorized Test",
        "email": "test@example.com",
        "phone": "+14155550123",
        "raw_message": "I need help with heating.",
        "service_requested": "heating",
        "address_text": "Test address",
        "service_area_id": "AREA-001",
        "admin_override": True,
        "export_all_leads": True,
    }

    with pytest.raises(ValidationError):
        LeadCreateInput.model_validate(payload)