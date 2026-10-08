from pathlib import Path
import subprocess
import sys

from pipelines.foundation_job import plan


def test_plan_contains_eight_governance_tables_and_two_semantic_objects():
    result = plan()
    assert result["mode"] == "DRY_RUN"
    assert len(result["governance_tables"]) == 8
    assert len(result["semantic_objects"]) == 2
    assert result["governance_tables"]["dq_rules"] == 88
    assert result["governance_tables"]["source_dictionary"] == 52
    assert result["governance_tables"]["metric_dictionary"] == 13
    assert result["read_only_dependencies"] == []
    assert "workspace.olist_agentic_gold" in result["write_schemas"]
    assert result["steps"][0] == "independent_etl"


def test_dry_run_requires_no_spark():
    root = Path(__file__).resolve().parents[1]
    p = subprocess.run(
        [sys.executable, "pipelines/foundation_job.py", "--dry-run"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    assert '"mode": "DRY_RUN"' in p.stdout
    assert '"steps": [' in p.stdout
