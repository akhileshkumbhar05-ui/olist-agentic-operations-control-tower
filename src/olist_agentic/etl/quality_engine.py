from dataclasses import dataclass
import json
import pandas as pd
from olist_agentic.domain.rules import Rule, RULES


@dataclass
class QualityResult:
    results: pd.DataFrame
    failures: pd.DataFrame
    quarantine: pd.DataFrame
    scorecard: pd.DataFrame
    accepted: dict[str, pd.DataFrame]


def readiness(results: pd.DataFrame) -> str:
    if results.empty or results.status.isin(["ERROR", "SKIPPED"]).any():
        return "BLOCKED"
    failed = results[results.status == "FAILED"]
    if ((failed.severity == "CRITICAL") | (failed.action == "FAIL")).any():
        return "BLOCKED"
    return "WARNING" if len(failed) else "READY"


def quality_score(results: pd.DataFrame) -> float:
    # Rule-record opportunities, not distinct records; all rules equally weighted.
    denominator = results.records_evaluated.sum()
    return round(100 * (1 - results.records_failed.sum() / denominator), 4) if denominator else 0.0


def mask_for(rule: Rule, df: pd.DataFrame, tables: dict[str, pd.DataFrame]) -> pd.Series:
    false = pd.Series(False, index=df.index)
    cols = list(rule.columns)
    if rule.kind == "schema":
        return pd.Series(set(df.columns) != set(cols), index=df.index)
    if not set(cols).issubset(df.columns):
        raise ValueError(f"Missing fields for {rule.rule_id}")
    s = df[cols[0]]
    if rule.kind == "required":
        return df[cols].isna().any(axis=1) | df[cols].eq("").any(axis=1)
    if rule.kind == "unique":
        return df.duplicated(cols, keep=False) & ~df[cols].isna().any(axis=1)
    if rule.kind == "fk":
        return s.notna() & ~s.isin(tables[rule.parent][rule.parent_key])
    if rule.kind == "number":
        import numpy as np
        parsed = pd.to_numeric(s, errors="coerce")
        return s.notna() & (parsed.isna() | ~np.isfinite(parsed.fillna(0).astype(float)))
    if rule.kind == "timestamp":
        return s.notna() & pd.to_datetime(s, errors="coerce", format="mixed").isna()
    if rule.kind == "domain":
        return s.isna() | ~s.isin(rule.values)
    if rule.kind in ("range", "nonnegative"):
        n = pd.to_numeric(s, errors="coerce")
        return n.notna() & ((n < float(rule.values[0])) | (n > float(rule.values[1]))) if rule.kind == "range" else n.notna() & (n < 0)
    if rule.kind == "delivered_required":
        return df.order_status.eq("delivered") & s.isna()
    if rule.kind == "lifecycle":
        failed = false.copy()
        for left, right in zip(cols, cols[1:]):
            l = pd.to_datetime(df[left], errors="coerce", format="mixed")
            r = pd.to_datetime(df[right], errors="coerce", format="mixed")
            failed |= l.notna() & r.notna() & (l > r)
        return df.order_status.eq("delivered") & failed
    if rule.kind == "reconciliation":
        items = tables["order_items"].copy()
        items["amount"] = pd.to_numeric(items.price, errors="coerce") + pd.to_numeric(items.freight_value, errors="coerce")
        item = items.groupby("order_id").amount.sum(min_count=1)
        payments = tables["payments"].copy()
        payments["amount"] = pd.to_numeric(payments.payment_value, errors="coerce")
        pay = payments.groupby("order_id").amount.sum(min_count=1)
        i, p = df.order_id.map(item), df.order_id.map(pay)
        return i.notna() & p.notna() & ((i - p).abs() > 0.010001)
    raise ValueError(rule.kind)


FAILURE_COLUMNS = ["run_id", "dataset", "source_record_id", "rule_id", "rule_name", "severity", "action", "failure_reason", "quarantine_timestamp", "original_values"]


def evaluate(tables, run_id, timestamp, rules=RULES) -> QualityResult:
    results, failures = [], []
    excluded = {name: set() for name in tables}
    for rule in rules:
        if not rule.active_flag:
            continue
        df = tables[rule.dataset]
        try:
            mask = mask_for(rule, df, tables).fillna(False)
            bad = df.loc[mask]
            count = len(bad)
            status = "FAILED" if count else "PASSED"
            error = ""
        except (ValueError, KeyError) as exc:
            bad = df
            count, status, error = 0, "ERROR", str(exc)
            excluded[rule.dataset].update(df.index)
        evaluated = 0 if status == "ERROR" else len(df)
        effective_action = "FAIL" if status == "ERROR" else rule.action
        # Schema is a table-level check even on empty input.
        if rule.kind == "schema":
            evaluated = 1
            count = int(set(df.columns) != set(rule.columns))
            status = "FAILED" if count else "PASSED"
        results.append({**rule.record(), "run_id": run_id, "execution_timestamp": timestamp,
                        "records_evaluated": evaluated, "records_failed": count,
                        "failure_percentage": 100 * count / evaluated if evaluated else 0.0,
                        "status": status, "error_message": error,
                        "sample_failed_identifiers": json.dumps([str(i) for i in bad.index[:10]])})
        if effective_action in {"QUARANTINE", "FAIL"}:
            excluded[rule.dataset].update(bad.index)
        for idx, row in bad.iterrows():
            failures.append({"run_id": run_id, "dataset": rule.dataset,
                             "source_record_id": str(idx), "rule_id": rule.rule_id,
                             "rule_name": rule.rule_name, "severity": rule.severity,
                             "action": effective_action, "failure_reason": error or rule.description or rule.rule_name,
                             "quarantine_timestamp": timestamp,
                             "original_values": json.dumps(row.dropna().to_dict(), default=str, ensure_ascii=False)})
    results = pd.DataFrame(results)
    failures = pd.DataFrame(failures, columns=FAILURE_COLUMNS)
    quarantine = failures[failures.action.isin(["QUARANTINE", "FAIL"])].copy()
    scorecard = pd.DataFrame([{"run_id": run_id, "dataset": name, "quality_score": quality_score(r),
                               "readiness": readiness(r), "rules_executed": len(r),
                               "rules_failed": int((r.status == "FAILED").sum()),
                               "source_records": len(tables[name]), "accepted_records": len(tables[name]) - len(excluded[name]),
                               "quarantined_records": len(excluded[name])}
                              for name, r in results.groupby("dataset")])
    accepted = {name: df.loc[~df.index.isin(excluded[name])].copy() for name, df in tables.items()}
    return QualityResult(results, failures, quarantine, scorecard, accepted)
