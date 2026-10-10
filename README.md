# Olist Agentic Operations Control Tower

Phase 2 Databricks POC: a single end-to-end Databricks App that combines a polished Databricks AI/BI dashboard with a context-aware Agentic RAG copilot.

## Product target

The finished application will let a business user:

- explore Executive, Operations, and Data Governance & Quality dashboards;
- ask the copilot to explain the KPI or chart currently in view;
- ask follow-up analytical questions through governed metrics / Genie;
- ask what a source field, metric, DQ rule, warning, or quarantine decision means;
- ask whether the current dashboard result is trustworthy;
- receive evidence grounded in structured data and governed RAG knowledge;
- inspect trace/evaluation evidence without exposing chain-of-thought.

## Schema model

```text
workspace
├── olist_bronze       # what arrived
├── olist_silver       # what passed
├── olist_gold         # what we analyze
├── olist_quality      # what happened during validation
├── olist_governance   # what everything means and why
└── olist_ai           # RAG / agent / evaluation assets
```

The Phase 1 repository, `olist-data-trust-control-tower`, remains unchanged as the engineering-validation POC.

## Current build phase

**Phase 1 — Governance foundation**

This repository starts by making the existing source contracts, 88 data-quality controls, 13 governed KPIs, source-field semantics, rule-to-metric impact, and dashboard visual semantics explicit and machine-queryable.

See [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

The current App agent uses Unity Gateway GPT-OSS 120B, governed SQL tools,
hybrid governance AI Search, and a deterministic fallback. See
[tracing and offline evaluation](docs/TRACING_EVALUATION.md) for the MLflow
experiment binding, trace boundaries, four-case evaluation, and redeploy checks.
