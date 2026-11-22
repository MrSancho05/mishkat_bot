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
