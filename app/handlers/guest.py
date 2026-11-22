"""
Guest (unverified new user) experience + Admin course catalog management.

Guest menu (shown after language selection to users without an approved role):
    📚 Kurslarimiz | ✍️ Kursga yozilish | 📍 Manzil va aloqa | 🌐 Tilni o'zgartirish

Admin menu: 📚 Kurslarni boshqarish (add / edit price / activate / delete, leads).
"""

import html
import logging
import re
from typing import Any, Optional

import aiosqlite
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

from app import config
from app.config import ADMIN_IDS, DB_PATH
from app.database import (
    add_course,
    create_lead,
    delete_course,
    get_all_dynamic_admins,
    get_course,
    get_lead,
    get_lead_admin_messages,
    get_lead_by_telegram_id,
    get_courses,
    get_recent_leads,
    get_user,
    get_user_lang,
    has_dual_student_parent_role,
    mark_lead_contacted,
    sync_leads_with_sheet,
    save_lead_admin_message,
    update_course,
)
from app.keyboards import (
    balance_inline_markup,
    get_main_menu_kb,
    guest_menu_kb,
    pair_buttons,
    share_phone_reply_kb,
)
from app.locales import t
from app.sheets import get_sheets_manager
from app.states import CourseManageStates, GuestLeadStates
from app.utils import format_tashkent, tashkent_now_str

logger = logging.getLogger(__name__)
router = Router(name="guest")

SIGNATURE = {
    "latn": "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!",
    "cyrl": "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!",
}

COURSES_TEXTS = {t("menu_guest_courses", "latn"), t("menu_guest_courses", "cyrl")}
ENROLL_TEXTS = {t("menu_guest_enroll", "latn"), t("menu_guest_enroll", "cyrl")}
CONTACT_TEXTS = {t("menu_guest_contact", "latn"), t("menu_guest_contact", "cyrl")}
ADMIN_COURSES_TEXTS = {t("menu_admin_courses", "latn"), t("menu_admin_courses", "cyrl")}
CANCEL_TEXTS = {t("btn_cancel", "latn"), t("btn_cancel", "cyrl")}
BACK_TEXTS = {t("btn_back", "latn"), t("btn_back", "cyrl")}

