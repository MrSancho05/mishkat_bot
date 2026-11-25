import asyncio
import html
import json
import logging
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

from app import database
from app.utils import (
    dual_role_header,
    get_lesson_time_for_weekday,
    now_tashkent,
    today_tashkent,
)
from app.config import ADMIN_IDS, DB_PATH, TZ
from app.scheduler import normalize_chat_id_text, send_group_chat_message
from app.database import (
    get_all_dynamic_admins,
    get_lesson_topic,
    get_teacher_by_telegram_id,
    get_user,
    get_user_lang,
    has_dual_student_parent_role,
    is_lesson_cancelled,
    record_cancelled_lesson,
    upsert_group_counter,
)
from app.keyboards import (
    InlineKeyboardBuilder,
    admin_attendance_report_kb,
    attendance_cancel_today_confirm_kb,
    attendance_marking_kb,
    attendance_session_picker_kb,
    build_attendance_mode_kb,
    groups_inline_kb,
)
from app.debt_view import compute_debt_details_map, format_uzs
from app.locales import (
    button_texts,
    format_uz_date,
    format_uz_date_long,
    format_weekday_full,
    t,
)
from app.sheets import (
    SheetsManager,
    get_group_daily_lessons,
    get_next_lesson_date_after,
    get_sheets_manager,
    parse_weekdays,
)
from app.states import AttendanceStates

logger = logging.getLogger(__name__)

router = Router(name="attendance")


class _FallbackAttendanceStates(StatesGroup):
    selecting_mode = State()
    selecting_date = State()


ATT_SELECTING_MODE = getattr(
    AttendanceStates, "selecting_mode", _FallbackAttendanceStates.selecting_mode
)
ATT_SELECTING_DATE = getattr(
    AttendanceStates, "selecting_date", _FallbackAttendanceStates.selecting_date
)

ATTENDANCE_MENU_TEXTS = button_texts(
    "menu_teacher_attendance", "menu_admin_attendance"
)

CANCEL_TEXTS = {t("btn_cancel", "latn"), t("btn_cancel", "cyrl"), "/cancel"}

LOCAL_TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "select_mode_title": (
            "📋 <b>Yo‘qlama qilish</b>\n\n"
            "Kerakli bo‘limni tanlang:"
        ),
        "select_past_date_title": (
            "🗓 <b>{group}</b> — o‘tgan darslardan birini tanlang:\n"
            "<i>(✅ — belgilangan, ⏳ — hali belgilanmagan, 🚫 — bekor qilingan)</i>"
        ),
        "no_past_lessons": (
            "ℹ️ <b>{group}</b> guruhi uchun o‘tgan dars sanalari topilmadi."
        ),
        "future_date_forbidden": (
            "⚠️ Kelajakdagi dars sanasi uchun yo‘qlama qilish mumkin emas."
        ),
        "default_parent_name": "ota-ona",
        "cycle_end_notice": (
            "🔔 <b>O‘quv oyi yakunlandi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 Yakunlangan o‘quv oyi: <b>{cycle_title}</b>"
            "{next_cycle_line}\n\n"
            "Joriy o‘quv oyi yakunlandi. Keyingi o‘quv oyining 1-darsidan kechikmasdan "
            "oylik to‘lovni amalga oshirishingizni so‘raymiz.\n\n"
            "💳 To‘lov uchun karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "cycle_end_next_line": (
            "\n🆕 Navbatdagi o‘quv oyi: <b>{next_cycle_title}</b> "
            "(1-dars: <b>{next_start_date}</b>)"
        ),
    },
    "cyrl": {
        "select_mode_title": (
            "📋 <b>Йўқлама қилиш</b>\n\n"
            "Керакли бўлимни танланг:"
        ),
        "select_past_date_title": (
            "🗓 <b>{group}</b> — ўтган дарслардан бирини танланг:\n"
            "<i>(✅ — белгиланган, ⏳ — ҳали белгиланмаган, 🚫 — бекор қилинган)</i>"
        ),
        "no_past_lessons": (
            "ℹ️ <b>{group}</b> гуруҳи учун ўтган дарс саналари топилмади."
        ),
        "future_date_forbidden": (
            "⚠️ Келажакдаги дарс санаси учун йўқлама қилиш мумкин эмас."
        ),
        "default_parent_name": "ота-она",
        "cycle_end_notice": (
            "🔔 <b>Ўқув ойи якунланди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Якунланган ўқув ойи: <b>{cycle_title}</b>"
            "{next_cycle_line}\n\n"
            "Жорий ўқув ойи якунланди. Кейинги ўқув ойининг 1-дарсидан кечикмасдан "
            "ойлик тўловни амалга оширишингизни сўраймиз.\n\n"
            "💳 Тўлов учун карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "cycle_end_next_line": (
            "\n🆕 Навбатдаги ўқув ойи: <b>{next_cycle_title}</b> "
            "(1-дарс: <b>{next_start_date}</b>)"
        ),
    },
}


def _lt(key: str, lang: str = "latn", **kwargs: Any) -> str:
    safe_lang = lang if lang in LOCAL_TEXTS else "latn"
    template = LOCAL_TEXTS[safe_lang].get(key) or LOCAL_TEXTS["latn"].get(key, key)
    return template.format(**kwargs) if kwargs else template


def _get_card_info() -> tuple[str, str]:
    card_number = (
        os.getenv("CARD_NUMBER", "").strip()
        or os.getenv("PAYMENT_CARD_NUMBER", "").strip()
        or "—"
    )
    card_owner = (
        os.getenv("CARD_OWNER", "").strip()
        or os.getenv("PAYMENT_CARD_OWNER", "").strip()
        or "—"
    )
    return card_number, card_owner


