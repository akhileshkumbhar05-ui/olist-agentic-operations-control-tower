"""The NEXUS favicon is packaged, parseable, and exposed by FastAPI."""
from pathlib import Path
from xml.etree import ElementTree as ET

from fastapi.responses import FileResponse

from app.main import app
from app.nexus_api import nexus_favicon


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "app/static/nexus.html").read_text(encoding="utf-8")
SVG_PATH = ROOT / "app/static/nexus_favicon.svg"


def test_svg_is_self_contained_and_matches_nexus_emblem():
    assert SVG_PATH.is_file()
    data = SVG_PATH.read_text(encoding="utf-8")
    root = ET.fromstring(data)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["viewBox"] == "0 0 64 64"
    assert "#071421" in data
    assert "#80f4f2" in data
    assert "#fd5672" in data
    assert "rotate(45 32 32)" in data
    assert "<script" not in data.lower()
    assert "http://" not in data.replace("http://www.w3.org/2000/svg", "")
    assert "<image" not in data


def test_page_declares_correct_svg_favicon():
    assert '<link rel="icon" type="image/svg+xml" href="/nexus/favicon.svg">' in HTML
    assert HTML.count('rel="icon"') == 1
    assert "OLIST // NEXUS" in HTML


def test_favicon_route_returns_read_only_svg_file_response():
    assert "/nexus/favicon.svg" in {route.path for route in app.routes}
    response = nexus_favicon()
    assert isinstance(response, FileResponse)
    assert Path(response.path) == SVG_PATH
    assert response.media_type == "image/svg+xml"
    assert SVG_PATH.stat().st_size < 4096


def test_original_nexus_page_and_api_are_preserved():
    routes = {route.path for route in app.routes}
    assert "/nexus" in routes
    assert "/" in routes
    assert "/api/ask" in routes
    assert "/api/nexus/state-kpis" in routes
    assert "/healthz" in routes