_G: dict[str, dict[str, str]] = {
    "latn": {
        "courses_header": (
            "📚 <b>Mishkat Nodavlat Ta'lim Muassasasi kurslari</b>\n\n"
            "Batafsil ma'lumot olish uchun kursni tanlang 👇"
        ),
        "courses_empty": "ℹ️ Hozircha kurslar ro‘yxati shakllantirilmoqda. Tez orada!",
        "course_line": "{idx}. <b>{name}</b> — {price}",
        "course_card": (
            "📘 <b>{name}</b>\n\n"
            "{description}\n\n"
            "💰 Narxi: <b>{price}</b>\n"
            "⏳ Davomiyligi: <b>{duration}</b>\n"
            "📆 Dars jadvali: <b>{schedule}</b>"
        ),
        "price_monthly": "{amount} so‘m / oy",
        "price_ask": "administrator bilan kelishiladi",
        "btn_enroll_this": "✍️ Kursga yozilish",
        "btn_back_courses": "⬅️ Kurslar",
        "btn_not_sure": "🤔 Maslahat kerak",
        "enroll_choose": "✍️ <b>Kursga yozilish</b>\n\nQaysi kursga yozilmoqchisiz?",
        "enroll_enter_name": (
            "✍️ <b>Kurs:</b> {course}\n\n"
            "Iltimos, to‘liq <b>Familiya va Ismingizni</b> kiriting "
            "(masalan: <i>Aliyev Vali</i>):"
        ),
        "enroll_invalid_name": (
            "❌ Iltimos, Familiya va Ismingizni kamida 2 ta so‘z bilan kiriting "
            "(masalan: <i>Aliyev Vali</i>):"
        ),
        "enroll_share_phone": (
            "📞 Rahmat, <b>{name}</b>!\n\n"
            "Endi pastdagi «📱 Telefon raqamni yuborish» tugmasi orqali "
            "telefon raqamingizni yuboring:"
        ),
        "enroll_own_contact": "❗️ Iltimos, faqat o‘zingizning telefon raqamingizni yuboring.",
        "enroll_use_button": "❗️ Iltimos, telefon raqamni pastdagi tugma orqali yuboring.",
        "enroll_success": (
            "✅ <b>Arizangiz qabul qilindi!</b>\n\n"
            "👤 F.I.O.: <b>{name}</b>\n"
            "📞 Telefon: <b>{phone}</b>\n"
            "📚 Kurs: <b>{course}</b>\n\n"
            "Tez orada administratorlarimiz siz bilan bog‘lanishadi. "
            "Bizni tanlaganingiz uchun rahmat!"
        ),
        "enroll_cancelled": "❌ Ariza bekor qilindi.",
        "not_sure_course": "Hali aniq emas (maslahat kerak)",
        "admin_lead_notify": (
            "🆕 <b>Yangi ariza (kursga yozilish)!</b>\n\n"
            "👤 F.I.O.: <b>{name}</b>\n"
            "📞 Telefon: {phone_link}\n"
            "💬 Telegram: {tg_link}\n"
            "📚 Kurs: <b>{course}</b>\n"
            "🌐 Til: <b>{lang_label}</b>\n"
            "🕒 Yuborilgan vaqt: <b>{submitted_at}</b> (Toshkent)\n"
            "🆔 Ariza: <code>#{lead_id}</code>"
        ),
        "btn_lead_contacted": "✅ Bog'lanildi",
        "lead_marked": "✅ Ariza #{lead_id} «bog‘lanildi» deb belgilandi.",
        "lead_already_marked": "ℹ️ Ariza #{lead_id} allaqachon «bog‘lanildi» deb belgilangan.",
        "lead_status_line": "✅ Holat: Bog'lanildi ({admin_name}, {time})",
        "enroll_blocked_pending": (
            "⏳ Arizangiz qabul qilingan va adminga yuborilgan. "
            "Iltimos, siz bilan aloqaga chiqishlarini kuting."
        ),
        "enroll_blocked_contacted": (
            "✅ Siz bilan allaqachon bog'lanib bo'lganmiz. "
            "Qandaydir savol va takliflaringiz bo'lsa, quyidagi raqamga murojaat qiling:"
        ),
        "enroll_blocked_phone": "📞 {phone}",
        "contact_header": "📍 <b>Manzil va aloqa</b>",
        "contact_address": "🏢 Manzil: <b>{value}</b>",
        "contact_landmark": "🧭 Mo‘ljal: <b>{value}</b>",
        "contact_phone": "📞 Telefon: {value}",
        "contact_telegram": "✈️ Telegram: {value}",
        "contact_instagram": "📸 Instagram: {value}",
        "contact_hours": "🕘 Ish vaqti: <b>{value}</b>",
        "contact_map": "🗺 Xaritada: <a href=\"{value}\">ochish</a>",
        "contact_missing": (
            "ℹ️ Manzil va aloqa ma'lumotlari tez orada qo‘shiladi. "
            "Hozircha «✍️ Kursga yozilish» orqali ariza qoldiring — administratorlarimiz "
            "o‘zlari siz bilan bog‘lanishadi."
        ),
        "contact_admins": "👤 Administratorlar: {value}",
        # Admin course management
        "adm_panel": "📚 <b>Kurslarni boshqarish</b>\n\nJami: <b>{total} ta</b> kurs. Kursni tanlang:",
        "adm_btn_add": "➕ Yangi kurs",
        "adm_btn_leads": "🧾 So‘nggi arizalar",
        "adm_btn_price": "💰 Narxni yangilash",
        "adm_btn_toggle_on": "🟢 Faollashtirish",
        "adm_btn_toggle_off": "🔴 Yashirish",
        "adm_btn_delete": "🗑 O‘chirish",
        "adm_btn_delete_yes": "✅ Ha, o‘chirish",
        "adm_btn_back": "⬅️ Kurslar",
        "adm_status_on": "🟢 faol",
        "adm_status_off": "🔴 yashirin",
        "adm_course_admin_card": "{card}\n\n📊 Holati: <b>{status}</b>",
        "adm_enter_name": "➕ <b>Yangi kurs</b>\n\n1️⃣ Kurs nomini kiriting:",
        "adm_enter_desc": "2️⃣ Kurs haqida qisqacha tavsif kiriting:",
        "adm_enter_price": (
            "3️⃣ Oylik narxini kiriting (so‘mda, masalan <code>450000</code>).\n"
            "Narx kelishiladigan bo‘lsa <code>0</code> kiriting:"
        ),
        "adm_enter_duration": (
            "4️⃣ Davomiyligi va dars jadvalini kiriting, masalan:\n"
            "<code>6 oy | Haftasiga 3 marta</code>"
        ),
        "adm_invalid_price": "❌ Faqat raqam kiriting (0 — kelishiladi).",
        "adm_saved": "✅ Kurs saqlandi!",
        "adm_price_saved": "✅ Narx yangilandi!",
        "adm_deleted": "🗑 Kurs o‘chirildi.",
        "adm_confirm_delete": "⚠️ <b>{name}</b> kursini o‘chirmoqchimisiz?",
        "adm_leads_header": "🧾 <b>So‘nggi arizalar</b>",
        "adm_leads_empty": "ℹ️ Hozircha arizalar yo‘q.",
        "adm_lead_item": (
            "#{lead_id} • <b>{name}</b> — {phone_link} | {tg_link}\n"
            "   📚 {course} | 🕘 {date} | {status}"
        ),
        "lead_status_new": "🆕 yangi",
        "lead_status_contacted": "✅ bog‘lanildi",
        "no_permission": "❌ Sizda ushbu amalni bajarish huquqi yo‘q.",
    },
    "cyrl": {
        "courses_header": (
            "📚 <b>Мишкат Нодавлат Таълим Муассасаси курслари</b>\n\n"
            "Батафсил маълумот олиш учун курсни танланг 👇"
        ),
        "courses_empty": "ℹ️ Ҳозирча курслар рўйхати шакллантирилмоқда. Тез орада!",
        "course_line": "{idx}. <b>{name}</b> — {price}",
        "course_card": (
            "📘 <b>{name}</b>\n\n"
            "{description}\n\n"
            "💰 Нархи: <b>{price}</b>\n"
            "⏳ Давомийлиги: <b>{duration}</b>\n"
            "📆 Дарс жадвали: <b>{schedule}</b>"
        ),
        "price_monthly": "{amount} сўм / ой",
        "price_ask": "администратор билан келишилади",
        "btn_enroll_this": "✍️ Курсга ёзилиш",
        "btn_back_courses": "⬅️ Курслар",
        "btn_not_sure": "🤔 Маслаҳат керак",
        "enroll_choose": "✍️ <b>Курсга ёзилиш</b>\n\nҚайси курсга ёзилмоқчисиз?",
        "enroll_enter_name": (
            "✍️ <b>Курс:</b> {course}\n\n"
            "Илтимос, тўлиқ <b>Фамилия ва Исмингизни</b> киритинг "
            "(масалан: <i>Алиев Вали</i>):"
        ),
        "enroll_invalid_name": (
            "❌ Илтимос, Фамилия ва Исмингизни камида 2 та сўз билан киритинг "
            "(масалан: <i>Алиев Вали</i>):"
        ),
        "enroll_share_phone": (
            "📞 Раҳмат, <b>{name}</b>!\n\n"
            "Энди пастдаги «📱 Телефон рақамни юбориш» тугмаси орқали "
            "телефон рақамингизни юборинг:"
        ),
        "enroll_own_contact": "❗️ Илтимос, фақат ўзингизнинг телефон рақамингизни юборинг.",
        "enroll_use_button": "❗️ Илтимос, телефон рақамни пастдаги тугма орқали юборинг.",
        "enroll_success": (
            "✅ <b>Аризангиз қабул қилинди!</b>\n\n"
            "👤 Ф.И.О.: <b>{name}</b>\n"
            "📞 Телефон: <b>{phone}</b>\n"
            "📚 Курс: <b>{course}</b>\n\n"
            "Тез орада администраторларимиз сиз билан боғланишади. "
            "Бизни танлаганингиз учун раҳмат!"
        ),
        "enroll_cancelled": "❌ Ариза бекор қилинди.",
        "not_sure_course": "Ҳали аниқ эмас (маслаҳат керак)",
        "admin_lead_notify": (
            "🆕 <b>Янги ариза (курсга ёзилиш)!</b>\n\n"
            "👤 Ф.И.О.: <b>{name}</b>\n"
            "📞 Телефон: {phone_link}\n"
            "💬 Telegram: {tg_link}\n"
            "📚 Курс: <b>{course}</b>\n"
            "🌐 Тил: <b>{lang_label}</b>\n"
            "🕒 Юборилган вақт: <b>{submitted_at}</b> (Тошкент)\n"
            "🆔 Ариза: <code>#{lead_id}</code>"
        ),
        "btn_lead_contacted": "✅ Боғланилди",
        "lead_marked": "✅ Ариза #{lead_id} «боғланилди» деб белгиланди.",
        "lead_already_marked": "ℹ️ Ариза #{lead_id} аллақачон «боғланилди» деб белгиланган.",
        "lead_status_line": "✅ Ҳолат: Боғланилди ({admin_name}, {time})",
        "enroll_blocked_pending": (
            "⏳ Аризангиз қабул қилинган ва админга юборилган. "
            "Илтимос, сиз билан алоқага чиқишларини кутинг."
        ),
        "enroll_blocked_contacted": (
            "✅ Сиз билан аллақачон боғланиб бўлганмиз. "
            "Қандайдир савол ва таклифларингиз бўлса, қуйидаги рақамга мурожаат қилинг:"
        ),
        "enroll_blocked_phone": "📞 {phone}",
        "contact_header": "📍 <b>Манзил ва алоқа</b>",
        "contact_address": "🏢 Манзил: <b>{value}</b>",
        "contact_landmark": "🧭 Мўлжал: <b>{value}</b>",
        "contact_phone": "📞 Телефон: {value}",
        "contact_telegram": "✈️ Telegram: {value}",
        "contact_instagram": "📸 Instagram: {value}",
        "contact_hours": "🕘 Иш вақти: <b>{value}</b>",
        "contact_map": "🗺 Харитада: <a href=\"{value}\">очиш</a>",
        "contact_missing": (
            "ℹ️ Манзил ва алоқа маълумотлари тез орада қўшилади. "
            "Ҳозирча «✍️ Курсга ёзилиш» орқали ариза қолдиринг — администраторларимиз "
            "ўзлари сиз билан боғланишади."
        ),
        "contact_admins": "👤 Администраторлар: {value}",
        "adm_panel": "📚 <b>Курсларни бошқариш</b>\n\nЖами: <b>{total} та</b> курс. Курсни танланг:",
        "adm_btn_add": "➕ Янги курс",
        "adm_btn_leads": "🧾 Сўнгги аризалар",
        "adm_btn_price": "💰 Нархни янгилаш",
        "adm_btn_toggle_on": "🟢 Фаоллаштириш",
        "adm_btn_toggle_off": "🔴 Яшириш",
        "adm_btn_delete": "🗑 Ўчириш",
        "adm_btn_delete_yes": "✅ Ҳа, ўчириш",
        "adm_btn_back": "⬅️ Курслар",
        "adm_status_on": "🟢 фаол",
        "adm_status_off": "🔴 яширин",
        "adm_course_admin_card": "{card}\n\n📊 Ҳолати: <b>{status}</b>",
        "adm_enter_name": "➕ <b>Янги курс</b>\n\n1️⃣ Курс номини киритинг:",
        "adm_enter_desc": "2️⃣ Курс ҳақида қисқача тавсиф киритинг:",
        "adm_enter_price": (
            "3️⃣ Ойлик нархини киритинг (сўмда, масалан <code>450000</code>).\n"
            "Нарх келишиладиган бўлса <code>0</code> киритинг:"
        ),
        "adm_enter_duration": (
            "4️⃣ Давомийлиги ва дарс жадвалини киритинг, масалан:\n"
            "<code>6 ой | Ҳафтасига 3 марта</code>"
        ),
        "adm_invalid_price": "❌ Фақат рақам киритинг (0 — келишилади).",
        "adm_saved": "✅ Курс сақланди!",
        "adm_price_saved": "✅ Нарх янгиланди!",
        "adm_deleted": "🗑 Курс ўчирилди.",
        "adm_confirm_delete": "⚠️ <b>{name}</b> курсини ўчирмоқчимисиз?",
        "adm_leads_header": "🧾 <b>Сўнгги аризалар</b>",
        "adm_leads_empty": "ℹ️ Ҳозирча аризалар йўқ.",
        "adm_lead_item": (
            "#{lead_id} • <b>{name}</b> — {phone_link} | {tg_link}\n"
            "   📚 {course} | 🕘 {date} | {status}"
        ),
        "lead_status_new": "🆕 янги",
        "lead_status_contacted": "✅ боғланилди",
        "no_permission": "❌ Сизда ушбу амални бажариш ҳуқуқи йўқ.",
    },
}


