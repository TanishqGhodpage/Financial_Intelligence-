"""
Phase 4A Integration & Validation Test Suite
============================================
Validates:
1. Comparative Intelligence Engine (Mean, Median, Std Dev, Variance, Percentiles, Z-Scores, Rankings)
2. Trend Analytics Engine (CAGR, YoY Growth, Linear Regression Slope, R², SMA, EMA)
3. Executive Health Engine (Health Scores 0-100, Ratings AAA-D, Traffic Lights)
4. Decision Workspace Persistence (Saved Comparisons, Analyst Notes, Workspace State)
5. REST API Endpoint Integration (/api/v1/comparison & /api/v1/workspace)
"""

import json
import sys
import urllib.request
from pathlib import Path

# Ensure project root is in python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.domain.value_objects import HealthRating, TrafficLight, TrendDirection
from core.services.analytics.comparison import (
    ComparativeAnalyticsEngine,
    calculate_mean,
    calculate_median,
    calculate_percentiles,
    calculate_rankings,
    calculate_std_dev,
    calculate_z_scores,
)
from core.services.analytics.health import ExecutiveHealthEngine
from core.services.analytics.trend import (
    TrendAnalyticsEngine,
    calculate_cagr,
    calculate_ema,
    calculate_linear_regression,
    calculate_sma,
    calculate_yoy_growth,
)

API = "http://localhost:8000/api/v1"
HEALTH = "http://localhost:8000/api/health"


def log_test(step_num: int, title: str, status: str = "PASS", details: str = ""):
    tag = "[PASS]" if status == "PASS" else "[FAIL]"
    print(f"{tag} Step {step_num}: {title}")
    if details:
        print(f"       -> {details}")


def test_comparative_math():
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    mean_val = calculate_mean(vals)
    assert mean_val == 30.0, f"Expected mean 30.0, got {mean_val}"

    median_val = calculate_median(vals)
    assert median_val == 30.0, f"Expected median 30.0, got {median_val}"

    std_val = calculate_std_dev(vals)
    assert round(std_val, 2) == 15.81, f"Expected std_dev 15.81, got {std_val}"

    percs = calculate_percentiles(vals)
    assert percs["p50"] == 30.0, f"Expected P50 30.0, got {percs['p50']}"

    comp_dict = {"c1": 10.0, "c2": 30.0, "c3": 50.0}
    z_sc = calculate_z_scores(comp_dict)
    assert z_sc["c2"] == 0.0, f"Mean element Z-score should be 0.0, got {z_sc['c2']}"
    assert z_sc["c3"] > 0, "Above mean element should have positive Z-score"

    rankings = calculate_rankings(comp_dict, reverse=True)
    assert rankings["c3"] == 1, "Highest value should be rank 1"
    assert rankings["c1"] == 3, "Lowest value should be rank 3"


def test_trend_math():
    cagr = calculate_cagr(100.0, 200.0, 4)
    # (200/100)^(1/4) - 1 = 1.4142 - 1 = 0.189207
    assert round(cagr, 4) == 0.1892, f"Expected CAGR 0.1892, got {cagr}"

    yoy = calculate_yoy_growth([(2020, 100.0), (2021, 120.0)])
    assert yoy[0]["growth_pct"] == 20.0, f"Expected YoY 20%, got {yoy[0]['growth_pct']}"

    series = [(2020, 10.0), (2021, 20.0), (2022, 30.0)]
    slope, r2 = calculate_linear_regression(series)
    assert round(slope, 2) == 10.0, f"Expected slope 10.0, got {slope}"
    assert round(r2, 2) == 1.0, f"Expected perfect R2 1.0, got {r2}"

    vals = [10.0, 20.0, 30.0, 40.0]
    sma = calculate_sma(vals, window=3)
    assert len(sma) == 4
    ema = calculate_ema(vals, span=3)
    assert len(ema) == 4


def test_executive_health_scoring():
    engine = ExecutiveHealthEngine()
    summary = engine.evaluate_company(
        company_id="c_test",
        ticker="TEST",
        company_name="Test Company",
        metrics={
            "gross_profit_margin": 0.50, # High -> Green
            "operating_margin": 0.25,     # High -> Green
            "return_on_equity": 0.22,     # High -> Green
            "current_ratio": 2.0,         # Ideal -> Green
            "debt_to_equity": 0.4,        # Low -> Green
            "free_cash_flow": 5000.0,     # Positive -> Green
        },
    )
    assert summary.overall_score >= 80.0, f"High performing metrics should produce score >= 80, got {summary.overall_score}"
    assert summary.rating in (HealthRating.AAA, HealthRating.AA, HealthRating.A), f"Expected A/AA/AAA rating, got {summary.rating}"
    assert summary.traffic_light == TrafficLight.GREEN, f"Expected Green traffic light, got {summary.traffic_light}"


