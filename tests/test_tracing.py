"""Tracing checks use a fake MLflow SDK and never contact Databricks."""
import json
import sys
from types import SimpleNamespace

from olist_agentic.copilot import tracing
from olist_agentic.copilot.agent import run_agent
from olist_agentic.copilot.queries import Context


class FakeMlflow:
    def __init__(self):
        self.stack = []
        self.spans = []

    def start_span(self, *, name, span_type, attributes):
        owner = self
        class Manager:
            def __enter__(self):
                self.span = SimpleNamespace(name=name, span_type=span_type,
                                            parent=owner.stack[-1] if owner.stack else None,
                                            attributes=dict(attributes))
                self.span.set_attributes = self.span.attributes.update
                owner.spans.append(self.span)
                owner.stack.append(name)
                return self.span

            def __exit__(self, *_):
                owner.stack.pop()
        return Manager()


def test_one_trace_nests_sql_model_and_retrieval(monkeypatch):
    recorder = FakeMlflow()
    monkeypatch.setattr(tracing, "_mlflow", lambda: recorder)
    def call(name, args, call_id):
        return SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args),
                               call_id=call_id, model_dump=lambda **_: {
                                   "type": "function_call", "name": name,
                                   "arguments": json.dumps(args), "call_id": call_id})
    outputs = [
        SimpleNamespace(output=[call("search_governance_knowledge",
                                     {"question": "freight definition"}, "call-1"),
                                call("fetch_governed_evidence", {"tool": "metric_dictionary"}, "call-2")],
                        output_text=""),
        SimpleNamespace(output=[], output_text="Freight is excluded. Source: workspace.olist_governance.metric_dictionary"),
    ]
    class Model:
        def __init__(self):
            self.responses = self
        def create(self, **_):
            return outputs.pop(0)
    def sql(statement):
        if "dq_run_summary" in statement:
            return [{"run_id": "published-id", "readiness": "WARNING"}]
        return [{"metric_id": "gmv", "business_definition": "Freight excluded"}]
    with tracing.trace_span("olist.ask", "CHAIN"):
        result = run_agent("Explain the formula and definition of freight.", Context(),
                           sql, Model(), "system.ai.gpt-oss-120b",
                           search_knowledge=lambda _: [{"id": "metric:gmv", "source":
                                "workspace.olist_governance.metric_dictionary", "text": "Freight excluded"}])
    assert result["evidence"]["retrieval_mode"] == "ai_search_hybrid"
    assert recorder.stack == []
    assert [(span.name, span.parent) for span in recorder.spans] == [
        ("olist.ask", None), ("governed_sql.publication", "olist.ask"),
        ("gateway.model", "olist.ask"), ("governance.retrieval", "olist.ask"),
        ("governed_sql.metric_dictionary", "olist.ask"), ("gateway.model", "olist.ask")]


def test_trace_export_failure_does_not_change_result(monkeypatch):
    class Broken:
        def start_span(self, **_):
            raise RuntimeError("trace unavailable")
    monkeypatch.setattr(tracing, "_mlflow", lambda: Broken())
    with tracing.trace_span("olist.ask", "CHAIN"):
        result = 42
    assert result == 42


def test_mlflow_initializes_databricks_tracking_before_experiment(monkeypatch):
    calls = []
    fake = SimpleNamespace(
        set_tracking_uri=lambda uri: calls.append(("tracking", uri)),
        set_experiment=lambda **kw: calls.append(("experiment", kw["experiment_id"])),
    )
    monkeypatch.setenv("MLFLOW_EXPERIMENT_ID", "2462690133412615")
    monkeypatch.setitem(sys.modules, "mlflow", fake)
    tracing._mlflow.cache_clear()
    try:
        assert tracing._mlflow() is fake
        assert calls == [("tracking", "databricks"),
                         ("experiment", "2462690133412615")]
    finally:
        tracing._mlflow.cache_clear()



