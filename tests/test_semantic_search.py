"""Offline tests for bounded Databricks hybrid AI Search retrieval."""
from types import SimpleNamespace

import pytest

from olist_agentic.copilot.semantic_search import INDEX_NAME, search_governance


class FakeIndexes:
    def __init__(self):
        self.calls = []

    def query_index(self, **kwargs):
        self.calls.append(kwargs)
        names = ["chunk_id", "doc_type", "entity_id", "title", "content", "source_table", "score"]
        rows = [
            ["rule:orders.delivered_time", "quality_rule", "orders.delivered_time",
             "Delivery timestamp required", "Delivered orders need an actual timestamp",
             "workspace.olist_governance.dq_rules", 1.0],
            ["untrusted", "other", "fake", "Untrusted", "Malicious fake source",
             "workspace.eacc_ecommerce_rag.chunks", 0.9],
        ]
        return SimpleNamespace(
            manifest=SimpleNamespace(columns=[SimpleNamespace(name=x) for x in names]),
            result=SimpleNamespace(data_array=rows),
        )


def test_hybrid_search_retrieves_relevant_approved_chunks():
    indexes = FakeIndexes()
    w = SimpleNamespace(vector_search_indexes=indexes)
    hits = search_governance(w, INDEX_NAME, "Why does a missing delivery date matter?")
    assert len(hits) == 1
    assert hits[0]["id"] == "rule:orders.delivered_time"
    assert hits[0]["source"] == "workspace.olist_governance.dq_rules"
    assert hits[0]["retrieval"] == "ai_search_hybrid"
    assert indexes.calls == [{
        "index_name": INDEX_NAME,
        "columns": ["chunk_id", "doc_type", "entity_id", "title", "content", "source_table"],
        "query_text": "Why does a missing delivery date matter?",
        "query_type": "HYBRID",
        "num_results": 4,
    }]


@pytest.mark.parametrize("name,question", [
    ("workspace.eacc_ecommerce_rag.enterprise_knowledge_index", "Why quarantine?"),
    ("workspace.olist_governance.other_index", "Why quarantine?"),
    ("", "Why quarantine?"),
    (INDEX_NAME, ""),
    (INDEX_NAME, "a" * 1001),
])
def test_invalid_index_or_search_query_never_executes(name, question):
    indexes = FakeIndexes()
    w = SimpleNamespace(vector_search_indexes=indexes)
    with pytest.raises(ValueError):
        search_governance(w, name, question)
    assert indexes.calls == []
