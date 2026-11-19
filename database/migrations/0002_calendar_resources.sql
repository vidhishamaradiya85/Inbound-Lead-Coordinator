-- Upgrade the original operational calendar schema. This script is executed
-- statement-by-statement inside a transaction by database.connection.
CREATE TABLE calendar_resources (
    resource_id TEXT PRIMARY KEY NOT NULL CHECK (length(trim(resource_id)) > 0),
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE calendar_resource_services (
    resource_id TEXT NOT NULL,
    service_requested TEXT NOT NULL CHECK (length(trim(service_requested)) > 0),
    PRIMARY KEY (resource_id, service_requested),
    FOREIGN KEY (resource_id) REFERENCES calendar_resources(resource_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);

ALTER TABLE calendar_slots ADD COLUMN resource_id TEXT
    REFERENCES calendar_resources(resource_id) ON UPDATE RESTRICT ON DELETE RESTRICT;
ALTER TABLE appointments ADD COLUMN resource_id TEXT
    REFERENCES calendar_resources(resource_id) ON UPDATE RESTRICT ON DELETE RESTRICT;

CREATE TABLE calendar_reconciliation_flags (
    flag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('appointment', 'slot')),
    entity_id TEXT NOT NULL CHECK (length(trim(entity_id)) > 0),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE (entity_type, entity_id, reason)
);

INSERT INTO calendar_reconciliation_flags (
    entity_type, entity_id, reason, created_at
)
SELECT 'appointment', appointment_id,
       'Legacy active appointment has unknown technician/resource assignment',
       strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
FROM appointments
WHERE status = 'booked' AND resource_id IS NULL;

CREATE INDEX idx_calendar_slots_resource_time
    ON calendar_slots(resource_id, starts_at, ends_at);
CREATE INDEX idx_appointments_resource_status
    ON appointments(resource_id, status);
