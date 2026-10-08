"""Curated semantics for every original Olist field and executable DQ predicate.

Definitions are reviewed POC interpretations of the public dataset, not business-owner
certifications. Keep this file separate from runtime quality results.
"""

# (Business meaning, recommended use, misuse to avoid)
FIELD_DETAILS = {
    "orders": {
        "order_id": ("Unique identifier for a placed order.", "Use as the order-grain identifier and child-table join key.", "Do not treat it as a customer identifier."),
        "customer_id": ("Order-specific customer identity; joins to customers.customer_id.", "Link each order to its source customer record.", "Do not count persistent repeat customers with this field."),
        "order_status": ("Final order lifecycle status in the public historical snapshot.", "Use governed status groups for delivered and cancelled KPIs.", "Do not interpret as a live fulfillment state."),
        "order_purchase_timestamp": ("Source timestamp recording when the order was placed.", "Use for historical purchase cohorts and order trends.", "Do not claim timezone precision the source does not supply."),
        "order_approved_at": ("Source timestamp when the order was approved, when recorded.", "Inspect approval timing as a lifecycle signal.", "Do not require it for every order status."),
        "order_delivered_carrier_date": ("Source timestamp of carrier handoff, when recorded.", "Inspect shipment lifecycle and carrier timing.", "Do not confuse carrier handoff with customer delivery."),
        "order_delivered_customer_date": ("Actual customer-delivery event timestamp, if supplied.", "Calculate delivery duration and compare with estimated delivery date.", "Do not calculate delivered KPIs from a delivered order when this is null."),
        "order_estimated_delivery_date": ("Estimated customer-delivery deadline provided by the source.", "Use its calendar day as the lateness comparison deadline.", "Do not treat the estimate as proof of delivery or an actual event."),
    },
    "customers": {
        "customer_id": ("Order-specific customer row identifier, linked from orders.customer_id.", "Join orders to the customer dimension at source grain.", "Do not use as a persistent customer identity."),
        "customer_unique_id": ("Persistent customer identity reused across order-specific customer records.", "Use for repeat-customer and distinct-customer analysis.", "Do not assume the customer has only one customer_id."),
        "customer_zip_code_prefix": ("Customer postal-code prefix in the Brazilian source.", "Use for approximate regional analysis with governed geography.", "Do not infer a complete street address or unique coordinate."),
        "customer_city": ("Customer city label in the source.", "Use for descriptive segmentation after normalization.", "Do not assume spelling/casing alone identifies a unique geographic place."),
        "customer_state": ("Two-letter Brazilian customer state code.", "Use to aggregate accepted orders by customer state.", "Do not present as the seller's location or delivery root cause."),
    },
    "order_items": {
        "order_id": ("Order identifier for this item; several item rows can belong to one order.", "Join through order grain after child aggregation when computing KPIs.", "Do not join raw items directly to raw payments before aggregation."),
        "order_item_id": ("Item sequence identifier unique only within its order.", "Use together with order_id as the item-grain key.", "Do not treat as a globally unique identifier."),
        "product_id": ("Identifier of the product purchased in this item.", "Join to the governed product dimension.", "Do not assume the product category is always known."),
        "seller_id": ("Identifier of the seller associated with this order item.", "Analyze seller exposure using distinct orders per seller cohort.", "Do not attribute all order outcomes causally to a seller."),
        "shipping_limit_date": ("Source shipping-limit deadline recorded for an order item.", "Use for investigations of shipment timing with caveats.", "Do not confuse with estimated customer delivery or actual shipment."),
        "price": ("Merchandise price of one order item in BRL, excluding freight.", "Aggregate accepted prices for merchandise GMV on delivered orders.", "Do not call GMV accounting revenue or implicitly include freight."),
        "freight_value": ("Freight amount associated with one order item in BRL.", "Sum separately from item merchandise value.", "Do not add freight to item price without stating the combined measure."),
    },
    "payments": {
        "order_id": ("Order identifier associated with this payment sequence.", "Aggregate payment sequences to order grain before joining items.", "Do not join raw payments to raw item rows directly."),
        "payment_sequential": ("Sequence number for one payment within an order.", "Use with order_id as the payment-grain key.", "Do not assume every order has exactly one payment."),
        "payment_type": ("Payment method classification recorded by the source.", "Segment payment methods using the governed recognized values.", "Do not assume a payment method implies complete settlement."),
        "payment_installments": ("Count of installments represented by the payment entry.", "Analyze installment distribution at payment-sequence grain.", "Do not treat as the number of payment rows."),
        "payment_value": ("Monetary value for one payment sequence in BRL.", "Sum per order before reconciliation with items plus freight.", "Do not call payment totals recognized revenue."),
    },
    "reviews": {
        "review_id": ("Source review identifier that can recur across different orders.", "Use together with order_id as the source candidate key.", "Do not assume review_id alone is unique."),
        "order_id": ("Order associated with the review.", "Join accepted reviews to accepted orders.", "Do not treat every raw review as the chosen one-per-order metric observation."),
        "review_score": ("Customer review rating from 1 through 5.", "Use the latest answered accepted review per order for governed KPIs.", "Do not average all raw review rows when orders have multiple reviews."),
        "review_comment_title": ("Optional free-text title supplied with the review.", "Use only for restricted review-context investigations.", "Do not assume absence of a title means a negative review."),
        "review_comment_message": ("Optional free-text customer review body.", "Handle as restricted potentially identifying free text.", "Do not expose it in unrestricted dashboards or Genie tables."),
        "review_creation_date": ("Timestamp/date when a review record was created.", "Inspect review creation timing with source timezone caveats.", "Do not equate creation with customer answer time."),
        "review_answer_timestamp": ("Timestamp when a review was answered, when recorded.", "Select the latest accepted review per order with review_id tie-breaker.", "Do not use as an order delivery timestamp."),
    },
    "products": {
        "product_id": ("Unique product identifier in the product catalog.", "Join accepted items to product attributes.", "Do not assume every product has a category translation."),
        "product_category_name": ("Original Portuguese product category identifier/label.", "Use as the translation join key and category fallback.", "Do not assume a matching English label always exists."),
        "product_name_lenght": ("Length of product name as recorded by the source (original spelling).", "Use as product-content metadata if needed.", "Do not rename the physical source column silently."),
        "product_description_lenght": ("Length of product description as recorded by the source (original spelling).", "Use as product-content completeness metadata.", "Do not treat the numeric length as the actual description text."),
        "product_photos_qty": ("Reported count of product photos.", "Use for descriptive product metadata analysis.", "Do not assume this field supplies image URLs."),
        "product_weight_g": ("Recorded product weight in grams.", "Use for product-dimension analysis after numeric validation.", "Do not assume it equals shipment/packaging weight."),
        "product_length_cm": ("Recorded product length in centimeters.", "Use for dimension-based descriptive analysis.", "Do not assume shipping-box dimensions."),
        "product_height_cm": ("Recorded product height in centimeters.", "Use for dimension-based descriptive analysis.", "Do not treat as order-delivery distance."),
        "product_width_cm": ("Recorded product width in centimeters.", "Use for dimension-based descriptive analysis.", "Do not assume missing dimensions are zero."),
    },
    "sellers": {
        "seller_id": ("Unique seller identifier in the source seller catalog.", "Join accepted items to their seller attributes.", "Do not assume seller association proves delivery responsibility."),
        "seller_zip_code_prefix": ("Seller postal-code prefix in the Brazilian source.", "Support approximate seller-geography segmentation.", "Do not infer a complete seller address."),
        "seller_city": ("Seller city label in the source.", "Use for descriptive geographic reporting.", "Do not assume labels are fully standardized."),
        "seller_state": ("Two-letter Brazilian state code for a seller.", "Group accepted seller cohorts by seller location.", "Do not confuse with the customer's state."),
    },
    "geolocation": {
        "geolocation_zip_code_prefix": ("Observed Brazilian postal-code prefix; appears on multiple rows.", "Join only after canonicalization to one governed ZIP row.", "Do not join raw geolocation observations to order facts."),
        "geolocation_lat": ("Observed latitude coordinate for the postal-code prefix.", "Aggregate valid observations to canonical median latitude.", "Do not assume one coordinate per raw ZIP prefix."),
        "geolocation_lng": ("Observed longitude coordinate for the postal-code prefix.", "Aggregate valid observations to canonical median longitude.", "Do not treat a coordinate as an exact customer address."),
        "geolocation_city": ("City label observed with a ZIP/coordinate record.", "Choose the governed deterministic modal city per ZIP.", "Do not expect all observations for a ZIP to agree."),
        "geolocation_state": ("Two-letter Brazilian state code observed with the coordinate.", "Choose the governed deterministic modal state per ZIP.", "Do not treat raw observations as a unique state dimension."),
    },
    "translation": {
        "product_category_name": ("Original Portuguese category key.", "Join from products.product_category_name for English display.", "Do not drop products solely because a translation is absent."),
        "product_category_name_english": ("English display label for the Portuguese product category.", "Use when available, otherwise retain the Portuguese source category.", "Do not assume every source category has an English translation."),
    },
}


