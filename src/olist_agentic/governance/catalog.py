"""Human-readable governance metadata used by BI, Genie and the Agentic Copilot."""

from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from olist_agentic.domain.metrics import METRICS
from olist_agentic.domain.rules import RULES, Rule
from olist_agentic.domain.sources import RELATIONSHIPS, SOURCES
from olist_agentic.governance.semantics import FIELD_DETAILS, SOURCE_NOTES, failure_condition


RULE_OVERRIDES = {
    "orders.delivered_time": {
        "business_name": "Delivered orders must have a delivery timestamp",
        "plain_english_description": "If an order is marked delivered, it must contain the timestamp showing when the customer received it.",
        "business_reason": "Delivery duration, delay, and on-time performance cannot be calculated reliably without an actual customer-delivery event.",
        "why_this_action": "QUARANTINE is used because the record cannot safely contribute to delivery KPIs while the source row still needs to remain auditable.",
        "downstream_effect": "The order is excluded from accepted Silver/Gold facts. Dependent order-item, payment, and review records are also excluded through accepted-parent integrity.",
        "example_failure": "order_status = delivered while order_delivered_customer_date is null.",
    },
    "orders.lifecycle": {
        "business_name": "Delivered order lifecycle events should be chronologically ordered",
        "plain_english_description": "For delivered orders, adjacent known lifecycle timestamps should move forward from purchase to approval to carrier handoff to customer delivery.",
        "business_reason": "Out-of-order events can make elapsed-time analysis misleading, but Olist event semantics are not sufficiently certified to treat every sequence anomaly as invalid business data.",
        "why_this_action": "WARN retains the row for analysis while making the sequencing exception visible for investigation.",
        "downstream_effect": "The order remains in trusted facts unless it fails another quarantining rule; analysts should avoid claiming causal meaning from the timestamp anomaly.",
        "example_failure": "A known later lifecycle event has a timestamp earlier than the preceding known event.",
    },
    "orders.payment_reconciliation": {
        "business_name": "Order payments should approximately reconcile to item price plus freight",
        "plain_english_description": "When both sides are available, compare total payments with accepted item price plus freight and flag differences greater than BRL 0.01.",
        "business_reason": "The comparison is useful for identifying unusual order economics, but the public dataset does not provide enough accounting semantics to label every discrepancy as incorrect.",
        "why_this_action": "WARN is intentionally used because the discrepancy is an investigation signal, not proof of bad accounting or incorrect revenue.",
        "downstream_effect": "The order remains available to analytics; the warning must not be interpreted as an accounting restatement.",
        "example_failure": "Aggregated payment_value differs from aggregated price + freight_value by more than BRL 0.01.",
    },
    "products.category": {
        "business_name": "Products should have a category",
        "plain_english_description": "A product should contain its Portuguese product category when available.",
        "business_reason": "Missing categories reduce category-level analytical coverage but do not invalidate the order or product itself.",
        "why_this_action": "WARN preserves the product and allows the Gold layer to use an Unknown fallback rather than discarding otherwise usable transactions.",
        "downstream_effect": "The product remains usable, but category analysis can contain Unknown values.",
        "example_failure": "product_category_name is null.",
    },
    "products.fk_product_category_name": {
        "business_name": "Product categories should have an English translation",
        "plain_english_description": "When a product category is present, it should normally have a matching category in the translation source.",
        "business_reason": "Missing translations reduce English-label coverage but do not invalidate the underlying product or transaction.",
        "why_this_action": "WARN preserves the product and falls back to the Portuguese source category.",
        "downstream_effect": "The product remains in trusted facts; English category labels can fall back to the source Portuguese value.",
        "example_failure": "product_category_name exists on a product but is absent from product_category_name_translation.",
    },
}


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip()


