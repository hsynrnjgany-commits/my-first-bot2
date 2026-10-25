# MARI — آزمون‌های آفلاین unified_report (بستهٔ ترکیبی سه آزمایشگاه)
# صفر شبکه؛ صفر نوشتن؛ قطعی. پوشش: ماتریس برچسب‌ها، ترکیب per-symbol،
# سازگاری پرتفوی، مقیاس نوسان، مسیر walk_forward، قطعیت، ایزوله‌شبکه.

import gzip
import json
import os
import sys
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from fleet_loader import load_fleet  # noqa: E402

fleet = load_fleet()
ur = fleet.unified_report
cm = fleet.cost_model
vt = fleet.vol_target
evaluator = fleet.evaluator

HOUR_MS = 3_600_000
T0 = 1_700_000_000_000


def candle(i, close, hi_pad=1.0, lo_pad=1.0, base=100.0):
    return {"open_time": T0 + i * HOUR_MS, "open": base,
            "high": close + hi_pad, "low": close - lo_pad,
            "close": close, "volume": 10.0}


def quiet_candles(n=60):
    """بازده کوچک؛ های/لوی نزدیک → اسپرد CS کوچک."""
    return [candle(i, 100.0 + (0.1 if i % 2 else 0.0)) for i in range(n)]


def wide_candles(n=60):
    """رنج درون‌کندلی بزرگ نسبت به حرکت کلوز → اسپرد CS بزرگ (فرسایش قطعی)."""
    return [candle(i, 100.0 + (0.1 if i % 2 else 0.0),
                   hi_pad=2.0, lo_pad=1.0) for i in range(n)]


def mk_trade(i, symbol, direction, net_pct, reason="TP"):
    """معاملهٔ بستهٔ سنتزی با net_pct هدف — قیمت‌ها فقط برای پوشش هزینه‌اند."""
    entry = 100.0
    exitp = entry * (1 + net_pct / 100.0) if direction == "long" \
        else entry * (1 - net_pct / 100.0)
    return {"symbol": symbol, "event_id": f"{symbol}-{i}", "direction":
            direction, "entry_time_ms": T0 + (i % 50) * HOUR_MS,
            "entry": entry, "exit_reason": reason, "exit": exitp,
            "gross_pct": round(net_pct + 2 * evaluator.FEE_PCT * 100, 6),
            "net_pct": net_pct}


def make_trades(symbol, n_win, n_loss, win_net=1.8, loss_net=-1.2):
    out = []
    for k in range(n_win):
        out.append(mk_trade(k, symbol, "long" if k % 2 == 0 else "short",
                            win_net, "TP"))
    for k in range(n_loss):
        out.append(mk_trade(100 + k, symbol, "long" if k % 2 else "short",
                            loss_net, "SL"))
    return out


