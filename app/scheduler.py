import asyncio
import html
import logging
import os
import re
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app import config
from app.config import ADMIN_IDS, TZ
from app.database import (
    get_group_counter,
    get_lesson_topic,
    get_teacher_by_telegram_id,
    get_user,
    get_user_lang,
    upsert_group_counter,
)
from app.locales import format_uz_date, t
from app.sheets import (
    SheetsManager,
    get_next_lesson_date_after,
    get_sheets_manager,
    parse_weekdays,
)

logger = logging.getLogger(__name__)

TIME_RE = re.compile(r"^(\d{1,2})[:.](\d{2})$")


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


def _parse_int_chat_id(raw: Any) -> Optional[int]:
    val = str(raw or "").strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _parse_lesson_time(raw: str) -> Optional[time]:
    match = TIME_RE.match((raw or "").strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour=hour, minute=minute)
    return None


def _collect_parent_chat_ids(
    student: dict[str, Any], exclude_chat_id: Optional[int] = None
) -> list[int]:
    parent_ids: list[int] = []
    for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
        cid = _parse_int_chat_id(student.get(col))
        if cid is not None and cid != exclude_chat_id and cid not in parent_ids:
            parent_ids.append(cid)
    return parent_ids


async def _safe_send_message(
    bot: Bot,
    chat_id: int | str,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    parsed_id = _parse_int_chat_id(chat_id)
    if parsed_id is None:
        return False
    try:
        await bot.send_message(
            chat_id=parsed_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after + 0.5)
        try:
            await bot.send_message(
                chat_id=parsed_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return True
        except Exception as retry_err:
            logger.warning("Failed retry send_message to %s: %s", parsed_id, retry_err)
            return False
    except (TelegramForbiddenError, TelegramBadRequest) as exc:
        logger.warning("Cannot send message to %s: %s", parsed_id, exc)
        return False
    except Exception as exc:
        logger.exception("Unexpected error sending message to %s: %s", parsed_id, exc)
        return False


def _extract_latest_cycle_completion_data(
    sheets: SheetsManager,
    group_name: str,
    reference_date: date,
) -> tuple[Optional[str], date, list[str]]:
    """
    Finds the latest cycle block for `group_name`, returning:
    (cycle_title, last_calendar_date, unpaid_student_ids).
    """
    with sheets._lock:
        ss = sheets._get_spreadsheet()
        for year_candidate in (reference_date.year, reference_date.year - 1):
            sheet_title = f"{group_name.strip()}_{year_candidate}"
            try:
                ws = ss.worksheet(sheet_title)
            except Exception:
                continue
            cycles = sheets.parse_cycles_from_sheet(ws)
            if not cycles:
                continue
            cycle = cycles[-1]
            cycle_title = cycle["title"].strip()

            prev_d: Optional[date] = None
            running_year = year_candidate
            for dc in cycle["date_columns"]:
                try:
                    d_val, m_val = map(int, dc["date_str"].split("."))
                except ValueError:
                    continue
                if prev_d and m_val < prev_d.month:
                    running_year += 1
                prev_d = date(running_year, m_val, d_val)

            paid_ids = {
                row["student_id"].strip()
                for row in cycle["student_rows"]
                if (
                    "✅" in row.get("payment_status", "")
                    or "to'langan" in row.get("payment_status", "").lower()
                )
                and "to'lanmagan" not in row.get("payment_status", "").lower()
            }
            active_students = sheets.get_all_students(
                group_name=group_name, active_only=True
            )
            unpaid_ids = [
                s["Talaba_ID"].strip()
                for s in active_students
                if s["Talaba_ID"].strip() not in paid_ids
            ]
            last_date = (
                prev_d if (prev_d and prev_d > reference_date) else reference_date
            )
            return cycle_title, last_date, unpaid_ids

    return None, reference_date, []


# ----------------------------------------------------------------------
# 1. Cycle Completion Processor (safety net & shared notification logic)
# ----------------------------------------------------------------------


async def handle_cycle_completion(
    bot: Bot,
    sheets: SheetsManager,
    group: dict[str, Any],
    cycle_title: str,
    last_cycle_date: date,
    unpaid_ids: list[str],
) -> None:
    group_name = group.get("Guruh_Nomi", "").strip()
    if not group_name:
        return

    for uid in unpaid_ids:
        await asyncio.to_thread(sheets.add_debt_cycle, uid, cycle_title)

    await asyncio.to_thread(sheets.reset_group_lesson_counter, group_name)
    await upsert_group_counter(group_name, lesson_count=0)

    lesson_days = parse_weekdays(group.get("Dars_Kunlari", ""))
    next_cycle_info: Optional[dict[str, Any]] = None
    if lesson_days:
        next_start_date = get_next_lesson_date_after(last_cycle_date, lesson_days)
        next_cycle_info = await asyncio.to_thread(
            sheets.create_cycle_table, group_name, next_start_date
        )

    card_number, card_owner = _get_payment_card_info()
    grp_escaped = html.escape(group_name)
    cyc_escaped = html.escape(cycle_title)
    card_esc = html.escape(card_number)
    owner_esc = html.escape(card_owner)

    # Group Telegram chat reminder (Latin script)
    group_tg_chat_id = _parse_int_chat_id(group.get("Guruh_TG_Chat_ID"))
    if group_tg_chat_id:
        group_msg = (
            "🔔 <b>O‘quv oyi yakunlandi!</b>\n\n"
            f"📚 Guruh: <b>{grp_escaped}</b>\n"
            f"🗓 Davr: <b>{cyc_escaped}</b>\n\n"
            "Navbatdagi darslar uchun oylik to‘lovni o‘z vaqtida amalga oshirishingizni so‘raymiz.\n\n"
            f"💳 To‘lov uchun karta: <code>{card_esc}</code>\n"
            f"👤 Karta egasi: <b>{owner_esc}</b>"
        )
        await _safe_send_message(bot, group_tg_chat_id, group_msg)

    students = await asyncio.to_thread(
        sheets.get_all_students, group_name=group_name, active_only=False
    )
    students_by_id = {s["Talaba_ID"].strip(): s for s in students}

    # Student + Father + Mother payment reminders for unpaid students
    for uid in unpaid_ids:
        student = students_by_id.get(uid)
        if not student:
            continue
        stu_name = html.escape(student.get("F.I.O.", "").strip() or uid)

        stu_chat_id = _parse_int_chat_id(student.get("Talaba_Chat_ID"))
        if stu_chat_id:
            s_lang = await get_user_lang(stu_chat_id)
            await _safe_send_message(
                bot,
                stu_chat_id,
                t(
                    "cycle_completed_remind_student",
                    s_lang,
                    group=grp_escaped,
                    cycle_title=cyc_escaped,
                    card_number=card_esc,
                    card_owner=owner_esc,
                ),
            )

        for par_chat_id in _collect_parent_chat_ids(student, stu_chat_id):
            p_lang = await get_user_lang(par_chat_id)
            await _safe_send_message(
                bot,
                par_chat_id,
                t(
                    "cycle_completed_remind_parent",
                    p_lang,
                    student_name=stu_name,
                    group=grp_escaped,
                    cycle_title=cyc_escaped,
                    card_number=card_esc,
                    card_owner=owner_esc,
                ),
            )

    # Teacher report
    ustoz_chat_id = _parse_int_chat_id(group.get("Ustoz_Chat_ID"))
    if not ustoz_chat_id and ADMIN_IDS:
        ustoz_chat_id = ADMIN_IDS[0]
    if ustoz_chat_id and next_cycle_info:
        u_lang = await get_user_lang(ustoz_chat_id)
        await _safe_send_message(
            bot,
            ustoz_chat_id,
            t(
                "cycle_completed_report_teacher",
                u_lang,
                group=grp_escaped,
                cycle_title=cyc_escaped,
                next_cycle_title=html.escape(next_cycle_info["cycle_title"]),
            ),
        )


async def process_completed_cycles(bot: Bot) -> None:
    now_date = datetime.now(TZ).date()
    sheets = get_sheets_manager()
    try:
        groups = await asyncio.to_thread(sheets.get_all_groups)
    except Exception as exc:
        logger.exception("Failed loading groups for cycle check: %s", exc)
        return

    for group in groups:
        group_name = group.get("Guruh_Nomi", "").strip()
        if not group_name:
            continue
        try:
            current_count = int(group.get("Otilgan_Dars_Hisoblagich") or 0)
            limit = int(group.get("Oylik_Dars_Soni") or 12)
        except ValueError:
            continue
        if limit <= 0 or current_count < limit:
            continue

        try:
            cycle_title, last_date, unpaid_ids = await asyncio.to_thread(
                _extract_latest_cycle_completion_data, sheets, group_name, now_date
            )
            if not cycle_title:
                continue
            await handle_cycle_completion(
                bot=bot,
                sheets=sheets,
                group=group,
                cycle_title=cycle_title,
                last_cycle_date=last_date,
                unpaid_ids=unpaid_ids,
            )
        except Exception as exc:
            logger.exception(
                "Error advancing completed cycle for %s: %s", group_name, exc
            )


# ----------------------------------------------------------------------
# 2. Smart 2-Tier Lesson Reminders (every 1 minute)
# ----------------------------------------------------------------------


async def process_lesson_reminders(bot: Bot) -> None:
    now = datetime.now(TZ)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    sheets = get_sheets_manager()

    try:
        groups = await asyncio.to_thread(sheets.get_all_groups)
    except Exception as exc:
        logger.exception("Failed loading groups for reminders: %s", exc)
        return

    for group in groups:
        group_name = group.get("Guruh_Nomi", "").strip()
        if not group_name:
            continue

        lesson_days = parse_weekdays(group.get("Dars_Kunlari", ""))
        lesson_time = _parse_lesson_time(group.get("Dars_Vaqti", ""))
        if not lesson_days or lesson_time is None:
            continue

        time_str = lesson_time.strftime("%H:%M")
        counter = await get_group_counter(group_name)
        last_reminded = counter.get("last_reminded_date") if counter else None
        last_1h_reminded = counter.get("last_1h_reminded_date") if counter else None

        active_students: Optional[list[dict[str, Any]]] = None

        async def _get_active_students() -> list[dict[str, Any]]:
            nonlocal active_students
            if active_students is None:
                active_students = await asyncio.to_thread(
                    sheets.get_all_students, group_name, True
                )
            return active_students

        # --- Tier 1: Advance reminder (Group chat in Latin + Active students in saved lang) ---
        target_advance_date: Optional[date] = None
        reminder_key: Optional[str] = None

        if lesson_time < time(10, 0):
            if (
                tomorrow.weekday() in lesson_days
                and time(20, 0) <= now.time() < time(20, 15)
                and last_reminded != tomorrow.isoformat()
            ):
                target_advance_date = tomorrow
                reminder_key = "reminder_evening_before"
        else:
            if (
                today.weekday() in lesson_days
                and time(8, 0) <= now.time() < time(8, 15)
                and last_reminded != today.isoformat()
            ):
                target_advance_date = today
                reminder_key = "reminder_morning_today"

        if target_advance_date and reminder_key:
            group_tg_id = _parse_int_chat_id(group.get("Guruh_TG_Chat_ID"))
            if group_tg_id:
                await _safe_send_message(
                    bot,
                    group_tg_id,
                    t(
                        reminder_key,
                        "latn",
                        group=html.escape(group_name),
                        time=time_str,
                    ),
                )

            for student in await _get_active_students():
                stu_chat_id = _parse_int_chat_id(student.get("Talaba_Chat_ID"))
                if stu_chat_id:
                    s_lang = await get_user_lang(stu_chat_id)
                    await _safe_send_message(
                        bot,
                        stu_chat_id,
                        t(
                            reminder_key,
                            s_lang,
                            group=html.escape(group_name),
                            time=time_str,
                        ),
                    )

            await upsert_group_counter(
                group_name, last_reminded_date=target_advance_date.isoformat()
            )

        # --- Tier 2: 1 hour before lesson start (Active students only) ---
        if today.weekday() in lesson_days and last_1h_reminded != today.isoformat():
            lesson_dt = datetime.combine(today, lesson_time, tzinfo=TZ)
            seconds_until_lesson = (lesson_dt - now).total_seconds()
            if 3300 <= seconds_until_lesson <= 3660:
                for student in await _get_active_students():
                    stu_chat_id = _parse_int_chat_id(student.get("Talaba_Chat_ID"))
                    if stu_chat_id:
                        s_lang = await get_user_lang(stu_chat_id)
                        await _safe_send_message(
                            bot,
                            stu_chat_id,
                            t(
                                "reminder_1h_before",
                                s_lang,
                                group=html.escape(group_name),
                                time=time_str,
                            ),
                        )
                await upsert_group_counter(
                    group_name, last_1h_reminded_date=today.isoformat()
                )


# ----------------------------------------------------------------------
# 3. 1-Day-Ahead Polite Teacher Topic Reminder (Daily at 18:00 Asia/Tashkent)
# ----------------------------------------------------------------------


async def teacher_topic_reminder(bot: Bot) -> None:
    now = datetime.now(TZ)
    tomorrow = now.date() + timedelta(days=1)
    tomorrow_date_str = tomorrow.strftime("%d.%m")
    tomorrow_iso = tomorrow.isoformat()
    sheets = get_sheets_manager()

    try:
        groups = await asyncio.to_thread(sheets.get_all_groups)
    except Exception as exc:
        logger.exception("Failed loading groups for teacher topic reminder: %s", exc)
        return

    for group in groups:
        group_name = group.get("Guruh_Nomi", "").strip()
        if not group_name:
            continue

        lesson_days = parse_weekdays(group.get("Dars_Kunlari", ""))
        if tomorrow.weekday() not in lesson_days:
            continue

        ustoz_chat_id = _parse_int_chat_id(group.get("Ustoz_Chat_ID"))
        if not ustoz_chat_id:
            continue

        existing_topic = await get_lesson_topic(
            group_name, tomorrow_date_str
        ) or await get_lesson_topic(group_name, tomorrow_iso)
        if existing_topic and (
            existing_topic.get("topic") or existing_topic.get("topic_title")
        ):
            continue

        t_lang = await get_user_lang(ustoz_chat_id)
        teacher_rec = await sheets.a_get_teacher_by_chat_id(ustoz_chat_id)
        db_teacher = await get_teacher_by_telegram_id(ustoz_chat_id)
        db_user = await get_user(ustoz_chat_id)
        teacher_name = (
            (teacher_rec.get("F.I.O.") if teacher_rec else "")
            or (db_teacher.get("full_name") if db_teacher else "")
            or (db_user.get("full_name") if db_user else "")
            or ("Устоз" if t_lang == "cyrl" else "Ustoz")
        )

        tomorrow_formatted = format_uz_date(tomorrow_date_str, t_lang)
        if t_lang == "cyrl":
            msg_text = (
                f"Ассалому алайкум, ҳурматли <b>{html.escape(teacher_name)}</b> устоз!\n\n"
                f"Эртага ({html.escape(tomorrow_formatted)}) «<b>{html.escape(group_name)}</b>» "
                f"гуруҳида дарсингиз бор.\n"
                f"Талабалар ва ота-оналар олдиндан тайёрланишлари учун эртанги дарс "
                f"мавзуси ва режасини киритиб қўйишингизни илтимос қиламиз."
            )
        else:
            msg_text = (
                f"Assalomu alaykum, hurmatli <b>{html.escape(teacher_name)}</b> ustoz!\n\n"
                f"Ertaga ({html.escape(tomorrow_formatted)}) «<b>{html.escape(group_name)}</b>» "
                f"guruhida darsingiz bor.\n"
                f"Talabalar va ota-onalar oldindan tayyorlanishlari uchun ertangi dars "
                f"mavzusi va rejasini kiritib qo'yishingizni iltimos qilamiz."
            )

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("btn_enter_topic_plan", t_lang),
                        callback_data=f"enter_topic:{group_name}:{tomorrow_date_str}",
                    )
                ]
            ]
        )
        await _safe_send_message(bot, ustoz_chat_id, msg_text, reply_markup=kb)