def _g(key: str, lang: str, **kwargs: Any) -> str:
    safe_lang = lang if lang in _G else "latn"
    template = _G[safe_lang].get(key) or _G["latn"].get(key, key)
    return template.format(**kwargs) if kwargs else template


def _sig(lang: str) -> str:
    return f"\n\n<i>{SIGNATURE.get(lang, SIGNATURE['latn'])}</i>"


def _fmt_sum(amount: int) -> str:
    return f"{int(amount or 0):,}".replace(",", " ")


def _price_text(course: dict[str, Any], lang: str) -> str:
    price = int(course.get("price") or 0)
    if price > 0:
        return _g("price_monthly", lang, amount=_fmt_sum(price))
    return _g("price_ask", lang)


def _normalize_phone(raw_phone: str) -> str:
    compact = re.sub(r"[^\d+]", "", (raw_phone or "").strip())
    digits = re.sub(r"\D", "", compact)
    if len(digits) == 9:
        return f"+998{digits}"
    if digits.startswith("998") and len(digits) == 12:
        return f"+{digits}"
    if compact and not compact.startswith("+") and len(digits) >= 7:
        return f"+{digits}"
    return compact


def _tel_link(phone: str) -> str:
    norm = _normalize_phone(phone)
    if not norm:
        return "—"
    safe = html.escape(norm)
    return f'<a href="tel:{safe}">{safe}</a>'


