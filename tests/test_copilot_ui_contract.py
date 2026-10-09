"""Static regression contracts for the standalone Databricks App frontend.

These checks do not substitute for browser/UI integration testing.
"""
from pathlib import Path

from olist_agentic.copilot.agent import SYSTEM_INSTRUCTIONS


HTML = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")


def test_agent_answers_use_safe_dom_rendering():
    assert "renderAnswer(data.answer)" in HTML
    assert "document.createTextNode(span)" in HTML
    assert "document.createElement(\"table\")" in HTML
    assert "document.createElement(\"strong\")" in HTML
    assert ".innerHTML" not in HTML


def test_traceable_sources_display_and_raw_json_are_retained():
    assert 'id="evidenceSummary"' in HTML
    assert 'id="rawEvidence"' in HTML
    assert 'id="evidence"' in HTML
    assert "renderEvidence(data.evidence)" in HTML
    assert 'data.evidence,null,2' in HTML
    assert "model_selected_tools" in HTML


def test_metric_warning_uncertainty_is_explained_to_model():
    assert "WARNING-level records remain" in SYSTEM_INSTRUCTIONS
    assert "NEVER claim warnings" in SYSTEM_INSTRUCTIONS
    assert "independently" in SYSTEM_INSTRUCTIONS
