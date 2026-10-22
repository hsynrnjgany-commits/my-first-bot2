# MARI — آزمون آفلاین آزمایشگاه کمّی (خوشهٔ M) + ارزیاب v2 + تجزیهٔ منابع نو

import math
import unittest

from fleet_loader import load_fleet

fleet = load_fleet()
quant = fleet.quant
sources = fleet.sources
evaluator = fleet.evaluator


def mk(i, o, h, l, c, v=10.0):
    return {"open_time": 1_700_000_000_000 + i * 3_600_000,
            "open": o, "high": h, "low": l, "close": c, "volume": v}


class TestHurst(unittest.TestCase):

    def test_trending_above_reverting(self):
        # روند خالص: بازده‌های مثبت رشدی → H بالا
        trending = [0.001 * (1 + 0.02 * i) for i in range(120)]
        # بازگشت به میانگین: نوسان حول صفر (سینوسی)
        reverting = [0.01 * math.sin(i / 3.0) for i in range(120)]
        h_t = quant.hurst_exponent(trending)
        h_r = quant.hurst_exponent(reverting)
        self.assertIsNotNone(h_t)
        self.assertIsNotNone(h_r)
        self.assertGreater(h_t, h_r)
        self.assertTrue(0.0 < h_t < 1.5)
        self.assertTrue(0.0 < h_r < 1.5)

    def test_short_series_none(self):
        self.assertIsNone(quant.hurst_exponent([0.001] * 5))


class TestEwmaVol(unittest.TestCase):

    def test_exact_small_case(self):
        returns = [0.01] * 5 + [0.02]
        # var0 = 0.0001؛ var1 = 0.94*0.0001 + 0.06*0.0004 = 0.000118
        sigma = quant.ewma_volatility(returns)
        self.assertAlmostEqual(sigma, math.sqrt(0.000118), places=8)

    def test_short_none(self):
        self.assertIsNone(quant.ewma_volatility([0.01] * 4))


class TestReturnZ(unittest.TestCase):

    def test_extreme_positive_detected(self):
        hist = [0.001 if i % 2 else -0.001 for i in range(50)]
        z = quant.return_zscore(hist + [0.05])
        self.assertIsNotNone(z)
        self.assertGreater(z, 2.0)

    def test_normal_return_none(self):
        hist = [0.001 if i % 2 else -0.001 for i in range(50)]
        self.assertIsNone(quant.return_zscore(hist + [0.001]))

    def test_zero_variance_none(self):
        self.assertIsNone(quant.return_zscore([0.001] * 50 + [0.05]))


class TestAtrPercentile(unittest.TestCase):

    def test_rising_volatility_high_percentile(self):
        candles = []
        for i in range(40):
            width = 1.0 + i * 0.2  # TR به‌مرور بزرگ می‌شود
            candles.append(mk(i, 100, 100 + width, 100 - width, 100))
        p = quant.atr_percentile(candles)
        self.assertIsNotNone(p)
        self.assertGreaterEqual(p, 0.95)


class TestCointegrationLite(unittest.TestCase):

    def test_constructed_pair_detected(self):
        n = 80
        x = [100.0 + i for i in range(n)]
        # resid میرای کوچک (φ≈0.9) — نیم‌عمر ≈ ۶٫۶ کندل؛ کوچک تا رگرسیون را نبلعد
        y = [2.0 * math.log(xx) + 0.5 + (0.05 * 0.9 ** i) for i, xx in
             enumerate(x)]
        lx = [math.log(xx) for xx in x]
        fit = quant.cointegration_lite(y, lx)
        self.assertIsNotNone(fit)
        # β نزدیک ۲ است ولی بایاس OLS از همبستگی باقیماندهٔ میرا با x مجاز است
        self.assertTrue(1.9 <= fit["beta"] <= 2.1)
        self.assertTrue(2.0 <= fit["half_life_candles"] <= 15.0)

    def test_flat_residual_rejected(self):
        n = 80
        x = [100.0 + i for i in range(n)]
        y = [2.0 * math.log(xx) + 0.5 for xx in x]  # resid = 0
        fit = quant.cointegration_lite(y, [math.log(xx) for xx in x])
        self.assertIsNone(fit)  # σ=۰ → هیچ عددی جعل نمی‌شود

    def test_short_series_rejected(self):
        fit = quant.cointegration_lite([1.0] * 30, [1.0] * 30)
        self.assertIsNone(fit)


