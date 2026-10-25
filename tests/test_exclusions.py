# MARI — آزمون‌های آفلاین exclusions (فهرست استثنای نماد — تصمیم مالک)
# صفر شبکه؛ صفر نوشتن؛ قطعی. پوشش: فیلتر خالص، ترتیب، شواهد، سیم‌کشی اسکن.

import os
import sys
import unittest
import urllib.request
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

from fleet_loader import load_fleet  # noqa: E402

fleet = load_fleet()
exclusions = fleet.exclusions


class ExclusionsFilter(unittest.TestCase):
    def test_gram_removed(self):
        out = exclusions.filter_symbols(["BTCUSDT", "GRAMUSDT", "ETHUSDT"])
        self.assertEqual(out["kept"], ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(len(out["excluded"]), 1)
        self.assertEqual(out["excluded"][0]["symbol"], "GRAMUSDT")
        self.assertEqual(out["n_in"], 3)
        self.assertEqual(out["n_kept"], 2)

    def test_order_preserved(self):
        syms = ["ZZUSDT", "GRAMUSDT", "AAUSDT", "MMUSDT"]
        out = exclusions.filter_symbols(syms)
        self.assertEqual(out["kept"], ["ZZUSDT", "AAUSDT", "MMUSDT"])

    def test_unknown_symbols_pass_through(self):
        out = exclusions.filter_symbols(["FOOUSDT", "BARUSDT"])
        self.assertEqual(out["kept"], ["FOOUSDT", "BARUSDT"])
        self.assertEqual(out["excluded"], [])

    def test_empty_input(self):
        out = exclusions.filter_symbols([])
        self.assertEqual(out["kept"], [])
        self.assertEqual(out["excluded"], [])
        self.assertEqual(out["n_in"], 0)

    def test_evidence_fields_present(self):
        info = exclusions.UNAVAILABLE_SYMBOLS["GRAMUSDT"]
        for k in ("reason", "evidence", "decision"):
            self.assertTrue(info.get(k), f"missing {k}")
        out = exclusions.filter_symbols(["GRAMUSDT"])
        row = out["excluded"][0]
        self.assertEqual(row["reason"], "EXCHANGE_INVALID_SYMBOL")
        self.assertIn("HTTP400", row["evidence"])
        self.assertIn("OWNER_ORDER", row["decision"])
        self.assertEqual(row["source"], "toobit")
        self.assertEqual(row["method"], "exclusions/denylist_v1")

    def test_source_passthrough(self):
        out = exclusions.filter_symbols(["GRAMUSDT"], source="binance")
        self.assertEqual(out["excluded"][0]["source"], "binance")

    def test_deterministic(self):
        a = exclusions.filter_symbols(["GRAMUSDT", "XUSDT"])
        b = exclusions.filter_symbols(["GRAMUSDT", "XUSDT"])
        self.assertEqual(a, b)

    def test_no_history_rewrite_by_design(self):
        """فقط فیلتر آینده — هیچ تابع بازنویسی داده‌ای در ماژول نیست."""
        src_txt = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "src", "fleet",
            "exclusions.py"), encoding="utf-8").read()
        self.assertNotIn("open(", src_txt)
        self.assertNotIn("json.dump", src_txt)

    def test_network_isolation(self):
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=AssertionError("NO NETWORK")):
            out = exclusions.filter_symbols(["GRAMUSDT", "OKUSDT"])
            self.assertEqual(out["n_kept"], 1)


class ExclusionsScanWiring(unittest.TestCase):
    def test_scan_calls_filter_before_clusters(self):
        """ساختاری: scan.py فیلتر را بعد از کشف و قبل از خوشه‌ها صدا می‌زند."""
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "src", "fleet", "scan.py")
        src_txt = open(path, encoding="utf-8").read()
        self.assertIn("exclusions.filter_symbols", src_txt)
        disc = src_txt.index("symbols = top[\"symbols\"]")
        filt = src_txt.index("exclusions.filter_symbols")
        first_task = src_txt.index("tasks.append")
        self.assertLess(disc, filt)
        self.assertLess(filt, first_task)


if __name__ == "__main__":
    unittest.main()
