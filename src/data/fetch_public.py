
import json
import urllib.request
import urllib.error

URL = "https://api.toobit.com/api/v1/ticker/24hr?symbol=BTCUSDT"

def main():
    print("Starting public market data test...")

    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "MarketDataTest/1.0"}
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))

        print("Connection successful!")
        print("Public BTCUSDT market response:")
        print(json.dumps(data, indent=2)[:2000])

    except urllib.error.URLError as error:
        print("Connection failed:", str(error))
    except Exception as error:
        print("Test failed:", str(error))

if __name__ == "__main__":
    main()
