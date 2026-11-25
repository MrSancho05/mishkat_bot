import hashlib
import logging
import re
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Optional

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    TelegramObject,
)

from app.config import is_main_admin

from app.database import (
    get_callback_token_data,
    get_user_lang,
    save_callback_token,
)
from app.keyboards import global_cancel_fsm_kb
from app.locales import button_texts, t

_MAIN_MENU_KEYS = (
    "menu_admin_groups",
    "menu_admin_students",
    "menu_admin_schedule",
    "menu_admin_cancel_lesson",
    "menu_admin_attendance",
    "menu_admin_payments",
    "menu_admin_debtors",
    "menu_teacher_groups",
    "menu_teacher_schedule",
    "menu_teacher_attendance",
    "menu_teacher_cancel_lesson",
    "menu_teacher_payments",
    "menu_teacher_add_student",
    "menu_teacher_debtors",
    "menu_student_group",
    "menu_student_schedule",
    "menu_student_payments",
    "menu_parent_schedule",
    "menu_parent_payments",
    "btn_change_lang",
    "menu_admin_courses",
    "btn_role_switch",
    "menu_guest_courses",
    "menu_guest_enroll",
    "menu_guest_contact",
)

# Current labels plus legacy ones (older reply keyboards may still be on screen).
MAIN_MENU_BUTTONS: set[str] = button_texts(*_MAIN_MENU_KEYS)

DEEP_LINK_START_RE = re.compile(r"^/start(?:@\w+)?\s+\S+")

# Callback prefixes strictly tied to specific local FSM flows
_STRICT_STATE_CALLBACK_PREFIXES: dict[str, tuple[str, ...]] = {
    "GroupAddStates": ("grp_add:", "grp_cal:"),
    "TeacherAddStates": ("tch_add:",),
    "GroupJoinStates": (),
}

# Inline calendar callbacks (group creation start-date picker) are NEVER treated
# as a "tugallanmagan jarayon" violation: they belong to the active flow itself.
_CALENDAR_CALLBACK_PREFIXES = ("grp_cal:",)

# Navigation / cross-flow callbacks blocked whenever any FSM state is active
_NON_FSM_BLOCKED_CALLBACK_PREFIXES = (
    "groups_info:",
    "set_lang:",
    "stu_pay_toggle:",
)


