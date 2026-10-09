-- Olist Agentic Operations Control Tower: governed semantic retrieval corpus.
-- Independent of EACC and the original Olist Data Trust schemas.
-- Run manually once with the existing Serverless Starter Warehouse.
-- Change Data Feed is required by the Standard AI Search Delta Sync index.
-- CREATE IF NOT EXISTS deliberately avoids overwriting any pre-existing table.
CREATE TABLE IF NOT EXISTS workspace.olist_governance.knowledge_chunks
USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
SELECT
  CONCAT('metric:', CAST(metric_id AS STRING)) AS chunk_id,
  'metric' AS doc_type,
  CAST(metric_id AS STRING) AS entity_id,
  CAST(metric_name AS STRING) AS title,
  CONCAT(
    'Governed metric: ', COALESCE(CAST(metric_name AS STRING), ''),
    '. Metric ID: ', COALESCE(CAST(metric_id AS STRING), ''),
    '. Definition: ', COALESCE(CAST(business_definition AS STRING), ''),
    '. Formula: ', COALESCE(CAST(formula_description AS STRING), ''),
    '. Unit: ', COALESCE(CAST(unit AS STRING), ''),
    '. Known caveats: ', COALESCE(CAST(known_caveat AS STRING), ''),
    '. Exclusions: ', COALESCE(CAST(exclusions AS STRING), '')
  ) AS content,
  'workspace.olist_governance.metric_dictionary' AS source_table
FROM workspace.olist_governance.metric_dictionary

UNION ALL

SELECT
  CONCAT('rule:', CAST(rule_id AS STRING)) AS chunk_id,
  'quality_rule' AS doc_type,
  CAST(rule_id AS STRING) AS entity_id,
  CAST(business_name AS STRING) AS title,
  CONCAT(
    'Data quality rule: ', COALESCE(CAST(rule_id AS STRING), ''),
    '. Dataset: ', COALESCE(CAST(dataset AS STRING), ''),
    '. Rule name: ', COALESCE(CAST(business_name AS STRING), ''),
    '. Plain-English description: ', COALESCE(CAST(plain_english_description AS STRING), ''),
    '. Business reason: ', COALESCE(CAST(business_reason AS STRING), ''),
    '. Action: ', COALESCE(CAST(action AS STRING), ''),
    '. Why this action: ', COALESCE(CAST(why_this_action AS STRING), ''),
    '. Downstream effect: ', COALESCE(CAST(downstream_effect AS STRING), '')
  ) AS content,
  'workspace.olist_governance.dq_rules' AS source_table
FROM workspace.olist_governance.dq_rules

UNION ALL

SELECT
  CONCAT('source:', CAST(dataset AS STRING), '.', CAST(column_name AS STRING)) AS chunk_id,
  'source_field' AS doc_type,
  CONCAT(CAST(dataset AS STRING), '.', CAST(column_name AS STRING)) AS entity_id,
  CONCAT(CAST(dataset AS STRING), '.', CAST(column_name AS STRING)) AS title,
  CONCAT(
    'Source data field: ', COALESCE(CAST(dataset AS STRING), ''),
    '.', COALESCE(CAST(column_name AS STRING), ''),
    '. Business definition: ', COALESCE(CAST(business_definition AS STRING), ''),
    '. Recommended use: ', COALESCE(CAST(recommended_use AS STRING), ''),
    '. Avoid using for: ', COALESCE(CAST(avoid_use AS STRING), '')
  ) AS content,
  'workspace.olist_governance.source_dictionary' AS source_table
FROM workspace.olist_governance.source_dictionary;

-- Sanity check: the primary key must be non-NULL and unique.
SELECT
  doc_type,
  COUNT(*) AS chunk_count,
  COUNT(DISTINCT chunk_id) AS distinct_chunk_ids,
  SUM(CASE WHEN chunk_id IS NULL OR content IS NULL OR TRIM(content) = '' THEN 1 ELSE 0 END)
    AS invalid_chunks
FROM workspace.olist_governance.knowledge_chunks
GROUP BY doc_type
ORDER BY doc_type;

-- After executing, configure a TRIGGERED Delta Sync index:
-- endpoint: olist-governance-search
-- index: workspace.olist_governance.knowledge_search_index
-- source table: workspace.olist_governance.knowledge_chunks
-- primary key: chunk_id
-- embedding source column: content