def _parse_int(raw: Any) -> Optional[int]:
    val = normalize_chat_id_text(raw)
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
    date_dmy = selected_date.strftime("%d.%m.%Y")
    date_iso = selected_date.isoformat()
    for d_key in (date_dm, date_dmy, date_iso):
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
    db_fn = getattr(database, "is_admin", None)
    if callable(db_fn):
        try:
            if await db_fn(user_id):
                return True
        except Exception:
            pass
    db_user = await get_user(user_id)
    if db_user:
        if db_user.get("role") == "admin" or db_user.get("active_role") == "admin":
            return True
        if "admin" in (db_user.get("roles") or []):
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
        if hasattr(sheets, "a_get_groups_for_role"):
            groups = await sheets.a_get_groups_for_role(user_id, is_admin=True)
        elif hasattr(sheets, "get_groups_for_role"):
            groups = await asyncio.to_thread(
                sheets.get_groups_for_role, user_id, True
            )
        else:
            groups = await asyncio.to_thread(sheets.get_all_groups)
        return True, groups

    if hasattr(sheets, "a_get_groups_for_role"):
        groups = await sheets.a_get_groups_for_role(user_id, is_admin=False)
    elif hasattr(sheets, "get_groups_for_role"):
        groups = await asyncio.to_thread(
            sheets.get_groups_for_role, user_id, False
        )
    else:
        raw_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
        groups = [
            g
            for g in raw_groups
            if str(g.get("Ustoz_Chat_ID") or "").strip() == str(user_id)
        ]

    if not groups:
        return False, []
    return True, groups


async def _filter_today_groups(
    sheets: SheetsManager,
    groups: list[dict[str, Any]],
    today_str: str,
    lang: str,
) -> list[dict[str, Any]]:
    def _filter_sync() -> list[dict[str, Any]]:
        matched: list[dict[str, Any]] = []
        for grp in groups:
            g_name = str(grp.get("Guruh_Nomi") or "").strip()
            if not g_name:
                continue
            cat = sheets.get_group_lesson_dates_categorized(
                g_name, today_str=today_str, lang=lang
            )
            if cat.get("today_lessons"):
                matched.append(grp)
        return matched

    return await asyncio.to_thread(_filter_sync)


async def _can_manage_group(user_id: int, group_name: str) -> bool:
    if await _is_admin(user_id):
        return True
    sheets = get_sheets_manager()
    if hasattr(sheets, "a_get_groups_for_role"):
        teacher_groups = await sheets.a_get_groups_for_role(user_id, is_admin=False)
    else:
        teacher_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
    target = group_name.strip().lower()
    return any(
        str(g.get("Guruh_Nomi") or "").strip().lower() == target
        for g in teacher_groups
    )


async def _resolve_teacher_name(
    sheets: SheetsManager,
    group: Optional[dict[str, Any]],
    fallback_user_id: int,
    fallback_name: str,
) -> str:
    raw_tid = str(group.get("Ustoz_Chat_ID") or "" if group else "").strip()
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


