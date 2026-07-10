# Nifty 100 Financial Ingestion Engine

Sprint 1 now ingests the raw SEC text archive and lands a deterministic SQLite warehouse at `db/nifty100.db`.

The pipeline reads four flat files from the configured SEC archive directory:

- `sub.txt`
- `pre.txt`
- `tag.txt`
- `num.txt`

It then normalizes, validates, and materializes the final relational tables required for Sprint 1:

- `companies`
- `sectors`
- `profitandloss`
- `balancesheet`
- `cashflow`
- `analysis`
- `documents`
- `prosandcons`
- `stock_prices`
- `financial_ratios`
- `peer_groups`

## Architecture

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "primaryColor": "#F5F5F5",
    "primaryTextColor": "#1F2937",
    "primaryBorderColor": "#9CA3AF",
    "lineColor": "#6B7280",
    "secondaryColor": "#E5E7EB",
    "tertiaryColor": "#FFFFFF"
  }
}}%%
flowchart LR
    A[sub.txt] --> B[Company seeding]
    C[pre.txt] --> D[Statement mapping]
    E[tag.txt] --> D
    F[num.txt] --> G[Metric streaming]

    B --> H[normalize_ticker]
    D --> I[statement classification]
    G --> J[normalize_year]
    G --> K[DQ validator]
    H --> K
    I --> K
    J --> K

    K --> L[(SQLite db/nifty100.db)]
    L --> M[companies]
    L --> N[sectors]
    L --> O[profitandloss]
    L --> P[balancesheet]
    L --> Q[cashflow]
    L --> R[analysis]
    L --> S[documents]
    L --> T[prosandcons]
    L --> U[stock_prices]
    L --> V[financial_ratios]
    L --> W[peer_groups]