def _tg_link(chat_id: Any, username: str = "", label: str = "Telegram") -> str:
    uname = (username or "").strip().lstrip("@")
    parts: list[str] = []
    try:
        cid = int(str(chat_id).split(".", 1)[0])
    except (TypeError, ValueError):
        cid = 0
    if cid > 0:
        parts.append(f'<a href="tg://user?id={cid}">{html.escape(label)}</a>')
    if re.fullmatch(r"[A-Za-z0-9_]{3,}", uname):
        parts.append(f'<a href="https://t.me/{uname}">@{html.escape(uname)}</a>')
    return " | ".join(parts) or "—"


def _validate_full_name(raw: str) -> Optional[str]:
    cleaned = " ".join((raw or "").strip().split())
    if (
        not cleaned
        or cleaned.startswith("/")
        or len(cleaned) < 4
        or len(cleaned) > 80
        or cleaned in CANCEL_TEXTS
        or cleaned in BACK_TEXTS
    ):
        return None
    words = [w for w in cleaned.split(" ") if len(w) >= 2]
    return cleaned if len(words) >= 2 else None


async def _is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    db_user = await get_user(user_id)
    if db_user and db_user.get("role") == "admin":
        return True
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM dynamic_admins WHERE telegram_id = ?;", (user_id,)
            ) as cur:
                if await cur.fetchone():
                    return True
    except Exception:
        pass
    return False


async def _all_admin_ids() -> list[int]:
    ids: list[int] = list(ADMIN_IDS)
    try:
        for row in await get_all_dynamic_admins():
            tid = int(row["telegram_id"])
            if tid not in ids:
                ids.append(tid)
    except Exception:
        logger.exception("Failed loading dynamic admins")
    return ids


async def _menu_for_user(user_id: int, lang: str) -> Any:
    """Reply keyboard of the user's real role (guest menu when no role)."""
    db_user = await get_user(user_id)
    role = (db_user.get("active_role") or db_user.get("role")) if db_user else None
    if user_id in ADMIN_IDS:
        role = "admin"
    if role in {"admin", "teacher", "student", "parent"}:
        return get_main_menu_kb(
            role, lang, has_dual_role=await has_dual_student_parent_role(user_id)
        )
    return guest_menu_kb(lang)


# ----------------------------------------------------------------------
# 📚 Kurslarimiz
# ----------------------------------------------------------------------


def _courses_list_kb(
    courses: list[dict[str, Any]], prefix: str, lang: str, include_not_sure: bool = False
) -> InlineKeyboardMarkup:
    rows = pair_buttons(
        [
            InlineKeyboardButton(
                text=f"📘 {c['name']}", callback_data=f"{prefix}:{c['id']}"
            )
            for c in courses
        ]
    )
    if include_not_sure:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_g("btn_not_sure", lang), callback_data=f"{prefix}:0"
                ),
                InlineKeyboardButton(
                    text=t("btn_cancel", lang), callback_data="guest:cancel"
                ),
            ]
        )
    return balance_inline_markup(InlineKeyboardMarkup(inline_keyboard=rows))


async def _render_courses_list(lang: str) -> tuple[str, Optional[InlineKeyboardMarkup]]:
    courses = await get_courses(active_only=True)
    if not courses:
        return _g("courses_empty", lang) + _sig(lang), None
    lines = [_g("courses_header", lang), ""]
    for idx, c in enumerate(courses, start=1):
        lines.append(
            _g(
                "course_line",
                lang,
                idx=idx,
                name=html.escape(c["name"]),
                price=html.escape(_price_text(c, lang)),
            )
        )
    return "\n".join(lines) + _sig(lang), _courses_list_kb(courses, "guest:course", lang)


def _course_card(course: dict[str, Any], lang: str) -> str:
    return _g(
        "course_card",
        lang,
        name=html.escape(course.get("name") or ""),
        description=html.escape(course.get("description") or "—"),
        price=html.escape(_price_text(course, lang)),
        duration=html.escape(course.get("duration") or "—"),
        schedule=html.escape(course.get("schedule") or "—"),
    )


