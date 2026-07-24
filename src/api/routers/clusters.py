from __future__ import annotations

"""Cluster summary endpoints."""

from pathlib import Path

import pandas as pd

from api._compat import HTTPException, JSONResponse, APIRouter

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_DIR = PROJECT_ROOT / "output"
CLUSTER_LABELS = OUTPUT_DIR / "cluster_labels.csv"
OUTLIER_REPORT = OUTPUT_DIR / "outlier_report.csv"
PORTFOLIO_STATS = OUTPUT_DIR / "portfolio_stats.csv"
ELBOW_PLOT = PROJECT_ROOT / "reports" / "elbow_plot.png"
CORRELATION_PLOT = PROJECT_ROOT / "reports" / "correlation_heatmap.png"

router = APIRouter()


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


@router.get("/clusters")
def clusters() -> JSONResponse:
    """Return the clustering summary artifacts."""

    labels = _read_csv(CLUSTER_LABELS)
    outliers = _read_csv(OUTLIER_REPORT)
    stats = _read_csv(PORTFOLIO_STATS)
    if labels.empty:
        raise HTTPException(404, "Cluster labels not found")
    summary = {
        "cluster_labels": labels.fillna("").to_dict(orient="records"),
        "cluster_counts": labels.groupby("cluster_id", dropna=False).size().reset_index(name="count").to_dict(orient="records"),
        "outliers": outliers.fillna("").to_dict(orient="records"),
        "portfolio_stats": stats.fillna("").to_dict(orient="records"),
        "plots": {
            "elbow_plot": str(ELBOW_PLOT) if ELBOW_PLOT.exists() else None,
            "correlation_heatmap": str(CORRELATION_PLOT) if CORRELATION_PLOT.exists() else None,
        },
    }
    return JSONResponse(summary)


@router.get("/clusters/{cluster_id}")
def cluster_detail(cluster_id: int) -> JSONResponse:
    """Return companies in a single cluster."""

    labels = _read_csv(CLUSTER_LABELS)
    if labels.empty:
        raise HTTPException(404, "Cluster labels not found")
    result = labels.loc[pd.to_numeric(labels["cluster_id"], errors="coerce").eq(int(cluster_id))]
    if result.empty:
        raise HTTPException(404, f"Cluster not found: {cluster_id}")
    return JSONResponse(result.fillna("").to_dict(orient="records"))

