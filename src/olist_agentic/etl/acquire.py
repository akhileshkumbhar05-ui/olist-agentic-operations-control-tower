"""Immutable raw landing with checksum verification; Kaggle cache is staging only."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import shutil
import os
import tempfile
import pandas as pd
from olist_agentic.domain.sources import SOURCES

HANDLE = "olistbr/brazilian-ecommerce"


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def verify_raw(raw: Path) -> dict:
    manifest = json.loads((raw / "manifest.json").read_text())
    for name, spec in SOURCES.items():
        path = raw / spec.filename
        if checksum(path) != manifest["files"][name]["sha256"]:
            raise ValueError(f"Raw checksum mismatch: {name}")
    return manifest


def land(raw: Path, source: Path | None = None) -> dict:
    if (raw / "manifest.json").exists():
        return verify_raw(raw)
    if source is None:
        os.environ.setdefault("KAGGLEHUB_CACHE", str(Path(tempfile.gettempdir()) / "olist-kaggle-cache"))
        import kagglehub
        source = Path(kagglehub.dataset_download(HANDLE))
    raw.mkdir(parents=True, exist_ok=True)
    files = {}
    for name, spec in SOURCES.items():
        candidate = source / spec.filename
        header = pd.read_csv(candidate, nrows=0)
        target = raw / spec.filename
        digest = checksum(candidate)
        if target.exists() and checksum(target) != digest:
            raise ValueError(f"Refusing to overwrite different raw source: {target}")
        if not target.exists():
            shutil.copy2(candidate, target)
        files[name] = {"filename": spec.filename, "bytes": target.stat().st_size,
                       "sha256": digest, "actual_columns": header.columns.tolist(),
                       "header_matches_contract": set(header.columns) == set(spec.columns)}
    manifest = {"dataset": HANDLE, "landed_at": datetime.now(timezone.utc).isoformat(),
                "files": files, "source": "Kaggle historical public dataset"}
    (raw / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def read_sources(raw: Path) -> dict[str, pd.DataFrame]:
    verify_raw(raw)
    # String types preserve ZIP leading zeroes and original source values.
    return {name: pd.read_csv(raw / spec.filename, dtype="string", keep_default_na=False,
                             na_values=[""]) for name, spec in SOURCES.items()}
