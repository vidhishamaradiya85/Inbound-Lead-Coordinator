
"""Run all synthetic leads through the local lead processor."""

import json
import tempfile
from collections import Counter
from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import load_settings
from database.connection import open_connection, initialize_database
from tools.crm import MockCRM
from agent.lead_processor import LeadProcessor

DATASET_PATH = PROJECT_ROOT / "dataset" / "leads.json"
REPORT_PATH = PROJECT_ROOT / "evaluations" / "dataset_run_report.json"


def main():
    leads = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    settings = load_settings()

    results = []
    failures = []
    decisions = Counter()

    with tempfile.TemporaryDirectory(prefix="lead-agent-") as temp_dir:
        database_settings = settings.database.model_copy(
            update={"sqlite_path": Path(temp_dir) / "evaluation.sqlite3"}
        )

        connection = open_connection(database_settings)
        try:
            initialize_database(connection)

            # Safety changes apply only to this temporary evaluation database.
            connection.execute(
                """
                UPDATE system_controls
                SET kill_switch_active = 0,
                    spending_limit_micros = 10000000
                WHERE control_id = 1
                """
            )
            connection.commit()

            crm = MockCRM(connection, settings)
            processor = LeadProcessor(crm)
            run_id = "dataset-evaluation-001"

            max_iterations = settings.agent.max_processing_iterations
            max_leads = settings.agent.max_leads_per_run
            processing_limit = min(len(leads), max_iterations, max_leads)

            for iteration, lead_data in enumerate(leads):
                if iteration >= processing_limit:
                    break

                lead_id = lead_data["lead_id"]
                create_result = crm.create_lead(
                    {
                        "run_id": run_id,
                        "idempotency_key": f"create-{lead_id}",
                        "lead_id": lead_id,
                        "source": lead_data["source"],
                        "name": lead_data.get("name"),
                        "email": lead_data.get("email"),
                        "phone": lead_data.get("phone"),
                        "raw_message": lead_data["raw_message"],
                        "service_requested": lead_data.get("service_requested"),
                        "address_text": lead_data.get("address_text"),
                        "service_area_id": lead_data.get("service_area_id"),
                    }
                )

                if not create_result.success:
                    failures.append(
                        {
                            "lead_id": lead_id,
                            "stage": "create",
                            "error": (
                                create_result.error.model_dump()
                                if create_result.error
                                else "Lead creation failed"
                            ),
                        }
                    )
                    continue

                result = processor.process_lead(
                    lead_id=lead_id,
                    run_id=run_id,
                )

                if not result["success"]:
                    failures.append(
                        {
                            "lead_id": lead_id,
                            "stage": "process",
                            "error": result.get("error"),
                        }
                    )
                    continue

                decision = result["decision"]
                decisions[decision["decision"]] += 1
                results.append(
                    {
                        "lead_id": lead_id,
                        "decision": decision,
                    }
                )

        finally:
            connection.close()

    report = {
        "total_dataset_leads": len(leads),
        "successfully_processed": len(results),
        "failed": len(failures),
        "decision_counts": dict(decisions),
        "failures": failures,
        "results": results,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("\nDATASET EVALUATION SUMMARY")
    print("--------------------------")
    print(f"Dataset leads:          {len(leads)}")
    print(f"Successfully processed: {len(results)}")
    print(f"Failures:               {len(failures)}")
    print("\nDecision counts:")

    for decision, count in sorted(decisions.items()):
        print(f"  {decision}: {count}")

    print(f"\nReport saved to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
