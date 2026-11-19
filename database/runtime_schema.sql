PRAGMA foreign_keys = ON;

-- Operational schema only. Evaluator labels and evaluation_cases are excluded.
CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(lead_id)) > 0),
    source TEXT NOT NULL CHECK (source IN ('website', 'phone', 'sms', 'referral')),
    name TEXT,
    email TEXT,
    phone TEXT,
    raw_message TEXT NOT NULL CHECK (length(raw_message) > 0),
    service_requested TEXT,
    address_text TEXT,
    service_area_id TEXT,
    created_at TEXT NOT NULL,
    lead_status TEXT NOT NULL DEFAULT 'new'
        CHECK (lead_status IN (
            'new', 'in_progress', 'qualified', 'rejected',
            'duplicate', 'escalated', 'needs_info', 'mock_booked'
        )),
    qualification_status TEXT NOT NULL DEFAULT 'not_evaluated'
        CHECK (qualification_status IN (
            'not_evaluated', 'qualified', 'unqualified', 'needs_review', 'needs_info'
        )),
    qualification_score REAL
        CHECK (
            qualification_score IS NULL
            OR (qualification_score >= 0.0 AND qualification_score <= 1.0)
        ),
    qualification_reason TEXT,
    service_area_eligible INTEGER
        CHECK (service_area_eligible IS NULL OR service_area_eligible IN (0, 1)),
    detected_risk_flags_json TEXT NOT NULL DEFAULT '[]'
        CHECK (
            json_valid(detected_risk_flags_json)
            AND json_type(detected_risk_flags_json) = 'array'
        ),
    escalation_reason TEXT,
    detected_duplicate_of_lead_id TEXT,
    FOREIGN KEY (detected_duplicate_of_lead_id)
        REFERENCES leads(lead_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CHECK (
        detected_duplicate_of_lead_id IS NULL
        OR detected_duplicate_of_lead_id <> lead_id
    )
);

