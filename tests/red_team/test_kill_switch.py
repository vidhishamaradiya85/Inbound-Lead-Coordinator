def test_kill_switch_blocks_crm_lead_creation(enabled_tools, db):
    crm = enabled_tools["crm"]

    db.execute(
        "UPDATE system_controls SET kill_switch_active = 1 WHERE control_id = 1"
    )

    result = crm.create_lead({
        "run_id": "red-team-kill-001",
        "idempotency_key": "kill-switch-create-001",
        "lead_id": "KILL-TEST-001",
        "source": "website",
        "name": "Kill Switch Test",
        "email": "kill@example.test",
        "phone": "+1 202 555 0147",
        "raw_message": "Please schedule a heating inspection.",
        "service_requested": "heating inspection",
        "service_area_id": "DEMO-NORTH",
    })

    assert result.success is False
    assert result.error.code == "KILL_SWITCH_ACTIVE"

    count = db.execute(
        "SELECT COUNT(*) FROM leads WHERE lead_id = ?",
        ("KILL-TEST-001",),
    ).fetchone()[0]

    assert count == 0