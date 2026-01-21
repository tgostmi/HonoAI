from typing import Optional, List
import time
from .sqlite import SQLite


class ReminderDB:
    def __init__(self, db: SQLite):
        self.db = db

    async def init_table(self):
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                send_at INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                sent INTEGER DEFAULT 0
            )
        """)

    async def add(self, user_id: int, chat_id: int, message: str, send_at: int) -> int:
        return await self.db.execute(
            "INSERT INTO reminders (user_id, chat_id, message, send_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, chat_id, message, send_at, int(time.time()))
        )

    async def get_pending(self) -> List[dict]:
        now = int(time.time())
        return await self.db.fetchall(
            "SELECT * FROM reminders WHERE sent = 0 AND send_at <= ?",
            (now,)
        )

    async def mark_sent(self, reminder_id: int):
        await self.db.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))

    async def get_user_reminders(self, user_id: int) -> List[dict]:
        return await self.db.fetchall(
            "SELECT * FROM reminders WHERE user_id = ? AND sent = 0 ORDER BY send_at",
            (user_id,)
        )

    async def delete(self, reminder_id: int):
        await self.db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))