SOURCE_NOTES = {
    "orders": ("Orders are one row per order. Source timestamps are historical and timezone semantics are unspecified.", "Orders with invalid mandatory delivery events can be quarantined, which also excludes dependent children."),
    "customers": ("customer_id is order-specific while customer_unique_id is the persistent identity.", "Use customer_unique_id for repeat-customer analysis."),
    "order_items": ("Multiple items and sellers can appear in one order.", "Aggregate items to order grain before joining payments or reviews."),
    "payments": ("Multiple payment sequences can appear in one order.", "Aggregate independently before comparing with item price plus freight."),
    "reviews": ("review_id alone is not unique; a single order can have multiple reviews.", "Select latest answered accepted review per order with tie-breaker."),
    "products": ("Source uses intentional original spellings including product_name_lenght.", "Missing/unknown categories affect descriptive segmentation, not proof of invalid sales."),
    "sellers": ("Seller records identify selling entities, not proven responsibility for a delivery outcome.", "Multi-seller cohorts overlap and are not additive."),
    "geolocation": ("One observation per source row; ZIP prefix is not unique.", "Canonicalize to one ZIP prefix using median coordinates and deterministic modal labels."),
    "translation": ("Portuguese-to-English category lookup is not exhaustive.", "Fallback to Portuguese category when an English translation is unavailable."),
}


