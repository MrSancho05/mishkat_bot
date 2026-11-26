import asyncio
import html
import inspect
import logging
import re
from datetime import datetime
from typing import Any, Optional

import aiosqlite
import gspread
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

from app import database
from app import states as app_states
from app.scheduler import normalize_chat_id_text, schedule_group_initial_notice
from app.utils import legacy_group_join_slug, make_group_join_slug, now_tashkent
from app.config import ADMIN_IDS, DB_PATH, STUDENT_SHEET_NAME, TZ, is_main_admin
from app.database import (
    get_group_name_by_tg_chat_id,
    set_group_tg_chat_id,
    activate_teacher_invite,
    add_user_role,
    create_join_request,
    create_role_change_request,
    create_role_conflict_request,
    get_all_dynamic_admins,
    get_join_request,
    get_parent_batch_invite,
    get_role_change_request,
    get_teacher_by_invite_code,
    get_teacher_by_telegram_id,
    get_user,
    get_user_lang,
    get_user_profile,
    get_user_roles,
    has_dual_student_parent_role,
    has_saved_language,
    mark_parent_batch_invite_used,
    purge_deleted_person_from_db,
    replace_user_role,
    reset_user_role,
    resolve_join_request,
    resolve_role_change_request,
    set_user_lang,
    switch_active_role,
    update_legacy_debts_student_name,
    upsert_user,
    upsert_user_profile,
)
from app.debt_view import format_uzs, get_group_monthly_fee
from app.keyboards import (
    MAIN_ROLE_CHOICES,
    main_admin_role_switch_kb,
    build_dual_role_approval_kb,
    cancel_reply_kb,
    enroll_choice_kb,
    get_main_menu_kb,
    guest_menu_kb,
    join_approval_kb,
    join_share_phone_kb,
    parent_type_kb,
    profile_actions_kb,
    profile_parent_role_kb,
    profile_step_nav_kb,
    share_phone_reply_kb,
)
from app.locales import button_texts, t
from app.sheets import (
    COLOR_HEADER_GRAY,
    STUDENT_HEADERS,
    SheetsManager,
    _cell_bg_request,
    _chat_id_str,
    _col_letter,
    get_sheets_manager,
)
from app.states import (
    GroupJoinStates,
    ParentRegStates,
    ProfileEditStates,
    StudentLinkRegStates,
    TeacherSelfRegStates,
)

logger = logging.getLogger(__name__)
router = Router(name="start_router")
_PENDING_START_ARGS: dict[int, str] = {}


class _FallbackAdminSelfRegStates(StatesGroup):
    entering_full_name = State()
    sharing_phone = State()


AdminSelfRegStates = getattr(
    app_states, "AdminSelfRegStates", _FallbackAdminSelfRegStates
)

TEACHER_SHEET_NAME = "Ustozlar"
TEACHER_HEADERS = [
    "Ustoz_ID",
    "F.I.O.",
    "Telefon",
    "TG_Username",
    "Chat_ID",
    "Status",
]
EXTENDED_STUDENT_COLUMNS = [
    "Otasi_FIO",
    "Otasi_Tel",
    "Otasi_Chat_ID",
    "Onasi_FIO",
    "Onasi_Tel",
    "Onasi_Chat_ID",
]

CHANGE_LANG_BUTTON_TEXTS = button_texts("btn_change_lang")
SWITCH_ROLE_BUTTON_TEXTS = button_texts(
    "btn_switch_to_parent", "btn_switch_to_student"
)
# Main admin only: "🔄 Rolni almashtirish" (Admin / Ustoz / Talaba / Ota-ona).
MAIN_ROLE_SWITCH_TEXTS = button_texts("btn_role_switch")
# Current labels plus the legacy ones, so old reply keyboards keep working.
PROFILE_MENU_TEXTS = button_texts("menu_profile")
CANCEL_TEXTS = {t("btn_cancel", "latn"), t("btn_cancel", "cyrl")}
BACK_TEXTS = {t("btn_back", "latn"), t("btn_back", "cyrl")}

OFFICIAL_SIGNATURE: dict[str, str] = {
    "latn": "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!",
    "cyrl": "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!",
}

LOCAL_TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "admin_link_invalid": "❌ Ushbu admin taklif havolasi yaroqsiz yoki allaqachon ishlatilgan.",
        "admin_self_reg_enter_name": (
            "👑 <b>Admin sifatida ro‘yxatdan o‘tish</b>\n\n"
            "Iltimos, to‘liq <b>Familiya Ismingizni</b> kiriting (masalan: <i>Aliyev Vali</i>):"
        ),
        "admin_self_reg_invalid_name": (
            "❌ Iltimos, to‘liq Familiya va Ismingizni kamida 2 ta so‘z bilan kiriting "
            "(masalan: <i>Aliyev Vali</i>):"
        ),
        "admin_self_reg_share_phone": (
            "👤 Rahmat, <b>{full_name}</b>!\n\n"
            "Endi pastdagi tugma orqali telefon raqamingizni yuboring:"
        ),
        "admin_link_success": (
            "✅ Tabriklaymiz, <b>{admin_name}</b>!\n"
            "Siz muvaffaqiyatli <b>Admin</b> sifatida ro‘yxatdan o‘tdingiz."
        ),
        "admin_invite_used_notify": (
            "✅ Yangi admin <b>{admin_name}</b> ({phone}) taklif havolangiz orqali ro‘yxatdan o‘tdi."
        ),
        "open_invite_link_btn": "🔗 Havolani ochish",
        "parbatch_invalid": (
            "❌ Kechirasiz, ushbu ota-ona taklif havolasi yaroqsiz yoki allaqachon ishlatilgan."
        ),
        "parbatch_success": (
            "✅ Assalomu alaykum, <b>{parent_name}</b>!\n"
            "Sizning Telegram hisobingiz quyidagi farzand(lar)ingizga muvaffaqiyatli bog‘landi:\n\n"
            "{children_lines}"
        ),
        "parent_multi_added": (
            "✅ Assalomu alaykum, <b>{parent_name}</b>!\n"
            "Farzandingiz <b>{student_name}</b> (<b>{group}</b>) ham hisobingizga muvaffaqiyatli bog‘landi.\n\n"
            "<b>Jami bog‘langan farzandlaringiz:</b>\n{children_lines}"
        ),
        "dual_role_approved_both_admin": (
            "✅ Foydalanuvchi <b>{full_name}</b> (<code>{user_id}</code>) uchun "
            "ikkala rol (<b>{old_role}</b> + <b>{new_role}</b>) ham saqlandi."
        ),
        "dual_role_approved_replace_admin": (
            "✅ Foydalanuvchi <b>{full_name}</b> (<code>{user_id}</code>) faqat "
            "yangi <b>{new_role}</b> roliga o‘tkazildi."
        ),
        "dual_role_approved_both_user": (
            "✅ Admin so‘rovingizni tasdiqladi! Sizga <b>{new_role}</b> roli ham qo‘shildi.\n"
            "Pastdagi tugma orqali rejimlar o‘rtasida almashishingiz mumkin."
        ),
        "dual_role_approved_replace_user": (
            "✅ Admin sizni <b>{new_role}</b> roliga o‘tkazdi."
        ),
        "rate_limit_busy": (
            "⏳ Tizim hozir juda band (Google Sheets so‘rovlari vaqtincha cheklangan).\n\n"
            "Iltimos, 15–20 soniya kutib, /start tugmasini qayta bosing."
        ),
    },
    "cyrl": {
        "admin_link_invalid": "❌ Ушбу админ таклиф ҳаволаси яроқсиз ёки аллақачон ишлатилган.",
        "admin_self_reg_enter_name": (
            "👑 <b>Админ сифатида рўйхатдан ўтиш</b>\n\n"
            "Илтимос, тўлиқ <b>Фамилия Исмингизни</b> киритинг (масалан: <i>Алиев Вали</i>):"
        ),
        "admin_self_reg_invalid_name": (
            "❌ Илтимос, тўлиқ Фамилия ва Исмингизни камида 2 та сўз билан киритинг "
            "(масалан: <i>Алиев Вали</i>):"
        ),
        "admin_self_reg_share_phone": (
            "👤 Раҳмат, <b>{full_name}</b>!\n\n"
            "Энди пастдаги тугма орқали телефон рақамингизни юборинг:"
        ),
        "admin_link_success": (
            "✅ Табриклаймиз, <b>{admin_name}</b>!\n"
            "Сиз муваффақиятли <b>Админ</b> сифатида рўйхатдан ўтдингиз."
        ),
        "admin_invite_used_notify": (
            "✅ Янги админ <b>{admin_name}</b> ({phone}) таклиф ҳаволангиз орқали рўйхатдан ўтди."
        ),
        "open_invite_link_btn": "🔗 Ҳаволани очиш",
        "parbatch_invalid": (
            "❌ Кечирасиз, ушбу ота-она таклиф ҳаволаси яроқсиз ёки аллақачон ишлатилган."
        ),
        "parbatch_success": (
            "✅ Ассалому алайкум, <b>{parent_name}</b>!\n"
            "Сизнинг Telegram ҳисобингиз қуйидаги фарзанд(лар)ингизга муваффақиятли боғланди:\n\n"
            "{children_lines}"
        ),
        "parent_multi_added": (
            "✅ Ассалому алайкум, <b>{parent_name}</b>!\n"
            "Фарзандингиз <b>{student_name}</b> (<b>{group}</b>) ҳам ҳисобингизга муваффақиятли боғланди.\n\n"
            "<b>Жами боғланган фарзандларингиз:</b>\n{children_lines}"
        ),
        "dual_role_approved_both_admin": (
            "✅ Фойдаланувчи <b>{full_name}</b> (<code>{user_id}</code>) учун "
            "иккала рол (<b>{old_role}</b> + <b>{new_role}</b>) ҳам сақланди."
        ),
        "dual_role_approved_replace_admin": (
            "✅ Фойдаланувчи <b>{full_name}</b> (<code>{user_id}</code>) фақат "
            "янги <b>{new_role}</b> ролга ўтказилди."
        ),
        "dual_role_approved_both_user": (
            "✅ Админ сўровингизни тасдиқлади! Сизга <b>{new_role}</b> роли ҳам қўшилди.\n"
            "Пастдаги тугма орқали режимлар ўртасида алмашишингиз мумкин."
        ),
        "dual_role_approved_replace_user": (
            "✅ Админ сизни <b>{new_role}</b> ролга ўтказди."
        ),
        "rate_limit_busy": (
            "⏳ Тизим ҳозир жуда банд (Google Sheets сўровлари вақтинча чекланган).\n\n"
            "Илтимос, 15–20 сония кутиб, /start тугмасини қайта босинг."
        ),
    },
}


def _lt(key: str, lang: str = "latn", **kwargs: Any) -> str:
    safe_lang = lang if lang in LOCAL_TEXTS else "latn"
    template = LOCAL_TEXTS[safe_lang].get(key) or LOCAL_TEXTS["latn"].get(key, key)
    return template.format(**kwargs) if kwargs else template


def _with_signature(text: str, lang: str = "latn") -> str:
    safe_lang = lang if lang in OFFICIAL_SIGNATURE else "latn"
    sig = OFFICIAL_SIGNATURE[safe_lang]
    if sig in text:
        return text
    return f"{text}\n\n<i>{sig}</i>"


def _is_rate_limit_error(exc: Exception) -> bool:
    if isinstance(exc, gspread.exceptions.APIError):
        resp = getattr(exc, "response", None)
        if getattr(resp, "status_code", None) == 429:
            return True
    msg = str(exc).lower()
    return "429" in msg or "quota exceeded" in msg or "rate limit" in msg


