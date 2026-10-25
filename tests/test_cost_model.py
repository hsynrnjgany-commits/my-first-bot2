# MARI — آزمون‌های آفلاین cost_model (اولویت P2 EXECUTION ORDER 001)
# صفر شبکه؛ صفر نوشتن؛ قطعی. پوشش: پروکسی CS، پوشش هزینه، یکنوایی سناریو،
# سربه‌سر (تقاطع با فرم بسته)، حکم‌ها، بازتولیدپذیری، ایزوله‌شبکه.

import os
import sys
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from fleet_loader import load_fleet  # noqa: E402

fleet = load_fleet()
cm = fleet.cost_model
evaluator = fleet.evaluator

HOUR_MS = 3_600_000
T0 = 1_700_000_000_000


def vol_candle(i, close, base=100.0):
    """کندل پرنوسان با دامنهٔ ±۳٫۵٪ — پروکسی CS مثبت می‌دهد."""
    return {"open_time": T0 + i * HOUR_MS, "open": base, "high": base + 3.5,
            "low": base - 3.5, "close": close, "volume": 10.0}


def flat_candle(i, price=100.0):
    return {"open_time": T0 + i * HOUR_MS, "open": price, "high": price,
            "low": price, "close": price, "volume": 1.0}


def mk_trade(i, direction, entry, exit_price, reason="TP"):
    long_ = direction == "long"
    gross = (exit_price - entry) / entry if long_ \
        else (entry - exit_price) / entry
    net = gross - 2 * evaluator.FEE_PCT
    return {"symbol": "AAAUSDT", "event_id": f"E{i}", "direction": direction,
            "entry_time_ms": T0 + i * HOUR_MS, "entry": entry,
            "exit_reason": reason, "exit": exit_price,
            "gross_pct": round(gross * 100, 6),
            "net_pct": round(net * 100, 6),
            "mfe_pct": 0.0, "mae_pct": 0.0, "hold_candles": 3}


def mixed_trades(n=30):
    """نیمه TP (+۲٪) و نیمه SL (−۱٪) لانگ — با لبهٔ مثبت خالص."""
    out = []
    for i in range(n):
        if i % 2 == 0:
            out.append(mk_trade(i, "long", 100.0, 102.0, "TP"))
        else:
            out.append(mk_trade(i, "long", 100.0, 99.0, "SL"))
    return out


class TestSpreadProxy(unittest.TestCase):

    def test_positive_finite_on_volatile_series(self):
        cs = [vol_candle(i, 100.0 + (3.0 if i % 2 == 0 else -3.0))
              for i in range(60)]
        bps = cm.corwin_schultz_spread_bps(cs)
        self.assertIsInstance(bps, float)
        self.assertGreater(bps, 0.0)
        self.assertLess(bps, 10_000.0)

    def test_flat_series_yields_zero(self):
        cs = [flat_candle(i) for i in range(10)]
        self.assertEqual(cm.corwin_schultz_spread_bps(cs), 0.0)

    def test_invalid_windows_skipped_and_none_when_all_bad(self):
        cs = [vol_candle(i, 100.0) for i in range(6)]
        cs[2] = dict(cs[2], high=0.0)  # کندل نامعتبر در میانه
        bps = cm.corwin_schultz_spread_bps(cs)
        self.assertIsInstance(bps, float)
        self.assertGreaterEqual(bps, 0.0)
        all_bad = [dict(flat_candle(0), high=0.0), flat_candle(1)]
        self.assertIsNone(cm.corwin_schultz_spread_bps(all_bad))
        self.assertIsNone(cm.corwin_schultz_spread_bps([flat_candle(0)]))


class TestOverlay(unittest.TestCase):

    def test_zero_cost_reproduces_original(self):
        ts = mixed_trades(10) + [mk_trade(99, "short", 100.0, 101.0, "OPEN")]
        adj = cm.apply_execution_costs(ts, spread_bps=0.0, slippage_bps=0.0)
        for a, t in zip(adj, ts):
            self.assertEqual(a["net_pct_adj"], t["net_pct"])
            self.assertEqual(a["entry_eff"], t["entry"])
            self.assertEqual(a["exit_eff"], t["exit"])

    def test_long_adverse_fills(self):
        t = mk_trade(0, "long", 100.0, 102.0, "TP")
        a = cm.apply_execution_costs([t], spread_bps=20.0, slippage_bps=10.0)[0]
        # h = (10 + 10) bps = 0.002
        self.assertAlmostEqual(a["entry_eff"], 100.2, places=9)
        self.assertAlmostEqual(a["exit_eff"], 101.796, places=9)
        self.assertLess(a["net_pct_adj"], t["net_pct"])
        self.assertAlmostEqual(a["net_pct_adj"], 1.392814, places=4)

    def test_short_adverse_fills_symmetric(self):
        t = mk_trade(0, "short", 100.0, 99.0, "TP")
        a = cm.apply_execution_costs([t], spread_bps=20.0, slippage_bps=10.0)[0]
        self.assertLess(a["entry_eff"], 100.0)
        self.assertGreater(a["exit_eff"], 99.0)
        self.assertLess(a["net_pct_adj"], t["net_pct"])
        self.assertAlmostEqual(a["net_pct_adj"], 0.403213, places=4)

    def test_open_trades_get_adj_fields(self):
        t = mk_trade(0, "long", 100.0, 100.5, "OPEN")
        a = cm.apply_execution_costs([t], spread_bps=10.0, slippage_bps=5.0)[0]
        self.assertIn("net_pct_adj", a)
        self.assertLess(a["net_pct_adj"], t["net_pct"])


