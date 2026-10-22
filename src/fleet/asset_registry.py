# دفتر دارایی جهانی — WORLD MARKET CORE (فاز ۲)
# هویت چندبعدی: نماد ≠ asset_id ≠ شبکه ≠ قرارداد ≠ صرافی (ادغام کورکورانه ممنوع).
# کیفیت داده صادقانه ثبت می‌شود؛ دارایی بی‌داده هیچ‌گاه صعودی/نزولی فرض نمی‌شود.
# READ ONLY | PAPER ONLY | NO LIVE ORDERS

import json
import os
import statistics

from .global_sources import MARKETS_MAX_PAGES

REGISTRY_VERSION = "mari.asset-registry/v1"
# آستانهٔ تازگی: قیمت قدیمی‌تر از این = کهنه (بند ۶)
STALE_MS = 6 * 60 * 60 * 1000  # ۶ ساعت
# برچسب استیبل‌کوین بر پایهٔ نماد — فقط برچسب، هرگز حذف از فهرست (بند ۶)
STABLE_SYMBOLS = {
    "USDT", "USDC", "DAI", "FDUSD", "TUSD", "USDE", "BUSD", "USDP",
    "PYUSD", "FRAX", "USDD", "LUSD", "SUSD", "USDS", "USD1", "USDF",
}

# برچسب نسخهٔ رپ‌شده — فقط مجموعهٔ صریح؛ حدس «W اول نماد» ممنوع (WLD≠WBTC)
KNOWN_WRAPPED = {
    "WBTC", "WETH", "WSTETH", "RETH", "CBETH", "WBETH", "WEETH",
    "WBNB", "WMATIC", "WAVAX", "WFTM", "JITOSOL", "JUPSOL", "MSOL",
    "STSOL", "BSOL", "SCNSOL",
}

PRICEABLE_MIN_USD_VOL = 1.0     # حداقل حجم ۲۴س برای «قابل قیمت‌گذاری فعال»
MIN_RANK_FRESH = 1               # رتبهٔ دارایی‌های پیش‌رو صف (اولویت‌بندی)


# ---------- هویت ----------

def identity_cex_gecko(row: dict) -> str:
    """هویت ردیف CoinGecko = شناسهٔ جهانی خودش (دقیق‌تر از نماد)."""
    return f"gecko:{row.get('id')}"


def identity_dex_pool(pool: dict) -> str:
    """هویت استخر DEX = شبکه + شناسهٔ استخر (هر استخر بازار مستقل است)."""
    return f"dex:{pool.get('gt_network_id')}:{pool.get('gt_pool_id')}"


# ---------- نرمال‌سازی CoinGecko ----------

def normalize_coingecko_rows(rows: list, fetched_at_ms: int,
                             page: int) -> list:
    out = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        last_updated = row.get("last_updated")
        asof_ms = _parse_iso_ms(last_updated)
        sym = (row.get("symbol") or "").upper()
        age_ms = None if asof_ms is None else max(0, fetched_at_ms - asof_ms)
        stale = age_ms is None or age_ms > STALE_MS
        price = _f(row.get("current_price"))
        vol = _f(row.get("total_volume"))
        mcap = _f(row.get("market_cap"))
        ch = {w: _f(row.get(f"price_change_percentage_{w}_in_currency"))
              for w in ("1h", "24h", "7d", "30d")}
        quality = {
            "has_price": price is not None,
            "has_volume": vol is not None,
            "zero_volume": vol is not None and vol <= 0.0,
            "stale_price": stale,
            "age_ms": age_ms,
        }
        healthy = (price is not None and vol is not None and vol > 0.0
                   and not stale)
        out.append({
            "identity": identity_cex_gecko(row),
            "kind": "cex-aggregated",
            "asset_id": row.get("id"),
            "symbol": sym,
            "name": row.get("name"),
            "rank": _f(row.get("market_cap_rank")),
            "network": None,            # CoinGecko سطح دارایی است، نه قرارداد
            "contract": None,
            "primary_source": "coingecko/coins-markets",
            "source_page": page,
            "price_usd": price,
            "market_cap_usd": mcap,
            "volume_24h_usd": vol,
            "liquidity_usd": None,
            "change_pct": ch,
            "wrapped_hint": sym in KNOWN_WRAPPED,
            "stablecoin": sym in STABLE_SYMBOLS,
            "fetched_at_ms": fetched_at_ms,
            "data_asof_ms": asof_ms,
            "quality": quality,
            "healthy": healthy,
        })
    return out


# ---------- نرمال‌سازی استخرهای DEX ----------

