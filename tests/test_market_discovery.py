# MARI — آزمون‌های مستقل آفلاین موتور کشف بازار (Stage 1)
# اجرا: python -m unittest discover -s tests -v
# هیچ شبکه‌ای در کار نیست: واکشی با opener تزریقی و پاسخ ساختگی آزموده می‌شود.
# اگر هر آزمون شکست بخورد، exit کد غیرصفر می‌شود (عبور صوری ممنوع).

import importlib.util
import json
import os
import socket
import unittest
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENGINE_PATH = os.path.join(ROOT, "src", "market_discovery.py")
_spec = importlib.util.spec_from_file_location("market_discovery", _ENGINE_PATH)
md = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(md)


def good_spot(symbol="BTCUSDT", status="TRADING", base="BTC", quote="USDT"):
    return {"symbol": symbol, "status": status, "baseAsset": base,
            "quoteAsset": quote, "baseAssetPrecision": 8, "quotePrecision": 8}


def fake_payload():
    """پاسخ ساختگی با خواص معلوم: ۵ اسپات (۲ معتبر + ۲ ناقص + ۱ تکراری) + ۲ فیوچرز."""
    return {
        "timezone": "UTC",
        "serverTime": 1_700_000_000_000,
        "symbols": [
            good_spot("BTCUSDT"),
            good_spot("ETHUSDT", status="API_TRADE_FORBIDDEN"),
            {"symbol": "BADUSDT", "status": "TRADING"},          # base/quote غایب → invalid
            {"symbol": "", "status": "TRADING", "baseAsset": "X",
             "quoteAsset": "Y"},                                  # نماد خالی → invalid
            good_spot("BTCUSDT"),                                 # تکراری → duplicate
        ],
        "contracts": [
            {"symbol": "BTCUSDT-PERP", "status": "TRADING",
             "baseAsset": "BTC", "quoteAsset": "USDT"},
            {"symbol": "ETHUSDT-PERP", "status": "TRADING",
             "baseAsset": "ETH", "quoteAsset": "USDT"},
        ],
        "rateLimits": [{"rateLimitType": "REQUEST_WEIGHT", "limit": 3000}],
    }


class _FakeResponse:
    def __init__(self, raw: bytes):
        self._raw = raw

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def opener_returning(raw: bytes):
    return lambda request, timeout: _FakeResponse(raw)


def opener_raising(exc):
    def _opener(request, timeout):
        raise exc
    return _opener


class InstrumentValidationTests(unittest.TestCase):
    """آزمون یکپارچگی داده + قرارداد پاسخ + تشخیص تکرار — همگی آفلاین."""

    def setUp(self):
        self.rep = md.validate_instruments(fake_payload(), 1_700_000_000_500,
                                           "https://fake.local/exchangeInfo", 120)

    def test_totals_exact_no_fixed_assumption(self):
        # اسپات: ۵ رکورد خام → ۲ valid + ۱ تکراری + ۲ invalid | فیوچرز: ۲ valid
        self.assertEqual(self.rep["markets"]["spot"]["total"], 5)
        self.assertEqual(self.rep["markets"]["spot"]["valid"], 2)
        self.assertEqual(self.rep["markets"]["spot"]["invalid"], 2)
        self.assertEqual(self.rep["markets"]["spot"]["duplicates"], 1)
        self.assertEqual(self.rep["markets"]["futures"]["total"], 2)
        self.assertEqual(self.rep["markets"]["futures"]["valid"], 2)
        self.assertEqual(self.rep["totals"]["total"], 7)

    def test_tradable_only_when_status_trading(self):
        # فقط status==TRADING قابل‌معامله است؛ API_TRADE_FORBIDDEN عیناً ثبت ولی غیرقابل‌معامله
        self.assertEqual(self.rep["markets"]["spot"]["tradable"], 1)
        self.assertEqual(self.rep["markets"]["spot"]["statuses"]["API_TRADE_FORBIDDEN"], 1)

    def test_invalid_reason_recorded_not_guessed(self):
        reasons = [e["reason"] for e in self.rep["markets"]["spot"]["invalid_examples"]]
        self.assertIn("missing:baseAsset,quoteAsset", reasons)
        self.assertIn("missing_or_empty_symbol", reasons)

    def test_duplicate_detection_first_occurrence_kept(self):
        self.assertEqual(self.rep["markets"]["spot"]["duplicate_symbols"], ["BTCUSDT"])

    def test_spot_futures_split_from_verified_keys(self):
        self.assertEqual(self.rep["markets"]["spot"]["source_key"], "symbols")
        self.assertEqual(self.rep["markets"]["futures"]["source_key"], "contracts")
        self.assertTrue(self.rep["markets"]["spot"]["source_present"])
        self.assertTrue(self.rep["markets"]["futures"]["source_present"])


class MissingSourceKeyTests(unittest.TestCase):
    """اگر endpoint بازاری را ارائه ندهد، صریح گزارش می‌شود — نه صفرِ ساختگی."""

    def test_absent_contracts_reported_not_fabricated(self):
        payload = {"timezone": "UTC", "serverTime": 1, "symbols": [good_spot()]}
        rep = md.validate_instruments(payload, 1_700_000_000_000, "u")
        self.assertFalse(rep["markets"]["futures"]["source_present"])
        self.assertIsNone(rep["markets"]["futures"].get("total"))
        self.assertTrue(any("contracts" in n for n in rep["notes"]))


