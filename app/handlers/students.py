import asyncio
import html
import re
from typing import Any, Optional

import aiosqlite
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import database
from app.config import ADMIN_IDS, DB_PATH, STUDENT_SHEET_NAME
from app.database import get_user, get_user_lang
from app.keyboards import (
    confirm_cancel_kb,
    confirm_delete_student_kb,
    get_main_menu_kb,
    groups_inline_kb,
    skip_or_cancel_inline_kb,
    step_nav_inline_kb,
    student_actions_kb,
    student_add_method_kb,
    student_edit_fields_kb,
    student_root_menu_kb,
    student_transfer_keep_kb,
    students_list_kb,
)
from app.locales import t
from app.sheets import (
    COLOR_HEADER_GRAY,
    COLOR_WHITE,
    STUDENT_HEADERS,
    _borders_request,
    _cell_bg_request,
    _col_letter,
    get_sheets_manager,
)
from app.states import StudentAddStates, StudentManageStates

router = Router(name="students")

EXTENDED_STUDENT_COLUMNS = [
    "Otasi_FIO",
    "Otasi_Tel",
    "Otasi_Chat_ID",
    "Onasi_FIO",
    "Onasi_Tel",
    "Onasi_Chat_ID",
]

_LOCAL_STU_TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "root_title": "👥 <b>Talabalar bo‘limi</b>\nKerakli amalni tanlang:",
        "no_groups": "ℹ️ Sizga biriktirilgan guruhlar topilmadi.",
        "no_permission": "❌ Sizda ushbu amalni bajarish huquqi yo‘q.",
        "select_group_add": "➕ Yangi talaba qo‘shiladigan guruhni tanlang:",
        "select_group_manage": "👤 Talabalarni ko‘rish uchun guruhni tanlang:",
        "enter_full_name": "👤 Talabaning <b>F.I.O.</b> ni kiriting:",
        "enter_stu_phone": "📞 Talabaning telefon raqamini kiriting (masalan: <code>+998901234567</code>):",
        "enter_stu_tg": "✈️ Talabaning Telegram username ni kiriting (masalan: <code>@username</code>):",
        "enter_father_phone": "🧔‍♂️ Otasining telefon raqamini kiriting (masalan: <code>+998901234567</code>):",
        "enter_mother_phone": "🧕 Onasining telefon raqamini kiriting (masalan: <code>+998901234567</code>):",
        "invite_links_info": (
            "🔗 <b>Taklif havolalari ({group})</b>\n\n"
            "🎓 <b>Talaba o‘zi qo‘shilishi uchun havola:</b>\n"
            "<code>https://t.me/{bot_username}?start=join_{group_slug}</code>\n\n"
            "👨‍👩‍👧 <b>Ota-ona qo‘shilishi uchun:</b>\n"
            "Talaba so‘rovi tasdiqlangach avtomatik shaxsiy <code>?start=par_ID</code> havolasi yaratiladi. "
            "Mavjud talaba uchun esa «👤 Talabalarni boshqarish → 🔗 Taklif havolalari» orqali olishingiz mumkin."
        ),
        "teacher_invite_only_info": (
            "🔗 <b>{group} — Talaba taklif havolasi</b>\n\n"
            "Talaba ushbu havola orqali botga kirib, o‘z F.I.O. va telefon raqamini yuborgach, "
            "sizga tasdiqlash uchun so‘rov yuboriladi:\n\n"
            "<code>https://t.me/{bot_username}?start=join_{group_slug}</code>"
        ),
        "add_confirm": (
            "➕ <b>Yangi talaba ma'lumotlarini tasdiqlang:</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📞 Talaba tel: <b>{stu_phone}</b>\n"
            "✈️ Talaba TG: <b>{stu_tg}</b>\n"
            "🧔‍♂️ Otasi tel: <b>{father_phone}</b>\n"
            "🧕 Onasi tel: <b>{mother_phone}</b>"
        ),
        "add_success": (
            "✅ <b>Talaba muvaffaqiyatli qo‘shildi!</b>\n\n"
            "🆔 Talaba ID: <code>{student_id}</code>\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n\n"
            "🔗 <b>Taklif havolalari:</b>\n"
            "🎓 Talaba uchun:\n<code>https://t.me/{bot_username}?start=stu_{student_id}</code>\n\n"
            "👨‍👩‍👧 Ota-ona uchun:\n<code>https://t.me/{bot_username}?start=par_{student_id}</code>"
        ),
        "links_card": (
            "🔗 <b>{full_name}</b> (<code>{student_id}</code>) uchun taklif havolalari:\n\n"
            "🎓 Talaba uchun:\n<code>https://t.me/{bot_username}?start=stu_{student_id}</code>\n\n"
            "👨‍👩‍👧 Ota-ona uchun:\n<code>https://t.me/{bot_username}?start=par_{student_id}</code>"
        ),
        "no_students_in_group": "ℹ️ <b>{group}</b> guruhida talabalar topilmadi.",
        "select_student": "👤 Talabani tanlang (<b>{group}</b>):",
        "student_card": (
            "👤 <b>Talaba kartasi</b>\n\n"
            "🆔 ID: <code>{student_id}</code>\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📊 Status: <b>{status}</b>\n"
            "📞 Talaba tel: <b>{stu_phone}</b>\n"
            "✈️ Talaba TG: <b>{stu_tg}</b>\n"
            "🧔‍♂️ Otasi tel: <b>{father_phone}</b>\n"
            "🧕 Onasi tel: <b>{mother_phone}</b>\n"
            "⚠️ Qarzdorlik: <b>{debts}</b>"
        ),
        "choose_edit_field": "✏️ Qaysi ma'lumotni o‘zgartirmoqchisiz?",
        "enter_new_value": "📝 <b>{field}</b> uchun yangi qiymatni kiriting:",
        "select_new_group": "📚 Yangi guruhni tanlang:",
        "updated_ok": "✅ Ma'lumot yangilandi!",
        "confirm_delete": "⚠️ Haqiqatan ham <b>{full_name}</b> (<code>{student_id}</code>) ni bazadan va guruh jadvalidan o‘chirmoqchimisiz?",
        "deleted_ok": "🗑 Talaba (<code>{student_id}</code>) bazadan va guruh jadvalidan o‘chirildi.",
        "action_cancelled": "❌ Amal bekor qilindi.",
        "none_val": "Kiritilmagan",
    },
    "cyrl": {
        "root_title": "👥 <b>Талабалар бўлими</b>\nКеракли амални танланг:",
        "no_groups": "ℹ️ Сизга бириктирилган гуруҳлар топилмади.",
        "no_permission": "❌ Сизда ушбу амални бажариш ҳуқуқи йўқ.",
        "select_group_add": "➕ Янги талаба қўшиладиган гуруҳни танланг:",
        "select_group_manage": "👤 Талабаларни кўриш учун гуруҳни танланг:",
        "enter_full_name": "👤 Талабанинг <b>Ф.И.О.</b> ни киритинг:",
        "enter_stu_phone": "📞 Талабанинг телефон рақамини киритинг (масалан: <code>+998901234567</code>):",
        "enter_stu_tg": "✈️ Талабанинг Telegram username ни киритинг (масалан: <code>@username</code>):",
        "enter_father_phone": "🧔‍♂️ Отасининг телефон рақамини киритинг (масалан: <code>+998901234567</code>):",
        "enter_mother_phone": "🧕 Онасининг телефон рақамини киритинг (масалан: <code>+998901234567</code>):",
        "invite_links_info": (
            "🔗 <b>Таклиф ҳаволалари ({group})</b>\n\n"
            "🎓 <b>Талаба ўзи қўшилиши учун ҳавола:</b>\n"
            "<code>https://t.me/{bot_username}?start=join_{group_slug}</code>\n\n"
            "👨‍👩‍👧 <b>Ота-она қўшилиши учун:</b>\n"
            "Талаба сўрови тасдиқлангач автоматик шахсий <code>?start=par_ID</code> ҳаволаси яратилади. "
            "Мавжуд талаба учун эса «👤 Талабаларни бошқариш → 🔗 Таклиф ҳаволалари» орқали олишингиз мумкин."
        ),
        "teacher_invite_only_info": (
            "🔗 <b>{group} — Талаба таклиф ҳаволаси</b>\n\n"
            "Талаба ушбу ҳавола орқали ботга кириб, ўз Ф.И.О. ва телефон рақамини юборгач, "
            "сизга тасдиқлаш учун сўров юборилади:\n\n"
            "<code>https://t.me/{bot_username}?start=join_{group_slug}</code>"
        ),
        "add_confirm": (
            "➕ <b>Янги талаба маълумотларини тасдиқланг:</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📞 Талаба тел: <b>{stu_phone}</b>\n"
            "✈️ Талаба ТГ: <b>{stu_tg}</b>\n"
            "🧔‍♂️ Отаси тел: <b>{father_phone}</b>\n"
            "🧕 Онаси тел: <b>{mother_phone}</b>"
        ),
        "add_success": (
            "✅ <b>Талаба муваффақиятли қўшилди!</b>\n\n"
            "🆔 Талаба ID: <code>{student_id}</code>\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n\n"
            "🔗 <b>Таклиф ҳаволалари:</b>\n"
            "🎓 Талаба учун:\n<code>https://t.me/{bot_username}?start=stu_{student_id}</code>\n\n"
            "👨‍👩‍👧 Ота-она учун:\n<code>https://t.me/{bot_username}?start=par_{student_id}</code>"
        ),
        "links_card": (
            "🔗 <b>{full_name}</b> (<code>{student_id}</code>) учун таклиф ҳаволалари:\n\n"
            "🎓 Талаба учун:\n<code>https://t.me/{bot_username}?start=stu_{student_id}</code>\n\n"
            "👨‍👩‍👧 Ота-она учун:\n<code>https://t.me/{bot_username}?start=par_{student_id}</code>"
        ),
        "no_students_in_group": "ℹ️ <b>{group}</b> гуруҳида талабалар топилмади.",
        "select_student": "👤 Талабани танланг (<b>{group}</b>):",
        "student_card": (
            "👤 <b>Талаба картаси</b>\n\n"
            "🆔 ID: <code>{student_id}</code>\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📊 Статус: <b>{status}</b>\n"
            "📞 Талаба тел: <b>{stu_phone}</b>\n"
            "✈️ Талаба ТГ: <b>{stu_tg}</b>\n"
            "🧔‍♂️ Отаси тел: <b>{father_phone}</b>\n"
            "🧕 Онаси тел: <b>{mother_phone}</b>\n"
            "⚠️ Қарздорлик: <b>{debts}</b>"
        ),
        "choose_edit_field": "✏️ Қайси маълумотни ўзгартирмоқчисиз?",
        "enter_new_value": "📝 <b>{field}</b> учун янги қийматни киритинг:",
        "select_new_group": "📚 Янги гуруҳни танланг:",
        "updated_ok": "✅ Маълумот янгиланди!",
        "confirm_delete": "⚠️ Ҳақиқатан ҳам <b>{full_name}</b> (<code>{student_id}</code>) ни базадан ва гуруҳ жадвалидан ўчирмоқчимисиз?",
        "deleted_ok": "🗑 Талаба (<code>{student_id}</code>) базадан ва гуруҳ жадвалидан ўчирилди.",
        "action_cancelled": "❌ Амал бекор қилинди.",
        "none_val": "Киритилмаган",
    },
}


