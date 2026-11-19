
import pytest

from config.settings import load_settings
from database.connection import open_connection, initialize_database
from tools.crm import MockCRM
from agent.lead_processor import LeadProcessor
from types import SimpleNamespace


@pytest.fixture
def processor(tmp_path):
    settings = load_settings()

    # Use a temporary database instead of the project database.
    database_settings = settings.database.model_copy(
        update={"sqlite_path": tmp_path / "test_leads.sqlite3"}
    )

    connection = open_connection(database_settings)
    initialize_database(connection)

    # Enable mock tools only in this temporary test database.
    connection.execute(
        """
        UPDATE system_controls
        SET kill_switch_active = 0,
            spending_limit_micros = 10000000
        WHERE control_id = 1
        """
    )
    connection.commit()

    crm = MockCRM(connection, settings)
    yield LeadProcessor(crm)

    connection.close()


def test_processor_handles_unknown_lead(processor):
    result = processor.process_lead(
        lead_id="UNKNOWN-LEAD",
        run_id="processor-test-001",
    )

    assert result["success"] is False
    assert result["lead_id"] == "UNKNOWN-LEAD"

def make_test_lead(**overrides):
    data = {
        "lead_id": "SYN-TEST-001",
        "raw_message": "I need help with heat pump inspection.",
        "email": "test@example.com",
        "phone": "+12025550100",
        "service_requested": "heat pump inspection",
        "service_area_id": "DEMO-NORTH",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def classify(lead):
    return LeadProcessor._classify(
        lead=lead,
        risk_flags=[],
        duplicate_matches=[],
    )


def test_valid_lead_is_eligible():
    result = classify(make_test_lead())
    assert result.decision == "eligible_for_qualification"


def test_outside_service_area_is_rejected():
    result = classify(
        make_test_lead(),
        ["outside_service_area"],
        [],
    ) if False else LeadProcessor._classify(
        make_test_lead(),
        ["outside_service_area"],
        [],
    )
    assert result.decision == "reject_outside_service_area"


def test_missing_service_area_requests_information():
    result = LeadProcessor._classify(
        make_test_lead(service_area_id=None),
        ["missing_service_area"],
        [],
    )
    assert result.decision == "request_information"


def test_prompt_injection_is_escalated():
    result = LeadProcessor._classify(
        make_test_lead(),
        ["possible_prompt_injection"],
        [],
    )
    assert result.decision == "escalate"
    assert result.requires_human is True


def test_angry_customer_is_escalated():
    result = LeadProcessor._classify(
        make_test_lead(),
        ["angry_or_complaint"],
        [],
    )
    assert result.decision == "escalate"


def test_spam_is_flagged_for_review():
    result = LeadProcessor._classify(
        make_test_lead(),
        ["possible_spam"],
        [],
    )
    assert result.decision == "reject_for_review"
    assert result.requires_human is True


def test_full_pipeline_with_valid_synthetic_lead(processor):
    run_id = "pipeline-valid-001"

    create_result = processor.crm.create_lead({
        "run_id": run_id,
        "idempotency_key": "create-syn-000001",
        "lead_id": "SYN-000001",
        "source": "referral",
        "name": "Synthetic Lead 000001",
        "email": "lead000001@example.com",
        "phone": "+1-202-555-0100",
        "raw_message": (
            "Could someone take a look at our heat pump inspection? "
            "It makes a light rattling sound."
        ),
        "service_requested": "heat pump inspection",
        "address_text": "Demo North / Sample Block 02 / Unit 02",
        "service_area_id": "DEMO-NORTH",
    })

    assert create_result.success is True

    result = processor.process_lead(
        lead_id="SYN-000001",
        run_id=run_id,
    )

    assert result["success"] is True
    assert result["decision"]["decision"] == "eligible_for_qualification"
