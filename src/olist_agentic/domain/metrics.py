from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    metric_id: str
    name: str
    definition: str
    formula: str
    exclusions: str
    assumption: str
    unit: str = "number"
    source: str = "gold.fact_orders"
    grain: str = "One accepted order"
    owner: str = "Operations Analytics Owner"


METRICS = [
    Metric("total_orders", "Total Orders", "Accepted orders in selected purchase period", "count(order_id)", "Quarantined orders and missing accepted customer", "Historical purchase cohorts"),
    Metric("delivered_orders", "Delivered Orders", "Accepted orders with delivered status", "sum(is_delivered)", "Other statuses", "Final source status"),
    Metric("cancelled_orders", "Cancelled Orders", "Accepted orders with canceled status", "sum(is_cancelled)", "Other statuses", "Final source status"),
    Metric("gmv", "Delivered Item GMV", "Accepted item price on delivered orders in BRL", "sum(item_gmv) where is_delivered", "Freight, canceled, unavailable, quarantined items", "GMV is merchandise value, not recognized revenue", "BRL"),
    Metric("freight", "Delivered Freight", "Accepted item freight on delivered orders", "sum(freight_value) where is_delivered", "Other statuses", "Freight is separate from merchandise GMV", "BRL"),
    Metric("aov", "Average Delivered Order Value", "Delivered item GMV per delivered order with accepted items", "delivered GMV / delivered orders with item_count > 0", "Delivered orders without accepted items", "No accounting revenue claim", "BRL"),
    Metric("on_time_rate", "On-Time Delivery Rate", "Eligible deliveries on or before estimated calendar day", "100 * count(eligible and not late) / count(eligible)", "Non-delivered or missing delivery/estimate", "Date-level deadline; source timezone unspecified", "%"),
    Metric("late_rate", "Late Delivery Rate", "Eligible deliveries after estimated calendar day", "100 * count(eligible and late) / count(eligible)", "Non-eligible deliveries", "Historical outcome, not live backlog", "%"),
    Metric("delivery_days", "Average Delivery Time", "Mean elapsed days purchase to delivery", "avg(nonnegative delivery_days)", "Non-delivered or negative intervals", "Elapsed days, not business days", "days"),
    Metric("delay_days", "Average Late Delivery Delay", "Mean positive date-level delay among late deliveries", "avg(delay_days) where is_late", "On-time and non-eligible", "Calendar days", "days"),
    Metric("review_score", "Average Latest Review Score", "Mean latest answered accepted review per order", "avg(review_score)", "No accepted review", "Latest answer then review_id tie-breaker", "score"),
    Metric("negative_review_rate", "Negative Review Rate", "Latest accepted reviews rated 1 or 2", "100 * count(review_score <= 2) / count(nonnull review_score)", "No review", "One latest review per order", "%"),
    Metric("repeat_customer_rate", "Repeat Customer Rate", "Persistent customers with multiple accepted orders in selection", "100 * customers with >1 order / distinct customer_unique_id", "Missing persistent identity", "Selection-dependent; customer_id is not persistent", "%"),
]
