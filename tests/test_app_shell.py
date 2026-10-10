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
