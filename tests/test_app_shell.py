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



def test_enterprise_blue_theme_and_dashboard_embed_frame():
    # Embedded AI/BI dashboard retains its own theme; App chrome is styled locally.
    assert '--wl-navy:#081525' in HTML
    assert '--wl-blue:#2b77d5' in HTML
    assert '--wl-cyan:#45c4e8' in HTML
    assert '.dashboard-ready{border:1px solid #42698b' in HTML
    assert 'mount.classList.toggle("dashboard-ready",Boolean(dashboardEmbedUrl));' in HTML
    assert 'frame.src=dashboardEmbedUrl' in HTML
    assert 'id="tabGenie"' in HTML
