# منابع جهانی بازار — WORLD MARKET CORE (فاز ۱)
# فقط APIهای عمومی و رایگان؛ بدون کلید. الگوی صادقانهٔ sources.py:
# خروجی {"ok": True, ...} یا {"ok": False, "error": {...}} — هیچ ساختگی نیست.
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import json
import time
import urllib.request
import urllib.error

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
GECKOTERMINAL_BASE = "https://api.geckoterminal.com/api/v2"
TOOBIT_TICKER24_URL = "https://api.toobit.com/quote/v1/ticker/24hr"

DEFAULT_TIMEOUT_SEC = 20.0
# سقف سخت صف صفحه (بند ۸: جلوگیری از اسکن بی‌پایان) — ۸×۲۵۰ = ۲۰۰۰ دارایی
MARKETS_MAX_PAGES = 8
MARKETS_PER_PAGE = 250
# شبکه‌های واقعی موجود در پاسخ /networks (سولانا در صفحهٔ ۱ نیست و id آن رد شد)
GT_POOL_NETWORKS = ("eth", "bsc")
# فاصلهٔ احترام به نرخ CoinGecko بین فراخوان‌ها (بند ۶: مدیریت 429)
COINGECKO_SPACING_SEC = 2.5
RETRY_AFTER_CAP_SEC = 10.0


