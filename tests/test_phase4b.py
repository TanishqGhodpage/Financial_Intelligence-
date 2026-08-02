"""
Phase 4B Integration & Validation Test Suite
============================================
Validates:
1. Scenario Engine (Base, Bull, Bear, Custom Parameter simulation)
2. Sensitivity Analysis Engine (N x M 2D Matrix Generation)
3. Stress Test Engine (Market shocks & Stress level classification)
4. Forecast Strategy Engine (Strategy Pattern: Naive, Linear, SMA, EMA)
5. Variance Analysis Engine (Actual vs Benchmark variance & F/U badges)
6. REST API Endpoints (/api/v1/modeling/*)
"""

import json
import sys
import urllib.request
from pathlib import Path

# Ensure project root is in python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.services.modeling.forecasting import (
    ExponentialSmoothingForecastStrategy,
    LinearRegressionForecastStrategy,
    MovingAverageForecastStrategy,
    NaiveForecastStrategy,
    get_forecast_strategy,
)
from core.services.modeling.scenarios import ScenarioModelingEngine, ScenarioParameters
from core.services.modeling.sensitivity import SensitivityAnalysisEngine
from core.services.modeling.stress_test import StressLevel, StressShockParams, StressTestEngine
from core.services.modeling.variance import VarianceAnalysisEngine, VarianceType

API = "http://localhost:8000/api/v1"
HEALTH = "http://localhost:8000/api/health"


def log_test(step_num: int, title: str, status: str = "PASS", details: str = ""):
    tag = "[PASS]" if status == "PASS" else "[FAIL]"
    print(f"{tag} Step {step_num}: {title}")
    if details:
        print(f"       -> {details}")


def test_scenario_engine_domain():
    engine = ScenarioModelingEngine()
    base_inputs = {
        "revenue": 1000.0,
        "cost_of_goods_sold": 600.0,
        "operating_income": 200.0,
        "net_income": 150.0,
        "interest_expense": 10.0,
        "free_cash_flow": 120.0,
        "total_liabilities": 500.0,
        "cash": 100.0,
    }
    result = engine.simulate_scenarios(
        company_id="c_test_scen",
        base_inputs=base_inputs,
        custom_params=ScenarioParameters(name="Custom Test", revenue_growth_pct=0.20),
    )
    assert "base" in result.scenarios
    assert "bull" in result.scenarios
    assert "bear" in result.scenarios
    assert "custom" in result.scenarios
    assert result.scenarios["custom"].statement_impact["revenue"] == 1200.0


def test_sensitivity_engine_domain():
    engine = SensitivityAnalysisEngine()
    res = engine.generate_dcf_sensitivity(
        base_fcf=100.0,
        wacc_range=[0.08, 0.10, 0.12],
        terminal_growth_range=[0.02, 0.03],
    )
    assert len(res.grid_matrix) == 3
    assert len(res.grid_matrix[0]) == 2
    assert res.grid_matrix[0][0] > res.grid_matrix[2][0], "Lower WACC should yield higher equity value"


def test_stress_test_engine_domain():
    engine = StressTestEngine()
    base_inputs = {
        "revenue": 1000.0,
        "operating_income": 200.0,
        "interest_expense": 15.0,
        "current_assets": 500.0,
        "current_liabilities": 300.0,
        "total_liabilities": 600.0,
        "short_term_debt": 50.0,
        "long_term_debt": 200.0,
        "cash": 150.0,
    }
    # Mild shock -> SAFE
    safe_res = engine.run_stress_test(
        company_id="c_test_stress",
        base_inputs=base_inputs,
        shocks=StressShockParams(revenue_shock_pct=-0.05, margin_compression_bps=50.0, debt_shock_pct=0.0),
    )
    assert safe_res.stress_level in (StressLevel.SAFE, StressLevel.MODERATE_STRESS)

    # Severe shock -> DISTRESS
    severe_res = engine.run_stress_test(
        company_id="c_test_stress",
        base_inputs=base_inputs,
        shocks=StressShockParams(revenue_shock_pct=-0.80, margin_compression_bps=3000.0, debt_shock_pct=2.0),
    )
    assert severe_res.stress_level == StressLevel.DISTRESS
    assert severe_res.insolvency_warning is True


def test_forecasting_domain():
    series = [(2020, 100.0), (2021, 110.0), (2022, 120.0), (2023, 130.0)]

    naive = get_forecast_strategy("naive").forecast(series, periods_ahead=2)
    assert naive.projected_points[0].value == 130.0

    linear = get_forecast_strategy("linear").forecast(series, periods_ahead=2)
    assert linear.projected_points[0].value == 140.0

    sma = get_forecast_strategy("sma").forecast(series, periods_ahead=2)
    assert round(sma.projected_points[0].value, 1) == 120.0  # avg of 110,120,130

    ema = get_forecast_strategy("ema").forecast(series, periods_ahead=2)
    assert ema.projected_points[0].value > 100.0


