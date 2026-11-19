# Development Plan – Inbound Lead Coordinator

## Project Objective

Build an autonomous AI-powered Inbound Lead Coordinator for a home services company.

The agent must receive leads, understand customer requirements, qualify leads, book estimates, send follow-ups, maintain customer records and escalate uncertain cases.

The initial implementation must use synthetic data and mock integrations.

## Phase 1 – Project Foundation
- Establish project folder structure.
- Configure Python environment.
- Establish project configuration.
- Configure environment variables.
- Document security requirements.
- Verify project instructions and permissions.

**Completion criteria:** Project structure is ready and security documentation is verified.

## Phase 2 – Synthetic Lead Dataset
- Generate at least 200 synthetic lead records.
- Include website, call and SMS lead sources.
- Include duplicate leads.
- Include spam submissions.
- Include angry customers.
- Include incorrect contact details.
- Include customers outside the service area.
- Include prompt injection attempts.
- Include incomplete and ambiguous enquiries.

**Completion criteria:** Dataset contains at least 200 testable lead records and all required difficult cases.

## Phase 3 – Mock Business Tools
Develop four mock tools:

1. CRM:
   - Find customers.
   - Create customers.
   - Update customer records.
   - Identify duplicates.

2. Calendar:
   - Check available slots.
   - Book estimates.
   - Check existing bookings.
   - Cancel bookings safely.

3. SMS:
   - Simulate outgoing messages.
   - Record message status.
   - Prevent duplicate messages.

4. Email:
   - Simulate outgoing emails.
   - Record email status.
   - Prevent duplicate emails.

All tools must use strict input and output schemas.

**Completion criteria:** All four tools work locally and reject invalid or unauthorized requests.

## Phase 4 – Agent Decision Engine
Develop the agent's decision-making functionality.

The agent must:
- Understand incoming customer enquiries.
- Identify requested services.
- Extract relevant customer information.
- Check service-area eligibility.
- Identify spam and suspicious content.
- Identify customer complaints.
- Check customer contact preferences.
- Assign confidence scores.
- Decide whether to qualify, reject or escalate a lead.

**Completion criteria:** The agent produces validated decisions for different lead scenarios.

## Phase 5 – Autonomous Processing Loop
- Automatically retrieve pending leads.
- Process leads without manual intervention between steps.
- Select appropriate tools.
- Execute approved actions.
- Check tool results.
- Update lead status.
- Continue processing the queue.
- Stop safely when execution limits are reached.

**Completion criteria:** The agent processes multiple leads automatically until the queue is empty or a safety condition stops execution.

## Phase 6 – Database and Persistent Memory
Use SQLite for the initial implementation.

Store:
- Leads.
- Customer records.
- Processing status.
- Agent memory.
- Booking records.
- Tool actions.
- Retry attempts.
- Dead-letter records.
- Budget usage.
- Execution traces.
- Kill-switch status.

Memory must:
- Persist between application runs.
- Store relevant verified customer information.
- Preserve previous actions.
- Avoid unnecessary sensitive information.
- Support controlled updates and expiry.

**Completion criteria:** Restarting the application does not erase existing records or agent memory.

## Phase 7 – Security and Guardrails
Implement:
- Prompt injection protection.
- Input validation.
- Strict tool permissions.
- Database access restrictions.
- Customer data isolation.
- PII and secret redaction.
- Confidence thresholds.
- Human escalation.
- Spending limits.
- Persistent kill switch.
- Safe execution limits.

**Completion criteria:** Every major security control has an automated test and recorded result.

## Phase 8 – Retry and Failure Handling
Implement:
- Operation timeouts.
- Bounded retries.
- Exponential backoff with jitter.
- Idempotency keys.
- Duplicate action prevention.
- Failure classification.
- Dead-letter queue.
- Safe recovery from uncertain operations.

**Completion criteria:** Temporary failures recover safely, repeated failures stop after configured limits, and duplicate actions are prevented.

## Phase 9 – Tracing and Cost Tracking
Record:
- Lead processing stages.
- Agent decisions.
- Tool calls.
- Tool responses.
- Errors.
- Retry attempts.
- Execution duration.
- Model usage.
- Estimated processing cost.

Generate:
- Execution reports.
- Error reports.
- Cost per lead report.
- Processing summary.

**Completion criteria:** Every important decision and tool action can be traced using a unique execution ID.

## Phase 10 – Evaluation Suite
Develop at least 30 evaluation cases.

Include:
- Normal qualified leads.
- Unqualified leads.
- Duplicate leads.
- Spam.
- Angry customers.
- Invalid contact information.
- Outside-service-area requests.
- Prompt injection.
- Unauthorized tool requests.
- Booking failures.
- Retry failures.
- Budget exhaustion.
- Kill-switch activation.
- Customer data protection.

Generate automated pass/fail reports.

**Completion criteria:** At least 30 evaluation cases execute and produce a documented pass/fail report.

## Phase 11 – Red-Team Preparation
Prepare the agent for Task 4.

- Create at least 10 attack scenarios.
- Test direct prompt injection.
- Test indirect prompt injection.
- Test customer data exfiltration.
- Test unauthorized tool usage.
- Test duplicate actions.
- Test runaway loops.
- Test budget exhaustion.
- Test logging exposure.
- Record attack results.
- Implement and test fixes.

**Completion criteria:** Each attack has a documented result, mitigation and residual risk.

## Phase 12 – Final Deliverables
Prepare:
- Complete source repository.
- README.md.
- requirements.txt.
- .env.example.
- One-command execution script.
- Synthetic dataset.
- Evaluation reports.
- Test reports.
- Red-team report.
- Five-minute demonstration recording.

**Completion criteria:** The project can be set up and run using the documented instructions, and all deliverables are prepared for review.

## Global Development Rules
- Follow AGENTS.md and SECURITY_RULES.md.
- Work on one approved phase at a time.
- Do not skip security requirements.
- Do not install unnecessary dependencies.
- Do not use real customer data.
- Do not connect real messaging or booking services in the initial demo.
- Test every important feature.
- Document failures and limitations.
- Never claim unverified functionality is complete.

## Final Project Goal

Deliver a working, autonomous, secure and testable Inbound Lead Coordinator Agent that satisfies the Task 3 requirements and is ready for Task 4 red-team testing.
