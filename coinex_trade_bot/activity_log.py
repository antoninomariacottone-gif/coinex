from __future__ import annotations

import json
import time
from pathlib import Path


class ActivityLog:
    def __init__(self, path: Path, max_entries: int = 200):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_entries = max_entries

    def _read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []

    def _write_all(self, payload: list[dict]) -> None:
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def append(self, kind: str, message: str, **extra) -> None:
        rows = self._read_all()
        rows.append(
            {
                "ts": int(time.time() * 1000),
                "kind": kind,
                "message": message,
                **extra,
            }
        )
        self._write_all(rows[-self.max_entries :])

    def latest(self, limit: int = 50) -> list[dict]:
        return list(reversed(self._read_all()[-limit:]))

