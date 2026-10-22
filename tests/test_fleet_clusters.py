# MARI — آزمون آفلاین خوشه‌های تخصصی D/E/C/F/G/H (بدون شبکه، سری‌های ساختگی معلوم)

import unittest

from fleet_loader import load_fleet

fleet = load_fleet()
structure = fleet.structure
volume = fleet.volume
liquidity = fleet.liquidity
sessions = fleet.sessions
derivatives = fleet.derivatives
crossmarket = fleet.crossmarket

HOUR = 3_600_000
T0 = 1_700_000_000_000


def mk(i, o, h, l, c, v=10.0):
    return {"open_time": T0 + i * HOUR, "open": o, "high": h, "low": l,
            "close": c, "volume": v}


def asof(candles):
    return candles[-1]["open_time"]


class TestStructureCluster(unittest.TestCase):
    """سری دست‌ساز: قلهٔ ۱۱۰ در i=3، افت، و شکست کلوز ۱۱۱ در کندل ۲۴."""

    def build(self):
        c = []
        c.append(mk(0, 100, 101, 99.5, 100.5))
        c.append(mk(1, 100.5, 102, 100, 101.5))
        c.append(mk(2, 101.5, 105, 101, 104))
        c.append(mk(3, 104, 110, 103.5, 108))          # پیوت HIGH = 110
        decline_highs = [104, 100, 96, 93, 91, 90, 90, 89, 89, 89, 89]
        price = 108.0
        for k, h in enumerate(decline_highs, start=4):
            o = min(price, h)
            price = h - 2
            c.append(mk(k, o, h, price - 0.5, price))
        for k in range(15, 21):                        # کف راکد — پیوت جدید نه
            c.append(mk(k, 87, 88, 86.5, 87.5))
        surge = [(87.5, 96), (96, 100), (100, 105), (105, 111)]
        for k, (o, cl) in enumerate(surge, start=21):  # کلوز ۱۱۱ > ۱۱۰ → BOS
            c.append(mk(k, o, cl + 0.5, o - 0.5, cl))
        return c

    def test_bos_detected_on_breaking_close(self):
        candles = self.build()
        events = structure.analyze(candles, symbol="BTCUSDT",
                                   exchange="toobit", timeframe="1h",
                                   data_asof_ms=asof(candles))
        bos = [e for e in events if e["event_type"] == "BOS_BULLISH"]
        self.assertEqual(len(bos), 1)
        self.assertEqual(bos[0]["features"]["broken_level"], 110.0)
        self.assertEqual(bos[0]["features"]["direction"], "long")
        self.assertEqual(bos[0]["features"]["entry_index"], 24)
        self.assertEqual(bos[0]["validation_status"], "HYPOTHESIS")

    def test_no_lookahead(self):
        candles = self.build()
        events = structure.analyze(candles, symbol="BTCUSDT",
                                   exchange="toobit", timeframe="1h",
                                   data_asof_ms=asof(candles))
        for e in events:
            self.assertLessEqual(e["event_time_ms"], asof(candles))

    def test_bearish_bos_choch_flagged(self):
        # آینهٔ نزولی: کف ۹۰ در i=3 و شکست کلوز ۸۹
        c = [mk(0, 100, 101, 99.5, 100.5), mk(1, 100.5, 100, 98.5, 99),
             mk(2, 99, 99, 95, 95.5), mk(3, 95.5, 96, 90, 92)]
        rise_lows = [91, 95, 99, 102, 104, 106, 108, 108, 108, 108, 108]
        price = 92.0
        for k, l in enumerate(rise_lows, start=4):
            o = max(price, l)
            price = l + 2
            c.append(mk(k, o, price + 0.5, l, price))
        for k in range(15, 21):
            c.append(mk(k, 108, 109.5, 108, 109))
        fall = [(109, 100), (100, 96), (96, 92), (92, 89)]
        for k, (o, cl) in enumerate(fall, start=21):
            c.append(mk(k, o, o + 0.5, cl - 0.5, cl))
        events = structure.analyze(c, symbol="BTCUSDT", exchange="toobit",
                                   timeframe="1h", data_asof_ms=asof(c))
        bos = [e for e in events if e["event_type"] == "BOS_BEARISH"]
        self.assertEqual(len(bos), 1)
        self.assertEqual(bos[0]["features"]["broken_level"], 90.0)
        self.assertEqual(bos[0]["features"]["direction"], "short")


