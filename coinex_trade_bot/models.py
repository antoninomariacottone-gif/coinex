from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any
from uuid import uuid4


def decimal_to_str(value: Decimal) -> str:
    return format(value, "f")


@dataclass
class ParsedSignal:
    market: str
    side: str
    entry_price: Decimal
    targets: list[Decimal]
    stop_loss: Decimal
    break_even_price: Decimal | None = None
    entry_range: list[Decimal] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["entry_price"] = decimal_to_str(self.entry_price)
        data["targets"] = [decimal_to_str(target) for target in self.targets]
        data["stop_loss"] = decimal_to_str(self.stop_loss)
        if self.break_even_price is not None:
            data["break_even_price"] = decimal_to_str(self.break_even_price)
        data["entry_range"] = [decimal_to_str(value) for value in self.entry_range]
        return data


@dataclass
class MarketInfo:
    market: str
    min_amount: Decimal
    tick_size: Decimal
    base_precision: int
    quote_precision: int
    leverage_options: list[int]
    is_api_trading_available: bool


@dataclass
class PositionPlan:
    size: Decimal
    tp_amounts: list[Decimal]
    remainder: Decimal


@dataclass
class ManagedTradeState:
    trade_id: str
    market: str
    side: str
    entry_price: str
    stop_loss: str
    break_even_price: str
    targets: list[str]
    entry_order_type: str
    signal_entry_price: str | None = None
    execution_mode: str = "live"
    source_label: str | None = None
    leverage: int = 0
    balance_pct: str | None = None
    starting_balance_quote: str | None = None
    allocated_margin_quote: str | None = None
    position_notional_quote: str | None = None
    entry_order_id: int | None = None
    position_size: str | None = None
    remaining_size: str | None = None
    tp_amounts: list[str] = field(default_factory=list)
    stop_loss_order_id: int | None = None
    take_profit_order_ids: list[int] = field(default_factory=list)
    tp1_done: bool = False
    completed_target_count: int = 0
    exits_placed: bool = False
    position_open: bool = False
    break_even_moved: bool = False
    closed: bool = False
    realized_pnl_quote: str = "0"
    realized_r_multiple: str = "0"
    realized_trade_return_pct: str = "0"
    realized_portfolio_return_pct: str = "0"
    status: str = "created"
    created_at: int = 0
    updated_at: int = 0
    raw_signal_text: str = ""
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_signal(
        cls,
        signal: ParsedSignal,
        entry_order_type: str,
        leverage: int,
        execution_mode: str = "live",
        source_label: str | None = None,
        balance_pct: Decimal | None = None,
        created_at: int = 0,
    ) -> "ManagedTradeState":
        break_even_price = signal.break_even_price or signal.entry_price
        return cls(
            trade_id=uuid4().hex[:12],
            market=signal.market,
            side=signal.side,
            entry_price=decimal_to_str(signal.entry_price),
            signal_entry_price=decimal_to_str(signal.entry_price),
            stop_loss=decimal_to_str(signal.stop_loss),
            break_even_price=decimal_to_str(break_even_price),
            targets=[decimal_to_str(target) for target in signal.targets],
            entry_order_type=entry_order_type,
            execution_mode=execution_mode,
            source_label=source_label,
            leverage=leverage,
            balance_pct=decimal_to_str(balance_pct) if balance_pct is not None else None,
            created_at=created_at,
            updated_at=created_at,
            raw_signal_text=signal.raw_text,
        )

    @property
    def market_side_key(self) -> str:
        return f"{self.market}:{self.side}"


@dataclass
class DemoChannelConfig:
    channel_id: str
    name: str
    telegram_ref: str
    balance_pct: str
    leverage: int
    enabled: bool = True
    created_at: int = 0
    updated_at: int = 0
