"""
Creates sample Excel financial statement files for testing.
Run: python data/create_samples.py
"""
import os
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))

samples = {
    "AAPL/financials/AAPL_Q1_2025.xlsx": {
        "Income Statement": [
            {"metric_key": "revenue", "value": 124300000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "cost_of_goods_sold", "value": 65680000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "gross_profit", "value": 58620000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "operating_income", "value": 40990000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "net_income", "value": 36330000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
        ],
        "Balance Sheet": [
            {"metric_key": "total_assets", "value": 353514000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "total_liabilities", "value": 302083000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "total_equity", "value": 51431000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "current_assets", "value": 152987000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "current_liabilities", "value": 143753000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
        ],
    },
    "MSFT/financials/MSFT_Q1_2025.xlsx": {
        "Income Statement": [
            {"metric_key": "revenue", "value": 65585000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "cost_of_goods_sold", "value": 17241000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "gross_profit", "value": 48344000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "operating_income", "value": 29524000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "net_income", "value": 24667000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
        ],
        "Balance Sheet": [
            {"metric_key": "total_assets", "value": 523017000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "total_liabilities", "value": 245836000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "total_equity", "value": 277181000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "current_assets", "value": 169456000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
            {"metric_key": "current_liabilities", "value": 112022000000, "fiscal_year": 2025, "fiscal_period": "Q1", "currency": "USD"},
        ],
    },
}

for relative_path, sheets in samples.items():
    full_path = os.path.join(BASE, "companies", relative_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with pd.ExcelWriter(full_path, engine="openpyxl") as writer:
        for sheet_name, rows in sheets.items():
            df = pd.DataFrame(rows)
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    print(f"Created: {full_path}")

print("\nAll sample files created successfully.")