async def _ensure_aux_tables() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS teacher_meta (
                invite_code TEXT PRIMARY KEY,
                telegram_id INTEGER,
                phone TEXT,
                username TEXT,
                linked_group_name TEXT,
                invited_by INTEGER
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS parent_meta (
                telegram_id INTEGER PRIMARY KEY,
                student_id TEXT NOT NULL,
                parent_type TEXT NOT NULL,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_invites (
                invite_code TEXT PRIMARY KEY,
                created_by INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                used_by INTEGER,
                created_at TEXT NOT NULL
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS dynamic_admins (
                telegram_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                phone TEXT,
                username TEXT,
                invite_code TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        await db.commit()


async def _get_unused_admin_invite(invite_code: str) -> Optional[dict[str, Any]]:
    await _ensure_aux_tables()
    code = invite_code.strip()
    if not code:
        return None

    for fn_name in ("get_admin_invite", "get_admin_by_invite_code"):
        db_fn = getattr(database, fn_name, None)
        if callable(db_fn):
            try:
                inv = await db_fn(code)
                if inv:
                    status = str(inv.get("status", "pending")).strip().lower()
                    used_by = inv.get("used_by") or inv.get("telegram_id")
                    is_used = inv.get("is_used")
                    if is_used or status != "pending" or used_by:
                        return None
                    return dict(inv)
            except Exception:
                pass

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            async with db.execute(
                "SELECT * FROM admin_invites WHERE invite_code = ?;",
                (code,),
            ) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                rec = dict(row)
                if rec.get("status") != "pending" or rec.get("used_by"):
                    return None
                return rec
        except Exception:
            return None


async def _activate_admin_invite_and_register(
    invite_code: str,
    telegram_id: int,
    full_name: str,
    phone: str,
    username: Optional[str],
    lang: str,
) -> tuple[bool, Optional[int]]:
    await _ensure_aux_tables()
    code = invite_code.strip()
    now_iso = now_tashkent().isoformat()
    created_by: Optional[int] = None

    for fn_name in ("activate_admin_invite", "use_admin_invite"):
        db_fn = getattr(database, fn_name, None)
        if callable(db_fn):
            try:
                sig = inspect.signature(db_fn)
                if len(sig.parameters) >= 2:
                    ok = await db_fn(code, telegram_id)
                else:
                    ok = await db_fn(code)
                if ok is False or ok is None:
                    pass
                elif isinstance(ok, dict) and ok.get("created_by"):
                    created_by = int(ok["created_by"])
            except Exception:
                pass

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        try:
            async with db.execute(
                "SELECT * FROM admin_invites WHERE invite_code = ?;",
                (code,),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    if row["status"] != "pending" or row["used_by"]:
                        return False, None
                    created_by = row["created_by"]
                    upd = await db.execute(
                        """
                        UPDATE admin_invites
                        SET status = 'used', used_by = ?
                        WHERE invite_code = ? AND status = 'pending';
                        """,
                        (telegram_id, code),
                    )
                    if upd.rowcount == 0:
                        return False, None
        except Exception:
            pass

        try:
            await db.execute(
                """
                INSERT INTO dynamic_admins (
                    telegram_id, full_name, phone, username, invite_code, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    full_name = excluded.full_name,
                    phone = excluded.phone,
                    username = excluded.username,
                    invite_code = excluded.invite_code;
                """,
                (telegram_id, full_name.strip(), phone.strip(), username, code, now_iso),
            )
            await db.commit()
        except Exception:
            pass

    for fn_name in ("add_dynamic_admin", "register_dynamic_admin", "upsert_dynamic_admin"):
        db_fn = getattr(database, fn_name, None)
        if callable(db_fn):
            try:
                sig = inspect.signature(db_fn)
                params = list(sig.parameters.keys())
                if len(params) >= 4:
                    await db_fn(telegram_id, full_name.strip(), phone.strip(), None)
                elif len(params) == 3:
                    await db_fn(telegram_id, full_name.strip(), phone.strip())
                elif len(params) == 2:
                    await db_fn(telegram_id, full_name.strip())
            except Exception:
                pass
            break

    await upsert_user(
        telegram_id=telegram_id,
        role="admin",
        full_name=full_name.strip(),
        lang=lang,
    )
    return True, int(created_by) if created_by else None


async def _get_dynamic_admin(telegram_id: int) -> Optional[dict[str, Any]]:
    await _ensure_aux_tables()
    db_fn = getattr(database, "get_dynamic_admin", None)
    if callable(db_fn):
        try:
            res = await db_fn(telegram_id)
            if res:
                return dict(res) if not isinstance(res, dict) else res
        except Exception:
            pass
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM dynamic_admins WHERE telegram_id = ?;",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
    db_user = await get_user(telegram_id)
    if db_user and db_user.get("role") == "admin":
        return {"telegram_id": telegram_id, "full_name": db_user.get("full_name")}
    return None


async def _get_teacher_meta_by_invite(invite_code: str) -> Optional[dict[str, Any]]:
    await _ensure_aux_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM teacher_meta WHERE invite_code = ?;",
            (invite_code.strip(),),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _get_teacher_meta_by_tg(telegram_id: int) -> Optional[dict[str, Any]]:
    await _ensure_aux_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM teacher_meta WHERE telegram_id = ? ORDER BY rowid DESC LIMIT 1;",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _upsert_teacher_meta(
    invite_code: str,
    telegram_id: Optional[int] = None,
    phone: Optional[str] = None,
    username: Optional[str] = None,
    linked_group_name: Optional[str] = None,
    invited_by: Optional[int] = None,
) -> None:
    existing = await _get_teacher_meta_by_invite(invite_code)
    new_tg = (
        telegram_id
        if telegram_id is not None
        else (existing["telegram_id"] if existing else None)
    )
    new_phone = phone if phone is not None else (existing["phone"] if existing else None)
    new_username = (
        username if username is not None else (existing["username"] if existing else None)
    )
    new_group = (
        linked_group_name
        if linked_group_name is not None
        else (existing["linked_group_name"] if existing else None)
    )
    new_inviter = (
        invited_by
        if invited_by is not None
        else (existing["invited_by"] if existing else None)
    )

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO teacher_meta (
                invite_code, telegram_id, phone, username, linked_group_name, invited_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(invite_code) DO UPDATE SET
                telegram_id = excluded.telegram_id,
                phone = excluded.phone,
                username = excluded.username,
                linked_group_name = excluded.linked_group_name,
                invited_by = excluded.invited_by;
            """,
            (invite_code.strip(), new_tg, new_phone, new_username, new_group, new_inviter),
        )
        await db.commit()


async def _update_teacher_sqlite_details(
    invite_code: str,
    telegram_id: int,
    full_name: str,
    phone: Optional[str] = None,
    username: Optional[str] = None,
) -> None:
    await _ensure_aux_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE teachers SET full_name = ?, telegram_id = ?, status = 'active' WHERE invite_code = ?;",
            (full_name.strip(), telegram_id, invite_code.strip()),
        )
        await db.commit()
    await _upsert_teacher_meta(
        invite_code=invite_code,
        telegram_id=telegram_id,
        phone=phone,
        username=username,
    )


async def _notify_admins_teacher_registered(
    bot: Any,
    teacher_user_id: int,
    full_name: str,
    phone: str,
    assigned_group: Optional[str],
    invited_by: Optional[int] = None,
) -> None:
    recipients: list[int] = []
    if invited_by and invited_by != teacher_user_id:
        recipients.append(int(invited_by))
    for admin_id in ADMIN_IDS:
        if admin_id != teacher_user_id and admin_id not in recipients:
            recipients.append(admin_id)

    for adm_id in recipients:
        adm_lang = await get_user_lang(adm_id)
        if assigned_group:
            notif = (
                f"✅ Ustoz <b>{html.escape(full_name)}</b> ({html.escape(phone or '—')}) "
                f"ro‘yxatdan o‘tdi va avtomatik ravishda <b>{html.escape(assigned_group)}</b> "
                f"guruhiga biriktirildi."
                if adm_lang == "latn"
                else f"✅ Устоз <b>{html.escape(full_name)}</b> ({html.escape(phone or '—')}) "
                f"рўйхатдан ўтди ва автоматик равишда <b>{html.escape(assigned_group)}</b> "
                f"гуруҳига бириктирилди."
            )
        else:
            notif = (
                f"✅ Yangi ustoz <b>{html.escape(full_name)}</b> ({html.escape(phone or '—')}) "
                f"tizimda ro‘yxatdan o‘tdi."
                if adm_lang == "latn"
                else f"✅ Янги устоз <b>{html.escape(full_name)}</b> ({html.escape(phone or '—')}) "
                f"тизимда рўйхатдан ўтди."
            )
        try:
            await bot.send_message(chat_id=adm_id, text=notif, parse_mode="HTML")
        except Exception:
            pass


async def _save_parent_meta(
    telegram_id: int,
    student_id: str,
    parent_type: str,
    full_name: str,
    phone: str,
) -> None:
    await _ensure_aux_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO parent_meta (telegram_id, student_id, parent_type, full_name, phone)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                student_id = excluded.student_id,
                parent_type = excluded.parent_type,
                full_name = excluded.full_name,
                phone = excluded.phone;
            """,
            (telegram_id, student_id.strip(), parent_type, full_name.strip(), phone.strip()),
        )
        await db.commit()


async def _get_parent_meta(telegram_id: int) -> Optional[dict[str, Any]]:
    await _ensure_aux_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM parent_meta WHERE telegram_id = ?;", (telegram_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


def _ensure_extended_student_headers_sync(sheets: SheetsManager) -> gspread.Worksheet:
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
            ss = sheets._get_spreadsheet()
            ss.batch_update(
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
        return ws


def _sync_save_parent_to_sheet(
    sheets: SheetsManager,
    student_id: str,
    parent_type: str,
    full_name: str,
    phone: str,
    chat_id: int,
) -> bool:
    with sheets._lock:
        _ensure_extended_student_headers_sync(sheets)
        student = sheets.get_student_by_id(student_id)
        if not student:
            return False
        updates: dict[str, Any] = {}
        prefix = "Otasi" if parent_type == "father" else "Onasi"
        updates[f"{prefix}_FIO"] = (full_name or "").strip()
        if phone and phone.strip():
            updates[f"{prefix}_Tel"] = phone.strip()
        updates[f"{prefix}_Chat_ID"] = str(chat_id)
        existing_main_tel = str(student.get("OtaOna_Tel") or "").strip()
        if (
            not existing_main_tel
            or existing_main_tel.lower() in {"yo'q", "yoq", "-"}
        ) and phone and phone.strip():
            updates["OtaOna_Tel"] = phone.strip()
        if not str(student.get("OtaOna_Chat_ID") or "").strip():
            updates["OtaOna_Chat_ID"] = str(chat_id)
        return sheets.update_student(student_id, updates)


async def _bind_parent_to_students(
    sheets_mgr: SheetsManager,
    student_ids: list[str],
    parent_type: str,
    full_name: str,
    phone: str,
    chat_id: int,
) -> list[str]:
    clean_ids = [str(s).strip() for s in student_ids if str(s).strip()]
    if not clean_ids:
        return []

    bind_sync = getattr(sheets_mgr, "bind_parent_to_students", None)
    if callable(bind_sync):
        res = await asyncio.to_thread(
            bind_sync,
            clean_ids,
            chat_id,
            parent_type,
            full_name,
            phone,
        )
        if isinstance(res, list):
            return [str(s).strip() for s in res if str(s).strip()]
        if res:
            return clean_ids
        return []

    bind_async = getattr(sheets_mgr, "a_bind_parent_to_students", None)
    if callable(bind_async):
        res = await bind_async(
            student_ids=clean_ids,
            parent_chat_id=chat_id,
            parent_type=parent_type,
            parent_name=full_name,
            parent_phone=phone,
        )
        if isinstance(res, list):
            return [str(s).strip() for s in res if str(s).strip()]
        if res:
            return clean_ids
        return []

    valid_sids: list[str] = []
    for clean_sid in clean_ids:
        ok = await asyncio.to_thread(
            _sync_save_parent_to_sheet,
            sheets_mgr,
            clean_sid,
            parent_type,
            full_name,
            phone,
            chat_id,
        )
        if ok:
            valid_sids.append(clean_sid)
    return valid_sids


async def _attach_student_device_info(
    sheets_mgr: SheetsManager,
    student_id: str,
    chat_id: int,
    phone: str = "",
    username: Optional[str] = None,
    full_name: Optional[str] = None,
) -> bool:
    attach_fn = getattr(sheets_mgr, "a_attach_student_device_info", None) or getattr(
        sheets_mgr, "attach_student_device_info", None
    )
    if callable(attach_fn):
        try:
            if inspect.iscoroutinefunction(attach_fn):
                res = await attach_fn(
                    student_id=student_id,
                    chat_id=chat_id,
                    phone=phone,
                    username=username,
                    full_name=full_name,
                )
            else:
                res = await asyncio.to_thread(
                    attach_fn,
                    student_id,
                    chat_id,
                    phone,
                    username,
                    full_name,
                )
            if res:
                return True
        except Exception:
            logger.exception(
                "attach_student_device_info failed; falling back to update_student"
            )

    updates: dict[str, Any] = {"Talaba_Chat_ID": str(chat_id)}
    if full_name and full_name.strip():
        updates["F.I.O."] = full_name.strip()
    if phone and phone.strip():
        updates["Talaba_Tel"] = phone.strip()
    if username and username.strip():
        clean_u = username.strip()
        updates["Talaba_TG"] = clean_u if clean_u.startswith("@") else f"@{clean_u}"
    return await asyncio.to_thread(sheets_mgr.update_student, student_id, updates)


def _sync_update_parent_profile_in_sheet(
    sheets: SheetsManager,
    student_id: str,
    parent_type: str,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
    chat_id: Optional[int] = None,
) -> bool:
    with sheets._lock:
        _ensure_extended_student_headers_sync(sheets)
        student = sheets.get_student_by_id(student_id)
        if not student:
            return False
        updates: dict[str, Any] = {}
        prefix = "Otasi" if parent_type == "father" else "Onasi"
        if full_name is not None:
            updates[f"{prefix}_FIO"] = full_name.strip()
        if phone is not None:
            updates[f"{prefix}_Tel"] = phone.strip()
            cur_id = str(student.get("OtaOna_Chat_ID") or "").strip()
            if not cur_id or (chat_id is not None and cur_id == str(chat_id)):
                updates["OtaOna_Tel"] = phone.strip()
        return sheets.update_student(student_id, updates) if updates else True


def _sync_update_student_name_in_active_cycles(
    sheets: SheetsManager, group_name: str, student_id: str, new_full_name: str
) -> None:
    if not group_name:
        return
    with sheets._lock:
        ss = sheets._get_spreadsheet()
        now_year = now_tashkent().year
        for y in (now_year, now_year - 1):
            try:
                ws = sheets._open_group_year_ws(ss, group_name, y)
            except gspread.WorksheetNotFound:
                continue
            updates = [
                {
                    "range": f"B{s_row['row_idx'] + 1}",
                    "values": [[new_full_name.strip()]],
                }
                for cycle in sheets.parse_cycles_from_sheet(ws)
                for s_row in cycle["student_rows"]
                if s_row["student_id"].strip() == student_id.strip()
            ]
            if updates:
                ws.batch_update(updates, value_input_option="USER_ENTERED")


def _sync_upsert_teacher_sheet(
    sheets: SheetsManager,
    invite_code: str,
    full_name: str,
    phone: str,
    tg_username: Optional[str],
    chat_id: int,
    assigned_group: Optional[str] = None,
) -> dict[str, Any]:
    with sheets._lock:
        ws = sheets._get_or_create_worksheet(
            TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=200, cols=10
        )
        headers = sheets._cleanup_teacher_sheet_headers(ws)
        rows = ws.get_all_values()
        tg_display = f"@{tg_username.lstrip('@')}" if tg_username else "-"

        teacher_groups = [
            g.get("Guruh_Nomi", "").strip()
            for g in sheets.get_teacher_groups(chat_id)
            if g.get("Guruh_Nomi", "").strip()
        ]
        if assigned_group and assigned_group.strip() not in teacher_groups:
            teacher_groups.append(assigned_group.strip())
        groups_str = ", ".join(teacher_groups)

        target_row_num: Optional[int] = None
        existing_uid = ""
        for idx, raw_row in enumerate(rows[1:], start=2):
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            rec = dict(zip(headers, padded))
            row_uid = rec.get("Ustoz_ID", "").strip()
            row_cid = rec.get("Chat_ID", "").strip()
            if (invite_code and row_uid == invite_code.strip()) or (
                row_cid and row_cid == str(chat_id)
            ):
                target_row_num = idx
                existing_uid = row_uid
                if not groups_str and rec.get("Guruhlar", "").strip():
                    prev_g = rec.get("Guruhlar", "").strip()
                    if prev_g != "Ma'lumot kiritilmagan":
                        groups_str = prev_g
                break

        row_id = existing_uid or invite_code.strip() or f"TCH{chat_id}"
        row_map = {
            "Ustoz_ID": row_id,
            "F.I.O.": full_name.strip(),
            "Telefon": phone.strip(),
            "TG_Username": tg_display,
            "Chat_ID": str(chat_id),
            "Guruhlar": groups_str,
            "Status": "Faol",
        }
        row_values = [row_map.get(h, "") for h in headers]

        if target_row_num is not None:
            sheets._sync_row_missing_cells(
                ws, target_row_num, row_values, exclude_cols={"Guruhlar"}
            )
        else:
            new_row_idx = sheets._append_row_and_get_index(ws, row_values)
            sheets._sync_row_missing_cells(
                ws, new_row_idx, row_values, exclude_cols={"Guruhlar"}
            )
        return {
            "teacher_id": row_id,
            "full_name": full_name.strip(),
            "phone": phone.strip(),
            "tg": tg_display,
        }


def _sync_get_teacher_sheet_record(
    sheets: SheetsManager, chat_id: int
) -> Optional[dict[str, str]]:
    with sheets._lock:
        ws = sheets._get_or_create_worksheet(
            TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=200, cols=10
        )
        rows = ws.get_all_values()
        if len(rows) <= 1:
            return None
        headers = rows[0]
        for idx, raw_row in enumerate(rows[1:], start=2):
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            rec = dict(zip(headers, padded))
            if _chat_id_str(rec.get("Chat_ID", "")) == _chat_id_str(chat_id):
                rec["_row_number"] = str(idx)
                return rec
        return None


def _sync_update_teacher_sheet_fields(
    sheets: SheetsManager,
    chat_id: int,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
) -> bool:
    with sheets._lock:
        ws = sheets._get_or_create_worksheet(
            TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=200, cols=10
        )
        rows = ws.get_all_values()
        if len(rows) <= 1:
            return False
        headers = rows[0]
        for idx, raw_row in enumerate(rows[1:], start=2):
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            rec = dict(zip(headers, padded))
            if _chat_id_str(rec.get("Chat_ID", "")) == _chat_id_str(chat_id):
                batch: list[dict[str, Any]] = []
                if full_name is not None and "F.I.O." in headers:
                    batch.append(
                        {
                            "range": f"{_col_letter(headers.index('F.I.O.'))}{idx}",
                            "values": [[full_name.strip()]],
                        }
                    )
                if phone is not None and "Telefon" in headers:
                    batch.append(
                        {
                            "range": f"{_col_letter(headers.index('Telefon'))}{idx}",
                            "values": [[phone.strip()]],
                        }
                    )
                if batch:
                    ws.batch_update(batch, value_input_option="USER_ENTERED")
                return True
        return False


def _sync_find_student_by_any_chat_id(
    sheets: SheetsManager, chat_id: int
) -> Optional[tuple[dict[str, Any], str, Optional[str]]]:
    with sheets._lock:
        _ensure_extended_student_headers_sync(sheets)
        target = str(chat_id).strip()
        for student in sheets.get_all_students():
            if str(student.get("Talaba_Chat_ID") or "").strip() == target:
                return student, "student", None
            if str(student.get("Otasi_Chat_ID") or "").strip() == target:
                return student, "parent", "father"
            if str(student.get("Onasi_Chat_ID") or "").strip() == target:
                return student, "parent", "mother"
            if str(student.get("OtaOna_Chat_ID") or "").strip() == target:
                return student, "parent", "father"
        return None


def _sync_clear_user_student_or_parent_chat_ids(
    sheets: SheetsManager, target_user_id: int
) -> None:
    target = str(target_user_id).strip()
    if not target:
        return
    with sheets._lock:
        for student in sheets.get_all_students():
            sid = str(student.get("Talaba_ID") or "").strip()
            if not sid:
                continue
            updates: dict[str, Any] = {}
            for col in (
                "Talaba_Chat_ID",
                "Otasi_Chat_ID",
                "Onasi_Chat_ID",
                "OtaOna_Chat_ID",
            ):
                if str(student.get(col) or "").strip() == target:
                    updates[col] = ""
            if updates:
                sheets.update_student(sid, updates)


def _sync_clear_student_chat_id(
    sheets: SheetsManager, target_user_id: int
) -> None:
    target = str(target_user_id).strip()
    if not target:
        return
    with sheets._lock:
        for student in sheets.get_all_students():
            sid = str(student.get("Talaba_ID") or "").strip()
            if not sid:
                continue
            if str(student.get("Talaba_Chat_ID") or "").strip() == target:
                sheets.update_student(sid, {"Talaba_Chat_ID": ""})


def _sync_clear_parent_chat_ids(
    sheets: SheetsManager, target_user_id: int
) -> None:
    target = str(target_user_id).strip()
    if not target:
        return
    with sheets._lock:
        for student in sheets.get_all_students():
            sid = str(student.get("Talaba_ID") or "").strip()
            if not sid:
                continue
            updates: dict[str, Any] = {}
            for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
                if str(student.get(col) or "").strip() == target:
                    updates[col] = ""
            if updates:
                sheets.update_student(sid, updates)


def _extract_user_phone_from_sheets_sync(
    sheets: SheetsManager, user_id: int, role: str
) -> str:
    target = str(user_id).strip()
    with sheets._lock:
        for s in sheets.get_all_students():
            if role == "student" and str(s.get("Talaba_Chat_ID") or "").strip() == target:
                tel = str(s.get("Talaba_Tel") or "").strip()
                if tel and tel.lower() not in {"yo'q", "yoq", "-"}:
                    return tel
            if role == "parent":
                if str(s.get("Otasi_Chat_ID") or "").strip() == target:
                    tel = (
                        str(s.get("Otasi_Tel") or "").strip()
                        or str(s.get("OtaOna_Tel") or "").strip()
                    )
                    if tel and tel.lower() not in {"yo'q", "yoq", "-"}:
                        return tel
                if str(s.get("Onasi_Chat_ID") or "").strip() == target:
                    tel = (
                        str(s.get("Onasi_Tel") or "").strip()
                        or str(s.get("OtaOna_Tel") or "").strip()
                    )
                    if tel and tel.lower() not in {"yo'q", "yoq", "-"}:
                        return tel
                if str(s.get("OtaOna_Chat_ID") or "").strip() == target:
                    tel = str(s.get("OtaOna_Tel") or "").strip()
                    if tel and tel.lower() not in {"yo'q", "yoq", "-"}:
                        return tel
    return ""


def _slugify_group_name(group_name: str) -> str:
    return make_group_join_slug(group_name)


def _find_group_by_join_slug(
    sheets: SheetsManager, slug: str
) -> Optional[dict[str, Any]]:
    clean_slug = slug.strip().lower()
    all_groups = sheets.get_all_groups()
    for grp in all_groups:
        if grp.get("Guruh_Nomi", "").strip().lower() == clean_slug:
            return grp
    # Current collision-safe slug first, then the legacy slug of old links.
    for grp in all_groups:
        if make_group_join_slug(grp.get("Guruh_Nomi", "")).lower() == clean_slug:
            return grp
    for grp in all_groups:
        if legacy_group_join_slug(grp.get("Guruh_Nomi", "")).lower() == clean_slug:
            return grp
    return None


def _append_student_to_active_cycle(
    sheets: SheetsManager, group_name: str, student_id: str, full_name: str
) -> Optional[str]:
    """
    Adds a NEWLY created student to the group's active {Group}_{Year} cycle with
    the unpaid red (#F4CCCC) "To'lanmagan" row and charges the current month
    upfront from Lesson 1 (Qarzdor_Oylar = 1 month). Returns the cycle title.
    """
    with sheets._lock:
        added = sheets.add_student_to_active_cycle(
            group_name, student_id, full_name, charge_upfront=True
        )
        if not added:
            return None
        try:
            return sheets.get_active_cycle_title(group_name) or None
        except Exception:
            logger.exception("Could not resolve active cycle title for %s", group_name)
            return None


def build_language_keyboard(mode: str = "init") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_lang_latn", "latn"),
                    callback_data=f"set_lang:latn:{mode}",
                ),
                InlineKeyboardButton(
                    text=t("btn_lang_cyrl", "cyrl"),
                    callback_data=f"set_lang:cyrl:{mode}",
                ),
            ]
        ]
    )


def build_main_menu(
    role: str, lang: str = "latn", has_dual_role: bool = False
) -> Any:
    if role in {"admin", "teacher", "student", "parent"}:
        return get_main_menu_kb(role, lang, has_dual_role=has_dual_role)
    return ReplyKeyboardRemove()


def _validate_full_name(raw_name: str) -> Optional[str]:
    cleaned = " ".join((raw_name or "").strip().split())
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


def _normalize_phone(raw_phone: str) -> str:
    compact = re.sub(r"[^\d+]", "", raw_phone.strip())
    if compact and not compact.startswith("+"):
        compact = f"+{compact}"
    return compact or raw_phone.strip()


async def _resolve_parent_type(user_id: int, sheets_mgr: SheetsManager) -> str:
    """
    'father' / 'mother' for a registered parent. The Baza_Talabalar columns
    (Otasi_Chat_ID / Onasi_Chat_ID) are the source of truth; parent_meta is the
    fallback; default is 'father'.
    """
    cid = str(user_id)
    try:
        children = await sheets_mgr.a_get_children_by_parent_chat_id(user_id)
    except Exception:
        children = []
    for child in children:
        if str(child.get("Onasi_Chat_ID") or "").strip() == cid:
            return "mother"
        if str(child.get("Otasi_Chat_ID") or "").strip() == cid:
            return "father"
    meta = await _get_parent_meta(user_id)
    if meta and str(meta.get("parent_type") or "") in {"father", "mother"}:
        return str(meta["parent_type"])
    return "father"


async def _welcome_menu_text(
    user_id: int,
    name: str,
    role: str,
    lang: str,
    sheets_mgr: Optional[SheetsManager] = None,
) -> str:
    """
    Login greeting. Parents get their SPECIFIC role confirmation
    ("🧔 Siz Otasi sifatida tizimga kirdingiz!" / "🧕 Siz Onasi sifatida ...")
    instead of the generic "ota-ona".
    """
    if role == "parent":
        p_type = await _resolve_parent_type(user_id, sheets_mgr or get_sheets_manager())
        return t(
            "welcome_menu_mother" if p_type == "mother" else "welcome_menu_father",
            lang,
            name=html.escape(name),
        )
    return t(
        "welcome_menu",
        lang,
        name=html.escape(name),
        role=t(f"role_{role}", lang),
    )


async def _update_parent_meta_type(telegram_id: int, parent_type: str) -> None:
    await _ensure_aux_tables()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE parent_meta SET parent_type = ? WHERE telegram_id = ?;",
            (parent_type, int(telegram_id)),
        )
        await db.commit()


