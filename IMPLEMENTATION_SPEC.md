# Implementation Specification

## North star

Build one Databricks App containing:

1. a Power BI/Tableau-caliber Databricks AI/BI dashboard;
2. a persistent Agentic RAG copilot;
3. governed metric semantics;
4. explainable data-quality and quarantine behavior;
5. source/feature definitions;
6. structured analytics through Genie/deterministic tools;
7. RAG over curated governance and methodology knowledge;
8. MLflow tracing and evaluation.

The dashboard and copilot must share explicit context: page, visual, metric, filters, and published run.

## Dashboard pages

### Executive Overview
Operational KPIs, trends, filters, and a persistent Data Trust status.

### Operations Analytics
State, seller, category, delivery and customer-experience investigations with denominators and non-causality caveats.

### Data Governance & Quality
Quality overview, failed rules, rule explorer, quarantine, metric governance, source dictionary, lineage/trust.

## Core architectural rule

> No dashboard metric, rule, or important source field should be visible without governed metadata that the copilot can query to explain it.

## Unity Catalog

```text
olist_bronze
olist_silver
olist_gold
olist_quality
olist_governance
olist_ai
```

Definitions live in `olist_governance`; runtime DQ evidence lives in `olist_quality`.

## Governance tables

- `dq_rules`
- `source_dictionary`
- `source_contracts`
- `metric_dictionary`
- `rule_metric_impact`
- `table_catalog`
- `lineage_edges`
- `dashboard_visual_catalog`

## Agent routes

- ANALYTICS
- KNOWLEDGE
- TRUST
- HYBRID
- GENERAL

## Build order

1. Governance foundation
2. Metric views / semantic layer
3. AI/BI dashboard
4. Curated Genie Agent
5. RAG / Vector Search
6. Supervisor agent
7. Databricks App integration + context broker
8. MLflow tracing/evaluation
9. Demo hardening

## Definition of done

A VP can open one Databricks App, interact with a polished dashboard, ask the copilot to explain any important KPI/chart/rule/record/source field, receive grounded evidence scoped to the active filters and published run, and see that the AI flow is traceable and evaluated.
