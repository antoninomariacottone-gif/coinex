from __future__ import annotations

import time

from coinex_trade_bot.db import ActivityRow, Database

class ActivityLog:
    def __init__(self, database: Database, max_entries: int = 200):
        self.database = database
        self.max_entries = max_entries

    def append(self, kind: str, message: str, **extra) -> None:
        payload = {
            "ts": int(time.time() * 1000),
            "kind": kind,
            "message": message,
            **extra,
        }
        with self.database.session() as session:
            session.add(ActivityRow(ts=payload["ts"], kind=kind, payload_json=self.database.dumps(payload)))
            all_ids = list(session.query(ActivityRow.id).order_by(ActivityRow.id.desc()).scalars())
            for stale_id in all_ids[self.max_entries :]:
                stale = session.get(ActivityRow, stale_id)
                if stale is not None:
                    session.delete(stale)

    def latest(self, limit: int = 50) -> list[dict]:
        with self.database.session() as session:
            rows = session.query(ActivityRow).order_by(ActivityRow.id.desc()).limit(limit).all()
            return [self.database.loads(row.payload_json) for row in rows]
