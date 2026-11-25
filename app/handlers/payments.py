import asyncio
import html
import logging
import os
import re
import uuid
from datetime import date, datetime
from typing import Any, Optional

import aiosqlite
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app import config
from app.utils import dual_role_header, now_tashkent
from app.config import ADMIN_IDS, DB_PATH, TZ
from app.database import (
    get_cycle_overrides_sync,
    AUDIT_PAYMENT_CONFIRMED,
    AUDIT_PAYMENT_REVERTED,
    get_legacy_debts,
    log_audit_event,
    get_unpaid_legacy_debts_map,
    get_notification_details,
    get_pending_action,
    get_teacher_by_telegram_id,
    get_user,
    get_user_lang,
    has_dual_student_parent_role,
    save_notification_details,
    update_pending_action_status,
)
from app.debt_view import (
    build_debt_notice,
    compute_children_debts,
    format_admin_extra_lines,
    load_group_fees,
    send_expandable_notice,
)
from app.debt_view import _dt as debt_text
from app.debt_view import format_uzs as debt_format_uzs
from app.keyboards import (
    InlineKeyboardBuilder,
    build_expandable_notif_kb,
    groups_inline_kb,
    payment_confirm_kb,
    student_payment_detail_kb,
    students_list_kb,
)
from app.locales import (
    button_texts,
    format_human_cycle_title,
    format_lesson_line,
    format_next_payment_info,
    format_uz_date,
    t,
)
from app.sheets import SheetsManager, _is_paid_status, get_sheets_manager
from app.states import PaymentStates

logger = logging.getLogger(__name__)

router = Router(name="payments")

PAYMENT_CONFIRM_MENU_TEXTS = button_texts(
    "menu_admin_payments", "menu_teacher_payments"
)

STUDENT_PARENT_PAYMENTS_TEXTS = button_texts(
    "menu_student_payments", "menu_parent_payments"
)

DEBTORS_MENU_TEXTS = button_texts("menu_admin_debtors", "menu_teacher_debtors")

LOCAL_TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "fee_summary_line": "💰 Guruh oylik to‘lovi: <b>{fee} so‘m</b>",
        "cycle_fee_line": "💰 To‘lov summasi: <b>{fee} so‘m</b>",
        "debt_summary_line": (
            "⚠️ Jami qarzdorlik: <b>{months} oy × {fee} = {total} so‘m</b>\n"
            "🗓 Qarzdor sikllar: <i>{cycles}</i>"
        ),
        "debtor_amount_part": "💰 <b>{months} oy × {fee} = {total} so‘m</b>",
        "debtors_grand_total": (
            "\n━━━━━━━━━━━━━━\n"
            "👥 Jami qarzdorlar: <b>{count} ta</b>\n"
            "💵 Umumiy qarz summasi: <b>{total} so‘m</b>"
        ),
        "btn_remind_debtors": "📢 Eslatma yuborish",
        "btn_debtors_compact": "🔼 Qisqacha",
        "btn_debtors_detailed": "📄 Batafsil",
        "debtor_compact_line": (
            "• <b>{name}</b> ({group})\n"
            "  📞 {phone} | 💰 <b>{total} so'm</b>"
        ),
        "debtor_unpaid_cycle_line": "  🗓 <b>{cycle}</b>: {lessons}",
        "debtor_dates_copy_line": "  📋 Sanalar: <code>{dates}</code>",
        "parent_child_payment_block": (
            "👶 Farzand: <b>{child_fio}</b>\n"
            "📚 Guruh: <b>{group_name}</b>\n"
            "💵 Oylik to'lov: <b>{monthly_fee} so'm</b>\n"
            "📊 Holati: <b>{status_text}</b>\n"
            "❗️ Qarzdorlik: <b>{child_debt} so'm ({debt_months} oy)</b>"
        ),
        "parent_total_debt_footer": (
            "━━━━━━━━━━━━━━\n"
            "💰 Barcha farzandlar bo'yicha umumiy qarzdorlik: <b>{total_debt} so'm</b>\n\n"
            "💳 To‘lov uchun karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "reminder_student": (
            "🔔 <b>To‘lov eslatmasi</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 Qarzdor oylar: <b>{cycles}</b>\n"
            "💰 Qarzdorlik summasi: <b>{months} oy × {fee} = {total} so‘m</b>\n\n"
            "To‘lovni o‘z vaqtida amalga oshirishingizni so‘raymiz.\n\n"
            "💳 Karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "reminder_parent_same_group": (
            "🔔 <b>To‘lov eslatmasi</b>\n\n"
            "📚 Guruh: <b>{group}</b> (Oylik to‘lov: <b>{fee} so‘m</b>)\n\n"
            "👨‍👩‍👧‍👦 <b>Farzandlaringiz ({child_count} nafar):</b>\n{children_lines}\n\n"
            "💰 <b>Jami qarzdorlik: {total} so‘m</b>\n\n"
            "To‘lovni o‘z vaqtida amalga oshirishingizni so‘raymiz.\n\n"
            "💳 Karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "reminder_parent_multi_group": (
            "🔔 <b>Umumiy to‘lov eslatmasi</b>\n\n"
            "{groups_blocks}\n\n"
            "━━━━━━━━━━━━━━\n"
            "💵 <b>Umumiy jami qarzdorlik: {grand_total} so‘m</b>\n\n"
            "To‘lovni o‘z vaqtida amalga oshirishingizni so‘raymiz.\n\n"
            "💳 Karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "reminder_sent_report_short": (
            "✅ <b>Qarzdorlik eslatmasi yuborildi!</b>\n\n"
            "🎓 Talabalarga yuborildi: <b>{stu_sent} ta</b>\n"
            "👨‍👩‍👧 Ota-onalarga yuborildi: <b>{par_sent} ta</b>\n"
            "📨 Jami xabarlar: <b>{total_sent} ta</b>\n\n"
            "<i>Batafsil ro‘yxat va aloqa havolalarini ko‘rish uchun pastdagi tugmani bosing.</i>"
        ),
        "reminder_sent_report_detailed": (
            "✅ <b>Qarzdorlik eslatmasi hisoboti (Batafsil)</b>\n\n"
            "🎓 Talabalar: <b>{stu_sent} ta</b> | 👨‍👩‍👧 Ota-onalar: <b>{par_sent} ta</b>\n\n"
            "🎓 <b>Xabar yuborilgan talabalar:</b>\n{student_lines}\n\n"
            "👨‍👩‍👧 <b>Xabar yuborilgan ota-onalar:</b>\n{parent_lines}"
        ),
        "payment_confirmed_instant_admin": (
            "✅ <b>To‘lov tasdiqlandi va jadval yashil rangga bo‘yaldi!</b>\n\n"
            "👤 Talaba: <b>{student_name}</b> ({group})\n"
            "🗓 O‘quv oyi: <b>{cycle_title}</b>"
        ),
        "signature_center": "\n\nHurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!",
    },
    "cyrl": {
        "fee_summary_line": "💰 Гуруҳ ойлик тўлови: <b>{fee} сўм</b>",
        "cycle_fee_line": "💰 Тўлов суммаси: <b>{fee} сўм</b>",
        "debt_summary_line": (
            "⚠️ Жами қарздорлик: <b>{months} ой × {fee} = {total} сўм</b>\n"
            "🗓 Қарздор сикллар: <i>{cycles}</i>"
        ),
        "debtor_amount_part": "💰 <b>{months} ой × {fee} = {total} сўм</b>",
        "debtors_grand_total": (
            "\n━━━━━━━━━━━━━━\n"
            "👥 Жами қарздорлар: <b>{count} та</b>\n"
            "💵 Умумий қарз суммаси: <b>{total} сўм</b>"
        ),
        "btn_remind_debtors": "📢 Эслатма юбориш",
        "btn_debtors_compact": "🔼 Қисқача",
        "btn_debtors_detailed": "📄 Батафсил",
        "debtor_compact_line": (
            "• <b>{name}</b> ({group})\n"
            "  📞 {phone} | 💰 <b>{total} сўм</b>"
        ),
        "debtor_unpaid_cycle_line": "  🗓 <b>{cycle}</b>: {lessons}",
        "debtor_dates_copy_line": "  📋 Саналар: <code>{dates}</code>",
        "parent_child_payment_block": (
            "👶 Фарзанд: <b>{child_fio}</b>\n"
            "📚 Гуруҳ: <b>{group_name}</b>\n"
            "💵 Ойлик тўлов: <b>{monthly_fee} сўм</b>\n"
            "📊 Ҳолати: <b>{status_text}</b>\n"
            "❗️ Қарздорлик: <b>{child_debt} сўм ({debt_months} ой)</b>"
        ),
        "parent_total_debt_footer": (
            "━━━━━━━━━━━━━━\n"
            "💰 Барча фарзандлар бўйича умумий қарздорлик: <b>{total_debt} сўм</b>\n\n"
            "💳 Тўлов учун карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "reminder_student": (
            "🔔 <b>Тўлов эслатмаси</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Қарздор ойлар: <b>{cycles}</b>\n"
            "💰 Қарздорлик суммаси: <b>{months} ой × {fee} = {total} сўм</b>\n\n"
            "Тўловни ўз вақтида амалга оширишингизни сўраймиз.\n\n"
            "💳 Карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "reminder_parent_same_group": (
            "🔔 <b>Тўлов эслатмаси</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b> (Ойлик тўлов: <b>{fee} сўм</b>)\n\n"
            "👨‍👩‍👧‍👦 <b>Фарзандларингиз ({child_count} нафар):</b>\n{children_lines}\n\n"
            "💰 <b>Жами қарздорлик: {total} сўм</b>\n\n"
            "Тўловни ўз вақтида амалга оширишингизни сўраймиз.\n\n"
            "💳 Карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "reminder_parent_multi_group": (
            "🔔 <b>Умумий тўлов эслатмаси</b>\n\n"
            "{groups_blocks}\n\n"
            "━━━━━━━━━━━━━━\n"
            "💵 <b>Умумий жами қарздорлик: {grand_total} сўм</b>\n\n"
            "Тўловни ўз вақтида амалга оширишингизни сўраймиз.\n\n"
            "💳 Карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "reminder_sent_report_short": (
            "✅ <b>Қарздорлик эслатмаси юборилди!</b>\n\n"
            "🎓 Талабаларга юборилди: <b>{stu_sent} та</b>\n"
            "👨‍👩‍👧 Ота-оналарга юборилди: <b>{par_sent} та</b>\n"
            "📨 Жами хабарлар: <b>{total_sent} та</b>\n\n"
            "<i>Батафсил рўйхат ва алоқа ҳаволаларини кўриш учун пастдаги тугмани босинг.</i>"
        ),
        "reminder_sent_report_detailed": (
            "✅ <b>Қарздорлик эслатмаси ҳисоботи (Батафсил)</b>\n\n"
            "🎓 Талабалар: <b>{stu_sent} та</b> | 👨‍👩‍👧 Ота-оналар: <b>{par_sent} та</b>\n\n"
            "🎓 <b>Хабар юборилган талабалар:</b>\n{student_lines}\n\n"
            "👨‍👩‍👧 <b>Хабар юборилган ота-оналар:</b>\n{parent_lines}"
        ),
        "payment_confirmed_instant_admin": (
            "✅ <b>Тўлов тасдиқланди ва жадвал яшил рангга бўялди!</b>\n\n"
            "👤 Талаба: <b>{student_name}</b> ({group})\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>"
        ),
        "signature_center": "\n\nҲурмат билан,\nМишкат Нодавлат Таълим Муассасаси!",
    },
}


def _lt(key: str, lang: str = "latn", **kwargs: Any) -> str:
    safe_lang = lang if lang in LOCAL_TEXTS else "latn"
    template = LOCAL_TEXTS[safe_lang].get(key) or LOCAL_TEXTS["latn"].get(key, key)
    return template.format(**kwargs) if kwargs else template


