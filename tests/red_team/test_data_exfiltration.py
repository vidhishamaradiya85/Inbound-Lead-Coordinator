
import pytest

from config.settings import load_settings
from database.connection import open_connection, initialize_database
from tools.crm import MockCRM


@pytest.fixture
def crm(tmp_path):
    settings = load_settings()

    database_settings = settings.database.model_copy(
        update={"sqlite_path": tmp_path / "exfiltration.sqlite3"}
    )

    connection = open_connection(database_settings)
    initialize_database(connection)

    connection.execute(
        """
        UPDATE system_controls
        SET kill_switch_active = 0,
            spending_limit_micros = 10000000
        WHERE control_id = 1
        """
    )
    connection.commit()

    client = MockCRM(connection, settings)
    yield client

    connection.close()


def test_retrieve_another_leads_private_information(crm):
    # Create the first customer's record.
    first = crm.create_lead({
        "run_id": "red-team-exfil-001",
        "idempotency_key": "create-customer-001",
        "lead_id": "CUSTOMER-001",
        "source": "website",
        "name": "Customer One",
        "email": "customer1@example.com",
        "phone": "+12025550101",
        "raw_message": "I need a heat pump inspection.",
        "service_requested": "heat pump inspection",
        "address_text": "Private Customer Address 1",
        "service_area_id": "DEMO-NORTH",
    })

    assert first.success is True

    # Create a second customer's record.
    second = crm.create_lead({
        "run_id": "red-team-exfil-002",
        "idempotency_key": "create-customer-002",
        "lead_id": "CUSTOMER-002",
        "source": "website",
        "name": "Customer Two",
        "email": "customer2@example.com",
        "phone": "+12025550102",
        "raw_message": "I need a boiler inspection.",
        "service_requested": "boiler inspection",
        "address_text": "Private Customer Address 2",
        "service_area_id": "DEMO-NORTH",
    })

    assert second.success is True

    # Simulate an unauthorized request for Customer Two's record.
    result = crm.retrieve_lead({
        "run_id": "red-team-exfil-003",
        "idempotency_key": "retrieve-customer-002",
        "lead_id": "CUSTOMER-002",
    })

    assert result.success is False
    assert result.data is None
    assert result.error is not None
    assert result.error.code == "FORBIDDEN"
    

def test_unauthorized_caller_cannot_change_another_leads_status(crm):
    # Create a customer's lead.
    created = crm.create_lead({
        "run_id": "red-team-change-001",
        "idempotency_key": "create-status-customer-001",
        "lead_id": "CUSTOMER-STATUS-001",
        "source": "website",
        "name": "Protected Customer",
        "email": "protected@example.com",
        "phone": "+12025550150",
        "raw_message": "I need a heat pump inspection.",
        "service_requested": "heat pump inspection",
        "address_text": "Private Customer Address",
        "service_area_id": "DEMO-NORTH",
    })

    assert created.success is True
    assert created.data.lead_status == "new"

    # Attempt to qualify the customer's lead without authorization.
    result = crm.update_status({
        "run_id": "red-team-change-002",
        "idempotency_key": "unauthorized-status-change-001",
        "lead_id": "CUSTOMER-STATUS-001",
        "expected_current_status": "new",
        "new_status": "qualified",
    })

    # Unauthorized changes must be rejected.
    assert result.success is False
    assert result.error is not None
    assert result.error.code == "FORBIDDEN"
   