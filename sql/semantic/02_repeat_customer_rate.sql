-- Repeat-customer rate is SELECTION-DEPENDENT.
-- Use the SAME scope as the dashboard before grouping by persistent customer.
-- This full published-cohort baseline can be independently verified.
-- A future deterministic agent tool will parameterize the scoped_orders WHERE.
WITH scoped_orders AS (
  SELECT customer_unique_id
  FROM workspace.olist_semantic.v_published_orders
  WHERE customer_unique_id IS NOT NULL
),
customer_orders AS (
  SELECT customer_unique_id, COUNT(*) AS order_count
  FROM scoped_orders
  GROUP BY customer_unique_id
)
SELECT
  100.0 * SUM(CASE WHEN order_count > 1 THEN 1 ELSE 0 END)
  / NULLIF(COUNT(*), 0) AS repeat_customer_rate
FROM customer_orders;
