import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import BOT_TOKEN
from app.database import init_db
from app.handlers.attendance import router as attendance_router
from app.handlers.groups_info import router as groups_info_router
from app.handlers.payments import router as payments_router
from app.handlers.schedule import router as schedule_router
from app.handlers.start import router as start_router
from app.handlers.students import router as students_router
from app.middlewares import StateGuardMiddleware
from app.scheduler import setup_scheduler
from app.sheets import get_sheets_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing in environment / .env file.")

    await init_db()
    await asyncio.to_thread(get_sheets_manager().ensure_master_sheets)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    state_guard = StateGuardMiddleware()
    dp.message.outer_middleware(state_guard)
    dp.callback_query.outer_middleware(state_guard)

    dp.include_router(start_router)
    dp.include_router(schedule_router)
    dp.include_router(students_router)
    dp.include_router(attendance_router)
    dp.include_router(payments_router)
    dp.include_router(groups_info_router)

    scheduler = setup_scheduler(bot)
    scheduler.start()
    logger.info("Bot and APScheduler started.")

    try:
        await dp.start_polling(
            bot,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        logger.info("Shutting down scheduler and bot session...")
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")