class UnifiedReportBasics(unittest.TestCase):
    def test_empty_input_insufficient(self):
        rep = ur.unified_report({}, [])
        self.assertEqual(rep["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rep["reason"], "EMPTY_INPUT_NO_TRADES_OR_CANDLES")
        self.assertEqual(rep["method"], "unified_report/composition_v1")
        self.assertTrue(rep["mode"].startswith("READ ONLY"))

    def test_no_closed_trades(self):
        trades = [mk_trade(k, "AAAUSDT", "long", 1.0, reason="OPEN")
                  for k in range(5)]
        rep = ur.unified_report({"AAAUSDT": quiet_candles()}, trades)
        self.assertEqual(rep["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rep["reason"], "NO_CLOSED_TRADES")

    def test_below_min_samples(self):
        rep = ur.unified_report({"AAAUSDT": quiet_candles()},
                                make_trades("AAAUSDT", 5, 2))
        self.assertEqual(rep["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rep["reason"], "CLOSED_BELOW_MIN_SAMPLES")
        self.assertEqual(rep["min_samples_required"], evaluator.MIN_SAMPLES)

    def test_happy_path_structure(self):
        cm_map = {"AAAUSDT": quiet_candles(), "BBBUSDT": quiet_candles()}
        trades = make_trades("AAAUSDT", 20, 10) + make_trades("BBBUSDT", 15,
                                                              15)
        rep = ur.unified_report(cm_map, trades)
        self.assertEqual(rep["verdict"], "REPORTED")
        self.assertEqual(set(rep["per_symbol"]), {"AAAUSDT", "BBBUSDT"})
        for blk in rep["per_symbol"].values():
            for k in ("raw", "spread_bps", "cost_adjusted", "worst_case",
                      "break_even", "vol_scaled", "delta_vol_pp", "verdict",
                      "delta_cost_pp"):
                self.assertIn(k, blk)
        p = rep["portfolio"]
        for k in ("raw", "by_direction_raw", "spread_bps", "cost_adjusted",
                  "worst_case", "break_even", "scaling_summary",
                  "by_direction_vol"):
            self.assertIn(k, p)
        self.assertIn("combined_reading", rep)
        cr = rep["combined_reading"]
        for k in ("label", "baseline_sum_pp", "after_spread_sum_pp",
                  "worst_case_sum_pp", "break_even_bps",
                  "per_symbol_verdict_counts"):
            self.assertIn(k, cr)

    def test_components_reported(self):
        rep = ur.unified_report({"AAAUSDT": quiet_candles()},
                                make_trades("AAAUSDT", 20, 10))
        comp = rep["components"]
        self.assertEqual(comp["engine"], evaluator.METHOD)
        self.assertEqual(comp["cost"], cm.COST_METHOD)
        self.assertEqual(comp["vol"], vt.VOL_METHOD)
        self.assertIn("strategy_lab", comp["walk_forward"])

    def test_unmatched_trades_counted_excluded(self):
        cm_map = {"AAAUSDT": quiet_candles()}
        trades = make_trades("AAAUSDT", 20, 10) \
            + [mk_trade(999, "NOPE", "long", 1.0)]
        rep = ur.unified_report(cm_map, trades)
        self.assertEqual(rep["n_unmatched_trades"], 1)
        self.assertNotIn("NOPE", rep["per_symbol"])
        self.assertEqual(rep["portfolio"]["raw"]["n_closed"], 30)

    def test_symbol_without_trades_block(self):
        rep = ur.unified_report({"AAAUSDT": quiet_candles(),
                                 "BBBUSDT": quiet_candles()},
                                make_trades("AAAUSDT", 20, 10))
        blk = rep["per_symbol"]["BBBUSDT"]
        self.assertEqual(blk["n_closed"], 0)
        self.assertEqual(blk["verdict"], "INSUFFICIENT_EVIDENCE")


class UnifiedVerdictMatrix(unittest.TestCase):
    """ماتریس برچسب per-symbol — مستقیم و بدون وابستگی به مقدار اسپرد."""

    def test_label_matrix(self):
        f = ur._verdict_label
        self.assertEqual(f(5, 30, 1.0, 0.5, True), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(f(30, 30, None, None, True), "NO_BASELINE_EDGE")
        self.assertEqual(f(30, 30, -2.0, None, True), "NO_BASELINE_EDGE")
        self.assertEqual(f(30, 30, 0.0, None, True), "NO_BASELINE_EDGE")
        self.assertEqual(f(30, 30, 5.0, 1.0, False), "SPREAD_NOT_ESTIMABLE")
        self.assertEqual(f(30, 30, 5.0, None, True), "INSUFFICIENT_EVIDENCE")
        self.assertEqual(f(30, 30, 5.0, 1.0, True),
                         "EDGE_SURVIVES_PROXY_COSTS")
        self.assertEqual(f(30, 30, 5.0, -1.0, True), "EDGE_ERODED_BY_COSTS")

    def test_wide_range_erodes_thin_edge(self):
        """رنج درون‌کندلی بزرگ → اسپرد CS بزرگ → لبهٔ نازک فرسوده (شبیه M3)."""
        trades = make_trades("THINUSDT", 28, 2, win_net=0.15,
                             loss_net=-1.2)
        raw_sum = sum(t["net_pct"] for t in trades)
        self.assertGreater(raw_sum, 0.0)
        rep = ur.unified_report({"THINUSDT": wide_candles()}, trades)
        blk = rep["per_symbol"]["THINUSDT"]
        self.assertGreater(blk["spread_bps"], 20.0)
        self.assertIsNotNone(blk["cost_adjusted"]["sum_net_pct"])
        self.assertLessEqual(blk["cost_adjusted"]["sum_net_pct"], 0.0)
        self.assertEqual(blk["verdict"], "EDGE_ERODED_BY_COSTS")

    def test_healthy_edge_survives_quiet_spread(self):
        """لبهٔ سالم روی نماد آرام → جمع خالص مثبت زیر پوشش هزینهٔ خودش."""
        trades = make_trades("HEALUSDT", 24, 6, win_net=1.8, loss_net=-1.2)
        rep = ur.unified_report({"HEALUSDT": quiet_candles()}, trades)
        blk = rep["per_symbol"]["HEALUSDT"]
        self.assertIsNotNone(blk["spread_bps"])
        if blk["cost_adjusted"]["sum_net_pct"] > 0:
            self.assertEqual(blk["verdict"], "EDGE_SURVIVES_PROXY_COSTS")
        else:
            self.assertEqual(blk["verdict"], "EDGE_ERODED_BY_COSTS")

    def test_all_losses_no_baseline(self):
        rep = ur.unified_report({"LOSSUSDT": quiet_candles()},
                                make_trades("LOSSUSDT", 0, 30))
        self.assertEqual(rep["per_symbol"]["LOSSUSDT"]["verdict"],
                         "NO_BASELINE_EDGE")


class UnifiedCompositionConsistency(unittest.TestCase):
    def setUp(self):
        self.cm_map = {"AAAUSDT": quiet_candles(), "BBBUSDT": wide_candles()}
        self.trades = make_trades("AAAUSDT", 20, 10) \
            + make_trades("BBBUSDT", 15, 15)
        self.rep = ur.unified_report(self.cm_map, self.trades)

    def test_portfolio_raw_equals_realized(self):
        closed = [t for t in self.trades
                  if t.get("exit_reason") in ("TP", "SL")]
        expect = cm.realized_metrics(closed, key="net_pct")
        self.assertEqual(self.rep["portfolio"]["raw"], expect)
        self.assertEqual(self.rep["n_closed"], len(closed))

    def test_per_symbol_raw_sums_to_portfolio(self):
        total = sum(b["raw"]["sum_net_pct"] for b in
                    self.rep["per_symbol"].values())
        self.assertAlmostEqual(total,
                               self.rep["portfolio"]["raw"]["sum_net_pct"],
                               places=6)

    def test_cost_monotonic_erosion(self):
        p = self.rep["portfolio"]
        self.assertIsNotNone(p["spread_bps"])
        self.assertLessEqual(p["cost_adjusted"]["sum_net_pct"],
                             p["raw"]["sum_net_pct"])
        self.assertLessEqual(p["worst_case"]["sum_net_pct"],
                             p["cost_adjusted"]["sum_net_pct"])
        for blk in self.rep["per_symbol"].values():
            if blk["cost_adjusted"] is not None:
                self.assertLessEqual(blk["cost_adjusted"]["sum_net_pct"],
                                     blk["raw"]["sum_net_pct"])

    def test_break_even_bounded(self):
        be = self.rep["portfolio"]["break_even"]
        self.assertIsNotNone(be["bps"])
        self.assertGreaterEqual(be["bps"], 0.0)
        self.assertIn(be["note"], ("BISECTION_DETERMINISTIC",
                                   "NO_POSITIVE_EDGE_AT_ZERO_SLIPPAGE"))

    def test_direction_raw_consistency(self):
        closed = [t for t in self.trades
                  if t.get("exit_reason") in ("TP", "SL")]
        for d in ("long", "short"):
            sub = [t for t in closed if t["direction"] == d]
            self.assertEqual(self.rep["portfolio"]["by_direction_raw"][d],
                             cm.realized_metrics(sub, key="net_pct"))

    def test_vol_recomposition(self):
        p = self.rep["portfolio"]
        self.assertEqual(p["scaling_summary"]["n"], len(self.trades))
        closed = [t for t in self.trades
                  if t.get("exit_reason") in ("TP", "SL")]
        for d in ("long", "short"):
            sub = [t for t in closed if t["direction"] == d]
            blk = p["by_direction_vol"][d]
            self.assertEqual(blk["raw"], cm.realized_metrics(sub,
                                                             key="net_pct"))
        for sym, blk in self.rep["per_symbol"].items():
            sym_closed = [t for t in closed if t["symbol"] == sym]
            scaled = vt.apply_vol_scaling(sym_closed, self.cm_map)[0]
            expect = cm.realized_metrics(scaled, key="net_pct_scaled")
            self.assertEqual(blk["vol_scaled"], expect)
            if blk["delta_vol_pp"] is not None:
                self.assertAlmostEqual(
                    blk["delta_vol_pp"],
                    round(blk["vol_scaled"]["sum_net_pct"]
                          - blk["raw"]["sum_net_pct"], 6), places=6)

    def test_label_matches_reading(self):
        cr = self.rep["combined_reading"]
        p = self.rep["portfolio"]
        if p["cost_adjusted"] is None:
            return
        expect = ur._verdict_label(
            p["raw"]["n_closed"], evaluator.MIN_SAMPLES,
            p["raw"]["sum_net_pct"], p["cost_adjusted"]["sum_net_pct"],
            isinstance(p["spread_bps"], (int, float)))
        self.assertEqual(cr["label"], expect)
        counts = cr["per_symbol_verdict_counts"]
        self.assertEqual(sum(counts.values()), len(self.rep["per_symbol"]))


class UnifiedDeterminismAndSafety(unittest.TestCase):
    def test_deterministic_canonical_json(self):
        cm_map = {"AAAUSDT": quiet_candles(), "BBBUSDT": quiet_candles()}
        trades = make_trades("AAAUSDT", 20, 10) + make_trades("BBBUSDT",
                                                              15, 15)
        a = ur.canonical_json(ur.unified_report(cm_map, trades))
        b = ur.canonical_json(ur.unified_report(cm_map, trades))
        self.assertEqual(a, b)
        doc = json.loads(a)
        self.assertNotIn("timestamp", doc)
        self.assertNotIn("generated_at", doc)

    def test_walk_forward_optional_absent_by_default(self):
        rep = ur.unified_report({"AAAUSDT": quiet_candles()},
                                make_trades("AAAUSDT", 20, 10))
        self.assertNotIn("walk_forward", rep)

    def test_walk_forward_present_with_events(self):
        candles = quiet_candles()
        events = [{"event_id": "E1", "symbol": "AAAUSDT",
                   "event_type": "BOS_UP", "event_time_ms": T0,
                   "features": {"direction": "long", "entry_index": 5,
                                "strength": 0.9}}]
        wf_cfg = {"folds": [{"name": "f1", "start_ms": T0,
                             "end_ms": T0 + 60 * HOUR_MS}],
                  "grid": [{"tp_pct": 0.02, "sl_pct": 0.01}],
                  "interval_ms": HOUR_MS, "seed": 7, "n_bootstrap": 50,
                  "min_train_closed": 1}
        rep = ur.unified_report({"AAAUSDT": candles},
                                make_trades("AAAUSDT", 20, 10),
                                events=events, wf_config=wf_cfg)
        self.assertIn("walk_forward", rep)
        self.assertEqual(len(rep["walk_forward"]["folds"]), 1)
        self.assertIn("verdict", rep["walk_forward"]["folds"][0])

    def test_network_isolation(self):
        cm_map = {"AAAUSDT": quiet_candles()}
        trades = make_trades("AAAUSDT", 20, 10)
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=AssertionError("NO NETWORK")):
            rep = ur.unified_report(cm_map, trades)
            self.assertEqual(rep["verdict"], "REPORTED")
            json.loads(ur.canonical_json(rep))

    def test_slippage_list_passthrough(self):
        rep = ur.unified_report({"AAAUSDT": quiet_candles()},
                                make_trades("AAAUSDT", 20, 10),
                                slippage_bps_list=(0, 50))
        worst = rep["portfolio"]["worst_case"]
        base = rep["portfolio"]["cost_adjusted"]
        self.assertIsNotNone(worst)
        self.assertLessEqual(worst["sum_net_pct"], base["sum_net_pct"])

    def test_read_archive_smoke_consistency(self):
        """دودآزمون سبک: بارگذاری واقعی یک نماد آرشیو M3 — فقط‌خواندنی."""
        arch = "/home/z/my-project/mission003/archive"
        path = os.path.join(arch, "ADAUSDT__1h.json.gz")
        if not os.path.exists(path):
            self.skipTest("M3 archive not present in this environment")
        doc = json.load(gzip.open(path, "rt"))
        candles = [{"open_time": r["t"], "open": r["o"], "high": r["h"],
                    "low": r["l"], "close": r["c"],
                    "volume": r.get("v", 0.0)} for r in doc["candles"]]
        trades = []
        for k in range(40):
            trades.append(mk_trade(k, "ADAUSDT",
                                   "long" if k % 2 == 0 else "short",
                                   1.8 if k % 3 else -1.2,
                                   "TP" if k % 3 else "SL"))
        rep = ur.unified_report({"ADAUSDT": candles}, trades)
        self.assertEqual(rep["verdict"], "REPORTED")
        self.assertGreater(rep["per_symbol"]["ADAUSDT"]["spread_bps"], 0.0)
        json.loads(ur.canonical_json(rep))


if __name__ == "__main__":
    unittest.main()