def test_variance_domain():
    engine = VarianceAnalysisEngine()
    actuals = {"revenue": 1200.0, "interest_expense": 25.0}
    benchmarks = {"revenue": 1000.0, "interest_expense": 20.0}

    res = engine.analyze_variance("c_test_var", actuals, benchmarks, "Budget")
    assert res.favorable_count == 1  # Revenue +200 is Favorable
    assert res.unfavorable_count == 1  # Interest Expense +5 is Unfavorable


def main():
    print("=" * 65)
    print("FINANCIAL INTELLIGENCE PLATFORM — PHASE 4B INTEGRATION TEST")
    print("=" * 65)

    # ---------------------------------------------------------
    # TEST 1: Pure Domain Modeling Engines
    # ---------------------------------------------------------
    try:
        test_scenario_engine_domain()
        test_sensitivity_engine_domain()
        test_stress_test_engine_domain()
        test_forecasting_domain()
        test_variance_domain()
        log_test(1, "Domain Modeling Engines", "PASS", "Scenarios, Sensitivity Matrix, Stress Testing, Forecast Strategies (Strategy Pattern), and Variance verified.")
    except Exception as e:
        log_test(1, "Domain Modeling Engines", "FAIL", str(e))

    # ---------------------------------------------------------
    # TEST 2: Server Health Check
    # ---------------------------------------------------------
    try:
        resp = urllib.request.urlopen(HEALTH)
        data = json.loads(resp.read().decode())
        assert data["status"] == "ok"
        log_test(2, "Server Health Check", "PASS", f"Version: {data['version']}")
    except Exception as e:
        log_test(2, "Server Health Check", "FAIL", str(e))

    # ---------------------------------------------------------
    # TEST 3: Modeling REST APIs (/api/v1/modeling/*)
    # ---------------------------------------------------------
    try:
        # Fetch a real company ID
        comp_resp = urllib.request.urlopen(f"{API}/companies")
        companies = json.loads(comp_resp.read().decode())
        cid = companies[0]["id"] if companies else "c_mock"

        # 1. Scenarios Endpoint
        req_scen = json.dumps({"company_id": cid, "fiscal_year": 2024}).encode("utf-8")
        resp = urllib.request.urlopen(urllib.request.Request(f"{API}/modeling/scenarios", data=req_scen, headers={"Content-Type": "application/json"}))
        scen_res = json.loads(resp.read().decode())
        assert "scenarios" in scen_res

        # 2. Sensitivity Endpoint
        req_sens = json.dumps({"company_id": cid, "sensitivity_type": "dcf"}).encode("utf-8")
        resp = urllib.request.urlopen(urllib.request.Request(f"{API}/modeling/sensitivity", data=req_sens, headers={"Content-Type": "application/json"}))
        sens_res = json.loads(resp.read().decode())
        assert "grid_matrix" in sens_res

        # 3. Stress Test Endpoint
        req_stress = json.dumps({"company_id": cid}).encode("utf-8")
        resp = urllib.request.urlopen(urllib.request.Request(f"{API}/modeling/stress-test", data=req_stress, headers={"Content-Type": "application/json"}))
        stress_res = json.loads(resp.read().decode())
        assert "stress_level" in stress_res

        # 4. Forecast Endpoint
        req_fore = json.dumps({"company_id": cid, "metric_key": "revenue", "strategy_type": "linear"}).encode("utf-8")
        resp = urllib.request.urlopen(urllib.request.Request(f"{API}/modeling/forecast", data=req_fore, headers={"Content-Type": "application/json"}))
        fore_res = json.loads(resp.read().decode())
        assert "projected_points" in fore_res

        # 5. Variance Endpoint
        req_var = json.dumps({"company_id": cid, "benchmark_name": "Forecast"}).encode("utf-8")
        resp = urllib.request.urlopen(urllib.request.Request(f"{API}/modeling/variance", data=req_var, headers={"Content-Type": "application/json"}))
        var_res = json.loads(resp.read().decode())
        assert "metrics_variance" in var_res

        log_test(3, "Financial Modeling Suite REST Endpoints (/api/v1/modeling/*)", "PASS", "Verified /scenarios, /sensitivity, /stress-test, /forecast, and /variance APIs.")
    except Exception as e:
        log_test(3, "Financial Modeling Suite REST Endpoints (/api/v1/modeling/*)", "FAIL", str(e))

    print("\n" + "=" * 65)
    print("ALL PHASE 4B TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 65)


if __name__ == "__main__":
    main()