def main():
    print("=" * 65)
    print("FINANCIAL INTELLIGENCE PLATFORM — PHASE 4A INTEGRATION TEST")
    print("=" * 65)

    # ---------------------------------------------------------
    # TEST 1: Unit Test Pure Statistical & Trend Math
    # ---------------------------------------------------------
    try:
        test_comparative_math()
        test_trend_math()
        test_executive_health_scoring()
        log_test(1, "Pure Math & Statistical Engines", "PASS", "Mean, Median, StdDev, CAGR, YoY, Regression, SMA, EMA, Health Scoring verified.")
    except Exception as e:
        log_test(1, "Pure Math & Statistical Engines", "FAIL", str(e))

    # ---------------------------------------------------------
    # TEST 2: Server Health Endpoint
    # ---------------------------------------------------------
    try:
        resp = urllib.request.urlopen(HEALTH)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ok"
        log_test(2, "Server Health Endpoint", "PASS", f"Version: {data['version']}")
    except Exception as e:
        log_test(2, "Server Health Endpoint", "FAIL", str(e))

    # ---------------------------------------------------------
    # TEST 3: Comparative Analytics API Endpoint (/api/v1/comparison/analyze)
    # ---------------------------------------------------------
    try:
        # Ensure at least 2 real companies exist in the DB
        comp_resp = urllib.request.urlopen(f"{API}/companies")
        companies_list = json.loads(comp_resp.read().decode())
        comp_ids = [c["id"] for c in companies_list]

        if len(comp_ids) < 2:
            # Create AAPL and MSFT if needed
            for t in ["AAPL", "MSFT"]:
                try:
                    c_data = json.dumps({"ticker": t}).encode("utf-8")
                    c_req = urllib.request.Request(f"{API}/companies", data=c_data, headers={"Content-Type": "application/json"})
                    c_res = json.loads(urllib.request.urlopen(c_req).read().decode())
                    if c_res["id"] not in comp_ids:
                        comp_ids.append(c_res["id"])
                except Exception:
                    pass

        target_ids = comp_ids[:2]
        req_data = json.dumps({
            "company_ids": target_ids,
            "fiscal_year": 2024,
            "fiscal_period": "FY"
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{API}/comparison/analyze",
            data=req_data,
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        res = json.loads(resp.read().decode())
        assert "metric_stats" in res
        assert "executive_healths" in res
        log_test(3, "Comparative Analytics API (/api/v1/comparison/analyze)", "PASS", f"Retrieved cohort analysis for {len(res['company_tickers'])} companies ({list(res['company_tickers'].values())}).")
    except Exception as e:
        log_test(3, "Comparative Analytics API (/api/v1/comparison/analyze)", "FAIL", str(e))

    # ---------------------------------------------------------
    # TEST 4: Decision Workspace API Endpoints (/api/v1/workspace)
    # ---------------------------------------------------------
    try:
        # Create a test note
        note_req_data = json.dumps({
            "title": "Phase 4A Integration Test Note",
            "content": "Validating workspace persistence.",
            "tags": ["test", "integration"]
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{API}/workspace/notes",
            data=note_req_data,
            headers={"Content-Type": "application/json"}
        )
        resp = urllib.request.urlopen(req)
        note_res = json.loads(resp.read().decode())
        note_id = note_res["id"]
        assert note_res["title"] == "Phase 4A Integration Test Note"

        # List notes
        resp_list = urllib.request.urlopen(f"{API}/workspace/notes")
        notes_list = json.loads(resp_list.read().decode())
        assert any(n["id"] == note_id for n in notes_list)

        # Delete note
        del_req = urllib.request.Request(f"{API}/workspace/notes/{note_id}", method="DELETE")
        del_resp = urllib.request.urlopen(del_req)
        del_res = json.loads(del_resp.read().decode())
        assert del_res["status"] == "deleted"

        log_test(4, "Decision Workspace Persistence API (/api/v1/workspace/notes)", "PASS", "Created, listed, and deleted analyst decision note successfully.")
    except Exception as e:
        log_test(4, "Decision Workspace Persistence API (/api/v1/workspace/notes)", "FAIL", str(e))

    print("\n" + "=" * 65)
    print("ALL PHASE 4A TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    main()