@router.message(F.chat.type == ChatType.PRIVATE, F.text.in_(COURSES_TEXTS))
async def guest_courses(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    text, kb = await _render_courses_list(lang)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "guest:courses")
async def cb_guest_courses(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    text, kb = await _render_courses_list(lang)
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("guest:course:"))
async def cb_guest_course_detail(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    try:
        course_id = int((callback.data or "").rsplit(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    course = await get_course(course_id)
    if not course or not int(course.get("is_active") or 0):
        await callback.answer(_g("courses_empty", lang), show_alert=True)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_g("btn_enroll_this", lang),
                    callback_data=f"guest:enroll:{course_id}",
                ),
                InlineKeyboardButton(
                    text=_g("btn_back_courses", lang), callback_data="guest:courses"
                ),
            ],
        ]
    )
    try:
        await callback.message.edit_text(
            _course_card(course, lang) + _sig(lang), reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        await callback.message.answer(
            _course_card(course, lang) + _sig(lang), reply_markup=kb, parse_mode="HTML"
        )
    await callback.answer()


# ----------------------------------------------------------------------
# ✍️ Kursga yozilish (lead registration)
# ----------------------------------------------------------------------


async def _ask_lead_name(
    target: Message, state: FSMContext, lang: str, course_id: int
) -> None:
    course_name = _g("not_sure_course", lang)
    if course_id:
        course = await get_course(course_id)
        if course:
            course_name = str(course.get("name") or course_name)
    await state.update_data(lead_course_id=course_id or None, lead_course_name=course_name)
    await state.set_state(GuestLeadStates.entering_full_name)
    await target.answer(
        _g("enroll_enter_name", lang, course=html.escape(course_name)),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="guest:cancel")]
            ]
        ),
        parse_mode="HTML",
    )


async def _existing_lead_status(user_id: int) -> Optional[str]:
    """
    'new' / 'contacted' when this Telegram account already has an application,
    else None. SQLite is checked first; the Qiziquvchilar_Lidlar sheet (by
    Chat_ID) is the fallback so the limit survives a lost / reset database.
    """
    snapshot = await _sync_leads_with_sheet()
    lead = await get_lead_by_telegram_id(user_id)
    if lead:
        return "contacted" if str(lead.get("status") or "") == "contacted" else "new"
    if snapshot is None:
        return None
    sheet_lead = (snapshot.get("by_chat") or {}).get(str(user_id))
    if sheet_lead:
        return str(sheet_lead.get("status") or "new")
    return None


async def _sync_leads_with_sheet() -> Optional[dict[str, Any]]:
    """
    Reads Qiziquvchilar_Lidlar once and drops stale SQLite leads whose row an
    admin deleted from the sheet (so that account may apply again). Returns the
    sheet snapshot, or None when the sheet could not be read (nothing is
    deleted in that case).
    """
    try:
        snapshot = await get_sheets_manager().a_get_lead_snapshot()
    except Exception:
        logger.exception("Could not read Qiziquvchilar_Lidlar for lead sync")
        return None
    try:
        removed = await sync_leads_with_sheet(set((snapshot.get("by_chat") or {}).keys()))
        if removed:
            logger.info("Removed %s stale lead(s) missing from the sheet", removed)
    except Exception:
        logger.exception("Stale lead cleanup failed")
    return snapshot