def _parse_chat_id(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if val != 0 else None
    if isinstance(val, float):
        try:
            int_val = int(val)
            return int_val if int_val != 0 and float(int_val) == val else None
        except (ValueError, OverflowError):
            return None
    cleaned = str(val).strip()
    if not cleaned or cleaned == "Ma'lumot kiritilmagan":
        return None
    if re.fullmatch(r"-?\d+(?:\.0+)?", cleaned):
        int_val = int(cleaned.split(".", 1)[0])
        return int_val if int_val != 0 else None
    return None


def _normalize_phone_key(phone: Any) -> str:
    cleaned = str(phone or "").strip()
    if not cleaned or cleaned in {"Ma'lumot kiritilmagan", "Yo'q", "yo'q", "yoq", "—", "-"}:
        return ""
    digits = re.sub(r"\D", "", cleaned)
    if not digits or len(digits) < 7:
        return ""
    if len(digits) == 9:
        return f"998{digits}"
    if len(digits) == 12 and digits.startswith("998"):
        return digits
    return digits


def _get_default_monthly_fee() -> int:
    cfg_val = getattr(config, "DEFAULT_MONTHLY_FEE", None)
    if cfg_val is not None and str(cfg_val).strip() != "":
        cleaned = re.sub(r"[^\d]", "", str(cfg_val).strip())
        if cleaned:
            return int(cleaned)
    env_val = os.getenv("DEFAULT_MONTHLY_FEE", "").strip()
    if env_val:
        cleaned = re.sub(r"[^\d]", "", env_val)
        if cleaned:
            return int(cleaned)
    return 500000


def _parse_group_fee(group: Optional[dict[str, Any]]) -> int:
    if group:
        raw = str(group.get("Oylik_Tolov_Summa", "")).strip()
        if raw:
            cleaned = re.sub(r"[^\d]", "", raw)
            if cleaned:
                val = int(cleaned)
                if val > 0:
                    return val
    return _get_default_monthly_fee()


def _format_uzs(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def _count_debt_months(debt_raw: str) -> int:
    cleaned = str(debt_raw or "").strip()
    if not cleaned or cleaned == "0":
        return 0
    if cleaned.isdigit():
        return int(cleaned)
    items = [
        x.strip()
        for x in cleaned.split(";")
        if x.strip() and x.strip() != "0"
    ]
    return len(items)


def _format_lesson_attendance_stats(
    held: int, attended: int, missed: int, lang: str
) -> str:
    if lang == "cyrl":
        return (
            f"📊 <b>{held}</b> та ўтилган дарс: "
            f"<b>{attended}</b> та келган, <b>{missed}</b> та келмаган"
        )
    return (
        f"📊 <b>{held}</b> ta o'tilgan dars: "
        f"<b>{attended}</b> ta kelgan, <b>{missed}</b> ta kelmagan"
    )


async def _resolve_debtor_stats(
    sheets: SheetsManager, debtor: dict[str, Any], group_name: str
) -> dict[str, Any]:
    if (
        "total_held_lessons" in debtor
        and "attended_lessons" in debtor
        and "missed_lessons" in debtor
    ):
        return {
            "total_held_lessons": int(debtor.get("total_held_lessons") or 0),
            "attended_lessons": int(debtor.get("attended_lessons") or 0),
            "missed_lessons": int(debtor.get("missed_lessons") or 0),
            "cycle_title": str(debtor.get("cycle_title") or ""),
        }
    return await asyncio.to_thread(
        sheets.get_student_cycle_lesson_stats,
        group_name,
        str(debtor.get("Talaba_ID", "")).strip(),
        str(debtor.get("F.I.O.", "")).strip(),
    )


def _get_payment_card_info() -> tuple[str, str]:
    card_number = (
        getattr(config, "PAYMENT_CARD_NUMBER", None)
        or getattr(config, "CARD_NUMBER", None)
        or os.getenv("PAYMENT_CARD_NUMBER", "").strip()
        or os.getenv("CARD_NUMBER", "").strip()
        or "—"
    )
    card_owner = (
        getattr(config, "PAYMENT_CARD_OWNER", None)
        or getattr(config, "CARD_OWNER", None)
        or os.getenv("PAYMENT_CARD_OWNER", "").strip()
        or os.getenv("CARD_OWNER", "").strip()
        or "—"
    )
    return str(card_number).strip(), str(card_owner).strip()


def _normalize_phone(raw_phone: str) -> str:
    cleaned = str(raw_phone or "").strip()
    if not cleaned:
        return ""
    compact = re.sub(r"[^\d+]", "", cleaned)
    if re.fullmatch(r"\d{9}", compact):
        return f"+998{compact}"
    if re.fullmatch(r"998\d{9}", compact):
        return f"+{compact}"
    if compact and not compact.startswith("+") and len(compact) >= 7:
        return f"+{compact}"
    return compact


def _format_tel_link(raw_phone: str) -> str:
    cleaned = str(raw_phone or "").strip()
    if not cleaned or cleaned == "—":
        return "—"
    norm = _normalize_phone(cleaned)
    if not norm or not any(ch.isdigit() for ch in norm):
        return html.escape(cleaned)
    safe_norm = html.escape(norm)
    return f'<a href="tel:{safe_norm}">{safe_norm}</a>'


def _format_tg_link(
    raw_tg: str = "", chat_id: Any = None, fallback_label: str = "Telegram"
) -> str:
    cid_int = _parse_chat_id(chat_id)
    cid_str = str(cid_int) if cid_int is not None else ""
    cleaned_tg = str(raw_tg or "").strip()
    if cleaned_tg.startswith(("https://t.me/", "http://t.me/", "t.me/")):
        username = cleaned_tg.rstrip("/").split("/")[-1].lstrip("@")
    else:
        username = cleaned_tg.lstrip("@")
    valid_username = bool(re.fullmatch(r"[A-Za-z0-9_]{3,}", username))

    if cid_int is not None and cid_int > 0:
        label = f"@{username}" if valid_username else fallback_label
        return f'<a href="tg://user?id={cid_str}">{html.escape(label)}</a>'
    if valid_username:
        safe_u = html.escape(username)
        return f'<a href="https://t.me/{safe_u}">@{safe_u}</a>'
    return "—"


def _safe_truncate_html_lines(text: str, limit: int = 3950) -> str:
    if len(text) <= limit:
        return text
    out_lines: list[str] = []
    cur_len = 0
    for line in text.split("\n"):
        add_len = len(line) + (1 if out_lines else 0)
        if cur_len + add_len > limit - 4:
            break
        out_lines.append(line)
        cur_len += add_len
    return "\n".join(out_lines) + "\n..."


def _debt_report_toggle_kb(
    notif_id: str, is_detailed: bool, lang: str
) -> InlineKeyboardMarkup:
    btn_text = t("btn_short", lang) if is_detailed else t("btn_detailed", lang)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=btn_text,
                    callback_data=f"debt_rep_toggle:{notif_id}:{int(not is_detailed)}",
                )
            ]
        ]
    )


async def _is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    db_user = await get_user(user_id)
    if db_user and db_user.get("role") == "admin":
        return True
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM dynamic_admins WHERE telegram_id = ?;",
                (user_id,),
            ) as cur:
                if await cur.fetchone():
                    return True
    except Exception:
        pass
    return False


async def _resolve_actor_teacher_name(
    user_id: int, group: Optional[dict[str, Any]]
) -> str:
    db_tch = await get_teacher_by_telegram_id(user_id)
    if db_tch and db_tch.get("full_name"):
        return str(db_tch["full_name"]).strip()
    sheets = get_sheets_manager()
    try:
        sheet_tch = await sheets.a_get_teacher_by_chat_id(user_id)
        if sheet_tch and sheet_tch.get("F.I.O."):
            fio = str(sheet_tch["F.I.O."]).strip()
            if fio and fio != "Ma'lumot kiritilmagan":
                return fio
    except Exception:
        pass
    db_usr = await get_user(user_id)
    if db_usr and db_usr.get("full_name"):
        return str(db_usr["full_name"]).strip()
    if group and group.get("Ustoz_FIO"):
        return str(group["Ustoz_FIO"]).strip()
    return str(user_id)


