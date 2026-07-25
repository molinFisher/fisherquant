import sys
import subprocess
import tempfile
from pathlib import Path
from fisher_temp.data_downloader import DataDownloader, A_SHARE_TICKERS, HK_CONNECT_TICKERS
from fisher_temp.auto_fixer import AutoFixEngine
from fisher_temp.backtest_runner import BacktestRunner
from fisher_temp.monitor_verifier import MonitorVerifier
from fisher_temp.report_generator import ReportGenerator
from fisher.store.engine import DuckDBEngine
from fisher.store.schema import init_schema
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_runner")


def main():
    db_path = "data/test_system.db"
    engine = DuckDBEngine(db_path)
    init_schema(engine)

    results = {
        "data_ok": False, "a_share_count": 0, "hk_count": 0,
        "unit_passed": 0, "unit_failed": 0, "unit_total": 0,
        "backtest_status": "not_run", "backtest_orders": 0,
        "monitor_status": "not_run", "monitor_results": {},
        "total_fixed": 0, "unresolved": 0,
        "error_details": [], "backtest_details": [], "fix_details": [],
    }

    # Phase 1: Data
    logger.info("=== Phase 1: Data Download ===")
    dl = DataDownloader(engine)
    dl_result = dl.download_all()
    results["a_share_count"] = len(dl_result["a_share"])
    results["hk_count"] = len(dl_result["hk_connect"])
    results["data_ok"] = results["a_share_count"] > 0 or results["hk_count"] > 0
    logger.info("Downloaded %d A-share, %d HK, %d errors",
                results["a_share_count"], results["hk_count"], len(dl_result["errors"]))

    # Phase 2: Unit Tests
    logger.info("=== Phase 2: Unit Tests ===")
    test_result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short", "--timeout=30"],
        capture_output=True, text=True, timeout=300, cwd=".",
    )
    fixer = AutoFixEngine(".")
    errors = fixer.parse_test_output(test_result.stdout + "\n" + test_result.stderr)
    results["unit_total"] = test_result.stdout.count("PASSED") + test_result.stdout.count("FAILED")
    results["unit_failed"] = len(errors)
    results["unit_passed"] = results["unit_total"] - results["unit_failed"]

    # Phase 2b: Auto-Fix (3 rounds)
    logger.info("=== Phase 2b: Auto-Fix ===")
    for rnd in range(3):
        fix_results, msg = fixer.run_iteration(test_result.stdout + "\n" + test_result.stderr)
        logger.info("Round %d: %s", rnd+1, msg)
        if all(r.fixed for r in fix_results):
            break
        test_result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
            capture_output=True, text=True, timeout=300, cwd=".",
        )
    results["total_fixed"] = sum(1 for r in fixer.fix_log if r.fixed)
    results["unresolved"] = len(fixer.fix_log) - results["total_fixed"]
    results["fix_details"] = [
        {"error": r.record.exception_type, "strategy": r.record.exception_type,
         "fixed": r.fixed, "description": r.description}
        for r in fixer.fix_log
    ]

    # Phase 3: Backtest
    logger.info("=== Phase 3: Backtest ===")
    runner = BacktestRunner(db_path)
    try:
        a_result = runner.run_a_share_backtest(
            ["000001.SZ", "600519.SH", "300750.SZ"],
            {"start": "2024-01-01", "end": "2024-12-31", "fast": 10, "slow": 30, "capital": 1000000},
        )
        results["backtest_details"].append({
            "name": "A-share Momentum", "tickers": ["000001.SZ", "600519.SH", "300750.SZ"],
            "status": a_result.get("status"), "orders": a_result.get("total_orders", 0),
            "metrics": a_result.get("metrics", {}),
        })
        results["backtest_orders"] = a_result.get("total_orders", 0)
        results["backtest_status"] = a_result.get("status", "failed")
    except Exception as e:
        results["backtest_status"] = f"failed: {e}"
        logger.error("Backtest failed: %s", e)

    try:
        hk_result = runner.run_hk_backtest(
            ["00700.HK", "03690.HK"],
            {"start": "2024-01-01", "end": "2024-12-31", "fast": 5, "slow": 20, "capital": 1000000},
        )
        results["backtest_details"].append({
            "name": "HK Connect Momentum", "tickers": ["00700.HK", "03690.HK"],
            "status": hk_result.get("status"), "orders": hk_result.get("total_orders", 0),
            "metrics": hk_result.get("metrics", {}),
        })
    except Exception as e:
        logger.error("HK backtest failed: %s", e)

    # Phase 4: Monitor
    logger.info("=== Phase 4: Monitor ===")
    try:
        verifier = MonitorVerifier()
        monitor_results = verifier.run()
        results["monitor_results"] = monitor_results
        results["monitor_status"] = "pass" if all(
            isinstance(v, int) and 200 <= v < 400 for v in monitor_results.values()
        ) else "fail"
    except Exception as e:
        results["monitor_status"] = f"failed: {e}"

    # Phase 5: Report
    logger.info("=== Phase 5: Report ===")
    gen = ReportGenerator()
    report_path = gen.generate(results)
    logger.info("Report generated: %s", report_path)

    engine.close()
    return results


if __name__ == "__main__":
    result = main()
    print("\n=== FINAL SUMMARY ===")
    print(f"Data:  {result['a_share_count']} A-share, {result['hk_count']} HK")
    print(f"Tests: {result['unit_passed']} pass, {result['unit_failed']} fail, {result['total_fixed']} fixed")
    print(f"Backtest: {result['backtest_status']} ({result['backtest_orders']} orders)")
    print(f"Monitor: {result['monitor_status']}")
    print(f"Unresolved: {result['unresolved']}")