class StateGuardMiddleware(BaseMiddleware):
    """
    Strict FSM State Lock Middleware.
    Whenever a user has an active FSM state, blocks main ReplyKeyboard menu
    buttons, slash commands (except /start <deep_link>), and cross-flow inline
    callbacks, replying with a warning and an inline ❌ Bekor qilish button.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state: Optional[FSMContext] = data.get("state")
        if state is None:
            return await handler(event, data)

        current_state = await state.get_state()
        if current_state is None:
            return await handler(event, data)

        if isinstance(event, Message):
            if not event.from_user:
                return await handler(event, data)

            text = (event.text or "").strip()
            if not text:
                return await handler(event, data)

            if DEEP_LINK_START_RE.match(text):
                return await handler(event, data)

            is_slash_command = text.startswith("/")
            is_main_menu_button = text in MAIN_MENU_BUTTONS

            if is_slash_command or is_main_menu_button:
                lang = await get_user_lang(event.from_user.id)
                await event.answer(
                    text=t("fsm_lock_warning", lang),
                    reply_markup=global_cancel_fsm_kb(lang),
                )
                return None

            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            if not event.from_user:
                return await handler(event, data)

            cb_data = event.data or ""
            if cb_data == "global_cancel_fsm" or cb_data.startswith(
                _CALENDAR_CALLBACK_PREFIXES
            ):
                return await handler(event, data)

            state_group = current_state.split(":", 1)[0]
            should_block = False

            if state_group in _STRICT_STATE_CALLBACK_PREFIXES:
                allowed_prefixes = _STRICT_STATE_CALLBACK_PREFIXES[state_group]
                if not any(cb_data.startswith(p) for p in allowed_prefixes):
                    should_block = True
            elif cb_data.startswith(_NON_FSM_BLOCKED_CALLBACK_PREFIXES):
                should_block = True

            if should_block:
                lang = await get_user_lang(event.from_user.id)
                if event.message:
                    await event.message.answer(
                        text=t("fsm_lock_warning", lang),
                        reply_markup=global_cancel_fsm_kb(lang),
                    )
                await event.answer()
                return None

            return await handler(event, data)

        return await handler(event, data)

# ----------------------------------------------------------------------
# Long callback_data support (unrestricted group names)
# ----------------------------------------------------------------------
# Telegram rejects inline buttons whose callback_data exceeds 64 bytes. Group
# names are embedded in many callbacks ("grp_edit:open:{group}", ...), so long
# or multi-byte names would break those keyboards. Every outgoing inline
# keyboard is scanned; an over-long payload is swapped for a short
# deterministic token "~<hash>" persisted in SQLite, and the incoming callback
# is expanded back to the exact original payload before any filter/handler
# (including StateGuardMiddleware) sees it.

TELEGRAM_CALLBACK_MAX_BYTES = 64
CALLBACK_TOKEN_PREFIX = "~"
_TOKEN_CACHE_LIMIT = 5000
_token_cache: "OrderedDict[str, str]" = OrderedDict()
_mw_logger = logging.getLogger(__name__)


def callback_token_for(data: str) -> str:
    digest = hashlib.sha1(data.encode("utf-8")).hexdigest()[:24]
    return f"{CALLBACK_TOKEN_PREFIX}{digest}"


def _remember_token(token: str, data: str) -> None:
    _token_cache[token] = data
    _token_cache.move_to_end(token)
    while len(_token_cache) > _TOKEN_CACHE_LIMIT:
        _token_cache.popitem(last=False)


async def shorten_callback_data(data: str) -> str:
    if len(data.encode("utf-8")) <= TELEGRAM_CALLBACK_MAX_BYTES:
        return data
    token = callback_token_for(data)
    if _token_cache.get(token) != data:
        await save_callback_token(token, data)
        _remember_token(token, data)
    return token


async def resolve_callback_token(token: str) -> Optional[str]:
    cached = _token_cache.get(token)
    if cached is not None:
        _token_cache.move_to_end(token)
        return cached
    data = await get_callback_token_data(token)
    if data is not None:
        _remember_token(token, data)
    return data


async def _shorten_inline_markup(
    markup: InlineKeyboardMarkup,
) -> Optional[InlineKeyboardMarkup]:
    changed = False
    new_rows: list[list[InlineKeyboardButton]] = []
    for row in markup.inline_keyboard:
        new_row: list[InlineKeyboardButton] = []
        for button in row:
            cb = button.callback_data
            if isinstance(cb, str) and cb:
                short = await shorten_callback_data(cb)
                if short != cb:
                    button = button.model_copy(update={"callback_data": short})
                    changed = True
            new_row.append(button)
        new_rows.append(new_row)
    if not changed:
        return None
    return markup.model_copy(update={"inline_keyboard": new_rows})


class CallbackDataShortenerRequestMiddleware(BaseRequestMiddleware):
    """Outgoing (bot.session) middleware: tokenizes over-long callback_data."""

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType,
        bot: Any,
        method: Any,
    ) -> Any:
        markup = getattr(method, "reply_markup", None)
        if isinstance(markup, InlineKeyboardMarkup):
            try:
                new_markup = await _shorten_inline_markup(markup)
            except Exception:
                _mw_logger.exception("Failed to shorten inline keyboard callbacks")
                new_markup = None
            if new_markup is not None:
                method = method.model_copy(update={"reply_markup": new_markup})
        return await make_request(bot, method)


class CallbackTokenResolverMiddleware(BaseMiddleware):
    """Incoming (outer callback_query) middleware: expands '~<hash>' tokens."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery):
            cb_data = event.data or ""
            if cb_data.startswith(CALLBACK_TOKEN_PREFIX):
                original = await resolve_callback_token(cb_data)
                if original is None:
                    lang = (
                        await get_user_lang(event.from_user.id)
                        if event.from_user
                        else "latn"
                    )
                    await event.answer(
                        t("callback_token_expired", lang), show_alert=True
                    )
                    return None
                event = event.model_copy(update={"data": original})
        return await handler(event, data)


# ----------------------------------------------------------------------
# "🔄 Rolni almashtirish" — injected ONLY into the main admin's main menus
# ----------------------------------------------------------------------

ROLE_SWITCH_TEXTS: set[str] = button_texts("btn_role_switch")
_MAIN_MENU_MARKER_TEXTS: set[str] = button_texts("btn_change_lang")


class MainAdminRoleSwitchMenuMiddleware(BaseRequestMiddleware):
    """
    Outgoing (bot.session) middleware: every main-menu reply keyboard (it always
    contains the 🌐 language button) sent to the MAIN admin (ADMIN_ID / first
    ADMIN_IDS) gets a '🔄 Rolni almashtirish' row — whichever role's menu
    (Admin / Ustoz / Talaba / Ota-ona) is being shown. Secondary admins and
    everyone else never receive the button.
    """

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType,
        bot: Any,
        method: Any,
    ) -> Any:
        markup = getattr(method, "reply_markup", None)
        chat_id = getattr(method, "chat_id", None)
        if isinstance(markup, ReplyKeyboardMarkup) and is_main_admin(chat_id):
            texts = {btn.text for row in markup.keyboard for btn in row}
            if texts & _MAIN_MENU_MARKER_TEXTS and not texts & ROLE_SWITCH_TEXTS:
                try:
                    lang = await get_user_lang(int(str(chat_id)))
                    new_rows = [list(row) for row in markup.keyboard]
                    new_rows.append([KeyboardButton(text=t("btn_role_switch", lang))])
                    method = method.model_copy(
                        update={
                            "reply_markup": markup.model_copy(
                                update={"keyboard": new_rows}
                            )
                        }
                    )
                except Exception:
                    _mw_logger.exception("Could not add the role switch button")
        return await make_request(bot, method)
