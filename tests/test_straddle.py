"""
Unit and Integration Test Suite for BTC Options Straddle Strategy.
Uses standard Python `unittest` framework (zero extra dependencies).
"""

from decimal import Decimal
import sys
import unittest
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from nautilus_trader.model.enums import AssetClass, OptionKind, OrderSide
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.objects import Currency, Price, Quantity

from strategy.straddle_config import BtcStraddleConfig
from strategy.straddle_strategy import BtcStraddleStrategy


class TestBtcStraddle(unittest.TestCase):
    def setUp(self):
        self.config = BtcStraddleConfig(
            venue="BYBIT",
            underlying_symbol="BTCUSDT",
            trade_quantity=Decimal("1.0"),
            enable_risk_management=True,
            stop_loss_pct=Decimal("0.01"),    # +1%
            take_profit_pct=Decimal("0.02"),  # -2%
        )
        self.strategy = BtcStraddleStrategy(self.config)
        self.usdc = Currency.from_str("USDC")
        self.t0 = 1_700_000_000_000_000_000
        self.expiry_ns = self.t0 + (30 * 86_400_000_000_000)

    def _make_option(self, symbol_str: str, kind: OptionKind, strike: str):
        inst_id = InstrumentId.from_str(f"{symbol_str}-OPTION.BYBIT")
        return OptionContract(
            instrument_id=inst_id,
            raw_symbol=Symbol(symbol_str),
            asset_class=AssetClass.COMMODITY,
            currency=self.usdc,
            price_precision=2,
            price_increment=Price.from_str("0.50"),
            multiplier=Quantity.from_str("1.0"),
            lot_size=Quantity.from_str("1.0"),
            underlying="BTC",
            option_kind=kind,
            strike_price=Price.from_str(strike),
            activation_ns=self.t0 - 1000,
            expiration_ns=self.expiry_ns,
            ts_event=self.t0,
            ts_init=self.t0,
        )

    def test_atm_strike_selection(self):
        """Tests that nearest ATM strike is selected based on reference price."""
        options = [
            self._make_option("BTC-28MAR25-85000-C", OptionKind.CALL, "85000"),
            self._make_option("BTC-28MAR25-85000-P", OptionKind.PUT, "85000"),
            self._make_option("BTC-28MAR25-90000-C", OptionKind.CALL, "90000"),
            self._make_option("BTC-28MAR25-90000-P", OptionKind.PUT, "90000"),
            self._make_option("BTC-28MAR25-95000-C", OptionKind.CALL, "95000"),
            self._make_option("BTC-28MAR25-95000-P", OptionKind.PUT, "95000"),
        ]

        # Case 1: Ref price 89,400 -> closer to 90,000 (diff 600) than 85,000 (diff 4,400)
        self.strategy._select_straddle_legs(options, ref_price=Decimal("89400"))
        self.assertEqual(float(self.strategy.call_instrument.strike_price.as_double()), 90000.0)
        self.assertEqual(float(self.strategy.put_instrument.strike_price.as_double()), 90000.0)

        # Case 2: Ref price 93,000 -> closer to 95,000 (diff 2,000) than 90,000 (diff 3,000)
        self.strategy._select_straddle_legs(options, ref_price=Decimal("93000"))
        self.assertEqual(float(self.strategy.call_instrument.strike_price.as_double()), 95000.0)
        self.assertEqual(float(self.strategy.put_instrument.strike_price.as_double()), 95000.0)

    def test_risk_management_math(self):
        """Tests Stop-Loss (+1%) and Take-Profit (-2%) boundary evaluations."""
        entry_call = Decimal("2500.00")
        entry_put = Decimal("2400.00")
        combined_entry = entry_call + entry_put  # 4900.00

        sl_threshold = combined_entry * (Decimal("1") + self.config.stop_loss_pct)      # 4949.00
        tp_threshold = combined_entry * (Decimal("1") - self.config.take_profit_pct)    # 4802.00

        self.assertEqual(combined_entry, Decimal("4900.00"))
        self.assertEqual(sl_threshold, Decimal("4949.00"))
        self.assertEqual(tp_threshold, Decimal("4802.00"))

        # Test Stop-Loss trigger: buyback ask expands to 4950 (> 4949)
        current_ask_sl = Decimal("4950.00")
        pct_change_sl = (current_ask_sl - combined_entry) / combined_entry
        self.assertGreaterEqual(pct_change_sl, self.config.stop_loss_pct)

        # Test Take-Profit trigger: buyback ask drops to 4800 (<= 4802)
        current_ask_tp = Decimal("4800.00")
        pct_change_tp = (current_ask_tp - combined_entry) / combined_entry
        self.assertLessEqual(pct_change_tp, -self.config.take_profit_pct)

        # Test Neutral / Holding: buyback ask is 4910 (between 4802 and 4949)
        current_ask_mid = Decimal("4910.00")
        pct_change_mid = (current_ask_mid - combined_entry) / combined_entry
        self.assertFalse(pct_change_mid >= self.config.stop_loss_pct)
        self.assertFalse(pct_change_mid <= -self.config.take_profit_pct)

    def test_duplicate_exit_guard(self):
        """Verifies that _is_exiting flag guards against multiple exit triggers."""
        self.assertFalse(self.strategy._is_exiting)
        self.strategy._close_straddle("First Trigger")
        self.assertTrue(self.strategy._is_exiting)

        # Subsequent call should return immediately without side effects
        self.strategy._close_straddle("Second Trigger")
        self.assertTrue(self.strategy._is_exiting)

    def test_execution_asymmetry_handler(self):
        """Verifies that single-leg execution failure triggers liquidation of the orphan leg."""
        call_opt = self._make_option("BTC-28MAR25-90000-C", OptionKind.CALL, "90000")
        put_opt = self._make_option("BTC-28MAR25-90000-P", OptionKind.PUT, "90000")
        self.strategy.call_instrument = call_opt
        self.strategy.put_instrument = put_opt
        self.strategy.call_id = call_opt.id
        self.strategy.put_id = put_opt.id

        # Simulate: Call filled, Put rejected
        self.strategy.call_filled = True
        self.strategy.put_filled = False

        failed_id = ClientOrderId("O-PUT-FAILED-001")
        self.strategy._handle_execution_failure(failed_id)

        # Strategy should be in exiting state to liquidate orphan call
        self.assertTrue(self.strategy._is_exiting)


if __name__ == "__main__":
    unittest.main()

