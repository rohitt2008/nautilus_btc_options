#!/usr/bin/env python3
"""
Bybit Testnet Account & Options Diagnostic Tool

Queries Bybit V5 public and private endpoints to verify:
  1. Bybit server connectivity & latency.
  2. Live BTC reference price (Index / Ticker).
  3. Active BTC option instruments, strikes, and expiries currently tradable.
  4. Unified Trading Account (UTA) status and wallet balance (if credentials provided).
"""

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from config.settings import BYBIT_API_KEY, BYBIT_API_SECRET

BASE_URL = "https://api-testnet.bybit.com"


def http_get(endpoint: str, params: dict | None = None, api_key: str = "", api_secret: str = "") -> dict:
    query_str = urllib.parse.urlencode(params or {})
    url = f"{BASE_URL}{endpoint}"
    if query_str:
        url += f"?{query_str}"

    headers = {"Content-Type": "application/json"}

    if api_key and api_secret:
        timestamp = str(int(time.time() * 1000))
        recv_window = "5000"
        param_str = query_str
        sign_str = f"{timestamp}{api_key}{recv_window}{param_str}"
        signature = hmac.new(api_secret.encode("utf-8"), sign_str.encode("utf-8"), hashlib.sha256).hexdigest()
        headers.update({
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-SIGN": signature,
            "X-BAPI-SIGN-TYPE": "2",
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window,
        })

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        return {"retCode": e.code, "retMsg": body}
    except Exception as e:
        return {"retCode": -1, "retMsg": str(e)}


def main():
    print("=" * 75)
    print("  BYBIT TESTNET - CONNECTIVITY & OPTIONS DIAGNOSTIC TOOL")
    print("=" * 75)

    # 1. Server Time Check
    t_start = time.time()
    server_time_resp = http_get("/v5/market/time")
    latency_ms = int((time.time() - t_start) * 1000)

    if server_time_resp.get("retCode") == 0:
        server_time = server_time_resp.get("result", {}).get("timeSecond", "N/A")
        print(f"✓ Bybit Testnet Gateway: CONNECTED (Latency: {latency_ms} ms)")
        print(f"  Server Timestamp: {server_time}")
    else:
        print(f"✗ Failed to connect to Bybit Testnet: {server_time_resp.get('retMsg')}")
        return

    # 2. Underlying BTC Reference Price
    ticker_resp = http_get("/v5/market/tickers", {"category": "linear", "symbol": "BTCUSDT"})
    btc_price = "N/A"
    if ticker_resp.get("retCode") == 0:
        tickers = ticker_resp.get("result", {}).get("list", [])
        if tickers:
            btc_price = tickers[0].get("lastPrice", "N/A")
            print(f"✓ BTC Reference Price (BTCUSDT Perp): ${float(btc_price):,.2f}")
    else:
        print("  Could not fetch BTC reference price.")

    # 3. Active BTC Option Instruments
    print("\nFetching active BTC option contracts from Bybit V5 Option API...")
    options_resp = http_get("/v5/market/instruments-info", {"category": "option", "baseCoin": "BTC", "limit": 100})

    if options_resp.get("retCode") == 0:
        option_list = options_resp.get("result", {}).get("list", [])
        print(f"✓ Retrieved {len(option_list)} BTC option instruments listed on Bybit Testnet.")

        if option_list:
            expiries = sorted(list({item.get("deliveryTime") for item in option_list if item.get("deliveryTime")}))
            print(f"  Available Expiry Dates: {len(expiries)} expiries found.")
            
            # Show nearest 5 contracts
            print("\n  Sample Available Contracts:")
            print(f"  {'Symbol':<32} {'Type':<8} {'Strike':<10} {'Status'}")
            print("  " + "-" * 60)
            for opt in option_list[:6]:
                sym = opt.get("symbol", "")
                opt_type = opt.get("optionsType", "")
                strike = opt.get("symbol", "").split("-")[2] if len(opt.get("symbol", "").split("-")) > 2 else "N/A"
                status = opt.get("status", "")
                print(f"  {sym:<32} {opt_type:<8} {strike:<10} {status}")
    else:
        print(f"  Could not list options: {options_resp.get('retMsg')}")

    # 4. Bybit Account Credentials & Balance (if supplied)
    print("\nAccount Verification:")
    if BYBIT_API_KEY and BYBIT_API_SECRET:
        wallet_resp = http_get("/v5/account/wallet-balance", {"accountType": "UNIFIED"}, BYBIT_API_KEY, BYBIT_API_SECRET)
        if wallet_resp.get("retCode") == 0:
            accounts = wallet_resp.get("result", {}).get("list", [])
            print("✓ Bybit API Key & Secret: AUTHENTICATED")
            if accounts:
                total_equity = accounts[0].get("totalEquity", "0")
                print(f"  Unified Trading Account Equity: ${float(total_equity):,.2f} USD")
                for coin in accounts[0].get("coin", []):
                    c_name = coin.get("coin")
                    c_bal = coin.get("walletBalance", "0")
                    if float(c_bal) > 0:
                        print(f"    - {c_name}: {float(c_bal):,.4f}")
        else:
            print(f"✗ Account Authentication Failed: {wallet_resp.get('retMsg')}")
    else:
        print("  [INFO] No API keys configured in .env yet.")
        print("  (API keys are only needed for live Testnet order execution, not for simulation).")

    print("\n" + "=" * 75)
    print("  DIAGNOSTICS COMPLETED")
    print("=" * 75)


if __name__ == "__main__":
    main()

