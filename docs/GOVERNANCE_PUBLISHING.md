# Phase 1 — Governance Metadata Publishing

## Status

The new GitHub repo now contains the publishing code. It is **not yet evidence
that tables were created in Databricks**.

The old Phase 1 POC repository is deliberately unchanged.

## What this publishes

Eight metadata-only Delta tables into a **new** dedicated schema:

```text
workspace.olist_governance.dq_rules
workspace.olist_governance.source_dictionary
workspace.olist_governance.source_contracts
workspace.olist_governance.metric_dictionary
workspace.olist_governance.rule_metric_impact
workspace.olist_governance.table_catalog
workspace.olist_governance.lineage_edges
workspace.olist_governance.dashboard_visual_catalog
```

The publisher never overwrites Olist Bronze, Silver, Gold or Quality tables.

### Catalog behavior

- 88 runtime-engine rules are mirrored into the governance catalog.
- Human-readable explanations and real failure predicates are generated for all active rules, with curated overrides for the known five failing controls.
- Every original source column is included in the source dictionary, with manually written business meaning and known misuse warnings.
- All 13 Phase 1 governed metrics have semantic dictionary entries.
- Every active DQ rule has at least one explicit metric-or-asset impact row.
- A rule/metric relationship is a **potential dependency**, not evidence
  of a measured KPI change.
- WARN retains the record; QUARANTINE excludes; blocking conditions
  preserve the previous published snapshot.

## Run from a Databricks Serverless notebook or Python task

In a Databricks Git folder pointing to the **new repository**, install the
package in the notebook's environment or add its `src` directory to the Python
path. Then run:

```python
# Review the destination before execution.
from pathlib import Path
import sys
repo_root = Path("/Workspace/Users/YOUR_EMAIL/olist-agentic-operations-control-tower")
sys.path.insert(0, str(repo_root / "src"))

from olist_agentic.config import Config
from olist_agentic.governance.catalog import all_catalogs
from pipelines.governance_publish import validate_catalogs, publish

print(validate_catalogs())
print(publish(spark, Config(catalog="workspace", schema_prefix="olist")))
```

**Note:** importing `pipelines` may require the repository root on
`sys.path`. The most reliable implementation path is to execute
`pipelines/governance_publish.py` as a Databricks Python task with this
repository as its source, or add the repo root before the import:

```python
sys.path.insert(0, str(repo_root))
```

### Pure-Python dry run (no Spark)

```bash
python pipelines/governance_publish.py --dry-run --catalog workspace --schema-prefix olist
```

This validates the generated metadata and prints destination and counts without
writing to Unity Catalog.

## Verify after publishing

```sql
SHOW TABLES IN workspace.olist_governance;
SELECT COUNT(*) FROM workspace.olist_governance.dq_rules;
SELECT COUNT(*) FROM workspace.olist_governance.source_dictionary;
SELECT COUNT(*) FROM workspace.olist_governance.metric_dictionary;
SELECT COUNT(DISTINCT rule_id)
FROM workspace.olist_governance.rule_metric_impact;

SELECT
  rule_id,
  business_name,
  plain_english_description,
  why_this_action,
  downstream_effect
FROM workspace.olist_governance.dq_rules
WHERE rule_id = 'orders.delivered_time';
```

Check the live publication location before configuring Genie permissions.
Do **not** claim that Unity Catalog grants, Genie Space attachment, vector
indexing, or AI/BI embedding are complete until separately tested.
