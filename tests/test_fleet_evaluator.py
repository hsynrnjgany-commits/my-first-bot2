# MARI — آزمون آفلاین ارزیاب مستقل (بند ۵) + خوشهٔ K + قفل ایمنی سراسری ناوگان

import glob
import os
import re
import unittest

from fleet_loader import load_fleet

fleet = load_fleet()
evaluator = fleet.evaluator
risk = fleet.risk
contract = fleet.contract

FLEET_SRC = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src", "fleet")


def mk(i, o, h, l, c, v=10.0):
    return {"open_time": 1_700_000_000_000 + i * 3_600_000,
            "open": o, "high": h, "low": l, "close": c, "volume": v}


def bos_event(index, direction):
    return contract.make_message(
        cluster_id="D", symbol="TESTUSDT",
        event_type="BOS_BULLISH" if direction == "long" else "BOS_BEARISH",
        event_time_ms=mk(index, 0, 0, 0, 0)["open_time"],
        data_asof_ms=mk(index, 0, 0, 0, 0)["open_time"],
        features={"direction": direction, "entry_index": index})


class TestSimulator(unittest.TestCase):

    def test_tp_hit_exact_math(self):
        candles = [mk(0, 100, 100.5, 99.5, 100),
                   mk(1, 100, 101, 99.8, 100.5),      # ورود در اپن ۱۰۰
                   mk(2, 100.5, 102.5, 100, 102)]     # TP 102 لمس
        trades = evaluator.simulate_trades(
            candles, [bos_event(0, "long")], symbol="TESTUSDT")
        self.assertEqual(trades[0]["exit_reason"], "TP")
        self.assertEqual(trades[0]["gross_pct"], 2.0)
        self.assertEqual(trades[0]["net_pct"], 1.8)   # ۲٪ − ۰٫۲٪ کارمزد
        self.assertEqual(trades[0]["mfe_pct"], 2.5)
        self.assertEqual(trades[0]["mae_pct"], 0.2)

    def test_conservative_tie_rule_sl_first(self):
        candles = [mk(0, 100, 100.5, 99.5, 100),
                   mk(1, 100, 102.5, 98, 99)]          # TP و SL هم‌زمان
        trades = evaluator.simulate_trades(
            candles, [bos_event(0, "long")], symbol="TESTUSDT")
        self.assertEqual(trades[0]["exit_reason"], "SL")
        self.assertEqual(trades[0]["net_pct"], -1.2)   # −۱٪ − ۰٫۲٪

    def test_short_direction(self):
        candles = [mk(0, 100, 100.5, 99.5, 100),
                   mk(1, 100, 100.2, 99.4, 99.5),
                   mk(2, 99.5, 99.6, 97.8, 98)]        # SL کوتاه = ۱۰۱؟ خیر: ۹۹ → TP کوتاه ۹۸
        trades = evaluator.simulate_trades(
            candles, [bos_event(0, "short")], symbol="TESTUSDT")
        self.assertEqual(trades[0]["exit_reason"], "TP")
        self.assertEqual(trades[0]["net_pct"], 1.8)

    def test_open_exit_is_honest(self):
        candles = [mk(0, 100, 100.5, 99.5, 100), mk(1, 100, 100.4, 99.6, 100)]
        trades = evaluator.simulate_trades(
            candles, [bos_event(0, "long")], symbol="TESTUSDT")
        self.assertEqual(trades[0]["exit_reason"], "OPEN")


