# PROJECT: WORLD MARKET CORE (MARI)
# MODE: READ ONLY
# EXECUTION: PAPER ONLY
# LIVE ORDERS: DISABLED
# SOURCE MODIFICATION: PROHIBITED
# PURPOSE: STAGE 1 — MARKET DISCOVERY (instrument discovery + validation + provenance)
# CONTRACT: mari.discovery.report/v1
# EXIT CODES: 0=success, 10=network/environment error, 20=source-contract error, 30=internal error
#
# قواعد سخت این ماژول:
# 1) فقط GET به endpoint عمومی و مستند — هیچ سفارشی، هیچ POST/DELETE، هیچ کلیدی.
# 2) هیچ عددی از پیش فرض نمی‌شود (نه ۳۰۰ نه ۳۰۰۰) — تعداد واقعی فقط از پاسخ معتبر API.
# 3) هیچ داده‌ای جعل نمی‌شود؛ endpoint غایب صریحاً «ارائه‌نشده توسط منبع» گزارش می‌شود.
# 4) این ماژول هرگز فایل موجودی بازنویسی نمی‌کند: فایل شواهد فقط با حالت 'x' ساخته می‌شود.
# 5) خطای شبکه از خطای منطق تفکیک می‌شود (کدهای خروج ۱۰ در برابر ۲۰/۳۰).

import json
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

TOOBIT_EXCHANGE_INFO_URL = "https://api.toobit.com/api/v1/exchangeInfo"
USER_AGENT = "MARI-ReadOnly-MarketDiscovery/1.0"
DEFAULT_TIMEOUT_SEC = 15

# پرچم ایمنی — هیچ مسیری در این ماژول سفارش نمی‌سازد؛ آزمون مستقل این را قفل می‌کند
ORDERS_DISABLED = True
READ_ONLY = True
PAPER_ONLY = True

# فیلدهای ضروری هر ابزار (برای هر دو لیست اسپات و فیوچرز این endpoint)
REQUIRED_FIELDS = ("symbol", "status", "baseAsset", "quoteAsset")

REPORT_SCHEMA = "mari.discovery.report/v1"

# وضعیت «قابل‌معامله» فقط از منبع: TRADING یعنی بازار فعال معامله — هر چیز دیگر
# عیناً همان‌طور که منبع داده ثبت می‌شود، هرگز حدس زده نمی‌شود.
TRADABLE_STATUS = "TRADING"


class _FakeClock:
    """تزریق زمان برای آزمون قطعی — در اجرای واقعی None می‌ماند."""


def _utc_iso(ms: int) -> str:
    """میلی‌ثانیهٔ یونیکس → رشتهٔ ISO-8601 UTC با پسوند Z (سیاست timestamp این ماژول)."""
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms % 1000:03d}Z"


def _load_json(raw: bytes):
    """تجزیهٔ JSON — تابع خالص؛ خطا را به شکل نتیجه برمی‌گرداند نه exception."""
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        return None, {"error_type": "INVALID_JSON", "message": str(err)}


def _default_opener(request: urllib.request.Request, timeout: float):
    return urllib.request.urlopen(request, timeout=timeout)


def fetch_exchange_info(url: str = TOOBIT_EXCHANGE_INFO_URL,
                        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
                        opener=None,
                        now_ms: int | None = None) -> dict:
    """دریافت exchangeInfo — هرگز exception پس نمی‌دهد؛ همیشه نتیجهٔ ساختاریافته."""
    opener = opener or _default_opener
    started_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(request, timeout_sec) as response:
            raw = response.read()
    except urllib.error.HTTPError as err:
        return {"ok": False, "error_type": "HTTP_ERROR", "http_status": err.code,
                "message": f"HTTP {err.code} از منبع: {err.reason}", "url": url,
                "started_ms": started_ms}
    except (TimeoutError, socket.timeout):
        return {"ok": False, "error_type": "TIMEOUT",
                "message": f"پاسخ بیشتر از {timeout_sec} ثانیه طول کشید", "url": url,
                "started_ms": started_ms}
    except urllib.error.URLError as err:
        return {"ok": False, "error_type": "NETWORK",
                "message": f"خطای شبکه: {err.reason}", "url": url,
                "started_ms": started_ms}
    except Exception as err:  # noqa: BLE001 — آخرین گارد صادقانه
        return {"ok": False, "error_type": "INTERNAL",
                "message": f"{type(err).__name__}: {err}", "url": url,
                "started_ms": started_ms}

    ended_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    payload, parse_err = _load_json(raw)
    if parse_err is not None:
        return {"ok": False, **parse_err, "url": url, "started_ms": started_ms,
                "ended_ms": ended_ms}
    if not isinstance(payload, dict):
        return {"ok": False, "error_type": "INVALID_SHAPE",
                "message": f"پاسخ یک شیء JSON نبود؛ نوع: {type(payload).__name__}",
                "url": url, "started_ms": started_ms, "ended_ms": ended_ms}
    return {"ok": True, "payload": payload, "url": url,
            "started_ms": started_ms, "ended_ms": ended_ms,
            "elapsed_ms": ended_ms - started_ms}


