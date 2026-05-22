from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
import time

from coinex_trade_bot.coinex_client import CoinExClient
from coinex_trade_bot.config import Settings
from coinex_trade_bot.models import ManagedTradeState, MarketInfo, ParsedSignal, PositionPlan
from coinex_trade_bot.state_store import StateStore


LOGGER = logging.getLogger("coinex_trade_bot")


class TradeManager:
    def __init__(self, settings: Settings, client: CoinExClient, store: StateStore):
        self.settings = settings
        self.client = client
        self.store = store

    def _get_available_balance(self, ccy: str) -> Decimal:
        balances = self.client.get_futures_balance()
        for item in balances:
            if item["ccy"].upper() == ccy.upper():
                return Decimal(item["available"])
        raise ValueError(f"No futures balance found for {ccy}")

    def _touch(self, state: ManagedTradeState, note: str | None = None, status: str | None = None) -> None:
        state.updated_at = int(time.time() * 1000)
        if note:
            state.notes.append(note)
        if status:
            state.status = status
        self.store.save(state)

    def _select_trigger_price(self, item: dict) -> Decimal:
        price_type = self.settings.trigger_price_type
        if price_type == "mark_price":
            candidate = item.get("mark_price") or item.get("last")
        elif price_type == "index_price":
            candidate = item.get("index_price") or item.get("last")
        else:
            candidate = item.get("last")
        if candidate is None:
            raise RuntimeError(f"Missing trigger price in market update for price type {price_type}")
        return Decimal(str(candidate))

    def prepare_paper_signal(self, signal: ParsedSignal) -> ParsedSignal:
        ticker = self.client.get_futures_ticker(signal.market)
        start_price = self._select_trigger_price(ticker)
        return ParsedSignal(
            market=signal.market,
            side=signal.side,
            entry_price=start_price,
            targets=signal.targets,
            stop_loss=signal.stop_loss,
            break_even_price=start_price,
            raw_text=signal.raw_text,
        )

    def _split_take_profit_amounts(self, size: Decimal, split_count: int, base_precision: int) -> list[Decimal]:
        tp_amounts: list[Decimal] = []
        remaining = size
        for index in range(split_count):
            if index == split_count - 1:
                amount = remaining
            else:
                amount = self.client.quantize_amount(size / Decimal(split_count), base_precision)
                remaining -= amount
            tp_amounts.append(amount)

        if sum(tp_amounts) != size:
            tp_amounts[-1] = size - sum(tp_amounts[:-1])
        return tp_amounts

    def build_position_plan(
        self,
        signal: ParsedSignal,
        market_info: MarketInfo,
        leverage: int | None = None,
        balance_pct: Decimal | None = None,
    ) -> PositionPlan:
        leverage = leverage or self.settings.leverage
        effective_balance_pct = balance_pct if balance_pct is not None else self.settings.default_balance_pct
        available_balance: Decimal | None = None

        if effective_balance_pct is not None:
            if effective_balance_pct <= 0 or effective_balance_pct > 100:
                raise ValueError("Balance percentage must be between 0 and 100")
            available_balance = self._get_available_balance(self.settings.futures_quote_ccy)
            margin_budget = available_balance * (effective_balance_pct / Decimal("100"))
            raw_size = (margin_budget * Decimal(leverage)) / signal.entry_price
            size = self.client.quantize_amount(raw_size, market_info.base_precision)
        elif self.settings.position_size_base is not None:
            size = self.client.quantize_amount(self.settings.position_size_base, market_info.base_precision)
        else:
            assert self.settings.margin_usdt is not None
            notional = self.settings.margin_usdt * Decimal(leverage)
            raw_size = notional / signal.entry_price
            size = self.client.quantize_amount(raw_size, market_info.base_precision)

        if size < market_info.min_amount:
            raise ValueError(f"Position size {size} is smaller than CoinEx minimum amount {market_info.min_amount}")

        split_count = len(signal.targets)
        tp_amounts = self._split_take_profit_amounts(size, split_count, market_info.base_precision)

        if any(amount <= 0 for amount in tp_amounts):
            raise ValueError(
                f"Position size {size} is too small to split into {split_count} targets with "
                f"{market_info.base_precision} decimals. Increase balance percentage or reduce the number of targets."
            )

        return PositionPlan(size=size, tp_amounts=tp_amounts, remainder=tp_amounts[-1])

    def summarize(
        self,
        signal: ParsedSignal,
        plan: PositionPlan,
        market_info: MarketInfo,
        leverage: int | None = None,
        balance_pct: Decimal | None = None,
        execution_mode: str = "live",
    ) -> dict[str, object]:
        leverage = leverage or self.settings.leverage
        effective_balance_pct = balance_pct if balance_pct is not None else self.settings.default_balance_pct
        return {
            "market": signal.market,
            "side": signal.side,
            "entry_price": format(signal.entry_price, "f"),
            "stop_loss": format(signal.stop_loss, "f"),
            "break_even_price": format((signal.break_even_price or signal.entry_price), "f"),
            "targets": [format(target, "f") for target in signal.targets],
            "position_size": format(plan.size, "f"),
            "take_profit_amounts": [format(amount, "f") for amount in plan.tp_amounts],
            "min_amount": format(market_info.min_amount, "f"),
            "tick_size": format(market_info.tick_size, "f"),
            "leverage": leverage,
            "balance_pct": None if effective_balance_pct is None else format(effective_balance_pct, "f"),
            "margin_mode": self.settings.margin_mode,
            "trigger_price_type": self.settings.trigger_price_type,
            "entry_order_type": self.settings.entry_order_type,
            "break_even_mode": self.settings.break_even_mode,
            "execution_mode": execution_mode,
            "dry_run": self.settings.dry_run,
        }

    async def run_new_trade(
        self,
        signal: ParsedSignal,
        leverage_override: int | None = None,
        balance_pct_override: Decimal | None = None,
        source_label: str | None = None,
    ) -> None:
        leverage = leverage_override or self.settings.leverage
        market_info = self.client.get_market_info(signal.market)
        if not market_info.is_api_trading_available:
            raise RuntimeError(f"API trading is not available for {signal.market}")
        if leverage not in market_info.leverage_options:
            raise RuntimeError(
                f"Leverage {leverage}x is not available for {signal.market}. "
                f"Allowed: {market_info.leverage_options}"
            )

        plan = self.build_position_plan(signal, market_info, leverage=leverage, balance_pct=balance_pct_override)
        summary = self.summarize(
            signal,
            plan,
            market_info,
            leverage=leverage,
            balance_pct=balance_pct_override,
            execution_mode="live",
        )
        LOGGER.info("Trade summary:\n%s", json.dumps(summary, indent=2))
        created_at = int(time.time() * 1000)
        state = ManagedTradeState.from_signal(
            signal,
            self.settings.entry_order_type,
            leverage=leverage,
            execution_mode="live",
            source_label=source_label,
            balance_pct=balance_pct_override,
            created_at=created_at,
        )
        state.position_size = format(plan.size, "f")
        state.tp_amounts = [format(amount, "f") for amount in plan.tp_amounts]
        self._touch(state, status="planned")

        if self.settings.dry_run:
            LOGGER.warning("DRY_RUN=true, no live order will be sent.")
            state.closed = True
            self._touch(state, note="Dry-run summary generated", status="dry_run")
            return state

        try:
            self.client.adjust_leverage(signal.market, leverage=leverage)
            self._touch(state, note=f"Leverage set to {leverage}x", status="awaiting_entry")

            entry_response = self.client.place_entry_order(
                market=signal.market,
                side=signal.side,
                amount=plan.size,
                price=signal.entry_price if self.settings.entry_order_type == "limit" else None,
            )
            state.entry_order_id = entry_response["order_id"]
            self._touch(state, note=f"Entry order placed: {entry_response['order_id']}", status="entry_submitted")
            return state
        except Exception as exc:
            state.closed = True
            self._touch(state, note=f"Trade setup failed: {exc}", status="error")
            raise

    async def run_new_paper_trade(
        self,
        signal: ParsedSignal,
        leverage_override: int | None = None,
        balance_pct_override: Decimal | None = None,
        source_label: str | None = None,
    ) -> ManagedTradeState:
        leverage = leverage_override or self.settings.leverage
        market_info = self.client.get_market_info(signal.market)
        if not market_info.is_api_trading_available:
            raise RuntimeError(f"API trading is not available for {signal.market}")

        plan = self.build_position_plan(signal, market_info, leverage=leverage, balance_pct=balance_pct_override)
        summary = self.summarize(
            signal,
            plan,
            market_info,
            leverage=leverage,
            balance_pct=balance_pct_override,
            execution_mode="paper",
        )
        LOGGER.info("Paper trade summary:\n%s", json.dumps(summary, indent=2))
        created_at = int(time.time() * 1000)
        state = ManagedTradeState.from_signal(
            signal,
            entry_order_type="market",
            leverage=leverage,
            execution_mode="paper",
            source_label=source_label,
            balance_pct=balance_pct_override,
            created_at=created_at,
        )
        state.position_size = format(plan.size, "f")
        state.remaining_size = format(plan.size, "f")
        state.tp_amounts = [format(amount, "f") for amount in plan.tp_amounts]
        state.position_open = True
        state.exits_placed = True
        state.signal_entry_price = state.signal_entry_price or format(signal.entry_price, "f")
        self._touch(state, note=f"Paper trade opened at live price {signal.entry_price}", status="paper_open")
        return state

    async def resume_trade_from_state(self, state: ManagedTradeState) -> None:
        signal = ParsedSignal(
            market=state.market,
            side=state.side,
            entry_price=Decimal(state.entry_price),
            targets=[Decimal(value) for value in state.targets],
            stop_loss=Decimal(state.stop_loss),
            break_even_price=Decimal(state.break_even_price),
            raw_text=state.raw_signal_text,
        )
        market_info = self.client.get_market_info(state.market)
        tp_amounts = [Decimal(value) for value in state.tp_amounts] if state.tp_amounts else []
        position_size = Decimal(state.position_size) if state.position_size else Decimal("0")
        plan = PositionPlan(size=position_size, tp_amounts=tp_amounts, remainder=tp_amounts[-1] if tp_amounts else Decimal("0"))
        if state.execution_mode == "paper":
            await self.monitor_paper_trade(signal, plan, state, market_info)
        else:
            await self.monitor_trade(signal, plan, state, market_info)

    async def close_trade(self, state: ManagedTradeState) -> ManagedTradeState:
        if state.execution_mode == "paper":
            state.closed = True
            self._touch(state, note="Paper trade closed manually", status="closed")
            return state
        try:
            if state.entry_order_id and not state.position_open:
                try:
                    self.client.cancel_order(state.market, state.entry_order_id)
                    self._touch(state, note=f"Pending entry order canceled: {state.entry_order_id}")
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning("Entry cancel failed for %s: %s", state.trade_id, exc)

            try:
                self.client.cancel_position_take_profit(state.market)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Take-profit cancel failed for %s: %s", state.trade_id, exc)
            try:
                self.client.cancel_position_stop_loss(state.market)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Stop-loss cancel failed for %s: %s", state.trade_id, exc)

            if state.position_open:
                self.client.close_position(state.market, order_type="market")
                self._touch(state, note="Manual market close sent", status="closing")
            else:
                state.closed = True
                self._touch(state, note="Trade closed before entry fill", status="closed")
            return state
        except Exception:
            self._touch(state, note="Manual close failed", status="error")
            raise

    async def monitor_trade(
        self,
        signal: ParsedSignal,
        plan: PositionPlan,
        state: ManagedTradeState,
        market_info: MarketInfo,
    ) -> None:
        conn = await self.client.ws_connect()
        try:
            await self.client.ws_auth(conn)
            await self._subscribe(conn, "state.subscribe", [signal.market], request_id=10)
            await self._subscribe(conn, "position.subscribe", [signal.market], request_id=11)
            await self._subscribe(conn, "user_deals.subscribe", [signal.market], request_id=12)
            await self._subscribe(conn, "order.subscribe", [signal.market], request_id=13)
            asyncio.create_task(self.client.ws_ping(conn))
            await self._reconcile_live_position(signal, plan, state, market_info)

            while not state.closed:
                try:
                    message = await asyncio.wait_for(self.client.ws_recv_json(conn), timeout=5)
                    await self._handle_message(message, signal, plan, state, market_info)
                except asyncio.TimeoutError:
                    await self._reconcile_live_position(signal, plan, state, market_info)
        except Exception as exc:
            self._touch(state, note=f"Live monitor failed: {exc}", status="error")
            raise
        finally:
            await conn.close()

    async def _subscribe(self, conn, method: str, markets: list[str], request_id: int) -> None:
        await conn.send(json.dumps({"method": method, "params": {"market_list": markets}, "id": request_id}))

    async def _handle_message(
        self,
        message: dict,
        signal: ParsedSignal,
        plan: PositionPlan,
        state: ManagedTradeState,
        market_info: MarketInfo,
    ) -> None:
        method = message.get("method")
        if method == "position.update":
            await self._handle_position_update(message["data"]["position"], signal, plan, state, market_info)
        elif method == "user_deals.update":
            await self._handle_user_deal(message["data"], signal, state)
        elif method == "state.update" and self.settings.break_even_mode == "price_touch":
            await self._handle_price_touch(message["data"]["state_list"], signal, state)
        elif method == "order.update":
            LOGGER.info("Order update: %s", message["data"])

    async def _handle_position_update(
        self,
        position: dict,
        signal: ParsedSignal,
        plan: PositionPlan,
        state: ManagedTradeState,
        market_info: MarketInfo,
    ) -> None:
        side_ok = position["side"] == signal.side
        amount = Decimal(position["open_interest"])
        if not side_ok:
            return

        avg_entry_price = position.get("avg_entry_price")
        if avg_entry_price and Decimal(avg_entry_price) > 0 and not state.break_even_moved:
            normalized_avg_entry = format(Decimal(avg_entry_price), "f")
            if state.break_even_price != normalized_avg_entry:
                state.break_even_price = normalized_avg_entry
                self._touch(state, note=f"Average entry price synced from CoinEx: {state.break_even_price}")

        if amount > 0 and not state.position_open:
            state.position_open = True
            self._touch(state, note=f"Position opened with size {amount}", status="position_open")

        if amount > 0 and not state.exits_placed:
            await self._place_exit_orders(signal, amount, state, market_info)

        current_tp_ids = {item["id"] for item in position.get("take_profit_list", [])}
        if state.take_profit_order_ids and not state.tp1_done:
            first_tp_id = state.take_profit_order_ids[0]
            if first_tp_id not in current_tp_ids:
                state.tp1_done = True
                self._touch(state, note="First take-profit filled", status="tp1_hit")
                await self._move_stop_to_break_even(signal, state)
                return

        if not state.tp1_done and self._did_position_reduce_after_tp1(state, amount):
            state.tp1_done = True
            self._touch(state, note="First take-profit inferred from reduced position size", status="tp1_hit")
            await self._move_stop_to_break_even(signal, state)
            return

        current_stop_ids = [item["id"] for item in position.get("stop_loss_list", [])]
        if current_stop_ids and state.stop_loss_order_id is None:
            state.stop_loss_order_id = current_stop_ids[0]
            self._touch(state)

        if amount == 0 and state.position_open:
            state.closed = True
            self._touch(state, note="Position closed", status="closed")
            await self._cleanup_after_close(signal.market)

    async def _handle_user_deal(self, deal: dict, signal: ParsedSignal, state: ManagedTradeState) -> None:
        if deal.get("market") != signal.market:
            return
        LOGGER.info("User deal update: %s", deal)

    async def _handle_price_touch(self, state_list: list[dict], signal: ParsedSignal, state: ManagedTradeState) -> None:
        if state.break_even_moved or not state.position_open:
            return
        for item in state_list:
            if item.get("market") != signal.market:
                continue
            last = self._select_trigger_price(item)
            target_1 = signal.targets[0]
            touched = last >= target_1 if signal.side == "long" else last <= target_1
            if touched:
                await self._move_stop_to_break_even(signal, state)
                return

    async def _place_exit_orders(
        self,
        signal: ParsedSignal,
        position_amount: Decimal,
        state: ManagedTradeState,
        market_info: MarketInfo,
    ) -> None:
        if state.exits_placed:
            return

        tp_amounts = self._split_take_profit_amounts(position_amount, len(signal.targets), market_info.base_precision)
        if any(amount <= 0 for amount in tp_amounts):
            raise RuntimeError(
                f"Position size {position_amount} is too small to build {len(signal.targets)} partial take-profits "
                f"with {market_info.base_precision} decimals."
            )

        sl_response = self.client.set_position_stop_loss(signal.market, signal.stop_loss)
        stop_items = sl_response.get("stop_loss_list", [])
        if stop_items:
            full_stop = next((item for item in stop_items if item.get("is_all")), stop_items[0])
            state.stop_loss_order_id = full_stop["id"]

        tp_ids: list[int] = []
        for target, amount in zip(signal.targets, tp_amounts):
            price = self.client.quantize_price(target, market_info.tick_size)
            response = self.client.set_position_take_profit(signal.market, price, amount)
            tp_item = response["take_profit_list"][-1]
            tp_ids.append(tp_item["id"])

        state.position_size = format(position_amount, "f")
        state.tp_amounts = [format(amount, "f") for amount in tp_amounts]
        state.take_profit_order_ids = tp_ids
        state.exits_placed = True
        self._touch(state, note="Single position exit ladder placed", status="protected")

    async def _move_stop_to_break_even(self, signal: ParsedSignal, state: ManagedTradeState) -> None:
        if state.break_even_moved:
            return
        if state.stop_loss_order_id is None:
            raise RuntimeError("Cannot move stop to break even: stop_loss_order_id is missing")

        break_even = Decimal(state.break_even_price)
        self.client.modify_position_stop_loss(signal.market, state.stop_loss_order_id, break_even)
        state.break_even_moved = True
        self._touch(state, note=f"Stop moved to break-even at {break_even}", status="break_even")

    async def _cleanup_after_close(self, market: str) -> None:
        try:
            self.client.cancel_position_stop_loss(market)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Stop-loss cleanup failed: %s", exc)
        try:
            self.client.cancel_position_take_profit(market)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Take-profit cleanup failed: %s", exc)

    async def _reconcile_live_position(
        self,
        signal: ParsedSignal,
        plan: PositionPlan,
        state: ManagedTradeState,
        market_info: MarketInfo,
    ) -> None:
        try:
            positions = self.client.get_pending_position(signal.market)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Live position reconciliation failed for %s: %s", signal.market, exc)
            return

        matching_position = None
        for item in positions:
            side = str(item.get("side", "")).lower()
            if side == signal.side:
                matching_position = item
                break

        if matching_position is None:
            if state.position_open:
                state.closed = True
                self._touch(state, note="Position closed (REST reconciliation)", status="closed")
                await self._cleanup_after_close(signal.market)
            return

        open_interest = Decimal(str(matching_position.get("open_interest", "0")))
        if open_interest <= 0:
            if state.position_open:
                state.closed = True
                self._touch(state, note="Position closed (REST reconciliation)", status="closed")
                await self._cleanup_after_close(signal.market)
            return

        normalized_position = {
            "side": matching_position.get("side", signal.side),
            "open_interest": str(open_interest),
            "avg_entry_price": matching_position.get("avg_entry_price") or matching_position.get("open_avg_price") or matching_position.get("entry_price"),
            "take_profit_list": matching_position.get("take_profit_list", []),
            "stop_loss_list": matching_position.get("stop_loss_list", []),
        }
        await self._handle_position_update(normalized_position, signal, plan, state, market_info)

    async def monitor_paper_trade(
        self,
        signal: ParsedSignal,
        plan: PositionPlan,
        state: ManagedTradeState,
        market_info: MarketInfo,
    ) -> None:
        conn = await self.client.ws_connect()
        try:
            await self._subscribe(conn, "state.subscribe", [signal.market], request_id=30)
            asyncio.create_task(self.client.ws_ping(conn))
            await self._reconcile_paper_price(signal, plan, state, market_info)

            while not state.closed:
                try:
                    message = await asyncio.wait_for(self.client.ws_recv_json(conn), timeout=5)
                    if message.get("method") != "state.update":
                        continue
                    await self._handle_paper_price_update(message["data"]["state_list"], signal, plan, state, market_info)
                except asyncio.TimeoutError:
                    await self._reconcile_paper_price(signal, plan, state, market_info)
        except Exception as exc:
            self._touch(state, note=f"Paper monitor failed: {exc}", status="error")
            raise
        finally:
            await conn.close()

    async def _handle_paper_price_update(
        self,
        state_list: list[dict],
        signal: ParsedSignal,
        plan: PositionPlan,
        state: ManagedTradeState,
        market_info: MarketInfo,
    ) -> None:
        for item in state_list:
            if item.get("market") != signal.market:
                continue

            last = self._select_trigger_price(item)
            while state.completed_target_count < len(signal.targets):
                target_index = state.completed_target_count
                target_price = signal.targets[target_index]
                touched = last >= target_price if signal.side == "long" else last <= target_price
                if not touched:
                    break

                tp_amount = plan.tp_amounts[target_index]
                self._apply_paper_realized_pnl(state, signal, tp_amount, target_price)
                state.completed_target_count += 1
                state.tp1_done = state.completed_target_count >= 1
                remaining = Decimal(state.remaining_size or "0") - tp_amount
                state.remaining_size = format(max(remaining, Decimal("0")), "f")
                if state.completed_target_count == 1 and not state.break_even_moved:
                    state.break_even_moved = True
                    self._touch(
                        state,
                        note=f"Paper TP1 hit at {target_price}; stop moved to break-even {state.break_even_price}",
                        status="break_even",
                    )
                else:
                    self._touch(
                        state,
                        note=f"Paper TP{state.completed_target_count} hit at {target_price}",
                        status=f"paper_tp{state.completed_target_count}",
                    )

            if state.completed_target_count >= len(signal.targets):
                state.closed = True
                state.position_open = False
                self._touch(state, note="Paper trade closed on final target", status="closed")
                return

            stop_price = Decimal(state.break_even_price) if state.break_even_moved else signal.stop_loss
            stopped = last <= stop_price if signal.side == "long" else last >= stop_price
            if stopped:
                remaining_amount = Decimal(state.remaining_size or "0")
                if remaining_amount > 0:
                    self._apply_paper_realized_pnl(state, signal, remaining_amount, stop_price)
                state.remaining_size = "0"
                state.position_open = False
                state.closed = True
                state.break_even_moved = state.break_even_moved or stop_price == Decimal(state.break_even_price)
                label = "break-even" if stop_price == Decimal(state.break_even_price) else "stop-loss"
                self._touch(state, note=f"Paper trade closed by {label} at {stop_price}", status="closed")
                return

    def _apply_paper_realized_pnl(
        self,
        state: ManagedTradeState,
        signal: ParsedSignal,
        amount: Decimal,
        exit_price: Decimal,
    ) -> None:
        entry = Decimal(state.entry_price)
        price_delta = exit_price - entry if signal.side == "long" else entry - exit_price
        realized = Decimal(state.realized_pnl_quote) + (price_delta * amount)
        state.realized_pnl_quote = format(realized, "f")

        initial_size = Decimal(state.position_size or "0")
        risk_per_unit = abs(entry - Decimal(state.stop_loss))
        total_risk = risk_per_unit * initial_size
        if total_risk > 0:
            state.realized_r_multiple = format(realized / total_risk, "f")

    async def _reconcile_paper_price(
        self,
        signal: ParsedSignal,
        plan: PositionPlan,
        state: ManagedTradeState,
        market_info: MarketInfo,
    ) -> None:
        try:
            ticker = self.client.get_futures_ticker(signal.market)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Paper price reconciliation failed for %s: %s", signal.market, exc)
            return

        synthetic_state = {
            "market": signal.market,
            "last": ticker.get("last"),
            "mark_price": ticker.get("mark_price"),
            "index_price": ticker.get("index_price"),
        }
        await self._handle_paper_price_update([synthetic_state], signal, plan, state, market_info)

    def _did_position_reduce_after_tp1(self, state: ManagedTradeState, current_amount: Decimal) -> bool:
        if not state.position_size or not state.tp_amounts:
            return False
        initial_amount = Decimal(state.position_size)
        first_tp_amount = Decimal(state.tp_amounts[0])
        if first_tp_amount <= 0 or current_amount <= 0:
            return False
        expected_after_tp1 = initial_amount - first_tp_amount
        return current_amount <= expected_after_tp1 or current_amount < initial_amount