class TestEvaluate(unittest.TestCase):

    def synthetic_trades(self, n_tp, n_sl):
        trades = []
        for _ in range(n_tp):
            trades.append({"symbol": "TESTUSDT", "event_id": "x",
                           "direction": "long", "entry_time_ms": 1,
                           "entry": 100, "exit_reason": "TP", "exit": 102,
                           "gross_pct": 2.0, "net_pct": 1.8,
                           "mfe_pct": 2.5, "mae_pct": 0.2,
                           "hold_candles": 3})
        for _ in range(n_sl):
            trades.append({"symbol": "TESTUSDT", "event_id": "y",
                           "direction": "long", "entry_time_ms": 2,
                           "entry": 100, "exit_reason": "SL", "exit": 99,
                           "gross_pct": -1.0, "net_pct": -1.2,
                           "mfe_pct": 0.5, "mae_pct": 1.0,
                           "hold_candles": 2})
        return trades

    def test_insufficient_evidence_below_threshold(self):
        result = evaluator.evaluate(self.synthetic_trades(2, 3))
        self.assertEqual(result["validation_status"], "INSUFFICIENT_EVIDENCE")

    def test_exact_metrics_at_threshold(self):
        result = evaluator.evaluate(self.synthetic_trades(12, 18))
        self.assertEqual(result["n"], 30)
        self.assertEqual(result["validation_status"], "UNVALIDATED")
        self.assertEqual(result["win_rate"], 0.4)
        self.assertEqual(result["profit_factor"], 1.0)  # ۲۱٫۶ / ۲۱٫۶
        self.assertEqual(result["exit_mix"], {"TP": 12, "SL": 18, "OPEN": 0})

    def test_no_losses_reported_honestly(self):
        result = evaluator.evaluate(self.synthetic_trades(30, 0))
        self.assertEqual(result["profit_factor"], "UNDEFINED_NO_LOSSES")

    def test_evaluation_message_wraps_contract(self):
        msg = evaluator.evaluation_message(
            "TESTUSDT", evaluator.evaluate(self.synthetic_trades(2, 2)),
            data_asof_ms=1)
        self.assertEqual(msg["cluster_id"], "A")
        self.assertEqual(msg["event_type"], "EVALUATION_REPORT")
        self.assertEqual(msg["validation_status"], "INSUFFICIENT_EVIDENCE")


class TestRiskCluster(unittest.TestCase):

    def test_max_drawdown_exact(self):
        dd = risk.max_drawdown([100, 120, 90, 110])
        self.assertAlmostEqual(dd["max_dd"], 0.25, places=6)
        self.assertEqual(dd["peak_index"], 1)
        self.assertEqual(dd["trough_index"], 2)

    def test_hhi_concentration(self):
        self.assertAlmostEqual(risk.hhi([0.5, 0.5]), 0.5, places=6)
        self.assertAlmostEqual(risk.hhi([1.0]), 1.0, places=6)
        self.assertAlmostEqual(risk.hhi([0.25] * 4), 0.25, places=6)

    def test_pearson_known_and_honest_none(self):
        self.assertAlmostEqual(risk.pearson([1, 2, 3], [2, 4, 6]), 1.0,
                               places=6)
        self.assertIsNone(risk.pearson([1, 1, 1], [1, 2, 3]))
        self.assertIsNone(risk.pearson([1], [1]))

    def test_concentration_top_share(self):
        trades = [{"symbol": "A", "net_pct": 3.0},
                  {"symbol": "A", "net_pct": 1.0},
                  {"symbol": "B", "net_pct": -1.0}]
        conc = risk.concentration(trades)
        self.assertEqual(conc["top_symbol"], "A")
        self.assertAlmostEqual(conc["top_share"], 0.8, places=4)


class TestFleetSafetyLock(unittest.TestCase):
    """بند ۲ و ۸ گزارش: وضعیت قفل سفارش واقعی — با آزمون ثابت نگه داشته می‌شود."""

    FORBIDDEN_PATTERNS = (
        re.compile(r"method\s*=\s*['\"](POST|PUT|DELETE)"),
        re.compile(r"urlopen\([^)]*data\s*="),
        re.compile(r"\.data\s*=\s*[^=]"),
    )

    def test_no_write_methods_anywhere_in_fleet(self):
        files = sorted(glob.glob(os.path.join(FLEET_SRC, "*.py")))
        self.assertTrue(len(files) >= 12, "فایل‌های ناوگان ناقص دیده شدند")
        for path in files:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            for pattern in self.FORBIDDEN_PATTERNS:
                self.assertIsNone(pattern.search(text),
                                  f"الگوی ممنوع در {os.path.basename(path)}")

    def test_safety_flags_exist(self):
        self.assertTrue(fleet.PAPER_ONLY)
        self.assertTrue(fleet.READ_ONLY)
        self.assertTrue(fleet.ORDERS_DISABLED)
        self.assertIn("NO_LIVE_ORDERS", contract.SAFETY_MODE)


if __name__ == "__main__":
    unittest.main()