def normalize_gt_pools(pools: list, network: str, fetched_at_ms: int) -> list:
    out = []
    for p in pools or []:
        price = p.get("price_usd")
        vol = p.get("volume_24h_usd")
        liq = p.get("liquidity_usd")
        # GeckoTerminal بدون last_updated ردیفی؛ تازگی = زمان دریافت خود منبع
        quality = {
            "has_price": price is not None,
            "has_volume": vol is not None,
            "zero_volume": vol is not None and vol <= 0.0,
            "stale_price": False,   # دریافت زندهٔ همین چرخه — کهنه نیست
            "age_ms": 0,
        }
        healthy = (price is not None and (vol or 0) > 0.0
                   and (liq or 0) > 0.0)
        out.append({
            "identity": identity_dex_pool(p),
            "kind": "dex-pool",
            "asset_id": p.get("gt_pool_id"),
            "symbol": (p.get("base_token_symbol") or "").upper(),
            "name": p.get("base_token_name"),
            "rank": None,
            "network": network,
            "contract": p.get("base_token_address"),
            "primary_source": f"geckoterminal/pools/{network}",
            "source_page": p.get("page", 1),
            "price_usd": price,
            "market_cap_usd": p.get("market_cap_usd"),
            "volume_24h_usd": vol,
            "liquidity_usd": liq,
            "change_pct": {"1h": p.get("change_1h_pct"),
                           "24h": p.get("change_24h_pct"),
                           "7d": None, "30d": None},
            "wrapped_hint": False,
            "stablecoin": (p.get("base_token_symbol") or "").upper()
                          in STABLE_SYMBOLS,
            "fetched_at_ms": fetched_at_ms,
            "data_asof_ms": fetched_at_ms,
            "quality": quality,
            "healthy": healthy,
        })
    return out


# ---------- نرمال‌سازی تیکر Toobit (بازار واقعی قابل‌معامله) ----------

def normalize_toobit_rows(rows: list, fetched_at_ms: int) -> list:
    """هر جفت معاملاتی = یک بازار مستقل با هویت خودش (بند ۳).
    فقط ۲۴س از منبع هست — ۱س/۷ر/۳۰ر None می‌ماند، ساختگی نمی‌شود."""
    out = []
    for row in rows or []:
        sym = (row.get("s") or "").upper()
        if not sym:
            continue
        base = sym[:-4] if sym.endswith("USDT") else sym
        price = _f(row.get("c"))
        qvol = _f(row.get("qv"))
        pcp = _f(row.get("pcp"))
        asof_ms = _f(row.get("t"))
        asof_ms = int(asof_ms) if asof_ms is not None else None
        age_ms = None if asof_ms is None else max(0, fetched_at_ms - asof_ms)
        stale = age_ms is None or age_ms > STALE_MS
        healthy = (price is not None and (qvol or 0) > 0.0 and not stale)
        out.append({
            "identity": f"cex:toobit:spot:{sym}",
            "kind": "cex",
            "asset_id": sym,
            "symbol": base,
            "name": None,
            "rank": None,
            "network": None,
            "contract": None,
            "primary_source": "toobit/ticker24",
            "source_page": None,
            "price_usd": price,
            "market_cap_usd": None,
            "volume_24h_usd": qvol,
            "liquidity_usd": None,
            "change_pct": {"1h": None, "24h": pcp, "7d": None, "30d": None},
            "wrapped_hint": base in KNOWN_WRAPPED,
            "stablecoin": base in STABLE_SYMBOLS,
            "fetched_at_ms": fetched_at_ms,
            "data_asof_ms": asof_ms,
            "quality": {
                "has_price": price is not None,
                "has_volume": qvol is not None,
                "zero_volume": qvol is not None and qvol <= 0.0,
                "stale_price": stale,
                "age_ms": age_ms,
            },
            "healthy": healthy,
        })
    return out


# ---------- پهنای بازار (بند ۷) — فقط تازه‌های غیراستیبل ----------

def breadth(rows: list, window: str) -> dict:
    """شمارش واقعی از دادهٔ دارای زمان؛ بدون داده = بدون فرض جهت."""
    chs, ups, downs, flats = [], 0, 0, 0
    b2 = b5 = b10 = 0
    excluded = {"stablecoin": 0, "stale": 0, "no_change": 0}
    for r in rows or []:
        if r.get("stablecoin"):
            excluded["stablecoin"] += 1
            continue
        if r.get("quality", {}).get("stale_price") or \
                not r.get("quality", {}).get("has_price"):
            excluded["stale"] += 1
            continue
        v = (r.get("change_pct") or {}).get(window)
        if v is None:
            excluded["no_change"] += 1
            continue
        chs.append(v)
        if v > 0:
            ups += 1
        elif v < 0:
            downs += 1
        else:
            flats += 1
        if v > 2:
            b2 += 1
        if v > 5:
            b5 += 1
        if v > 10:
            b10 += 1
    n = len(chs)
    total = ups + downs + flats
    med = statistics.median(chs) if chs else None
    return {
        "window": window,
        "counted": n,
        "up": ups, "down": downs, "flat": flats,
        "up_pct": round(100 * ups / total, 2) if total else None,
        "down_pct": round(100 * downs / total, 2) if total else None,
        "ad_ratio": round(ups / downs, 3) if downs > 0 else
                    (None if ups == 0 else "inf"),
        "median_change_pct": round(med, 4) if med is not None else None,
        "gt_2pct": b2, "gt_5pct": b5, "gt_10pct": b10,
        "excluded": excluded,
    }