def _validate_list(entries, source_key: str) -> dict:
    """اعتبارسنجی یک لیست ابزار — تابع خالص و قطعی.

    سیاست دسته‌بندی (هر رکورد دقیقاً یک دسته):
      invalid    — فیلد ضروری غایب/خراب (علت ثبت می‌شود)
      unverified — شکل سالم ولی وضعیت غایب/خالی → قابل‌معامله‌بودن قابل اثبات نیست
      duplicate  — نماد تکراری در همین لیست؛ فقط رخداد اول شمرده می‌شود
      valid      — همهٔ فیلدها حاضر + وضعیت حاضر؛ tradable فقط اگر status==TRADING
    """
    counts = {"total": 0, "valid": 0, "unverified": 0, "invalid": 0,
              "duplicates": 0, "tradable": 0}
    statuses: dict[str, int] = {}
    invalid_examples: list[dict] = []
    duplicate_symbols: list[str] = []
    seen: set[str] = set()

    if not isinstance(entries, list):
        # قانون «هیچ عدد ساختگی»: کلید غایب یعنی نامشخص (None) — نه صفر.
        absent = {"total": None, "valid": None, "unverified": None,
                  "invalid": None, "duplicates": None, "tradable": None}
        return {"source_key": source_key, "source_present": False, **absent,
                "statuses": {}, "invalid_examples": [], "duplicate_symbols": [],
                "note": "کلید در پاسخ منبع موجود نبود — تعداد واقعی وجود ندارد و جعل نمی‌شود"}

    counts["total"] = len(entries)
    for idx, item in enumerate(entries):
        if not isinstance(item, dict):
            counts["invalid"] += 1
            if len(invalid_examples) < 10:
                invalid_examples.append({"index": idx, "symbol": None,
                                         "reason": "not_object"})
            continue

        symbol = item.get("symbol")
        has_symbol = isinstance(symbol, str) and symbol.strip() != ""
        missing = [f for f in REQUIRED_FIELDS if f != "symbol" and item.get(f) in (None, "")]
        if not has_symbol:
            counts["invalid"] += 1
            if len(invalid_examples) < 10:
                invalid_examples.append({"index": idx, "symbol": str(symbol)[:32],
                                         "reason": "missing_or_empty_symbol"})
            continue
        if missing:
            counts["invalid"] += 1
            if len(invalid_examples) < 10:
                invalid_examples.append({"index": idx, "symbol": symbol,
                                         "reason": "missing:" + ",".join(missing)})
            continue

        if symbol in seen:
            counts["duplicates"] += 1
            if len(duplicate_symbols) < 20:
                duplicate_symbols.append(symbol)
            continue
        seen.add(symbol)

        status = item.get("status")
        if status in (None, ""):
            counts["unverified"] += 1
            continue

        counts["valid"] += 1
        statuses[str(status)] = statuses.get(str(status), 0) + 1
        if status == TRADABLE_STATUS:
            counts["tradable"] += 1

    return {"source_key": source_key, "source_present": True, **counts,
            "statuses": statuses, "invalid_examples": invalid_examples,
            "duplicate_symbols": duplicate_symbols, "note": ""}