def _rule_template(rule: Rule) -> dict[str, str]:
    columns = ", ".join(rule.columns) if rule.columns else "the dataset contract"
    if rule.kind == "schema":
        plain = f"The {rule.dataset} source must contain exactly the columns expected by the governed source contract."
        reason = "Unexpected schema changes can shift meanings, break transformations, or silently corrupt downstream analytics."
        action_reason = "FAIL blocks publication because the pipeline cannot safely interpret an unrecognized source structure."
        downstream = "A schema-contract failure blocks the new trusted publication; the previous published snapshot remains current."
        example = "A required source column is missing or an unexpected column appears."
    elif rule.kind == "required":
        plain = f"Required field(s) {columns} must be present when this rule applies."
        reason = "Missing required values prevent the record from satisfying its declared key, relationship, or business contract."
        action_reason = f"{rule.action} is used because the missing value has the declared {rule.severity} quality impact."
        downstream = "QUARANTINE removes the failing record from accepted downstream facts; WARN retains it with a visible exception."
        example = f"One or more required values in {columns} are null or empty."
    elif rule.kind == "unique":
        plain = f"The candidate key ({columns}) must identify one record within the source snapshot."
        reason = "Duplicate candidate keys make row identity ambiguous and can multiply downstream facts."
        action_reason = "QUARANTINE protects downstream grain by excluding ambiguous duplicate-key records."
        downstream = "Failing records do not pass into accepted Silver/Gold data."
        example = f"Two source records share the same candidate key ({columns})."
    elif rule.kind in {"number", "timestamp"}:
        expected = "numeric" if rule.kind == "number" else "timestamp"
        plain = f"Non-null values in {columns} must parse as {expected} values."
        reason = f"The field is used with {expected} semantics downstream, so unparseable text cannot be interpreted safely."
        action_reason = "QUARANTINE prevents malformed values from being silently coerced into trusted analytics."
        downstream = "Failing records are excluded from accepted downstream facts."
        example = f"A non-null {columns} value cannot be parsed as a {expected}."
    elif rule.kind == "fk":
        plain = f"The relationship field {columns} must resolve to an existing governed parent record in {rule.parent}."
        reason = "Broken references can create facts with missing business context or orphaned child records."
        action_reason = f"{rule.action} reflects whether this relationship is required for trusted downstream use."
        downstream = "QUARANTINE excludes required orphan relationships; WARN retains optional enrichment gaps."
        example = f"A {rule.dataset} record references a {rule.parent} key that is not present."
    elif rule.kind == "domain":
        plain = f"The value in {columns} must belong to the recognized governed value set."
        reason = "Unexpected categorical values can split reporting categories or indicate source drift."
        action_reason = f"{rule.action} is used according to the field's business criticality."
        downstream = "The rule either retains the row with a warning or excludes it when the domain is required for trusted use."
        example = f"A value in {columns} is outside the recognized domain."
    elif rule.kind == "range":
        plain = f"The value in {columns} must remain inside the governed numeric range."
        reason = "Out-of-range values are physically or semantically invalid for the field."
        action_reason = "QUARANTINE prevents invalid numeric values from entering trusted facts."
        downstream = "Failing records are excluded from accepted downstream data."
        example = f"A value in {columns} falls outside the permitted bounds."
    elif rule.kind == "nonnegative":
        plain = f"The value in {columns} must be zero or greater."
        reason = "Negative values are not valid under the current Olist POC semantics for this field."
        action_reason = "QUARANTINE prevents invalid economic or product-dimension values from reaching trusted analytics."
        downstream = "Failing records are excluded from accepted downstream data."
        example = f"A value in {columns} is negative."
    elif rule.kind == "delivered_required":
        plain = "Delivered orders must contain the governed delivery event."
        reason = "Delivery analytics require an actual customer-delivery event."
        action_reason = "QUARANTINE protects delivery KPIs from incomplete delivered records."
        downstream = "The failing order and accepted-parent dependents are excluded."
        example = "A delivered order is missing its customer-delivery timestamp."
    elif rule.kind == "lifecycle":
        plain = rule.description or "Delivered lifecycle events should be ordered when adjacent events are known."
        reason = "Sequencing exceptions can distort duration analysis."
        action_reason = "WARN is used because event semantics are not sufficiently certified for hard rejection."
        downstream = "The order remains usable but the anomaly is disclosed."
        example = "A later lifecycle event occurs before an earlier known event."
    elif rule.kind == "reconciliation":
        plain = rule.description or "Payments should approximately reconcile to item economics."
        reason = "Large discrepancies can identify unusual order economics."
        action_reason = "WARN is used because source accounting semantics are not certified."
        downstream = "The row remains usable and the discrepancy remains visible."
        example = "Payment total differs from item price plus freight beyond the governed tolerance."
    else:
        plain = rule.description or rule.rule_name
        reason = "This control protects the governed data contract."
        action_reason = f"{rule.action} is the configured control action."
        downstream = "Downstream handling follows the configured action."
        example = "The configured rule predicate evaluates to failure."

    return {
        "business_name": rule.rule_name,
        "plain_english_description": plain,
        "business_reason": reason,
        "why_this_action": action_reason,
        "downstream_effect": downstream,
        "example_failure": example,
    }


