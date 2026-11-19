def test_spending_limit_blocks_action_when_budget_is_exhausted(
    db, settings
):
    from tools.common import ActionResult, run_operation
    from tools.schemas import LeadCreateInput

    db.execute(
        """
        UPDATE system_controls
        SET kill_switch_active = 0,
            spending_limit_micros = 1000000
        WHERE control_id = 1
        """
    )

    request = LeadCreateInput.model_validate({
        "run_id": "red-team-spending-001",
        "idempotency_key": "spending-limit-001",
        "lead_id": "SPENDING-TEST-001",
        "source": "website",
        "name": "Spending Test",
        "email": "spending@example.test",
        "phone": "+1 202 555 0147",
        "raw_message": "Please schedule a heating inspection.",
        "service_requested": "heating inspection",
        "service_area_id": "DEMO-NORTH",
    })

    called = False

    def action(connection, operation_id):
        nonlocal called
        called = True
        return ActionResult({"created": True}, None)

    result = run_operation(
        db,
        request,
        tool_name="red_team",
        operation_name="spending_test",
        mutating=True,
        action=action,
        replay=lambda connection, resource_id: {"created": True},
        settings=settings,
        estimated_cost_micros=1000001,
    )

    assert result.success is False
    assert result.error.code == "SPENDING_LIMIT_EXCEEDED"
    assert called is False

    assert db.execute(
        "SELECT COUNT(*) FROM spending_ledger"
    ).fetchone()[0] == 0