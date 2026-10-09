"""Bounded hybrid AI Search adapter for Olist governance RAG."""
from __future__ import annotations

INDEX_NAME = "workspace.olist_governance.knowledge_search_index"
ALLOWED_SOURCES = frozenset({
    "workspace.olist_governance.metric_dictionary",
    "workspace.olist_governance.dq_rules",
    "workspace.olist_governance.source_dictionary",
})
COLUMNS = ["chunk_id", "doc_type", "entity_id", "title", "content", "source_table"]


def search_governance(workspace, index_name: str, question: str) -> list[dict]:
    """Query only the approved index; return short, traceable source chunks."""
    if index_name != INDEX_NAME:
        raise ValueError("The approved Olist AI Search index is not configured")
    if not question.strip() or len(question) > 1000:
        raise ValueError("Search question must contain 1-1000 characters")
    reply = workspace.vector_search_indexes.query_index(
        index_name=INDEX_NAME, columns=COLUMNS, query_text=question,
        query_type="HYBRID", num_results=4,
    )
    names = [column.name for column in reply.manifest.columns]
    rows = reply.result.data_array or []
    hits = []
    used_ids = set()
    for raw in rows[:4]:
        if len(raw) != len(names):
            raise ValueError("Unexpected AI Search response columns")
        row = dict(zip(names, raw))
        source = str(row.get("source_table") or "")
        chunk_id = str(row.get("chunk_id") or "")
        content = str(row.get("content") or "").strip()
        if source not in ALLOWED_SOURCES or not chunk_id or not content:
            continue
        if chunk_id in used_ids:
            continue
        used_ids.add(chunk_id)
        hits.append({
            "id": chunk_id, "source": source,
            "title": str(row.get("title") or ""),
            "doc_type": str(row.get("doc_type") or ""),
            "text": content[:1400], "retrieval": "ai_search_hybrid",
        })
    return hits