def dq_rule_records() -> list[dict]:
    rows = []
    for rule in RULES:
        explanation = _rule_template(rule)
        explanation.update(RULE_OVERRIDES.get(rule.rule_id, {}))
        rows.append(
            {
                "rule_id": rule.rule_id,
                "rule_version": rule.version,
                "business_name": explanation["business_name"],
                "dataset": rule.dataset,
                "column_name": ", ".join(rule.columns),
                "category": rule.rule_type,
                "technical_description": rule.description or rule.rule_name,
                "plain_english_description": explanation["plain_english_description"],
                "business_reason": explanation["business_reason"],
                "failure_condition": failure_condition(rule),
                "severity": rule.severity,
                "action": rule.action,
                "why_this_action": explanation["why_this_action"],
                "downstream_effect": explanation["downstream_effect"],
                "example_failure": explanation["example_failure"],
                "owner": rule.owner,
                "active": rule.active_flag,
            }
        )
    return rows



def source_dictionary_records() -> list[dict]:
    required_columns: set[tuple[str, str]] = {
        (rule.dataset, column)
        for rule in RULES
        if rule.active_flag and rule.kind == "required"
        for column in rule.columns
    }
    rows: list[dict] = []
    fk_lookup = {(child, fk): f"{parent}.{pk}" for child, fk, parent, pk in RELATIONSHIPS}
    for dataset, source in SOURCES.items():
        declared = FIELD_DETAILS.get(dataset, {})
        if set(declared) != set(source.columns):
            raise ValueError(
                f"Curated dictionary coverage mismatch for {dataset}: "
                f"missing={sorted(set(source.columns) - set(declared))}, "
                f"unexpected={sorted(set(declared) - set(source.columns))}"
            )
        for column in source.columns:
            definition, recommended, avoid = declared[column]
            expected_type = (
                "DOUBLE" if column in source.numeric
                else "TIMESTAMP" if column in source.timestamps
                else "STRING"
            )
            role = (
                "candidate key" if column in source.key
                else "foreign key" if (dataset, column) in fk_lookup
                else ""
            )
            null_action = next(
                (
                    rule.action for rule in RULES
                    if rule.dataset == dataset
                    and rule.active_flag
                    and rule.kind == "required"
                    and column in rule.columns
                ),
                "",
            )
            rows.append(
                {
                    "dataset": dataset,
                    "column_name": column,
                    "display_name": _humanize(column).title(),
                    "business_definition": definition,
                    "source_type": "STRING",
                    "expected_type": expected_type,
                    # This expresses the configured DQ expectation, not empirical null frequency.
                    "nullable": (dataset, column) not in required_columns and column not in source.key,
                    "null_failure_action": null_action,
                    "key_role": role,
                    "relationship": fk_lookup.get((dataset, column), ""),
                    "sensitivity": "restricted" if dataset in {"customers", "reviews", "geolocation"} else "internal",
                    "example_value": "",
                    "known_caveat": SOURCE_NOTES[dataset][0],
                    "recommended_use": recommended,
                    "avoid_use": avoid,
                }
            )
    return rows


def source_contract_records() -> list[dict]:
    parents: dict[str, list[str]] = {}
    for child, fk, parent, pk in RELATIONSHIPS:
        parents.setdefault(child, []).append(f"{fk} -> {parent}.{pk}")
    return [
        {
            "dataset": name,
            "source_file": source.filename,
            "business_description": SOURCE_NOTES[name][0],
            "grain": source.grain,
            "candidate_key": ", ".join(source.key),
            "parent_dataset": "; ".join(parents.get(name, [])),
            "expected_columns": list(source.columns),
            "source_system": "Kaggle Olist Brazilian E-Commerce Public Dataset",
            "update_pattern": "Historical snapshot; POC batch simulation only",
            "sensitivity": "restricted" if name in {"customers", "reviews", "geolocation"} else "internal",
            "known_cardinality": source.grain,
            "known_limitations": SOURCE_NOTES[name][1],
            "owner": "Source Data Steward",
        }
        for name, source in SOURCES.items()
    ]


def metric_dictionary_records() -> list[dict]:
    return [
        {
            "metric_id": metric.metric_id,
            "metric_name": metric.name,
            "business_definition": metric.definition,
            # This is the governed formula description from Phase 1,
            # NOT executable SQL; metric views will supply executable SQL.
            "formula_description": metric.formula,
            "grain": metric.grain,
            "population": metric.assumption,
            "inclusions": "Accepted governed records satisfying the metric definition",
            "exclusions": metric.exclusions,
            "unit": metric.unit,
            "owner": metric.owner,
            "source_object": metric.source,
            "quality_dependency": "Current published run after quality gating",
            "known_caveat": metric.assumption,
        }
        for metric in METRICS
    ]


