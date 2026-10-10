"""Best-effort MLflow tracing with bounded, non-content metadata.

Trace failures must never change a governed answer or its fallback behavior.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _mlflow():
    if not os.getenv("MLFLOW_EXPERIMENT_ID", "").strip():
        return None
    try:
        import mlflow
        mlflow.set_experiment(experiment_id=os.environ["MLFLOW_EXPERIMENT_ID"])
        return mlflow
    except Exception:
        logger.exception("MLflow trace setup failed; continuing without tracing")
        return None


def set_span_attributes(span, attributes: dict) -> None:
    if span is not None:
        try:
            span.set_attributes(attributes)
        except Exception:
            logger.exception("MLflow span metadata update failed")


@contextmanager
def trace_span(name: str, span_type: str, attributes: dict | None = None):
    """Nest a span when configured, without letting trace export break serving."""
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