def test_local_audit_records_nested_spans_without_mlflow_export(monkeypatch):
    events = []
    monkeypatch.setenv("OLIST_EXECUTION_AUDIT_LOGS", "true")
    monkeypatch.setattr(tracing, "_mlflow", lambda: None)
    monkeypatch.setattr(tracing.audit_logger, "info",
                        lambda fmt, *values: events.append(fmt % values))
    with tracing.trace_span("olist.ask", "CHAIN", {"endpoint": "/api/ask", "question": "PRIVATE"}):
        with tracing.trace_span("governed_sql.gmv_summary", "TOOL", {"tool": "gmv_summary"}):
            tracing.set_span_attributes(None, {
                "row_count": 1, "question": "PRIVATE", "content": "SECRET",
                "sources": "PRIVATE", "token": "SECRET",
            })
        tracing.set_span_attributes(None, {"generation": "agentic_tool_calling", "route": "ANALYTICS"})
    assert len(events) == 2
    assert all(line.startswith("OLIST_TRACE ") for line in events)
    child = json.loads(events[0].split(" ", 1)[1])
    parent = json.loads(events[1].split(" ", 1)[1])
    assert child["name"] == "governed_sql.gmv_summary"
    assert child["parent"] == "olist.ask"
    assert child["attributes"] == {"tool": "gmv_summary", "row_count": 1}
    assert parent["attributes"] == {"generation": "agentic_tool_calling", "route": "ANALYTICS"}
    assert parent["parent"] is None
    assert child["request_id"] == parent["request_id"]
    assert child["status"] == parent["status"] == "ok"
    assert child["duration_ms"] >= 0
    assert "PRIVATE" not in "\n".join(events)
    assert "SECRET" not in "\n".join(events)


def test_local_audit_logs_error_type_not_exception_text(monkeypatch):
    import pytest
    events = []
    monkeypatch.setenv("OLIST_EXECUTION_AUDIT_LOGS", "1")
    monkeypatch.setattr(tracing, "_mlflow", lambda: None)
    monkeypatch.setattr(tracing.audit_logger, "info",
                        lambda fmt, *values: events.append(fmt % values))
    with pytest.raises(RuntimeError, match="PRIVATE"):
        with tracing.trace_span("olist.ask", "CHAIN"):
            raise RuntimeError("PRIVATE error: raw model content")
    assert len(events) == 1
    record = json.loads(events[0].split(" ", 1)[1])
    assert record["status"] == "error"
    assert record["error_type"] == "RuntimeError"
    assert record["parent"] is None
    assert "PRIVATE" not in events[0]


def test_local_audit_correlation_is_reset_across_requests(monkeypatch):
    events = []
    monkeypatch.setenv("OLIST_EXECUTION_AUDIT_LOGS", "true")
    monkeypatch.setattr(tracing, "_mlflow", lambda: None)
    monkeypatch.setattr(tracing.audit_logger, "info",
                        lambda fmt, *values: events.append(fmt % values))
    with tracing.trace_span("olist.ask", "CHAIN"):
        pass
    with tracing.trace_span("olist.ask", "CHAIN"):
        pass
    assert len(events) == 2
    left, right = [json.loads(line.split(" ", 1)[1]) for line in events]
    assert left["request_id"] != right["request_id"]
    assert left["parent"] is right["parent"] is None


def test_local_audit_does_not_override_mlflow_export_failures(monkeypatch):
    events = []
    class Broken:
        def start_span(self, **_):
            raise RuntimeError("storage export unavailable")
    monkeypatch.setenv("OLIST_EXECUTION_AUDIT_LOGS", "true")
    monkeypatch.setattr(tracing, "_mlflow", lambda: Broken())
    monkeypatch.setattr(tracing.audit_logger, "info",
                        lambda fmt, *values: events.append(fmt % values))
    with tracing.trace_span("olist.ask", "CHAIN"):
        answer = "verified answer"
    assert answer == "verified answer"
    assert json.loads(events[0].split(" ", 1)[1])["status"] == "ok"
