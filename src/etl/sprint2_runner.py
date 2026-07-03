from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    SRC_ROOT = Path(__file__).resolve().parents[1]
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

from analytics.cagr import compute_metric_cagrs
from analytics.cashflow_kpis import (
    build_capital_allocation_frame,
    capex_intensity,
    cfo_quality_score,
    fcf_conversion_rate,
    free_cash_flow,
    load_cashflow_records,
)
from analytics.common import MetricOutcome, as_float, clamp, ensure_parent, is_financials_sector, sign_of
from analytics.ratios import (
    asset_turnover,
    debt_to_equity,
    interest_coverage_ratio,
    net_debt,
    net_profit_margin,
    operating_profit_margin,
    return_on_assets,
    return_on_capital_employed,
    return_on_equity,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "db" / "nifty100.db"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
DEFAULT_WORKBOOK_PATH = PROJECT_ROOT / "companies.xlsx"
PRIMARY_RATIO_METRICS = [
    "net_profit_margin_pct",
    "operating_profit_margin_pct",
    "return_on_equity_pct",
    "debt_to_equity",
    "interest_coverage",
    "asset_turnover",
    "free_cash_flow_cr",
    "capex_cr",
    "earnings_per_share",
    "book_value_per_share",
    "dividend_payout_ratio_pct",
    "total_debt_cr",
    "cash_from_operations_cr",
    "revenue_cagr_5yr",
    "pat_cagr_5yr",
    "eps_cagr_5yr",
    "composite_quality_score",
]


def _to_float(value: Any) -> float | None:
    return as_float(value)


def _legacy_metric(value: Any) -> float | None:
    number = as_float(value)
    return None if number is None else float(number)


class Sprint2RatioEngine:
    def __init__(
        self,
        db_path: Path | None = None,
        output_dir: Path | None = None,
        workbook_path: Path | None = None,
    ) -> None:
        self.db_path = Path(db_path or DEFAULT_DB_PATH)
        self.output_dir = Path(output_dir or DEFAULT_OUTPUT_DIR)
        self.workbook_path = Path(workbook_path or DEFAULT_WORKBOOK_PATH)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    @staticmethod
    def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return [str(row[1]) for row in rows]

    @staticmethod
    def _insert_frame(conn: sqlite3.Connection, table_name: str, frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        table_columns = Sprint2RatioEngine._table_columns(conn, table_name)
        payload_columns = [column for column in frame.columns if column in table_columns and column != "created_at"]
        payload = frame.loc[:, payload_columns].copy()
        if payload.empty:
            return 0
        payload.to_sql(table_name, conn, if_exists="append", index=False)
        return len(payload)

    def ensure_schema(self, conn: sqlite3.Connection) -> None:
        existing = set(self._table_columns(conn, "financial_ratios"))
        additions = [
            ("net_profit_margin_pct", "REAL"),
            ("operating_profit_margin_pct", "REAL"),
            ("return_on_equity_pct", "REAL"),
            ("return_on_capital_employed_pct", "REAL"),
            ("return_on_assets_pct", "REAL"),
            ("interest_coverage", "REAL"),
            ("asset_turnover", "REAL"),
            ("free_cash_flow_cr", "REAL"),
            ("capex_cr", "REAL"),
            ("earnings_per_share", "REAL"),
            ("book_value_per_share", "REAL"),
            ("dividend_payout_ratio_pct", "REAL"),
            ("total_debt_cr", "REAL"),
            ("cash_from_operations_cr", "REAL"),
            ("revenue_cagr_5yr", "REAL"),
            ("pat_cagr_5yr", "REAL"),
            ("eps_cagr_5yr", "REAL"),
            ("composite_quality_score", "REAL"),
            ("high_leverage_flag", "INTEGER"),
            ("icr_label", "TEXT"),
            ("icr_warning_flag", "INTEGER"),
        ]
        for column_name, column_type in additions:
            if column_name not in existing:
                conn.execute(f"ALTER TABLE financial_ratios ADD COLUMN {column_name} {column_type};")

    def _load_company_universe(self, conn: sqlite3.Connection) -> pd.DataFrame:
        query = """
            WITH year_keys AS (
                SELECT company_id, financial_year FROM profitandloss
                UNION
                SELECT company_id, financial_year FROM balancesheet
                UNION
                SELECT company_id, financial_year FROM cashflow
            )
            SELECT DISTINCT y.company_id, y.financial_year
            FROM year_keys y
            ORDER BY y.company_id, y.financial_year;
        """.strip()
        return pd.read_sql_query(query, conn)

    def _load_sector_map(self, conn: sqlite3.Connection) -> dict[int, str | None]:
        frame = pd.read_sql_query(
            "SELECT company_id, sector_name FROM sectors ORDER BY company_id;",
            conn,
        )
        return {int(row.company_id): row.sector_name for row in frame.itertuples(index=False)}

    def _load_workbook_lookup(self) -> dict[tuple[str | int, int], dict[str, float | None]]:
        if not self.workbook_path.exists():
            return {}
        try:
            workbook = pd.read_excel(self.workbook_path)
        except Exception:
            return {}
        if workbook.empty:
            return {}
        normalized = {str(column).strip().lower(): column for column in workbook.columns}
        key_column = normalized.get("company_id") or normalized.get("ticker") or normalized.get("company_name")
        year_column = normalized.get("year") or normalized.get("financial_year")
        if key_column is None or year_column is None:
            return {}
        lookup: dict[tuple[str, int], dict[str, float | None]] = {}
        for row in workbook.to_dict(orient="records"):
            key = row.get(key_column)
            year = row.get(year_column)
            if key is None or year is None:
                continue
            try:
                year_int = int(year)
            except Exception:
                continue
            lookup[(str(key).strip(), year_int)] = {
                "roe_percentage": _legacy_metric(row.get(normalized.get("roe_percentage", "roe_percentage"))),
                "roce_percentage": _legacy_metric(row.get(normalized.get("roce_percentage", "roce_percentage"))),
                "opm_percentage": _legacy_metric(row.get(normalized.get("opm_percentage", "opm_percentage"))),
            }
        return lookup

    def _legacy_ratio_lookup(self, conn: sqlite3.Connection) -> dict[tuple[int, int], dict[str, float | None]]:
        legacy = pd.read_sql_query(
            """
            SELECT company_id, financial_year, operating_margin, return_on_equity, return_on_assets
            FROM financial_ratios
            ORDER BY company_id, financial_year;
            """.strip(),
            conn,
        )
        return {
            (int(row.company_id), int(row.financial_year)): {
                "operating_margin": _legacy_metric(row.operating_margin),
                "return_on_equity": _legacy_metric(row.return_on_equity),
                "return_on_assets": _legacy_metric(row.return_on_assets),
            }
            for row in legacy.itertuples(index=False)
        }

    def _database_benchmark_lookup(self, conn: sqlite3.Connection) -> dict[tuple[int, int], dict[str, float | None]]:
        benchmark = pd.read_sql_query(
            """
            SELECT
                p.company_id,
                p.financial_year,
                p.operating_profit,
                p.net_income,
                b.total_equity,
                b.debt
            FROM profitandloss p
            LEFT JOIN balancesheet b
              ON b.company_id = p.company_id
             AND b.financial_year = p.financial_year
            ORDER BY p.company_id, p.financial_year;
            """.strip(),
            conn,
        )
        lookup: dict[tuple[int, int], dict[str, float | None]] = {}
        for row in benchmark.itertuples(index=False):
            total_equity = _to_float(row.total_equity)
            debt = _to_float(row.debt)
            operating_profit = _to_float(row.operating_profit)
            net_income = _to_float(row.net_income)
            roe = None
            roce = None
            if total_equity not in {None, 0}:
                roe = (net_income or 0.0) / total_equity * 100.0
                capital_employed = total_equity + (debt or 0.0)
                if capital_employed not in {None, 0}:
                    roce = (operating_profit or 0.0) / capital_employed * 100.0
            lookup[(int(row.company_id), int(row.financial_year))] = {
                "roe_percentage": roe,
                "roce_percentage": roce,
            }
        return lookup

    def _load_source_frames(self, conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        pnl = pd.read_sql_query(
            """
            SELECT company_id, financial_year, revenue, operating_profit, net_income, eps, operating_profit_margin
            FROM profitandloss
            ORDER BY company_id, financial_year;
            """.strip(),
            conn,
        )
        bs = pd.read_sql_query(
            """
            SELECT company_id, financial_year, total_assets, total_liabilities, total_equity, current_assets, current_liabilities, debt, cash_and_equivalents
            FROM balancesheet
            ORDER BY company_id, financial_year;
            """.strip(),
            conn,
        )
        cf = pd.read_sql_query(
            """
            SELECT company_id, financial_year, net_cash_from_operations, net_cash_from_investing, net_cash_from_financing, interest_paid, dividend_paid
            FROM cashflow
            ORDER BY company_id, financial_year;
            """.strip(),
            conn,
        )
        sector = pd.read_sql_query(
            "SELECT company_id, sector_name FROM sectors ORDER BY company_id;",
            conn,
        )
        return pnl, bs, cf, sector

    @staticmethod
    def _shares_outstanding(net_income: float | None, eps: float | None) -> float | None:
        if net_income is None or eps in {None, 0}:
            return None
        shares = abs(net_income / eps)
        return shares if shares > 0 else None

    @staticmethod
    def _book_value_per_share(total_equity: float | None, net_income: float | None, eps: float | None) -> float | None:
        shares = Sprint2RatioEngine._shares_outstanding(net_income, eps)
        if total_equity is None or shares in {None, 0}:
            return None
        return total_equity / shares

    @staticmethod
    def _dividend_payout_ratio(dividend_paid: float | None, net_income: float | None) -> float | None:
        if net_income in {None, 0}:
            return None
        if dividend_paid is None:
            return None
        return abs(dividend_paid) / abs(net_income) * 100.0

    @staticmethod
    def _current_ratio(current_assets: float | None, current_liabilities: float | None) -> float | None:
        if current_assets is None or current_liabilities in {None, 0}:
            return None
        return current_assets / current_liabilities

    @staticmethod
    def _gross_margin_proxy(operating_profit_margin_value: float | None) -> float | None:
        return operating_profit_margin_value

    @staticmethod
    def _composite_quality_score(row: dict[str, Any]) -> float | None:
        contributions: list[float] = []
        nppm = row.get("net_profit_margin_pct")
        opm = row.get("operating_profit_margin_pct")
        roe = row.get("return_on_equity_pct")
        roce = row.get("return_on_capital_employed_pct")
        roa = row.get("return_on_assets_pct")
        icr = row.get("interest_coverage")
        dte = row.get("debt_to_equity")
        fcf = row.get("free_cash_flow_cr")
        cfo_quality = row.get("cfo_quality_score")

        if nppm is not None:
            contributions.append(clamp((nppm + 20.0) * 2.0, 0.0, 100.0))
        if opm is not None:
            contributions.append(clamp((opm + 20.0) * 2.0, 0.0, 100.0))
        if roe is not None:
            contributions.append(clamp(roe * 2.0 + 50.0, 0.0, 100.0))
        if roce is not None:
            contributions.append(clamp(roce * 2.0 + 50.0, 0.0, 100.0))
        if roa is not None:
            contributions.append(clamp(roa * 3.0 + 50.0, 0.0, 100.0))
        if icr is not None:
            contributions.append(clamp(icr * 10.0, 0.0, 100.0))
        if dte is not None:
            contributions.append(clamp(100.0 - min(dte * 10.0, 100.0), 0.0, 100.0))
        if fcf is not None:
            contributions.append(100.0 if fcf > 0 else 25.0)
        if cfo_quality is not None:
            contributions.append(clamp((cfo_quality + 2.0) * 25.0, 0.0, 100.0))

        if not contributions:
            return None
        return round(sum(contributions) / len(contributions), 6)

    def _log_variance(
        self,
        *,
        category: str,
        company_id: int,
        financial_year: int,
        metric: str,
        computed_value: float | None,
        source_value: float | None,
        detail: str,
    ) -> None:
        from analytics.common import append_edge_case_log

        append_edge_case_log(
            self.output_dir / "ratio_edge_cases.log",
            category=category,
            company_id=company_id,
            financial_year=financial_year,
            metric=metric,
            computed_value=computed_value,
            source_value=source_value,
            detail=detail,
        )

    def _build_ratio_rows(self, conn: sqlite3.Connection) -> tuple[pd.DataFrame, pd.DataFrame]:
        pnl, bs, cf, sector = self._load_source_frames(conn)
        universe = self._load_company_universe(conn)
        if universe.empty:
            return pd.DataFrame(), pd.DataFrame()

        benchmark_lookup = self._database_benchmark_lookup(conn)
        workbook_lookup = self._load_workbook_lookup()
        company_identity = pd.read_sql_query("SELECT id, ticker, company_name FROM companies ORDER BY id;", conn)
        identity_lookup = {
            int(row.id): [str(row.id), str(row.ticker), str(row.company_name)]
            for row in company_identity.itertuples(index=False)
        }
        sector_lookup = {int(row.company_id): row.sector_name for row in sector.itertuples(index=False)}
        pnl_map = {(int(row.company_id), int(row.financial_year)): row._asdict() for row in pnl.itertuples(index=False)}
        bs_map = {(int(row.company_id), int(row.financial_year)): row._asdict() for row in bs.itertuples(index=False)}
        cf_map = {(int(row.company_id), int(row.financial_year)): row._asdict() for row in cf.itertuples(index=False)}

        revenue_history: dict[int, dict[int, float | None]] = {}
        pat_history: dict[int, dict[int, float | None]] = {}
        eps_history: dict[int, dict[int, float | None]] = {}
        cfo_history: dict[int, dict[int, float | None]] = {}
        for row in pnl.itertuples(index=False):
            company_id = int(row.company_id)
            revenue_history.setdefault(company_id, {})[int(row.financial_year)] = _to_float(row.revenue)
            pat_history.setdefault(company_id, {})[int(row.financial_year)] = _to_float(row.net_income)
            eps_history.setdefault(company_id, {})[int(row.financial_year)] = _to_float(row.eps)
        for row in cf.itertuples(index=False):
            company_id = int(row.company_id)
            cfo_history.setdefault(company_id, {})[int(row.financial_year)] = _to_float(row.net_cash_from_operations)

        ratio_rows: list[dict[str, Any]] = []
        peer_rows: list[dict[str, Any]] = []
        cashflow_export_records = load_cashflow_records(conn).to_dict(orient="records")

        for item in universe.itertuples(index=False):
            company_id = int(item.company_id)
            year = int(item.financial_year)
            pnl_row = pnl_map.get((company_id, year), {})
            bs_row = bs_map.get((company_id, year), {})
            cf_row = cf_map.get((company_id, year), {})
            broad_sector = sector_lookup.get(company_id)

            revenue = _to_float(pnl_row.get("revenue"))
            operating_profit = _to_float(pnl_row.get("operating_profit"))
            net_income = _to_float(pnl_row.get("net_income"))
            eps = _to_float(pnl_row.get("eps"))
            opm_source = _to_float(pnl_row.get("operating_profit_margin"))

            total_assets = _to_float(bs_row.get("total_assets"))
            total_liabilities = _to_float(bs_row.get("total_liabilities"))
            total_equity = _to_float(bs_row.get("total_equity"))
            current_assets = _to_float(bs_row.get("current_assets"))
            current_liabilities = _to_float(bs_row.get("current_liabilities"))
            debt = _to_float(bs_row.get("debt"))
            cash_and_equivalents = _to_float(bs_row.get("cash_and_equivalents"))

            cfo = _to_float(cf_row.get("net_cash_from_operations"))
            cfi = _to_float(cf_row.get("net_cash_from_investing"))
            cff = _to_float(cf_row.get("net_cash_from_financing"))
            interest_paid = abs(_to_float(cf_row.get("interest_paid")) or 0.0)
            dividend_paid = _to_float(cf_row.get("dividend_paid"))

            net_profit_margin_pct = net_profit_margin(net_income, revenue).value
            opm = operating_profit_margin(
                operating_profit,
                revenue,
                source_percentage=opm_source,
                edge_log_path=self.output_dir / "ratio_edge_cases.log",
                company_id=company_id,
                financial_year=year,
            ).value
            roe_pct = return_on_equity(net_income, total_equity, 0.0).value
            roce_pct = return_on_capital_employed(operating_profit, total_equity, 0.0, debt, broad_sector=broad_sector).value
            roa_pct = return_on_assets(net_income, total_assets).value
            de_result = debt_to_equity(debt, total_equity, 0.0, broad_sector=broad_sector)
            icr_result = interest_coverage_ratio(operating_profit, 0.0, interest_paid)
            asset_turnover_value = asset_turnover(revenue, total_assets).value
            fcf = free_cash_flow(cfo, cfi).value
            capex = abs(cfi) if cfi is not None else None
            bvs = self._book_value_per_share(total_equity, net_income, eps)
            dpr = self._dividend_payout_ratio(dividend_paid, net_income)
            ordered_years = sorted(pat_history.get(company_id, {}).keys())
            cfo_quality = cfo_quality_score(
                [cfo_history.get(company_id, {}).get(year_key) for year_key in ordered_years],
                [pat_history.get(company_id, {}).get(year_key) for year_key in ordered_years],
            )
            capex_intensity_value = capex_intensity(cfi, revenue)
            fcf_conversion = fcf_conversion_rate(fcf, operating_profit).value
            cash_from_operations_cr = cfo
            total_debt = debt
            net_debt_value = net_debt(debt, cash_and_equivalents).value
            cagr_results = compute_metric_cagrs(
                {
                    "revenue": revenue_history.get(company_id, {}),
                    "pat": pat_history.get(company_id, {}),
                    "eps": eps_history.get(company_id, {}),
                },
                end_year=year,
                windows=(5,),
            )

            revenue_cagr_5yr = cagr_results.get("revenue_cagr_5yr", MetricOutcome(None)).value
            pat_cagr_5yr = cagr_results.get("pat_cagr_5yr", MetricOutcome(None)).value
            eps_cagr_5yr = cagr_results.get("eps_cagr_5yr", MetricOutcome(None)).value

            workbook_row = None
            for candidate in identity_lookup.get(company_id, [str(company_id)]):
                workbook_row = workbook_lookup.get((candidate, year))
                if workbook_row is not None:
                    break
            benchmark_row = benchmark_lookup.get((company_id, year), {})
            if workbook_row:
                for metric_name, computed_value, source_value in (
                    ("return_on_equity", roe_pct, workbook_row.get("roe_percentage")),
                    ("return_on_capital_employed", roce_pct, workbook_row.get("roce_percentage")),
                    ("operating_profit_margin", opm, workbook_row.get("opm_percentage")),
                ):
                    if computed_value is not None and source_value is not None and abs(computed_value - source_value) > 5.0:
                        self._log_variance(
                            category="formula discrepancy",
                            company_id=company_id,
                            financial_year=year,
                            metric=metric_name,
                            computed_value=round(computed_value, 6),
                            source_value=round(source_value, 6),
                            detail="legacy workbook variance above 5 percentage points",
                        )
            else:
                for metric_name, computed_value, source_value in (
                    ("return_on_equity", roe_pct, benchmark_row.get("roe_percentage")),
                    ("return_on_capital_employed", roce_pct, benchmark_row.get("roce_percentage")),
                ):
                    if computed_value is not None and source_value is not None and abs(computed_value - source_value) > 5.0:
                        self._log_variance(
                            category="formula discrepancy",
                            company_id=company_id,
                            financial_year=year,
                            metric=metric_name,
                            computed_value=round(computed_value, 6),
                            source_value=round(source_value, 6),
                            detail="database benchmark variance above 5 percentage points",
                        )

            if de_result.high_leverage_flag:
                self._log_variance(
                    category="formula discrepancy",
                    company_id=company_id,
                    financial_year=year,
                    metric="debt_to_equity",
                    computed_value=round(de_result.value or 0.0, 6),
                    source_value=None,
                    detail="high leverage exceeds threshold for non-financial sector",
                )

            row = {
                "company_id": company_id,
                "financial_year": year,
                "gross_margin": self._gross_margin_proxy(opm),
                "operating_margin": opm,
                "net_margin": net_profit_margin_pct,
                "debt_to_equity": de_result.value,
                "current_ratio": self._current_ratio(current_assets, current_liabilities),
                "interest_coverage_ratio": icr_result.value,
                "return_on_equity": roe_pct,
                "return_on_assets": roa_pct,
                "peer_group_code": f"PG-{company_id:03d}",
                "peer_group_name": f"Peer Group {company_id:03d}",
                "source_ref": "sprint2",
                "net_profit_margin_pct": net_profit_margin_pct,
                "operating_profit_margin_pct": opm,
                "return_on_equity_pct": roe_pct,
                "return_on_capital_employed_pct": roce_pct,
                "return_on_assets_pct": roa_pct,
                "interest_coverage": icr_result.value,
                "asset_turnover": asset_turnover_value,
                "free_cash_flow_cr": fcf,
                "capex_cr": capex,
                "earnings_per_share": eps,
                "book_value_per_share": bvs,
                "dividend_payout_ratio_pct": dpr,
                "total_debt_cr": total_debt,
                "cash_from_operations_cr": cash_from_operations_cr,
                "revenue_cagr_5yr": revenue_cagr_5yr,
                "pat_cagr_5yr": pat_cagr_5yr,
                "eps_cagr_5yr": eps_cagr_5yr,
                "composite_quality_score": self._composite_quality_score(
                    {
                        "net_profit_margin_pct": net_profit_margin_pct,
                        "operating_profit_margin_pct": opm,
                        "return_on_equity_pct": roe_pct,
                        "return_on_capital_employed_pct": roce_pct,
                        "return_on_assets_pct": roa_pct,
                        "interest_coverage": icr_result.value,
                        "debt_to_equity": de_result.value,
                        "free_cash_flow_cr": fcf,
                        "cfo_quality_score": cfo_quality.value,
                    }
                ),
                "high_leverage_flag": 1 if de_result.high_leverage_flag else 0,
                "icr_label": icr_result.label,
                "icr_warning_flag": 1 if icr_result.icr_warning_flag else 0,
            }

            ratio_rows.append(row)
            peer_rows.append(
                {
                    "company_id": company_id,
                    "financial_year": year,
                    "peer_group_code": f"PG-{company_id:03d}",
                    "peer_group_name": f"Peer Group {company_id:03d}",
                    "source_ref": "sprint2",
                }
            )
        ratio_frame = pd.DataFrame(ratio_rows)
        peer_frame = pd.DataFrame(peer_rows)
        build_capital_allocation_frame(cashflow_export_records, self.output_dir / "capital_allocation.csv")
        return ratio_frame, peer_frame

    def refresh(self) -> dict[str, int]:
        with self._connect() as conn:
            self.ensure_schema(conn)
            ratios, peers = self._build_ratio_rows(conn)
            conn.execute("DELETE FROM financial_ratios;")
            conn.execute("DELETE FROM peer_groups;")
            if not ratios.empty:
                self._insert_frame(conn, "financial_ratios", ratios)
            if not peers.empty:
                self._insert_frame(conn, "peer_groups", peers)
            conn.commit()
            return {
                "financial_ratios": int(conn.execute("SELECT COUNT(*) FROM financial_ratios;").fetchone()[0]),
                "peer_groups": int(conn.execute("SELECT COUNT(*) FROM peer_groups;").fetchone()[0]),
            }
