# MARI — آزمون‌های آفلاین vol_target (اولویت P3 EXECUTION ORDER 001)
# صفر شبکه؛ صفر نوشتن؛ قطعی. پوشش: ضدنشت، ریاضی مقیاس، سقف/کف، پرچم‌ها،
# تفکیک جهت، حکم‌ها، بازتولیدپذیری، ایزوله‌شبکه.

import os
import sys
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from fleet_loader import load_fleet  # noqa: E402

fleet = load_fleet()
vt = fleet.vol_target
quant = fleet.quant
evaluator = fleet.evaluator

HOUR_MS = 3_600_000
T0 = 1_700_000_000_000


def candle(i, close, base=100.0):
    return {"open_time": T0 + i * HOUR_MS, "open": base, "high": base + 1.0,
            "low": base - 1.0, "close": close, "volume": 10.0}


def quiet_candles(n=60):
    """بازده کوچک ±۰٫۱٪ → σ کم → مقیاس سقف می‌خورد."""
    return [candle(i, 100.0 * (1 + (0.001 if i % 2 else -0.001)))
            for i in range(n)]


def wild_candles(n=60):
    """بازده بزرگ ±۵٪ → σ زیاد → مقیاس کف می‌خورد."""
    return [candle(i, 100.0 * (1 + (0.05 if i % 2 else -0.05)))
            for i in range(n)]


def mk_trade(i, symbol, direction, entry, exit_price, reason="TP"):
    long_ = direction == "long"
    gross = (exit_price - entry) / entry if long_ \
        else (entry - exit_price) / entry
    net = gross - 2 * evaluator.FEE_PCT
    return {"symbol": symbol, "event_id": f"E{i}", "direction": direction,
            "entry_time_ms": T0 + i * HOUR_MS, "entry": entry,
            "exit_reason": reason, "exit": exit_price,
            "gross_pct": round(gross * 100, 6), "net_pct": round(net * 100, 6),
            "mfe_pct": 0.0, "mae_pct": 0.0, "hold_candles": 3}


def mixed(n=30, symbol="AAAUSDT", start=0):
    """نیمه TP لانگ، نیمه SL شورت — هر دو جهت؛ start برای تاریخچهٔ کافی σ."""
    out = []
    for i in range(start, start + n):
        if i % 2 == 0:
            out.append(mk_trade(i, symbol, "long", 100.0, 102.0, "TP"))
        else:
            out.append(mk_trade(i, symbol, "short", 100.0, 101.0, "SL"))
    return out


class TestEntryVolScale(unittest.TestCase):

    def test_expected_scale_matches_quant_ewma(self):
        cs = quiet_candles()
        j = 50
        rets = [b["close"] / a["close"] - 1.0
                for a, b in zip(cs[j - 24:j], cs[j - 24 + 1:j])]
        sigma = quant.ewma_volatility(rets)
        expected = min((0.8 / 100.0) / sigma, 2.0)
        sc = vt.entry_vol_scale(cs, j)
        self.assertEqual(sc["flag"], "UPSCALED_CAPPED")
        self.assertAlmostEqual(sc["scale"], round(expected, 6), places=6)

    def test_clip_bounds(self):
        low = vt.entry_vol_scale(quiet_candles(), 50)["scale"]
        high = vt.entry_vol_scale(wild_candles(), 50)
        self.assertEqual(low, 2.0)
        self.assertEqual(high["flag"], "DOWNSCALED")
        self.assertLessEqual(high["scale"], 0.5)  # ±۵٪ → σ ≫ هدف ۰٫۸٪

    def test_insufficient_history_flag(self):
        cs = quiet_candles()
        sc = vt.entry_vol_scale(cs, 3)
        self.assertEqual(sc["flag"], "UNSCALED_INSUFFICIENT_HISTORY")
        self.assertIsNone(sc["scale"])
        flat = [candle(i, 100.0) for i in range(40)]
        zv = vt.entry_vol_scale(flat, 30)
        self.assertEqual(zv["flag"], "ZERO_VOL_CAPPED")
        self.assertEqual(zv["scale"], 2.0)


