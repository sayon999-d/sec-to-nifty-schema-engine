from __future__ import annotations
import logging
import math
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("MPLCONFIGDIR", str(PROJECT_ROOT / ".matplotlib"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

KMeans = None
StandardScaler = None

DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
OUTPUT_DIR = PROJECT_ROOT / "output"
REPORTS_DIR = PROJECT_ROOT / "reports"
CORRELATION_PATH = REPORTS_DIR / "correlation_heatmap.png"
ELBOW_PATH = REPORTS_DIR / "elbow_plot.png"
CLUSTER_LABELS_PATH = OUTPUT_DIR / "cluster_labels.csv"
OUTLIER_REPORT_PATH = OUTPUT_DIR / "outlier_report.csv"
PORTFOLIO_STATS_PATH = OUTPUT_DIR / "portfolio_stats.csv"

LOGGER = logging.getLogger(__name__)
if not LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)

CLUSTER_NAME_MAP = {
    0: "High-Quality Compounders",
    1: "Defensive Dividend Payers",
    2: "Value Cyclicals",
    3: "Distressed or Turnaround",
    4: "Emerging Growth",
}

CLUSTER_FEATURES = [
    "return_on_equity_pct",
    "debt_to_equity",
    "revenue_cagr_5yr",
    "fcf_cagr_5yr",
    "operating_profit_margin_pct",
]

PORTFOLIO_KPIS = [
    "return_on_equity_pct",
    "debt_to_equity",
    "revenue_cagr_5yr",
    "fcf_cagr_5yr",
    "operating_profit_margin_pct",
    "net_profit_margin_pct",
    "interest_coverage",
    "composite_quality_score",
    "pe_ratio",
    "pb_ratio",
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def _ensure_output_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _standard_scaler() -> Any:
    if StandardScaler is not None:
        return StandardScaler()

    @dataclass
    class _FallbackScaler:
        mean_: np.ndarray | None = None
        scale_: np.ndarray | None = None

        def fit(self, data: np.ndarray) -> "_FallbackScaler":
            self.mean_ = np.nanmean(data, axis=0)
            self.scale_ = np.nanstd(data, axis=0)
            self.scale_[self.scale_ == 0] = 1.0
            return self

        def transform(self, data: np.ndarray) -> np.ndarray:
            assert self.mean_ is not None and self.scale_ is not None
            return (data - self.mean_) / self.scale_

        def fit_transform(self, data: np.ndarray) -> np.ndarray:
            return self.fit(data).transform(data)

    return _FallbackScaler()


def _fallback_kmeans(data: np.ndarray, n_clusters: int, random_state: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(random_state)
    if len(data) < n_clusters:
        centers = data.copy()
        labels = np.arange(len(data)) % max(1, len(data))
        return labels, centers

    indices = rng.choice(len(data), n_clusters, replace=False)
    centers = data[indices].copy()
    for _ in range(100):
        distances = np.linalg.norm(data[:, None, :] - centers[None, :, :], axis=2)
        labels = distances.argmin(axis=1)
        new_centers = np.array(
            [
                data[labels == idx].mean(axis=0) if np.any(labels == idx) else centers[idx]
                for idx in range(n_clusters)
            ]
        )
        if np.allclose(new_centers, centers, equal_nan=True):
            break
        centers = new_centers
    return labels, centers


def _read_frame() -> pd.DataFrame:
    query = """
        WITH latest AS (
            SELECT company_id, MAX(financial_year) AS financial_year
            FROM financial_ratios
            WHERE financial_year <= 2024
            GROUP BY company_id
        )
        SELECT
            fr.company_id,
            c.company_name,
            c.ticker,
            fr.financial_year AS year,
            s.sector_name,
            s.industry_name,
            s.sub_industry_name,
            fr.return_on_equity_pct,
            fr.debt_to_equity,
            fr.revenue_cagr_5yr,
            fr.operating_profit_margin_pct,
            fr.net_profit_margin_pct,
            fr.interest_coverage,
            fr.composite_quality_score,
            fr.free_cash_flow_cr,
            fr.cash_from_operations_cr,
            fr.pat_cagr_5yr,
            fr.eps_cagr_5yr,
            p.revenue,
            p.operating_profit,
            p.net_income,
            mc.market_cap_crore,
            mc.pe_ratio,
            mc.pb_ratio
        FROM financial_ratios fr
        JOIN latest l
          ON l.company_id = fr.company_id
         AND l.financial_year = fr.financial_year
        JOIN companies c ON c.id = fr.company_id
        LEFT JOIN sectors s ON s.company_id = fr.company_id
        LEFT JOIN profitandloss p
          ON p.company_id = fr.company_id
         AND p.financial_year = fr.financial_year
        LEFT JOIN market_cap mc
          ON mc.company_id = fr.company_id
         AND mc.financial_year = fr.financial_year
        ORDER BY fr.company_id;
    """
    with _connect() as conn:
        frame = pd.read_sql_query(query, conn)
        if frame.empty:
            return frame
    frame["broad_sector"] = frame["sector_name"].fillna("Unknown")
    frame = _attach_fcf_cagr(frame)
    for column in CLUSTER_FEATURES + PORTFOLIO_KPIS + ["market_cap_crore"]:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _attach_fcf_cagr(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    with _connect() as conn:
        cashflow = pd.read_sql_query(
            """
            SELECT
                company_id,
                financial_year AS year,
                COALESCE(net_cash_from_operations, 0) + COALESCE(net_cash_from_investing, 0) AS free_cash_flow_cr
            FROM cashflow
            WHERE financial_year BETWEEN 2019 AND 2024
            ORDER BY company_id, financial_year;
            """,
            conn,
        )
    rows: list[dict[str, float | int | None]] = []
    for company_id, group in cashflow.groupby("company_id"):
        ordered = pd.to_numeric(group["free_cash_flow_cr"], errors="coerce").dropna()
        if len(ordered) < 2:
            value = np.nan
        else:
            start = ordered.iloc[0]
            end = ordered.iloc[-1]
            years = max(len(ordered) - 1, 1)
            value = np.nan if start <= 0 else ((end / start) ** (1 / years) - 1) * 100.0
        rows.append({"company_id": int(company_id), "fcf_cagr_5yr": value})
    return frame.drop(columns=["fcf_cagr_5yr"], errors="ignore").merge(pd.DataFrame(rows), on="company_id", how="left")


def _sector_medians(frame: pd.DataFrame) -> pd.DataFrame:
    medians = (
        frame.groupby("broad_sector", dropna=False)[CLUSTER_FEATURES]
        .median(numeric_only=True)
        .reset_index()
        .rename(columns={"broad_sector": "sector"})
    )
    return medians


def _impute_and_scale(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    medians = _sector_medians(result).set_index("sector")
    for idx, row in result.iterrows():
        sector = row.get("broad_sector", "Unknown")
        for feature in CLUSTER_FEATURES:
            if pd.isna(row.get(feature)):
                sector_median = medians.loc[sector, feature] if sector in medians.index and feature in medians.columns else result[feature].median()
                result.at[idx, feature] = sector_median
    scaler = _standard_scaler()
    result[[f"{feature}_scaled" for feature in CLUSTER_FEATURES]] = scaler.fit_transform(result[CLUSTER_FEATURES].fillna(0).to_numpy())
    return result


def _cluster(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame[[f"{feature}_scaled" for feature in CLUSTER_FEATURES]].fillna(0).to_numpy(dtype=float)
    if KMeans is not None:
        model = KMeans(n_clusters=5, random_state=42, n_init=10)
        labels = model.fit_predict(data)
        centers = model.cluster_centers_
    else:  # pragma: no cover - fallback
        labels, centers = _fallback_kmeans(data, n_clusters=5, random_state=42)
    distances = np.linalg.norm(data - centers[labels], axis=1)
    clustered = frame.copy()
    clustered["cluster_id"] = labels
    clustered["distance_from_centroid"] = distances
    clustered["cluster_name"] = clustered["cluster_id"].map(CLUSTER_NAME_MAP).fillna("Emerging Growth")
    return clustered


def _inertia_for_k(data: np.ndarray, k: int) -> float:
    if len(data) == 0:
        return 0.0
    if len(data) <= k:
        _, centers = _fallback_kmeans(data, n_clusters=max(1, min(k, len(data))), random_state=42)
        if len(centers) == 0:
            return 0.0
        labels = np.arange(len(data)) % len(centers)
    else:
        labels, centers = _fallback_kmeans(data, n_clusters=k, random_state=42)
    return float(np.sum((data - centers[labels]) ** 2))


def _elbow_plot(frame: pd.DataFrame) -> None:
    data = frame[[f"{feature}_scaled" for feature in CLUSTER_FEATURES]].fillna(0).to_numpy(dtype=float)
    if data.size == 0:
        return
    ks = list(range(1, min(10, len(data)) + 1))
    inertias = [_inertia_for_k(data, k) for k in ks]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(ks, inertias, marker="o", linewidth=2, color="#1F77B4")
    ax.set_title("KMeans Elbow Plot")
    ax.set_xlabel("Number of Clusters (k)")
    ax.set_ylabel("Inertia")
    ax.grid(True, alpha=0.3)
    ax.set_xticks(ks)
    fig.tight_layout()
    fig.savefig(ELBOW_PATH, dpi=180)
    plt.close(fig)


def _correlation_heatmap(frame: pd.DataFrame) -> None:
    numeric = frame[PORTFOLIO_KPIS].apply(pd.to_numeric, errors="coerce")
    corr = numeric.corr(method="pearson")
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(14, 10))
    im = ax.imshow(corr.values, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)), corr.columns, rotation=45, ha="right")
    ax.set_yticks(range(len(corr.index)), corr.index)
    ax.set_title("10-KPI Pearson Correlation Matrix")
    for i in range(len(corr.index)):
        for j in range(len(corr.columns)):
            value = corr.iat[i, j]
            ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=8)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()
    fig.savefig(CORRELATION_PATH, dpi=180)
    plt.close(fig)


def _outliers(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for sector, sector_frame in frame.groupby("broad_sector", dropna=False):
        if sector_frame.empty:
            continue
        for metric in PORTFOLIO_KPIS:
            series = pd.to_numeric(sector_frame[metric], errors="coerce")
            std = series.std(ddof=0)
            mean = series.mean()
            if pd.isna(std) or std == 0:
                continue
            z_scores = (series - mean) / std
            for idx, z in z_scores.items():
                if pd.notna(z) and abs(float(z)) > 3:
                    row = sector_frame.loc[idx]
                    rows.append(
                        {
                            "company_id": int(row["company_id"]),
                            "company_name": row["company_name"],
                            "ticker": row["ticker"],
                            "sector": sector,
                            "metric": metric,
                            "z_score": float(z),
                            "value": None if pd.isna(row[metric]) else float(row[metric]),
                        }
                    )
    return pd.DataFrame(rows, columns=["company_id", "company_name", "ticker", "sector", "metric", "z_score", "value"])


def _portfolio_stats(frame: pd.DataFrame) -> pd.DataFrame:
    numeric = frame[PORTFOLIO_KPIS].apply(pd.to_numeric, errors="coerce")
    rows: list[dict[str, Any]] = []
    quantiles = {"P10": 0.10, "P25": 0.25, "P50": 0.50, "P75": 0.75, "P90": 0.90}
    for metric in PORTFOLIO_KPIS:
        series = numeric[metric].dropna()
        if series.empty:
            values = {name: np.nan for name in quantiles}
            mean = np.nan
            std = np.nan
        else:
            values = {name: float(series.quantile(q)) for name, q in quantiles.items()}
            mean = float(series.mean())
            std = float(series.std(ddof=0))
        rows.append({"metric": metric, **values, "Mean": mean, "Std Dev": std})
    return pd.DataFrame(rows)


def build_cluster_outputs() -> pd.DataFrame:
    """Build clustering, correlation, outlier, and portfolio statistics outputs."""

    _ensure_output_dirs()
    frame = _read_frame()
    if frame.empty:
        for path in [CLUSTER_LABELS_PATH, OUTLIER_REPORT_PATH, PORTFOLIO_STATS_PATH]:
            pd.DataFrame().to_csv(path, index=False)
        return frame
    frame = _attach_fcf_cagr(frame)
    frame = _impute_and_scale(frame)
    _elbow_plot(frame)
    clustered = _cluster(frame)
    clustered[["company_id", "cluster_id", "cluster_name", "distance_from_centroid"]].to_csv(CLUSTER_LABELS_PATH, index=False)
    _correlation_heatmap(clustered)
    _outliers(clustered).to_csv(OUTLIER_REPORT_PATH, index=False)
    _portfolio_stats(clustered).to_csv(PORTFOLIO_STATS_PATH, index=False)
    return clustered


def main() -> int:
    build_cluster_outputs()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
