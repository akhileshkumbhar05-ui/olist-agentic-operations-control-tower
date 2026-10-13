"""Contracts for visible, clickable UF labels on the NEXUS Brazil map.

These are static regressions and do not replace final browser verification.
"""
from pathlib import Path
import json
import re
import math


HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text(encoding="utf-8")
CSS = HTML.split("<style>", 1)[1].split("</style>", 1)[0]


def _boundaries():
    m = re.search(r'<script id="geoBoundaryData" type="application/json">(.*?)</script>', HTML, re.S)
    assert m is not None
    return json.loads(m.group(1))


def _labels():
    m = re.search(r"const STATE_CODE_POSITIONS=\{\s*(.*?)\s*\};", HTML, re.S)
    assert m is not None
    placements = {}
    for state, coords in re.findall(r"([A-Z]{2}):\[([\d,\s]+)\]", m.group(1)):
        assert state not in placements, "Duplicate UF label: " + state
        placements[state] = [int(c.strip()) for c in coords.split(",")]
    return placements


def test_all_27_states_are_labeled_exactly_once():
    states = _boundaries()
    labels = _labels()
    assert len(states) == len(labels) == 27
    assert set(states) == set(labels)
    assert {"RJ", "SP", "DF", "SE", "PE"} <= set(labels)
    for code, place in labels.items():
        assert len(place) in (2, 4), (code, place)
        x, y = place[:2]
        assert 5 <= x <= 385 and 0 <= y <= 365, (code, place)


def test_coastal_states_and_tiny_federal_district_use_callouts():
    labels = _labels()
    for uf in ("RJ", "ES", "DF", "SE", "AL", "PB", "RN", "PE"):
        assert len(labels[uf]) == 4, uf
    assert labels["RJ"][:2] == [321, 253]
    assert labels["RJ"][2:] == [295, 248]


def test_visible_labels_do_not_stack_on_top_of_each_other():
    labels = _labels()
    for code_a, pos_a in labels.items():
        for code_b, pos_b in labels.items():
            if code_a >= code_b:
                continue
            distance = math.dist(pos_a[:2], pos_b[:2])
            assert distance >= 13, (code_a, code_b, round(distance, 1))


def test_labels_are_in_svg_overlay_and_select_state_on_click():
    assert '<g id="statePaths" role="group"' in HTML
    assert '<g id="stateLabels" aria-hidden="true"></g>' in HTML
    assert "renderStateCodes(ns);" in HTML
    assert "document.createElementNS(ns,'text')" in HTML
    assert "document.createElementNS(ns,'line')" in HTML
    assert "code.setAttribute('data-uf',uf)" in HTML
    assert "code.addEventListener('click',()=>selectState(uf))" in HTML
    assert "code.addEventListener('pointerenter'" in HTML
    assert "document.querySelectorAll('#stateLabels text[data-uf]')" in HTML
    assert "t.classList.toggle('active',t.dataset.uf===uf)" in HTML
    assert "el.addEventListener('click',()=>selectState(uf))" in HTML
    assert "el.addEventListener('keydown'" in HTML


def test_labels_have_contrast_and_existing_map_remains_responsive():
    assert "#stateLabels .map-state-code{" in CSS
    assert "paint-order:stroke fill" in CSS
    assert "pointer-events:all" in CSS
    assert "#stateLabels .map-state-code.callout{" in CSS
    assert "#stateLabels .map-state-code.active{" in CSS
    assert "#stateLabels .map-state-leader{" in CSS
    assert "pointer-events:none" in CSS
    assert "#brazilMap{" in CSS
    assert ".geo-explorer.collapsed .geo-content{display:none}" in CSS


def test_native_dashboard_and_live_investigator_are_preserved():
    assert '<iframe id="nativeDashboard"' in HTML
    assert 'id="toggleGeo"' in HTML
    assert 'id="submitAsk"' in HTML
    assert "runRealNexusQuestion(q)" in HTML
    assert "fetch('/api/ask'" in HTML
