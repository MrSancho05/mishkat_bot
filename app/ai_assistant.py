"""
Mishkat AI assistant (Google Gemini via the google-genai SDK).

* Only for the ``admin`` and ``teacher`` roles (current active role). Students,
  parents and guests never reach Gemini, so no API quota is spent on them.
* Strictly limited to Mishkat Nodavlat Ta'lim Muassasasi operations; anything
  else is rejected in one sentence (often locally, without an API call).
* Read tools query Google Sheets / SQLite through the existing helpers.
* Write tools NEVER change data: they create a pending draft (10-minute TTL,
  bound to the creator's chat) shown as a card with "✅ Tasdiqlash" /
  "❌ Bekor qilish". Only the confirm button runs the existing sheets.py /
  database.py logic (incl. Audit_Log and notifications) — see execute_draft().
"""

import asyncio
import difflib
import html
import json
import logging
import re
import secrets
import time as _time
from collections import deque
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Optional

from app import database
from app.config import ADMIN_IDS, AI_ENABLED, GEMINI_API_KEY, GEMINI_MODEL
from app.database import (
    AUDIT_GROUP_EDITED,
    AUDIT_STUDENT_RESTORED,
    AUDIT_STUDENT_TO_RESERVE,
    create_ai_draft,
    get_group_topics_history,
    get_lead,
    get_recent_leads,
    get_teacher_by_telegram_id,
    get_user,
    is_dynamic_admin,
    log_audit_event,
    mark_lead_contacted,
    save_lesson_topic,
)
from app.sheets import RESERVE_GROUP_NAME, get_sheets_manager, parse_weekdays
from app.utils import (
    AGREED_LESSON_TIME,
    LESSON_DAY_ABBR,
    format_lesson_time_display,
    is_agreed_lesson_time,
    normalize_session_times,
    now_tashkent,
    parse_lesson_sessions,
    tashkent_now_str,
    today_tashkent,
)

logger = logging.getLogger(__name__)

AI_ROLES = {"admin", "teacher"}
RATE_LIMIT_SECONDS = 3.0
MAX_CONCURRENT_REQUESTS = 2
MAX_OUTPUT_TOKENS = 450
TEMPERATURE = 0.2
MEMORY_TURNS = 4
MEMORY_TTL_SECONDS = 600
DRAFT_TTL_MINUTES = 10
MAX_TOOL_ROUNDS = 4
MAX_VOICE_BYTES = 15 * 1024 * 1024
TOOL_RESULT_CHAR_LIMIT = 6000

OFF_TOPIC_REPLY = {
    "latn": (
        "⚠️ Men faqat Mishkat o'quv markazi guruhlari, dars jadvali, to'lovlar va "
        "talabalar bo'yicha ishga oid savollarga javob beraman."
    ),
    "cyrl": (
        "⚠️ Мен фақат Мишкат ўқув маркази гуруҳлари, дарс жадвали, тўловлар ва "
        "талабалар бўйича ишга оид саволларга жавоб бераман."
    ),
}

TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "busy_wait": "⏳ Iltimos, 3 soniya kutib qayta yozing.",
        "api_busy": "⏳ AI yordamchi hozir band. Birozdan so‘ng qayta urinib ko‘ring.",
        "api_error": "⚠️ AI yordamchi vaqtincha ishlamayapti. Bot menyusidan foydalaning.",
        "empty_answer": "ℹ️ Savolni aniqroq yozib ko‘ring (masalan: guruh yoki talaba nomi bilan).",
        "voice_too_big": "⚠️ Ovozli xabar juda katta (15 MB dan oshmasin).",
        "draft_hint": "Ma’lumotlar faqat «✅ Tasdiqlash» bosilgandan keyin o‘zgaradi.",
        "btn_confirm": "✅ Tasdiqlash",
        "btn_cancel": "❌ Bekor qilish",
        "draft_expired": "⌛️ Bu qoralama eskirgan (10 daqiqa). So‘rovni qayta yuboring.",
        "draft_done": "ℹ️ Bu qoralama allaqachon ko‘rib chiqilgan.",
        "draft_forbidden": "⛔️ Bu qoralama sizga tegishli emas.",
        "draft_not_found": "ℹ️ Qoralama topilmadi.",
        "draft_cancelled": "❌ Bekor qilindi. Hech narsa o‘zgartirilmadi.",
        "no_permission": "⛔️ Bu amal uchun ruxsatingiz yo‘q.",
        "exec_failed": "⚠️ Amalni bajarib bo‘lmadi: {reason}",
        "title_schedule": "🗓 <b>Dars jadvalini o‘zgartirish (qoralama)</b>",
        "title_payment": "💳 <b>To‘lovni tasdiqlash (qoralama)</b>",
        "title_to_zaxira": "⏸ <b>Talabani Zaxiraga o‘tkazish (qoralama)</b>",
        "title_restore": "▶️ <b>Talabani darsga tiklash (qoralama)</b>",
        "title_lead": "📞 <b>Lid bilan bog‘lanildi (qoralama)</b>",
        "title_topic": "📝 <b>Dars mavzusini saqlash (qoralama)</b>",
        "done_schedule": "✅ <b>{group}</b> guruhi jadvali yangilandi. Xabar yuborildi: {sent} ta.",
        "done_payment": "✅ <b>{student}</b> ({group}) — <b>{cycle}</b> to‘lovi tasdiqlandi.",
        "done_to_zaxira": "✅ <b>{student}</b> Zaxiraga o‘tkazildi (avvalgi guruh: {group}).",
        "done_restore": "✅ <b>{student}</b> <b>{group}</b> guruhiga tiklandi.",
        "done_lead": "✅ Lid #{lead_id} ({name}) «Bog'lanildi» deb belgilandi.",
        "done_topic": (
            "✅ <b>{group}</b> — {date} mavzusi saqlandi. U 30 daqiqadan so‘ng "
            "avtomatik e’lon qilinadi."
        ),
        "lbl_group": "📚 Guruh",
        "lbl_student": "👤 Talaba",
        "lbl_cycle": "🗓 Sikl",
        "lbl_amount": "💰 Summa",
        "lbl_time": "⏰ Dars vaqti",
        "lbl_days": "📆 Dars kunlari",
        "lbl_count": "🔢 Oylik darslar",
        "lbl_date": "📅 Sana",
        "lbl_topic": "📝 Mavzu",
        "lbl_plan": "📋 Reja",
        "lbl_lead": "📞 Lid",
        "lbl_target": "➡️ Guruh",
    },
    "cyrl": {
        "busy_wait": "⏳ Илтимос, 3 сония кутиб қайта ёзинг.",
        "api_busy": "⏳ AI ёрдамчи ҳозир банд. Бироздан сўнг қайта уриниб кўринг.",
        "api_error": "⚠️ AI ёрдамчи вақтинча ишламаяпти. Бот менюсидан фойдаланинг.",
        "empty_answer": "ℹ️ Саволни аниқроқ ёзиб кўринг (масалан: гуруҳ ёки талаба номи билан).",
        "voice_too_big": "⚠️ Овозли хабар жуда катта (15 MB дан ошмасин).",
        "draft_hint": "Маълумотлар фақат «✅ Тасдиқлаш» босилгандан кейин ўзгаради.",
        "btn_confirm": "✅ Тасдиқлаш",
        "btn_cancel": "❌ Бекор қилиш",
        "draft_expired": "⌛️ Бу қоралама эскирган (10 дақиқа). Сўровни қайта юборинг.",
        "draft_done": "ℹ️ Бу қоралама аллақачон кўриб чиқилган.",
        "draft_forbidden": "⛔️ Бу қоралама сизга тегишли эмас.",
        "draft_not_found": "ℹ️ Қоралама топилмади.",
        "draft_cancelled": "❌ Бекор қилинди. Ҳеч нарса ўзгартирилмади.",
        "no_permission": "⛔️ Бу амал учун рухсатингиз йўқ.",
        "exec_failed": "⚠️ Амални бажариб бўлмади: {reason}",
        "title_schedule": "🗓 <b>Дарс жадвалини ўзгартириш (қоралама)</b>",
        "title_payment": "💳 <b>Тўловни тасдиқлаш (қоралама)</b>",
        "title_to_zaxira": "⏸ <b>Талабани Захирага ўтказиш (қоралама)</b>",
        "title_restore": "▶️ <b>Талабани дарсга тиклаш (қоралама)</b>",
        "title_lead": "📞 <b>Лид билан боғланилди (қоралама)</b>",
        "title_topic": "📝 <b>Дарс мавзусини сақлаш (қоралама)</b>",
        "done_schedule": "✅ <b>{group}</b> гуруҳи жадвали янгиланди. Хабар юборилди: {sent} та.",
        "done_payment": "✅ <b>{student}</b> ({group}) — <b>{cycle}</b> тўлови тасдиқланди.",
        "done_to_zaxira": "✅ <b>{student}</b> Захирага ўтказилди (аввалги гуруҳ: {group}).",
        "done_restore": "✅ <b>{student}</b> <b>{group}</b> гуруҳига тикланди.",
        "done_lead": "✅ Лид #{lead_id} ({name}) «Боғланилди» деб белгиланди.",
        "done_topic": (
            "✅ <b>{group}</b> — {date} мавзуси сақланди. У 30 дақиқадан сўнг "
            "автоматик эълон қилинади."
        ),
        "lbl_group": "📚 Гуруҳ",
        "lbl_student": "👤 Талаба",
        "lbl_cycle": "🗓 Цикл",
        "lbl_amount": "💰 Сумма",
        "lbl_time": "⏰ Дарс вақти",
        "lbl_days": "📆 Дарс кунлари",
        "lbl_count": "🔢 Ойлик дарслар",
        "lbl_date": "📅 Сана",
        "lbl_topic": "📝 Мавзу",
        "lbl_plan": "📋 Режа",
        "lbl_lead": "📞 Лид",
        "lbl_target": "➡️ Гуруҳ",
    },
}


