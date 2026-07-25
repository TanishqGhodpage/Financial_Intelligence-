"""
End-to-End Test Script for Financial Intelligence Platform
==========================================================
Tests: Company creation → Market data fetch → Pipeline ingestion → Analytics
"""
import json
import sys
import urllib.request

API = "http://localhost:8000/api/v1"

def api_post(endpoint, data):
    req = urllib.request.Request(
        f"{API}/{endpoint}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read().decode())

def api_get(endpoint):
    resp = urllib.request.urlopen(f"{API}/{endpoint}")
    return json.loads(resp.read().decode())

def main():
    print("=" * 60)
    print("Financial Intelligence Platform — E2E Test")
    print("=" * 60)

    # 1. Health Check
    print("\n[1/5] Health check...")
    # Health endpoint is at /api/health, not /api/v1/health
    resp = urllib.request.urlopen("http://localhost:8000/api/health")
    health = json.loads(resp.read().decode())
    assert health["status"] == "ok", f"Health check failed: {health}"
    print(f"  [OK] API is healthy (v{health['version']})")

    # 2. Create Company
    print("\n[2/5] Creating AAPL company...")
    company = api_post("companies", {
        "ticker": "AAPL",
        "name": "Apple Inc.",
        "sector": "Technology",
        "currency": "USD",
    })
    company_id = company["id"]
    print(f"  ✓ Company created: {company['ticker']} (ID: {company_id[:8]}...)")

    # 3. Fetch Market Data
    print("\n[3/5] Fetching AAPL market data (2025-06-23 → 2025-06-30)...")
    result = api_post("documents/fetch-market-data", {
        "company_id": company_id,
        "ticker": "AAPL",
        "start_date": "2025-06-23",
        "end_date": "2025-06-30",
    })
    print(f"  ✓ Status:       {result['status']}")
    print(f"  ✓ Rows fetched: {result['rows_fetched']}")
    print(f"  ✓ Rows stored:  {result['rows_stored']}")
    print(f"  ✓ Saved to:     {result['saved_path']}")
    print(f"  ✓ Filename:     {result['filename']}")
    assert result["status"] == "COMPLETED", f"Pipeline failed: {result}"
    assert result["rows_fetched"] > 0, "No data fetched!"

    # 4. Upload CSV
    print("\n[4/5] Uploading AAPL FY2024 CSV from data/ folder...")
    import io
    import os
    csv_path = os.path.join("data", "companies", "AAPL", "financials", "AAPL_FY2024.csv")
    with open(csv_path, "rb") as f:
        csv_bytes = f.read()

    # Build multipart/form-data manually (no requests library)
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    body = b""
    # company_id field
    body += f"--{boundary}\r\n".encode()
    body += f'Content-Disposition: form-data; name="company_id"\r\n\r\n{company_id}\r\n'.encode()
    # fiscal_year
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="fiscal_year"\r\n\r\n2024\r\n'
    # fiscal_period
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="fiscal_period"\r\n\r\nFY\r\n'
    # source_authority
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="source_authority"\r\n\r\nsec_filing\r\n'
    # file
    body += f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="files"; filename="AAPL_FY2024.csv"\r\n'
    body += b"Content-Type: text/csv\r\n\r\n"
    body += csv_bytes
    body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(
        f"{API}/documents",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req)
        upload_result = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print("HTTP ERROR body:", e.read().decode())
        raise
    print(f"  ✓ Files processed: {upload_result['files_processed']}")
    print(f"  ✓ Rows stored:  {upload_result['total_rows_stored']}")
    assert upload_result["files_processed"] > 0, f"Upload pipeline failed!"

    # 5. Run Analytics
    print("\n[5/5] Running analytics on AAPL FY2024...")
    analytics = api_get(f"analytics/{company_id}?fiscal_year=2024&fiscal_period=FY")
    print(f"  ✓ Metrics calculated: {len(analytics['metrics'])}")
    for m in analytics["metrics"]:
        val = f"{m['value']*100:.2f}%" if "margin" in m["key"] or "return" in m["key"] or "ratio" in m["key"] else f"{m['value']:.4f}"
        conf = f"{m['confidence']*100:.0f}%"
        print(f"    • {m['key']:30s}  {val:>14s}  (confidence: {conf})")

    print()
    print("=" * 60)
    print("✅ ALL 5 TESTS PASSED — Phase 1 Pipeline is FULLY OPERATIONAL")
    print("=" * 60)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
