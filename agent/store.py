"""시도 기록. 규칙 검사(영상당 1개, 하루 상한)도 이 표를 기준으로 한다."""

import sqlite3
import threading
import time
from pathlib import Path

from .rules import kst_date

SCHEMA = """CREATE TABLE IF NOT EXISTS logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  day TEXT NOT NULL,
  video_id TEXT, video_title TEXT, channel_id TEXT, channel_name TEXT,
  profile TEXT, comment TEXT,
  status TEXT NOT NULL,          -- success | failed | blocked
  reason TEXT, screenshot TEXT, comment_url TEXT
)"""


class Store:
    def __init__(self, file: Path):
        file.parent.mkdir(parents=True, exist_ok=True)
        # 요청 처리 스레드가 여러 개라 연결 하나를 잠금과 함께 쓴다
        self._db = sqlite3.connect(file, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._db.execute(SCHEMA)

    def _query(self, sql: str, *args) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def add(self, row: dict, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO logs (ts, day, video_id, video_title, channel_id, channel_name, profile, comment,
                   status, reason, screenshot, comment_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(now * 1000),
                    kst_date(now),  # ts는 화면과 맞추려고 밀리초
                    row.get("videoId"),
                    row.get("title"),
                    row.get("channelId"),
                    row.get("channelName"),
                    row.get("profile"),
                    row.get("comment"),
                    row["status"],
                    row.get("reason"),
                    row.get("screenshot"),
                    row.get("commentUrl"),
                ),
            )

    def has_success(self, video_id: str) -> bool:
        return bool(
            self._query(
                "SELECT 1 FROM logs WHERE video_id = ? AND status = 'success' LIMIT 1",
                video_id,
            )
        )

    def count_success_on(self, day: str) -> int:
        return self._query(
            "SELECT COUNT(*) FROM logs WHERE day = ? AND status = 'success'", day
        )[0][0]

    def commented_ids(self) -> set[str]:
        return {
            r[0]
            for r in self._query("SELECT video_id FROM logs WHERE status = 'success'")
        }

    def previous_comments(self, n: int = 30, except_video_id: str = "") -> list[str]:
        rows = self._query(
            "SELECT comment FROM logs WHERE status = 'success' AND video_id IS NOT ? ORDER BY ts DESC LIMIT ?",
            except_video_id,
            n,
        )
        return [r[0] for r in rows]

    def last_used(self, profile: str) -> int:
        row = self._query(
            "SELECT MAX(ts) FROM logs WHERE profile = ? AND status IN ('success','failed')",
            profile,
        )
        return row[0][0] or 0

    def list(self, limit: int = 200) -> list[dict]:
        return [
            dict(r)
            for r in self._query("SELECT * FROM logs ORDER BY ts DESC LIMIT ?", limit)
        ]
