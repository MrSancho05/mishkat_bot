import asyncio
import html
import logging
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

import aiosqlite
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
from app.utils import (
    dual_role_header,
    get_lesson_time_for_weekday,
    now_tashkent,
    today_tashkent,
)
from app.config import ADMIN_IDS, DB_PATH, TZ
from app.database import (
    claim_group_initial_notice,
    claim_group_weekly_reminder,
    current_iso_week,
    ensure_group_initial_due,
    get_group_counter,
    get_group_reminder_state,
    list_due_initial_group_notices,
    release_group_initial_notice,
    release_group_weekly_reminder,
    get_cycle_overrides_for_students,
    get_unpaid_legacy_debts_map,
    get_lesson_topic,
    get_teacher_by_telegram_id,
    get_user,
    get_user_lang,
    has_dual_student_parent_role,
    mark_topics_published,
    upsert_group_counter,
)
from app.debt_view import (
    build_debt_notice,
    compute_children_debts,
    format_cycle_title,
    send_expandable_notice,
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


def _parse_int_chat_id(raw: Any) -> Optional[int]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw != 0 else None
    if isinstance(raw, float):
        try:
            int_val = int(raw)
            return int_val if int_val != 0 and float(int_val) == raw else None
        except (ValueError, OverflowError):
            return None
    val = str(raw).strip()
    if not val or val == "Ma'lumot kiritilmagan":
        return None
    if re.fullmatch(r"-?\d+(?:\.0+)?", val):
        int_val = int(val.split(".", 1)[0])
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


def _parse_lesson_time(raw: str) -> Optional[time]:
    match = TIME_RE.match((raw or "").strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return time(hour=hour, minute=minute)
    return None


def _collect_parent_chat_ids(
    student: dict[str, Any],
    exclude_chat_id: Optional[int] = None,
    phone_to_parent_cids: Optional[dict[str, set[int]]] = None,
) -> list[int]:
    parent_ids: list[int] = []
    for chat_col, tel_col in (
        ("Otasi_Chat_ID", "Otasi_Tel"),
        ("Onasi_Chat_ID", "Onasi_Tel"),
        ("OtaOna_Chat_ID", "OtaOna_Tel"),
    ):
        cid = _parse_int_chat_id(student.get(chat_col))
        if cid is not None:
            if cid != exclude_chat_id and cid not in parent_ids:
                parent_ids.append(cid)
        elif phone_to_parent_cids:
            p_key = _normalize_phone_key(student.get(tel_col))
            if p_key and p_key in phone_to_parent_cids:
                for p_cid in sorted(phone_to_parent_cids[p_key]):
                    if p_cid != exclude_chat_id and p_cid not in parent_ids:
                        parent_ids.append(p_cid)
    return parent_ids


def _build_phone_parent_map(
    students: list[dict[str, Any]],
) -> dict[str, set[int]]:
    phone_map: dict[str, set[int]] = {}
    for row in students:
        for chat_col, tel_col in (
            ("Otasi_Chat_ID", "Otasi_Tel"),
            ("Onasi_Chat_ID", "Onasi_Tel"),
            ("OtaOna_Chat_ID", "OtaOna_Tel"),
        ):
            cid = _parse_int_chat_id(row.get(chat_col))
            p_key = _normalize_phone_key(row.get(tel_col))
            if cid is not None and p_key:
                phone_map.setdefault(p_key, set()).add(cid)
    return phone_map


def _center_signature(lang: str) -> str:
    if lang == "cyrl":
        return "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
    return "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"


def _teacher_signature(teacher_name: str, lang: str) -> str:
    return t("topic_teacher_footer", lang, teacher_name=html.escape(teacher_name))


def _safe_limit_message(text: str, limit: int = 4085) -> str:
    if len(text) <= limit:
        return text
    lines: list[str] = []
    cur = 0
    for line in text.split("\n"):
        add = len(line) + (1 if lines else 0)
        if cur + add > limit - 4:
            break
        lines.append(line)
        cur += add
    return "\n".join(lines) + "\n..."


async def _safe_send_message(
    bot: Bot,
    chat_id: int | str,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    parsed_id = _parse_int_chat_id(chat_id)
    if parsed_id is None:
        return False
    safe_text = _safe_limit_message(text, limit=4085)
    try:
        await bot.send_message(
            chat_id=parsed_id,
            text=safe_text,
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
                text=safe_text,
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
    with sheets._lock:
        ss = sheets._get_spreadsheet()
        for year_candidate in (reference_date.year, reference_date.year - 1):
            try:
                ws = sheets._open_group_year_ws(ss, group_name, year_candidate)
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
# 1. Cycle Completion Processor (Aggregated 1 Message per Parent)
# ----------------------------------------------------------------------


def _format_cycle_parent_combined_message(
    items: list[dict[str, Any]],
    lang: str,
    card_number: str,
    card_owner: str,
    has_dual_role: bool,
) -> str:
    prefix = (
        dual_role_header("parent", lang, [str(it.get("student_name") or "") for it in items])
        if has_dual_role
        else ""
    )
    currency = "сўм" if lang == "cyrl" else "so‘m"

    grouped: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        key = f"{it['group_name'].strip().lower()}||{it['cycle_title'].strip().lower()}"
        grouped.setdefault(key, []).append(it)

    blocks: list[str] = []
    grand_total = 0

    for grp_items in grouped.values():
        first = grp_items[0]
        group_name = first["group_name"]
        cycle_title = first["cycle_title"]
        fee = int(first["monthly_fee"])
        count = len(grp_items)
        # Prorated ("🆕 Bugundan qo‘shildi") children owe their custom amount for
        # the cycle that just ended; everyone else owes the full monthly fee.
        amounts = [
            int(it["amount"]) if it.get("amount") is not None else int(it["monthly_fee"])
            for it in grp_items
        ]
        sub_total = sum(amounts)
        uniform_fee = all(a == fee for a in amounts)
        grand_total += sub_total

        seen_names: list[str] = []
        for it in grp_items:
            nm = str(it["student_name"]).strip()
            if nm and nm not in seen_names:
                seen_names.append(nm)
        names_str = ", ".join(html.escape(n) for n in seen_names)

        if count > 1:
            money = (
                f"{count} × {_format_uzs(fee)} = {_format_uzs(sub_total)} {currency}"
                if uniform_fee
                else f"{_format_uzs(sub_total)} {currency}"
            )
            if lang == "cyrl":
                blocks.append(
                    f"👶 Фарзандларингиз: <b>{names_str}</b>\n"
                    f"📚 Гуруҳ: <b>{html.escape(group_name)}</b>\n"
                    f"🗓 Якунланган давр: <b>{html.escape(cycle_title)}</b>\n"
                    f"💰 Ойлик тўлов: <b>{money}</b>"
                )
            else:
                blocks.append(
                    f"👶 Farzandlaringiz: <b>{names_str}</b>\n"
                    f"📚 Guruh: <b>{html.escape(group_name)}</b>\n"
                    f"🗓 Yakunlangan davr: <b>{html.escape(cycle_title)}</b>\n"
                    f"💰 Oylik to‘lov: <b>{money}</b>"
                )
        else:
            if lang == "cyrl":
                blocks.append(
                    f"👶 Фарзандингиз: <b>{names_str}</b>\n"
                    f"📚 Гуруҳ: <b>{html.escape(group_name)}</b>\n"
                    f"🗓 Якунланган давр: <b>{html.escape(cycle_title)}</b>\n"
                    f"💰 Ойлик тўлов: <b>{_format_uzs(sub_total)} {currency}</b>"
                )
            else:
                blocks.append(
                    f"👶 Farzandingiz: <b>{names_str}</b>\n"
                    f"📚 Guruh: <b>{html.escape(group_name)}</b>\n"
                    f"🗓 Yakunlangan davr: <b>{html.escape(cycle_title)}</b>\n"
                    f"💰 Oylik to‘lov: <b>{_format_uzs(sub_total)} {currency}</b>"
                )

    header = (
        "🔔 <b>Ўқув ойи якунланди!</b>"
        if lang == "cyrl"
        else "🔔 <b>O‘quv oyi yakunlandi!</b>"
    )
    notice = (
        "Илтимос, навбатдаги ойлик тўловни ўз вақтида амалга оширинг."
        if lang == "cyrl"
        else "Iltimos, navbatdagi oylik to‘lovni o‘z vaqtida amalga oshiring."
    )
    total_line = (
        f"\n💵 Умумий тўлов суммаси: <b>{_format_uzs(grand_total)} {currency}</b>"
        if len(grouped) > 1
        else ""
    )
    card_block = t(
        "payment_card_block",
        lang,
        card_number=html.escape(card_number),
        card_owner=html.escape(card_owner),
    )

    body = "\n\n━━━━━━━━━━━━━━\n\n".join(blocks)
    return (
        f"{prefix}{header}\n\n"
        f"{body}{total_line}\n\n"
        f"{notice}\n\n"
        f"{card_block}\n\n"
        f"{_center_signature(lang)}"
    )


async def handle_cycle_completion(
    bot: Bot,
    sheets: SheetsManager,
    group: dict[str, Any],
    cycle_title: str,
    last_cycle_date: date,
    unpaid_ids: list[str],
    defer_parent_payloads: Optional[dict[int, list[dict[str, Any]]]] = None,
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
    monthly_fee = _parse_group_fee(group)
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
    all_students = await asyncio.to_thread(sheets.get_all_students, None, False)
    phone_map = _build_phone_parent_map(all_students)

    local_parent_payloads: dict[int, list[dict[str, Any]]] = (
        defer_parent_payloads if defer_parent_payloads is not None else {}
    )
    cycle_overrides = await get_cycle_overrides_for_students(list(unpaid_ids))

    def _owed_amount(student_id: str) -> int:
        for ov in cycle_overrides.get(student_id, []):
            if (
                ov["cycle_title"] == str(cycle_title or "").strip()
                and ov["group_name"] == group_name.strip().lower()
            ):
                return int(ov["custom_amount"])
        return monthly_fee

    for uid in unpaid_ids:
        student = students_by_id.get(uid)
        if not student:
            continue
        stu_name_raw = student.get("F.I.O.", "").strip() or uid

        stu_chat_id = _parse_int_chat_id(student.get("Talaba_Chat_ID"))
        parent_cids = _collect_parent_chat_ids(
            student, exclude_chat_id=stu_chat_id, phone_to_parent_cids=phone_map
        )

        if stu_chat_id and stu_chat_id not in parent_cids:
            s_lang = await get_user_lang(stu_chat_id)
            s_prefix = (
                dual_role_header("student", s_lang)
                if await has_dual_student_parent_role(stu_chat_id)
                else ""
            )
            await _safe_send_message(
                bot,
                stu_chat_id,
                s_prefix
                + t(
                    "cycle_completed_remind_student",
                    s_lang,
                    group=grp_escaped,
                    cycle_title=cyc_escaped,
                    card_number=card_esc,
                    card_owner=owner_esc,
                ),
            )

        for par_chat_id in parent_cids:
            bucket = local_parent_payloads.setdefault(par_chat_id, [])
            if not any(
                x["student_id"] == uid and x["group_name"].lower() == group_name.lower()
                for x in bucket
            ):
                bucket.append(
                    {
                        "student_id": uid,
                        "student_name": stu_name_raw,
                        "group_name": group_name,
                        "cycle_title": cycle_title,
                        "monthly_fee": monthly_fee,
                        "amount": _owed_amount(uid),
                    }
                )

    if defer_parent_payloads is None:
        for par_chat_id, p_items in local_parent_payloads.items():
            p_lang = await get_user_lang(par_chat_id)
            is_dual = await has_dual_student_parent_role(par_chat_id)
            combined = _format_cycle_parent_combined_message(
                items=p_items,
                lang=p_lang,
                card_number=card_number,
                card_owner=card_owner,
                has_dual_role=is_dual,
            )
            await _safe_send_message(bot, par_chat_id, combined)

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
    now_date = today_tashkent()
    sheets = get_sheets_manager()
    try:
        groups = await asyncio.to_thread(sheets.get_all_groups)
    except Exception as exc:
        logger.exception("Failed loading groups for cycle check: %s", exc)
        return

    parent_payloads: dict[int, list[dict[str, Any]]] = {}

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
            if cycle_title:
                await handle_cycle_completion(
                    bot=bot,
                    sheets=sheets,
                    group=group,
                    cycle_title=cycle_title,
                    last_cycle_date=last_date,
                    unpaid_ids=unpaid_ids,
                    defer_parent_payloads=parent_payloads,
                )
        except Exception as exc:
            logger.exception(
                "Error advancing completed cycle for %s: %s", group_name, exc
            )
        await asyncio.sleep(0.3)

    card_number, card_owner = _get_payment_card_info()
    for par_chat_id, p_items in parent_payloads.items():
        p_lang = await get_user_lang(par_chat_id)
        is_dual = await has_dual_student_parent_role(par_chat_id)
        combined = _format_cycle_parent_combined_message(
            items=p_items,
            lang=p_lang,
            card_number=card_number,
            card_owner=card_owner,
            has_dual_role=is_dual,
        )
        await _safe_send_message(bot, par_chat_id, combined)


# ----------------------------------------------------------------------
# 2. Smart 2-Tier Lesson Reminders (Aggregated 1 Parent = 1 Message)
# ----------------------------------------------------------------------


def _format_lesson_parent_combined_message(
    items: list[dict[str, Any]],
    lang: str,
    has_dual_role: bool,
) -> str:
    prefix = (
        dual_role_header("parent", lang, [str(it.get("student_name") or "") for it in items])
        if has_dual_role
        else ""
    )

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for it in items:
        key = (
            it["group_name"].strip().lower(),
            it["reminder_key"],
            it["time_str"],
        )
        grouped.setdefault(key, []).append(it)

    blocks: list[str] = []
    for grp_items in grouped.values():
        first = grp_items[0]
        group_name = first["group_name"]
        reminder_key = first["reminder_key"]
        time_str = first["time_str"]

        seen_names: list[str] = []
        for it in grp_items:
            nm = str(it["student_name"]).strip()
            if nm and nm not in seen_names:
                seen_names.append(nm)
        names_str = ", ".join(html.escape(n) for n in seen_names)

        if len(seen_names) > 1:
            child_line = (
                f"👶 Фарзандларингиз: <b>{names_str}</b>"
                if lang == "cyrl"
                else f"👶 Farzandlaringiz: <b>{names_str}</b>"
            )
        else:
            child_line = (
                f"👶 Фарзандингиз: <b>{names_str}</b>"
                if lang == "cyrl"
                else f"👶 Farzandingiz: <b>{names_str}</b>"
            )

        base_rem = t(
            reminder_key,
            lang,
            group=html.escape(group_name),
            time=time_str,
        )
        blocks.append(f"{child_line}\n{base_rem}")

    body = "\n\n━━━━━━━━━━━━━━\n\n".join(blocks)
    return f"{prefix}{body}\n\n{_center_signature(lang)}"


async def process_lesson_reminders(bot: Bot) -> None:
    now = now_tashkent()
    today = now.date()
    tomorrow = today + timedelta(days=1)
    sheets = get_sheets_manager()

    try:
        groups = await asyncio.to_thread(sheets.get_all_groups)
        all_active_students = await asyncio.to_thread(
            sheets.get_all_students, None, True
        )
    except Exception as exc:
        logger.exception("Failed loading groups/students for reminders: %s", exc)
        return

    phone_map = _build_phone_parent_map(all_active_students)

    students_by_group: dict[str, list[dict[str, Any]]] = {}
    for s in all_active_students:
        g_key = str(s.get("Guruh", "")).strip().lower()
        if g_key:
            students_by_group.setdefault(g_key, []).append(s)

    student_payloads: dict[int, list[dict[str, Any]]] = {}
    parent_payloads: dict[int, list[dict[str, Any]]] = {}

    for group in groups:
        group_name = group.get("Guruh_Nomi", "").strip()
        if not group_name:
            continue

        lesson_days = parse_weekdays(group.get("Dars_Kunlari", ""))
        if not lesson_days:
            continue

        # Per-day schedules ("Du 14:00, Chor 15:30"): every trigger below uses the
        # exact time of the weekday it refers to (today's for same-day / 1h-before
        # reminders, tomorrow's for the evening-before reminder).
        dars_vaqti = str(group.get("Dars_Vaqti", "") or "")
        today_time = (
            _parse_lesson_time(get_lesson_time_for_weekday(dars_vaqti, today) or "")
            if today.weekday() in lesson_days
            else None
        )
        tomorrow_time = (
            _parse_lesson_time(get_lesson_time_for_weekday(dars_vaqti, tomorrow) or "")
            if tomorrow.weekday() in lesson_days
            else None
        )
        if today_time is None and tomorrow_time is None:
            continue

        counter = await get_group_counter(group_name)
        last_reminded = counter.get("last_reminded_date") if counter else None
        last_1h_reminded = counter.get("last_1h_reminded_date") if counter else None

        active_in_group = students_by_group.get(group_name.lower(), [])
        group_tg_id = _parse_int_chat_id(group.get("Guruh_TG_Chat_ID"))

        # --- Tier 1: Advance reminder ---
        target_advance_date: Optional[date] = None
        reminder_key: Optional[str] = None
        time_str = ""

        if (
            tomorrow_time is not None
            and tomorrow_time < time(10, 0)
            and time(20, 0) <= now.time() < time(20, 15)
            and last_reminded != tomorrow.isoformat()
        ):
            target_advance_date = tomorrow
            reminder_key = "reminder_evening_before"
            time_str = tomorrow_time.strftime("%H:%M")
        elif (
            today_time is not None
            and today_time >= time(10, 0)
            and time(8, 0) <= now.time() < time(8, 15)
            and last_reminded != today.isoformat()
        ):
            target_advance_date = today
            reminder_key = "reminder_morning_today"
            time_str = today_time.strftime("%H:%M")

        if target_advance_date and reminder_key:
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

            for student in active_in_group:
                stu_id = str(student.get("Talaba_ID", "")).strip()
                stu_name = str(student.get("F.I.O.", "")).strip() or stu_id
                stu_chat_id = _parse_int_chat_id(student.get("Talaba_Chat_ID"))
                parent_cids = _collect_parent_chat_ids(
                    student,
                    exclude_chat_id=stu_chat_id,
                    phone_to_parent_cids=phone_map,
                )

                if stu_chat_id and stu_chat_id not in parent_cids:
                    s_bucket = student_payloads.setdefault(stu_chat_id, [])
                    if not any(
                        x["group_name"].lower() == group_name.lower()
                        and x["reminder_key"] == reminder_key
                        for x in s_bucket
                    ):
                        s_bucket.append(
                            {
                                "group_name": group_name,
                                "reminder_key": reminder_key,
                                "time_str": time_str,
                            }
                        )

                for p_cid in parent_cids:
                    p_bucket = parent_payloads.setdefault(p_cid, [])
                    if not any(
                        x["student_id"] == stu_id
                        and x["group_name"].lower() == group_name.lower()
                        and x["reminder_key"] == reminder_key
                        for x in p_bucket
                    ):
                        p_bucket.append(
                            {
                                "student_id": stu_id,
                                "student_name": stu_name,
                                "group_name": group_name,
                                "reminder_key": reminder_key,
                                "time_str": time_str,
                            }
                        )

            await upsert_group_counter(
                group_name, last_reminded_date=target_advance_date.isoformat()
            )

        # --- Tier 2: 1 hour before lesson start ---
        if today_time is not None and last_1h_reminded != today.isoformat():
            time_str = today_time.strftime("%H:%M")
            lesson_dt = datetime.combine(today, today_time, tzinfo=TZ)
            seconds_until_lesson = (lesson_dt - now).total_seconds()
            if 3300 <= seconds_until_lesson <= 3660:
                for student in active_in_group:
                    stu_id = str(student.get("Talaba_ID", "")).strip()
                    stu_name = str(student.get("F.I.O.", "")).strip() or stu_id
                    stu_chat_id = _parse_int_chat_id(student.get("Talaba_Chat_ID"))
                    parent_cids = _collect_parent_chat_ids(
                        student,
                        exclude_chat_id=stu_chat_id,
                        phone_to_parent_cids=phone_map,
                    )

                    if stu_chat_id and stu_chat_id not in parent_cids:
                        s_bucket = student_payloads.setdefault(stu_chat_id, [])
                        if not any(
                            x["group_name"].lower() == group_name.lower()
                            and x["reminder_key"] == "reminder_1h_before"
                            for x in s_bucket
                        ):
                            s_bucket.append(
                                {
                                    "group_name": group_name,
                                    "reminder_key": "reminder_1h_before",
                                    "time_str": time_str,
                                }
                            )

                    for p_cid in parent_cids:
                        p_bucket = parent_payloads.setdefault(p_cid, [])
                        if not any(
                            x["student_id"] == stu_id
                            and x["group_name"].lower() == group_name.lower()
                            and x["reminder_key"] == "reminder_1h_before"
                            for x in p_bucket
                        ):
                            p_bucket.append(
                                {
                                    "student_id": stu_id,
                                    "student_name": stu_name,
                                    "group_name": group_name,
                                    "reminder_key": "reminder_1h_before",
                                    "time_str": time_str,
                                }
                            )

                await upsert_group_counter(
                    group_name, last_1h_reminded_date=today.isoformat()
                )

    # Flush student DMs (1 message per student)
    for stu_cid, s_items in student_payloads.items():
        s_lang = await get_user_lang(stu_cid)
        s_prefix = (
            dual_role_header("student", s_lang)
            if await has_dual_student_parent_role(stu_cid)
            else ""
        )
        blocks = [
            t(
                it["reminder_key"],
                s_lang,
                group=html.escape(it["group_name"]),
                time=it["time_str"],
            )
            for it in s_items
        ]
        combined_stu = f"{s_prefix}" + "\n\n━━━━━━━━━━━━━━\n\n".join(blocks)
        await _safe_send_message(bot, stu_cid, combined_stu)

    # Flush parent DMs (Strictly 1 message per parent)
    for p_cid, p_items in parent_payloads.items():
        p_lang = await get_user_lang(p_cid)
        is_dual = await has_dual_student_parent_role(p_cid)
        combined_par = _format_lesson_parent_combined_message(
            items=p_items, lang=p_lang, has_dual_role=is_dual
        )
        await _safe_send_message(bot, p_cid, combined_par)


# ----------------------------------------------------------------------
# 3. 30-Minute Auto-Publish Lesson Topics (1 Parent = 1 Message)
# ----------------------------------------------------------------------


def _parse_topic_timestamp(raw_ts: Any) -> Optional[datetime]:
    val = str(raw_ts or "").strip()
    if not val:
        return None
    normalized = val.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                dt = datetime.strptime(val, fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None

    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc)

    now_utc = now_tashkent().astimezone(timezone.utc).replace(tzinfo=None)
    if dt > now_utc + timedelta(minutes=5):
        return dt.replace(tzinfo=TZ).astimezone(timezone.utc)
    return dt.replace(tzinfo=timezone.utc)


def _fmt_topic_date_str(raw_date: str, lang: str) -> str:
    cleaned = str(raw_date or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        try:
            cleaned = datetime.strptime(cleaned, "%Y-%m-%d").strftime("%d.%m")
        except ValueError:
            pass
    return format_uz_date(cleaned, lang)


def _format_topic_group_block(
    group_name: str,
    topic_rows: list[dict[str, Any]],
    teacher_name: str,
    lang: str,
    children_names: Optional[list[str]] = None,
) -> str:
    modes = {str(r.get("edit_mode") or "new").strip() for r in topic_rows}
    if modes == {"appended"}:
        header = (
            "➕ Мавзуларга қўшимча киритилди"
            if lang == "cyrl"
            else "➕ Mavzularga qo'shimcha kiritildi"
        )
    elif "edited" in modes or ("appended" in modes and "new" not in modes):
        header = (
            "✏️ Дарс мавзуси ўзгартирилди"
            if lang == "cyrl"
            else "✏️ Dars mavzusi o'zgartirildi"
        )
    else:
        header = (
            "📚 Янги дарс мавзуси ва режаси"
            if lang == "cyrl"
            else "📚 Yangi dars mavzusi va rejasi"
        )

    lbl_group = "📚 Гуруҳ:" if lang == "cyrl" else "📚 Guruh:"
    lbl_date = "📅 Сана:" if lang == "cyrl" else "📅 Sana:"
    lbl_topic = "📖 Мавзу:" if lang == "cyrl" else "📖 Mavzu:"
    lbl_plan = (
        "📝 Дарс мазмуни / Уйга вазифа:"
        if lang == "cyrl"
        else "📝 Dars mazmuni / Uyga vazifa:"
    )

    child_header = ""
    if children_names:
        names_escaped = ", ".join(html.escape(n) for n in children_names)
        if len(children_names) > 1:
            child_header = (
                f"👶 Фарзандларингиз: <b>{names_escaped}</b>\n"
                if lang == "cyrl"
                else f"👶 Farzandlaringiz: <b>{names_escaped}</b>\n"
            )
        else:
            child_header = (
                f"👶 Фарзандингиз: <b>{names_escaped}</b>\n"
                if lang == "cyrl"
                else f"👶 Farzandingiz: <b>{names_escaped}</b>\n"
            )

    row_blocks: list[str] = []
    for r in topic_rows:
        d_fmt = _fmt_topic_date_str(str(r.get("lesson_date", "")), lang)
        top_val = str(r.get("topic") or r.get("topic_title") or "—").strip()
        pln_val = str(r.get("plan") or r.get("lesson_details") or "—").strip()
        if len(pln_val) > 600:
            pln_val = pln_val[:597] + "..."
        row_blocks.append(
            f"{lbl_date} <b>{html.escape(d_fmt)}</b>\n"
            f"{lbl_topic} <b>{html.escape(top_val)}</b>\n"
            f"{lbl_plan}\n<i>{html.escape(pln_val)}</i>"
        )

    return (
        f"<b>{html.escape(header)}</b>\n\n"
        f"{child_header}"
        f"{lbl_group} <b>{html.escape(group_name)}</b>\n\n"
        + "\n\n".join(row_blocks)
        + f"\n\n{_teacher_signature(teacher_name, lang)}"
    )


async def _resolve_topic_teacher_name(
    sheets: SheetsManager,
    row_teacher_id: Any,
    fallback_name: str,
    group: Optional[dict[str, Any]],
) -> str:
    if fallback_name and fallback_name.strip():
        return fallback_name.strip()

    tid = _parse_int_chat_id(row_teacher_id)
    if tid:
        try:
            s_tch = await sheets.a_get_teacher_by_chat_id(tid)
            if s_tch and str(s_tch.get("F.I.O.", "")).strip():
                fio = str(s_tch["F.I.O."]).strip()
                if fio != "Ma'lumot kiritilmagan":
                    return fio
        except Exception:
            pass
        db_t = await get_teacher_by_telegram_id(tid)
        if db_t and str(db_t.get("full_name", "")).strip():
            return str(db_t["full_name"]).strip()
        db_u = await get_user(tid)
        if db_u and str(db_u.get("full_name", "")).strip():
            return str(db_u["full_name"]).strip()

    if group:
        g_cid = _parse_int_chat_id(group.get("Ustoz_Chat_ID"))
        if g_cid:
            db_t = await get_teacher_by_telegram_id(g_cid)
            if db_t and str(db_t.get("full_name", "")).strip():
                return str(db_t["full_name"]).strip()
            db_u = await get_user(g_cid)
            if db_u and str(db_u.get("full_name", "")).strip():
                return str(db_u["full_name"]).strip()
        g_tid = str(group.get("Ustoz_ID", "")).strip()
        if g_tid:
            try:
                t_rec = await sheets.a_get_teacher_by_id(g_tid)
                if t_rec and str(t_rec.get("F.I.O.", "")).strip():
                    return str(t_rec["F.I.O."]).strip()
            except Exception:
                pass
    return "Ustoz"


async def auto_publish_pending_topics(bot: Bot) -> None:
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM lesson_topics WHERE COALESCE(is_published, 0) = 0;"
            ) as cur:
                raw_rows = [dict(r) for r in await cur.fetchall()]
    except Exception as exc:
        logger.exception("Failed querying pending lesson topics: %s", exc)
        return

    if not raw_rows:
        return

    now_utc = now_tashkent().astimezone(timezone.utc)
    ready_by_group: dict[str, list[dict[str, Any]]] = {}

    for row in raw_rows:
        ts = _parse_topic_timestamp(row.get("updated_at") or row.get("created_at"))
        if ts is None:
            continue
        if (now_utc - ts).total_seconds() >= 1800:
            grp = str(row.get("group_name") or "").strip()
            if grp:
                ready_by_group.setdefault(grp, []).append(row)

    if not ready_by_group:
        return

    sheets = get_sheets_manager()
    try:
        all_groups = await asyncio.to_thread(sheets.get_all_groups)
        all_active_students = await asyncio.to_thread(
            sheets.get_all_students, None, True
        )
    except Exception as exc:
        logger.exception("Failed loading groups/students for topic auto-publish: %s", exc)
        return

    groups_by_lower = {
        g.get("Guruh_Nomi", "").strip().lower(): g
        for g in all_groups
        if g.get("Guruh_Nomi", "").strip()
    }
    students_by_group: dict[str, list[dict[str, Any]]] = {}
    for s in all_active_students:
        g_key = str(s.get("Guruh", "")).strip().lower()
        if g_key:
            students_by_group.setdefault(g_key, []).append(s)
    phone_map = _build_phone_parent_map(all_active_students)

    student_payloads: dict[int, list[dict[str, Any]]] = {}
    parent_payloads: dict[int, dict[str, dict[str, Any]]] = {}

    for group_name, topic_rows in ready_by_group.items():
        group_key = group_name.lower()
        group = groups_by_lower.get(group_key)
        canonical_name = (
            str(group.get("Guruh_Nomi", "")).strip() if group else group_name
        )
        first_row = topic_rows[0]
        teacher_name = await _resolve_topic_teacher_name(
            sheets,
            first_row.get("teacher_id"),
            str(first_row.get("teacher_name") or ""),
            group,
        )

        # 1. Group Telegram Chat (Latin)
        if group:
            grp_tg_cid = _parse_int_chat_id(group.get("Guruh_TG_Chat_ID"))
            if grp_tg_cid is not None:
                grp_msg = _format_topic_group_block(
                    group_name=canonical_name,
                    topic_rows=topic_rows,
                    teacher_name=teacher_name,
                    lang="latn",
                )
                await _safe_send_message(bot, grp_tg_cid, grp_msg)

        # 2. Collect Students & Parents across all ready groups
        for stu in students_by_group.get(group_key, []):
            stu_id = str(stu.get("Talaba_ID", "")).strip()
            stu_name = str(stu.get("F.I.O.", "")).strip() or stu_id
            stu_cid = _parse_int_chat_id(stu.get("Talaba_Chat_ID"))
            parent_cids = _collect_parent_chat_ids(
                stu, exclude_chat_id=stu_cid, phone_to_parent_cids=phone_map
            )

            if stu_cid and stu_cid not in parent_cids:
                s_bucket = student_payloads.setdefault(stu_cid, [])
                if not any(x["group_key"] == group_key for x in s_bucket):
                    s_bucket.append(
                        {
                            "group_key": group_key,
                            "group_name": canonical_name,
                            "topic_rows": topic_rows,
                            "teacher_name": teacher_name,
                        }
                    )

            for p_cid in parent_cids:
                p_groups = parent_payloads.setdefault(p_cid, {})
                entry = p_groups.setdefault(
                    group_key,
                    {
                        "group_name": canonical_name,
                        "topic_rows": topic_rows,
                        "teacher_name": teacher_name,
                        "children_names": [],
                    },
                )
                if stu_name and stu_name not in entry["children_names"]:
                    entry["children_names"].append(stu_name)

        published_dates = [
            str(r.get("lesson_date", "")).strip()
            for r in topic_rows
            if str(r.get("lesson_date", "")).strip()
        ]
        await mark_topics_published(group_name, lesson_dates=published_dates)

    # Flush Student DMs
    for stu_cid, s_entries in student_payloads.items():
        s_lang = await get_user_lang(stu_cid)
        s_prefix = (
            dual_role_header("student", s_lang)
            if await has_dual_student_parent_role(stu_cid)
            else ""
        )
        s_blocks = [
            _format_topic_group_block(
                group_name=e["group_name"],
                topic_rows=e["topic_rows"],
                teacher_name=e["teacher_name"],
                lang=s_lang,
            )
            for e in s_entries
        ]
        await _safe_send_message(
            bot, stu_cid, f"{s_prefix}" + "\n\n━━━━━━━━━━━━━━\n\n".join(s_blocks)
        )

    # Flush Parent DMs (Strictly 1 combined message per parent)
    for p_cid, grp_map in parent_payloads.items():
        p_lang = await get_user_lang(p_cid)
        p_prefix = (
            dual_role_header(
                "parent",
                p_lang,
                [n for entry in grp_map.values() for n in entry["children_names"]],
            )
            if await has_dual_student_parent_role(p_cid)
            else ""
        )
        p_blocks = [
            _format_topic_group_block(
                group_name=entry["group_name"],
                topic_rows=entry["topic_rows"],
                teacher_name=entry["teacher_name"],
                lang=p_lang,
                children_names=entry["children_names"],
            )
            for entry in grp_map.values()
        ]
        await _safe_send_message(
            bot, p_cid, f"{p_prefix}" + "\n\n━━━━━━━━━━━━━━\n\n".join(p_blocks)
        )


# ----------------------------------------------------------------------
# 4. 1-Day-Ahead Polite Teacher Topic Reminder (Daily at 18:00 Asia/Tashkent)
# ----------------------------------------------------------------------


async def teacher_topic_reminder(bot: Bot) -> None:
    now = now_tashkent()
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
        await asyncio.sleep(0.5)


# ----------------------------------------------------------------------
# 5. Weekly Debt Reminder (Every Monday at 10:00 Asia/Tashkent)
#    Strictly 1 Combined Message per Parent (`parent_payloads`)
# ----------------------------------------------------------------------


def _format_weekly_debt_parent_message(
    items: list[dict[str, Any]],
    lang: str,
    card_number: str,
    card_owner: str,
    has_dual_role: bool,
) -> str:
    prefix = (
        dual_role_header("parent", lang, [str(it.get("student_name") or "") for it in items])
        if has_dual_role
        else ""
    )
    currency = "сўм" if lang == "cyrl" else "so‘m"
    month_unit = "ой" if lang == "cyrl" else "oy"

    grouped: dict[str, list[dict[str, Any]]] = {}
    for it in items:
        grouped.setdefault(it["group_name"].strip().lower(), []).append(it)

    blocks: list[str] = []
    grand_total = 0

    for grp_items in grouped.values():
        group_name = grp_items[0]["group_name"]
        fee = int(grp_items[0]["fee"])
        total_months = sum(int(x["months"]) for x in grp_items)
        group_sum = sum(int(x["total"]) for x in grp_items)
        grand_total += group_sum

        seen_names: list[str] = []
        seen_debts: list[str] = []
        for x in grp_items:
            nm = str(x["student_name"]).strip()
            if nm and nm not in seen_names:
                seen_names.append(nm)
            db_str = str(x["debts"]).strip()
            if db_str and db_str not in seen_debts:
                seen_debts.append(db_str)

        names_str = ", ".join(html.escape(n) for n in seen_names)
        debts_str = ", ".join(html.escape(d) for d in seen_debts)

        if len(seen_names) > 1:
            if lang == "cyrl":
                blocks.append(
                    f"👶 Фарзандларингиз: <b>{names_str}</b>\n"
                    f"📚 Гуруҳ: <b>{html.escape(group_name)}</b>\n"
                    f"🗓 Тўланмаган ойлар: <i>{debts_str}</i>\n"
                    f"💰 Қарздорлик: <b>{total_months} {month_unit} × {_format_uzs(fee)} = {_format_uzs(group_sum)} {currency}</b>"
                )
            else:
                blocks.append(
                    f"👶 Farzandlaringiz: <b>{names_str}</b>\n"
                    f"📚 Guruh: <b>{html.escape(group_name)}</b>\n"
                    f"🗓 To‘lanmagan oylar: <i>{debts_str}</i>\n"
                    f"💰 Qarzdorlik: <b>{total_months} {month_unit} × {_format_uzs(fee)} = {_format_uzs(group_sum)} {currency}</b>"
                )
        else:
            if lang == "cyrl":
                blocks.append(
                    f"👶 Фарзандингиз: <b>{names_str}</b>\n"
                    f"📚 Гуруҳ: <b>{html.escape(group_name)}</b>\n"
                    f"🗓 Тўланмаган ойлар: <i>{debts_str}</i>\n"
                    f"💰 Қарздорлик: <b>{total_months} {month_unit} × {_format_uzs(fee)} = {_format_uzs(group_sum)} {currency}</b>"
                )
            else:
                blocks.append(
                    f"👶 Farzandingiz: <b>{names_str}</b>\n"
                    f"📚 Guruh: <b>{html.escape(group_name)}</b>\n"
                    f"🗓 To‘lanmagan oylar: <i>{debts_str}</i>\n"
                    f"💰 Qarzdorlik: <b>{total_months} {month_unit} × {_format_uzs(fee)} = {_format_uzs(group_sum)} {currency}</b>"
                )

    header = (
        "⚠️ <b>Қарздорлик эслатмаси</b>"
        if lang == "cyrl"
        else "⚠️ <b>Qarzdorlik eslatmasi</b>"
    )
    prompt = (
        "Илтимос, ўқув маркази тўловини ўз вақтида амалга оширишингизни сўраймиз."
        if lang == "cyrl"
        else "Iltimos, o‘quv markazi to‘lovini o‘z vaqtida amalga oshirishingizni so‘raymiz."
    )
    total_line = (
        (
            f"\n💵 <b>Умумий қарздорлик: {_format_uzs(grand_total)} {currency}</b>"
            if lang == "cyrl"
            else f"\n💵 <b>Umumiy qarzdorlik: {_format_uzs(grand_total)} {currency}</b>"
        )
        if len(grouped) > 1
        else ""
    )
    card_block = t(
        "payment_card_block",
        lang,
        card_number=html.escape(card_number),
        card_owner=html.escape(card_owner),
    )

    body = "\n\n━━━━━━━━━━━━━━\n\n".join(blocks)
    return (
        f"{prefix}{header}\n\n"
        f"{body}{total_line}\n\n"
        f"{prompt}\n\n"
        f"{card_block}\n\n"
        f"{_center_signature(lang)}"
    )


def _weekly_debt_period_text(
    child_debt: Optional[dict[str, Any]], raw_debts: str, lang: str
) -> str:
    """HTML-safe list of unpaid periods (current cycles + legacy labels)."""
    parts: list[str] = []
    if child_debt:
        overrides = child_debt.get("overrides") or {}

        def _period(raw_title: str) -> str:
            label = format_cycle_title(raw_title, lang)
            ov = overrides.get(raw_title)
            if not ov:
                return label
            remaining = int(ov.get("remaining_lessons") or 0)
            if lang == "cyrl":
                return f"{label} — қолган {remaining} та дарс"
            return f"{label} — qolgan {remaining} ta dars"

        for cyc in child_debt.get("cycles") or []:
            title = str(cyc.get("title") or "").strip()
            if title:
                parts.append(_period(title))
        for title in child_debt.get("extra_titles") or []:
            parts.append(_period(str(title).strip()))
        for leg in child_debt.get("legacy") or []:
            label = str(leg.get("label") or "").strip()
            if label and label != "—":
                parts.append(html.escape(label))
    if not parts:
        cleaned = str(raw_debts or "").strip()
        if cleaned and not cleaned.isdigit():
            parts = [
                format_cycle_title(x.strip(), lang)
                for x in cleaned.split(";")
                if x.strip() and x.strip() != "0"
            ]
    seen: list[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return ", ".join(seen) if seen else "—"


async def _resolve_weekly_parent_name(
    par_chat_id: int,
    items: list[dict[str, Any]],
    students_by_id: dict[str, dict[str, Any]],
    lang: str,
) -> str:
    for it in items:
        stu = students_by_id.get(str(it.get("student_id") or "").strip()) or {}
        for cid_col, name_col in (
            ("Otasi_Chat_ID", "Otasi_FIO"),
            ("Onasi_Chat_ID", "Onasi_FIO"),
            ("OtaOna_Chat_ID", "Otasi_FIO"),
        ):
            if _parse_int_chat_id(stu.get(cid_col)) == par_chat_id:
                name = str(stu.get(name_col) or "").strip()
                if name:
                    return name
    db_user = await get_user(par_chat_id)
    if db_user and str(db_user.get("full_name") or "").strip():
        return str(db_user["full_name"]).strip()
    return "ota-ona" if lang != "cyrl" else "ота-она"


async def weekly_debt_reminder(bot: Bot) -> None:
    sheets = get_sheets_manager()
    try:
        debtors = await asyncio.to_thread(sheets.get_debtors)
        groups = await asyncio.to_thread(sheets.get_all_groups)
        all_students = await asyncio.to_thread(sheets.get_all_students, None, False)
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
    default_fee = _get_default_monthly_fee()
    group_fees = {
        k: _parse_group_fee(g) for k, g in groups_by_lower.items()
    }
    phone_map = _build_phone_parent_map(all_students)

    # Merge pre-system (legacy) debts: students owing ONLY legacy cycles are
    # reminded too, and every total combines legacy + current unpaid cycles.
    try:
        legacy_map = await get_unpaid_legacy_debts_map()
    except Exception as exc:
        logger.exception("Failed loading legacy debts for weekly reminder: %s", exc)
        legacy_map = {}
    known_sids = {str(d.get("Talaba_ID", "")).strip() for d in debtors}
    students_by_id = {str(s.get("Talaba_ID", "")).strip(): s for s in all_students}
    for l_sid in legacy_map:
        if l_sid not in known_sids and l_sid in students_by_id:
            debtors.append(dict(students_by_id[l_sid]))
            known_sids.add(l_sid)
    try:
        child_debts = await compute_children_debts(
            sheets, debtors, group_fees, default_fee, legacy_map=legacy_map
        )
    except Exception as exc:
        logger.exception("Failed computing combined debts: %s", exc)
        child_debts = []
    child_by_sid = {c["student_id"]: c for c in child_debts}

    student_payloads: dict[int, list[dict[str, Any]]] = {}
    parent_payloads: dict[int, list[dict[str, Any]]] = {}

    for student in debtors:
        debts = student.get("Qarzdor_Oylar", "").strip()
        child_debt = child_by_sid.get(str(student.get("Talaba_ID", "")).strip())
        months = (
            child_debt["total_months"] if child_debt else _count_debt_months(debts)
        )
        if months <= 0:
            continue

        stu_id = str(student.get("Talaba_ID", "")).strip()
        group_raw = student.get("Guruh", "").strip()
        student_name = student.get("F.I.O.", "").strip() or stu_id
        fee = group_fees.get(group_raw.lower(), default_fee)
        total = child_debt["total_sum"] if child_debt else months * fee

        item = {
            "student_id": stu_id,
            "student_name": student_name,
            "group_name": group_raw,
            "debts": debts,
            "months": months,
            "fee": fee,
            "total": total,
        }

        stu_chat_id = _parse_int_chat_id(student.get("Talaba_Chat_ID"))
        parent_cids = _collect_parent_chat_ids(
            student, exclude_chat_id=stu_chat_id, phone_to_parent_cids=phone_map
        )

        if stu_chat_id and stu_chat_id not in parent_cids:
            s_bucket = student_payloads.setdefault(stu_chat_id, [])
            if not any(
                x["student_id"] == stu_id and x["group_name"].lower() == group_raw.lower()
                for x in s_bucket
            ):
                s_bucket.append(item)

        for par_chat_id in parent_cids:
            p_bucket = parent_payloads.setdefault(par_chat_id, [])
            if not any(
                x["student_id"] == stu_id and x["group_name"].lower() == group_raw.lower()
                for x in p_bucket
            ):
                p_bucket.append(item)

    # 1) Student DMs (one reminder per unpaid group, upfront Lesson-1 wording)
    for stu_cid, s_items in student_payloads.items():
        s_lang = await get_user_lang(stu_cid)
        s_prefix = (
            dual_role_header("student", s_lang)
            if await has_dual_student_parent_role(stu_cid)
            else ""
        )
        for it in s_items:
            s_msg = t(
                "weekly_debt_student_dm",
                s_lang,
                student_name=html.escape(it["student_name"]),
                group_name=html.escape(it["group_name"]),
                debts=_weekly_debt_period_text(
                    child_by_sid.get(it["student_id"]), it["debts"], s_lang
                ),
                amount=_format_uzs(int(it["total"])),
                card_number=card_esc,
                card_owner=owner_esc,
            )
            await _safe_send_message(bot, stu_cid, f"{s_prefix}{s_msg}")
            await asyncio.sleep(0.05)

    # 2) Parent DMs (strictly 1 message per parent chat: single or combined)
    for par_chat_id, p_items in parent_payloads.items():
        p_lang = await get_user_lang(par_chat_id)
        is_dual = await has_dual_student_parent_role(par_chat_id)
        p_name = await _resolve_weekly_parent_name(
            par_chat_id, p_items, students_by_id, p_lang
        )
        p_prefix = (
            dual_role_header(
                "parent", p_lang, [str(it.get("student_name") or "") for it in p_items]
            )
            if is_dual
            else ""
        )
        if len(p_items) == 1:
            it = p_items[0]
            p_msg = t(
                "weekly_debt_parent_single_dm",
                p_lang,
                parent_name=html.escape(p_name),
                student_name=html.escape(it["student_name"]),
                group_name=html.escape(it["group_name"]),
                debts=_weekly_debt_period_text(
                    child_by_sid.get(it["student_id"]), it["debts"], p_lang
                ),
                amount=_format_uzs(int(it["total"])),
                card_number=card_esc,
                card_owner=owner_esc,
            )
        else:
            child_blocks = [
                t(
                    "weekly_debt_child_block",
                    p_lang,
                    student_name=html.escape(it["student_name"]),
                    group_name=html.escape(it["group_name"]),
                    debts=_weekly_debt_period_text(
                        child_by_sid.get(it["student_id"]), it["debts"], p_lang
                    ),
                    amount=_format_uzs(int(it["total"])),
                )
                for it in p_items
            ]
            p_msg = t(
                "weekly_debt_parent_multi_dm",
                p_lang,
                parent_name=html.escape(p_name),
                children_blocks="\n\n──────────────────\n\n".join(child_blocks),
                grand_total=_format_uzs(sum(int(it["total"]) for it in p_items)),
                card_number=card_esc,
                card_owner=owner_esc,
            )
        await _safe_send_message(bot, par_chat_id, f"{p_prefix}{p_msg}")
        await asyncio.sleep(0.05)

    # 3) Stage 2 - Group Telegram Chat reminder: COUNT ONLY (no names / personal
    #    data). Only groups whose initial notice was already sent and that were
    #    not yet reminded this ISO week; nothing is sent once everyone has paid.
    for grp in groups:
        grp_name = str(grp.get("Guruh_Nomi", "")).strip()
        if not grp_name or not _parse_int_chat_id(grp.get("Guruh_TG_Chat_ID")):
            continue
        if await maybe_send_group_weekly_reminder(bot, grp_name, group=grp):
            await asyncio.sleep(0.5)


async def _count_unpaid_active_students(sheets: SheetsManager, group_name: str) -> int:
    """Number of active ("O'qiyapti") students of the group with an unpaid cycle."""
    students = await asyncio.to_thread(sheets.get_all_students, group_name, True)
    return sum(
        1
        for stu in students
        if _count_debt_months(str(stu.get("Qarzdor_Oylar", "") or "")) > 0
    )


async def maybe_send_group_weekly_reminder(
    bot: Bot,
    group_name: str,
    *,
    group: Optional[dict[str, Any]] = None,
    unpaid_count: Optional[int] = None,
) -> bool:
    """
    Stage 2: anonymized, count-only "Haftalik to‘lov eslatmasi" for the group's
    Telegram chat (`Guruh_TG_Chat_ID`) - never any student names.

    Sends only when the chat is linked, the initial notice was already sent
    (group_reminder_state.initial_sent == 1), the current Asia/Tashkent ISO week
    is not yet recorded in last_weekly_iso_week and at least one active student
    is still unpaid. With 0 unpaid students nothing is sent (auto-stop).
    Never raises. Returns True only when a message was actually delivered.
    """
    try:
        clean_name = str(group_name or "").strip()
        if not clean_name:
            return False
        sheets = get_sheets_manager()
        if group is None:
            group = await asyncio.to_thread(sheets.get_group, clean_name)
        if not group:
            return False
        group_tg_id = _parse_int_chat_id(group.get("Guruh_TG_Chat_ID"))
        if not group_tg_id:
            return False

        canonical_group = str(group.get("Guruh_Nomi", "")).strip() or clean_name
        iso_week = current_iso_week()
        state = await get_group_reminder_state(canonical_group)
        if (
            not state
            or int(state.get("initial_sent") or 0) != 1
            or state.get("last_weekly_iso_week") == iso_week
        ):
            return False

        if unpaid_count is None:
            unpaid_count = await _count_unpaid_active_students(sheets, canonical_group)
        if unpaid_count <= 0:
            return False

        claimed, previous_week = await claim_group_weekly_reminder(
            canonical_group, iso_week
        )
        if not claimed:
            return False

        card_number, card_owner = _get_payment_card_info()
        group_msg = t(
            "group_weekly_reminder",
            "latn",
            canonical_group=html.escape(canonical_group),
            unpaid_count=unpaid_count,
            card_esc=html.escape(card_number),
            owner_esc=html.escape(card_owner),
        )
        delivered = await _safe_send_message(bot, group_tg_id, group_msg)
        if not delivered:
            await release_group_weekly_reminder(canonical_group, previous_week)
        return delivered
    except Exception:
        logger.exception("Group weekly reminder failed for %s", group_name)
        return False


async def send_group_initial_notice(
    bot: Bot,
    group_name: str,
    *,
    group: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Stage 1: "Oylik to‘lov eslatmasi" (no unpaid count, no names), sent once
    when the 1-hour timer of group_reminder_state has elapsed, the group chat is
    linked and at least one active student is unpaid. On success it sets
    initial_sent = 1 and last_weekly_iso_week = current ISO week. Never raises.
    """
    try:
        clean_name = str(group_name or "").strip()
        if not clean_name:
            return False
        sheets = get_sheets_manager()
        if group is None:
            group = await asyncio.to_thread(sheets.get_group, clean_name)
        if not group:
            return False
        group_tg_id = _parse_int_chat_id(group.get("Guruh_TG_Chat_ID"))
        if not group_tg_id:
            return False
        canonical_group = str(group.get("Guruh_Nomi", "")).strip() or clean_name

        if await _count_unpaid_active_students(sheets, canonical_group) <= 0:
            return False
        if not await claim_group_initial_notice(canonical_group):
            return False

        card_number, card_owner = _get_payment_card_info()
        msg = t(
            "group_initial_notice",
            "latn",
            canonical_group=html.escape(canonical_group),
            card_esc=html.escape(card_number),
            owner_esc=html.escape(card_owner),
        )
        delivered = await _safe_send_message(bot, group_tg_id, msg)
        if not delivered:
            await release_group_initial_notice(canonical_group)
        return delivered
    except Exception:
        logger.exception("Group initial notice failed for %s", group_name)
        return False


# group key -> earliest time the (still unmet) initial notice is re-checked, so a
# due-but-not-sendable group (chat unlinked / everyone paid) does not hit Google
# Sheets every minute. The persistent timer in SQLite is never touched by this.
_initial_retry_after: dict[str, Any] = {}
_INITIAL_RETRY_DELAY = timedelta(minutes=10)


async def process_initial_group_notices(bot: Bot) -> None:
    """
    Runs every minute (and right after startup, so a restart never loses a
    pending 1-hour timer): sends every initial group notice whose
    initial_due_at has passed and whose initial_sent is still 0.
    """
    try:
        due_keys = await list_due_initial_group_notices()
    except Exception:
        logger.exception("Failed listing due initial group notices")
        return
    now = now_tashkent()
    pending = [
        k for k in due_keys if _initial_retry_after.get(k, now) <= now
    ]
    if not pending:
        return
    sheets = get_sheets_manager()
    try:
        groups = await asyncio.to_thread(sheets.get_all_groups)
    except Exception:
        logger.exception("Failed loading groups for initial group notices")
        return
    by_key = {
        str(g.get("Guruh_Nomi", "")).strip().lower(): g
        for g in groups
        if str(g.get("Guruh_Nomi", "")).strip()
    }
    for key in pending:
        grp = by_key.get(key)
        if grp is None:
            _initial_retry_after[key] = now + _INITIAL_RETRY_DELAY
            continue
        if await send_group_initial_notice(
            bot, str(grp.get("Guruh_Nomi", "")), group=grp
        ):
            _initial_retry_after.pop(key, None)
            await asyncio.sleep(0.5)
        else:
            _initial_retry_after[key] = now_tashkent() + _INITIAL_RETRY_DELAY


async def register_group_initial_notice(
    group_name: str, *, require_students: bool = True
) -> bool:
    """
    Starts the persistent 1-hour countdown (now_tashkent + 1h) of the initial
    group notice, unless one is already running or was already sent. Called when
    a student is added to a group and when /link_group links a group chat.
    Never raises. Returns True when a new timer was set.
    """
    try:
        clean_name = str(group_name or "").strip()
        if not clean_name:
            return False
        if require_students:
            students = await asyncio.to_thread(
                get_sheets_manager().get_all_students, clean_name, True
            )
            if not students:
                return False
        _initial_retry_after.pop(clean_name.lower(), None)
        return await ensure_group_initial_due(clean_name)
    except Exception:
        logger.exception("Could not start initial group notice timer for %s", group_name)
        return False


_group_reminder_tasks: set["asyncio.Task[Any]"] = set()
_registered_bot: Optional[Bot] = None


def schedule_group_initial_notice(bot: Optional[Bot], group_name: str) -> None:
    """
    Fire-and-forget wrapper so handlers never wait on Google Sheets reads.
    (`bot` is accepted for call-site symmetry; the timer itself is persistent
    and delivered by the scheduler.)
    """
    if not str(group_name or "").strip():
        return
    try:
        task = asyncio.get_running_loop().create_task(
            register_group_initial_notice(group_name)
        )
    except RuntimeError:
        return
    _group_reminder_tasks.add(task)
    task.add_done_callback(_group_reminder_tasks.discard)


def setup_scheduler(bot: Bot) -> AsyncIOScheduler:
    global _registered_bot
    _registered_bot = bot
    scheduler = AsyncIOScheduler(timezone=TZ)
    now_tz = now_tashkent()

    scheduler.add_job(
        process_lesson_reminders,
        trigger=IntervalTrigger(minutes=2, timezone=TZ),
        next_run_time=now_tz + timedelta(seconds=15),
        args=[bot],
        id="process_lesson_reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_initial_group_notices,
        trigger=IntervalTrigger(minutes=1, timezone=TZ),
        next_run_time=now_tz + timedelta(seconds=20),
        args=[bot],
        id="process_initial_group_notices",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        auto_publish_pending_topics,
        trigger=IntervalTrigger(minutes=2, timezone=TZ),
        next_run_time=now_tz + timedelta(seconds=45),
        args=[bot],
        id="auto_publish_pending_topics",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        process_completed_cycles,
        trigger=IntervalTrigger(minutes=5, timezone=TZ),
        next_run_time=now_tz + timedelta(seconds=90),
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