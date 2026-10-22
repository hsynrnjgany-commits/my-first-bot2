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
BYBIT_KLINES_URL = "https://api.bybit.com/v5/market/kline"
OKX_KLINES_URL = "https://www.okx.com/api/v5/market/candles"
BYBIT_TICKER_URL = "https://api.bybit.com/v5/market/tickers"
OKX_TICKER_URL = "https://www.okx.com/api/v5/market/ticker"

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


def parse_bybit_klines(payload) -> list:
    """v5/market/kline: result.list نزولی [start,o,h,l,c,v,turnover] → صعودی."""
    rows = payload["result"]["list"]
    candles = []
    for row in rows:
        candles.append({
            "open_time": int(row[0]),
            "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]),
            "volume": float(row[5]),
        })
    candles.reverse()  # از قدیمی به جدید
    return candles


def to_okx_inst(symbol: str) -> "str | None":
    """BTCUSDT → BTC-USDT؛ غیر USDT پشتیبانی نمی‌شود (صادقانه None)."""
    if symbol.endswith("USDT") and len(symbol) > 4:
        return symbol[:-4] + "-USDT"
    return None


def parse_okx_klines(payload) -> list:
    """v5/market/candles: data نزولی [ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]
    — فقط کندل‌های confirmed (confirm=="1") نگه داشته می‌شود."""
    rows = payload["data"]
    candles = []
    for row in rows:
        if len(row) < 9 or row[8] != "1":
            continue  # کندل ناتمام آخر — وارد تحلیل نمی‌شود
        candles.append({
            "open_time": int(row[0]),
            "open": float(row[1]), "high": float(row[2]),
            "low": float(row[3]), "close": float(row[4]),
            "volume": float(row[5]),
        })
    candles.reverse()
    return candles


def fetch_klines(symbol: str, interval: str = "1h", limit: int = 200,
                 opener=None) -> dict:
    """زنجیرهٔ منابع: Toobit → Binance → Bybit → OKX. شکست هر منبع ثبت و ادامه."""
    errors = []
    okx_inst = to_okx_inst(symbol)
    targets = (
        ("toobit", f"{TOOBIT_KLINES_URL}?symbol={symbol}&interval={interval}&limit={limit}", parse_klines),
        ("binance", f"{BINANCE_KLINES_URL}?symbol={symbol}&interval={interval}&limit={limit}", parse_klines),
        ("bybit", f"{BYBIT_KLINES_URL}?category=spot&symbol={symbol}&interval=60&limit={limit}", parse_bybit_klines),
        ("okx", f"{OKX_KLINES_URL}?instId={okx_inst}&bar=1H&limit={limit}" if okx_inst else None, parse_okx_klines),
    )
    for name, url, parser in targets:
        if not url:
            errors.append({"source": name, "error_type": "SYMBOL_UNSUPPORTED"})
            continue
        payload, err = _get_json(url, opener)
        if err:
            errors.append({"source": name, **err})
            continue
        try:
            candles = parser(payload)
        except (ValueError, TypeError, IndexError, KeyError) as parse_err:
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
    elif exchange == "bybit":
        url = f"{BYBIT_TICKER_URL}?category=spot&symbol={symbol}"
    elif exchange == "okx":
        inst = to_okx_inst(symbol)
        if not inst:
            return {"ok": False, "error": {"error_type": "SYMBOL_UNSUPPORTED"}}
        url = f"{OKX_TICKER_URL}?instId={inst}"
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
        if exchange == "bybit" and isinstance(payload, dict):
            lst = payload["result"]["list"]
            if lst:
                return {"ok": True, "price": float(lst[0]["lastPrice"]),
                        "asof_ms": int(float(lst[0].get("ts") or 0))}
        if exchange == "okx" and isinstance(payload, dict):
            data = payload["data"]
            if data:
                return {"ok": True, "price": float(data[0]["last"]),
                        "asof_ms": int(data[0].get("ts") or 0)}
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


# ---------- منابع خوشهٔ I (آن‌چین و توکن جدید) — همهٔ رایگان و بدون کلید ----------

COINGECKO_TRENDING_URL = "https://api.coingecko.com/api/v3/search/trending"
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_COIN_URL = "https://api.coingecko.com/api/v3/coins"
MEMPOOL_FEES_URL = "https://mempool.space/api/v1/fees/recommended"
MEMPOOL_DIFF_URL = "https://mempool.space/api/v1/difficulty-adjustment"


