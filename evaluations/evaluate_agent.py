
"""Case-by-case evaluation engine for the Inbound Lead Coordinator."""

import json
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timezone


# ---------------------------------------------------------
# File paths
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_FILE = PROJECT_ROOT / "dataset" / "evaluation_cases.json"
ACTUAL_FILE = PROJECT_ROOT / "evaluations" / "dataset_run_report.json"

OUTPUT_FILE = PROJECT_ROOT / "evaluations" / "evaluation_report.json"


# ---------------------------------------------------------
# Decision mapping
# ---------------------------------------------------------

DECISION_MAPPING = {
    "qualify": "eligible_for_qualification",
    "escalate": "escalate",
    "deduplicate": "mark_duplicate",
    "reject_spam": "reject_for_review",
    "reject_invalid": "reject_invalid",
    "reject_out_of_area": "reject_outside_service_area",
    "request_more_info": "request_information",
}


# Expected dataset terminology -> Agent terminology.
RISK_FLAG_ALIASES = {
    "complaint": "angry_or_complaint",
    "angry_customer": "angry_or_complaint",
    "angry_or_complaint": "angry_or_complaint",

    "prompt_injection": "possible_prompt_injection",
    "unauthorized_data_request": "possible_prompt_injection",
    "possible_prompt_injection": "possible_prompt_injection",

    "spam": "possible_spam",
    "possible_spam": "possible_spam",

    "duplicate": "possible_duplicate",
    "possible_duplicate": "possible_duplicate",

    "invalid_email": "invalid_email",
    "invalid_phone": "invalid_phone",

    "incomplete": "incomplete",
    "missing_service": "missing_service",
    "missing_service_area": "missing_service_area",
    "missing_contact_details": "missing_contact_details",
    "outside_service_area": "outside_service_area",
    "conflicting_contact_details": "conflicting_contact_details",
    "bulk_solicitation": "bulk_solicitation",
    "unclear_service_details": "unclear_service_details",
}


# ---------------------------------------------------------
# Utility functions
# ---------------------------------------------------------

def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Required file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def parse_flags(value):
    """Accept risk flags stored as either a list or JSON string."""

    if value is None:
        return []

    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value else []

    if not isinstance(value, list):
        return []

    return [str(flag) for flag in value]


def normalize_flags(flags):
    """Normalize equivalent expected and actual risk flag names."""

    normalized = set()

    for flag in flags:
        flag = flag.strip().lower()
        normalized.add(RISK_FLAG_ALIASES.get(flag, flag))

    return normalized


def normalize_expected_escalation_reason(value):
    if value is None:
        return None

    value = str(value).strip().lower()

    return RISK_FLAG_ALIASES.get(value, value)


# ---------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------

