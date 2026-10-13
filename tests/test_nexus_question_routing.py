"""Regression tests: the NEXUS investigator must never replace a typed question.

Node is provided on GitHub Actions ubuntu-latest; no browser or Databricks
credentials required. Test the exact JavaScript helper executed by NEXUS.
"""
from pathlib import Path
import json
import re
import shutil
import subprocess

import pytest

HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text(encoding="utf-8")


def test_arbitrary_revenue_question_reaches_live_api_unchanged():
    assert "if(nexusLiveAgent){runRealNexusQuestion(q);return}" in HTML
    assert "body:JSON.stringify({question,page:'operations',visual:'overview',state:questionScope,source_domain:selectedDomain})" in HTML
    assert "const selectedDomain=question===domainInvestigationPrompt?domainPromptDomain:null" in HTML
    assert "const questionScope=selectedDomain?'ALL':agentStateScope(question)" in HTML
    # General freeform prompts still use the original geographic parser; only the
    # exact, visibly prefilled domain-wide prompt intentionally scopes to ALL.
    assert "['Question sent',question]" in HTML
    assert "function classify(q)" not in HTML
    assert "let key=classify(q)" not in HTML


def test_canned_scenarios_only_explicitly_selected():
    assert "cases[which]?.question||$('question').value" in HTML
    assert "runRealNexusQuestion(q)" in HTML
    assert "const key=Object.keys(cases).find" in HTML  # local file demo exact match only
    assert "const nexusLiveAgent=location.protocol==='http:'||location.protocol==='https:'" in HTML
    assert "nexusLiveAgent=true;" not in HTML


def test_production_labels_do_not_claim_playback():
    assert "LIVE AGENT / QUESTIONS SENT UNMODIFIED" in HTML
    assert "document.querySelector('.simulation-warning').hidden=true" in HTML
    assert "DEMONSTRATION PLAYBACK / NOT CONNECTED" not in HTML
    assert "RUN STATUS" not in HTML or "LIVE REQUEST FAILED" in HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js unavailable")
def test_nexus_script_syntax_and_dynamic_state_scoping():
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script>", HTML, flags=re.DOTALL)
    assert scripts
    script = scripts[-1]
    check = subprocess.run(["node", "--check", "-"], input=script, text=True, capture_output=True)
    assert check.returncode == 0, check.stderr

    start = script.index("function agentStateScope(question){")
    stop = script.index("// Safe simple Markdown renderer", start)
    helper = script[start:stop]
    runner = (
        "const FEATURED_STATES=['RJ','SP','MG','BA','PR','RS','SC','PE','DF'];"
        "const stateShapes={RJ:['Rio de Janeiro',''],SP:['São Paulo',''],GO:['Goiás',''],"
        "AM:['Amazonas',''],TO:['Tocantins','']};"
        "const activeState='SP';"
        + helper
        + "\nconsole.log(JSON.stringify(["
        "agentStateScope('how much revenue did the state of RJ generate?'),"
        "agentStateScope('Compare late deliveries for RJ and SP'),"
        "agentStateScope('What is delivered-item GMV?'),"
        "agentStateScope('What is the GMV for Rio de Janeiro?'),"
        "agentStateScope('how much GMV did the state of sp generate?'),"
        "agentStateScope('We need to improve the delivery rate'),"
        "agentStateScope('The merchandise should go to the customer')"
        "]));"
    )
    result = subprocess.run(["node", "-e", runner], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    values = json.loads(result.stdout)
    assert values == ["RJ", "ALL", "SP", "RJ", "SP", "SP", "SP"]


def test_safe_markdown_rendering_instead_of_raw_markdown_or_html():
    assert "renderAgentAnswer(data.answer)" in HTML
    assert "child.textContent=part.slice(2,-2)" in HTML
    assert "box.replaceChildren()" in HTML
    assert "pre.textContent=data.answer" not in HTML
    assert "innerHTML=data.answer" not in HTML
