import asyncio
from db.db import DB
from bot import TG_Bot
from db.storage import UserStorage
from config import Config

async def init_db():
    db = DB(host=Config.host, port=Config.port, login=Config.login, database = Config.database)
    await db.init()
    user_storage = UserStorage(db)
    await user_storage.init()
    return user_storage

async def main():
    user_storage = await init_db()
    tg_bot = TG_Bot(user_storage)
    tg_bot.init()
    await tg_bot.start()

if __name__ == '__main__':
    loop = asyncio.new_event_loop()
    loop.run_until_complete(main())