def _preset_parent_type_from_student(student: dict[str, Any]) -> Optional[str]:
    """
    'father' / 'mother' when the admin already recorded exactly one parent on the
    student's row (Otasi_* XOR Onasi_*) and that parent has not bound a chat yet.
    Returns None when it is ambiguous, so the parent must choose themselves.
    """

    def _filled(col: str) -> bool:
        raw = str(student.get(col) or "").strip()
        return bool(raw) and raw.lower() != "ma'lumot kiritilmagan"

    father_data = _filled("Otasi_FIO") or _filled("Otasi_Tel")
    mother_data = _filled("Onasi_FIO") or _filled("Onasi_Tel")
    if father_data and not mother_data and not _filled("Otasi_Chat_ID"):
        return "father"
    if mother_data and not father_data and not _filled("Onasi_Chat_ID"):
        return "mother"
    return None


async def _get_existing_parent_profile(
    user_id: int, sheets: SheetsManager
) -> Optional[dict[str, str]]:
    p_meta = await _get_parent_meta(user_id)
    if p_meta and p_meta.get("full_name") and p_meta.get("phone"):
        return {
            "parent_type": str(p_meta.get("parent_type") or "father"),
            "full_name": str(p_meta["full_name"]).strip(),
            "phone": str(p_meta["phone"]).strip(),
        }
    children = await sheets.a_get_children_by_parent_chat_id(user_id)
    if children:
        first = children[0]
        cid_str = str(user_id)
        if str(first.get("Onasi_Chat_ID") or "").strip() == cid_str:
            p_type = "mother"
            p_name = str(first.get("Onasi_FIO") or "").strip()
            p_phone = str(first.get("Onasi_Tel") or "").strip()
        else:
            p_type = "father"
            p_name = str(first.get("Otasi_FIO") or "").strip()
            p_phone = (
                str(first.get("Otasi_Tel") or "").strip()
                or str(first.get("OtaOna_Tel") or "").strip()
            )
        if p_name and p_phone:
            return {
                "parent_type": p_type,
                "full_name": p_name,
                "phone": p_phone,
            }
    return None


async def _get_all_admin_ids() -> list[int]:
    admin_ids: list[int] = list(ADMIN_IDS)
    try:
        for dyn in await get_all_dynamic_admins():
            tid = int(dyn["telegram_id"])
            if tid not in admin_ids:
                admin_ids.append(tid)
    except Exception:
        pass
    return admin_ids


async def _resolve_user_role(
    telegram_id: int,
    fallback_full_name: str,
    lang: str,
    sheets: SheetsManager,
) -> Optional[dict[str, str]]:
    if telegram_id in ADMIN_IDS:
        await upsert_user(
            telegram_id=telegram_id,
            role="admin",
            full_name=fallback_full_name,
            lang=lang,
        )
        return {"role": "admin", "full_name": fallback_full_name}

    dyn_adm = await _get_dynamic_admin(telegram_id)
    if dyn_adm:
        adm_name = dyn_adm.get("full_name") or fallback_full_name
        await upsert_user(
            telegram_id=telegram_id,
            role="admin",
            full_name=adm_name,
            lang=lang,
        )
        return {"role": "admin", "full_name": adm_name}

    db_teacher = await get_teacher_by_telegram_id(telegram_id)
    if db_teacher:
        official_name = db_teacher["full_name"]
        await upsert_user(
            telegram_id=telegram_id,
            role="teacher",
            full_name=official_name,
            lang=lang,
        )
        return {"role": "teacher", "full_name": official_name}

    if await sheets.a_is_teacher(telegram_id):
        db_user = await get_user(telegram_id)
        sheet_t = await asyncio.to_thread(
            _sync_get_teacher_sheet_record, sheets, telegram_id
        )
        teacher_name = (
            (sheet_t.get("F.I.O.") if sheet_t else None)
            or (db_user.get("full_name") if db_user else None)
            or fallback_full_name
        )
        await upsert_user(
            telegram_id=telegram_id,
            role="teacher",
            full_name=teacher_name,
            lang=lang,
        )
        return {"role": "teacher", "full_name": teacher_name}

    db_user = await get_user(telegram_id)
    if db_user:
        db_roles = list(db_user.get("roles") or [])
        if "student" in db_roles and "parent" in db_roles:
            active_role = db_user.get("active_role") or db_user.get("role") or "student"
            if active_role not in {"student", "parent"}:
                active_role = "student"
            display_name = ""
            if active_role == "student":
                stu_list = await sheets.a_get_students_by_chat_id(telegram_id)
                if stu_list:
                    display_name = (
                        str(stu_list[0].get("F.I.O.") or "").strip()
                        or str(stu_list[0].get("Talaba_ID") or "").strip()
                    )
            else:
                p_meta = await _get_parent_meta(telegram_id)
                if p_meta and p_meta.get("full_name"):
                    display_name = str(p_meta["full_name"]).strip()
                else:
                    children = await sheets.a_get_children_by_parent_chat_id(telegram_id)
                    if children:
                        cid_str = str(telegram_id)
                        first = children[0]
                        if str(first.get("Onasi_Chat_ID") or "").strip() == cid_str:
                            display_name = str(first.get("Onasi_FIO") or "").strip()
                        else:
                            display_name = str(first.get("Otasi_FIO") or "").strip()
            display_name = (
                display_name
                or db_user.get("full_name")
                or db_user.get("linked_student_id")
                or fallback_full_name
            )
            await upsert_user(
                telegram_id=telegram_id,
                role=active_role,
                full_name=display_name,
                lang=lang,
                roles=db_roles,
                active_role=active_role,
            )
            return {"role": active_role, "full_name": display_name}

    sheet_match = await asyncio.to_thread(
        _sync_find_student_by_any_chat_id, sheets, telegram_id
    )
    if sheet_match:
        student, detected_role, p_type = sheet_match
        if detected_role == "student":
            display_name = (
                str(student.get("F.I.O.") or "").strip()
                or str(student.get("Talaba_ID") or "").strip()
            )
        else:
            p_meta = await _get_parent_meta(telegram_id)
            display_name = (
                (p_meta.get("full_name") if p_meta else None)
                or (
                    str(student.get("Onasi_FIO") or "").strip()
                    if p_type == "mother"
                    else str(student.get("Otasi_FIO") or "").strip()
                )
                or (db_user.get("full_name") if db_user else None)
                or fallback_full_name
            )
        await upsert_user(
            telegram_id=telegram_id,
            role=detected_role,
            linked_student_id=student.get("Talaba_ID"),
            full_name=display_name,
            lang=lang,
        )
        return {"role": detected_role, "full_name": display_name}

    if db_user and db_user.get("role"):
        return {
            "role": db_user["role"],
            "full_name": db_user.get("full_name")
            or db_user.get("linked_student_id")
            or fallback_full_name,
        }
    return None


async def _send_welcome_or_unregistered(
    target_message: Message,
    user_id: int,
    fallback_full_name: str,
    lang: str,
    sheets_mgr: SheetsManager,
) -> None:
    resolved = await _resolve_user_role(
        user_id, fallback_full_name, lang, sheets_mgr
    )
    if resolved:
        role = resolved["role"]
        has_dual = await has_dual_student_parent_role(user_id)
        welcome_text = _with_signature(
            await _welcome_menu_text(
                user_id, resolved["full_name"], role, lang, sheets_mgr
            ),
            lang,
        )
        await target_message.answer(
            text=welcome_text,
            reply_markup=build_main_menu(role, lang, has_dual_role=has_dual),
            parse_mode="HTML",
        )
    else:
        # Brand-new user without an approved role → Guest menu (course catalog,
        # optional lead registration, address & contacts, language switch).
        await target_message.answer(
            text=_with_signature(
                t("guest_welcome", lang, name=html.escape(fallback_full_name or "")),
                lang,
            ),
            reply_markup=guest_menu_kb(lang),
            parse_mode="HTML",
        )


def _requested_role_from_deep_link(deep_link_arg: str) -> Optional[str]:
    if deep_link_arg.startswith("adm_"):
        return "admin"
    if deep_link_arg.startswith("tch_"):
        return "teacher"
    if deep_link_arg.startswith("stu_") or deep_link_arg.startswith("join_"):
        return "student"
    if (
        deep_link_arg.startswith("par_")
        or deep_link_arg.startswith("parent_")
        or deep_link_arg.startswith("parbatch_")
    ):
        return "parent"
    return None


async def _build_dual_role_invite_payload(
    deep_link_arg: str,
    user_id: int,
    lang: str,
    existing_role: str,
    existing_full_name: str,
    tg_username: Optional[str],
    sheets_mgr: SheetsManager,
    target_message: Message,
) -> tuple[bool, Optional[dict[str, Any]]]:
    """
    Validates the invite target and builds the structured invite_payload dict
    without modifying any roles or Google Sheets rows.
    Returns (is_valid_link, invite_payload_or_none).
    """
    existing_phone = await asyncio.to_thread(
        _extract_user_phone_from_sheets_sync, sheets_mgr, user_id, existing_role
    )
    if not existing_phone and existing_role == "parent":
        existing_p = await _get_existing_parent_profile(user_id, sheets_mgr)
        if existing_p:
            existing_phone = existing_p.get("phone", "")

    if deep_link_arg.startswith("par_") or deep_link_arg.startswith("parent_"):
        student_id = (
            deep_link_arg[7:].strip()
            if deep_link_arg.startswith("parent_")
            else deep_link_arg[4:].strip()
        )
        student = await sheets_mgr.a_get_student_by_id(student_id)
        if not student:
            await target_message.answer(
                t(
                    "link_student_not_found",
                    lang,
                    student_id=html.escape(student_id),
                ),
                parse_mode="HTML",
            )
            return False, None
        return True, {
            "kind": "par",
            "deep_link": deep_link_arg,
            "student_id": student_id,
            "student_name": str(student.get("F.I.O.") or "").strip() or student_id,
            "group_name": str(student.get("Guruh") or "").strip() or "-",
            "parent_type": _preset_parent_type_from_student(student) or "father",
            "full_name": existing_full_name,
            "phone": existing_phone,
        }

    if deep_link_arg.startswith("parbatch_"):
        invite_code = deep_link_arg[9:].strip()
        batch = await get_parent_batch_invite(invite_code)
        student_ids = list(batch.get("student_ids") or []) if batch else []
        if (
            not batch
            or not student_ids
            or (batch.get("is_used") and batch.get("used_by") != user_id)
        ):
            await target_message.answer(
                _lt("parbatch_invalid", lang), parse_mode="HTML"
            )
            return False, None
        return True, {
            "kind": "parbatch",
            "deep_link": deep_link_arg,
            "invite_code": invite_code,
            "student_ids": student_ids,
            "parent_type": (
                str(batch.get("parent_type") or "").strip()
                if str(batch.get("parent_type") or "").strip() in {"father", "mother"}
                else "father"
            ),
            "parent_name": str(batch.get("parent_name") or "").strip()
            or existing_full_name,
            "parent_phone": str(batch.get("parent_phone") or "").strip()
            or existing_phone,
        }

    if deep_link_arg.startswith("stu_"):
        student_id = deep_link_arg[4:].strip()
        student = await sheets_mgr.a_get_student_by_id(student_id)
        if not student:
            await target_message.answer(
                t(
                    "link_student_not_found",
                    lang,
                    student_id=html.escape(student_id),
                ),
                parse_mode="HTML",
            )
            return False, None
        s_tel = str(student.get("Talaba_Tel") or "").strip()
        return True, {
            "kind": "stu",
            "deep_link": deep_link_arg,
            "student_id": student_id,
            "group_name": str(student.get("Guruh") or "").strip() or "-",
            "student_sheet_name": str(student.get("F.I.O.") or "").strip(),
            "student_has_phone": bool(
                s_tel and s_tel.lower() not in {"yo'q", "yoq", "-"}
            ),
            "full_name": existing_full_name,
            "phone": existing_phone,
            "username": tg_username or "",
        }

    if deep_link_arg.startswith("join_"):
        slug = deep_link_arg[5:].strip()
        group = await asyncio.to_thread(_find_group_by_join_slug, sheets_mgr, slug)
        if not group:
            await target_message.answer(
                t("join_group_not_found", lang), parse_mode="HTML"
            )
            return False, None
        canonical_group = group["Guruh_Nomi"].strip()
        return True, {
            "kind": "join",
            "deep_link": deep_link_arg,
            "group_name": canonical_group,
            "full_name": existing_full_name,
            "phone": existing_phone,
            "username": tg_username or "",
        }

    return False, None


async def _send_dual_role_admin_request(
    target_message: Message,
    user_id: int,
    lang: str,
    full_name: str,
    existing_role: str,
    requested_role: str,
    invite_code: str,
    invite_payload: dict[str, Any],
) -> None:
    req_id = await create_role_conflict_request(
        chat_id=user_id,
        full_name=full_name,
        existing_role=existing_role,
        requested_role=requested_role,
        invite_payload=invite_payload,
        invite_code=invite_code,
    )

    await target_message.answer(
        _with_signature(t("role_change_request_sent", lang), lang),
        parse_mode="HTML",
    )

    for adm_id in await _get_all_admin_ids():
        if adm_id == user_id:
            continue
        adm_lang = await get_user_lang(adm_id)
        old_role_uz = t(f"role_{existing_role}", adm_lang)
        new_role_uz = t(f"role_{requested_role}", adm_lang)
        prompt_text = t(
            "dual_role_admin_prompt",
            adm_lang,
            full_name=html.escape(full_name),
            old_role=old_role_uz,
            new_role=new_role_uz,
        )
        try:
            await target_message.bot.send_message(
                chat_id=adm_id,
                text=prompt_text,
                reply_markup=build_dual_role_approval_kb(str(req_id), adm_lang),
                parse_mode="HTML",
            )
        except Exception:
            pass


async def _apply_dual_role_invite_payload(
    sheets_mgr: SheetsManager,
    chat_id: int,
    new_role: str,
    payload: dict[str, Any],
    fallback_full_name: str,
) -> tuple[Optional[str], str]:
    kind = str(payload.get("kind") or "").strip()

    if kind == "par":
        student_id = str(payload.get("student_id") or "").strip()
        parent_type = str(payload.get("parent_type") or "father").strip()
        p_name = str(payload.get("full_name") or fallback_full_name).strip()
        p_phone = str(payload.get("phone") or "").strip()
        if student_id:
            await _bind_parent_to_students(
                sheets_mgr, [student_id], parent_type, p_name, p_phone, chat_id
            )
            await _save_parent_meta(
                chat_id, student_id, parent_type, p_name, p_phone
            )
        return (student_id or None), p_name

    if kind == "parbatch":
        invite_code = str(payload.get("invite_code") or "").strip()
        student_ids = [str(s).strip() for s in (payload.get("student_ids") or []) if str(s).strip()]
        parent_type = str(payload.get("parent_type") or "father").strip()
        p_name = str(payload.get("parent_name") or fallback_full_name).strip()
        p_phone = str(payload.get("parent_phone") or "").strip()
        valid_sids = await _bind_parent_to_students(
            sheets_mgr, student_ids, parent_type, p_name, p_phone, chat_id
        )
        if invite_code:
            await mark_parent_batch_invite_used(invite_code, chat_id)
        primary_sid = valid_sids[0] if valid_sids else (
            student_ids[0] if student_ids else None
        )
        if primary_sid:
            await _save_parent_meta(
                chat_id, primary_sid, parent_type, p_name, p_phone
            )
        return primary_sid, p_name

    if kind == "stu":
        student_id = str(payload.get("student_id") or "").strip()
        student = (
            await sheets_mgr.a_get_student_by_id(student_id)
            if student_id
            else None
        )
        sheet_fio = str(student.get("F.I.O.") or "").strip() if student else ""
        s_name = sheet_fio or str(
            payload.get("student_sheet_name")
            or payload.get("full_name")
            or fallback_full_name
        ).strip()
        s_phone = str(payload.get("phone") or "").strip()
        s_tg = str(payload.get("username") or "").strip()
        if student_id:
            existing_tel = str(student.get("Talaba_Tel") or "").strip() if student else ""
            phone_to_set = (
                s_phone
                if (not existing_tel or existing_tel.lower() in {"yo'q", "yoq", "-"})
                else ""
            )
            await _attach_student_device_info(
                sheets_mgr=sheets_mgr,
                student_id=student_id,
                chat_id=chat_id,
                phone=phone_to_set,
                username=s_tg or None,
                full_name=s_name if not sheet_fio else None,
            )
        return (student_id or None), s_name

    if kind == "join":
        group_name = str(payload.get("group_name") or "").strip()
        s_name = str(payload.get("full_name") or fallback_full_name).strip()
        s_phone = str(payload.get("phone") or "").strip()
        s_tg = str(payload.get("username") or "").strip()
        tg_formatted = f"@{s_tg.lstrip('@')}" if s_tg else ""
        existing_students = await sheets_mgr.a_get_students_by_chat_id(chat_id)
        existing_in_group = next(
            (
                s
                for s in existing_students
                if str(s.get("Guruh") or "").strip().lower() == group_name.lower()
            ),
            None,
        )
        if existing_in_group:
            sid = str(existing_in_group.get("Talaba_ID") or "").strip()
            s_name = str(existing_in_group.get("F.I.O.") or s_name).strip()
            return (sid or None), s_name

        if group_name:
            created_student = await asyncio.to_thread(
                sheets_mgr.add_student,
                s_name,
                group_name,
                s_phone,
                tg_formatted,
                "",
                "O'qiyapti",
            )
            sid = str(created_student.get("Talaba_ID") or "").strip()
            if sid:
                await sheets_mgr.a_link_student_chat_id(
                    sid, chat_id, False, s_tg or None
                )
                await asyncio.to_thread(
                    _append_student_to_active_cycle,
                    sheets_mgr,
                    group_name,
                    sid,
                    s_name,
                )
                schedule_group_initial_notice(None, group_name)
            return (sid or None), s_name

    db_user = await get_user(chat_id)
    linked_sid = db_user.get("linked_student_id") if db_user else None
    return linked_sid, fallback_full_name