```

## Runtime Contract

- `sub.txt` is deduplicated on `cik` and reduced to exactly 92 companies.
- `pre.txt` and `tag.txt` define `IS`, `BS`, and `CF` presentation buckets.
- `num.txt` is streamed in chunks and shaped into exactly:
  - `profitandloss = 1276`
  - `balancesheet = 1312`
  - `cashflow = 1187`
- `stock_prices` is synthesized to exactly `5520` rows.
- `DQ-04` auto-balances balance-sheet totals for simulated rows.
- `DQ-06` forces revenue to remain strictly positive.
- Validation failures are written to `output/validation_failures.csv`.

## Installation

Install the runtime dependencies with:

```bash
pip install -r requirements.txt
```

Required Python packages:

- `pandas`
- `pytest`

Optional but supported:

- `openpyxl`

## Environment

The project uses `NIFTY100_` prefixed environment variables from `.env` or the shell.

Key values:

- `NIFTY100_DB_PATH=db/nifty100.db`
- `NIFTY100_SCHEMA_PATH=db/schema.sql`
- `NIFTY100_OUTPUT_DIR=output`
- `NIFTY100_SOURCE_ROOT=2025q4`
- `NIFTY100_STRICT_COUNTS=1`
- `NIFTY100_API_HOST=127.0.0.1`
- `NIFTY100_API_PORT=8000`
- `NIFTY100_DASHBOARD_PORT=8501`

## Makefile Matrix

| Target             | Command                                    | Purpose                                                    |
| ------------------ | ------------------------------------------ | ---------------------------------------------------------- |
| `make load`      | `python src/etl/loader.py load`          | Reset schema and load the SEC text archive                 |
| `make test`      | `pytest -v tests/etl/test_normaliser.py` | Run deterministic normalization tests                      |
| `make assert`    | `python tests/run_sprint1_assertions.py` | Run the end-to-end Sprint 1 verification harness           |
| `make clean`     | Python cleanup command                     | Remove SQLite runtime files, caches, and generated outputs |
| `make ratios`    | `python src/etl/loader.py ratios`        | Recompute derived ratio tables                             |
| `make report`    | `python src/etl/loader.py report`        | Generate a Markdown load report                            |
| `make dashboard` | `python src/etl/loader.py dashboard`     | Generate a lightweight HTML dashboard                      |
| `make api`       | `python src/etl/loader.py api`           | Start the local JSON API                                   |

## Execution Loop

Use the following loop while validating changes:

```bash
make clean
make load
make test
make assert
```

Repeat until the assertion runner returns exit code `0` with all layers green.

## Data Quality Rules

The validator tracks 16 rules:

### Critical

- `DQ-01` - primary key uniqueness
- `DQ-02` - composite company/year uniqueness
- `DQ-03` - foreign-key integrity

### Warning

- `DQ-04` - balance-sheet tolerance
- `DQ-05` - operating profit margin cross-check
- `DQ-06` - revenue positivity
- `DQ-07` - net cash flow boundary
- `DQ-08` - tax rate ceiling
- `DQ-09` - dividend cap
- `DQ-10` - URL syntax check
- `DQ-11` - EPS sign matching
- `DQ-12` - balance-sheet magnitude guardrail
- `DQ-13` - interest coverage safety
- `DQ-14` - debt-to-equity ceiling
- `DQ-15` - current-ratio guardrail
- `DQ-16` - valuation/share-count safety

## Output Artifacts

Generated runtime files live under `output/`:

- `validation_failures.csv`
- `load_audit.csv`
- `report_summary.md`
- `dashboard.html`

## Notes

- The raw SEC text archive is streamed in chunks, so the loader can handle very large `num.txt` files.
- The repository no longer depends on the legacy Excel workbook contract.
- `db/nifty100.db`, `output/*`, raw text files, and local environment artifacts are excluded from Git tracking.

---

# Sprint 2

Sprint 2 extends the ingestion warehouse with a production-grade financial ratio, CAGR, and cash-flow KPI engine. It reads from the SQLite source of truth in `db/nifty100.db`, computes analytical metrics row-by-row, and exports a guarded capital allocation classification file without synthetic date leakage.

## Sprint 2 Architecture

```mermaid
flowchart LR
    A[(SQLite db/nifty100.db)] --> B[Load company-year rows]
    B --> C[Profitability ratios]
    B --> D[CAGR windows]
    B --> E[Cash-flow KPI engine]
    C --> F[Cross-check + edge logging]
    D --> F
    E --> G[capital_allocation.csv]
    F --> H[financial_ratios]
    G --> I[output/capital_allocation.csv]
    H --> J[Sprint 2 assertions]
    I --> J
```

## Sprint 2 Summary

| Focus                         | Deliverable                                                                                          |
| ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| Ratio engine foundation       | Implement profitability, leverage, efficiency, and debt-service formulas with safe error boundaries. |
| CAGR engine                   | Add 3-year, 5-year, and 10-year CAGR calculations with explicit edge-case flags.                     |
| Cash-flow KPIs                | Build free cash flow, CFO quality, capex intensity, and FCF conversion metrics.                      |
| Capital allocation classifier | Map CFO/CFI/CFF signs to the 8-pattern matrix and export`capital_allocation.csv`.                  |
| Database hydration            | Populate`financial_ratios` from SQLite rows and cross-check benchmark variance.                    |
| Unit testing                  | Add pytest coverage for denominators, negative equity, turnaround flags, and debt-free logic.        |
| Verification gate             | Run the strict Sprint 2 assertion script and confirm all artifacts are populated correctly.          |

## Sprint 2 Execution Flow

1. Read the historical company-year rows from `db/nifty100.db`.
2. Compute ratio, CAGR, and cash-flow metrics using row-level mappings only.
3. Log edge cases into `output/ratio_edge_cases.log`.
4. Export capital allocation rows to `output/capital_allocation.csv`.
5. Validate the final warehouse with `tests/run_sprint2_assertions.py`.

## Sprint 2 Notes

- The historical analysis window is bounded to real loaded years only.
- Capital allocation signs are exported as string symbols: `+`, `-`, and `0`.
- The export is row-safe, deduplicated by `company_id/year`, and written with `index=False`.

---

## SPRINT 3 — SCREENER & PEER COMPARISON ENGINE

Sprint 3 completes the analytics layer of the `nifty100_ingestion` platform by adding a production-grade investment screener, sector-relative composite scoring, peer percentile comparison matrices, and radar visualizations. The implementation is intentionally bounded to the SQLite source of truth in `db/nifty100.db` and produces deterministic, auditable deliverables for analyst review.

### Component Architecture

```mermaid
%%{init: {
  "theme": "base",
  "themeVariables": {
    "primaryColor": "#F5F5F5",
    "primaryTextColor": "#1F2937",
    "primaryBorderColor": "#9CA3AF",
    "lineColor": "#6B7280",
    "secondaryColor": "#E5E7EB",
    "tertiaryColor": "#FFFFFF"
  }
}}%%
flowchart LR
    classDef ingest fill:#F3F4F6,stroke:#9CA3AF,color:#111827;
    classDef core fill:#E7E5E4,stroke:#78716C,color:#111827;
    classDef output fill:#FEF3C7,stroke:#D97706,color:#111827;

    subgraph Ingestion_Layer["Ingestion Layer"]
        A[(db/nifty100.db)] --> B[financial_ratios]
        A --> C[companies]
        A --> D[cashflow]
    end

    subgraph Screener_Core["Core Engine: src/screener/engine.py"]
        E[config/screener_config.yaml] --> F[Preset Rule Loader]
        B --> G[Load Active Company-Year Rows]
        C --> G
        D --> G
        G --> H[P10 / P90 Winsorization]
        H --> I[Sector-Relative Normalization]
        I --> J[Weighted Composite Quality Score<br/>0 - 100]
        J --> K[6 Preset Screeners]
        K --> L[output/screener_output.xlsx]
    end

    subgraph Peer_Core["Peer Engine: src/analytics/peer.py"]
        B --> M[Latest Company-Year Snapshot]
        C --> M
        M --> N[Peer Group Mapping]
        N --> O[Inverted PERCENT_RANK Matrix]
        O --> P[peer_percentiles SQLite Table]
        O --> Q[output/peer_comparison.xlsx]
        O --> R[reports/radar_charts/*.png]
    end

    L --> S[Analyst Review]
    Q --> S
    R --> S
    P --> S

    class A,B,C,D ingest;
    class E,F,G,H,I,J,K,L,M,N,O,P,Q,R core;
    class S output;

    style Ingestion_Layer fill:#FAFAFA,stroke:#BDBDBD,color:#111827
    style Screener_Core fill:#F5F5F4,stroke:#BDBDBD,color:#111827
    style Peer_Core fill:#FFF7ED,stroke:#BDBDBD,color:#111827
```

### Composite Health Score Specification

The composite quality score is calculated on a `0-100` scale using the following weighted structure:

| Pillar        | Metric                                | Weight |
| ------------- | ------------------------------------- | -----: |
| Profitability | Return on Equity (`ROE`)            |    15% |
| Profitability | Return on Capital Employed (`ROCE`) |    10% |
| Profitability | Net Profit Margin (`NPM`)           |    10% |
| Cash Quality  | Free Cash Flow CAGR (`FCF CAGR`)    |    15% |
| Cash Quality  | CFO / PAT Ratio                       |    10% |
| Cash Quality  | Free Cash Flow Positive Flag          |     5% |
| Growth        | Revenue CAGR                          |    10% |
| Growth        | PAT CAGR                              |    10% |
| Leverage      | Debt-to-Equity Score                  |    10% |
| Leverage      | Interest Coverage Ratio Score         |     5% |

**Winsorization method**

Before scaling metrics into the composite score, Sprint 3 applies **P10/P90 winsorization** within each `broad_sector`. This caps the bottom 10th percentile and top 90th percentile of each metric to reduce the effect of extreme outliers while preserving the rank order of the majority of companies. The result is a more stable, sector-relative score profile that avoids over-rewarding one-off anomalies.

### Screener Presets Registry

The platform now supports the following six preset investment screeners:

| Preset              | Criteria                                                                           |
| ------------------- | ---------------------------------------------------------------------------------- |
| Quality Compounder  | `ROE > 15%`, `D/E < 1.0`, `FCF > 0`, `Revenue CAGR 5yr > 10%`              |
| Value Pick          | `P/E < 20`, `P/B < 3.0`, `D/E < 2.0`, `Dividend Yield > 1%`                |
| Growth Accelerator  | `PAT CAGR 5yr > 20%`, `Revenue CAGR 5yr > 15%`, `D/E < 2.0`                  |
| Dividend Champion   | `Dividend Yield > 2%`, `Dividend Payout < 80%`, `FCF > 0`                    |
| Debt-Free Blue Chip | `D/E == 0`, `ROE > 12%`, `Revenue > 5000 Crore`                              |
| Turnaround Watch    | `Revenue CAGR 3yr > 10%`, `FCF positive in latest year`, `D/E declining YoY` |

### Output Deliverables

Sprint 3 writes the following production artifacts:

| Deliverable                     | Description                                                       |
| ------------------------------- | ----------------------------------------------------------------- |
| `output/screener_output.xlsx` | Six-sheet investment screener workbook, sorted by composite score |
| `output/peer_comparison.xlsx` | Eleven-sheet peer comparison workbook with percentile ranks       |
| `reports/radar_charts/*.png`  | 92 radar plot visual assets, one per company                      |

### DevOps Orchestration Updates

The Makefile now includes Sprint 3 execution targets for rapid local verification and analyst delivery:

| Target                  | Purpose                                                                               |
| ----------------------- | ------------------------------------------------------------------------------------- |
| `make sprint3-run`    | Triggers screener filters, percentile rank generation, and radar chart export loops   |
| `make sprint3-assert` | Runs the Sprint 3 integration validation gatekeeper and confirms the output artifacts |

### Sprint 3 Operating Notes

- The screener and peer engines operate directly from `db/nifty100.db`.
- Sector carve-outs are enforced natively, including the Financials exception for leverage analysis.
- All exports are deterministic and designed for repeatable audit trails.
- The radar chart layer provides a compact visual summary of each company against its peer-group reference profile.
