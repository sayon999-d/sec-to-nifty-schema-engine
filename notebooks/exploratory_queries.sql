SELECT 'companies' AS table_name, COUNT(*) AS row_count
FROM companies;

SELECT
    company_id,
    COUNT(DISTINCT financial_year) AS years_covered,
    MIN(financial_year) AS first_year,
    MAX(financial_year) AS last_year
FROM profitandloss
GROUP BY company_id
ORDER BY years_covered DESC, company_id
LIMIT 50;

SELECT
    company_id,
    financial_year,
    total_assets,
    total_liabilities,
    ROUND(ABS(total_assets - total_liabilities) / NULLIF(ABS(total_assets), 0) * 100.0, 4) AS balance_gap_pct
FROM balancesheet
WHERE ABS(total_assets - total_liabilities) / NULLIF(ABS(total_assets), 0) > 0.01
ORDER BY balance_gap_pct DESC, company_id, financial_year;

SELECT
    company_id,
    financial_year,
    operating_profit_margin,
    ROUND((operating_profit / NULLIF(revenue, 0)) * 100.0, 4) AS derived_opm
FROM profitandloss
WHERE revenue IS NOT NULL AND revenue > 0
ORDER BY ABS(COALESCE(operating_profit_margin, 0) - COALESCE(ROUND((operating_profit / NULLIF(revenue, 0)) * 100.0, 4), 0)) DESC,
         company_id,
         financial_year;

SELECT
    trade_date,
    open_price,
    high_price,
    low_price,
    close_price,
    volume,
    turnover
FROM stock_prices
ORDER BY trade_date DESC
LIMIT 100;

SELECT
    company_id,
    financial_year,
    net_cash_flow
FROM cashflow
WHERE net_cash_flow IS NOT NULL
ORDER BY net_cash_flow ASC, company_id, financial_year
LIMIT 100;

SELECT
    sector_name,
    COUNT(*) AS company_count
FROM sectors
GROUP BY sector_name
ORDER BY company_count DESC, sector_name;

SELECT
    company_id,
    financial_year,
    gross_margin,
    operating_margin,
    net_margin,
    debt_to_equity,
    current_ratio,
    interest_coverage_ratio
FROM financial_ratios
WHERE interest_coverage_ratio IS NOT NULL
   OR current_ratio IS NOT NULL
   OR debt_to_equity IS NOT NULL
ORDER BY company_id, financial_year;

SELECT
    document_type,
    COUNT(*) AS document_count
FROM documents
GROUP BY document_type
ORDER BY document_count DESC, document_type;

SELECT
    p.company_id,
    p.financial_year,
    p.revenue,
    b.total_assets,
    c.net_cash_flow,
    r.operating_margin,
    r.current_ratio
FROM profitandloss AS p
LEFT JOIN balancesheet AS b
    ON p.company_id = b.company_id AND p.financial_year = b.financial_year
LEFT JOIN cashflow AS c
    ON p.company_id = c.company_id AND p.financial_year = c.financial_year
LEFT JOIN financial_ratios AS r
    ON p.company_id = r.company_id AND p.financial_year = r.financial_year
WHERE p.revenue IS NOT NULL
ORDER BY p.revenue DESC, p.company_id, p.financial_year
LIMIT 200;
