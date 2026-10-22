# آزمون‌های آفلاین WORLD MARKET CORE (خوشهٔ N) — بدون شبکه، opener تزریقی
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import json
import os
import sys
import tempfile
import time
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.fleet import asset_registry as ar          # noqa: E402
from src.fleet import global_sources as gs          # noqa: E402
from src.fleet.global_market import GlobalMarketCluster  # noqa: E402
from src.fleet.contract import make_message         # noqa: E402


# ---------- قلاب‌های ساختگی ----------

class FakeResp:
    def __init__(self, body, code=200):
        self._body = json.dumps(body).encode()
        self.status = code
        self.code = code

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def make_opener(routes):
    """routes: list of (predicate(url), body|Exception) — پاسخ به ترتیب."""
    def opener(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        for pred, body in routes:
            if pred(url):
                if isinstance(body, Exception):
                    raise body
                return FakeResp(body)
        raise AssertionError(f"URL بدون مسیر قلاب: {url}")
    return opener


NOW_MS = 1730000000000
NOW_ISO = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(NOW_MS / 1000))


def coin(cid, sym, name, price, vol, mcap, ch1h, ch24h, ch7d, ch30d,
         rank=1, last_updated=NOW_ISO):
    return {
        "id": cid, "symbol": sym, "name": name,
        "market_cap_rank": rank,
        "current_price": price, "total_volume": vol, "market_cap": mcap,
        "price_change_percentage_1h_in_currency": ch1h,
        "price_change_percentage_24h_in_currency": ch24h,
        "price_change_percentage_7d_in_currency": ch7d,
        "price_change_percentage_30d_in_currency": ch30d,
        "last_updated": last_updated,
    }


COINS_P1 = [
    coin("bitcoin", "BTC", "Bitcoin", 81000, 5e10, 1.6e12, 0.5, 2.1, 7.3, 11.0, 1),
    coin("wrapped-bitcoin", "WBTC", "Wrapped Bitcoin", 80900, 3e8, 1.2e10,
         0.4, 2.0, 7.1, 10.8, 15),
    coin("worldcoin", "WLD", "Worldcoin", 2.5, 2e8, 9e8, -1.2, -3.3, 4.0, -8.0, 55),
    coin("tether", "USDT", "Tether", 1.0, 9e10, 1.4e11, 0.01, 0.0, 0.02, 0.1, 3),
    coin("dead-coin", "DEAD", "Dead Coin", 0.5, 0.0, 1e6, None, None, None, None, 900),
]
STALE_ISO = time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                          time.gmtime((NOW_MS / 1000) - 7 * 3600))
COINS_P1.append(
    coin("stale-coin", "STALE", "Stale Coin", 3.0, 5e6, 2e7, 99.0, 99.0,
         99.0, 99.0, 700, last_updated=STALE_ISO))

TOOBIT_BODY = [
    {"t": NOW_MS - 60000, "s": "BTCUSDT", "c": "81000",
     "o": "79411", "h": "82000", "l": "79000", "v": "6172",
     "qv": "500000000", "pc": "1589", "pcp": "2.0"},
    {"t": NOW_MS - 60000, "s": "ETHUSDT", "c": "3000",
     "o": "3045", "h": "3050", "l": "2980", "v": "66666",
     "qv": "200000000", "pc": "-45", "pcp": "-1.5"},
    {"t": NOW_MS - 60000, "s": "USDCUSDT", "c": "1.0",
     "o": "1.0", "h": "1.0", "l": "1.0", "v": "10000000",
     "qv": "10000000", "pc": "0.0001", "pcp": "0.01"},
]

GLOBAL_BODY = {"data": {
    "active_cryptocurrencies": 17000, "markets": 1200,
    "total_market_cap": {"usd": 2.7e12},
    "total_volume": {"usd": 1.1e11},
    "market_cap_percentage": {"btc": 54.1, "eth": 12.3},
    "market_cap_change_percentage_24h_usd": 1.8,
}}