def tr(key: str, lang: str, **kwargs: Any) -> str:
    table = TEXTS.get(lang) or TEXTS["latn"]
    template = table.get(key) or TEXTS["latn"].get(key, key)
    return template.format(**kwargs) if kwargs else template


# ----------------------------------------------------------------------
# Role gate, script detection, trivial / off-topic pre-filters
# ----------------------------------------------------------------------


async def resolve_ai_role(user_id: int) -> Optional[str]:
    """
    'admin' / 'teacher' when the user's CURRENT active role is one of them,
    otherwise None (students, parents, guests, and staff who switched their
    active role to student / parent never reach Gemini).
    """
    db_user = await get_user(user_id)
    active = str((db_user or {}).get("active_role") or (db_user or {}).get("role") or "")
    if active in {"student", "parent", "guest"}:
        return None
    is_admin_user = user_id in ADMIN_IDS
    if not is_admin_user:
        try:
            is_admin_user = await is_dynamic_admin(user_id)
        except Exception:
            is_admin_user = False
    if is_admin_user:
        return "teacher" if active == "teacher" else "admin"
    if active == "teacher":
        return "teacher"
    if await get_teacher_by_telegram_id(user_id):
        return "teacher"
    return None


def detect_script(text: str, fallback: str = "latn") -> str:
    cyr = len(re.findall(r"[Ѐ-ӿ]", text or ""))
    lat = len(re.findall(r"[A-Za-z]", text or ""))
    if cyr == 0 and lat == 0:
        return fallback if fallback in {"latn", "cyrl"} else "latn"
    return "cyrl" if cyr > lat else "latn"


def is_trivial(text: str) -> bool:
    """'+', '-', '.', '?', 'ok', emoji-only... -> no API call."""
    cleaned = (text or "").strip()
    if len(cleaned) <= 2:
        return True
    return not any(ch.isalnum() for ch in cleaned)


_WORK_HINT_RE = re.compile(
    r"guruh|гуруҳ|talaba|талаба|o.quvchi|ўқувчи|dars|дарс|to.lov|тўлов|qarz|қарз|"
    r"ustoz|устоз|lid|лид|mavzu|мавзу|jadval|жадвал|yo.qlama|йўқлама|sikl|цикл|"
    r"zaxira|захира|ota-ona|ота-она|kurs|курс|mishkat|мишкат|bot|бот|admin|админ|"
    r"student|group|lesson|payment|debt|teacher|schedule|attendance",
    re.IGNORECASE,
)
_OFF_TOPIC_RE = re.compile(
    r"ob-?havo|об-?ҳаво|weather|hazil|ҳазил|latifa|латифа|anekdot|анекдот|joke|"
    r"she.r yoz|шеър ёз|poem|futbol|футбол|football|kino|кино|film|фильм|movie|"
    r"retsept|рецепт|recipe|yangilik|янгилик|\bnews\b|siyosat|сиёсат|politic|"
    r"python|javascript|\bjava\b|\bc\+\+|\bcode\b|kod yoz|код ёз|programm|"
    r"bitcoin|kripto|крипто|crypto|valyuta kursi|dollar kursi|horoscope|munajjim|"
    r"tarjima qil|translate|qo.shiq|қўшиқ|\bsong\b|o.yin|ўйин|\bgame\b",
    re.IGNORECASE,
)


def looks_off_topic(text: str) -> bool:
    """Obvious non-work requests are rejected locally (zero tokens)."""
    cleaned = text or ""
    return bool(_OFF_TOPIC_RE.search(cleaned)) and not _WORK_HINT_RE.search(cleaned)


# ----------------------------------------------------------------------
# Rate limits & short conversation memory
# ----------------------------------------------------------------------

_last_request_at: dict[int, float] = {}
_memory: dict[int, tuple[float, deque]] = {}
_semaphore: Optional[asyncio.Semaphore] = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    return _semaphore


def check_and_mark_rate_limit(user_id: int) -> bool:
    """True = allowed now (and the slot is taken); False = too soon."""
    now_ts = _time.monotonic()
    last = _last_request_at.get(user_id)
    if last is not None and now_ts - last < RATE_LIMIT_SECONDS:
        return False
    _last_request_at[user_id] = now_ts
    return True


def _history(user_id: int) -> list[tuple[str, str]]:
    entry = _memory.get(user_id)
    if not entry:
        return []
    ts, turns = entry
    if _time.monotonic() - ts > MEMORY_TTL_SECONDS:
        _memory.pop(user_id, None)
        return []
    return list(turns)


