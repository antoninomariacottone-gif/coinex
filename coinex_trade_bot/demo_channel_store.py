from __future__ import annotations

import time
from dataclasses import asdict
from uuid import uuid4

from coinex_trade_bot.db import Database, DemoChannelRow
from coinex_trade_bot.models import DemoChannelConfig


class DemoChannelStore:
    def __init__(self, database: Database):
        self.database = database

    def list_all(self) -> list[DemoChannelConfig]:
        with self.database.session() as session:
            rows = session.query(DemoChannelRow).all()
            return [DemoChannelConfig(**self.database.loads(row.payload_json)) for row in rows]

    def list_enabled(self) -> list[DemoChannelConfig]:
        return [item for item in self.list_all() if item.enabled]

    def load(self, channel_id: str) -> DemoChannelConfig | None:
        with self.database.session() as session:
            row = session.get(DemoChannelRow, channel_id)
            return None if row is None else DemoChannelConfig(**self.database.loads(row.payload_json))

    def save(self, channel: DemoChannelConfig) -> DemoChannelConfig:
        payload = asdict(channel)
        with self.database.session() as session:
            row = session.get(DemoChannelRow, channel.channel_id)
            if row is None:
                row = DemoChannelRow(
                    channel_id=channel.channel_id,
                    payload_json=self.database.dumps(payload),
                    enabled=channel.enabled,
                    telegram_ref=channel.telegram_ref,
                    name=channel.name,
                )
                session.add(row)
            else:
                row.payload_json = self.database.dumps(payload)
                row.enabled = channel.enabled
                row.telegram_ref = channel.telegram_ref
                row.name = channel.name
        return channel

    def create(self, name: str, telegram_ref: str, balance_pct: str, leverage: int, enabled: bool = True) -> DemoChannelConfig:
        now = int(time.time() * 1000)
        channel = DemoChannelConfig(
            channel_id=uuid4().hex[:12],
            name=name,
            telegram_ref=telegram_ref.strip(),
            balance_pct=balance_pct,
            leverage=leverage,
            enabled=enabled,
            created_at=now,
            updated_at=now,
        )
        return self.save(channel)

    def update(
        self,
        channel_id: str,
        *,
        name: str | None = None,
        telegram_ref: str | None = None,
        balance_pct: str | None = None,
        leverage: int | None = None,
        enabled: bool | None = None,
    ) -> DemoChannelConfig:
        channel = self.load(channel_id)
        if channel is None:
            raise RuntimeError(f"Demo channel {channel_id} not found")
        if name is not None:
            channel.name = name
        if telegram_ref is not None:
            channel.telegram_ref = telegram_ref.strip()
        if balance_pct is not None:
            channel.balance_pct = balance_pct
        if leverage is not None:
            channel.leverage = leverage
        if enabled is not None:
            channel.enabled = enabled
        channel.updated_at = int(time.time() * 1000)
        return self.save(channel)

    def delete(self, channel_id: str) -> None:
        with self.database.session() as session:
            row = session.get(DemoChannelRow, channel_id)
            if row is not None:
                session.delete(row)
