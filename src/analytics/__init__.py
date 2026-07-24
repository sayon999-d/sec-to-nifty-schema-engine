from .cagr import calculate_cagr, compute_cagr_windows
from .clustering import build_cluster_outputs
from .cashflow_kpis import (
    build_capital_allocation_frame,
    capex_intensity,
    classify_capital_allocation,
    cfo_quality_score,
    fcf_conversion_rate,
    free_cash_flow,
)
from .peer import build_peer_percentiles, generate_peer_reports
from .ratios import (
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