def _remember(user_id: int, user_text: str, model_text: str) -> None:
    entry = _memory.get(user_id)
    turns = entry[1] if entry and _time.monotonic() - entry[0] <= MEMORY_TTL_SECONDS else None
    if turns is None:
        turns = deque(maxlen=MEMORY_TURNS)
    turns.append((user_text[:600], model_text[:600]))
    _memory[user_id] = (_time.monotonic(), turns)


# ----------------------------------------------------------------------
# Tool context & lookup helpers
# ----------------------------------------------------------------------


class ToolContext:
    def __init__(self, user_id: int, role: str, lang: str, actor_name: str) -> None:
        self.user_id = user_id
        self.role = role
        self.lang = lang
        self.actor_name = actor_name
        self.drafts: list[dict[str, Any]] = []
        self._groups: Optional[list[dict[str, Any]]] = None
        self._students: Optional[list[dict[str, Any]]] = None

    async def groups(self) -> list[dict[str, Any]]:
        """Groups this user may touch: all for admin, only own for teacher."""
        if self._groups is None:
            sheets = get_sheets_manager()
            self._groups = await asyncio.to_thread(
                sheets.get_groups_for_role, self.user_id, self.role == "admin"
            )
        return self._groups

    async def group_names_lower(self) -> set[str]:
        return {str(g.get("Guruh_Nomi") or "").strip().lower() for g in await self.groups()}

    async def students(self) -> list[dict[str, Any]]:
        """Students visible to this user (teacher: only their groups)."""
        if self._students is None:
            sheets = get_sheets_manager()
            rows = await asyncio.to_thread(sheets.get_all_students, None, False)
            if self.role != "admin":
                allowed = await self.group_names_lower()
                rows = [
                    s for s in rows if str(s.get("Guruh") or "").strip().lower() in allowed
                ]
            self._students = rows
        return self._students


def _norm(text: Any) -> str:
    return " ".join(str(text or "").replace("’", "'").replace("‘", "'").split()).casefold()


async def _match_group(ctx: ToolContext, query: str) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    groups = await ctx.groups()
    q = _norm(query)
    if not q:
        return None, {"error": "group_required", "available_groups": _names(groups)}
    by_name = {_norm(g.get("Guruh_Nomi")): g for g in groups}
    if q in by_name:
        return by_name[q], {}
    contains = [g for key, g in by_name.items() if q in key or key in q]
    if len(contains) == 1:
        return contains[0], {}
    close = difflib.get_close_matches(q, list(by_name), n=3, cutoff=0.6)
    if len(close) == 1:
        return by_name[close[0]], {}
    candidates = [by_name[c]["Guruh_Nomi"] for c in close] or [g["Guruh_Nomi"] for g in contains]
    if candidates:
        return None, {"error": "ambiguous_group", "candidates": candidates[:5]}
    return None, {
        "error": "group_not_found_or_not_allowed",
        "available_groups": _names(groups),
    }


def _names(groups: list[dict[str, Any]]) -> list[str]:
    return [str(g.get("Guruh_Nomi") or "") for g in groups][:40]


