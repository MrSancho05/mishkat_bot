import asyncio
import html
import logging
import re
from datetime import date, datetime
from typing import Any, Optional

import aiosqlite
from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.utils import format_lesson_time_display, today_tashkent
from app.config import ADMIN_IDS, DB_PATH, TZ
from app.database import (
    get_group_topics_history,
    get_lesson_topic,
    get_teacher_by_telegram_id,
    get_user,
    get_user_lang,
    mark_topics_published,
    save_lesson_topic,
)
from app.keyboards import (
    InlineKeyboardBuilder,
    groups_inline_kb,
    parent_schedule_kb,
    step_nav_inline_kb,
    topic_dates_kb,
    topic_group_action_kb,
)
from app.locales import (
    WEEKDAYS_SHORT,
    button_texts,
    format_full_weekdays,
    format_uz_date,
    format_uz_date_list,
    format_weekday_full,
    t,
)
from app.sheets import (
    generate_cycle_dates,
    get_sheets_manager,
    parse_weekdays,
)
from app.states import TopicStates

logger = logging.getLogger(__name__)
router = Router(name="schedule")

TOPIC_MENU_TEXTS = button_texts("menu_teacher_topic", "menu_lesson_topic")

_LOCAL_SCHED_TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "no_groups": "ℹ️ Sizga biriktirilgan guruhlar topilmadi.",
        "schedule_not_configured": (
            "ℹ️ <b>{group}</b> guruhi uchun dars jadvali hali sozlanmagan."
        ),
        "remaining_lessons_line": "📊 Qolgan darslar: <b>{remaining} / {total} ta</b>",
        "upcoming_dates_line": "🗓 Joriy oy sanalari: <code>{dates}</code>",
        "teacher_schedule_card": (
            "📅 <b>Dars jadvali — {group}</b>\n\n"
            "📆 Dars kunlari: <b>{days}</b>\n"
            "⏰ Dars vaqti: <b>{time}</b>\n"
            "📊 Qolgan darslar: <b>{remaining} / {total} ta</b>\n"
            "🗓 Joriy oy sanalari: <code>{dates}</code>"
        ),
        "parent_child_block": (
            "👶 Farzand: <b>{child_fio}</b>\n"
            "📚 Guruh: <b>{group_name}</b>\n"
            "🗓 Dars kunlari: <b>{full_weekdays}</b>\n"
            "⏰ Dars vaqti: <b>{lesson_time}</b>\n"
            "👨‍🏫 Ustoz: <b>{teacher_name}</b>\n"
            "📖 Oxirgi mavzu: {latest_topic}"
        ),
        "not_set": "Belgilanmagan",
        "no_topic_yet": "Hali kiritilmagan",
        "topic_choose_action": "📝 <b>{group}</b> — kerakli bo‘limni tanlang:",
        "topic_no_permission": "❌ Sizda ushbu guruh uchun mavzu kiritish huquqi yo‘q.",
        "topic_existing_hint": (
            "\n\nℹ️ <i>Avvalgi mavzu:</i> <b>{topic}</b>\n"
            "<i>Avvalgi reja:</i> {plan}"
        ),
        "topic_header_new": "📚 Yangi dars mavzusi va rejasi",
        "topic_header_added": "➕ Mavzularga qo'shimcha kiritildi",
        "topic_header_updated": "✏️ Dars mavzusi o'zgartirildi",
        "topic_auto_publish_note": (
            "⏳ <i>Agar «📢 Guruhga yuborish» tugmasini bosmasangiz, saqlangan mavzu "
            "30 daqiqadan so‘ng avtomatik ravishda guruh, talabalar va ota-onalarga yuboriladi.</i>"
        ),
        "topic_saved_with_count": (
            "✅ <b>{group} ({date})</b> uchun dars mavzusi saqlandi "
            "(yuborishga tayyor: <b>{pending_count} ta</b> sana).\n\n"
            "⏳ <i>«📢 Guruhga yuborish» tugmasini bosmasangiz, tizim 30 daqiqadan so‘ng "
            "saqlangan mavzularni avtomatik e'lon qiladi.</i>"
        ),
        "btn_add_more_date": "➕ Boshqa sana",
        "topic_nothing_to_publish": (
            "ℹ️ Ushbu guruh uchun yuborilmagan yangi mavzular topilmadi "
            "(allaqachon e'lon qilingan bo‘lishi mumkin)."
        ),
        "topic_broadcast_summary": (
            "✅ <b>{group}</b> guruhi bo‘yicha <b>{topic_count} ta</b> dars mavzusi va rejasi "
            "e'lon qilindi (<b>{sent} ta</b> chatga yuborildi)!"
        ),
        "sched_detail_header": "📄 <b>Dars jadvali — batafsil</b>",
        "sched_detail_child": "👶 <b>{child_fio}</b> — 📚 {group_name}",
        "sched_lesson_present": "🟢 {sana} ({hafta_kuni}) — Kelgan",
        "sched_lesson_absent": "🔴 {sana} ({hafta_kuni}) — Kelmagan",
        "sched_lesson_upcoming": "⏳ {sana} ({hafta_kuni}) — Kelgusi dars",
        "sched_lesson_unmarked": "➖ {sana} ({hafta_kuni}) — Belgilanmagan",
        "sched_no_lessons": "ℹ️ Joriy o'quv oyi uchun dars sanalari topilmadi.",
        "sched_detail_error": "❌ Ma'lumotni yuklab bo'lmadi. Keyinroq qayta urinib ko'ring.",
        "label_group": "📚 Guruh:",
        "label_date": "📅 Sana:",
        "label_topic": "📖 Mavzu:",
        "label_plan": "📝 Dars mazmuni / Uyga vazifa:",
    },
    "cyrl": {
        "no_groups": "ℹ️ Сизга бириктирилган гуруҳлар топилмади.",
        "schedule_not_configured": (
            "ℹ️ <b>{group}</b> гуруҳи учун дарс жадвали ҳали созланмаган."
        ),
        "remaining_lessons_line": "📊 Қолган дарслар: <b>{remaining} / {total} та</b>",
        "upcoming_dates_line": "🗓 Жорий ой саналари: <code>{dates}</code>",
        "teacher_schedule_card": (
            "📅 <b>Дарс жадвали — {group}</b>\n\n"
            "📆 Дарс кунлари: <b>{days}</b>\n"
            "⏰ Дарс вақти: <b>{time}</b>\n"
            "📊 Қолган дарслар: <b>{remaining} / {total} та</b>\n"
            "🗓 Жорий ой саналари: <code>{dates}</code>"
        ),
        "parent_child_block": (
            "👶 Фарзанд: <b>{child_fio}</b>\n"
            "📚 Гуруҳ: <b>{group_name}</b>\n"
            "🗓 Дарс кунлари: <b>{full_weekdays}</b>\n"
            "⏰ Дарс вақти: <b>{lesson_time}</b>\n"
            "👨‍🏫 Устоз: <b>{teacher_name}</b>\n"
            "📖 Охирги мавзу: {latest_topic}"
        ),
        "not_set": "Белгиланмаган",
        "no_topic_yet": "Ҳали киритилмаган",
        "topic_choose_action": "📝 <b>{group}</b> — керакли бўлимни танланг:",
        "topic_no_permission": "❌ Сизда ушбу гуруҳ учун мавзу киритиш ҳуқуқи йўқ.",
        "topic_existing_hint": (
            "\n\nℹ️ <i>Аввалги мавзу:</i> <b>{topic}</b>\n"
            "<i>Аввалги режа:</i> {plan}"
        ),
        "topic_header_new": "📚 Янги дарс мавзуси ва режаси",
        "topic_header_added": "➕ Мавзуларга қўшимча киритилди",
        "topic_header_updated": "✏️ Дарс мавзуси ўзгартирилди",
        "topic_auto_publish_note": (
            "⏳ <i>Агар «📢 Гуруҳга юбориш» тугмасини босмасангиз, сақланган мавзу "
            "30 дақиқадан сўнг автоматик равишда гуруҳ, талабалар ва ота-оналарга юборилади.</i>"
        ),
        "topic_saved_with_count": (
            "✅ <b>{group} ({date})</b> учун дарс мавзуси сақланди "
            "(юборишга тайёр: <b>{pending_count} та</b> сана).\n\n"
            "⏳ <i>«📢 Гуруҳга юбориш» тугмасини босмасангиз, тизим 30 дақиқадан сўнг "
            "сақланган мавзуларни автоматик эълон қилади.</i>"
        ),
        "btn_add_more_date": "➕ Бошқа сана",
        "topic_nothing_to_publish": (
            "ℹ️ Ушбу гуруҳ учун юборилмаган янги мавзулар топилмади "
            "(аллақачон эълон қилинган бўлиши мумкин)."
        ),
        "topic_broadcast_summary": (
            "✅ <b>{group}</b> гуруҳи бўйича <b>{topic_count} та</b> дарс мавзуси ва режаси "
            "эълон қилинди (<b>{sent} та</b> чатга юборилди)!"
        ),
        "sched_detail_header": "📄 <b>Дарс жадвали — батафсил</b>",
        "sched_detail_child": "👶 <b>{child_fio}</b> — 📚 {group_name}",
        "sched_lesson_present": "🟢 {sana} ({hafta_kuni}) — Келган",
        "sched_lesson_absent": "🔴 {sana} ({hafta_kuni}) — Келмаган",
        "sched_lesson_upcoming": "⏳ {sana} ({hafta_kuni}) — Келгуси дарс",
        "sched_lesson_unmarked": "➖ {sana} ({hafta_kuni}) — Белгиланмаган",
        "sched_no_lessons": "ℹ️ Жорий ўқув ойи учун дарс саналари топилмади.",
        "sched_detail_error": "❌ Маълумотни юклаб бўлмади. Кейинроқ қайта уриниб кўринг.",
        "label_group": "📚 Гуруҳ:",
        "label_date": "📅 Сана:",
        "label_topic": "📖 Мавзу:",
        "label_plan": "📝 Дарс мазмуни / Уйга вазифа:",
    },
}


