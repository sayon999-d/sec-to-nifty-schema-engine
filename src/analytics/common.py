from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class MetricOutcome:
    value: float | None
    label: str | None = None
    flag: str | None = None
    high_leverage_flag: bool = False
    icr_warning_flag: bool = False


EDGE_LOG_FIELDS = [
    "timestamp",
    "category",
    "company_id",
    "financial_year",
    "metric",
    "computed_value",
    "source_value",
    "detail",
]


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if parsed != parsed:
        return None
    return parsed


def sign_of(value: Any) -> int:
    number = as_float(value)
    if number is None or number == 0:
        return 0
    return 1 if number > 0 else -1


def safe_divide(numerator: Any, denominator: Any) -> float | None:
    num = as_float(numerator)
    den = as_float(denominator)
    if num is None or den is None or den == 0:
        return None
    return num / den


def is_financials_sector(value: str | None) -> bool:
    if not value:
        return False
    cleaned = value.strip().lower()
    return "financial" in cleaned or cleaned in {"banking", "nbfc", "banks", "financials"}


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def append_edge_case_log(
    path: Path,
    *,
    category: str,
    company_id: Any,
    financial_year: Any,
    metric: str,
    computed_value: Any,
    source_value: Any,
    detail: str,
) -> None:
    ensure_parent(path)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as handle:
        if is_new:
            handle.write(",".join(EDGE_LOG_FIELDS) + "\n")
        handle.write(
            ",".join(
                [
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    str(category),
                    "" if company_id is None else str(company_id),
                    "" if financial_year is None else str(financial_year),
                    str(metric),
                    "" if computed_value is None else str(computed_value),
                    "" if source_value is None else str(source_value),
                    detail.replace("\n", " ").replace(",", ";"),
                ]
            )
            + "\n"
        )


def rolling_average(values: Iterable[float | None]) -> float | None:
    cleaned = [float(value) for value in values if value is not None]
    if not cleaned:
        return None
    return sum(cleaned) / len(cleaned)

