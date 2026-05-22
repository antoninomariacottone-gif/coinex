from __future__ import annotations

from dataclasses import asdict

from coinex_trade_bot.db import Database, TradeRow
from coinex_trade_bot.models import ManagedTradeState


class StateStore:
    def __init__(self, database: Database):
        self.database = database

    def save(self, state: ManagedTradeState) -> None:
        payload = asdict(state)
        with self.database.session() as session:
            row = session.get(TradeRow, state.trade_id)
            if row is None:
                row = TradeRow(
                    trade_id=state.trade_id,
                    payload_json=self.database.dumps(payload),
                    closed=state.closed,
                    market=state.market,
                    side=state.side,
                    execution_mode=state.execution_mode,
                )
                session.add(row)
            else:
                row.payload_json = self.database.dumps(payload)
                row.closed = state.closed
                row.market = state.market
                row.side = state.side
                row.execution_mode = state.execution_mode

    def load(self, trade_id: str) -> ManagedTradeState | None:
        with self.database.session() as session:
            row = session.get(TradeRow, trade_id)
            return None if row is None else ManagedTradeState(**self.database.loads(row.payload_json))

    def load_all(self) -> list[ManagedTradeState]:
        with self.database.session() as session:
            rows = session.query(TradeRow).all()
            return [ManagedTradeState(**self.database.loads(row.payload_json)) for row in rows]

    def load_active(self) -> list[ManagedTradeState]:
        return [trade for trade in self.load_all() if not trade.closed]

    def load_by_market_side(self, market: str, side: str, execution_mode: str | None = None) -> ManagedTradeState | None:
        for trade in self.load_active():
            if trade.market == market and trade.side == side and (execution_mode is None or trade.execution_mode == execution_mode):
                return trade
        return None

    def delete(self, trade_id: str) -> None:
        with self.database.session() as session:
            row = session.get(TradeRow, trade_id)
            if row is not None:
                session.delete(row)

    def clear(self) -> None:
        with self.database.session() as session:
            session.query(TradeRow).delete()