async def _match_student(
    ctx: ToolContext, query: str, group_name: str = ""
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    students = await ctx.students()
    if group_name:
        g_key = group_name.strip().lower()
        scoped = [
            s
            for s in students
            if str(s.get("Guruh") or "").strip().lower() == g_key
            or str(s.get("Sobiq_Guruh") or "").strip().lower() == g_key
        ]
        students = scoped or students
    q = _norm(query)
    if not q:
        return None, {"error": "student_required"}
    for s in students:
        if _norm(s.get("Talaba_ID")) == q:
            return s, {}
    q_digits = re.sub(r"\D", "", q)
    if len(q_digits) >= 7:
        phone_hits = [
            s
            for s in students
            if q_digits[-9:] and q_digits[-9:] in re.sub(r"\D", "", str(s.get("Talaba_Tel") or ""))
        ]
        if len(phone_hits) == 1:
            return phone_hits[0], {}
    scored: list[tuple[float, dict[str, Any]]] = []
    q_tokens = q.split()
    for s in students:
        name = _norm(s.get("F.I.O."))
        if not name:
            continue
        ratio = difflib.SequenceMatcher(None, q, name).ratio()
        if all(any(tok in part for part in name.split()) for tok in q_tokens):
            ratio = max(ratio, 0.9)
        scored.append((ratio, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored or scored[0][0] < 0.6:
        return None, {"error": "student_not_found_or_not_allowed"}
    best = scored[0]
    ties = [s for r, s in scored if r >= best[0] - 0.03]
    if len(ties) > 1:
        return None, {
            "error": "ambiguous_student",
            "candidates": [
                f"{s.get('F.I.O.')} ({s.get('Talaba_ID')}, {s.get('Guruh')})" for s in ties[:6]
            ],
        }
    return best[1], {}


def _parse_lesson_date(raw: str) -> Optional[date]:
    text = _norm(raw)
    today = today_tashkent()
    if text in {"bugun", "бугун", "today"}:
        return today
    if text in {"ertaga", "эртага", "tomorrow"}:
        return today + timedelta(days=1)
    if text in {"kecha", "кеча", "yesterday"}:
        return today - timedelta(days=1)
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})", text)
    if m:
        try:
            return date(today.year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def _fmt_money(amount: Any) -> str:
    return f"{int(amount or 0):,}".replace(",", " ")


# ----------------------------------------------------------------------
# READ tools
# ----------------------------------------------------------------------


async def tool_list_groups(ctx: ToolContext) -> dict[str, Any]:
    groups = await ctx.groups()
    students = await ctx.students()
    active_by_group: dict[str, int] = {}
    for s in students:
        if str(s.get("Status") or "").strip() == "O'qiyapti":
            key = str(s.get("Guruh") or "").strip().lower()
            active_by_group[key] = active_by_group.get(key, 0) + 1
    teacher_names = await _teacher_name_map()
    return {
        "groups": [
            {
                "name": g.get("Guruh_Nomi"),
                "teacher": teacher_names.get(str(g.get("Ustoz_ID") or "").strip())
                or teacher_names.get(str(g.get("Ustoz_Chat_ID") or "").strip())
                or "",
                "days": g.get("Dars_Kunlari"),
                "time": format_lesson_time_display(g.get("Dars_Vaqti"), "latn"),
                "monthly_lessons": g.get("Oylik_Dars_Soni"),
                "lessons_done": g.get("Otilgan_Dars_Hisoblagich"),
                "lessons_per_day": g.get("Kunlik_Dars_Soni") or "1",
                "monthly_fee": g.get("Oylik_Tolov_Summa"),
                "start_date": g.get("Boshlanish_Sanasi"),
                "group_chat_linked": bool(str(g.get("Guruh_TG_Chat_ID") or "").strip()),
                "active_students": active_by_group.get(
                    str(g.get("Guruh_Nomi") or "").strip().lower(), 0
                ),
            }
            for g in groups
        ]
    }


async def _teacher_name_map() -> dict[str, str]:
    try:
        teachers = await asyncio.to_thread(get_sheets_manager().get_all_teachers, False)
    except Exception:
        return {}
    result: dict[str, str] = {}
    for tch in teachers:
        name = str(tch.get("F.I.O.") or "").strip()
        for key in (tch.get("Ustoz_ID"), tch.get("Chat_ID"), tch.get("Ustoz_Chat_ID")):
            if str(key or "").strip():
                result[str(key).strip()] = name
    return result


async def tool_group_details(ctx: ToolContext, group: str = "") -> dict[str, Any]:
    grp, err = await _match_group(ctx, group)
    if not grp:
        return err
    name = grp["Guruh_Nomi"]
    sheets = get_sheets_manager()
    roster = [
        {
            "id": s.get("Talaba_ID"),
            "name": s.get("F.I.O."),
            "phone": s.get("Talaba_Tel"),
            "debt_months_raw": s.get("Qarzdor_Oylar"),
        }
        for s in await ctx.students()
        if str(s.get("Guruh") or "").strip().lower() == name.strip().lower()
        and str(s.get("Status") or "").strip() == "O'qiyapti"
    ]
    try:
        dates = await asyncio.to_thread(sheets.get_cycle_dates_with_status, name)
    except Exception:
        dates = []
    return {
        "group": name,
        "days": grp.get("Dars_Kunlari"),
        "time": format_lesson_time_display(grp.get("Dars_Vaqti"), "latn"),
        "monthly_lessons": grp.get("Oylik_Dars_Soni"),
        "lessons_done": grp.get("Otilgan_Dars_Hisoblagich"),
        "monthly_fee": grp.get("Oylik_Tolov_Summa"),
        "active_students": roster,
        "active_cycle_lessons": [
            {
                "date": d.get("label") or d.get("date_str"),
                "status": "cancelled"
                if d.get("is_cancelled")
                else ("held" if d.get("is_marked") else "pending"),
            }
            for d in dates
        ],
    }


async def tool_list_students(
    ctx: ToolContext, status: str = "active", group: str = ""
) -> dict[str, Any]:
    rows = await ctx.students()
    if group:
        grp, err = await _match_group(ctx, group)
        if not grp:
            return err
        key = grp["Guruh_Nomi"].strip().lower()
        rows = [
            s
            for s in rows
            if str(s.get("Guruh") or "").strip().lower() == key
            or str(s.get("Sobiq_Guruh") or "").strip().lower() == key
        ]
    status = (status or "active").lower()
    if status == "active":
        rows = [s for s in rows if str(s.get("Status") or "").strip() == "O'qiyapti"]
    elif status == "zaxira":
        rows = [
            s
            for s in rows
            if str(s.get("Guruh") or "").strip().lower() == RESERVE_GROUP_NAME.lower()
            or str(s.get("Status") or "").strip() != "O'qiyapti"
        ]
    return {
        "count": len(rows),
        "students": [
            {
                "id": s.get("Talaba_ID"),
                "name": s.get("F.I.O."),
                "group": s.get("Guruh"),
                "former_group": s.get("Sobiq_Guruh") or "",
                "status": s.get("Status"),
                "phone": s.get("Talaba_Tel"),
            }
            for s in rows[:80]
        ],
        "truncated": len(rows) > 80,
    }


async def tool_list_debtors(ctx: ToolContext, group: str = "") -> dict[str, Any]:
    from app.debt_view import compute_children_debts, load_group_fees
    from app.handlers.payments import _augment_debtors_with_legacy

    sheets = get_sheets_manager()
    allowed: Optional[set[str]] = None if ctx.role == "admin" else await ctx.group_names_lower()
    if group:
        grp, err = await _match_group(ctx, group)
        if not grp:
            return err
        allowed = {grp["Guruh_Nomi"].strip().lower()}
    debtors = await asyncio.to_thread(sheets.get_debtors, None)
    if allowed is not None:
        debtors = [
            d
            for d in debtors
            if str(d.get("Guruh") or "").strip().lower() in allowed
            or str(d.get("Sobiq_Guruh") or "").strip().lower() in allowed
        ]
    debtors = await _augment_debtors_with_legacy(sheets, debtors, allowed)
    group_fees, default_fee = await load_group_fees(sheets)
    legacy_map = {
        str(d.get("Talaba_ID") or "").strip(): list(d.get("_legacy_rows") or [])
        for d in debtors
    }
    children = await compute_children_debts(
        sheets, debtors, group_fees, default_fee, legacy_map=legacy_map
    )
    rows = [c for c in children if int(c.get("total_sum") or 0) > 0]
    rows.sort(key=lambda c: -int(c["total_sum"]))
    return {
        "count": len(rows),
        "total_debt_uzs": sum(int(c["total_sum"]) for c in rows),
        "debtors": [
            {
                "id": c["student_id"],
                "name": c["name"],
                "group": c["group"],
                "months": c["total_months"],
                "debt_uzs": c["total_sum"],
                "unpaid_cycles": [str(x.get("title") or "") for x in c.get("cycles") or []]
                + list(c.get("extra_titles") or []),
                "legacy_debts": [item["label"] for item in c.get("legacy") or []],
            }
            for c in rows[:60]
        ],
    }


async def tool_list_leads(ctx: ToolContext, only_new: bool = True, limit: int = 15) -> dict[str, Any]:
    rows = await get_recent_leads(max(5, min(int(limit or 15), 40)) * 3)
    if only_new:
        rows = [r for r in rows if str(r.get("status") or "") != "contacted"]
    rows = rows[: max(1, min(int(limit or 15), 40))]
    return {
        "leads": [
            {
                "id": r.get("id"),
                "name": r.get("full_name"),
                "phone": r.get("phone"),
                "course": r.get("course_name"),
                "status": "Bog'lanildi" if r.get("status") == "contacted" else "Yangi",
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]
    }


async def tool_list_teachers(ctx: ToolContext) -> dict[str, Any]:
    sheets = get_sheets_manager()
    teachers = await asyncio.to_thread(sheets.get_all_teachers, False)
    groups = await asyncio.to_thread(sheets.get_all_groups)
    return {
        "teachers": [
            {
                "id": tch.get("Ustoz_ID"),
                "name": tch.get("F.I.O."),
                "phone": tch.get("Telefon"),
                "username": tch.get("TG_Username"),
                "status": tch.get("Status"),
                "groups": [
                    g.get("Guruh_Nomi")
                    for g in groups
                    if str(g.get("Ustoz_ID") or "").strip() == str(tch.get("Ustoz_ID") or "").strip()
                    or (
                        str(tch.get("Chat_ID") or "").strip()
                        and str(g.get("Ustoz_Chat_ID") or "").strip()
                        == str(tch.get("Chat_ID") or "").strip()
                    )
                ],
            }
            for tch in teachers
        ]
    }


async def tool_list_lesson_topics(ctx: ToolContext, group: str = "", limit: int = 8) -> dict[str, Any]:
    grp, err = await _match_group(ctx, group)
    if not grp:
        return err
    rows = await get_group_topics_history(grp["Guruh_Nomi"], limit=max(1, min(int(limit or 8), 20)))
    return {
        "group": grp["Guruh_Nomi"],
        "topics": [
            {
                "date": r.get("lesson_date"),
                "topic": r.get("topic"),
                "plan": str(r.get("plan") or "")[:200],
                "published": bool(r.get("is_published")),
            }
            for r in rows
        ],
    }


# ----------------------------------------------------------------------
# WRITE tools -> drafts only
# ----------------------------------------------------------------------


async def _make_draft(ctx: ToolContext, action: str, payload: dict[str, Any]) -> dict[str, Any]:
    draft_id = secrets.token_hex(6)
    await create_ai_draft(draft_id, ctx.user_id, action, payload, ttl_minutes=DRAFT_TTL_MINUTES)
    ctx.drafts.append({"draft_id": draft_id, "action": action, "payload": payload})
    return {
        "draft_created": True,
        "draft_id": draft_id,
        "note": "Nothing changed yet. The user must press ✅ Tasdiqlash on the card.",
    }


async def tool_prepare_schedule_update(
    ctx: ToolContext,
    group: str = "",
    lesson_time: str = "",
    lesson_days: str = "",
    lesson_count: int = 0,
) -> dict[str, Any]:
    grp, err = await _match_group(ctx, group)
    if not grp:
        return err
    old_days = parse_weekdays(grp.get("Dars_Kunlari", ""))
    new_days = parse_weekdays(lesson_days) if lesson_days else old_days
    if lesson_days and not new_days:
        return {"error": "invalid_days", "hint": "Use: Du, Se, Chor, Pay, Ju, Shan, Yak"}
    if not new_days:
        return {"error": "group_has_no_days"}
    old_count = int(str(grp.get("Oylik_Dars_Soni") or "12").strip() or 12)
    new_count = int(lesson_count or 0) or old_count
    if new_count not in {8, 12}:
        return {"error": "lesson_count_must_be_8_or_12"}
    daily = 2 if str(grp.get("Kunlik_Dars_Soni") or "1").strip() == "2" else 1
    raw_time = (lesson_time or "").strip()
    new_time = str(grp.get("Dars_Vaqti") or "").strip()
    if raw_time:
        if is_agreed_lesson_time(raw_time):
            new_time = AGREED_LESSON_TIME
        else:
            uniform = normalize_session_times(raw_time, daily)
            if uniform:
                new_time = uniform
            else:
                _u, per_day = parse_lesson_sessions(raw_time)
                if not per_day:
                    return {
                        "error": "invalid_time",
                        "hint": "Uniform '14:00' (double lessons '10:00 / 11:30') or "
                        "per-day 'Du 14:00, Chor 15:30'",
                    }
                new_time = ", ".join(
                    f"{LESSON_DAY_ABBR[idx]} {' / '.join(per_day[idx])}" for idx in sorted(per_day)
                )
    _uni, per_day_now = parse_lesson_sessions(new_time)
    if per_day_now and not all(d in per_day_now for d in new_days):
        return {
            "error": "per_day_time_missing_for_some_days",
            "hint": "Give a time for every lesson day, e.g. 'Du 14:00, Chor 15:30'",
        }
    from app.handlers.groups_info import _format_days_from_indices

    payload = {
        "group": grp["Guruh_Nomi"],
        "old": {
            "time": grp.get("Dars_Vaqti") or "",
            "days": grp.get("Dars_Kunlari") or "",
            "count": str(old_count),
        },
        "new": {
            "time": new_time,
            "days": _format_days_from_indices(new_days, "latn"),
            "days_idx": new_days,
            "count": new_count,
        },
    }
    if (
        payload["new"]["time"] == payload["old"]["time"]
        and new_days == old_days
        and new_count == old_count
    ):
        return {"error": "nothing_changes"}
    return await _make_draft(ctx, "schedule", payload)


async def tool_prepare_payment_confirmation(
    ctx: ToolContext, student: str = "", group: str = "", cycle: str = ""
) -> dict[str, Any]:
    from app.handlers.payments import _fetch_full_cycle_history_sync

    grp_name = ""
    if group:
        grp, err = await _match_group(ctx, group)
        if not grp:
            return err
        grp_name = grp["Guruh_Nomi"]
    stu, err = await _match_student(ctx, student, grp_name)
    if not stu:
        return err
    grp_name = grp_name or str(stu.get("Guruh") or "").strip()
    if grp_name.strip().lower() not in await ctx.group_names_lower():
        return {"error": "group_not_allowed"}
    cycles = await asyncio.to_thread(
        _fetch_full_cycle_history_sync, grp_name, str(stu["Talaba_ID"])
    )
    unpaid = [c for c in cycles if not c.get("is_paid")]
    if not unpaid:
        return {"error": "no_unpaid_cycle", "student": stu.get("F.I.O.")}
    chosen = None
    if cycle:
        q = _norm(cycle)
        chosen = next((c for c in unpaid if q in _norm(c.get("cycle_title"))), None)
        if chosen is None:
            return {
                "error": "cycle_not_found",
                "unpaid_cycles": [c["cycle_title"] for c in unpaid],
            }
    else:
        unpaid.sort(key=lambda c: int(c.get("cycle_number") or 0))
        chosen = unpaid[0]
    group_row = next(
        (g for g in await ctx.groups() if g["Guruh_Nomi"].strip().lower() == grp_name.lower()),
        {},
    )
    fee_digits = re.sub(r"\D", "", str(group_row.get("Oylik_Tolov_Summa") or ""))
    amount = int(chosen["prorated_amount"]) if chosen.get("prorated_amount") else (
        int(fee_digits) if fee_digits else 0
    )
    payload = {
        "student_id": str(stu["Talaba_ID"]),
        "student_name": str(stu.get("F.I.O.") or ""),
        "group": grp_name,
        "cycle_title": chosen["cycle_title"],
        "amount": amount,
        "other_unpaid": [c["cycle_title"] for c in unpaid if c is not chosen],
    }
    return await _make_draft(ctx, "payment", payload)


async def tool_prepare_student_status(
    ctx: ToolContext, student: str = "", action: str = "", target_group: str = ""
) -> dict[str, Any]:
    action = (action or "").strip().lower()
    if action not in {"to_zaxira", "restore"}:
        return {"error": "action_must_be_to_zaxira_or_restore"}
    stu, err = await _match_student(ctx, student)
    if not stu:
        return err
    cur_group = str(stu.get("Guruh") or "").strip()
    if action == "to_zaxira":
        if cur_group.lower() == RESERVE_GROUP_NAME.lower():
            return {"error": "already_in_zaxira"}
        payload = {"student_id": str(stu["Talaba_ID"]), "student_name": stu.get("F.I.O."), "group": cur_group}
        return await _make_draft(ctx, "to_zaxira", payload)
    target = target_group or str(stu.get("Sobiq_Guruh") or "").strip()
    if not target:
        return {"error": "target_group_required"}
    grp, err = await _match_group(ctx, target)
    if not grp:
        return err
    payload = {
        "student_id": str(stu["Talaba_ID"]),
        "student_name": stu.get("F.I.O."),
        "group": grp["Guruh_Nomi"],
    }
    return await _make_draft(ctx, "restore", payload)


async def tool_prepare_lead_contacted(ctx: ToolContext, lead: str = "") -> dict[str, Any]:
    query = str(lead or "").strip().lstrip("#")
    row: Optional[dict[str, Any]] = None
    if query.isdigit() and len(query) < 7:
        row = await get_lead(int(query))
    if row is None:
        rows = await get_recent_leads(120)
        q = _norm(query)
        q_digits = re.sub(r"\D", "", query)
        hits = [
            r
            for r in rows
            if (q and q in _norm(r.get("full_name")))
            or (len(q_digits) >= 7 and q_digits[-9:] in re.sub(r"\D", "", str(r.get("phone") or "")))
        ]
        if len(hits) > 1:
            return {
                "error": "ambiguous_lead",
                "candidates": [f"#{r['id']} {r.get('full_name')} {r.get('phone')}" for r in hits[:6]],
            }
        row = hits[0] if hits else None
    if not row:
        return {"error": "lead_not_found"}
    if str(row.get("status") or "") == "contacted":
        return {"error": "lead_already_contacted"}
    payload = {
        "lead_id": int(row["id"]),
        "name": row.get("full_name"),
        "phone": row.get("phone"),
        "course": row.get("course_name"),
    }
    return await _make_draft(ctx, "lead", payload)


async def tool_prepare_lesson_topic(
    ctx: ToolContext, group: str = "", date: str = "", topic: str = "", plan: str = ""
) -> dict[str, Any]:
    grp, err = await _match_group(ctx, group)
    if not grp:
        return err
    lesson_day = _parse_lesson_date(date or "bugun")
    if lesson_day is None:
        return {"error": "invalid_date", "hint": "DD.MM or DD.MM.YYYY"}
    clean_topic = " ".join(str(topic or "").split())
    if len(clean_topic) < 2:
        return {"error": "topic_required"}
    payload = {
        "group": grp["Guruh_Nomi"],
        "date": lesson_day.strftime("%d.%m"),
        "date_full": lesson_day.strftime("%d.%m.%Y"),
        "topic": clean_topic[:300],
        "plan": str(plan or "").strip()[:2000],
    }
    return await _make_draft(ctx, "topic", payload)


ToolFn = Callable[..., Awaitable[dict[str, Any]]]

# name -> (allowed roles, description, JSON schema of parameters, implementation)
TOOLS: dict[str, tuple[set[str], str, dict[str, Any], ToolFn]] = {
    "list_groups": (
        {"admin", "teacher"},
        "List the groups the user may see (teacher: only own groups) with teacher, days, "
        "time, monthly lessons, lessons done, fee and active student count.",
        {"type": "object", "properties": {}},
        tool_list_groups,
    ),
    "group_details": (
        {"admin", "teacher"},
        "One group's schedule, active student roster and active-cycle lesson dates with status.",
        {
            "type": "object",
            "properties": {"group": {"type": "string", "description": "Group name"}},
            "required": ["group"],
        },
        tool_group_details,
    ),
    "list_students": (
        {"admin"},
        "List students. status: 'active' (O'qiyapti), 'zaxira' (reserve) or 'all'. "
        "Optional group filter.",
        {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["active", "zaxira", "all"]},
                "group": {"type": "string"},
            },
        },
        tool_list_students,
    ),
    "list_debtors": (
        {"admin", "teacher"},
        "Debtors with exact debt in UZS (unpaid cycles incl. Qarzdor_Oylar + legacy debts). "
        "Teacher: only own groups. Optional group filter.",
        {"type": "object", "properties": {"group": {"type": "string"}}},
        tool_list_debtors,
    ),
    "list_leads": (
        {"admin"},
        "Recent leads (Qiziquvchilar_Lidlar). only_new=true hides contacted ones.",
        {
            "type": "object",
            "properties": {"only_new": {"type": "boolean"}, "limit": {"type": "integer"}},
        },
        tool_list_leads,
    ),
    "list_teachers": (
        {"admin"},
        "All teachers (Ustozlar) with phone, username, status and their groups.",
        {"type": "object", "properties": {}},
        tool_list_teachers,
    ),
    "list_lesson_topics": (
        {"admin", "teacher"},
        "Recent lesson topics saved for a group.",
        {
            "type": "object",
            "properties": {"group": {"type": "string"}, "limit": {"type": "integer"}},
            "required": ["group"],
        },
        tool_list_lesson_topics,
    ),
    "prepare_schedule_update": (
        {"admin"},
        "DRAFT (needs ✅ confirmation) changing a group's lesson time ('14:00', double "
        "'10:00 / 11:30', per-day 'Du 14:00, Chor 15:30' or 'Kelishilgan vaqtda'), "
        "lesson days ('Du, Chor, Ju') and/or monthly lesson count (8 or 12). "
        "Omit fields that do not change.",
        {
            "type": "object",
            "properties": {
                "group": {"type": "string"},
                "lesson_time": {"type": "string"},
                "lesson_days": {"type": "string"},
                "lesson_count": {"type": "integer"},
            },
            "required": ["group"],
        },
        tool_prepare_schedule_update,
    ),
    "prepare_payment_confirmation": (
        {"admin", "teacher"},
        "DRAFT (needs ✅ confirmation) confirming a student's payment for one unpaid "
        "cycle (oldest unpaid if cycle is omitted). Teacher: only own groups.",
        {
            "type": "object",
            "properties": {
                "student": {"type": "string", "description": "Name, Talaba_ID or phone"},
                "group": {"type": "string"},
                "cycle": {"type": "string", "description": "e.g. 'NOYABR 2026'"},
            },
            "required": ["student"],
        },
        tool_prepare_payment_confirmation,
    ),
    "prepare_student_status": (
        {"admin"},
        "DRAFT (needs ✅ confirmation): action 'to_zaxira' moves a student to Zaxira; "
        "'restore' returns them to target_group (default: former group).",
        {
            "type": "object",
            "properties": {
                "student": {"type": "string"},
                "action": {"type": "string", "enum": ["to_zaxira", "restore"]},
                "target_group": {"type": "string"},
            },
            "required": ["student", "action"],
        },
        tool_prepare_student_status,
    ),
    "prepare_lead_contacted": (
        {"admin"},
        "DRAFT (needs ✅ confirmation) marking a lead as \"Bog'lanildi\" (lead id, name or phone).",
        {
            "type": "object",
            "properties": {"lead": {"type": "string"}},
            "required": ["lead"],
        },
        tool_prepare_lead_contacted,
    ),
    "prepare_lesson_topic": (
        {"admin", "teacher"},
        "DRAFT (needs ✅ confirmation) saving a lesson topic and optional plan for a group "
        "and date (DD.MM, DD.MM.YYYY, 'bugun', 'ertaga'). Teacher: only own groups.",
        {
            "type": "object",
            "properties": {
                "group": {"type": "string"},
                "date": {"type": "string"},
                "topic": {"type": "string"},
                "plan": {"type": "string"},
            },
            "required": ["group", "topic"],
        },
        tool_prepare_lesson_topic,
    ),
}


async def dispatch_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    spec = TOOLS.get(name)
    if spec is None or ctx.role not in spec[0]:
        # Role-locked server side: a teacher can never reach admin tools even
        # if the model tries to call them.
        return {"error": "tool_not_allowed_for_role", "role": ctx.role}
    allowed_params = set((spec[2].get("properties") or {}).keys())
    clean_args = {k: v for k, v in (args or {}).items() if k in allowed_params}
    try:
        return await spec[3](ctx, **clean_args)
    except Exception as exc:
        logger.exception("AI tool %s failed", name)
        return {"error": "tool_failed", "detail": str(exc)[:200]}


# ----------------------------------------------------------------------
# Gemini call
# ----------------------------------------------------------------------

_client: Any = None
_thinking_supported = True


def _get_client() -> Any:
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _system_prompt(ctx: ToolContext) -> str:
    now = now_tashkent()
    scope = (
        "ADMIN: full read access to the whole center; write actions only as drafts."
        if ctx.role == "admin"
        else "TEACHER: only the teacher's OWN assigned groups. Never reveal or change other "
        "teachers' groups, leads, Zaxira moves, schedules or fees."
    )
    return (
        "You are the internal work assistant of Mishkat Nodavlat Ta'lim Muassasasi "
        "(an education center in Uzbekistan) inside its Telegram bot.\n"
        f"Today: {now.strftime('%d.%m.%Y %A %H:%M')} (Asia/Tashkent). User: {ctx.actor_name}. "
        f"Role: {scope}\n"
        "ALLOWED TOPICS ONLY: the center's groups, schedules, attendance, payments, debtors, "
        "students, teachers, leads, lesson topics and how to use this bot.\n"
        "If the message is about anything else (weather, jokes, coding, news, general chat, "
        "translation, homework help...), reply with EXACTLY this one sentence and nothing "
        "else, without calling any tool:\n"
        f"- Latin-script message: {OFF_TOPIC_REPLY['latn']}\n"
        f"- Cyrillic-script message: {OFF_TOPIC_REPLY['cyrl']}\n"
        "RULES:\n"
        "1. Use the tools for every fact; never invent names, numbers or dates.\n"
        "2. Changes are ONLY made through prepare_* tools, which create a draft card. "
        "After a draft is created say briefly that the user must press '✅ Tasdiqlash' "
        "on the card. Never claim something was already changed.\n"
        "3. If a tool returns ambiguous/not-found candidates, ask one short clarifying question.\n"
        "4. Answer in Uzbek, in the SAME script as the user (Latin or Cyrillic), plain text "
        "without Markdown, at most 8 short lines. Money as '450 000 so'm'.\n"
        "5. Lesson day abbreviations: Du, Se, Chor, Pay, Ju, Shan, Yak."
    )


def _function_declarations(role: str) -> list[Any]:
    from google.genai import types

    return [
        types.FunctionDeclaration(
            name=name, description=desc, parameters_json_schema=schema
        )
        for name, (roles, desc, schema, _fn) in TOOLS.items()
        if role in roles
    ]


def _response_text(resp: Any) -> str:
    try:
        parts = resp.candidates[0].content.parts or []
    except (AttributeError, IndexError, TypeError):
        return ""
    return "".join(
        str(p.text) for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False)
    ).strip()