class TestQuantAnalyzeMulti(unittest.TestCase):

    def build_map(self):
        n = 70
        base_a = [mk(i, 100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(n)]
        # BBB = ۲×AAA با باقیماندهٔ لگاریتمی میرا (φ≈0.9) — نه صفر، نه سفید
        base_b = []
        for i in range(n):
            cb = (201.0 + 2 * i) * (1.0 + 0.1 * 0.9 ** i)
            base_b.append(mk(i, cb - 1, cb + 1, cb - 2, cb))
        base_c = [mk(i, 50, 55, 45, 50 + (2 if i % 3 else -2))
                  for i in range(n)]
        return {"AAAUSDT": base_a, "BBBUSDT": base_b, "CCCUSDT": base_c}

    def test_events_follow_contract(self):
        cmap = self.build_map()
        events = quant.analyze_multi(cmap, timeframe="1h",
                                     data_asof_ms=1_700_000_070_000)
        for e in events:
            self.assertEqual(e["cluster_id"], "M")
            self.assertIn(e["validation_status"], ("OBSERVED", "HYPOTHESIS"))
            self.assertIn("PAPER_ONLY", e["safety"]["mode"])
        # با این حجم نمونه، VOLATILITY_REGIME برای همهٔ نمادها باید بیاید
        vol = [e for e in events if e["event_type"] == "VOLATILITY_REGIME"]
        self.assertEqual(len(vol), 3)

    def test_pair_candidate_flagged_heuristic(self):
        cmap = self.build_map()  # BBBB ≈ ۲×AAA با میرای کوچک → جفت درون‌نمونه
        events = quant.analyze_multi(cmap, timeframe="1h",
                                     data_asof_ms=1_700_000_070_000)
        pairs = [e for e in events if e["event_type"] == "PAIR_CANDIDATE"]
        self.assertTrue(len(pairs) >= 1)
        self.assertEqual(pairs[0]["features"]["method_label"], "HEURISTIC")
        self.assertEqual(pairs[0]["validation_status"], "HYPOTHESIS")


class TestEvaluatorV2(unittest.TestCase):

    def test_t_stat_exact(self):
        nets = [1.0, -1.0, 1.0, -1.0, 1.0]
        # mean=0.2، std نمونه≈1.0954، t=0.2/(1.0954/√5)=0.4082
        self.assertAlmostEqual(evaluator.t_stat(nets), 0.4082, places=3)
        self.assertIsNone(evaluator.t_stat([1.0]))
        self.assertIsNone(evaluator.t_stat([2.0, 2.0]))

    def test_kelly_exact(self):
        nets = [1.8] * 5 + [-1.2] * 5  # p=0.5، b=1.5 → f=(0.75−0.5)/1.5
        self.assertAlmostEqual(evaluator.kelly_fraction_paper(nets),
                               0.1667, places=3)
        self.assertIsNone(evaluator.kelly_fraction_paper([1.0] * 5))

    def test_walk_forward_insufficient_then_computed(self):
        few = [{"net_pct": 1.0, "entry_time_ms": i} for i in range(10)]
        self.assertEqual(evaluator.walk_forward(few)["status"],
                         "INSUFFICIENT_EVIDENCE")
        many = []
        for i in range(20):
            many.append({"net_pct": 2.0 if i < 10 else -1.0,
                         "entry_time_ms": i})
        wf = evaluator.walk_forward(many)
        self.assertEqual(wf["status"], "COMPUTED")
        self.assertEqual(len(wf["windows"]), 4)
        self.assertEqual(wf["positive_windows"], 2)

    def test_evaluate_includes_new_fields(self):
        trades = [{"symbol": "T", "net_pct": 1.8, "mfe_pct": 2.5,
                   "mae_pct": 0.2, "entry_time_ms": 1, "exit_reason": "TP"}
                  for _ in range(30)]
        result = evaluator.evaluate(trades)
        self.assertIn("t_stat", result)
        self.assertIn("kelly_fraction_paper", result)
        self.assertIn("walk_forward", result)
        self.assertEqual(result["validation_status"], "UNVALIDATED")


class TestNewSourceParsers(unittest.TestCase):

    def test_bybit_parse_descending_input(self):
        payload = {"result": {"list": [
            ["1700000300000", "102", "103", "101", "102.5", "12", "1000"],
            ["1700000000000", "100", "101", "99", "101", "10", "900"],
        ]}}
        candles = sources.parse_bybit_klines(payload)
        self.assertEqual(candles[0]["open_time"], 1700000000000)
        self.assertEqual(candles[-1]["close"], 102.5)
        self.assertEqual(len(candles), 2)

    def test_okx_parse_filters_unconfirmed(self):
        payload = {"data": [
            ["1700000360000", "102", "103", "101", "102.5", "12", "x", "y", "0"],
            ["1700000000000", "100", "101", "99", "101", "10", "x", "y", "1"],
        ]}
        candles = sources.parse_okx_klines(payload)
        self.assertEqual(len(candles), 1)  # کندل ناتمام حذف شد
        self.assertEqual(candles[0]["open_time"], 1700000000000)

    def test_okx_symbol_conversion(self):
        self.assertEqual(sources.to_okx_inst("BTCUSDT"), "BTC-USDT")
        self.assertIsNone(sources.to_okx_inst("BTCUSD"))
        self.assertIsNone(sources.to_okx_inst("USDT"))


if __name__ == "__main__":
    unittest.main()
