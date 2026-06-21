PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cik TEXT NOT NULL UNIQUE,
    adsh TEXT NOT NULL UNIQUE,
    ticker TEXT NOT NULL UNIQUE,
    company_name TEXT NOT NULL,
    sic TEXT,
    countryba TEXT,
    stateba TEXT,
    cityba TEXT,
    form TEXT,
    period TEXT,
    fye TEXT,
    filed TEXT,
    accepted TEXT,
    source_file TEXT,
    listing_status TEXT NOT NULL DEFAULT 'listed',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sectors (
    company_id INTEGER NOT NULL,
    sector_name TEXT NOT NULL,
    industry_name TEXT,
    sub_industry_name TEXT,
    exchange_code TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, sector_name),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS profitandloss (
    company_id INTEGER NOT NULL,
    financial_year INTEGER NOT NULL,
    source_adsh TEXT,
    source_tag TEXT,
    statement_type TEXT NOT NULL DEFAULT 'IS',
    line_no INTEGER,
    line_label TEXT,
    source_date TEXT,
    source_value REAL,
    revenue REAL,
    cost_of_goods_sold REAL,
    operating_expenses REAL,
    operating_profit REAL,
    net_income REAL,
    eps REAL,
    operating_profit_margin REAL,
    tax_rate REAL,
    source_sheet TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, financial_year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS balancesheet (
    company_id INTEGER NOT NULL,
    financial_year INTEGER NOT NULL,
    source_adsh TEXT,
    source_tag TEXT,
    statement_type TEXT NOT NULL DEFAULT 'BS',
    line_no INTEGER,
    line_label TEXT,
    source_date TEXT,
    source_value REAL,
    total_assets REAL,
    total_liabilities REAL,
    total_equity REAL,
    current_assets REAL,
    current_liabilities REAL,
    debt REAL,
    cash_and_equivalents REAL,
    source_sheet TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, financial_year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cashflow (
    company_id INTEGER NOT NULL,
    financial_year INTEGER NOT NULL,
    source_adsh TEXT,
    source_tag TEXT,
    statement_type TEXT NOT NULL DEFAULT 'CF',
    line_no INTEGER,
    line_label TEXT,
    source_date TEXT,
    source_value REAL,
    net_cash_from_operations REAL,
    net_cash_from_investing REAL,
    net_cash_from_financing REAL,
    net_cash_flow REAL,
    interest_paid REAL,
    dividend_paid REAL,
    source_sheet TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, financial_year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS analysis (
    company_id INTEGER NOT NULL,
    financial_year INTEGER NOT NULL,
    source_name TEXT NOT NULL,
    analyst_name TEXT,
    recommendation TEXT,
    target_price REAL,
    risk_rating TEXT,
    source_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, financial_year, source_name),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS documents (
    company_id INTEGER NOT NULL,
    document_type TEXT NOT NULL,
    document_date TEXT NOT NULL,
    document_title TEXT,
    document_url TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, document_type, document_date),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS prosandcons (
    company_id INTEGER NOT NULL,
    financial_year INTEGER NOT NULL,
    pros TEXT,
    cons TEXT,
    summary_score REAL,
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, financial_year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS stock_prices (
    company_id INTEGER NOT NULL,
    trade_date TEXT NOT NULL,
    open_price REAL,
    high_price REAL,
    low_price REAL,
    close_price REAL,
    volume INTEGER,
    turnover REAL,
    adjusted_close REAL,
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, trade_date),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS financial_ratios (
    company_id INTEGER NOT NULL,
    financial_year INTEGER NOT NULL,
    gross_margin REAL,
    operating_margin REAL,
    net_margin REAL,
    debt_to_equity REAL,
    current_ratio REAL,
    interest_coverage_ratio REAL,
    return_on_equity REAL,
    return_on_assets REAL,
    peer_group_code TEXT,
    peer_group_name TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, financial_year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS peer_groups (
    company_id INTEGER NOT NULL,
    financial_year INTEGER NOT NULL,
    peer_group_code TEXT,
    peer_group_name TEXT,
    source_ref TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (company_id, financial_year),
    FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sectors_company ON sectors(company_id);
CREATE INDEX IF NOT EXISTS idx_profitandloss_company_year ON profitandloss(company_id, financial_year);
CREATE INDEX IF NOT EXISTS idx_balancesheet_company_year ON balancesheet(company_id, financial_year);
CREATE INDEX IF NOT EXISTS idx_cashflow_company_year ON cashflow(company_id, financial_year);
CREATE INDEX IF NOT EXISTS idx_documents_company_date ON documents(company_id, document_date);
CREATE INDEX IF NOT EXISTS idx_stock_prices_company_date ON stock_prices(company_id, trade_date);
CREATE INDEX IF NOT EXISTS idx_financial_ratios_company_year ON financial_ratios(company_id, financial_year);
CREATE INDEX IF NOT EXISTS idx_peer_groups_company_year ON peer_groups(company_id, financial_year);