def _st(key: str, lang: str, **kwargs: Any) -> str:
    safe = lang if lang in _LOCAL_STU_TEXTS else "latn"
    txt = _LOCAL_STU_TEXTS[safe][key]
    return txt.format(**kwargs) if kwargs else txt


def _slugify_group_name(group_name: str) -> str:
    return (
        re.sub(r"[^A-Za-z0-9_-]+", "_", group_name.strip()).strip("_")[:55]
        or "group"
    )


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


async def _get_role_and_groups(user_id: int) -> tuple[str | None, list[dict]]:
    sheets = get_sheets_manager()
    if await _is_admin(user_id):
        return "admin", await asyncio.to_thread(sheets.get_all_groups)
    raw_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
    t_groups = [
        g
        for g in raw_groups
        if str(g.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
    ]
    if t_groups:
        return "teacher", t_groups
    return None, []


def _ensure_extended_student_headers_sync() -> None:
    sheets = get_sheets_manager()
    with sheets._lock:
        ws = sheets._get_or_create_worksheet(
            STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=18
        )
        headers = ws.row_values(1) or list(STUDENT_HEADERS)
        missing = [c for c in EXTENDED_STUDENT_COLUMNS if c not in headers]
        if missing:
            if ws.col_count < len(headers) + len(missing):
                ws.resize(cols=len(headers) + len(missing))
            start_col = len(headers)
            ws.update(
                f"{_col_letter(start_col)}1",
                [missing],
                value_input_option="USER_ENTERED",
            )
            sheets._get_spreadsheet().batch_update(
                {
                    "requests": [
                        _cell_bg_request(
                            ws.id,
                            0,
                            1,
                            start_col,
                            start_col + len(missing),
                            COLOR_HEADER_GRAY,
                            bold=True,
                        )
                    ]
                }
            )


def _sync_append_student_to_active_cycle(
    group_name: str, student_id: str, full_name: str
) -> None:
    sheets = get_sheets_manager()
    from datetime import datetime
    from app.config import TZ

    current_year = datetime.now(TZ).year
    with sheets._lock:
        ss = sheets._get_spreadsheet()
        try:
            ws = ss.worksheet(f"{group_name.strip()}_{current_year}")
        except Exception:
            return
        cycles = sheets.parse_cycles_from_sheet(ws)
        if not cycles:
            return
        latest = cycles[-1]
        if any(
            r["student_id"].strip() == student_id.strip()
            for r in latest["student_rows"]
        ):
            return
        insert_row_0 = latest["last_row_idx"] + 1
        tolov_col_idx = latest["tolov_col_idx"]
        row_data = [student_id, full_name] + [""] * (tolov_col_idx - 1)
        ws.insert_row(
            row_data, index=insert_row_0 + 1, value_input_option="USER_ENTERED"
        )
        ss.batch_update(
            {
                "requests": [
                    _cell_bg_request(
                        ws.id,
                        insert_row_0,
                        insert_row_0 + 1,
                        0,
                        2,
                        COLOR_WHITE,
                        bold=False,
                    ),
                    _cell_bg_request(
                        ws.id,
                        insert_row_0,
                        insert_row_0 + 1,
                        2,
                        tolov_col_idx + 1,
                        COLOR_WHITE,
                        bold=False,
                        h_align="CENTER",
                    ),
                    _borders_request(
                        ws.id,
                        insert_row_0,
                        insert_row_0 + 1,
                        0,
                        tolov_col_idx + 1,
                    ),
                ]
            }
        )


async def _cleanup_deleted_student_sqlite(
    student_id: str, deleted_student: Optional[dict[str, Any]] = None
) -> None:
    """
    Safely updates/clears SQLite roles after deleting a specific student_id.
    If the student (or parent) still has another active enrollment in a different
    group, keeps their role active and re-points linked_student_id to a remaining
    enrollment.
    """
    sheets = get_sheets_manager()
    clean_sid = student_id.strip()

    stu_cid_str = (
        str(deleted_student.get("Talaba_Chat_ID", "")).strip()
        if deleted_student
        else ""
    )
    parent_cids: list[str] = []
    if deleted_student:
        for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
            val = str(deleted_student.get(col, "")).strip()
            if val and val not in parent_cids:
                parent_cids.append(val)

    async with aiosqlite.connect(DB_PATH) as db:
        if stu_cid_str.isdigit():
            remaining = await sheets.a_get_students_by_chat_id(stu_cid_str)
            if remaining:
                next_sid = remaining[0]["Talaba_ID"]
                await db.execute(
                    "UPDATE users SET role = 'student', linked_student_id = ? "
                    "WHERE telegram_id = ? AND (linked_student_id = ? OR linked_student_id IS NULL);",
                    (next_sid, int(stu_cid_str), clean_sid),
                )
            else:
                await db.execute(
                    "UPDATE users SET role = NULL, linked_student_id = NULL "
                    "WHERE telegram_id = ? AND role = 'student';",
                    (int(stu_cid_str),),
                )

        for p_cid in parent_cids:
            if not p_cid.isdigit():
                continue
            remaining_children = await sheets.a_get_children_by_parent_chat_id(
                p_cid
            )
            if remaining_children:
                next_sid = remaining_children[0]["Talaba_ID"]
                await db.execute(
                    "UPDATE users SET role = 'parent', linked_student_id = ? "
                    "WHERE telegram_id = ? AND linked_student_id = ?;",
                    (next_sid, int(p_cid), clean_sid),
                )
            else:
                await db.execute(
                    "UPDATE users SET role = NULL, linked_student_id = NULL "
                    "WHERE telegram_id = ? AND role = 'parent';",
                    (int(p_cid),),
                )

        await db.execute(
            "UPDATE users SET role = NULL, linked_student_id = NULL WHERE linked_student_id = ?;",
            (clean_sid,),
        )
        try:
            await db.execute(
                "DELETE FROM parent_meta WHERE student_id = ?;",
                (clean_sid,),
            )
        except Exception:
            pass
        await db.commit()


def _format_student_card(
    student: dict[str, Any],
    lang: str,
    viewer_user_id: Optional[int] = None,
) -> str:
    none_val = _st("none_val", lang)
    full_name_disp = html.escape(student.get("F.I.O.", ""))
    if (
        viewer_user_id is not None
        and str(student.get("Talaba_Chat_ID", "")).strip() == str(viewer_user_id)
    ):
        full_name_disp = f"{full_name_disp} {t('self_marker', lang)}"

    father_phone = (
        student.get("Otasi_Tel", "").strip()
        or student.get("OtaOna_Tel", "").strip()
        or none_val
    )
    if (
        viewer_user_id is not None
        and str(student.get("Otasi_Chat_ID", "")).strip() == str(viewer_user_id)
    ):
        father_fio = str(student.get("Otasi_FIO", "")).strip()
        if father_fio:
            father_phone = (
                f"{father_fio} {t('self_marker', lang)} | {father_phone}"
            )
        else:
            father_phone = f"{father_phone} {t('self_marker', lang)}"

    mother_phone = student.get("Onasi_Tel", "").strip() or none_val
    if (
        viewer_user_id is not None
        and str(student.get("Onasi_Chat_ID", "")).strip() == str(viewer_user_id)
    ):
        mother_fio = str(student.get("Onasi_FIO", "")).strip()
        if mother_fio:
            mother_phone = (
                f"{mother_fio} {t('self_marker', lang)} | {mother_phone}"
            )
        else:
            mother_phone = f"{mother_phone} {t('self_marker', lang)}"

    return _st(
        "student_card",
        lang,
        student_id=html.escape(student.get("Talaba_ID", "")),
        full_name=full_name_disp,
        group=html.escape(student.get("Guruh", "")),
        status=html.escape(student.get("Status", "")),
        stu_phone=html.escape(student.get("Talaba_Tel") or none_val),
        stu_tg=html.escape(student.get("Talaba_TG") or none_val),
        father_phone=html.escape(father_phone),
        mother_phone=html.escape(mother_phone),
        debts=html.escape(student.get("Qarzdor_Oylar") or none_val),
    )


# ======================================================================
# Entry Points (Admin & Teacher)
# ======================================================================


@router.message(
    F.text.in_({t("menu_admin_students", "latn"), t("menu_admin_students", "cyrl")})
)
async def admin_students_menu(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await message.answer(_st("no_permission", lang), parse_mode="HTML")
        return
    await state.clear()
    await message.answer(
        _st("root_title", lang),
        reply_markup=student_root_menu_kb(lang),
        parse_mode="HTML",
    )


@router.message(
    F.text.in_(
        {t("menu_teacher_add_student", "latn"), t("menu_teacher_add_student", "cyrl")}
    )
)
async def teacher_add_student_direct(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    role, groups = await _get_role_and_groups(user_id)
    if role not in {"admin", "teacher"}:
        return
    if not groups:
        await message.answer(_st("no_groups", lang), parse_mode="HTML")
        return
    await state.clear()
    await state.update_data(
        stu_entry_role="admin_direct" if role == "admin" else "teacher_direct"
    )
    await state.set_state(StudentAddStates.selecting_group)
    await message.answer(
        _st("select_group_add", lang),
        reply_markup=groups_inline_kb(
            groups,
            "stu_add_grp",
            lang,
            include_back=(role == "admin"),
            include_cancel=True,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("stu_menu:"))
async def student_root_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    action = (callback.data or "").split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return

    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return

    _, groups = await _get_role_and_groups(user_id)
    if not groups:
        await callback.message.edit_text(_st("no_groups", lang))
        await callback.answer()
        return

    await state.update_data(stu_entry_role="admin_menu")
    if action == "add":
        await state.set_state(StudentAddStates.selecting_group)
        await callback.message.edit_text(
            _st("select_group_add", lang),
            reply_markup=groups_inline_kb(
                groups, "stu_add_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
    elif action == "manage":
        await state.set_state(StudentManageStates.selecting_group)
        await callback.message.edit_text(
            _st("select_group_manage", lang),
            reply_markup=groups_inline_kb(
                groups, "stu_mng_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
    await callback.answer()


# ======================================================================
# 1. ADD NEW STUDENT FLOW (Admin: Manual & Invite | Teacher: Invite Only)
# ======================================================================


@router.callback_query(
    StateFilter(StudentAddStates.selecting_group), F.data.startswith("stu_add_grp:")
)
async def stu_add_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    group_name = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()

    if group_name == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return

    is_admin = await _is_admin(user_id)
    if group_name == "__back__":
        await state.clear()
        if is_admin and data.get("stu_entry_role") == "admin_menu":
            await callback.message.edit_text(
                _st("root_title", lang),
                reply_markup=student_root_menu_kb(lang),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return

    if not is_admin:
        # Teacher: verify the group is actually assigned to this teacher and
        # immediately generate & send ONLY the invite deep-link.
        _, t_groups = await _get_role_and_groups(user_id)
        allowed = any(
            str(g.get("Guruh_Nomi", "")).strip().lower()
            == group_name.strip().lower()
            for g in t_groups
        )
        if not allowed:
            await state.clear()
            await callback.answer(_st("no_permission", lang), show_alert=True)
            return

        bot_me = await callback.bot.get_me()
        group_slug = _slugify_group_name(group_name)
        await state.clear()
        await callback.message.edit_text(
            _st(
                "teacher_invite_only_info",
                lang,
                group=html.escape(group_name),
                bot_username=bot_me.username,
                group_slug=group_slug,
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await callback.answer()
        return

    await state.update_data(group_name=group_name)
    await state.set_state(StudentAddStates.choosing_method)
    await callback.message.edit_text(
        t("student_add_choose_method", lang),
        reply_markup=student_add_method_kb(lang, back_cb="stu_add_method:back"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentAddStates.choosing_method), F.data.startswith("stu_add_method:")
)
async def stu_add_method_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    choice = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()

    if choice == "cancel":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return

    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return

    if choice == "back":
        _, groups = await _get_role_and_groups(user_id)
        await state.set_state(StudentAddStates.selecting_group)
        await callback.message.edit_text(
            _st("select_group_add", lang),
            reply_markup=groups_inline_kb(
                groups, "stu_add_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    if choice == "invite":
        group_name = data["group_name"]
        entry_role = data.get("stu_entry_role", "admin_menu")
        bot_me = await callback.bot.get_me()
        group_slug = _slugify_group_name(group_name)
        await state.clear()
        await callback.message.edit_text(
            _st(
                "invite_links_info",
                lang,
                group=html.escape(group_name),
                bot_username=bot_me.username,
                group_slug=group_slug,
            ),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb=f"stu_add_invite_back:{entry_role}:{group_name}",
                cancel_cb="stu_add_cancel",
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await callback.answer()
        return

    if choice == "manual":
        await state.set_state(StudentAddStates.entering_full_name)
        await callback.message.edit_text(
            _st("enter_full_name", lang),
            reply_markup=step_nav_inline_kb(
                lang, back_cb="stu_add_back:method", cancel_cb="stu_add_cancel"
            ),
            parse_mode="HTML",
        )
        await callback.answer()


@router.callback_query(F.data.startswith("stu_add_invite_back:"))
async def stu_add_invite_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    _, entry_role, group_name = (callback.data or "").split(":", 2)
    await state.update_data(stu_entry_role=entry_role, group_name=group_name)
    await state.set_state(StudentAddStates.choosing_method)
    await callback.message.edit_text(
        t("student_add_choose_method", lang),
        reply_markup=student_add_method_kb(lang, back_cb="stu_add_method:back"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "stu_add_cancel")
async def stu_add_cancel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user and callback.message:
        lang = await get_user_lang(callback.from_user.id)
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
    await callback.answer()


@router.callback_query(StateFilter(StudentAddStates), F.data.startswith("stu_add_back:"))
async def stu_add_step_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    target = (callback.data or "").split(":", 1)[1]

    if target == "method":
        await state.set_state(StudentAddStates.choosing_method)
        await callback.message.edit_text(
            t("student_add_choose_method", lang),
            reply_markup=student_add_method_kb(lang, back_cb="stu_add_method:back"),
            parse_mode="HTML",
        )
    elif target == "name":
        await state.set_state(StudentAddStates.entering_full_name)
        await callback.message.edit_text(
            _st("enter_full_name", lang),
            reply_markup=step_nav_inline_kb(
                lang, back_cb="stu_add_back:method", cancel_cb="stu_add_cancel"
            ),
            parse_mode="HTML",
        )
    elif target == "stu_phone":
        await state.set_state(StudentAddStates.entering_student_phone)
        await callback.message.edit_text(
            _st("enter_stu_phone", lang),
            reply_markup=skip_or_cancel_inline_kb(
                "stu_add_skip:stu_phone",
                "stu_add_cancel",
                lang,
                back_cb="stu_add_back:name",
            ),
            parse_mode="HTML",
        )
    elif target == "stu_tg":
        await state.set_state(StudentAddStates.entering_student_tg)
        await callback.message.edit_text(
            _st("enter_stu_tg", lang),
            reply_markup=skip_or_cancel_inline_kb(
                "stu_add_skip:stu_tg",
                "stu_add_cancel",
                lang,
                back_cb="stu_add_back:stu_phone",
            ),
            parse_mode="HTML",
        )
    elif target == "father_phone":
        await state.set_state(StudentAddStates.entering_father_phone)
        await callback.message.edit_text(
            _st("enter_father_phone", lang),
            reply_markup=skip_or_cancel_inline_kb(
                "stu_add_skip:father_phone",
                "stu_add_cancel",
                lang,
                back_cb="stu_add_back:stu_tg",
            ),
            parse_mode="HTML",
        )
    elif target == "mother_phone":
        await state.set_state(StudentAddStates.entering_mother_phone)
        await callback.message.edit_text(
            _st("enter_mother_phone", lang),
            reply_markup=skip_or_cancel_inline_kb(
                "stu_add_skip:mother_phone",
                "stu_add_cancel",
                lang,
                back_cb="stu_add_back:father_phone",
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(StateFilter(StudentAddStates.entering_full_name))
async def stu_add_name_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_st("no_permission", lang))
        return
    full_name = (message.text or "").strip()
    if full_name in {t("btn_cancel", "latn"), t("btn_cancel", "cyrl")}:
        await state.clear()
        await message.answer(
            _st("action_cancelled", lang),
            reply_markup=get_main_menu_kb("admin", lang),
        )
        return

    await state.update_data(full_name=full_name)
    await state.set_state(StudentAddStates.entering_student_phone)
    await message.answer(
        _st("enter_stu_phone", lang),
        reply_markup=skip_or_cancel_inline_kb(
            "stu_add_skip:stu_phone",
            "stu_add_cancel",
            lang,
            back_cb="stu_add_back:name",
        ),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(
        StudentAddStates.entering_student_phone,
        StudentAddStates.entering_student_tg,
        StudentAddStates.entering_father_phone,
        StudentAddStates.entering_mother_phone,
    ),
    F.data.startswith("stu_add_skip:"),
)
async def stu_add_skip_step(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    step = (callback.data or "").split(":", 1)[1]

    if step == "stu_phone":
        await state.update_data(stu_phone="")
        await state.set_state(StudentAddStates.entering_student_tg)
        await callback.message.edit_text(
            _st("enter_stu_tg", lang),
            reply_markup=skip_or_cancel_inline_kb(
                "stu_add_skip:stu_tg",
                "stu_add_cancel",
                lang,
                back_cb="stu_add_back:stu_phone",
            ),
            parse_mode="HTML",
        )
    elif step == "stu_tg":
        await state.update_data(stu_tg="")
        await state.set_state(StudentAddStates.entering_father_phone)
        await callback.message.edit_text(
            _st("enter_father_phone", lang),
            reply_markup=skip_or_cancel_inline_kb(
                "stu_add_skip:father_phone",
                "stu_add_cancel",
                lang,
                back_cb="stu_add_back:stu_tg",
            ),
            parse_mode="HTML",
        )
    elif step == "father_phone":
        await state.update_data(father_phone="")
        await state.set_state(StudentAddStates.entering_mother_phone)
        await callback.message.edit_text(
            _st("enter_mother_phone", lang),
            reply_markup=skip_or_cancel_inline_kb(
                "stu_add_skip:mother_phone",
                "stu_add_cancel",
                lang,
                back_cb="stu_add_back:father_phone",
            ),
            parse_mode="HTML",
        )
    elif step == "mother_phone":
        await state.update_data(mother_phone="")
        await _show_add_student_confirm(callback.message, state, lang, edit=True)
    await callback.answer()


@router.message(StateFilter(StudentAddStates.entering_student_phone))
async def stu_add_phone_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_st("no_permission", lang))
        return
    val = (message.text or "").strip()
    await state.update_data(stu_phone="" if val == "-" else val)
    await state.set_state(StudentAddStates.entering_student_tg)
    await message.answer(
        _st("enter_stu_tg", lang),
        reply_markup=skip_or_cancel_inline_kb(
            "stu_add_skip:stu_tg",
            "stu_add_cancel",
            lang,
            back_cb="stu_add_back:stu_phone",
        ),
        parse_mode="HTML",
    )


@router.message(StateFilter(StudentAddStates.entering_student_tg))
async def stu_add_tg_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_st("no_permission", lang))
        return
    val = (message.text or "").strip()
    tg_val = "" if val == "-" else (val if val.startswith("@") else f"@{val}")
    await state.update_data(stu_tg=tg_val)
    await state.set_state(StudentAddStates.entering_father_phone)
    await message.answer(
        _st("enter_father_phone", lang),
        reply_markup=skip_or_cancel_inline_kb(
            "stu_add_skip:father_phone",
            "stu_add_cancel",
            lang,
            back_cb="stu_add_back:stu_tg",
        ),
        parse_mode="HTML",
    )


@router.message(StateFilter(StudentAddStates.entering_father_phone))
async def stu_add_father_phone_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_st("no_permission", lang))
        return
    val = (message.text or "").strip()
    await state.update_data(father_phone="" if val == "-" else val)
    await state.set_state(StudentAddStates.entering_mother_phone)
    await message.answer(
        _st("enter_mother_phone", lang),
        reply_markup=skip_or_cancel_inline_kb(
            "stu_add_skip:mother_phone",
            "stu_add_cancel",
            lang,
            back_cb="stu_add_back:father_phone",
        ),
        parse_mode="HTML",
    )


@router.message(StateFilter(StudentAddStates.entering_mother_phone))
async def stu_add_mother_phone_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_st("no_permission", lang))
        return
    val = (message.text or "").strip()
    await state.update_data(mother_phone="" if val == "-" else val)
    await _show_add_student_confirm(message, state, lang, edit=False)


async def _show_add_student_confirm(
    target_msg: Message, state: FSMContext, lang: str, edit: bool
) -> None:
    data = await state.get_data()
    none_val = _st("none_val", lang)
    await state.set_state(StudentAddStates.confirming)
    text = _st(
        "add_confirm",
        lang,
        group=html.escape(data["group_name"]),
        full_name=html.escape(data["full_name"]),
        stu_phone=html.escape(data.get("stu_phone") or none_val),
        stu_tg=html.escape(data.get("stu_tg") or none_val),
        father_phone=html.escape(data.get("father_phone") or none_val),
        mother_phone=html.escape(data.get("mother_phone") or none_val),
    )
    kb = confirm_cancel_kb(
        "stu_add_confirm",
        "stu_add_cancel",
        lang,
        back_cb="stu_add_back:mother_phone",
    )
    await (target_msg.edit_text if edit else target_msg.answer)(
        text, reply_markup=kb, parse_mode="HTML"
    )


@router.callback_query(
    StateFilter(StudentAddStates.confirming), F.data == "stu_add_confirm"
)
async def stu_add_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    data = await state.get_data()
    sheets = get_sheets_manager()

    father_phone = data.get("father_phone", "")
    mother_phone = data.get("mother_phone", "")
    primary_parent_phone = father_phone or mother_phone

    await asyncio.to_thread(_ensure_extended_student_headers_sync)
    new_student = await asyncio.to_thread(
        sheets.add_student,
        full_name=data["full_name"],
        group_name=data["group_name"],
        student_phone=data.get("stu_phone", ""),
        student_tg=data.get("stu_tg", ""),
        parent_phone=primary_parent_phone,
        status="O'qiyapti",
    )
    student_id = new_student["Talaba_ID"]
    extra_updates: dict[str, Any] = {}
    if father_phone:
        extra_updates["Otasi_Tel"] = father_phone
    if mother_phone:
        extra_updates["Onasi_Tel"] = mother_phone
    if extra_updates:
        await asyncio.to_thread(sheets.update_student, student_id, extra_updates)

    await asyncio.to_thread(
        _sync_append_student_to_active_cycle,
        data["group_name"],
        student_id,
        data["full_name"],
    )
    bot_info = await callback.bot.get_me()
    await state.clear()
    await callback.message.edit_text(
        _st(
            "add_success",
            lang,
            student_id=html.escape(student_id),
            full_name=html.escape(data["full_name"]),
            group=html.escape(data["group_name"]),
            bot_username=bot_info.username,
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


# ======================================================================
# 2. MANAGE EXISTING STUDENTS (Admin Only: Status, Edit, Transfer, Links, Delete)
# ======================================================================


@router.callback_query(
    StateFilter(StudentManageStates.selecting_group), F.data.startswith("stu_mng_grp:")
)
async def stu_mng_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    group_name = (callback.data or "").split(":", 1)[1]

    if group_name == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return
    if group_name == "__back__":
        await state.clear()
        await callback.message.edit_text(
            _st("root_title", lang),
            reply_markup=student_root_menu_kb(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    sheets = get_sheets_manager()
    students = await asyncio.to_thread(
        sheets.get_all_students, group_name=group_name, active_only=False
    )
    if not students:
        _, groups = await _get_role_and_groups(user_id)
        await callback.message.edit_text(
            _st("no_students_in_group", lang, group=html.escape(group_name)),
            reply_markup=groups_inline_kb(
                groups, "stu_mng_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.update_data(group_name=group_name)
    await state.set_state(StudentManageStates.selecting_student)
    await callback.message.edit_text(
        _st("select_student", lang, group=html.escape(group_name)),
        reply_markup=students_list_kb(
            students, "stu_sel", lang, include_back=True, include_cancel=True
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.selecting_student), F.data.startswith("stu_sel:")
)
async def stu_mng_student_selected(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1]

    if sid == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return
    if sid == "__back__":
        _, groups = await _get_role_and_groups(user_id)
        await state.set_state(StudentManageStates.selecting_group)
        await callback.message.edit_text(
            _st("select_group_manage", lang),
            reply_markup=groups_inline_kb(
                groups, "stu_mng_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    student = await get_sheets_manager().a_get_student_by_id(sid)
    if not student:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    await state.update_data(student_id=sid)
    await state.set_state(StudentManageStates.viewing_student)
    await callback.message.edit_text(
        _format_student_card(student, lang, viewer_user_id=user_id),
        reply_markup=student_actions_kb(sid, student.get("Status", "O'qiyapti"), lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.viewing_student), F.data.startswith("stu_act:")
)
async def stu_mng_action_clicked(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    parts = (callback.data or "").split(":")
    action = parts[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return
    if action == "back":
        group_name = (await state.get_data()).get("group_name", "")
        students = await asyncio.to_thread(
            get_sheets_manager().get_all_students,
            group_name=group_name,
            active_only=False,
        )
        await state.set_state(StudentManageStates.selecting_student)
        await callback.message.edit_text(
            _st("select_student", lang, group=html.escape(group_name)),
            reply_markup=students_list_kb(
                students, "stu_sel", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    sid = parts[2]
    sheets = get_sheets_manager()
    student = await sheets.a_get_student_by_id(sid)
    if not student:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    if action == "status":
        new_status = (
            "O'qimayapti" if student.get("Status") == "O'qiyapti" else "O'qiyapti"
        )
        await asyncio.to_thread(sheets.update_student, sid, {"Status": new_status})
        student = await sheets.a_get_student_by_id(sid)
        await callback.message.edit_text(
            _format_student_card(student, lang, viewer_user_id=user_id),
            reply_markup=student_actions_kb(sid, new_status, lang),
            parse_mode="HTML",
        )
        await callback.answer(_st("updated_ok", lang))
    elif action == "edit":
        await state.set_state(StudentManageStates.editing_field)
        await callback.message.edit_text(
            _st("choose_edit_field", lang),
            reply_markup=student_edit_fields_kb(sid, lang),
            parse_mode="HTML",
        )
        await callback.answer()
    elif action == "links":
        bot_info = await callback.bot.get_me()
        await callback.message.answer(
            _st(
                "links_card",
                lang,
                full_name=html.escape(student.get("F.I.O.", "")),
                student_id=html.escape(sid),
                bot_username=bot_info.username,
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await callback.answer()
    elif action == "delete":
        await state.set_state(StudentManageStates.confirming_delete)
        await callback.message.edit_text(
            _st(
                "confirm_delete",
                lang,
                full_name=html.escape(student.get("F.I.O.", "")),
                student_id=html.escape(sid),
            ),
            reply_markup=confirm_delete_student_kb(sid, lang),
            parse_mode="HTML",
        )
        await callback.answer()


@router.callback_query(StateFilter(StudentManageStates), F.data == "stu_act:cancel")
async def stu_mng_global_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user and callback.message:
        lang = await get_user_lang(callback.from_user.id)
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
    await callback.answer()


@router.callback_query(
    StateFilter(
        StudentManageStates.editing_field,
        StudentManageStates.entering_new_value,
        StudentManageStates.selecting_new_group,
    ),
    F.data.startswith("stu_field_back:"),
)
async def stu_edit_field_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1]
    student = await get_sheets_manager().a_get_student_by_id(sid)
    if not student:
        await state.clear()
        await callback.answer()
        return
    await state.set_state(StudentManageStates.viewing_student)
    await callback.message.edit_text(
        _format_student_card(student, lang, viewer_user_id=user_id),
        reply_markup=student_actions_kb(sid, student.get("Status", "O'qiyapti"), lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(
        StudentManageStates.entering_new_value,
        StudentManageStates.selecting_new_group,
    ),
    F.data.startswith("stu_edit_fields_back:"),
)
async def stu_edit_back_to_fields(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1]
    await state.set_state(StudentManageStates.editing_field)
    await callback.message.edit_text(
        _st("choose_edit_field", lang),
        reply_markup=student_edit_fields_kb(sid, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.editing_field), F.data.startswith("stu_field:")
)
async def stu_edit_field_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    _, sid, field_name = (callback.data or "").split(":", 2)
    await state.update_data(student_id=sid, edit_field=field_name)

    if field_name == "Guruh":
        _, groups = await _get_role_and_groups(user_id)
        await state.set_state(StudentManageStates.selecting_new_group)
        await callback.message.edit_text(
            _st("select_new_group", lang),
            reply_markup=groups_inline_kb(
                groups, "stu_new_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
    else:
        await state.set_state(StudentManageStates.entering_new_value)
        await callback.message.edit_text(
            _st("enter_new_value", lang, field=html.escape(field_name)),
            reply_markup=step_nav_inline_kb(
                lang, back_cb=f"stu_edit_fields_back:{sid}", cancel_cb="stu_act:cancel"
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.selecting_new_group),
    F.data.startswith("stu_new_grp:"),
)
async def stu_edit_new_group_selected(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    new_group = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()
    sid = data["student_id"]

    if new_group == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return
    if new_group == "__back__":
        await state.set_state(StudentManageStates.editing_field)
        await callback.message.edit_text(
            _st("choose_edit_field", lang),
            reply_markup=student_edit_fields_kb(sid, lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    sheets = get_sheets_manager()
    student = await sheets.a_get_student_by_id(sid)
    if not student:
        await state.clear()
        await callback.message.edit_text(t("error_generic", lang))
        await callback.answer()
        return

    old_group = str(student.get("Guruh", "")).strip()
    if old_group.lower() == new_group.strip().lower():
        await state.set_state(StudentManageStates.viewing_student)
        await callback.message.edit_text(
            _format_student_card(student, lang, viewer_user_id=user_id),
            reply_markup=student_actions_kb(
                sid, student.get("Status", "O'qiyapti"), lang
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.update_data(
        student_id=sid,
        target_group=new_group.strip(),
        old_group=old_group,
    )
    await state.set_state(StudentManageStates.confirm_keep_in_old_group)
    await callback.message.edit_text(
        t(
            "stu_transfer_keep_question",
            lang,
            student_name=html.escape(student.get("F.I.O.", "")),
            old_group=html.escape(old_group),
            new_group=html.escape(new_group.strip()),
        ),
        reply_markup=student_transfer_keep_kb(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.confirm_keep_in_old_group),
    F.data.startswith("transfer_keep:"),
)
async def stu_transfer_keep_confirmed(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    choice = (callback.data or "").split(":", 1)[1]
    keep_in_old_group = choice == "yes"

    data = await state.get_data()
    sid = str(data.get("student_id", "")).strip()
    target_group = str(data.get("target_group", "")).strip()
    if not sid or not target_group:
        await state.clear()
        await callback.message.edit_text(t("error_generic", lang))
        await callback.answer()
        return

    sheets = get_sheets_manager()
    try:
        result = await sheets.a_transfer_or_enroll_student(
            sid, target_group, keep_in_old_group
        )
    except Exception:
        await state.clear()
        await callback.message.edit_text(t("error_generic", lang))
        await callback.answer()
        return

    old_group = result["old_group"]
    new_group = result["new_group"]
    new_student_id = result["new_student_id"]
    updated_student = result["student"]
    student_name = str(updated_student.get("F.I.O.", "")).strip()

    # Notify Student via DM
    stu_cid_str = str(updated_student.get("Talaba_Chat_ID", "")).strip()
    if stu_cid_str.isdigit() and int(stu_cid_str) != user_id:
        try:
            s_cid = int(stu_cid_str)
            s_lang = await get_user_lang(s_cid)
            s_key = (
                "stu_transfer_notify_dual_student"
                if keep_in_old_group
                else "stu_transfer_notify_move_student"
            )
            await callback.bot.send_message(
                chat_id=s_cid,
                text=t(
                    s_key,
                    s_lang,
                    student_name=html.escape(student_name),
                    old_group=html.escape(old_group),
                    new_group=html.escape(new_group),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Notify Father & Mother via DM
    notified_parents: set[int] = set()
    father_cid_str = str(updated_student.get("Otasi_Chat_ID", "")).strip()
    if father_cid_str.isdigit() and int(father_cid_str) != user_id:
        f_cid = int(father_cid_str)
        notified_parents.add(f_cid)
        try:
            f_lang = await get_user_lang(f_cid)
            f_name = (
                str(updated_student.get("Otasi_FIO", "")).strip()
                or t("parent_label_father", f_lang)
            )
            f_key = (
                "stu_transfer_notify_dual_father"
                if keep_in_old_group
                else "stu_transfer_notify_move_father"
            )
            await callback.bot.send_message(
                chat_id=f_cid,
                text=t(
                    f_key,
                    f_lang,
                    parent_name=html.escape(f_name),
                    student_name=html.escape(student_name),
                    old_group=html.escape(old_group),
                    new_group=html.escape(new_group),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    mother_cid_str = str(updated_student.get("Onasi_Chat_ID", "")).strip()
    if mother_cid_str.isdigit() and int(mother_cid_str) != user_id:
        m_cid = int(mother_cid_str)
        if m_cid not in notified_parents:
            notified_parents.add(m_cid)
            try:
                m_lang = await get_user_lang(m_cid)
                m_name = (
                    str(updated_student.get("Onasi_FIO", "")).strip()
                    or t("parent_label_mother", m_lang)
                )
                m_key = (
                    "stu_transfer_notify_dual_mother"
                    if keep_in_old_group
                    else "stu_transfer_notify_move_mother"
                )
                await callback.bot.send_message(
                    chat_id=m_cid,
                    text=t(
                        m_key,
                        m_lang,
                        parent_name=html.escape(m_name),
                        student_name=html.escape(student_name),
                        old_group=html.escape(old_group),
                        new_group=html.escape(new_group),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    legacy_parent_cid_str = str(
        updated_student.get("OtaOna_Chat_ID", "")
    ).strip()
    if legacy_parent_cid_str.isdigit() and int(legacy_parent_cid_str) != user_id:
        p_cid = int(legacy_parent_cid_str)
        if p_cid not in notified_parents:
            try:
                p_lang = await get_user_lang(p_cid)
                p_key = (
                    "stu_transfer_notify_dual_father"
                    if keep_in_old_group
                    else "stu_transfer_notify_move_father"
                )
                await callback.bot.send_message(
                    chat_id=p_cid,
                    text=t(
                        p_key,
                        p_lang,
                        parent_name=t("role_parent", p_lang),
                        student_name=html.escape(student_name),
                        old_group=html.escape(old_group),
                        new_group=html.escape(new_group),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    # Notify Teacher(s) via DM
    new_grp_obj = await sheets.a_get_group(new_group)
    new_t_cid_str = (
        str(new_grp_obj.get("Ustoz_Chat_ID", "")).strip()
        if new_grp_obj
        else ""
    )
    if new_t_cid_str.isdigit() and int(new_t_cid_str) != user_id:
        try:
            nt_cid = int(new_t_cid_str)
            nt_lang = await get_user_lang(nt_cid)
            await callback.bot.send_message(
                chat_id=nt_cid,
                text=t(
                    "stu_transfer_notify_new_teacher",
                    nt_lang,
                    new_group=html.escape(new_group),
                    student_name=html.escape(student_name),
                    student_id=html.escape(new_student_id),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    if not keep_in_old_group and old_group:
        old_grp_obj = await sheets.a_get_group(old_group)
        old_t_cid_str = (
            str(old_grp_obj.get("Ustoz_Chat_ID", "")).strip()
            if old_grp_obj
            else ""
        )
        if (
            old_t_cid_str.isdigit()
            and int(old_t_cid_str) != user_id
            and old_t_cid_str != new_t_cid_str
        ):
            try:
                ot_cid = int(old_t_cid_str)
                ot_lang = await get_user_lang(ot_cid)
                await callback.bot.send_message(
                    chat_id=ot_cid,
                    text=t(
                        "stu_transfer_notify_old_teacher_moved",
                        ot_lang,
                        student_name=html.escape(student_name),
                        old_group=html.escape(old_group),
                        new_group=html.escape(new_group),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    if keep_in_old_group:
        admin_notice = t(
            "stu_transfer_success_dual_admin",
            lang,
            student_name=html.escape(student_name),
            old_group=html.escape(old_group),
            new_group=html.escape(new_group),
            new_student_id=html.escape(new_student_id),
        )
    else:
        admin_notice = t(
            "stu_transfer_success_move_admin",
            lang,
            student_name=html.escape(student_name),
            student_id=html.escape(new_student_id),
            old_group=html.escape(old_group),
            new_group=html.escape(new_group),
        )

    await state.update_data(student_id=new_student_id, group_name=new_group)
    await state.set_state(StudentManageStates.viewing_student)
    card_text = _format_student_card(updated_student, lang, viewer_user_id=user_id)
    await callback.message.edit_text(
        f"{admin_notice}\n\n{card_text}",
        reply_markup=student_actions_kb(
            new_student_id, updated_student.get("Status", "O'qiyapti"), lang
        ),
        parse_mode="HTML",
    )
    await callback.answer(_st("updated_ok", lang))


@router.message(StateFilter(StudentManageStates.entering_new_value))
async def stu_edit_new_value_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_st("no_permission", lang))
        return
    new_val = (message.text or "").strip()
    data = await state.get_data()
    sid = data["student_id"]
    field_name = data["edit_field"]

    if field_name == "Talaba_TG" and new_val and not new_val.startswith("@"):
        new_val = f"@{new_val}"

    sheets = get_sheets_manager()
    await asyncio.to_thread(_ensure_extended_student_headers_sync)
    updates: dict[str, Any] = {field_name: new_val}
    if field_name == "Otasi_Tel":
        student_cur = await sheets.a_get_student_by_id(sid)
        if student_cur and not student_cur.get("OtaOna_Tel", "").strip():
            updates["OtaOna_Tel"] = new_val
    await asyncio.to_thread(sheets.update_student, sid, updates)
    student = await sheets.a_get_student_by_id(sid)
    await state.set_state(StudentManageStates.viewing_student)

    await message.answer(_st("updated_ok", lang))
    if student:
        await message.answer(
            _format_student_card(student, lang, viewer_user_id=user_id),
            reply_markup=student_actions_kb(
                sid, student.get("Status", "O'qiyapti"), lang
            ),
            parse_mode="HTML",
        )


@router.callback_query(
    StateFilter(StudentManageStates.confirming_delete),
    F.data.startswith("stu_del_cancel:"),
)
async def stu_delete_cancelled(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1]
    student = await get_sheets_manager().a_get_student_by_id(sid)
    await state.set_state(StudentManageStates.viewing_student)
    if student:
        await callback.message.edit_text(
            _format_student_card(student, lang, viewer_user_id=user_id),
            reply_markup=student_actions_kb(
                sid, student.get("Status", "O'qiyapti"), lang
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.confirming_delete),
    F.data.startswith("stu_del_confirm:"),
)
async def stu_delete_confirmed(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1]
    sheets = get_sheets_manager()
    student_before = await sheets.a_get_student_by_id(sid)
    deleted = await sheets.a_delete_student(sid)
    await state.clear()
    if deleted:
        await _cleanup_deleted_student_sqlite(sid, student_before)
        await callback.message.edit_text(
            _st("deleted_ok", lang, student_id=html.escape(sid)), parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(t("error_generic", lang))
    await callback.answer()