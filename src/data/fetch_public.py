import json
import urllib.request
from datetime import datetime, timezone

URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

def main():
    print("=== MARI MARKET BOT ===")
    print("Mode: READ ONLY | PAPER ONLY")
    print("Live orders: DISABLED")

    try:
        request = urllib.request.Request(
            URL,
            headers={"User-Agent": "MariMarketBot/1.0"}
        )

        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        print("Time UTC:", datetime.now(timezone.utc).isoformat())
        print("Symbol:", data["symbol"])
        print("BTC Price USDT:", data["price"])
        print("Public market data: OK")

    except Exception as error:
        print("Market data error:", str(error))
        raise

    print("Bot test completed successfully.")

if __name__ == "__main__":
    main()
