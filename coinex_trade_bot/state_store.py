from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from coinex_trade_bot.models import ManagedTradeState


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> dict:
        if not self.path.exists():
            return {"trades": []}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "trades" in data:
            return data
        if isinstance(data, dict):
            return {"trades": [data]}
        if isinstance(data, list):
            return {"trades": data}
        return {"trades": []}

    def _write_all(self, payload: dict) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def save(self, state: ManagedTradeState) -> None:
        data = self._read_all()
        trades = [item for item in data["trades"] if item.get("trade_id") != state.trade_id]
        trades.append(asdict(state))
        self._write_all({"trades": trades})

    def load(self, trade_id: str) -> ManagedTradeState | None:
        for item in self._read_all()["trades"]:
            if item.get("trade_id") == trade_id:
                return ManagedTradeState(**item)
        return None

    def load_all(self) -> list[ManagedTradeState]:
        return [ManagedTradeState(**item) for item in self._read_all()["trades"]]

    def load_active(self) -> list[ManagedTradeState]:
        return [trade for trade in self.load_all() if not trade.closed]

    def load_by_market_side(self, market: str, side: str, execution_mode: str | None = None) -> ManagedTradeState | None:
        for trade in self.load_active():
            if trade.market == market and trade.side == side and (execution_mode is None or trade.execution_mode == execution_mode):
                return trade
        return None

    def delete(self, trade_id: str) -> None:
        data = self._read_all()
        trades = [item for item in data["trades"] if item.get("trade_id") != trade_id]
        self._write_all({"trades": trades})

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
