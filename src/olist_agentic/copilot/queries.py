"""Allowlisted read-only SQL tools for the Olist Agentic Copilot.

The LLM cannot generate or execute SQL. Only named templates may run.
Queries use the independently published Phase 2 assets and exclude raw payloads.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

STATES = frozenset("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
ROUTES = ("ANALYTICS", "TRUST", "KNOWLEDGE", "HYBRID", "GENERAL")
METRICS = frozenset({"total_orders", "delivered_orders", "cancelled_orders", "gmv", "late_rate",
                     "on_time_rate", "freight", "aov", "negative_review_rate", "repeat_customer_rate"})
VISUALS = frozenset({"overview", "orders_by_state", "late_deliveries_by_state",
                     "quality_rules", "quarantine", "metric_dictionary"})
PAGES = frozenset({"operations", "trust", "governance", "copilot"})


@dataclass(frozen=True)
class Context:
    page: str = "operations"
    visual: str = "overview"
    state: str = "ALL"
    start_date: str | None = None
    end_date: str | None = None

    def __post_init__(self):
        if self.page not in PAGES or self.visual not in VISUALS:
            raise ValueError("Unsupported dashboard context")
        if self.state != "ALL" and self.state not in STATES:
            raise ValueError("Unknown state abbreviation")
        for field in ("start_date", "end_date"):
            value = getattr(self, field)
            if value is not None:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError("Dates must use YYYY-MM-DD")
                date.fromisoformat(value)
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("Start date cannot be after end date")


def route(question: str, context: Context) -> str:
    q = question.lower()
    trust = any(w in q for w in ("quarantin", "fail", "quality", "trust", "warn", "blocked",
                                "rule", "rejected", "exclude", "cascade"))
    analytic = any(w in q for w in ("gmv", "deliver", "late", "revenue", "metric",
                                   "order", "state", "percent", "rate", "compare", "chart",
                                   "graph", "number", "kpi", "trend"))
    knowledge = any(w in q for w in ("define", "definition", "mean", "formula", "source",
                                    "field", "dictionary", "why", "explain"))
    if trust and analytic:
        return "HYBRID"
    if trust:
        return "TRUST"
    if analytic:
        return "ANALYTICS"
    if knowledge or context.page == "governance":
        return "KNOWLEDGE"
    return "GENERAL"


def _time_filter(context: Context) -> str:
    # All literals have passed strict date.fromisoformat() validation.
    terms = []
    if context.start_date:
        terms.append(f"purchase_date >= DATE '{context.start_date}'")
    if context.end_date:
        terms.append(f"purchase_date <= DATE '{context.end_date}'")
    return " AND ".join(terms)


def _state_filter(question: str, context: Context) -> str:
    # A selected dashboard state takes precedence. Only enumerated literals
    # can be used, never arbitrary question text.
    if context.state != "ALL":
        selected = [context.state]
    else:
        mentioned = set(re.findall(r"\b[A-Z]{2}\b", question))
        selected = sorted(mentioned & STATES)
        if re.search(r"rio de janeiro", question, re.I):
            selected = sorted(set(selected) | {"RJ"})
        if re.search(r"s[aã]o paulo", question, re.I):
            selected = sorted(set(selected) | {"SP"})
    return "customer_state IN (" + ",".join(repr(s) for s in selected) + ")" if selected else ""


def _where(context: Context, state_clause: str = "") -> str:
    parts = [p for p in (_time_filter(context), state_clause) if p]
    return (" WHERE " + " AND ".join(parts)) if parts else ""


def statements(question: str, context: Context, chosen_route: str) -> dict[str, str]:
    """Produce only reviewed fixed-template SELECT statements.

    No user-provided table name, field name, predicate, or free-text SQL.
    """
    if chosen_route not in ROUTES:
        raise ValueError("Unrecognized route")
    statements_by_tool: dict[str, str] = {
        "publication": """
            SELECT p.run_id, s.readiness, s.quality_score, s.failed_rules,
                   s.quarantined_records, s.critical_failures
            FROM workspace.olist_agentic_quality.published_run p
            JOIN workspace.olist_agentic_quality.dq_run_summary s ON p.run_id = s.run_id
        """,
    }
    if chosen_route in ("ANALYTICS", "HYBRID"):
        where = _where(context, _state_filter(question, context))
        statements_by_tool["state_delivery"] = f"""
            SELECT customer_state,
                   SUM(CASE WHEN delivery_eligible THEN 1 ELSE 0 END) AS eligible_deliveries,
                   SUM(CASE WHEN delivery_eligible AND is_late THEN 1 ELSE 0 END) AS late_deliveries,
                   ROUND(100.0 * SUM(CASE WHEN delivery_eligible AND is_late THEN 1 ELSE 0 END)
                       / NULLIF(SUM(CASE WHEN delivery_eligible THEN 1 ELSE 0 END), 0), 4)
                       AS late_delivery_rate_pct,
                   COUNT(*) AS accepted_orders,
                   SUM(CASE WHEN is_delivered THEN COALESCE(item_gmv, 0) ELSE 0 END)
                       AS delivered_item_gmv_brl
            FROM workspace.olist_semantic.v_published_orders
            {where}
            GROUP BY customer_state ORDER BY accepted_orders DESC LIMIT 27
        """
    if chosen_route in ("ANALYTICS", "HYBRID") and re.search(r"\b(gmv|revenue|merchandise)\b", question, re.I):
        # One-row scoped measure; don't infer a national total from truncated state lists.
        # Use exactly the same validated state/date filters as the geographic tool.
        where = _where(context, _state_filter(question, context))
        statements_by_tool["gmv_summary"] = f"""
            SELECT COUNT(*) AS accepted_orders,
                   SUM(CASE WHEN is_delivered THEN 1 ELSE 0 END) AS delivered_orders,
                   SUM(CASE WHEN is_delivered THEN COALESCE(item_gmv, 0) ELSE 0 END)
                       AS delivered_item_gmv_brl
            FROM workspace.olist_semantic.v_published_orders
            {where}
        """
    if chosen_route in ("TRUST", "HYBRID"):
        statements_by_tool["failed_rules"] = """
            SELECT r.rule_id, r.dataset, r.action, r.severity, r.records_failed,
                   g.plain_english_description, g.why_this_action, g.downstream_effect
            FROM workspace.olist_agentic_quality.dq_rule_results r
            JOIN workspace.olist_agentic_quality.published_run p ON p.run_id = r.run_id
            LEFT JOIN workspace.olist_governance.dq_rules g ON r.rule_id = g.rule_id
            WHERE r.status = 'FAILED' ORDER BY r.records_failed DESC LIMIT 88
        """
        statements_by_tool["quarantine_breakdown"] = """
            SELECT q.dataset, COUNT(DISTINCT q.source_record_id) AS distinct_quarantined
            FROM workspace.olist_agentic_quality.quarantine q
            JOIN workspace.olist_agentic_quality.published_run p ON p.run_id = q.run_id
            GROUP BY q.dataset ORDER BY q.dataset
        """
    if chosen_route in ("KNOWLEDGE", "HYBRID", "TRUST"):
        statements_by_tool["metric_dictionary"] = """
            SELECT metric_id, metric_name, business_definition, formula_description,
                   known_caveat, exclusions, unit
            FROM workspace.olist_governance.metric_dictionary LIMIT 20
        """
        statements_by_tool["rule_dictionary"] = """
            SELECT rule_id, dataset, business_name, plain_english_description,
                   business_reason, why_this_action, downstream_effect, action
            FROM workspace.olist_governance.dq_rules LIMIT 100
        """
        statements_by_tool["source_dictionary"] = """
            SELECT dataset, column_name, business_definition, recommended_use, avoid_use
            FROM workspace.olist_governance.source_dictionary LIMIT 80
        """
    return {name: " ".join(sql.split()) for name, sql in statements_by_tool.items()}


def assert_read_only(sql: str) -> None:
    """Defense in depth; placeholders and multiple statements are forbidden."""
    if not re.match(r"^\s*SELECT\b", sql, re.I):
        raise ValueError("Only SELECT queries are permitted")
    if ";" in sql or "--" in sql or "/*" in sql:
        raise ValueError("Multiple statements and comments are not permitted")
    if re.search(r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|MERGE|COPY|GRANT|REVOKE|EXECUTE)\b", sql, re.I):
        raise ValueError("Data-modifying SQL is not permitted")
    if "workspace.olist_bronze" in sql or "original_values" in sql:
        raise ValueError("Raw source access is not permitted")
