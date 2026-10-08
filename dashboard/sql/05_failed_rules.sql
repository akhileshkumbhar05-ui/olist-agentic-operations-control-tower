-- Human-readable governed rule metadata linked to ACTUAL current-run failures.
SELECT r.rule_id, g.business_name, g.plain_english_description,
  g.failure_condition, g.why_this_action, g.downstream_effect,
  r.dataset, r.action, r.severity, r.records_failed,
  r.records_evaluated, r.failure_percentage
FROM workspace.olist_agentic_quality.dq_rule_results r
JOIN workspace.olist_governance.dq_rules g ON r.rule_id = g.rule_id
JOIN workspace.olist_agentic_quality.published_run p ON r.run_id = p.run_id
WHERE r.status = 'FAILED'
ORDER BY r.records_failed DESC