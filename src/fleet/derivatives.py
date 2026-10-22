# MARI — خوشهٔ G: Derivatives (بند ۳-G دستور)
# MODE: READ ONLY | PAPER ONLY | NO LIVE ORDERS
# Funding Rate و Open Interest فقط از منبع معتبر عمومی (Binance fapi).
# نبود داده = وضعیت UNAVAILABLE با علت صریح — تولید دادهٔ ساختگی ممنوع.

from .contract import make_message
from . import sources as sources_mod

METHOD = "binance_fapi_snapshot/v1"


def analyze(symbol: str, *, data_asof_ms: int, timeframe: str = "1h",
            task_id: str = None, funding_fetcher=None, oi_fetcher=None) -> list:
    ff = funding_fetcher or sources_mod.fetch_funding
    of = oi_fetcher or sources_mod.fetch_open_interest
    funding = ff(symbol)
    oi = of(symbol)

    if funding.get("ok") and oi.get("ok"):
        return [make_message(
            cluster_id="G", symbol=symbol, event_type="DERIVATIVES_SNAPSHOT",
            event_time_ms=max(funding["funding_time"], oi["asof_ms"]),
            data_asof_ms=data_asof_ms, exchange="binance",
            market_type="perpetual", timeframe=timeframe,
            features={
                "funding_rate": funding["funding_rate"],
                "mark_price": funding["mark_price"],
                "open_interest": oi["open_interest"],
                "funding_time": funding["funding_time"],
                "oi_asof_ms": oi["asof_ms"],
            },
            evidence={"source": "binance.fapi/v1 (public, keyless)",
                      "method": METHOD},
            validation_status="OBSERVED", task_id=task_id,
        )]

    errors = {}
    if not funding.get("ok"):
        errors["funding"] = funding.get("error", {"error_type": "UNKNOWN"})
    if not oi.get("ok"):
        errors["open_interest"] = oi.get("error", {"error_type": "UNKNOWN"})
    return [make_message(
        cluster_id="G", symbol=symbol, event_type="DERIVATIVES_UNAVAILABLE",
        event_time_ms=data_asof_ms, data_asof_ms=data_asof_ms,
        exchange="binance", market_type="perpetual", timeframe=timeframe,
        features={"errors": errors},
        evidence={"source": "binance.fapi/v1 (public, keyless)",
                  "method": METHOD},
        validation_status="UNAVAILABLE", task_id=task_id,
        uncertainty=["دادهٔ مشتقات این نماد از منبع عمومی در دسترس نبود — "
                     "هیچ جایگزین ساختگی تولید نشد"],
    )]


class DerivativesCluster:
    """پوستهٔ استاندارد برای Orchestrator؛ fetcherها تزریق‌پذیر برای آزمون آفلاین."""
    cluster_id = "G"

    def __init__(self, funding_fetcher=None, oi_fetcher=None):
        self._ff = funding_fetcher
        self._of = oi_fetcher

    def run(self, task: dict) -> list:
        ctx = task["ctx"]
        return analyze(task["symbol"], data_asof_ms=ctx["data_asof_ms"],
                       timeframe=ctx.get("interval", "1h"),
                       task_id=task.get("task_id"),
                       funding_fetcher=self._ff, oi_fetcher=self._of)