async def _generate(contents: list[Any], ctx: ToolContext) -> Any:
    global _thinking_supported
    from google.genai import errors, types

    def _config(with_thinking: bool) -> Any:
        kwargs: dict[str, Any] = dict(
            system_instruction=_system_prompt(ctx),
            temperature=TEMPERATURE,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            tools=[types.Tool(function_declarations=_function_declarations(ctx.role))],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        if with_thinking:
            kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=types.ThinkingLevel.MINIMAL
            )
        return types.GenerateContentConfig(**kwargs)

    client = _get_client()
    async with _get_semaphore():
        try:
            return await client.aio.models.generate_content(
                model=GEMINI_MODEL, contents=contents, config=_config(_thinking_supported)
            )
        except errors.ClientError as exc:
            if _thinking_supported and int(getattr(exc, "code", 0) or 0) == 400 and "think" in str(exc).lower():
                # Model does not accept a thinking level: retry without it.
                _thinking_supported = False
                return await client.aio.models.generate_content(
                    model=GEMINI_MODEL, contents=contents, config=_config(False)
                )
            raise


class AiReply:
    def __init__(self, text: str = "", drafts: Optional[list[dict[str, Any]]] = None, lang: str = "latn") -> None:
        self.text = text
        self.drafts = drafts or []
        self.lang = lang


