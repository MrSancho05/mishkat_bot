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
        "done_payment_revert": "↩️ <b>{student}</b> ({group}) — <b>{cycle}</b> to‘lovi bekor qilindi.",
        "done_topic_published": "✅ <b>{group}</b> — {date} mavzusi saqlandi va e’lon qilindi (yuborildi: {sent}).",
        "done_student_edit": "✅ <b>{student}</b>: {field} → <b>{value}</b>",
        "done_device_link": "📱 <b>{student}</b> uchun qurilmaga ulash havolasi:\n<code>{link}</code>",
        "done_group_update": "✅ <b>{group}</b> guruhi yangilandi: {parts}",
        "done_group_delete": "🗑 <b>{group}</b> guruhi o‘chirildi (talabalar Zahira guruhiga o‘tkazildi).",
        "done_teacher_invite": "🔗 Ustoz taklif havolasi ({group}):\n<code>{link}</code>",
        "link_group_hint": "👥 Telegram guruhini ulash uchun guruh chatida yuboring:\n<code>/link_group {group}</code>",
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
        "done_payment_revert": "↩️ <b>{student}</b> ({group}) — <b>{cycle}</b> тўлови бекор қилинди.",
        "done_topic_published": "✅ <b>{group}</b> — {date} мавзуси сақланди ва эълон қилинди (юборилди: {sent}).",
        "done_student_edit": "✅ <b>{student}</b>: {field} → <b>{value}</b>",
        "done_device_link": "📱 <b>{student}</b> учун қурилмага улаш ҳаволаси:\n<code>{link}</code>",
        "done_group_update": "✅ <b>{group}</b> гуруҳи янгиланди: {parts}",
        "done_group_delete": "🗑 <b>{group}</b> гуруҳи ўчирилди (талабалар Захира гуруҳига ўтказилди).",
        "done_teacher_invite": "🔗 Устоз таклиф ҳаволаси ({group}):\n<code>{link}</code>",
        "link_group_hint": "👥 Telegram гуруҳини улаш учун гуруҳ чатида юборинг:\n<code>/link_group {group}</code>",
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
    def __init__(
        self, user_id: int, role: str, lang: str, actor_name: str, bot: Any = None
    ) -> None:
        self.bot = bot
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


def _name_match_score(q_tokens: list[str], name_parts: list[str]) -> float:
    """
    Every typed word must match a DIFFERENT part of the name: a prefix
    ("Ali Val" -> "Ali Valiyev") or a close spelling (>= 0.8, "Valiev" ->
    "Valiyev"). Word order is free. "Vali Aliyev" therefore never matches
    "Ali Valiyev". Returns 0 when not matched, else a score in (0, 1].
    """
    if not q_tokens or not name_parts:
        return 0.0
    remaining = list(name_parts)
    total = 0.0
    for tok in q_tokens:
        best_idx, best_score = -1, 0.0
        for idx, part in enumerate(remaining):
            if part == tok:
                score = 1.0
            elif part.startswith(tok) and len(tok) >= 2:
                score = 0.9
            else:
                score = difflib.SequenceMatcher(None, tok, part).ratio()
                if score < 0.8:
                    score = 0.0
            if score > best_score:
                best_idx, best_score = idx, score
        if best_idx < 0:
            return 0.0
        total += best_score
        remaining.pop(best_idx)
    # Prefer names whose every part was mentioned ("Ali Valiyev" over "Ali Valiyev Karim").
    return total / len(q_tokens) - 0.01 * len(remaining)


def _fuzzy_pick(
    query: str, students: list[dict[str, Any]]
) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    """Talaba_ID / phone / fuzzy F.I.O. match inside `students`."""
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
            if q_digits[-9:] in re.sub(r"\D", "", str(s.get("Talaba_Tel") or ""))
        ]
        if len(phone_hits) == 1:
            return phone_hits[0], {}
    scored: list[tuple[float, dict[str, Any]]] = []
    q_tokens = q.split()
    for s in students:
        name = _norm(s.get("F.I.O."))
        if not name:
            continue
        score = _name_match_score(q_tokens, name.split())
        if score > 0:
            scored.append((score, s))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None, {"error": "student_not_found_or_not_allowed", "query": query}
    best = scored[0]
    ties = [s for r, s in scored if r >= best[0] - 0.02]
    if len(ties) > 1:
        return None, {
            "error": "ambiguous_student",
            "query": query,
            "candidates": [
                f"{s.get('F.I.O.')} ({s.get('Talaba_ID')}, {s.get('Guruh')})" for s in ties[:6]
            ],
        }
    return best[1], {}


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
    return _fuzzy_pick(query, students)


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


def _validate_schedule(
    grp: dict[str, Any], lesson_time: str = "", lesson_days: str = "", lesson_count: int = 0
) -> dict[str, Any]:
    """
    Validates a schedule change against the group's current values. Returns
    {"group", "old", "new", "changed"} or {"error": ...}. Nothing is written.
    """
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
    payload["changed"] = not (
        payload["new"]["time"] == payload["old"]["time"]
        and new_days == old_days
        and new_count == old_count
    )
    return payload


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
    payload = _validate_schedule(grp, lesson_time, lesson_days, lesson_count)
    if payload.get("error"):
        return payload
    if not payload.pop("changed"):
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


# ----------------------------------------------------------------------
# Extended tools: every button-menu capability of the admin / teacher roles
# ----------------------------------------------------------------------

STUDENT_EDITABLE_FIELDS = {
    "F.I.O.": "F.I.O.",
    "fio": "F.I.O.",
    "name": "F.I.O.",
    "Talaba_Tel": "Talaba_Tel",
    "phone": "Talaba_Tel",
    "Talaba_TG": "Talaba_TG",
    "telegram": "Talaba_TG",
    "Otasi_FIO": "Otasi_FIO",
    "father_name": "Otasi_FIO",
    "Otasi_Tel": "Otasi_Tel",
    "father_phone": "Otasi_Tel",
    "Onasi_FIO": "Onasi_FIO",
    "mother_name": "Onasi_FIO",
    "Onasi_Tel": "Onasi_Tel",
    "mother_phone": "Onasi_Tel",
}


def _active_roster(students: list[dict[str, Any]], group_name: str) -> list[dict[str, Any]]:
    key = group_name.strip().lower()
    return [
        s
        for s in students
        if str(s.get("Guruh") or "").strip().lower() == key
        and str(s.get("Status") or "").strip() == "O'qiyapti"
    ]


def _parse_fee(raw: Any) -> Optional[int]:
    digits = re.sub(r"\D", "", str(raw or ""))
    if not digits:
        return None
    amount = int(digits)
    if amount <= 0 or amount > 100_000_000:
        return None
    return amount * 1000 if amount < 10000 else amount


