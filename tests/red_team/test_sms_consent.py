def test_sms_send_is_blocked_when_contact_has_opted_out(enabled_tools, db):
    crm = enabled_tools["crm"]
    sms = enabled_tools["sms"]

    created = crm.create_lead({
        "run_id": "red-team-sms-001",
        "idempotency_key": "sms-consent-create-001",
        "lead_id": "SMS-OPT-OUT-001",
        "source": "website",
        "name": "SMS Opt Out Test",
        "email": "sms-optout@example.test",
        "phone": "+1 202 555 0147",
        "raw_message": "Please contact me about heating.",
        "service_requested": "heating",
        "service_area_id": "DEMO-NORTH",
    })

    assert created.success is True

    db.execute(
        """
        UPDATE contact_preferences
        SET sms_allowed = 0,
            opted_out_at = '2026-11-19T10:00:00Z'
        WHERE lead_id = ?
        """,
        ("SMS-OPT-OUT-001",),
    )

    result = sms.simulate_send({
        "run_id": "red-team-sms-001",
        "idempotency_key": "sms-consent-send-001",
        "lead_id": "SMS-OPT-OUT-001",
        "purpose": "lead_follow_up_1",
        "body": "Following up on your enquiry.",
    })

    assert result.success is False
    assert result.error.code == "CONSENT_REQUIRED"

    count = db.execute(
        """
        SELECT COUNT(*) FROM outbound_messages
        WHERE lead_id = ? AND channel = 'sms'
        """,
        ("SMS-OPT-OUT-001",),
    ).fetchone()[0]

    assert count == 0