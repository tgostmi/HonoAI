import aiosqlite


class SQLite:
    def __init__(self, db_path: str = "data/database.db"):
        self.db_path = db_path
        self.db = None

    async def connect(self):
        self.db = await aiosqlite.connect(self.db_path)
        self.db.row_factory = aiosqlite.Row

    async def execute(self, query: str, args: tuple = None):
        async with self.db.execute(query, args or ()) as cursor:
            await self.db.commit()
            return cursor.lastrowid

    async def fetchone(self, query: str, args: tuple = None):
        async with self.db.execute(query, args or ()) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def fetchall(self, query: str, args: tuple = None):
        async with self.db.execute(query, args or ()) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def close(self):
        if self.db:
            await self.db.close()

