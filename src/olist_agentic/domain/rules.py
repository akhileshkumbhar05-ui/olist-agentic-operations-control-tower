from dataclasses import dataclass

from olist_agentic.domain.sources import RELATIONSHIPS, SOURCES


STATES = tuple("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO".split())
STATUSES = ("created", "approved", "invoiced", "processing", "shipped", "delivered", "unavailable", "canceled")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    dataset: str
    rule_name: str
    rule_type: str
    severity: str
    action: str
    kind: str
    columns: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    parent: str = ""
    parent_key: str = ""
    description: str = ""
    owner: str = "Data Quality Steward"
    active_flag: bool = True
    version: int = 1


def catalog() -> list[Rule]:
    rules: list[Rule] = []

    def add(ds, suffix, name, typ, severity, action, kind, cols=(), **kwargs):
        rules.append(
            Rule(
                f"{ds}.{suffix}",
                ds,
                name,
                typ,
                severity,
                action,
                kind,
                tuple(cols),
                **kwargs,
            )
        )

    for ds, spec in SOURCES.items():
        add(ds, "schema", "Source columns match contract", "SCHEMA", "CRITICAL", "FAIL", "schema", spec.columns)
        if spec.key:
            add(ds, "required_key", "Candidate keys are present", "COMPLETENESS", "CRITICAL", "QUARANTINE", "required", spec.key)
            add(ds, "unique_key", "Candidate key is unique", "UNIQUENESS", "CRITICAL", "QUARANTINE", "unique", spec.key)
        for col in spec.numeric:
            add(ds, f"parse_{col}", f"{col} parses as number", "SCHEMA", "HIGH", "QUARANTINE", "number", (col,))
        for col in spec.timestamps:
            add(ds, f"parse_{col}", f"{col} parses as timestamp", "SCHEMA", "HIGH", "QUARANTINE", "timestamp", (col,))

    for child, fk, parent, pk in RELATIONSHIPS:
        optional = child == "products"
        if not optional:
            add(child, f"required_{fk}", f"{fk} is present", "COMPLETENESS", "HIGH", "QUARANTINE", "required", (fk,))
        add(
            child,
            f"fk_{fk}",
            f"{fk} exists in {parent}",
            "REFERENTIAL",
            "MEDIUM" if optional else "HIGH",
            "WARN" if optional else "QUARANTINE",
            "fk",
            (fk,),
            parent=parent,
            parent_key=pk,
        )

    add("orders", "required_events", "Purchase and estimate are present", "COMPLETENESS", "HIGH", "QUARANTINE", "required", ("order_purchase_timestamp", "order_estimated_delivery_date"))
    add("customers", "persistent_id", "Persistent customer identity is present", "COMPLETENESS", "HIGH", "QUARANTINE", "required", ("customer_unique_id",))
    add("orders", "status", "Recognized order status", "DOMAIN", "HIGH", "QUARANTINE", "domain", ("order_status",), values=STATUSES)
    add("payments", "type", "Recognized payment type", "DOMAIN", "MEDIUM", "WARN", "domain", ("payment_type",), values=("credit_card", "boleto", "voucher", "debit_card", "not_defined"))
    add("reviews", "score", "Review score from 1 to 5", "DOMAIN", "HIGH", "QUARANTINE", "range", ("review_score",), values=("1", "5"))

    for ds, cols in {
        "order_items": ("price", "freight_value"),
        "payments": ("payment_value", "payment_installments"),
        "products": SOURCES["products"].numeric,
    }.items():
        for col in cols:
            add(ds, f"nonnegative_{col}", f"{col} is nonnegative", "DOMAIN", "HIGH", "QUARANTINE", "nonnegative", (col,))

    for ds, col in (("customers", "customer_state"), ("sellers", "seller_state"), ("geolocation", "geolocation_state")):
        add(ds, "state", "Valid Brazilian state", "DOMAIN", "MEDIUM", "WARN", "domain", (col,), values=STATES)

    for col, bounds in (("geolocation_lat", ("-90", "90")), ("geolocation_lng", ("-180", "180"))):
        add("geolocation", col, "Physical coordinate bounds", "DOMAIN", "HIGH", "QUARANTINE", "range", (col,), values=bounds)

    add("geolocation", "zip", "ZIP prefix is present", "COMPLETENESS", "HIGH", "QUARANTINE", "required", ("geolocation_zip_code_prefix",))
    add("products", "category", "Category is populated", "COMPLETENESS", "MEDIUM", "WARN", "required", ("product_category_name",))
    add("orders", "delivered_time", "Delivered orders have delivery event", "BUSINESS", "HIGH", "QUARANTINE", "delivered_required", ("order_delivered_customer_date",))
    add(
        "orders",
        "lifecycle",
        "Delivered lifecycle is ordered",
        "TEMPORAL",
        "MEDIUM",
        "WARN",
        "lifecycle",
        ("order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date", "order_delivered_customer_date"),
        description="Check adjacent known events only for delivered orders; do not infer causal impact or require events for canceled orders.",
    )
    add(
        "orders",
        "payment_reconciliation",
        "Payment and item economics within BRL 0.01",
        "BUSINESS",
        "MEDIUM",
        "WARN",
        "reconciliation",
        ("order_id",),
        description="Compare payments to item price plus freight when both are present. Accounting semantics unconfirmed; discrepancy is a warning, not evidence of incorrect revenue.",
    )
    return rules


RULES = catalog()
