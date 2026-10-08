# Architecture

## Product

The Databricks App is the product shell. A published Databricks AI/BI dashboard provides the BI experience, while a persistent Agentic Copilot explains business metrics, visuals, filters, quality state, source semantics, and governance policy.

## Data and semantics

```text
Kaggle historical Olist
      |
UC Volume / Bronze
      |
Quality engine -------> olist_quality runtime evidence
      |
Silver
      |
Gold / Metric Views --> AI/BI dashboard / Genie
      |
olist_governance ------> rule, field, metric, visual semantics
      |
olist_ai --------------> RAG knowledge / evaluation
```

## Important separation

- `olist_quality`: what happened during a run.
- `olist_governance`: what rules, fields, metrics and visuals mean.
- `olist_ai`: knowledge and evaluation material consumed by AI components.

This separation lets the copilot answer both “what happened?” and “why does that matter?” without treating runtime logs as documentation.