async def _match_teacher(query: str) -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    teachers = await asyncio.to_thread(get_sheets_manager().get_all_teachers, False)
    q = _norm(query)
    if not q:
        return None, {"error": "teacher_required"}
    for tch in teachers:
        if q in {_norm(tch.get("Ustoz_ID")), _norm(tch.get("Chat_ID"))}:
            return tch, {}
    by_name = {_norm(tch.get("F.I.O.")): tch for tch in teachers if _norm(tch.get("F.I.O."))}
    hits = [tch for name, tch in by_name.items() if _name_match_score(q.split(), name.split()) > 0]
    if len(hits) == 1:
        return hits[0], {}
    close = difflib.get_close_matches(q, list(by_name), n=3, cutoff=0.6)
    if len(close) == 1 and not hits:
        return by_name[close[0]], {}
    cands = hits or [by_name[c] for c in close]
    if cands:
        return None, {
            "error": "ambiguous_teacher",
            "candidates": [f"{c.get('F.I.O.')} ({c.get('Ustoz_ID')})" for c in cands[:6]],
        }
    return None, {
        "error": "teacher_not_found",
        "teachers": [f"{t.get('F.I.O.')} ({t.get('Ustoz_ID')})" for t in teachers[:30]],
    }


async def tool_list_today_groups(ctx: ToolContext) -> dict[str, Any]:
    """Groups that have a lesson today (by Dars_Kunlari and start date)."""
    today = today_tashkent()
    groups = []
    for g in await ctx.groups():
        if today.weekday() not in parse_weekdays(g.get("Dars_Kunlari", "")):
            continue
        start_raw = str(g.get("Boshlanish_Sanasi") or "").strip().lstrip("'")
        try:
            if start_raw and datetime.strptime(start_raw, "%d.%m.%Y").date() > today:
                continue
        except ValueError:
            pass
        groups.append(
            {
                "name": g.get("Guruh_Nomi"),
                "time": format_lesson_time_display(g.get("Dars_Vaqti"), "latn"),
                "lessons_done": g.get("Otilgan_Dars_Hisoblagich"),
                "monthly_lessons": g.get("Oylik_Dars_Soni"),
            }
        )
    return {"date": today.strftime("%d.%m.%Y"), "groups": groups}


async def tool_group_contacts(ctx: ToolContext, group: str = "") -> dict[str, Any]:
    grp, err = await _match_group(ctx, group)
    if not grp:
        return err
    roster = _active_roster(await ctx.students(), grp["Guruh_Nomi"])
    return {
        "group": grp["Guruh_Nomi"],
        "students": [
            {
                "name": s.get("F.I.O."),
                "phone": s.get("Talaba_Tel"),
                "telegram": s.get("Talaba_TG"),
                "father": s.get("Otasi_FIO"),
                "father_phone": s.get("Otasi_Tel"),
                "mother": s.get("Onasi_FIO"),
                "mother_phone": s.get("Onasi_Tel"),
                "bot_linked": bool(str(s.get("Talaba_Chat_ID") or "").strip()),
            }
            for s in roster
        ],
    }


async def tool_debtor_lesson_dates(ctx: ToolContext, student: str = "") -> dict[str, Any]:
    """Detailed debtor view: unpaid cycles with every lesson date + status."""
    from app.handlers.payments import _sync_collect_unpaid_cycles

    stu, err = await _match_student(ctx, student)
    if not stu:
        return err
    cycles = await asyncio.to_thread(
        _sync_collect_unpaid_cycles, get_sheets_manager(), [stu]
    )
    rows = cycles.get(str(stu.get("Talaba_ID") or "").strip(), [])
    return {
        "student": stu.get("F.I.O."),
        "group": stu.get("Guruh"),
        "unpaid_cycles": [
            {
                "cycle": c["title"],
                "lessons": [f"{label} {icon}" for label, icon in c["lessons"]],
                "dates_copy": ", ".join(label for label, _icon in c["lessons"]),
            }
            for c in rows
        ],
    }


async def tool_student_invite_link(ctx: ToolContext, group: str = "") -> dict[str, Any]:
    """Self-join link (?start=join_<slug>) of a group — read-only, no change."""
    from app.utils import make_group_join_slug

    grp, err = await _match_group(ctx, group)
    if not grp:
        return err
    if ctx.bot is None:
        return {"error": "bot_unavailable"}
    me = await ctx.bot.get_me()
    return {
        "group": grp["Guruh_Nomi"],
        "student_invite_link": f"https://t.me/{me.username}?start=join_{make_group_join_slug(grp['Guruh_Nomi'])}",
        "note": "Students and parents open this link to request joining the group.",
    }


async def tool_center_statistics(ctx: ToolContext) -> dict[str, Any]:
    sheets = get_sheets_manager()
    students = await asyncio.to_thread(sheets.get_all_students, None, False)
    groups = await asyncio.to_thread(sheets.get_all_groups)
    teachers = await asyncio.to_thread(sheets.get_all_teachers, False)
    leads = await get_recent_leads(500)
    debt = await tool_list_debtors(ctx)
    active = [s for s in students if str(s.get("Status") or "").strip() == "O'qiyapti"]
    return {
        "active_students": len(active),
        "reserve_students": len(students) - len(active),
        "groups": len(groups),
        "groups_without_teacher": [
            g.get("Guruh_Nomi")
            for g in groups
            if not str(g.get("Ustoz_ID") or g.get("Ustoz_Chat_ID") or "").strip()
        ],
        "teachers": len(teachers),
        "debtors": debt.get("count", 0),
        "total_debt_uzs": debt.get("total_debt_uzs", 0),
        "leads_new": sum(1 for r in leads if r.get("status") != "contacted"),
        "leads_contacted": sum(1 for r in leads if r.get("status") == "contacted"),
    }


async def tool_prepare_attendance(
    ctx: ToolContext,
    group: str = "",
    date: str = "bugun",
    absent: Optional[list[str]] = None,
    present: Optional[list[str]] = None,
    session: int = 0,
) -> dict[str, Any]:
    """
    Attendance draft: everyone ✅ except `absent`; when only `present` is
    given, everyone else is ❌. Today or a past lesson date of the active cycle.
    """
    grp, err = await _match_group(ctx, group)
    if not grp:
        return err
    name = grp["Guruh_Nomi"]
    lesson_day = _parse_lesson_date(date or "bugun")
    today = today_tashkent()
    if lesson_day is None:
        return {"error": "invalid_date", "hint": "DD.MM, 'bugun' or 'kecha'"}
    if lesson_day > today:
        return {"error": "future_date_not_allowed"}
    sheets = get_sheets_manager()
    cat = await asyncio.to_thread(
        sheets.get_group_lesson_dates_categorized, name, today.strftime("%d.%m.%Y"), "latn"
    )
    if lesson_day == today:
        entries = list(cat.get("today_lessons") or [])
    else:
        entries = [
            e for e in cat.get("past_lessons") or [] if e.get("full_date") == lesson_day.isoformat()
        ]
    if not entries:
        return {
            "error": "not_a_lesson_date_of_active_cycle",
            "recent_lesson_dates": [e.get("full_date_dmy") for e in (cat.get("past_lessons") or [])[:8]],
        }
    with_session = [e for e in entries if e.get("session")]
    chosen = entries[0]
    if len(with_session) > 1:
        if int(session or 0) not in {1, 2}:
            return {"error": "double_lesson_day_session_required", "sessions": [1, 2]}
        chosen = next(e for e in with_session if int(e["session"]) == int(session))
    if chosen.get("is_cancelled"):
        return {"error": "lesson_cancelled"}
    roster = _active_roster(await ctx.students(), name)
    if not roster:
        return {"error": "no_active_students"}
    default_mark = "❌" if (present and not absent) else "✅"
    marks = {str(s["Talaba_ID"]): default_mark for s in roster}
    for query, mark in [(q, "❌") for q in (absent or [])] + [(q, "✅") for q in (present or [])]:
        hit, miss = _fuzzy_pick(str(query), roster)
        if not hit:
            miss["roster"] = [s.get("F.I.O.") for s in roster]
            return miss
        marks[str(hit["Talaba_ID"])] = mark
    payload = {
        "group": name,
        "date": lesson_day.isoformat(),
        "date_dmy": lesson_day.strftime("%d.%m.%Y"),
        "session": int(chosen.get("session") or 0) or None,
        "already_marked": bool(chosen.get("is_marked")),
        "marks": marks,
        "names": {str(s["Talaba_ID"]): str(s.get("F.I.O.") or "") for s in roster},
    }
    return await _make_draft(ctx, "attendance", payload)


