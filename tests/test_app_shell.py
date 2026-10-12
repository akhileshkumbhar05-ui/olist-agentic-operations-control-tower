"""Static checks for correct primary/backup Databricks App layout."""
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "app" / "static" / "index.html").read_text(encoding="utf-8")


def test_genie_backup_uses_full_width_native_dashboard_without_primary_sidebar():
    assert 'id="mainLayout"' in HTML
    assert 'id="copilotPanel"' in HTML
    assert "document.getElementById(\"copilotPanel\").hidden=kind===\"genie\"" in HTML
    assert 'main.genie-mode{grid-template-columns:minmax(0,1fr)}' in HTML
    assert '#copilotPanel[hidden]{display:none}' in HTML


def test_dashboard_keeps_custom_copilot_and_genie_fallback():
    assert 'onclick="showTab(\'dashboard\')"' in HTML
    assert 'onclick="showTab(\'genie\')"' in HTML
    assert "link.href=dashboardUrl" in HTML
    assert "frame.src=dashboardEmbedUrl" in HTML
    assert "Open Genie-enabled published dashboard" in HTML
    assert 'id="askBtn"' in HTML



def test_copilot_renders_readable_validation_errors_and_char_budget():
    assert 'MAX_QUESTION_CHARS=2000' in HTML
    assert 'id="questionCount"' in HTML
    assert 'function apiErrorMessage(data,status)' in HTML
    assert 'Array.isArray(detail)' in HTML
    assert 'new Error(apiErrorMessage(data,r.status))' in HTML
    assert 'e instanceof Error?e.message' in HTML



def test_copilot_focus_mode_keeps_dashboard_and_genie_separate():
    assert 'minmax(440px,min(40vw,620px))' in HTML
    assert 'main.focus-mode #dashboardPanel{display:none}' in HTML
    assert 'id="focusBtn"' in HTML
    assert 'function toggleCopilotFocus()' in HTML
    assert 'if(kind==="genie")document.getElementById("mainLayout").classList.remove("focus-mode")' in HTML


def test_copy_status_and_collapsible_evidence_are_present():
    assert 'id="copyAnswerBtn"' in HTML
    assert 'id="answerMode"' in HTML
    assert 'id="evidenceDetails"' in HTML
    assert 'id="evidenceMeta"' in HTML
    assert 'navigator.clipboard.writeText(lastAnswer)' in HTML
    assert 'Verified SQL fallback' in HTML
    assert 'AI agent + governed tools' in HTML
    assert 'function renderEvidence(evidence)' in HTML



def test_worldlink_template_palette_and_dashboard_embed_frame():
    # Use exact colors from the supplied WorldLink master slide; don't recolor the native iframe.
    assert '--wl-red:#EE2D3D' in HTML
    assert '--wl-navy:#140C64' in HTML
    assert '--wl-sky:#48B9FD' in HTML
    assert '--wl-violet:#602CF3' in HTML
    assert '--wl-magenta:#C10D68' in HTML
    assert 'font:15px Roboto,' in HTML
    assert 'nav button.active{background:' in HTML
    assert '#askBtn{background:' in HTML
    assert '#dashboardPanel{border-top:3px solid var(--wl-red)}' in HTML
    assert '#copilotPanel{border-top:3px solid var(--wl-sky)}' in HTML
    assert '.dashboard-ready{border:1px solid #515d8c' in HTML
    assert 'mount.classList.toggle("dashboard-ready",Boolean(dashboardEmbedUrl));' in HTML
    assert 'frame.src=dashboardEmbedUrl' in HTML
    assert 'id="tabGenie"' in HTML



def test_executive_presentation_uses_only_existing_frontend_contracts():
    assert 'class="capability-strip"' in HTML
    assert 'id="dashboardFocusBtn"' in HTML
    assert 'function toggleDashboardFocus()' in HTML
    assert 'main.dashboard-focus-mode #copilotPanel{display:none}' in HTML
    assert 'id="agentAvatar"' in HTML
    assert 'class="agent-orb"' in HTML
    assert 'id="agentSignal"' in HTML
    assert 'id="avatarStateLabel"' in HTML
    assert 'function setAgentVisualState(state)' in HTML
    assert 'setAgentVisualState("thinking")' in HTML
    assert 'setAgentVisualState("ready")' in HTML
    assert 'setAgentVisualState("error")' in HTML
    assert '@media(prefers-reduced-motion:reduce)' in HTML
    assert 'type="button" onclick="setQuestion(' in HTML


def test_existing_backend_request_contract_is_unchanged():
    assert 'fetch("/api/config")' in HTML
    assert 'fetch("/api/ask",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)})' in HTML
    assert 'const body={question,page:document.getElementById("page").value,state:document.getElementById("state").value,visual:"overview"}' in HTML
    assert 'if(!r.ok)throw new Error(apiErrorMessage(data,r.status))' in HTML
    assert 'renderAnswer(data.answer)' in HTML
    assert 'renderEvidence(data.evidence)' in HTML
    assert 'frame.src=dashboardEmbedUrl' in HTML
    assert 'if(kind==="genie")' in HTML



def test_copilot_v3_is_unboxed_and_preserves_the_animated_avatar():
    assert "WorldLink-inspired · Governed intelligence" not in HTML
    assert "Evidence-grounded Copilot</h1>" in HTML
    assert 'id="agentAvatar"' in HTML
    assert 'class="agent-orb"' in HTML
    assert 'id="agentSignal"' in HTML
    assert "INTELLIGENCE WORKSPACE" in HTML
    assert 'class="assistant-trust"' in HTML
    assert 'class="prompt-heading"' in HTML
    assert 'class="prompt-suggestions"' in HTML
    assert 'class="composer-card"' in HTML
    assert 'class="context-bar"' in HTML
    assert 'class="answer-shell"' in HTML
    assert 'class="answer-title"' in HTML
    assert 'class="evidence-drawer"' in HTML
    assert "#copilotPanel .assistant-header{" in HTML
    assert "#copilotPanel .answer-shell{" in HTML
    assert "#copilotPanel .evidence-details{border:0" in HTML


def test_copilot_v3_preserves_input_and_output_dom_ids():
    for name in (
        "state", "page", "question", "questionCount", "askBtn",
        "status", "answer", "answerMode", "copyAnswerBtn",
        "evidenceDetails", "evidenceMeta", "evidenceSummary",
        "rawEvidence", "evidence", "agentAvatar", "agentSignal",
        "avatarStateLabel", "focusBtn",
    ):
        assert HTML.count(f'id="{name}"') == 1, name
    assert 'aria-describedby="questionCount"' in HTML
    assert 'onclick="ask()"' in HTML
    assert 'onclick="copyAnswer()"' in HTML
    assert 'onclick="toggleCopilotFocus()"' in HTML
    assert "setAgentVisualState(\"thinking\")" in HTML
    assert "setAgentVisualState(\"ready\")" in HTML
    assert "setAgentVisualState(\"error\")" in HTML
