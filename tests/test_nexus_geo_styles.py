"""Regression contracts for the custom Brazil State Explorer CSS.

No Databricks calls. These tests protect the explicit styling and collapse
contract so native dashboard changes do not silently break the SVG explorer.
"""
from pathlib import Path
import json
import re


HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text(encoding="utf-8")
CSS = HTML.split("<style>", 1)[1].split("</style>", 1)[0]


def test_embedded_27_state_shapes_are_loaded_by_same_js_logic():
    found = re.search(r'<script id="geoBoundaryData" type="application/json">(.*?)</script>', HTML, re.S)
    assert found, "Map boundary source must be embedded in the NEXUS HTML"
    shapes = json.loads(found.group(1))
    assert len(shapes) == 27
    assert {"RJ", "SP", "DF", "PI"} <= shapes.keys()
    assert all(len(entry) == 2 and entry[1].startswith("M") for entry in shapes.values())
    assert 'id="statePaths"' in HTML
    assert "group.appendChild(el)" in HTML
    assert "el.addEventListener('click',()=>selectState(uf))" in HTML


def test_svg_paths_have_visible_nonblack_fills_and_state_highlight():
    assert re.search(r'#statePaths path\s*\{[^}]*fill:\s*#[0-9a-fA-F]{6}\s*;', CSS)
    assert re.search(r'#statePaths path\s*\{[^}]*stroke:\s*#[0-9a-fA-F]{6}\s*;', CSS)
    assert "#statePaths path:hover" in CSS
    assert "#statePaths path:focus-visible" in CSS
    assert "#statePaths path.selected" in CSS
    assert '#statePaths path[aria-pressed="true"]' in CSS
    assert "p.classList.toggle('selected',p.dataset.uf===uf)" in HTML


def test_collapse_button_hides_geo_content_and_remains_available():
    assert re.search(
        r'\.geo-explorer\.collapsed\s+\.geo-content\s*\{\s*display:\s*none\s*;?\s*\}',
        CSS,
    )
    assert 'id="toggleGeo" type="button" aria-expanded="true"' in HTML
    assert "$('geoExplorer').classList.toggle('collapsed')" in HTML
    assert "$('toggleGeo').setAttribute('aria-expanded',String(!c))" in HTML


def test_map_is_size_limited_and_responsive():
    for selector in (".geo-explorer", ".geo-header", ".geo-content",
                     ".geo-map-wrap", "#brazilMap", ".geo-intel",
                     ".geo-numbers", ".map-tooltip", ".map-source"):
        assert selector + "{" in CSS
    assert re.search(r'#brazilMap\s*\{[^}]*max-width:\s*\d+px', CSS)
    assert re.search(r'#brazilMap\s*\{[^}]*max-height:\s*\d+px', CSS)
    assert "@media(max-width:1050px)" in CSS
    assert "@media(max-width:620px)" in CSS


def test_native_dashboard_and_agent_interfaces_remain_present():
    assert '<iframe id="nativeDashboard"' in HTML
    assert '<section class="geo-explorer" id="geoExplorer"' in HTML
    assert 'id="dashboardInvestigator"' in HTML
    assert 'id="submitAsk"' in HTML
    assert "runRealNexusQuestion(q)" in HTML
    assert "/api/ask" in HTML
