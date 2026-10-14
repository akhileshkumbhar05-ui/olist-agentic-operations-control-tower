"""NEXUS-only agent UI contracts, preserved from the retired Classic surface."""
from pathlib import Path

from olist_agentic.copilot.agent import SYSTEM_INSTRUCTIONS

HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text(encoding="utf-8")


def test_agent_answers_use_safe_dom_rendering_and_support_classic_markdown_parity():
    assert "renderAgentAnswer(data.answer)" in HTML
    assert "document.createTextNode(part)" in HTML
    for tag in ("table", "thead", "tbody", "tr", "th", "td", "strong", "em", "code"):
        assert f"document.createElement('{tag}')" in HTML
    assert "box.replaceChildren()" in HTML
    assert "innerHTML=data.answer" not in HTML
    assert "pre.textContent=data.answer" not in HTML


def test_agent_evidence_source_passages_and_raw_json_are_retained():
    for key in ("agentEvidenceDetails", "agentEvidenceSummary",
                "agentRawEvidence", "agentEvidenceJson", "copyAgentAnswer"):
        assert f'id="{key}"' in HTML
    assert "renderAgentEvidence(data.evidence)" in HTML
    assert "JSON.stringify(evidence||{},null,2)" in HTML
    assert "model_selected_tools" in HTML
    assert "retrieval_mode" in HTML
    assert "ai_search_hybrid" in HTML
    assert "verified_metrics" in HTML
    assert "slice(0,280)" in HTML
    assert "lastAgentAnswer=data.answer" in HTML
    assert "navigator.clipboard.writeText(lastAgentAnswer)" in HTML


def test_metric_warning_uncertainty_is_explained_to_model():
    assert "WARNING-level records remain" in SYSTEM_INSTRUCTIONS
    assert "NEVER claim warnings" in SYSTEM_INSTRUCTIONS
    assert "independently" in SYSTEM_INSTRUCTIONS
