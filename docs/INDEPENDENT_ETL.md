# Independent Phase 2 ETL

## Purpose

This repository ports the validated Phase 1 historical Olist ingestion, Spark quality evaluation, accepted-parent cascades, Silver standardization and Gold modeling into an **independent** data flow.

Old POC data schemas `workspace.olist_bronze`, `workspace.olist_silver`, `workspace.olist_gold`, and `workspace.olist_quality` are not write targets.

## New UC destinations

```text
/Volumes/workspace/olist_agentic_bronze/raw/
workspace.olist_agentic_bronze.*
workspace.olist_agentic_silver.*
workspace.olist_agentic_gold.*
workspace.olist_agentic_quality.*
workspace.olist_governance.*
workspace.olist_semantic.*
```

The raw landing logic verifies existing checksums, refuses to overwrite conflicting CSVs and preserves original string-typed Bronze rows. The Spark DQ engine continues to use the 88 existing controls, WARN/QUARANTINE/FAIL behavior and accepted-parent integrity. Gold facts are at order and order-item grain; quality data and snapshots are run-scoped.

The `published_run` pointer is updated only after successful Gold writes. On a BLOCKED run, the previous published snapshot remains current.

## Orchestration

`pipelines/foundation_job.py` is the consolidated entry point:

1. Independent ingestion / Bronze / DQ / Silver / Gold
2. Governance metadata publication
3. Published-order view / metric-view publication
4. KPI validation against the historical real Olist benchmark

Run the source-independent dry run in GitHub Actions or local Python:

```bash
python pipelines/foundation_job.py --dry-run
```

**Do not run `--apply` until the new Databricks job is configured and reviewed.** It will download/use historical Olist source files and write only to the new data schemas plus the documented metadata/semantic destinations.

## Validation boundary

The source-code, catalog and unit tests can run in GitHub Actions, but real Spark/Delta execution, Unity Catalog permissions and Databricks Metric View SQL dialect must be validated once in the Databricks workspace. No new live ETL run has been claimed yet.

Expected baseline for an identical full historical source version:
- 1,550,922 received source records
- 32 quarantined source records
- 99,433 Gold orders
- 112,642 Gold item records
- readiness WARNING
- 5 failed rule definitions (0 critical)
- 13 historical KPI benchmarks in the original POC evidence

These are **validation expectations**, not fresh measured results of Phase 2.

## Planned job implementation

Use one Serverless Databricks Job with a source-controlled Python task or a minimal source-controlled notebook adapter. Task dependencies must enforce ETL before metadata/semantic publishing. The job requires permissions to create and write the **new** UC schemas and the independent raw Volume.

Avoid deploying this as a manually repeated series of notebook cells.
