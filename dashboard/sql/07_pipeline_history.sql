SELECT run_id, status, started_at, ended_at,
  records_received, accepted_records, quarantined_records, failed_checks,
  latest_source_event, duration_seconds
FROM workspace.olist_agentic_quality.pipeline_run_audit
ORDER BY started_at DESC