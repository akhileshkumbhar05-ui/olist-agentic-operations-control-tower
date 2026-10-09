"""Regression checks for Unity Gateway model-service URL selection.

No live model calls or credentials are used.
"""
import sys
from types import SimpleNamespace

import pytest


def test_app_uses_unity_gateway_mlflow_responses_base_url(monkeypatch):
    # The app itself depends on FastAPI; lightweight source-only CI can skip
    # this test while deployed-app dependency environments exercise it.
    pytest.importorskip("fastapi")
    from app import main as appmain

    workspace = SimpleNamespace(config=SimpleNamespace(
        host="https://dbc-example.cloud.databricks.com"))
    constructor_args = []

    def fake_databricks_openai(*, workspace_client, base_url):
        constructor_args.append((workspace_client, base_url))
        return SimpleNamespace(responses=SimpleNamespace(create=lambda **kw: kw))

    monkeypatch.setitem(sys.modules, "databricks_openai", SimpleNamespace(
        DatabricksOpenAI=fake_databricks_openai))
    monkeypatch.setattr(appmain, "client", lambda: workspace)
    appmain.gateway_model_client.cache_clear()
    try:
        api = appmain.gateway_model_client()
        assert constructor_args == [
            (workspace,
             "https://dbc-example.cloud.databricks.com/ai-gateway/mlflow/v1")]
        assert api.responses.create(model="system.ai.gpt-oss-120b") == {
            "model": "system.ai.gpt-oss-120b"}
    finally:
        appmain.gateway_model_client.cache_clear()


def test_frontend_config_uses_gateway_model_binding(monkeypatch):
    pytest.importorskip("fastapi")
    from app import main as appmain

    monkeypatch.setenv("DATABRICKS_MODEL_SERVICE", "system.ai.gpt-oss-120b")
    monkeypatch.delenv("DATABRICKS_SERVING_ENDPOINT", raising=False)
    assert appmain.config()["model_configured"] is True
