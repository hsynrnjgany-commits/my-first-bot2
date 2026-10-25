# MARI — آزمون‌های آفلاین strategy_lab (بخش ۷ EXECUTION ORDER 001)
# صفر شبکه؛ صفر نوشتن؛ قطعی با بذر. هفت آزمون پذیرش + مرزهای ورودی.

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
lab = fleet.strategy_lab
evaluator = fleet.evaluator
contract = fleet.contract

HOUR_MS = 3_600_000
T0 = 1_700_000_000_000


def mk(i, close, v=10.0):
    base = 100.0
    return {"open_time": T0 + i * HOUR_MS, "open": base, "high": base + 3.5,
            "low": base - 3.5, "close": close, "volume": v}


def candles(n=120):
    # نوسان ±۳٪ → TP ۲٪ و SL ۱٪ هر دو در کندل‌های نخست لمس می‌شوند
    out = []
    for i in range(n):
        close = 100.0 + (3.0 if i % 2 == 0 else -3.0)
        out.append(mk(i, close))
    return out


def bos_event(index, direction, symbol):
    return contract.make_message(
        cluster_id="D", symbol=symbol,
        event_type="BOS_BULLISH" if direction == "long" else "BOS_BEARISH",
        event_time_ms=T0 + index * HOUR_MS,
        data_asof_ms=T0 + index * HOUR_MS,
        features={"direction": direction, "entry_index": index})


def lab_config(**over):
    cfg = {
        "interval_ms": HOUR_MS,
        "folds": [
            {"name": "F1", "start_ms": T0 + 10 * HOUR_MS,
             "end_ms": T0 + 60 * HOUR_MS},
            {"name": "F2", "start_ms": T0 + 60 * HOUR_MS,
             "end_ms": T0 + 110 * HOUR_MS},
        ],
        "grid": [{"tp_pct": 0.02, "sl_pct": 0.01},
                 {"tp_pct": 0.04, "sl_pct": 0.02}],
        "min_train_closed": 5,
        "seed": 20261025,
        "n_bootstrap": 500,
    }
    cfg.update(over)
    return cfg


def lab_input():
    cm = {"AAAUSDT": candles(), "BBBUSDT": candles()}
    evs = [bos_event(5, "long", "AAAUSDT"), bos_event(20, "short", "AAAUSDT"),
           bos_event(35, "long", "AAAUSDT"), bos_event(70, "long", "AAAUSDT"),
           bos_event(12, "short", "BBBUSDT"), bos_event(40, "long", "BBBUSDT"),
           bos_event(75, "short", "BBBUSDT")]
    return cm, evs


class TestNoLookahead(unittest.TestCase):
    """فولد اول باید با کندل‌های کامل و بریده‌شده در مرز فولد یکسان باشد."""

    def test_fold1_unchanged_without_future_data(self):
        cm, evs = lab_input()
        full = lab.anchored_walk_forward(cm, evs, lab_config())
        horizon = T0 + 62 * HOUR_MS  # مرز فولد ۱ + قد کفایت خروج
        cut = {s: [c for c in cs if c["open_time"] + HOUR_MS <= horizon]
               for s, cs in cm.items()}
        cut_evs = [e for e in evs
                   if e["features"]["entry_index"] * HOUR_MS + T0 < horizon]
        part = lab.anchored_walk_forward(cut, cut_evs, lab_config())
        self.assertEqual(full["folds"][0]["metrics"], part["folds"][0]["metrics"])
        self.assertEqual(full["folds"][0]["selection"]["train_pf_range"],
                         part["folds"][0]["selection"]["train_pf_range"])


class TestDeterminism(unittest.TestCase):

    def test_two_runs_byte_identical(self):
        cm, evs = lab_input()
        r1 = lab.anchored_walk_forward(cm, evs, lab_config())
        r2 = lab.anchored_walk_forward(cm, evs, lab_config())
        self.assertEqual(lab.canonical_json(r1), lab.canonical_json(r2))


