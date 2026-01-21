from typing import List, Optional
from .sqlite import SQLite
import random


class StickerDB:
    def __init__(self, db: SQLite):
        self.db = db

    async def init_table(self):
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS stickers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT UNIQUE NOT NULL,
                emoji TEXT,
                keywords TEXT DEFAULT ''
            )
        """)

    async def add(self, file_id: str, emoji: str = None, keywords: str = "") -> bool:
        try:
            await self.db.execute(
                "INSERT OR IGNORE INTO stickers (file_id, emoji, keywords) VALUES (?, ?, ?)",
                (file_id, emoji, keywords)
            )
            return True
        except:
            return False

    async def get_all(self) -> List[dict]:
        return await self.db.fetchall("SELECT * FROM stickers ORDER BY id")

    async def get_random(self) -> Optional[dict]:
        stickers = await self.get_all()
        return random.choice(stickers) if stickers else None

    async def get_by_keywords(self, text: str) -> Optional[dict]:
        text_lower = text.lower()
        stickers = await self.db.fetchall("SELECT * FROM stickers WHERE keywords != ''")
        
        matches = []
        for s in stickers:
            keywords = s.get('keywords', '').lower().split(',')
            for kw in keywords:
                if kw.strip() and kw.strip() in text_lower:
                    matches.append(s)
                    break
        
        return random.choice(matches) if matches else None

    async def delete(self, sticker_id: int) -> bool:
        await self.db.execute("DELETE FROM stickers WHERE id = ?", (sticker_id,))
        return True

    async def count(self) -> int:
        result = await self.db.fetchone("SELECT COUNT(*) as cnt FROM stickers")
        return result['cnt'] if result else 0

