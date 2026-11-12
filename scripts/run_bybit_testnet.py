#!/usr/bin/env python3
"""
NautilusTrader BTC Options Straddle - Bybit Testnet Live Runner

Connects to Bybit Testnet using TradingNode, streams real-time market data
for BTC options, selects the nearest ATM strike, executes the short straddle,
and runs Level 2 automated risk management (Stop-Loss / Take-Profit).
"""

import os
import signal
import sys
from decimal import Decimal
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from nautilus_trader.adapters.bybit import (
    BYBIT,
    BybitDataClientConfig,
    BybitExecClientConfig,
    BybitLiveDataClientFactory,
    BybitLiveExecClientFactory,
    BybitProductType,
)
from nautilus_trader.config import InstrumentProviderConfig, TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import TraderId

from config.settings import (
    BYBIT_API_KEY,
    BYBIT_API_SECRET,
    ENABLE_RISK_MANAGEMENT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    TRADE_QUANTITY,
)
from strategy.straddle_config import BtcStraddleConfig
from strategy.straddle_strategy import BtcStraddleStrategy


def main():
    print("=" * 75)
    print("  NAUTILUS TRADER - BYBIT TESTNET BTC OPTIONS STRADDLE")
    print("=" * 75)

    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        print("\n[WARNING] Bybit Testnet API credentials not found in environment!")
        print("Please copy .env.example to .env and set your BYBIT_API_KEY and BYBIT_API_SECRET.")
        print("To verify strategy execution locally without credentials, run:")
        print("    python scripts/run_simulation.py\n")

    # 1. Configure Bybit Data Client
    # Product types: OPTION (for options data & greeks) and LINEAR (for BTC underlying reference price)
    data_client_config = BybitDataClientConfig(
        testnet=True,
        api_key=BYBIT_API_KEY or None,
        api_secret=BYBIT_API_SECRET or None,
        product_types=[BybitProductType.OPTION, BybitProductType.LINEAR],
        instrument_provider=InstrumentProviderConfig(
            load_all=True,
            filters={"base_coin": "BTC"},
        ),
    )

    # 2. Configure Bybit Execution Client
    # Bybit Unified Trading Account (UTA) handles option orders
    exec_client_config = BybitExecClientConfig(
        testnet=True,
        api_key=BYBIT_API_KEY or None,
        api_secret=BYBIT_API_SECRET or None,
        product_types=[BybitProductType.OPTION],
    )

    # 3. Build TradingNode Configuration
    node_config = TradingNodeConfig(
        trader_id=TraderId("BYBIT-STRADDLE-001"),
        data_clients={BYBIT: data_client_config},
        exec_clients={BYBIT: exec_client_config},
        timeout_connection=30.0,
        timeout_reconciliation=15.0,
        timeout_disconnection=10.0,
    )

    # 4. Instantiate and build TradingNode
    node = TradingNode(config=node_config)
    node.add_data_client_factory(BYBIT, BybitLiveDataClientFactory)
    node.add_exec_client_factory(BYBIT, BybitLiveExecClientFactory)
    node.build()

    # 5. Configure Straddle Strategy
    strategy_config = BtcStraddleConfig(
        venue=BYBIT,
        underlying_symbol="BTCUSDT",
        trade_quantity=TRADE_QUANTITY,
        enable_risk_management=ENABLE_RISK_MANAGEMENT,
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
    )
    strategy = BtcStraddleStrategy(strategy_config)
    node.trader.add_strategy(strategy)

    # 6. Graceful shutdown handler
    def shutdown(sig, frame):
        print("\nGracefully shutting down TradingNode...")
        node.stop()
        node.dispose()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 7. Run Trading Node
    print("\nStarting Trading Node and connecting to Bybit Testnet...")
    try:
        node.run()
    except KeyboardInterrupt:
        shutdown(None, None)


if __name__ == "__main__":
    main()

