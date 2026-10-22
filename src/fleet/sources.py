# MARI — منابع دادهٔ عمومی ناوگان (فقط GET، فقط رایگان، فقط مستند)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# بند ۲: شکست یک منبع کل سامانه را متوقف نمی‌کند — خطا ثبت و منبع بعدی آزموده می‌شود.
# opener تزریقی است تا آزمون آفلاین بدون شبکه ممکن باشد (الگوی Stage 1).

import json
import socket
import urllib.error
import urllib.request

USER_AGENT = "MARI-ReadOnly-Fleet/1.0"
DEFAULT_TIMEOUT_SEC = 15

TOOBIT_KLINES_URL = "https://api.toobit.com/quote/v1/klines"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
TOOBIT_TICKER24_URL = "https://api.toobit.com/quote/v1/ticker/24hr"
TOOBIT_PRICE_URL = "https://api.toobit.com/quote/v1/ticker/price"
BINANCE_PRICE_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
BINANCE_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"

# بازهٔ «1h» با پروب واقعی روی هر دو منبع تأیید شد (۱۰۰تایی از Toobit و Binance)
INTERVALS = ("15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")


def _get_json(url: str, opener=None, timeout: float = DEFAULT_TIMEOUT_SEC):
    """(payload, error) — هرگز exception بیرون نمی‌دهد؛ خطا تایپ‌بندی و ثبت‌شدنی است."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    do = opener.open if opener is not None else urllib.request.urlopen
    try:
        with do(request, timeout=timeout) as response:
            raw = response.read()
    except socket.timeout:
        return None, {"error_type": "TIMEOUT", "message": f"timeout after {timeout}s"}
    except urllib.error.HTTPError as err:
        return None, {"error_type": "HTTP_ERROR", "status": err.code}
    except urllib.error.URLError as err:
        return None, {"error_type": "NETWORK", "message": str(err.reason)}
    except Exception as err:  # noqa: BLE001 — گارد نهایی منبع
        return None, {"error_type": "INTERNAL", "message": f"{type(err).__name__}: {err}"}
    try:
        return json.loads(raw.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        return None, {"error_type": "INVALID_JSON", "message": str(err)}


def parse_klines(payload) -> list:
    """آرایهٔ سبک Binance/Toobit → فهرست کندل دیکشنری. ورودی خراب → exception (تماس‌گیرنده می‌گیرد)."""
    candles = []
    for row in payload:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise ValueError("kline row malformed")
        candles.append({
            "open_time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })
    return candles


def fetch_klines(symbol: str, interval: str = "1h", limit: int = 200,
                 opener=None) -> dict:
    """Toobit اول، Binance پشتیبان. خروجی همیشه ok/candles/source/errors دارد."""
    errors = []
    targets = (
        ("toobit", f"{TOOBIT_KLINES_URL}?symbol={symbol}&interval={interval}&limit={limit}"),
        ("binance", f"{BINANCE_KLINES_URL}?symbol={symbol}&interval={interval}&limit={limit}"),
    )
    for name, url in targets:
        payload, err = _get_json(url, opener)
        if err:
            errors.append({"source": name, **err})
            continue
        try:
            candles = parse_klines(payload)
        except (ValueError, TypeError, IndexError) as parse_err:
            errors.append({"source": name, "error_type": "PARSE_ERROR",
                           "message": str(parse_err)})
            continue
        if candles:
            return {"ok": True, "candles": candles, "source": name,
                    "errors": errors}
        errors.append({"source": name, "error_type": "EMPTY_PAYLOAD"})
    return {"ok": False, "candles": [], "source": None, "errors": errors}


def fetch_top_symbols(n: int = 8, quote: str = "USDT", opener=None) -> dict:
    """انتخاب پربحجم‌ترین نمادهای quote از تیکر ۲۴ساعتهٔ Toobit (شمارش واقعی از منبع)."""
    payload, err = _get_json(TOOBIT_TICKER24_URL, opener)
    if err:
        return {"ok": False, "symbols": [], "error": err}
    rows = []
    for r in payload if isinstance(payload, list) else []:
        sym = r.get("s") if isinstance(r, dict) else None
        if sym and sym.endswith(quote):
            rows.append(r)
    rows.sort(key=lambda r: float(r.get("qv") or 0), reverse=True)
    asof = max((int(r.get("t") or 0) for r in rows), default=0)
    return {
        "ok": True,
        "symbols": [r["s"] for r in rows[:max(1, n)]],
        "universe_count": len(rows),
        "asof_ms": asof,
        "source": "toobit.ticker24/v1",
    }


def fetch_price(symbol: str, exchange: str = "toobit", opener=None) -> dict:
    """آخرین قیمت — برای خوشهٔ H (بین‌بازاری). خروجی: ok/price/asof_ms یا error."""
    if exchange == "toobit":
        url = f"{TOOBIT_PRICE_URL}?symbol={symbol}"
    elif exchange == "binance":
        url = f"{BINANCE_PRICE_URL}?symbol={symbol}"
    else:
        return {"ok": False, "error": {"error_type": "UNKNOWN_EXCHANGE",
                                       "message": exchange}}
    payload, err = _get_json(url, opener)
    if err:
        return {"ok": False, "error": err}
    try:
        if exchange == "toobit" and isinstance(payload, list) and payload:
            return {"ok": True, "price": float(payload[0]["p"]),
                    "asof_ms": int(payload[0].get("t") or 0)}
        if exchange == "binance" and isinstance(payload, dict):
            return {"ok": True, "price": float(payload["price"]),
                    "asof_ms": int(payload.get("time") or 0)}
    except (KeyError, TypeError, ValueError) as conv_err:
        return {"ok": False, "error": {"error_type": "PARSE_ERROR",
                                       "message": str(conv_err)}}
    return {"ok": False, "error": {"error_type": "EMPTY_PAYLOAD"}}


def fetch_funding(symbol: str, limit: int = 3, opener=None) -> dict:
    """نرخ تأمین مالی از Binance fapi (عمومی). شکست → error صریح؛ هرگز دادهٔ ساختگی."""
    url = f"{BINANCE_FUNDING_URL}?symbol={symbol}&limit={limit}"
    payload, err = _get_json(url, opener)
    if err:
        return {"ok": False, "error": err}
    if not isinstance(payload, list) or not payload:
        return {"ok": False, "error": {"error_type": "EMPTY_PAYLOAD"}}
    latest = payload[-1]
    try:
        return {
            "ok": True,
            "funding_rate": float(latest["fundingRate"]),
            "mark_price": float(latest["markPrice"]),
            "funding_time": int(latest["fundingTime"]),
            "history_count": len(payload),
        }
    except (KeyError, TypeError, ValueError) as conv_err:
        return {"ok": False, "error": {"error_type": "PARSE_ERROR",
                                       "message": str(conv_err)}}


def fetch_open_interest(symbol: str, opener=None) -> dict:
    """بازِ ناخالص باز از Binance fapi (عمومی). شکست → error صریح."""
    url = f"{BINANCE_OI_URL}?symbol={symbol}"
    payload, err = _get_json(url, opener)
    if err:
        return {"ok": False, "error": err}
    try:
        return {"ok": True, "open_interest": float(payload["openInterest"]),
                "asof_ms": int(payload["time"])}
    except (KeyError, TypeError, ValueError) as conv_err:
        return {"ok": False, "error": {"error_type": "PARSE_ERROR",
                                       "message": str(conv_err)}}
