# Custom Copilot vertical slice (Phase 3)

## Implemented in GitHub (NOT YET DEPLOYED)

- `app/main.py`: FastAPI Databricks App with `POST /api/ask`, `GET /healthz`, `GET /api/config`.
- `app/static/index.html`: dark responsive operations shell, native published AI/BI iframe/link, **Genie backup** link, primary custom Copilot panel.
- `src/olist_agentic/copilot/queries.py`: allowlisted read-only SQL, validated state/date filters, deterministic KPI denominators, five router categories.
- `src/olist_agentic/copilot/engine.py`: structured evidence collection, lexical governance retrieval, deterministic fallback, optional serving-endpoint-grounded LLM response.
- `tests/test_copilot.py`: SQL-safety, routing, filters, publication, retrieval tests.

**Important:** This is a guarded *vertical slice*, not a completed multi-agent or vector-search implementation. Deterministic routing and SQL are implemented; an actual free model endpoint has **not** been verified or connected. The lexical retriever uses UC governance records and exposes source identifiers; managed Vector Search, MLflow tracing, agent graph/orchestration and full dashboard filter bridge are upcoming.

## Running on a Databricks App

Deploy only to the **new** app, without changing the original POC. Databricks App setup must grant its service principal least-privilege `USE CATALOG`, `USE SCHEMA` and `SELECT` on:

- `workspace.olist_semantic`
- `workspace.olist_agentic_quality`
- `workspace.olist_governance`

The native dashboard must be shared/authorized separately, and embedding is workspace/domain-policy dependent; secure direct link fallback exists.

In the App resource bindings:
- Add SQL Warehouse resource with resource key `sql-warehouse` (as referenced by `app.yaml`).
- Configure `DATABRICKS_DASHBOARD_URL` to the **actual published** AI/BI dashboard HTTPS URL; do not invent or assume one.
- Optionally configure `DATABRICKS_SERVING_ENDPOINT` **only after identifying and testing an allowed free Foundation Model endpoint** and granting the new app SP access. The SDK client then generates the explanation from retrieved facts. In default mode no LLM is invoked, and the UI explicitly says so.
- Python dependencies: `requirements-app.txt`. Configure app build/install to use them; no Databricks-specific workspace deployment has yet been tested.
- Databricks SDK statement execution returns textual values; renderers explicitly convert number fields. If task exceeds inline 30s SQL timeout, move to bounded polling/handling of statement status before release.

## Trust and safety boundaries

1. LLM never executes arbitrary SQL, composes SQL, or chooses writable Unity Catalog identifiers.
2. SQL is generated from fixed templates, and state/date inputs are allowlisted.
3. The independent published run pointer is mandatory for each question.
4. Raw/PII payloads are excluded; don't grant source or Bronze read permissions to the app.
5. Model-generated explanations are labeled `hosted_llm`; fallback is explicitly labeled `deterministic_template`.
6. Agent model endpoint failures fall back to evidence-based wording, not invented facts.
7. Potential rule-to-metric impacts are not proven changes.
8. Genie is not removed. It is available through the published dashboard's native Genie UI when permissions allow.

## Next live checkpoint

First verify latest CI, then create new Databricks App sourced from **this** repository. Confirm App compute exposes the required SQL resource binding and dependencies. Run `/healthz`, then test an actual `/api/ask` request. Record endpoint type and availability before enabling model-based response.

No existing working Databricks App or old POC gets modified.
