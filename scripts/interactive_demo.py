#!/usr/bin/env python3
"""
Interactive Strategy Demo & Interview Presentation CLI

Allows walking through the strategy lifecycle interactively during an interview meet call:
  1. Dynamic ATM Strike Discovery & Pairing
  2. Order Generation & Level 1 Short Straddle Entry
  3. Interactive Live Valuation:
     - Preset 1: Simulate Volatility Crush (Take-Profit Trigger <= -2%)
     - Preset 2: Simulate Volatility Spike (Stop-Loss Trigger >= +1%)
     - Custom: Input arbitrary Call Ask & Put Ask prices and see the engine react!
"""

from decimal import Decimal
import sys
import time
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import AssetClass, OptionKind, OrderSide
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.objects import Currency, Price, Quantity

from strategy.straddle_config import BtcStraddleConfig
from strategy.straddle_strategy import BtcStraddleStrategy


def create_mock_contracts(venue_name: str = "BYBIT", ref_price: Decimal = Decimal("90000")):
    usdc = Currency.from_str("USDC")
    now_ns = int(time.time() * 1e9)
    expiry_ns = now_ns + (30 * 86_400_000_000_000)

    strikes = ["85000", "88000", "90000", "92000", "95000"]
    options = []
    for s in strikes:
        call_id = InstrumentId.from_str(f"BTC-28MAR25-{s}-C-OPTION.{venue_name}")
        c = OptionContract(
            instrument_id=call_id,
            raw_symbol=Symbol(f"BTC-28MAR25-{s}-C"),
            asset_class=AssetClass.COMMODITY,
            currency=usdc,
            price_precision=2,
            price_increment=Price.from_str("0.50"),
            multiplier=Quantity.from_str("1.0"),
            lot_size=Quantity.from_str("1.0"),
            underlying="BTC",
            option_kind=OptionKind.CALL,
            strike_price=Price.from_str(s),
            activation_ns=now_ns - 1000,
            expiration_ns=expiry_ns,
            ts_event=now_ns,
            ts_init=now_ns,
        )
        put_id = InstrumentId.from_str(f"BTC-28MAR25-{s}-P-OPTION.{venue_name}")
        p = OptionContract(
            instrument_id=put_id,
            raw_symbol=Symbol(f"BTC-28MAR25-{s}-P"),
            asset_class=AssetClass.COMMODITY,
            currency=usdc,
            price_precision=2,
            price_increment=Price.from_str("0.50"),
            multiplier=Quantity.from_str("1.0"),
            lot_size=Quantity.from_str("1.0"),
            underlying="BTC",
            option_kind=OptionKind.PUT,
            strike_price=Price.from_str(s),
            activation_ns=now_ns - 1000,
            expiration_ns=expiry_ns,
            ts_event=now_ns,
            ts_init=now_ns,
        )
        options.extend([c, p])
    return options


def print_banner(text: str):
    print("\n" + "=" * 70)
    print(f"  {text}")
    print("=" * 70)


