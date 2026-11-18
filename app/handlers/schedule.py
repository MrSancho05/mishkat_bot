import asyncio
import html
import re
from datetime import date, datetime
from typing import Any, Optional

import aiosqlite
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.config import ADMIN_IDS, DB_PATH, TZ
from app.database import (
    get_group_topics_history,
    get_lesson_topic,
    get_user,
    get_user_lang,
    save_lesson_topic,
)
from app.keyboards import (
    confirm_cancel_kb,
    get_main_menu_kb,
    groups_inline_kb,
    lesson_count_kb,
    step_nav_inline_kb,
    topic_after_save_kb,
    topic_dates_kb,
    topic_group_action_kb,
    weekdays_toggle_kb,
)
from app.locales import (
    WEEKDAYS_SHORT,
    format_uz_date,
    format_uz_date_list,
    t,
)
from app.sheets import (
    format_cycle_title,
    generate_cycle_dates,
    get_sheets_manager,
    parse_weekdays,
)
from app.states import ScheduleSetupStates, TopicStates

router = Router(name="schedule")

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

TOPIC_MENU_TEXTS = {
    t("menu_teacher_topic", "latn"),
    t("menu_teacher_topic", "cyrl"),
    t("menu_lesson_topic", "latn"),
    t("menu_lesson_topic", "cyrl"),
}