def failure_condition(rule) -> str:
    cols = ", ".join(rule.columns)
    if rule.kind == "schema":
        return "Observed source column set differs from the governed expected column set (order is not material)."
    if rule.kind == "required":
        return f"At least one of [{cols}] is NULL or the empty string."
    if rule.kind == "unique":
        return f"At least two non-null-key rows share the same candidate key [{cols}] within the evaluated snapshot."
    if rule.kind == "number":
        return f"{cols} is non-null but cannot be converted to a finite DOUBLE."
    if rule.kind == "timestamp":
        return f"{cols} is non-null but cannot be parsed as a TIMESTAMP."
    if rule.kind == "fk":
        return f"A non-null [{cols}] value has no matching [{rule.parent}.{rule.parent_key}] in the source parent table."
    if rule.kind == "domain":
        return f"{cols} is NULL or not in the allowed set: {', '.join(rule.values)}."
    if rule.kind == "range":
        return f"A parsable [{cols}] value is outside the inclusive range [{rule.values[0]}, {rule.values[1]}]."
    if rule.kind == "nonnegative":
        return f"A parsable [{cols}] value is less than zero."
    if rule.kind == "delivered_required":
        return "order_status = delivered AND order_delivered_customer_date IS NULL."
    if rule.kind == "lifecycle":
        return "For delivered orders, at least one adjacent pair of known purchase/approval/carrier/customer timestamps is out of order."
    if rule.kind == "reconciliation":
        return "Where item and payment totals exist, ABS(total payment_value - SUM(item price + freight)) exceeds approximately BRL 0.01."
    raise ValueError(f"Unknown rule kind: {rule.kind}")
