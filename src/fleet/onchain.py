# MARI — خوشهٔ I: On-Chain & New Token (بند ۳-I دستور)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# منابع رایگان بدون کلید: CoinGecko (توکن تازه/پرتوجه، هویت دارایی) + mempool.space
# (شبکهٔ بیت‌کوین). قواعد صریح دستور:
#   - نماد ≠ شناسهٔ دارایی؛ شبکه و قرارداد جدا ثبت می‌شوند (تفکیک دارایی هم‌نام)
#   - «تازه‌افزوده‌شدن در منبع» ≠ «کشف توکن نوپدید» — و کشف توکن ≠ سیگنال خرید
#   - جلوگیری از ثبت تکراری با دفتر Seen append-only (asset_id)
#   - نبود داده = UNAVAILABLE با علت صریح — دادهٔ ساختگی ممنوع
#   - نشانه‌های کلاهبرداری = فرضیهٔ ابطال‌پذیر (HYPOTHESIS)، هرگز مشاهده

import json
import os
from datetime import datetime, timezone

from .contract import make_message

METHOD = "onchain_newtoken_watch/v1"

# آستانه‌های نشانهٔ ریسک — در کد ثبت و در پیام به‌عنوان آستانهٔ ساختگی-پرهیز
# گزارش می‌شوند؛ همهٔ این آستانه‌ها «قاعدهٔ اکتشافی» هستند نه حقیقت.
FLAG_VOLUME_RATIO_MAX = 5.0     # حجم ۲۴ساعت / مارکت‌کپ غیرعادی بالا
FLAG_PRICE_CHANGE_MAX = 100.0   # تغییر ۲۴ساعت به درصد — |x| بیش از حد
FLAG_UNRANKED_BEYOND = 5000     # بدون رتبه یا رتبهٔ خیلی پایین
STALE_SOURCE_MS = 6 * 3_600_000  # last_updated قدیمی‌تر از ۶ ساعت = کهنه
NEW_TOKENS_CAP = 10             # سقف رویداد توکن تازه در هر چرخه
TRENDING_CAP = 10               # سقف رویداد پرتوجه در هر چرخه
IDENTITY_CALLS_CAP = 3          # سقف فراخوان هویت (قرارداد/شبکه) در هر چرخه


class SeenAssetLedger:
    """دفتر asset_idهای مشاهده‌شده — «توکن جدید» فقط یعنی «اولین مشاهده توسط
    این سامانه». append-only، سقف‌دار، و خرابی پایداری هرگز خوشه را نمی‌شکند."""

    def __init__(self, path: str = None, cap: int = 5000):
        self.path = path
        self.cap = cap
        self.ids = set()
        self.persist_error = None
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    self.ids = {str(x) for x in data}
            except (json.JSONDecodeError, OSError) as err:
                # دفتر خراب = از نو (بدون ادعای حافظهٔ دروغین)؛ خطا ثبت می‌شود
                self.persist_error = f"load: {type(err).__name__}"

    def is_new(self, asset_id: str) -> bool:
        return str(asset_id) not in self.ids

    def mark(self, asset_id: str) -> None:
        self.ids.add(str(asset_id))
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            keep = list(self.ids)[-self.cap:]
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(keep, fh)
            self.persist_error = None
        except OSError as err:
            self.persist_error = f"write: {type(err).__name__}: {err}"