_LOCAL_SCHED_TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "no_groups": "ℹ️ Sizga biriktirilgan guruhlar topilmadi.",
        "select_at_least_one_day": "⚠️ Kamida bitta dars kunini tanlang!",
        "action_cancelled": "❌ Amal bekor qilindi.",
        "schedule_not_configured": "ℹ️ <b>{group}</b> guruhi uchun dars jadvali hali sozlanmagan.",
        "remaining_lessons_line": "📊 Qolgan darslar: <b>{remaining} / {total} ta</b>",
        "upcoming_dates_line": "🗓 Joriy oy sanalari: <code>{dates}</code>",
        "topic_choose_action": "📝 <b>{group}</b> — kerakli bo‘limni tanlang:",
        "topic_no_permission": "❌ Sizda ushbu guruh uchun mavzu kiritish huquqi yo‘q.",
        "topic_existing_hint": "\n\nℹ️ <i>Avvalgi mavzu:</i> <b>{topic}</b>\n<i>Avvalgi reja:</i> {plan}",
        "topic_dm_notify": (
            "📢 <b>Dars mavzusi va rejasi</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📅 Sana: <b>{date}</b>\n"
            "📖 Mavzu: <b>{topic_title}</b>\n\n"
            "📝 <b>Darsda o‘tiladigan mavzular / vazifa:</b>\n{lesson_details}\n\n"
            "Hurmat bilan, Mishkat o'quv muassasasi"
        ),
        "topic_broadcast_summary": (
            "✅ Dars mavzusi va rejasi saqlandi hamda guruh va ishtirokchilarga "
            "(<b>{sent} ta</b> xabar) yuborildi!"
        ),
    },
    "cyrl": {
        "no_groups": "ℹ️ Сизга бириктирилган гуруҳлар топилмади.",
        "select_at_least_one_day": "⚠️ Камида битта дарс кунини танланг!",
        "action_cancelled": "❌ Амал бекор қилинди.",
        "schedule_not_configured": "ℹ️ <b>{group}</b> гуруҳи учун дарс жадвали ҳали созланмаган.",
        "remaining_lessons_line": "📊 Қолган дарслар: <b>{remaining} / {total} та</b>",
        "upcoming_dates_line": "🗓 Жорий ой саналари: <code>{dates}</code>",
        "topic_choose_action": "📝 <b>{group}</b> — керакли бўлимни танланг:",
        "topic_no_permission": "❌ Сизда ушбу гуруҳ учун мавзу киритиш ҳуқуқи йўқ.",
        "topic_existing_hint": "\n\nℹ️ <i>Аввалги мавзу:</i> <b>{topic}</b>\n<i>Аввалги режа:</i> {plan}",
        "topic_dm_notify": (
            "📢 <b>Дарс мавзуси ва режаси</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📅 Сана: <b>{date}</b>\n"
            "📖 Мавзу: <b>{topic_title}</b>\n\n"
            "📝 <b>Дарсда ўтиладиган мавзулар / вазифа:</b>\n{lesson_details}\n\n"
            "Ҳурмат билан, Мишкат ўқув муассасаси"
        ),
        "topic_broadcast_summary": (
            "✅ Дарс мавзуси ва режаси сақланди ҳамда гуруҳ ва иштирокчиларга "
            "(<b>{sent} та</b> хабар) юборилди!"
        ),
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


# ======================================================================
# 1. DARS JADVALI (Admin Setup & Student/Parent View)
# ======================================================================


@router.message(
    F.text.in_(
        {
            t("menu_admin_schedule", "latn"),
            t("menu_admin_schedule", "cyrl"),
            t("menu_student_schedule", "latn"),
            t("menu_student_schedule", "cyrl"),
        }
    )
)
async def entry_schedule_or_student_view(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)

    if await _is_admin(user_id):
        await state.clear()
        groups = await asyncio.to_thread(get_sheets_manager().get_all_groups)
        if not groups:
            await message.answer(_lt("no_groups", lang), parse_mode="HTML")
            return
        await state.set_state(ScheduleSetupStates.selecting_group)
        await message.answer(
            t("schedule_select_group", lang),
            reply_markup=groups_inline_kb(groups, "sched_grp", lang),
            parse_mode="HTML",
        )
        return

    await _send_student_or_parent_schedule(message, lang)


@router.message(
    F.text.in_(
        {
            t("menu_parent_schedule", "latn"),
            t("menu_parent_schedule", "cyrl"),
            "📅 Farzandimning dars jadvali",
            "📅 Фарзандимнинг дарс жадвали",
        }
    )
)
async def parent_schedule_view(message: Message) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    await _send_student_or_parent_schedule(message, lang)


async def _send_student_or_parent_schedule(message: Message, lang: str) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    sheets = get_sheets_manager()

    student_records = await sheets.a_get_students_by_chat_id(user_id)
    parent_records = await sheets.a_get_children_by_parent_chat_id(user_id)

    entries: list[tuple[dict[str, Any], str]] = []
    if student_records:
        for s in student_records:
            entries.append((s, "student"))
    if parent_records:
        seen_sids = {s.get("Talaba_ID") for s, _ in entries}
        for c in parent_records:
            if c.get("Talaba_ID") not in seen_sids or not student_records:
                entries.append((c, "parent"))

    if not entries:
        linked = await sheets.a_get_student_by_chat_id(user_id)
        if linked:
            entries.append(linked)

    if not entries:
        await message.answer(t("unregistered_user", lang), parse_mode="HTML")
        return

    for student, link_role in entries:
        student_name = str(student.get("F.I.O.", "")).strip() or student.get("Talaba_ID", "")
        group_name = str(student.get("Guruh", "")).strip()
        group = await sheets.a_get_group(group_name) if group_name else None
        if not group or not group.get("Dars_Kunlari") or not group.get("Dars_Vaqti"):
            await message.answer(
                _lt("schedule_not_configured", lang, group=html.escape(group_name or "—")),
                parse_mode="HTML",
            )
            continue

        day_indices = parse_weekdays(group["Dars_Kunlari"])
        days_formatted = _format_days_list(day_indices, lang)
        lesson_time = str(group.get("Dars_Vaqti", "")).strip() or "—"
        total_count = int(group.get("Oylik_Dars_Soni") or 12)
        completed = int(group.get("Otilgan_Dars_Hisoblagich") or 0)
        remaining = max(0, total_count - completed)

        dates_info = await sheets.a_get_cycle_dates_with_status(group_name, lang=lang)
        date_strs = [d["date_str"] for d in dates_info if d.get("date_str")]
        dates_formatted = format_uz_date_list(date_strs, lang) if date_strs else "—"

        if link_role == "parent":
            base_text = t(
                "schedule_view_parent",
                lang,
                student_name=html.escape(student_name),
                group=html.escape(group_name),
                days=html.escape(days_formatted),
                time=html.escape(lesson_time),
                count=total_count,
            )
        else:
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
        await message.answer(f"{base_text}{extra}", parse_mode="HTML")


@router.callback_query(
    StateFilter(ScheduleSetupStates.selecting_group), F.data.startswith("sched_grp:")
)
async def sched_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return
    group_name = (callback.data or "").split(":", 1)[1]
    if group_name == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_lt("action_cancelled", lang))
        await callback.answer()
        return

    await state.update_data(group_name=group_name, selected_days=[])
    await state.set_state(ScheduleSetupStates.selecting_lesson_count)
    await callback.message.edit_text(
        t("schedule_select_count", lang),
        reply_markup=lesson_count_kb(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(ScheduleSetupStates), F.data == "sched_cancel"
)
async def sched_cancel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user and callback.message:
        lang = await get_user_lang(callback.from_user.id)
        await state.clear()
        await callback.message.edit_text(_lt("action_cancelled", lang))
    await callback.answer()


@router.callback_query(
    StateFilter(ScheduleSetupStates.selecting_lesson_count),
    F.data.startswith("sched_count:"),
)
async def sched_count_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    count = int((callback.data or "").split(":", 1)[1])
    await state.update_data(lesson_count=count, selected_days=[])
    await state.set_state(ScheduleSetupStates.selecting_days)
    await callback.message.edit_text(
        t("schedule_select_days", lang),
        reply_markup=weekdays_toggle_kb([], lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(ScheduleSetupStates.selecting_days), F.data.startswith("sched_day:")
)
async def sched_day_toggled(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    day_idx = int((callback.data or "").split(":", 1)[1])
    data = await state.get_data()
    selected_days: list[int] = list(data.get("selected_days", []))

    if day_idx in selected_days:
        selected_days.remove(day_idx)
    else:
        selected_days.append(day_idx)
        selected_days.sort()

    await state.update_data(selected_days=selected_days)
    await callback.message.edit_reply_markup(
        reply_markup=weekdays_toggle_kb(selected_days, lang)
    )
    await callback.answer()


@router.callback_query(
    StateFilter(ScheduleSetupStates.selecting_days), F.data == "sched_days_done"
)
async def sched_days_done(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    lang = await get_user_lang(callback.from_user.id)
    data = await state.get_data()
    selected_days: list[int] = data.get("selected_days", [])
    if not selected_days:
        await callback.answer(_lt("select_at_least_one_day", lang), show_alert=True)
        return

    await state.set_state(ScheduleSetupStates.entering_time)
    await callback.message.edit_text(
        t("schedule_enter_time", lang), parse_mode="HTML"
    )
    await callback.answer()


@router.message(StateFilter(ScheduleSetupStates.entering_time))
async def sched_time_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    raw_time = (message.text or "").strip()

    if raw_time in {t("btn_cancel", "latn"), t("btn_cancel", "cyrl")}:
        await state.clear()
        await message.answer(
            _lt("action_cancelled", lang),
            reply_markup=get_main_menu_kb("admin", lang),
        )
        return

    if not TIME_RE.match(raw_time):
        await message.answer(t("schedule_invalid_time", lang), parse_mode="HTML")
        return

    data = await state.get_data()
    group_name: str = data["group_name"]
    count: int = int(data["lesson_count"])
    selected_days: list[int] = sorted(data["selected_days"])

    today = datetime.now(TZ).date()
    preview_dates = generate_cycle_dates(today, selected_days, count)
    cycle_title = format_cycle_title(preview_dates, 1)

    await state.update_data(lesson_time=raw_time)
    await state.set_state(ScheduleSetupStates.confirming)

    await message.answer(
        t(
            "schedule_confirm_summary",
            lang,
            group=group_name,
            count=count,
            days=_format_days_list(selected_days, lang),
            time=raw_time,
            cycle_title=cycle_title,
            start_date=format_uz_date(preview_dates[0].strftime("%d.%m"), lang),
            end_date=format_uz_date(preview_dates[-1].strftime("%d.%m"), lang),
        ),
        reply_markup=confirm_cancel_kb("sched_confirm_save", "sched_cancel", lang),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(ScheduleSetupStates.confirming), F.data == "sched_confirm_save"
)
async def sched_confirm_save(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(t("link_group_no_permission", lang), show_alert=True)
        return

    data = await state.get_data()
    group_name: str = data["group_name"]
    count: int = int(data["lesson_count"])
    selected_days: list[int] = sorted(data["selected_days"])
    lesson_time: str = data["lesson_time"]

    days_canonical = _format_days_list(selected_days, "latn")
    sheets = get_sheets_manager()
    today = datetime.now(TZ).date()

    await asyncio.to_thread(
        sheets.update_group,
        group_name,
        {
            "Oylik_Dars_Soni": str(count),
            "Dars_Kunlari": days_canonical,
            "Dars_Vaqti": lesson_time,
        },
    )
    await asyncio.to_thread(sheets.create_cycle_table, group_name, today)

    await state.clear()
    await callback.message.edit_text(
        t("schedule_saved", lang, group=group_name), parse_mode="HTML"
    )
    await callback.answer()

    students = await asyncio.to_thread(
        sheets.get_all_students, group_name=group_name, active_only=True
    )
    for stu in students:
        s_chat = str(stu.get("Talaba_Chat_ID", "")).strip()
        s_cid = int(s_chat) if s_chat.lstrip("-").isdigit() else None
        if s_cid is not None:
            try:
                s_lang = await get_user_lang(s_cid)
                await callback.bot.send_message(
                    s_cid,
                    t(
                        "schedule_notify_user",
                        s_lang,
                        group=group_name,
                        days=_format_days_list(selected_days, s_lang),
                        time=lesson_time,
                        count=count,
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        sent_parents: set[int] = set()
        for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
            p_chat = str(stu.get(col, "")).strip()
            if not p_chat.lstrip("-").isdigit():
                continue
            p_cid = int(p_chat)
            if p_cid == s_cid or p_cid in sent_parents:
                continue
            sent_parents.add(p_cid)
            try:
                p_lang = await get_user_lang(p_cid)
                await callback.bot.send_message(
                    p_cid,
                    t(
                        "schedule_notify_user",
                        p_lang,
                        group=group_name,
                        days=_format_days_list(selected_days, p_lang),
                        time=lesson_time,
                        count=count,
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass


# ======================================================================
# 2. STANDALONE LESSON TOPIC & PLAN + HISTORY (📝 Dars mavzusini kiritish)
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
    today = datetime.now(TZ).date()
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
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer()
        return
    group_name = parts[1].strip()
    date_str = parts[2].strip()

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
            lines.append(
                f"{idx}. 📅 <b>{html.escape(d_fmt)}</b> — <b>{top}</b>\n   <i>{pln}</i>"
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

    await save_lesson_topic(
        group_name=group_name,
        lesson_date=date_str,
        topic=topic_title,
        plan=plan_text[:2000],
        teacher_id=user_id,
    )
    await state.update_data(topic_plan=plan_text[:2000])
    await state.set_state(TopicStates.confirming)

    await message.answer(
        t(
            "topic_confirm_preview",
            lang,
            group=html.escape(group_name),
            date=html.escape(_fmt_topic_date(date_str, lang)),
            topic_title=html.escape(topic_title),
            lesson_details=html.escape(plan_text[:2000]),
        ),
        reply_markup=topic_after_save_kb(
            date_str,
            lang,
            include_save_only=True,
            back_cb="topic_back:date",
            cancel_cb="topic_cancel",
        ),
        parse_mode="HTML",
    )


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
    await state.clear()
    await callback.message.edit_text(
        t(
            "topic_saved",
            lang,
            group=html.escape(group_name),
            date=html.escape(_fmt_topic_date(date_str, lang)),
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(TopicStates.confirming), F.data.startswith("topic_bc:")
)
async def cb_topic_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()
    group_name = data.get("topic_group_name", "")
    date_str = (callback.data or "").split(":", 1)[1]
    topic_title = data.get("topic_title", "")
    plan_text = data.get("topic_plan", "")

    if not topic_title:
        rec = await get_lesson_topic(group_name, date_str)
        if rec:
            topic_title = rec.get("topic", "")
            plan_text = rec.get("plan", "")

    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    students = await asyncio.to_thread(
        sheets.get_all_students, group_name=group_name, active_only=True
    )

    sent_count = 0
    seen_cids: set[int] = set()

    # 1. Group Telegram Chat (Latin script)
    if group:
        grp_tg_raw = str(group.get("Guruh_TG_Chat_ID", "")).strip()
        if grp_tg_raw.lstrip("-").isdigit():
            grp_cid = int(grp_tg_raw)
            seen_cids.add(grp_cid)
            try:
                await callback.bot.send_message(
                    chat_id=grp_cid,
                    text=t(
                        "topic_group_broadcast_msg",
                        "latn",
                        group=html.escape(group_name),
                        date=html.escape(_fmt_topic_date(date_str, "latn")),
                        topic_title=html.escape(topic_title),
                        lesson_details=html.escape(plan_text),
                    ),
                    parse_mode="HTML",
                )
                sent_count += 1
            except Exception:
                pass

    # 2. Active Students + Father + Mother DMs
    dm_targets: list[int] = []
    for stu in students:
        for col in (
            "Talaba_Chat_ID",
            "Otasi_Chat_ID",
            "Onasi_Chat_ID",
            "OtaOna_Chat_ID",
        ):
            raw = str(stu.get(col, "")).strip()
            if raw.lstrip("-").isdigit():
                cid = int(raw)
                if cid not in seen_cids:
                    seen_cids.add(cid)
                    dm_targets.append(cid)

    for cid in dm_targets:
        try:
            r_lang = await get_user_lang(cid)
            await callback.bot.send_message(
                chat_id=cid,
                text=_lt(
                    "topic_dm_notify",
                    r_lang,
                    group=html.escape(group_name),
                    date=html.escape(_fmt_topic_date(date_str, r_lang)),
                    topic_title=html.escape(topic_title),
                    lesson_details=html.escape(plan_text),
                ),
                parse_mode="HTML",
            )
            sent_count += 1
        except Exception:
            pass

    await state.clear()
    await callback.message.edit_text(
        _lt("topic_broadcast_summary", lang, sent=sent_count),
        parse_mode="HTML",
    )
    await callback.answer()