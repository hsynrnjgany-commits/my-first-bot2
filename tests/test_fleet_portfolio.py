# MARI — آزمون‌های پذیرش خوشهٔ K (ریسک سبد پژوهشی) — کاملاً آفلاین
# پوشش دستور: بازتولیدپذیری محاسبات، ورودی ناقص/نامعتبر، هشدار دادهٔ ناکافی،
# تفکیک تاریخی/سناریو، اتصال واقعی به Orchestrator، ایمنی و نشت کلید.

import json
import os
import tempfile
import unittest

from fleet_loader import load_fleet

fleet = load_fleet()
risk = fleet.risk
contract = fleet.contract
orchestrator_mod = fleet.orchestrator

ASOF = 1_799_000_000_000


def trade(sym, net, entry_ms, exit_reason="TP", exit_ms=None):
    return {"symbol": sym, "net_pct": net, "entry_time_ms": entry_ms,
            "exit_reason": exit_reason,
            "exit_time_ms": exit_ms if exit_ms is not None
            else entry_ms + 3_600_000}


def candle(i, close):
    return {"open_time": 1_700_000_000_000 + i * 3_600_000,
            "open": close, "high": close, "low": close, "close": close,
            "volume": 1.0}


def candles_for(closes):
    return [candle(i, c) for i, c in enumerate(closes)]


TRADES = [
    trade("AAAUSDT", 2.0, 0), trade("AAAUSDT", -1.0, 3600_000),
    trade("BBBUSDT", 1.5, 0), trade("BBBUSDT", -1.0, 7200_000),
    trade("CCCUSDT", 0.5, 0), trade("CCCUSDT", -1.0, 10_800_000),
    trade("AAAUSDT", 2.0, 14_400_000), trade("BBBUSDT", -1.0, 18_000_000),
    trade("CCCUSDT", 2.0, 21_600_000), trade("AAAUSDT", -1.0, 25_200_000),
]


class RiskMathTests(unittest.TestCase):
    def test_multiplicative_equity_known_values(self):
        res = risk.multiplicative_equity(
            [trade("X", 10.0, 0), trade("X", -10.0, 1)], base_usd=100.0)
        # 100 → 110 → 99 : بازسرگذاشت ضربی واقعی است
        self.assertEqual(res["final_equity_usd"], 99.0)
        self.assertAlmostEqual(res["max_drawdown_pct"], 10.0, places=4)
        self.assertEqual(res["cumulative_pct"], -1.0)

    def test_var95_insufficient_sample_returns_none(self):
        self.assertIsNone(risk.historical_var95([1.0, -1.0, 2.0]))

    def test_var95_known_percentile(self):
        nets = [-10.0] + [float(i) for i in range(19)]  # n=20 → صدک پنجم
        self.assertEqual(risk.historical_var95(nets), -10.0)

    def test_fee_sensitivity_monotonic_decreasing(self):
        rows = risk.fee_sensitivity(TRADES)
        self.assertEqual(len(rows), 3)
        totals = [r["total_net_pct"] for r in rows]
        self.assertEqual(totals, sorted(totals, reverse=True))
        for row in rows:
            self.assertTrue(row["scenario"])  # برچسب سناریو اجباری است

    def test_pairwise_correlation_perfect_and_insufficient(self):
        # جفت دقیقاً قرینه: بازده‌های B = منفیِ بازده‌های A → همبستگی دقیقاً -1
        rets = [0.05, -0.03, 0.04, -0.01, 0.02] * 12
        closes_a, closes_b = [100.0], [100.0]
        for r in rets:
            closes_a.append(closes_a[-1] * (1.0 + r))
            closes_b.append(closes_b[-1] * (1.0 - r))
        up = candles_for(closes_a)
        down = candles_for(closes_b)
        short = candles_for([1.0, 2.0, 3.0])
        zero = candles_for([0.0] * 60)  # قیمت نامعتبر — بند ۶ دستور
        res = risk.pairwise_correlation({"A": up, "B": down, "C": short,
                                         "Z": zero})
        self.assertEqual(res["A/B"], -1.0)  # کامل خلاف جهت
        self.assertIsNone(res["A/C"])       # دادهٔ ناکافی → None (نه صفر جعلی)
        self.assertIsNone(res["A/Z"])       # ورودی نامعتبر → None (نه کرش)

    def test_simultaneous_positions_overlap(self):
        tr = [trade("A", 1.0, 0, exit_reason="OPEN", exit_ms=86_400_000),
              trade("B", 1.0, 1_000_000, exit_reason="OPEN",
                    exit_ms=86_400_000 + 1_000_000)]
        res = risk.simultaneous_positions(tr)
        self.assertEqual(res["max_simultaneous"], 2)
        self.assertEqual(res["currently_open"], 2)
        self.assertEqual(res["open_symbols"], ["A", "B"])
        self.assertGreater(res["all_open_sl_scenario_loss_pct"], 0)

    def test_exposure_table_shares_sum(self):
        table = risk.exposure_table(TRADES)
        shares = sum(v["trade_share_pct"] for v in table.values())
        self.assertAlmostEqual(shares, 100.0, places=1)
        for row in table.values():
            self.assertTrue(row["assumed_nominal_usd"] > 0)

    def test_concentration_function_existing(self):
        res = risk.concentration(TRADES)
        self.assertIn("hhi", res)
        self.assertIn("AAAUSDT", res["symbols"])


