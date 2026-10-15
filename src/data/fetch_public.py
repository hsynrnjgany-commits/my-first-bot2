import json
import urllib.request

URL = "https://api.binance.com/api/v3/time"

def main():
print("MARI AI INTEGRATION TEST")
print("Mode: READ ONLY")
print("Live orders: DISABLED")

request = urllib.request.Request(
    URL,
    headers={"User-Agent": "MARI-Public-Data-Test"}
)

with urllib.request.urlopen(request, timeout=10) as response:
    data = json.loads(response.read().decode("utf-8"))

print("Public API connection: SUCCESS")
print("Server time (ms):", data["serverTime"])
print("Test completed successfully.")

if name == "main":
try:
main()
except Exception as error:
print("TEST FAILED:", type(error).name, str(error))
raise