class TestScenarios(unittest.TestCase):

    def test_monotone_decay_and_baseline_exact(self):
        ts = mixed_trades(20)
        grid = cm.scenario_grid(ts, spread_bps=10.0,
                                slippage_bps_list=[0, 5, 10, 20])
        sums = [r["sum_net_pct"] for r in grid["rows"]]
        for i in range(1, len(sums)):
            self.assertLessEqual(sums[i], sums[i - 1])
        base_sum = sum(t["net_pct"] for t in ts)  # همهٔ ۲۰ تا بسته‌اند
        self.assertAlmostEqual(grid["baseline_zero_cost"]["sum_net_pct"],
                               round(base_sum, 6), places=6)
        decays = [r["edge_decayed_pct"] for r in grid["rows"]]
        for i in range(1, len(decays)):
            self.assertGreaterEqual(decays[i], decays[i - 1])
        # ستون مطلق: دلتای هر ردیف نسبت به خط پایه باید دقیق و نانوصعودی باشد
        base_sum_adj = grid["baseline_zero_cost"]["sum_net_pct"]
        for r in grid["rows"]:
            self.assertAlmostEqual(r["delta_sum_net_pp"],
                                   round(r["sum_net_pct"] - base_sum_adj, 6),
                                   places=6)
            self.assertLessEqual(r["delta_sum_net_pp"], 0.0)


class TestBreakEven(unittest.TestCase):

    def test_closed_form_cross_check(self):
        ts = [mk_trade(i, "long", 100.0, 101.0, "TP") for i in range(10)]
        be = cm.break_even_slippage_bps(ts, spread_bps=0.0)
        # فرم بسته: 1.01(1−s)/(1+s) = 1.002 → s = 0.008/2.012
        manual_bps = (0.008 / 2.012) * 10_000
        self.assertEqual(be["note"], "BISECTION_DETERMINISTIC")
        self.assertAlmostEqual(be["bps"], manual_bps, delta=0.1)

    def test_spread_shrinks_break_even(self):
        ts = mixed_trades(20)
        no_spread = cm.break_even_slippage_bps(ts, spread_bps=0.0)["bps"]
        with_spread = cm.break_even_slippage_bps(ts, spread_bps=10.0)["bps"]
        self.assertLess(with_spread, no_spread)

    def test_negative_edge_flagged(self):
        ts = [mk_trade(i, "long", 100.0, 99.0, "SL") for i in range(10)]
        be = cm.break_even_slippage_bps(ts, spread_bps=0.0)
        self.assertEqual(be["bps"], 0.0)
        self.assertEqual(be["note"], "NO_POSITIVE_EDGE_AT_ZERO_SLIPPAGE")

    def test_no_closed_trades(self):
        ts = [mk_trade(0, "long", 100.0, 100.5, "OPEN")]
        be = cm.break_even_slippage_bps(ts)
        self.assertIsNone(be["bps"])
        self.assertEqual(be["note"], "NO_CLOSED_TRADES")


class TestReport(unittest.TestCase):

    def test_report_structure_and_verdicts(self):
        candles = {"AAAUSDT": [vol_candle(i, 100.0 + (1 if i % 2 else -1))
                               for i in range(50)],
                   "BBBUSDT": [vol_candle(i, 50.0 + (0.5 if i % 2 else -0.5))
                               for i in range(50)]}
        rep = cm.cost_report(candles, mixed_trades(30))
        self.assertEqual(rep["verdict"], "REPORTED")
        self.assertEqual(rep["method"], "cost_model/overlay_v1")
        self.assertIn("READ ONLY", rep["mode"])
        med = rep["spread_proxy"]["median_bps"]
        self.assertIsInstance(med, float)
        self.assertGreaterEqual(med, 0.0)
        self.assertEqual(len(rep["scenarios"]["rows"]), 4)
        self.assertIsInstance(rep["break_even"]["bps"], float)
        small = cm.cost_report(candles, mixed_trades(5))
        self.assertEqual(small["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(small["reason"], "CLOSED_BELOW_MIN_SAMPLES")

    def test_empty_input_refused(self):
        rep = cm.cost_report({}, [])
        self.assertEqual(rep["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rep["reason"], "EMPTY_INPUT_NO_TRADES_OR_CANDLES")

    def test_no_valid_spread_refused(self):
        candles = {"FLATUSDT": [flat_candle(i) for i in range(5)]}
        bad = [dict(flat_candle(0), high=0.0), flat_candle(1)]
        candles["FLATUSDT"] = bad  # همهٔ پنجره‌ها نامعتبر
        rep = cm.cost_report(candles, mixed_trades(30))
        self.assertEqual(rep["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rep["reason"], "NO_VALID_SPREAD_ESTIMATE")


class TestDeterminismAndIsolation(unittest.TestCase):

    def test_two_runs_byte_identical(self):
        candles = {"AAAUSDT": [vol_candle(i, 100.0 + (1 if i % 2 else -1))
                               for i in range(40)]}
        r1 = cm.cost_report(candles, mixed_trades(30))
        r2 = cm.cost_report(candles, mixed_trades(30))
        self.assertEqual(cm.canonical_json(r1), cm.canonical_json(r2))

    def test_no_network_calls(self):
        candles = {"AAAUSDT": [vol_candle(i, 100.0) for i in range(20)]}
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=RuntimeError("NETWORK_FORBIDDEN")):
            rep = cm.cost_report(candles, mixed_trades(30))
        self.assertIn("scenarios", rep)


if __name__ == "__main__":
    unittest.main()
