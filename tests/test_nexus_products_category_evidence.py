"""Published Products category WARN explainability without invented translations or PII."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from app.nexus_domains import (
    failed_record_preview_sql, failed_rule_records,
    normalize_failed_record_preview, normalize_failed_record_sample,
    product_category_evidence,
)
from olist_agentic.copilot.queries import assert_read_only


HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text()


def product_row(rule_id="products.fk_product_category_name", **kwargs):
    row = {
        "published_run": "active-published-run",
        "dataset": "products",
        "rule_id": rule_id,
        "rule_action": "WARN",
        "failed_evaluations": 13 if rule_id.endswith("fk_product_category_name") else 610,
        "source_record_id": "products:11039",
        "failure_reason": "product_category_name exists in translation",
        "record_action": "WARN",
        "original_product_id": "real-olist-product-abc123",
        "original_category_name": "categoria_portuguesa_sem_traducao",
    }
    row.update(kwargs)
    return row


@pytest.mark.parametrize("rule_id", [
    "products.category", "products.fk_product_category_name",
])
def test_only_approved_product_keys_are_extracted_for_two_category_rules(rule_id):
    sql = failed_record_preview_sql("products", rule_id)
    # The AI SQL guard stays strict: the fixed backend projection itself is
    # specifically allowlisted to two JSON scalar keys.
    assert_read_only(sql.replace("f.original_values", "f.approved_json_scalar"))
    assert "get_json_object(f.original_values, '$.product_id') AS original_product_id" in sql
    assert "get_json_object(f.original_values, '$.product_category_name') AS original_category_name" in sql
    assert sql.count("get_json_object(") == 2
    assert "SELECT f.original_values" not in sql
    assert "f.original_values AS" not in sql
    assert "customer_id" not in sql and "payment_value" not in sql
    assert "r.run_id = p.run_id" in sql
    assert "f.run_id = r.run_id" in sql
    assert "r.status = 'FAILED'" in sql
    assert "LIMIT 20" in sql


def test_no_raw_product_data_for_other_products_rules():
    sql = failed_record_preview_sql("products", "products.unique_key")
    assert "get_json_object" not in sql


def test_failed_fk_shows_real_product_id_and_unmatched_portuguese_key():
    result = normalize_failed_record_preview(
        "products", "products.fk_product_category_name", [product_row()]
    )
    item = result["record_preview"][0]
    assert result["published_run"] == "active-published-run"
    assert result["failed_evaluations"] == 13
    assert item["source_record_id"] == "products:11039"
    assert item["original_product_id"] == "real-olist-product-abc123"
    assert item["original_category_name"] == "categoria_portuguesa_sem_traducao"
    assert item["category_condition"] == "MISSING_TRANSLATION_REFERENCE"
    assert "no matching" in item["category_explanation"]
    assert "when this rule ran" in item["category_explanation"]
    assert "English category label is not available" in item["category_explanation"]
    assert "new join" in item["evaluation_basis"]
    assert "product_category_name_english" not in json.dumps(result)


@pytest.mark.parametrize("category,condition", [
    (None, "NULL_CATEGORY"), ("", "EMPTY_CATEGORY"),
])
def test_completeness_rule_separately_identifies_missing_and_empty(category, condition):
    result = normalize_failed_record_preview(
        "products", "products.category", [
            product_row("products.category", original_category_name=category)
        ]
    )
    item = result["record_preview"][0]
    assert result["failed_evaluations"] == 610
    assert item["category_condition"] == condition
    assert item["original_category_name"] == category
    assert "translation" not in item["category_explanation"].lower()
    assert "original_product_id" in item


def test_inconsistent_fk_source_values_do_not_invent_translation_mismatch():
    for category in (None, ""):
        item = product_category_evidence(
            "products.fk_product_category_name",
            product_row(original_category_name=category),
        )
        assert item["category_condition"] == "SOURCE_VALUE_CONFLICT"
        assert "no translation mismatch is inferred" in item["category_explanation"]


def test_source_mismatch_for_completeness_not_claimed_null():
    result = product_category_evidence(
        "products.category",
        product_row(rule_id="products.category", original_category_name="moveis_decoracao"),
    )
    assert result["category_condition"] == "SOURCE_VALUE_CONFLICT"


def test_missing_json_columns_not_fabricated_from_run_level_failure():
    result = normalize_failed_record_preview("products", "products.category", [
        {k:v for k,v in product_row("products.category").items()
         if k not in ("original_product_id", "original_category_name")}
    ])
    assert result["record_preview"] == [{
        "source_record_id": "products:11039",
        "failure_reason": "product_category_name exists in translation",
        "record_action": "WARN",
    }]


def test_unexpected_raw_source_json_and_private_fields_never_leave_api(monkeypatch):
    from app import main
    seen = []
    def sql_query(statement):
        seen.append(statement)
        return [product_row(
            original_values='{"customer_id":"SECRET_CUST","payment_value":"999"}',
            unrelated_source_field="SECRET_FIELD",
        )]
    monkeypatch.setattr(main, "sql_query", sql_query)
    out = failed_rule_records("products", "products.fk_product_category_name")
    assert len(seen) == 1
    assert out["preview_source"] == "detailed_failed_records"
    assert out["record_preview"][0]["original_product_id"] == "real-olist-product-abc123"
    payload = json.dumps(out)
    for forbidden in ("SECRET_CUST", "SECRET_FIELD", "payment_value",
                      "original_values", "product_name_lenght", "customer_id"):
        assert forbidden not in payload


def test_existing_run_result_id_fallback_still_fails_gracefully_without_business_details():
    result = normalize_failed_record_sample("products", "products.category", [{
        "published_run": "active-published-run", "dataset": "products",
        "rule_id": "products.category", "rule_action": "WARN",
        "failed_evaluations": 610,
        "sample_failed_identifiers": '["products:11039"]',
    }])
    item = result["record_preview"][0]
    assert item["source_record_id"] == "products:11039"
    assert "original_product_id" not in item
    assert "category_condition" not in item
    assert result["preview_source"] == "published_rule_result_sample"


def test_shared_ui_uses_safe_expandable_product_evidence_in_both_inspectors():
    assert "function renderProductCategoryEvidence(parent,record,evidence,index)" in HTML
    assert "if(index===0)item.open=true" in HTML
    assert "Olist product ID: " in HTML
    assert "Source product_category_name (Portuguese key)" in HTML
    assert "Missing category · NULL" in HTML
    assert "Missing category · empty string" in HTML
    assert "Missing translation reference" in HTML
    assert "Stored source value conflicts with the rule result" in HTML
    assert "WARN findings do not automatically exclude products." in HTML
    assert "renderProductCategoryEvidence(parent,record,evidence,index);return;" in HTML
    assert "renderFailedRecordEvidence($('qualityRecords'),record,evidence,i)" in HTML
    assert "rows.forEach((record,index)=>renderFailedRecordEvidence(panel,record,evidence,index))" in HTML
    assert "textContent" in HTML
    assert "innerHTML=record" not in HTML


def test_nexus_inline_script_still_parses_as_javascript(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js unavailable")
    script = HTML.rsplit("<script>", 1)[1].split("</script>", 1)[0]
    path = tmp_path / "nexus.js"
    path.write_text(script, encoding="utf-8")
    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
