from typing import Optional, List
import time
from .sqlite import SQLite


RELATIONSHIP_LEVELS = {
    -5: ("💀 Враг", "ненавидишь, максимально грубо, можешь оскорблять"),
    -4: ("😡 Ненависть", "презираешь, отвечаешь с отвращением"),
    -3: ("😤 Неприязнь", "раздражён, груб, саркастичен"),
    -2: ("🙄 Недоверие", "подозрительно, холодно, с претензией"),
    -1: ("😒 Антипатия", "неприятен, отвечаешь сухо и неохотно"),
    0: ("👤 Незнакомец", "нейтрально, отстранённо"),
    1: ("🙂 Знакомый", "вежливо, но сдержанно"),
    2: ("😊 Приятель", "дружелюбно, открыто"),
    3: ("💛 Друг", "тепло, с симпатией"),
    4: ("🧡 Близкий друг", "очень тепло, можно флиртовать"),
    5: ("❤️ Влюблённость", "флиртует, мило, романтично"),
    6: ("💕 Пара", "как с парнем/девушкой, нежно, интимно"),
    7: ("💍 Вместе навсегда", "обожаешь, скучаешь, очень нежно и страстно")
}


class UserDB:
    def __init__(self, db: SQLite):
        self.db = db

    async def init_table(self):
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                name TEXT,
                profile TEXT DEFAULT '',
                mood INTEGER DEFAULT 0,
                relationship INTEGER DEFAULT 0,
                last_seen INTEGER DEFAULT 0,
                last_updated INTEGER DEFAULT 0
            )
        """)
        
        for col, default in [("mood", 0), ("last_seen", 0), ("relationship", 0)]:
            try:
                await self.db.execute(f"ALTER TABLE user_profiles ADD COLUMN {col} INTEGER DEFAULT {default}")
            except:
                pass
        
        try:
            await self.db.execute("ALTER TABLE user_profiles ADD COLUMN topics TEXT DEFAULT ''")
        except:
            pass
        
        try:
            await self.db.execute("ALTER TABLE user_profiles ADD COLUMN dates TEXT DEFAULT ''")
        except:
            pass
        
        try:
            await self.db.execute("ALTER TABLE user_profiles ADD COLUMN message_count INTEGER DEFAULT 0")
        except:
            pass

    async def get_profile(self, user_id: int) -> Optional[dict]:
        return await self.db.fetchone(
            "SELECT * FROM user_profiles WHERE user_id = ?",
            (user_id,)
        )

    async def update_profile(self, user_id: int, profile: str, username: str = None, name: str = None):
        existing = await self.get_profile(user_id)
        now = int(time.time())
        
        if existing:
            await self.db.execute(
                "UPDATE user_profiles SET profile = ?, username = COALESCE(?, username), name = COALESCE(?, name), last_updated = ? WHERE user_id = ?",
                (profile, username, name, now, user_id)
            )
        else:
            await self.db.execute(
                "INSERT INTO user_profiles (user_id, username, name, profile, last_updated) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, name, profile, now)
            )

    async def update_mood(self, user_id: int, mood: int):
        existing = await self.get_profile(user_id)
        if existing:
            await self.db.execute("UPDATE user_profiles SET mood = ? WHERE user_id = ?", (mood, user_id))
        else:
            await self.db.execute("INSERT INTO user_profiles (user_id, mood) VALUES (?, ?)", (user_id, mood))

    async def update_relationship(self, user_id: int, level: int):
        level = max(-5, min(7, level))
        existing = await self.get_profile(user_id)
        if existing:
            await self.db.execute("UPDATE user_profiles SET relationship = ? WHERE user_id = ?", (level, user_id))
        else:
            await self.db.execute("INSERT INTO user_profiles (user_id, relationship) VALUES (?, ?)", (user_id, level))

    async def get_close_users(self, min_level: int = 4) -> List[dict]:
        return await self.db.fetchall(
            "SELECT * FROM user_profiles WHERE relationship >= ?",
            (min_level,)
        )
    
    async def get_all_profiles(self) -> List[dict]:
        return await self.db.fetchall("SELECT * FROM user_profiles", ())

    async def update_last_seen(self, user_id: int, username: str = None, name: str = None):
        existing = await self.get_profile(user_id)
        now = int(time.time())
        if existing:
            if username or name:
                await self.db.execute(
                    "UPDATE user_profiles SET last_seen = ?, username = COALESCE(?, username), name = COALESCE(?, name) WHERE user_id = ?",
                    (now, username, name, user_id)
                )
            else:
                await self.db.execute("UPDATE user_profiles SET last_seen = ? WHERE user_id = ?", (now, user_id))
        else:
            await self.db.execute(
                "INSERT INTO user_profiles (user_id, last_seen, username, name) VALUES (?, ?, ?, ?)",
                (user_id, now, username, name)
            )

    async def increment_message_count(self, user_id: int):
        existing = await self.get_profile(user_id)
        if existing:
            await self.db.execute("UPDATE user_profiles SET message_count = COALESCE(message_count, 0) + 1 WHERE user_id = ?", (user_id,))

    async def delete_profile(self, user_id: int):
        await self.db.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))

    async def delete_all_profiles(self) -> int:
        result = await self.db.fetchone("SELECT COUNT(*) as cnt FROM user_profiles")
        count = result['cnt'] if result else 0
        await self.db.execute("DELETE FROM user_profiles")
        return count

    async def update_topics(self, user_id: int, topics: str):
        existing = await self.get_profile(user_id)
        if existing:
            await self.db.execute("UPDATE user_profiles SET topics = ? WHERE user_id = ?", (topics, user_id))
        else:
            await self.db.execute("INSERT INTO user_profiles (user_id, topics) VALUES (?, ?)", (user_id, topics))

    async def update_dates(self, user_id: int, dates: str):
        existing = await self.get_profile(user_id)
        if existing:
            await self.db.execute("UPDATE user_profiles SET dates = ? WHERE user_id = ?", (dates, user_id))
        else:
            await self.db.execute("INSERT INTO user_profiles (user_id, dates) VALUES (?, ?)", (user_id, dates))

    @staticmethod
    def get_relationship_info(level: int) -> tuple:
        level = max(-5, min(7, level))
        return RELATIONSHIP_LEVELS.get(level, RELATIONSHIP_LEVELS[0])
