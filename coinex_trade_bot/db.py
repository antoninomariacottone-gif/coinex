from __future__ import annotations

import json
from contextlib import contextmanager

from sqlalchemy import Boolean, Integer, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


class Base(DeclarativeBase):
    pass


class TradeRow(Base):
    __tablename__ = "trades"

    trade_id: Mapped[str] = mapped_column(Text, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    market: Mapped[str] = mapped_column(Text, nullable=False)
    side: Mapped[str] = mapped_column(Text, nullable=False)
    execution_mode: Mapped[str] = mapped_column(Text, nullable=False, default="live")


class DemoChannelRow(Base):
    __tablename__ = "demo_channels"

    channel_id: Mapped[str] = mapped_column(Text, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    telegram_ref: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)


class ActivityRow(Base):
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class Database:
    def __init__(self, database_url: str):
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, future=True, connect_args=connect_args)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        Base.metadata.create_all(self.engine)

    @contextmanager
    def session(self) -> Session:
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @staticmethod
    def dumps(payload: dict | list) -> str:
        return json.dumps(payload, separators=(",", ":"))

    @staticmethod
    def loads(payload_json: str) -> dict | list:
        return json.loads(payload_json)