def evaluate_cases(expected_cases, actual_results):

    actual_by_lead = {}

    for result in actual_results:
        decision = result.get("decision", {})
        lead_id = decision.get("lead_id") or result.get("lead_id")

        if lead_id:
            actual_by_lead[lead_id] = decision

    case_results = []

    category_stats = defaultdict(
        lambda: {
            "total": 0,
            "passed": 0,
            "failed": 0,
        }
    )

    confusion_matrix = defaultdict(Counter)

    total_outcome_pass = 0
    total_risk_pass = 0
    total_duplicate_pass = 0
    total_pass = 0
    total_failed = 0

    for expected in expected_cases:

        lead_id = expected["lead_id"]
        category = expected.get("primary_category", "unknown")

        expected_outcome = expected.get("expected_outcome")

        expected_decision = DECISION_MAPPING.get(
            expected_outcome,
            expected_outcome,
        )

        expected_flags = parse_flags(
            expected.get("expected_risk_flags_json", [])
        )

        expected_flags_normalized = normalize_flags(expected_flags)

        expected_duplicate = expected.get(
            "expected_duplicate_of_lead_id"
        )

        expected_escalation_reason = normalize_expected_escalation_reason(
            expected.get("expected_escalation_reason")
        )

        actual = actual_by_lead.get(lead_id)

        if actual is None:
            actual_decision = None
            actual_flags = []
            actual_duplicate = None
            actual_reason = None
        else:
            actual_decision = actual.get("decision")
            actual_flags = parse_flags(actual.get("risk_flags", []))
            actual_duplicate = actual.get("duplicate_of")
            actual_reason = actual.get("reason")

        actual_flags_normalized = normalize_flags(actual_flags)

        # Check 1: Expected decision.

        outcome_pass = (
            actual_decision == expected_decision
        )

        # Check 2: Expected risk flags.

        risk_flags_pass = (
            expected_flags_normalized == actual_flags_normalized
        )

        # Check 3: Duplicate target, when one is specified.

        if expected_duplicate is not None:
            duplicate_pass = (
                actual_duplicate == expected_duplicate
            )
        else:
            duplicate_pass = True

        # Check 4: Escalation reason, when supplied.
        # This is reported separately because the agent's current
        # reason field contains human-readable explanations.

        escalation_reason_pass = None

        if expected_escalation_reason is not None:
            escalation_reason_pass = (
                expected_escalation_reason
                in actual_flags_normalized
            )

        # Overall case result.

        case_pass = (
            outcome_pass
            and risk_flags_pass
            and duplicate_pass
        )

        if outcome_pass:
            total_outcome_pass += 1

        if risk_flags_pass:
            total_risk_pass += 1

        if duplicate_pass:
            total_duplicate_pass += 1

        if case_pass:
            total_pass += 1
            status = "PASS"
        else:
            total_failed += 1
            status = "FAIL"

        category_stats[category]["total"] += 1

        if case_pass:
            category_stats[category]["passed"] += 1
        else:
            category_stats[category]["failed"] += 1

        actual_outcome = (
            next(
                (
                    outcome
                    for outcome, decision in DECISION_MAPPING.items()
                    if decision == actual_decision
                ),
                actual_decision,
            )
            if actual_decision
            else "missing"
        )

        confusion_matrix[expected_outcome][actual_outcome] += 1

        case_results.append({
            "case_id": expected.get("case_id"),
            "lead_id": lead_id,
            "category": category,
            "status": status,

            "expected_outcome": expected_outcome,
            "actual_outcome": actual_outcome,
            "outcome_pass": outcome_pass,

            "expected_risk_flags": sorted(expected_flags_normalized),
            "actual_risk_flags": sorted(actual_flags_normalized),
            "risk_flags_pass": risk_flags_pass,

            "expected_duplicate_of": expected_duplicate,
            "actual_duplicate_of": actual_duplicate,
            "duplicate_pass": duplicate_pass,

            "expected_escalation_reason": expected_escalation_reason,
            "actual_reason": actual_reason,
            "escalation_reason_pass": escalation_reason_pass,
        })

    total = len(expected_cases)

    return {
        "total_cases": total,
        "passed": total_pass,
        "failed": total_failed,

        "accuracy_percentage": round(
            (total_pass / total * 100), 2
        ) if total else 0,

        "outcome_accuracy_percentage": round(
            (total_outcome_pass / total * 100), 2
        ) if total else 0,

        "risk_flag_accuracy_percentage": round(
            (total_risk_pass / total * 100), 2
        ) if total else 0,

        "duplicate_accuracy_percentage": round(
            (total_duplicate_pass / total * 100), 2
        ) if total else 0,

        "category_results": {
            category: {
                **stats,
                "accuracy_percentage": round(
                    stats["passed"] / stats["total"] * 100, 2
                ) if stats["total"] else 0,
            }
            for category, stats in sorted(category_stats.items())
        },

        "confusion_matrix": {
            expected: dict(actual)
            for expected, actual in sorted(confusion_matrix.items())
        },

        "cases": case_results,
    }


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():

    print("\nINBOUND LEAD COORDINATOR")
    print("CASE-BY-CASE EVALUATION")
    print("=" * 50)

    expected_cases = load_json(EXPECTED_FILE)
    actual_report = load_json(ACTUAL_FILE)

    actual_results = actual_report.get("results", [])

    report = evaluate_cases(
        expected_cases,
        actual_results,
    )

    report["generated_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    report["source_files"] = {
        "expected": str(EXPECTED_FILE.relative_to(PROJECT_ROOT)),
        "actual": str(ACTUAL_FILE.relative_to(PROJECT_ROOT)),
    }

    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=4)

    # Print summary.

    print(f"\nTotal cases: {report['total_cases']}")
    print(f"Passed:      {report['passed']}")
    print(f"Failed:      {report['failed']}")

    print(
        f"Overall accuracy: "
        f"{report['accuracy_percentage']}%"
    )

    print(
        f"Decision accuracy: "
        f"{report['outcome_accuracy_percentage']}%"
    )

    print(
        f"Risk flag accuracy: "
        f"{report['risk_flag_accuracy_percentage']}%"
    )

    print(
        f"Duplicate accuracy: "
        f"{report['duplicate_accuracy_percentage']}%"
    )

    # Category results.

    print("\nCATEGORY-WISE RESULTS")
    print("-" * 50)

    for category, stats in report["category_results"].items():
        print(
            f"{category:25} "
            f"{stats['passed']}/{stats['total']} passed "
            f"({stats['accuracy_percentage']}%)"
        )

    # Failed cases.

    failed_cases = [
        case
        for case in report["cases"]
        if case["status"] == "FAIL"
    ]

    print("\nFAILED CASES")
    print("-" * 50)

    if not failed_cases:
        print("No failed cases.")
    else:
        for case in failed_cases:
            print(
                f"{case['lead_id']} | "
                f"Expected: {case['expected_outcome']} | "
                f"Actual: {case['actual_outcome']}"
            )

            if not case["outcome_pass"]:
                print("  - Decision mismatch")

            if not case["risk_flags_pass"]:
                print(
                    "  - Risk flag mismatch:",
                    "Expected:", case["expected_risk_flags"],
                    "Actual:", case["actual_risk_flags"],
                )

            if not case["duplicate_pass"]:
                print("  - Duplicate target mismatch")

    print("\n" + "=" * 50)
    print(f"Detailed report saved to:\n{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
