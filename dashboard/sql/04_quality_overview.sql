-- Latest successful published run ONLY; quality WARNING != pipeline failure.
SELECT s.run_id, s.readiness, s.quality_score, s.failed_rules,
  s.quarantined_records, a.records_received, a.accepted_records,
  a.status AS pipeline_status, a.latest_source_event,
  a.ended_at AS run_completed_at
FROM workspace.olist_agentic_quality.published_run p
JOIN workspace.olist_agentic_quality.dq_run_summary s ON p.run_id = s.run_id
JOIN workspace.olist_agentic_quality.pipeline_run_audit a ON p.run_id = a.run_id