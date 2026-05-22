from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _load_secret(name: str, required: bool = True) -> str:
    direct = os.getenv(name, "").strip()
    if direct:
        return direct

    file_path = os.getenv(f"{name}_FILE", "").strip()
    if file_path:
        return Path(file_path).read_text(encoding="utf-8").strip()

    if not required:
        return ""

    raise ValueError(f"Missing required environment variable: {name} or {name}_FILE")


@dataclass(frozen=True)
class Settings:
    access_id: str
    secret_key: str
    dry_run: bool
    market_type: str
    margin_mode: str
    leverage: int
    default_balance_pct: Decimal | None
    trigger_price_type: str
    position_size_base: Decimal | None
    margin_usdt: Decimal | None
    entry_order_type: str
    break_even_mode: str
    break_even_price_override: Decimal | None
    state_file: Path
    demo_channels_file: Path
    log_level: str
    dashboard_username: str
    dashboard_password: str
    test_trade_enabled: bool
    test_market: str
    test_hold_seconds: int
    test_position_size_base: Decimal | None
    test_margin_usdt: Decimal | None
    futures_quote_ccy: str
    telegram_enabled: bool
    telegram_api_id: int | None
    telegram_api_hash: str
    telegram_session_string: str
    telegram_source_chats: list[str]
    telegram_balance_pct: Decimal | None
    telegram_leverage: int | None
    telegram_paper_source_chats: list[str]
    telegram_paper_balance_pct: Decimal | None
    telegram_paper_leverage: int | None
    http_base_url: str = "https://api.coinex.com/v2"
    ws_futures_url: str = "wss://socket.coinex.com/v2/futures"


def _parse_decimal(name: str) -> Decimal | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return Decimal(raw)


def load_settings(allow_missing_secrets: bool = False) -> Settings:
    entry_order_type = os.getenv("ENTRY_ORDER_TYPE", "limit").strip().lower()
    if entry_order_type not in {"limit", "market"}:
        raise ValueError("ENTRY_ORDER_TYPE must be 'limit' or 'market'")

    break_even_mode = os.getenv("BREAK_EVEN_MODE", "tp1_fill").strip().lower()
    if break_even_mode not in {"tp1_fill", "price_touch"}:
        raise ValueError("BREAK_EVEN_MODE must be 'tp1_fill' or 'price_touch'")

    trigger_price_type = os.getenv("COINEX_TRIGGER_PRICE_TYPE", "latest_price").strip().lower()
    if trigger_price_type not in {"latest_price", "mark_price", "index_price"}:
        raise ValueError("COINEX_TRIGGER_PRICE_TYPE must be latest_price, mark_price, or index_price")

    margin_mode = os.getenv("COINEX_MARGIN_MODE", "isolated").strip().lower()
    if margin_mode not in {"isolated", "cross"}:
        raise ValueError("COINEX_MARGIN_MODE must be isolated or cross")

    position_size_base = _parse_decimal("POSITION_SIZE_BASE")
    margin_usdt = _parse_decimal("MARGIN_USDT")
    default_balance_pct = _parse_decimal("DEFAULT_BALANCE_PCT")
    if position_size_base is None and margin_usdt is None and default_balance_pct is None:
        raise ValueError("Set POSITION_SIZE_BASE, MARGIN_USDT, or DEFAULT_BALANCE_PCT")

    state_file = Path(os.getenv("STATE_FILE", r"runtime\active_trade.json"))
    demo_channels_file = Path(os.getenv("DEMO_CHANNELS_FILE", r"runtime\demo_channels.json"))
    telegram_enabled = os.getenv("TELEGRAM_ENABLED", "false").strip().lower() == "true"
    telegram_api_id_raw = os.getenv("TELEGRAM_API_ID", "").strip()
    telegram_api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    telegram_session_string = os.getenv("TELEGRAM_SESSION_STRING", "").strip()
    telegram_source_chats = [item.strip() for item in os.getenv("TELEGRAM_SOURCE_CHATS", "").split(",") if item.strip()]
    telegram_paper_source_chats = [item.strip() for item in os.getenv("TELEGRAM_PAPER_SOURCE_CHATS", "").split(",") if item.strip()]
    return Settings(
        access_id=_load_secret("COINEX_ACCESS_ID", required=not allow_missing_secrets),
        secret_key=_load_secret("COINEX_SECRET_KEY", required=not allow_missing_secrets),
        dry_run=os.getenv("DRY_RUN", "true").strip().lower() == "true",
        market_type=os.getenv("COINEX_MARKET_TYPE", "FUTURES").strip().upper(),
        margin_mode=margin_mode,
        leverage=int(os.getenv("COINEX_LEVERAGE", "20")),
        default_balance_pct=default_balance_pct,
        trigger_price_type=trigger_price_type,
        position_size_base=position_size_base,
        margin_usdt=margin_usdt,
        entry_order_type=entry_order_type,
        break_even_mode=break_even_mode,
        break_even_price_override=_parse_decimal("BREAK_EVEN_PRICE_OVERRIDE"),
        state_file=state_file,
        demo_channels_file=demo_channels_file,
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        dashboard_username=os.getenv("BOT_DASHBOARD_USERNAME", "admin").strip(),
        dashboard_password=_require("BOT_DASHBOARD_PASSWORD"),
        test_trade_enabled=os.getenv("TEST_TRADE_ENABLED", "false").strip().lower() == "true",
        test_market=os.getenv("TEST_MARKET", "BTCUSDT").strip().upper(),
        test_hold_seconds=int(os.getenv("TEST_HOLD_SECONDS", "2")),
        test_position_size_base=_parse_decimal("TEST_POSITION_SIZE_BASE"),
        test_margin_usdt=_parse_decimal("TEST_MARGIN_USDT"),
        futures_quote_ccy=os.getenv("FUTURES_QUOTE_CCY", "USDT").strip().upper(),
        telegram_enabled=telegram_enabled,
        telegram_api_id=int(telegram_api_id_raw) if telegram_api_id_raw else None,
        telegram_api_hash=telegram_api_hash,
        telegram_session_string=telegram_session_string,
        telegram_source_chats=telegram_source_chats,
        telegram_balance_pct=_parse_decimal("TELEGRAM_BALANCE_PCT"),
        telegram_leverage=int(os.getenv("TELEGRAM_LEVERAGE", "0")) or None,
        telegram_paper_source_chats=telegram_paper_source_chats,
        telegram_paper_balance_pct=_parse_decimal("TELEGRAM_PAPER_BALANCE_PCT"),
        telegram_paper_leverage=int(os.getenv("TELEGRAM_PAPER_LEVERAGE", "0")) or None,
    )