GT_NETWORKS = {"data": [
    {"id": "eth", "attributes": {"name": "Ethereum", "chain_id": "1",
                                 "dexes_count": 900, "pool_count": 200000}},
    {"id": "sol", "attributes": {"name": "Solana", "chain_id": "solana",
                                 "dexes_count": 120, "pool_count": 300000}},
]}


def gt_pool(pid, name, sym, price, ch1, ch24, vol, liq):
    return {"gt_network_id": "eth", "gt_pool_id": pid, "pool_name": name,
            "dex_id": "uniswap-v3", "base_token_symbol": sym,
            "base_token_name": name, "base_token_gecko_id": None,
            "base_token_address": f"0x{pid}", "price_usd": price,
            "change_1h_pct": ch1, "change_24h_pct": ch24,
            "volume_24h_usd": vol, "liquidity_usd": liq,
            "fdv_usd": None, "market_cap_usd": None}


def gt_body(pools):
    return {"data": [
        {"id": p["gt_pool_id"],
         "attributes": {
             "name": p["pool_name"], "dex_id": "uniswap-v3",
             "base_token_price_usd": str(p["price_usd"]),
             "price_change_percentage": {"h1": str(p["change_1h_pct"]),
                                         "h24": str(p["change_24h_pct"])},
             "volume_usd": {"h24": str(p["volume_24h_usd"])},
             "reserve_in_usd": str(p["liquidity_usd"]),
             "fdv_usd": None, "market_cap_usd": None},
         "relationships": {"base_token": {"data": {"id": f"eth:{p['base_token_address']}"}}}}
        for p in pools],
        "included": [
            {"id": f"eth:{p['base_token_address']}",
             "attributes": {"symbol": p["base_token_symbol"],
                            "name": p["base_token_name"],
                            "address": p["base_token_address"]}}
            for p in pools]}


def full_routes(markets_pages=None):
    routes = [
        (lambda u: "ticker/24hr" in u, TOOBIT_BODY),
        (lambda u: "/global" in u, GLOBAL_BODY),
        (lambda u: "/networks?page=1" in u, GT_NETWORKS),
    ]
    pages = markets_pages or {1: COINS_P1, 2: []}
    for pnum, rows in pages.items():
        routes.append(
            (lambda u, p=pnum: "/coins/markets" in u and
             (f"page={p}&" in u or u.endswith(f"page={p}")), rows))
    for net in ("eth", "bsc"):
        routes.append(
            (lambda u, n=net: "/pools" in u and f"/networks/{n}/" in u,
             gt_body([gt_pool(f"{net}-pool-1", f"{net} pool", "FOO",
                              1.0, 1.5, 4.2, 1e6, 5e5)
                      ] if net == "eth" else [])))
    return routes


# ---------- ۱) هویت چندبعدی ----------

def test_identity_separation():
    rows = ar.normalize_coingecko_rows(COINS_P1, NOW_MS, 1)
    ids = {r["identity"] for r in rows}
    # BTC و WBTC هر دو نماد نزدیک دارند اما asset_id جدا — ادغام ممنوع
    assert "gecko:bitcoin" in ids and "gecko:wrapped-bitcoin" in ids
    assert len(ids) == len(rows)
    # استخر DEX فضای هویتی مستقل دارد
    pr = ar.normalize_gt_pools(
        [gt_pool("pool-1", "ETH/USDC", "ETH", 3000, 1, 2, 1e6, 5e5)],
        "eth", NOW_MS)
    assert pr[0]["identity"] == "dex:eth:pool-1"
    assert pr[0]["contract"] == "0xpool-1"


def test_wrapped_hint_no_false_positive():
    rows = ar.normalize_coingecko_rows(COINS_P1, NOW_MS, 1)
    by_sym = {r["symbol"]: r for r in rows}
    assert by_sym["WBTC"]["wrapped_hint"] is True
    assert by_sym["WLD"]["wrapped_hint"] is False   # حدس «W اول» ممنوع
    assert by_sym["BTC"]["wrapped_hint"] is False