async def _reply_if_already_applied(
    target: Message, user_id: int, lang: str, state: Optional[FSMContext] = None
) -> bool:
    """One Telegram account = one application ever. True when the user was blocked."""
    status = await _existing_lead_status(user_id)
    if status is None:
        return False
    if state is not None:
        await state.clear()
    if status == "contacted":
        text = _g("enroll_blocked_contacted", lang)
        phone = config.SUPPORT_PHONE
        if phone:
            text += "\n" + _g("enroll_blocked_phone", lang, phone=_tel_link(phone))
    else:
        text = _g("enroll_blocked_pending", lang)
    await target.answer(
        text + _sig(lang),
        reply_markup=await _menu_for_user(user_id, lang),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    return True


@router.message(F.chat.type == ChatType.PRIVATE, F.text.in_(ENROLL_TEXTS))
async def guest_enroll_start(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    await state.clear()
    if await _reply_if_already_applied(message, message.from_user.id, lang):
        return
    courses = await get_courses(active_only=True)
    await state.set_state(GuestLeadStates.choosing_course)
    await message.answer(
        _g("enroll_choose", lang),
        reply_markup=_courses_list_kb(courses, "guest:pick", lang, include_not_sure=True),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("guest:enroll:"))
async def cb_guest_enroll_from_card(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    try:
        course_id = int((callback.data or "").rsplit(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    await state.clear()
    if await _reply_if_already_applied(callback.message, callback.from_user.id, lang):
        await callback.answer()
        return
    await _ask_lead_name(callback.message, state, lang, course_id)
    await callback.answer()


@router.callback_query(GuestLeadStates.choosing_course, F.data.startswith("guest:pick:"))
async def cb_guest_pick_course(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    try:
        course_id = int((callback.data or "").rsplit(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _ask_lead_name(callback.message, state, lang, course_id)
    await callback.answer()


async def _cancel_lead(target: Message, state: FSMContext, user_id: int) -> None:
    lang = await get_user_lang(user_id)
    await state.clear()
    await target.answer(
        _g("enroll_cancelled", lang),
        reply_markup=await _menu_for_user(user_id, lang),
    )


@router.callback_query(StateFilter(GuestLeadStates), F.data == "guest:cancel")
async def cb_guest_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _cancel_lead(callback.message, state, callback.from_user.id)
    await callback.answer()


@router.callback_query(F.data == "guest:cancel")
async def cb_guest_cancel_stale(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()


@router.message(StateFilter(GuestLeadStates), F.text.in_(CANCEL_TEXTS))
async def msg_guest_cancel(message: Message, state: FSMContext) -> None:
    if message.from_user:
        await _cancel_lead(message, state, message.from_user.id)


@router.message(GuestLeadStates.entering_full_name)
async def msg_guest_full_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    full_name = _validate_full_name(message.text or "")
    if not full_name:
        await message.answer(_g("enroll_invalid_name", lang), parse_mode="HTML")
        return
    await state.update_data(lead_full_name=full_name)
    await state.set_state(GuestLeadStates.sharing_phone)
    await message.answer(
        _g("enroll_share_phone", lang, name=html.escape(full_name)),
        reply_markup=share_phone_reply_kb(lang, include_back=True),
        parse_mode="HTML",
    )


@router.message(GuestLeadStates.sharing_phone, F.text.in_(BACK_TEXTS))
async def msg_guest_phone_back(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    data = await state.get_data()
    await state.set_state(GuestLeadStates.entering_full_name)
    await message.answer(
        _g(
            "enroll_enter_name",
            lang,
            course=html.escape(str(data.get("lead_course_name") or "—")),
        ),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )


def _render_lead_notify(lead: dict[str, Any], a_lang: str) -> str:
    lead_lang = str(lead.get("lang") or "latn")
    username = str(lead.get("username") or "")
    full_name = str(lead.get("full_name") or "")
    return _g(
        "admin_lead_notify",
        a_lang,
        name=html.escape(full_name),
        phone_link=_tel_link(str(lead.get("phone") or "")),
        tg_link=_tg_link(
            lead.get("telegram_id"), username, label=full_name or "Telegram"
        ),
        course=html.escape(str(lead.get("course_name") or "—")),
        lang_label="Кирилл" if lead_lang == "cyrl" else "Lotin",
        submitted_at=html.escape(format_tashkent(lead.get("created_at"), "%d.%m.%Y %H:%M:%S")),
        lead_id=lead.get("id", "—"),
    )


async def _finalize_lead(message: Message, state: FSMContext, phone: str) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()
    full_name = str(data.get("lead_full_name") or message.from_user.full_name or "").strip()
    course_name = str(data.get("lead_course_name") or _g("not_sure_course", lang))
    course_id = data.get("lead_course_id")
    username = message.from_user.username or ""

    # Final guard: a second tap / parallel flow must never create another application.
    if await _reply_if_already_applied(message, user_id, lang, state):
        return

    # Sequential numbering: reconcile with the sheet first, then number the new
    # lead from max(existing ids in SQLite + sheet) + 1 (or 1 when both are empty).
    snapshot = await _sync_leads_with_sheet()
    sheet_max_id = int((snapshot or {}).get("max_id") or 0)
    lead = await create_lead(
        telegram_id=user_id,
        full_name=full_name,
        phone=phone,
        course_id=int(course_id) if course_id else None,
        course_name=course_name,
        username=username,
        lang=lang,
        sheet_max_id=sheet_max_id,
    )
    try:
        await get_sheets_manager().a_append_lead(lead)
    except Exception:
        logger.exception("Failed syncing lead #%s to Qiziquvchilar_Lidlar", lead.get("id"))

    lead_id = int(lead.get("id") or 0)
    for admin_id in await _all_admin_ids():
        try:
            a_lang = await get_user_lang(admin_id)
            sent = await message.bot.send_message(
                chat_id=admin_id,
                text=_render_lead_notify(lead, a_lang),
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=_g("btn_lead_contacted", a_lang),
                                callback_data=f"lead_contacted:{lead_id}",
                            )
                        ]
                    ]
                ),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            await save_lead_admin_message(lead_id, admin_id, sent.message_id)
        except Exception as exc:
            logger.warning("Lead notification to admin %s failed: %s", admin_id, exc)

    await state.clear()
    await message.answer(
        _g(
            "enroll_success",
            lang,
            name=html.escape(full_name),
            phone=html.escape(phone),
            course=html.escape(course_name),
        )
        + _sig(lang),
        reply_markup=await _menu_for_user(user_id, lang),
        parse_mode="HTML",
    )


@router.message(GuestLeadStates.sharing_phone, F.contact)
async def msg_guest_contact(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.contact:
        return
    lang = await get_user_lang(message.from_user.id)
    if message.contact.user_id and message.contact.user_id != message.from_user.id:
        await message.answer(
            _g("enroll_own_contact", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )
        return
    await _finalize_lead(message, state, _normalize_phone(message.contact.phone_number))


@router.message(GuestLeadStates.sharing_phone)
async def msg_guest_phone_fallback(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    await message.answer(
        _g("enroll_use_button", lang),
        reply_markup=share_phone_reply_kb(lang, include_back=True),
    )


@router.message(GuestLeadStates.choosing_course)
async def msg_guest_choose_fallback(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    courses = await get_courses(active_only=True)
    await message.answer(
        _g("enroll_choose", lang),
        reply_markup=_courses_list_kb(courses, "guest:pick", lang, include_not_sure=True),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith(("lead_contacted:", "lead_done:")))
async def cb_lead_contacted(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    if not await _is_admin(callback.from_user.id):
        await callback.answer(_g("no_permission", lang), show_alert=True)
        return
    try:
        lead_id = int((callback.data or "").split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    lead = await get_lead(lead_id)
    if not lead:
        await callback.answer()
        return

    admin_id = callback.from_user.id
    admin_name = callback.from_user.full_name or str(admin_id)
    now_str = tashkent_now_str("%d.%m.%Y %H:%M:%S")
    changed = await mark_lead_contacted(lead_id, admin_id, now_str)

    if changed:
        # Sheet: Holat "Yangi" -> "Bog'lanildi", red (#F4CCCC) -> green (#D9EAD3).
        try:
            await get_sheets_manager().a_mark_lead_contacted(
                f"{lead_id}", lead.get("telegram_id")
            )
        except Exception:
            logger.exception("Failed updating lead #%s in Qiziquvchilar_Lidlar", lead_id)
        lead = await get_lead(lead_id) or lead
        shown_time = now_str[:16]
        copies = await get_lead_admin_messages(lead_id)
        known = {(int(c["admin_id"]), int(c["message_id"])) for c in copies}
        known.add((callback.message.chat.id, callback.message.message_id))
        for chat_id, message_id in known:
            try:
                a_lang = await get_user_lang(chat_id)
                text = (
                    _render_lead_notify(lead, a_lang)
                    + "\n\n"
                    + _g(
                        "lead_status_line",
                        a_lang,
                        admin_name=html.escape(admin_name),
                        time=shown_time,
                    )
                )
                await callback.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=None,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
            except Exception as exc:
                logger.warning(
                    "Could not update lead #%s message for admin %s: %s",
                    lead_id,
                    chat_id,
                    exc,
                )
        await callback.answer(_g("lead_marked", lang, lead_id=lead_id), show_alert=True)
        return

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer(_g("lead_already_marked", lang, lead_id=lead_id), show_alert=True)


# ----------------------------------------------------------------------
# 📍 Manzil va aloqa
# ----------------------------------------------------------------------


@router.message(F.chat.type == ChatType.PRIVATE, F.text.in_(CONTACT_TEXTS))
async def guest_contact_info(message: Message) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    lines = [_g("contact_header", lang), ""]
    has_info = False
    if config.CENTER_ADDRESS:
        lines.append(_g("contact_address", lang, value=html.escape(config.CENTER_ADDRESS)))
        has_info = True
    if config.CENTER_LANDMARK:
        lines.append(_g("contact_landmark", lang, value=html.escape(config.CENTER_LANDMARK)))
        has_info = True
    phones = [p for p in (config.CENTER_PHONE, config.CENTER_PHONE_2) if p]
    if phones:
        lines.append(_g("contact_phone", lang, value=", ".join(_tel_link(p) for p in phones)))
        has_info = True
    if config.CENTER_TELEGRAM:
        tg_val = config.CENTER_TELEGRAM.strip()
        uname = tg_val.rstrip("/").split("/")[-1].lstrip("@")
        lines.append(
            _g(
                "contact_telegram",
                lang,
                value=f'<a href="https://t.me/{html.escape(uname)}">@{html.escape(uname)}</a>',
            )
        )
        has_info = True
    if config.CENTER_INSTAGRAM:
        ig = config.CENTER_INSTAGRAM.strip().rstrip("/").split("/")[-1].lstrip("@")
        lines.append(
            _g(
                "contact_instagram",
                lang,
                value=f'<a href="https://instagram.com/{html.escape(ig)}">@{html.escape(ig)}</a>',
            )
        )
        has_info = True
    if config.CENTER_WORKING_HOURS:
        lines.append(_g("contact_hours", lang, value=html.escape(config.CENTER_WORKING_HOURS)))
        has_info = True
    if config.CENTER_MAP_URL:
        lines.append(_g("contact_map", lang, value=html.escape(config.CENTER_MAP_URL, quote=True)))
        has_info = True
    if not has_info:
        lines.append(_g("contact_missing", lang))
    await message.answer(
        "\n".join(lines) + _sig(lang),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    if config.CENTER_LATITUDE is not None and config.CENTER_LONGITUDE is not None:
        try:
            await message.answer_location(
                latitude=config.CENTER_LATITUDE, longitude=config.CENTER_LONGITUDE
            )
        except Exception as exc:
            logger.warning("Failed sending centre location: %s", exc)


# ----------------------------------------------------------------------
# Admin: 📚 Kurslarni boshqarish
# ----------------------------------------------------------------------


async def _render_admin_panel(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    courses = await get_courses(active_only=False)
    rows: list[list[InlineKeyboardButton]] = []
    for c in courses:
        mark = "🟢" if int(c.get("is_active") or 0) else "🔴"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {c['name']} — {_price_text(c, lang)}",
                    callback_data=f"crs_adm:view:{c['id']}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text=_g("adm_btn_add", lang), callback_data="crs_adm:add"),
            InlineKeyboardButton(text=_g("adm_btn_leads", lang), callback_data="crs_adm:leads"),
        ]
    )
    return _g("adm_panel", lang, total=len(courses)), InlineKeyboardMarkup(inline_keyboard=rows)


async def _edit_or_answer(
    message: Message, text: str, kb: Optional[InlineKeyboardMarkup], edit: bool
) -> None:
    if edit:
        try:
            await message.edit_text(
                text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True
            )
            return
        except Exception:
            pass
    await message.answer(text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True)


@router.message(F.chat.type == ChatType.PRIVATE, F.text.in_(ADMIN_COURSES_TEXTS))
async def admin_courses_menu(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    if not await _is_admin(message.from_user.id):
        await message.answer(_g("no_permission", lang))
        return
    await state.clear()
    text, kb = await _render_admin_panel(lang)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("crs_adm:"))
async def cb_admin_courses(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_g("no_permission", lang), show_alert=True)
        return
    parts = (callback.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    course_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0

    if action == "list":
        await state.clear()
        text, kb = await _render_admin_panel(lang)
        await _edit_or_answer(callback.message, text, kb, edit=True)
    elif action == "view" and course_id:
        await _show_admin_course(callback.message, course_id, lang, edit=True)
    elif action == "toggle" and course_id:
        course = await get_course(course_id)
        if course:
            await update_course(
                course_id, {"is_active": 0 if int(course.get("is_active") or 0) else 1}
            )
        await _show_admin_course(callback.message, course_id, lang, edit=True)
    elif action == "price" and course_id:
        await state.set_state(CourseManageStates.editing_price)
        await state.update_data(crs_edit_id=course_id)
        await callback.message.answer(
            _g("adm_enter_price", lang),
            reply_markup=_admin_cancel_kb(lang),
            parse_mode="HTML",
        )
    elif action == "del" and course_id:
        course = await get_course(course_id)
        if course:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=_g("adm_btn_delete_yes", lang),
                            callback_data=f"crs_adm:delyes:{course_id}",
                        ),
                        InlineKeyboardButton(
                            text=t("btn_cancel", lang),
                            callback_data=f"crs_adm:view:{course_id}",
                        ),
                    ]
                ]
            )
            await _edit_or_answer(
                callback.message,
                _g("adm_confirm_delete", lang, name=html.escape(course["name"])),
                kb,
                edit=True,
            )
    elif action == "delyes" and course_id:
        await delete_course(course_id)
        text, kb = await _render_admin_panel(lang)
        await _edit_or_answer(
            callback.message, f"{_g('adm_deleted', lang)}\n\n{text}", kb, edit=True
        )
    elif action == "add":
        await state.set_state(CourseManageStates.entering_name)
        await state.update_data(crs_new={})
        await callback.message.answer(
            _g("adm_enter_name", lang), reply_markup=_admin_cancel_kb(lang), parse_mode="HTML"
        )
    elif action == "cancel":
        await state.clear()
        text, kb = await _render_admin_panel(lang)
        await _edit_or_answer(callback.message, text, kb, edit=True)
    elif action == "leads":
        await _show_recent_leads(callback.message, lang)
    await callback.answer()


def _admin_cancel_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t("btn_cancel", lang), callback_data="crs_adm:cancel")]
        ]
    )


async def _show_admin_course(
    message: Message, course_id: int, lang: str, edit: bool = True, notice: str = ""
) -> None:
    course = await get_course(course_id)
    if not course:
        text, kb = await _render_admin_panel(lang)
        await _edit_or_answer(message, text, kb, edit)
        return
    is_active = bool(int(course.get("is_active") or 0))
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_g("adm_btn_price", lang), callback_data=f"crs_adm:price:{course_id}"
                ),
                InlineKeyboardButton(
                    text=_g("adm_btn_toggle_off" if is_active else "adm_btn_toggle_on", lang),
                    callback_data=f"crs_adm:toggle:{course_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=_g("adm_btn_delete", lang), callback_data=f"crs_adm:del:{course_id}"
                ),
                InlineKeyboardButton(text=_g("adm_btn_back", lang), callback_data="crs_adm:list"),
            ],
        ]
    )
    text = _g(
        "adm_course_admin_card",
        lang,
        card=_course_card(course, lang),
        status=_g("adm_status_on" if is_active else "adm_status_off", lang),
    )
    if notice:
        text = f"{notice}\n\n{text}"
    await _edit_or_answer(message, text, kb, edit)


async def _show_recent_leads(message: Message, lang: str) -> None:
    leads = await get_recent_leads(limit=15)
    if not leads:
        await message.answer(_g("adm_leads_empty", lang))
        return
    lines = [_g("adm_leads_header", lang), ""]
    for lead in leads:
        created = format_tashkent(lead.get("created_at"))
        status_key = (
            "lead_status_contacted" if lead.get("status") == "contacted" else "lead_status_new"
        )
        lines.append(
            _g(
                "adm_lead_item",
                lang,
                lead_id=lead.get("id"),
                name=html.escape(str(lead.get("full_name") or "")),
                phone_link=_tel_link(str(lead.get("phone") or "")),
                tg_link=_tg_link(lead.get("telegram_id"), str(lead.get("username") or "")),
                course=html.escape(str(lead.get("course_name") or "—")),
                date=html.escape(created),
                status=_g(status_key, lang),
            )
        )
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\n…"
    await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)


@router.message(CourseManageStates.editing_price)
async def msg_admin_course_price(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return
    digits = re.sub(r"[\s,._]", "", (message.text or "").strip())
    if not digits.isdigit():
        await message.answer(_g("adm_invalid_price", lang), reply_markup=_admin_cancel_kb(lang))
        return
    amount = int(digits)
    if 0 < amount < 10000:
        amount *= 1000
    course_id = int((await state.get_data()).get("crs_edit_id") or 0)
    await state.clear()
    if course_id:
        await update_course(course_id, {"price": amount})
        await _show_admin_course(
            message, course_id, lang, edit=False, notice=_g("adm_price_saved", lang)
        )


@router.message(CourseManageStates.entering_name)
async def msg_admin_course_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return
    name = " ".join((message.text or "").split())
    if not name or name.startswith("/") or len(name) > 80:
        await message.answer(_g("adm_enter_name", lang), reply_markup=_admin_cancel_kb(lang), parse_mode="HTML")
        return
    await state.update_data(crs_name=name)
    await state.set_state(CourseManageStates.entering_description)
    await message.answer(_g("adm_enter_desc", lang), reply_markup=_admin_cancel_kb(lang))


@router.message(CourseManageStates.entering_description)
async def msg_admin_course_desc(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return
    await state.update_data(crs_desc=(message.text or "").strip()[:900])
    await state.set_state(CourseManageStates.entering_price)
    await message.answer(
        _g("adm_enter_price", lang), reply_markup=_admin_cancel_kb(lang), parse_mode="HTML"
    )


@router.message(CourseManageStates.entering_price)
async def msg_admin_course_new_price(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return
    digits = re.sub(r"[\s,._]", "", (message.text or "").strip())
    if not digits.isdigit():
        await message.answer(_g("adm_invalid_price", lang), reply_markup=_admin_cancel_kb(lang))
        return
    amount = int(digits)
    if 0 < amount < 10000:
        amount *= 1000
    await state.update_data(crs_price=amount)
    await state.set_state(CourseManageStates.entering_duration)
    await message.answer(
        _g("adm_enter_duration", lang), reply_markup=_admin_cancel_kb(lang), parse_mode="HTML"
    )


@router.message(CourseManageStates.entering_duration)
async def msg_admin_course_duration(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return
    raw = (message.text or "").strip()
    duration, _, schedule = raw.partition("|")
    data = await state.get_data()
    await state.clear()
    course = await add_course(
        name=str(data.get("crs_name") or ""),
        description=str(data.get("crs_desc") or ""),
        price=int(data.get("crs_price") or 0),
        duration=duration.strip()[:80],
        schedule=schedule.strip()[:80],
    )
    if course.get("id"):
        await _show_admin_course(
            message, int(course["id"]), lang, edit=False, notice=_g("adm_saved", lang)
        )