async def tool_prepare_payment_revert(
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
    cycles = await asyncio.to_thread(_fetch_full_cycle_history_sync, grp_name, str(stu["Talaba_ID"]))
    paid = [c for c in cycles if c.get("is_paid")]
    if not paid:
        return {"error": "no_paid_cycle", "student": stu.get("F.I.O.")}
    if cycle:
        q = _norm(cycle)
        chosen = next((c for c in paid if q in _norm(c.get("cycle_title"))), None)
        if chosen is None:
            return {"error": "cycle_not_found", "paid_cycles": [c["cycle_title"] for c in paid]}
    else:
        paid.sort(key=lambda c: int(c.get("cycle_number") or 0))
        chosen = paid[-1]
    payload = {
        "student_id": str(stu["Talaba_ID"]),
        "student_name": str(stu.get("F.I.O.") or ""),
        "group": grp_name,
        "cycle_title": chosen["cycle_title"],
        "amount": int(chosen.get("prorated_amount") or 0),
    }
    return await _make_draft(ctx, "payment_revert", payload)


async def tool_prepare_student_edit(
    ctx: ToolContext, student: str = "", field: str = "", value: str = ""
) -> dict[str, Any]:
    column = STUDENT_EDITABLE_FIELDS.get(str(field or "").strip()) or STUDENT_EDITABLE_FIELDS.get(
        _norm(field)
    )
    if not column:
        return {"error": "field_not_editable", "allowed": sorted(set(STUDENT_EDITABLE_FIELDS.values()))}
    new_val = " ".join(str(value or "").split())
    if not new_val:
        return {"error": "value_required"}
    stu, err = await _match_student(ctx, student)
    if not stu:
        return err
    payload = {
        "student_id": str(stu["Talaba_ID"]),
        "student_name": str(stu.get("F.I.O.") or ""),
        "group": str(stu.get("Guruh") or ""),
        "field": column,
        "old_value": str(stu.get(column) or ""),
        "new_value": new_val[:120],
    }
    return await _make_draft(ctx, "student_edit", payload)


async def tool_prepare_device_link(
    ctx: ToolContext, student: str = "", phone: str = ""
) -> dict[str, Any]:
    stu, err = await _match_student(ctx, student)
    if not stu:
        return err
    clean_phone = ""
    if phone:
        digits = re.sub(r"\D", "", phone)
        if len(digits) < 7 or len(digits) > 15:
            return {"error": "invalid_phone"}
        clean_phone = phone.strip()
    payload = {
        "student_id": str(stu["Talaba_ID"]),
        "student_name": str(stu.get("F.I.O.") or ""),
        "group": str(stu.get("Guruh") or ""),
        "phone": clean_phone,
    }
    return await _make_draft(ctx, "device_link", payload)


async def tool_prepare_student_transfer(
    ctx: ToolContext, student: str = "", target_group: str = "", keep_in_old_group: bool = False
) -> dict[str, Any]:
    stu, err = await _match_student(ctx, student)
    if not stu:
        return err
    grp, err = await _match_group(ctx, target_group)
    if not grp:
        return err
    old_group = str(stu.get("Guruh") or "").strip()
    if old_group.lower() == grp["Guruh_Nomi"].strip().lower():
        return {"error": "already_in_this_group"}
    payload = {
        "student_id": str(stu["Talaba_ID"]),
        "student_name": str(stu.get("F.I.O.") or ""),
        "old_group": old_group,
        "group": grp["Guruh_Nomi"],
        "keep_in_old_group": bool(keep_in_old_group),
    }
    return await _make_draft(ctx, "student_transfer", payload)


async def tool_prepare_student_delete(ctx: ToolContext, student: str = "") -> dict[str, Any]:
    stu, err = await _match_student(ctx, student)
    if not stu:
        return err
    payload = {
        "student_id": str(stu["Talaba_ID"]),
        "student_name": str(stu.get("F.I.O.") or ""),
        "group": str(stu.get("Guruh") or ""),
    }
    return await _make_draft(ctx, "student_delete", payload)


async def tool_prepare_group_create(
    ctx: ToolContext,
    name: str = "",
    teacher: str = "",
    lesson_count: int = 12,
    lesson_days: str = "",
    lesson_time: str = "",
    monthly_fee: str = "",
    lessons_per_day: int = 1,
    start_date: str = "",
) -> dict[str, Any]:
    from app.handlers.groups_info import _format_days_from_indices

    group_name = str(name or "").strip()
    if not group_name or group_name in {"__cancel__", "__back__"}:
        return {"error": "group_name_required"}
    if await asyncio.to_thread(get_sheets_manager().get_group, group_name):
        return {"error": "group_already_exists"}
    days = parse_weekdays(lesson_days)
    if not days:
        return {"error": "lesson_days_required", "hint": "Du, Se, Chor, Pay, Ju, Shan, Yak"}
    count = int(lesson_count or 12)
    if count not in {8, 12}:
        return {"error": "lesson_count_must_be_8_or_12"}
    daily = 2 if int(lessons_per_day or 1) >= 2 else 1
    raw_time = str(lesson_time or "").strip()
    if not raw_time or is_agreed_lesson_time(raw_time):
        time_value = AGREED_LESSON_TIME
    else:
        time_value = normalize_session_times(raw_time, daily) or ""
        if not time_value:
            _u, per_day = parse_lesson_sessions(raw_time)
            if not per_day or not all(d in per_day for d in days):
                return {"error": "invalid_time", "hint": "'14:00', '10:00 / 11:30' or 'Du 14:00, Chor 15:30'"}
            time_value = ", ".join(
                f"{LESSON_DAY_ABBR[i]} {' / '.join(per_day[i])}" for i in sorted(per_day)
            )
    fee = _parse_fee(monthly_fee) if monthly_fee else 0
    if monthly_fee and fee is None:
        return {"error": "invalid_fee"}
    teacher_chat, teacher_label = "", ""
    if teacher:
        tch, err = await _match_teacher(teacher)
        if not tch:
            return err
        teacher_chat = str(tch.get("Chat_ID") or tch.get("Ustoz_Chat_ID") or "").strip()
        teacher_label = str(tch.get("F.I.O.") or tch.get("Ustoz_ID") or "").strip()
        if not teacher_chat:
            return {"error": "teacher_not_registered_in_bot", "teacher": teacher_label}
    start_iso = ""
    if start_date:
        parsed = _parse_lesson_date(start_date)
        if parsed is None:
            return {"error": "invalid_start_date"}
        start_iso = parsed.isoformat()
    payload = {
        "group": group_name,
        "teacher_chat_id": teacher_chat,
        "teacher_label": teacher_label,
        "lesson_count": count,
        "selected_days": days,
        "days_text": _format_days_from_indices(days, "latn"),
        "lesson_time": time_value,
        "monthly_fee": fee or 0,
        "daily_lessons": daily,
        "start_date": start_iso,
    }
    return await _make_draft(ctx, "group_create", payload)


async def tool_prepare_group_update(
    ctx: ToolContext,
    group: str = "",
    new_name: str = "",
    teacher: str = "",
    monthly_fee: str = "",
    lesson_days: str = "",
    lesson_time: str = "",
    lesson_count: int = 0,
) -> dict[str, Any]:
    grp, err = await _match_group(ctx, group)
    if not grp:
        return err
    payload: dict[str, Any] = {"group": grp["Guruh_Nomi"], "changes": {}}
    changes = payload["changes"]
    if lesson_days or lesson_time or lesson_count:
        sched = _validate_schedule(grp, lesson_time, lesson_days, lesson_count)
        if sched.get("error"):
            return sched
        if sched.pop("changed"):
            changes["schedule"] = {"old": sched["old"], "new": sched["new"]}
    if monthly_fee:
        fee = _parse_fee(monthly_fee)
        if fee is None:
            return {"error": "invalid_fee"}
        changes["fee"] = {"old": str(grp.get("Oylik_Tolov_Summa") or ""), "new": fee}
    if teacher:
        tch, err = await _match_teacher(teacher)
        if not tch:
            return err
        changes["teacher"] = {
            "teacher_id": str(tch.get("Ustoz_ID") or tch.get("Chat_ID") or ""),
            "teacher_name": str(tch.get("F.I.O.") or ""),
        }
    clean_name = str(new_name or "").strip()
    if clean_name and clean_name != grp["Guruh_Nomi"]:
        existing = await asyncio.to_thread(get_sheets_manager().get_group, clean_name)
        if existing and existing["Guruh_Nomi"].strip().lower() != grp["Guruh_Nomi"].strip().lower():
            return {"error": "group_name_taken"}
        changes["name"] = {"old": grp["Guruh_Nomi"], "new": clean_name}
    if not changes:
        return {"error": "nothing_changes"}
    return await _make_draft(ctx, "group_update", payload)


async def tool_prepare_group_delete(ctx: ToolContext, group: str = "") -> dict[str, Any]:
    grp, err = await _match_group(ctx, group)
    if not grp:
        return err
    roster = _active_roster(await ctx.students(), grp["Guruh_Nomi"])
    return await _make_draft(
        ctx, "group_delete", {"group": grp["Guruh_Nomi"], "active_students": len(roster)}
    )


async def tool_prepare_teacher_invite(ctx: ToolContext, group: str = "") -> dict[str, Any]:
    linked = ""
    if group:
        grp, err = await _match_group(ctx, group)
        if not grp:
            return err
        linked = grp["Guruh_Nomi"]
    return await _make_draft(ctx, "teacher_invite", {"group": linked})


async def tool_prepare_teacher_assign(
    ctx: ToolContext, teacher: str = "", group: str = ""
) -> dict[str, Any]:
    grp, err = await _match_group(ctx, group)
    if not grp:
        return err
    tch, err = await _match_teacher(teacher)
    if not tch:
        return err
    return await _make_draft(
        ctx,
        "teacher_assign",
        {
            "group": grp["Guruh_Nomi"],
            "teacher_id": str(tch.get("Ustoz_ID") or tch.get("Chat_ID") or ""),
            "teacher_name": str(tch.get("F.I.O.") or ""),
        },
    )


async def tool_prepare_teacher_delete(ctx: ToolContext, teacher: str = "") -> dict[str, Any]:
    tch, err = await _match_teacher(teacher)
    if not tch:
        return err
    return await _make_draft(
        ctx,
        "teacher_delete",
        {
            "teacher_id": str(tch.get("Ustoz_ID") or ""),
            "teacher_name": str(tch.get("F.I.O.") or ""),
        },
    )


ToolFn = Callable[..., Awaitable[dict[str, Any]]]

_BOTH = {"admin", "teacher"}
_ADMIN = {"admin"}
_OBJ = "object"


def _schema(props: dict[str, Any], required: Optional[list[str]] = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": _OBJ, "properties": props}
    if required:
        schema["required"] = required
    return schema


_S = {"type": "string"}
_I = {"type": "integer"}
_B = {"type": "boolean"}
_LIST = {"type": "array", "items": {"type": "string"}}

# name -> (allowed roles, description, JSON schema of parameters, implementation)
# Teacher tools are additionally scoped to the teacher's OWN groups/students in
# Python (ToolContext.groups()/students()), never only by the prompt.
TOOLS: dict[str, tuple[set[str], str, dict[str, Any], ToolFn]] = {
    # ---------------- read (both roles; teacher = own groups only)
    "list_groups": (_BOTH, "Groups with teacher, days, time, lessons done/monthly, fee, active students.", _schema({}), tool_list_groups),
    "list_today_groups": (_BOTH, "Groups that have a lesson TODAY.", _schema({}), tool_list_today_groups),
    "group_details": (_BOTH, "One group's schedule, active roster and active-cycle lesson dates with status.", _schema({"group": _S}, ["group"]), tool_group_details),
    "group_contacts": (_BOTH, "Clickable contacts of a group's students and their father/mother.", _schema({"group": _S}, ["group"]), tool_group_contacts),
    "list_students": (_BOTH, "Students. status: active | zaxira | all. Optional group.", _schema({"status": {"type": "string", "enum": ["active", "zaxira", "all"]}, "group": _S}), tool_list_students),
    "list_debtors": (_BOTH, "Debtors summary with exact debt in UZS (optional group).", _schema({"group": _S}), tool_list_debtors),
    "debtor_lesson_dates": (_BOTH, "Detailed debtor view: unpaid cycles with every lesson date and attendance status.", _schema({"student": _S}, ["student"]), tool_debtor_lesson_dates),
    "list_lesson_topics": (_BOTH, "Saved lesson topics of a group.", _schema({"group": _S, "limit": _I}, ["group"]), tool_list_lesson_topics),
    "student_invite_link": (_BOTH, "Student self-join invite link (?start=join_...) of a group.", _schema({"group": _S}, ["group"]), tool_student_invite_link),
    # ---------------- drafts (both roles; teacher = own groups only)
    "prepare_attendance": (
        _BOTH,
        "DRAFT attendance (📋 Yo'qlama) for today or a PAST lesson date (never future). "
        "absent = names who missed; present = names who came (then the rest are absent). "
        "session = 1 or 2 on double-lesson days.",
        _schema({"group": _S, "date": _S, "absent": _LIST, "present": _LIST, "session": _I}, ["group"]),
        tool_prepare_attendance,
    ),
    "prepare_payment_confirmation": (_BOTH, "DRAFT confirming a student's payment for an unpaid cycle (oldest if omitted).", _schema({"student": _S, "group": _S, "cycle": _S}, ["student"]), tool_prepare_payment_confirmation),
    "prepare_payment_revert": (_BOTH, "DRAFT reverting (cancelling) a confirmed payment of a paid cycle (latest if omitted).", _schema({"student": _S, "group": _S, "cycle": _S}, ["student"]), tool_prepare_payment_revert),
    "prepare_lesson_topic": (_BOTH, "DRAFT saving AND publishing a lesson topic/plan (date DD.MM, 'bugun', 'ertaga').", _schema({"group": _S, "date": _S, "topic": _S, "plan": _S}, ["group", "topic"]), tool_prepare_lesson_topic),
    "prepare_student_status": (_BOTH, "DRAFT: action 'to_zaxira' (O'qimayapti) or 'restore' (O'qiyapti, target_group default former group).", _schema({"student": _S, "action": {"type": "string", "enum": ["to_zaxira", "restore"]}, "target_group": _S}, ["student", "action"]), tool_prepare_student_status),
    "prepare_student_edit": (_BOTH, "DRAFT editing one student field: F.I.O., Talaba_Tel, Talaba_TG, Otasi_FIO, Otasi_Tel, Onasi_FIO, Onasi_Tel.", _schema({"student": _S, "field": _S, "value": _S}, ["student", "field", "value"]), tool_prepare_student_edit),
    "prepare_device_link": (_BOTH, "DRAFT generating the device-binding link (?start=stu_<ID>) for a student without the bot; optional phone.", _schema({"student": _S, "phone": _S}, ["student"]), tool_prepare_device_link),
    "prepare_student_transfer": (_BOTH, "DRAFT moving a student to another group; keep_in_old_group=true keeps them in both groups.", _schema({"student": _S, "target_group": _S, "keep_in_old_group": _B}, ["student", "target_group"]), tool_prepare_student_transfer),
    # ---------------- admin only
    "list_leads": (_ADMIN, "Leads (Qiziquvchilar_Lidlar). only_new=true hides contacted ones.", _schema({"only_new": _B, "limit": _I}), tool_list_leads),
    "list_teachers": (_ADMIN, "All teachers with phone, username, status and their groups.", _schema({}), tool_list_teachers),
    "center_statistics": (_ADMIN, "Center statistics: active/reserve students, groups, teachers, debtors, leads.", _schema({}), tool_center_statistics),
    "prepare_schedule_update": (_ADMIN, "DRAFT changing a group's lesson time / days / monthly lesson count (8 or 12).", _schema({"group": _S, "lesson_time": _S, "lesson_days": _S, "lesson_count": _I}, ["group"]), tool_prepare_schedule_update),
    "prepare_group_create": (
        _ADMIN,
        "DRAFT creating a group: name, teacher (name or Ustoz_ID), lesson_count 8/12, lesson_days "
        "('Du, Chor, Ju'), lesson_time ('14:00' / 'Du 14:00, Chor 15:30' / empty = Kelishilgan vaqtda), "
        "monthly_fee, lessons_per_day 1/2, optional start_date.",
        _schema({"name": _S, "teacher": _S, "lesson_count": _I, "lesson_days": _S, "lesson_time": _S, "monthly_fee": _S, "lessons_per_day": _I, "start_date": _S}, ["name", "lesson_days"]),
        tool_prepare_group_create,
    ),
    "prepare_group_update": (_ADMIN, "DRAFT updating a group: new_name, teacher, monthly_fee, lesson_days, lesson_time, lesson_count (only what changes).", _schema({"group": _S, "new_name": _S, "teacher": _S, "monthly_fee": _S, "lesson_days": _S, "lesson_time": _S, "lesson_count": _I}, ["group"]), tool_prepare_group_update),
    "prepare_group_delete": (_ADMIN, "DRAFT deleting a group (Guruhlar row + its {Group}_{Year} sheets; students go to Zahira).", _schema({"group": _S}, ["group"]), tool_prepare_group_delete),
    "prepare_teacher_invite": (_ADMIN, "DRAFT creating a one-time teacher invite link (?start=tch_...), optionally bound to a group.", _schema({"group": _S}), tool_prepare_teacher_invite),
    "prepare_teacher_assign": (_ADMIN, "DRAFT assigning an existing teacher to a group.", _schema({"teacher": _S, "group": _S}, ["teacher", "group"]), tool_prepare_teacher_assign),
    "prepare_teacher_delete": (_ADMIN, "DRAFT permanently deleting a teacher.", _schema({"teacher": _S}, ["teacher"]), tool_prepare_teacher_delete),
    "prepare_student_delete": (_ADMIN, "DRAFT permanently deleting a student (Sheets + SQLite purge incl. orphaned parents).", _schema({"student": _S}, ["student"]), tool_prepare_student_delete),
    "prepare_lead_contacted": (_ADMIN, "DRAFT marking a lead as \"Bog'lanildi\" (lead id, name or phone).", _schema({"lead": _S}, ["lead"]), tool_prepare_lead_contacted),
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
        "5. Lesson day abbreviations: Du, Se, Chor, Pay, Ju, Shan, Yak.\n"
        "6. Attendance: 'hamma keldi' = absent []; 'faqat X kelmadi' = absent [X]; "
        "'bugun' = today, 'kecha' = yesterday. Never use a future date.\n"
        "7. You can do everything the user's role can do with the bot's buttons: read "
        "data with the list/details tools and prepare changes with prepare_* tools. "
        "If a needed detail is missing (e.g. which group), ask one short question."
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
    bot: Any = None,
) -> AiReply:
    """Runs one assistant turn (text or voice) with the tool loop."""
    from google.genai import errors, types

    lang = detect_script(text, lang_hint) if text else (lang_hint if lang_hint in TEXTS else "latn")
    if not AI_ENABLED:
        return AiReply("", lang=lang)
    ctx = ToolContext(user_id, role, lang, actor_name, bot)

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


_CARD_TITLES: dict[str, tuple[str, str]] = {
    # action: (latn, cyrl)
    "schedule": ("🗓 <b>Dars jadvalini o‘zgartirish</b>", "🗓 <b>Дарс жадвалини ўзгартириш</b>"),
    "payment": ("💳 <b>To‘lovni tasdiqlash</b>", "💳 <b>Тўловни тасдиқлаш</b>"),
    "payment_revert": ("↩️ <b>To‘lovni bekor qilish</b>", "↩️ <b>Тўловни бекор қилиш</b>"),
    "to_zaxira": ("⏸ <b>Talabani Zaxiraga o‘tkazish</b>", "⏸ <b>Талабани Захирага ўтказиш</b>"),
    "restore": ("▶️ <b>Talabani darsga tiklash</b>", "▶️ <b>Талабани дарсга тиклаш</b>"),
    "lead": ("📞 <b>Lid bilan bog‘lanildi</b>", "📞 <b>Лид билан боғланилди</b>"),
    "topic": ("📝 <b>Dars mavzusini saqlash va e’lon qilish</b>", "📝 <b>Дарс мавзусини сақлаш ва эълон қилиш</b>"),
    "attendance": ("📋 <b>Yo‘qlama</b>", "📋 <b>Йўқлама</b>"),
    "student_edit": ("✏️ <b>Talaba ma’lumotini o‘zgartirish</b>", "✏️ <b>Талаба маълумотини ўзгартириш</b>"),
    "device_link": ("📱 <b>Qurilmaga ulash havolasi</b>", "📱 <b>Қурилмага улаш ҳаволаси</b>"),
    "student_transfer": ("🔄 <b>Talabani boshqa guruhga o‘tkazish</b>", "🔄 <b>Талабани бошқа гуруҳга ўтказиш</b>"),
    "student_delete": ("🗑 <b>Talabani butunlay o‘chirish</b>", "🗑 <b>Талабани бутунлай ўчириш</b>"),
    "group_create": ("➕ <b>Yangi guruh yaratish</b>", "➕ <b>Янги гуруҳ яратиш</b>"),
    "group_update": ("✏️ <b>Guruhni tahrirlash</b>", "✏️ <b>Гуруҳни таҳрирлаш</b>"),
    "group_delete": ("🗑 <b>Guruhni o‘chirish</b>", "🗑 <b>Гуруҳни ўчириш</b>"),
    "teacher_invite": ("🔗 <b>Ustoz taklif havolasi</b>", "🔗 <b>Устоз таклиф ҳаволаси</b>"),
    "teacher_assign": ("👨‍🏫 <b>Ustozni guruhga biriktirish</b>", "👨‍🏫 <b>Устозни гуруҳга бириктириш</b>"),
    "teacher_delete": ("🗑 <b>Ustozni o‘chirish</b>", "🗑 <b>Устозни ўчириш</b>"),
}


def _schedule_change_lines(old: dict[str, Any], new: dict[str, Any], lang: str) -> list[str]:
    """Only the schedule fields that really change (days / time / lesson count)."""
    from app.handlers.groups_info import _format_days_from_indices

    esc = html.escape
    lines: list[str] = []
    old_idx = parse_weekdays(old.get("days") or "")
    new_idx = list(new.get("days_idx") or [])
    if old_idx != new_idx:
        lines.append(
            f"{tr('lbl_days', lang)}: {esc(_format_days_from_indices(old_idx, lang) or '—')} ➡️ "
            f"<b>{esc(_format_days_from_indices(new_idx, lang))}</b>"
        )
    if str(old.get("time") or "").strip() != str(new.get("time") or "").strip():
        lines.append(
            f"{tr('lbl_time', lang)}: {esc(format_lesson_time_display(old.get('time'), lang) or '—')} ➡️ "
            f"<b>{esc(format_lesson_time_display(new.get('time'), lang) or '—')}</b>"
        )
    if str(old.get("count")) != str(new.get("count")):
        lines.append(
            f"{tr('lbl_count', lang)}: {esc(str(old.get('count')))} ➡️ <b>{esc(str(new.get('count')))}</b>"
        )
    return lines


def render_draft_card(action: str, payload: dict[str, Any], lang: str) -> str:
    esc = html.escape
    cy = lang == "cyrl"
    title = _CARD_TITLES.get(action, ("📝 <b>Qoralama</b>", "📝 <b>Қоралама</b>"))[1 if cy else 0]
    lines: list[str] = [title + (" (қоралама)" if cy else " (qoralama)"), ""]
    group_line = f"{tr('lbl_group', lang)}: <b>{esc(str(payload.get('group') or '—'))}</b>"
    student_line = (
        f"{tr('lbl_student', lang)}: <b>{esc(str(payload.get('student_name') or ''))}</b> "
        f"({esc(str(payload.get('student_id') or ''))})"
    )
    if action == "schedule":
        lines += [group_line, *_schedule_change_lines(payload["old"], payload["new"], lang)]
    elif action in {"payment", "payment_revert"}:
        lines += [student_line, group_line, f"{tr('lbl_cycle', lang)}: <b>{esc(payload['cycle_title'])}</b>"]
        if int(payload.get("amount") or 0) > 0:
            lines.append(f"{tr('lbl_amount', lang)}: <b>{_fmt_money(payload['amount'])} so'm</b>")
    elif action in {"to_zaxira", "restore", "student_delete", "device_link"}:
        lines += [student_line, group_line]
        if action == "device_link" and payload.get("phone"):
            lines.append(f"📱 <b>{esc(payload['phone'])}</b>")
    elif action == "student_edit":
        lines += [
            student_line,
            f"🔤 {esc(payload['field'])}: {esc(payload['old_value'] or '—')} ➡️ <b>{esc(payload['new_value'])}</b>",
        ]
    elif action == "student_transfer":
        keep = payload.get("keep_in_old_group")
        lines += [
            student_line,
            f"📚 {esc(payload.get('old_group') or '—')} ➡️ <b>{esc(payload['group'])}</b>",
            ("✅ Eski guruhda ham qoladi" if not cy else "✅ Эски гуруҳда ҳам қолади")
            if keep
            else ("🚪 Eski guruhdan chiqariladi" if not cy else "🚪 Эски гуруҳдан чиқарилади"),
        ]
    elif action == "lead":
        lines += [
            f"{tr('lbl_lead', lang)}: <b>#{payload['lead_id']} {esc(str(payload.get('name') or ''))}</b>",
            f"📱 {esc(str(payload.get('phone') or '—'))} | 📚 {esc(str(payload.get('course') or '—'))}",
        ]
    elif action == "topic":
        lines += [
            group_line,
            f"{tr('lbl_date', lang)}: <b>{esc(payload['date_full'])}</b>",
            f"{tr('lbl_topic', lang)}: <b>{esc(payload['topic'])}</b>",
        ]
        if payload.get("plan"):
            lines.append(f"{tr('lbl_plan', lang)}: {esc(payload['plan'][:500])}")
    elif action == "attendance":
        session = payload.get("session")
        lines += [
            group_line,
            f"{tr('lbl_date', lang)}: <b>{esc(payload['date_dmy'])}</b>"
            + (f" — <b>{int(session)}-dars</b>" if session else ""),
        ]
        if payload.get("already_marked"):
            lines.append("♻️ Avval belgilangan — qayta yangilanadi" if not cy else "♻️ Аввал белгиланган — қайта янгиланади")
        lines.append("")
        for sid, mark in payload["marks"].items():
            name = esc(str(payload["names"].get(sid) or sid))
            if mark == "✅":
                lines.append(f"🟢 {name} — {'Қатнашди' if cy else 'Qatnashdi'}")
            else:
                lines.append(f"🔴 {name} — {'Келмади' if cy else 'Kelmadi'}")
    elif action == "group_create":
        lines += [
            f"{tr('lbl_group', lang)}: <b>{esc(payload['group'])}</b>",
            f"👨‍🏫 {esc(payload.get('teacher_label') or '—')}",
            f"{tr('lbl_days', lang)}: <b>{esc(payload['days_text'])}</b>",
            f"{tr('lbl_time', lang)}: <b>{esc(format_lesson_time_display(payload['lesson_time'], lang))}</b>",
            f"{tr('lbl_count', lang)}: <b>{payload['lesson_count']}</b>"
            + (" | 🔁 2/kun" if int(payload.get("daily_lessons") or 1) >= 2 else ""),
        ]
        if int(payload.get("monthly_fee") or 0) > 0:
            lines.append(f"{tr('lbl_amount', lang)}: <b>{_fmt_money(payload['monthly_fee'])} so'm</b>")
        if payload.get("start_date"):
            lines.append(f"{tr('lbl_date', lang)}: <b>{esc(payload['start_date'])}</b>")
    elif action == "group_update":
        changes = payload["changes"]
        lines.append(group_line)
        if "name" in changes:
            lines.append(f"📝 {esc(changes['name']['old'])} ➡️ <b>{esc(changes['name']['new'])}</b>")
        if "teacher" in changes:
            lines.append(f"👨‍🏫 ➡️ <b>{esc(changes['teacher']['teacher_name'])}</b>")
        if "fee" in changes:
            lines.append(
                f"{tr('lbl_amount', lang)}: {esc(changes['fee']['old'] or '—')} ➡️ "
                f"<b>{_fmt_money(changes['fee']['new'])} so'm</b>"
            )
        if "schedule" in changes:
            lines += _schedule_change_lines(
                changes["schedule"]["old"], changes["schedule"]["new"], lang
            )
    elif action == "group_delete":
        lines += [
            group_line,
            (
                f"⚠️ Guruh varaqlari o‘chiriladi, {payload.get('active_students', 0)} ta talaba Zahira guruhiga o‘tadi."
                if not cy
                else f"⚠️ Гуруҳ варақлари ўчирилади, {payload.get('active_students', 0)} та талаба Захира гуруҳига ўтади."
            ),
        ]
    elif action == "teacher_invite":
        lines.append(group_line)
    elif action in {"teacher_assign", "teacher_delete"}:
        lines.append(f"👨‍🏫 <b>{esc(str(payload.get('teacher_name') or ''))}</b> ({esc(str(payload.get('teacher_id') or ''))})")
        if action == "teacher_assign":
            lines.append(group_line)
    lines += ["", f"<i>{tr('draft_hint', lang)}</i>"]
    return "\n".join(lines)


_ACTION_ROLES: dict[str, set[str]] = {
    "attendance": _BOTH,
    "payment": _BOTH,
    "payment_revert": _BOTH,
    "topic": _BOTH,
    "to_zaxira": _BOTH,
    "restore": _BOTH,
    "student_edit": _BOTH,
    "device_link": _BOTH,
    "student_transfer": _BOTH,
    "schedule": _ADMIN,
    "lead": _ADMIN,
    "student_delete": _ADMIN,
    "group_create": _ADMIN,
    "group_update": _ADMIN,
    "group_delete": _ADMIN,
    "teacher_invite": _ADMIN,
    "teacher_assign": _ADMIN,
    "teacher_delete": _ADMIN,
}

_STUDENT_ACTIONS = {
    "payment", "payment_revert", "to_zaxira", "student_edit", "device_link",
    "student_transfer", "student_delete",
}


async def _run_schedule_change(
    bot: Any, actor_id: int, actor_name: str, group_name: str, old: dict[str, Any], new: dict[str, Any]
) -> int:
    """Existing "⏰/📆/🔢" schedule flow: rebuild cycle sheet + Audit_Log + broadcast."""
    from app.handlers.groups_info import _broadcast_group_update

    sheets = get_sheets_manager()
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
    return await _broadcast_group_update(
        bot,
        sheets,
        group_name,
        change_items=change_items or [("Dars_Vaqti", old["time"], new["time"])],
        dates_list=final_dates,
        triggered_by_user_id=actor_id,
    )


async def execute_draft(bot: Any, actor_id: int, actor_name: str, draft: dict[str, Any], lang: str) -> str:
    """Runs the confirmed draft through the existing helpers. Returns HTML text."""
    action = str(draft.get("action") or "")
    payload = dict(draft.get("payload") or {})
    role = await resolve_ai_role(actor_id)
    if role is None or role not in _ACTION_ROLES.get(action, set()):
        return tr("no_permission", lang)
    ctx = ToolContext(actor_id, role, lang, actor_name, bot)
    # Re-check scope at execution time (a teacher may have lost the group).
    group_name = str(payload.get("group") or "")
    if action not in {"group_create", "teacher_invite"} and group_name:
        if group_name.strip().lower() not in await ctx.group_names_lower():
            return tr("no_permission", lang)
    if action in _STUDENT_ACTIONS and role != "admin":
        visible = {str(s.get("Talaba_ID") or "") for s in await ctx.students()}
        if str(payload.get("student_id") or "") not in visible:
            return tr("no_permission", lang)
    esc = html.escape
    sheets = get_sheets_manager()

    if action == "schedule":
        sent = await _run_schedule_change(
            bot, actor_id, actor_name, group_name, payload["old"], payload["new"]
        )
        return tr("done_schedule", lang, group=esc(group_name), sent=sent)

    if action in {"payment", "payment_revert"}:
        from app.handlers.payments import execute_payment_confirmation

        result = await execute_payment_confirmation(
            bot,
            actor_id,
            actor_name,
            group_name,
            str(payload["student_id"]),
            str(payload["cycle_title"]),
            revert=action == "payment_revert",
        )
        if not result["ok"]:
            return tr("exec_failed", lang, reason=esc(result["reason"]))
        key = "done_payment_revert" if action == "payment_revert" else "done_payment"
        return tr(
            key,
            lang,
            student=esc(str(payload["student_name"])),
            group=esc(group_name),
            cycle=esc(str(payload["cycle_title"])),
        )

    if action == "attendance":
        from app.handlers.attendance import submit_attendance

        lesson_day = date.fromisoformat(str(payload["date"]))
        if lesson_day > today_tashkent():
            return tr("exec_failed", lang, reason="future_date")
        result = await submit_attendance(
            bot,
            actor_id,
            actor_name,
            lang,
            group_name,
            lesson_day,
            {str(k): str(v) for k, v in payload["marks"].items()},
            session=payload.get("session"),
        )
        return str(result.get("text") or "")

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

    if action == "student_edit":
        from app.handlers.students import execute_student_field_update

        updated = await execute_student_field_update(
            str(payload["student_id"]), str(payload["field"]), str(payload["new_value"])
        )
        if not updated:
            return tr("exec_failed", lang, reason="student_not_found")
        return tr(
            "done_student_edit",
            lang,
            student=esc(str(updated.get("F.I.O.") or payload["student_name"])),
            field=esc(str(payload["field"])),
            value=esc(str(payload["new_value"])),
        )

    if action == "device_link":
        from app.handlers.students import _attach_student_device_safe, _can_manage_student_device

        student = await sheets.a_get_student_by_id(str(payload["student_id"]))
        if not student or not await _can_manage_student_device(actor_id, student):
            return tr("no_permission", lang)
        updated = await _attach_student_device_safe(
            str(payload["student_id"]), new_phone=str(payload.get("phone") or "") or None
        )
        me = await bot.get_me()
        link = f"https://t.me/{me.username}?start=stu_{payload['student_id']}"
        return tr(
            "done_device_link",
            lang,
            student=esc(str((updated or student).get("F.I.O.") or payload["student_name"])),
            link=esc(link),
        )

    if action == "student_transfer":
        from app.handlers.students import execute_student_transfer

        result = await execute_student_transfer(
            bot,
            actor_id,
            lang,
            str(payload["student_id"]),
            group_name,
            bool(payload.get("keep_in_old_group")),
        )
        if not result.get("ok"):
            return tr("exec_failed", lang, reason="transfer_failed")
        return str(result["admin_notice"])

    if action == "student_delete":
        from app.handlers.students import execute_student_delete

        return await execute_student_delete(actor_id, actor_name, lang, str(payload["student_id"]))

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
        from app.handlers.schedule import publish_group_topics

        await save_lesson_topic(
            group_name=group_name,
            lesson_date=str(payload["date"]),
            topic=str(payload["topic"]),
            plan=str(payload.get("plan") or ""),
            teacher_id=actor_id,
            teacher_name=actor_name,
            is_published=0,
        )
        topic_count, sent = await publish_group_topics(
            bot=bot,
            group_name=group_name,
            lesson_dates=[str(payload["date"])],
            actor_user_id=actor_id,
        )
        return tr(
            "done_topic_published",
            lang,
            group=esc(group_name),
            date=esc(str(payload["date_full"])),
            sent=sent,
        )

    if action == "group_create":
        from app.handlers.groups_info import create_group_from_data

        data = {
            "group_name": group_name,
            "teacher_chat_id": str(payload.get("teacher_chat_id") or ""),
            "teacher_label": str(payload.get("teacher_label") or ""),
            "lesson_count": int(payload["lesson_count"]),
            "selected_days": list(payload["selected_days"]),
            "lesson_time": str(payload["lesson_time"]),
            "monthly_fee": int(payload.get("monthly_fee") or 0),
            "daily_lessons": int(payload.get("daily_lessons") or 1),
        }
        if payload.get("start_date"):
            data["start_date"] = str(payload["start_date"])
        result = await create_group_from_data(bot, actor_id, lang, data)
        text = str(result.get("text") or "")
        if result.get("ok"):
            text += "\n\n" + tr("link_group_hint", lang, group=esc(group_name))
        return text

    if action == "group_update":
        from app.handlers.groups_info import (
            _broadcast_group_update,
            _rename_group_in_sqlite,
            _sync_rename_group_everywhere,
            _sync_update_group_fee,
            execute_teacher_assignment,
        )

        changes = payload["changes"]
        done: list[str] = []
        current = group_name
        if "schedule" in changes:
            await _run_schedule_change(
                bot, actor_id, actor_name, current, changes["schedule"]["old"], changes["schedule"]["new"]
            )
            done.append("🗓")
        if "fee" in changes:
            new_fee = int(changes["fee"]["new"])
            await asyncio.to_thread(_sync_update_group_fee, sheets, current, new_fee)
            await log_audit_event(
                actor_id=actor_id,
                action=AUDIT_GROUP_EDITED,
                target=current,
                details=f"AI: Oylik_Tolov_Summa: {changes['fee']['old'] or '—'} → {new_fee}",
                actor_name=actor_name,
            )
            await _broadcast_group_update(
                bot,
                sheets,
                current,
                change_items=[("Oylik_Tolov_Summa", str(changes["fee"]["old"]), str(new_fee))],
                triggered_by_user_id=actor_id,
            )
            done.append("💰")
        if "teacher" in changes:
            assign = await execute_teacher_assignment(
                bot, actor_id, actor_name, lang, str(changes["teacher"]["teacher_id"]), current
            )
            done.append("👨‍🏫" if assign["status"] != "error" else "⚠️👨‍🏫")
        if "name" in changes:
            new_name = str(changes["name"]["new"])
            await asyncio.to_thread(_sync_rename_group_everywhere, sheets, current, new_name)
            await _rename_group_in_sqlite(current, new_name)
            await database.rename_group_weekly_reminder(current, new_name)
            await log_audit_event(
                actor_id=actor_id,
                action=AUDIT_GROUP_EDITED,
                target=new_name,
                details=f"AI: Guruh_Nomi: {current} → {new_name}",
                actor_name=actor_name,
            )
            await _broadcast_group_update(
                bot,
                sheets,
                new_name,
                change_items=[("Guruh_Nomi", current, new_name)],
                triggered_by_user_id=actor_id,
            )
            current = new_name
            done.append("📝")
        return tr("done_group_update", lang, group=esc(current), parts=" ".join(done))

    if action == "group_delete":
        from app.handlers.groups_info import execute_group_delete

        deleted, canonical = await execute_group_delete(actor_id, actor_name, group_name)
        if not deleted:
            return tr("exec_failed", lang, reason="group_not_found")
        return tr("done_group_delete", lang, group=esc(canonical))

    if action == "teacher_invite":
        from app.handlers.groups_info import create_teacher_invite_link

        link = await create_teacher_invite_link(bot, actor_id, group_name or None)
        return tr("done_teacher_invite", lang, group=esc(group_name or "—"), link=esc(link))

    if action == "teacher_assign":
        from app.handlers.groups_info import execute_teacher_assignment

        assign = await execute_teacher_assignment(
            bot, actor_id, actor_name, lang, str(payload["teacher_id"]), group_name
        )
        return str(assign["notice"])

    if action == "teacher_delete":
        from app.handlers.groups_info import execute_teacher_delete

        return await execute_teacher_delete(bot, actor_id, actor_name, lang, str(payload["teacher_id"]))

    return tr("draft_not_found", lang)
