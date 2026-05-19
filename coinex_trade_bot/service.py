from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Any

from coinex_trade_bot.coinex_client import CoinExClient
from coinex_trade_bot.config import Settings
from coinex_trade_bot.models import ManagedTradeState, ParsedSignal
from coinex_trade_bot.parser import parse_signal
from coinex_trade_bot.state_store import StateStore
from coinex_trade_bot.trade_manager import TradeManager


LOGGER = logging.getLogger("coinex_trade_bot.service")


class BotService:
    def __init__(self, settings: Settings, client: CoinExClient, store: StateStore):
        self.settings = settings
        self.client = client
        self.store = store
        self.trade_manager = TradeManager(settings, client, store)
        self._trade_tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def _register_trade_task(self, trade_id: str, task: asyncio.Task) -> None:
        self._trade_tasks[trade_id] = task

        def _cleanup(completed_task: asyncio.Task) -> None:
            self._trade_tasks.pop(trade_id, None)
            if completed_task.cancelled():
                return
            exc = completed_task.exception()
            if exc is not None:
                LOGGER.exception("Trade task %s crashed: %s", trade_id, exc)

        task.add_done_callback(_cleanup)

    def get_state(self) -> ManagedTradeState | None:
        active = self.store.load_active()
        return active[0] if active else None

    def get_active_trades(self) -> list[ManagedTradeState]:
        return self.store.load_active()

    def _build_paper_stats(self) -> dict[str, Any]:
        all_trades = self.store.load_all()
        paper_trades = [trade for trade in all_trades if trade.execution_mode == "paper"]
        closed_paper_trades = [trade for trade in paper_trades if trade.closed]
        realized_total = sum((Decimal(trade.realized_pnl_quote) for trade in paper_trades), Decimal("0"))
        realized_r_total = sum((Decimal(trade.realized_r_multiple) for trade in paper_trades), Decimal("0"))
        positive_closed = [trade for trade in closed_paper_trades if Decimal(trade.realized_pnl_quote) > 0]
        negative_closed = [trade for trade in closed_paper_trades if Decimal(trade.realized_pnl_quote) < 0]
        breakeven_closed = [trade for trade in closed_paper_trades if Decimal(trade.realized_pnl_quote) == 0]
        win_rate = (
            (Decimal(len(positive_closed)) / Decimal(len(closed_paper_trades)) * Decimal("100"))
            if closed_paper_trades
            else Decimal("0")
        )
        return {
            "paper_trade_count": len(paper_trades),
            "paper_open_count": len([trade for trade in paper_trades if not trade.closed]),
            "paper_closed_count": len(closed_paper_trades),
            "paper_positive_count": len(positive_closed),
            "paper_negative_count": len(negative_closed),
            "paper_breakeven_count": len(breakeven_closed),
            "paper_win_rate_pct": format(win_rate.quantize(Decimal("0.01")), "f"),
            "paper_realized_pnl_quote": format(realized_total, "f"),
            "paper_realized_r_total": format(realized_r_total, "f"),
        }

    async def get_dashboard_status(self) -> dict[str, Any]:
        active_trades = self.store.load_active()
        configured = bool(self.settings.access_id and self.settings.secret_key)
        status: dict[str, Any] = {
            "state": None if not active_trades else active_trades[0].__dict__,
            "active_trades": [trade.__dict__ for trade in active_trades],
            "configured": configured,
            "dry_run": self.settings.dry_run,
            "test_trade_enabled": self.settings.test_trade_enabled,
            "test_market": self.settings.test_market,
            "test_hold_seconds": self.settings.test_hold_seconds,
            "paper_stats": self._build_paper_stats(),
            "telegram": {
                "enabled": self.settings.telegram_enabled,
                "configured": bool(
                    self.settings.telegram_api_id
                    and self.settings.telegram_api_hash
                    and self.settings.telegram_session_string
                    and (self.settings.telegram_source_chats or self.settings.telegram_paper_source_chats)
                ),
                "source_chats": self.settings.telegram_source_chats,
                "balance_pct_override": None if self.settings.telegram_balance_pct is None else format(self.settings.telegram_balance_pct, "f"),
                "leverage_override": self.settings.telegram_leverage,
                "paper_source_chats": self.settings.telegram_paper_source_chats,
                "paper_balance_pct_override": None if self.settings.telegram_paper_balance_pct is None else format(self.settings.telegram_paper_balance_pct, "f"),
                "paper_leverage_override": self.settings.telegram_paper_leverage,
            },
        }

        if not configured:
            status["balance"] = None
            status["balance_error"] = "Missing CoinEx API keys"
            return status

        try:
            balances = self.client.get_futures_balance()
            quote_balance = next(
                (item for item in balances if item["ccy"].upper() == self.settings.futures_quote_ccy.upper()),
                None,
            )
            non_zero_balances = [
                {
                    "ccy": item["ccy"],
                    "available": item.get("available"),
                    "frozen": item.get("frozen"),
                    "margin": item.get("margin"),
                }
                for item in balances
                if any(Decimal(item.get(field, "0")) != 0 for field in ("available", "frozen", "margin"))
            ]
            status["balance"] = {
                "quote_ccy": self.settings.futures_quote_ccy,
                "quote_available": None if quote_balance is None else quote_balance.get("available"),
                "quote_frozen": None if quote_balance is None else quote_balance.get("frozen"),
                "assets": non_zero_balances,
            }
        except Exception as exc:  # noqa: BLE001
            status["balance"] = None
            status["balance_error"] = str(exc)

        return status

    async def startup(self) -> None:
        for state in self.store.load_active():
            LOGGER.info("Resuming active trade %s for %s", state.trade_id, state.market)
            self._register_trade_task(state.trade_id, asyncio.create_task(self.trade_manager.resume_trade_from_state(state)))

    async def submit_signal(
        self,
        signal_text: str,
        leverage: int | None = None,
        balance_pct: Decimal | None = None,
        execution_mode: str = "live",
        source_label: str | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            signal = parse_signal(signal_text, break_even_override=self.settings.break_even_price_override)
            self._ensure_trade_slot_available(signal.market, signal.side, execution_mode=execution_mode)
            market_info = self.client.get_market_info(signal.market)
            plan = self.trade_manager.build_position_plan(signal, market_info, leverage=leverage, balance_pct=balance_pct)
            summary = self.trade_manager.summarize(
                signal,
                plan,
                market_info,
                leverage=leverage,
                balance_pct=balance_pct,
                execution_mode=execution_mode,
            )
            if execution_mode == "paper":
                state = await self.trade_manager.run_new_paper_trade(
                    signal,
                    leverage_override=leverage,
                    balance_pct_override=balance_pct,
                    source_label=source_label,
                )
            else:
                state = await self.trade_manager.run_new_trade(
                    signal,
                    leverage_override=leverage,
                    balance_pct_override=balance_pct,
                    source_label=source_label,
                )

            if not state.closed and state.status != "dry_run":
                self._register_trade_task(
                    state.trade_id,
                    asyncio.create_task(self.trade_manager.resume_trade_from_state(self.store.load(state.trade_id) or state)),
                )
            summary["trade_id"] = state.trade_id
            summary["market_side_key"] = state.market_side_key
            summary["execution_mode"] = state.execution_mode
            return summary

    async def test_connection(self) -> dict[str, Any]:
        market_info = self.client.get_market_info(self.settings.test_market)
        balance = self.client.get_futures_balance()
        quote_balance = next(
            (item for item in balance if item["ccy"].upper() == self.settings.futures_quote_ccy.upper()),
            None,
        )
        return {
            "market": market_info.market,
            "api_trading_available": market_info.is_api_trading_available,
            "min_amount": format(market_info.min_amount, "f"),
            "tick_size": format(market_info.tick_size, "f"),
            "leverage_options": market_info.leverage_options,
            "balance_ccy_count": len(balance),
            "quote_balance": quote_balance,
        }

    async def run_test_trade(self) -> dict[str, Any]:
        if not self.settings.test_trade_enabled:
            raise RuntimeError("TEST_TRADE_ENABLED=false")
        async with self._lock:
            self._ensure_trade_slot_available(self.settings.test_market, "long")

            market_info = self.client.get_market_info(self.settings.test_market)
            if not market_info.is_api_trading_available:
                raise RuntimeError(f"API trading not available on {self.settings.test_market}")
            if self.settings.leverage not in market_info.leverage_options:
                raise RuntimeError(f"Leverage {self.settings.leverage}x not available on {self.settings.test_market}")

            if self.settings.test_position_size_base is not None:
                size = self.client.quantize_amount(self.settings.test_position_size_base, market_info.base_precision)
            else:
                size = market_info.min_amount

            if size < market_info.min_amount:
                size = market_info.min_amount

            self.client.adjust_leverage(self.settings.test_market)
            entry = self.client.place_entry_order(
                self.settings.test_market,
                "long",
                size,
                None,
                order_type_override="market",
            )
            await asyncio.sleep(self.settings.test_hold_seconds)
            close = self.client.close_position(self.settings.test_market, order_type="market", amount=size)
            return {
                "market": self.settings.test_market,
                "size": format(size, "f"),
                "entry_order_id": entry["order_id"],
                "close_order_id": close["order_id"],
                "hold_seconds": self.settings.test_hold_seconds,
                "real_trade": True,
            }

    async def close_trade(self, trade_id: str) -> dict[str, Any]:
        async with self._lock:
            state = self.store.load(trade_id)
            if state is None:
                raise RuntimeError(f"Trade {trade_id} not found")
            closed_state = await self.trade_manager.close_trade(state)
            task = self._trade_tasks.get(trade_id)
            if task and not task.done() and not closed_state.position_open:
                task.cancel()
                self._trade_tasks.pop(trade_id, None)
            return {"trade_id": trade_id, "market": closed_state.market, "status": closed_state.status}

    def _ensure_trade_slot_available(self, market: str, side: str, execution_mode: str = "live") -> None:
        existing = self.store.load_by_market_side(market, side, execution_mode=execution_mode)
        if existing is not None:
            raise RuntimeError(
                f"There is already an active {execution_mode} trade on {market} {side}. "
                "This bot allows only one active trade per market+side inside the same execution mode."
            )
