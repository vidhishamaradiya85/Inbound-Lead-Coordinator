# Inbound Lead Coordinator Agent

## 1. Project Overview

The Inbound Lead Coordinator Agent is an autonomous lead-management system designed to process incoming leads, qualify them, check appointment availability, manage follow-ups, and escalate cases that require human attention.

The project is being developed as part of a technical assessment.

The initial version will use synthetic lead data and mock CRM, calendar, SMS, and email tools. It will not contact real customers or create real bookings.

## 2. Main Objectives

- Process incoming leads automatically.
- Identify duplicate, spam, invalid, and genuine leads.
- Qualify leads based on predefined business rules.
- Check service-area eligibility.
- Check available appointment slots.
- Create mock appointments for eligible leads.
- Send simulated confirmations and follow-ups.
- Escalate complaints, uncertain cases, and high-risk situations to a human.
- Maintain persistent lead state and interaction history.
- Record decisions, tool calls, errors, and estimated costs.

## 3. Technology Stack

| Component               | Technology                   |
| ----------------------- | ---------------------------- |
| Programming language    | Python                       |
| Database                | SQLite                       |
| Lead data               | Synthetic dataset            |
| CRM                     | Mock CRM tool                |
| Calendar                | Mock Calendar tool           |
| Messaging               | Mock SMS and Email tools     |
| Agent execution         | Python-based autonomous loop |
| Testing                 | Automated evaluation suite   |
| Development environment | VS Code with Codex           |

An optional AI model integration may be added later. The initial implementation should be capable of running locally without requiring a paid AI API.

## 4. Agent Workflow

1. Receive an incoming lead.
2. Validate and normalize the lead information.
3. Check for duplicates and spam.
4. Identify the lead's intent and requirements.
5. Check service-area eligibility and contactability.
6. Decide whether the lead can proceed automatically.
7. Check mock calendar availability.
8. Create a mock appointment when appropriate.
9. Send a simulated confirmation.
10. Schedule eligible follow-ups for leads who have not booked.
11. Escalate uncertain, sensitive, or high-risk cases.
12. Save the outcome and complete execution logs.

## 5. Safety and Security

The application must enforce security independently of the AI agent.

Key requirements:

- Human approval for sensitive or high-risk actions.
- Configurable spending and execution limits.
- Confidence thresholds for automated decisions.
- Persistent kill switch.
- Idempotent tool operations.
- Bounded retries and timeouts.
- Input validation and strict tool schemas.
- Protection against prompt injection and data leakage.
- No unrestricted database, filesystem, URL, or command access.
- Logging and traceability for every decision and tool call.

Refer to `SECURITY_RULES.md` for detailed requirements.

## 6. Initial Demo Restrictions

The initial assessment version will:

- Use synthetic lead records only.
- Use mock CRM, calendar, SMS, and email tools.
- Avoid real customer communication.
- Avoid real appointment bookings.
- Avoid payment processing.
- Run locally using SQLite.
- Avoid unnecessary paid services.

## 7. Development Plan

Implementation will follow the stages documented in `DEVELOPMENT_PLAN.md`:

1. Project foundation
2. Synthetic lead dataset (200+ records)
3. Mock CRM, calendar, SMS, and email tools
4. Agent decision engine
5. Autonomous processing loop
6. SQLite and persistent memory
7. Security and guardrails
8. Retry and failure handling
9. Tracing and cost tracking
10. Evaluation suite (30+ cases)
11. Red-team preparation
12. Final deliverables

## 8. Project Status

**Current status:** Documentation and initial project guardrails established.

**Implementation status:** Not started.

Features will be marked complete only after implementation and verification.

## 9. Setup and Execution

Setup instructions and the one-command run instruction will be added after the project structure and execution scripts are implemented.

## 10. Testing

The project will include:

- Automated evaluation cases.
- Security and guardrail tests.
- Duplicate-processing tests.
- Retry and failure-handling tests.
- Persistent-state tests.
- Cost-per-lead reporting.
- Pass/fail evaluation results.

Exact test commands will be documented once the test runner is established.

## 11. Final Deliverables

- Working autonomous lead coordinator agent.
- Synthetic dataset containing at least 200 leads.
- Mock CRM, calendar, SMS, and email tools.
- Persistent database and agent state.
- Security guardrails and kill switch.
- Execution traces and cost reporting.
- Evaluation suite containing at least 30 cases.
- README and one-command run script.
- Five-minute video walkthrough.
- Red-team report documenting at least 10 attacks, their results, and fixes.
