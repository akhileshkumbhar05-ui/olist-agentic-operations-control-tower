"""Single-app NEXUS shell and feature-parity regressions.

Tests remain static and do not substitute for post-deployment browser tests.
"""
from pathlib import Path
import re
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/nexus.html").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")


def test_canonical_nexus_entry_and_native_genie_capability():
    assert '@app.get("/nexus", response_class=HTMLResponse' in MAIN
    assert 'id="nativeDashboard"' in HTML
    assert 'id="openDatabricks"' in HTML
    assert "Open AI/BI + Genie" in HTML
    assert "dashboard_embed_url" in HTML
    assert "function setView(" in HTML
    assert "id=\"dashboardInvestigator\"" in HTML
    assert "Ask Genie" in HTML
    assert "Classic UI" not in HTML


def test_all_state_contexts_and_analysis_mode_retained():
    assert 'id="agentStateSelect"' in HTML
    assert 'value="AUTO"' in HTML
    assert 'value="ALL"' in HTML
    assert "ALL_BRAZIL_STATES" in HTML
    assert 'id="agentPageSelect"' in HTML
    for page in ("operations", "trust", "governance"):
        assert f'<option value="{page}">' in HTML
    assert "const preferredState=$('agentStateSelect').value" in HTML
    assert "agentStateScope(question,selectedFallback)" in HTML
    assert "const selectedPage=$('agentPageSelect').value" in HTML
    assert "question,page:selectedPage" in HTML
    assert "These settings do not alter dashboard filters." in HTML


def test_rich_response_and_traceable_evidence_in_single_investigator():
    assert 'id="answerBox"' in HTML
    assert "renderAgentAnswer(data.answer)" in HTML
    assert "lastAgentAnswer=data.answer" in HTML
    assert 'id="copyAgentAnswer"' in HTML
    assert "navigator.clipboard.writeText(lastAgentAnswer)" in HTML
    for id in ("copyReceipt", "agentEvidenceDetails", "agentEvidenceSummary",
               "agentRawEvidence", "agentEvidenceJson"):
        assert f'id="{id}"' in HTML
    assert "renderAgentEvidence(data.evidence)" in HTML
    assert "evidence?.knowledge" in HTML
    assert "evidence?.verified_metrics" in HTML
    assert "evidence?.retrieval_mode" in HTML
    assert "JSON.stringify(evidence||{},null,2)" in HTML
    assert "receiptText=JSON.stringify({question,answer:data.answer" in HTML


def test_no_loss_of_classic_question_validation_and_keyboard_shortcut():
    assert 'maxlength="2000"' in HTML
    assert 'id="agentQuestionCount"' in HTML
    assert 'aria-describedby="agentQuestionCount"' in HTML
    assert "MAX_AGENT_CHARS=2000" in HTML
    assert "updateAgentQuestionCount()" in HTML
    assert "function nexusApiError(data,status)" in HTML
    assert "Array.isArray(detail)" in HTML
    assert "if(question.length>MAX_AGENT_CHARS)" in HTML
    assert "(e.ctrlKey||e.metaKey)&&e.key==='Enter'&&drawer.classList.contains('open')" in HTML


def test_core_nexus_workspaces_and_full_canvas_still_present():
    for page in ("overview", "dashboard", "network", "quality", "semantics", "agent"):
        assert f'data-view="{page}"' in HTML
    for element in ("qualityWorkspace", "semanticWorkspace", "domainInspector",
                    "nativeDashboard", "brazilMap", "drawer", "commandBtn",
                    "holo", "liveView"):
        assert f'id="{element}"' in HTML


def test_main_ui_element_ids_are_unique():
    for element in ("question", "submitAsk", "answerBox", "copyAgentAnswer",
                    "agentStateSelect", "agentPageSelect", "agentEvidenceJson",
                    "agentEvidenceSummary", "agentQuestionCount", "nativeDashboard"):
        assert HTML.count(f'id="{element}"') == 1, element


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_nexus_inline_javascript_has_no_syntax_error():
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", HTML, flags=re.DOTALL)
    assert scripts
    result = subprocess.run(["node", "--check", "-"], input=scripts[-1],
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
