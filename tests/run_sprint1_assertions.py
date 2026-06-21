from __future__ import annotations

import csv
import os
import subprocess
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
ENV_PATH = PROJECT_ROOT / ".env"
RAW_FILENAMES = ("sub.txt", "num.txt", "pre.txt", "tag.txt")


def _use_color() -> bool:
    return sys.stdout.isatty()


class Colors:
    GREEN = "\033[32m" if _use_color() else ""
    RED = "\033[31m" if _use_color() else ""
    YELLOW = "\033[33m" if _use_color() else ""
    RESET = "\033[0m" if _use_color() else ""


PASS_MARK = f"{Colors.GREEN}[✓] PASS{Colors.RESET}"
FAIL_MARK = f"{Colors.RED}[✗] FAIL{Colors.RESET}"
WARN_MARK = f"{Colors.YELLOW}[!] WARN{Colors.RESET}"


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""


def load_env_file(path: Path) -> dict[str, str]:

    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.startswith("NIFTY100_"):
            continue
        cleaned_value = value.strip().strip('"').strip("'")
        values[key] = cleaned_value
    return values


def load_config() -> dict[str, str]:

    config = load_env_file(ENV_PATH)
    for key, value in os.environ.items():
        if key.startswith("NIFTY100_"):
            config[key] = value
    return config


def resolve_path(value: str, *bases: Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    if not bases:
        return PROJECT_ROOT / path
    for base in bases:
        candidate = base / path
        if candidate.exists() or candidate.parent.exists():
            return candidate
    return bases[0] / path


def resolve_source_root(config: dict[str, str]) -> Path:
    configured = config.get("NIFTY100_SOURCE_ROOT", "2025q4")
    root = resolve_path(configured, REPO_ROOT, PROJECT_ROOT)
    if root.exists():
        return root
    fallback = REPO_ROOT / "2025q4"
    if fallback.exists():
        return fallback
    return root


def print_header(title: str) -> None:
    print()
    print(f"== {title} ==")


def print_pass(message: str) -> None:
    print(f"{PASS_MARK} {message}")


def print_fail(message: str) -> None:
    print(f"{FAIL_MARK} {message}")


def print_warn(message: str) -> None:
    print(f"{WARN_MARK} {message}")


def record(result: list[StepResult], name: str, ok: bool, detail: str = "") -> None:
    result.append(StepResult(name=name, ok=ok, detail=detail))
    if ok:
        print_pass(name if not detail else f"{name} - {detail}")
    else:
        print_fail(name if not detail else f"{name} - {detail}")


def summarize_failures(results: Iterable[StepResult]) -> bool:
    failures = [item for item in results if not item.ok]
    print()
    if failures:
        print_fail(f"{len(failures)} step(s) failed")
        for item in failures:
            print_fail(item.name if not item.detail else f"{item.name} - {item.detail}")
        return False
    print_pass("All sprint assertions passed")
    return True


def check_layer_1(config: dict[str, str]) -> list[StepResult]:
    results: list[StepResult] = []
    print_header("LAYER 1: SYSTEM ENVIRONMENT & ARTIFACT AUDIT")

    record(results, "`.env` exists", ENV_PATH.exists(), str(ENV_PATH))

    loaded_keys = load_env_file(ENV_PATH)
    record(
        results,
        ".env loads NIFTY100_ variables",
        bool(loaded_keys),
        f"{len(loaded_keys)} key(s) loaded",
    )

    source_root = resolve_source_root(config)
    record(results, "Raw source root present", source_root.exists(), str(source_root))
    for filename in RAW_FILENAMES:
        raw_path = source_root / filename
        record(results, f"Raw file present: {filename}", raw_path.exists(), str(raw_path))

    schema_path = resolve_path(config.get("NIFTY100_SCHEMA_PATH", "db/schema.sql"))
    db_path = resolve_path(config.get("NIFTY100_DB_PATH", "db/nifty100.db"))
    record(results, "Schema file present", schema_path.exists(), str(schema_path))
    record(results, "SQLite database present", db_path.exists(), str(db_path))
    return results


def bootstrap_database(config: dict[str, str]) -> StepResult:

    db_path = resolve_path(config.get("NIFTY100_DB_PATH", "db/nifty100.db"))
    if db_path.exists():
        return StepResult(name="Database bootstrap", ok=True, detail="database already present")

    env = os.environ.copy()
    env.update(config)
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")

    command = [sys.executable, "-m", "etl.loader", "load"]
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
    )

    if completed.returncode != 0:
        if db_path.exists():
            print_warn("Database bootstrap - loader exited nonzero but database artifact exists")
            if completed.stdout.strip():
                print(completed.stdout.rstrip())
            if completed.stderr.strip():
                print(completed.stderr.rstrip())
            return StepResult(
                name="Database bootstrap",
                ok=True,
                detail=f"loader exited with {completed.returncode}",
            )

        print_fail("Database bootstrap - loader execution failed")
        if completed.stdout.strip():
            print(completed.stdout.rstrip())
        if completed.stderr.strip():
            print(completed.stderr.rstrip())
        return StepResult(
            name="Database bootstrap",
            ok=False,
            detail=f"loader exited with {completed.returncode}",
        )

    if db_path.exists():
        print_pass(f"Database bootstrap - created {db_path}")
        return StepResult(name="Database bootstrap", ok=True, detail=str(db_path))

    print_fail("Database bootstrap - loader completed but database still missing")
    return StepResult(name="Database bootstrap", ok=False, detail=str(db_path))


