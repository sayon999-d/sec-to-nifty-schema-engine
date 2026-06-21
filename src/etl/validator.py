from __future__ import annotations

import csv
import dataclasses
import datetime as _dt
import json
import math
from collections import defaultdict
import os
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


@dataclasses.dataclass(frozen=True)
class ValidationFailure:
    rule_id: str
    company_id: str
    record_context: str
    failure_severity: str
    timestamp: str


class ValidationError(RuntimeError):
    """Raised when a critical data-quality rule blocks the load."""

class DQValidator:
    """Row-by-row quality gate with CSV failure logging for Sprint 1."""

    def __init__(
        self,
        failure_log_path: Path,
        known_company_ids: Iterable[Any] | None = None,
    ) -> None:
        self.failure_log_path = Path(failure_log_path)
        self.known_company_ids = {str(value) for value in (known_company_ids or [])}
        self._seen_primary_keys: set[tuple[Any, ...]] = set()
        self._seen_periodic_keys: dict[str, set[tuple[Any, Any]]] = defaultdict(set)
        self.balance_tolerance_pct = self._env_float("NIFTY100_BALANCE_SHEET_TOLERANCE_PCT", 1.0)
        self._ensure_log_header()

    @staticmethod
    def _env_float(name: str, default: float) -> float:
        raw = os.environ.get(name)
        if raw is None:
            return default
        try:
            return float(raw)
        except ValueError:
            return default

    def _ensure_log_header(self) -> None:
        self.failure_log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.failure_log_path.exists():
            with self.failure_log_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle,
                    fieldnames=[
                        "rule_id",
                        "company_id",
                        "record_context",
                        "failure_severity",
                        "timestamp",
                    ],
                )
                writer.writeheader()

    def _append_failure(self, failure: ValidationFailure) -> None:
        with self.failure_log_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "rule_id",
                    "company_id",
                    "record_context",
                    "failure_severity",
                    "timestamp",
                ],
            )
            writer.writerow(dataclasses.asdict(failure))

    @staticmethod
    def _now() -> str:
        return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    @staticmethod
    def _safe_json(record: Mapping[str, Any]) -> str:
        def _default(value: Any) -> Any:
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return str(value)

        return json.dumps(record, default=_default, sort_keys=True, ensure_ascii=True)

    @staticmethod
    def _to_number(value: Any) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            if isinstance(value, float) and math.isnan(value):
                return None
            return float(value)
        try:
            parsed = float(str(value).replace(",", "").strip())
        except Exception:
            return None
        if math.isnan(parsed):
            return None
        return parsed

    @staticmethod
    def _sign(value: float | None) -> int | None:
        if value is None or value == 0:
            return 0 if value == 0 else None
        return 1 if value > 0 else -1

    @staticmethod
    def _is_valid_url(value: Any) -> bool:
        if not value:
            return True
        parsed = urlparse(str(value).strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _log(self, rule_id: str, company_id: Any, record: Mapping[str, Any], severity: str) -> ValidationFailure:
        failure = ValidationFailure(
            rule_id=rule_id,
            company_id="" if company_id is None else str(company_id),
            record_context=self._safe_json(dict(record)),
            failure_severity=severity,
            timestamp=self._now(),
        )
        self._append_failure(failure)
        return failure

    def validate_record(
        self,
        record: Mapping[str, Any],
        table_name: str,
        pk_fields: tuple[str, ...] = ("id",),
        periodic: bool = False,
    ) -> list[ValidationFailure]:

        failures: list[ValidationFailure] = []
        critical_failures: list[ValidationFailure] = []

        def warn(rule_id: str, condition: bool) -> None:
            if condition:
                failure = self._log(rule_id, record.get("company_id"), record, "WARNING")
                failures.append(failure)

        def critical(rule_id: str, condition: bool) -> None:
            if condition:
                failure = self._log(rule_id, record.get("company_id"), record, "CRITICAL")
                failures.append(failure)
                critical_failures.append(failure)

        # DQ-01: primary key uniqueness across dimensions
        pk_value = tuple(record.get(field) for field in pk_fields)
        if all(value is not None for value in pk_value):
            duplicate_key = (table_name, pk_value)
            critical("DQ-01", duplicate_key in self._seen_primary_keys)
            self._seen_primary_keys.add(duplicate_key)

        # DQ-02: composite company/year uniqueness on periodic tables
        if periodic:
            company_id = record.get("company_id")
            financial_year = record.get("financial_year") or record.get("year")
            if company_id is not None and financial_year is not None:
                periodic_key = (str(company_id), financial_year)
                duplicate_periodic = periodic_key in self._seen_periodic_keys[table_name]
                critical("DQ-02", duplicate_periodic)
                self._seen_periodic_keys[table_name].add(periodic_key)

        # DQ-03: FK integrity back to master companies
        company_id = record.get("company_id")
        if company_id is not None and self.known_company_ids:
            critical("DQ-03", str(company_id) not in self.known_company_ids)

        revenue = self._to_number(record.get("revenue") or record.get("sales"))
        cost = self._to_number(record.get("cost_of_goods_sold") or record.get("costs"))
        operating_profit = self._to_number(record.get("operating_profit"))
        opm = self._to_number(record.get("operating_profit_margin"))
        total_assets = self._to_number(record.get("total_assets"))
        total_liabilities = self._to_number(record.get("total_liabilities"))
        net_income = self._to_number(record.get("net_income") or record.get("profit_after_tax"))
        eps = self._to_number(record.get("eps") or record.get("earnings_per_share"))
        tax_rate = self._to_number(record.get("tax_rate"))
        dividend = self._to_number(record.get("dividend"))
        dividend_payout = self._to_number(record.get("dividend_payout_ratio"))
        net_cash_flow = self._to_number(record.get("net_cash_flow"))
        interest_coverage = self._to_number(record.get("interest_coverage_ratio"))
        debt_to_equity = self._to_number(record.get("debt_to_equity"))
        current_ratio = self._to_number(record.get("current_ratio"))
        valuation_multiple = self._to_number(record.get("pe_ratio") or record.get("price_to_earnings_ratio"))
        url_value = record.get("source_url") or record.get("document_url") or record.get("url")
        shares_outstanding = self._to_number(record.get("shares_outstanding"))

        # DQ-04: balance sheet tolerance below 1%
        if total_assets is not None and total_liabilities is not None and total_assets != 0:
            gap_pct = abs(total_assets - total_liabilities) / abs(total_assets) * 100.0
            warn("DQ-04", gap_pct > self.balance_tolerance_pct)

        # DQ-05: operating profit margin cross-check
        if revenue not in (None, 0) and operating_profit is not None and opm is not None:
            if cost is not None:
                calculated_opm = ((revenue - cost) / revenue) * 100.0
            else:
                calculated_opm = (operating_profit / revenue) * 100.0
            warn("DQ-05", abs(calculated_opm - opm) > 1.0)

        # DQ-06: revenue/sales must be positive
        if revenue is not None:
            warn("DQ-06", revenue <= 0)

        # DQ-07: net cash flow boundaries
        if net_cash_flow is not None:
            warn("DQ-07", abs(net_cash_flow) > 1_000_000_000_000.0)

        if tax_rate is not None:
            warn("DQ-08", tax_rate < 0 or tax_rate > 0.45)

        if dividend is not None:
            warn("DQ-09", dividend < 0 or (eps is not None and abs(dividend) > max(abs(eps) * 2.0, 1.0)))
        elif dividend_payout is not None:
            warn("DQ-09", dividend_payout < 0 or dividend_payout > 1.0)

        if url_value is not None:
            warn("DQ-10", not self._is_valid_url(url_value))

        if eps is not None and net_income is not None and eps != 0 and net_income != 0:
            warn("DQ-11", self._sign(eps) != self._sign(net_income))

        if total_assets is not None:
            warn("DQ-12", total_assets < 0 or total_assets > 1_000_000_000_000_000.0)
        if total_liabilities is not None:
            warn("DQ-12", total_liabilities < 0 or total_liabilities > 1_000_000_000_000_000.0)

        if interest_coverage is not None:
            warn("DQ-13", interest_coverage < 1.5)

        if debt_to_equity is not None:
            warn("DQ-14", debt_to_equity < 0 or debt_to_equity > 10.0)

        if current_ratio is not None:
            warn("DQ-15", current_ratio < 0.5 or current_ratio > 10.0)

        if valuation_multiple is not None:
            warn("DQ-16", valuation_multiple < 0 or valuation_multiple > 1000.0)
        elif shares_outstanding is not None:
            warn("DQ-16", shares_outstanding <= 0)

        if critical_failures:
            raise ValidationError(
                f"critical validation failure(s) in {table_name}: "
                + ", ".join(f.rule_id for f in critical_failures)
            )

        return failures

    def validate_rows(
        self,
        rows: Iterable[Mapping[str, Any]],
        table_name: str,
        pk_fields: tuple[str, ...] = ("id",),
        periodic: bool = False,
    ) -> list[ValidationFailure]:
        failures: list[ValidationFailure] = []
        for record in rows:
            failures.extend(self.validate_record(record, table_name=table_name, pk_fields=pk_fields, periodic=periodic))
        return failures