def test_stablecoin_labeled_not_removed():
    rows = ar.normalize_coingecko_rows(COINS_P1, NOW_MS, 1)
    usdt = [r for r in rows if r["symbol"] == "USDT"]
    assert len(usdt) == 1 and usdt[0]["stablecoin"] is True
    # در فهرست دارایی‌ها می‌ماند (coverage.total شامل اوست)
    cov = ar.coverage(rows)
    assert cov["discovered"] == len(rows)


# ---------- ۲) کیفیت داده ----------

def test_quality_flags():
    rows = ar.normalize_coingecko_rows(COINS_P1, NOW_MS, 1)
    by_sym = {r["symbol"]: r for r in rows}
    assert by_sym["DEAD"]["quality"]["zero_volume"] is True
    assert by_sym["DEAD"]["healthy"] is False
    assert by_sym["STALE"]["quality"]["stale_price"] is True
    assert by_sym["STALE"]["healthy"] is False
    assert by_sym["BTC"]["healthy"] is True
    cov = ar.coverage(rows)
    assert cov["stale"] == 1 and cov["no_price"] == 0


# ---------- ۳) پهنای بازار ----------

def test_breadth_math():
    rows = ar.normalize_coingecko_rows(COINS_P1, NOW_MS, 1)
    b24 = ar.breadth(rows, "24h")
    # واجد شرایط: BTC، WBTC، WLD، STALE(کهنه→حذف)، DEAD(بدون تغییر→حذف)، USDT(استیبل→حذف)
    assert b24["counted"] == 3
    assert b24["up"] == 2 and b24["down"] == 1 and b24["flat"] == 0
    assert b24["excluded"]["stablecoin"] == 1
    assert b24["excluded"]["stale"] == 1      # فقط STALE (قیمت کهنه)
    assert b24["excluded"]["no_change"] == 1  # DEAD: فیلد تغییر غایب — بدون فرض جهت
    assert b24["gt_2pct"] == 1   # فقط BTC: 2.1>2 — WBTC دقیقاً 2.0، بیش از ۲٪ نیست
    assert b24["gt_5pct"] == 0
    assert b24["ad_ratio"] == round(2 / 1, 3)
    assert b24["up_pct"] == round(100 * 2 / 3, 2)


def test_breadth_empty_honest():
    b = ar.breadth([], "1h")
    assert b["counted"] == 0 and b["up_pct"] is None and b["ad_ratio"] is None


def test_top_movers_excludes_stable_and_stale():
    rows = ar.normalize_coingecko_rows(COINS_P1, NOW_MS, 1)
    mv = ar.top_movers(rows, "24h", k=5)
    syms = {g["symbol"] for g in mv["gainers"]} | \
           {l["symbol"] for l in mv["losers"]}
    assert "USDT" not in syms and "STALE" not in syms
    assert mv["gainers"][0]["symbol"] == "BTC"
    assert mv["losers"][0]["symbol"] == "WLD"
    # هر موور منبع و زمان مشاهده دارد (بند ۷)
    for x in mv["gainers"] + mv["losers"]:
        assert x["primary_source"] and x["data_asof_ms"]


# ---------- ۴) صف صفحه سقف‌دار ----------

def test_page_queue_bounded():
    with tempfile.TemporaryDirectory() as td:
        st = {"next_page": 9, "last_success_ms": {}}
        ar.save_page_queue(td, st)
        st2 = ar.load_page_queue(td)
        assert st2["next_page"] == 1  # چرخش به ابتدا، نه اسکن بی‌پایان
        st3 = {"next_page": 7, "last_success_ms": {"markets_p7": NOW_MS}}
        ar.save_page_queue(td, st3)
        assert ar.load_page_queue(td)["next_page"] == 7


def test_markets_page_range_guard():
    r = gs.fetch_coins_markets(page=99)
    assert r["ok"] is False and r["error"]["kind"] == "range_error"


# ---------- ۵) منابع با 429 و خطا ----------

def test_fetch_429_retry_then_ok():
    calls = {"n": 0}
    def opener(req, timeout=10):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 429, "slow down",
                                         {"Retry-After": "0"}, None)
        return FakeResp(GLOBAL_BODY)
    # تلاش مجدد کنترل‌شده در پوستهٔ خوشه است (فاز ۳) — همان‌جا آزمون می‌شود
    cl = GlobalMarketCluster(state_dir=None, opener=opener)
    r = cl._fetch(gs.fetch_global_market)
    assert r["ok"] is True and calls["n"] == 2
    assert r["data"]["btc_dominance_pct"] == 54.1