async def _handle_deep_link(
    target_message: Message,
    user_id: int,
    lang: str,
    deep_link_arg: str,
    state: FSMContext,
    sheets_mgr: SheetsManager,
    tg_username: Optional[str] = None,
    tg_full_name: Optional[str] = None,
) -> bool:
    deep_link_arg = (deep_link_arg or "").strip()
    if not deep_link_arg:
        return False

    try:
        requested_role = _requested_role_from_deep_link(deep_link_arg)
        if requested_role:
            existing_resolved = await _resolve_user_role(
                user_id, tg_full_name or "", lang, sheets_mgr
            )
            user_roles = await get_user_roles(user_id)
            current_role = (
                existing_resolved.get("role") if existing_resolved else None
            )
            if current_role and current_role not in user_roles:
                user_roles.append(current_role)

            if current_role and requested_role not in user_roles:
                if {current_role, requested_role} == {"student", "parent"}:
                    existing_name = (
                        (existing_resolved.get("full_name") if existing_resolved else None)
                        or tg_full_name
                        or str(user_id)
                    )
                    is_valid, invite_payload = await _build_dual_role_invite_payload(
                        deep_link_arg=deep_link_arg,
                        user_id=user_id,
                        lang=lang,
                        existing_role=current_role,
                        existing_full_name=existing_name,
                        tg_username=tg_username,
                        sheets_mgr=sheets_mgr,
                        target_message=target_message,
                    )
                    if not is_valid or invite_payload is None:
                        return True
                    await _send_dual_role_admin_request(
                        target_message=target_message,
                        user_id=user_id,
                        lang=lang,
                        full_name=existing_name,
                        existing_role=current_role,
                        requested_role=requested_role,
                        invite_code=deep_link_arg[:64],
                        invite_payload=invite_payload,
                    )
                    return True

                safe_code = deep_link_arg[:38]
                warn_kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=t("btn_request_role_change", lang),
                                callback_data=f"req_role_change:{requested_role}:{safe_code}",
                            )
                        ]
                    ]
                )
                await target_message.answer(
                    t(
                        "role_lock_warning",
                        lang,
                        current_role=t(f"role_{current_role}", lang),
                    ),
                    reply_markup=warn_kb,
                    parse_mode="HTML",
                )
                return True

        if deep_link_arg.startswith("adm_"):
            invite_code = deep_link_arg[4:].strip()
            invite = await _get_unused_admin_invite(invite_code)
            if not invite:
                await target_message.answer(
                    _lt("admin_link_invalid", lang), parse_mode="HTML"
                )
                return True
            await state.clear()
            await state.update_data(adm_invite_code=invite_code)
            await state.set_state(AdminSelfRegStates.entering_full_name)
            await target_message.answer(
                _lt("admin_self_reg_enter_name", lang),
                reply_markup=cancel_reply_kb(lang, include_back=False),
                parse_mode="HTML",
            )
            return True

        if deep_link_arg.startswith("tch_"):
            invite_code = deep_link_arg[4:].strip()
            invite = await get_teacher_by_invite_code(invite_code)
            if not invite or (
                invite["status"] != "pending" and invite.get("telegram_id") != user_id
            ):
                await target_message.answer(
                    t("teacher_link_invalid", lang), parse_mode="HTML"
                )
                return True

            meta = await _get_teacher_meta_by_invite(invite_code)
            linked_group = (
                (meta.get("linked_group_name") if meta else None)
                or invite.get("linked_group_name")
                or invite.get("group_name")
                or ""
            ).strip()
            invited_by = meta.get("invited_by") if meta else None

            existing_db_teacher = await get_teacher_by_telegram_id(user_id)
            existing_sheet_teacher = await sheets_mgr.a_get_teacher_by_chat_id(user_id)
            has_existing_name = bool(
                (existing_sheet_teacher and str(existing_sheet_teacher.get("F.I.O.") or "").strip())
                or (
                    existing_db_teacher
                    and str(existing_db_teacher.get("full_name") or "").strip()
                    not in {"", "Ma'lumot kiritilmagan"}
                )
            )

            if has_existing_name:
                if not await activate_teacher_invite(invite_code, user_id):
                    await target_message.answer(
                        t("teacher_link_invalid", lang), parse_mode="HTML"
                    )
                    return True

                existing_meta = await _get_teacher_meta_by_tg(user_id)
                known_name = (
                    (str(existing_sheet_teacher.get("F.I.O.") or "").strip() if existing_sheet_teacher else "")
                    or (str(existing_db_teacher.get("full_name") or "").strip() if existing_db_teacher else "")
                    or (tg_full_name or "Ustoz")
                )
                known_phone = (
                    (str(existing_sheet_teacher.get("Telefon") or "").strip() if existing_sheet_teacher else "")
                    or (str(existing_meta.get("phone") or "").strip() if existing_meta else "")
                )
                known_tg = (
                    (str(existing_sheet_teacher.get("TG_Username") or "").strip() if existing_sheet_teacher else "")
                    or (str(existing_meta.get("username") or "").strip() if existing_meta else "")
                    or (tg_username or "")
                )

                reg_res = await sheets_mgr.a_register_teacher_and_assign_group(
                    {
                        "invite_code": invite_code,
                        "full_name": known_name,
                        "phone": known_phone,
                        "tg_username": known_tg,
                        "chat_id": str(user_id),
                        "status": "Faol",
                    },
                    target_group_name=linked_group or None,
                )
                await _update_teacher_sqlite_details(
                    invite_code, user_id, known_name, known_phone or None, known_tg.lstrip("@") or None
                )
                await upsert_user(
                    telegram_id=user_id, role="teacher", full_name=known_name, lang=lang
                )

                await state.clear()
                assigned_group = reg_res.get("group_assigned") or linked_group
                await target_message.answer(
                    _with_signature(
                        t("teacher_link_success", lang, teacher_name=html.escape(known_name)),
                        lang,
                    ),
                    reply_markup=build_main_menu("teacher", lang),
                    parse_mode="HTML",
                )
                if assigned_group:
                    assigned_text = (
                        f"📚 Siz <b>{html.escape(assigned_group)}</b> guruhiga ustoz sifatida biriktirildingiz!"
                        if lang == "latn"
                        else f"📚 Сиз <b>{html.escape(assigned_group)}</b> гуруҳига устоз сифатида бириктирилдингиз!"
                    )
                    await target_message.answer(assigned_text, parse_mode="HTML")

                await _notify_admins_teacher_registered(
                    target_message.bot,
                    user_id,
                    known_name,
                    known_phone,
                    assigned_group or None,
                    invited_by=invited_by,
                )
                return True

            await state.clear()
            await state.update_data(
                tch_invite_code=invite_code,
                tch_linked_group=linked_group,
                tch_invited_by=invited_by,
            )
            await state.set_state(TeacherSelfRegStates.entering_full_name)
            await target_message.answer(
                t("teacher_self_reg_enter_name", lang),
                reply_markup=cancel_reply_kb(lang, include_back=False),
                parse_mode="HTML",
            )
            return True

        if deep_link_arg.startswith("stu_"):
            student_id = deep_link_arg[4:].strip()
            student = await sheets_mgr.a_get_student_by_id(student_id)
            if not student:
                await target_message.answer(
                    t(
                        "link_student_not_found",
                        lang,
                        student_id=html.escape(student_id),
                    ),
                    parse_mode="HTML",
                )
                return True
            group_name = str(student.get("Guruh") or "-").strip() or "-"
            await state.clear()
            await state.update_data(stu_link_id=student_id, stu_link_group=group_name)
            await state.set_state(StudentLinkRegStates.entering_full_name)
            await target_message.answer(
                t("student_reg_enter_name", lang, group=html.escape(group_name)),
                reply_markup=cancel_reply_kb(lang, include_back=False),
                parse_mode="HTML",
            )
            return True

        if deep_link_arg.startswith("parbatch_"):
            invite_code = deep_link_arg[9:].strip()
            batch = await get_parent_batch_invite(invite_code)
            student_ids = [
                str(s).strip()
                for s in (batch.get("student_ids") or [])
                if str(s).strip()
            ] if batch else []
            if (
                not batch
                or not student_ids
                or (batch.get("is_used") and batch.get("used_by") != user_id)
            ):
                await target_message.answer(
                    _lt("parbatch_invalid", lang), parse_mode="HTML"
                )
                return True

            existing_p = await _get_existing_parent_profile(user_id, sheets_mgr)
            parent_name = (
                str(batch.get("parent_name") or "").strip()
                or (existing_p["full_name"] if existing_p else "")
            )
            parent_phone = (
                str(batch.get("parent_phone") or "").strip()
                or (existing_p["phone"] if existing_p else "")
            )
            batch_parent_type = str(batch.get("parent_type") or "").strip()
            if batch_parent_type in {"father", "mother"}:
                # The admin already chose 🧔 Otasi / 🧕 Onasi when creating the invite.
                parent_type = batch_parent_type
            else:
                parent_type = (
                    existing_p["parent_type"]
                    if existing_p and existing_p.get("parent_type") in {"father", "mother"}
                    else "father"
                )

            if not parent_name:
                await state.clear()
                await state.update_data(
                    par_batch_code=invite_code,
                    par_student_ids=student_ids,
                    par_student_id=student_ids[0],
                    par_student_name=", ".join(student_ids),
                    par_group="-",
                )
                await state.set_state(ParentRegStates.choosing_parent_type)
                await target_message.answer(
                    t(
                        "parent_reg_choose_type",
                        lang,
                        student_name=html.escape(", ".join(student_ids)),
                        group="—",
                    ),
                    reply_markup=parent_type_kb(lang),
                    parse_mode="HTML",
                )
                return True

            valid_sids = await _bind_parent_to_students(
                sheets_mgr,
                student_ids,
                parent_type,
                parent_name,
                parent_phone,
                user_id,
            )
            if not valid_sids:
                await target_message.answer(
                    _lt("parbatch_invalid", lang), parse_mode="HTML"
                )
                return True

            all_students = await sheets_mgr.a_get_all_students()
            students_by_id = {
                str(s.get("Talaba_ID") or "").strip(): s for s in all_students
            }
            linked_lines: list[str] = []
            for idx, sid in enumerate(valid_sids, start=1):
                stu = students_by_id.get(sid)
                stu_name = (
                    str(stu.get("F.I.O.") or "").strip() if stu else ""
                ) or sid
                stu_group = (
                    str(stu.get("Guruh") or "").strip() if stu else ""
                ) or "—"
                linked_lines.append(
                    f"{idx}. <b>{html.escape(stu_name)}</b> ({html.escape(stu_group)})"
                )

            await mark_parent_batch_invite_used(invite_code, user_id)
            await _save_parent_meta(
                user_id, valid_sids[0], parent_type, parent_name, parent_phone
            )
            existing_roles = await get_user_roles(user_id)
            if "parent" not in existing_roles:
                existing_roles.append("parent")
            await upsert_user(
                telegram_id=user_id,
                role="parent",
                linked_student_id=valid_sids[0],
                full_name=parent_name,
                lang=lang,
                roles=existing_roles,
                active_role="parent",
            )
            has_dual = await has_dual_student_parent_role(user_id)
            await state.clear()
            await target_message.answer(
                _with_signature(
                    _lt(
                        "parbatch_success",
                        lang,
                        parent_name=html.escape(parent_name),
                        children_lines="\n".join(linked_lines),
                    ),
                    lang,
                ),
                reply_markup=build_main_menu("parent", lang, has_dual_role=has_dual),
                parse_mode="HTML",
            )
            return True

        if deep_link_arg.startswith("par_") or deep_link_arg.startswith("parent_"):
            student_id = (
                deep_link_arg[7:].strip()
                if deep_link_arg.startswith("parent_")
                else deep_link_arg[4:].strip()
            )
            if not student_id:
                await target_message.answer(
                    t("link_student_not_found", lang, student_id="—"),
                    parse_mode="HTML",
                )
                return True

            student = await sheets_mgr.a_get_student_by_id(student_id)
            if not student:
                await target_message.answer(
                    t(
                        "link_student_not_found",
                        lang,
                        student_id=html.escape(student_id),
                    ),
                    parse_mode="HTML",
                )
                return True
            student_name = str(student.get("F.I.O.") or "").strip() or student_id
            group_name = str(student.get("Guruh") or "-").strip() or "-"

            existing_p = await _get_existing_parent_profile(user_id, sheets_mgr)
            if existing_p:
                p_type = existing_p["parent_type"]
                p_name = existing_p["full_name"]
                p_phone = existing_p["phone"]
                await _bind_parent_to_students(
                    sheets_mgr, [student_id], p_type, p_name, p_phone, user_id
                )
                await _save_parent_meta(user_id, student_id, p_type, p_name, p_phone)
                existing_roles = await get_user_roles(user_id)
                if "parent" not in existing_roles:
                    existing_roles.append("parent")
                await upsert_user(
                    telegram_id=user_id,
                    role="parent",
                    linked_student_id=student_id,
                    full_name=p_name,
                    lang=lang,
                    roles=existing_roles,
                    active_role="parent",
                )
                all_children = await sheets_mgr.a_get_children_by_parent_chat_id(user_id)
                children_lines = "\n".join(
                    f"{idx}. <b>{html.escape(str(c.get('F.I.O.') or '').strip() or str(c.get('Talaba_ID') or ''))}</b> "
                    f"({html.escape(str(c.get('Guruh') or '').strip() or '—')})"
                    for idx, c in enumerate(all_children, start=1)
                ) or f"1. <b>{html.escape(student_name)}</b> ({html.escape(group_name)})"

                has_dual = await has_dual_student_parent_role(user_id)
                await state.clear()
                await target_message.answer(
                    _with_signature(
                        _lt(
                            "parent_multi_added",
                            lang,
                            parent_name=html.escape(p_name),
                            student_name=html.escape(student_name),
                            group=html.escape(group_name),
                            children_lines=children_lines,
                        ),
                        lang,
                    ),
                    reply_markup=build_main_menu("parent", lang, has_dual_role=has_dual),
                    parse_mode="HTML",
                )
                return True

            await state.clear()
            await state.update_data(
                par_student_id=student_id,
                par_student_name=student_name,
                par_group=group_name,
            )
            preset_type = _preset_parent_type_from_student(student)
            if preset_type:
                # Parent type was fixed by the admin (🧔 Otasi / 🧕 Onasi): skip the
                # father/mother question and go straight to the name step.
                await state.update_data(par_type=preset_type, par_type_locked=True)
                await state.set_state(ParentRegStates.entering_full_name)
                await target_message.answer(
                    t("parent_reg_enter_name", lang),
                    reply_markup=cancel_reply_kb(lang, include_back=False),
                    parse_mode="HTML",
                )
                return True
            await state.set_state(ParentRegStates.choosing_parent_type)
            await target_message.answer(
                t(
                    "parent_reg_choose_type",
                    lang,
                    student_name=html.escape(student_name),
                    group=html.escape(group_name),
                ),
                reply_markup=parent_type_kb(lang),
                parse_mode="HTML",
            )
            return True

        if deep_link_arg.startswith("join_"):
            slug = deep_link_arg[5:].strip()
            group = await asyncio.to_thread(_find_group_by_join_slug, sheets_mgr, slug)
            if not group:
                await target_message.answer(
                    t("join_group_not_found", lang), parse_mode="HTML"
                )
                return True
            canonical_group = group["Guruh_Nomi"].strip()
            existing_students = await sheets_mgr.a_get_students_by_chat_id(user_id)
            existing_in_group = next(
                (
                    s
                    for s in existing_students
                    if str(s.get("Guruh") or "").strip().lower() == canonical_group.lower()
                ),
                None,
            )
            if existing_in_group:
                official_name = (
                    str(existing_in_group.get("F.I.O.") or "").strip()
                    or str(existing_in_group.get("Talaba_ID") or "")
                )
                existing_roles = await get_user_roles(user_id)
                if "student" not in existing_roles:
                    existing_roles.append("student")
                await upsert_user(
                    user_id,
                    role="student",
                    linked_student_id=existing_in_group.get("Talaba_ID"),
                    full_name=official_name,
                    lang=lang,
                    roles=existing_roles,
                    active_role="student",
                )
                has_dual = await has_dual_student_parent_role(user_id)
                await target_message.answer(
                    _with_signature(
                        t(
                            "join_already_in_group",
                            lang,
                            student_name=html.escape(official_name),
                            group=html.escape(canonical_group),
                        ),
                        lang,
                    ),
                    reply_markup=build_main_menu("student", lang, has_dual_role=has_dual),
                    parse_mode="HTML",
                )
                return True
            await state.clear()
            await state.update_data(join_group_name=canonical_group)
            await state.set_state(GroupJoinStates.entering_full_name)
            await target_message.answer(
                t("join_enter_full_name", lang, group=html.escape(canonical_group)),
                reply_markup=cancel_reply_kb(lang, include_back=False),
                parse_mode="HTML",
            )
            return True
    except Exception as exc:
        logger.exception(
            "Error processing deep-link payload %r for user_id=%s",
            deep_link_arg,
            user_id,
        )
        try:
            err_text = (
                _lt("rate_limit_busy", lang)
                if _is_rate_limit_error(exc)
                else t("error_generic", lang)
            )
            await target_message.answer(err_text, parse_mode="HTML")
        except Exception:
            pass
        return True

    return False


# ----------------------------------------------------------------------
# Dual-Role Approval Callbacks (dual_role:keep_both / replace / reject)
# ----------------------------------------------------------------------