class TestAntiLookahead(unittest.TestCase):

    def test_early_entries_identical_on_truncated_series(self):
        cm = {"AAAUSDT": quiet_candles(60)}
        ts = mixed(20)  # ورودها در ایندهای ۰..۱۹ (کندل‌های ۱..۲۰)
        full, _ = vt.apply_vol_scaling(ts, cm)
        cut = {"AAAUSDT": [c for c in cm["AAAUSDT"]
                           if c["open_time"] < T0 + 25 * HOUR_MS]}
        part, _ = vt.apply_vol_scaling(ts, cut)
        for a, b in zip(full, part):
            self.assertEqual(a["scaling_flag"], b["scaling_flag"])
            self.assertEqual(a["net_pct_scaled"], b["net_pct_scaled"])


class TestScalingMath(unittest.TestCase):

    def test_net_scaled_exact_and_flags_counted(self):
        cm = {"AAAUSDT": wild_candles(60)}
        ts = mixed(10, start=30)  # ایندکس ورود ۳۰..۳۹ ← تاریخچهٔ کافی
        adj, summary = vt.apply_vol_scaling(ts, cm)
        for a, t in zip(adj, ts):
            self.assertAlmostEqual(
                a["net_pct_scaled"],
                round(a["scale"] * t["net_pct"], 6) if a["scale"] is not None
                else t["net_pct"], places=6)
        self.assertEqual(summary["n"], 10)
        self.assertEqual(summary["n_scaled"], 10)

    def test_target_above_cap_reproduces_raw(self):
        cm = {"AAAUSDT": quiet_candles(60)}
        ts = mixed(10, start=30)
        adj, summary = vt.apply_vol_scaling(
            ts, cm, target_vol_pct=10_000.0, max_scale=1.0)
        self.assertEqual(summary["n_scaled"], 10)
        for a, t in zip(adj, ts):
            self.assertEqual(a["scale"], 1.0)
            self.assertEqual(a["net_pct_scaled"], t["net_pct"])

    def test_unknown_symbol_flagged(self):
        cm = {"AAAUSDT": quiet_candles(60)}
        ts = [mk_trade(5, "ZZZUSDT", "long", 100.0, 102.0, "TP")]
        _, summary = vt.apply_vol_scaling(ts, cm)
        self.assertEqual(summary["n_unscaled"], 1)
        self.assertIn("UNSCALED_ENTRY_NOT_FOUND", summary["flag_counts"])


class TestDirectionReport(unittest.TestCase):

    def test_direction_sums_consistent(self):
        cm = {"AAAUSDT": wild_candles(60)}
        ts = mixed(30)
        rep = vt.vol_report(cm, ts)
        self.assertEqual(rep["verdict"], "REPORTED")
        self.assertIn("long", rep["by_direction"])
        self.assertIn("short", rep["by_direction"])
        lb = rep["by_direction"]["long"]
        self.assertEqual(lb["raw"]["n_closed"] + rep["by_direction"]["short"]
                         ["raw"]["n_closed"], 30)
        delta = lb["scaled"]["sum_net_pct"] - lb["raw"]["sum_net_pct"]
        self.assertAlmostEqual(lb["delta_sum_net_pp"], round(delta, 6),
                               places=6)

    def test_verdict_gate_on_closed_count(self):
        cm = {"AAAUSDT": quiet_candles(60)}
        rep = vt.vol_report(cm, mixed(5))
        self.assertEqual(rep["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rep["reason"], "CLOSED_BELOW_MIN_SAMPLES")

    def test_empty_input_refused(self):
        rep = vt.vol_report({}, [])
        self.assertEqual(rep["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rep["reason"], "EMPTY_INPUT_NO_TRADES_OR_CANDLES")


class TestDeterminismAndIsolation(unittest.TestCase):

    def test_two_runs_byte_identical(self):
        cm = {"AAAUSDT": wild_candles(60), "BBBUSDT": quiet_candles(60)}
        ts = mixed(30) + mixed(10, "BBBUSDT")
        r1 = vt.vol_report(cm, ts)
        r2 = vt.vol_report(cm, ts)
        self.assertEqual(vt.canonical_json(r1), vt.canonical_json(r2))

    def test_no_network_calls(self):
        cm = {"AAAUSDT": quiet_candles(60)}
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=RuntimeError("NETWORK_FORBIDDEN")):
            rep = vt.vol_report(cm, mixed(30))
        self.assertIn("by_direction", rep)


if __name__ == "__main__":
    unittest.main()