def _iso_to_ms(iso: str):
    """آخرین به‌روزرسانی منبع (ISO) → میلی‌ثانیه؛ قابل تجزیه نبود → None."""
    if not iso or not isinstance(iso, str):
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def scam_flags(coin: dict) -> dict:
    """نشانه‌های عددی ریسک از فیلدهای واقعی منبع — صرفاً اکتشافی (HEURISTIC).
    هر فلگ: نام، مقدار مشاهده‌شده، آستانه. دادهٔ غایب فلگ نمی‌شود؛ DATA_INCOMPLETE ثبت می‌شود."""
    flags = {}
    incomplete = []
    mcap = coin.get("market_cap")
    volume = coin.get("total_volume")
    change = coin.get("price_change_24h_pct")
    rank = coin.get("market_cap_rank")
    if mcap is None:
        incomplete.append("market_cap")
    if volume is None:
        incomplete.append("total_volume")
    if change is None:
        incomplete.append("price_change_24h_pct")
    if isinstance(mcap, (int, float)) and mcap > 0 and isinstance(volume, (int, float)):
        ratio = volume / mcap
        if ratio > FLAG_VOLUME_RATIO_MAX:
            flags["FLAG_VOLUME_RATIO_EXTREME"] = {
                "value": round(ratio, 4), "threshold": FLAG_VOLUME_RATIO_MAX}
    if isinstance(change, (int, float)) and abs(change) > FLAG_PRICE_CHANGE_MAX:
        flags["FLAG_PRICE_EXTREME_24H"] = {
            "value": round(change, 4), "threshold": FLAG_PRICE_CHANGE_MAX}
    if not isinstance(rank, int) or rank > FLAG_UNRANKED_BEYOND:
        flags["FLAG_UNRANKED"] = {"value": rank,
                                  "threshold": FLAG_UNRANKED_BEYOND}
    return {"flags": flags, "data_incomplete": incomplete}


