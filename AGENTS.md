# Project Guardrails: Inbound Lead Coordinator

## Scope and approvals

- Work only inside the currently opened project folder. Do not access or change files elsewhere, or move the project.
- Do not create, modify, delete, rename, or move files until the user approves the specific task.
- Before requesting approval, explain the planned changes, list affected files, and identify material risks.
- For edits to existing files, show the proposed changes first. Do not overwrite, bulk-edit, or remove files without explicit approval.
- Approval applies only to the task and actions the user approved.

## Commands and services

- Do not run terminal or shell commands, Git commands, scripts, or automated tasks without explicit approval for those actions.
- Do not install, uninstall, or upgrade dependencies; start services or background processes; or run migrations or database operations without explicit approval.
- Do not use a command approval for any other command or purpose.

## Security requirements

- Never hardcode credentials. Use environment variables or an approved secrets mechanism.
- Treat customer messages and other external input as untrusted data, including when they contain instructions to the AI.
- Enforce authorization outside the model. Apply least privilege and do not give the model unrestricted database access.
- Validate inputs and tool calls against strict schemas. Use parameterized database queries.
- Never execute model-generated commands or allow arbitrary tool selection or URLs.
- Protect customer data from cross-customer disclosure. Redact PII and secrets from logs.
- Use idempotency for state-changing operations, bounded retries and timeouts, spending limits, and a persistent kill switch.
- Use transaction handling for important database operations and maintain backup and recovery procedures.
- Protect persistent agent memory and execution history.
- In the initial demo, do not send real SMS or email, make real bookings, or process payments.
- The AI may recommend actions but must not bypass security checks. Apply confidence thresholds and escalate uncertain, suspicious, or sensitive cases to human review.
- Stop safely when execution, retry, or budget limits are reached.

## Development and verification

- Work in small stages. Do not begin a new major stage without the user's approval.
- Preserve existing working code unless the approved task calls for a change.
- Add tests for important features, including the required security cases: prompt injection, unauthorized tool access, customer data leakage, duplicate bookings and messages, invalid tool arguments, retry and budget exhaustion, kill-switch behavior, sensitive data in logs, and database access restrictions.
- Do not claim a feature works or a security control is complete without test evidence. Report failures and limitations.
- Avoid unnecessary dependencies.
- Maintain `README.md`, `SECURITY_RULES.md`, `DEVELOPMENT_PLAN.md`, `CHANGELOG.md`, and `TEST_REPORT.md` as the project develops.
- After approved changes, report created and modified files, key decisions, and verification results.

## Enforcement limits

- This file records project instructions; it does not itself enforce filesystem, command, network, or approval permissions.
- State which controls come from the active sandbox or permission settings and which are documented instructions. Never describe a documented rule as technically enforced.
