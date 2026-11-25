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
from app.handlers.guest import router as guest_router
from app.handlers.payments import router as payments_router
from app.handlers.schedule import router as schedule_router
from app.handlers.start import router as start_router
from app.handlers.students import router as students_router
from app.middlewares import (
    MainAdminRoleSwitchMenuMiddleware,
    CallbackDataShortenerRequestMiddleware,
    CallbackTokenResolverMiddleware,
    StateGuardMiddleware,
)
from app.scheduler import setup_scheduler
from app.sheets import get_sheets_manager
from app.utils import send_annual_archive_document, to_tashkent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def _tashkent_log_time(record: logging.LogRecord, datefmt: str | None = None) -> str:
    """Render log timestamps in Asia/Tashkent regardless of the server timezone."""
    from datetime import datetime, timezone

    dt = to_tashkent(datetime.fromtimestamp(record.created, tz=timezone.utc))
    return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S") if dt else ""


for _handler in logging.getLogger().handlers:
    if _handler.formatter is not None:
        _handler.formatter.formatTime = _tashkent_log_time  # type: ignore[method-assign]
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
    bot.session.middleware(CallbackDataShortenerRequestMiddleware())
    bot.session.middleware(MainAdminRoleSwitchMenuMiddleware())
    dp = Dispatcher(storage=MemoryStorage())

    state_guard = StateGuardMiddleware()
    dp.message.outer_middleware(state_guard)
    # Token resolver must run BEFORE the state guard so it sees real payloads.
    dp.callback_query.outer_middleware(CallbackTokenResolverMiddleware())
    dp.callback_query.outer_middleware(state_guard)

    dp.include_router(start_router)
    dp.include_router(guest_router)
    dp.include_router(schedule_router)
    dp.include_router(students_router)
    dp.include_router(attendance_router)
    dp.include_router(payments_router)
    dp.include_router(groups_info_router)

    loop = asyncio.get_running_loop()

    def _archive_sender(filename: str, content: bytes, caption: str) -> None:
        asyncio.run_coroutine_threadsafe(
            send_annual_archive_document(bot, filename, content, caption), loop
        ).result(timeout=120)

    get_sheets_manager().set_archive_sender(_archive_sender)

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