async def ask(
    user_id: int,
    role: str,
    actor_name: str,
    lang_hint: str,
    text: str = "",
    audio: Optional[bytes] = None,
) -> AiReply:
    """Runs one assistant turn (text or voice) with the tool loop."""
    from google.genai import errors, types

    lang = detect_script(text, lang_hint) if text else (lang_hint if lang_hint in TEXTS else "latn")
    if not AI_ENABLED:
        return AiReply("", lang=lang)
    ctx = ToolContext(user_id, role, lang, actor_name)

    contents: list[Any] = []
    for user_turn, model_turn in _history(user_id):
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_turn)]))
        contents.append(types.Content(role="model", parts=[types.Part.from_text(text=model_turn)]))
    user_parts: list[Any] = []
    if text:
        user_parts.append(types.Part.from_text(text=text[:2000]))
    if audio:
        user_parts.append(types.Part.from_bytes(data=audio, mime_type="audio/ogg"))
        if not text:
            user_parts.insert(
                0,
                types.Part.from_text(
                    text="(Voice message from the user. Understand it and answer per the rules.)"
                ),
            )
    contents.append(types.Content(role="user", parts=user_parts))

    final_text = ""
    try:
        for _round in range(MAX_TOOL_ROUNDS + 1):
            resp = await _generate(contents, ctx)
            calls = list(resp.function_calls or [])
            if not calls or _round == MAX_TOOL_ROUNDS:
                final_text = _response_text(resp)
                break
            contents.append(resp.candidates[0].content)
            response_parts = []
            for call in calls:
                result = await dispatch_tool(ctx, str(call.name or ""), dict(call.args or {}))
                payload = json.dumps(result, ensure_ascii=False, default=str)
                if len(payload) > TOOL_RESULT_CHAR_LIMIT:
                    result = {"truncated_json": payload[:TOOL_RESULT_CHAR_LIMIT]}
                response_parts.append(
                    types.Part.from_function_response(name=str(call.name or ""), response={"result": result})
                )
            contents.append(types.Content(role="user", parts=response_parts))
    except errors.APIError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        logger.warning("Gemini API error %s for user %s: %s", code, user_id, str(exc)[:300])
        return AiReply(tr("api_busy" if code in {429, 503} else "api_error", lang), ctx.drafts, lang)
    except Exception:
        logger.exception("Gemini call failed for user %s", user_id)
        return AiReply(tr("api_error", lang), ctx.drafts, lang)

    if not final_text and not ctx.drafts:
        final_text = tr("empty_answer", lang)
    _remember(user_id, text or "[ovozli xabar]", final_text or "[qoralama yaratildi]")
    return AiReply(final_text, ctx.drafts, lang)


