# ============================================================
# Data Folder Structure — Financial Intelligence Platform
# ============================================================
#
# data/
# ├── companies/
# │   ├── AAPL/
# │   │   ├── financials/        ← CSV & Excel financial statements
# │   │   │   ├── AAPL_FY2024.csv         ← Annual full-year data
# │   │   │   └── AAPL_Q1_2025.xlsx       ← Quarterly Excel (multi-sheet)
# │   │   ├── reports/           ← PDF annual reports, 10-K, 10-Q (Phase 3)
# │   │   └── images/            ← Scanned tables, screenshots (Phase 3)
# │   └── MSFT/
# │       ├── financials/
# │       │   ├── MSFT_FY2024.csv
# │       │   └── MSFT_Q1_2025.xlsx
# │       ├── reports/
# │       └── images/
# ├── templates/
# │   └── financial_statement_template.csv    ← Blank template for analysts
# └── samples/                                ← Ready-to-upload test files
#
# ============================================================
# CSV FORMAT (required columns)
# ============================================================
# metric_key   | value          | fiscal_year | fiscal_period | currency | section
# -------------|----------------|-------------|---------------|----------|----------------
# revenue      | 394328000000   | 2024        | FY            | USD      | Income Statement
# net_income   | 93736000000    | 2024        | FY            | USD      | Income Statement
#
# ============================================================
# METRIC KEYS (canonical names)
# ============================================================
# revenue              · cost_of_goods_sold    · gross_profit
# operating_income     · net_income            · ebitda
# total_assets         · total_liabilities     · total_equity
# current_assets       · current_liabilities
# operating_cf         · capex                 · free_cash_flow
#
# ============================================================
# FISCAL PERIOD VALUES
# ============================================================
# FY, Q1, Q2, Q3, Q4, LTM