def test_fetch_network_error_honest():
    def opener(req, timeout=10):
        raise OSError("network down")
    r = gs.fetch_global_market(opener=opener)
    assert r["ok"] is False and r["error"]["kind"] == "fetch_error"


# ---------- ۶) خوشهٔ N کامل آفلاین ----------

def test_cluster_n_end_to_end_offline():
    gs.COINGECKO_SPACING_SEC = 0  # آزمون آفلاین بدون معطلی نرخ
    with tempfile.TemporaryDirectory() as td:
        cl = GlobalMarketCluster(state_dir=td, opener=make_opener(full_routes()))
        events = cl.run({"cluster_id": "N", "symbol": "GLOBAL",
                         "task_id": "t-n-1",
                         "ctx": {"data_asof_ms": NOW_MS}})
        types = sorted(e["event_type"] for e in events)
        assert types == ["BREADTH_WINDOW", "GLOBAL_DISCOVERY"]
        for e in events:
            assert e["cluster_id"] == "N"
            assert e["validation_status"] == "OBSERVED"
            assert e["event_time_ms"] == NOW_MS
            assert e["schema_version"] and e["safety"]["mode"]
        disc = events[0]
        cov = disc["features"]["coverage"]
        # ۳ جفت CEX + ۶ سکهٔ صفحهٔ ۱ + ۱ استخر eth = ۱۰ بازار
        assert cov["discovered"] == 10
        assert cov["by_kind"]["cex"] == 3
        assert cov["by_kind"]["cex-aggregated"] == 6
        assert cov["by_kind"]["dex-pool"] == 1
        br = events[1]["features"]["breadth"]
        # واجد ۲۴س: BTC، WBTC، WLD، FOO، BTCUSDT، ETHUSDT = ۶
        assert br["24h"]["counted"] == 6
        assert br["24h"]["up"] == 4 and br["24h"]["down"] == 2
        assert br["24h"]["excluded"]["stablecoin"] == 2  # USDT(gecko)+USDC(cex)
        assert br["24h"]["excluded"]["stale"] == 1
        assert br["24h"]["excluded"]["no_change"] == 1
        assert br["1h"]["counted"] == 4  # فقط gecko+pools 1h دارند؛ CEX فقط 24s
        # ماندگاری: اسنپ‌شات + دفتر خلاصه + وضعیت صف
        assert os.path.exists(os.path.join(td, "global-assets-snapshot.json"))
        reg = open(os.path.join(td, "asset-registry.jsonl"), encoding="utf-8").read()
        assert "mari.asset-registry/v1" in reg
        st = ar.load_page_queue(td)
        assert st["next_page"] == 3  # از ۱ شروع، ۲ صفحه مصرف → ۳
        assert st["last_success_ms"]["markets_p1"] == NOW_MS


def test_cluster_n_source_failure_is_isolated():
    def opener(req, timeout=10):
        raise OSError("all down")
    cl = GlobalMarketCluster(state_dir=None, opener=opener)
    events = cl.run({"cluster_id": "N", "symbol": "GLOBAL",
                     "task_id": "t-n-2", "ctx": {"data_asof_ms": NOW_MS}})
    # حتی با شکست کامل منابع، رویدادها صادقانه صادر می‌شوند (صفر ساختگی)
    assert len(events) == 2
    cov = events[0]["features"]["coverage"]
    assert cov["discovered"] == 0
    srcs = events[0]["features"]["sources"]
    assert all(s["ok"] is False for s in srcs.values())
    assert any("پاسخ نداد" in u for e in events for u in e["uncertainty"])


def test_make_message_cluster_guard():
    try:
        make_message(cluster_id="Z", symbol="X", event_type="T",
                     event_time_ms=NOW_MS, data_asof_ms=NOW_MS)
        assert False, "cluster_id نامعتبر باید رد شود"
    except ValueError:
        assert True
