PRAGMA foreign_keys = ON;

-- Runtime lead inputs and runtime processing outputs.
-- Expected labels and expected duplicate references belong only in the
-- evaluator-only evaluation_cases.json data path.
CREATE TABLE leads (
    lead_id TEXT PRIMARY KEY NOT NULL
        CHECK (lead_id GLOB 'SYN-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    source TEXT NOT NULL
        CHECK (source IN ('website', 'phone', 'sms', 'referral')),
    name TEXT,
    email TEXT,
    phone TEXT,
    raw_message TEXT NOT NULL
        CHECK (length(raw_message) > 0),
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

-- Evaluation labels are isolated from runtime lead fields. If loaded into
-- SQLite for evaluation, use an evaluator-only database/connection; the
-- normal agent data loader must not load or query this table.
CREATE TABLE evaluation_cases (
    case_id TEXT PRIMARY KEY NOT NULL
        CHECK (case_id GLOB 'CASE-[0-9][0-9][0-9][0-9][0-9][0-9]'),
    lead_id TEXT NOT NULL UNIQUE,
    primary_category TEXT NOT NULL
        CHECK (primary_category IN (
            'valid', 'duplicate', 'spam', 'angry_dissatisfied',
            'wrong_service_area', 'prompt_injection', 'incomplete_invalid'
        )),
    expected_outcome TEXT NOT NULL
        CHECK (expected_outcome IN (
            'qualify', 'deduplicate', 'reject_spam', 'escalate',
            'reject_out_of_area', 'request_more_info', 'reject_invalid'
        )),
    expected_risk_flags_json TEXT NOT NULL DEFAULT '[]'
        CHECK (
            json_valid(expected_risk_flags_json)
            AND json_type(expected_risk_flags_json) = 'array'
        ),
    expected_escalation_reason TEXT,
    expected_duplicate_of_lead_id TEXT,
    FOREIGN KEY (lead_id)
        REFERENCES leads(lead_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    FOREIGN KEY (expected_duplicate_of_lead_id)
        REFERENCES leads(lead_id)
        ON UPDATE RESTRICT
        ON DELETE RESTRICT,
    CHECK (
        expected_duplicate_of_lead_id IS NULL
        OR expected_duplicate_of_lead_id <> lead_id
    ),
    CHECK (
        (primary_category = 'duplicate' AND expected_duplicate_of_lead_id IS NOT NULL)
        OR
        (primary_category <> 'duplicate' AND expected_duplicate_of_lead_id IS NULL)
    )
);

CREATE INDEX idx_leads_created_at ON leads(created_at);
CREATE INDEX idx_leads_status_created_at ON leads(lead_status, created_at);
CREATE INDEX idx_leads_email ON leads(email);
CREATE INDEX idx_leads_phone ON leads(phone);
CREATE INDEX idx_evaluation_cases_category
    ON evaluation_cases(primary_category);