def coverage(rows: list) -> dict:
    """پوشش (بند ۳/۷): کشف‌شده/قابل‌قیمت‌گذاری/بازار فعال/دادهٔ سالم."""
    total = len(rows or [])
    priceable = sum(1 for r in rows if r.get("price_usd") is not None)
    active = sum(1 for r in rows
                 if (r.get("volume_24h_usd") or 0) > PRICEABLE_MIN_USD_VOL)
    healthy = sum(1 for r in rows if r.get("healthy"))
    stale = sum(1 for r in rows if r.get("quality", {}).get("stale_price"))
    no_price = total - priceable
    by_kind = {}
    for r in rows:
        by_kind[r.get("kind")] = by_kind.get(r.get("kind"), 0) + 1
    return {"discovered": total, "priceable": priceable, "active_market": active,
            "healthy_data": healthy, "stale": stale, "no_price": no_price,
            "by_kind": by_kind}


def top_movers(rows: list, window: str, k: int = 10) -> dict:
    """برترین رشدها/افت‌ها فقط از تازه‌های غیراستیبل با حجم (بند ۷)."""
    elig = []
    for r in rows or []:
        if r.get("stablecoin") or r.get("quality", {}).get("stale_price"):
            continue
        v = (r.get("change_pct") or {}).get(window)
        if v is None or (r.get("volume_24h_usd") or 0) <= 0:
            continue
        elig.append((v, r))
    elig.sort(key=lambda t: t[0], reverse=True)
    def _brief(v, r):
        return {"identity": r["identity"], "symbol": r.get("symbol"),
                "name": r.get("name"), "kind": r.get("kind"),
                "network": r.get("network"),
                "price_usd": r.get("price_usd"),
                "volume_24h_usd": r.get("volume_24h_usd"),
                "liquidity_usd": r.get("liquidity_usd"),
                "primary_source": r.get("primary_source"),
                "change_pct": v, "data_asof_ms": r.get("data_asof_ms")}
    gainers = [_brief(v, r) for v, r in elig[:k]]
    losers = [_brief(v, r) for v, r in reversed(elig[-k:]) if v < 0]
    return {"window": window, "gainers": gainers, "losers": losers}


# ---------- ماندگاری (بند ۸) ----------

def save_snapshot(state_dir: str, snapshot: dict) -> str:
    """فهرست کامل آخرین دریافت (رونویسی) — ذخیرهٔ پایدار + زمان موفق."""
    path = os.path.join(state_dir, "global-assets-snapshot.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def append_registry_line(state_dir: str, doc: dict) -> str:
    """دفتر append-only خلاصهٔ چرخه‌ها (شمارش/پهنای بازار/سلامت منبع)."""
    path = os.path.join(state_dir, "asset-registry.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(doc, ensure_ascii=False) + "\n")
    return path


def load_page_queue(state_dir: str) -> dict:
    """صف صفحه‌ها با سقف سخت — بعد از سقف به ابتدا برمی‌گردد (بی‌پایان ممنوع)."""
    path = os.path.join(state_dir, "global-core-state.json")
    st = {"next_page": 1, "last_success_ms": {}}
    if os.path.exists(path):
        try:
            st.update({k: v for k, v in
                       json.load(open(path, encoding="utf-8")).items()
                       if k in ("next_page", "last_success_ms")})
        except Exception:
            pass
    return st


def save_page_queue(state_dir: str, st: dict) -> str:
    path = os.path.join(state_dir, "global-core-state.json")
    nxt = int(st.get("next_page", 1))
    # ورودی بالاتر از سقف = چرخش به ابتدا (اسکن بی‌پایان ممنوع)
    st["next_page"] = max(1, nxt) if nxt <= MARKETS_MAX_PAGES else 1
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(st, fh, ensure_ascii=False)
    os.replace(tmp, path)
    return path


def _parse_iso_ms(s):
    if not s:
        return None
    try:
        from datetime import datetime, timezone
        s2 = s.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s2)
                   .timestamp() * 1000)
    except Exception:
        return None


def _f(x):
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None
