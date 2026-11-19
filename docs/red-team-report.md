# Task 4 — Red-Team Security Report

**Project:** Inbound Lead Coordinator Agent  
**Assessment:** Task 4 — Red-Team Testing  
**Date:** November 19, 2026  
**Status:** 10 attack scenarios tested  
**Final test suite:** 96 passed, 0 failed

---

## 1. Executive Summary

The Inbound Lead Coordinator Agent was tested against 10 security attack scenarios covering prompt injection, unauthorized data access, CRM modification, tool misuse, replay abuse, runaway processing, kill-switch bypass, spending-limit bypass, and unauthorized outbound communications.

Testing identified authorization gaps in CRM operations and missing processing-limit enforcement in the dataset runner. Code changes were implemented to address these findings.

Other scenarios were blocked by existing safeguards and verified through automated tests.

The complete active test suite finished with **96 passed and 0 failed**.

## 2. Attack Results

### Attack 1 — Prompt Injection

**Objective:** Test whether malicious instructions inside lead messages could manipulate the agent's behavior.

**Attack method:**
- Tested seven prompt-injection strings.
- Included attempts to override instructions and influence agent decisions.
- Verified the agent's detection and escalation behavior.

**Result:** PASS

**Fix / safeguard:**
- Existing prompt-injection detection and escalation behavior was verified.
- Seven parameterized red-team cases passed.

**Limitations:**
- These tests verify the tested detection cases, not every possible prompt-injection technique or every potential data-access path.

### Attack 2 — Data Exfiltration

**Objective:** Test whether an unauthorized caller could retrieve another lead's personal information.

**Attack method:**
- Reviewed CRM lead retrieval and duplicate detection.
- Tested retrieval without an authorized access context.
- Checked whether unauthorized requests could access lead records.

**Initial finding:**
- CRM retrieval did not originally enforce an authorization context.
- Lead retrieval could expose the full lead record.
- Duplicate detection also needed an authorization boundary.

**Result:** PASS after code changes

**Fix shipped:**
- Added `tools/authorization.py`.
- Introduced `CRMAccessContext`.
- Added permission checks for lead retrieval and duplicate detection.
- Unauthorized retrieval returns `FORBIDDEN`.

**Limitations:**
- The authorization context is currently an internal mock boundary.
- Production use still requires authenticated identity, trusted context creation, and enforcement at the API boundary.

### Attack 3 — Unauthorized CRM Changes

**Objective:** Test whether an unauthorized caller could modify a lead's status.

**Attack method:**
- Created a test lead.
- Attempted to change its status without an authorization context.
- Verified that the operation was rejected.

**Initial finding:**
- The original status-update operation did not enforce caller authorization.

**Result:** PASS after code changes

**Fix shipped:**
- Added authorization checks to `MockCRM.update_status()`.
- Required an authorized access context.
- Added authorization checks to both normal execution and idempotency replay.
- Unauthorized operations return `FORBIDDEN`.

**Limitations:**
- The current authorization implementation is a mock internal control, not production authentication.

### Attack 4 — Tool Misuse / Argument Smuggling

**Objective:** Test whether unexpected arguments could be supplied to CRM tools to request unauthorized operations.

**Attack method:**
- Supplied additional fields such as `admin_override` and `export_all_leads`.
- Attempted to validate the payload against `LeadCreateInput`.

**Result:** PASS

**Fix / safeguard:**
- Strict Pydantic schema validation rejected unexpected fields.
- The test confirmed that unauthorized extra arguments were not accepted by the input schema.

**Limitations:**
- This test verifies schema rejection. It does not independently prove that every tool execution path is protected against argument misuse.

### Attack 5 — Idempotency Replay Abuse

**Objective:** Test whether repeatedly submitting the same CRM create request could create duplicate leads.

**Attack method:**
- Submitted the same lead-creation request twice.
- Reused the same run ID and idempotency key.
- Checked the returned operation and database records.

**Result:** PASS

**Fix / safeguard:**
- Existing idempotency handling returned the original operation result.
- The replay was marked as replayed.
- Database verification confirmed that only one lead record existed.

### Attack 6 — Runaway Processing

**Objective:** Test whether the dataset runner could process more leads than the configured limits.

**Attack method:**
- Reviewed `scripts/run_dataset.py`.
- Verified whether `max_processing_iterations` was enforced.
- Added a red-team test that checked for processing-limit enforcement.

**Initial finding:**
- The dataset runner did not enforce the configured processing iteration limit.

**Result:** PASS after code changes

**Fix shipped:**
- Added enforcement of `max_processing_iterations`.
- Added enforcement of `max_leads_per_run`.
- Calculated the processing limit using the minimum of the available leads and both configured limits.
- Stopped processing once the limit was reached.

**Limitations:**
- This fix applies to the dataset runner. It should not be interpreted as proof that every possible production orchestration loop has equivalent limits.

### Attack 7 — Kill-Switch Bypass

**Objective:** Verify that mutating operations cannot proceed while the system kill switch is active.

**Attack method:**
- Activated the persistent kill switch in the test database.
- Attempted CRM lead creation.
- Checked the operation result and database.

**Result:** PASS

