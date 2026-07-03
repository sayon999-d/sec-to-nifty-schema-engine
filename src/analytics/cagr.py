from __future__ import annotations

import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Mapping

if __package__ in {None, ""}:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from analytics.common import MetricOutcome, as_float
else:
    from .common import MetricOutcome, as_float


def calculate_cagr(start: float | int | None, end: float | int | None, years: int) -> MetricOutcome:
    start_value = as_float(start)
    end_value = as_float(end)
    if years <= 0 or start_value is None or end_value is None:
        return MetricOutcome(value=None, flag="INSUFFICIENT")
    if start_value == 0:
        return MetricOutcome(value=None, flag="ZERO_BASE")

    start_positive = start_value > 0
    end_positive = end_value > 0
    if start_positive and end_positive:
        return MetricOutcome(value=((end_value / start_value) ** (1.0 / years) - 1.0) * 100.0)
    if start_positive and not end_positive:
        return MetricOutcome(value=None, flag="DECLINE_TO_LOSS")
    if not start_positive and end_positive:
        return MetricOutcome(value=None, flag="TURNAROUND")
    return MetricOutcome(value=None, flag="BOTH_NEGATIVE")


def compute_cagr_windows(
    history: Mapping[int, float | int | None],
    *,
    end_year: int,
    windows: tuple[int, ...] = (3, 5, 10),
) -> dict[int, MetricOutcome]:
    results: dict[int, MetricOutcome] = {}
    for window in windows:
        start_year = end_year - window
        if start_year not in history or end_year not in history:
            results[window] = MetricOutcome(value=None, flag="INSUFFICIENT")
            continue
        results[window] = calculate_cagr(history[start_year], history[end_year], window)
        if results[window].flag is None and history[start_year] is None:
            results[window] = MetricOutcome(value=None, flag="INSUFFICIENT")
    return results


def compute_metric_cagrs(
    metric_histories: Mapping[str, Mapping[int, float | int | None]],
    *,
    end_year: int,
    windows: tuple[int, ...] = (3, 5, 10),
) -> dict[str, MetricOutcome]:
    results: dict[str, MetricOutcome] = {}
    for metric_name, history in metric_histories.items():
        for window, outcome in compute_cagr_windows(history, end_year=end_year, windows=windows).items():
            results[f"{metric_name}_cagr_{window}yr"] = outcome
    return results