# ----------------------------------------------------------------------
# Draft cards & execution on "✅ Tasdiqlash"
# ----------------------------------------------------------------------


def render_draft_card(action: str, payload: dict[str, Any], lang: str) -> str:
    esc = html.escape
    lines: list[str] = []
    if action == "schedule":
        old, new = payload["old"], payload["new"]
        lines = [
            tr("title_schedule", lang),
            "",
            f"{tr('lbl_group', lang)}: <b>{esc(payload['group'])}</b>",
            f"{tr('lbl_days', lang)}: {esc(old['days'] or '—')} ➡️ <b>{esc(new['days'])}</b>",
            f"{tr('lbl_time', lang)}: {esc(format_lesson_time_display(old['time'], lang) or '—')} ➡️ "
            f"<b>{esc(format_lesson_time_display(new['time'], lang) or '—')}</b>",
            f"{tr('lbl_count', lang)}: {esc(str(old['count']))} ➡️ <b>{esc(str(new['count']))}</b>",
        ]
    elif action == "payment":
        lines = [
            tr("title_payment", lang),
            "",
            f"{tr('lbl_student', lang)}: <b>{esc(payload['student_name'])}</b> ({esc(payload['student_id'])})",
            f"{tr('lbl_group', lang)}: <b>{esc(payload['group'])}</b>",
            f"{tr('lbl_cycle', lang)}: <b>{esc(payload['cycle_title'])}</b>",
        ]
        if int(payload.get("amount") or 0) > 0:
            lines.append(f"{tr('lbl_amount', lang)}: <b>{_fmt_money(payload['amount'])} so'm</b>")
    elif action in {"to_zaxira", "restore"}:
        lines = [
            tr("title_to_zaxira" if action == "to_zaxira" else "title_restore", lang),
            "",
            f"{tr('lbl_student', lang)}: <b>{esc(str(payload['student_name']))}</b> ({esc(payload['student_id'])})",
            f"{tr('lbl_group' if action == 'to_zaxira' else 'lbl_target', lang)}: <b>{esc(payload['group'])}</b>",
        ]
    elif action == "lead":
        lines = [
            tr("title_lead", lang),
            "",
            f"{tr('lbl_lead', lang)}: <b>#{payload['lead_id']} {esc(str(payload.get('name') or ''))}</b>",
            f"📱 {esc(str(payload.get('phone') or '—'))} | 📚 {esc(str(payload.get('course') or '—'))}",
        ]
    elif action == "topic":
        lines = [
            tr("title_topic", lang),
            "",
            f"{tr('lbl_group', lang)}: <b>{esc(payload['group'])}</b>",
            f"{tr('lbl_date', lang)}: <b>{esc(payload['date_full'])}</b>",
            f"{tr('lbl_topic', lang)}: <b>{esc(payload['topic'])}</b>",
        ]
        if payload.get("plan"):
            lines.append(f"{tr('lbl_plan', lang)}: {esc(payload['plan'][:500])}")
    lines += ["", f"<i>{tr('draft_hint', lang)}</i>"]
    return "\n".join(lines)


