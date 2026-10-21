
import json
import urllib.request

print("MARI MARKET DATA TEST")
print("Mode: READ ONLY")
print("Live orders: DISABLED")

url = "https://api.toobit.com/api/v1/exchangeInfo"

try:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MARI-ReadOnly-Test"}
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))

    if isinstance(data, dict):
        symbols = data.get("symbols", [])

        print("TOOBIT MARKET API: SUCCESS")
        print("Symbols received:", len(symbols))

        for item in symbols[:5]:
            print(
                item.get("symbol"),
                item.get("status"),
                item.get("baseAsset"),
                item.get("quoteAsset"),
            )
    else:
        print("UNEXPECTED RESPONSE SHAPE:", type(data).__name__)

except Exception as error:
    print("TEST FAILED:", type(error).__name__, str(error))
    raise