class PortfolioMessageTests(unittest.TestCase):
    def call(self, trades=TRADES, candles_map=None, task_id=None):
        return risk.portfolio_risk_message(
            trades, data_asof_ms=ASOF, candles_map=candles_map,
            task_id=task_id)

    def test_valid_portfolio_message(self):
        msgs = self.call()
        self.assertEqual(len(msgs), 1)  # HHI این سبد < 0.6 → بدون فرضیهٔ تمرکز
        msg = msgs[0]
        self.assertEqual(msg["cluster_id"], "K")
        self.assertEqual(msg["event_type"], "PAPER_PORTFOLIO_RISK")
        self.assertEqual(msg["validation_status"], "OBSERVED")
        feats = msg["features"]
        self.assertEqual(feats["n_trades"], len(TRADES))
        self.assertTrue(feats["assumed_capital_is_paper"])
        self.assertIn("equity_multiplicative", feats)
        self.assertIn("fee_sensitivity", feats)

    def test_empty_portfolio_unavailable(self):
        msgs = self.call(trades=[])
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["event_type"],
                         "PAPER_PORTFOLIO_RISK_UNAVAILABLE")
        self.assertEqual(msgs[0]["validation_status"], "UNAVAILABLE")

    def test_small_sample_warning_no_false_precision(self):
        small = TRADES[:5]
        msgs = self.call(trades=small)
        joined = " ".join(msgs[0]["uncertainty"])
        self.assertIn("نمونهٔ کوچک", joined)
        self.assertIsNone(msgs[0]["features"]["var95_pct"])

    def test_concentration_hypothesis_threshold(self):
        tr = [trade("WHaleUSDT", 5.0, 0), trade("WHaleUSDT", 4.0, 1),
              trade("aUSDT", -0.05, 2), trade("bUSDT", 0.05, 3)]
        msgs = self.call(trades=tr)
        types = [m["event_type"] for m in msgs]
        self.assertIn("CONCENTRATION_HYPOTHESIS", types)
        hyp = next(m for m in msgs
                   if m["event_type"] == "CONCENTRATION_HYPOTHESIS")
        self.assertEqual(hyp["validation_status"], "HYPOTHESIS")
        self.assertTrue(hyp["hypothesis"]["falsifiable_by"])

    def test_reproducibility_same_input_same_ids(self):
        a = self.call()
        b = self.call()
        self.assertEqual([m["event_id"] for m in a], [m["event_id"] for m in b])
        self.assertEqual(json.dumps(a[0]["features"], sort_keys=True),
                         json.dumps(b[0]["features"], sort_keys=True))

    def test_no_orders_and_no_secrets(self):
        blob = json.dumps(self.call(candles_map={
            "AAAUSDT": candles_for([float(i) for i in range(60)])}),
            ensure_ascii=False)
        for needle in ("place_order", "sendOrder", "createOrder", "AKIA",
                       "xoxb", "ghp_", "Bearer ", "api_key", "secret",
                       "BEGIN PRIVATE"):
            self.assertNotIn(needle, blob)

    def test_invalid_trades_do_not_crash(self):
        broken = [{"symbol": "X", "net_pct": None, "entry_time_ms": None,
                   "exit_reason": "TP"}]
        with self.assertRaises((TypeError, KeyError)):
            self.call(trades=broken)  # ورودی نامعتبر قرمز است، نه ساکت


class OrchestratorConnectionTests(unittest.TestCase):
    def test_k_via_official_path_with_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch = orchestrator_mod.Orchestrator(state_dir=tmp)
            orch.register(risk.PortfolioRiskCluster())
            task = {"cluster_id": "K", "symbol": "PORTFOLIO", "candles": None,
                    "ctx": {"interval": "1h", "data_asof_ms": ASOF,
                            "paper_trades": TRADES}}
            first = orch.run_cycle([task])
            self.assertEqual(first["report"]["health"]["K"]["status"], "OK")
            self.assertTrue(first["events"])
            second = orch.run_cycle([dict(task)])
            self.assertEqual(second["report"]["tasks_skipped_duplicate"], 1)
            self.assertEqual(second["events"], [])  # ضدتکرار واقعی

    def test_k_failure_does_not_break_sibling(self):
        class Boom:
            cluster_id = "BOOM2"

            def run(self, task):
                raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            orch = orchestrator_mod.Orchestrator(state_dir=tmp)
            orch.register(risk.PortfolioRiskCluster())
            orch.register(Boom())
            result = orch.run_cycle([
                {"cluster_id": "K", "symbol": "PORTFOLIO", "candles": None,
                 "ctx": {"interval": "1h", "data_asof_ms": ASOF,
                         "paper_trades": TRADES}},
                {"cluster_id": "BOOM2", "symbol": "X", "candles": None,
                 "ctx": {"interval": "1h", "data_asof_ms": ASOF}},
            ])
            self.assertEqual(result["report"]["health"]["K"]["status"], "OK")
            self.assertEqual(result["report"]["health"]["BOOM2"]["status"],
                             "ERROR")


if __name__ == "__main__":
    unittest.main()
