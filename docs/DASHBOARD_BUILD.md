# Native Databricks AI/BI dashboard — initial source

## Build status

- Committed: editable AI/BI Lakeview JSON source file, SQL contracts, and structural CI tests.
- Not yet verified: Databricks accepting/importing this dashboard JSON, published dashboard rendering, application embedding, filter synchronization, or Genie interactions.
- DO NOT describe this dashboard as deployed. The existing independent ETL and semantic layer have been executed and validated separately.

## Source

`dashboard/src/Olist_Agentic_Operations_Control_Tower.lvdash.json`

Three pages:
1. **Operations Analytics**: published-run metric-view headline measures; order and late-delivery counts by customer state.
2. **Data Trust & Quality**: DQ rule results with explanations, WARN vs QUARANTINE distinction, record-level quarantine IDs without sensitive payloads.
3. **Governed Metric Definitions**: metrics, formulas, assumptions and caveats from Unity Catalog.

The JSON is a **first-pass editable AI/BI definition** and needs a UI import/compile check in this specific Databricks workspace. If importing surfaces a schema compatibility problem, use the Databricks dashboard editor to create a native dashboard, then export the known-good `.lvdash.json` and update the source-controlled file. GitHub unit tests validate JSON shape and internal references only, not the Databricks Lakeview API.

## Supporting governed SQL

`dashboard/sql/01_executive_kpis.sql` … `09_repeat_customer_rate.sql` define the additional KPI, trend, geographic, data-quality and metric dictionary datasets.

- GMV = delivered item value, not recognized revenue.
- Rates use correctly weighted eligible denominators; do **not** average rates by state or month.
- State-level late delivery counts are not late-delivery percentages.
- Repeat-customer rate requires grouping persistent IDs **after** filters are applied.
- Snapshot is historical (latest source event 2018), not real-time.
- Raw source payloads (including customer data) are intentionally excluded.

## Required next validation (one dashboard, no notebook cells)

1. Databricks **SQL → Dashboards → Create dashboard**, check whether **Import** or **Import dashboard** accepts the source JSON from the Git folder.
2. If accepted, choose the **Serverless Starter Warehouse** available in the workspace and inspect three tabs.
3. Run KPI cards and reconcile headline results with the validated baseline: 99,433 orders, 96,470 delivered, BRL 13,220,248.93 delivered item GMV.
4. Confirm Data Trust rule explanations and quarantine rows render.
5. Fix import/widget schema discrepancies based on the actual error, not guesses.
6. Only after publishing should we test embedding or shared filter context with the Copilot.

## Copilot integration contract

The future Databricks App shell will present the published AI/BI dashboard and the Copilot as separate panels/tabs. The Copilot must consume explicit filter-state parameters and query identical governed assets; **dashboard filters do not automatically pass themselves to the agent** merely because the dashboard is embedded. Implement and test the filter context bridge before claiming chart-context-aware reasoning. Answers require published run ID, metric definition, tool provenance and relevant governance citations. Do not expose raw hidden model reasoning.
