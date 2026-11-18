import asyncio
import html
import os
import re
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
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import config
from app.config import ADMIN_IDS, DB_PATH, TZ
from app.database import (
    get_pending_action,
    get_user,
    get_user_lang,
    update_pending_action_status,
)
from app.keyboards import (
    groups_inline_kb,
    payment_confirm_kb,
    student_payment_detail_kb,
    students_list_kb,
)
from app.locales import (
    format_human_cycle_title,
    format_lesson_line,
    format_next_payment_info,
    format_uz_date,
    t,
)
from app.sheets import get_sheets_manager
from app.states import PaymentStates

router = Router(name="payments")

PAYMENT_CONFIRM_MENU_TEXTS = {
    t("menu_admin_payments", "latn"),
    t("menu_admin_payments", "cyrl"),
    t("menu_teacher_payments", "latn"),
    t("menu_teacher_payments", "cyrl"),
}

STUDENT_PARENT_PAYMENTS_TEXTS = {
    t("menu_student_payments", "latn"),
    t("menu_student_payments", "cyrl"),
    t("menu_parent_payments", "latn"),
    t("menu_parent_payments", "cyrl"),
}

DEBTORS_MENU_TEXTS = {
    t("menu_admin_debtors", "latn"),
    t("menu_admin_debtors", "cyrl"),
    t("menu_teacher_debtors", "latn"),
    t("menu_teacher_debtors", "cyrl"),
}

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
        "btn_remind_debtors": "📢 Qarzdorlarga eslatma yuborish",
        "reminder_student": (
            "🔔 <b>To‘lov eslatmasi</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 Qarzdor oylar: <b>{cycles}</b>\n"
            "💰 Qarzdorlik summasi: <b>{months} oy × {fee} = {total} so‘m</b>\n\n"
            "To‘lovni o‘z vaqtida amalga oshirishingizni so‘raymiz.\n\n"
            "💳 Karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>\n\n"
            "Hurmat bilan, Mishkat o'quv muassasasi"
        ),
        "reminder_sent_report": (
            "✅ Qarzdorlik eslatmasi yuborildi!\n"
            "🎓 Talabalarga: <b>{stu_sent} ta</b> | 👨‍👩‍👧 Ota-onalarga: <b>{par_sent} ta</b>"
        ),
        "payment_confirmed_instant_admin": (
            "✅ <b>To‘lov tasdiqlandi va jadval yashil rangga bo‘yaldi!</b>\n\n"
            "👤 Talaba: <b>{student_name}</b> ({group})\n"
            "🗓 O‘quv oyi: <b>{cycle_title}</b>"
        ),
        "signature": "\n\nHurmat bilan, Mishkat o'quv muassasasi",
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
        "btn_remind_debtors": "📢 Қарздорларга эслатма юбориш",
        "reminder_student": (
            "🔔 <b>Тўлов эслатмаси</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Қарздор ойлар: <b>{cycles}</b>\n"
            "💰 Қарздорлик суммаси: <b>{months} ой × {fee} = {total} сўм</b>\n\n"
            "Тўловни ўз вақтида амалга оширишингизни сўраймиз.\n\n"
            "💳 Карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>\n\n"
            "Ҳурмат билан, Мишкат ўқув муассасаси"
        ),
        "reminder_sent_report": (
            "✅ Қарздорлик эслатмаси юборилди!\n"
            "🎓 Талабаларга: <b>{stu_sent} та</b> | 👨‍👩‍👧 Ота-оналарга: <b>{par_sent} та</b>"
        ),
        "payment_confirmed_instant_admin": (
            "✅ <b>Тўлов тасдиқланди ва жадвал яшил рангга бўялди!</b>\n\n"
            "👤 Талаба: <b>{student_name}</b> ({group})\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>"
        ),
        "signature": "\n\nҲурмат билан, Мишкат ўқув муассасаси",
    },
}


def _lt(key: str, lang: str = "latn", **kwargs: Any) -> str:
    safe_lang = lang if lang in LOCAL_TEXTS else "latn"
    template = LOCAL_TEXTS[safe_lang].get(key) or LOCAL_TEXTS["latn"].get(key, key)
    return template.format(**kwargs) if kwargs else template


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
    current_year = datetime.now(TZ).year
    cycles: list[dict[str, Any]] = []
    seen_titles: set[str] = set()

    for yr in (current_year - 1, current_year):
        yr_cycles = sheets.get_student_cycle_history(group_name, student_id, year=yr)
        for c in yr_cycles:
            title = c["cycle_title"]
            if title not in seen_titles:
                seen_titles.add(title)
                cycles.append(_enrich_cycle_with_weekdays(c, yr))
    return cycles


