"""Regression checks for parallel NEXUS and classic UI deployments.

Static checks intentionally require no Databricks credentials or FastAPI,
matching the repository's existing lightweight GitHub Actions environment.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEXUS = (ROOT / "app/static/nexus.html").read_text(encoding="utf-8")
CLASSIC = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
API = (ROOT / "app/nexus_api.py").read_text(encoding="utf-8")


def test_classic_homepage_preserved_and_switchable():
    assert '@app.get("/", response_class=HTMLResponse)' in MAIN
    assert 'id="dashboardPanel"' in CLASSIC
    assert 'id="copilotPanel"' in CLASSIC
    assert 'href="/nexus"' in CLASSIC
    assert 'href="/"' in NEXUS


def test_nexus_route_and_existing_endpoints():
    assert '@app.get("/nexus", response_class=HTMLResponse' in MAIN
    assert 'app.include_router(nexus_router)' in MAIN
    for endpoint in ("/healthz", "/api/ask", "/api/config"):
        assert endpoint in MAIN


def test_live_databricks_integration_contract():
    assert "/api/ask" in NEXUS
    assert "/api/config" in NEXUS
    assert "/api/nexus/state-kpis" in NEXUS
    assert "dashboard_embed_url" in NEXUS
    assert "nativeDashboard" in NEXUS
    assert "LIVE GOVERNED SQL" in NEXUS


def test_brazil_map_and_interactive_cohort_logic():
    states = json.loads((ROOT / "app/static/br_states_paths.json").read_text())
    assert len(states) == 27
    assert set(states) == set(
        "AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split()
    )
    assert all(value[1].startswith("M") and value[1].endswith("Z") for value in states.values())
    assert "function selectState(uf)" in NEXUS
    assert "loadBrazilMap()" in NEXUS


def test_governed_state_sql_is_read_only_and_run_scoped():
    assert "workspace.olist_semantic.v_published_orders" in API
    assert "GROUPING SETS ((), (customer_state))" in API
    assert "NULLIF(" in API
    assert "AS eligible_deliveries" in API
    assert '@router.get("/api/nexus/state-kpis")' in API
    query = API.split('COHORT_SQL = """', 1)[1].split('"""', 1)[0].upper()
    assert query.lstrip().startswith("SELECT")
    assert not any(word in query.split() for word in ("DELETE", "UPDATE", "INSERT", "MERGE", "DROP", "ALTER", "CREATE"))


def test_no_governance_or_pipeline_mutation():
    assert "CREATE SCHEMA" not in API
    assert "saveAsTable" not in API
    assert "write.format" not in API
    assert "app/static/nexus.html" not in CLASSIC