def _lt(key: str, lang: str, **kwargs: Any) -> str:
    safe = lang if lang in _LOCAL_SCHED_TEXTS else "latn"
    txt = _LOCAL_SCHED_TEXTS[safe][key]
    return txt.format(**kwargs) if kwargs else txt


def _format_days_list(day_indices: list[int], lang: str) -> str:
    safe = lang if lang in WEEKDAYS_SHORT else "latn"
    return ", ".join(WEEKDAYS_SHORT[safe][d] for d in sorted(day_indices))


def _fmt_topic_date(raw_date: str, lang: str) -> str:
    cleaned = str(raw_date or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
        try:
            cleaned = datetime.strptime(cleaned, "%Y-%m-%d").strftime("%d.%m")
        except ValueError:
            pass
    return format_uz_date(cleaned, lang)


def _topic_phone_key(phone: Any) -> str:
    cleaned = str(phone or "").strip()
    if not cleaned or cleaned in {"Ma'lumot kiritilmagan", "Yo'q", "yo'q", "yoq", "—", "-"}:
        return ""
    digits = re.sub(r"\D", "", cleaned)
    if len(digits) < 7:
        return ""
    if len(digits) == 9:
        return f"998{digits}"
    return digits


def _parse_int_chat_id(raw: Any) -> Optional[int]:
    val = str(raw or "").strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
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


async def _get_accessible_groups(user_id: int) -> tuple[str | None, list[dict]]:
    sheets = get_sheets_manager()
    if await _is_admin(user_id):
        groups = await asyncio.to_thread(sheets.get_all_groups)
        return "admin", groups
    raw_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
    teacher_groups = [
        g
        for g in raw_groups
        if str(g.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
    ]
    if teacher_groups:
        return "teacher", teacher_groups
    return None, []


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
    user_id: Optional[int],
    group_name: Optional[str] = None,
    fallback_name: str = "",
    group: Optional[dict[str, Any]] = None,
    lang: str = "latn",
) -> str:
    if fallback_name and fallback_name.strip():
        return fallback_name.strip()

    sheets = get_sheets_manager()
    if user_id:
        try:
            sheet_teacher = await sheets.a_get_teacher_by_chat_id(user_id)
            if sheet_teacher:
                fio = str(sheet_teacher.get("F.I.O.", "")).strip()
                if fio and fio != "Ma'lumot kiritilmagan":
                    return fio
        except Exception:
            pass
        db_teacher = await get_teacher_by_telegram_id(user_id)
        if db_teacher and str(db_teacher.get("full_name", "")).strip():
            return str(db_teacher["full_name"]).strip()
        db_user = await get_user(user_id)
        if db_user and str(db_user.get("full_name", "")).strip():
            return str(db_user["full_name"]).strip()

    resolved_group = group
    if resolved_group is None and group_name:
        resolved_group = await sheets.a_get_group(group_name)

    if resolved_group:
        g_cid = _parse_int_chat_id(resolved_group.get("Ustoz_Chat_ID"))
        if g_cid:
            try:
                t_rec = await sheets.a_get_teacher_by_chat_id(g_cid)
                if t_rec and str(t_rec.get("F.I.O.", "")).strip():
                    fio = str(t_rec["F.I.O."]).strip()
                    if fio != "Ma'lumot kiritilmagan":
                        return fio
            except Exception:
                pass
            db_t = await get_teacher_by_telegram_id(g_cid)
            if db_t and str(db_t.get("full_name", "")).strip():
                return str(db_t["full_name"]).strip()
            db_u = await get_user(g_cid)
            if db_u and str(db_u.get("full_name", "")).strip():
                return str(db_u["full_name"]).strip()
        g_tid = str(resolved_group.get("Ustoz_ID", "")).strip()
        if g_tid:
            try:
                t_rec = await sheets.a_get_teacher_by_id(g_tid)
                if t_rec and str(t_rec.get("F.I.O.", "")).strip():
                    fio = str(t_rec["F.I.O."]).strip()
                    if fio != "Ma'lumot kiritilmagan":
                        return fio
            except Exception:
                pass
        for col in ("Ustoz_FIO", "Ustoz"):
            g_fio = str(resolved_group.get(col, "")).strip()
            if g_fio and g_fio != "Ma'lumot kiritilmagan":
                return g_fio

    return "Устоз" if lang == "cyrl" else "Ustoz"


def _resolve_status_header(edit_modes: list[str], lang: str) -> str:
    unique_modes = {m.strip() for m in edit_modes if m and m.strip()}
    if unique_modes == {"appended"}:
        return _lt("topic_header_added", lang)
    if "edited" in unique_modes or (
        "appended" in unique_modes and "new" not in unique_modes
    ):
        return _lt("topic_header_updated", lang)
    return _lt("topic_header_new", lang)


def _format_topic_announcement_message(
    group_name: str,
    topic_rows: list[dict[str, Any]],
    teacher_name: str,
    lang: str,
) -> str:
    modes = [str(r.get("edit_mode") or "new") for r in topic_rows]
    header = _resolve_status_header(modes, lang)
    footer = t(
        "topic_teacher_footer",
        lang,
        teacher_name=html.escape(teacher_name),
    )

    blocks: list[str] = []
    for r in topic_rows:
        date_fmt = _fmt_topic_date(str(r.get("lesson_date", "")), lang)
        topic_val = str(r.get("topic") or r.get("topic_title") or "—").strip()
        plan_val = str(r.get("plan") or r.get("lesson_details") or "—").strip()
        mode = str(r.get("edit_mode") or "new").strip()

        mode_badge = ""
        if len(topic_rows) > 1:
            if mode == "appended":
                mode_badge = f" <i>({_lt('topic_header_added', lang)})</i>"
            elif mode == "edited":
                mode_badge = f" <i>({_lt('topic_header_updated', lang)})</i>"

        blocks.append(
            f"{_lt('label_date', lang)} <b>{html.escape(date_fmt)}</b>{mode_badge}\n"
            f"{_lt('label_topic', lang)} <b>{html.escape(topic_val)}</b>\n"
            f"{_lt('label_plan', lang)}\n<i>{html.escape(plan_val)}</i>"
        )

    body = "\n\n".join(blocks)
    return (
        f"<b>{html.escape(header)}</b>\n\n"
        f"{_lt('label_group', lang)} <b>{html.escape(group_name)}</b>\n\n"
        f"{body}\n\n"
        f"{footer}"
    )


def _build_topic_publish_kb(
    group_name: str,
    date_str: str,
    lang: str,
    include_save_only: bool = True,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("btn_topic_broadcast", lang),
            callback_data=f"publish_topics:{group_name}",
        ),
        InlineKeyboardButton(
            text=_lt("btn_add_more_date", lang),
            callback_data=f"topic_add_more:{group_name}",
        ),
    )
    row_actions = [
        InlineKeyboardButton(
            text=t("btn_topic_edit", lang),
            callback_data=f"topic_edit:{date_str}",
        )
    ]
    if include_save_only:
        row_actions.append(
            InlineKeyboardButton(
                text=t("btn_topic_save_only", lang),
                callback_data=f"topic_save:{date_str}",
            )
        )
    builder.row(*row_actions)
    builder.row(
        InlineKeyboardButton(
            text=t("btn_back", lang), callback_data="topic_back:date"
        ),
        InlineKeyboardButton(
            text=t("btn_cancel", lang), callback_data="topic_cancel"
        ),
    )
    return builder.as_markup()


