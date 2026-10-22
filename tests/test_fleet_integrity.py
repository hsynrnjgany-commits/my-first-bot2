# MARI — آزمون آفلاین خوشهٔ L (سلامت و جرم‌شناسی داده)

import unittest

from fleet_loader import load_fleet

fleet = load_fleet()
integrity = fleet.integrity

HOUR = 3_600_000


def mk(t, o, h, l, c, v):
    return {"open_time": t, "open": o, "high": h, "low": l, "close": c,
            "volume": v}


def clean_series(n=5, start=1_700_000_000_000):
    return [mk(start + i * HOUR, 100.0, 101.0, 99.0, 100.5, 10.0)
            for i in range(n)]


def run_audit(candles):
    return integrity.audit_candles(
        candles, interval_ms=HOUR, symbol="BTCUSDT", exchange="toobit",
        timeframe="1h", data_asof_ms=candles[-1]["open_time"] + HOUR)


class TestIntegrityAudit(unittest.TestCase):

    def test_clean_candles_no_findings(self):
        clean, findings = run_audit(clean_series())
        self.assertEqual(len(clean), 5)
        self.assertEqual(findings, [])

    def test_duplicate_timestamp_flagged_and_deduped(self):
        candles = clean_series()
        candles.append(dict(candles[-1]))  # تکرار کامل آخرین کندل
        clean, findings = run_audit(candles)
        types = [f["event_type"] for f in findings]
        self.assertIn("DUPLICATE_TIMESTAMP", types)
        self.assertEqual(len(clean), 5)

    def test_gap_detected(self):
        base = clean_series(3)  # T0، T0+1h، T0+2h
        base.append(mk(base[-1]["open_time"] + 3 * HOUR,
                       100, 101, 99, 100.5, 10))  # T0+5h → شکاف ۳ اینتروال
        clean, findings = run_audit(base)
        gaps = [f for f in findings if f["event_type"] == "GAP"]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["features"]["gap_intervals"], 3.0)

    def test_negative_volume_excluded(self):
        candles = clean_series()
        candles[2]["volume"] = -1
        clean, findings = run_audit(candles)
        types = [f["event_type"] for f in findings]
        self.assertIn("NEGATIVE_VOLUME", types)
        self.assertEqual(len(clean), 4)

    def test_inconsistent_ohlc_excluded(self):
        candles = clean_series()
        candles[1]["high"] = 90.0  # کمتر از open/close
        clean, findings = run_audit(candles)
        types = [f["event_type"] for f in findings]
        self.assertIn("INCONSISTENT_OHLC", types)
        self.assertEqual(len(clean), 4)

    def test_out_of_order_input_sorted_with_finding(self):
        candles = clean_series()
        shuffled = [candles[0], candles[2], candles[1], candles[4], candles[3]]
        clean, findings = run_audit(shuffled)
        types = [f["event_type"] for f in findings]
        self.assertIn("OUT_OF_ORDER", types)
        self.assertEqual(
            [c["open_time"] for c in clean],
            sorted(c["open_time"] for c in clean))

    def test_findings_follow_contract(self):
        _, findings = run_audit(
            [mk(0, 100, 101, 99, 100.5, -5), mk(HOUR, 100, 101, 99, 100.5, 5)])
        for f in findings:
            self.assertEqual(f["cluster_id"], "L")
            self.assertEqual(f["validation_status"], "OBSERVED")
            self.assertEqual(f["evidence"]["method"], integrity.METHOD)
            self.assertIn("PAPER_ONLY", f["safety"]["mode"])


if __name__ == "__main__":
    unittest.main()
