from .sqlite import SQLite


def utf16_len(text: str) -> int:
    return len(text.encode('utf-16-le')) // 2


class EmojiDB:
    def __init__(self, db: SQLite):
        self.db = db

    async def init_table(self):
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS emojis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emoji TEXT NOT NULL,
                document_id INTEGER UNIQUE NOT NULL,
                description TEXT NOT NULL
            )
        """)

    async def add(self, emoji: str, document_id: int, description: str) -> bool:
        await self.db.execute(
            """
            INSERT OR REPLACE INTO emojis (emoji, document_id, description)
            VALUES (?, ?, ?)
            """,
            (emoji, document_id, description)
        )
        return True

    async def get_all(self) -> list:
        return await self.db.fetchall("SELECT * FROM emojis ORDER BY id")

    async def get_by_index(self, index: int):
        emojis = await self.get_all()
        if 0 < index <= len(emojis):
            return emojis[index - 1]
        return None

    async def get_by_description(self, keywords: list[str]) -> list:
        if not keywords:
            return []
        conditions = " OR ".join(["description LIKE ?" for _ in keywords])
        args = tuple(f"%{kw}%" for kw in keywords)
        return await self.db.fetchall(f"SELECT * FROM emojis WHERE {conditions}", args)

    async def delete(self, document_id: int) -> bool:
        await self.db.execute("DELETE FROM emojis WHERE document_id=?", (document_id,))
        return True

    async def delete_by_index(self, index: int) -> bool:
        emoji = await self.get_by_index(index)
        if emoji:
            await self.delete(emoji['document_id'])
            return True
        return False

    async def get_formatted_list(self) -> tuple[str, list]:
        emojis = await self.get_all()
        if not emojis:
            return "Список пуст", []
        
        lines = []
        entities = []
        current_offset = 0
        
        for i, e in enumerate(emojis, 1):
            prefix = f"{i}. "
            line = f"{prefix}{e['emoji']} — {e['description']}"
            
            emoji_offset = current_offset + utf16_len(prefix)
            entities.append({
                "offset": emoji_offset,
                "length": utf16_len(e['emoji']),
                "document_id": e['document_id']
            })
            
            lines.append(line)
            current_offset += utf16_len(line) + 1
        
        return "\n".join(lines), entities