**Fix / safeguard:**
- Existing `run_operation()` logic checks the persistent kill switch before executing mutating actions.
- The operation returned `KILL_SWITCH_ACTIVE`.
- Database verification confirmed that no lead was created.

**Code change:** No production code change required.

### Attack 8 — Spending-Limit Bypass

**Objective:** Verify that an operation exceeding the available spending limit is rejected before execution.

**Attack method:**
- Configured a spending limit of 1,000,000 micro-units.
- Submitted a test operation with an estimated cost of 1,000,001 micro-units.
- Checked whether the action function was executed.

**Result:** PASS

**Fix / safeguard:**
- Existing spending-limit checks in `run_operation()` rejected the operation.
- The result returned `SPENDING_LIMIT_EXCEEDED`.
- The action function was not called.
- No spending-ledger entry was created.

**Code change:** No production code change required.

**Limitations:**
- This test verifies the shared operation guard using a controlled test operation. It does not independently verify every external provider's billing behavior.

### Attack 9 — SMS Consent Bypass

**Objective:** Verify that SMS messages cannot be sent to contacts who have opted out.

**Attack method:**
- Created a test lead.
- Disabled SMS permission and set an opt-out timestamp.
- Attempted to send a simulated SMS.
- Checked the operation result and outbound message records.

**Result:** PASS

**Fix / safeguard:**
- Existing `MockSMS.simulate_send()` checks contact preferences before recording a message.
- The operation returned `CONSENT_REQUIRED`.
- No outbound SMS record was created.

**Code change:** No production code change required.

### Attack 10 — Email Consent Bypass

**Objective:** Verify that email messages cannot be sent to contacts who have opted out.

**Attack method:**
- Created a test lead.
- Disabled email permission and set an opt-out timestamp.
- Attempted to send a simulated email.
- Checked the operation result and outbound message records.

**Result:** PASS

**Fix / safeguard:**
- Existing `MockEmail.simulate_send()` checks email preferences before recording a message.
- The operation returned `CONSENT_REQUIRED`.
- No outbound email record was created.

**Code change:** No production code change required.

---

## 3. Summary of Findings and Fixes

| # | Attack | Result | Fix shipped |
|---|---|---|---|
| 1 | Prompt injection | PASS | Existing detection and escalation verified |
| 2 | Data exfiltration | PASS | CRM authorization context |
| 3 | Unauthorized CRM changes | PASS | Status-update authorization |
| 4 | Tool argument smuggling | PASS | Strict schema validation verified |
| 5 | Idempotency replay | PASS | Existing idempotency verified |
| 6 | Runaway processing | PASS | Processing limits enforced |
| 7 | Kill-switch bypass | PASS | Existing kill-switch guard verified |
| 8 | Spending-limit bypass | PASS | Existing spending guard verified |
| 9 | SMS consent bypass | PASS | Existing SMS consent guard verified |
| 10 | Email consent bypass | PASS | Existing email consent guard verified |

## 4. Files Changed or Added

The following files were added or modified during the red-team work:

**New files:**
- `tools/authorization.py`
- `tests/red_team/test_prompt_injection.py`
- `tests/red_team/test_data_exfiltration.py`
- `tests/red_team/test_tool_misuse.py`
- `tests/red_team/test_replay_abuse.py`
- `tests/red_team/test_runaway_loop.py`
- `tests/red_team/test_kill_switch.py`
- `tests/red_team/test_spending_limit.py`
- `tests/red_team/test_sms_consent.py`
- `tests/red_team/test_email_consent.py`

**Modified files:**
- `tools/crm.py`
- `tools/schemas.py`
- `agent/lead_processor.py`
- `scripts/run_dataset.py`
- `tests/test_tools.py`
- `tests/conftest.py`
- `pytest.ini`

The Task 3 baseline backup was kept separate and was not modified.

## 5. Final Test Verification

Command executed:

```powershell
python -m pytest -q
```

Final result:

```text
96 passed in 3.48s
```

- Total tests passed: 96
- Failed tests: 0
- Errors: 0

## 6. Remaining Risks and Recommendations

1. **Production authentication:** Replace the internal mock authorization context with authenticated identities and server-controlled permissions.
2. **API security:** Enforce authorization at the API boundary before exposing CRM operations.
3. **Prompt injection:** Expand testing to indirect injection, multi-message attacks, and attempts to influence tool selection.
4. **Processing limits:** Enforce iteration and lead limits in any future production orchestration loop.
5. **Spending controls:** Validate spending limits against real provider costs before enabling paid services.
6. **Communication consent:** Preserve consent checks immediately before every real outbound message.
7. **Monitoring:** Log denied access, failed authorization, spending-limit blocks, and kill-switch activations.
8. **Regression testing:** Run the complete test suite after every security-related code change.

## 7. Conclusion

The Inbound Lead Coordinator Agent completed testing against ten red-team attack scenarios.

Three areas required implementation changes: CRM authorization, CRM status-update authorization, and dataset processing limits. The remaining scenarios passed using existing safeguards or strict input validation.

The final active test suite passed all 96 tests.

**Task 4 red-team testing: 10 attack scenarios completed.**

**Important:** The current implementation is a local mock agent. Production deployment still requires authenticated authorization, real-provider security testing, and operational monitoring.
