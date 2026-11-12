from decimal import Decimal
from nautilus_trader.config import StrategyConfig


class BtcStraddleConfig(StrategyConfig, frozen=True):
    """
    Configuration parameters for the BTC ATM Short Straddle strategy.
    
    Parameters
    ----------
    venue : str, default "BYBIT"
        The execution venue.
    underlying_symbol : str, default "BTCUSDT"
        Symbol for reference price tracking (e.g. BTCUSDT perp or spot).
    trade_quantity : Decimal, default Decimal("0.01")
        Quantity of options contracts to sell per leg.
    enable_risk_management : bool, default True
        Toggle for Level 2 Automated Risk Management (Stop-Loss and Take-Profit).
        If False, runs Level 1 naked straddle with no automated exit.
    stop_loss_pct : Decimal, default Decimal("0.01")
        Stop-loss threshold: if combined buyback ask premium increases by 1% from entry.
    take_profit_pct : Decimal, default Decimal("0.02")
        Take-profit threshold: if combined buyback ask premium decreases by 2% from entry.
    target_strike : Decimal, optional
        Explicit strike override. If None, dynamically chooses nearest ATM strike.
    target_expiry : str, optional
        Explicit expiry string (e.g. "28MAR25"). If None, picks earliest valid expiry.
    execution_timeout_secs : int, default 15
        Timeout in seconds to wait for both legs to fill before mitigating asymmetry.
    """
    venue: str = "BYBIT"
    underlying_symbol: str = "BTCUSDT"
    trade_quantity: Decimal = Decimal("0.01")
    enable_risk_management: bool = True
    stop_loss_pct: Decimal = Decimal("0.01")
    take_profit_pct: Decimal = Decimal("0.02")
    target_strike: Decimal | None = None
    target_expiry: str | None = None
    execution_timeout_secs: int = 15

