-- Phase 2 product writes ONLY to workspace.olist_semantic.
-- The underlying Phase 1 Gold/Quality tables are read-only references.
-- This view pins results to the currently published, quality-gated snapshot.
CREATE SCHEMA IF NOT EXISTS workspace.olist_semantic;

CREATE OR REPLACE VIEW workspace.olist_semantic.v_published_orders
COMMENT 'Read-only, published-run-filtered order grain for Phase 2 Databricks AI/BI and Genie.'
AS
SELECT
  order_id,
  customer_unique_id,
  customer_state,
  TO_DATE(purchase_date) AS purchase_date,
  order_status,
  is_delivered,
  is_cancelled,
  item_gmv,
  item_count,
  freight_value,
  review_score,
  delivery_eligible,
  is_late,
  delivery_days,
  delay_days
FROM workspace.olist_gold.fact_orders
WHERE pipeline_run_id = (
  SELECT run_id FROM workspace.olist_quality.published_run
);
