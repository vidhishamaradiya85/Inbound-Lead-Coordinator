# Task 5 — Vendor Design Review

**Scenario:** A vendor proposes an AI-agent design with the following weaknesses. This review identifies 12 problems, ranks them by severity, and recommends a fix for each.

## Critical severity

| # | Problem | Why it is a problem | Recommended fix |
|---|---|---|---|
| 1 | API key stored in frontend JavaScript | Anyone can inspect the frontend and steal the API key, potentially causing unauthorized usage and financial losses. | Store API keys securely on the backend using environment variables or a secrets manager. |
| 2 | Agent has full database read/write access | A compromised or manipulated agent could expose, modify, or delete sensitive production data. | Apply least-privilege access. Use restricted database accounts, scoped permissions, and controlled APIs. |
| 3 | Model output trusted and executed directly | Malicious or incorrect model output could trigger dangerous database queries, commands, or unauthorized actions. | Validate model output against strict schemas, apply business rules, and require authorization before executing sensitive actions. |
| 4 | Customer SSNs stored in plain-text prompt logs | Sensitive personal information could be exposed through unauthorized log access or data breaches. | Redact or tokenize sensitive information, encrypt protected data, restrict log access, and establish retention policies. |

## High severity

| # | Problem | Why it is a problem | Recommended fix |
|---|---|---|---|
| 5 | Failed calls retry forever | Infinite retries can cause runaway costs, excessive API requests, and system instability. | Implement bounded retries, exponential backoff, jitter, timeouts, and a maximum retry limit. |
| 6 | One giant prompt handles everything | A single prompt becomes difficult to maintain, test, debug, and secure. Different responsibilities become mixed together. | Use modular prompts and separate specialized components for classification, retrieval, decision-making, and tool execution. |
| 7 | No evaluation system | There is no systematic way to measure accuracy, detect regressions, or determine whether agent changes improve performance. | Create an evaluation dataset, define success metrics, and run automated regression tests before deployment. |
| 8 | Memory stored in one unlimited text file | Memory grows indefinitely, making retrieval inefficient and increasing the risk of outdated or conflicting information. | Use structured, searchable memory with retention limits, summarization, indexing, and expiration policies. |

## Medium severity

| # | Problem | Why it is a problem | Recommended fix |
|---|---|---|---|
| 9 | No separation between agent responsibilities | Mixing reasoning, data retrieval, and execution increases complexity and makes failures harder to isolate. | Separate the system into modular components with clearly defined responsibilities. |
| 10 | No human approval for sensitive actions | The agent may perform high-impact actions without appropriate human oversight. | Introduce human approval for financial transactions, destructive operations, and sensitive customer communications. |
| 11 | No monitoring or audit trail | Administrators cannot easily investigate failures, identify suspicious activity, or understand why actions occurred. | Implement structured logging, decision traces, monitoring, alerts, and audit records while protecting sensitive data. |
| 12 | No isolation between tools and permissions | A compromised component may gain access to capabilities it does not need. | Use tool-specific permissions, execution boundaries, input validation, and controlled service interfaces. |

## Overall severity ranking

| Severity | Number of problems |
|---|---:|
| Critical | 4 |
| High | 4 |
| Medium | 4 |
| **Total** | **12** |

## Final Vendor Recommendation

**Recommendation: Reject the proposed design in its current form.**

The proposed architecture has serious security, privacy, reliability, and maintainability weaknesses.

Before approving it, the vendor must:

1. Secure API credentials and sensitive customer information.
2. Implement least-privilege database access.
3. Validate and authorize all model-generated actions.
4. Introduce bounded retries and execution timeouts.
5. Replace the giant prompt with modular components.
6. Implement structured memory and automated evaluations.
7. Add human approval for sensitive operations.
8. Establish monitoring and audit controls.

**Conclusion:** The design should not be approved for production until the critical vulnerabilities are resolved and the remaining safeguards are implemented and tested.