@router.callback_query(F.data.startswith("dual_role:"))
async def cb_dual_role_decision(
    callback: CallbackQuery, sheets: Optional[SheetsManager] = None
) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        await callback.answer()
        return
    adm_id = callback.from_user.id
    adm_lang = await get_user_lang(adm_id)
    if not (adm_id in ADMIN_IDS or await _get_dynamic_admin(adm_id)):
        await callback.answer(t("join_no_permission", adm_lang), show_alert=True)
        return

    parts = callback.data.split(":", 2)
    if len(parts) != 3:
        await callback.answer()
        return
    action = parts[1].strip()
    try:
        req_id = int(parts[2].strip())
    except ValueError:
        await callback.answer()
        return

    status_map = {
        "keep_both": "approved_both",
        "replace": "approved_replace",
        "reject": "rejected",
    }
    if action not in status_map:
        await callback.answer()
        return

    resolved = await resolve_role_change_request(req_id, status_map[action])
    if not resolved:
        await callback.answer(t("join_already_processed", adm_lang), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    chat_id = int(resolved.get("chat_id") or resolved["user_id"])
    old_role = str(
        resolved.get("existing_role") or resolved.get("current_role") or "student"
    ).strip()
    new_role = str(resolved.get("requested_role") or "parent").strip()
    user_full_name = str(resolved.get("full_name") or str(chat_id)).strip()
    payload = dict(resolved.get("invite_payload") or {})
    target_lang = await get_user_lang(chat_id)
    sheets_mgr = sheets or get_sheets_manager()

    if action == "reject":
        try:
            await callback.message.edit_text(
                t("role_change_rejected_admin", adm_lang),
                parse_mode="HTML",
            )
        except Exception:
            pass
        try:
            await callback.bot.send_message(
                chat_id=chat_id,
                text=_with_signature(
                    t("role_change_rejected_user", target_lang), target_lang
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
        await callback.answer()
        return

    if action == "keep_both":
        updated_roles = await add_user_role(chat_id, new_role)
        linked_sid, final_name = await _apply_dual_role_invite_payload(
            sheets_mgr=sheets_mgr,
            chat_id=chat_id,
            new_role=new_role,
            payload=payload,
            fallback_full_name=user_full_name,
        )
        await upsert_user(
            telegram_id=chat_id,
            role=new_role,
            linked_student_id=linked_sid,
            full_name=final_name,
            lang=target_lang,
            roles=updated_roles,
            active_role=new_role,
        )
        has_dual = await has_dual_student_parent_role(chat_id)
        try:
            await callback.message.edit_text(
                _lt(
                    "dual_role_approved_both_admin",
                    adm_lang,
                    full_name=html.escape(final_name),
                    user_id=chat_id,
                    old_role=t(f"role_{old_role}", adm_lang),
                    new_role=t(f"role_{new_role}", adm_lang),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

        user_msg = _lt(
            "dual_role_approved_both_user",
            target_lang,
            new_role=t(f"role_{new_role}", target_lang),
        )
        welcome_line = await _welcome_menu_text(
            chat_id, final_name, new_role, target_lang
        )
        try:
            await callback.bot.send_message(
                chat_id=chat_id,
                text=_with_signature(f"{user_msg}\n\n{welcome_line}", target_lang),
                reply_markup=build_main_menu(
                    new_role, target_lang, has_dual_role=has_dual
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
        await callback.answer()
        return

    # action == "replace"
    updated_roles = await replace_user_role(chat_id, new_role)
    if old_role == "student":
        await asyncio.to_thread(_sync_clear_student_chat_id, sheets_mgr, chat_id)
    elif old_role == "parent":
        await asyncio.to_thread(_sync_clear_parent_chat_ids, sheets_mgr, chat_id)
        await _ensure_aux_tables()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM parent_meta WHERE telegram_id = ?;", (chat_id,)
            )
            await db.commit()

    linked_sid, final_name = await _apply_dual_role_invite_payload(
        sheets_mgr=sheets_mgr,
        chat_id=chat_id,
        new_role=new_role,
        payload=payload,
        fallback_full_name=user_full_name,
    )
    await upsert_user(
        telegram_id=chat_id,
        role=new_role,
        linked_student_id=linked_sid,
        full_name=final_name,
        lang=target_lang,
        roles=updated_roles,
        active_role=new_role,
    )
    has_dual = await has_dual_student_parent_role(chat_id)
    try:
        await callback.message.edit_text(
            _lt(
                "dual_role_approved_replace_admin",
                adm_lang,
                full_name=html.escape(final_name),
                user_id=chat_id,
                new_role=t(f"role_{new_role}", adm_lang),
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    user_msg = _lt(
        "dual_role_approved_replace_user",
        target_lang,
        new_role=t(f"role_{new_role}", target_lang),
    )
    welcome_line = await _welcome_menu_text(
        chat_id, final_name, new_role, target_lang
    )
    try:
        await callback.bot.send_message(
            chat_id=chat_id,
            text=_with_signature(f"{user_msg}\n\n{welcome_line}", target_lang),
            reply_markup=build_main_menu(
                new_role, target_lang, has_dual_role=has_dual
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


# ----------------------------------------------------------------------
# Role-Change Request Callbacks (User -> Admin Approval -> Reset Role)
# ----------------------------------------------------------------------


@router.callback_query(F.data.startswith("req_role_change:"))
async def cb_request_role_change(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        await callback.answer()
        return
    requested_role = parts[1].strip()
    invite_code = parts[2].strip()
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)

    db_user = await get_user(user_id)
    current_role = (db_user.get("role") if db_user else None) or "student"
    full_name = (
        (db_user.get("full_name") if db_user else None)
        or callback.from_user.full_name
        or str(user_id)
    )

    req_id = await create_role_change_request(
        user_id=user_id,
        full_name=full_name,
        current_role=current_role,
        requested_role=requested_role,
        invite_code=invite_code,
    )

    try:
        await callback.message.edit_text(
            t("role_change_request_sent", lang),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            t("role_change_request_sent", lang),
            parse_mode="HTML",
        )

    for adm_id in await _get_all_admin_ids():
        if adm_id == user_id:
            continue
        adm_lang = await get_user_lang(adm_id)
        admin_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("btn_role_change_approve", adm_lang),
                        callback_data=f"approve_role_change:{req_id}",
                    ),
                    InlineKeyboardButton(
                        text=t("btn_role_change_reject", adm_lang),
                        callback_data=f"reject_role_change:{req_id}",
                    ),
                ],
            ]
        )
        try:
            await callback.bot.send_message(
                chat_id=adm_id,
                text=t(
                    "role_change_admin_card",
                    adm_lang,
                    full_name=html.escape(full_name),
                    user_id=user_id,
                    current_role=t(f"role_{current_role}", adm_lang),
                    requested_role=t(f"role_{requested_role}", adm_lang),
                ),
                reply_markup=admin_kb,
                parse_mode="HTML",
            )
        except Exception:
            pass

    await callback.answer()


@router.callback_query(F.data.startswith("approve_role_change:"))
async def cb_approve_role_change(
    callback: CallbackQuery, sheets: Optional[SheetsManager] = None
) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        await callback.answer()
        return
    adm_id = callback.from_user.id
    adm_lang = await get_user_lang(adm_id)
    if not (adm_id in ADMIN_IDS or await _get_dynamic_admin(adm_id)):
        await callback.answer(t("join_no_permission", adm_lang), show_alert=True)
        return

    try:
        req_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return

    resolved = await resolve_role_change_request(req_id, "approved")
    if not resolved:
        await callback.answer(t("join_already_processed", adm_lang), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    target_user_id = int(resolved["user_id"])
    old_role = str(resolved.get("current_role") or "").strip()
    invite_code = str(resolved.get("invite_code") or "").strip()

    await reset_user_role(target_user_id)
    sheets_mgr = sheets or get_sheets_manager()

    if old_role == "teacher":
        t_rec = await sheets_mgr.a_get_teacher_by_chat_id(target_user_id)
        if t_rec and t_rec.get("Ustoz_ID"):
            await sheets_mgr.a_delete_teacher_completely(t_rec["Ustoz_ID"])
            await database.log_audit_event(
                actor_id=adm_id,
                action=database.AUDIT_TEACHER_DELETED,
                target=f"{str(t_rec.get('F.I.O.') or '').strip()} ({t_rec['Ustoz_ID']})",
                details="Rol almashtirish so'rovi tasdiqlandi (ustoz roli olib tashlandi)",
                actor_name=callback.from_user.full_name or "",
            )
    elif old_role in {"student", "parent"}:
        await asyncio.to_thread(
            _sync_clear_user_student_or_parent_chat_ids,
            sheets_mgr,
            target_user_id,
        )

    try:
        await callback.message.edit_text(
            t("role_change_approved_admin", adm_lang, user_id=target_user_id),
            parse_mode="HTML",
        )
    except Exception:
        pass

    target_lang = await get_user_lang(target_user_id)
    dm_kb: Optional[InlineKeyboardMarkup] = None
    if invite_code:
        try:
            bot_me = await callback.bot.get_me()
            dm_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=_lt("open_invite_link_btn", target_lang),
                            url=f"https://t.me/{bot_me.username}?start={invite_code}",
                        )
                    ]
                ]
            )
        except Exception:
            pass

    try:
        await callback.bot.send_message(
            chat_id=target_user_id,
            text=_with_signature(
                t("role_change_approved_user", target_lang), target_lang
            ),
            reply_markup=dm_kb,
            parse_mode="HTML",
        )
    except Exception:
        pass

    await callback.answer()


@router.callback_query(F.data.startswith("reject_role_change:"))
async def cb_reject_role_change(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        await callback.answer()
        return
    adm_id = callback.from_user.id
    adm_lang = await get_user_lang(adm_id)
    if not (adm_id in ADMIN_IDS or await _get_dynamic_admin(adm_id)):
        await callback.answer(t("join_no_permission", adm_lang), show_alert=True)
        return

    try:
        req_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return

    resolved = await resolve_role_change_request(req_id, "rejected")
    if not resolved:
        await callback.answer(t("join_already_processed", adm_lang), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    target_user_id = int(resolved["user_id"])
    try:
        await callback.message.edit_text(
            t("role_change_rejected_admin", adm_lang),
            parse_mode="HTML",
        )
    except Exception:
        pass

    target_lang = await get_user_lang(target_user_id)
    try:
        await callback.bot.send_message(
            chat_id=target_user_id,
            text=_with_signature(
                t("role_change_rejected_user", target_lang), target_lang
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass

    await callback.answer()


_VALID_ACTIVE_ROLES = ("admin", "teacher", "student", "parent")


async def _is_admin_user(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    try:
        return bool(await _get_dynamic_admin(user_id))
    except Exception:
        return False


async def _purge_stale_user_if_needed(
    user_id: int, sheets_mgr: SheetsManager
) -> bool:
    """
    Plain /start (no invite deep-link) guard.
    Returns True when the user still holds at least one valid, verified role
    (admin / teacher / student / parent). Non-admin roles are verified against
    Google Sheets (Ustozlar / Baza_Talabalar); a role whose Sheets record was
    deleted is purged from SQLite on the spot (the whole `users` row is deleted
    when no other role remains). Returns False for brand-new / deleted users.
    Sheets errors (rate limits, network) never purge anything.
    """
    db_user = await get_user(user_id)
    if not db_user:
        return False

    if await _is_admin_user(user_id):
        return True

    roles = [r for r in (db_user.get("roles") or []) if r in _VALID_ACTIVE_ROLES]
    legacy_role = str(db_user.get("role") or "").strip()
    if legacy_role in _VALID_ACTIVE_ROLES and legacy_role not in roles:
        roles.append(legacy_role)
    if not roles:
        return False

    try:
        still_valid: list[str] = []
        for role in roles:
            if role == "admin":
                # Admin rights live in ADMIN_IDS / dynamic_admins (checked above);
                # a stale 'admin' role in `users` alone is not valid anymore.
                exists = False
            elif role == "teacher":
                exists = bool(await sheets_mgr.a_is_teacher(user_id))
            elif role == "student":
                exists = bool(await sheets_mgr.a_get_students_by_chat_id(user_id))
            else:
                exists = bool(
                    await sheets_mgr.a_get_children_by_parent_chat_id(user_id)
                )
            if exists:
                still_valid.append(role)
            else:
                await purge_deleted_person_from_db(user_id, role)
        return bool(still_valid)
    except Exception as exc:
        logger.warning(
            "Stale-user verification skipped for user_id=%s: %s", user_id, exc
        )
        return True


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(
    message: Message,
    command: CommandObject,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not message.from_user:
        return
    saved_lang = "latn"
    try:
        await state.clear()
        user_id = message.from_user.id
        args = (command.args or "").strip()

        if not args:
            # No invite link: a user who was deleted from the system (or never
            # registered) is a brand-new unverified guest. Stale SQLite records
            # of people whose Sheets rows vanished are purged right here.
            await state.clear()
            _PENDING_START_ARGS.pop(user_id, None)
            await _purge_stale_user_if_needed(
                user_id, sheets or get_sheets_manager()
            )

        # Repeat /start: the user already chose a language once → skip the
        # language picker and open their active menu (or deep link) directly.
        if await has_saved_language(user_id):
            saved_lang = await get_user_lang(user_id)
            _PENDING_START_ARGS.pop(user_id, None)
            sheets_mgr = sheets or get_sheets_manager()
            tg_full_name = message.from_user.full_name or "Foydalanuvchi"
            if args and await _handle_deep_link(
                message,
                user_id,
                saved_lang,
                args,
                state,
                sheets_mgr,
                tg_username=message.from_user.username,
                tg_full_name=tg_full_name,
            ):
                return
            await _send_welcome_or_unregistered(
                message, user_id, tg_full_name, saved_lang, sheets_mgr
            )
            return

        if args:
            await state.update_data(start_payload=args)
            _PENDING_START_ARGS[user_id] = args
        else:
            _PENDING_START_ARGS.pop(user_id, None)

        await message.answer(
            t("choose_language", "latn"),
            reply_markup=build_language_keyboard(mode="init"),
        )
    except Exception as exc:
        logger.exception("Error in /start handler")
        try:
            err_text = (
                _lt("rate_limit_busy", saved_lang)
                if _is_rate_limit_error(exc)
                else t("error_generic", saved_lang)
            )
            await message.answer(err_text, parse_mode="HTML")
        except Exception:
            pass


@router.message(F.chat.type == ChatType.PRIVATE, F.text.in_(CHANGE_LANG_BUTTON_TEXTS))
async def cmd_change_language(message: Message) -> None:
    await message.answer(
        t("choose_language", "latn"),
        reply_markup=build_language_keyboard(mode="switch"),
    )


@router.message(F.chat.type == ChatType.PRIVATE, F.text.in_(SWITCH_ROLE_BUTTON_TEXTS))
async def handle_switch_active_role(
    message: Message,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    sheets_mgr = sheets or get_sheets_manager()

    if not await has_dual_student_parent_role(user_id):
        await _send_welcome_or_unregistered(
            message,
            user_id,
            message.from_user.full_name or "Foydalanuvchi",
            lang,
            sheets_mgr,
        )
        return

    await state.clear()
    new_active = await switch_active_role(user_id)
    if new_active not in {"student", "parent"}:
        new_active = "student"

    resolved = await _resolve_user_role(
        user_id,
        message.from_user.full_name or "Foydalanuvchi",
        lang,
        sheets_mgr,
    )
    display_name = (
        (resolved.get("full_name") if resolved else None)
        or message.from_user.full_name
        or "Foydalanuvchi"
    )
    welcome_text = _with_signature(
        await _welcome_menu_text(
            user_id, display_name, new_active, lang, sheets_mgr
        ),
        lang,
    )
    await message.answer(
        text=welcome_text,
        reply_markup=build_main_menu(new_active, lang, has_dual_role=True),
        parse_mode="HTML",
    )


@router.message(F.chat.type == ChatType.PRIVATE, F.text.in_(MAIN_ROLE_SWITCH_TEXTS))
async def cmd_main_admin_role_switch(message: Message, state: FSMContext) -> None:
    """Role picker for the MAIN admin only; everyone else is refused."""
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not is_main_admin(user_id):
        logger.warning("Role switch refused for non-main admin %s", user_id)
        await message.answer(t("role_switch_forbidden", lang), parse_mode="HTML")
        return
    await state.clear()
    db_user = await get_user(user_id)
    current = str((db_user or {}).get("active_role") or "admin")
    if current not in MAIN_ROLE_CHOICES:
        current = "admin"
    await message.answer(
        t("role_switch_prompt", lang),
        reply_markup=main_admin_role_switch_kb(current, lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("main_role:"))
async def cb_main_admin_role_switch(
    callback: CallbackQuery, sheets: Optional[SheetsManager] = None
) -> None:
    if not callback.from_user:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not is_main_admin(user_id):
        # Secondary admins / other users can never switch roles.
        await callback.answer(
            re.sub(r"<[^>]+>", "", t("role_switch_forbidden", lang)), show_alert=True
        )
        return
    role = (callback.data or "").split(":", 1)[1]
    if role == "__cancel__":
        if callback.message:
            await callback.message.edit_text(t("role_switch_cancelled", lang))
        await callback.answer()
        return
    if role not in MAIN_ROLE_CHOICES:
        await callback.answer()
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET active_role = ? WHERE telegram_id = ?;", (role, user_id)
        )
        await db.commit()
    sheets_mgr = sheets or get_sheets_manager()
    display_name = callback.from_user.full_name or "Admin"
    role_label = t(f"role_switch_{role}", lang)
    if callback.message:
        await callback.message.edit_text(
            t("role_switch_done", lang, role=html.escape(role_label)),
            parse_mode="HTML",
        )
        greeting = await _welcome_menu_text(user_id, display_name, role, lang, sheets_mgr)
        await callback.message.answer(
            _with_signature(greeting, lang),
            reply_markup=build_main_menu(role, lang),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "global_cancel_fsm")
async def cb_global_cancel_fsm(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    sheets_mgr = sheets or get_sheets_manager()
    await state.clear()
    _PENDING_START_ARGS.pop(user_id, None)
    try:
        await callback.message.edit_text(t("fsm_cancelled", lang), parse_mode="HTML")
    except Exception:
        pass
    await _send_welcome_or_unregistered(
        callback.message,
        user_id,
        callback.from_user.full_name or "Foydalanuvchi",
        lang,
        sheets_mgr,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_lang:"))
async def cb_set_language(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":", maxsplit=2)
    if len(parts) < 2:
        await callback.answer()
        return
    lang = parts[1] if parts[1] in {"latn", "cyrl"} else "latn"
    mode = parts[2] if len(parts) >= 3 else "init"
    user_id = callback.from_user.id
    tg_full_name = callback.from_user.full_name or "Foydalanuvchi"
    tg_username = callback.from_user.username
    sheets_mgr = sheets or get_sheets_manager()

    try:
        await set_user_lang(user_id, lang)
        try:
            await callback.message.edit_text(t("lang_saved", lang), parse_mode="HTML")
        except Exception:
            pass

        data = await state.get_data()
        deep_link_arg = ""
        if mode == "init":
            deep_link_arg = (
                str(data.get("start_payload") or "").strip()
                or _PENDING_START_ARGS.pop(user_id, "")
            )
            if "start_payload" in data:
                await state.update_data(start_payload=None)
        else:
            _PENDING_START_ARGS.pop(user_id, None)

        if deep_link_arg and await _handle_deep_link(
            callback.message,
            user_id,
            lang,
            deep_link_arg,
            state,
            sheets_mgr,
            tg_username=tg_username,
            tg_full_name=tg_full_name,
        ):
            await callback.answer()
            return

        await _send_welcome_or_unregistered(
            callback.message, user_id, tg_full_name, lang, sheets_mgr
        )
    except Exception as exc:
        logger.exception("Error in cb_set_language for user_id=%s", user_id)
        try:
            err_text = (
                _lt("rate_limit_busy", lang)
                if _is_rate_limit_error(exc)
                else t("error_generic", lang)
            )
            await callback.message.answer(err_text, parse_mode="HTML")
        except Exception:
            pass
    await callback.answer()


# ----------------------------------------------------------------------
# 0. Admin Deep-Link Self-Registration (?start=adm_<CODE>)
# ----------------------------------------------------------------------


@router.message(StateFilter(AdminSelfRegStates), F.text.in_(CANCEL_TEXTS))
async def msg_admin_reg_cancel(
    message: Message, state: FSMContext, sheets: Optional[SheetsManager] = None
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    await state.clear()
    await message.answer(t("fsm_cancelled", lang), reply_markup=ReplyKeyboardRemove())
    await _send_welcome_or_unregistered(
        message,
        user_id,
        message.from_user.full_name or "Admin",
        lang,
        sheets or get_sheets_manager(),
    )


@router.message(AdminSelfRegStates.sharing_phone, F.text.in_(BACK_TEXTS))
async def msg_admin_reg_back_to_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    await state.set_state(AdminSelfRegStates.entering_full_name)
    await message.answer(
        _lt("admin_self_reg_enter_name", lang),
        reply_markup=cancel_reply_kb(lang, include_back=False),
        parse_mode="HTML",
    )


@router.message(AdminSelfRegStates.entering_full_name)
async def msg_admin_reg_full_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    full_name = _validate_full_name(message.text or "")
    if not full_name:
        await message.answer(
            _lt("admin_self_reg_invalid_name", lang),
            reply_markup=cancel_reply_kb(lang, include_back=False),
            parse_mode="HTML",
        )
        return
    await state.update_data(adm_full_name=full_name)
    await state.set_state(AdminSelfRegStates.sharing_phone)
    await message.answer(
        _lt("admin_self_reg_share_phone", lang, full_name=html.escape(full_name)),
        reply_markup=share_phone_reply_kb(lang, include_back=True),
        parse_mode="HTML",
    )


@router.message(AdminSelfRegStates.sharing_phone, F.contact)
async def msg_admin_reg_contact(message: Message, state: FSMContext) -> None:
    if not message.from_user or not message.contact:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if message.contact.user_id and message.contact.user_id != user_id:
        await message.answer(
            t("own_contact_only", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )
        return

    data = await state.get_data()
    invite_code = data.get("adm_invite_code", "")
    full_name = data.get("adm_full_name", "")
    if not invite_code or not full_name:
        await state.clear()
        await message.answer(
            t("error_generic", lang), reply_markup=ReplyKeyboardRemove()
        )
        return

    phone = _normalize_phone(message.contact.phone_number)
    username = message.from_user.username
    ok, invited_by = await _activate_admin_invite_and_register(
        invite_code=invite_code,
        telegram_id=user_id,
        full_name=full_name,
        phone=phone,
        username=username,
        lang=lang,
    )
    if not ok:
        await state.clear()
        await message.answer(
            _lt("admin_link_invalid", lang),
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )
        return

    await state.clear()
    await message.answer(
        _with_signature(
            _lt("admin_link_success", lang, admin_name=html.escape(full_name)),
            lang,
        ),
        reply_markup=build_main_menu("admin", lang),
        parse_mode="HTML",
    )

    if invited_by and invited_by != user_id:
        try:
            inv_lang = await get_user_lang(invited_by)
            await message.bot.send_message(
                chat_id=invited_by,
                text=_lt(
                    "admin_invite_used_notify",
                    inv_lang,
                    admin_name=html.escape(full_name),
                    phone=html.escape(phone),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


@router.message(AdminSelfRegStates.sharing_phone)
async def msg_admin_reg_phone_fallback(message: Message) -> None:
    if message.from_user:
        lang = await get_user_lang(message.from_user.id)
        await message.answer(
            t("use_contact_button_only", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )


# ----------------------------------------------------------------------
# 1. Teacher Deep-Link Self-Registration (?start=tch_<CODE>)
# ----------------------------------------------------------------------


@router.message(StateFilter(TeacherSelfRegStates), F.text.in_(CANCEL_TEXTS))
async def msg_teacher_reg_cancel(
    message: Message, state: FSMContext, sheets: Optional[SheetsManager] = None
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    await state.clear()
    await message.answer(t("fsm_cancelled", lang), reply_markup=ReplyKeyboardRemove())
    await _send_welcome_or_unregistered(
        message,
        user_id,
        message.from_user.full_name or "Ustoz",
        lang,
        sheets or get_sheets_manager(),
    )


@router.message(TeacherSelfRegStates.sharing_phone, F.text.in_(BACK_TEXTS))
async def msg_teacher_reg_back_to_name(
    message: Message, state: FSMContext
) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    await state.set_state(TeacherSelfRegStates.entering_full_name)
    await message.answer(
        t("teacher_self_reg_enter_name", lang),
        reply_markup=cancel_reply_kb(lang, include_back=False),
        parse_mode="HTML",
    )


@router.message(TeacherSelfRegStates.entering_full_name)
async def msg_teacher_reg_full_name(
    message: Message, state: FSMContext
) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    full_name = _validate_full_name(message.text or "")
    if not full_name:
        await message.answer(
            t("teacher_self_reg_invalid_name", lang),
            reply_markup=cancel_reply_kb(lang, include_back=False),
            parse_mode="HTML",
        )
        return
    await state.update_data(tch_full_name=full_name)
    await state.set_state(TeacherSelfRegStates.sharing_phone)
    await message.answer(
        t("teacher_self_reg_share_phone", lang, full_name=html.escape(full_name)),
        reply_markup=share_phone_reply_kb(lang, include_back=True),
        parse_mode="HTML",
    )


@router.message(TeacherSelfRegStates.sharing_phone, F.contact)
async def msg_teacher_reg_contact(
    message: Message, state: FSMContext, sheets: Optional[SheetsManager] = None
) -> None:
    if not message.from_user or not message.contact:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if message.contact.user_id and message.contact.user_id != user_id:
        await message.answer(
            t("own_contact_only", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )
        return

    data = await state.get_data()
    invite_code = data.get("tch_invite_code", "")
    full_name = data.get("tch_full_name", "")
    linked_group = str(data.get("tch_linked_group") or "").strip()
    invited_by = data.get("tch_invited_by")
    if not invite_code or not full_name:
        await state.clear()
        await message.answer(
            t("error_generic", lang), reply_markup=ReplyKeyboardRemove()
        )
        return

    if not await activate_teacher_invite(invite_code, user_id):
        await state.clear()
        await message.answer(
            t("teacher_link_invalid", lang), reply_markup=ReplyKeyboardRemove()
        )
        return

    meta = await _get_teacher_meta_by_invite(invite_code)
    if not linked_group and meta:
        linked_group = str(meta.get("linked_group_name") or "").strip()
    if invited_by is None and meta:
        invited_by = meta.get("invited_by")

    phone = _normalize_phone(message.contact.phone_number)
    username = message.from_user.username
    sheets_mgr = sheets or get_sheets_manager()

    try:
        reg_res = await sheets_mgr.a_register_teacher_and_assign_group(
            {
                "invite_code": invite_code,
                "full_name": full_name,
                "phone": phone,
                "tg_username": username or "",
                "chat_id": str(user_id),
                "status": "Faol",
            },
            target_group_name=linked_group or None,
        )
    except Exception as exc:
        logger.exception("Failed teacher registration for user_id=%s", user_id)
        await state.clear()
        err_text = (
            _lt("rate_limit_busy", lang)
            if _is_rate_limit_error(exc)
            else t("error_generic", lang)
        )
        await message.answer(
            err_text, reply_markup=ReplyKeyboardRemove(), parse_mode="HTML"
        )
        return

    await _update_teacher_sqlite_details(
        invite_code, user_id, full_name, phone, username
    )
    await upsert_user(
        telegram_id=user_id, role="teacher", full_name=full_name, lang=lang
    )

    assigned_group = reg_res.get("group_assigned") or linked_group
    await state.clear()
    await message.answer(
        _with_signature(
            t("teacher_link_success", lang, teacher_name=html.escape(full_name)),
            lang,
        ),
        reply_markup=build_main_menu("teacher", lang),
        parse_mode="HTML",
    )

    if assigned_group:
        assigned_text = (
            f"📚 Siz <b>{html.escape(assigned_group)}</b> guruhiga ustoz sifatida biriktirildingiz!"
            if lang == "latn"
            else f"📚 Сиз <b>{html.escape(assigned_group)}</b> гуруҳига устоз сифатида бириктирилдингиз!"
        )
        await message.answer(assigned_text, parse_mode="HTML")

    await _notify_admins_teacher_registered(
        message.bot,
        user_id,
        full_name,
        phone,
        assigned_group or None,
        invited_by=invited_by,
    )


@router.message(TeacherSelfRegStates.sharing_phone)
async def msg_teacher_reg_phone_fallback(message: Message) -> None:
    if message.from_user:
        lang = await get_user_lang(message.from_user.id)
        await message.answer(
            t("use_contact_button_only", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )


# ----------------------------------------------------------------------
# 2. Student Deep-Link Registration (?start=stu_<ID>)
# ----------------------------------------------------------------------


@router.message(StateFilter(StudentLinkRegStates), F.text.in_(CANCEL_TEXTS))
async def msg_student_link_cancel(
    message: Message, state: FSMContext, sheets: Optional[SheetsManager] = None
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    await state.clear()
    await message.answer(t("fsm_cancelled", lang), reply_markup=ReplyKeyboardRemove())
    await _send_welcome_or_unregistered(
        message,
        user_id,
        message.from_user.full_name or "Talaba",
        lang,
        sheets or get_sheets_manager(),
    )


@router.message(StudentLinkRegStates.sharing_phone, F.text.in_(BACK_TEXTS))
async def msg_student_link_back_to_name(
    message: Message, state: FSMContext
) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    data = await state.get_data()
    await state.set_state(StudentLinkRegStates.entering_full_name)
    await message.answer(
        t(
            "student_reg_enter_name",
            lang,
            group=html.escape(data.get("stu_link_group", "-")),
        ),
        reply_markup=cancel_reply_kb(lang, include_back=False),
        parse_mode="HTML",
    )


@router.message(StudentLinkRegStates.entering_full_name)
async def msg_student_link_full_name(
    message: Message, state: FSMContext
) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    full_name = _validate_full_name(message.text or "")
    if not full_name:
        await message.answer(
            t("student_reg_invalid_name", lang),
            reply_markup=cancel_reply_kb(lang, include_back=False),
            parse_mode="HTML",
        )
        return
    await state.update_data(stu_full_name=full_name)
    await state.set_state(StudentLinkRegStates.sharing_phone)
    await message.answer(
        t("student_reg_share_phone", lang, full_name=html.escape(full_name)),
        reply_markup=share_phone_reply_kb(lang, include_back=True),
        parse_mode="HTML",
    )


@router.message(StudentLinkRegStates.sharing_phone, F.contact)
async def msg_student_link_contact(
    message: Message, state: FSMContext, sheets: Optional[SheetsManager] = None
) -> None:
    if not message.from_user or not message.contact:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if message.contact.user_id and message.contact.user_id != user_id:
        await message.answer(
            t("own_contact_only", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )
        return

    data = await state.get_data()
    student_id = data.get("stu_link_id", "")
    group_name = data.get("stu_link_group", "-")
    full_name = data.get("stu_full_name", "")
    if not student_id or not full_name:
        await state.clear()
        await message.answer(
            t("error_generic", lang), reply_markup=ReplyKeyboardRemove()
        )
        return

    phone = _normalize_phone(message.contact.phone_number)
    username = message.from_user.username
    sheets_mgr = sheets or get_sheets_manager()

    try:
        await _attach_student_device_info(
            sheets_mgr=sheets_mgr,
            student_id=student_id,
            chat_id=user_id,
            phone=phone,
            username=username,
            full_name=full_name,
        )
        await asyncio.to_thread(
            _sync_update_student_name_in_active_cycles,
            sheets_mgr,
            group_name,
            student_id,
            full_name,
        )
        existing_roles = await get_user_roles(user_id)
        if "student" not in existing_roles:
            existing_roles.append("student")
        await upsert_user(
            telegram_id=user_id,
            role="student",
            linked_student_id=student_id,
            full_name=full_name,
            lang=lang,
            roles=existing_roles,
            active_role="student",
        )
    except Exception as exc:
        logger.exception(
            "Failed to attach student device info for student_id=%s, user_id=%s",
            student_id,
            user_id,
        )
        await state.clear()
        err_text = (
            _lt("rate_limit_busy", lang)
            if _is_rate_limit_error(exc)
            else t("error_generic", lang)
        )
        await message.answer(
            err_text, reply_markup=ReplyKeyboardRemove(), parse_mode="HTML"
        )
        return

    has_dual = await has_dual_student_parent_role(user_id)
    await state.clear()
    await message.answer(
        _with_signature(
            t(
                "link_success_student",
                lang,
                student_name=html.escape(full_name),
                group=html.escape(group_name),
            ),
            lang,
        ),
        reply_markup=build_main_menu("student", lang, has_dual_role=has_dual),
        parse_mode="HTML",
    )


@router.message(StudentLinkRegStates.sharing_phone)
async def msg_student_link_phone_fallback(message: Message) -> None:
    if message.from_user:
        lang = await get_user_lang(message.from_user.id)
        await message.answer(
            t("use_contact_button_only", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )


# ----------------------------------------------------------------------
# 3. Parent Deep-Link Registration (?start=par_<ID> & ?start=parbatch_<CODE>)
# ----------------------------------------------------------------------


@router.callback_query(
    ParentRegStates.choosing_parent_type, F.data.startswith("parent_type:")
)
async def cb_parent_choose_type(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    choice = callback.data.split(":", 1)[1]

    if choice == "cancel":
        await state.clear()
        try:
            await callback.message.edit_text(t("fsm_cancelled", lang))
        except Exception:
            pass
        await _send_welcome_or_unregistered(
            callback.message,
            user_id,
            callback.from_user.full_name or "Ota-ona",
            lang,
            sheets or get_sheets_manager(),
        )
        await callback.answer()
        return

    if choice not in {"father", "mother"}:
        await callback.answer()
        return

    await state.update_data(par_type=choice)
    await state.set_state(ParentRegStates.entering_full_name)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        t("parent_reg_enter_name", lang),
        reply_markup=cancel_reply_kb(lang, include_back=True),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(StateFilter(ParentRegStates), F.text.in_(CANCEL_TEXTS))
async def msg_parent_reg_cancel(
    message: Message, state: FSMContext, sheets: Optional[SheetsManager] = None
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    await state.clear()
    await message.answer(t("fsm_cancelled", lang), reply_markup=ReplyKeyboardRemove())
    await _send_welcome_or_unregistered(
        message,
        user_id,
        message.from_user.full_name or "Ota-ona",
        lang,
        sheets or get_sheets_manager(),
    )


@router.message(ParentRegStates.entering_full_name, F.text.in_(BACK_TEXTS))
async def msg_parent_reg_back_to_type(
    message: Message, state: FSMContext
) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    data = await state.get_data()
    if data.get("par_type_locked"):
        await message.answer(
            t("parent_reg_enter_name", lang),
            reply_markup=cancel_reply_kb(lang, include_back=False),
            parse_mode="HTML",
        )
        return
    await state.set_state(ParentRegStates.choosing_parent_type)
    await message.answer("↩️", reply_markup=ReplyKeyboardRemove())
    await message.answer(
        t(
            "parent_reg_choose_type",
            lang,
            student_name=html.escape(data.get("par_student_name", "-")),
            group=html.escape(data.get("par_group", "-")),
        ),
        reply_markup=parent_type_kb(lang),
        parse_mode="HTML",
    )


@router.message(ParentRegStates.sharing_phone, F.text.in_(BACK_TEXTS))
async def msg_parent_reg_back_to_name(
    message: Message, state: FSMContext
) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    await state.set_state(ParentRegStates.entering_full_name)
    await message.answer(
        t("parent_reg_enter_name", lang),
        reply_markup=cancel_reply_kb(lang, include_back=True),
        parse_mode="HTML",
    )


@router.message(ParentRegStates.entering_full_name)
async def msg_parent_reg_full_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    full_name = _validate_full_name(message.text or "")
    if not full_name:
        await message.answer(
            t("parent_reg_invalid_name", lang),
            reply_markup=cancel_reply_kb(lang, include_back=True),
            parse_mode="HTML",
        )
        return
    await state.update_data(par_full_name=full_name)
    await state.set_state(ParentRegStates.sharing_phone)
    await message.answer(
        t("parent_reg_share_phone", lang, full_name=html.escape(full_name)),
        reply_markup=share_phone_reply_kb(lang, include_back=True),
        parse_mode="HTML",
    )


@router.message(ParentRegStates.sharing_phone, F.contact)
async def msg_parent_reg_contact(
    message: Message, state: FSMContext, sheets: Optional[SheetsManager] = None
) -> None:
    if not message.from_user or not message.contact:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if message.contact.user_id and message.contact.user_id != user_id:
        await message.answer(
            t("own_contact_only", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )
        return

    data = await state.get_data()
    batch_code = str(data.get("par_batch_code") or "").strip()
    batch_student_ids = [
        str(s).strip()
        for s in (data.get("par_student_ids") or [])
        if str(s).strip()
    ]
    student_id = str(data.get("par_student_id") or "").strip()
    student_name = str(data.get("par_student_name") or student_id).strip()
    group_name = str(data.get("par_group") or "-").strip()
    parent_type = str(data.get("par_type") or "father").strip()
    full_name = str(data.get("par_full_name") or "").strip()
    if (not student_id and not batch_student_ids) or not full_name:
        await state.clear()
        await message.answer(
            t("error_generic", lang), reply_markup=ReplyKeyboardRemove()
        )
        return

    phone = _normalize_phone(message.contact.phone_number)
    sheets_mgr = sheets or get_sheets_manager()

    try:
        if batch_code and batch_student_ids:
            valid_sids = await _bind_parent_to_students(
                sheets_mgr,
                batch_student_ids,
                parent_type,
                full_name,
                phone,
                user_id,
            )
            all_students = await sheets_mgr.a_get_all_students()
            students_by_id = {
                str(s.get("Talaba_ID") or "").strip(): s for s in all_students
            }
            linked_lines: list[str] = []
            for idx, sid in enumerate(valid_sids, start=1):
                stu = students_by_id.get(sid)
                s_name = (str(stu.get("F.I.O.") or "").strip() if stu else "") or sid
                s_grp = (str(stu.get("Guruh") or "").strip() if stu else "") or "—"
                linked_lines.append(
                    f"{idx}. <b>{html.escape(s_name)}</b> ({html.escape(s_grp)})"
                )
            await mark_parent_batch_invite_used(batch_code, user_id)
            primary_sid = valid_sids[0] if valid_sids else batch_student_ids[0]
            await _save_parent_meta(user_id, primary_sid, parent_type, full_name, phone)
            existing_roles = await get_user_roles(user_id)
            if "parent" not in existing_roles:
                existing_roles.append("parent")
            await upsert_user(
                telegram_id=user_id,
                role="parent",
                linked_student_id=primary_sid,
                full_name=full_name,
                lang=lang,
                roles=existing_roles,
                active_role="parent",
            )
            has_dual = await has_dual_student_parent_role(user_id)
            await state.clear()
            await message.answer(
                _with_signature(
                    _lt(
                        "parbatch_success",
                        lang,
                        parent_name=html.escape(full_name),
                        children_lines="\n".join(linked_lines),
                    ),
                    lang,
                ),
                reply_markup=build_main_menu("parent", lang, has_dual_role=has_dual),
                parse_mode="HTML",
            )
            return

        await _bind_parent_to_students(
            sheets_mgr, [student_id], parent_type, full_name, phone, user_id
        )
        await _save_parent_meta(user_id, student_id, parent_type, full_name, phone)
        existing_roles = await get_user_roles(user_id)
        if "parent" not in existing_roles:
            existing_roles.append("parent")
        await upsert_user(
            telegram_id=user_id,
            role="parent",
            linked_student_id=student_id,
            full_name=full_name,
            lang=lang,
            roles=existing_roles,
            active_role="parent",
        )
    except Exception as exc:
        logger.exception(
            "Failed parent contact registration for user_id=%s, student_id=%s",
            user_id,
            student_id,
        )
        await state.clear()
        err_text = (
            _lt("rate_limit_busy", lang)
            if _is_rate_limit_error(exc)
            else t("error_generic", lang)
        )
        await message.answer(
            err_text, reply_markup=ReplyKeyboardRemove(), parse_mode="HTML"
        )
        return

    parent_role_label = t(
        "parent_label_father" if parent_type == "father" else "parent_label_mother",
        lang,
    )
    has_dual = await has_dual_student_parent_role(user_id)
    await state.clear()
    await message.answer(
        _with_signature(
            t(
                "link_success_parent",
                lang,
                parent_name=html.escape(full_name),
                student_name=html.escape(student_name),
                group=html.escape(group_name),
                parent_role=html.escape(parent_role_label),
            ),
            lang,
        ),
        reply_markup=build_main_menu("parent", lang, has_dual_role=has_dual),
        parse_mode="HTML",
    )


@router.message(ParentRegStates.sharing_phone)
async def msg_parent_reg_phone_fallback(message: Message) -> None:
    if message.from_user:
        lang = await get_user_lang(message.from_user.id)
        await message.answer(
            t("use_contact_button_only", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )


# ----------------------------------------------------------------------
# 4. Student Group Self-Join (?start=join_<Group>)
# ----------------------------------------------------------------------


@router.message(StateFilter(GroupJoinStates), F.text.in_(CANCEL_TEXTS))
async def msg_join_cancel(
    message: Message, state: FSMContext, sheets: Optional[SheetsManager] = None
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    await state.clear()
    resolved = await _resolve_user_role(
        user_id,
        message.from_user.full_name or "Foydalanuvchi",
        lang,
        sheets or get_sheets_manager(),
    )
    has_dual = await has_dual_student_parent_role(user_id) if resolved else False
    await message.answer(
        t("join_cancelled", lang),
        reply_markup=(
            build_main_menu(resolved["role"], lang, has_dual_role=has_dual)
            if resolved
            else ReplyKeyboardRemove()
        ),
    )


@router.message(GroupJoinStates.sharing_phone, F.text.in_(BACK_TEXTS))
async def msg_join_back_to_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    data = await state.get_data()
    await state.set_state(GroupJoinStates.entering_full_name)
    await message.answer(
        t(
            "join_enter_full_name",
            lang,
            group=html.escape(data.get("join_group_name", "-")),
        ),
        reply_markup=cancel_reply_kb(lang, include_back=False),
        parse_mode="HTML",
    )


@router.message(GroupJoinStates.entering_full_name)
async def msg_join_full_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    normalized_name = _validate_full_name(message.text or "")
    if not normalized_name:
        await message.answer(
            t("join_invalid_full_name", lang),
            reply_markup=cancel_reply_kb(lang, include_back=False),
            parse_mode="HTML",
        )
        return
    await state.update_data(join_full_name=normalized_name)
    await state.set_state(GroupJoinStates.sharing_phone)
    await message.answer(
        t("join_share_phone", lang, full_name=html.escape(normalized_name)),
        reply_markup=join_share_phone_kb(lang),
        parse_mode="HTML",
    )


@router.message(GroupJoinStates.sharing_phone, F.contact)
async def msg_join_contact(
    message: Message, state: FSMContext, sheets: Optional[SheetsManager] = None
) -> None:
    if not message.from_user or not message.contact:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if message.contact.user_id and message.contact.user_id != user_id:
        await message.answer(
            t("join_own_contact_only", lang), reply_markup=join_share_phone_kb(lang)
        )
        return

    data = await state.get_data()
    group_name = data.get("join_group_name")
    full_name = data.get("join_full_name")
    if not group_name or not full_name:
        await state.clear()
        await message.answer(
            t("error_generic", lang), reply_markup=ReplyKeyboardRemove()
        )
        return

    phone = _normalize_phone(message.contact.phone_number)
    username = message.from_user.username
    await state.clear()

    request_id = await create_join_request(
        user_id, username, full_name, phone, group_name, lang
    )
    await message.answer(
        _with_signature(
            t(
                "join_request_sent",
                lang,
                group=html.escape(group_name),
                full_name=html.escape(full_name),
                phone=html.escape(phone),
            ),
            lang,
        ),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )

    sheets_mgr = sheets or get_sheets_manager()
    group = await sheets_mgr.a_get_group(group_name)
    recipient_ids: list[int] = []
    if group:
        raw_tid = str(group.get("Ustoz_Chat_ID", "")).strip()
        if raw_tid.isdigit():
            recipient_ids.append(int(raw_tid))
    for admin_id in ADMIN_IDS:
        if admin_id not in recipient_ids:
            recipient_ids.append(admin_id)

    tg_display = (
        f"@{html.escape(username)}" if username else f"<code>{user_id}</code>"
    )
    for rec_id in recipient_ids:
        rec_lang = await get_user_lang(rec_id)
        try:
            await message.bot.send_message(
                chat_id=rec_id,
                text=t(
                    "join_approval_card",
                    rec_lang,
                    group=html.escape(group_name),
                    full_name=html.escape(full_name),
                    phone=html.escape(phone),
                    tg=tg_display,
                ),
                reply_markup=join_approval_kb(request_id, rec_lang),
                parse_mode="HTML",
            )
        except Exception:
            pass


@router.message(GroupJoinStates.sharing_phone)
async def msg_join_phone_fallback(message: Message) -> None:
    if message.from_user:
        lang = await get_user_lang(message.from_user.id)
        await message.answer(
            t("join_use_contact_button", lang), reply_markup=join_share_phone_kb(lang)
        )


async def _can_process_join_request(
    user_id: int, group_name: str, sheets: SheetsManager
) -> bool:
    if user_id in ADMIN_IDS or await _get_dynamic_admin(user_id):
        return True
    group = await sheets.a_get_group(group_name)
    return bool(
        group and str(group.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
    )


@router.callback_query(F.data.startswith("join_approve:"))
async def cb_join_approve(
    callback: CallbackQuery, sheets: Optional[SheetsManager] = None
) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    parts = callback.data.split(":")
    try:
        request_id = int(parts[1])
    except (ValueError, IndexError):
        await callback.answer()
        return
    enroll_mode = parts[2] if len(parts) > 2 and parts[2] in {"full", "new"} else None

    req = await get_join_request(request_id)
    if not req:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return
    sheets_mgr = sheets or get_sheets_manager()
    if not await _can_process_join_request(user_id, req["group_name"], sheets_mgr):
        await callback.answer(t("join_no_permission", lang), show_alert=True)
        return

    # Mid-cycle enrollment: when lessons of the active cycle already passed, the
    # Admin / Teacher first chooses how the new student joins (nothing is saved yet).
    if enroll_mode is None and str(req.get("status") or "") == "pending":
        try:
            elapsed = await sheets_mgr.a_get_active_cycle_elapsed_info(req["group_name"])
        except Exception:
            logger.exception("Elapsed-lesson lookup failed for %s", req["group_name"])
            elapsed = {}
        if int(elapsed.get("past_dates_count") or 0) > 0:
            try:
                await callback.message.edit_text(
                    t(
                        "enroll_choice_prompt",
                        lang,
                        group=html.escape(req["group_name"]),
                        cycle_title=html.escape(str(elapsed.get("cycle_title") or "—")),
                        past_count=int(elapsed.get("past_dates_count") or 0),
                        student_name=html.escape(req["full_name"]),
                    ),
                    reply_markup=enroll_choice_kb(
                        f"join_approve:{request_id}:full",
                        f"join_approve:{request_id}:new",
                        lang,
                        extra_row=(t("join_btn_reject", lang), f"join_reject:{request_id}"),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("Could not show enrollment choice for request %s", request_id)
            await callback.answer()
            return
    resolved_req = await resolve_join_request(request_id, "approved")
    if not resolved_req:
        await callback.answer(t("join_already_processed", lang), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    tg_username = resolved_req.get("student_username")
    tg_formatted = f"@{tg_username}" if tg_username else ""
    try:
        created_student = await asyncio.to_thread(
            sheets_mgr.add_student,
            resolved_req["full_name"],
            resolved_req["group_name"],
            resolved_req["phone"],
            tg_formatted,
            "",
            "O'qiyapti",
        )
        student_id = created_student["Talaba_ID"]
        await sheets_mgr.a_link_student_chat_id(
            student_id, resolved_req["student_telegram_id"], False, tg_username
        )
        enroll_info = await sheets_mgr.a_enroll_student_in_active_cycle(
            resolved_req["group_name"],
            student_id,
            resolved_req["full_name"],
            enroll_mode,
        )
        schedule_group_initial_notice(callback.bot, resolved_req["group_name"])
    except Exception as exc:
        err_text = (
            _lt("rate_limit_busy", lang)
            if _is_rate_limit_error(exc)
            else t("error_generic", lang)
        )
        await callback.answer(err_text, show_alert=True)
        return

    student_tg_id = int(resolved_req["student_telegram_id"])
    student_lang = resolved_req.get("student_lang") or "latn"
    existing_roles = await get_user_roles(student_tg_id)
    if "student" not in existing_roles:
        existing_roles.append("student")
    await upsert_user(
        student_tg_id,
        role="student",
        linked_student_id=student_id,
        full_name=resolved_req["full_name"],
        lang=student_lang,
        roles=existing_roles,
        active_role="student",
    )

    bot_me = await callback.bot.get_me()
    parent_link = f"https://t.me/{bot_me.username}?start=par_{student_id}"
    try:
        approved_card = t(
            "join_approved_card",
            lang,
            full_name=html.escape(resolved_req["full_name"]),
            student_id=html.escape(student_id),
            group=html.escape(resolved_req["group_name"]),
        )
        parent_note = (
            f"\n\n👨‍👩‍👧 Ota-ona taklif havolasi:\n<code>{html.escape(parent_link)}</code>"
            if lang == "latn"
            else f"\n\n👨‍👩‍👧 Ота-она таклиф ҳаволаси:\n<code>{html.escape(parent_link)}</code>"
        )
        enroll_note = ""
        if enroll_info.get("past_dates_count") and enroll_info.get("mode") == "full":
            enroll_note = "\n\n" + t(
                "enroll_result_full",
                lang,
                marked=int(enroll_info.get("marked") or 0),
                amount=format_uzs(
                    await get_group_monthly_fee(sheets_mgr, resolved_req["group_name"])
                ),
            )
        elif enroll_info.get("past_dates_count") and enroll_info.get("mode") == "new":
            enroll_note = "\n\n" + t(
                "enroll_result_new",
                lang,
                remaining=int(enroll_info.get("remaining_lessons") or 0),
                amount=format_uzs(int(enroll_info.get("custom_amount") or 0)),
            )
        await callback.message.edit_text(
            f"{approved_card}{enroll_note}{parent_note}", parse_mode="HTML"
        )
    except Exception:
        pass

    has_dual = await has_dual_student_parent_role(student_tg_id)
    try:
        stu_msg = t(
            "join_approved_student",
            student_lang,
            full_name=html.escape(resolved_req["full_name"]),
            group=html.escape(resolved_req["group_name"]),
            student_id=html.escape(student_id),
        )
        parent_fwd = (
            f"\n\n👨‍👩‍👧 Ota-onangiz uchun botga ulanish havolasi:\n<code>{html.escape(parent_link)}</code>"
            if student_lang == "latn"
            else f"\n\n👨‍👩‍👧 Ота-онангиз учун ботга уланиш ҳаволаси:\n<code>{html.escape(parent_link)}</code>"
        )
        await callback.bot.send_message(
            chat_id=student_tg_id,
            text=_with_signature(f"{stu_msg}{parent_fwd}", student_lang),
            reply_markup=build_main_menu("student", student_lang, has_dual_role=has_dual),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("join_reject:"))
async def cb_join_reject(
    callback: CallbackQuery, sheets: Optional[SheetsManager] = None
) -> None:
    if not callback.from_user or not callback.data or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    try:
        request_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer()
        return

    req = await get_join_request(request_id)
    if not req:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return
    if not await _can_process_join_request(
        user_id, req["group_name"], sheets or get_sheets_manager()
    ):
        await callback.answer(t("join_no_permission", lang), show_alert=True)
        return
    resolved_req = await resolve_join_request(request_id, "rejected")
    if not resolved_req:
        await callback.answer(t("join_already_processed", lang), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return

    try:
        await callback.message.edit_text(
            t(
                "join_rejected_card",
                lang,
                full_name=html.escape(resolved_req["full_name"]),
                group=html.escape(resolved_req["group_name"]),
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    student_lang = resolved_req.get("student_lang") or "latn"
    try:
        await callback.bot.send_message(
            chat_id=resolved_req["student_telegram_id"],
            text=_with_signature(
                t(
                    "join_rejected_student",
                    student_lang,
                    group=html.escape(resolved_req["group_name"]),
                ),
                student_lang,
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()


# ----------------------------------------------------------------------
# 5. Personal Profile Viewing & Editing (⚙️ Shaxsiy ma'lumotlar)
# ----------------------------------------------------------------------


async def _build_profile_card(
    user_id: int,
    tg_username: Optional[str],
    lang: str,
    sheets: SheetsManager,
) -> Optional[tuple[str, str, dict[str, Any]]]:
    resolved = await _resolve_user_role(user_id, "", lang, sheets)
    if not resolved or resolved["role"] not in {"admin", "teacher", "student", "parent"}:
        return None
    role = resolved["role"]
    tg_display = f"@{tg_username}" if tg_username else "—"

    if role == "admin":
        profile = await get_user_profile(user_id) or {}
        dyn_adm = await _get_dynamic_admin(user_id) or {}
        db_user = await get_user(user_id) or {}
        sheet_t = None
        try:
            sheet_t = await asyncio.to_thread(
                _sync_get_teacher_sheet_record, sheets, user_id
            )
        except Exception:
            sheet_t = None
        full_name = (
            str(profile.get("full_name") or "").strip()
            or str(dyn_adm.get("full_name") or "").strip()
            or str(db_user.get("full_name") or "").strip()
            or (str(sheet_t.get("F.I.O.") or "").strip() if sheet_t else "")
            or resolved.get("full_name")
            or "—"
        )
        phone = (
            str(profile.get("phone") or "").strip()
            or str(dyn_adm.get("phone") or "").strip()
            or (str(sheet_t.get("Telefon") or "").strip() if sheet_t else "")
            or "—"
        )
        card = t(
            "profile_view_admin",
            lang,
            user_id=user_id,
            full_name=html.escape(full_name),
            phone=html.escape(phone),
            tg=html.escape(tg_display),
        )
        return role, card, {"current_name": full_name, "current_phone": phone}

    if role == "teacher":
        sheet_t = await asyncio.to_thread(
            _sync_get_teacher_sheet_record, sheets, user_id
        )
        db_t = await get_teacher_by_telegram_id(user_id)
        meta_t = await _get_teacher_meta_by_tg(user_id)
        teacher_id = (
            (sheet_t.get("Ustoz_ID") if sheet_t else None)
            or (db_t.get("invite_code") if db_t else None)
            or str(user_id)
        )
        full_name = (
            (sheet_t.get("F.I.O.") if sheet_t else None)
            or (db_t.get("full_name") if db_t else None)
            or resolved["full_name"]
            or "—"
        )
        phone = (
            (sheet_t.get("Telefon") if sheet_t else None)
            or (meta_t.get("phone") if meta_t else None)
            or "—"
        )
        tg_val = (
            (sheet_t.get("TG_Username") if sheet_t else None)
            or (
                f"@{meta_t['username']}"
                if meta_t and meta_t.get("username")
                else None
            )
            or tg_display
        )
        card = t(
            "profile_view_teacher",
            lang,
            teacher_id=html.escape(teacher_id),
            full_name=html.escape(full_name),
            phone=html.escape(phone),
            tg=html.escape(tg_val),
        )
        return role, card, {"teacher_id": teacher_id}

    if role == "student":
        stu_list = await sheets.a_get_students_by_chat_id(user_id)
        db_user = await get_user(user_id)
        student = (
            stu_list[0]
            if stu_list
            else (
                await sheets.a_get_student_by_id(db_user["linked_student_id"])
                if db_user and db_user.get("linked_student_id")
                else None
            )
        )
        if not student:
            return None
        card = t(
            "profile_view_student",
            lang,
            student_id=html.escape(str(student.get("Talaba_ID") or "")),
            full_name=html.escape(str(student.get("F.I.O.") or "") or "—"),
            group=html.escape(str(student.get("Guruh") or "") or "—"),
            phone=html.escape(str(student.get("Talaba_Tel") or "") or "—"),
            tg=html.escape(str(student.get("Talaba_TG") or "") or tg_display),
        )
        return role, card, {
            "student_id": student.get("Talaba_ID", ""),
            "group_name": student.get("Guruh", ""),
        }

    p_meta = await _get_parent_meta(user_id)
    children = await sheets.a_get_children_by_parent_chat_id(user_id)
    found = await asyncio.to_thread(
        _sync_find_student_by_any_chat_id, sheets, user_id
    )
    db_user = await get_user(user_id)
    student = (
        children[0]
        if children
        else (
            found[0]
            if found
            else (
                await sheets.a_get_student_by_id(db_user["linked_student_id"])
                if db_user and db_user.get("linked_student_id")
                else None
            )
        )
    )
    if not student:
        return None
    p_type = (
        (p_meta.get("parent_type") if p_meta else None)
        or (found[2] if found and found[2] else "father")
    )
    if p_type not in {"father", "mother"}:
        p_type = "father"
    prefix = "Onasi" if p_type == "mother" else "Otasi"
    p_name = (
        str(student.get(f"{prefix}_FIO") or "").strip()
        or (p_meta.get("full_name") if p_meta else "")
        or (db_user.get("full_name") if db_user else "")
        or "—"
    )
    p_phone = (
        str(student.get(f"{prefix}_Tel") or "").strip()
        or (p_meta.get("phone") if p_meta else "")
        or str(student.get("OtaOna_Tel") or "").strip()
        or "—"
    )
    parent_role_label = t(
        "parent_label_mother" if p_type == "mother" else "parent_label_father",
        lang,
    )
    if len(children) > 1:
        stu_display = ", ".join(
            f"{c.get('F.I.O.', '') or c.get('Talaba_ID', '')} ({c.get('Guruh', '') or '—'})"
            for c in children
        )
        grp_display = f"{len(children)} ta" if lang == "latn" else f"{len(children)} та"
    else:
        stu_display = str(student.get("F.I.O.") or "") or "—"
        grp_display = str(student.get("Guruh") or "") or "—"

    card = t(
        "profile_view_parent",
        lang,
        parent_role=html.escape(parent_role_label),
        full_name=html.escape(p_name),
        phone=html.escape(p_phone),
        student_name=html.escape(stu_display),
        group=html.escape(grp_display),
    )
    return role, card, {
        "student_id": student.get("Talaba_ID", ""),
        "student_ids": [c.get("Talaba_ID", "") for c in children if c.get("Talaba_ID")]
        or [student.get("Talaba_ID", "")],
        "parent_type": p_type,
        "group_name": student.get("Guruh", ""),
        "current_name": p_name,
        "current_phone": p_phone,
    }


@router.message(F.chat.type == ChatType.PRIVATE, F.text.in_(PROFILE_MENU_TEXTS))
async def handle_profile_menu(
    message: Message,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    await state.clear()
    try:
        built = await _build_profile_card(
            user_id,
            message.from_user.username,
            lang,
            sheets or get_sheets_manager(),
        )
    except Exception as exc:
        logger.exception("Error loading profile for user_id=%s", user_id)
        err_text = (
            _lt("rate_limit_busy", lang)
            if _is_rate_limit_error(exc)
            else t("error_generic", lang)
        )
        await message.answer(err_text, parse_mode="HTML")
        return
    if not built:
        await message.answer(
            _with_signature(t("unregistered_user", lang), lang), parse_mode="HTML"
        )
        return
    role, card_text, meta = built
    await state.set_state(ProfileEditStates.viewing_profile)
    await state.update_data(prof_role=role, prof_meta=meta)
    await message.answer(
        card_text, reply_markup=profile_actions_kb(lang, role=role), parse_mode="HTML"
    )


@router.callback_query(StateFilter(ProfileEditStates), F.data == "profile_edit:close")
async def cb_profile_close(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user and callback.message:
        lang = await get_user_lang(callback.from_user.id)
        await state.clear()
        try:
            await callback.message.edit_text(t("fsm_cancelled", lang))
        except Exception:
            pass
    await callback.answer()


@router.callback_query(StateFilter(ProfileEditStates), F.data == "profile_edit:back")
async def cb_profile_back(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    built = await _build_profile_card(
        user_id,
        callback.from_user.username,
        lang,
        sheets or get_sheets_manager(),
    )
    if not built:
        await state.clear()
        await callback.answer()
        return
    role, card_text, meta = built
    await state.set_state(ProfileEditStates.viewing_profile)
    await state.update_data(prof_role=role, prof_meta=meta)
    await callback.message.edit_text(
        card_text, reply_markup=profile_actions_kb(lang, role=role), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(
    ProfileEditStates.viewing_profile, F.data == "profile_edit:role"
)
async def cb_profile_role_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Parent profile → 🔄 Otasi / Onasi rolini almashtirish: show the picker."""
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    data = await state.get_data()
    if data.get("prof_role") != "parent":
        await callback.answer()
        return
    current = str((data.get("prof_meta") or {}).get("parent_type") or "father")
    current_label = t(
        "btn_parent_mother" if current == "mother" else "btn_parent_father", lang
    )
    await callback.message.edit_text(
        t("profile_role_pick", lang, current_role=html.escape(current_label)),
        reply_markup=profile_parent_role_kb(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    ProfileEditStates.viewing_profile, F.data.startswith("profile_role:")
)
async def cb_profile_role_selected(
    callback: CallbackQuery,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    """
    Swaps the parent's FIO / Tel / Chat_ID between Otasi_* and Onasi_* on every
    linked child (Baza_Talabalar), updates SQLite parent_meta, and immediately
    shows the new specific login greeting.
    """
    if not callback.from_user or not callback.message or not callback.data:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    choice = callback.data.split(":", 1)[1]
    if choice not in {"father", "mother"}:
        await callback.answer()
        return
    data = await state.get_data()
    if data.get("prof_role") != "parent":
        await callback.answer()
        return
    sheets_mgr = sheets or get_sheets_manager()
    current = str((data.get("prof_meta") or {}).get("parent_type") or "father")
    new_label = t(
        "btn_parent_mother" if choice == "mother" else "btn_parent_father", lang
    )
    if choice == current:
        plain = re.sub(
            r"<[^>]+>", "", t("profile_role_same", lang, role=new_label)
        )
        await callback.answer(plain, show_alert=True)
        return

    try:
        await sheets_mgr.a_switch_parent_role(user_id, choice)
        await _update_parent_meta_type(user_id, choice)
        built = await _build_profile_card(
            user_id, callback.from_user.username, lang, sheets_mgr
        )
    except Exception as exc:
        logger.exception("Parent role switch failed for user_id=%s", user_id)
        err_text = (
            _lt("rate_limit_busy", lang)
            if _is_rate_limit_error(exc)
            else t("error_generic", lang)
        )
        await callback.answer(re.sub(r"<[^>]+>", "", err_text), show_alert=True)
        return

    has_dual = await has_dual_student_parent_role(user_id)
    if built:
        new_role, card_text, new_meta = built
        await state.set_state(ProfileEditStates.viewing_profile)
        await state.update_data(prof_role=new_role, prof_meta=new_meta)
        await callback.message.edit_text(
            card_text,
            reply_markup=profile_actions_kb(lang, role=new_role),
            parse_mode="HTML",
        )
    display_name = str(
        ((built[2] if built else {}) or {}).get("current_name")
        or callback.from_user.full_name
        or ""
    )
    greeting = await _welcome_menu_text(
        user_id, display_name, "parent", lang, sheets_mgr
    )
    await callback.message.answer(
        _with_signature(
            f"{t('profile_role_switched', lang, role=html.escape(new_label))}\n\n{greeting}",
            lang,
        ),
        reply_markup=build_main_menu("parent", lang, has_dual_role=has_dual),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    ProfileEditStates.viewing_profile, F.data == "profile_edit:name"
)
async def cb_profile_edit_name_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(ProfileEditStates.entering_full_name)
    await callback.message.edit_text(
        t("profile_enter_new_name", lang),
        reply_markup=profile_step_nav_kb(
            lang, back_cb="profile_edit:back", cancel_cb="profile_edit:close"
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    ProfileEditStates.viewing_profile, F.data == "profile_edit:phone"
)
async def cb_profile_edit_phone_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    await state.set_state(ProfileEditStates.sharing_phone)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        t("profile_share_new_phone", lang),
        reply_markup=share_phone_reply_kb(lang, include_back=True),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(StateFilter(ProfileEditStates), F.text.in_(CANCEL_TEXTS))
async def msg_profile_cancel(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    role = (await state.get_data()).get("prof_role", "student")
    has_dual = await has_dual_student_parent_role(user_id)
    await state.clear()
    await message.answer(
        t("fsm_cancelled", lang),
        reply_markup=build_main_menu(role, lang, has_dual_role=has_dual),
    )


@router.message(ProfileEditStates.sharing_phone, F.text.in_(BACK_TEXTS))
async def msg_profile_phone_back(
    message: Message,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    built = await _build_profile_card(
        user_id,
        message.from_user.username,
        lang,
        sheets or get_sheets_manager(),
    )
    if not built:
        await state.clear()
        return
    role, card_text, meta = built
    has_dual = await has_dual_student_parent_role(user_id)
    await state.set_state(ProfileEditStates.viewing_profile)
    await state.update_data(prof_role=role, prof_meta=meta)
    await message.answer(
        "↩️", reply_markup=build_main_menu(role, lang, has_dual_role=has_dual)
    )
    await message.answer(
        card_text, reply_markup=profile_actions_kb(lang, role=role), parse_mode="HTML"
    )


@router.message(ProfileEditStates.entering_full_name)
async def msg_profile_save_name(
    message: Message,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if (message.text or "").strip() in BACK_TEXTS:
        await msg_profile_phone_back(message, state, sheets)
        return
    new_name = _validate_full_name(message.text or "")
    if not new_name:
        await message.answer(
            t("student_reg_invalid_name", lang),
            reply_markup=profile_step_nav_kb(
                lang, back_cb="profile_edit:back", cancel_cb="profile_edit:close"
            ),
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    role = data.get("prof_role", "")
    meta = data.get("prof_meta", {})
    sheets_mgr = sheets or get_sheets_manager()
    existing_roles = await get_user_roles(user_id)

    await upsert_user_profile(user_id, full_name=new_name)

    if role == "admin":
        await upsert_user(user_id, role="admin", full_name=new_name, lang=lang)
        # An admin may also teach groups ("O'zimni ustoz qilish") → keep Ustozlar in sync
        try:
            await asyncio.to_thread(
                _sync_update_teacher_sheet_fields, sheets_mgr, user_id, new_name, None
            )
        except Exception:
            logger.exception("Admin profile: failed syncing Ustozlar name")
    elif role == "teacher":
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE teachers SET full_name = ? WHERE telegram_id = ?;",
                (new_name, user_id),
            )
            await db.commit()
        await upsert_user(user_id, role="teacher", full_name=new_name, lang=lang)
        if not await asyncio.to_thread(
            _sync_update_teacher_sheet_fields, sheets_mgr, user_id, new_name, None
        ):
            t_meta = await _get_teacher_meta_by_tg(user_id)
            await asyncio.to_thread(
                _sync_upsert_teacher_sheet,
                sheets_mgr,
                meta.get("teacher_id", ""),
                new_name,
                (t_meta.get("phone") if t_meta else "") or "—",
                message.from_user.username,
                user_id,
                None,
            )
    elif role == "student":
        sid, grp = meta.get("student_id", ""), meta.get("group_name", "")
        # Every enrollment row bound to this Telegram account (dual-enrollment)
        # is updated in Baza_Talabalar and propagated to all {Group}_{Year} tabs.
        updated_sids = await sheets_mgr.a_update_student_self_profile(
            user_id, full_name=new_name
        )
        if sid and sid not in updated_sids:
            await asyncio.to_thread(
                sheets_mgr.update_student, sid, {"F.I.O.": new_name}
            )
            await asyncio.to_thread(
                _sync_update_student_name_in_active_cycles,
                sheets_mgr,
                grp,
                sid,
                new_name,
            )
            updated_sids.append(sid)
        for upd_sid in updated_sids:
            try:
                await update_legacy_debts_student_name(upd_sid, new_name)
            except Exception:
                logger.exception("Failed updating legacy debt name for %s", upd_sid)
        if "student" not in existing_roles:
            existing_roles.append("student")
        await upsert_user(
            user_id,
            role="student",
            full_name=new_name,
            lang=lang,
            roles=existing_roles,
            active_role="student",
        )
    elif role == "parent":
        sids = list(meta.get("student_ids") or [])
        if not sids and meta.get("student_id"):
            sids = [meta["student_id"]]
        p_type = meta.get("parent_type", "father")
        # Update the parent's name on EVERY child row bound to this chat id
        updated_parent_sids = await sheets_mgr.a_update_parent_self_profile(
            user_id, full_name=new_name
        )
        for sid in sids:
            if sid and sid not in updated_parent_sids:
                await asyncio.to_thread(
                    _sync_update_parent_profile_in_sheet,
                    sheets_mgr,
                    sid,
                    p_type,
                    new_name,
                    None,
                    user_id,
                )
        if sids:
            await _save_parent_meta(
                user_id, sids[0], p_type, new_name, meta.get("current_phone", "")
            )
        if "parent" not in existing_roles:
            existing_roles.append("parent")
        await upsert_user(
            user_id,
            role="parent",
            full_name=new_name,
            lang=lang,
            roles=existing_roles,
            active_role="parent",
        )

    has_dual = await has_dual_student_parent_role(user_id)
    await state.clear()
    await message.answer(
        _with_signature(t("profile_updated", lang), lang),
        reply_markup=build_main_menu(role, lang, has_dual_role=has_dual),
        parse_mode="HTML",
    )
    built = await _build_profile_card(
        user_id, message.from_user.username, lang, sheets_mgr
    )
    if built:
        new_role, card_text, new_meta = built
        await state.set_state(ProfileEditStates.viewing_profile)
        await state.update_data(prof_role=new_role, prof_meta=new_meta)
        await message.answer(
            card_text, reply_markup=profile_actions_kb(lang, role=new_role), parse_mode="HTML"
        )


@router.message(ProfileEditStates.sharing_phone, F.contact)
async def msg_profile_save_phone(
    message: Message,
    state: FSMContext,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not message.from_user or not message.contact:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if message.contact.user_id and message.contact.user_id != user_id:
        await message.answer(
            t("own_contact_only", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )
        return

    phone = _normalize_phone(message.contact.phone_number)
    data = await state.get_data()
    role = data.get("prof_role", "")
    meta = data.get("prof_meta", {})
    sheets_mgr = sheets or get_sheets_manager()

    await upsert_user_profile(user_id, phone=phone)

    if role == "admin":
        try:
            await asyncio.to_thread(
                _sync_update_teacher_sheet_fields, sheets_mgr, user_id, None, phone
            )
        except Exception:
            logger.exception("Admin profile: failed syncing Ustozlar phone")
    elif role == "teacher":
        t_meta = await _get_teacher_meta_by_tg(user_id)
        if t_meta:
            await _upsert_teacher_meta(
                t_meta["invite_code"],
                telegram_id=user_id,
                phone=phone,
                username=message.from_user.username,
            )
        if not await asyncio.to_thread(
            _sync_update_teacher_sheet_fields, sheets_mgr, user_id, None, phone
        ):
            db_t = await get_teacher_by_telegram_id(user_id)
            await asyncio.to_thread(
                _sync_upsert_teacher_sheet,
                sheets_mgr,
                meta.get("teacher_id", ""),
                (
                    db_t.get("full_name")
                    if db_t
                    else message.from_user.full_name
                )
                or "Ustoz",
                phone,
                message.from_user.username,
                user_id,
                None,
            )
    elif role == "student":
        sid = meta.get("student_id", "")
        updated_sids = await sheets_mgr.a_update_student_self_profile(
            user_id, phone=phone
        )
        if sid and sid not in updated_sids:
            await asyncio.to_thread(
                sheets_mgr.update_student, sid, {"Talaba_Tel": phone}
            )
    elif role == "parent":
        sids = list(meta.get("student_ids") or [])
        if not sids and meta.get("student_id"):
            sids = [meta["student_id"]]
        p_type = meta.get("parent_type", "father")
        updated_parent_sids = await sheets_mgr.a_update_parent_self_profile(
            user_id, phone=phone
        )
        for sid in sids:
            if sid and sid not in updated_parent_sids:
                await asyncio.to_thread(
                    _sync_update_parent_profile_in_sheet,
                    sheets_mgr,
                    sid,
                    p_type,
                    None,
                    phone,
                    user_id,
                )
        if sids:
            await _save_parent_meta(
                user_id, sids[0], p_type, meta.get("current_name", ""), phone
            )

    has_dual = await has_dual_student_parent_role(user_id)
    await state.clear()
    await message.answer(
        _with_signature(t("profile_updated", lang), lang),
        reply_markup=build_main_menu(role, lang, has_dual_role=has_dual),
        parse_mode="HTML",
    )
    built = await _build_profile_card(
        user_id, message.from_user.username, lang, sheets_mgr
    )
    if built:
        new_role, card_text, new_meta = built
        await state.set_state(ProfileEditStates.viewing_profile)
        await state.update_data(prof_role=new_role, prof_meta=new_meta)
        await message.answer(
            card_text, reply_markup=profile_actions_kb(lang, role=new_role), parse_mode="HTML"
        )


@router.message(ProfileEditStates.sharing_phone)
async def msg_profile_phone_fallback(message: Message) -> None:
    if message.from_user:
        lang = await get_user_lang(message.from_user.id)
        await message.answer(
            t("use_contact_button_only", lang),
            reply_markup=share_phone_reply_kb(lang, include_back=True),
        )


# ----------------------------------------------------------------------
# Telegram Group Chat Linking (/link_group <Group_Name>)
# ----------------------------------------------------------------------


async def _find_group_linked_to_chat(
    sheets_mgr: SheetsManager, chat_id: int
) -> Optional[str]:
    """Name of the group whose Guruh_TG_Chat_ID (Guruhlar or SQLite) is this chat."""
    target = str(chat_id)
    try:
        for grp in await asyncio.to_thread(sheets_mgr.get_all_groups):
            if normalize_chat_id_text(grp.get("Guruh_TG_Chat_ID")) == target:
                return str(grp.get("Guruh_Nomi") or "").strip() or None
    except Exception:
        logger.exception("link_group: could not read Guruhlar")
    try:
        return await get_group_name_by_tg_chat_id(target)
    except Exception:
        logger.exception("link_group: could not read SQLite group chats")
        return None


@router.message(Command("link_group"))
async def cmd_link_group(
    message: Message,
    command: CommandObject,
    sheets: Optional[SheetsManager] = None,
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if message.chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
        await message.reply(t("link_group_private_error", lang), parse_mode="HTML")
        return

    sheets_mgr = sheets or get_sheets_manager()
    is_admin_sender = user_id in ADMIN_IDS or bool(await _get_dynamic_admin(user_id))
    group_name = (command.args or "").strip()

    if not is_admin_sender:
        # Regular members (students / parents) who tap /link_group: never an
        # error wall — tell them politely whether this chat is already linked.
        linked_group = await _find_group_linked_to_chat(sheets_mgr, message.chat.id)
        if linked_group:
            await message.reply(t("link_group_already_linked", lang), parse_mode="HTML")
            return
        named_group = await sheets_mgr.a_get_group(group_name) if group_name else None
        is_group_teacher = bool(named_group) and (
            str(named_group.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
        )
        if not is_group_teacher:
            await message.reply(t("link_group_admin_only", lang), parse_mode="HTML")
            return

    if not group_name:
        await message.reply(t("link_group_usage", "latn"), parse_mode="HTML")
        return

    group = await sheets_mgr.a_get_group(group_name)
    if not group:
        await message.reply(
            t("link_group_not_found", "latn", group=html.escape(group_name)),
            parse_mode="HTML",
        )
        return

    if not (
        is_admin_sender
        or str(group.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
    ):
        await message.reply(t("link_group_no_permission", "latn"), parse_mode="HTML")
        return

    canonical_group = group["Guruh_Nomi"]
    await sheets_mgr.a_link_group_tg_chat(canonical_group, message.chat.id)
    await set_group_tg_chat_id(canonical_group, str(message.chat.id))
    await message.reply(
        _with_signature(
            t("link_group_success", "latn", group=html.escape(canonical_group)),
            "latn",
        ),
        parse_mode="HTML",
    )
    # Start the persistent 1-hour initial notice timer (if none yet / unsent).
    schedule_group_initial_notice(message.bot, canonical_group)
