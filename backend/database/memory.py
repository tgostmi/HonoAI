import aiosqlite
import time
import json
from typing import List, Optional, Dict

class GlobalMemory:
    def __init__(self, db_path: str = "data/global_memory.db"):
        self.db_path = db_path
    
    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    trigger_context TEXT,
                    lesson TEXT NOT NULL,
                    importance INTEGER DEFAULT 1,
                    times_applied INTEGER DEFAULT 0,
                    created_at INTEGER,
                    last_used INTEGER,
                    source_chat_id INTEGER,
                    source_user_id INTEGER
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    user_id INTEGER,
                    my_message TEXT,
                    user_reaction TEXT,
                    reaction_type TEXT,
                    analyzed INTEGER DEFAULT 0,
                    created_at INTEGER
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_type TEXT,
                    description TEXT,
                    examples TEXT,
                    effectiveness INTEGER DEFAULT 0,
                    created_at INTEGER
                )
            """)
            
            await db.execute("CREATE INDEX IF NOT EXISTS idx_lessons_category ON lessons(category)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_lessons_importance ON lessons(importance DESC)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_interactions_analyzed ON interactions(analyzed)")
            await db.commit()
    
    async def add_lesson(self, category: str, lesson: str, trigger_context: str = None, 
                         importance: int = 1, chat_id: int = None, user_id: int = None) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            existing = await db.execute(
                "SELECT id, importance FROM lessons WHERE lesson LIKE ? AND category = ?",
                (f"%{lesson[:50]}%", category)
            )
            row = await existing.fetchone()
            
            if row:
                new_importance = min(row[1] + 1, 10)
                await db.execute(
                    "UPDATE lessons SET importance = ?, last_used = ? WHERE id = ?",
                    (new_importance, int(time.time()), row[0])
                )
                await db.commit()
                return row[0]
            
            cursor = await db.execute(
                """INSERT INTO lessons (category, trigger_context, lesson, importance, created_at, source_chat_id, source_user_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (category, trigger_context, lesson, importance, int(time.time()), chat_id, user_id)
            )
            await db.commit()
            return cursor.lastrowid
    
    async def log_interaction(self, chat_id: int, user_id: int, my_message: str, 
                              user_reaction: str, reaction_type: str = "neutral"):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO interactions (chat_id, user_id, my_message, user_reaction, reaction_type, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (chat_id, user_id, my_message[:500], user_reaction[:500], reaction_type, int(time.time()))
            )
            await db.commit()
    
    async def get_relevant_lessons(self, context: str = None, category: str = None, limit: int = 5) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            if category:
                cursor = await db.execute(
                    """SELECT * FROM lessons WHERE category = ? 
                       ORDER BY importance DESC, times_applied DESC LIMIT ?""",
                    (category, limit)
                )
            else:
                cursor = await db.execute(
                    """SELECT * FROM lessons 
                       ORDER BY importance DESC, times_applied DESC LIMIT ?""",
                    (limit,)
                )
            
            rows = await cursor.fetchall()
            lessons = [dict(row) for row in rows]
            
            if context and lessons:
                context_lower = context.lower()
                scored = []
                for lesson in lessons:
                    score = lesson['importance']
                    trigger = (lesson.get('trigger_context') or '').lower()
                    if trigger and any(word in context_lower for word in trigger.split()):
                        score += 3
                    scored.append((score, lesson))
                scored.sort(key=lambda x: -x[0])
                lessons = [l for _, l in scored[:limit]]
            
            return lessons
    
    async def mark_lesson_used(self, lesson_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE lessons SET times_applied = times_applied + 1, last_used = ? WHERE id = ?",
                (int(time.time()), lesson_id)
            )
            await db.commit()
    
    async def get_unanalyzed_interactions(self, limit: int = 20) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM interactions WHERE analyzed = 0 ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def mark_interactions_analyzed(self, ids: List[int]):
        if not ids:
            return
        async with aiosqlite.connect(self.db_path) as db:
            placeholders = ','.join('?' * len(ids))
            await db.execute(f"UPDATE interactions SET analyzed = 1 WHERE id IN ({placeholders})", ids)
            await db.commit()
    
    async def add_pattern(self, pattern_type: str, description: str, examples: list = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO patterns (pattern_type, description, examples, created_at)
                   VALUES (?, ?, ?, ?)""",
                (pattern_type, description, json.dumps(examples or []), int(time.time()))
            )
            await db.commit()
    
    async def get_all_lessons(self) -> List[Dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM lessons ORDER BY importance DESC")
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    async def delete_lesson(self, lesson_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM lessons WHERE id = ?", (lesson_id,))
            await db.commit()
    
    async def get_stats(self) -> Dict:
        async with aiosqlite.connect(self.db_path) as db:
            lessons_count = await db.execute("SELECT COUNT(*) FROM lessons")
            lessons = (await lessons_count.fetchone())[0]
            
            interactions_count = await db.execute("SELECT COUNT(*) FROM interactions")
            interactions = (await interactions_count.fetchone())[0]
            
            patterns_count = await db.execute("SELECT COUNT(*) FROM patterns")
            patterns = (await patterns_count.fetchone())[0]
            
            categories = await db.execute("SELECT category, COUNT(*) FROM lessons GROUP BY category")
            cats = await categories.fetchall()
            
            return {
                "lessons": lessons,
                "interactions": interactions,
                "patterns": patterns,
                "by_category": {c[0]: c[1] for c in cats}
            }


REACTION_INDICATORS = {
    "positive": [
        "спасибо", "благодарю", "круто", "класс", "топ", "база", "based", 
        "лол", "ахах", "хах", "смешно", "угар", "ору", "😂", "🤣", "❤", "👍",
        "молодец", "умница", "хорошо", "отлично", "супер", "красава"
    ],
    "negative": [
        "заткнись", "замолчи", "хватит", "стоп", "не надо", "отстань",
        "бред", "чушь", "глупость", "тупо", "тупая", "дура", "идиот",
        "неправильно", "ошибка", "не так", "ты что", "ты чё", "ты че"
    ],
    "correction": [
        "не ", "нет,", "неправильно", "на самом деле", "вообще-то", 
        "ты путаешь", "ты перепутал", "это не", "а на самом деле"
    ]
}


def detect_reaction_type(text: str) -> str:
    text_lower = text.lower()
    
    for word in REACTION_INDICATORS["correction"]:
        if word in text_lower:
            return "correction"
    
    positive_count = sum(1 for word in REACTION_INDICATORS["positive"] if word in text_lower)
    negative_count = sum(1 for word in REACTION_INDICATORS["negative"] if word in text_lower)
    
    if negative_count > positive_count:
        return "negative"
    if positive_count > 0:
        return "positive"
    
    return "neutral"