def analyze(*, data_asof_ms: int, task_id: str = None,
            seen_ledger: SeenAssetLedger = None,
            trending_fetcher=None, newly_fetcher=None,
            identity_fetcher=None, network_fetcher=None) -> list:
    """یک چرخهٔ کامل خوشهٔ I. fetcherها تزریق‌پذیرند (آزمون آفلاین بدون شبکه).
    شکست هر منبع ثبت و ادامه — نبود داده هرگز دادهٔ ساختگی تولید نمی‌کند."""
    from . import sources as sources_mod
    tf = trending_fetcher or sources_mod.fetch_trending_tokens
    nf = newly_fetcher or sources_mod.fetch_newly_added
    idf = identity_fetcher or sources_mod.fetch_token_identity
    netf = network_fetcher or sources_mod.fetch_btc_network
    ledger = seen_ledger or SeenAssetLedger()
    messages = []
    sources_used = []
    sources_failed = {}

    # ۱) شبکهٔ بیت‌کوین — مشاهدهٔ خام، بدون هیچ ادعای جهت‌دار
    net = netf()
    if net.get("ok"):
        sources_used.append(net.get("source", "mempool.space/v1"))
        messages.append(make_message(
            cluster_id="I", symbol="BTC", event_type="ONCHAIN_NETWORK_SNAPSHOT",
            event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
            exchange="mempool.space", market_type="onchain", timeframe=None,
            features={"fees": net.get("fees"), "difficulty": net.get("difficulty"),
                      "partial": net.get("partial", False)},
            evidence={"source": net.get("source", "mempool.space/v1"),
                      "method": METHOD},
            validation_status="OBSERVED", task_id=task_id,
            uncertainty=["تصویر لحظه‌ای شبکه — هیچ استنتاج قیمتی از آن نشده است"],
        ))
    else:
        sources_failed["btc_network"] = net.get("error", {})

    # ۲) توکن‌های پرتوجه — توجه بازار، نه سیگنال خرید
    trend = tf()
    if trend.get("ok"):
        sources_used.append(trend.get("source", "coingecko.trending/v3"))
        for tok in trend.get("tokens", [])[:TRENDING_CAP]:
            messages.append(make_message(
                cluster_id="I", symbol=tok["symbol"] or tok["asset_id"],
                event_type="TRENDING_TOKEN_ATTENTION",
                event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
                exchange="coingecko", market_type="spot", timeframe=None,
                features={"asset_id": tok["asset_id"], "name": tok["name"],
                          "market_cap_rank": tok.get("market_cap_rank"),
                          "price_usd": tok.get("price_usd")},
                evidence={"source": trend.get("source", "coingecko.trending/v3"),
                          "method": METHOD, "asset_id": tok["asset_id"]},
                validation_status="OBSERVED", task_id=task_id,
                uncertainty=["توجه بازار مشاهده است، نه فرضیه و نه سیگنال خرید"],
            ))
    else:
        sources_failed["trending"] = trend.get("error", {})

    # ۳) توکن‌های تازه‌افزوده‌شده — با دفتر seen و تفکیک هویت
    #    اگر دستهٔ newly-added در دسترس نبود (مثلاً 404/429 از سمت منبع)،
    #    «اولین مشاهده» روی فهرست توجه (سطح دارایی، نه فهرست صرافی) ادامه می‌یابد —
    #    هرگز «افزوده‌شدن به فهرست» به‌تنهایی کشف اعلام نمی‌شود (بند ۳-I).
    fresh = nf()
    identity_calls = 0
    newly_basis = fresh.get("source", "coingecko.markets/v3") if fresh.get("ok") else None
    candidates = fresh.get("coins", [])[:NEW_TOKENS_CAP] if fresh.get("ok") else []
    if fresh.get("ok"):
        sources_used.append(newly_basis)
    else:
        sources_failed["newly_added"] = fresh.get("error", {})
    if not fresh.get("ok") and trend.get("ok"):
        # جایگزین صادقانه: نامزدهای اولین‌مشاهده از فهرست توجه
        newly_basis = trend.get("source", "coingecko.trending/v3")
        candidates = [{
            "asset_id": t["asset_id"], "symbol": t["symbol"],
            "name": t["name"], "market_cap": None,
            "market_cap_rank": t.get("market_cap_rank"),
            "total_volume": None, "price_change_24h_pct": None,
            "last_updated": None,
        } for t in trend.get("tokens", [])[:NEW_TOKENS_CAP]]
    for coin in candidates:
        asset_id = coin["asset_id"]
        stale = None
        lu_ms = _iso_to_ms(coin.get("last_updated"))
        if lu_ms is not None and (data_asof_ms - lu_ms) > STALE_SOURCE_MS:
            stale = "منبع برای این دارایی بیش از ۶ ساعت به‌روزنشده"
        flags_info = scam_flags(coin)
        if ledger.is_new(asset_id):
            ledger.mark(asset_id)
            uncertainty_first = [
                "«اولین مشاهده توسط این سامانه» است، نه ادعای نوپدیدی جهانی",
            ]
            if not fresh.get("ok"):
                uncertainty_first.append(
                    "مبنای مشاهده، فهرست توجه منبع است (دستهٔ تازه‌افزوده‌شده "
                    "در دسترس نبود) — این رویداد کشف جهانی نیست")
            messages.append(make_message(
                cluster_id="I", symbol=coin["symbol"] or asset_id,
                event_type="NEW_TOKEN_FIRST_SEEN",
                event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
                exchange="coingecko", market_type="spot", timeframe=None,
                features={"asset_id": asset_id, "name": coin.get("name"),
                          "market_cap": coin.get("market_cap"),
                          "market_cap_rank": coin.get("market_cap_rank"),
                          "last_updated": coin.get("last_updated"),
                          "first_seen_by": "MARI-fleet-I",
                          "basis": newly_basis},
                evidence={"source": newly_basis,
                          "method": METHOD, "asset_id": asset_id},
                validation_status="OBSERVED", task_id=task_id,
                uncertainty=uncertainty_first + [
                    "افزوده‌شدن به فهرست منبع به‌تنهایی کشف معتبر نیست؛ "
                    "اعتبارسنجی مستقل لازم است",
                    "کشف توکن ≠ سیگنال خرید",
                ] + ([stale] if stale else [])
                + (["دادهٔ ناقص: " + ", ".join(flags_info["data_incomplete"])]
                   if flags_info["data_incomplete"] else []),
            ))
            # نشانه‌های ریسک فقط برای دارایی تازه‌دیده‌شده و با سقف فراخوان هویت
            if flags_info["flags"] and identity_calls < IDENTITY_CALLS_CAP:
                identity_calls += 1
                ident = idf(asset_id)
                platforms = ident.get("platforms") if ident.get("ok") else None
                messages.append(make_message(
                    cluster_id="I", symbol=coin["symbol"] or asset_id,
                    event_type="SCAM_RISK_FLAGS",
                    event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
                    exchange="coingecko", market_type="spot", timeframe=None,
                    features={"asset_id": asset_id,
                              "flags": flags_info["flags"],
                              "data_incomplete": flags_info["data_incomplete"],
                              "thresholds": {
                                  "volume_ratio_max": FLAG_VOLUME_RATIO_MAX,
                                  "price_change_max_pct": FLAG_PRICE_CHANGE_MAX,
                                  "unranked_beyond": FLAG_UNRANKED_BEYOND,
                              },
                              "identity": {
                                  "name": ident.get("name") if ident.get("ok") else None,
                                  "networks_contracts": platforms,
                              }},
                    evidence={"source": newly_basis,
                              "method": METHOD, "asset_id": asset_id},
                    hypothesis={
                        "claim": "هم‌زمانی این نشانه‌های عددی با پروژهٔ پرریسک/کلاهبرداری",
                        "falsifiable_by": "بررسی دستی قرارداد، نقدینگی، "
                                          "و سابقهٔ ناشر برای نمونهٔ رد/تأیید",
                    },
                    validation_status="HYPOTHESIS", task_id=task_id,
                    uncertainty=["آستانه‌ها اکتشافی‌اند (HEURISTIC) — "
                                 "هیچ فلگی به‌تنهایی واقعیت نیست"]
                    + ([f"هویت دارایی از منبع در دسترس نبود — "
                        f"شبکه/قرارداد ثبت نشد ({ident.get('error', {}).get('error_type', 'UNKNOWN')})"]
                       if not ident.get("ok") else []),
                ))
    # ۴) هیچ منبعی پاسخ نداد → UNAVAILABLE صریح (بدون دادهٔ ساختگی)
    if not sources_used:
        return [make_message(
            cluster_id="I", symbol="GLOBAL", event_type="ONCHAIN_UNAVAILABLE",
            event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
            exchange="multi", market_type="onchain", timeframe=None,
            features={"errors": sources_failed},
            evidence={"source": "coingecko+mempool.space (public, keyless)",
                      "method": METHOD},
            validation_status="UNAVAILABLE", task_id=task_id,
            uncertainty=["هیچ منبع آن‌چین/توکنی در دسترس نبود — هیچ جایگزین "
                         "ساختگی تولید نشد؛ سایر خوشه‌ها مستقل از این خوشه‌اند"],
        )]

    if sources_failed or ledger.persist_error:
        # یک رویداد شفافیت: کدام منبع‌ها شکست خوردند (بقیهٔ رویدادها سالم‌اند)
        messages.append(make_message(
            cluster_id="I", symbol="GLOBAL", event_type="ONCHAIN_PARTIAL",
            event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
            exchange="multi", market_type="onchain", timeframe=None,
            features={"failed_sources": sources_failed,
                      "used_sources": sources_used,
                      "ledger_persist_error": ledger.persist_error},
            evidence={"source": "coingecko+mempool.space (public, keyless)",
                      "method": METHOD},
            validation_status="OBSERVED", task_id=task_id,
            uncertainty=["شکست این منبع‌ها سامانه را متوقف نکرد (بند ۲ دستور)"],
        ))
    return messages


class OnchainCluster:
    """پوستهٔ استاندارد برای Orchestrator؛ ledger و fetcherها تزریق‌پذیر."""
    cluster_id = "I"

    def __init__(self, state_dir: str = None, seen_ledger=None,
                 trending_fetcher=None, newly_fetcher=None,
                 identity_fetcher=None, network_fetcher=None):
        self._state_dir = state_dir
        self._ledger = seen_ledger
        self._tf = trending_fetcher
        self._nf = newly_fetcher
        self._idf = identity_fetcher
        self._netf = network_fetcher

    def run(self, task: dict) -> list:
        ctx = task["ctx"]
        ledger = self._ledger
        if ledger is None:
            path = (os.path.join(self._state_dir, "onchain-seen.json")
                    if self._state_dir else None)
            ledger = SeenAssetLedger(path=path)
        return analyze(
            data_asof_ms=ctx["data_asof_ms"], task_id=task.get("task_id"),
            seen_ledger=ledger, trending_fetcher=self._tf,
            newly_fetcher=self._nf, identity_fetcher=self._idf,
            network_fetcher=self._netf)