def validate_instruments(payload: dict, fetched_at_ms: int, source_url: str,
                         elapsed_ms: int = 0) -> dict:
    """ساخت گزارش کشف کامل — تابع خالص (بدون شبکه، بدون فایل، قطعی)."""
    spot = _validate_list(payload.get("symbols"), "symbols")
    futures = _validate_list(payload.get("contracts"), "contracts")
    server_time_ms = payload.get("serverTime")

    totals = {}
    for key in ("total", "valid", "unverified", "invalid", "duplicates", "tradable"):
        s = spot.get(key) or 0
        f = futures.get(key) or 0
        totals[key] = (s if spot.get("source_present") else 0) + \
                      (f if futures.get("source_present") else 0)

    notes = []
    if not spot.get("source_present"):
        notes.append("کلید «symbols» (اسپات) در پاسخ منبع نبود — صریحاً ارائه‌نشده، نه صفر")
    if not futures.get("source_present"):
        notes.append("کلید «contracts» (فیوچرز) در پاسخ منبع نبود — صریحاً ارائه‌نشده، نه صفر")
    if server_time_ms is None:
        notes.append("serverTime از منبع نیامده — انحراف ساعت قابل محاسبه نیست")

    return {
        "schema": REPORT_SCHEMA,
        "mode": {"read_only": READ_ONLY, "paper_only": PAPER_ONLY,
                 "live_orders_disabled": ORDERS_DISABLED},
        "source": {
            "provider": "toobit",
            "endpoint": "/api/v1/exchangeInfo",
            "url": source_url,
            "fetched_at_ms": fetched_at_ms,
            "fetched_at_utc": _utc_iso(fetched_at_ms),
            "server_time_ms": server_time_ms,
            "clock_skew_ms": (server_time_ms - fetched_at_ms)
            if isinstance(server_time_ms, (int, float)) else None,
            "elapsed_ms": elapsed_ms,
            "user_agent": USER_AGENT,
        },
        "rate_limits": payload.get("rateLimits"),
        "markets": {"spot": spot, "futures": futures},
        "totals": totals,
        "notes": notes,
        "policy": {
            "tradable_status": TRADABLE_STATUS,
            "fixed_count_assumed": False,
            "fabrication": "PROHIBITED",
            "evidence_overwrite": "PROHIBITED",
        },
    }


def write_evidence(report: dict, path: str) -> dict:
    """نوشتن شواهد — فقط فایل جدید؛ اگر مسیر موجود باشد هرگز بازنویسی نمی‌شود."""
    try:
        import os
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "x", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
        return {"ok": True, "path": path, "overwritten": False}
    except FileExistsError:
        return {"ok": False, "error": "EXISTS",
                "message": "فایل شواهد از قبل موجود بود — به‌دلیل ممنوعیت بازنویسی، دست نخورد"}
    except OSError as err:
        return {"ok": False, "error": "OS", "message": str(err)}


def _print_report(rep: dict) -> None:
    """گزارش متنی ساده — خوانا روی ترمینال اندروید و لاگ GitHub Actions."""
    src = rep["source"]
    print("=" * 62)
    print("MARI MARKET DISCOVERY — STAGE 1")
    print("Mode: READ ONLY | PAPER ONLY | Live orders: DISABLED")
    print("=" * 62)
    print("Source:", src["provider"], src["endpoint"])
    print("Fetched at (UTC):", src["fetched_at_utc"])
    if src["clock_skew_ms"] is not None:
        print("Clock skew (server - local, ms):", src["clock_skew_ms"])
    for market in ("spot", "futures"):
        m = rep["markets"][market]
        label = "SPOT (symbols)" if market == "spot" else "FUTURES (contracts)"
        print("-" * 62)
        print(f"{label}: source_key={m['source_key']} present={m['source_present']}")
        if not m["source_present"]:
            print("  -> ارائه‌نشده توسط منبع — هیچ عددی جعل نمی‌شود")
            continue
        print(f"  total={m['total']} valid={m['valid']} unverified={m['unverified']} "
              f"invalid={m['invalid']} duplicates={m['duplicates']} tradable={m['tradable']}")
        print("  statuses:", json.dumps(m["statuses"], ensure_ascii=False))
        if m["invalid_examples"]:
            print("  invalid examples:", json.dumps(m["invalid_examples"][:3], ensure_ascii=False))
        if m["duplicate_symbols"]:
            print("  duplicate symbols:", m["duplicate_symbols"][:5])
    print("-" * 62)
    print("TOTALS:", json.dumps(rep["totals"], ensure_ascii=False))
    for note in rep["notes"]:
        print("NOTE:", note)
    print("=" * 62)


def main(argv: list[str]) -> int:
    evidence_path = argv[1] if len(argv) > 1 and not argv[1].startswith("-") else None
    try:
        result = fetch_exchange_info()
    except Exception as err:  # noqa: BLE001 — گارد نهایی ماژول
        print("INTERNAL ERROR:", type(err).__name__, str(err))
        return 30
    if not result["ok"]:
        print("DISCOVERY FETCH FAILED:", result["error_type"])
        print("Message:", result.get("message"))
        print("این یک خطای محیط/شبکه/قرارداد است — نه یک اجرای موفق.")
        return 10 if result["error_type"] in ("HTTP_ERROR", "TIMEOUT", "NETWORK") else 20

    report = validate_instruments(
        result["payload"], result["ended_ms"], result["url"], result["elapsed_ms"]
    )
    _print_report(report)

    if evidence_path:
        wr = write_evidence(report, evidence_path)
        if wr["ok"]:
            print("Evidence written (new file only):", wr["path"])
        else:
            print("Evidence NOT written:", wr.get("message", wr.get("error")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
