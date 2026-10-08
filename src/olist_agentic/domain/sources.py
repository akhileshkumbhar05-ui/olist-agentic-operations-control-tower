from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    filename: str
    columns: tuple[str, ...]
    key: tuple[str, ...]
    grain: str
    numeric: tuple[str, ...] = ()
    timestamps: tuple[str, ...] = ()


SOURCES = {
    "orders": Source(
        "olist_orders_dataset.csv",
        tuple("order_id customer_id order_status order_purchase_timestamp order_approved_at order_delivered_carrier_date order_delivered_customer_date order_estimated_delivery_date".split()),
        ("order_id",),
        "One order",
        timestamps=tuple("order_purchase_timestamp order_approved_at order_delivered_carrier_date order_delivered_customer_date order_estimated_delivery_date".split()),
    ),
    "customers": Source(
        "olist_customers_dataset.csv",
        tuple("customer_id customer_unique_id customer_zip_code_prefix customer_city customer_state".split()),
        ("customer_id",),
        "One order-specific customer identity; customer_unique_id is persistent identity",
    ),
    "order_items": Source(
        "olist_order_items_dataset.csv",
        tuple("order_id order_item_id product_id seller_id shipping_limit_date price freight_value".split()),
        ("order_id", "order_item_id"),
        "One numbered item in an order",
        ("order_item_id", "price", "freight_value"),
        ("shipping_limit_date",),
    ),
    "payments": Source(
        "olist_order_payments_dataset.csv",
        tuple("order_id payment_sequential payment_type payment_installments payment_value".split()),
        ("order_id", "payment_sequential"),
        "One payment sequence in an order",
        ("payment_sequential", "payment_installments", "payment_value"),
    ),
    "reviews": Source(
        "olist_order_reviews_dataset.csv",
        tuple("review_id order_id review_score review_comment_title review_comment_message review_creation_date review_answer_timestamp".split()),
        ("review_id", "order_id"),
        "One review/order pair; review_id alone is not unique",
        ("review_score",),
        ("review_creation_date", "review_answer_timestamp"),
    ),
    "products": Source(
        "olist_products_dataset.csv",
        tuple("product_id product_category_name product_name_lenght product_description_lenght product_photos_qty product_weight_g product_length_cm product_height_cm product_width_cm".split()),
        ("product_id",),
        "One product",
        tuple("product_name_lenght product_description_lenght product_photos_qty product_weight_g product_length_cm product_height_cm product_width_cm".split()),
    ),
    "sellers": Source(
        "olist_sellers_dataset.csv",
        tuple("seller_id seller_zip_code_prefix seller_city seller_state".split()),
        ("seller_id",),
        "One seller",
    ),
    "geolocation": Source(
        "olist_geolocation_dataset.csv",
        tuple("geolocation_zip_code_prefix geolocation_lat geolocation_lng geolocation_city geolocation_state".split()),
        (),
        "One observed ZIP/coordinate/city/state record; ZIP prefix is not unique",
        ("geolocation_lat", "geolocation_lng"),
    ),
    "translation": Source(
        "product_category_name_translation.csv",
        ("product_category_name", "product_category_name_english"),
        ("product_category_name",),
        "One category translation",
    ),
}

RELATIONSHIPS = [
    ("orders", "customer_id", "customers", "customer_id"),
    ("order_items", "order_id", "orders", "order_id"),
    ("order_items", "product_id", "products", "product_id"),
    ("order_items", "seller_id", "sellers", "seller_id"),
    ("payments", "order_id", "orders", "order_id"),
    ("reviews", "order_id", "orders", "order_id"),
    ("products", "product_category_name", "translation", "product_category_name"),
]
