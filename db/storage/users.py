from db.db import DB
from typing import List
from dataclasses import dataclass
from datetime import datetime, timedelta

@dataclass
class User:
    ADMIN = "admin"
    USER = "user"
    BLOCKED = "blocked"
    PAID = "paid"
    DEDAULT_CALLS = 0
    PAID_CALLS = 100
    PAID_DURATION = timedelta(days=10)

    id:int
    role:str
    calls:int = 0
    expire_date:datetime = None

class UserStorage():
    __table = "users"
    def __init__(self, db:DB):
        self._db = db
    
    async def init(self):
        await self._db.execute(f'''
            CREATE TABLE IF NOT EXISTS {self.__table} (
                id BIGINT PRIMARY KEY,
                role TEXT,
                calls BIGINT DEFAULT 0,
                expire_date TIMESTAMP DEFAULT NULL
            )
        ''')

    async def get_by_id(self, id:int) -> User | None:
        data = await self._db.fetchrow(f"SELECT * FROM {self.__table} WHERE id = $1", id)
        if data is None:
            return None
        return User(data[0], data[1], data[2], data[3])

    async def promote_to_admin(self, id:int):
        await self._db.execute(f"UPDATE {self.__table} SET role = $1 WHERE id = $2", User.ADMIN, id)

    async def demote_from_admin(self, id:int):
        await self._db.execute(f"UPDATE {self.__table} SET role = $1 WHERE id = $2", User.USER, id)

    async def get_role_list(self, role:str) -> List[int] | None:
        roles = await self._db.fetch(f"SELECT * FROM {self.__table} WHERE role = $1", role)
        if roles is None:
            return None
        return [role[0] for role in roles]

    async def create(self, user:User):
        await self._db.execute(f'''
            INSERT INTO {self.__table} (id, role, calls, expire_date) VALUES ($1, $2, $3, $4)
        ''', user.id, user.role, user.calls, user.expire_date)

    async def get_all_members(self) -> List[User]| None:
        data = await self._db.fetch(f'''
            SELECT * FROM {self.__table}
        ''')
        if data is None:
            return None
        return [User(user_data[0], user_data[1], user_data[2], user_data[3],) for user_data in data]

    async def get_paid_members(self) -> List[User]| None:
        data = await self._db.fetch(f'''SELECT * FROM {self.__table} WHERE role = $1''', User.PAID)
        if data is None:
            return None
        return [User(user_data[0], user_data[1], user_data[2], user_data[3]) for user_data in data]

    async def get_unpaid_members(self) -> List[User]| None:
        data = await self._db.fetch(f'''SELECT * FROM {self.__table} WHERE role = $1''', User.USER)
        if data is None:
            return None
        return [User(user_data[0], user_data[1], user_data[2], user_data[3]) for user_data in data]

    async def get_user_amount(self) -> int:
        return await self._db.fetchval(f"SELECT COUNT(*) FROM {self.__table}")

    async def decrease_calls(self, user:User):
        await self._db.execute(f"UPDATE {self.__table} SET calls = calls - 1 WHERE id = $1", user.id)

    async def ban_user(self, user_id:User):
        await self._db.execute(f"UPDATE {self.__table} SET role = $1, calls = 0, expire_date = NULL WHERE id = $2", User.BLOCKED, user_id)
    
    async def unban_user(self, user_id:User):
        await self._db.execute(f"UPDATE {self.__table} SET role = $1 WHERE id = $2", User.USER, user_id)

    async def add_paid(self, user:User):
        await self._db.execute(f"UPDATE {self.__table} SET role = $1, calls = $2, expire_date = $3 WHERE id = $4", User.PAID, User.PAID_CALLS, datetime.now() + User.PAID_DURATION ,user.id)
    
    async def remove_paid(self, user:User):
        await self._db.execute(f"UPDATE {self.__table} SET role = $1, calls = 0, expire_date = NULL WHERE id = $2", User.USER, user.id)

    async def add_admin(self, user:User):
        await self._db.execute(f"UPDATE {self.__table} SET role = $1 WHERE id = $2", User.ADMIN, user.id)

    async def delete(self, user_id:int):
        await self._db.execute(f'''
            DELETE FROM {self.__table} WHERE id = $1
        ''', user_id)