# ----------------------------------------------------------------------
# 4. Weekly Debt Reminder (Every Monday at 10:00 Asia/Tashkent)
#    Sends to Group chat + Student + Father + Mother with tap-to-copy card
# ----------------------------------------------------------------------


async def weekly_debt_reminder(bot: Bot) -> None:
    sheets = get_sheets_manager()
    try:
        debtors = await asyncio.to_thread(sheets.get_debtors)
        groups = await asyncio.to_thread(sheets.get_all_groups)
    except Exception as exc:
        logger.exception("Failed fetching debtors/groups for weekly reminder: %s", exc)
        return

    card_number, card_owner = _get_payment_card_info()
    card_esc = html.escape(card_number)
    owner_esc = html.escape(card_owner)

    groups_by_lower = {
        g.get("Guruh_Nomi", "").strip().lower(): g
        for g in groups
        if g.get("Guruh_Nomi", "").strip()
    }
    debtors_by_group: dict[str, list[dict[str, Any]]] = {}

    for student in debtors:
        debts = student.get("Qarzdor_Oylar", "").strip()
        if not debts:
            continue

        group_raw = student.get("Guruh", "").strip()
        student_name = html.escape(student.get("F.I.O.", "").strip())
        group_escaped = html.escape(group_raw)
        debts_escaped = html.escape(debts)

        if group_raw:
            debtors_by_group.setdefault(group_raw.lower(), []).append(student)

        # 1) Student DM
        stu_chat_id = _parse_int_chat_id(student.get("Talaba_Chat_ID"))
        if stu_chat_id:
            s_lang = await get_user_lang(stu_chat_id)
            await _safe_send_message(
                bot,
                stu_chat_id,
                t(
                    "reminder_weekly_debt_student",
                    s_lang,
                    student_name=student_name,
                    group=group_escaped,
                    debts=debts_escaped,
                    card_number=card_esc,
                    card_owner=owner_esc,
                ),
            )

        # 2) Father & Mother DMs (plus OtaOna_Chat_ID fallback if distinct)
        for par_chat_id in _collect_parent_chat_ids(student, stu_chat_id):
            p_lang = await get_user_lang(par_chat_id)
            await _safe_send_message(
                bot,
                par_chat_id,
                t(
                    "reminder_weekly_debt_parent",
                    p_lang,
                    student_name=student_name,
                    group=group_escaped,
                    debts=debts_escaped,
                    card_number=card_esc,
                    card_owner=owner_esc,
                ),
            )

    # 3) Group Telegram Chat reminder (Latin script, tap-to-copy card)
    for grp_key, grp_debtors in debtors_by_group.items():
        grp = groups_by_lower.get(grp_key)
        if not grp:
            continue
        group_tg_id = _parse_int_chat_id(grp.get("Guruh_TG_Chat_ID"))
        if not group_tg_id:
            continue

        canonical_group = html.escape(grp.get("Guruh_Nomi", "").strip())
        debtor_lines = "\n".join(
            f"• <b>{html.escape(d.get('F.I.O.', '').strip())}</b> — "
            f"<i>{html.escape(d.get('Qarzdor_Oylar', '').strip())}</i>"
            for d in grp_debtors
        )
        group_msg = (
            "⚠️ <b>Haftalik to‘lov eslatmasi</b>\n\n"
            f"📚 Guruh: <b>{canonical_group}</b>\n\n"
            f"To‘lov muddati kelgan talabalar:\n{debtor_lines}\n\n"
            "Iltimos, oylik to‘lovni o‘z vaqtida amalga oshiring.\n\n"
            f"💳 To‘lov uchun karta: <code>{card_esc}</code>\n"
            f"👤 Karta egasi: <b>{owner_esc}</b>"
        )
        await _safe_send_message(bot, group_tg_id, group_msg)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TZ)

    scheduler.add_job(
        process_lesson_reminders,
        trigger=IntervalTrigger(minutes=1, timezone=TZ),
        args=[bot],
        id="process_lesson_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_completed_cycles,
        trigger=IntervalTrigger(minutes=1, timezone=TZ),
        args=[bot],
        id="process_completed_cycles",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        teacher_topic_reminder,
        trigger=CronTrigger(hour=18, minute=0, timezone=TZ),
        args=[bot],
        id="teacher_topic_reminder",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        weekly_debt_reminder,
        trigger=CronTrigger(day_of_week="mon", hour=10, minute=0, timezone=TZ),
        args=[bot],
        id="weekly_debt_reminder",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    return scheduler