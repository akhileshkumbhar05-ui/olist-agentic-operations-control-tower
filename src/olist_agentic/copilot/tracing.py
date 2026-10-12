"""Best-effort MLflow spans plus a privacy-bounded local execution audit.

The audit is independent from MLflow's artifact upload and can help diagnose
restricted Databricks App network egress. It never records questions, prompts,
SQL, answer text, data rows, tokens, or exception messages.
"""
from __future__ import annotations

import json
import logging
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import lru_cache
from time import perf_counter
from uuid import uuid4

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("olist.execution")
if not audit_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(handler)
audit_logger.setLevel(logging.INFO)
audit_logger.propagate = False

_request_id = ContextVar("olist_request_id", default=None)
_active_span = ContextVar("olist_active_span", default=None)
_active_details = ContextVar("olist_active_details", default=None)
_SAFE_TEXT_KEYS = frozenset({"model", "generation", "route", "tool", "endpoint"})
_SAFE_COUNT_KEYS = frozenset({"row_count", "hit_count", "function_call_count", "max_output_tokens"})
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def _auditing() -> bool:
    return os.getenv("OLIST_EXECUTION_AUDIT_LOGS", "").lower() in {"1", "true", "yes"}


def _safe_attributes(attributes: dict | None) -> dict:
    result = {}
    for key, value in (attributes or {}).items():
        if key in _SAFE_TEXT_KEYS and isinstance(value, str) and _SAFE_VALUE.fullmatch(value):
            result[key] = value
        elif key in _SAFE_COUNT_KEYS and type(value) in (int, float) and 0 <= value <= 10000000:
            result[key] = value
    return result


@lru_cache(maxsize=1)
def _mlflow():
    if not os.getenv("MLFLOW_EXPERIMENT_ID", "").strip():
        return None
    try:
        import mlflow
        mlflow.set_tracking_uri("databricks")
        mlflow.set_experiment(experiment_id=os.environ["MLFLOW_EXPERIMENT_ID"])
        logger.info("MLflow tracing initialized for experiment %s",
                    os.environ["MLFLOW_EXPERIMENT_ID"])
        return mlflow
    except Exception:
        logger.exception("MLflow trace setup failed; continuing without tracing")
        return None


def set_span_attributes(span, attributes: dict) -> None:
    # Capture only fixed-format operational metadata. Never emit raw prompt/data.
    details = _active_details.get()
    if details is not None:
        details.update(_safe_attributes(attributes))
    if span is not None:
        try:
            span.set_attributes(attributes)
        except Exception:
            logger.exception("MLflow span metadata update failed")


@contextmanager
def _mlflow_span(name: str, span_type: str, attributes: dict | None = None):
    """Original MLflow behavior; a trace export failure cannot change answers."""
    mlflow = _mlflow()
    if mlflow is None:
        yield None
        return
    try:
        manager = mlflow.start_span(name=name, span_type=span_type,
                                    attributes=attributes or {})
        span = manager.__enter__()
    except Exception:
        logger.exception("MLflow span start failed: %s", name)
        yield None
        return
    try:
        yield span
    except BaseException as exc:
        try:
            manager.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            logger.exception("MLflow span close failed: %s", name)
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception:
            logger.exception("MLflow span close failed: %s", name)


@contextmanager
def trace_span(name: str, span_type: str, attributes: dict | None = None):
    """Emit MLflow spans and optionally independent, content-free audit events."""
    if not _auditing():
        with _mlflow_span(name, span_type, attributes) as span:
            yield span
        return

    # ContextVars isolate concurrent FastAPI requests and parent-child spans.
    new_request = _request_id.get() is None
    request_token = _request_id.set(uuid4().hex[:16]) if new_request else None
    request_id = _request_id.get()
    parent = _active_span.get()
    span_token = _active_span.set(name)
    details = _safe_attributes(attributes)
    details_token = _active_details.set(details)
    start = perf_counter()
    started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    status = "ok"
    error_type = None
    try:
        with _mlflow_span(name, span_type, attributes) as span:
            yield span
    except BaseException as exc:
        status = "error"
        error_type = type(exc).__name__  # No exception text or sensitive payload.
        raise
    finally:
        try:
            record = {
                "event": "olist.execution.span",
                "request_id": request_id,
                "name": name,
                "parent": parent,
                "kind": span_type,
                "start_utc": started_at,
                "duration_ms": round((perf_counter() - start) * 1000, 2),
                "status": status,
                "attributes": details,
            }
            if error_type is not None:
                record["error_type"] = error_type
            audit_logger.info("OLIST_TRACE %s", json.dumps(record, separators=(",", ":")))
        except Exception:
            # Telemetry must never change an agent answer.
            logger.exception("Olist local span audit failed")
        finally:
            _active_details.reset(details_token)
            _active_span.reset(span_token)
            if request_token is not None:
                _request_id.reset(request_token)
