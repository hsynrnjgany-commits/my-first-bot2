# MARI — آزمون‌های آفلاین hypothesis_lab (حلقهٔ M-6 — راستی‌آزمایی فرض‌های AI)
# صفر شبکه؛ صفر نوشتن؛ قطعی. پوشش: عبارت‌یابی، ضدنشت پنجره، مسیرهای حکم،
# بازتولیدپذیری، ایزوله‌شبکه، دودآزمون دفترچهٔ واقعی روی آرشیو M3.

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
hl = fleet.hypothesis_lab
quant = fleet.quant

HOUR_MS = 3_600_000
T0 = 1_700_000_000_000


def lcg_candles(n, seed=42, base=100.0):
    """سری قطعی شبه‌تصادفی (LCG) — بازده نویزی؛ برای هومرست/EWMA معنادار."""
    out, state, price = [], seed, base
    for i in range(n):
        state = (1103515245 * state + 12345) % (2 ** 31)
        r = ((state % 2000) - 1000) / 100_000.0  # ±1٪
        o = price
        c = price * (1 + r)
        out.append({"open_time": T0 + i * HOUR_MS, "open": o,
                    "high": max(o, c) * 1.002, "low": min(o, c) * 0.998,
                    "close": c, "volume": 10.0})
        price = c
    return out


def mk_row(symbol, statement, asof_ms=T0 + 200 * HOUR_MS, event_id="E0"):
    return {"event_id": event_id, "symbol": symbol,
            "data_asof_ms": asof_ms, "features": {"statement": statement}}


class ClaimParsing(unittest.TestCase):
    def test_ewma_claim(self):
        c = hl.parse_claim("هیست اکسپوننشیال متحرک میانگین وزن‌دار (EWMA) "
                           "نوسان قیمت BTCUSDT در هر کندل 0.003083 است")
        self.assertEqual(c["metric"], "EWMA_VOL_PER_BAR")
        self.assertEqual(c["value"], 0.003083)
        self.assertIsNone(c["regime"])

    def test_hurst_claim_with_regime(self):
        c = hl.parse_claim("شاخص هرست BTCUSDT 0.6427 است که نشان‌دهنده "
                           "تمایل به روند (TRENDING_CANDIDATE) است")
        self.assertEqual(c["metric"], "HURST")
        self.assertEqual(c["value"], 0.6427)
        self.assertEqual(c["regime"], "TRENDING_CANDIDATE")

    def test_session_claim(self):
        c = hl.parse_claim("در سشن نیویورک، نوسان قیمت BTCUSDT به طور "
                           "میانگین 487.95 واحد است")
        self.assertEqual(c["metric"], "SESSION_RANGE_MEAN")
        self.assertEqual(c["value"], 487.95)

    def test_garbage_unparsed(self):
        self.assertIsNone(hl.parse_claim("قیمت خوب است")["metric"])
        self.assertIsNone(hl.parse_claim("")["metric"])
        self.assertIsNone(hl.parse_claim(None)["metric"])
        self.assertIsNone(hl.parse_claim("هرست بدون عدد")["value"])

    def test_measuring_regime_variant(self):
        c = hl.parse_claim("شاخص هرست X 0.30 است که بازگشت به میانگین "
                           "(MEAN_REVERTING_CANDIDATE) دارد")
        self.assertEqual(c["regime"], "MEAN_REVERTING_CANDIDATE")


class WindowAntiLookahead(unittest.TestCase):
    def test_only_candles_before_asof(self):
        candles = lcg_candles(300)
        asof = T0 + 250 * HOUR_MS
        wc = hl._window_before_asof(candles, asof, 200)
        self.assertEqual(len(wc), 200)
        self.assertTrue(all(c["open_time"] < asof for c in wc))
        self.assertEqual(wc[-1]["open_time"], T0 + 249 * HOUR_MS)

    def test_short_history_returns_all_past(self):
        candles = lcg_candles(40)
        wc = hl._window_before_asof(candles, T0 + 100 * HOUR_MS, 200)
        self.assertEqual(len(wc), 40)


