import aiosqlite
import json
import time
from typing import Optional


class GroupDB:
    def __init__(self, db_path: str = "data/groups.db"):
        self.db_path = db_path
    
    async def init(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    group_id INTEGER PRIMARY KEY,
                    title TEXT,
                    username TEXT,
                    rules TEXT,
                    staff TEXT,
                    topics TEXT,
                    join_date INTEGER,
                    last_activity INTEGER,
                    message_count INTEGER DEFAULT 0,
                    my_messages INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    message TEXT,
                    timestamp INTEGER,
                    msg_id INTEGER,
                    reply_to_msg_id INTEGER
                )
            """)
            
            for col in ["msg_id", "reply_to_msg_id"]:
                try:
                    await db.execute(f"ALTER TABLE group_context ADD COLUMN {col} INTEGER")
                except:
                    pass
            
            for col in ["rules_tried", "staff_tried"]:
                try:
                    await db.execute(f"ALTER TABLE groups ADD COLUMN {col} INTEGER DEFAULT 0")
                except:
                    pass
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_moderation (
                    group_id INTEGER PRIMARY KEY,
                    mod_level INTEGER DEFAULT 0,
                    promoted_by INTEGER,
                    promoted_at INTEGER,
                    admins_data TEXT DEFAULT '{}',
                    warnings_data TEXT DEFAULT '{}',
                    mod_stats TEXT DEFAULT '{}'
                )
            """)
            
            for col, default in [
                ("mod_level", "0"),
                ("promoted_by", "NULL"),
                ("promoted_at", "NULL"),
                ("admins_data", "'{}'"),
                ("warnings_data", "'{}'"),
                ("mod_stats", "'{}'")
            ]:
                try:
                    await db.execute(f"ALTER TABLE group_moderation ADD COLUMN {col} TEXT DEFAULT {default}")
                except:
                    pass
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    reason TEXT,
                    given_by TEXT,
                    timestamp INTEGER,
                    expires_at INTEGER
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS skupki (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    message_text TEXT,
                    parsed_text TEXT,
                    keywords TEXT,
                    timestamp INTEGER,
                    msg_hash TEXT
                )
            """)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS group_profiles (
                    group_id INTEGER PRIMARY KEY,
                    atmosphere TEXT,
                    main_topics TEXT,
                    communication_style TEXT,
                    key_members TEXT,
                    notes TEXT,
                    last_analyzed INTEGER,
                    analyze_count INTEGER DEFAULT 0
                )
            """)
            
            await db.commit()
    
    async def add_group(self, group_id: int, title: str, username: str = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO groups (group_id, title, username, join_date, last_activity)
                VALUES (?, ?, ?, ?, ?)
            """, (group_id, title, username, int(time.time()), int(time.time())))
            await db.commit()
    
    async def get_group(self, group_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM groups WHERE group_id = ? AND is_active = 1", (group_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def delete_group(self, group_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
            await db.execute("DELETE FROM group_context WHERE group_id = ?", (group_id,))
            await db.commit()
    
    async def update_rules(self, group_id: int, rules: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE groups SET rules = ? WHERE group_id = ?", (rules[:2000], group_id))
            await db.commit()
    
    async def update_staff(self, group_id: int, staff: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE groups SET staff = ? WHERE group_id = ?", (staff[:1000], group_id))
            await db.commit()
    
    async def update_topics(self, group_id: int, topics: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE groups SET topics = ? WHERE group_id = ?", (topics[:500], group_id))
            await db.commit()
    
    async def mark_rules_tried(self, group_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE groups SET rules_tried = 1 WHERE group_id = ?", (group_id,))
            await db.commit()
    
    async def mark_staff_tried(self, group_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE groups SET staff_tried = 1 WHERE group_id = ?", (group_id,))
            await db.commit()
    
    async def increment_messages(self, group_id: int, is_mine: bool = False):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE groups SET 
                    message_count = message_count + 1,
                    my_messages = my_messages + ?,
                    last_activity = ?
                WHERE group_id = ?
            """, (1 if is_mine else 0, int(time.time()), group_id))
            await db.commit()
    
    async def add_context(self, group_id: int, user_id: int, username: str, message: str, msg_id: int = None, reply_to_msg_id: int = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO group_context (group_id, user_id, username, message, timestamp, msg_id, reply_to_msg_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (group_id, user_id, username, message[:500], int(time.time()), msg_id, reply_to_msg_id))
            await db.execute("""
                DELETE FROM group_context 
                WHERE group_id = ? AND id NOT IN (
                    SELECT id FROM group_context WHERE group_id = ? ORDER BY timestamp DESC LIMIT 100
                )
            """, (group_id, group_id))
            await db.commit()
    
    async def get_message_by_msg_id(self, group_id: int, msg_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM group_context 
                WHERE group_id = ? AND msg_id = ?
            """, (group_id, msg_id)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_context(self, group_id: int, limit: int = 15) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM group_context 
                WHERE group_id = ? 
                ORDER BY timestamp DESC LIMIT ?
            """, (group_id, limit)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in reversed(rows)]
    
    async def get_message_by_id(self, group_id: int, msg_id: int) -> dict:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM group_context 
                WHERE group_id = ? AND id = ?
            """, (group_id, msg_id)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_messages_around(self, group_id: int, timestamp: int, before: int = 3, after: int = 3) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM (
                    SELECT * FROM group_context 
                    WHERE group_id = ? AND timestamp < ?
                    ORDER BY timestamp DESC LIMIT ?
                ) UNION ALL
                SELECT * FROM (
                    SELECT * FROM group_context 
                    WHERE group_id = ? AND timestamp >= ?
                    ORDER BY timestamp ASC LIMIT ?
                )
                ORDER BY timestamp ASC
            """, (group_id, timestamp, before, group_id, timestamp, after + 1)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def search_messages(self, group_id: int, query: str, limit: int = 10) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM group_context 
                WHERE group_id = ? AND message LIKE ?
                ORDER BY timestamp DESC LIMIT ?
            """, (group_id, f"%{query}%", limit)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in reversed(rows)]
    
    async def get_all_groups(self) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM groups WHERE is_active = 1") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def deactivate(self, group_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE groups SET is_active = 0 WHERE group_id = ?", (group_id,))
            await db.commit()
    
    async def get_mod_level(self, group_id: int) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT mod_level FROM group_moderation WHERE group_id = ?", (group_id,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
    
    async def set_mod_level(self, group_id: int, level: int, promoted_by: int = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO group_moderation (group_id, mod_level, promoted_by, promoted_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET 
                    mod_level = excluded.mod_level,
                    promoted_by = excluded.promoted_by,
                    promoted_at = excluded.promoted_at
            """, (group_id, level, promoted_by, int(time.time())))
            await db.commit()
            print(f"[DB] set_mod_level: group_id={group_id}, level={level}, promoted_by={promoted_by}")
    
    async def get_mod_info(self, group_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM group_moderation WHERE group_id = ?", (group_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    data = dict(row)
                    print(f"[DB] get_mod_info raw: {data}")
                    data['admins_data'] = json.loads(data.get('admins_data') or '{}')
                    data['warnings_data'] = json.loads(data.get('warnings_data') or '{}')
                    data['mod_stats'] = json.loads(data.get('mod_stats') or '{}')
                    return data
                print(f"[DB] get_mod_info: no data for group {group_id}")
                return None
    
    async def update_admin_performance(self, group_id: int, admin_id: int, admin_name: str, action: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT admins_data FROM group_moderation WHERE group_id = ?", (group_id,)) as cursor:
                row = await cursor.fetchone()
                admins = json.loads(row[0] if row and row[0] else '{}')
            
            admin_key = str(admin_id)
            if admin_key not in admins:
                admins[admin_key] = {'name': admin_name, 'actions': 0, 'last_action': 0, 'effectiveness': 50}
            
            admins[admin_key]['name'] = admin_name
            admins[admin_key]['actions'] += 1
            admins[admin_key]['last_action'] = int(time.time())
            
            if action in ['warn', 'mute', 'kick', 'ban']:
                admins[admin_key]['effectiveness'] = min(100, admins[admin_key]['effectiveness'] + 2)
            
            await db.execute("""
                INSERT INTO group_moderation (group_id, admins_data)
                VALUES (?, ?)
                ON CONFLICT(group_id) DO UPDATE SET admins_data = excluded.admins_data
            """, (group_id, json.dumps(admins, ensure_ascii=False)))
            await db.commit()
    
    async def add_warning(self, group_id: int, user_id: int, username: str, reason: str, given_by: str = "Хоно"):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO group_warnings (group_id, user_id, username, reason, given_by, timestamp, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (group_id, user_id, username, reason, given_by, int(time.time()), int(time.time()) + 86400 * 7))
            await db.commit()
    
    async def get_user_warnings(self, group_id: int, user_id: int) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM group_warnings 
                WHERE group_id = ? AND user_id = ? AND expires_at > ?
                ORDER BY timestamp DESC
            """, (group_id, user_id, int(time.time()))) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def get_warnings_count(self, group_id: int, user_id: int) -> int:
        warnings = await self.get_user_warnings(group_id, user_id)
        return len(warnings)
    
    async def update_mod_stats(self, group_id: int, action: str):
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT mod_stats FROM group_moderation WHERE group_id = ?", (group_id,)) as cursor:
                row = await cursor.fetchone()
                stats = json.loads(row[0] if row and row[0] else '{}')
            
            stats[action] = stats.get(action, 0) + 1
            stats['total'] = stats.get('total', 0) + 1
            stats['last_action'] = int(time.time())
            
            await db.execute("""
                INSERT INTO group_moderation (group_id, mod_stats)
                VALUES (?, ?)
                ON CONFLICT(group_id) DO UPDATE SET mod_stats = excluded.mod_stats
            """, (group_id, json.dumps(stats)))
            await db.commit()

    async def add_skupka(self, group_id: int, user_id: int, username: str, message_text: str, parsed_text: str, keywords: str, msg_hash: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT INTO skupki (group_id, user_id, username, message_text, parsed_text, keywords, timestamp, msg_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (group_id, user_id, username, message_text, parsed_text, keywords, int(time.time()), msg_hash))
            await db.commit()

    async def get_user_last_skupka(self, group_id: int, user_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM skupki WHERE group_id = ? AND user_id = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (group_id, user_id)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def search_skupki(self, group_id: int, query: str) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            query_lower = f"%{query.lower()}%"
            async with db.execute("""
                SELECT DISTINCT user_id, username, parsed_text, keywords, timestamp 
                FROM skupki 
                WHERE group_id = ? AND (
                    LOWER(keywords) LIKE ? OR 
                    LOWER(parsed_text) LIKE ? OR
                    LOWER(message_text) LIKE ?
                )
                ORDER BY timestamp DESC
                LIMIT 10
            """, (group_id, query_lower, query_lower, query_lower)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_all_skupki(self, group_id: int, limit: int = 20) -> list:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT DISTINCT user_id, username, parsed_text, keywords, timestamp 
                FROM skupki WHERE group_id = ?
                ORDER BY timestamp DESC LIMIT ?
            """, (group_id, limit)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def get_group_profile(self, group_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM group_profiles WHERE group_id = ?", (group_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_group_profile(self, group_id: int, atmosphere: str = None, main_topics: str = None,
                                   communication_style: str = None, key_members: str = None, notes: str = None):
        async with aiosqlite.connect(self.db_path) as db:
            existing = await self.get_group_profile(group_id)
            
            if existing:
                updates = []
                values = []
                if atmosphere is not None:
                    updates.append("atmosphere = ?")
                    values.append(atmosphere[:500])
                if main_topics is not None:
                    updates.append("main_topics = ?")
                    values.append(main_topics[:500])
                if communication_style is not None:
                    updates.append("communication_style = ?")
                    values.append(communication_style[:300])
                if key_members is not None:
                    updates.append("key_members = ?")
                    values.append(key_members[:500])
                if notes is not None:
                    updates.append("notes = ?")
                    values.append(notes[:500])
                
                if updates:
                    updates.append("last_analyzed = ?")
                    values.append(int(time.time()))
                    updates.append("analyze_count = analyze_count + 1")
                    values.append(group_id)
                    
                    query = f"UPDATE group_profiles SET {', '.join(updates)} WHERE group_id = ?"
                    await db.execute(query, values)
            else:
                await db.execute("""
                    INSERT INTO group_profiles (group_id, atmosphere, main_topics, communication_style, key_members, notes, last_analyzed, analyze_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """, (group_id, atmosphere or "", main_topics or "", communication_style or "", key_members or "", notes or "", int(time.time())))
            
            await db.commit()

    async def get_full_group_info(self, group_id: int) -> Optional[dict]:
        group = await self.get_group(group_id)
        if not group:
            return None
        
        profile = await self.get_group_profile(group_id)
        mod_info = await self.get_mod_info(group_id)
        
        return {
            "group_id": group_id,
            "title": group.get("title"),
            "username": group.get("username"),
            "rules": group.get("rules"),
            "staff": group.get("staff"),
            "message_count": group.get("message_count", 0),
            "my_messages": group.get("my_messages", 0),
            "atmosphere": profile.get("atmosphere") if profile else None,
            "main_topics": profile.get("main_topics") if profile else None,
            "communication_style": profile.get("communication_style") if profile else None,
            "key_members": profile.get("key_members") if profile else None,
            "notes": profile.get("notes") if profile else None,
            "mod_level": mod_info.get("mod_level", 0) if mod_info else 0
        }