def _get_json(url: str, opener=None, timeout: float = DEFAULT_TIMEOUT_SEC):
    """دریافت JSON با مدیریت صادقانهٔ خطا و 429. بازگشت (payload, err)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "MARI-Fleet/1 (research; paper-only)",
        "Accept": "application/json",
    })
    do_open = opener if opener is not None else urllib.request.urlopen
    t0 = time.monotonic()
    try:
        with do_open(req, timeout=timeout) as resp:
            status = getattr(resp, "status", getattr(resp, "code", 200))
            raw = resp.read()
    except urllib.error.HTTPError as e:
        retry_after = e.headers.get("Retry-After") if e.headers else None
        return None, {
            "kind": "http_error", "status": e.code,
            "rate_limited": e.code == 429,
            "retry_after_sec": float(retry_after) if retry_after else None,
        }
    except Exception as e:  # شبکه/تایم‌اوت/پروکسی
        return None, {"kind": "fetch_error", "detail": str(e)[:200]}
    try:
        return json.loads(raw.decode("utf-8")), None
    except Exception:
        return None, {"kind": "parse_error", "status": status,
                      "detail": "پاسخ JSON نامعتبر"}


def _stamp(payload, err, url, t0):
    dt_ms = int((time.monotonic() - t0) * 1000)
    if err is not None:
        return {"ok": False, "url": url, "latency_ms": dt_ms, "error": err}
    return {"ok": True, "url": url, "latency_ms": dt_ms, "payload": payload}


def fetch_global_market(opener=None) -> dict:
    """CoinGecko /global — تجمیع جهانی: ارزش بازار، حجم، دامیننس، دارایی فعال."""
    url = f"{COINGECKO_BASE}/global"
    t0 = time.monotonic()
    payload, err = _get_json(url, opener=opener)
    r = _stamp(payload, err, url, t0)
    if not r["ok"]:
        return r
    d = (payload or {}).get("data") or {}
    r["data"] = {
        "active_cryptocurrencies": d.get("active_cryptocurrencies"),
        "markets": d.get("markets"),
        "total_market_cap_usd": (d.get("total_market_cap") or {}).get("usd"),
        "total_volume_usd": (d.get("total_volume") or {}).get("usd"),
        "btc_dominance_pct": (d.get("market_cap_percentage") or {}).get("btc"),
        "eth_dominance_pct": (d.get("market_cap_percentage") or {}).get("eth"),
        "market_cap_change_24h_pct": d.get("market_cap_change_percentage_24h_usd"),
    }
    return r


def fetch_coins_markets(page: int = 1, per_page: int = MARKETS_PER_PAGE,
                        opener=None) -> dict:
    """CoinGecko /coins/markets — دسته‌ای (بند ۸) با تغییرات ۱س/۲۴س/۷ر/۳۰ر."""
    if page < 1 or page > MARKETS_MAX_PAGES:
        return {"ok": False,
                "error": {"kind": "range_error",
                          "detail": f"page خارج از سقف 1..{MARKETS_MAX_PAGES}"}}
    q = (f"?vs_currency=usd&order=market_cap_desc&per_page={per_page}"
         f"&page={page}&price_change_percentage=1h%2C24h%2C7d%2C30d")
    url = f"{COINGECKO_BASE}/coins/markets{q}"
    t0 = time.monotonic()
    payload, err = _get_json(url, opener=opener)
    r = _stamp(payload, err, url, t0)
    if not r["ok"]:
        return r
    rows = payload if isinstance(payload, list) else []
    r["data"] = {"page": page, "per_page": per_page, "rows": rows,
                 "row_count": len(rows)}
    return r


def fetch_gt_networks(opener=None) -> dict:
    """GeckoTerminal /networks — فهرست شبکه‌های DEX قابل رصد."""
    url = f"{GECKOTERMINAL_BASE}/networks?page=1"
    t0 = time.monotonic()
    payload, err = _get_json(url, opener=opener)
    r = _stamp(payload, err, url, t0)
    if not r["ok"]:
        return r
    nets = []
    for d in (payload or {}).get("data") or []:
        a = d.get("attributes") or {}
        nets.append({"gt_network_id": d.get("id"),
                     "name": a.get("name"),
                     "chain_id": a.get("chain_id"),
                     "coingecko_asset_platform": a.get("coingecko_asset_platform"),
                     "dex_count": a.get("dexes_count"),
                     "pool_count": a.get("pool_count")})
    r["data"] = {"networks": nets, "network_count": len(nets)}
    return r


def fetch_gt_pools(network: str = "eth", page: int = 1, opener=None) -> dict:
    """GeckoTerminal استخرهای برتر شبکه — نقدینگی/حجم/تغییر قیمت DEX."""
    if network not in GT_POOL_NETWORKS:
        return {"ok": False,
                "error": {"kind": "range_error",
                          "detail": f"network مجاز: {GT_POOL_NETWORKS}"}}
    url = (f"{GECKOTERMINAL_BASE}/networks/{network}/pools"
           f"?include=base_token,quote_token&page={page}")
    t0 = time.monotonic()
    payload, err = _get_json(url, opener=opener)
    r = _stamp(payload, err, url, t0)
    if not r["ok"]:
        return r
    pools = []
    for d in (payload or {}).get("data") or []:
        a = d.get("attributes") or {}
        pc = a.get("price_change_percentage") or {}
        vol = a.get("volume_usd") or {}
        rel = {x.get("id"): (x.get("attributes") or {})
               for x in (payload or {}).get("included") or []}
        base_id = (d.get("relationships") or {}).get("base_token", {}) \
            .get("data", {}).get("id")
        base_a = rel.get(base_id, {})
        pools.append({
            "gt_network_id": network,
            "gt_pool_id": d.get("id"),
            "pool_name": a.get("name"),
            "dex_id": a.get("dex_id"),
            "base_token_symbol": base_a.get("symbol"),
            "base_token_name": base_a.get("name"),
            "base_token_gecko_id": (base_a.get("coingecko_coin_id")
                                    or (base_a.get("address") or None)),
            "base_token_address": base_a.get("address"),
            "price_usd": _f(a.get("base_token_price_usd")),
            "change_1h_pct": _f(pc.get("h1")),
            "change_24h_pct": _f(pc.get("h24")),
            "volume_24h_usd": _f(vol.get("h24")),
            "liquidity_usd": _f(a.get("reserve_in_usd")),
            "fdv_usd": _f(a.get("fdv_usd")),
            "market_cap_usd": _f(a.get("market_cap_usd")),
        })
    r["data"] = {"network": network, "page": page, "pools": pools,
                 "pool_count": len(pools)}
    return r


def fetch_toobit_ticker24(opener=None) -> dict:
    """دنیای کامل معاملاتی Toobit (قیمت واقعی قابل‌معامله، بند ۶) — یک فراخوان دسته‌ای."""
    t0 = time.monotonic()
    payload, err = _get_json(TOOBIT_TICKER24_URL, opener=opener)
    r = _stamp(payload, err, TOOBIT_TICKER24_URL, t0)
    if not r["ok"]:
        return r
    rows = payload if isinstance(payload, list) else []
    r["data"] = {"rows": rows, "row_count": len(rows)}
    return r


def _f(x):
    """تبدیل امن عددی — مقدار غایب None می‌ماند، ساختگی نمی‌شود."""
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None