class ResponseContractTests(unittest.TestCase):
    """آزمون قرارداد پاسخ API — JSON نامعتبر و شکل نادرست."""

    def test_invalid_json_detected(self):
        payload, err = md._load_json(b"{not json at all")
        self.assertIsNone(payload)
        self.assertEqual(err["error_type"], "INVALID_JSON")

    def test_wrong_shape_detected(self):
        # لایهٔ JSON آرایهٔ معتبر را می‌پذیرد (کار JSON نیست، شکل‌سنجی کار fetch است)
        payload, err = md._load_json(json.dumps([1, 2, 3]).encode())
        self.assertIsNone(err)
        self.assertEqual(payload, [1, 2, 3])

    def test_fetch_invalid_shape_no_raise(self):
        res = md.fetch_exchange_info("https://fake.local", opener=opener_returning(b'[]'))
        self.assertFalse(res["ok"])
        self.assertEqual(res["error_type"], "INVALID_SHAPE")


class NetworkErrorSeparationTests(unittest.TestCase):
    """خطاهای شبکه از خطاهای منطق تفکیک می‌شوند — هیچ‌کدام exception پس نمی‌دهند."""

    def test_timeout(self):
        res = md.fetch_exchange_info("https://fake.local",
                                     opener=opener_raising(socket.timeout("timed out")))
        self.assertEqual(res["error_type"], "TIMEOUT")

    def test_http_error(self):
        res = md.fetch_exchange_info(
            "https://fake.local",
            opener=opener_raising(urllib.error.HTTPError("u", 503, "unavailable", {}, None)))
        self.assertEqual(res["error_type"], "HTTP_ERROR")
        self.assertEqual(res["http_status"], 503)

    def test_network_error(self):
        res = md.fetch_exchange_info(
            "https://fake.local",
            opener=opener_raising(urllib.error.URLError("connection refused")))
        self.assertEqual(res["error_type"], "NETWORK")

    def test_success_path_with_fake_response(self):
        raw = json.dumps(fake_payload()).encode()
        res = md.fetch_exchange_info("https://fake.local",
                                     opener=opener_returning(raw),
                                     now_ms=1_700_000_000_500)
        self.assertTrue(res["ok"])
        self.assertEqual(res["elapsed_ms"], 0)


class TimestampPolicyTests(unittest.TestCase):
    """آزمون هم‌ترازی زمانی — UTC قطعی با ساعت تزریقی."""

    def test_utc_iso_format_deterministic(self):
        self.assertEqual(md._utc_iso(1_700_000_000_500), "2023-11-14T22:13:20.500Z")

    def test_provenance_and_clock_skew_recorded(self):
        rep = md.validate_instruments(fake_payload(), 1_700_000_000_500, "u")
        self.assertEqual(rep["source"]["fetched_at_utc"], "2023-11-14T22:13:20.500Z")
        # serverTime پاسخ ساختگی ۵۰۰ms عقب‌تر از لحظهٔ دریافت است
        self.assertEqual(rep["source"]["clock_skew_ms"], -500)

    def test_missing_servertime_reported_not_zero(self):
        payload = {"symbols": [good_spot()]}
        rep = md.validate_instruments(payload, 1_700_000_000_000, "u")
        self.assertIsNone(rep["source"]["clock_skew_ms"])
        self.assertTrue(any("serverTime" in n for n in rep["notes"]))


class EvidenceProtectionTests(unittest.TestCase):
    """هیچ فایل موجودی بازنویسی نمی‌شود — قانون SOURCE MODIFICATION PROHIBITED."""

    def test_write_evidence_never_overwrites(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "ev.json")
            first = md.write_evidence({"n": 1}, path)
            self.assertTrue(first["ok"])
            with open(path, encoding="utf-8") as fh:
                before = fh.read()
            second = md.write_evidence({"n": 2}, path)
            self.assertFalse(second["ok"])
            self.assertEqual(second["error"], "EXISTS")
            with open(path, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), before)  # محتوا دست‌نخورده


class SafeModeTests(unittest.TestCase):
    """آزمون حالت امن: این ماژول هیچ مسیر سفارش واقعی ندارد."""

    def test_orders_disabled_flag(self):
        self.assertIs(md.ORDERS_DISABLED, True)
        self.assertIs(md.READ_ONLY, True)
        self.assertIs(md.PAPER_ONLY, True)

    def test_module_never_sets_http_method_post_or_delete(self):
        # منبع ماژول هرگز method="POST"/"DELETE" تعیین نمی‌کند → فقط GET پیش‌فرض
        with open(_ENGINE_PATH, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn('method="POST"', src)
        self.assertNotIn("method='POST'", src)
        self.assertNotIn('method="DELETE"', src)
        self.assertNotIn("method='DELETE'", src)

    def test_report_carries_mode_labels(self):
        rep = md.validate_instruments(fake_payload(), 1_700_000_000_000, "u")
        self.assertTrue(rep["mode"]["read_only"])
        self.assertTrue(rep["mode"]["paper_only"])
        self.assertTrue(rep["mode"]["live_orders_disabled"])
        self.assertFalse(rep["policy"]["fixed_count_assumed"])


class AntiFutureLeakPolicyTests(unittest.TestCase):
    """سیاست ضدنشت در مرحلهٔ کشف: هیچ کندلی (باز یا بسته) در این مرحله مصرف نمی‌شود."""

    def test_report_declares_no_candle_consumption(self):
        rep = md.validate_instruments(fake_payload(), 1_700_000_000_000, "u")
        self.assertEqual(rep["schema"], "mari.discovery.report/v1")
        self.assertNotIn("candles", json.dumps(rep["markets"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
