import os
from decimal import Decimal
from pathlib import Path
from dotenv import load_dotenv

# Load .env if present
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

BYBIT_API_KEY = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")

TRADE_QUANTITY = Decimal(os.getenv("TRADE_QUANTITY", "0.01"))
ENABLE_RISK_MANAGEMENT = os.getenv("ENABLE_RISK_MANAGEMENT", "true").lower() in ("true", "1", "yes")
STOP_LOSS_PCT = Decimal(os.getenv("STOP_LOSS_PCT", "0.01"))      # 1%
TAKE_PROFIT_PCT = Decimal(os.getenv("TAKE_PROFIT_PCT", "0.02"))  # 2%