CREATE TABLE IF NOT EXISTS calendar_resources (
    resource_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(resource_id)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendar_resource_services (
    resource_id TEXT NOT NULL,
    service_requested TEXT NOT NULL CHECK (length(trim(service_requested)) > 0),
    PRIMARY KEY (resource_id, service_requested),
    FOREIGN KEY (resource_id) REFERENCES calendar_resources(resource_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS calendar_slots (
    slot_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(slot_id)) > 0),
    service_area_id TEXT NOT NULL CHECK (length(trim(service_area_id)) > 0),
    service_requested TEXT NOT NULL CHECK (length(trim(service_requested)) > 0),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    resource_id TEXT,
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    CHECK (starts_at < ends_at),
    CHECK (
        length(starts_at) = 20
        AND starts_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
        AND strftime('%Y-%m-%dT%H:%M:%SZ', starts_at) IS NOT NULL
        AND strftime('%Y-%m-%dT%H:%M:%SZ', starts_at) = starts_at
    ),
    CHECK (
        length(ends_at) = 20
        AND ends_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
        AND strftime('%Y-%m-%dT%H:%M:%SZ', ends_at) IS NOT NULL
        AND strftime('%Y-%m-%dT%H:%M:%SZ', ends_at) = ends_at
    ),
    UNIQUE (service_area_id, service_requested, starts_at),
    FOREIGN KEY (resource_id) REFERENCES calendar_resources(resource_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS contact_preferences (
    lead_id TEXT PRIMARY KEY NOT NULL,
    sms_allowed INTEGER NOT NULL DEFAULT 0 CHECK (sms_allowed IN (0, 1)),
    email_allowed INTEGER NOT NULL DEFAULT 0 CHECK (email_allowed IN (0, 1)),
    opted_out_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (lead_id)
        REFERENCES leads(lead_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tool_operations (
    operation_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(operation_id)) > 0),
    tool_name TEXT NOT NULL CHECK (length(trim(tool_name)) > 0),
    operation_name TEXT NOT NULL CHECK (length(trim(operation_name)) > 0),
    idempotency_key TEXT NOT NULL CHECK (length(trim(idempotency_key)) BETWEEN 1 AND 128),
    request_hash TEXT NOT NULL CHECK (length(request_hash) = 64),
    status TEXT NOT NULL DEFAULT 'started'
        CHECK (status IN ('started', 'succeeded', 'failed')),
    result_code TEXT,
    resource_id TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    UNIQUE (tool_name, operation_name, idempotency_key)
);

CREATE TABLE IF NOT EXISTS appointments (
    appointment_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(appointment_id)) > 0),
    lead_id TEXT NOT NULL,
    slot_id TEXT NOT NULL,
    resource_id TEXT,
    operation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'booked'
        CHECK (status IN ('booked', 'cancelled')),
    created_at TEXT NOT NULL,
    cancelled_at TEXT,
    FOREIGN KEY (lead_id)
        REFERENCES leads(lead_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    FOREIGN KEY (slot_id)
        REFERENCES calendar_slots(slot_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    FOREIGN KEY (resource_id)
        REFERENCES calendar_resources(resource_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    FOREIGN KEY (operation_id)
        REFERENCES tool_operations(operation_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT
);

-- A slot can have only one active booking; cancelled slots can be booked again.
CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_one_active_booking_per_slot
    ON appointments(slot_id)
    WHERE status = 'booked';

CREATE TABLE IF NOT EXISTS calendar_reconciliation_flags (
    flag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('appointment', 'slot')),
    entity_id TEXT NOT NULL CHECK (length(trim(entity_id)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE (entity_type, entity_id, reason)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id TEXT PRIMARY KEY NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS trg_appointments_resource_insert
BEFORE INSERT ON appointments
WHEN NEW.status = 'booked'
BEGIN
    SELECT CASE WHEN NEW.resource_id IS NULL OR NOT EXISTS (
        SELECT 1
        FROM calendar_slots AS s
        JOIN calendar_resources AS r ON r.resource_id = s.resource_id
        JOIN calendar_resource_services AS rs
          ON rs.resource_id = r.resource_id
         AND rs.service_requested = s.service_requested
        WHERE s.slot_id = NEW.slot_id
          AND s.resource_id = NEW.resource_id
          AND s.is_active = 1
          AND EXISTS (
              SELECT 1 FROM leads AS l
              WHERE l.lead_id = NEW.lead_id
                AND l.service_requested = s.service_requested
                AND l.service_area_id = s.service_area_id
          )
          AND r.is_active = 1
    ) THEN RAISE(ABORT, 'unassigned or incompatible calendar resource') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM appointments AS a
        JOIN calendar_slots AS existing_slot ON existing_slot.slot_id = a.slot_id
        JOIN calendar_slots AS new_slot ON new_slot.slot_id = NEW.slot_id
        WHERE a.status = 'booked'
          AND (
              a.resource_id IS NULL
              OR a.resource_id = NEW.resource_id
          )
          AND new_slot.starts_at < existing_slot.ends_at
          AND existing_slot.starts_at < new_slot.ends_at
    ) THEN RAISE(ABORT, 'overlapping active appointment') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_appointments_resource_update
BEFORE UPDATE OF slot_id, status, resource_id ON appointments
WHEN NEW.status = 'booked'
BEGIN
    SELECT CASE WHEN NEW.resource_id IS NULL OR NOT EXISTS (
        SELECT 1
        FROM calendar_slots AS s
        JOIN calendar_resources AS r ON r.resource_id = s.resource_id
        JOIN calendar_resource_services AS rs
          ON rs.resource_id = r.resource_id
         AND rs.service_requested = s.service_requested
        WHERE s.slot_id = NEW.slot_id
          AND s.resource_id = NEW.resource_id
          AND s.is_active = 1
          AND EXISTS (
              SELECT 1 FROM leads AS l
              WHERE l.lead_id = NEW.lead_id
                AND l.service_requested = s.service_requested
                AND l.service_area_id = s.service_area_id
          )
          AND r.is_active = 1
    ) THEN RAISE(ABORT, 'unassigned or incompatible calendar resource') END;
    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM appointments AS a
        JOIN calendar_slots AS existing_slot ON existing_slot.slot_id = a.slot_id
        JOIN calendar_slots AS new_slot ON new_slot.slot_id = NEW.slot_id
        WHERE a.status = 'booked'
          AND a.appointment_id <> NEW.appointment_id
          AND (
              a.resource_id IS NULL
              OR a.resource_id = NEW.resource_id
          )
          AND new_slot.starts_at < existing_slot.ends_at
          AND existing_slot.starts_at < new_slot.ends_at
    ) THEN RAISE(ABORT, 'overlapping active appointment') END;
END;

CREATE TRIGGER IF NOT EXISTS trg_calendar_slot_assignment_immutable_while_booked
BEFORE UPDATE OF resource_id, starts_at, ends_at, service_requested, service_area_id, is_active
ON calendar_slots
WHEN EXISTS (
    SELECT 1 FROM appointments AS a
    WHERE a.slot_id = OLD.slot_id AND a.status = 'booked'
)
BEGIN
    SELECT RAISE(ABORT, 'calendar slot has an active appointment');
END;

CREATE TRIGGER IF NOT EXISTS trg_appointment_resource_immutable_while_booked
BEFORE UPDATE OF resource_id ON appointments
WHEN OLD.status = 'booked' AND NEW.status = 'booked'
     AND NEW.resource_id IS NOT OLD.resource_id
BEGIN
    SELECT RAISE(ABORT, 'active appointment resource cannot be changed');
END;

CREATE TRIGGER IF NOT EXISTS trg_resource_deactivation_guard
BEFORE UPDATE OF is_active ON calendar_resources
WHEN NEW.is_active = 0 AND OLD.is_active <> 0 AND EXISTS (
    SELECT 1
    FROM appointments AS a
    WHERE a.resource_id = OLD.resource_id AND a.status = 'booked'
)
BEGIN
    SELECT RAISE(ABORT, 'resource has active appointments');
END;

CREATE TRIGGER IF NOT EXISTS trg_resource_service_delete_guard
BEFORE DELETE ON calendar_resource_services
WHEN EXISTS (
    SELECT 1 FROM appointments AS a
    WHERE a.resource_id = OLD.resource_id
      AND a.status = 'booked'
      AND EXISTS (
          SELECT 1 FROM calendar_slots AS s
          WHERE s.slot_id = a.slot_id
            AND s.service_requested = OLD.service_requested
      )
)
BEGIN
    SELECT RAISE(ABORT, 'resource service has active appointments');
END;

CREATE TRIGGER IF NOT EXISTS trg_resource_service_update_guard
BEFORE UPDATE OF resource_id, service_requested ON calendar_resource_services
WHEN EXISTS (
    SELECT 1 FROM appointments AS a
    WHERE a.resource_id = OLD.resource_id AND a.status = 'booked'
)
BEGIN
    SELECT RAISE(ABORT, 'resource services have active appointments');
END;

CREATE TRIGGER IF NOT EXISTS trg_calendar_slot_timestamp_insert
BEFORE INSERT ON calendar_slots
WHEN NEW.starts_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
  OR NEW.ends_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
  OR strftime('%Y-%m-%dT%H:%M:%SZ', NEW.starts_at) IS NOT NEW.starts_at
  OR strftime('%Y-%m-%dT%H:%M:%SZ', NEW.ends_at) IS NOT NEW.ends_at
BEGIN
    SELECT RAISE(ABORT, 'calendar slot timestamps must be canonical UTC');
END;

CREATE TRIGGER IF NOT EXISTS trg_calendar_slot_timestamp_update
BEFORE UPDATE OF starts_at, ends_at ON calendar_slots
WHEN NEW.starts_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
  OR NEW.ends_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
  OR strftime('%Y-%m-%dT%H:%M:%SZ', NEW.starts_at) IS NOT NEW.starts_at
  OR strftime('%Y-%m-%dT%H:%M:%SZ', NEW.ends_at) IS NOT NEW.ends_at
BEGIN
    SELECT RAISE(ABORT, 'calendar slot timestamps must be canonical UTC');
END;

CREATE TABLE IF NOT EXISTS outbound_messages (
    message_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(message_id)) > 0),
    lead_id TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('sms', 'email')),
    purpose TEXT NOT NULL CHECK (length(trim(purpose)) > 0),
    logical_action_key TEXT NOT NULL CHECK (length(trim(logical_action_key)) > 0),
    destination TEXT NOT NULL CHECK (length(trim(destination)) > 0),
    subject TEXT,
    body TEXT NOT NULL CHECK (length(body) > 0),
    status TEXT NOT NULL DEFAULT 'simulated'
        CHECK (status IN ('simulated', 'blocked', 'failed')),
    operation_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY (lead_id)
        REFERENCES leads(lead_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    FOREIGN KEY (operation_id)
        REFERENCES tool_operations(operation_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CHECK (channel = 'email' OR subject IS NULL),
    UNIQUE (channel, logical_action_key)
);

CREATE TABLE IF NOT EXISTS system_controls (
    control_id INTEGER PRIMARY KEY CHECK (control_id = 1),
    kill_switch_active INTEGER NOT NULL DEFAULT 1 CHECK (kill_switch_active IN (0, 1)),
    kill_switch_activated_at TEXT,
    kill_switch_changed_by TEXT NOT NULL DEFAULT 'system',
    kill_switch_reason TEXT NOT NULL DEFAULT 'Initial fail-safe state',
    spending_limit_micros INTEGER NOT NULL DEFAULT 0 CHECK (spending_limit_micros >= 0),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spending_ledger (
    ledger_entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL CHECK (length(trim(run_id)) > 0),
    operation_id TEXT NOT NULL,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('reservation', 'charge', 'release', 'refund')),
    amount_micros INTEGER NOT NULL CHECK (amount_micros >= 0),
    created_at TEXT NOT NULL,
    FOREIGN KEY (operation_id)
        REFERENCES tool_operations(operation_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    UNIQUE (operation_id, entry_type)
);

CREATE INDEX IF NOT EXISTS idx_leads_status_created_at
    ON leads(lead_status, created_at);
CREATE INDEX IF NOT EXISTS idx_leads_email
    ON leads(email);
CREATE INDEX IF NOT EXISTS idx_leads_phone
    ON leads(phone);
CREATE INDEX IF NOT EXISTS idx_calendar_slots_area_service_start
    ON calendar_slots(service_area_id, service_requested, starts_at, is_active);
CREATE INDEX IF NOT EXISTS idx_calendar_slots_resource_time
    ON calendar_slots(resource_id, starts_at, ends_at);
CREATE INDEX IF NOT EXISTS idx_appointments_resource_status
    ON appointments(resource_id, status);
CREATE INDEX IF NOT EXISTS idx_appointments_lead_status
    ON appointments(lead_id, status);
CREATE INDEX IF NOT EXISTS idx_outbound_messages_lead_created_at
    ON outbound_messages(lead_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tool_operations_created_at
    ON tool_operations(created_at);
CREATE INDEX IF NOT EXISTS idx_spending_ledger_run_id
    ON spending_ledger(run_id, created_at);