_ACTION_ROLES = {
    "schedule": {"admin"},
    "payment": {"admin", "teacher"},
    "to_zaxira": {"admin"},
    "restore": {"admin"},
    "lead": {"admin"},
    "topic": {"admin", "teacher"},
}


async def execute_draft(bot: Any, actor_id: int, actor_name: str, draft: dict[str, Any], lang: str) -> str:
    """Runs the confirmed draft through the existing helpers. Returns HTML text."""
    action = str(draft.get("action") or "")
    payload = dict(draft.get("payload") or {})
    role = await resolve_ai_role(actor_id)
    if role is None or role not in _ACTION_ROLES.get(action, set()):
        return tr("no_permission", lang)
    ctx = ToolContext(actor_id, role, lang, actor_name)
    group_name = str(payload.get("group") or "")
    if group_name and group_name.strip().lower() not in await ctx.group_names_lower():
        return tr("no_permission", lang)
    esc = html.escape
    sheets = get_sheets_manager()

    if action == "schedule":
        from app.handlers.groups_info import _broadcast_group_update

        new = payload["new"]
        old = payload["old"]
        final_dates = await asyncio.to_thread(
            sheets.rebuild_active_cycle_sheet,
            group_name,
            int(new["count"]),
            str(new["days"]),
            str(new["time"]),
        )
        await database.set_group_lesson_time(group_name, str(new["time"]))
        change_items: list[tuple[str, str, str]] = []
        if str(new["count"]) != str(old["count"]):
            change_items.append(("Oylik_Dars_Soni", str(old["count"]), str(new["count"])))
        if parse_weekdays(old["days"]) != list(new["days_idx"]):
            change_items.append(("Dars_Kunlari", old["days"], new["days"]))
        if str(new["time"]).strip() != str(old["time"]).strip():
            change_items.append(("Dars_Vaqti", old["time"], new["time"]))
        await log_audit_event(
            actor_id=actor_id,
            action=AUDIT_GROUP_EDITED,
            target=group_name,
            details="AI: " + "; ".join(f"{k}: {a} → {b}" for k, a, b in change_items),
            actor_name=actor_name,
        )
        sent = await _broadcast_group_update(
            bot,
            sheets,
            group_name,
            change_items=change_items or [("Dars_Vaqti", old["time"], new["time"])],
            dates_list=final_dates,
            triggered_by_user_id=actor_id,
        )
        return tr("done_schedule", lang, group=esc(group_name), sent=sent)

    if action == "payment":
        from app.handlers.payments import execute_payment_confirmation

        result = await execute_payment_confirmation(
            bot,
            actor_id,
            actor_name,
            group_name,
            str(payload["student_id"]),
            str(payload["cycle_title"]),
        )
        if not result["ok"]:
            return tr("exec_failed", lang, reason=esc(result["reason"]))
        return tr(
            "done_payment",
            lang,
            student=esc(str(payload["student_name"])),
            group=esc(group_name),
            cycle=esc(str(payload["cycle_title"])),
        )

    if action == "to_zaxira":
        from app.handlers.students import _notify_reserve_move

        move_res = await sheets.a_move_student_to_reserve(str(payload["student_id"]))
        old_group = str(move_res.get("old_group") or group_name or "—")
        name = str(payload.get("student_name") or payload["student_id"])
        await log_audit_event(
            actor_id=actor_id,
            action=AUDIT_STUDENT_TO_RESERVE,
            target=f"{name} ({payload['student_id']}) | {old_group}",
            details=f"Talaba: {name}; Eski guruh: {old_group} (AI)",
            actor_name=actor_name,
        )
        student = move_res.get("student") or await sheets.a_get_student_by_id(str(payload["student_id"]))
        if student:
            await _notify_reserve_move(bot, student, old_group, actor_id)
        return tr("done_to_zaxira", lang, student=esc(name), group=esc(old_group))

    if action == "restore":
        from app.handlers.students import _notify_restore_from_reserve

        restored = await sheets.a_restore_student_from_reserve(str(payload["student_id"]), group_name)
        name = str(restored.get("F.I.O.") or payload.get("student_name") or payload["student_id"])
        new_group = str(restored.get("Guruh") or group_name)
        await log_audit_event(
            actor_id=actor_id,
            action=AUDIT_STUDENT_RESTORED,
            target=f"{name} ({payload['student_id']}) | {new_group}",
            details=f"Talaba: {name}; Guruh: {new_group} (AI)",
            actor_name=actor_name,
        )
        await _notify_restore_from_reserve(bot, restored, new_group, actor_id)
        return tr("done_restore", lang, student=esc(name), group=esc(new_group))

    if action == "lead":
        lead_id = int(payload["lead_id"])
        lead = await get_lead(lead_id)
        changed = await mark_lead_contacted(
            lead_id, actor_id, tashkent_now_str("%d.%m.%Y %H:%M:%S")
        )
        if changed:
            try:
                await sheets.a_mark_lead_contacted(f"{lead_id}", (lead or {}).get("telegram_id"))
            except Exception:
                logger.exception("AI: could not colour lead #%s in Qiziquvchilar_Lidlar", lead_id)
        return tr("done_lead", lang, lead_id=lead_id, name=esc(str(payload.get("name") or "")))

    if action == "topic":
        await save_lesson_topic(
            group_name=group_name,
            lesson_date=str(payload["date"]),
            topic=str(payload["topic"]),
            plan=str(payload.get("plan") or ""),
            teacher_id=actor_id,
            teacher_name=actor_name,
            is_published=0,
        )
        return tr("done_topic", lang, group=esc(group_name), date=esc(str(payload["date_full"])))

    return tr("draft_not_found", lang)