async def _get_authorized_groups(user_id: int) -> tuple[bool, list[dict[str, Any]]]:
    sheets = get_sheets_manager()
    if await _is_admin(user_id):
        groups = await asyncio.to_thread(sheets.get_all_groups)
        return True, groups
    raw_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
    teacher_groups = [
        g
        for g in raw_groups
        if str(g.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
    ]
    if teacher_groups:
        return True, teacher_groups
    return False, []


async def _can_manage_group(user_id: int, group_name: str) -> bool:
    if await _is_admin(user_id):
        return True
    sheets = get_sheets_manager()
    teacher_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
    target = group_name.strip().lower()
    return any(
        g.get("Guruh_Nomi", "").strip().lower() == target
        and str(g.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
        for g in teacher_groups
    )


def _enrich_cycle_with_weekdays(
    cycle: dict[str, Any], base_year: int
) -> dict[str, Any]:
    lessons = cycle.get("lessons", [])
    running_year = base_year
    prev_month: Optional[int] = None
    enriched_lessons: list[dict[str, Any]] = []

    for idx, lesson in enumerate(lessons, start=1):
        d_str = str(lesson.get("date", "")).strip()
        weekday_idx: Optional[int] = None
        try:
            day_val, month_val = map(int, d_str.split("."))
            if prev_month is not None and month_val < prev_month:
                running_year += 1
            prev_month = month_val
            weekday_idx = date(running_year, month_val, day_val).weekday()
        except ValueError:
            weekday_idx = None

        enriched_lessons.append(
            {
                "lesson_num": idx,
                "date": d_str,
                "mark": lesson.get("mark", "⏳"),
                "weekday_idx": weekday_idx,
            }
        )

    enriched = dict(cycle)
    enriched["enriched_lessons"] = enriched_lessons
    enriched["lesson_count"] = len(enriched_lessons)
    return enriched


def _fetch_full_cycle_history_sync(
    group_name: str, student_id: str
) -> list[dict[str, Any]]:
    sheets = get_sheets_manager()
    current_year = now_tashkent().year
    cycles: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    for yr in (current_year - 1, current_year):
        yr_cycles = sheets.get_student_cycle_history(group_name, student_id, year=yr)
        for c in yr_cycles:
            title = c["cycle_title"]
            if title not in seen_titles:
                seen_titles.add(title)
                cycles.append(_enrich_cycle_with_weekdays(c, yr))

    # Prorated ("🆕 Bugundan qo‘shildi") cycles of this student in this group.
    group_key = group_name.strip().lower()
    overrides_by_title = {
        o["cycle_title"]: {
            "remaining_lessons": o["remaining_lessons"],
            "custom_amount": o["custom_amount"],
        }
        for o in get_cycle_overrides_sync(student_id)
        if o["group_name"] == group_key
    }
    for cyc in cycles:
        cyc["student_overrides"] = overrides_by_title
        ov = overrides_by_title.get(str(cyc.get("cycle_title") or "").strip())
        if ov:
            cyc["prorated_remaining"] = ov["remaining_lessons"]
            cyc["prorated_amount"] = ov["custom_amount"]
    return cycles


def _debt_sum_with_overrides(
    debt_raw: str, fee: int, overrides_by_title: Optional[dict[str, Any]]
) -> int:
    """Debt total: prorated cycles at their custom amount, every other at full fee."""
    months = _count_debt_months(debt_raw)
    titles = {
        x.strip()
        for x in str(debt_raw or "").split(";")
        if x.strip() and x.strip() != "0" and not x.strip().isdigit()
    }
    prorated = [
        v for k, v in (overrides_by_title or {}).items() if k in titles
    ][: max(months, 0)]
    return (max(months, 0) - len(prorated)) * int(fee) + sum(
        int(v.get("custom_amount") or 0) for v in prorated
    )


def _format_cycle_display_title(cycle: dict[str, Any], lang: str) -> str:
    num = int(cycle.get("cycle_number") or 1)
    count = int(cycle.get("lesson_count") or len(cycle.get("lessons", [])) or 12)
    if cycle.get("prorated_remaining"):
        human = t(
            "human_cycle_label_prorated",
            lang,
            num=num,
            remaining=int(cycle["prorated_remaining"]),
        )
    else:
        human = format_human_cycle_title(num, count, lang)
    raw_title = cycle.get("cycle_title", "")
    return f"{human} — {raw_title}" if raw_title else human


def _compute_next_payment_info(cycle: dict[str, Any], lang: str) -> str:
    lessons = cycle.get("enriched_lessons") or cycle.get("lessons") or []
    total_lessons = len(lessons) or int(cycle.get("lesson_count") or 12)
    last_date = (
        lessons[-1].get("date", "") if lessons else cycle.get("end_date", "")
    )
    last_date_fmt = format_uz_date(last_date, lang) if last_date else "-"
    return format_next_payment_info(total_lessons, last_date_fmt or "-", lang)


def _build_lessons_lines(cycle: dict[str, Any], lang: str) -> str:
    enriched = cycle.get("enriched_lessons")
    if not enriched:
        enriched = _enrich_cycle_with_weekdays(
            cycle, now_tashkent().year
        ).get("enriched_lessons", [])
    if not enriched:
        return "—"
    return "\n".join(
        format_lesson_line(
            lesson_num=item["lesson_num"],
            date_str=format_uz_date(item["date"], lang),
            weekday_idx=item.get("weekday_idx"),
            mark=item["mark"],
            lang=lang,
        )
        for item in enriched
    )


def _cycles_selection_kb(
    cycles: list[dict[str, Any]], lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for idx, c in enumerate(cycles):
        icon = "✅" if c["is_paid"] else "❌"
        builder.button(
            text=f"{icon} {_format_cycle_display_title(c, lang)}",
            callback_data=f"pay_cyc:{idx}",
        )
    builder.adjust(2)
    builder.row(
        InlineKeyboardButton(text=t("btn_back", lang), callback_data="pay_cyc:__back__"),
        InlineKeyboardButton(
            text=t("btn_cancel", lang), callback_data="pay_cyc:__cancel__"
        ),
    )
    return builder.as_markup()


def _format_teacher_payment_text(
    student_name: str,
    group_name: str,
    cycle: dict[str, Any],
    is_detailed: bool,
    lang: str,
    monthly_fee: Optional[int] = None,
    debt_raw: str = "",
) -> str:
    payment_status = (
        t("status_paid", lang) if cycle["is_paid"] else t("status_unpaid", lang)
    )
    card_number, card_owner = _get_payment_card_info()
    cycle_display = _format_cycle_display_title(cycle, lang)
    next_payment_info = _compute_next_payment_info(cycle, lang)
    fee = monthly_fee if monthly_fee is not None else _get_default_monthly_fee()
    fee_fmt = _format_uzs(fee)
    debt_count = _count_debt_months(debt_raw)
    debt_total = _debt_sum_with_overrides(
        debt_raw, fee, cycle.get("student_overrides")
    )

    fee_lines = _lt("fee_summary_line", lang, fee=fee_fmt)
    if cycle.get("prorated_amount") and not cycle["is_paid"]:
        fee_lines += "\n" + _lt(
            "cycle_fee_line", lang, fee=_format_uzs(int(cycle["prorated_amount"]))
        )
    if debt_count > 0:
        fee_lines += "\n" + _lt(
            "debt_summary_line",
            lang,
            months=debt_count,
            fee=fee_fmt,
            total=_format_uzs(debt_total),
            cycles=html.escape(debt_raw),
        )

    if not is_detailed:
        base = t(
            "payment_summary_compact",
            lang,
            student_name=html.escape(student_name),
            group=html.escape(group_name),
            cycle_title=html.escape(cycle_display),
            next_payment_info=html.escape(next_payment_info),
            payment_status=payment_status,
            card_number=html.escape(card_number),
            card_owner=html.escape(card_owner),
        )
        return f"{base}\n\n{fee_lines}"

    dates_lines = _build_lessons_lines(cycle, lang)
    start_uz = format_uz_date(cycle.get("start_date", ""), lang)
    end_uz = format_uz_date(cycle.get("end_date", ""), lang)
    detailed_base = t(
        "payment_summary_detailed",
        lang,
        student_name=html.escape(student_name),
        group=html.escape(group_name),
        cycle_title=html.escape(cycle_display),
        start_date=html.escape(start_uz or "—"),
        end_date=html.escape(end_uz or "—"),
        next_payment_info=html.escape(next_payment_info),
        present_count=cycle.get("present_count", 0),
        absent_count=cycle.get("absent_count", 0),
        payment_status=payment_status,
        dates_lines=dates_lines,
        card_number=html.escape(card_number),
        card_owner=html.escape(card_owner),
    )
    return f"{detailed_base}\n\n{fee_lines}"


def _get_student_cycle_status_label(
    cycle: dict[str, Any],
    debt_titles: set[str],
    lang: str,
) -> str:
    if cycle["is_paid"]:
        return t("status_paid", lang)
    lessons = cycle.get("lessons", [])
    all_marked = bool(lessons) and all(
        lesson.get("mark") in {"✅", "❌"} for lesson in lessons
    )
    if cycle["cycle_title"] in debt_titles or all_marked:
        return t("status_unpaid", lang)
    return t("status_active_cycle", lang)


def _format_student_cycle_text(
    cycle: dict[str, Any],
    status_label: str,
    is_detailed: bool,
    lang: str,
    monthly_fee: Optional[int] = None,
    debt_raw: str = "",
) -> str:
    cycle_display = _format_cycle_display_title(cycle, lang)
    next_payment_info = _compute_next_payment_info(cycle, lang)
    fee = monthly_fee if monthly_fee is not None else _get_default_monthly_fee()
    cycle_fee = int(cycle.get("prorated_amount") or fee)
    fee_fmt = _format_uzs(cycle_fee)
    debt_count = _count_debt_months(debt_raw)
    debt_total = _debt_sum_with_overrides(
        debt_raw, fee, cycle.get("student_overrides")
    )

    if not is_detailed:
        compact_text = t(
            "student_payment_cycle_compact",
            lang,
            cycle_title=html.escape(cycle_display),
            next_payment_info=html.escape(next_payment_info),
            status_label=status_label,
        )
        if not cycle["is_paid"]:
            compact_text = f"{compact_text}\n{_lt('cycle_fee_line', lang, fee=fee_fmt)}"
        return compact_text

    card_number, card_owner = _get_payment_card_info()
    dates_lines = _build_lessons_lines(cycle, lang)
    start_uz = format_uz_date(cycle.get("start_date", ""), lang)
    end_uz = format_uz_date(cycle.get("end_date", ""), lang)
    body = t(
        "student_payment_cycle_detailed",
        lang,
        cycle_title=html.escape(cycle_display),
        start_date=html.escape(start_uz or "—"),
        end_date=html.escape(end_uz or "—"),
        next_payment_info=html.escape(next_payment_info),
        present_count=cycle.get("present_count", 0),
        absent_count=cycle.get("absent_count", 0),
        status_label=status_label,
        dates_lines=dates_lines,
    )
    fee_block = _lt("cycle_fee_line", lang, fee=fee_fmt)
    if debt_count > 0:
        fee_block += "\n" + _lt(
            "debt_summary_line",
            lang,
            months=debt_count,
            fee=_format_uzs(fee),
            total=_format_uzs(debt_total),
            cycles=html.escape(debt_raw),
        )
    card_block = t(
        "payment_card_block",
        lang,
        card_number=html.escape(card_number),
        card_owner=html.escape(card_owner),
    )
    return f"{body}\n\n{fee_block}\n\n{card_block}"


def _build_parent_payment_context_lines(
    target_student: dict[str, Any],
    group_name: str,
    monthly_fee: int,
    parent_cid: int,
    all_students: list[dict[str, Any]],
    group_fees: dict[str, int],
    default_fee: int,
    is_confirm: bool,
    lang: str,
    legacy_rows: Optional[list[dict[str, Any]]] = None,
    paid_amount: Optional[int] = None,
    overrides_by_title: Optional[dict[str, Any]] = None,
) -> str:
    """
    Real-time payment context for a parent. It names ONLY the specific child
    whose payment was confirmed/reverted (siblings are never listed or marked
    as paid) and shows that child's remaining debt (current cycles + legacy).
    """
    stu_name = str(target_student.get("F.I.O.") or target_student.get("Talaba_ID") or "").strip()
    fee_fmt = _format_uzs(monthly_fee)
    shown_amount_fmt = _format_uzs(
        int(paid_amount) if paid_amount is not None else monthly_fee
    )

    if lang == "cyrl":
        amount_label = "Тасдиқланган сумма" if is_confirm else "Янгиланган сумма"
        lines = [
            f"👦 <b>Фарзандингиз {html.escape(stu_name)}</b> ({html.escape(group_name)})",
            f"💰 {amount_label}: <b>{shown_amount_fmt} сўм</b>",
        ]
    else:
        amount_label = "Tasdiqlangan summa" if is_confirm else "Yangilangan summa"
        lines = [
            f"👦 <b>Farzandingiz {html.escape(stu_name)}</b> ({html.escape(group_name)})",
            f"💰 {amount_label}: <b>{shown_amount_fmt} so‘m</b>",
        ]

    debt_months = _count_debt_months(str(target_student.get("Qarzdor_Oylar") or "").strip())
    rem_sum = _debt_sum_with_overrides(
        str(target_student.get("Qarzdor_Oylar") or "").strip(),
        monthly_fee,
        overrides_by_title,
    )
    legacy_list = list(legacy_rows or [])
    legacy_months = sum(max(1, int(r.get("months") or 1)) for r in legacy_list)
    legacy_sum = sum(max(0, int(r.get("amount") or 0)) for r in legacy_list)
    total_months = debt_months + legacy_months
    total_sum = rem_sum + legacy_sum

    if lang == "cyrl":
        if total_months <= 0:
            lines.append(
                f"✅ <b>{html.escape(stu_name)}</b> бўйича қолган қарздорлик: <b>0 сўм</b>"
            )
        else:
            lines.append(
                f"⚠️ <b>{html.escape(stu_name)}</b> бўйича қолган қарздорлик: "
                f"<b>{total_months} ой — {_format_uzs(total_sum)} сўм</b>"
            )
            if legacy_sum:
                lines.append(
                    f"   (жорий: {debt_months} ой × {fee_fmt} = {_format_uzs(rem_sum)} сўм; "
                    f"аввалги қарз: {legacy_months} ой — {_format_uzs(legacy_sum)} сўм)"
                )
    else:
        if total_months <= 0:
            lines.append(
                f"✅ <b>{html.escape(stu_name)}</b> bo‘yicha qolgan qarzdorlik: <b>0 so‘m</b>"
            )
        else:
            lines.append(
                f"⚠️ <b>{html.escape(stu_name)}</b> bo‘yicha qolgan qarzdorlik: "
                f"<b>{total_months} oy — {_format_uzs(total_sum)} so‘m</b>"
            )
            if legacy_sum:
                lines.append(
                    f"   (joriy: {debt_months} oy × {fee_fmt} = {_format_uzs(rem_sum)} so‘m; "
                    f"avvalgi qarz: {legacy_months} oy — {_format_uzs(legacy_sum)} so‘m)"
                )
    return "\n".join(lines)


async def _notify_admins_delivery_failure(
    bot: Any,
    actor_user_id: int,
    student_name: str,
    group_name: str,
    failed_parents: list[tuple[int, str]],
) -> None:
    if not failed_parents:
        return
    recipients: set[int] = set(ADMIN_IDS)
    if await _is_admin(actor_user_id):
        recipients.add(actor_user_id)

    fail_lines = "\n".join(
        f"• Chat ID <code>{cid}</code>: <code>{html.escape(err[:180])}</code>"
        for cid, err in failed_parents
    )
    alert_text = (
        f"⚠️ <b>To‘lov xabarini yetkazishda xatolik (talaba / ota-ona)!</b>\n\n"
        f"👤 Talaba: <b>{html.escape(student_name)}</b> ({html.escape(group_name)})\n"
        f"{fail_lines}"
    )
    for admin_cid in recipients:
        try:
            await bot.send_message(
                chat_id=admin_cid,
                text=alert_text,
                parse_mode="HTML",
            )
        except Exception:
            logger.exception(
                "Failed to notify admin_id=%s about parent payment delivery failure",
                admin_cid,
            )


async def _broadcast_payment_event(
    bot: Any,
    group_name: str,
    student: dict[str, Any],
    cycle_title: str,
    is_confirm: bool,
    actor_user_id: int,
    paid_amount: Optional[int] = None,
    overrides_by_title: Optional[dict[str, Any]] = None,
) -> None:
    sheets = get_sheets_manager()
    student_id = str(student.get("Talaba_ID") or "").strip()
    if student_id:
        fresh_student = await sheets.a_get_student_by_id(student_id)
        if fresh_student:
            student = fresh_student

    all_students = await sheets.a_get_all_students()
    all_groups = await sheets.a_get_all_groups()
    group = await sheets.a_get_group(group_name)
    default_fee = _get_default_monthly_fee()
    group_fees = {
        g.get("Guruh_Nomi", "").strip().lower(): _parse_group_fee(g)
        for g in all_groups
    }
    monthly_fee = group_fees.get(group_name.strip().lower(), _parse_group_fee(group))
    stu_name = str(student.get("F.I.O.") or student_id).strip()

    def _signature(target_lang: str) -> str:
        """Payment confirmations / reversals always carry the official center signature."""
        return _lt("signature_center", target_lang)

    stu_key = "payment_confirmed_student" if is_confirm else "payment_reverted_student"
    par_key = "payment_confirmed_parent" if is_confirm else "payment_reverted_parent"
    tch_key = "payment_confirmed_teacher" if is_confirm else "payment_reverted_teacher"

    try:
        legacy_rows = await get_legacy_debts(student_id) if student_id else []
    except Exception:
        logger.exception("Failed loading legacy debts for %s", student_id)
        legacy_rows = []

    failed_deliveries: list[tuple[int, str]] = []

    stu_cid = _parse_chat_id(student.get("Talaba_Chat_ID"))
    if stu_cid is not None:
        try:
            s_lang = await get_user_lang(stu_cid)
            s_prefix = (
                dual_role_header("student", s_lang)
                if await has_dual_student_parent_role(stu_cid)
                else ""
            )
            stu_name_line = (
                f"👤 Талаба: <b>{html.escape(stu_name)}</b>\n"
                if s_lang == "cyrl"
                else f"👤 Talaba: <b>{html.escape(stu_name)}</b>\n"
            )
            stu_body = t(
                stu_key,
                s_lang,
                group=html.escape(group_name),
                cycle_title=html.escape(cycle_title),
                student_name=html.escape(stu_name),
            )
            first_break = stu_body.find("\n\n")
            if first_break != -1 and html.escape(stu_name) not in stu_body:
                stu_body = (
                    stu_body[: first_break + 2] + stu_name_line + stu_body[first_break + 2 :]
                )
            await bot.send_message(
                chat_id=stu_cid,
                text=s_prefix + stu_body + _signature(s_lang),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.exception(
                "Failed to send payment notification to student chat_id=%s student=%s",
                stu_cid,
                stu_name,
            )
            failed_deliveries.append((stu_cid, f"student: {exc}"))

    parent_cids: set[int] = set()
    for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
        p_cid = _parse_chat_id(student.get(col))
        if p_cid is not None:
            parent_cids.add(p_cid)

    src_phones = {
        p
        for p in (
            _normalize_phone_key(student.get("Otasi_Tel")),
            _normalize_phone_key(student.get("Onasi_Tel")),
            _normalize_phone_key(student.get("OtaOna_Tel")),
        )
        if p
    }
    if src_phones:
        for row in all_students:
            row_phones = {
                p
                for p in (
                    _normalize_phone_key(row.get("Otasi_Tel")),
                    _normalize_phone_key(row.get("Onasi_Tel")),
                    _normalize_phone_key(row.get("OtaOna_Tel")),
                )
                if p
            }
            if src_phones & row_phones:
                for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
                    sib_p_cid = _parse_chat_id(row.get(col))
                    if sib_p_cid is not None:
                        parent_cids.add(sib_p_cid)

    failed_parents: list[tuple[int, str]] = failed_deliveries
    notified_parents: set[int] = set()
    for p_cid in sorted(parent_cids):
        if p_cid == stu_cid or p_cid in notified_parents:
            continue
        notified_parents.add(p_cid)
        try:
            p_lang = await get_user_lang(p_cid)
            p_prefix = (
                dual_role_header("parent", p_lang, [stu_name])
                if await has_dual_student_parent_role(p_cid)
                else ""
            )
            base_par_text = t(
                par_key,
                p_lang,
                student_name=html.escape(stu_name),
                group=html.escape(group_name),
                cycle_title=html.escape(cycle_title),
            )
            context_block = _build_parent_payment_context_lines(
                target_student=student,
                group_name=group_name,
                monthly_fee=monthly_fee,
                parent_cid=p_cid,
                all_students=all_students,
                group_fees=group_fees,
                default_fee=default_fee,
                is_confirm=is_confirm,
                lang=p_lang,
                legacy_rows=legacy_rows,
                paid_amount=paid_amount,
                overrides_by_title=overrides_by_title,
            )
            await bot.send_message(
                chat_id=p_cid,
                text=f"{p_prefix}{base_par_text}\n\n{context_block}{_signature(p_lang)}",
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.exception(
                "Failed to send payment notification to parent chat_id=%s student=%s",
                p_cid,
                stu_name,
            )
            failed_parents.append((p_cid, f"parent: {exc}"))

    if failed_parents:
        await _notify_admins_delivery_failure(
            bot=bot,
            actor_user_id=actor_user_id,
            student_name=stu_name,
            group_name=group_name,
            failed_parents=failed_parents,
        )

    if group:
        t_cid = _parse_chat_id(group.get("Ustoz_Chat_ID"))
        if t_cid is not None and t_cid != actor_user_id and t_cid != stu_cid and t_cid not in notified_parents:
            try:
                t_lang = await get_user_lang(t_cid)
                await bot.send_message(
                    chat_id=t_cid,
                    text=t(
                        tch_key,
                        t_lang,
                        student_name=html.escape(stu_name),
                        group=html.escape(group_name),
                        cycle_title=html.escape(cycle_title),
                    )
                    + _signature(t_lang),
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception(
                    "Failed to send payment notification to teacher chat_id=%s student=%s",
                    t_cid,
                    stu_name,
                )


# ----------------------------------------------------------------------
# 1. Teacher / Admin: "💰 To'lovni tasdiqlash" / "💳 To'lovlarni tasdiqlash"
# ----------------------------------------------------------------------


@router.message(F.text.in_(PAYMENT_CONFIRM_MENU_TEXTS))
async def cmd_payment_start(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    await state.clear()
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)

    authorized, groups = await _get_authorized_groups(user_id)
    if not authorized:
        return

    if not groups:
        await message.answer(t("contacts_empty", lang))
        return

    await state.set_state(PaymentStates.selecting_group)
    await message.answer(
        t("payment_select_group", lang),
        reply_markup=groups_inline_kb(
            groups, prefix="pay_grp", lang=lang, include_back=False, include_cancel=True
        ),
    )


@router.callback_query(PaymentStates.selecting_group, F.data.startswith("pay_grp:"))
async def cb_payment_select_group(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    group_name = (callback.data or "").split(":", 1)[1]

    if group_name == "__cancel__":
        await state.clear()
        await callback.message.edit_text(t("btn_cancel", lang))
        await callback.answer()
        return

    if not await _can_manage_group(user_id, group_name):
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return

    sheets = get_sheets_manager()
    students = await asyncio.to_thread(sheets.get_all_students, group_name, False)
    if not students:
        await callback.answer(t("contacts_empty", lang), show_alert=True)
        return

    group = await sheets.a_get_group(group_name)
    monthly_fee = _parse_group_fee(group)

    await state.set_state(PaymentStates.selecting_student)
    await state.update_data(group_name=group_name, monthly_fee=monthly_fee)
    await callback.message.edit_text(
        t("payment_select_student", lang, group=html.escape(group_name)),
        reply_markup=students_list_kb(
            students, prefix="pay_stu", lang=lang, include_back=True, include_cancel=True
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(PaymentStates.selecting_student, F.data.startswith("pay_stu:"))
async def cb_payment_select_student(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    student_id = (callback.data or "").split(":", 1)[1]

    if student_id == "__cancel__":
        await state.clear()
        await callback.message.edit_text(t("btn_cancel", lang))
        await callback.answer()
        return

    if student_id == "__back__":
        _, groups = await _get_authorized_groups(user_id)
        await state.set_state(PaymentStates.selecting_group)
        await callback.message.edit_text(
            t("payment_select_group", lang),
            reply_markup=groups_inline_kb(
                groups,
                prefix="pay_grp",
                lang=lang,
                include_back=False,
                include_cancel=True,
            ),
        )
        await callback.answer()
        return

    data = await state.get_data()
    group_name: str = data["group_name"]

    sheets = get_sheets_manager()
    student = await asyncio.to_thread(sheets.get_student_by_id, student_id)
    if not student:
        await callback.answer(
            t("link_student_not_found", lang, student_id=student_id),
            show_alert=True,
        )
        return

    cycles = await asyncio.to_thread(
        _fetch_full_cycle_history_sync, group_name, student_id
    )
    if not cycles:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    cycles.sort(key=lambda c: (c["is_paid"], c["cycle_number"]))
    debt_raw = str(student.get("Qarzdor_Oylar", "")).strip()

    await state.set_state(PaymentStates.selecting_cycle)
    await state.update_data(
        student_id=student_id,
        student_name=student["F.I.O."],
        student_debts=debt_raw,
        cycles=cycles,
    )
    await callback.message.edit_text(
        t("payment_select_cycle", lang),
        reply_markup=_cycles_selection_kb(cycles, lang),
    )
    await callback.answer()


@router.callback_query(PaymentStates.selecting_cycle, F.data.startswith("pay_cyc:"))
async def cb_payment_select_cycle(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    val = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()
    group_name: str = data["group_name"]

    if val == "__cancel__":
        await state.clear()
        await callback.message.edit_text(t("btn_cancel", lang))
        await callback.answer()
        return

    if val == "__back__":
        sheets = get_sheets_manager()
        students = await asyncio.to_thread(sheets.get_all_students, group_name, False)
        await state.set_state(PaymentStates.selecting_student)
        await callback.message.edit_text(
            t("payment_select_student", lang, group=html.escape(group_name)),
            reply_markup=students_list_kb(
                students,
                prefix="pay_stu",
                lang=lang,
                include_back=True,
                include_cancel=True,
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    cycle_idx = int(val)
    cycles: list[dict[str, Any]] = data["cycles"]
    if cycle_idx < 0 or cycle_idx >= len(cycles):
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    student_id: str = data["student_id"]
    student_name: str = data["student_name"]
    monthly_fee: Optional[int] = data.get("monthly_fee")
    debt_raw: str = data.get("student_debts", "")
    cycle = cycles[cycle_idx]

    await state.set_state(PaymentStates.confirming)
    await state.update_data(selected_cycle_idx=cycle_idx)

    text = _format_teacher_payment_text(
        student_name=student_name,
        group_name=group_name,
        cycle=cycle,
        is_detailed=False,
        lang=lang,
        monthly_fee=monthly_fee,
        debt_raw=debt_raw,
    )
    await callback.message.edit_text(
        text,
        reply_markup=payment_confirm_kb(
            student_id,
            cycle_idx,
            is_detailed=False,
            lang=lang,
            include_confirm=True,
            back_cb="pay_back:cycle",
            is_paid=bool(cycle["is_paid"]),
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(PaymentStates.confirming, F.data == "pay_back:cycle")
async def cb_payment_back_to_cycle(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    data = await state.get_data()
    cycles: list[dict[str, Any]] = data.get("cycles", [])
    await state.set_state(PaymentStates.selecting_cycle)
    await callback.message.edit_text(
        t("payment_select_cycle", lang),
        reply_markup=_cycles_selection_kb(cycles, lang),
    )
    await callback.answer()


@router.callback_query(PaymentStates.confirming, F.data.startswith("pay_toggle:"))
async def cb_payment_toggle_detail(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    _, student_id, cycle_idx_str, detailed_str = (callback.data or "").split(":", 3)
    cycle_idx = int(cycle_idx_str)
    is_detailed = bool(int(detailed_str))

    data = await state.get_data()
    group_name: str = data["group_name"]
    student_name: str = data["student_name"]
    cycles: list[dict[str, Any]] = data["cycles"]
    monthly_fee: Optional[int] = data.get("monthly_fee")
    debt_raw: str = data.get("student_debts", "")

    if cycle_idx < 0 or cycle_idx >= len(cycles):
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    cycle = cycles[cycle_idx]
    text = _format_teacher_payment_text(
        student_name=student_name,
        group_name=group_name,
        cycle=cycle,
        is_detailed=is_detailed,
        lang=lang,
        monthly_fee=monthly_fee,
        debt_raw=debt_raw,
    )
    if len(text) > 4090:
        text = text[:4085] + "..."
    await callback.message.edit_text(
        text,
        reply_markup=payment_confirm_kb(
            student_id,
            cycle_idx,
            is_detailed=is_detailed,
            lang=lang,
            include_confirm=True,
            back_cb="pay_back:cycle",
            is_paid=bool(cycle["is_paid"]),
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(PaymentStates.confirming, F.data == "pay_edit")
async def cb_payment_edit_return_groups(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    _, groups = await _get_authorized_groups(user_id)

    await state.set_state(PaymentStates.selecting_group)
    await callback.message.edit_text(
        t("payment_select_group", lang),
        reply_markup=groups_inline_kb(
            groups, prefix="pay_grp", lang=lang, include_back=False, include_cancel=True
        ),
    )
    await callback.answer()


@router.callback_query(StateFilter(PaymentStates), F.data == "pay_cancel")
async def cb_payment_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text(t("btn_cancel", lang))
    await callback.answer()


@router.callback_query(PaymentStates.confirming, F.data.startswith("pay_confirm:"))
async def cb_payment_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    _, student_id, cycle_idx_str = (callback.data or "").split(":", 2)
    cycle_idx = int(cycle_idx_str)

    data = await state.get_data()
    group_name: str = data["group_name"]
    student_name: str = data["student_name"]
    cycles: list[dict[str, Any]] = data["cycles"]
    monthly_fee: Optional[int] = data.get("monthly_fee")

    if not await _can_manage_group(user_id, group_name):
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return

    if cycle_idx < 0 or cycle_idx >= len(cycles):
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    cycle = cycles[cycle_idx]
    cycle_title = cycle["cycle_title"]
    sheets = get_sheets_manager()

    ok = await sheets.a_confirm_student_payment(
        student_id=student_id,
        group_name=group_name,
        cycle_title=cycle_title,
    )
    if not ok:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    await log_audit_event(
        actor_id=user_id,
        action=AUDIT_PAYMENT_CONFIRMED,
        target=f"{student_name} ({student_id}) | {group_name} | {cycle_title}",
        amount=(
            int(cycle["prorated_amount"])
            if cycle.get("prorated_amount")
            else (int(monthly_fee) if monthly_fee is not None else _get_default_monthly_fee())
        ),
        details=f"Talaba: {student_name}; Guruh: {group_name}; Sikl: {cycle_title}",
        actor_name=callback.from_user.full_name or "",
    )

    student = await sheets.a_get_student_by_id(student_id)
    if student:
        await _broadcast_payment_event(
            bot=callback.bot,
            group_name=group_name,
            student=student,
            cycle_title=_format_cycle_display_title(cycle, "latn"),
            is_confirm=True,
            actor_user_id=user_id,
            paid_amount=cycle.get("prorated_amount"),
            overrides_by_title=cycle.get("student_overrides"),
        )

    cycle["is_paid"] = True
    cycles[cycle_idx] = cycle
    new_debt_raw = str(student.get("Qarzdor_Oylar", "") if student else "").strip()
    await state.update_data(cycles=cycles, student_debts=new_debt_raw)

    notice = _lt(
        "payment_confirmed_instant_admin",
        lang,
        student_name=html.escape(student_name),
        group=html.escape(group_name),
        cycle_title=html.escape(_format_cycle_display_title(cycle, lang)),
    )
    card_text = _format_teacher_payment_text(
        student_name=student_name,
        group_name=group_name,
        cycle=cycle,
        is_detailed=False,
        lang=lang,
        monthly_fee=monthly_fee,
        debt_raw=new_debt_raw,
    )
    await callback.message.edit_text(
        f"{notice}\n\n{card_text}",
        reply_markup=payment_confirm_kb(
            student_id,
            cycle_idx,
            is_detailed=False,
            lang=lang,
            include_confirm=True,
            back_cb="pay_back:cycle",
            is_paid=True,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(PaymentStates.confirming, F.data.startswith("pay_revert:"))
async def cb_payment_revert(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    _, student_id, cycle_idx_str = (callback.data or "").split(":", 2)
    cycle_idx = int(cycle_idx_str)

    data = await state.get_data()
    group_name: str = data["group_name"]
    student_name: str = data["student_name"]
    cycles: list[dict[str, Any]] = data["cycles"]
    monthly_fee: Optional[int] = data.get("monthly_fee")

    if not await _can_manage_group(user_id, group_name):
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return

    if cycle_idx < 0 or cycle_idx >= len(cycles):
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    cycle = cycles[cycle_idx]
    cycle_title = cycle["cycle_title"]
    sheets = get_sheets_manager()

    ok = await sheets.a_revert_student_payment(
        student_id=student_id,
        group_name=group_name,
        cycle_title=cycle_title,
    )
    if not ok:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    await log_audit_event(
        actor_id=user_id,
        action=AUDIT_PAYMENT_REVERTED,
        target=f"{student_name} ({student_id}) | {group_name} | {cycle_title}",
        amount=(
            int(cycle["prorated_amount"])
            if cycle.get("prorated_amount")
            else (int(monthly_fee) if monthly_fee is not None else _get_default_monthly_fee())
        ),
        details=f"Talaba: {student_name}; Guruh: {group_name}; Sikl: {cycle_title}",
        actor_name=callback.from_user.full_name or "",
    )

    student = await sheets.a_get_student_by_id(student_id)
    if student:
        await _broadcast_payment_event(
            bot=callback.bot,
            group_name=group_name,
            student=student,
            cycle_title=_format_cycle_display_title(cycle, "latn"),
            is_confirm=False,
            actor_user_id=user_id,
            paid_amount=cycle.get("prorated_amount"),
            overrides_by_title=cycle.get("student_overrides"),
        )

    cycle["is_paid"] = False
    cycles[cycle_idx] = cycle
    new_debt_raw = str(student.get("Qarzdor_Oylar", "") if student else "").strip()
    await state.update_data(cycles=cycles, student_debts=new_debt_raw)

    notice = t(
        "payment_reverted_admin",
        lang,
        student_name=html.escape(student_name),
        group=html.escape(group_name),
        cycle_title=html.escape(_format_cycle_display_title(cycle, lang)),
    )
    card_text = _format_teacher_payment_text(
        student_name=student_name,
        group_name=group_name,
        cycle=cycle,
        is_detailed=False,
        lang=lang,
        monthly_fee=monthly_fee,
        debt_raw=new_debt_raw,
    )
    await callback.message.edit_text(
        f"{notice}\n\n{card_text}",
        reply_markup=payment_confirm_kb(
            student_id,
            cycle_idx,
            is_detailed=False,
            lang=lang,
            include_confirm=True,
            back_cb="pay_back:cycle",
            is_paid=False,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pay_pending_cancel:"))
async def cb_payment_pending_cancel(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    action_id = int((callback.data or "").split(":", 1)[1])

    action = await get_pending_action(action_id)
    if (
        not action
        or action["status"] != "pending"
        or action["action_type"] != "payment"
    ):
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    await update_pending_action_status(action_id, "cancelled")
    await callback.message.edit_text(t("btn_cancel", lang))
    await callback.answer()


# ----------------------------------------------------------------------
# 2. Student & Parent: "💳 To'lovlar va Qarzlar" (Strictly Single Message)
# ----------------------------------------------------------------------


def _find_role_linked_students_sync(
    user_id: int, fallback_student_id: Optional[str] = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sheets = get_sheets_manager()
    target = _parse_chat_id(user_id)
    self_students: list[dict[str, Any]] = []
    parent_children: list[dict[str, Any]] = []
    seen_self: set[tuple[str, str]] = set()
    seen_parent: set[tuple[str, str]] = set()

    all_rows = sheets.get_all_students()
    for s in all_rows:
        sid = str(s.get("Talaba_ID", "")).strip()
        grp = str(s.get("Guruh", "")).strip().lower()
        if not sid:
            continue
        key = (sid, grp)

        stu_cid = _parse_chat_id(s.get("Talaba_Chat_ID"))
        parent_cids = {
            cid
            for cid in (
                _parse_chat_id(s.get("Otasi_Chat_ID")),
                _parse_chat_id(s.get("Onasi_Chat_ID")),
                _parse_chat_id(s.get("OtaOna_Chat_ID")),
            )
            if cid is not None
        }

        if target is not None and stu_cid == target and key not in seen_self:
            seen_self.add(key)
            self_students.append(s)

        if target is not None and target in parent_cids and key not in seen_parent:
            seen_parent.add(key)
            parent_children.append(s)

    if not self_students and not parent_children and fallback_student_id:
        single = sheets.get_student_by_id(fallback_student_id)
        if single:
            parent_children.append(single)

    return self_students, parent_children


async def _send_combined_debt_view(
    message: Message,
    students: list[dict[str, Any]],
    lang: str,
    audience: str,
    recipient_name: str = "",
) -> None:
    """
    Student / Parent "💳 To'lovlarim" view: polite short summary (total sum +
    total months, legacy + current cycles combined) with an inline
    📄 Batafsil / 📋 Qisqacha toggle listing every unpaid cycle and its exact
    lesson dates.
    """
    sheets = get_sheets_manager()
    all_groups = await asyncio.to_thread(sheets.get_all_groups)
    group_fees = {
        g.get("Guruh_Nomi", "").strip().lower(): _parse_group_fee(g)
        for g in all_groups
    }
    default_fee = _get_default_monthly_fee()
    card_number, card_owner = _get_payment_card_info()

    children = await compute_children_debts(sheets, students, group_fees, default_fee)
    user_id = message.from_user.id if message.from_user else 0
    prefix = ""
    if user_id and await has_dual_student_parent_role(user_id):
        prefix = dual_role_header(
            "parent" if audience == "parent" else "student",
            lang,
            [str(s.get("F.I.O.") or "") for s in students],
        )
    short_text, detailed_text = build_debt_notice(
        children,
        lang,
        audience=audience,
        card_number=card_number,
        card_owner=card_owner,
        recipient_name=recipient_name,
        header_key="header_view",
        prefix=prefix,
    )
    if detailed_text != short_text:
        notif_id = f"dbt{uuid.uuid4().hex[:12]}_{lang}"
        await save_notification_details(notif_id, short_text, detailed_text)
        await message.answer(
            short_text,
            reply_markup=build_expandable_notif_kb(notif_id, expanded=False, lang=lang),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await message.answer(short_text, parse_mode="HTML", disable_web_page_preview=True)


def _build_parent_payments_text(
    children_debts: list[dict[str, Any]],
    lang: str,
    card_number: str = "",
    card_owner: str = "",
) -> str:
    """
    Plain-language single summary for parents (no Batafsil/Qisqacha toggle):
    every child's group, monthly fee, paid/unpaid status, individual debt and
    the total debt across all children.
    """
    blocks: list[str] = []
    total_debt = 0
    for idx, child in enumerate(children_debts, 1):
        child_debt = int(child.get("total_sum") or 0)
        total_debt += child_debt
        status_key = (
            "parent_pay_status_unpaid" if child_debt > 0 else "parent_pay_status_paid"
        )
        blocks.append(
            t(
                "parent_pay_child",
                lang,
                tartib=idx,
                talaba_ismi=html.escape(str(child.get("name") or "—")),
                guruh_nomi=html.escape(str(child.get("group") or "—")),
                oylik_tolov=debt_format_uzs(int(child.get("fee") or 0)),
                tolov_holati=t(status_key, lang),
                qarz_summasi=debt_format_uzs(child_debt),
            )
        )
    text = t("parent_pay_header", lang) + t("parent_pay_separator", lang).join(blocks)
    text += t("parent_pay_total", lang, umumiy_qarz=debt_format_uzs(total_debt))
    if total_debt > 0 and card_number:
        text += "\n\n" + debt_text(
            "card_block",
            lang,
            card_number=html.escape(card_number),
            card_owner=html.escape(card_owner or "—"),
        )
    return text


async def _send_parent_payments_single_message(
    message: Message,
    children: list[dict[str, Any]],
    lang: str,
) -> None:
    sheets = get_sheets_manager()
    group_fees, default_fee = await load_group_fees(sheets)
    card_number, card_owner = _get_payment_card_info()
    children_debts = await compute_children_debts(
        sheets, children, group_fees, default_fee
    )
    user_id = message.from_user.id if message.from_user else 0
    prefix = ""
    if user_id and await has_dual_student_parent_role(user_id):
        prefix = dual_role_header(
            "parent", lang, [str(c.get("F.I.O.") or "") for c in children]
        )
    text = prefix + _build_parent_payments_text(
        children_debts, lang, card_number=card_number, card_owner=card_owner
    )
    await message.answer(
        text[:4090], parse_mode="HTML", disable_web_page_preview=True
    )


@router.message(F.text.in_(STUDENT_PARENT_PAYMENTS_TEXTS))
async def cmd_student_parent_payments(message: Message) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)

    db_user = await get_user(user_id)
    active_role = db_user.get("role") if db_user else None
    fallback_sid = db_user.get("linked_student_id") if db_user else None

    try:
        self_students, parent_children = await asyncio.to_thread(
            _find_role_linked_students_sync, user_id, fallback_sid
        )

        if active_role == "parent" or (parent_children and active_role != "student"):
            target_children = parent_children or self_students
            if not target_children:
                await message.answer(t("unregistered_user", lang))
                return
            await _send_parent_payments_single_message(message, target_children, lang)
            return

        students = self_students or parent_children
        if not students:
            await message.answer(t("unregistered_user", lang))
            return
        await _send_combined_debt_view(
            message,
            students,
            lang,
            audience="student",
            recipient_name=str(students[0].get("F.I.O.") or "").strip(),
        )
    except Exception:
        logger.exception("Failed building payments view for user_id=%s", user_id)
        await message.answer(t("error_generic", lang))


@router.callback_query(F.data.startswith("stu_pay_toggle:"))
async def cb_student_payment_toggle(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    _, student_id, cycle_idx_str, detailed_str = (callback.data or "").split(":", 3)
    cycle_idx = int(cycle_idx_str)
    is_detailed = bool(int(detailed_str))

    sheets = get_sheets_manager()
    student = await asyncio.to_thread(sheets.get_student_by_id, student_id)
    if not student:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    group_name = student.get("Guruh", "")
    group = await sheets.a_get_group(group_name) if group_name else None
    monthly_fee = _parse_group_fee(group)

    cycles = await asyncio.to_thread(
        _fetch_full_cycle_history_sync, group_name, student_id
    )
    if cycle_idx < 0 or cycle_idx >= len(cycles):
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    debt_raw = student.get("Qarzdor_Oylar", "").strip()
    debt_titles = {
        x.strip()
        for x in debt_raw.split(";")
        if x.strip() and x.strip() != "0" and not x.strip().isdigit()
    }
    cycle = cycles[cycle_idx]
    status_label = _get_student_cycle_status_label(cycle, debt_titles, lang)

    text = _format_student_cycle_text(
        cycle,
        status_label,
        is_detailed,
        lang,
        monthly_fee=monthly_fee,
        debt_raw=debt_raw,
    )
    if len(text) > 4090:
        text = text[:4085] + "..."
    await callback.message.edit_text(
        text,
        reply_markup=student_payment_detail_kb(
            student_id, cycle_idx, is_detailed, lang
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------------------
# 3. Teacher / Admin: "⚠️ Qarzdorlar" + Smart Multi-Child Debt Broadcast
# ----------------------------------------------------------------------


async def _fetch_authorized_debtors_and_fees(
    user_id: int,
) -> tuple[bool, list[dict[str, Any]], dict[str, int]]:
    sheets = get_sheets_manager()
    is_admin = await _is_admin(user_id)
    all_groups = await asyncio.to_thread(sheets.get_all_groups)
    group_fees = {
        g.get("Guruh_Nomi", "").strip().lower(): _parse_group_fee(g)
        for g in all_groups
    }

    if is_admin:
        debtors = await asyncio.to_thread(sheets.get_debtors, None)
        debtors = await _augment_debtors_with_legacy(sheets, debtors, None)
        return True, debtors, group_fees

    raw_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
    teacher_groups = [
        g
        for g in raw_groups
        if str(g.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
    ]
    if not teacher_groups:
        return False, [], group_fees

    allowed_groups = {
        g.get("Guruh_Nomi", "").strip().lower() for g in teacher_groups
    }
    all_debtors = await asyncio.to_thread(sheets.get_debtors, None)
    debtors = [
        d
        for d in all_debtors
        if d.get("Guruh", "").strip().lower() in allowed_groups
    ]
    debtors = await _augment_debtors_with_legacy(sheets, debtors, allowed_groups)
    return True, debtors, group_fees


async def _augment_debtors_with_legacy(
    sheets: SheetsManager,
    debtors: list[dict[str, Any]],
    allowed_groups: Optional[set[str]],
) -> list[dict[str, Any]]:
    """
    Adds students who owe ONLY pre-system (legacy) debts to the debtor list and
    attaches `_legacy_rows` to every debtor so totals include legacy cycles.
    """
    try:
        legacy_map = await get_unpaid_legacy_debts_map()
    except Exception:
        logger.exception("Failed loading legacy debts map")
        legacy_map = {}
    result = list(debtors)
    known = {str(d.get("Talaba_ID", "")).strip() for d in result}
    if legacy_map:
        all_students = await sheets.a_get_all_students()
        by_id = {str(s.get("Talaba_ID", "")).strip(): s for s in all_students}
        for sid in legacy_map:
            if sid in known or sid not in by_id:
                continue
            stu = by_id[sid]
            grp_key = str(stu.get("Guruh", "")).strip().lower()
            sobiq_key = str(stu.get("Sobiq_Guruh", "")).strip().lower()
            if allowed_groups is not None and not (
                grp_key in allowed_groups or sobiq_key in allowed_groups
            ):
                continue
            enriched = dict(stu)
            enriched.setdefault("total_held_lessons", 0)
            enriched.setdefault("attended_lessons", 0)
            enriched.setdefault("missed_lessons", 0)
            result.append(enriched)
            known.add(sid)
    for d in result:
        d["_legacy_rows"] = legacy_map.get(str(d.get("Talaba_ID", "")).strip(), [])
    return result


# Per-user cache of the rendered debtors views, so "🔼 Qisqacha" / "📄 Batafsil"
# and page switches are instant edits (no Google Sheets re-reads).
_DEBTOR_VIEW_TTL_SECONDS = 300
_debtor_view_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_MARK_ICONS = {"✅": "✅", "❌": "❌"}


def _lesson_status_icon(mark: str) -> str:
    cleaned = str(mark or "").strip()
    if cleaned in _MARK_ICONS:
        return _MARK_ICONS[cleaned]
    if cleaned.casefold().startswith("qoldirildi"):
        return "🚫"
    if cleaned in {"+", "1", "bor", "Bor", "Keldi", "keldi"}:
        return "✅"
    if cleaned in {"-", "0", "yo'q", "Yo'q", "Kelmadi", "kelmadi"}:
        return "❌"
    return "⏳"


def _sync_collect_unpaid_cycles(
    sheets: SheetsManager, debtors: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """
    {Talaba_ID: [{"title", "lessons": [(label, icon)], "labels": [...]}]} for every
    UNPAID cycle row of each debtor in their group's cycle sheets (this year and
    last year). Each group/year sheet is read only once.
    """
    by_group: dict[str, set[str]] = {}
    for d in debtors:
        sid = str(d.get("Talaba_ID", "")).strip()
        grp = str(d.get("Guruh", "")).strip()
        if sid and grp:
            by_group.setdefault(grp, set()).add(sid)
    result: dict[str, list[dict[str, Any]]] = {}
    now_year = now_tashkent().year
    with sheets._lock:
        ss = sheets._get_spreadsheet()
        for grp, sids in by_group.items():
            for year in (now_year - 1, now_year):
                try:
                    ws = sheets._open_group_year_ws(ss, grp, year)
                except Exception:
                    continue
                try:
                    cycles = sheets.parse_cycles_from_sheet(ws)
                except Exception:
                    logger.exception("Debtors view: cannot parse %s %s", grp, year)
                    continue
                for cycle in cycles:
                    for s_row in cycle["student_rows"]:
                        sid = str(s_row.get("student_id") or "").strip()
                        if sid not in sids:
                            continue
                        if _is_paid_status(str(s_row.get("payment_status") or "")):
                            continue
                        lessons = [
                            (
                                str(dc.get("label") or dc["date_str"]),
                                _lesson_status_icon(
                                    s_row["marks"].get(dc["col_idx"], "")
                                ),
                            )
                            for dc in cycle["date_columns"]
                        ]
                        result.setdefault(sid, []).append(
                            {"title": cycle["title"], "lessons": lessons}
                        )
    return result


def _format_unpaid_cycles_block(cycles: list[dict[str, Any]], lang: str) -> str:
    """Detailed view: unpaid cycles, dated lessons with ✅/❌/⏳ and a one-tap
    copyable <code>DD.MM, DD.MM, ...</code> block of all those dates."""
    if not cycles:
        return ""
    parts: list[str] = []
    all_labels: list[str] = []
    for cyc in cycles:
        lesson_txt = ", ".join(
            f"{html.escape(label)} {icon}" for label, icon in cyc["lessons"]
        )
        parts.append(
            _lt(
                "debtor_unpaid_cycle_line",
                lang,
                cycle=html.escape(str(cyc["title"])),
                lessons=lesson_txt or "—",
            )
        )
        all_labels.extend(label for label, _icon in cyc["lessons"])
    copy_block = ", ".join(html.escape(label) for label in all_labels)
    tail = (
        "\n" + _lt("debtor_dates_copy_line", lang, dates=copy_block) if copy_block else ""
    )
    return "\n" + "\n".join(parts) + tail


def _paginate_lines(header: str, lines: list[str], footer: str) -> list[str]:
    pages: list[str] = []
    current = header
    for line in lines:
        addition = f"\n{line}"
        if len(current) + len(addition) > 3600 and current != header:
            pages.append(current)
            current = f"{header}\n{line}"
        else:
            current += addition
    if len(current) + len(footer) > 4000:
        pages.append(current)
        current = header
    pages.append(current + footer)
    return pages


async def _build_debtor_views(user_id: int, lang: str) -> Optional[dict[str, Any]]:
    """
    Builds both debtors views for the user (None = not authorized):
    {"compact": [pages], "detailed": [pages]} or {"empty": True}.
    """
    authorized, debtors, group_fees = await _fetch_authorized_debtors_and_fees(
        user_id
    )
    if not authorized:
        return None
    if not debtors:
        return {"empty": True}

    sheets = get_sheets_manager()
    default_fee = _get_default_monthly_fee()
    header = t("debtors_list_header", lang)
    compact_lines: list[str] = []
    detailed_lines: list[str] = []
    grand_total = 0

    legacy_map_local = {
        str(d.get("Talaba_ID", "")).strip(): list(d.get("_legacy_rows") or [])
        for d in debtors
    }
    try:
        child_debts = await compute_children_debts(
            sheets, debtors, group_fees, default_fee, legacy_map=legacy_map_local
        )
    except Exception:
        logger.exception("Failed computing combined debts for debtor list")
        child_debts = []
    child_by_sid = {c["student_id"]: c for c in child_debts}
    try:
        unpaid_cycles = await asyncio.to_thread(
            _sync_collect_unpaid_cycles, sheets, debtors
        )
    except Exception:
        logger.exception("Failed collecting unpaid cycle dates for debtors view")
        unpaid_cycles = {}

    for d in debtors:
        name = html.escape(d.get("F.I.O.", ""))
        group_name = d.get("Guruh", "")
        group = html.escape(group_name)
        debts_raw = d.get("Qarzdor_Oylar", "").strip()

        fee = group_fees.get(group_name.strip().lower(), default_fee)
        child = child_by_sid.get(str(d.get("Talaba_ID", "")).strip())
        months = child["total_months"] if child else _count_debt_months(debts_raw)
        if months <= 0:
            continue
        total_debt = child["total_sum"] if child else months * fee
        grand_total += total_debt
        if not debts_raw or debts_raw == "0":
            debts_raw = (
                "Аввалги қарз" if lang == "cyrl" else "Avvalgi qarz"
            ) if child and child["legacy"] else debts_raw

        stats = await _resolve_debtor_stats(sheets, d, group_name)
        cycle_title = str(stats.get("cycle_title") or "").strip()
        debts_display = (
            f"{debts_raw} ({cycle_title})"
            if debts_raw.isdigit() and cycle_title
            else debts_raw
        )
        debts = html.escape(debts_display)
        lesson_stats_line = _format_lesson_attendance_stats(
            stats["total_held_lessons"],
            stats["attended_lessons"],
            stats["missed_lessons"],
            lang,
        )

        stu_phone_link = _format_tel_link(d.get("Talaba_Tel", ""))
        stu_tg_link = _format_tg_link(
            d.get("Talaba_TG", ""),
            d.get("Talaba_Chat_ID", ""),
            fallback_label="Talaba TG" if lang == "latn" else "Талаба TG",
        )

        par_parts: list[str] = []
        father_phone = str(d.get("Otasi_Tel") or "").strip()
        father_cid = _parse_chat_id(d.get("Otasi_Chat_ID"))
        if father_phone or father_cid is not None:
            lbl = "Otasi" if lang == "latn" else "Отаси"
            f_tel = _format_tel_link(father_phone)
            f_tg = _format_tg_link("", father_cid, fallback_label=lbl)
            f_info = f"{lbl}: {f_tel}"
            if f_tg != "—":
                f_info += f" ({f_tg})"
            par_parts.append(f_info)

        mother_phone = str(d.get("Onasi_Tel") or "").strip()
        mother_cid = _parse_chat_id(d.get("Onasi_Chat_ID"))
        if mother_phone or mother_cid is not None:
            lbl = "Onasi" if lang == "latn" else "Онаси"
            m_tel = _format_tel_link(mother_phone)
            m_tg = _format_tg_link("", mother_cid, fallback_label=lbl)
            m_info = f"{lbl}: {m_tel}"
            if m_tg != "—":
                m_info += f" ({m_tg})"
            par_parts.append(m_info)

        if not par_parts:
            fallback_par = str(d.get("OtaOna_Tel") or "").strip()
            fallback_cid = _parse_chat_id(d.get("OtaOna_Chat_ID"))
            if fallback_par or fallback_cid is not None:
                lbl = "Ota-ona" if lang == "latn" else "Ота-она"
                p_tel = _format_tel_link(fallback_par)
                p_tg = _format_tg_link("", fallback_cid, fallback_label=lbl)
                p_info = f"{lbl}: {p_tel}"
                if p_tg != "—":
                    p_info += f" ({p_tg})"
                par_parts.append(p_info)
            else:
                par_parts.append("—")

        if child and child["legacy_sum"]:
            amount_part = (
                f"💰 <b>{months} ой — {_format_uzs(total_debt)} сўм</b>"
                if lang == "cyrl"
                else f"💰 <b>{months} oy — {_format_uzs(total_debt)} so‘m</b>"
            )
        else:
            amount_part = _lt(
                "debtor_amount_part",
                lang,
                months=months,
                fee=_format_uzs(fee),
                total=_format_uzs(total_debt),
            )
        extra_lines = format_admin_extra_lines(child, lang) if child else ""
        compact_lines.append(
            _lt(
                "debtor_compact_line",
                lang,
                name=name,
                group=group,
                phone=stu_phone_link,
                total=_format_uzs(total_debt),
            )
        )
        detailed_lines.append(
            f"• <b>{name}</b> ({group}) — <i>{debts}</i> | {amount_part}\n"
            f"  {lesson_stats_line}\n"
            + (f"{extra_lines}\n" if extra_lines else "")
            + f"  📞 {stu_phone_link} | 💬 {stu_tg_link}\n"
            f"  👨‍👩‍👧 {' | '.join(par_parts)}"
            + _format_unpaid_cycles_block(
                unpaid_cycles.get(str(d.get("Talaba_ID", "")).strip(), []), lang
            )
        )

    if not compact_lines:
        return {"empty": True}

    footer = "\n" + _lt(
        "debtors_grand_total",
        lang,
        count=len(compact_lines),
        total=_format_uzs(grand_total),
    )
    return {
        "compact": _paginate_lines(header, compact_lines, footer),
        "detailed": _paginate_lines(header, detailed_lines, footer),
    }


def _debtors_view_kb(mode: str, page: int, pages: int, lang: str) -> InlineKeyboardMarkup:
    compact_lbl = _lt("btn_debtors_compact", lang)
    detailed_lbl = _lt("btn_debtors_detailed", lang)
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=f"✅ {compact_lbl}" if mode == "compact" else compact_lbl,
                callback_data="debt_view:compact:0",
            ),
            InlineKeyboardButton(
                text=f"✅ {detailed_lbl}" if mode == "detailed" else detailed_lbl,
                callback_data="debt_view:detailed:0",
            ),
        ]
    ]
    if pages > 1:
        nav: list[InlineKeyboardButton] = []
        if page > 0:
            nav.append(
                InlineKeyboardButton(text="◀️", callback_data=f"debt_view:{mode}:{page - 1}")
            )
        nav.append(
            InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="debt_view:noop")
        )
        if page < pages - 1:
            nav.append(
                InlineKeyboardButton(text="▶️", callback_data=f"debt_view:{mode}:{page + 1}")
            )
        rows.append(nav)
    rows.append(
        [
            InlineKeyboardButton(
                text=_lt("btn_remind_debtors", lang),
                callback_data="debt_remind_all",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _get_debtor_views(
    user_id: int, lang: str, refresh: bool = False
) -> Optional[dict[str, Any]]:
    now_ts = datetime.now().timestamp()
    cached = _debtor_view_cache.get(user_id)
    if (
        not refresh
        and cached is not None
        and now_ts - cached[0] < _DEBTOR_VIEW_TTL_SECONDS
        and cached[1].get("lang") == lang
    ):
        return cached[1]
    views = await _build_debtor_views(user_id, lang)
    if views is not None:
        views["lang"] = lang
        _debtor_view_cache[user_id] = (now_ts, views)
    return views


@router.message(F.text.in_(DEBTORS_MENU_TEXTS))
async def cmd_debtors_list(message: Message) -> None:
    """⚠️ Qarzdorlar: compact view by default, with 🔼 Qisqacha / 📄 Batafsil toggle."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    views = await _get_debtor_views(user_id, lang, refresh=True)
    if views is None:
        return
    if views.get("empty"):
        await message.answer(t("debtors_empty", lang))
        return
    pages = views["compact"]
    await message.answer(
        pages[0],
        reply_markup=_debtors_view_kb("compact", 0, len(pages), lang),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(F.data.startswith("debt_view:"))
async def cb_debtors_view_toggle(callback: CallbackQuery) -> None:
    """🔼 Qisqacha / 📄 Batafsil / page switch — updates the SAME message (edit_text)."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or parts[1] not in {"compact", "detailed"}:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    mode = parts[1]
    try:
        page = max(0, int(parts[2]))
    except ValueError:
        page = 0
    views = await _get_debtor_views(user_id, lang)
    if views is None:
        await callback.answer()
        return
    if views.get("empty"):
        await callback.message.edit_text(t("debtors_empty", lang))
        await callback.answer()
        return
    pages = views[mode]
    page = min(page, len(pages) - 1)
    try:
        await callback.message.edit_text(
            pages[page],
            reply_markup=_debtors_view_kb(mode, page, len(pages), lang),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception as exc:
        if "message is not modified" not in str(exc):
            logger.warning("Debtors view edit failed: %s", exc)
    await callback.answer()


def _format_parent_debt_reminder_text(
    grouped_by_group: dict[str, list[dict[str, Any]]],
    target_lang: str,
    card_number: str,
    card_owner: str,
) -> str:
    if len(grouped_by_group) == 1:
        items = next(iter(grouped_by_group.values()))
        group_name = items[0]["group_name"]
        fee = items[0]["fee"]
        if len(items) == 1:
            it = items[0]
            return (
                t(
                    "reminder_weekly_debt_parent",
                    target_lang,
                    student_name=html.escape(it["student_name"]),
                    group=html.escape(group_name),
                    debts=html.escape(it["debts_raw"]),
                    card_number=html.escape(card_number),
                    card_owner=html.escape(card_owner),
                )
                + (
                    f"\n💰 {it['months']} oy × {_format_uzs(fee)} = <b>{_format_uzs(it['total'])} so‘m</b>"
                    if target_lang == "latn"
                    else f"\n💰 {it['months']} ой × {_format_uzs(fee)} = <b>{_format_uzs(it['total'])} сўм</b>"
                )
                + _lt("signature_center", target_lang)
            )

        child_lines = "\n".join(
            f"{idx}. <b>{html.escape(it['student_name'])}</b> — "
            f"<i>{html.escape(it['debts_raw'])}</i> "
            f"({it['months']} {'ой' if target_lang == 'cyrl' else 'oy'} = "
            f"<b>{_format_uzs(it['total'])} {'сўм' if target_lang == 'cyrl' else 'so‘m'}</b>)"
            for idx, it in enumerate(items, start=1)
        )
        total_sum = sum(it["total"] for it in items)
        return _lt(
            "reminder_parent_same_group",
            target_lang,
            group=html.escape(group_name),
            fee=_format_uzs(fee),
            child_count=len(items),
            children_lines=child_lines,
            total=_format_uzs(total_sum),
            card_number=html.escape(card_number),
            card_owner=html.escape(card_owner),
        )

    group_blocks: list[str] = []
    grand_total = 0
    for items in grouped_by_group.values():
        group_name = items[0]["group_name"]
        fee = items[0]["fee"]
        group_sum = sum(it["total"] for it in items)
        grand_total += group_sum
        child_lines = "\n".join(
            f"   • <b>{html.escape(it['student_name'])}</b> — "
            f"<i>{html.escape(it['debts_raw'])}</i> "
            f"({it['months']} {'ой' if target_lang == 'cyrl' else 'oy'} = "
            f"<b>{_format_uzs(it['total'])} {'сўм' if target_lang == 'cyrl' else 'so‘m'}</b>)"
            for it in items
        )
        if target_lang == "cyrl":
            block = (
                f"📚 <b>{html.escape(group_name)}</b> "
                f"(Ойлик тўлов: <b>{_format_uzs(fee)} сўм</b>)\n"
                f"{child_lines}\n"
                f"   💰 Гуруҳ жами: <b>{_format_uzs(group_sum)} сўм</b>"
            )
        else:
            block = (
                f"📚 <b>{html.escape(group_name)}</b> "
                f"(Oylik to‘lov: <b>{_format_uzs(fee)} so‘m</b>)\n"
                f"{child_lines}\n"
                f"   💰 Guruh jami: <b>{_format_uzs(group_sum)} so‘m</b>"
            )
        group_blocks.append(block)

    return _lt(
        "reminder_parent_multi_group",
        target_lang,
        groups_blocks="\n\n".join(group_blocks),
        grand_total=_format_uzs(grand_total),
        card_number=html.escape(card_number),
        card_owner=html.escape(card_owner),
    )


@router.callback_query(F.data == "debt_remind_all")
async def cb_remind_all_debtors(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)

    authorized, debtors, group_fees = await _fetch_authorized_debtors_and_fees(
        user_id
    )
    if not authorized:
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return
    if not debtors:
        await callback.answer(t("debtors_empty", lang), show_alert=True)
        return

    sheets = get_sheets_manager()
    all_students = await sheets.a_get_all_students()
    default_fee = _get_default_monthly_fee()
    card_number, card_owner = _get_payment_card_info()
    # Teacher-initiated reminders are signed by the teacher; admin ones officially.
    actor_teacher_name = (
        "" if await _is_admin(user_id) else await _resolve_actor_teacher_name(user_id, None)
    )

    # Map normalized parent phone -> known parent chat IDs across all students
    phone_to_parent_cids: dict[str, set[int]] = {}
    for row in all_students:
        for chat_col, tel_col in (
            ("Otasi_Chat_ID", "Otasi_Tel"),
            ("Onasi_Chat_ID", "Onasi_Tel"),
            ("OtaOna_Chat_ID", "OtaOna_Tel"),
        ):
            c_id = _parse_chat_id(row.get(chat_col))
            p_key = _normalize_phone_key(row.get(tel_col))
            if c_id is not None and p_key:
                phone_to_parent_cids.setdefault(p_key, set()).add(c_id)

    parent_buckets: dict[int, dict[str, list[dict[str, Any]]]] = {}
    parent_meta: dict[int, dict[str, Any]] = {}
    parent_cids_by_student: dict[str, set[int]] = {}
    student_entries: dict[int, list[dict[str, Any]]] = {}

    legacy_map_local = {
        str(d.get("Talaba_ID", "")).strip(): list(d.get("_legacy_rows") or [])
        for d in debtors
    }
    try:
        child_debts = await compute_children_debts(
            sheets, debtors, group_fees, default_fee, legacy_map=legacy_map_local
        )
    except Exception:
        logger.exception("Failed computing combined debts for reminders")
        child_debts = []
    child_by_sid = {c["student_id"]: c for c in child_debts}

    for d in debtors:
        stu_id = str(d.get("Talaba_ID", "")).strip()
        stu_name = d.get("F.I.O.", "").strip() or stu_id
        group_name = d.get("Guruh", "").strip()
        debts_raw = d.get("Qarzdor_Oylar", "").strip()
        child_debt = child_by_sid.get(stu_id)
        months = (
            child_debt["total_months"] if child_debt else _count_debt_months(debts_raw)
        )
        if months <= 0:
            continue

        stats = await _resolve_debtor_stats(sheets, d, group_name)
        cycle_title = str(stats.get("cycle_title") or "").strip()
        debts_display = (
            f"{debts_raw} ({cycle_title})"
            if debts_raw.isdigit() and cycle_title
            else debts_raw
        )

        fee = group_fees.get(group_name.lower(), default_fee)
        total = child_debt["total_sum"] if child_debt else months * fee
        item = {
            "student_id": stu_id,
            "student_name": stu_name,
            "group_name": group_name,
            "debts_raw": debts_display,
            "months": months,
            "fee": fee,
            "total": total,
            "stu_tel": d.get("Talaba_Tel", "").strip(),
            "stu_tg": d.get("Talaba_TG", "").strip(),
            "total_held_lessons": stats["total_held_lessons"],
            "attended_lessons": stats["attended_lessons"],
            "missed_lessons": stats["missed_lessons"],
        }

        stu_cid = _parse_chat_id(d.get("Talaba_Chat_ID"))

        seen_parents_for_student: set[int] = set()
        seen_item_keys_for_parent: set[tuple[int, str, str]] = set()
        for col, role_latn, role_cyrl, tel_col, name_col in (
            ("Otasi_Chat_ID", "Otasi", "Отаси", "Otasi_Tel", "Otasi_FIO"),
            ("Onasi_Chat_ID", "Onasi", "Онаси", "Onasi_Tel", "Onasi_FIO"),
            ("OtaOna_Chat_ID", "Ota-ona", "Ота-она", "OtaOna_Tel", "Otasi_FIO"),
        ):
            candidate_cids: list[int] = []
            direct_cid = _parse_chat_id(d.get(col))
            if direct_cid is not None:
                candidate_cids.append(direct_cid)
            else:
                p_key = _normalize_phone_key(d.get(tel_col))
                if p_key and p_key in phone_to_parent_cids:
                    candidate_cids.extend(sorted(phone_to_parent_cids[p_key]))

            for p_cid in candidate_cids:
                if p_cid in seen_parents_for_student:
                    continue
                seen_parents_for_student.add(p_cid)
                parent_cids_by_student.setdefault(stu_id, set()).add(p_cid)

                dedup_item_key = (p_cid, stu_id, group_name.lower())
                if dedup_item_key in seen_item_keys_for_parent:
                    continue
                seen_item_keys_for_parent.add(dedup_item_key)

                grp_map = parent_buckets.setdefault(p_cid, {})
                grp_map.setdefault(group_name.lower(), []).append(item)

                meta = parent_meta.setdefault(
                    p_cid,
                    {
                        "chat_id": p_cid,
                        "role_latn": role_latn,
                        "role_cyrl": role_cyrl,
                        "name": str(d.get(name_col, "")).strip(),
                        "phone": str(d.get(tel_col, "")).strip(),
                        "children": [],
                    },
                )
                if not meta["phone"]:
                    meta["phone"] = str(d.get(tel_col, "")).strip()
                if not meta["name"]:
                    meta["name"] = str(d.get(name_col, "")).strip()
                meta["children"].append(f"{stu_name} ({group_name})")

        if stu_cid is not None and stu_cid not in parent_cids_by_student.get(stu_id, set()):
            student_entries.setdefault(stu_cid, []).append(item)

    notified_students_lines: list[str] = []
    notified_parents_lines: list[str] = []
    stu_sent = 0
    par_sent = 0

    # 1. Send private reminders to Students (skipping any chat_id already handled as parent for same student)
    for stu_cid, s_items in student_entries.items():
        if stu_cid in parent_buckets:
            s_items = [
                it
                for it in s_items
                if stu_cid not in parent_cids_by_student.get(it["student_id"], set())
            ]
            if not s_items:
                continue

        s_lang = await get_user_lang(stu_cid)
        s_prefix = (
            dual_role_header("student", s_lang)
            if await has_dual_student_parent_role(stu_cid)
            else ""
        )
        s_children = [
            child_by_sid[it["student_id"]]
            for it in s_items
            if it["student_id"] in child_by_sid
        ]
        if s_children:
            s_short, s_detailed = build_debt_notice(
                s_children,
                s_lang,
                audience="student",
                card_number=card_number,
                card_owner=card_owner,
                recipient_name=s_items[0]["student_name"],
                prefix=s_prefix,
                teacher_name=actor_teacher_name,
            )
        else:
            grouped_stu: dict[str, list[dict[str, Any]]] = {}
            for it in s_items:
                grouped_stu.setdefault(it["group_name"].lower(), []).append(it)
            s_short = s_detailed = f"{s_prefix}" + _format_parent_debt_reminder_text(
                grouped_stu, s_lang, card_number, card_owner
            )

        try:
            delivered = await send_expandable_notice(
                callback.bot, stu_cid, s_short, s_detailed, s_lang
            )
            if not delivered:
                raise RuntimeError("Telegram delivery failed")
            stu_sent += 1
            first = s_items[0]
            tel_link = _format_tel_link(first["stu_tel"])
            tg_link = _format_tg_link(
                first["stu_tg"],
                stu_cid,
                fallback_label="Telegram",
            )
            for x in s_items:
                stats_str = _format_lesson_attendance_stats(
                    x["total_held_lessons"],
                    x["attended_lessons"],
                    x["missed_lessons"],
                    lang,
                )
                notified_students_lines.append(
                    f"• <b>{html.escape(x['student_name'])}</b> ({html.escape(x['group_name'])}) — "
                    f"<i>{html.escape(x['debts_raw'])}</i> | "
                    f"<b>{_format_uzs(x['total'])} {'сўм' if lang == 'cyrl' else 'so‘m'}</b>\n"
                    f"  {stats_str}\n"
                    f"  📞 {tel_link} | 💬 {tg_link}"
                )
        except Exception:
            logger.exception(
                "Failed to send debt reminder to student chat_id=%s", stu_cid
            )

    # 2. Send strictly ONE combined private reminder per parent_chat_id
    for p_cid, grouped_by_group in parent_buckets.items():
        p_lang = await get_user_lang(p_cid)
        p_children = [
            child_by_sid[it["student_id"]]
            for grp_items in grouped_by_group.values()
            for it in grp_items
            if it["student_id"] in child_by_sid
        ]
        p_prefix = (
            dual_role_header(
                "parent",
                p_lang,
                [
                    str(it.get("student_name") or "")
                    for grp_items in grouped_by_group.values()
                    for it in grp_items
                ],
            )
            if await has_dual_student_parent_role(p_cid)
            else ""
        )
        if p_children:
            p_short, p_detailed = build_debt_notice(
                p_children,
                p_lang,
                audience="parent",
                card_number=card_number,
                card_owner=card_owner,
                prefix=p_prefix,
                teacher_name=actor_teacher_name,
            )
        else:
            msg_text = _format_parent_debt_reminder_text(
                grouped_by_group, p_lang, card_number, card_owner
            )
            p_short = p_detailed = _safe_truncate_html_lines(
                f"{p_prefix}{msg_text}", limit=4085
            )

        try:
            delivered = await send_expandable_notice(
                callback.bot, p_cid, p_short, p_detailed, p_lang
            )
            if not delivered:
                raise RuntimeError("Telegram delivery failed")
            par_sent += 1
            meta = parent_meta[p_cid]
            p_name = meta.get("name", "")
            if not p_name:
                db_p = await get_user(p_cid)
                if db_p and db_p.get("full_name"):
                    p_name = str(db_p["full_name"]).strip()
            role_lbl = meta["role_cyrl"] if p_lang == "cyrl" else meta["role_latn"]
            if not p_name:
                p_name = meta["role_cyrl"] if lang == "cyrl" else meta["role_latn"]
            else:
                p_name = f"{p_name} ({role_lbl})"

            grand_p = sum(
                it["total"]
                for grp_items in grouped_by_group.values()
                for it in grp_items
            )
            tel_link = _format_tel_link(meta.get("phone", ""))
            tg_link = _format_tg_link("", p_cid, fallback_label="Telegram")
            child_detail_lines: list[str] = []
            for grp_items in grouped_by_group.values():
                for it in grp_items:
                    stats_str = _format_lesson_attendance_stats(
                        it["total_held_lessons"],
                        it["attended_lessons"],
                        it["missed_lessons"],
                        lang,
                    )
                    child_detail_lines.append(
                        f"  ↳ <b>{html.escape(it['student_name'])}</b> ({html.escape(it['group_name'])}) — "
                        f"<i>{html.escape(it['debts_raw'])}</i> | "
                        f"<b>{_format_uzs(it['total'])} {'сўм' if lang == 'cyrl' else 'so‘m'}</b>\n"
                        f"     {stats_str}"
                    )
            notified_parents_lines.append(
                f"• <b>{html.escape(p_name)}</b> "
                f"(<b>{_format_uzs(grand_p)} {'сўм' if lang == 'cyrl' else 'so‘m'}</b>)\n"
                + "\n".join(child_detail_lines)
                + f"\n  📞 {tel_link} | 💬 {tg_link}"
            )
        except Exception:
            logger.exception(
                "Failed to send debt reminder to parent chat_id=%s", p_cid
            )

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    short_text = _lt(
        "reminder_sent_report_short",
        lang,
        stu_sent=stu_sent,
        par_sent=par_sent,
        total_sent=stu_sent + par_sent,
    )
    detailed_text = _lt(
        "reminder_sent_report_detailed",
        lang,
        stu_sent=stu_sent,
        par_sent=par_sent,
        student_lines="\n".join(notified_students_lines) if notified_students_lines else "—",
        parent_lines="\n".join(notified_parents_lines) if notified_parents_lines else "—",
    )

    notif_id = f"debt_{uuid.uuid4().hex[:12]}"
    await save_notification_details(notif_id, short_text, detailed_text)

    await callback.message.answer(
        short_text,
        reply_markup=_debt_report_toggle_kb(notif_id, is_detailed=False, lang=lang),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("debt_rep_toggle:"))
async def cb_debt_report_toggle(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message or not callback.data:
        await callback.answer()
        return
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer()
        return

    notif_id = parts[1]
    is_detailed = bool(int(parts[2])) if parts[2].isdigit() else False
    lang = await get_user_lang(callback.from_user.id)

    record = await get_notification_details(notif_id)
    if not record:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    raw_text = record["detailed_text"] if is_detailed else record["short_text"]
    text = _safe_truncate_html_lines(raw_text, limit=3950)
    await callback.message.edit_text(
        text,
        reply_markup=_debt_report_toggle_kb(notif_id, is_detailed=is_detailed, lang=lang),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()