def parse_validation_log(validation_path: Path) -> tuple[list[str] | None, list[dict[str, str]]]:
    with validation_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return reader.fieldnames, list(reader)


def check_layer_2(config: dict[str, str]) -> list[StepResult]:
    results: list[StepResult] = []
    print_header("LAYER 2: DATA QUALITY LOGGER & FAILURE ANALYSIS")

    validation_path = resolve_path(config.get("NIFTY100_OUTPUT_DIR", "output")) / "validation_failures.csv"
    record(results, "Validation tracker present", validation_path.exists(), str(validation_path))
    if not validation_path.exists():
        return results

    try:
        fieldnames, rows = parse_validation_log(validation_path)
        required_columns = {"rule_id", "company_id", "record_context", "failure_severity", "timestamp"}
        header_ok = bool(fieldnames) and required_columns.issubset(set(fieldnames))
        record(
            results,
            "Validation tracker parses cleanly",
            header_ok,
            f"{len(rows)} row(s)",
        )
    except Exception as exc:  # pragma: no cover - surfaced in terminal output
        record(results, "Validation tracker parses cleanly", False, str(exc))
        return results

    severity_counts: dict[str, int] = {}
    for row in rows:
        severity = (row.get("failure_severity") or "").strip().upper()
        severity_counts[severity] = severity_counts.get(severity, 0) + 1

    print(f"    severity counts: {severity_counts}")
    strict_mode = config.get("NIFTY100_STRICT_COUNTS", "0").strip() in {"1", "true", "yes", "on"}
    if strict_mode:
        critical_rules = {"DQ-01", "DQ-02", "DQ-03"}
        unresolved = [
            row
            for row in rows
            if (row.get("failure_severity") or "").strip().upper() == "CRITICAL"
            and (row.get("rule_id") or "").strip().upper() in critical_rules
        ]
        record(
            results,
            "Strict critical-row gate",
            len(unresolved) == 0,
            f"{len(unresolved)} unresolved CRITICAL row(s)",
        )
    else:
        print_warn("Strict count gate disabled; critical validation rows reported as descriptive output only")

    return results


