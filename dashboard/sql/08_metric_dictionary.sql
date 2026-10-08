SELECT metric_id, metric_name, business_definition,
  formula_description, population, exclusions, unit, known_caveat
FROM workspace.olist_governance.metric_dictionary
ORDER BY metric_name