class VerdictPaths(unittest.TestCase):
    def setUp(self):
        self.candles = lcg_candles(260)
        self.cmap = {"FAKEUSDT": self.candles}
        self.asof = T0 + 250 * HOUR_MS
        wc = hl._window_before_asof(self.candles, self.asof, 200)
        self.ewma_val = quant.ewma_volatility(quant.log_returns(wc))
        self.hurst_val = quant.hurst_exponent(quant.log_returns(wc))

    def test_ewma_reproduced(self):
        row = mk_row("FAKEUSDT",
                     f"هیست اکسپوننشیال (EWMA) نوسان FAKEUSDT در هر کندل "
                     f"{self.ewma_val:.6f} است", asof_ms=self.asof)
        rep = hl.evaluate_hypotheses([row], self.cmap)
        r = rep["results"][0]
        self.assertEqual(r["verdict"], "REPRODUCED")
        # گرد کردن بیانیه (مثل دفترچهٔ واقعی) بخشی از اختلاف است — زیر تلورانس
        self.assertLess(r["rel_diff_pct"], 5.0)
        self.assertEqual(rep["summary"], {"REPRODUCED": 1})

    def test_ewma_not_reproduced(self):
        bad = self.ewma_val * 1.5
        row = mk_row("FAKEUSDT",
                     f"EWMA نوسان FAKEUSDT در هر کندل {bad:.6f} است",
                     asof_ms=self.asof)
        rep = hl.evaluate_hypotheses([row], self.cmap)
        self.assertEqual(rep["results"][0]["verdict"], "NOT_REPRODUCED")

    def test_hurst_reproduced_with_regime_fields(self):
        self.assertIsNotNone(self.hurst_val)
        row = mk_row("FAKEUSDT",
                     f"شاخص هرست FAKEUSDT {self.hurst_val:.4f} است که "
                     f"نشان‌دهنده تمایل به روند (TRENDING_CANDIDATE) است",
                     asof_ms=self.asof)
        rep = hl.evaluate_hypotheses([row], self.cmap)
        r = rep["results"][0]
        self.assertEqual(r["verdict"], "REPRODUCED")
        self.assertIn("regime_recomputed", r)
        self.assertIn("regime_claimed", r)

    def test_session_mean_reproduced_with_note(self):
        wc = hl._window_before_asof(self.candles, self.asof, 200)
        ny = [c for c in wc if "NEWYORK"
              in fleet.sessions.session_tags(c["open_time"])]
        self.assertTrue(ny)
        claimed = sum(c["high"] - c["low"] for c in ny) / len(ny)
        row = mk_row("FAKEUSDT",
                     f"در سشن نیویورک، نوسان قیمت FAKEUSDT به طور میانگین "
                     f"{claimed:.6f} واحد است", asof_ms=self.asof)
        rep = hl.evaluate_hypotheses([row], self.cmap)
        r = rep["results"][0]
        self.assertEqual(r["verdict"], "REPRODUCED")
        self.assertIn("DEFINITION_ASSUMED", r.get("note", ""))

    def test_unparsed_claim(self):
        rep = hl.evaluate_hypotheses(
            [mk_row("FAKEUSDT", "کاملاً نامفهوم")], self.cmap)
        self.assertEqual(rep["results"][0]["verdict"],
                         "UNVERIFIABLE_CLAIM_UNPARSED")

    def test_symbol_missing(self):
        row = mk_row("NOPEUSDT", "EWMA نوسان NOPEUSDT در هر کندل 0.001 است",
                     asof_ms=self.asof)
        rep = hl.evaluate_hypotheses([row], self.cmap)
        self.assertEqual(rep["results"][0]["verdict"],
                         "UNVERIFIABLE_SYMBOL_MISSING")

    def test_insufficient_history(self):
        small = {"FAKEUSDT": lcg_candles(20)}
        row = mk_row("FAKEUSDT", "EWMA نوسان FAKEUSDT در هر کندل 0.001 است",
                     asof_ms=T0 + 100 * HOUR_MS)
        rep = hl.evaluate_hypotheses([row], small)
        self.assertEqual(rep["results"][0]["verdict"],
                         "UNVERIFIABLE_INSUFFICIENT_HISTORY")

    def test_empty_input(self):
        rep = hl.evaluate_hypotheses([], {"FAKEUSDT": self.candles})
        self.assertEqual(rep["verdict"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(rep["reason"], "EMPTY_INPUT_NO_ROWS_OR_CANDLES")

    def test_missing_features_safe(self):
        rep = hl.evaluate_hypotheses(
            [{"event_id": "X", "symbol": "FAKEUSDT",
              "data_asof_ms": self.asof}], self.cmap)
        self.assertEqual(rep["results"][0]["verdict"],
                         "UNVERIFIABLE_CLAIM_UNPARSED")


class DeterminismSafetyRealLedger(unittest.TestCase):
    def test_deterministic_and_no_timestamp(self):
        candles = lcg_candles(260)
        cmap = {"FAKEUSDT": candles}
        asof = T0 + 250 * HOUR_MS
        row = mk_row("FAKEUSDT", "EWMA نوسان FAKEUSDT در هر کندل 0.001 است",
                     asof_ms=asof)
        a = hl.canonical_json(hl.evaluate_hypotheses([row], cmap))
        b = hl.canonical_json(hl.evaluate_hypotheses([row], cmap))
        self.assertEqual(a, b)
        doc = json.loads(a)
        self.assertNotIn("timestamp", doc)
        self.assertNotIn("generated_at", doc)

    def test_network_isolation(self):
        candles = lcg_candles(260)
        row = mk_row("FAKEUSDT", "EWMA نوسان FAKEUSDT در هر کندل 0.001 است",
                     asof_ms=T0 + 250 * HOUR_MS)
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=AssertionError("NO NETWORK")):
            rep = hl.evaluate_hypotheses([row], {"FAKEUSDT": candles})
            self.assertEqual(rep["verdict"], "REPORTED")
            json.loads(hl.canonical_json(rep))

    def test_real_ledger_smoke_on_m3_archive(self):
        """دودآزمون واقعی: ۸ فرض دفترچه در برابر آرشیو M3 — فقط‌خواندنی."""
        ledger = "/home/z/my-project/repos/my-first-bot2/data/fleet/ai-hypotheses.jsonl"
        arch = "/home/z/my-project/mission003/archive"
        if not (os.path.exists(ledger) and os.path.exists(arch)):
            self.skipTest("ledger or archive not present")
        rows = hl.load_ledger(ledger)
        self.assertEqual(len(rows), 8)
        cmap = {}
        for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            path = os.path.join(arch, f"{s}__1h.json.gz")
            if not os.path.exists(path):
                self.skipTest(f"{s} missing in archive")
            doc = json.load(gzip.open(path, "rt"))
            cmap[s] = [{"open_time": r["t"], "open": r["o"], "high": r["h"],
                        "low": r["l"], "close": r["c"],
                        "volume": r.get("v", 0.0)} for r in doc["candles"]]
        rep = hl.evaluate_hypotheses(rows, cmap)
        self.assertEqual(rep["verdict"], "REPORTED")
        self.assertEqual(len(rep["results"]), 8)
        enum = {"REPRODUCED", "NOT_REPRODUCED", "UNVERIFIABLE_CLAIM_UNPARSED",
                "UNVERIFIABLE_SYMBOL_MISSING",
                "UNVERIFIABLE_INSUFFICIENT_HISTORY",
                "UNVERIFIABLE_RECOMPUTE_NULL"}
        for r in rep["results"]:
            self.assertIn(r["verdict"], enum)
        self.assertEqual(sum(rep["summary"].values()), 8)
        json.loads(hl.canonical_json(rep))


if __name__ == "__main__":
    unittest.main()