class TestVolumeCluster(unittest.TestCase):

    def base_volumes(self, n=20):
        # ±۱۰ حول ۱۰۰ → انحراف معیار دقیقاً ۱۰؛ z حجم ۳۰۰ = ۲۰٫۰
        return [100.0 + (10.0 if i % 2 else -10.0) for i in range(n)]

    def test_surge_detected_with_exact_z(self):
        candles = [mk(i, 100, 101, 99, 100.5, v)
                   for i, v in enumerate(self.base_volumes())]
        candles.append(mk(20, 100, 101, 99, 100.5, 300.0))
        events = volume.unusual_volume(candles, symbol="BTCUSDT",
                                       exchange="toobit", timeframe="1h",
                                       data_asof_ms=asof(candles))
        self.assertEqual(len(events), 1)
        self.assertAlmostEqual(events[0]["features"]["z"], 20.0, places=2)
        self.assertAlmostEqual(events[0]["features"]["ratio_to_mean"], 3.0,
                               places=3)

    def test_normal_volume_no_event(self):
        candles = [mk(i, 100, 101, 99, 100.5, v)
                   for i, v in enumerate(self.base_volumes())]
        candles.append(mk(20, 100, 101, 99, 100.5, 105.0))
        events = volume.unusual_volume(candles, symbol="BTCUSDT",
                                       exchange="toobit", timeframe="1h",
                                       data_asof_ms=asof(candles))
        self.assertEqual(events, [])

    def test_flat_history_yields_no_fabricated_stat(self):
        candles = [mk(i, 100, 101, 99, 100.5, 100.0) for i in range(21)]
        events = volume.unusual_volume(candles, symbol="BTCUSDT",
                                       exchange="toobit", timeframe="1h",
                                       data_asof_ms=asof(candles))
        self.assertEqual(events, [])  # واریانس صفر → هیچ عددی جعل نمی‌شود


class TestLiquidityCluster(unittest.TestCase):

    def build_equal_highs_with_sweep(self):
        c = [mk(0, 100, 101, 99.5, 100.5), mk(1, 100.5, 102, 100, 101.5),
             mk(2, 101.5, 105, 101, 104),
             mk(3, 104, 110, 103.5, 108),                    # پیوت ۱ = ۱۱۰
             mk(4, 108, 104, 103, 103.5), mk(5, 103.5, 100, 99, 99.5),
             mk(6, 99.5, 96, 95, 95.5), mk(7, 95.5, 100, 95, 99),
             mk(8, 99, 104, 98.5, 103), mk(9, 103, 108, 102, 107),
             mk(10, 107, 110, 106, 109),                     # پیوت ۲ = ۱۱۰
             mk(11, 109, 106, 105, 105.5), mk(12, 105.5, 104, 103, 103.5),
             mk(13, 103.5, 111, 103, 105),                   # سوئیپ: عبور+بازگشت
             mk(14, 105, 106, 104, 105.5), mk(15, 105.5, 106, 105, 105.5)]
        return c

    def test_equal_highs_pool_observed(self):
        candles = self.build_equal_highs_with_sweep()
        events = liquidity.analyze(candles, symbol="BTCUSDT",
                                   exchange="toobit", timeframe="1h",
                                   data_asof_ms=asof(candles))
        pools = [e for e in events if e["event_type"] == "LIQ_POOL_ABOVE"]
        self.assertEqual(len(pools), 1)
        self.assertEqual(pools[0]["features"]["levels"], [110.0, 110.0])
        self.assertEqual(pools[0]["validation_status"], "OBSERVED")

    def test_failed_break_observed_with_hypothesis(self):
        candles = self.build_equal_highs_with_sweep()
        events = liquidity.analyze(candles, symbol="BTCUSDT",
                                   exchange="toobit", timeframe="1h",
                                   data_asof_ms=asof(candles))
        fb = [e for e in events if e["event_type"] == "FAILED_BREAK_ABOVE"]
        self.assertEqual(len(fb), 1)
        self.assertEqual(fb[0]["features"]["swing_level"], 110.0)
        self.assertIsNotNone(fb[0]["hypothesis"])
        self.assertIn("sweep", str(fb[0]["hypothesis"]))