def fetch_trending_tokens(opener=None) -> dict:
    """توکن‌های پرتوجه‌شده از CoinGecko (عمومی). خروجی با asset_id متمایز از نماد.
    نماد ≠ شناسهٔ دارایی؛ دارایی‌های هم‌نام با asset_id جدا می‌شوند."""
    payload, err = _get_json(COINGECKO_TRENDING_URL, opener)
    if err:
        return {"ok": False, "error": err}
    coins = payload.get("coins") if isinstance(payload, dict) else None
    if not isinstance(coins, list):
        return {"ok": False, "error": {"error_type": "EMPTY_PAYLOAD"}}
    tokens = []
    asof_ms = 0
    for row in coins:
        item = row.get("item") if isinstance(row, dict) else None
        if not isinstance(item, dict):
            continue
        asset_id = item.get("id")
        if not asset_id:
            continue  # بدون شناسهٔ دارایی ثبت نمی‌شود — نماد به‌تنهایی کافی نیست
        meta = item.get("data") if isinstance(item.get("data"), dict) else {}
        tokens.append({
            "asset_id": str(asset_id),
            "symbol": str(item.get("symbol") or ""),
            "name": str(item.get("name") or ""),
            "market_cap_rank": item.get("market_cap_rank"),
            "price_usd": meta.get("price"),
        })
    return {"ok": True, "tokens": tokens[:10], "source": "coingecko.trending/v3",
            "asof_ms": asof_ms}


def fetch_newly_added(opener=None, per_page: int = 30) -> dict:
    """توکن‌های تازه‌افزوده‌شدهٔ CoinGecko (category=newly-added، عمومی).
    توجه صریح: «تازه‌افزوده‌شده در منبع» ≠ «توکن نوپدید جهانی» — این تفاوت در
    پیام خوشه با uncertainty ثبت می‌شود."""
    url = (f"{COINGECKO_MARKETS_URL}?vs_currency=usd&category=newly-added"
           f"&order=market_cap_desc&per_page={max(1, min(int(per_page), 50))}"
           "&page=1&price_change_percentage=24h")
    payload, err = _get_json(url, opener)
    if err:
        return {"ok": False, "error": err}
    if not isinstance(payload, list):
        return {"ok": False, "error": {"error_type": "EMPTY_PAYLOAD"}}
    coins = []
    for row in payload:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        coins.append({
            "asset_id": str(row["id"]),
            "symbol": str(row.get("symbol") or ""),
            "name": str(row.get("name") or ""),
            "market_cap": row.get("market_cap"),
            "market_cap_rank": row.get("market_cap_rank"),
            "total_volume": row.get("total_volume"),
            "price_change_24h_pct": row.get("price_change_percentage_24h"),
            "last_updated": row.get("last_updated"),
        })
    return {"ok": True, "coins": coins, "source": "coingecko.markets/v3"}


def fetch_token_identity(asset_id: str, opener=None) -> dict:
    """هویت کامل دارایی: شناسه، نماد، نام و نگاشت شبکه→قرارداد (پلتفرم‌ها).
    برای تفکیک دارایی‌های هم‌نام و ثبت شبکه/قرارداد هر توکن (بند ۳-I)."""
    url = (f"{COINGECKO_COIN_URL}/{asset_id}"
           "?localization=false&tickers=false&market_data=false"
           "&community_data=false&developer_data=false")
    payload, err = _get_json(url, opener)
    if err:
        return {"ok": False, "error": err}
    try:
        platforms = payload.get("platforms")
        if not isinstance(platforms, dict):
            platforms = {}
        return {
            "ok": True,
            "asset_id": str(payload["id"]),
            "symbol": str(payload.get("symbol") or ""),
            "name": str(payload.get("name") or ""),
            "platforms": {str(k): (str(v) if v else None)
                          for k, v in platforms.items()},
            "source": "coingecko.coin/v3",
        }
    except (KeyError, TypeError, ValueError) as conv_err:
        return {"ok": False, "error": {"error_type": "PARSE_ERROR",
                                       "message": str(conv_err)}}


def fetch_btc_network(opener=None) -> dict:
    """وضعیت شبکهٔ بیت‌کوین از mempool.space (عمومی، بدون کلید):
    کارمزدهای پیشنهادی + تنظیم دشواری. هر دو بخش غایب → ok=False (صادقانه)."""
    fees_payload, fees_err = _get_json(MEMPOOL_FEES_URL, opener)
    diff_payload, diff_err = _get_json(MEMPOOL_DIFF_URL, opener)
    if fees_err and diff_err:
        return {"ok": False, "error": fees_err or diff_err}
    fees = None
    if not fees_err and isinstance(fees_payload, dict):
        fees = {k: fees_payload.get(k) for k in
                ("fastestFee", "hourFee", "economyFee", "minimumFee")
                if k in fees_payload}
    diff = None
    if not diff_err and isinstance(diff_payload, dict):
        diff = {k: diff_payload.get(k) for k in
                ("progressPercent", "difficultyChange", "remainingBlocks",
                 "estimatedRetargetDate") if k in diff_payload}
    return {"ok": True, "fees": fees, "difficulty": diff,
            "source": "mempool.space/v1",
            "partial": bool(fees_err or diff_err)}
