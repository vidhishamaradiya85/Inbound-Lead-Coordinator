def test_repeated_crm_create_request_does_not_create_duplicate_leads(enabled_tools):
    crm = enabled_tools["crm"]

    payload = {
        "run_id": "red-team-replay-001",
        "idempotency_key": "red-team-replay-key-001",
        "lead_id": "REPLAY-LEAD-001",
        "source": "website",
        "name": "Replay Test",
        "email": "replay@example.test",
        "phone": "+1 202 555 0147",
        "raw_message": "Please schedule a heating inspection.",
        "service_requested": "heating inspection",
        "service_area_id": "DEMO-NORTH",
    }

    first = crm.create_lead(payload)
    replay = crm.create_lead(payload)

    assert first.success
    assert replay.success
    assert replay.replayed
    assert replay.operation_id == first.operation_id
    assert replay.data == first.data

    count = crm.connection.execute(
        "SELECT COUNT(*) FROM leads WHERE lead_id = ?",
        ("REPLAY-LEAD-001",),
    ).fetchone()[0]

    assert count == 1