async def publish_group_topics(
    bot: Bot,
    group_name: str,
    lesson_dates: Optional[list[str]] = None,
    actor_user_id: Optional[int] = None,
) -> tuple[int, int]:
    """
    Publishes unpublished lesson topics for `group_name` (or specific `lesson_dates`)
    to Group chat, Students, and Parents deduplicated per (OtaOna_Chat_ID, Guruh).
    Returns (published_topic_count, messages_sent_count).
    """
    history = await get_group_topics_history(group_name, limit=50)
    unpublished = [
        row for row in reversed(history) if int(row.get("is_published") or 0) == 0
    ]
    if lesson_dates is not None:
        wanted = {d.strip() for d in lesson_dates if d and d.strip()}
        unpublished = [
            row
            for row in unpublished
            if str(row.get("lesson_date", "")).strip() in wanted
        ]

    if not unpublished:
        return 0, 0

    first_row = unpublished[0]
    row_teacher_id = first_row.get("teacher_id") or actor_user_id
    row_teacher_name = str(first_row.get("teacher_name") or "").strip()
    teacher_name = await _resolve_teacher_name(
        user_id=row_teacher_id,
        group_name=group_name,
        fallback_name=row_teacher_name,
    )

    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    active_students = await asyncio.to_thread(
        sheets.get_all_students, group_name, True
    )

    sent_count = 0
    group_key = group_name.strip().lower()

    # 1. Group Telegram Chat (Latin script)
    if group:
        grp_tg_cid = _parse_int_chat_id(group.get("Guruh_TG_Chat_ID"))
        if grp_tg_cid is not None:
            grp_msg = _format_topic_announcement_message(
                group_name=group_name,
                topic_rows=unpublished,
                teacher_name=teacher_name,
                lang="latn",
            )
            try:
                await bot.send_message(
                    chat_id=grp_tg_cid,
                    text=grp_msg,
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
                sent_count += 1
            except Exception as exc:
                logger.warning(
                    "Topic broadcast to group chat %s (%s) failed: %s",
                    grp_tg_cid,
                    group_name,
                    exc,
                )

    # 2. Students & Parents (deduplicated per (parent_chat_id, group_name))
    seen_dm_group: set[tuple[int, str]] = set()
    msg_cache_by_lang: dict[str, str] = {}

    # Parent chat ids bound on sibling rows (same parent phone) are reused so
    # a parent who registered through another child still gets the topic.
    try:
        all_rows = await asyncio.to_thread(sheets.get_all_students, None, False)
    except Exception:
        all_rows = list(active_students)
    phone_to_parent: dict[str, set[int]] = {}
    for row in all_rows:
        for chat_col, tel_col in (
            ("Otasi_Chat_ID", "Otasi_Tel"),
            ("Onasi_Chat_ID", "Onasi_Tel"),
            ("OtaOna_Chat_ID", "OtaOna_Tel"),
        ):
            p_cid_row = _parse_int_chat_id(row.get(chat_col))
            p_key = _topic_phone_key(row.get(tel_col))
            if p_cid_row is not None and p_key:
                phone_to_parent.setdefault(p_key, set()).add(p_cid_row)

    parent_children: dict[int, list[str]] = {}
    student_targets: list[int] = []
    for stu in active_students:
        stu_cid = _parse_int_chat_id(stu.get("Talaba_Chat_ID"))
        if stu_cid is not None:
            dm_key = (stu_cid, group_key)
            if dm_key not in seen_dm_group:
                seen_dm_group.add(dm_key)
                student_targets.append(stu_cid)

        stu_name = str(stu.get("F.I.O.") or stu.get("Talaba_ID") or "").strip()
        for chat_col, tel_col in (
            ("Otasi_Chat_ID", "Otasi_Tel"),
            ("Onasi_Chat_ID", "Onasi_Tel"),
            ("OtaOna_Chat_ID", "OtaOna_Tel"),
        ):
            candidates: list[int] = []
            direct = _parse_int_chat_id(stu.get(chat_col))
            if direct is not None:
                candidates.append(direct)
            else:
                p_key = _topic_phone_key(stu.get(tel_col))
                candidates.extend(sorted(phone_to_parent.get(p_key, set())))
            for p_cid in candidates:
                if p_cid == stu_cid:
                    continue
                names = parent_children.setdefault(p_cid, [])
                if stu_name and stu_name not in names:
                    names.append(stu_name)

    async def _send_dm_for_target(chat_id: int, children_names: Optional[list[str]] = None) -> None:
        nonlocal sent_count
        try:
            r_lang = await get_user_lang(chat_id)
            if children_names:
                text = _format_topic_announcement_message(
                    group_name=group_name,
                    topic_rows=unpublished,
                    teacher_name=teacher_name,
                    lang=r_lang,
                )
                child_label = (
                    ("👶 Фарзандларингиз" if len(children_names) > 1 else "👶 Фарзандингиз")
                    if r_lang == "cyrl"
                    else ("👶 Farzandlaringiz" if len(children_names) > 1 else "👶 Farzandingiz")
                )
                child_line = (
                    f"{child_label}: <b>"
                    + ", ".join(html.escape(n) for n in children_names)
                    + "</b>\n"
                )
                first_break = text.find("\n\n")
                text = (
                    text[: first_break + 2] + child_line + text[first_break + 2 :]
                    if first_break != -1
                    else child_line + text
                )
            else:
                if r_lang not in msg_cache_by_lang:
                    msg_cache_by_lang[r_lang] = _format_topic_announcement_message(
                        group_name=group_name,
                        topic_rows=unpublished,
                        teacher_name=teacher_name,
                        lang=r_lang,
                    )
                text = msg_cache_by_lang[r_lang]
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            sent_count += 1
        except Exception as exc:
            logger.warning(
                "Topic broadcast DM to chat_id=%s (%s) failed: %s",
                chat_id,
                group_name,
                exc,
            )

    for stu_cid in student_targets:
        await _send_dm_for_target(stu_cid)

    for p_cid, names in parent_children.items():
        parent_key = (p_cid, group_key)
        if parent_key in seen_dm_group:
            continue
        seen_dm_group.add(parent_key)
        await _send_dm_for_target(p_cid, names)

    published_dates = [
        str(r.get("lesson_date", "")).strip()
        for r in unpublished
        if str(r.get("lesson_date", "")).strip()
    ]
    await mark_topics_published(group_name, lesson_dates=published_dates)
    return len(unpublished), sent_count


# ======================================================================
# 1. DARS JADVALI (Teacher, Student & Parent Views — Admin Handler Removed)
# ======================================================================


@router.message(
    F.text.in_(
        {
            t("menu_teacher_schedule", "latn"),
            t("menu_teacher_schedule", "cyrl"),
            t("menu_student_schedule", "latn"),
            t("menu_student_schedule", "cyrl"),
        }
    )
)
async def entry_schedule_view(message: Message) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    if await _is_admin(user_id):
        return

    lang = await get_user_lang(user_id)
    sheets = get_sheets_manager()
    db_user = await get_user(user_id)
    role = db_user.get("role") if db_user else None

    if role == "teacher":
        await _send_teacher_schedule(message, user_id, lang)
        return

    teacher_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
    if teacher_groups and role not in {"student", "parent"}:
        await _send_teacher_schedule(message, user_id, lang)
        return

    await _send_student_or_parent_schedule(message, lang)


@router.message(F.text.in_(button_texts("menu_parent_schedule")))
async def parent_schedule_view(message: Message) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    await _send_parent_schedule(message, message.from_user.id, lang)


async def _send_teacher_schedule(
    message: Message, user_id: int, lang: str
) -> None:
    sheets = get_sheets_manager()
    raw_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
    teacher_groups = [
        g
        for g in raw_groups
        if str(g.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
    ]
    if not teacher_groups:
        await message.answer(_lt("no_groups", lang), parse_mode="HTML")
        return

    for group in teacher_groups:
        group_name = str(group.get("Guruh_Nomi", "")).strip()
        if not group.get("Dars_Kunlari") or not group.get("Dars_Vaqti"):
            await message.answer(
                _lt(
                    "schedule_not_configured",
                    lang,
                    group=html.escape(group_name or "—"),
                ),
                parse_mode="HTML",
            )
            continue

        day_indices = parse_weekdays(group["Dars_Kunlari"])
        days_formatted = _format_days_list(day_indices, lang)
        lesson_time = format_lesson_time_display(group.get("Dars_Vaqti", ""), lang) or "—"
        total_count = int(group.get("Oylik_Dars_Soni") or 12)
        completed = int(group.get("Otilgan_Dars_Hisoblagich") or 0)
        remaining = max(0, total_count - completed)

        dates_info = await sheets.a_get_cycle_dates_with_status(group_name, lang=lang)
        date_strs = [d["date_str"] for d in dates_info if d.get("date_str")]
        dates_formatted = format_uz_date_list(date_strs, lang) if date_strs else "—"

        await message.answer(
            _lt(
                "teacher_schedule_card",
                lang,
                group=html.escape(group_name),
                days=html.escape(days_formatted),
                time=html.escape(lesson_time),
                remaining=remaining,
                total=total_count,
                dates=html.escape(dates_formatted),
            ),
            parse_mode="HTML",
        )


async def _format_latest_topic_for_group(group_name: str, lang: str) -> str:
    if not group_name:
        return _lt("no_topic_yet", lang)
    history = await get_group_topics_history(group_name, limit=10)
    if not history:
        return _lt("no_topic_yet", lang)
    published = [r for r in history if int(r.get("is_published") or 0) == 1]
    latest = published[0] if published else history[0]
    t_title = str(latest.get("topic") or latest.get("topic_title") or "").strip()
    t_plan = str(latest.get("plan") or latest.get("lesson_details") or "").strip()
    t_date = _fmt_topic_date(str(latest.get("lesson_date") or ""), lang)
    if not t_title:
        return _lt("no_topic_yet", lang)
    if len(t_plan) > 160:
        t_plan = t_plan[:157] + "..."
    header = f"<b>{html.escape(t_title)}</b>"
    if t_date:
        header = f"{header} ({html.escape(t_date)})"
    if t_plan:
        return f"{header}\n   <i>{html.escape(t_plan)}</i>"
    return header


async def _load_parent_children(
    sheets: Any, user_id: int
) -> list[dict[str, Any]]:
    raw_children = await sheets.a_get_children_by_parent_chat_id(user_id)

    children: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()
    for ch in raw_children:
        sid = str(ch.get("Talaba_ID", "")).strip()
        grp = str(ch.get("Guruh", "")).strip().lower()
        key = (sid, grp)
        if key not in seen_keys:
            seen_keys.add(key)
            children.append(ch)

    if not children:
        db_user = await get_user(user_id)
        linked_sid = str(db_user.get("linked_student_id") or "").strip() if db_user else ""
        if linked_sid:
            linked_stu = await sheets.a_get_student_by_id(linked_sid)
            if linked_stu:
                children.append(linked_stu)
    return children


async def _build_parent_schedule_text(
    sheets: Any, user_id: int, children: list[dict[str, Any]], lang: str
) -> str:
    group_cache: dict[str, Optional[dict[str, Any]]] = {}
    teacher_cache: dict[str, str] = {}
    topic_cache: dict[str, str] = {}
    child_blocks: list[str] = []

    for child in children:
        child_fio = (
            str(child.get("F.I.O.", "")).strip()
            or str(child.get("Talaba_ID", "")).strip()
            or "—"
        )
        group_name = str(child.get("Guruh", "")).strip()
        group_key = group_name.lower()

        if group_name:
            if group_key not in group_cache:
                group_cache[group_key] = await sheets.a_get_group(group_name)
            group = group_cache[group_key]
        else:
            group = None

        if group:
            raw_days = str(group.get("Dars_Kunlari", "")).strip()
            full_weekdays = (
                format_full_weekdays(raw_days, lang)
                if raw_days
                else _lt("not_set", lang)
            )
            lesson_time = format_lesson_time_display(
                group.get("Dars_Vaqti", ""), lang
            ) or _lt("not_set", lang)
            if group_key not in teacher_cache:
                teacher_cache[group_key] = await _resolve_teacher_name(
                    user_id=None,
                    group_name=group_name,
                    group=group,
                    lang=lang,
                )
            teacher_name = teacher_cache[group_key]
        else:
            full_weekdays = _lt("not_set", lang)
            lesson_time = _lt("not_set", lang)
            teacher_name = "Устоз" if lang == "cyrl" else "Ustoz"

        if group_key not in topic_cache:
            topic_cache[group_key] = await _format_latest_topic_for_group(
                group_name, lang
            )
        latest_topic = topic_cache[group_key]

        child_blocks.append(
            _lt(
                "parent_child_block",
                lang,
                child_fio=html.escape(child_fio),
                group_name=html.escape(group_name or "—"),
                full_weekdays=html.escape(full_weekdays),
                lesson_time=html.escape(lesson_time),
                teacher_name=html.escape(teacher_name),
                latest_topic=latest_topic,
            )
        )

    combined_text = "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(child_blocks)
    if len(combined_text) > 4090:
        combined_text = combined_text[:4085] + "..."
    return combined_text


async def _build_parent_schedule_detail_text(
    sheets: Any, children: list[dict[str, Any]], lang: str
) -> str:
    """Past (🟢/🔴) and upcoming (⏳) lessons of every child's current cycle."""
    today = today_tashkent()
    blocks: list[str] = [_lt("sched_detail_header", lang)]

    for child in children:
        child_fio = (
            str(child.get("F.I.O.", "")).strip()
            or str(child.get("Talaba_ID", "")).strip()
            or "—"
        )
        group_name = str(child.get("Guruh", "")).strip()
        sid = str(child.get("Talaba_ID", "")).strip()
        lines = [
            _lt(
                "sched_detail_child",
                lang,
                child_fio=html.escape(child_fio),
                group_name=html.escape(group_name or "—"),
            )
        ]
        lessons: list[dict[str, Any]] = []
        if group_name:
            lessons = await sheets.a_get_student_current_cycle_lessons(
                group_name, sid, child_fio
            )
        if not lessons:
            lines.append(_lt("sched_no_lessons", lang))
        for lesson in lessons:
            try:
                lesson_date = date.fromisoformat(lesson["iso"])
            except ValueError:
                continue
            if lesson["mark"] == "present":
                key = "sched_lesson_present"
            elif lesson["mark"] == "absent":
                key = "sched_lesson_absent"
            elif lesson_date >= today:
                key = "sched_lesson_upcoming"
            else:
                key = "sched_lesson_unmarked"
            lines.append(
                _lt(
                    key,
                    lang,
                    sana=lesson_date.strftime("%d.%m.%Y"),
                    hafta_kuni=format_weekday_full(lesson_date, lang),
                )
            )
        blocks.append("\n".join(lines))

    text = "\n\n".join(blocks)
    if len(text) > 4090:
        kept: list[str] = []
        size = 0
        for line in text.split("\n"):
            if size + len(line) + 1 > 4080:
                break
            kept.append(line)
            size += len(line) + 1
        text = "\n".join(kept) + "\n…"
    return text


async def _send_parent_schedule(
    message: Message, user_id: int, lang: str
) -> None:
    sheets = get_sheets_manager()
    children = await _load_parent_children(sheets, user_id)

    if not children:
        await message.answer(t("unregistered_user", lang), parse_mode="HTML")
        return

    combined_text = await _build_parent_schedule_text(sheets, user_id, children, lang)
    await message.answer(
        combined_text,
        parse_mode="HTML",
        reply_markup=parent_schedule_kb(expanded=False, lang=lang),
    )


@router.callback_query(F.data.in_({"psched:detail", "psched:back"}))
async def cb_parent_schedule_toggle(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    expanded = callback.data == "psched:detail"
    sheets = get_sheets_manager()

    try:
        children = await _load_parent_children(sheets, user_id)
        if not children:
            await callback.answer(t("unregistered_user", lang), show_alert=True)
            return
        if expanded:
            text = await _build_parent_schedule_detail_text(sheets, children, lang)
        else:
            text = await _build_parent_schedule_text(sheets, user_id, children, lang)
    except Exception:
        logger.exception("Failed building parent schedule view for user_id=%s", user_id)
        await callback.answer(_lt("sched_detail_error", lang), show_alert=True)
        return

    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=parent_schedule_kb(expanded=expanded, lang=lang),
        )
    except Exception as exc:
        if "message is not modified" not in str(exc).lower():
            logger.exception("Failed editing parent schedule message")
    await callback.answer()


async def _send_student_or_parent_schedule(message: Message, lang: str) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    sheets = get_sheets_manager()
    db_user = await get_user(user_id)
    active_role = db_user.get("role") if db_user else None

    if active_role == "parent":
        await _send_parent_schedule(message, user_id, lang)
        return

    student_records = await sheets.a_get_students_by_chat_id(user_id)
    if not student_records:
        parent_records = await sheets.a_get_children_by_parent_chat_id(user_id)
        if parent_records:
            await _send_parent_schedule(message, user_id, lang)
            return
        linked = await sheets.a_get_student_by_chat_id(user_id)
        if linked:
            student_records = [linked]
        elif db_user and db_user.get("linked_student_id"):
            single = await sheets.a_get_student_by_id(str(db_user["linked_student_id"]))
            if single:
                student_records = [single]

    if not student_records:
        await message.answer(t("unregistered_user", lang), parse_mode="HTML")
        return

    student_blocks: list[str] = []
    for student in student_records:
        group_name = str(student.get("Guruh", "")).strip()
        group = await sheets.a_get_group(group_name) if group_name else None
        if not group or not group.get("Dars_Kunlari") or not group.get("Dars_Vaqti"):
            student_blocks.append(
                _lt(
                    "schedule_not_configured",
                    lang,
                    group=html.escape(group_name or "—"),
                )
            )
            continue

        day_indices = parse_weekdays(group["Dars_Kunlari"])
        days_formatted = _format_days_list(day_indices, lang)
        lesson_time = format_lesson_time_display(group.get("Dars_Vaqti", ""), lang) or "—"
        total_count = int(group.get("Oylik_Dars_Soni") or 12)
        completed = int(group.get("Otilgan_Dars_Hisoblagich") or 0)
        remaining = max(0, total_count - completed)

        dates_info = await sheets.a_get_cycle_dates_with_status(group_name, lang=lang)
        date_strs = [d["date_str"] for d in dates_info if d.get("date_str")]
        dates_formatted = format_uz_date_list(date_strs, lang) if date_strs else "—"

        base_text = t(
            "schedule_view_student",
            lang,
            group=html.escape(group_name),
            days=html.escape(days_formatted),
            time=html.escape(lesson_time),
            count=total_count,
        )
        extra = (
            f"\n{_lt('remaining_lessons_line', lang, remaining=remaining, total=total_count)}"
            f"\n{_lt('upcoming_dates_line', lang, dates=html.escape(dates_formatted))}"
        )
        student_blocks.append(f"{base_text}{extra}")

    combined_text = "\n\n━━━━━━━━━━━━━━━━━━\n\n".join(student_blocks)
    if len(combined_text) > 4090:
        combined_text = combined_text[:4085] + "..."
    await message.answer(combined_text, parse_mode="HTML")


# ======================================================================
# 2. LESSON TOPIC & PLAN + HISTORY (📝 Dars mavzusini kiritish)
# ======================================================================


async def _get_topic_dates_for_group(
    group_name: str, lang: str
) -> list[dict[str, Any]]:
    sheets = get_sheets_manager()
    dates_info = await sheets.a_get_cycle_dates_with_status(group_name, lang=lang)
    if dates_info:
        return dates_info
    group = await sheets.a_get_group(group_name)
    lesson_days = parse_weekdays(group.get("Dars_Kunlari", "") if group else "")
    if not lesson_days:
        lesson_days = [0, 2, 4]
    today = today_tashkent()
    gen_dates = generate_cycle_dates(today, lesson_days, 8)
    wd_map = WEEKDAYS_SHORT.get(lang, WEEKDAYS_SHORT["latn"])
    return [
        {
            "date_str": d.strftime("%d.%m"),
            "weekday": wd_map.get(d.weekday(), ""),
            "is_marked": False,
            "is_cancelled": False,
        }
        for d in gen_dates
    ]


@router.message(F.text.in_(TOPIC_MENU_TEXTS))
async def cmd_topic_menu_start(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    role, groups = await _get_accessible_groups(user_id)
    if role not in {"admin", "teacher"}:
        return
    if not groups:
        await message.answer(_lt("no_groups", lang), parse_mode="HTML")
        return

    await state.clear()
    await state.set_state(TopicStates.selecting_group)
    await message.answer(
        t("topic_select_group", lang),
        reply_markup=groups_inline_kb(
            groups, "topic_grp", lang, include_back=False, include_cancel=True
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("enter_topic:"))
async def cb_reminder_enter_topic(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Entry point from 1-day-ahead polite Teacher Topic Reminder."""
    if not callback.from_user or not callback.message or not callback.data:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    # Group names may contain ":" -> the date is split off from the right.
    parts = callback.data.split(":", 1)[1].rsplit(":", 1) if ":" in callback.data else []
    if len(parts) < 2:
        await callback.answer()
        return
    group_name = parts[0].strip()
    date_str = parts[1].strip()

    if not await _can_manage_group(user_id, group_name):
        await callback.answer(_lt("topic_no_permission", lang), show_alert=True)
        return

    await state.clear()
    await state.update_data(topic_group_name=group_name, topic_date_str=date_str)
    await state.set_state(TopicStates.entering_topic)

    existing = await get_lesson_topic(group_name, date_str)
    hint = (
        _lt(
            "topic_existing_hint",
            lang,
            topic=html.escape(existing["topic"]),
            plan=html.escape(existing["plan"]),
        )
        if existing and existing.get("topic")
        else ""
    )
    prompt = t(
        "topic_enter_title",
        lang,
        group=html.escape(group_name),
        date=html.escape(_fmt_topic_date(date_str, lang)),
    )
    await callback.message.answer(
        f"{prompt}{hint}",
        reply_markup=step_nav_inline_kb(
            lang,
            back_cb=f"topic_back:action:{group_name}",
            cancel_cb="topic_cancel",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(
    StateFilter(TopicStates),
    F.text.in_({t("btn_cancel", "latn"), t("btn_cancel", "cyrl"), "/cancel"}),
)
async def msg_topic_cancel(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    await state.clear()
    await message.answer(t("topic_cancelled", lang))


@router.callback_query(StateFilter(TopicStates), F.data == "topic_cancel")
async def cb_topic_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user and callback.message:
        lang = await get_user_lang(callback.from_user.id)
        await state.clear()
        await callback.message.edit_text(t("topic_cancelled", lang))
    await callback.answer()


@router.callback_query(
    TopicStates.selecting_group, F.data.startswith("topic_grp:")
)
async def cb_topic_group_selected(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    group_name = (callback.data or "").split(":", 1)[1]

    if group_name == "__cancel__":
        await state.clear()
        await callback.message.edit_text(t("topic_cancelled", lang))
        await callback.answer()
        return

    if not await _can_manage_group(user_id, group_name):
        await callback.answer(_lt("topic_no_permission", lang), show_alert=True)
        return

    await state.update_data(topic_group_name=group_name)
    await state.set_state(TopicStates.choosing_action)
    await callback.message.edit_text(
        _lt("topic_choose_action", lang, group=html.escape(group_name)),
        reply_markup=topic_group_action_kb(
            group_name, lang, back_cb="topic_back:group", cancel_cb="topic_cancel"
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(TopicStates), F.data.startswith("topic_back:")
)
async def cb_topic_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    parts = (callback.data or "").split(":", 2)
    target = parts[1] if len(parts) > 1 else "group"
    data = await state.get_data()
    group_name = (
        parts[2] if len(parts) > 2 else data.get("topic_group_name", "")
    )

    if target == "group":
        _, groups = await _get_accessible_groups(user_id)
        await state.set_state(TopicStates.selecting_group)
        await callback.message.edit_text(
            t("topic_select_group", lang),
            reply_markup=groups_inline_kb(
                groups, "topic_grp", lang, include_back=False, include_cancel=True
            ),
            parse_mode="HTML",
        )
    elif target == "action" and group_name:
        await state.update_data(topic_group_name=group_name)
        await state.set_state(TopicStates.choosing_action)
        await callback.message.edit_text(
            _lt("topic_choose_action", lang, group=html.escape(group_name)),
            reply_markup=topic_group_action_kb(
                group_name, lang, back_cb="topic_back:group", cancel_cb="topic_cancel"
            ),
            parse_mode="HTML",
        )
    elif target == "date" and group_name:
        dates_info = await _get_topic_dates_for_group(group_name, lang)
        await state.set_state(TopicStates.selecting_date)
        await callback.message.edit_text(
            t("topic_select_date", lang, group=html.escape(group_name)),
            reply_markup=topic_dates_kb(
                dates_info,
                lang,
                back_cb=f"topic_back:action:{group_name}",
                cancel_cb="topic_cancel",
            ),
            parse_mode="HTML",
        )
    elif target == "title":
        date_str = data.get("topic_date_str", "")
        await state.set_state(TopicStates.entering_topic)
        await callback.message.edit_text(
            t(
                "topic_enter_title",
                lang,
                group=html.escape(group_name),
                date=html.escape(_fmt_topic_date(date_str, lang)),
            ),
            reply_markup=step_nav_inline_kb(
                lang, back_cb="topic_back:date", cancel_cb="topic_cancel"
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(
    TopicStates.choosing_action, F.data.startswith("topic_act:")
)
async def cb_topic_action_selected(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    _, action, group_name = (callback.data or "").split(":", 2)

    if not await _can_manage_group(user_id, group_name):
        await callback.answer(_lt("topic_no_permission", lang), show_alert=True)
        return

    await state.update_data(topic_group_name=group_name)

    if action == "new":
        dates_info = await _get_topic_dates_for_group(group_name, lang)
        await state.set_state(TopicStates.selecting_date)
        await callback.message.edit_text(
            t("topic_select_date", lang, group=html.escape(group_name)),
            reply_markup=topic_dates_kb(
                dates_info,
                lang,
                back_cb=f"topic_back:action:{group_name}",
                cancel_cb="topic_cancel",
            ),
            parse_mode="HTML",
        )
    elif action == "history":
        history = await get_group_topics_history(group_name, limit=20)
        await state.set_state(TopicStates.viewing_history)
        nav_kb = step_nav_inline_kb(
            lang,
            back_cb=f"topic_back:action:{group_name}",
            cancel_cb="topic_cancel",
        )
        if not history:
            await callback.message.edit_text(
                t("topic_history_empty", lang),
                reply_markup=nav_kb,
                parse_mode="HTML",
            )
            await callback.answer()
            return

        header = t("topic_history_header", lang, group=html.escape(group_name))
        lines: list[str] = []
        for idx, item in enumerate(history, start=1):
            d_fmt = _fmt_topic_date(item.get("lesson_date", ""), lang)
            top = html.escape(item.get("topic") or item.get("topic_title") or "—")
            pln = html.escape(item.get("plan") or item.get("lesson_details") or "—")
            pub_mark = "✅" if int(item.get("is_published") or 0) == 1 else "⏳"
            lines.append(
                f"{idx}. 📅 <b>{html.escape(d_fmt)}</b> {pub_mark} — <b>{top}</b>\n"
                f"   <i>{pln}</i>"
            )
        text = f"{header}\n" + "\n\n".join(lines)
        if len(text) > 4090:
            text = text[:4085] + "..."
        await callback.message.edit_text(
            text, reply_markup=nav_kb, parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(
    TopicStates.selecting_date, F.data.startswith("topic_date:")
)
async def cb_topic_date_selected(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    date_str = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()
    group_name = data.get("topic_group_name", "")

    await state.update_data(topic_date_str=date_str)
    await state.set_state(TopicStates.entering_topic)

    existing = await get_lesson_topic(group_name, date_str)
    hint = (
        _lt(
            "topic_existing_hint",
            lang,
            topic=html.escape(existing["topic"]),
            plan=html.escape(existing["plan"]),
        )
        if existing and existing.get("topic")
        else ""
    )
    prompt = t(
        "topic_enter_title",
        lang,
        group=html.escape(group_name),
        date=html.escape(_fmt_topic_date(date_str, lang)),
    )
    await callback.message.edit_text(
        f"{prompt}{hint}",
        reply_markup=step_nav_inline_kb(
            lang, back_cb="topic_back:date", cancel_cb="topic_cancel"
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(TopicStates.entering_topic)
async def msg_topic_title_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    topic_title = " ".join((message.text or "").strip().split())
    if len(topic_title) < 2 or topic_title.startswith("/"):
        await message.answer(
            t("topic_invalid_title", lang),
            reply_markup=step_nav_inline_kb(
                lang, back_cb="topic_back:date", cancel_cb="topic_cancel"
            ),
        )
        return

    await state.update_data(topic_title=topic_title[:250])
    await state.set_state(TopicStates.entering_plan)
    await message.answer(
        t("topic_enter_details", lang),
        reply_markup=step_nav_inline_kb(
            lang, back_cb="topic_back:title", cancel_cb="topic_cancel"
        ),
        parse_mode="HTML",
    )


@router.message(TopicStates.entering_plan)
async def msg_topic_plan_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    plan_text = (message.text or "").strip()
    if len(plan_text) < 2 or plan_text.startswith("/"):
        await message.answer(
            t("topic_invalid_details", lang),
            reply_markup=step_nav_inline_kb(
                lang, back_cb="topic_back:title", cancel_cb="topic_cancel"
            ),
        )
        return

    data = await state.get_data()
    group_name = data.get("topic_group_name", "")
    date_str = data.get("topic_date_str", "")
    topic_title = data.get("topic_title", "")

    teacher_name = await _resolve_teacher_name(
        user_id=user_id,
        group_name=group_name,
        fallback_name="",
        lang=lang,
    )

    saved_row = await save_lesson_topic(
        group_name=group_name,
        lesson_date=date_str,
        topic=topic_title,
        plan=plan_text[:2000],
        teacher_id=user_id,
        teacher_name=teacher_name,
        is_published=0,
    )
    await state.update_data(topic_plan=plan_text[:2000])
    await state.set_state(TopicStates.confirming)

    preview_msg = _format_topic_announcement_message(
        group_name=group_name,
        topic_rows=[saved_row],
        teacher_name=teacher_name,
        lang=lang,
    )
    auto_note = _lt("topic_auto_publish_note", lang)

    await message.answer(
        f"{preview_msg}\n\n{auto_note}",
        reply_markup=_build_topic_publish_kb(
            group_name=group_name,
            date_str=date_str,
            lang=lang,
            include_save_only=True,
        ),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(TopicStates), F.data.startswith("topic_add_more:")
)
async def cb_topic_add_more_dates(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    group_name = (callback.data or "").split(":", 1)[1].strip()

    if not await _can_manage_group(user_id, group_name):
        await callback.answer(_lt("topic_no_permission", lang), show_alert=True)
        return

    await state.update_data(topic_group_name=group_name)
    dates_info = await _get_topic_dates_for_group(group_name, lang)
    await state.set_state(TopicStates.selecting_date)
    await callback.message.edit_text(
        t("topic_select_date", lang, group=html.escape(group_name)),
        reply_markup=topic_dates_kb(
            dates_info,
            lang,
            back_cb=f"topic_back:action:{group_name}",
            cancel_cb="topic_cancel",
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(TopicStates.confirming), F.data.startswith("topic_edit:")
)
async def cb_topic_edit_again(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    data = await state.get_data()
    group_name = data.get("topic_group_name", "")
    date_str = (callback.data or "").split(":", 1)[1]
    await state.update_data(topic_date_str=date_str)
    await state.set_state(TopicStates.entering_topic)
    await callback.message.edit_text(
        t(
            "topic_enter_title",
            lang,
            group=html.escape(group_name),
            date=html.escape(_fmt_topic_date(date_str, lang)),
        ),
        reply_markup=step_nav_inline_kb(
            lang, back_cb="topic_back:date", cancel_cb="topic_cancel"
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(TopicStates.confirming), F.data.startswith("topic_save:")
)
async def cb_topic_save_only(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    data = await state.get_data()
    group_name = data.get("topic_group_name", "")
    date_str = (callback.data or "").split(":", 1)[1]

    history = await get_group_topics_history(group_name, limit=50)
    pending_count = sum(
        1 for row in history if int(row.get("is_published") or 0) == 0
    )

    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_topic_broadcast", lang),
                    callback_data=f"publish_topics:{group_name}",
                )
            ]
        ]
    )
    await callback.message.edit_text(
        _lt(
            "topic_saved_with_count",
            lang,
            group=html.escape(group_name),
            date=html.escape(_fmt_topic_date(date_str, lang)),
            pending_count=pending_count,
        ),
        reply_markup=kb if pending_count > 0 else None,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("publish_topics:"))
async def cb_publish_topics(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    group_name = (callback.data or "").split(":", 1)[1].strip()

    if not await _can_manage_group(user_id, group_name):
        await callback.answer(_lt("topic_no_permission", lang), show_alert=True)
        return

    topic_count, sent_count = await publish_group_topics(
        bot=callback.bot,
        group_name=group_name,
        actor_user_id=user_id,
    )
    if await state.get_state() in {
        s.state for s in TopicStates.__all_states__
    }:
        await state.clear()

    if topic_count == 0:
        await callback.message.edit_text(
            _lt("topic_nothing_to_publish", lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        _lt(
            "topic_broadcast_summary",
            lang,
            group=html.escape(group_name),
            topic_count=topic_count,
            sent=sent_count,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(TopicStates.confirming), F.data.startswith("topic_bc:")
)
async def cb_topic_broadcast_legacy(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()
    group_name = data.get("topic_group_name", "")
    date_str = (callback.data or "").split(":", 1)[1].strip()

    if not group_name or not await _can_manage_group(user_id, group_name):
        await callback.answer(_lt("topic_no_permission", lang), show_alert=True)
        return

    topic_count, sent_count = await publish_group_topics(
        bot=callback.bot,
        group_name=group_name,
        lesson_dates=[date_str] if date_str else None,
        actor_user_id=user_id,
    )
    await state.clear()

    if topic_count == 0:
        await callback.message.edit_text(
            _lt("topic_nothing_to_publish", lang),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            _lt(
                "topic_broadcast_summary",
                lang,
                group=html.escape(group_name),
                topic_count=topic_count,
                sent=sent_count,
            ),
            parse_mode="HTML",
        )
    await callback.answer()