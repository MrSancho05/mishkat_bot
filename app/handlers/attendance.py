import asyncio
import html
import json
import os
import re
from datetime import date, datetime
from typing import Any, Optional

import aiosqlite
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import database
from app.config import ADMIN_IDS, DB_PATH, TZ
from app.database import (
    get_all_dynamic_admins,
    get_lesson_topic,
    get_teacher_by_telegram_id,
    get_user,
    get_user_lang,
    upsert_group_counter,
)
from app.keyboards import (
    admin_attendance_report_kb,
    attendance_marking_kb,
    groups_inline_kb,
)
from app.locales import WEEKDAYS_SHORT, format_uz_date, t
from app.sheets import (
    SheetsManager,
    get_next_lesson_date_after,
    get_sheets_manager,
    parse_weekdays,
)
from app.states import AttendanceStates

router = Router(name="attendance")


class _FallbackAttendanceStates(StatesGroup):
    selecting_date = State()


ATT_SELECTING_DATE = getattr(
    AttendanceStates, "selecting_date", _FallbackAttendanceStates.selecting_date
)

ATTENDANCE_MENU_TEXTS = {
    t("menu_teacher_attendance", "latn"),
    t("menu_teacher_attendance", "cyrl"),
    t("menu_admin_attendance", "latn"),
    t("menu_admin_attendance", "cyrl"),
}

CANCEL_TEXTS = {t("btn_cancel", "latn"), t("btn_cancel", "cyrl"), "/cancel"}

LOCAL_TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "select_date_title": (
            "📅 <b>{group}</b> — yo‘qlama qilish yoki tahrirlash uchun dars sanasini tanlang:\n"
            "<i>(✅ — belgilangan, ⏳ — hali belgilanmagan)</i>"
        ),
        "absent_topic_appendix": (
            "\n\n📝 <b>Dars mavzusi:</b> {topic}"
            "\n📖 <b>O‘tiladigan mavzu / Uyga vazifa:</b> {content}"
        ),
    },
    "cyrl": {
        "select_date_title": (
            "📅 <b>{group}</b> — йўқлама қилиш ёки таҳрирлаш учун дарс санасини танланг:\n"
            "<i>(✅ — белгиланган, ⏳ — ҳали белгиланмаган)</i>"
        ),
        "absent_topic_appendix": (
            "\n\n📝 <b>Дарс мавзуси:</b> {topic}"
            "\n📖 <b>Ўтиладиган мавзу / Уйга вазифа:</b> {content}"
        ),
    },
}


def _lt(key: str, lang: str = "latn", **kwargs: Any) -> str:
    safe_lang = lang if lang in LOCAL_TEXTS else "latn"
    template = LOCAL_TEXTS[safe_lang].get(key) or LOCAL_TEXTS["latn"].get(key, key)
    return template.format(**kwargs) if kwargs else template


def _get_card_info() -> tuple[str, str]:
    card_number = os.getenv("CARD_NUMBER", "").strip() or os.getenv("PAYMENT_CARD_NUMBER", "").strip() or "—"
    card_owner = os.getenv("CARD_OWNER", "").strip() or os.getenv("PAYMENT_CARD_OWNER", "").strip() or "—"
    return card_number, card_owner


def _parse_int(raw: Any) -> Optional[int]:
    val = str(raw or "").strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _format_clickable_phone(raw_phone: str) -> str:
    cleaned = raw_phone.strip()
    if not cleaned:
        return "—"
    compact = re.sub(r"[^\d+]", "", cleaned)
    if re.fullmatch(r"\d{9}", compact):
        compact = f"+998{compact}"
    elif re.fullmatch(r"998\d{9}", compact):
        compact = f"+{compact}"
    elif compact and not compact.startswith("+") and len(compact) >= 7:
        compact = f"+{compact}"
    return html.escape(compact or cleaned)


def _format_clickable_tg(raw_tg: str) -> str:
    cleaned = raw_tg.strip()
    if not cleaned:
        return "—"
    if cleaned.startswith(("https://t.me/", "http://t.me/", "t.me/")):
        username = cleaned.rstrip("/").split("/")[-1].lstrip("@")
    else:
        username = cleaned.lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{3,}", username):
        return html.escape(cleaned)
    safe_u = html.escape(username)
    return f'<a href="https://t.me/{safe_u}">@{safe_u}</a>'


