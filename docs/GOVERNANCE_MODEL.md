# Governance Model

## Principle

Runtime quality evidence and semantic explanation are separate products.

- `olist_quality` answers **what happened?**
- `olist_governance` answers **what does it mean and why?**

This prevents an agent from treating a terse execution result as sufficient business documentation.

## Governance objects

### dq_rules
Human-readable definitions for every active/versioned quality control.

### source_dictionary
Business meaning, expected type, key role, relationship, sensitivity, recommended use and misuse warnings for every raw source field.

### source_contracts
Dataset grain, candidate keys, relationships, expected columns and known cardinality limitations.

### metric_dictionary
Business definition, formula, population, exclusions, units, ownership and caveats for every governed KPI.

### rule_metric_impact
Explicit bridge between data-quality controls and affected KPIs.

### dashboard_visual_catalog
Explicit bridge between an AI/BI visual and the business question, metrics, dimensions, sources, interpretation and caveats that the copilot needs to explain it.

## Explainability requirement

No quality rule is considered presentation-ready if the user must read Python or SQL to understand:
- what failed;
- why it matters;
- why WARN / QUARANTINE / FAIL was selected;
- what happens downstream;
- which metrics can be affected.

The initial catalog generates governed explanations for all 88 Phase 1 rules and adds curated overrides for the important business exceptions observed in the real Olist data.
