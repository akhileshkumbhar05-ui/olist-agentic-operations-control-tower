# Phase 2 — Semantic Analytics

## Separation from Phase 1

The original POC in `workspace.olist_gold` and `workspace.olist_quality` is
**read-only**. All Phase 2 semantic assets are created under a new schema:

```text
workspace.olist_semantic
├── v_published_orders
└── mv_order_operations
```

This is a **new semantic schema** in addition to the six data/metadata schemas
in the original architectural diagram. It prevents changes to Phase 1 Gold.

## Why two views?

1. `v_published_orders` is an order-grain standard Unity Catalog view with a
   strict `published_run` filter. It provides only approved columns.
2. `mv_order_operations` is a Unity Catalog **metric view** with business
   measures and dimensions that Databricks AI/BI and Genie can reuse.

The metric view currently implements **12 of the 13** Phase 1 metrics. It
preserves the original calculation semantics: delivered-only merchandise GMV,
separate freight, calendar-date lateness, positive delay, and latest-review
population.

## Why repeat-customer rate is separate

The repeat-customer rate is calculated from the order count **per persistent
customer within the selected filtered cohort**. A fixed global
`customer_order_count` would produce incorrect results when a user filters the
dashboard by date/state/category/seller.

`sql/semantic/02_repeat_customer_rate.sql` is the independently verifiable
full-cohort SQL baseline. In the final app, the deterministic agent/query tool
must apply the dashboard filters BEFORE grouping by `customer_unique_id`.

It is intentionally not misrepresented as a simple additive metric-view
measure. We will implement the fully context-aware version later.

## How to validate the source without publishing anything

```sql
SELECT run_id FROM workspace.olist_quality.published_run;
SELECT COUNT(*) AS accepted_orders
FROM workspace.olist_gold.fact_orders
WHERE pipeline_run_id =
  (SELECT run_id FROM workspace.olist_quality.published_run);
```

Expected based on the existing real Olist published run: **99,433** rows.

## Publishing

The new repo contains:

```text
sql/semantic/01_published_orders.sql
dashboard/metric_views/mv_order_operations.yaml
pipelines/semantic_publish.py
```

From a Databricks Serverless notebook in the NEW Git folder:

```python
import sys
repo_path = "/Workspace/Users/akhileshkumbhar0405@gmail.com/olist-agentic-operations-control-tower"
sys.path.insert(0, repo_path)
from pipelines.semantic_publish import statements, publish
for s in statements():
    print(s[:160], "...")
# Only execute the following after checking the read-only source:
# print(publish(spark))
```

Databricks reference:
https://docs.databricks.com/aws/en/uc-semantics/metric-views/create

## Metric view query syntax (after publishing)

```sql
SELECT
  MEASURE(total_orders) AS total_orders,
  MEASURE(delivered_orders) AS delivered_orders,
  MEASURE(gmv) AS delivered_item_gmv,
  MEASURE(late_rate) AS late_delivery_rate
FROM workspace.olist_semantic.mv_order_operations;
```

And state analysis:

```sql
SELECT customer_state, MEASURE(late_rate) AS late_rate,
       MEASURE(total_orders) AS orders
FROM workspace.olist_semantic.mv_order_operations
GROUP BY customer_state
ORDER BY late_rate DESC;
```

Check dashboard/Genie privileges on both the semantic schema and its underlying
published Gold and Quality sources. Semantic views do not guarantee inferred
application-level permissions.

## Quality gates

Before considering this view stable:

- compare unfiltered measures against Phase 1 validated evidence;
- compare RJ/SP late-delivery rates against the validated cohort;
- check NULL handling and denominator behavior;
- confirm filters in AI/BI and Genie reproduce SQL results;
- do not claim live Olist freshness or accounting revenue.
