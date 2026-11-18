import re
from typing import Any, Awaitable, Callable, Optional

from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.database import get_user_lang
from app.keyboards import global_cancel_fsm_kb
from app.locales import TEXTS, t

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
)

MAIN_MENU_BUTTONS: set[str] = {
    "🌐 Tilni o'zgartirish",
    "🌐 Tilni o‘zgartirish",
    "🌐 Тилни ўзгартириш",
}
for _lang in ("latn", "cyrl"):
    for _key in _MAIN_MENU_KEYS:
        _val = TEXTS.get(_lang, {}).get(_key)
        if _val:
            MAIN_MENU_BUTTONS.add(_val)

DEEP_LINK_START_RE = re.compile(r"^/start(?:@\w+)?\s+\S+")

# Callback prefixes strictly tied to specific local FSM flows
_STRICT_STATE_CALLBACK_PREFIXES: dict[str, tuple[str, ...]] = {
    "GroupAddStates": ("grp_add:",),
    "TeacherAddStates": ("tch_add:",),
    "GroupJoinStates": (),
}

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
            if cb_data == "global_cancel_fsm":
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