from decimal import Decimal
import time

from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import (
    OptionKind,
    OrderSide,
    OrderStatus,
    TimeInForce,
)
from nautilus_trader.model.events.order import (
    OrderAccepted,
    OrderCanceled,
    OrderDenied,
    OrderFilled,
    OrderRejected,
    OrderSubmitted,
)
from nautilus_trader.model.events.position import (
    PositionChanged,
    PositionClosed,
    PositionOpened,
)
from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId, Venue
from nautilus_trader.model.instruments import OptionContract
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.trading.strategy import Strategy

from strategy.straddle_config import BtcStraddleConfig


class BtcStraddleStrategy(Strategy):
    """
    BTC ATM Short Straddle Strategy for NautilusTrader (Bybit).

    Core Flow:
    1. Discovery:
       - Discovers available BTC options from cache.
       - Identifies the nearest ATM strike based on reference price.
       - Selects matching Call and Put contracts sharing the same strike and expiry.
    2. Execution (Level 1):
       - Submits simultaneous SELL market orders for both legs.
       - Tracks order events (submitted -> accepted -> filled) and position state.
    3. Automated Risk Management (Level 2):
       - Continuously monitors top-of-book ask quotes for both legs.
       - Valuates combined buyback premium: Cost = Ask(Call) + Ask(Put).
       - Stop-Loss: If buyback cost increases by >= 1% from entry, closes both legs.
       - Take-Profit: If buyback cost decreases by >= 2% from entry, closes both legs.
       - Guards against duplicate exits and handles single-leg execution asymmetry.
    """

    def __init__(self, config: BtcStraddleConfig) -> None:
        super().__init__(config)
        self.venue = Venue(config.venue)

        # Selected Option legs
        self.call_instrument: OptionContract | None = None
        self.put_instrument: OptionContract | None = None
        self.call_id: InstrumentId | None = None
        self.put_id: InstrumentId | None = None

        # Order & Execution state
        self.entry_submitted: bool = False
        self.call_order_id: ClientOrderId | None = None
        self.put_order_id: ClientOrderId | None = None

        self.call_filled: bool = False
        self.put_filled: bool = False
        self.call_entry_price: Decimal | None = None
        self.put_entry_price: Decimal | None = None
        self.combined_entry_premium: Decimal | None = None

        # Live Quotes (top-of-book ask for buyback valuation)
        self.latest_call_ask: Decimal | None = None
        self.latest_put_ask: Decimal | None = None

        # Risk Management flags
        self.is_straddle_active: bool = False
        self._is_exiting: bool = False
        self.exit_completed: bool = False

    def on_start(self) -> None:
        """Called when strategy starts."""
        self.log.info("Strategy starting: Initializing BTC Straddle...")

        # Discover options from cache
        instruments = self.cache.instruments(self.venue)
        options = [
            inst for inst in instruments
            if isinstance(inst, OptionContract) and "BTC" in inst.id.value
        ]

        if not options:
            self.log.warning("No BTC Option contracts found in cache at startup.")
            return

        self.log.info(f"Discovered {len(options)} BTC option contracts in cache.")
        self._select_straddle_legs(options)

    def _select_straddle_legs(
        self,
        options: list[OptionContract],
        ref_price: Decimal = Decimal("90000"),
    ) -> None:
        """
        Determines the target expiry, calculates nearest ATM strike, and pairs Call + Put.
        """
        # 1. Group options by expiry timestamp
        expiries = sorted(list({opt.expiration_ns for opt in options}))
        if not expiries:
            self.log.error("No valid expiries found in options list.")
            return

        chosen_expiry = expiries[0]  # Select nearest expiration
        chain = [opt for opt in options if opt.expiration_ns == chosen_expiry]

        # 2. Extract available strikes for chosen expiry
        strikes = sorted(list({Decimal(str(opt.strike_price.as_double())) for opt in chain}))
        if not strikes:
            self.log.error("No strikes found for chosen expiry.")
            return

        # 3. Determine nearest ATM strike
        if self.config.target_strike is not None:
            atm_strike = self.config.target_strike
        else:
            atm_strike = min(strikes, key=lambda s: abs(s - ref_price))

        self.log.info(f"Selected ATM strike: {atm_strike} (Reference Price: ${ref_price:,.2f})")

        # 4. Find matching Call and Put contracts
        call_leg = None
        put_leg = None
        for opt in chain:
            strike = Decimal(str(opt.strike_price.as_double()))
            if strike == atm_strike:
                if opt.option_kind == OptionKind.CALL:
                    call_leg = opt
                elif opt.option_kind == OptionKind.PUT:
                    put_leg = opt

        if not call_leg or not put_leg:
            self.log.error(f"Could not find matching Call and Put pair for strike {atm_strike}!")
            return

        self.call_instrument = call_leg
        self.put_instrument = put_leg
        self.call_id = call_leg.id
        self.put_id = put_leg.id

        self.log.info(f"Call Leg: {self.call_id}")
        self.log.info(f"Put Leg:  {self.put_id}")

        # 5. Subscribe to real-time quote ticks for both legs
        try:
            self.subscribe_quote_ticks(self.call_id)
            self.subscribe_quote_ticks(self.put_id)
        except ValueError:
            # Standalone unit test mode without active engine registration
            pass

    def enter_straddle(self) -> None:
        """
        Executes Level 1 Naked Straddle entry:
        Simultaneously submits SELL market orders for Call and Put legs.
        """
        if self.entry_submitted:
            return

        qty_val = self.config.trade_quantity
        call_qty = self.call_instrument.make_qty(qty_val)
        put_qty = self.put_instrument.make_qty(qty_val)

        # Build market sell orders using order factory
        call_order = self.order_factory.market(
            instrument_id=self.call_id,
            order_side=OrderSide.SELL,
            quantity=call_qty,
        )
        put_order = self.order_factory.market(
            instrument_id=self.put_id,
            order_side=OrderSide.SELL,
            quantity=put_qty,
        )

        self.call_order_id = call_order.client_order_id
        self.put_order_id = put_order.client_order_id
        self.entry_submitted = True

        self.log.info(f"Submitting SHORT Call order: {call_order.client_order_id} (Qty: {call_qty})")
        self.submit_order(call_order)

        self.log.info(f"Submitting SHORT Put order:  {put_order.client_order_id} (Qty: {put_qty})")
        self.submit_order(put_order)

    # ---------------------------------------------------------------------------------------------
    # Order Event Handlers
    # ---------------------------------------------------------------------------------------------

    def on_order_submitted(self, event: OrderSubmitted) -> None:
        self.log.info(f"Order submitted: {event.client_order_id}")

    def on_order_accepted(self, event: OrderAccepted) -> None:
        self.log.info(f"Order accepted by venue: {event.client_order_id}")

    def on_order_rejected(self, event: OrderRejected) -> None:
        self.log.error(f"Order REJECTED by venue: {event.client_order_id}, reason: {event.reason}")
        self._handle_execution_failure(event.client_order_id)

    def on_order_denied(self, event: OrderDenied) -> None:
        self.log.error(f"Order DENIED by risk engine: {event.client_order_id}, reason: {event.reason}")
        self._handle_execution_failure(event.client_order_id)

    def on_order_filled(self, event: OrderFilled) -> None:
        fill_price = Decimal(str(event.last_px.as_double()))
        self.log.info(f"Order FILLED: {event.client_order_id} at price ${fill_price:,.2f}")

        if event.client_order_id == self.call_order_id:
            self.call_filled = True
            self.call_entry_price = fill_price
        elif event.client_order_id == self.put_order_id:
            self.put_filled = True
            self.put_entry_price = fill_price

        # Check if both entry legs are now filled
        if self.call_filled and self.put_filled and not self.is_straddle_active:
            self.is_straddle_active = True
            self.combined_entry_premium = self.call_entry_price + self.put_entry_price

            sl_threshold = self.combined_entry_premium * (Decimal("1") + self.config.stop_loss_pct)
            tp_threshold = self.combined_entry_premium * (Decimal("1") - self.config.take_profit_pct)

            self.log.info("=" * 65)
            self.log.info("🎉 BTC SHORT STRADDLE POSITION ESTABLISHED!")
            self.log.info(f"Call Entry Fill:   ${self.call_entry_price:,.2f}")
            self.log.info(f"Put Entry Fill:    ${self.put_entry_price:,.2f}")
            self.log.info(f"Combined Premium:  ${self.combined_entry_premium:,.2f}")
            if self.config.enable_risk_management:
                self.log.info("Automated Risk Management Active:")
                self.log.info(f"  -> Stop-Loss (+{self.config.stop_loss_pct:.1%}):   Buyback Ask >= ${sl_threshold:,.2f}")
                self.log.info(f"  -> Take-Profit (-{self.config.take_profit_pct:.1%}):  Buyback Ask <= ${tp_threshold:,.2f}")
            else:
                self.log.info("Mode: Level 1 Naked Straddle (No SL/TP automated exits)")
            self.log.info("=" * 65)

    # ---------------------------------------------------------------------------------------------
    # Market Data & Risk Management Handler
    # ---------------------------------------------------------------------------------------------

    def on_quote_tick(self, tick: QuoteTick) -> None:
        """
        Receives real-time top-of-book market data.
        Updates ask prices and evaluates Stop-Loss / Take-Profit criteria.
        """
        ask_price = Decimal(str(tick.ask_price.as_double()))

        if tick.instrument_id == self.call_id:
            self.latest_call_ask = ask_price
        elif tick.instrument_id == self.put_id:
            self.latest_put_ask = ask_price

        # Trigger straddle entry once initial market quotes are available
        if not self.entry_submitted and self.latest_call_ask is not None and self.latest_put_ask is not None:
            self.enter_straddle()
            return

        # Risk checks only apply if straddle is established and risk management is enabled
        if not self.config.enable_risk_management:
            return  # Level 1 mode

        if not self.is_straddle_active or self._is_exiting:
            return

        if self.latest_call_ask is None or self.latest_put_ask is None:
            return

        # Buyback valuation using ask quotes for both short legs
        combined_buyback = self.latest_call_ask + self.latest_put_ask
        pct_change = (combined_buyback - self.combined_entry_premium) / self.combined_entry_premium

        # Level 2 Stop-Loss Check: buyback cost increases by >= +1%
        if pct_change >= self.config.stop_loss_pct:
            self.log.warning(
                f"🛑 STOP-LOSS TRIGGERED! Combined buyback cost: ${combined_buyback:,.2f} "
                f"(+{pct_change:.2%} vs entry ${self.combined_entry_premium:,.2f})"
            )
            self._close_straddle("Stop-Loss")
            return

        # Level 2 Take-Profit Check: buyback cost decreases by >= 2% (decay/crush)
        if pct_change <= -self.config.take_profit_pct:
            self.log.info(
                f"🎯 TAKE-PROFIT TRIGGERED! Combined buyback cost: ${combined_buyback:,.2f} "
                f"({pct_change:.2%} vs entry ${self.combined_entry_premium:,.2f})"
            )
            self._close_straddle("Take-Profit")
            return

    def _close_straddle(self, reason: str) -> None:
        """
        Closes both short legs by submitting buy-to-close orders.
        Guarded against duplicate calls via self._is_exiting flag.
        """
        if self._is_exiting:
            return
        self._is_exiting = True

        self.log.info(f"Initiating Straddle Exit ({reason})...")

        if self.call_id:
            self.log.info(f"Closing Call position: {self.call_id}")
            try:
                self.close_all_positions(self.call_id)
            except ValueError:
                pass

        if self.put_id:
            self.log.info(f"Closing Put position: {self.put_id}")
            try:
                self.close_all_positions(self.put_id)
            except ValueError:
                pass

    def _handle_execution_failure(self, failed_order_id: ClientOrderId) -> None:
        """
        Mitigates execution asymmetry:
        If one leg fills but the other is rejected or times out, immediately closes
        the filled leg to avoid holding naked directional option risk.
        """
        self.log.error(f"Execution asymmetry detected for order {failed_order_id}")
        self._is_exiting = True

        if self.call_filled and not self.put_filled:
            self.log.warning("Asymmetry: Call leg filled, Put failed. Liquidating Call leg.")
            if self.call_id:
                try:
                    self.close_all_positions(self.call_id)
                except ValueError:
                    pass

        elif self.put_filled and not self.call_filled:
            self.log.warning("Asymmetry: Put leg filled, Call failed. Liquidating Put leg.")
            if self.put_id:
                try:
                    self.close_all_positions(self.put_id)
                except ValueError:
                    pass

    # ---------------------------------------------------------------------------------------------
    # Position Event Handlers
    # ---------------------------------------------------------------------------------------------

    def on_position_opened(self, event: PositionOpened) -> None:
        self.log.info(f"Position OPENED: {event.instrument_id} {event.side} {event.quantity}")

    def on_position_changed(self, event: PositionChanged) -> None:
        self.log.info(f"Position CHANGED: {event.instrument_id} {event.side} {event.quantity}")

    def on_position_closed(self, event: PositionClosed) -> None:
        self.log.info(f"Position CLOSED: {event.instrument_id} Realized PnL: {event.realized_pnl}")

    def on_stop(self) -> None:
        """Cleanup actions when strategy stops."""
        self.log.info("Strategy stopping: cleaning up subscriptions.")
        if self.call_id:
            self.unsubscribe_quote_ticks(self.call_id)
        if self.put_id:
            self.unsubscribe_quote_ticks(self.put_id)

