"""
Centralised Uzbekistan time helpers.

Every date / time shown to Admins, Teachers, Students and Parents (and every
timestamp stored in SQLite) must come from here so the bot reports true
``Asia/Tashkent`` (UTC+5) local time even when the host runs on a UTC server
(for example Oracle Cloud Linux).
"""

import html
from datetime import date, datetime
from typing import Iterable, Optional, Union
from zoneinfo import ZoneInfo

TASHKENT_TZ_NAME: str = "Asia/Tashkent"
TASHKENT_TZ: ZoneInfo = ZoneInfo(TASHKENT_TZ_NAME)

DISPLAY_DT_FMT = "%d.%m.%Y %H:%M"
DISPLAY_DT_SEC_FMT = "%d.%m.%Y %H:%M:%S"


def now_tashkent() -> datetime:
    """Timezone-aware current datetime in Asia/Tashkent."""
    return datetime.now(TASHKENT_TZ)


def today_tashkent() -> date:
    """Today's calendar date in Asia/Tashkent."""
    return now_tashkent().date()


def tashkent_now_str(fmt: str = DISPLAY_DT_FMT) -> str:
    """Current Tashkent time formatted for display / storage."""
    return now_tashkent().strftime(fmt)


def to_tashkent(value: object) -> Optional[datetime]:
    """
    Converts an ISO string / datetime into an aware Asia/Tashkent datetime.
    Naive values are assumed to be UTC (legacy rows written before the
    Tashkent-time migration). Returns None when the value cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", DISPLAY_DT_SEC_FMT, DISPLAY_DT_FMT):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    dt = None  # type: ignore[assignment]
            if dt is None:
                return None
    if dt.tzinfo is None:
        from datetime import timezone as _tz

        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(TASHKENT_TZ)


def format_tashkent(value: object, fmt: str = DISPLAY_DT_FMT) -> str:
    """Formats any stored timestamp as Tashkent local time ('' if unparsable)."""
    dt = to_tashkent(value)
    return dt.strftime(fmt) if dt else ""


# ----------------------------------------------------------------------
# Per-day lesson times (stored in the existing ``Dars_Vaqti`` column)
#
#   uniform : "14:00"
#   per-day : "Du 14:00, Chor 15:30, Ju 17:00"
# ----------------------------------------------------------------------

import re as _re

# Canonical Uzbek day abbreviations used when WRITING per-day schedules.
LESSON_DAY_ABBR: dict[int, str] = {
    0: "Du",
    1: "Se",
    2: "Chor",
    3: "Pay",
    4: "Ju",
    5: "Shan",
    6: "Yak",
}

# Every spelling accepted when READING (canonical, long Latin and Cyrillic).
_LESSON_DAY_TOKENS: dict[str, int] = {
    "du": 0, "dush": 0, "dushanba": 0, "mon": 0, "душ": 0, "ду": 0, "душанба": 0,
    "se": 1, "sesh": 1, "seshanba": 1, "tue": 1, "сеш": 1, "се": 1, "сешанба": 1,
    "chor": 2, "ch": 2, "chorshanba": 2, "wed": 2, "чор": 2, "ч": 2, "чоршанба": 2,
    "pay": 3, "pa": 3, "payshanba": 3, "thu": 3, "пай": 3, "па": 3, "пайшанба": 3,
    "ju": 4, "jum": 4, "juma": 4, "fri": 4, "жум": 4, "жу": 4, "жума": 4,
    "shan": 5, "sh": 5, "shanba": 5, "sat": 5, "шан": 5, "ш": 5, "шанба": 5,
    "yak": 6, "ya": 6, "yakshanba": 6, "sun": 6, "як": 6, "якшанба": 6,
}

_SIMPLE_TIME_RE = _re.compile(r"^\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*$")
_PER_DAY_ENTRY_RE = _re.compile(
    r"^\s*([^\W\d_]+)\.?\s*[-:=]?\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*$",
    _re.UNICODE,
)
# Double lessons ("Juft dars"): "10:00 / 11:30" for every day, or per day
# "Shan 10:00 / 11:30, Yak 14:00 / 15:30".
_TIME_PAIR_RE = _re.compile(
    r"^\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*(?:/|\||\s)\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*$"
)
_PER_DAY_PAIR_ENTRY_RE = _re.compile(
    r"^\s*([^\W\d_]+)\.?\s*[-:=]?\s*(\d{1,2})\s*[:.]\s*(\d{2})"
    r"\s*(?:/|\|)\s*(\d{1,2})\s*[:.]\s*(\d{2})\s*$",
    _re.UNICODE,
)

# Individual groups whose time is agreed with the student each time.
AGREED_LESSON_TIME = "Kelishilgan vaqtda"
AGREED_LESSON_TIME_CYRL = "Келишилган вақтда"


def is_agreed_lesson_time(dars_vaqti: object) -> bool:
    """True for the 'Kelishilgan vaqtda' (flexible / agreed time) marker."""
    raw = " ".join(str(dars_vaqti or "").split()).casefold()
    return raw.startswith("kelishilgan") or raw.startswith("келишилган")


def normalize_hhmm(raw: object) -> Optional[str]:
    """'9:5' is invalid, '9:05' / '09.05' -> '09:05'; None if not a valid 00:00-23:59."""
    match = _SIMPLE_TIME_RE.match(str(raw or ""))
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return f"{hour:02d}:{minute:02d}"
    return None


def normalize_session_times(raw: object, daily_lessons: int = 1) -> Optional[str]:
    """
    Validates the time text typed for ONE day.
    daily_lessons == 1 -> '14:00'
    daily_lessons == 2 -> '10:00 / 11:30' (two times, the second one later)
    Returns the canonical string or None when invalid.
    """
    text = str(raw or "").strip()
    if int(daily_lessons or 1) >= 2:
        pair = _TIME_PAIR_RE.match(text)
        if not pair:
            return None
        first = normalize_hhmm(f"{pair.group(1)}:{pair.group(2)}")
        second = normalize_hhmm(f"{pair.group(3)}:{pair.group(4)}")
        if not first or not second or second <= first:
            return None
        return f"{first} / {second}"
    return normalize_hhmm(text)


def _session_value(value: object) -> list[str]:
    """'14:00' -> ['14:00']; '10:00 / 11:30' -> ['10:00', '11:30']; else []."""
    single = normalize_hhmm(value)
    if single:
        return [single]
    pair = _TIME_PAIR_RE.match(str(value or ""))
    if pair:
        first = normalize_hhmm(f"{pair.group(1)}:{pair.group(2)}")
        second = normalize_hhmm(f"{pair.group(3)}:{pair.group(4)}")
        if first and second:
            return [first, second]
    return []


def parse_lesson_sessions(
    dars_vaqti: object,
) -> tuple[Optional[list[str]], dict[int, list[str]]]:
    """
    Like parse_lesson_times, but keeps every session of the day:
    * "14:00"                               -> (["14:00"], {})
    * "10:00 / 11:30"                       -> (["10:00", "11:30"], {})
    * "Du 14:00, Chor 15:30"                -> (None, {0: ["14:00"], 2: ["15:30"]})
    * "Shan 10:00 / 11:30, Yak 14:00 / 15:30" -> (None, {5: [...], 6: [...]})
    * "Kelishilgan vaqtda" / empty / junk   -> (None, {})
    """
    raw = str(dars_vaqti or "").strip()
    if not raw or is_agreed_lesson_time(raw):
        return None, {}
    uniform = _session_value(raw)
    if uniform:
        return uniform, {}
    per_day: dict[int, list[str]] = {}
    for chunk in _re.split(r"[,;\n]+", raw):
        pair = _PER_DAY_PAIR_ENTRY_RE.match(chunk)
        if pair:
            idx = _LESSON_DAY_TOKENS.get(pair.group(1).lower())
            first = normalize_hhmm(f"{pair.group(2)}:{pair.group(3)}")
            second = normalize_hhmm(f"{pair.group(4)}:{pair.group(5)}")
            if idx is not None and first and second:
                per_day[idx] = [first, second]
            continue
        entry = _PER_DAY_ENTRY_RE.match(chunk)
        if not entry:
            continue
        idx = _LESSON_DAY_TOKENS.get(entry.group(1).lower())
        hhmm = normalize_hhmm(f"{entry.group(2)}:{entry.group(3)}")
        if idx is not None and hhmm:
            per_day[idx] = [hhmm]
    return None, per_day


def parse_lesson_times(dars_vaqti: object) -> tuple[Optional[str], dict[int, str]]:
    """
    Parses a ``Dars_Vaqti`` value into ``(uniform_time, per_day_times)``.
    For double lessons the FIRST session's start time is returned (used for
    pre-lesson reminders); see parse_lesson_sessions for every session.

    * "14:00"                         -> ("14:00", {})
    * "Du 14:00, Chor 15:30, Ju 17:00" -> (None, {0: "14:00", 2: "15:30", 4: "17:00"})
    * empty / unparsable / "Kelishilgan vaqtda" -> (None, {})
    """
    uniform, per_day = parse_lesson_sessions(dars_vaqti)
    if uniform:
        return uniform[0], {}
    return None, {idx: times[0] for idx, times in per_day.items() if times}


def get_lesson_sessions_for_weekday(
    dars_vaqti: str, target_date_or_weekday: Union[date, datetime, int, str, None]
) -> list[str]:
    """Every session start time ('HH:MM') of the given day, [] when none."""
    uniform, per_day = parse_lesson_sessions(dars_vaqti)
    if uniform:
        return list(uniform)
    weekday = _weekday_of(target_date_or_weekday)
    if weekday is None:
        return []
    return list(per_day.get(weekday, []))


def _weekday_of(target: Union[date, datetime, int, str, None]) -> Optional[int]:
    if target is None:
        return None
    if isinstance(target, datetime):
        dt = target if target.tzinfo else target.replace(tzinfo=TASHKENT_TZ)
        return dt.astimezone(TASHKENT_TZ).weekday()
    if isinstance(target, date):
        return target.weekday()
    if isinstance(target, int):
        return target if 0 <= target <= 6 else None
    return _LESSON_DAY_TOKENS.get(str(target).strip().lower().rstrip("."))


def get_lesson_time_for_weekday(
    dars_vaqti: str, target_date_or_weekday: Union[date, datetime, int, str, None]
) -> Optional[str]:
    """
    'HH:MM' lesson time for the given date / weekday index (0=Mon) / weekday name.

    A simple "HH:MM" value applies to every day. A per-day value returns the exact
    time of that weekday, or None when the group has no lesson on that weekday.
    Aware datetimes are converted to Asia/Tashkent first.
    """
    uniform, per_day = parse_lesson_times(dars_vaqti)
    if uniform:
        return uniform
    weekday = _weekday_of(target_date_or_weekday)
    if weekday is None:
        return None
    return per_day.get(weekday)


def is_per_day_lesson_time(dars_vaqti: object) -> bool:
    return bool(parse_lesson_times(dars_vaqti)[1])


def build_per_day_lesson_time(times_by_weekday: dict[int, str]) -> str:
    """
    {0: '14:00', 2: '15:30'} -> 'Du 14:00, Chor 15:30' (weekday order).
    Double lessons: {5: '10:00 / 11:30'} -> 'Shan 10:00 / 11:30'.
    """
    parts: list[str] = []
    for idx in sorted(times_by_weekday):
        sessions = _session_value(times_by_weekday[idx])
        if sessions and idx in LESSON_DAY_ABBR:
            parts.append(f"{LESSON_DAY_ABBR[idx]} {' / '.join(sessions)}")
    return ", ".join(parts)


def format_lesson_time_display(dars_vaqti: object, lang: str = "latn") -> str:
    """
    Value for a card's single "time" slot: '14:00' for uniform schedules,
    'Dush 14:00, Chor 15:30, Jum 17:00' for per-day ones (plain text, not HTML-escaped).
    Unparsable legacy text is returned unchanged; empty -> ''.
    """
    from app.locales import WEEKDAYS_SHORT

    raw = str(dars_vaqti or "").strip()
    if is_agreed_lesson_time(raw):
        return AGREED_LESSON_TIME_CYRL if lang == "cyrl" else AGREED_LESSON_TIME
    uniform, per_day = parse_lesson_sessions(raw)
    if uniform:
        return " / ".join(uniform)
    if not per_day:
        return raw
    names = WEEKDAYS_SHORT.get(lang) or WEEKDAYS_SHORT["latn"]
    return ", ".join(
        f"{names[idx]} {' / '.join(per_day[idx])}" for idx in sorted(per_day)
    )


def format_group_schedule(
    dars_kunlari: str, dars_vaqti: str, lang: str = "latn"
) -> str:
    """
    Single-string schedule for group cards.

    * uniform : 'Dush, Chor, Jum — 14:00'
    * per-day : 'Dush 14:00, Chor 15:30, Jum 17:00'
    Days listed in ``dars_kunlari`` that have no entry in a per-day schedule are
    shown without a time; legacy free-text values pass through unchanged.
    """
    from app.locales import WEEKDAYS_SHORT

    names = WEEKDAYS_SHORT.get(lang) or WEEKDAYS_SHORT["latn"]
    uniform_sessions, per_day_sessions = parse_lesson_sessions(dars_vaqti)
    uniform = " / ".join(uniform_sessions) if uniform_sessions else None
    per_day = {idx: " / ".join(v) for idx, v in per_day_sessions.items()}
    if is_agreed_lesson_time(dars_vaqti):
        uniform = AGREED_LESSON_TIME_CYRL if lang == "cyrl" else AGREED_LESSON_TIME
    day_idx: list[int] = []
    for tok in _re.split(r"[,;/\s]+", str(dars_kunlari or "").strip()):
        idx = _LESSON_DAY_TOKENS.get(tok.lower().strip(".-"))
        if idx is not None and idx not in day_idx:
            day_idx.append(idx)
    day_idx.sort()
    if per_day:
        ordered = day_idx or sorted(per_day)
        return ", ".join(
            f"{names[i]} {per_day[i]}" if i in per_day else names[i] for i in ordered
        )
    days_txt = ", ".join(names[i] for i in day_idx) or str(dars_kunlari or "").strip()
    time_txt = uniform or str(dars_vaqti or "").strip()
    if days_txt and time_txt:
        return f"{days_txt} — {time_txt}"
    return days_txt or time_txt or "—"


# ----------------------------------------------------------------------
# Inline calendar helpers (cycle start date picker)
# ----------------------------------------------------------------------


def shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """(year, month) moved by `delta` months (negative = back), 1 <= month <= 12."""
    index = year * 12 + (month - 1) + int(delta)
    return index // 12, index % 12 + 1


def month_weeks(year: int, month: int) -> list[list[int]]:
    """Monday-first weeks of the month; 0 marks an empty cell."""
    import calendar as _calendar

    return [list(week) for week in _calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)]


def parse_calendar_month(raw: str) -> Optional[tuple[int, int]]:
    """'2026-11' -> (2026, 11); None when malformed / out of range."""
    try:
        year_s, month_s = str(raw or "").strip().split("-", 1)
        year, month = int(year_s), int(month_s)
    except ValueError:
        return None
    if not (2000 <= year <= 2100 and 1 <= month <= 12):
        return None
    return year, month


# ----------------------------------------------------------------------
# Dual-role (Student + Parent) notification context headers
# ----------------------------------------------------------------------

_DUAL_ROLE_HEADERS: dict[str, dict[str, str]] = {
    "latn": {
        "student": "🎓 <b>Shaxsiy darsingiz bo'yicha:</b>\n\n",
        "parent": "👨‍👩‍👧 <b>Farzandingiz {talaba_ismi} bo'yicha:</b>\n\n",
        "parent_multi": "👨‍👩‍👧 <b>Farzandlaringiz bo'yicha:</b>\n\n",
    },
    "cyrl": {
        "student": "🎓 <b>Шахсий дарсингиз бўйича:</b>\n\n",
        "parent": "👨‍👩‍👧 <b>Фарзандингиз {talaba_ismi} бўйича:</b>\n\n",
        "parent_multi": "👨‍👩‍👧 <b>Фарзандларингиз бўйича:</b>\n\n",
    },
}


def dual_role_header(
    role: str,
    lang: str = "latn",
    student_names: Union[str, Iterable[str], None] = None,
) -> str:
    """
    Human-friendly context header for users who are BOTH a student and a parent.

    * role == "student": "🎓 Shaxsiy darsingiz bo'yicha:" (their own studies)
    * role == "parent":  "👨‍👩‍👧 Farzandingiz {talaba_ismi} bo'yicha:" (one child), or the
      plural "Farzandlaringiz bo'yicha:" when the message covers several children
      (or the child's name is unknown).

    Always ends with a blank line; the caller prepends it to the message body.
    """
    table = _DUAL_ROLE_HEADERS.get(lang) or _DUAL_ROLE_HEADERS["latn"]
    if role != "parent":
        return table["student"]
    if student_names is None:
        names: list[str] = []
    elif isinstance(student_names, str):
        names = [student_names]
    else:
        names = list(student_names)
    unique: list[str] = []
    seen: set[str] = set()
    for raw in names:
        clean = " ".join(str(raw or "").split())
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            unique.append(clean)
    if len(unique) == 1:
        return table["parent"].format(talaba_ismi=html.escape(unique[0]))
    return table["parent_multi"]


# ----------------------------------------------------------------------
# Annual group archive report (standalone Uzbek HTML document)
# ----------------------------------------------------------------------


def _fmt_money(amount: int) -> str:
    return f"{int(amount or 0):,}".replace(",", " ")


def legacy_group_join_slug(group_name: str) -> str:
    """Original '?start=join_<slug>' slug (kept so already shared links still work)."""
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(group_name or "").strip())
    return cleaned.strip("_")[:55] or "group"


def make_group_join_slug(group_name: str) -> str:
    """
    Deterministic deep-link slug for a group of ANY name.
    Plain ASCII names (letters, digits, '_' '-', up to 55 chars) keep exactly the
    legacy slug; any other name (spaces, ':' '/', Cyrillic, emojis, long...)
    gets a short stable hash suffix so different groups never share one link.
    The result always fits Telegram's 64-char /start payload with 'join_'.
    """
    import hashlib

    raw = str(group_name or "").strip()
    legacy = legacy_group_join_slug(raw)
    if legacy == raw:
        return legacy
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    base = legacy if legacy != "group" else "g"
    return f"{base[:46].rstrip('_-') or 'g'}-{digest}"


def annual_report_filename(group_name: str, year: int) -> str:
    """'Mishkat_Yillik_Hisobot_{group_name}_{year}.html' with a filesystem-safe group."""
    import re

    safe = re.sub(r"[^\w\-]+", "_", str(group_name or "").strip(), flags=re.UNICODE)
    safe = safe.strip("_")[:80].strip("_") or "Guruh"
    return f"Mishkat_Yillik_Hisobot_{safe}_{year}.html"


def build_annual_report_html(report: dict) -> str:
    """
    Renders a clean, mobile-friendly, fully self-contained HTML document.

    Expected ``report`` keys:
      group, year, teacher, fee (int, 0 = unknown),
      cycles: [{title, dates: [str], students: [{id, name, present, absent,
                paid (bool), marks: [str]}]}]
    """
    esc = html.escape
    group = str(report.get("group") or "")
    year = int(report.get("year") or 0)
    teacher = str(report.get("teacher") or "—")
    fee = int(report.get("fee") or 0)
    cycles: list[dict] = list(report.get("cycles") or [])

    totals: dict[str, dict] = {}
    order: list[str] = []
    total_paid_cnt = 0
    total_unpaid_cnt = 0
    completed = 0
    for cyc in cycles:
        dates = list(cyc.get("dates") or [])
        held_cols = set()
        for stu in cyc.get("students") or []:
            for idx, mk in enumerate(stu.get("marks") or []):
                if mk in ("✅", "❌"):
                    held_cols.add(idx)
        if dates and len(held_cols) >= len(dates):
            completed += 1
        for stu in cyc.get("students") or []:
            key = str(stu.get("id") or stu.get("name") or "")
            if key not in totals:
                totals[key] = {
                    "name": str(stu.get("name") or ""),
                    "present": 0,
                    "absent": 0,
                    "paid": 0,
                    "unpaid": 0,
                }
                order.append(key)
            rec = totals[key]
            rec["present"] += int(stu.get("present") or 0)
            rec["absent"] += int(stu.get("absent") or 0)
            if stu.get("paid"):
                rec["paid"] += 1
                total_paid_cnt += 1
            else:
                rec["unpaid"] += 1
                total_unpaid_cnt += 1

    debtors = sum(1 for k in order if totals[k]["unpaid"] > 0)
    revenue_txt = f"{_fmt_money(total_paid_cnt * fee)} so‘m" if fee else "—"
    debt_txt = f"{_fmt_money(total_unpaid_cnt * fee)} so‘m" if fee else "—"
    generated = now_tashkent().strftime("%d.%m.%Y %H:%M")

    def _badge(paid: bool) -> str:
        return (
            '<span class="b ok">To‘langan</span>'
            if paid
            else '<span class="b no">To‘lanmagan</span>'
        )

    cycle_html: list[str] = []
    for cyc in cycles:
        dates = list(cyc.get("dates") or [])
        head = "".join(f"<th>{esc(str(d))}</th>" for d in dates)
        rows: list[str] = []
        for n, stu in enumerate(cyc.get("students") or [], start=1):
            marks = list(stu.get("marks") or [])
            marks += [""] * (len(dates) - len(marks))
            cells = "".join(f"<td class='c'>{esc(str(m or '·'))}</td>" for m in marks[: len(dates)])
            rows.append(
                f"<tr><td class='c'>{n}</td><td>{esc(str(stu.get('name') or ''))}</td>{cells}"
                f"<td class='c'>{int(stu.get('present') or 0)}</td>"
                f"<td class='c'>{int(stu.get('absent') or 0)}</td>"
                f"<td class='c'>{_badge(bool(stu.get('paid')))}</td></tr>"
            )
        body = "".join(rows) or f"<tr><td colspan='{len(dates) + 5}' class='c'>Talabalar yo‘q</td></tr>"
        cycle_html.append(
            f"<section><h2>{esc(str(cyc.get('title') or ''))}</h2>"
            "<div class='w'><table><thead><tr><th>№</th><th>F.I.O.</th>"
            f"{head}<th>✅</th><th>❌</th><th>To‘lov</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div></section>"
        )

    summary_rows: list[str] = []
    for n, key in enumerate(order, start=1):
        rec = totals[key]
        paid_sum = f"{_fmt_money(rec['paid'] * fee)}" if fee else "—"
        debt_sum = f"{_fmt_money(rec['unpaid'] * fee)}" if fee else "—"
        summary_rows.append(
            f"<tr><td class='c'>{n}</td><td>{esc(rec['name'])}</td>"
            f"<td class='c'>{rec['present']}</td><td class='c'>{rec['absent']}</td>"
            f"<td class='c'>{rec['paid']}</td><td class='c'>{rec['unpaid']}</td>"
            f"<td class='r'>{paid_sum}</td><td class='r'>{debt_sum}</td></tr>"
        )
    summary_body = "".join(summary_rows) or "<tr><td colspan='8' class='c'>Ma’lumot yo‘q</td></tr>"

    return f"""<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yillik hisobot — {esc(group)} ({year})</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;padding:16px;background:#f4f6f8;color:#1f2933;font:15px/1.5 -apple-system,Segoe UI,Roboto,Arial,sans-serif}}
.page{{max-width:980px;margin:0 auto}}
header{{background:#1f4e79;color:#fff;border-radius:12px;padding:20px;margin-bottom:16px}}
header h1{{margin:0 0 4px;font-size:21px}}
header p{{margin:0;opacity:.85;font-size:13px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}}
.card{{background:#fff;border-radius:10px;padding:12px 14px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.card small{{display:block;color:#617080;font-size:12px}}
.card strong{{font-size:17px}}
section{{background:#fff;border-radius:12px;padding:14px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
h2{{margin:0 0 10px;font-size:17px;color:#1f4e79}}
.w{{overflow-x:auto;-webkit-overflow-scrolling:touch}}
table{{border-collapse:collapse;width:100%;font-size:13px}}
th,td{{border:1px solid #d9e0e6;padding:6px 8px;white-space:nowrap}}
th{{background:#eaf1f8}}
.c{{text-align:center}}.r{{text-align:right}}
.b{{padding:2px 8px;border-radius:10px;font-size:12px}}
.ok{{background:#d9ead3;color:#1e5a1e}}.no{{background:#f4cccc;color:#8a1c1c}}
footer{{text-align:center;color:#617080;font-size:12px;margin:18px 0}}
</style>
</head>
<body>
<div class="page">
<header>
<h1>📚 {esc(group)} — {year}-yil yillik hisoboti</h1>
<p>Mishkat Nodavlat Ta'lim Muassasasi · Tuzilgan sana: {generated}</p>
</header>
<div class="grid">
<div class="card"><small>Guruh</small><strong>{esc(group)}</strong></div>
<div class="card"><small>Ustoz</small><strong>{esc(teacher)}</strong></div>
<div class="card"><small>Jami sikllar / yakunlangan</small><strong>{len(cycles)} / {completed}</strong></div>
<div class="card"><small>Yig‘ilgan to‘lovlar</small><strong>{revenue_txt}</strong></div>
<div class="card"><small>Qarzdor talabalar</small><strong>{debtors} nafar</strong></div>
<div class="card"><small>To‘lanmagan summa</small><strong>{debt_txt}</strong></div>
</div>
{''.join(cycle_html)}
<section>
<h2>Yillik talabalar xulosasi</h2>
<div class="w"><table><thead><tr><th>№</th><th>F.I.O.</th><th>✅ Qatnashgan</th><th>❌ Qatnashmagan</th>
<th>To‘langan sikllar</th><th>To‘lanmagan sikllar</th><th>To‘langan summa</th><th>Qarz summa</th></tr></thead>
<tbody>{summary_body}</tbody></table></div>
</section>
<footer>Hurmat bilan,<br>Mishkat Nodavlat Ta'lim Muassasasi!</footer>
</div>
</body>
</html>
"""


async def send_annual_archive_document(
    bot: object, filename: str, content: bytes, caption: str
) -> bool:
    """
    Sends the archive .html to BACKUP_CHAT_ID (+ BACKUP_THREAD_ID when set),
    falling back to ADMIN_IDS[0]. Returns True on success; never raises.
    """
    import logging

    from aiogram.types import BufferedInputFile

    from app import config

    chat_id = getattr(config, "BACKUP_CHAT_ID", None)
    thread_id = getattr(config, "BACKUP_THREAD_ID", None) if chat_id else None
    if not chat_id:
        admins = list(getattr(config, "ADMIN_IDS", []) or [])
        chat_id = admins[0] if admins else None
        thread_id = None
    if not chat_id:
        logging.getLogger(__name__).warning(
            "Annual archive %s not sent: no BACKUP_CHAT_ID / ADMIN_IDS configured",
            filename,
        )
        return False
    try:
        kwargs: dict = {}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        await bot.send_document(  # type: ignore[attr-defined]
            chat_id=chat_id,
            document=BufferedInputFile(content, filename=filename),
            caption=caption,
            parse_mode="HTML",
            **kwargs,
        )
        return True
    except Exception:
        logging.getLogger(__name__).exception(
            "Failed sending annual archive %s to %s", filename, chat_id
        )
        return False