# Curated additional interpretation warnings: these do not automatically
# exclude records, and they must not be advertised as measured KPI errors.
RULE_IMPACT_OVERRIDES = {
    "orders.delivered_time": ("delivered_orders", "gmv", "freight", "aov", "on_time_rate", "late_rate", "delivery_days", "delay_days", "review_score", "negative_review_rate", "repeat_customer_rate", "total_orders"),
    "orders.lifecycle": ("delivery_days", "delay_days"),
    "orders.payment_reconciliation": ("gmv", "freight", "aov"),
    "customers.persistent_id": ("repeat_customer_rate",),
    "reviews.score": ("review_score", "negative_review_rate"),
}


def _potential_metrics(rule: Rule) -> tuple[str, ...]:
    if rule.rule_id in RULE_IMPACT_OVERRIDES:
        return RULE_IMPACT_OVERRIDES[rule.rule_id]
    # These are POTENTIAL dependencies, not observed attribution of a KPI delta.
    if rule.dataset == "orders":
        return tuple(m.metric_id for m in METRICS)
    if rule.dataset == "customers" and rule.action == "QUARANTINE":
        return tuple(m.metric_id for m in METRICS)  # accepted-parent orders may be excluded
    if rule.dataset in {"order_items", "products", "sellers"} and rule.action == "QUARANTINE":
        return ("gmv", "freight", "aov")
    if rule.dataset == "reviews" and rule.action == "QUARANTINE":
        return ("review_score", "negative_review_rate")
    return ()


def rule_metric_impact_records() -> list[dict]:
    metric_ids = {metric.metric_id for metric in METRICS}
    rows = []
    for rule in RULES:
        if not rule.active_flag:
            continue
        impacted = _potential_metrics(rule)
        if not set(impacted).issubset(metric_ids):
            raise ValueError(f"Unknown metric dependency for {rule.rule_id}")
        is_gate = rule.severity == "CRITICAL" or rule.action == "FAIL"
        action_type = (
            "PUBLICATION_BLOCK" if is_gate
            else "POTENTIAL_EXCLUSION" if rule.action == "QUARANTINE"
            else "QUALITY_WARNING" if impacted
            else "NO_DIRECT_KPI_EFFECT"
        )
        direction = (
            "current_published_snapshot_retained" if is_gate
            else "accepted_population_may_shrink" if rule.action == "QUARANTINE"
            else "no_direct_row_exclusion"
        )
        explanation = (
            "A failed critical/FAIL gate prevents a new Gold snapshot from being published; prior published metrics remain current."
            if is_gate else
            "If this rule fails, offending rows are excluded from accepted entities (and dependent rows may be excluded); metric changes depend on the actual affected cohort."
            if rule.action == "QUARANTINE" else
            "A failed WARN control retains source rows. The rule is an interpretation/coverage signal, not by itself a measured KPI error."
        )
        for metric_id in impacted or (None,):
            rows.append(
                {
                    "rule_id": rule.rule_id,
                    "metric_id": metric_id,
                    "affected_asset": metric_id or f"{rule.dataset}_quality_and_segmentation",
                    "impact_type": action_type,
                    "impact_direction": direction,
                    "evidence_status": "POTENTIAL_DEPENDENCY_NOT_OBSERVED_DELTA",
                    "explanation": explanation,
                }
            )
    return rows


def table_catalog_records() -> list[dict]:
    rows = []
    for layer in ("bronze", "silver"):
        for name, source in SOURCES.items():
            rows.append(
                {
                    "schema_name": f"olist_{layer}",
                    "table_name": name,
                    "display_name": f"{layer.title()} {name.replace('_', ' ').title()}",
                    "description": source.grain,
                    "grain": "One canonical ZIP prefix" if layer == "silver" and name == "geolocation" else source.grain,
                    "key_columns": ", ".join(source.key) or ("geolocation_zip_code_prefix" if layer == "silver" else "source_record_id"),
                    "logical_owner": "Operations Data Product Owner",
                    "classification": "restricted" if name in {"customers", "reviews", "geolocation"} else "internal",
                    "update_pattern": "Historical POC snapshot",
                    "retention_note": "POC retention only; production policy requires organizational approval",
                }
            )
    for table, grain, key in (
        ("fact_orders", "One accepted order", "order_id"),
        ("fact_order_items", "One accepted order item", "order_id, order_item_id"),
        ("dim_geography", "One canonical ZIP prefix", "geolocation_zip_code_prefix"),
    ):
        rows.append(
            {
                "schema_name": "olist_gold",
                "table_name": table,
                "display_name": table.replace("_", " ").title(),
                "description": grain,
                "grain": grain,
                "key_columns": key,
                "logical_owner": "Operations Analytics Owner",
                "classification": "internal; identifiers restricted",
                "update_pattern": "After quality-gated publication",
                "retention_note": "POC snapshot",
            }
        )
    return rows


