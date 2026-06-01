from __future__ import annotations

import json
import logging
from contextlib import contextmanager

from sqlalchemy import inspect, text
from sqlalchemy import BigInteger, Boolean, Integer, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker


LOGGER = logging.getLogger("coinex_trade_bot.db")


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
    ts: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)


class Database:
    def __init__(self, database_url: str):
        self.database_url = database_url
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        self.engine = create_engine(database_url, future=True, connect_args=connect_args)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False, future=True)
        Base.metadata.create_all(self.engine)
        LOGGER.info("Database ready: dialect=%s tables=%s", self.engine.dialect.name, ",".join(self.table_names()))

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

    def table_names(self) -> list[str]:
        return sorted(inspect(self.engine).get_table_names())

    def status(self) -> dict[str, object]:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {
            "dialect": self.engine.dialect.name,
            "url_driver": self.engine.url.drivername,
            "database": self.engine.url.database,
            "tables": self.table_names(),
            "using_sqlite_fallback": self.engine.dialect.name == "sqlite",
        }