class TestSessionCluster(unittest.TestCase):

    def test_session_tags_boundaries(self):
        self.assertEqual(sessions.session_tags(3 * HOUR), ["ASIA"])
        self.assertEqual(sessions.session_tags(10 * HOUR), ["LONDON"])
        self.assertEqual(sessions.session_tags(14 * HOUR), ["NEWYORK"])
        self.assertEqual(sessions.session_tags(7 * HOUR + 1),
                         ["ASIA", "LONDON"])  # هم‌پوشانی ثبت‌شده

    def test_amd_accumulation_is_hypothesis_only(self):
        candles = []
        for i in range(6):   # دامنهٔ پهن ۱۰
            candles.append(mk(i, 100, 105, 95, 100))
        for i in range(6, 12):  # فشرده ۴
            candles.append(mk(i, 100, 102, 98, 100))
        events = sessions.analyze(candles, symbol="BTCUSDT",
                                  exchange="toobit", timeframe="1h",
                                  data_asof_ms=asof(candles))
        amd = [e for e in events if e["event_type"] == "AMD_CANDIDATE"]
        self.assertEqual(len(amd), 1)
        self.assertEqual(amd[0]["features"]["phase"], "ACCUMULATION_CANDIDATE")
        self.assertEqual(amd[0]["validation_status"], "HYPOTHESIS")


class TestDerivativesCluster(unittest.TestCase):

    def test_snapshot_observed(self):
        ff = lambda s: {"ok": True, "funding_rate": 0.0001,
                        "mark_price": 81000.0, "funding_time": 123,
                        "history_count": 3}
        of = lambda s: {"ok": True, "open_interest": 95000.0, "asof_ms": 456}
        events = derivatives.analyze("BTCUSDT", data_asof_ms=999,
                                     funding_fetcher=ff, oi_fetcher=of)
        self.assertEqual(events[0]["event_type"], "DERIVATIVES_SNAPSHOT")
        self.assertEqual(events[0]["validation_status"], "OBSERVED")
        self.assertEqual(events[0]["features"]["open_interest"], 95000.0)

    def test_unavailable_never_fabricated(self):
        ff = lambda s: {"ok": False,
                        "error": {"error_type": "HTTP_ERROR", "status": 451}}
        of = lambda s: {"ok": True, "open_interest": 1.0, "asof_ms": 2}
        events = derivatives.analyze("BTCUSDT", data_asof_ms=999,
                                     funding_fetcher=ff, oi_fetcher=of)
        self.assertEqual(events[0]["event_type"], "DERIVATIVES_UNAVAILABLE")
        self.assertEqual(events[0]["validation_status"], "UNAVAILABLE")
        self.assertEqual(events[0]["features"]["errors"]["funding"]["status"],
                         451)


class TestCrossMarketCluster(unittest.TestCase):

    def test_divergence_above_cost_unvalidated(self):
        events = crossmarket.analyze(
            "BTCUSDT", {"toobit": 100.0, "binance": 100.5},
            quotes_asof_ms={"toobit": T0, "binance": T0},
            data_asof_ms=T0)
        self.assertEqual(events[0]["event_type"], "CROSS_MARKET_DIVERGENCE")
        self.assertEqual(events[0]["validation_status"], "UNVALIDATED")
        self.assertTrue(len(events[0]["uncertainty"]) >= 3)

    def test_small_divergence_no_edge(self):
        events = crossmarket.analyze(
            "BTCUSDT", {"toobit": 100.0, "binance": 100.1},
            quotes_asof_ms={"toobit": T0, "binance": T0},
            data_asof_ms=T0)
        self.assertEqual(events[0]["event_type"], "NO_ACTIONABLE_EDGE")
        self.assertIsNone(events[0]["hypothesis"])

    def test_stale_quotes_block_claim(self):
        events = crossmarket.analyze(
            "BTCUSDT", {"toobit": 100.0, "binance": 105.0},
            quotes_asof_ms={"toobit": T0, "binance": T0 - 1_000_000},
            data_asof_ms=T0)
        self.assertEqual(events[0]["event_type"], "NO_ACTIONABLE_EDGE")

    def test_single_source_unavailable(self):
        events = crossmarket.analyze("BTCUSDT", {"toobit": 100.0},
                                     data_asof_ms=T0)
        self.assertEqual(events[0]["event_type"], "CROSS_MARKET_UNAVAILABLE")
        self.assertEqual(events[0]["validation_status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