class TestParamsAndTieRule(unittest.TestCase):

    def test_sl_first_tie_and_params_passed_through(self):
        cm, evs = lab_input()
        rep = lab.anchored_walk_forward(cm, evs, lab_config())
        f1 = rep["folds"][0]["metrics"]
        self.assertGreater(f1["closed"], 0)
        # کندل‌های آزمون هم TP (۱۴۰+) و هم SL (۹۶−) را لمس می‌کنند؛ قاعدهٔ
        # محافظه‌کارانهٔ SL-first از شبیه‌ساز باید عیناً پابرجا باشد
        direct = evaluator.simulate_trades(
            [mk(0, 100.0), mk(1, 103.2)], [bos_event(0, "long", "XUSDT")],
            symbol="XUSDT", tp_pct=0.02, sl_pct=0.01)
        self.assertEqual(direct[0]["exit_reason"], "SL")
        self.assertEqual(direct[0]["net_pct"], -1.2)  # −۱٪ − ۰٫۲٪ کارمزد
        self.assertEqual(rep["grid"], lab_config()["grid"])


class TestSelectionControl(unittest.TestCase):
    """DSR-lite: واریانس صفر → None؛ پراکندگی بیشتر → سقف انتظاری بالاتر."""

    def test_expected_max_sr_behavior(self):
        self.assertIsNone(lab.expected_max_sr([1.0, 1.0]))
        low = lab.expected_max_sr([0.9, 1.0, 1.1])
        high = lab.expected_max_sr([0.1, 1.0, 1.1])
        self.assertGreater(low, 0.0)
        self.assertGreater(high, low)

    def test_fold_reports_selection_control(self):
        cm, evs = lab_input()
        rep = lab.anchored_walk_forward(cm, evs, lab_config())
        for f in rep["folds"]:
            sc = f["selection_control"]
            self.assertIn("expected_max_pf_under_n_trials", sc)
            self.assertIn("best_train_pf", sc)


class TestFrozenGuard(unittest.TestCase):

    def test_all_stale_refused(self):
        cm, evs = lab_input()
        stale_cm = {s: [{"open_time": T0 - 40 * HOUR_MS, "open": 100.0,
                         "high": 101.0, "low": 99.0, "close": 100.0,
                         "volume": 1.0}] for s in cm}
        cfg = lab_config(now_ms=T0)
        rep = lab.anchored_walk_forward(stale_cm, evs, cfg)
        self.assertEqual(rep["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rep["reason"], "STALE_FROZEN_SERIES_ALL_SYMBOLS")


class TestConfidenceIntervals(unittest.TestCase):

    def test_wilson_contains_point(self):
        lo, hi = lab.wilson_ci(3, 10)
        self.assertLessEqual(lo, 0.3)
        self.assertGreaterEqual(hi, 0.3)
        self.assertIsNone(lab.wilson_ci(0, 0))

    def test_bootstrap_zero_mean_coverage(self):
        nets = [1.0, -1.0] * 10  # میانگین صفر
        covered = 0
        for s in range(100):
            lo, hi = lab.bootstrap_avg_ci(nets, seed=s, n_boot=300)
            if lo <= 0.0 <= hi:
                covered += 1
        self.assertGreaterEqual(covered, 90)  # هدف نظری ≈۹۵٪؛ کف پذیرش ۹۰٪


class TestIsolation(unittest.TestCase):
    """ماژول نباید هیچ شبکه‌ای باز کند — حتی زیر قلابِ پرتاب‌کننده."""

    def test_no_network_calls(self):
        cm, evs = lab_input()
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=RuntimeError("NETWORK_FORBIDDEN")):
            rep = lab.anchored_walk_forward(cm, evs, lab_config())
        self.assertEqual(len(rep["folds"]), 2)

    def test_invalid_fold_boundaries_refused(self):
        cm, evs = lab_input()
        bad = lab_config(folds=[{"name": "X", "start_ms": T0 + 50 * HOUR_MS,
                                 "end_ms": T0 + 50 * HOUR_MS}])
        rep = lab.anchored_walk_forward(cm, evs, bad)
        self.assertEqual(rep["reason"], "INVALID_FOLD_BOUNDARIES")


if __name__ == "__main__":
    unittest.main()