def main():
    print_banner("NAUTILUS TRADER - INTERACTIVE STRADDLE WALKTHROUGH DEMO")

    config = BtcStraddleConfig(
        venue="BYBIT",
        underlying_symbol="BTCUSDT",
        trade_quantity=Decimal("1.0"),
        enable_risk_management=True,
        stop_loss_pct=Decimal("0.01"),    # 1.0%
        take_profit_pct=Decimal("0.02"),  # 2.0%
    )
    strategy = BtcStraddleStrategy(config)

    # 1. ATM Strike Selection Demo
    ref_price = Decimal("90450")
    print(f"\n[STEP 1] Underlying BTC Reference Price: ${ref_price:,.2f}")
    print("Available strikes listed: $85,000, $88,000, $90,000, $92,000, $95,000")
    print("Discovering options and selecting ATM strike...")

    options = create_mock_contracts(ref_price=ref_price)
    strategy._select_straddle_legs(options, ref_price=ref_price)

    print(f"✓ Selected ATM Strike: ${strategy.call_instrument.strike_price.as_double():,.2f}")
    print(f"  -> Call Leg ID: {strategy.call_id}")
    print(f"  -> Put Leg ID:  {strategy.put_id}")

    # 2. Execution Entry Demo
    print_banner("[STEP 2] Executing Level 1 Short Straddle Entry")
    call_fill = Decimal("2500.00")
    put_fill = Decimal("2400.00")
    combined_entry = call_fill + put_fill

    strategy.entry_submitted = True
    strategy.call_filled = True
    strategy.put_filled = True
    strategy.call_entry_price = call_fill
    strategy.put_entry_price = put_fill
    strategy.combined_entry_premium = combined_entry
    strategy.is_straddle_active = True

    sl_threshold = combined_entry * (Decimal("1") + config.stop_loss_pct)
    tp_threshold = combined_entry * (Decimal("1") - config.take_profit_pct)

    print(f"✓ SHORT Call Filled at: ${call_fill:,.2f}")
    print(f"✓ SHORT Put  Filled at: ${put_fill:,.2f}")
    print(f"✓ Combined Entry Premium Received: ${combined_entry:,.2f}")
    print(f"\nAutomated Risk Parameters:")
    print(f"  • Stop-Loss (+{config.stop_loss_pct:.1%}):   Buyback Ask >= ${sl_threshold:,.2f}")
    print(f"  • Take-Profit (-{config.take_profit_pct:.1%}):  Buyback Ask <= ${tp_threshold:,.2f}")

    # 3. Interactive Risk Evaluation Loop
    print_banner("[STEP 3] Real-time Quote Valuation & Exit Evaluation")
    print("Select an evaluation test:")
    print("  1. Simulate Volatility Crush (Ask: Call $2380, Put $2380 -> Buyback $4760, -2.85% -> TP)")
    print("  2. Simulate Volatility Spike (Ask: Call $2580, Put $2420 -> Buyback $5000, +2.04% -> SL)")
    print("  3. Input custom Call & Put Ask prices")

    choice = input("\nEnter choice [1/2/3] (default 1): ").strip() or "1"

    if choice == "2":
        call_ask = Decimal("2580.00")
        put_ask = Decimal("2420.00")
    elif choice == "3":
        try:
            call_ask = Decimal(input("Enter Call Ask price: ").strip())
            put_ask = Decimal(input("Enter Put Ask price: ").strip())
        except Exception:
            print("Invalid input, using default neutral prices.")
            call_ask = Decimal("2505.00")
            put_ask = Decimal("2405.00")
    else:
        call_ask = Decimal("2380.00")
        put_ask = Decimal("2380.00")

    combined_buyback = call_ask + put_ask
    pct_change = (combined_buyback - combined_entry) / combined_entry

    print("\n--- Live Market Evaluation ---")
    print(f"Call Ask Quote: ${call_ask:,.2f}")
    print(f"Put  Ask Quote: ${put_ask:,.2f}")
    print(f"Combined Buyback Ask: ${combined_buyback:,.2f}")
    print(f"Premium Change vs Entry: {pct_change:+.2%}")

    t_ns = int(time.time() * 1e9)
    tick_call = QuoteTick(strategy.call_id, Price.from_str(str(call_ask - 10)), Price.from_str(str(call_ask)), Quantity.from_str("1"), Quantity.from_str("1"), t_ns, t_ns)
    tick_put = QuoteTick(strategy.put_id, Price.from_str(str(put_ask - 10)), Price.from_str(str(put_ask)), Quantity.from_str("1"), Quantity.from_str("1"), t_ns + 1000, t_ns + 1000)

    strategy.on_quote_tick(tick_call)
    strategy.on_quote_tick(tick_put)

    if strategy._is_exiting:
        print(f"\n✓ Strategy Status: EXIT EXECUTED successfully! (Duplicate exit guard active: {strategy._is_exiting})")
    else:
        print(f"\n✓ Strategy Status: Position Maintained (Within risk thresholds, holding short straddle).")

    print("\n" + "=" * 70)
    print("  WALKTHROUGH DEMO COMPLETED")
    print("=" * 70)


if __name__ == "__main__":
    main()

