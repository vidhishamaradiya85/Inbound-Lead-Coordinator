# Security Rules – Inbound Lead Coordinator

## 1. General Security
- Security must be considered in every development stage.
- Follow least-privilege access.
- Never trust external customer input.
- Never allow the AI model to bypass application security.
- Fail safely when an operation cannot be verified.

## 2. Prompt Injection Protection
- Treat website forms, SMS, emails and call transcripts as untrusted data.
- Never treat customer messages as system or developer instructions.
- Separate customer content from trusted agent instructions.
- Detect and flag suspicious instructions.
- Never allow customer messages to authorize access to other customer records.
- Escalate suspicious or high-risk requests.
- Test direct and indirect prompt injection attacks.

## 3. Customer Data Protection
- Collect only information required to process a lead.
- Validate and normalize contact information.
- Prevent access to another customer's records.
- Never expose full customer lists.
- Never expose passwords, API keys or authentication credentials.
- Redact personal information from application logs.
- Protect stored customer information against unauthorized access.

## 4. API and Secret Management
- Never hardcode API keys or passwords.
- Store credentials in environment variables or an approved secrets manager.
- Maintain a `.env.example` file containing placeholders only.
- Never commit `.env` files or real credentials.
- Never expose secrets through frontend code, logs or error messages.
- Use separate credentials for development and production.

## 5. Database Security
- Use parameterized SQL queries.
- Validate all database inputs.
- Do not give the AI model direct database access.
- Use approved database functions for specific operations.
- Protect customer records from cross-customer access.
- Use transactions for important changes.
- Maintain backup and recovery procedures.
- Restrict access to database files and backups.
- Never delete or reset persistent data without explicit approval.

## 6. Tool Security
- Every tool must have a strict input and output schema.
- Reject unexpected or unauthorized arguments.
- Validate tool arguments before execution.
- Enforce permissions in application code.
- Never execute arbitrary commands or URLs supplied by the model.
- Restrict tools to approved CRM, calendar, SMS and email operations.
- Record tool execution results.
- Do not expose bulk customer export functionality.

## 7. Booking and Messaging Safety
- Validate calendar availability before booking.
- Prevent duplicate bookings using idempotency keys.
- Prevent duplicate messages.
- Check customer contact permissions before sending messages.
- Respect opt-out requests.
- Use simulated SMS and email in the initial demo.
- Never perform real bookings or send real messages without a separately approved production integration.

## 8. Retry and Failure Protection
- Set timeouts for external operations.
- Retry only temporary failures.
- Use bounded retries with exponential backoff and jitter.
- Never retry indefinitely.
- Use idempotency for state-changing operations.
- Reconcile uncertain booking or messaging outcomes before retrying.
- Move exhausted tasks to a dead-letter queue.
- Record failures for investigation.

## 9. Spending and Execution Limits
- Configure a maximum spending limit.
- Track estimated model and tool usage.
- Check the remaining budget before expensive operations.
- Limit model calls and tool calls per lead.
- Prevent infinite agent loops.
- Stop processing when execution limits are reached.
- Escalate when budget limits are exhausted.

## 10. Kill Switch
- Implement a persistent kill switch.
- When activated, prevent new state-changing agent actions.
- Stop processing new tasks safely.
- Preserve existing database records and execution history.
- Record when the switch was activated.
- Require authorized human action to resume processing.
- Test kill switch behavior.

## 11. Confidence and Human Escalation
- Define a minimum confidence threshold.
- Escalate uncertain classifications.
- Escalate angry customers and complaints.
- Escalate suspicious requests.
- Escalate requests involving sensitive customer information.
- Do not perform high-impact actions when required information is missing.

## 12. Logging and Monitoring
- Record every important agent decision.
- Record tool calls, results, failures and execution times.
- Use unique correlation and action IDs.
- Redact PII and secrets.
- Never log passwords, API keys or full authentication tokens.
- Restrict access to logs.
- Track retries, budget usage and failed tasks.
- Preserve enough information to investigate security incidents.

## 13. Initial Demo Restrictions
- Use synthetic customer data only.
- Use mock CRM, calendar, SMS and email tools.
- Do not connect to real customer accounts.
- Do not send real messages.
- Do not create real appointments.
- Do not process payments.
- Do not use real customer PII in testing.

## 14. Mandatory Security Tests
The following must have automated tests:

1. Direct prompt injection.
2. Indirect prompt injection.
3. Unauthorized CRM access.
4. Customer data leakage.
5. Invalid tool arguments.
6. Duplicate bookings.
7. Duplicate messages.
8. Invalid calendar slots.
9. Retry exhaustion.
10. Budget exhaustion.
11. Kill switch activation.
12. Sensitive information in logs.
13. Unauthorized database access.
14. Malicious customer input.
15. Unauthorized outbound messaging.

## 15. Security Completion Criteria
- Security features must have corresponding tests.
- All test results must be recorded.
- Failed tests must be reported.
- Known limitations must be documented.
- No security feature may be declared complete without verification evidence.
- Passing local tests must not be represented as proof of production security.