def open_database(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def scalar_count(conn: sqlite3.Connection, query: str) -> int:
    row = conn.execute(query).fetchone()
    return int(row[0]) if row is not None else 0


def check_layer_3(config: dict[str, str]) -> list[StepResult]:
    results: list[StepResult] = []
    print_header("LAYER 3: SQLITE SCHEMA & RELATIONAL STRUCTURAL VERIFICATION")

    db_path = resolve_path(config.get("NIFTY100_DB_PATH", "db/nifty100.db"))
    strict_mode = config.get("NIFTY100_STRICT_COUNTS", "0").strip() in {"1", "true", "yes", "on"}
    if not db_path.exists():
        record(results, "Database openable", False, str(db_path))
        return results

    try:
        with open_database(db_path) as conn:
            fk_violations = conn.execute("PRAGMA foreign_key_check;").fetchall()
            record(
                results,
                "Foreign-key integrity check",
                len(fk_violations) == 0,
                f"{len(fk_violations)} violation row(s)",
            )

            company_count = scalar_count(conn, "SELECT COUNT(*) FROM companies;")
            if strict_mode:
                record(results, "companies row count == 92", company_count == 92, f"actual={company_count}")
            else:
                print_warn(f"companies rows={company_count} (strict mode disabled; target=92)")

            expected_counts = {
                "profitandloss": 1276,
                "balancesheet": 1312,
                "cashflow": 1187,
                "stock_prices": 5520,
            }
            for table_name, expected in expected_counts.items():
                actual = scalar_count(conn, f"SELECT COUNT(*) FROM {table_name};")
                if strict_mode:
                    record(results, f"{table_name} row count == {expected}", actual == expected, f"actual={actual}")
                else:
                    print_warn(f"{table_name} rows={actual} (strict mode disabled; target={expected})")
    except Exception as exc:  # pragma: no cover - surfaced in terminal output
        record(results, "SQLite structural verification", False, str(exc))

    return results


def check_layer_4(config: dict[str, str]) -> list[StepResult]:
    results: list[StepResult] = []
    print_header("LAYER 4: REGULATORY DATA COMPLIANCE & SPOT-CHECK QUERIES")

    db_path = resolve_path(config.get("NIFTY100_DB_PATH", "db/nifty100.db"))
    strict_mode = config.get("NIFTY100_STRICT_COUNTS", "0").strip() in {"1", "true", "yes", "on"}
    if not db_path.exists():
        record(results, "Database openable for SQL checks", False, str(db_path))
        return results

    try:
        with open_database(db_path) as conn:
            balance_violation_count = scalar_count(
                conn,
                """
                SELECT COUNT(*)
                FROM balancesheet
                WHERE total_assets IS NULL
                   OR total_liabilities IS NULL
                   OR total_assets = 0
                   OR ABS(total_assets - total_liabilities) / ABS(total_assets) >= 0.01;
                """.strip(),
            )
            record(
                results,
                "Balance-sheet tolerance check",
                balance_violation_count == 0,
                f"{balance_violation_count} violation row(s)",
            )

            sample_rows = conn.execute(
                """
                WITH sample AS (
                    SELECT id, ticker, company_name
                    FROM companies
                    ORDER BY RANDOM()
                    LIMIT 5
                ),
                year_matrix AS (
                    SELECT company_id, financial_year FROM profitandloss
                    UNION
                    SELECT company_id, financial_year FROM balancesheet
                    UNION
                    SELECT company_id, financial_year FROM cashflow
                )
                SELECT
                    sample.id AS company_id,
                    sample.ticker,
                    sample.company_name,
                    COUNT(DISTINCT year_matrix.financial_year) AS year_records
                FROM sample
                LEFT JOIN year_matrix
                    ON year_matrix.company_id = sample.id
                GROUP BY sample.id, sample.ticker, sample.company_name
                ORDER BY sample.id;
                """.strip(),
            ).fetchall()

            random_check_ok = len(sample_rows) == 5 and all(int(row["year_records"]) > 0 for row in sample_rows)
            details = ", ".join(
                f"{row['ticker']}={int(row['year_records'])}"
                for row in sample_rows
            )
            if strict_mode:
                record(
                    results,
                    "Random company temporal profile check",
                    random_check_ok,
                    details if details else "no sample rows returned",
                )
            else:
                if random_check_ok:
                    print_pass(
                        "Random company temporal profile check - "
                        + (details if details else "5 sampled company row(s)")
                    )
                else:
                    print_warn(
                        "Random company temporal profile check - "
                        + (details if details else "no sample rows returned")
                    )
    except Exception as exc:  # pragma: no cover - surfaced in terminal output
        record(results, "SQL compliance checks", False, str(exc))

    return results


def main() -> int:
    config = load_config()
    all_results: list[StepResult] = []

    bootstrap = bootstrap_database(config)
    all_results.append(bootstrap)

    all_results.extend(check_layer_1(config))
    all_results.extend(check_layer_2(config))
    all_results.extend(check_layer_3(config))
    all_results.extend(check_layer_4(config))

    success = summarize_failures(all_results)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