def _get_existing_attendance_for_date_sync(
    sheets: SheetsManager,
    group_name: str,
    lesson_date: date,
    session: Optional[int] = None,
) -> dict[str, str]:
    with sheets._lock:
        ss = sheets._get_spreadsheet()
        date_str = lesson_date.strftime("%d.%m")
        for year_candidate in (lesson_date.year, lesson_date.year - 1):
            try:
                ws = sheets._open_group_year_ws(ss, group_name, year_candidate)
            except Exception:
                continue
            for cycle in reversed(sheets.parse_cycles_from_sheet(ws)):
                target_col = next(
                    (
                        dc["col_idx"]
                        for dc in cycle["date_columns"]
                        if dc["date_str"] == date_str
                        and (
                            session is None
                            or int(dc.get("session") or 1) == int(session)
                        )
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
                ws = sheets._open_group_year_ws(ss, group_name, year_candidate)
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


def _collect_parent_targets(
    student: dict[str, Any], exclude_chat_id: Optional[int]
) -> list[tuple[int, str]]:
    """Returns unique list of (parent_chat_id, parent_name_from_sheet)."""
    targets: list[tuple[int, str]] = []
    seen: set[int] = set()
    for cid_col, name_col in (
        ("Otasi_Chat_ID", "Otasi_FIO"),
        ("Onasi_Chat_ID", "Onasi_FIO"),
        ("OtaOna_Chat_ID", "Otasi_FIO"),
    ):
        cid = _parse_int(student.get(cid_col))
        if cid and cid != exclude_chat_id and cid not in seen:
            seen.add(cid)
            p_name = str(student.get(name_col) or "").strip()
            if not p_name and cid_col == "OtaOna_Chat_ID":
                p_name = str(student.get("Onasi_FIO") or "").strip()
            targets.append((cid, p_name))
    return targets


async def _safe_send(
    bot: Any, chat_id: int, text: str, reply_markup: Any = None
) -> bool:
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


def _past_attendance_dates_kb(
    past_lessons: list[dict[str, Any]], lang: str
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    buttons: list[InlineKeyboardButton] = []
    # Double lessons: one button per DATE ("1-dars"/"2-dars" is picked next).
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in past_lessons:
        key = str(item.get("full_date") or item.get("date_str") or "")
        if key not in merged:
            merged[key] = {**item, "_all_cancelled": True, "_all_marked": True}
            order.append(key)
        bucket = merged[key]
        if not item.get("is_cancelled"):
            bucket["_all_cancelled"] = False
            if not item.get("is_marked"):
                bucket["_all_marked"] = False
    for key in order:
        item = merged[key]
        date_str = item.get("date_str", "")
        full_date = item.get("full_date", "")
        weekday = item.get("weekday", "")
        if item.get("_all_cancelled"):
            icon = "🚫"
        elif item.get("_all_marked"):
            icon = "✅"
        else:
            icon = "⏳"
        label = (
            f"{format_uz_date(date_str, lang)} ({weekday}) {icon}"
            if weekday
            else f"{format_uz_date(date_str, lang)} {icon}"
        )
        buttons.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"att_date:{full_date}",
            )
        )
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


def _no_groups_nav_kb(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("btn_back", lang), callback_data="att_grp:__back__"
        ),
        InlineKeyboardButton(
            text=t("btn_cancel", lang), callback_data="att_grp:__cancel__"
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
            parent_parts.append(
                f"{lbl}: {_format_clickable_phone(item['father_tel'])}"
            )
        if item.get("mother_tel"):
            lbl = "Onasi" if lang == "latn" else "Онаси"
            parent_parts.append(
                f"{lbl}: {_format_clickable_phone(item['mother_tel'])}"
            )
        if not parent_parts and item.get("parent_tel"):
            lbl = "Ota-ona" if lang == "latn" else "Ота-она"
            parent_parts.append(
                f"{lbl}: {_format_clickable_phone(item['parent_tel'])}"
            )
        par_str = " | ".join(parent_parts) if parent_parts else "—"
        return (
            f"• <b>{name}</b> ({dm_tags})\n"
            f"  📞 {stu_tel} | {stu_tg}\n"
            f"  👨‍👩‍👧 {par_str}"
        )

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


async def _broadcast_group_lesson_progress(
    bot: Any,
    group: Optional[dict[str, Any]],
    group_name: str,
    cycle_title: str,
    lesson_num: int,
    total_lessons: int,
    lesson_date: date,
    topic: str,
    teacher_name: str,
) -> bool:
    """
    Posts the clean "📋 Dars yakunlandi" progress summary to the linked group
    Telegram chat (Guruh_TG_Chat_ID). It never contains student names, absences
    or debts. Returns True only when the message was delivered; never raises.
    """
    if not group or not _parse_int(group.get("Guruh_TG_Chat_ID")):
        logging.getLogger(__name__).info(
            "[GROUP_MSG] Lesson progress skipped for %r: no group chat linked",
            group_name,
        )
        return False
    clean_topic = " ".join(str(topic or "").split())
    topic_line = (
        t("group_lesson_progress_topic_line", "latn", topic=html.escape(clean_topic))
        if clean_topic
        else ""
    )
    text = t(
        "group_lesson_progress",
        "latn",
        group_name=html.escape(group_name),
        cycle_title=html.escape(cycle_title or "—"),
        lesson_num=int(lesson_num),
        total_lessons=int(total_lessons),
        date_str=lesson_date.strftime("%d.%m.%Y"),
        optional_topic_line=topic_line,
        teacher_name=html.escape(teacher_name or "—"),
    )
    return await send_group_chat_message(bot, group, text)


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
    card_esc = html.escape(card_number)
    owner_esc = html.escape(card_owner)

    def _build_cycle_end_text(target_lang: str) -> str:
        next_line = ""
        if next_cycle_info:
            next_start_fmt = format_uz_date(
                str(next_cycle_info.get("start_date") or ""), target_lang
            )
            next_line = _lt(
                "cycle_end_next_line",
                target_lang,
                next_cycle_title=html.escape(
                    str(next_cycle_info.get("cycle_title") or "")
                ),
                next_start_date=html.escape(next_start_fmt or "—"),
            )
        return _lt(
            "cycle_end_notice",
            target_lang,
            group=grp_esc,
            cycle_title=cyc_esc,
            next_cycle_line=next_line,
            card_number=card_esc,
            card_owner=owner_esc,
        )

    if _parse_int(group.get("Guruh_TG_Chat_ID")):
        await send_group_chat_message(bot, group, _build_cycle_end_text("latn"))

    active_students = [
        s
        for s in students_by_id.values()
        if str(s.get("Status") or "").strip() == "O'qiyapti"
    ]
    if not active_students:
        active_students = list(students_by_id.values())

    group_key = group_name.strip().lower()
    seen_dm_group: set[tuple[int, str]] = set()
    seen_parent_group: set[tuple[int, str]] = set()

    for student in active_students:
        stu_cid = _parse_int(student.get("Talaba_Chat_ID"))
        if stu_cid:
            stu_key = (stu_cid, group_key)
            if stu_key not in seen_dm_group:
                seen_dm_group.add(stu_key)
                s_lang = await get_user_lang(stu_cid)
                await _safe_send(bot, stu_cid, _build_cycle_end_text(s_lang))

        for par_cid in _collect_parent_chat_ids(student, stu_cid):
            parent_key = (par_cid, group_key)
            if parent_key in seen_parent_group or parent_key in seen_dm_group:
                continue
            seen_parent_group.add(parent_key)
            seen_dm_group.add(parent_key)
            p_lang = await get_user_lang(par_cid)
            await _safe_send(bot, par_cid, _build_cycle_end_text(p_lang))

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
# Attendance Handlers (📋 Yo'qlama qilish) — Two-Button Mode Entry
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

    today_str = now_tashkent().strftime("%d.%m.%Y")
    await state.set_state(ATT_SELECTING_MODE)
    await state.update_data(att_today_str=today_str)
    await message.answer(
        _lt("select_mode_title", lang),
        reply_markup=build_attendance_mode_kb(today_str, lang),
        parse_mode="HTML",
    )


@router.message(
    StateFilter(AttendanceStates, _FallbackAttendanceStates),
    F.text.in_(CANCEL_TEXTS),
)
async def msg_attendance_cancel(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    await state.clear()
    await message.answer(t("attendance_cancelled", lang))


@router.callback_query(StateFilter(ATT_SELECTING_MODE), F.data.startswith("att_mode:"))
async def cb_attendance_select_mode(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message or not callback.data:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    mode = callback.data.split(":", 1)[1].strip()
    if mode not in {"today", "other"}:
        await callback.answer()
        return

    authorized, groups = await _get_authorized_groups(user_id)
    if not authorized:
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return

    today_str = now_tashkent().strftime("%d.%m.%Y")
    sheets = get_sheets_manager()

    if mode == "today":
        today_groups = await _filter_today_groups(sheets, groups, today_str, lang)
        await state.set_state(AttendanceStates.selecting_group)
        await state.update_data(att_mode="today", att_today_str=today_str)
        if not today_groups:
            await callback.message.edit_text(
                t("attendance_no_groups_today", lang),
                reply_markup=_no_groups_nav_kb(lang),
                parse_mode="HTML",
            )
            await callback.answer()
            return

        await callback.message.edit_text(
            t("attendance_select_group", lang),
            reply_markup=groups_inline_kb(
                today_groups,
                prefix="att_grp",
                lang=lang,
                include_back=True,
                include_cancel=True,
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.set_state(AttendanceStates.selecting_group)
    await state.update_data(att_mode="other", att_today_str=today_str)
    await callback.message.edit_text(
        t("attendance_select_group", lang),
        reply_markup=groups_inline_kb(
            groups,
            prefix="att_grp",
            lang=lang,
            include_back=True,
            include_cancel=True,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    AttendanceStates.selecting_group, F.data.startswith("att_grp:")
)
async def cb_attendance_select_group(
    callback: CallbackQuery, state: FSMContext
) -> None:
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

    if group_name == "__back__":
        today_str = now_tashkent().strftime("%d.%m.%Y")
        await state.set_state(ATT_SELECTING_MODE)
        await state.update_data(att_today_str=today_str)
        await callback.message.edit_text(
            _lt("select_mode_title", lang),
            reply_markup=build_attendance_mode_kb(today_str, lang),
            parse_mode="HTML",
        )
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

    data = await state.get_data()
    att_mode = data.get("att_mode", "other")
    today_date = today_tashkent()
    today_str = today_date.strftime("%d.%m.%Y")

    categorized = await sheets.a_get_group_lesson_dates_categorized(
        group_name, today_str=today_str, lang=lang
    )
    cycle_title = categorized.get("cycle_title", "")

    if att_mode == "today":
        today_lessons = categorized.get("today_lessons") or []
        if not today_lessons:
            await callback.answer(
                t("attendance_no_groups_today", lang), show_alert=True
            )
            return

        lesson_date = today_date
        try:
            if today_lessons[0].get("full_date"):
                lesson_date = date.fromisoformat(today_lessons[0]["full_date"])
        except ValueError:
            lesson_date = today_date

        await state.update_data(
            group_name=group_name,
            cycle_title_hint=cycle_title,
        )
        await _open_marking_or_session_picker(
            callback.message,
            state,
            lang,
            group_name,
            lesson_date,
            today_lessons,
            back_cb="att_back:group",
        )
        await callback.answer()
        return

    # Mode == "other": ONLY strictly past lesson dates (< today_dd_mm_yyyy)
    past_lessons = categorized.get("past_lessons") or []
    await state.set_state(ATT_SELECTING_DATE)
    await state.update_data(
        group_name=group_name,
        cycle_title_hint=cycle_title,
        att_today_str=today_str,
    )
    if not past_lessons:
        await callback.message.edit_text(
            _lt("no_past_lessons", lang, group=html.escape(group_name)),
            reply_markup=_past_attendance_dates_kb([], lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        _lt("select_past_date_title", lang, group=html.escape(group_name)),
        reply_markup=_past_attendance_dates_kb(past_lessons, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(StateFilter(ATT_SELECTING_DATE), F.data.startswith("att_date:"))
async def cb_attendance_select_date(
    callback: CallbackQuery, state: FSMContext
) -> None:
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
                include_back=True,
                include_cancel=True,
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    try:
        lesson_date = date.fromisoformat(val)
    except ValueError:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    today_date = today_tashkent()
    if lesson_date >= today_date:
        await callback.answer(_lt("future_date_forbidden", lang), show_alert=True)
        return

    data = await state.get_data()
    group_name: str = data["group_name"]
    if not await _can_manage_group(user_id, group_name):
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return

    sheets = get_sheets_manager()
    categorized = await sheets.a_get_group_lesson_dates_categorized(
        group_name, today_str=today_date.strftime("%d.%m.%Y"), lang=lang
    )
    date_entries = [
        e
        for e in (categorized.get("past_lessons") or [])
        if str(e.get("full_date") or "") == lesson_date.isoformat()
    ]
    await _open_marking_or_session_picker(
        callback.message,
        state,
        lang,
        group_name,
        lesson_date,
        date_entries,
        back_cb="att_back:date",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(
        AttendanceStates.marking_students,
        AttendanceStates.selecting_session,
        AttendanceStates.confirming_cancel_today,
    ),
    F.data.in_({"att_back:date", "att_back:group"}),
)
async def cb_attendance_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()
    group_name = data.get("group_name", "")
    att_mode = data.get("att_mode", "other")
    today_str = now_tashkent().strftime("%d.%m.%Y")
    sheets = get_sheets_manager()

    if callback.data == "att_back:date" and group_name and att_mode != "today":
        categorized = await sheets.a_get_group_lesson_dates_categorized(
            group_name, today_str=today_str, lang=lang
        )
        past_lessons = categorized.get("past_lessons") or []
        await state.set_state(ATT_SELECTING_DATE)
        await state.update_data(
            cycle_title_hint=categorized.get("cycle_title", "")
        )
        await callback.message.edit_text(
            _lt("select_past_date_title", lang, group=html.escape(group_name)),
            reply_markup=_past_attendance_dates_kb(past_lessons, lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    _, groups = await _get_authorized_groups(user_id)
    if att_mode == "today":
        groups = await _filter_today_groups(sheets, groups, today_str, lang)

    await state.set_state(AttendanceStates.selecting_group)
    if not groups:
        await callback.message.edit_text(
            t("attendance_no_groups_today", lang)
            if att_mode == "today"
            else t("contacts_empty", lang),
            reply_markup=_no_groups_nav_kb(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        t("attendance_select_group", lang),
        reply_markup=groups_inline_kb(
            groups,
            prefix="att_grp",
            lang=lang,
            include_back=True,
            include_cancel=True,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    AttendanceStates.marking_students, F.data.startswith("att_toggle:")
)
async def cb_attendance_toggle_student(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    student_id = (callback.data or "").split(":", 1)[1]

    data = await state.get_data()
    students = data.get("students", [])
    marks_map: dict[str, str] = dict(data.get("marks_map", {}))
    att_mode = data.get("att_mode", "other")
    back_cb = "att_back:group" if att_mode == "today" else "att_back:date"

    current = marks_map.get(student_id, "✅")
    marks_map[student_id] = "❌" if current == "✅" else "✅"

    await state.update_data(marks_map=marks_map)
    await callback.message.edit_reply_markup(
        reply_markup=attendance_marking_kb(
            students,
            marks_map,
            lang,
            back_cb=str(data.get("att_back_cb") or back_cb),
            include_topic_btn=False,
            cancel_today_btn=str(data.get("lesson_date") or "")
            == today_tashkent().isoformat(),
        )
    )
    await callback.answer()


@router.callback_query(
    StateFilter(
        AttendanceStates.marking_students,
        AttendanceStates.selecting_session,
        AttendanceStates.confirming_cancel_today,
    ),
    F.data == "att_cancel",
)
async def cb_attendance_cancel_marking(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text(t("attendance_cancelled", lang))
    await callback.answer()


@router.callback_query(AttendanceStates.marking_students, F.data == "att_finish")
async def cb_attendance_finish_instant(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()

    group_name: str = data["group_name"]
    if not await _can_manage_group(user_id, group_name):
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return

    lesson_date = date.fromisoformat(data["lesson_date"])
    marks_map: dict[str, str] = data["marks_map"]
    cycle_title_hint: str = data.get("cycle_title_hint", "")
    date_dm = lesson_date.strftime("%d.%m")
    sana_dmy = lesson_date.strftime("%d.%m.%Y")
    today_dmy = today_tashkent().strftime("%d.%m.%Y")
    is_past_date = sana_dmy != today_dmy
    date_display = format_uz_date(date_dm, lang)

    lesson_session = _parse_int(data.get("lesson_session"))
    sheets = get_sheets_manager()
    previous_marks = await asyncio.to_thread(
        _get_existing_attendance_for_date_sync,
        sheets,
        group_name,
        lesson_date,
        lesson_session,
    )
    prev_was_marked = any(v in {"✅", "❌"} for v in previous_marks.values())

    # Each session of a double-lesson day is its own column (+1 counter each).
    mark_result = await sheets.a_save_attendance_for_date(
        group_name, date_dm, marks_map, session=lesson_session
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
    # Exact ordinal of the lesson date inside its monthly cycle (1-dars ... N-dars).
    dars_raqami = _parse_int(mark_result.get("lesson_number")) or new_count or 1

    all_students = await asyncio.to_thread(
        sheets.get_all_students, group_name=group_name, active_only=False
    )
    students_by_id = {s["Talaba_ID"].strip(): s for s in all_students}

    present_count = sum(1 for m in marks_map.values() if m == "✅")
    absent_count = sum(1 for m in marks_map.values() if m == "❌")

    lesson_topic = await _get_silent_lesson_topic(group_name, lesson_date)
    mavzu = str(lesson_topic.get("topic") or "").strip() if lesson_topic else ""
    teacher_name = await _resolve_teacher_name(
        sheets, group, user_id, callback.from_user.full_name or str(user_id)
    )

    students_sent = 0
    parents_sent = 0
    recipients_names: list[str] = []
    present_items: list[dict[str, Any]] = []
    absent_items: list[dict[str, Any]] = []

    marked_students = [
        students_by_id[sid] for sid in marks_map if sid in students_by_id
    ]
    debt_details = await compute_debt_details_map(sheets, marked_students)
    debt_map = {
        sid: int(child.get("total_sum") or 0) for sid, child in debt_details.items()
    }
    # Prorated ("🆕 Bugundan qo‘shildi") students: remaining lessons of the
    # CURRENT cycle, when that cycle is still part of their unpaid debt.
    prorated_remaining: dict[str, int] = {}
    for _sid, _child in debt_details.items():
        _ov = (_child.get("overrides") or {}).get(str(cycle_title or "").strip())
        if _ov and int(_ov.get("remaining_lessons") or 0) > 0:
            prorated_remaining[_sid] = int(_ov["remaining_lessons"])
    weekday_cache: dict[str, str] = {}
    sana_cache: dict[str, str] = {}

    def _date_parts(l_code: str) -> tuple[str, str]:
        if l_code not in sana_cache:
            sana_cache[l_code] = format_uz_date_long(lesson_date, l_code)
            weekday_cache[l_code] = format_weekday_full(lesson_date, l_code)
        return sana_cache[l_code], weekday_cache[l_code]

    def _topic_line(l_code: str) -> str:
        if not mavzu:
            return ""
        return t("attendance_topic_line", l_code, mavzu=html.escape(mavzu))

    student_dm_ok: dict[str, bool] = {}
    parent_dm_ok_count: dict[str, int] = {}
    # parent_chat_id -> {"name": str, "children": [(sid, stu_name, mark, debt)]}
    parent_buckets: dict[int, dict[str, Any]] = {}

    for sid, mark in marks_map.items():
        student = students_by_id.get(sid)
        if not student:
            continue

        stu_name = str(student.get("F.I.O.") or "").strip() or sid
        stu_cid = _parse_int(student.get("Talaba_Chat_ID"))
        parent_targets = _collect_parent_targets(student, stu_cid)
        total_debt = int(debt_map.get(sid, 0) or 0)

        student_dm_ok[sid] = False
        parent_dm_ok_count[sid] = 0

        if stu_cid:
            s_lang = await get_user_lang(stu_cid)
            stu_has_dual = await has_dual_student_parent_role(stu_cid)
            sana_uz, hafta_kuni = _date_parts(s_lang)
            s_key = (
                "attendance_student_present"
                if mark == "✅"
                else "attendance_student_absent"
            )
            if total_debt > 0 and sid in prorated_remaining:
                s_debt_note = t(
                    "attendance_student_debt_note_prorated",
                    s_lang,
                    qarz_summasi=format_uzs(total_debt),
                    remaining_lessons=prorated_remaining[sid],
                )
            elif total_debt > 0:
                s_debt_note = t(
                    "attendance_student_debt_note",
                    s_lang,
                    qarz_summasi=format_uzs(total_debt),
                )
            else:
                s_debt_note = "\n"
            s_body = t(
                s_key,
                s_lang,
                talaba_ismi=html.escape(stu_name),
                guruh_nomi=html.escape(group_name),
                sana_uz=sana_uz,
                hafta_kuni=hafta_kuni,
                dars_raqami=dars_raqami,
                mavzu_qatori=_topic_line(s_lang),
                talaba_qarz_eslatmasi=s_debt_note,
            )
            s_prefix = ""
            if stu_has_dual:
                s_prefix += dual_role_header("student", s_lang)
            if is_past_date:
                s_prefix += t(
                    "attendance_past_date_notice",
                    s_lang,
                    sana=html.escape(sana_dmy),
                )
            student_dm_ok[sid] = await _safe_send(
                callback.bot, stu_cid, f"{s_prefix}{s_body}"
            )
            if student_dm_ok[sid]:
                students_sent += 1

        for p_cid, p_sheet_name in parent_targets:
            bucket = parent_buckets.setdefault(
                p_cid, {"name": "", "children": []}
            )
            if p_sheet_name and not bucket["name"]:
                bucket["name"] = p_sheet_name
            bucket["children"].append((sid, stu_name, mark, total_debt))

    # One consolidated message per parent chat (siblings are grouped together).
    for p_cid, bucket in parent_buckets.items():
        p_lang = await get_user_lang(p_cid)
        par_has_dual = await has_dual_student_parent_role(p_cid)
        p_name = bucket["name"]
        if not p_name:
            db_p = await get_user(p_cid)
            if db_p and db_p.get("full_name"):
                p_name = str(db_p["full_name"]).strip()
        if not p_name:
            p_name = _lt("default_parent_name", p_lang)

        sana_uz, hafta_kuni = _date_parts(p_lang)
        children_list: list[tuple[str, str, str, int]] = bucket["children"]

        if len(children_list) == 1:
            _sid, c_name, c_mark, c_debt = children_list[0]
            p_key = (
                "attendance_parent_present"
                if c_mark == "✅"
                else "attendance_parent_absent"
            )
            if c_debt > 0 and _sid in prorated_remaining:
                p_debt_note = t(
                    "attendance_parent_debt_note_prorated",
                    p_lang,
                    qarz_summasi=format_uzs(c_debt),
                    remaining_lessons=prorated_remaining[_sid],
                )
            elif c_debt > 0:
                p_debt_note = t(
                    "attendance_parent_debt_note",
                    p_lang,
                    qarz_summasi=format_uzs(c_debt),
                )
            else:
                p_debt_note = "\n"
            p_body = t(
                p_key,
                p_lang,
                ota_ona_ismi=html.escape(p_name),
                talaba_ismi=html.escape(c_name),
                guruh_nomi=html.escape(group_name),
                sana_uz=sana_uz,
                hafta_kuni=hafta_kuni,
                dars_raqami=dars_raqami,
                mavzu_qatori=_topic_line(p_lang),
                ota_ona_qarz_eslatmasi=p_debt_note,
            )
        else:
            blocks: list[str] = []
            debt_items: list[str] = []
            for idx, (_sid, c_name, c_mark, c_debt) in enumerate(children_list, 1):
                is_present = c_mark == "✅"
                blocks.append(
                    t(
                        "attendance_multi_child",
                        p_lang,
                        status_emoji="🟢" if is_present else "🔴",
                        tartib=idx,
                        talaba_ismi=html.escape(c_name),
                        guruh_nomi=html.escape(group_name),
                        dars_raqami=dars_raqami,
                        hafta_kuni=hafta_kuni,
                        holat_matni=t(
                            "attendance_multi_status_present"
                            if is_present
                            else "attendance_multi_status_absent",
                            p_lang,
                        ),
                        oqituvchi_ismi=html.escape(teacher_name),
                        mavzu_qatori=_topic_line(p_lang),
                    )
                )
                if c_debt > 0:
                    debt_items.append(
                        t(
                            "attendance_multi_debt_item",
                            p_lang,
                            talaba_ismi=html.escape(c_name),
                            qarz_summasi=format_uzs(c_debt),
                        )
                    )
            p_body = t(
                "attendance_multi_header",
                p_lang,
                ota_ona_ismi=html.escape(p_name),
                sana_uz=sana_uz,
                hafta_kuni=hafta_kuni,
            ) + "\n\n".join(blocks)
            if debt_items:
                p_body += (
                    f"\n\n{t('attendance_multi_debt_title', p_lang)}\n"
                    + "\n".join(debt_items)
                )
            p_body += f"\n\n{t('attendance_signature', p_lang)}"

        p_prefix = ""
        if par_has_dual:
            p_prefix += dual_role_header(
                "parent", p_lang, [c[1] for c in children_list]
            )
        if is_past_date:
            p_prefix += t(
                "attendance_past_date_notice",
                p_lang,
                sana=html.escape(sana_dmy),
            )
        if await _safe_send(callback.bot, p_cid, f"{p_prefix}{p_body}"):
            parents_sent += 1
            for c_sid, _n, _m, _d in children_list:
                parent_dm_ok_count[c_sid] = parent_dm_ok_count.get(c_sid, 0) + 1

    for sid, mark in marks_map.items():
        student = students_by_id.get(sid)
        if not student:
            continue
        stu_name = str(student.get("F.I.O.") or "").strip() or sid
        stu_dm_ok = student_dm_ok.get(sid, False)
        par_dm_ok_count = parent_dm_ok_count.get(sid, 0)

        if stu_dm_ok or par_dm_ok_count > 0:
            recipients_names.append(stu_name)

        dm_status_parts = [
            "🎓✅" if stu_dm_ok else "🎓❌",
            f"👨‍👩‍👧✅({par_dm_ok_count})" if par_dm_ok_count > 0 else "👨‍👩‍👧❌",
        ]

        item_payload = {
            "name": stu_name,
            "stu_tel": str(student.get("Talaba_Tel") or "").strip(),
            "stu_tg": str(student.get("Talaba_TG") or "").strip(),
            "father_tel": str(student.get("Otasi_Tel") or "").strip(),
            "mother_tel": str(student.get("Onasi_Tel") or "").strip(),
            "parent_tel": str(student.get("OtaOna_Tel") or "").strip(),
            "dm_status": " ".join(dm_status_parts),
        }
        if mark == "✅":
            present_items.append(item_payload)
        else:
            absent_items.append(item_payload)

    await state.clear()
    await callback.message.edit_text(
        t(
            "attendance_saved_instant",
            lang,
            group=html.escape(group_name),
            date=date_display,
            present_count=present_count,
            absent_count=absent_count,
        ),
        parse_mode="HTML",
    )

    # Group chat progress summary (no student names / absences / debts). Sent once
    # per lesson - an edited re-submission does not spam the group again.
    if not is_resubmit:
        await _broadcast_group_lesson_progress(
            bot=callback.bot,
            group=group,
            group_name=group_name,
            cycle_title=cycle_title,
            lesson_num=dars_raqami,
            total_lessons=limit,
            lesson_date=lesson_date,
            topic=mavzu,
            teacher_name=teacher_name,
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
            "name": str(d.get("F.I.O.") or "").strip() or str(d.get("Talaba_ID") or ""),
            "debts": str(d.get("Qarzdor_Oylar") or "").strip(),
            "debt_count": len(
                [x for x in str(d.get("Qarzdor_Oylar") or "").split(";") if x.strip()]
            ),
            "stu_tel": str(d.get("Talaba_Tel") or "").strip(),
            "parent_tel": (
                str(d.get("Otasi_Tel") or "").strip()
                or str(d.get("Onasi_Tel") or "").strip()
                or str(d.get("OtaOna_Tel") or "").strip()
            ),
        }
        for d in group_debtors
    ]

    # Per-day schedules: the report shows the time of THAT lesson's weekday.
    raw_lesson_time = str(group.get("Dars_Vaqti") or "").strip() if group else ""
    lesson_time = (
        get_lesson_time_for_weekday(raw_lesson_time, lesson_date) or raw_lesson_time
    ) or "—"

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

# ----------------------------------------------------------------------
# Double lessons ("1-dars" / "2-dars") and "🚫 Bugungi dars bo‘lmaydi"
# ----------------------------------------------------------------------


def _session_suffix(session: Optional[int], lang: str) -> str:
    return t("attendance_session_suffix", lang, n=int(session)) if session else ""


async def _open_attendance_marking(
    target_msg: Message,
    state: FSMContext,
    lang: str,
    group_name: str,
    lesson_date: date,
    session: Optional[int],
    back_cb: str,
) -> None:
    """Shows the ✅/❌ marking screen of one lesson (one session on double days)."""
    sheets = get_sheets_manager()
    active_students = await asyncio.to_thread(sheets.get_all_students, group_name, True)
    if not active_students:
        await state.clear()
        await target_msg.edit_text(t("contacts_empty", lang))
        return
    existing_marks = await asyncio.to_thread(
        _get_existing_attendance_for_date_sync, sheets, group_name, lesson_date, session
    )
    students_min = [
        {"Talaba_ID": s["Talaba_ID"], "F.I.O.": s["F.I.O."]} for s in active_students
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
        group_name=group_name,
        lesson_date=lesson_date.isoformat(),
        lesson_session=session,
        students=students_min,
        marks_map=marks_map,
        att_back_cb=back_cb,
    )
    await _render_marking_screen(target_msg, state, lang)


async def _render_marking_screen(target_msg: Message, state: FSMContext, lang: str) -> None:
    data = await state.get_data()
    group_name = str(data.get("group_name") or "")
    lesson_date = date.fromisoformat(str(data["lesson_date"]))
    session = _parse_int(data.get("lesson_session"))
    await target_msg.edit_text(
        t(
            "attendance_mark_title",
            lang,
            group=html.escape(group_name),
            date=format_uz_date(lesson_date.strftime("%d.%m"), lang),
        )
        + _session_suffix(session, lang),
        reply_markup=attendance_marking_kb(
            list(data.get("students") or []),
            dict(data.get("marks_map") or {}),
            lang,
            back_cb=str(data.get("att_back_cb") or "att_back:group"),
            include_topic_btn=False,
            cancel_today_btn=lesson_date == today_tashkent(),
        ),
        parse_mode="HTML",
    )


async def _open_marking_or_session_picker(
    target_msg: Message,
    state: FSMContext,
    lang: str,
    group_name: str,
    lesson_date: date,
    date_entries: list[dict[str, Any]],
    back_cb: str,
) -> None:
    """
    Double-lesson day (2 columns for the date) -> '1-dars' / '2-dars' picker;
    otherwise straight to the marking screen of the date's only lesson.
    """
    sessions = sorted(
        (e for e in date_entries if e.get("session")),
        key=lambda e: int(e.get("session") or 1),
    )
    if len(sessions) > 1:
        await state.set_state(AttendanceStates.selecting_session)
        await state.update_data(
            group_name=group_name,
            lesson_date=lesson_date.isoformat(),
            att_back_cb=back_cb,
            att_sessions=[
                {
                    "session": int(e.get("session") or 1),
                    "is_marked": bool(e.get("is_marked")),
                    "is_cancelled": bool(e.get("is_cancelled")),
                }
                for e in sessions
            ],
        )
        await target_msg.edit_text(
            t(
                "attendance_select_session",
                lang,
                group=html.escape(group_name),
                date=format_uz_date(lesson_date.strftime("%d.%m"), lang),
            ),
            reply_markup=attendance_session_picker_kb(sessions, lang, back_cb=back_cb),
            parse_mode="HTML",
        )
        return
    only_session = (
        int(sessions[0].get("session") or 1) if len(sessions) == 1 else None
    )
    await _open_attendance_marking(
        target_msg, state, lang, group_name, lesson_date, only_session, back_cb
    )


@router.callback_query(AttendanceStates.selecting_session, F.data.startswith("att_sess:"))
async def cb_attendance_select_session(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()
    group_name = str(data.get("group_name") or "")
    if not group_name or not await _can_manage_group(user_id, group_name):
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return
    session = _parse_int((callback.data or "").split(":", 1)[1])
    known = {int(x.get("session") or 0): x for x in (data.get("att_sessions") or [])}
    if session not in known:
        await callback.answer()
        return
    if known[session].get("is_cancelled"):
        await callback.answer(t("attendance_session_cancelled", lang), show_alert=True)
        return
    await _open_attendance_marking(
        callback.message,
        state,
        lang,
        group_name,
        date.fromisoformat(str(data["lesson_date"])),
        session,
        str(data.get("att_back_cb") or "att_back:group"),
    )
    await callback.answer()


@router.callback_query(AttendanceStates.marking_students, F.data == "att_cancel_today")
async def cb_attendance_cancel_today_ask(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """'🚫 Bugungi dars bo‘lmaydi' -> confirmation."""
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()
    group_name = str(data.get("group_name") or "")
    if not group_name or not await _can_manage_group(user_id, group_name):
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return
    lesson_date = date.fromisoformat(str(data["lesson_date"]))
    if lesson_date != today_tashkent():
        await callback.answer(t("lesson_not_today_only_today", lang), show_alert=True)
        return
    session = _parse_int(data.get("lesson_session"))
    await state.set_state(AttendanceStates.confirming_cancel_today)
    await callback.message.edit_text(
        t(
            "lesson_not_today_confirm",
            lang,
            group=html.escape(group_name),
            date=format_uz_date_long(lesson_date, lang),
            session_line=_session_suffix(session, lang),
        ),
        reply_markup=attendance_cancel_today_confirm_kb(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    AttendanceStates.confirming_cancel_today, F.data.startswith("att_cancel_today:")
)
async def cb_attendance_cancel_today_decide(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()
    group_name = str(data.get("group_name") or "")
    choice = (callback.data or "").split(":", 1)[1]
    if choice != "yes":
        await state.set_state(AttendanceStates.marking_students)
        await _render_marking_screen(callback.message, state, lang)
        await callback.answer()
        return
    if not group_name or not await _can_manage_group(user_id, group_name):
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return

    lesson_date = date.fromisoformat(str(data["lesson_date"]))
    session = _parse_int(data.get("lesson_session"))
    if lesson_date != today_tashkent():
        await callback.answer(t("lesson_not_today_only_today", lang), show_alert=True)
        return
    if await is_lesson_cancelled(group_name, lesson_date.isoformat(), session or 0):
        await state.clear()
        await callback.message.edit_text(
            t("lesson_not_today_already", lang, group=html.escape(group_name)),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    sheets = get_sheets_manager()
    try:
        # Column -> "Qoldirildi" (muted gray) + 1 replacement column at the end.
        # Otilgan_Dars_Hisoblagich is NOT incremented (+0).
        result = await sheets.a_cancel_lesson_and_shift_date(
            group_name, lesson_date, session=session, muted=True
        )
    except Exception:
        logger.exception("Teacher lesson cancel failed for %s %s", group_name, lesson_date)
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    new_date = result.get("new_lesson_date")
    new_session = result.get("new_session")
    group = await sheets.a_get_group(group_name) or {}
    is_double = get_group_daily_lessons(group) >= 2
    new_date_iso = new_date.isoformat() if isinstance(new_date, date) else ""
    await record_cancelled_lesson(
        group_name,
        lesson_date.isoformat(),
        session or 0,
        cancelled_by=user_id,
        replacement_date=new_date_iso,
    )
    await state.clear()

    def _new_date_text(l_code: str) -> str:
        if not isinstance(new_date, date):
            return "—"
        text = format_uz_date_long(new_date, l_code)
        if is_double and new_session:
            text += _session_suffix(int(new_session), l_code)
        return text

    counter = _parse_int(group.get("Otilgan_Dars_Hisoblagich")) or 0
    total = _parse_int(group.get("Oylik_Dars_Soni")) or 12
    await callback.message.edit_text(
        t(
            "lesson_not_today_done",
            lang,
            group=html.escape(group_name),
            date=format_uz_date_long(lesson_date, lang),
            session_line=_session_suffix(session, lang),
            new_date=_new_date_text(lang),
            counter=counter,
            total=total,
        ),
        parse_mode="HTML",
    )
    await callback.answer()

    teacher_name = await _resolve_teacher_name(
        sheets, group, user_id, callback.from_user.full_name or str(user_id)
    )
    if group:
        await send_group_chat_message(
            callback.bot,
            group,
            t(
                "lesson_not_today_group_notice",
                "latn",
                group=html.escape(group_name),
                date=format_uz_date_long(lesson_date, "latn"),
                session_line=_session_suffix(session, "latn"),
                new_date=_new_date_text("latn"),
                teacher_name=html.escape(teacher_name or "—"),
            ),
        )
    students = await asyncio.to_thread(sheets.get_all_students, group_name, True)
    for stu in students:
        stu_cid = _parse_int(stu.get("Talaba_Chat_ID"))
        if not stu_cid:
            continue
        s_lang = await get_user_lang(stu_cid)
        await _safe_send(
            callback.bot,
            stu_cid,
            t(
                "lesson_not_today_group_notice",
                s_lang,
                group=html.escape(group_name),
                date=format_uz_date_long(lesson_date, s_lang),
                session_line=_session_suffix(session, s_lang),
                new_date=_new_date_text(s_lang),
                teacher_name=html.escape(teacher_name or "—"),
            ),
        )