def lineage_edge_records() -> list[dict]:
    rows = []
    for name, source in SOURCES.items():
        rows.extend(
            [
                {"source_asset": f"Kaggle:{source.filename}", "target_asset": f"olist_bronze.raw/{source.filename}", "relationship_type": "ingestion", "description": "Checksum-verified source landing", "metric_id": ""},
                {"source_asset": f"olist_bronze.{name}", "target_asset": f"olist_silver.{name}", "relationship_type": "quality_gate", "description": "DQ evaluation, quarantine and standardization", "metric_id": ""},
            ]
        )
    for metric in METRICS:
        rows.append(
            {
                "source_asset": metric.source.replace("gold.", "olist_gold."),
                "target_asset": f"metric:{metric.metric_id}",
                "relationship_type": "metric_definition",
                "description": metric.definition,
                "metric_id": metric.metric_id,
            }
        )
    return rows


DASHBOARD_VISUALS = [
    {
        "dashboard_id": "olist_operations",
        "page_id": "executive_overview",
        "widget_id": "kpi_gmv",
        "display_name": "Delivered Item GMV",
        "business_question": "How much accepted merchandise value was delivered in the selected cohort?",
        "metric_ids": ["gmv"],
        "dimension_ids": [],
        "source_objects": ["olist_gold.mv_order_operations"],
        "default_interpretation": "Merchandise value on delivered accepted orders; freight is separate and this is not accounting revenue.",
        "caveat": "Historical Olist outcome, not live revenue.",
        "agent_instruction": "Always distinguish GMV from recognized revenue and freight.",
    },
    {
        "dashboard_id": "olist_operations",
        "page_id": "operations",
        "widget_id": "late_rate_by_state",
        "display_name": "Late delivery rate by customer state",
        "business_question": "Which customer states have the highest proportion of late eligible deliveries?",
        "metric_ids": ["late_rate"],
        "dimension_ids": ["customer_state"],
        "source_objects": ["olist_gold.mv_delivery_performance"],
        "default_interpretation": "Compare late rate together with eligible-delivery denominator and late-order count.",
        "caveat": "A high rate identifies a cohort to investigate; it does not establish root cause.",
        "agent_instruction": "State active filters and denominator; never attribute causation to a state or seller without evidence.",
    },
    {
        "dashboard_id": "olist_operations",
        "page_id": "operations",
        "widget_id": "seller_delivery_exposure",
        "display_name": "Seller late-delivery exposure",
        "business_question": "Which seller cohorts contain the largest late-delivery exposure?",
        "metric_ids": ["late_rate"],
        "dimension_ids": ["seller_id"],
        "source_objects": ["olist_gold.mv_delivery_performance"],
        "default_interpretation": "Use both late-order count and late rate with eligible deliveries.",
        "caveat": "Multi-seller order cohorts can overlap; ranking is investigative, not causal.",
        "agent_instruction": "Do not call a seller at fault. Explain volume, rate and denominator separately.",
    },
    {
        "dashboard_id": "olist_operations",
        "page_id": "data_governance_quality",
        "widget_id": "quality_readiness",
        "display_name": "Current Data Trust status",
        "business_question": "Is the current published analytical snapshot ready, warning, or blocked?",
        "metric_ids": [],
        "dimension_ids": [],
        "source_objects": ["olist_quality.dq_run_summary", "olist_quality.published_run"],
        "default_interpretation": "Readiness is a gate and is not equivalent to the numerical quality score.",
        "caveat": "A high quality score never overrides a critical or FAIL-action block.",
        "agent_instruction": "Explain readiness, quality score, failed rules and quarantine separately.",
    },
]


def dashboard_visual_records() -> list[dict]:
    return list(DASHBOARD_VISUALS)


def all_catalogs() -> dict[str, list[dict]]:
    return {
        "dq_rules": dq_rule_records(),
        "source_dictionary": source_dictionary_records(),
        "source_contracts": source_contract_records(),
        "metric_dictionary": metric_dictionary_records(),
        "rule_metric_impact": rule_metric_impact_records(),
        "table_catalog": table_catalog_records(),
        "lineage_edges": lineage_edge_records(),
        "dashboard_visual_catalog": dashboard_visual_records(),
    }
