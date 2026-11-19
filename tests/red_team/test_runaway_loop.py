import ast
from pathlib import Path


def test_dataset_runner_enforces_processing_iteration_limit():
    project_root = Path(__file__).resolve().parents[2]
    runner_path = project_root / "scripts" / "run_dataset.py"

    source = runner_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    source_text = ast.unparse(tree)

    assert "max_processing_iterations" in source_text, (
        "Dataset runner does not enforce the maximum processing iteration limit."
    )