def _format_cycle_display_title(cycle: dict[str, Any], lang: str) -> str:
    num = int(cycle.get("cycle_number") or 1)
    count = int(cycle.get("lesson_count") or len(cycle.get("lessons", [])) or 12)
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
            cycle, datetime.now(TZ).year
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
        builder.row(
            InlineKeyboardButton(
                text=f"{icon} {_format_cycle_display_title(c, lang)}",
                callback_data=f"pay_cyc:{idx}",
            )
        )
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

    fee_lines = _lt("fee_summary_line", lang, fee=fee_fmt)
    if debt_count > 0:
        fee_lines += "\n" + _lt(
            "debt_summary_line",
            lang,
            months=debt_count,
            fee=fee_fmt,
            total=_format_uzs(debt_count * fee),
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
    fee_fmt = _format_uzs(fee)
    debt_count = _count_debt_months(debt_raw)

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
            fee=fee_fmt,
            total=_format_uzs(debt_count * fee),
            cycles=html.escape(debt_raw),
        )
    card_block = t(
        "payment_card_block",
        lang,
        card_number=html.escape(card_number),
        card_owner=html.escape(card_owner),
    )
    return f"{body}\n\n{fee_block}\n\n{card_block}"


async def _broadcast_payment_event(
    bot: Any,
    group_name: str,
    student: dict[str, Any],
    cycle_title: str,
    is_confirm: bool,
    actor_user_id: int,
) -> None:
    """
    Sends payment confirmation or accidental-payment reversion notifications
    to Student, Father, Mother, Teacher, and Group chat.
    """
    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    stu_name = student.get("F.I.O.", "").strip() or student.get("Talaba_ID", "")

    stu_key = "payment_confirmed_student" if is_confirm else "payment_reverted_student"
    par_key = "payment_confirmed_parent" if is_confirm else "payment_reverted_parent"
    tch_key = "payment_confirmed_teacher" if is_confirm else "payment_reverted_teacher"
    grp_key = "payment_confirmed_group" if is_confirm else "payment_reverted_group"

    # 1. Student DM
    stu_cid_str = str(student.get("Talaba_Chat_ID", "")).strip()
    stu_cid = int(stu_cid_str) if stu_cid_str.lstrip("-").isdigit() else None
    if stu_cid:
        try:
            s_lang = await get_user_lang(stu_cid)
            await bot.send_message(
                chat_id=stu_cid,
                text=t(
                    stu_key,
                    s_lang,
                    group=html.escape(group_name),
                    cycle_title=html.escape(cycle_title),
                )
                + _lt("signature", s_lang),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # 2. Father & Mother DMs (plus OtaOna_Chat_ID fallback)
    notified_parents: set[int] = set()
    for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
        raw = str(student.get(col, "")).strip()
        if not raw.lstrip("-").isdigit():
            continue
        p_cid = int(raw)
        if p_cid == stu_cid or p_cid in notified_parents:
            continue
        notified_parents.add(p_cid)
        try:
            p_lang = await get_user_lang(p_cid)
            await bot.send_message(
                chat_id=p_cid,
                text=t(
                    par_key,
                    p_lang,
                    student_name=html.escape(stu_name),
                    group=html.escape(group_name),
                    cycle_title=html.escape(cycle_title),
                )
                + _lt("signature", p_lang),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # 3. Teacher DM
    if group:
        tch_cid_str = str(group.get("Ustoz_Chat_ID", "")).strip()
        if tch_cid_str.lstrip("-").isdigit():
            t_cid = int(tch_cid_str)
            if t_cid != actor_user_id:
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
                        + _lt("signature", t_lang),
                        parse_mode="HTML",
                    )
                except Exception:
                    pass

        # 4. Group Telegram Chat (Latin script)
        grp_tg_str = str(group.get("Guruh_TG_Chat_ID", "")).strip()
        if grp_tg_str.lstrip("-").isdigit():
            try:
                await bot.send_message(
                    chat_id=int(grp_tg_str),
                    text=t(
                        grp_key,
                        "latn",
                        student_name=html.escape(stu_name),
                        group=html.escape(group_name),
                        cycle_title=html.escape(cycle_title),
                    )
                    + _lt("signature", "latn"),
                    parse_mode="HTML",
                )
            except Exception:
                pass


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

    student = await sheets.a_get_student_by_id(student_id)
    if student:
        await _broadcast_payment_event(
            bot=callback.bot,
            group_name=group_name,
            student=student,
            cycle_title=_format_cycle_display_title(cycle, "latn"),
            is_confirm=True,
            actor_user_id=user_id,
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

    student = await sheets.a_get_student_by_id(student_id)
    if student:
        await _broadcast_payment_event(
            bot=callback.bot,
            group_name=group_name,
            student=student,
            cycle_title=_format_cycle_display_title(cycle, "latn"),
            is_confirm=False,
            actor_user_id=user_id,
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
# 2. Student & Parent: "💳 To'lovlar va Qarzlar"
# ----------------------------------------------------------------------


def _find_student_by_any_chat_sync(user_id: int) -> Optional[dict[str, Any]]:
    sheets = get_sheets_manager()
    res = sheets.get_student_by_chat_id(user_id)
    if res:
        return res[0]
    target = str(user_id).strip()
    for s in sheets.get_all_students():
        if (
            str(s.get("Otasi_Chat_ID", "")).strip() == target
            or str(s.get("Onasi_Chat_ID", "")).strip() == target
        ):
            return s
    return None


async def _resolve_linked_student(user_id: int) -> Optional[dict[str, Any]]:
    sheets = get_sheets_manager()
    db_user = await get_user(user_id)
    if db_user and db_user.get("linked_student_id"):
        student = await asyncio.to_thread(
            sheets.get_student_by_id, db_user["linked_student_id"]
        )
        if student:
            return student
    return await asyncio.to_thread(_find_student_by_any_chat_sync, user_id)


@router.message(F.text.in_(STUDENT_PARENT_PAYMENTS_TEXTS))
async def cmd_student_parent_payments(message: Message) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)

    student = await _resolve_linked_student(user_id)
    if not student:
        await message.answer(t("unregistered_user", lang))
        return

    sheets = get_sheets_manager()
    student_id = student["Talaba_ID"]
    student_name = student["F.I.O."]
    group_name = student.get("Guruh", "")
    group = await sheets.a_get_group(group_name) if group_name else None
    monthly_fee = _parse_group_fee(group)
    fee_fmt = _format_uzs(monthly_fee)
    card_number, card_owner = _get_payment_card_info()

    debt_raw = student.get("Qarzdor_Oylar", "").strip()
    debt_titles = {
        x.strip()
        for x in debt_raw.split(";")
        if x.strip() and x.strip() != "0" and not x.strip().isdigit()
    }
    debt_count = _count_debt_months(debt_raw)

    header_text = t(
        "student_payments_header",
        lang,
        student_name=html.escape(student_name),
        group=html.escape(group_name),
        card_number=html.escape(card_number),
        card_owner=html.escape(card_owner),
    )
    header_text = f"{header_text}\n{_lt('fee_summary_line', lang, fee=fee_fmt)}"
    if debt_count > 0:
        header_text += "\n" + _lt(
            "debt_summary_line",
            lang,
            months=debt_count,
            fee=fee_fmt,
            total=_format_uzs(debt_count * monthly_fee),
            cycles=html.escape(debt_raw),
        )
    await message.answer(header_text, parse_mode="HTML")

    cycles = await asyncio.to_thread(
        _fetch_full_cycle_history_sync, group_name, student_id
    )

    shown_any = False
    for idx, cycle in enumerate(cycles):
        if cycle["is_paid"]:
            continue
        status_label = _get_student_cycle_status_label(cycle, debt_titles, lang)
        text = _format_student_cycle_text(
            cycle,
            status_label,
            False,
            lang,
            monthly_fee=monthly_fee,
            debt_raw=debt_raw,
        )
        await message.answer(
            text,
            reply_markup=student_payment_detail_kb(student_id, idx, False, lang),
            parse_mode="HTML",
        )
        shown_any = True

    existing_titles = {c["cycle_title"] for c in cycles}
    for debt_title in sorted(debt_titles):
        if debt_title not in existing_titles:
            item_text = t(
                "student_payment_cycle_compact",
                lang,
                cycle_title=html.escape(debt_title),
                next_payment_info="—",
                status_label=t("status_unpaid", lang),
            )
            item_text = f"{item_text}\n{_lt('cycle_fee_line', lang, fee=fee_fmt)}"
            await message.answer(item_text, parse_mode="HTML")
            shown_any = True

    if not shown_any:
        await message.answer(t("no_debts_msg", lang))


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
# 3. Teacher / Admin: "⚠️ Qarzdorlar"
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
    return True, debtors, group_fees


@router.message(F.text.in_(DEBTORS_MENU_TEXTS))
async def cmd_debtors_list(message: Message) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)

    authorized, debtors, group_fees = await _fetch_authorized_debtors_and_fees(
        user_id
    )
    if not authorized:
        return

    if not debtors:
        await message.answer(t("debtors_empty", lang))
        return

    default_fee = _get_default_monthly_fee()
    header = t("debtors_list_header", lang)
    lines: list[str] = []
    grand_total = 0

    for d in debtors:
        name = html.escape(d.get("F.I.O.", ""))
        group_name = d.get("Guruh", "")
        group = html.escape(group_name)
        debts_raw = d.get("Qarzdor_Oylar", "").strip()
        debts = html.escape(debts_raw)
        stu_phone = html.escape(d.get("Talaba_Tel", "") or "—")
        father_phone = d.get("Otasi_Tel", "").strip()
        mother_phone = d.get("Onasi_Tel", "").strip()
        fallback_par = d.get("OtaOna_Tel", "").strip()

        fee = group_fees.get(group_name.strip().lower(), default_fee)
        months = _count_debt_months(debts_raw)
        if months <= 0:
            continue
        total_debt = months * fee
        grand_total += total_debt

        par_parts: list[str] = []
        if father_phone:
            par_parts.append(f"Otasi: {html.escape(father_phone)}")
        if mother_phone:
            par_parts.append(f"Onasi: {html.escape(mother_phone)}")
        if not par_parts:
            par_parts.append(html.escape(fallback_par or "—"))

        tg_raw = d.get("Talaba_TG", "").strip()
        if tg_raw and not tg_raw.startswith("@"):
            tg_raw = f"@{tg_raw}"
        tg_display = html.escape(tg_raw) if tg_raw else "—"

        base_line = t(
            "debtor_item",
            lang,
            student_name=name,
            group=group,
            debts=debts,
            phone=stu_phone,
        )
        amount_part = _lt(
            "debtor_amount_part",
            lang,
            months=months,
            fee=_format_uzs(fee),
            total=_format_uzs(total_debt),
        )
        lines.append(
            f"{base_line} | {amount_part} | {' / '.join(par_parts)} | {tg_display}"
        )

    if not lines:
        await message.answer(t("debtors_empty", lang))
        return

    lines.append(
        _lt(
            "debtors_grand_total",
            lang,
            count=len(lines),
            total=_format_uzs(grand_total),
        )
    )

    remind_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_lt("btn_remind_debtors", lang),
                    callback_data="debt_remind_all",
                )
            ]
        ]
    )

    chunks: list[str] = []
    current_chunk = header
    for line in lines:
        addition = f"\n{line}"
        if len(current_chunk) + len(addition) > 3900:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += addition
    if current_chunk:
        chunks.append(current_chunk)

    for idx, chunk in enumerate(chunks):
        await message.answer(
            chunk,
            reply_markup=(remind_kb if idx == len(chunks) - 1 else None),
            parse_mode="HTML",
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

    default_fee = _get_default_monthly_fee()
    card_number, card_owner = _get_payment_card_info()
    stu_sent = 0
    par_sent = 0

    for d in debtors:
        stu_name = d.get("F.I.O.", "").strip() or d.get("Talaba_ID", "")
        group_name = d.get("Guruh", "").strip()
        debts_raw = d.get("Qarzdor_Oylar", "").strip()
        months = _count_debt_months(debts_raw)
        if months <= 0:
            continue

        fee = group_fees.get(group_name.lower(), default_fee)
        total = months * fee

        def _build_reminder(target_lang: str) -> str:
            return _lt(
                "reminder_student",
                target_lang,
                student_name=html.escape(stu_name),
                group=html.escape(group_name),
                cycles=html.escape(debts_raw),
                months=months,
                fee=_format_uzs(fee),
                total=_format_uzs(total),
                card_number=html.escape(card_number),
                card_owner=html.escape(card_owner),
            )

        stu_cid_raw = str(d.get("Talaba_Chat_ID", "")).strip()
        stu_cid = int(stu_cid_raw) if stu_cid_raw.isdigit() else None
        if stu_cid:
            try:
                s_lang = await get_user_lang(stu_cid)
                await callback.bot.send_message(
                    chat_id=stu_cid,
                    text=_build_reminder(s_lang),
                    parse_mode="HTML",
                )
                stu_sent += 1
            except Exception:
                pass

        parent_cids: list[int] = []
        for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
            raw = str(d.get(col, "")).strip()
            if raw.isdigit():
                cid = int(raw)
                if cid != stu_cid and cid not in parent_cids:
                    parent_cids.append(cid)

        for p_cid in parent_cids:
            try:
                p_lang = await get_user_lang(p_cid)
                await callback.bot.send_message(
                    chat_id=p_cid,
                    text=_build_reminder(p_lang),
                    parse_mode="HTML",
                )
                par_sent += 1
            except Exception:
                pass

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        _lt("reminder_sent_report", lang, stu_sent=stu_sent, par_sent=par_sent),
        parse_mode="HTML",
    )
    await callback.answer()