"""
Mishkat AI assistant handlers.

This router is included LAST in main.py, so it only receives private text /
voice messages that no command, menu button or other handler matched, and only
when the user has NO active FSM state. Students, parents and guests (and staff
whose active role is switched to student / parent) are ignored silently, so no
Gemini quota is ever spent on them and their behaviour is unchanged.
"""

import html
import io
import logging

from aiogram import F, Router
from aiogram.enums import ChatAction, ChatType
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import ai_assistant as ai
from app.config import AI_ENABLED
from app.database import claim_ai_draft, get_user_lang

logger = logging.getLogger(__name__)

router = Router(name="ai_assistant")


def _draft_kb(draft_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=ai.tr("btn_confirm", lang), callback_data=f"ai_mk_confirm:{draft_id}"
                ),
                InlineKeyboardButton(
                    text=ai.tr("btn_cancel", lang), callback_data=f"ai_mk_cancel:{draft_id}"
                ),
            ]
        ]
    )


@router.message(
    F.chat.type == ChatType.PRIVATE,
    StateFilter(None),
    F.text | F.voice,
)
async def ai_fallback_message(message: Message) -> None:
    if not AI_ENABLED or not message.from_user:
        return
    text = (message.text or "").strip()
    if text.startswith("/"):
        return
    user_id = message.from_user.id
    role = await ai.resolve_ai_role(user_id)
    if role not in ai.AI_ROLES:
        # Students / parents / guests: unchanged behaviour, zero API calls.
        return

    user_lang = await get_user_lang(user_id)
    lang = ai.detect_script(text, user_lang) if text else user_lang

    if message.voice is None:
        if ai.is_trivial(text):
            return
        if ai.looks_off_topic(text):
            await message.answer(ai.OFF_TOPIC_REPLY[lang], parse_mode=None)
            return

    audio: bytes | None = None
    if message.voice is not None:
        if int(message.voice.file_size or 0) > ai.MAX_VOICE_BYTES:
            await message.answer(ai.tr("voice_too_big", lang))
            return

    if not ai.check_and_mark_rate_limit(user_id):
        await message.answer(ai.tr("busy_wait", lang))
        return

    if message.voice is not None:
        try:
            buffer = io.BytesIO()
            await message.bot.download(message.voice, destination=buffer)
            audio = buffer.getvalue()
        except Exception:
            logger.exception("Could not download voice message of %s", user_id)
            await message.answer(ai.tr("api_error", lang))
            return
        if len(audio) > ai.MAX_VOICE_BYTES:
            await message.answer(ai.tr("voice_too_big", lang))
            return

    try:
        await message.bot.send_chat_action(message.chat.id, ChatAction.TYPING)
    except Exception:
        logger.debug("typing action failed", exc_info=True)

    reply = await ai.ask(
        user_id=user_id,
        role=role,
        actor_name=message.from_user.full_name or str(user_id),
        lang_hint=lang,
        text=text,
        audio=audio,
    )
    if reply.text:
        # Model text is plain text: escape it for the bot's HTML parse mode.
        await message.answer(html.escape(reply.text), disable_web_page_preview=True)
    for draft in reply.drafts:
        await message.answer(
            ai.render_draft_card(draft["action"], draft["payload"], reply.lang),
            reply_markup=_draft_kb(draft["draft_id"], reply.lang),
            disable_web_page_preview=True,
        )


@router.callback_query(F.data.startswith("ai_mk_confirm:") | F.data.startswith("ai_mk_cancel:"))
async def cb_ai_draft_decision(callback: CallbackQuery) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    kind, _, draft_id = (callback.data or "").partition(":")
    confirm = kind == "ai_mk_confirm"
    result, draft = await claim_ai_draft(draft_id, user_id, "confirmed" if confirm else "cancelled")
    if result != "ok" or draft is None:
        key = {
            "expired": "draft_expired",
            "done": "draft_done",
            "forbidden": "draft_forbidden",
        }.get(result, "draft_not_found")
        await callback.answer(ai.tr(key, lang), show_alert=True)
        if result == "expired" and callback.message:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                logger.debug("could not drop expired draft keyboard", exc_info=True)
        return

    card = ai.render_draft_card(str(draft["action"]), dict(draft["payload"]), lang)
    if not confirm:
        if callback.message:
            await callback.message.edit_text(f"{card}\n\n{ai.tr('draft_cancelled', lang)}")
        await callback.answer()
        return

    await callback.answer("⏳")
    if callback.message:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("could not remove draft keyboard", exc_info=True)
    try:
        outcome = await ai.execute_draft(
            callback.bot,
            user_id,
            callback.from_user.full_name or str(user_id),
            draft,
            lang,
        )
    except Exception as exc:
        logger.exception("AI draft %s failed", draft_id)
        outcome = ai.tr("exec_failed", lang, reason=html.escape(str(exc)[:200]))
    if callback.message:
        await callback.message.edit_text(f"{card}\n\n{outcome}")
