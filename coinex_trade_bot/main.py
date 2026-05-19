from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from coinex_trade_bot.coinex_client import CoinExClient
from coinex_trade_bot.config import load_settings
from coinex_trade_bot.parser import parse_signal
from coinex_trade_bot.state_store import StateStore
from coinex_trade_bot.trade_manager import TradeManager


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CoinEx multi-target trade bot")
    parser.add_argument("--signal-file", type=Path, help="Path to a text file containing the trading signal")
    parser.add_argument("--signal-text", type=str, help="Signal text passed directly on the command line")
    return parser


def load_signal_text(args: argparse.Namespace) -> str:
    if args.signal_text:
        return args.signal_text
    if args.signal_file:
        return args.signal_file.read_text(encoding="utf-8")
    raise ValueError("Pass --signal-file or --signal-text")


async def async_main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    args = build_parser().parse_args()
    settings = load_settings()
    signal_text = load_signal_text(args)
    signal = parse_signal(signal_text, break_even_override=settings.break_even_price_override)

    client = CoinExClient(settings)
    store = StateStore(settings.state_file)
    manager = TradeManager(settings, client, store)
    await manager.run_new_trade(signal)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
