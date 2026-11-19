-- Strengthen booking and timestamp guards for both fresh and upgraded databases.
DROP TRIGGER IF EXISTS trg_appointments_resource_insert;
DROP TRIGGER IF EXISTS trg_appointments_resource_update;
DROP TRIGGER IF EXISTS trg_calendar_slot_assignment_immutable_while_booked;
DROP TRIGGER IF EXISTS trg_calendar_slot_timestamp_insert;
DROP TRIGGER IF EXISTS trg_calendar_slot_timestamp_update;

CREATE TRIGGER trg_appointments_resource_insert
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
        JOIN leads AS l ON l.lead_id = NEW.lead_id
        WHERE s.slot_id = NEW.slot_id
          AND s.resource_id = NEW.resource_id
          AND s.is_active = 1
          AND l.service_requested = s.service_requested
          AND l.service_area_id = s.service_area_id
          AND r.is_active = 1
    ) THEN RAISE(ABORT, 'inactive, unassigned, or incompatible calendar booking') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM appointments AS a
        JOIN calendar_slots AS existing_slot ON existing_slot.slot_id = a.slot_id
        JOIN calendar_slots AS new_slot ON new_slot.slot_id = NEW.slot_id
        WHERE a.status = 'booked'
          AND (a.resource_id IS NULL OR a.resource_id = NEW.resource_id)
          AND new_slot.starts_at < existing_slot.ends_at
          AND existing_slot.starts_at < new_slot.ends_at
    ) THEN RAISE(ABORT, 'overlapping active appointment') END;
END;

CREATE TRIGGER trg_appointments_resource_update
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
        JOIN leads AS l ON l.lead_id = NEW.lead_id
        WHERE s.slot_id = NEW.slot_id
          AND s.resource_id = NEW.resource_id
          AND s.is_active = 1
          AND l.service_requested = s.service_requested
          AND l.service_area_id = s.service_area_id
          AND r.is_active = 1
    ) THEN RAISE(ABORT, 'inactive, unassigned, or incompatible calendar booking') END;

    SELECT CASE WHEN EXISTS (
        SELECT 1
        FROM appointments AS a
        JOIN calendar_slots AS existing_slot ON existing_slot.slot_id = a.slot_id
        JOIN calendar_slots AS new_slot ON new_slot.slot_id = NEW.slot_id
        WHERE a.status = 'booked'
          AND a.appointment_id <> NEW.appointment_id
          AND (a.resource_id IS NULL OR a.resource_id = NEW.resource_id)
          AND new_slot.starts_at < existing_slot.ends_at
          AND existing_slot.starts_at < new_slot.ends_at
    ) THEN RAISE(ABORT, 'overlapping active appointment') END;
END;

CREATE TRIGGER trg_calendar_slot_assignment_immutable_while_booked
BEFORE UPDATE OF resource_id, starts_at, ends_at, service_requested, service_area_id, is_active
ON calendar_slots
WHEN EXISTS (
    SELECT 1 FROM appointments AS a
    WHERE a.slot_id = OLD.slot_id AND a.status = 'booked'
)
BEGIN
    SELECT RAISE(ABORT, 'calendar slot has an active appointment');
END;

CREATE TRIGGER trg_calendar_slot_timestamp_insert
BEFORE INSERT ON calendar_slots
WHEN NEW.starts_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
  OR NEW.ends_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
  OR strftime('%Y-%m-%dT%H:%M:%SZ', NEW.starts_at) IS NOT NEW.starts_at
  OR strftime('%Y-%m-%dT%H:%M:%SZ', NEW.ends_at) IS NOT NEW.ends_at
BEGIN
    SELECT RAISE(ABORT, 'calendar slot timestamps must be canonical UTC');
END;

CREATE TRIGGER trg_calendar_slot_timestamp_update
BEFORE UPDATE OF starts_at, ends_at ON calendar_slots
WHEN NEW.starts_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
  OR NEW.ends_at NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z'
  OR strftime('%Y-%m-%dT%H:%M:%SZ', NEW.starts_at) IS NOT NEW.starts_at
  OR strftime('%Y-%m-%dT%H:%M:%SZ', NEW.ends_at) IS NOT NEW.ends_at
BEGIN
    SELECT RAISE(ABORT, 'calendar slot timestamps must be canonical UTC');
END;