async def _ensure_reports_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payload_json TEXT NOT NULL
            );
            """
        )
        await db.commit()


async def _save_attendance_report(payload: dict[str, Any]) -> int:
    await _ensure_reports_table()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO attendance_reports (payload_json) VALUES (?);",
            (json.dumps(payload, ensure_ascii=False),),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def _get_attendance_report(report_id: int) -> Optional[dict[str, Any]]:
    await _ensure_reports_table()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT payload_json FROM attendance_reports WHERE id = ?;",
            (report_id,),
        ) as cur:
            row = await cur.fetchone()
            return json.loads(row[0]) if row else None


async def _get_silent_lesson_topic(
    group_name: str, selected_date: date
) -> Optional[dict[str, str]]:
    date_dm = selected_date.strftime("%d.%m")
    date_iso = selected_date.isoformat()
    for d_key in (date_dm, date_iso):
        try:
            rec = await get_lesson_topic(group_name, d_key)
        except Exception:
            rec = None
        if rec:
            topic = str(rec.get("topic") or rec.get("topic_title") or "").strip()
            plan = str(rec.get("plan") or rec.get("lesson_details") or "").strip()
            if topic or plan:
                return {"topic": topic, "content": plan}
    return None


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


async def _get_all_admin_ids() -> list[int]:
    ids: list[int] = list(ADMIN_IDS)
    try:
        for dyn in await get_all_dynamic_admins():
            tid = int(dyn["telegram_id"])
            if tid not in ids:
                ids.append(tid)
    except Exception:
        pass
    return ids


async def _get_authorized_groups(user_id: int) -> tuple[bool, list[dict[str, Any]]]:
    sheets = get_sheets_manager()
    is_admin = await _is_admin(user_id)
    if is_admin:
        groups = await asyncio.to_thread(sheets.get_all_groups)
        return True, groups

    raw_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
    groups = [
        g
        for g in raw_groups
        if str(g.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
    ]
    if not groups:
        return False, []
    return True, groups


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


async def _resolve_teacher_name(
    sheets: SheetsManager,
    group: Optional[dict[str, Any]],
    fallback_user_id: int,
    fallback_name: str,
) -> str:
    raw_tid = str(group.get("Ustoz_Chat_ID", "") if group else "").strip()
    tid = _parse_int(raw_tid) or fallback_user_id

    def _lookup_sheet() -> str:
        with sheets._lock:
            try:
                ws = sheets._get_spreadsheet().worksheet("Ustozlar")
            except Exception:
                return ""
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return ""
            headers = rows[0]
            for raw_row in rows[1:]:
                padded = raw_row + [""] * (len(headers) - len(raw_row))
                rec = dict(zip(headers, padded))
                if rec.get("Chat_ID", "").strip() == str(tid):
                    fio = rec.get("F.I.O.", "").strip()
                    if fio and fio != "Ma'lumot kiritilmagan":
                        return fio
            return ""

    sheet_name = await asyncio.to_thread(_lookup_sheet)
    if sheet_name:
        return sheet_name
    db_t = await get_teacher_by_telegram_id(tid)
    if db_t and db_t.get("full_name"):
        return db_t["full_name"]
    db_u = await get_user(tid)
    if db_u and db_u.get("full_name"):
        return db_u["full_name"]
    return fallback_name or str(tid)


def _get_current_cycle_dates_sync(
    sheets: SheetsManager, group_name: str, reference_date: date
) -> tuple[str, list[dict[str, Any]]]:
    with sheets._lock:
        ss = sheets._get_spreadsheet()
        for year_candidate in (reference_date.year, reference_date.year - 1):
            try:
                ws = ss.worksheet(f"{group_name.strip()}_{year_candidate}")
            except Exception:
                continue
            cycles = sheets.parse_cycles_from_sheet(ws)
            if not cycles:
                continue
            cycle = cycles[-1]
            prev_d: Optional[date] = None
            running_year = year_candidate
            items: list[dict[str, Any]] = []
            for dc in cycle.get("date_columns", []):
                d_str = str(dc.get("date_str", "")).strip()
                try:
                    d_val, m_val = map(int, d_str.split("."))
                except ValueError:
                    continue
                if prev_d and m_val < prev_d.month:
                    running_year += 1
                lesson_d = date(running_year, m_val, d_val)
                prev_d = lesson_d

                col_idx = dc["col_idx"]
                is_marked = any(
                    s_row["marks"].get(col_idx, "").strip() in {"✅", "❌"}
                    for s_row in cycle.get("student_rows", [])
                )
                items.append(
                    {
                        "date_iso": lesson_d.isoformat(),
                        "date_str": d_str,
                        "weekday_idx": lesson_d.weekday(),
                        "is_marked": is_marked,
                    }
                )
            if items:
                return cycle["title"], items

        return "", [
            {
                "date_iso": reference_date.isoformat(),
                "date_str": reference_date.strftime("%d.%m"),
                "weekday_idx": reference_date.weekday(),
                "is_marked": False,
            }
        ]


def _get_existing_attendance_for_date_sync(
    sheets: SheetsManager, group_name: str, lesson_date: date
) -> dict[str, str]:
    with sheets._lock:
        ss = sheets._get_spreadsheet()
        date_str = lesson_date.strftime("%d.%m")
        for year_candidate in (lesson_date.year, lesson_date.year - 1):
            try:
                ws = ss.worksheet(f"{group_name.strip()}_{year_candidate}")
            except Exception:
                continue
            for cycle in reversed(sheets.parse_cycles_from_sheet(ws)):
                target_col = next(
                    (
                        dc["col_idx"]
                        for dc in cycle["date_columns"]
                        if dc["date_str"] == date_str
                    ),
                    None,
                )
                if target_col is None:
                    continue
                return {
                    s_row["student_id"].strip(): s_row["marks"].get(target_col, "").strip()
                    for s_row in cycle["student_rows"]
                    if s_row["student_id"].strip()
                }
        return {}


def _extract_last_cycle_date_and_unpaid(
    sheets: SheetsManager,
    group_name: str,
    cycle_title: str,
    reference_date: date,
) -> tuple[date, list[str]]:
    with sheets._lock:
        ss = sheets._get_spreadsheet()
        for year_candidate in (reference_date.year, reference_date.year - 1):
            try:
                ws = ss.worksheet(f"{group_name.strip()}_{year_candidate}")
            except Exception:
                continue
            for cycle in reversed(sheets.parse_cycles_from_sheet(ws)):
                if cycle["title"].strip() != cycle_title.strip():
                    continue
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
                return last_date, unpaid_ids

        active_students = sheets.get_all_students(
            group_name=group_name, active_only=True
        )
        return reference_date, [s["Talaba_ID"].strip() for s in active_students]


def _collect_parent_chat_ids(
    student: dict[str, Any], exclude_chat_id: Optional[int]
) -> list[int]:
    parent_ids: list[int] = []
    for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
        cid = _parse_int(student.get(col))
        if cid and cid != exclude_chat_id and cid not in parent_ids:
            parent_ids.append(cid)
    return parent_ids


async def _safe_send(bot: Any, chat_id: int, text: str, reply_markup: Any = None) -> bool:
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception:
        return False


def _attendance_dates_kb(
    date_items: list[dict[str, Any]], lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    wd_names = WEEKDAYS_SHORT.get(lang, WEEKDAYS_SHORT["latn"])
    buttons = [
        InlineKeyboardButton(
            text=(
                f"{format_uz_date(item['date_str'], lang)} ({wd_names.get(item['weekday_idx'], '')}) "
                f"{'✅' if item['is_marked'] else '⏳'}"
            ),
            callback_data=f"att_date:{item['date_iso']}",
        )
        for item in date_items
    ]
    for i in range(0, len(buttons), 2):
        builder.row(*buttons[i : i + 2])
    builder.row(
        InlineKeyboardButton(
            text=t("btn_back", lang), callback_data="att_date:__back__"
        ),
        InlineKeyboardButton(
            text=t("btn_cancel", lang), callback_data="att_date:__cancel__"
        ),
    )
    return builder.as_markup()


def _format_admin_report_text(
    payload: dict[str, Any], is_detailed: bool, lang: str
) -> str:
    updated_badge = (
        t("admin_report_updated_tag", lang) if payload.get("is_resubmit") else ""
    )
    group_esc = html.escape(payload.get("group_name", ""))
    teacher_esc = html.escape(payload.get("teacher_name", "—"))
    raw_dm = payload.get("lesson_date_dm")
    date_esc = html.escape(
        format_uz_date(raw_dm, lang) if raw_dm else payload.get("date_display", "")
    )
    time_esc = html.escape(payload.get("lesson_time", "—"))
    present_count = payload.get("present_count", 0)
    absent_count = payload.get("absent_count", 0)

    delivery_summary = payload.get("delivery_summary", {})
    stu_sent = delivery_summary.get("students_sent", 0)
    par_sent = delivery_summary.get("parents_sent", 0)
    recipients_list = delivery_summary.get("recipients", [])

    if not is_detailed:
        base = t(
            "admin_attendance_report_compact",
            lang,
            updated_badge=updated_badge,
            group=group_esc,
            teacher_name=teacher_esc,
            date=date_esc,
            lesson_time=time_esc,
            present_count=present_count,
            absent_count=absent_count,
        )
        delivery_line = (
            f"\n📨 Xabar yuborildi: Talaba (<b>{stu_sent}</b> ta), Ota-ona (<b>{par_sent}</b> ta)"
            if lang == "latn"
            else f"\n📨 Хабар юборилди: Талаба (<b>{stu_sent}</b> та), Ота-она (<b>{par_sent}</b> та)"
        )
        if recipients_list:
            names_preview = ", ".join(html.escape(n) for n in recipients_list)
            lbl = "Qabul qilganlar" if lang == "latn" else "Қабул қилганлар"
            delivery_line += f"\n👥 {lbl}: <i>{names_preview}</i>"
        return f"{base}{delivery_line}"

    present_items: list[dict[str, Any]] = payload.get("present_items", [])
    absent_items: list[dict[str, Any]] = payload.get("absent_items", [])
    debtor_items: list[dict[str, Any]] = payload.get("debtor_items", [])

    def _build_student_detail_line(item: dict[str, Any]) -> str:
        name = html.escape(item.get("name", ""))
        stu_tel = _format_clickable_phone(item.get("stu_tel", ""))
        stu_tg = _format_clickable_tg(item.get("stu_tg", ""))
        dm_tags = html.escape(item.get("dm_status", ""))
        parent_parts: list[str] = []
        if item.get("father_tel"):
            lbl = "Otasi" if lang == "latn" else "Отаси"
            parent_parts.append(f"{lbl}: {_format_clickable_phone(item['father_tel'])}")
        if item.get("mother_tel"):
            lbl = "Onasi" if lang == "latn" else "Онаси"
            parent_parts.append(f"{lbl}: {_format_clickable_phone(item['mother_tel'])}")
        if not parent_parts and item.get("parent_tel"):
            lbl = "Ota-ona" if lang == "latn" else "Ота-она"
            parent_parts.append(f"{lbl}: {_format_clickable_phone(item['parent_tel'])}")
        par_str = " | ".join(parent_parts) if parent_parts else "—"
        return f"• <b>{name}</b> ({dm_tags})\n  📞 {stu_tel} | {stu_tg}\n  👨‍👩‍👧 {par_str}"

    present_lines = (
        "\n".join(_build_student_detail_line(it) for it in present_items)
        if present_items
        else "—"
    )
    absent_lines = (
        "\n".join(_build_student_detail_line(it) for it in absent_items)
        if absent_items
        else "—"
    )
    if debtor_items:
        debtor_lines = "\n".join(
            f"• <b>{html.escape(d['name'])}</b> — <i>{html.escape(d['debts'])}</i> "
            f"({d['debt_count']} ta sikl) | 📞 {_format_clickable_phone(d.get('stu_tel', ''))}"
            + (
                f" | 👨‍👩‍👧 {_format_clickable_phone(d.get('parent_tel', ''))}"
                if d.get("parent_tel")
                else ""
            )
            for d in debtor_items
        )
    else:
        debtor_lines = "—"

    return t(
        "admin_attendance_report_detailed",
        lang,
        updated_badge=updated_badge,
        group=group_esc,
        teacher_name=teacher_esc,
        date=date_esc,
        lesson_time=time_esc,
        present_count=present_count,
        absent_count=absent_count,
        present_lines=present_lines,
        absent_lines=absent_lines,
        debtor_lines=debtor_lines,
    )


async def _trigger_cycle_completion(
    bot: Any,
    sheets: SheetsManager,
    group: dict[str, Any],
    group_name: str,
    cycle_title: str,
    lesson_date: date,
    students_by_id: dict[str, dict[str, Any]],
    initiating_teacher_id: int,
) -> None:
    last_cycle_date, unpaid_ids = await asyncio.to_thread(
        _extract_last_cycle_date_and_unpaid,
        sheets,
        group_name,
        cycle_title,
        lesson_date,
    )

    for uid in unpaid_ids:
        await asyncio.to_thread(sheets.add_debt_cycle, uid, cycle_title)

    await asyncio.to_thread(sheets.reset_group_lesson_counter, group_name)
    await upsert_group_counter(group_name, lesson_count=0)

    lesson_days = parse_weekdays(group.get("Dars_Kunlari", ""))
    next_cycle_info: Optional[dict[str, Any]] = None
    if lesson_days:
        next_start = get_next_lesson_date_after(last_cycle_date, lesson_days)
        next_cycle_info = await asyncio.to_thread(
            sheets.create_cycle_table, group_name, next_start
        )

    card_number, card_owner = _get_card_info()
    grp_esc = html.escape(group_name)
    cyc_esc = html.escape(cycle_title)

    group_tg_id = _parse_int(group.get("Guruh_TG_Chat_ID"))
    if group_tg_id:
        group_msg = (
            "🔔 <b>Oylik o‘quv sikli yakunlandi!</b>\n\n"
            f"📚 Guruh: <b>{grp_esc}</b>\n"
            f"🗓 Davr: <b>{cyc_esc}</b>\n\n"
            "Keyingi darslar uchun oylik to‘lovni o‘z vaqtida amalga oshirishingizni so‘raymiz.\n\n"
            f"💳 Karta: <code>{html.escape(card_number)}</code>\n"
            f"👤 Karta egasi: <b>{html.escape(card_owner)}</b>\n\n"
            "Hurmat bilan, Mishkat o'quv muassasasi"
        )
        await _safe_send(bot, group_tg_id, group_msg)

    for uid in unpaid_ids:
        student = students_by_id.get(uid)
        if not student:
            continue
        stu_name_esc = html.escape(student.get("F.I.O.", "").strip())

        stu_cid = _parse_int(student.get("Talaba_Chat_ID"))
        if stu_cid:
            s_lang = await get_user_lang(stu_cid)
            await _safe_send(
                bot,
                stu_cid,
                t(
                    "cycle_completed_remind_student",
                    s_lang,
                    group=grp_esc,
                    cycle_title=cyc_esc,
                    card_number=html.escape(card_number),
                    card_owner=html.escape(card_owner),
                ),
            )

        for par_cid in _collect_parent_chat_ids(student, stu_cid):
            p_lang = await get_user_lang(par_cid)
            await _safe_send(
                bot,
                par_cid,
                t(
                    "cycle_completed_remind_parent",
                    p_lang,
                    student_name=stu_name_esc,
                    group=grp_esc,
                    cycle_title=cyc_esc,
                    card_number=html.escape(card_number),
                    card_owner=html.escape(card_owner),
                ),
            )

    ustoz_cid = _parse_int(group.get("Ustoz_Chat_ID")) or initiating_teacher_id
    if ustoz_cid and next_cycle_info:
        u_lang = await get_user_lang(ustoz_cid)
        await _safe_send(
            bot,
            ustoz_cid,
            t(
                "cycle_completed_report_teacher",
                u_lang,
                group=grp_esc,
                cycle_title=cyc_esc,
                next_cycle_title=html.escape(next_cycle_info["cycle_title"]),
            ),
        )


# ----------------------------------------------------------------------
# Attendance Handlers (📋 Yo'qlama qilish) — NO Topic Prompts
# ----------------------------------------------------------------------


@router.message(F.text.in_(ATTENDANCE_MENU_TEXTS))
async def cmd_attendance_start(message: Message, state: FSMContext) -> None:
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

    await state.set_state(AttendanceStates.selecting_group)
    await message.answer(
        t("attendance_select_group", lang),
        reply_markup=groups_inline_kb(
            groups, prefix="att_grp", lang=lang, include_back=False, include_cancel=True
        ),
    )


@router.message(StateFilter(AttendanceStates), F.text.in_(CANCEL_TEXTS))
async def msg_attendance_cancel(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    await state.clear()
    await message.answer(t("attendance_cancelled", lang))


@router.callback_query(AttendanceStates.selecting_group, F.data.startswith("att_grp:"))
async def cb_attendance_select_group(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    group_name = (callback.data or "").split(":", 1)[1]

    if group_name == "__cancel__":
        await state.clear()
        await callback.message.edit_text(t("attendance_cancelled", lang))
        await callback.answer()
        return

    if not await _can_manage_group(user_id, group_name):
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return

    sheets = get_sheets_manager()
    active_students = await asyncio.to_thread(
        sheets.get_all_students, group_name, True
    )
    if not active_students:
        await state.clear()
        await callback.message.edit_text(t("contacts_empty", lang))
        await callback.answer()
        return

    today = datetime.now(TZ).date()
    cycle_title, date_items = await asyncio.to_thread(
        _get_current_cycle_dates_sync, sheets, group_name, today
    )

    await state.set_state(ATT_SELECTING_DATE)
    await state.update_data(
        group_name=group_name,
        cycle_title_hint=cycle_title,
    )
    await callback.message.edit_text(
        _lt("select_date_title", lang, group=html.escape(group_name)),
        reply_markup=_attendance_dates_kb(date_items, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(StateFilter(ATT_SELECTING_DATE), F.data.startswith("att_date:"))
async def cb_attendance_select_date(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    val = (callback.data or "").split(":", 1)[1]

    if val == "__cancel__":
        await state.clear()
        await callback.message.edit_text(t("attendance_cancelled", lang))
        await callback.answer()
        return

    if val == "__back__":
        _, groups = await _get_authorized_groups(user_id)
        if not groups:
            await state.clear()
            await callback.message.edit_text(t("contacts_empty", lang))
            await callback.answer()
            return
        await state.set_state(AttendanceStates.selecting_group)
        await callback.message.edit_text(
            t("attendance_select_group", lang),
            reply_markup=groups_inline_kb(
                groups,
                prefix="att_grp",
                lang=lang,
                include_back=False,
                include_cancel=True,
            ),
        )
        await callback.answer()
        return

    try:
        lesson_date = date.fromisoformat(val)
    except ValueError:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    data = await state.get_data()
    group_name: str = data["group_name"]

    sheets = get_sheets_manager()
    active_students = await asyncio.to_thread(
        sheets.get_all_students, group_name, True
    )
    if not active_students:
        await state.clear()
        await callback.message.edit_text(t("contacts_empty", lang))
        await callback.answer()
        return

    existing_marks = await asyncio.to_thread(
        _get_existing_attendance_for_date_sync, sheets, group_name, lesson_date
    )
    students_min = [
        {"Talaba_ID": s["Talaba_ID"], "F.I.O.": s["F.I.O."]}
        for s in active_students
    ]
    marks_map = {
        s["Talaba_ID"]: (
            existing_marks[s["Talaba_ID"]]
            if existing_marks.get(s["Talaba_ID"]) in {"✅", "❌"}
            else "✅"
        )
        for s in students_min
    }

    await state.set_state(AttendanceStates.marking_students)
    await state.update_data(
        lesson_date=lesson_date.isoformat(),
        students=students_min,
        marks_map=marks_map,
    )

    await callback.message.edit_text(
        t(
            "attendance_mark_title",
            lang,
            group=html.escape(group_name),
            date=format_uz_date(lesson_date.strftime("%d.%m"), lang),
        ),
        reply_markup=attendance_marking_kb(
            students_min,
            marks_map,
            lang,
            back_cb="att_back:date",
            include_topic_btn=False,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    AttendanceStates.marking_students, F.data.in_({"att_back:date", "att_back:group"})
)
async def cb_attendance_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()
    group_name = data.get("group_name", "")

    if callback.data == "att_back:date" and group_name:
        today = datetime.now(TZ).date()
        cycle_title, date_items = await asyncio.to_thread(
            _get_current_cycle_dates_sync, get_sheets_manager(), group_name, today
        )
        await state.set_state(ATT_SELECTING_DATE)
        await state.update_data(cycle_title_hint=cycle_title)
        await callback.message.edit_text(
            _lt("select_date_title", lang, group=html.escape(group_name)),
            reply_markup=_attendance_dates_kb(date_items, lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    _, groups = await _get_authorized_groups(user_id)
    if not groups:
        await state.clear()
        await callback.message.edit_text(t("contacts_empty", lang))
        await callback.answer()
        return

    await state.set_state(AttendanceStates.selecting_group)
    await callback.message.edit_text(
        t("attendance_select_group", lang),
        reply_markup=groups_inline_kb(
            groups, prefix="att_grp", lang=lang, include_back=False, include_cancel=True
        ),
    )
    await callback.answer()


@router.callback_query(
    AttendanceStates.marking_students, F.data.startswith("att_toggle:")
)
async def cb_attendance_toggle_student(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    student_id = (callback.data or "").split(":", 1)[1]

    data = await state.get_data()
    students = data.get("students", [])
    marks_map: dict[str, str] = dict(data.get("marks_map", {}))

    current = marks_map.get(student_id, "✅")
    marks_map[student_id] = "❌" if current == "✅" else "✅"

    await state.update_data(marks_map=marks_map)
    await callback.message.edit_reply_markup(
        reply_markup=attendance_marking_kb(
            students,
            marks_map,
            lang,
            back_cb="att_back:date",
            include_topic_btn=False,
        )
    )
    await callback.answer()


@router.callback_query(AttendanceStates.marking_students, F.data == "att_cancel")
async def cb_attendance_cancel_marking(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text(t("attendance_cancelled", lang))
    await callback.answer()


@router.callback_query(AttendanceStates.marking_students, F.data == "att_finish")
async def cb_attendance_finish_instant(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()

    group_name: str = data["group_name"]
    lesson_date = date.fromisoformat(data["lesson_date"])
    marks_map: dict[str, str] = data["marks_map"]
    cycle_title_hint: str = data.get("cycle_title_hint", "")
    date_dm = lesson_date.strftime("%d.%m")
    date_display = format_uz_date(date_dm, lang)

    sheets = get_sheets_manager()
    previous_marks = await asyncio.to_thread(
        _get_existing_attendance_for_date_sync, sheets, group_name, lesson_date
    )
    prev_was_marked = any(v in {"✅", "❌"} for v in previous_marks.values())

    mark_result = await sheets.a_save_attendance_for_date(
        group_name, date_dm, marks_map
    )
    cycle_title = mark_result.get("cycle_title") or cycle_title_hint
    was_unmarked = mark_result.get("was_unmarked")
    is_resubmit = (
        (not bool(was_unmarked)) if was_unmarked is not None else prev_was_marked
    )

    group = await sheets.a_get_group(group_name)
    new_count = (
        _parse_int(mark_result.get("lesson_count"))
        or _parse_int(group.get("Otilgan_Dars_Hisoblagich") if group else None)
        or 0
    )
    limit = (
        _parse_int(mark_result.get("lessons_limit"))
        or _parse_int(group.get("Oylik_Dars_Soni") if group else None)
        or 12
    )
    await upsert_group_counter(group_name, lesson_count=new_count)

    all_students = await asyncio.to_thread(
        sheets.get_all_students, group_name=group_name, active_only=False
    )
    students_by_id = {s["Talaba_ID"].strip(): s for s in all_students}

    present_count = sum(1 for m in marks_map.values() if m == "✅")
    absent_count = sum(1 for m in marks_map.values() if m == "❌")

    lesson_topic = await _get_silent_lesson_topic(group_name, lesson_date)

    students_sent = 0
    parents_sent = 0
    recipients_names: list[str] = []
    present_items: list[dict[str, Any]] = []
    absent_items: list[dict[str, Any]] = []

    for sid, mark in marks_map.items():
        student = students_by_id.get(sid)
        if not student:
            continue

        stu_name = student.get("F.I.O.", "").strip() or sid
        prev_mark = previous_marks.get(sid, "")
        should_notify = (not prev_was_marked) or (prev_mark != mark)

        stu_cid = _parse_int(student.get("Talaba_Chat_ID"))
        par_cids = _collect_parent_chat_ids(student, stu_cid)

        stu_dm_ok = False
        par_dm_ok_count = 0

        if should_notify:
            if prev_was_marked:
                msg_key = (
                    "attendance_notify_updated_present"
                    if mark == "✅"
                    else "attendance_notify_updated_absent"
                )
            else:
                msg_key = (
                    "attendance_notify_present"
                    if mark == "✅"
                    else "attendance_notify_absent"
                )

            def _compose_dm_text(target_lang: str, is_parent: bool = False) -> str:
                resolved_key = msg_key
                if mark == "❌" and is_parent:
                    resolved_key = (
                        "attendance_notify_updated_absent_parent"
                        if prev_was_marked
                        else "attendance_notify_absent_parent"
                    )
                base_msg = t(
                    resolved_key,
                    target_lang,
                    student_name=html.escape(stu_name),
                    group=html.escape(group_name),
                    date=format_uz_date(date_dm, target_lang),
                )
                if mark == "❌" and lesson_topic:
                    appendix = _lt(
                        "absent_topic_appendix",
                        target_lang,
                        topic=html.escape(lesson_topic.get("topic") or "—"),
                        content=html.escape(lesson_topic.get("content") or "—"),
                    )
                    return f"{base_msg}{appendix}"
                return base_msg

            if stu_cid:
                s_lang = await get_user_lang(stu_cid)
                stu_dm_ok = await _safe_send(
                    callback.bot, stu_cid, _compose_dm_text(s_lang, is_parent=False)
                )
                if stu_dm_ok:
                    students_sent += 1

            for p_cid in par_cids:
                p_lang = await get_user_lang(p_cid)
                if await _safe_send(
                    callback.bot, p_cid, _compose_dm_text(p_lang, is_parent=True)
                ):
                    par_dm_ok_count += 1
                    parents_sent += 1

            if stu_dm_ok or par_dm_ok_count > 0:
                recipients_names.append(stu_name)

        dm_status_parts: list[str] = []
        if should_notify:
            dm_status_parts.append("🎓✅" if stu_dm_ok else "🎓❌")
            dm_status_parts.append(
                f"👨‍👩‍👧✅({par_dm_ok_count})" if par_dm_ok_count > 0 else "👨‍👩‍👧❌"
            )
        else:
            dm_status_parts.append("o‘zgarmadi")

        item_payload = {
            "name": stu_name,
            "stu_tel": student.get("Talaba_Tel", "").strip(),
            "stu_tg": student.get("Talaba_TG", "").strip(),
            "father_tel": student.get("Otasi_Tel", "").strip(),
            "mother_tel": student.get("Onasi_Tel", "").strip(),
            "parent_tel": student.get("OtaOna_Tel", "").strip(),
            "dm_status": " ".join(dm_status_parts),
        }
        if mark == "✅":
            present_items.append(item_payload)
        else:
            absent_items.append(item_payload)

    await state.clear()
    confirm_key = (
        "attendance_updated_instant" if is_resubmit else "attendance_saved_instant"
    )
    await callback.message.edit_text(
        t(
            confirm_key,
            lang,
            group=html.escape(group_name),
            date=date_display,
            present_count=present_count,
            absent_count=absent_count,
        ),
        parse_mode="HTML",
    )

    if (not is_resubmit) and group and new_count >= limit:
        await _trigger_cycle_completion(
            bot=callback.bot,
            sheets=sheets,
            group=group,
            group_name=group_name,
            cycle_title=cycle_title,
            lesson_date=lesson_date,
            students_by_id=students_by_id,
            initiating_teacher_id=user_id,
        )

    group_debtors = await asyncio.to_thread(sheets.get_debtors, group_name)
    debtor_items = [
        {
            "name": d.get("F.I.O.", "").strip() or d.get("Talaba_ID", ""),
            "debts": d.get("Qarzdor_Oylar", "").strip(),
            "debt_count": len(
                [x for x in d.get("Qarzdor_Oylar", "").split(";") if x.strip()]
            ),
            "stu_tel": d.get("Talaba_Tel", "").strip(),
            "parent_tel": (
                d.get("Otasi_Tel", "").strip()
                or d.get("Onasi_Tel", "").strip()
                or d.get("OtaOna_Tel", "").strip()
            ),
        }
        for d in group_debtors
    ]

    teacher_name = await _resolve_teacher_name(
        sheets, group, user_id, callback.from_user.full_name or str(user_id)
    )
    lesson_time = (group.get("Dars_Vaqti", "").strip() if group else "") or "—"

    report_payload = {
        "group_name": group_name,
        "teacher_name": teacher_name,
        "lesson_date_dm": date_dm,
        "date_display": date_display,
        "lesson_time": lesson_time,
        "present_count": present_count,
        "absent_count": absent_count,
        "is_resubmit": is_resubmit,
        "delivery_summary": {
            "students_sent": students_sent,
            "parents_sent": parents_sent,
            "recipients": recipients_names,
        },
        "present_items": present_items,
        "absent_items": absent_items,
        "debtor_items": debtor_items,
    }
    report_id = await _save_attendance_report(report_payload)

    for admin_id in await _get_all_admin_ids():
        admin_lang = await get_user_lang(admin_id)
        report_text = _format_admin_report_text(
            report_payload, is_detailed=False, lang=admin_lang
        )
        await _safe_send(
            callback.bot,
            admin_id,
            report_text,
            reply_markup=admin_attendance_report_kb(
                report_id, is_detailed=False, lang=admin_lang
            ),
        )

    await callback.answer()


@router.callback_query(F.data.startswith("att_rep_toggle:"))
async def cb_admin_report_toggle(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message or not callback.data:
        await callback.answer()
        return
    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer()
        return
    try:
        report_id = int(parts[1])
        is_detailed = bool(int(parts[2]))
    except ValueError:
        await callback.answer()
        return

    lang = await get_user_lang(callback.from_user.id)
    payload = await _get_attendance_report(report_id)
    if not payload:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    text = _format_admin_report_text(payload, is_detailed=is_detailed, lang=lang)
    if len(text) > 4090:
        text = text[:4085] + "..."
    await callback.message.edit_text(
        text,
        reply_markup=admin_attendance_report_kb(report_id, is_detailed, lang),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()