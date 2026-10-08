SELECT q.dataset, q.rule_id, count(DISTINCT q.source_record_id) AS quarantined_records
FROM workspace.olist_agentic_quality.quarantine q
JOIN workspace.olist_agentic_quality.published_run p ON q.run_id = p.run_id
GROUP BY q.dataset, q.rule_id
ORDER BY quarantined_records DESC