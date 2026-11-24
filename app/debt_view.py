"""
Unified debt view: combines pre-system (legacy) debts recorded by Admin with
current unpaid {Group}_{Year} cycles (including their exact lesson dates), and
renders a polite short summary + an expandable detailed view
(📄 Batafsil / 📋 Qisqacha) for students, parents and admins.
"""

import asyncio
import html
import logging
import os
import re
import uuid
from datetime import date
from typing import Any, Optional

from app.database import (
    get_cycle_overrides_for_students,
    get_unpaid_legacy_debts_map,
    save_notification_details,
)
from app.keyboards import build_expandable_notif_kb
from app.locales import MONTHS_UZ, WEEKDAYS_FULL, WEEKDAYS_SHORT, t

logger = logging.getLogger(__name__)

CENTER_SIGNATURE: dict[str, str] = {
    "latn": "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!",
    "cyrl": "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!",
}

_TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "currency": "so‘m",
        "month_unit": "oy",
        "lesson_unit": "ta dars",
        "greet_student": "Assalomu alaykum, hurmatli <b>{name}</b>!",
        "greet_parent": "Assalomu alaykum, hurmatli ota-ona!",
        "intro_student": (
            "Sizga hurmat bilan ma'lum qilamizki, o‘qishingiz bo‘yicha "
            "to‘lanmagan o‘quv oylari mavjud:"
        ),
        "intro_parent_one": (
            "Sizga hurmat bilan ma'lum qilamizki, farzandingiz bo‘yicha "
            "to‘lanmagan o‘quv oylari mavjud:"
        ),
        "intro_parent_many": (
            "Sizga hurmat bilan ma'lum qilamizki, farzandlaringiz bo‘yicha "
            "to‘lanmagan o‘quv oylari mavjud:"
        ),
        "child_short_line": "👤 <b>{name}</b> ({group}) — <b>{months} oy</b>, <b>{total} so‘m</b>",
        "total_sum_line": "💰 Jami qarzdorlik: <b>{total} so‘m</b>",
        "total_months_line": "🗓 Jami to‘lanmagan oylar: <b>{months} oy</b>",
        "polite_request": (
            "To‘lovni imkoniyatingiz bo‘yicha o‘z vaqtida amalga oshirishingizni "
            "iltimos qilamiz. Tushunganingiz uchun rahmat!"
        ),
        "detail_hint": "ℹ️ Har bir oy va dars sanalarini ko‘rish uchun «📄 Batafsil» tugmasini bosing.",
        "detail_header": "📄 <b>Qarzdorlik tafsilotlari</b>",
        "child_detail_header": "👤 <b>{name}</b> — 📚 {group}",
        "fee_line": "💵 Oylik to‘lov: <b>{fee} so‘m</b>",
        "legacy_title": "📜 <b>Avvalgi (tizimdan oldingi) qarzlar:</b>",
        "legacy_item": "   • <b>{label}</b> — {months} oy, <b>{amount} so‘m</b>",
        "current_title": "🗓 <b>Joriy to‘lanmagan sikllar:</b>",
        "current_item": "   • <b>{title}</b> — {count} ta dars, <b>{fee} so‘m</b>",
        "dates_line": "      📅 {dates}",
        "extra_item": "   • <b>{title}</b> — <b>{fee} so‘m</b>",
        "child_total": "   💰 Jami: <b>{months} oy</b> — <b>{total} so‘m</b>",
        "no_debt": "✅ Hozircha qarzdorlik mavjud emas. Rahmat!",
        "card_block": "💳 To‘lov uchun karta: <code>{card_number}</code>\n👤 Karta egasi: <b>{card_owner}</b>",
        "header_student": "🔔 <b>To‘lov bo‘yicha eslatma</b>",
        "header_parent": "🔔 <b>To‘lov bo‘yicha eslatma</b>",
        "header_view": "💳 <b>To‘lovlar holati</b>",
        "admin_dates_line": "  📅 To‘lanmagan darslar: {dates}",
        "admin_legacy_line": "  📜 Avvalgi qarz: {items}",
        "prorated_suffix": " (qolgan {remaining} ta dars)",
    },
    "cyrl": {
        "currency": "сўм",
        "month_unit": "ой",
        "lesson_unit": "та дарс",
        "greet_student": "Ассалому алайкум, ҳурматли <b>{name}</b>!",
        "greet_parent": "Ассалому алайкум, ҳурматли ота-она!",
        "intro_student": (
            "Сизга ҳурмат билан маълум қиламизки, ўқишингиз бўйича "
            "тўланмаган ўқув ойлари мавжуд:"
        ),
        "intro_parent_one": (
            "Сизга ҳурмат билан маълум қиламизки, фарзандингиз бўйича "
            "тўланмаган ўқув ойлари мавжуд:"
        ),
        "intro_parent_many": (
            "Сизга ҳурмат билан маълум қиламизки, фарзандларингиз бўйича "
            "тўланмаган ўқув ойлари мавжуд:"
        ),
        "child_short_line": "👤 <b>{name}</b> ({group}) — <b>{months} ой</b>, <b>{total} сўм</b>",
        "total_sum_line": "💰 Жами қарздорлик: <b>{total} сўм</b>",
        "total_months_line": "🗓 Жами тўланмаган ойлар: <b>{months} ой</b>",
        "polite_request": (
            "Тўловни имкониятингиз бўйича ўз вақтида амалга оширишингизни "
            "илтимос қиламиз. Тушунганингиз учун раҳмат!"
        ),
        "detail_hint": "ℹ️ Ҳар бир ой ва дарс саналарини кўриш учун «📄 Батафсил» тугмасини босинг.",
        "detail_header": "📄 <b>Қарздорлик тафсилотлари</b>",
        "child_detail_header": "👤 <b>{name}</b> — 📚 {group}",
        "fee_line": "💵 Ойлик тўлов: <b>{fee} сўм</b>",
        "legacy_title": "📜 <b>Аввалги (тизимдан олдинги) қарзлар:</b>",
        "legacy_item": "   • <b>{label}</b> — {months} ой, <b>{amount} сўм</b>",
        "current_title": "🗓 <b>Жорий тўланмаган цикллар:</b>",
        "current_item": "   • <b>{title}</b> — {count} та дарс, <b>{fee} сўм</b>",
        "dates_line": "      📅 {dates}",
        "extra_item": "   • <b>{title}</b> — <b>{fee} сўм</b>",
        "child_total": "   💰 Жами: <b>{months} ой</b> — <b>{total} сўм</b>",
        "no_debt": "✅ Ҳозирча қарздорлик мавжуд эмас. Раҳмат!",
        "card_block": "💳 Тўлов учун карта: <code>{card_number}</code>\n👤 Карта эгаси: <b>{card_owner}</b>",
        "header_student": "🔔 <b>Тўлов бўйича эслатма</b>",
        "header_parent": "🔔 <b>Тўлов бўйича эслатма</b>",
        "header_view": "💳 <b>Тўловлар ҳолати</b>",
        "admin_dates_line": "  📅 Тўланмаган дарслар: {dates}",
        "admin_legacy_line": "  📜 Аввалги қарз: {items}",
        "prorated_suffix": " (қолган {remaining} та дарс)",
    },
}


def _dt(key: str, lang: str, **kwargs: Any) -> str:
    safe_lang = lang if lang in _TEXTS else "latn"
    template = _TEXTS[safe_lang].get(key) or _TEXTS["latn"].get(key, key)
    return template.format(**kwargs) if kwargs else template


def signature(lang: str) -> str:
    return CENTER_SIGNATURE.get(lang, CENTER_SIGNATURE["latn"])


def teacher_signature(teacher_name: str, lang: str) -> str:
    return t("topic_teacher_footer", lang, teacher_name=html.escape(teacher_name.strip()))


def format_uzs(amount: int) -> str:
    return f"{int(amount or 0):,}".replace(",", " ")


def count_debt_months(debt_raw: Any) -> int:
    cleaned = str(debt_raw or "").strip()
    if not cleaned or cleaned == "0":
        return 0
    if cleaned.isdigit():
        return int(cleaned)
    return len([x for x in cleaned.split(";") if x.strip() and x.strip() != "0"])


def debt_titles_from_raw(debt_raw: Any) -> list[str]:
    cleaned = str(debt_raw or "").strip()
    if not cleaned or cleaned.isdigit():
        return []
    return [
        x.strip()
        for x in cleaned.split(";")
        if x.strip() and x.strip() != "0" and not x.strip().isdigit()
    ]


def format_lesson_date(iso_or_ddmm: str, lang: str, full_weekday: bool = True) -> str:
    """'2026-11-03' -> '03.11.2026 (Seshanba)'."""
    raw = str(iso_or_ddmm or "").strip()
    try:
        d_val = date.fromisoformat(raw)
    except ValueError:
        return html.escape(raw)
    safe_lang = lang if lang in WEEKDAYS_FULL else "latn"
    weekday_map = WEEKDAYS_FULL if full_weekday else WEEKDAYS_SHORT
    return f"{d_val.strftime('%d.%m.%Y')} ({weekday_map[safe_lang][d_val.weekday()]})"


def format_legacy_dates(raw: str, lang: str) -> str:
    """Adds full weekday names to 'dd.mm.yyyy' tokens of a legacy dates string."""
    text = str(raw or "").strip()
    if not text:
        return "—"

    def _repl(match: "re.Match[str]") -> str:
        d_val, m_val, y_val = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if y_val < 100:
            y_val += 2000
        try:
            return format_lesson_date(date(y_val, m_val, d_val).isoformat(), lang)
        except ValueError:
            return match.group(0)

    escaped = html.escape(text)
    return re.sub(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b", _repl, escaped)


def format_cycle_title(title: str, lang: str) -> str:
    """'NOYABR 2026 (Sikl #3)' -> 'Noyabr 2026 (3-sikl)' / Cyrillic variant."""
    clean = str(title or "").strip()
    match = re.match(r"^([A-ZʻʼO'‘]+)\s+(\d{4})\s*\(Sikl\s*#(\d+)\)$", clean, re.IGNORECASE)
    if not match:
        return html.escape(clean)
    month_word = match.group(1).upper()
    year_val = match.group(2)
    num = match.group(3)
    month_idx: Optional[int] = None
    for idx, name in MONTHS_UZ["latn"].items():
        if name.upper() == month_word:
            month_idx = idx
            break
    safe_lang = lang if lang in MONTHS_UZ else "latn"
    month_name = MONTHS_UZ[safe_lang].get(month_idx, month_word.title()) if month_idx else month_word.title()
    cycle_word = "цикл" if safe_lang == "cyrl" else "sikl"
    return html.escape(f"{month_name} {year_val} ({num}-{cycle_word})")


def build_child_debt(
    student: dict[str, Any],
    fee: int,
    unpaid_cycles: list[dict[str, Any]],
    legacy_rows: list[dict[str, Any]],
    overrides: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    debt_raw = str(student.get("Qarzdor_Oylar") or "").strip()
    current_months = count_debt_months(debt_raw)
    if current_months == 0 and unpaid_cycles and not debt_raw:
        current_months = len(unpaid_cycles)
    legacy_items = [
        {
            "id": row.get("id"),
            "label": str(row.get("cycle_label") or "").strip() or "—",
            "dates": str(row.get("lesson_dates") or "").strip(),
            "months": max(1, int(row.get("months") or 1)),
            "amount": max(0, int(row.get("amount") or 0)),
            "note": str(row.get("note") or "").strip(),
        }
        for row in legacy_rows
    ]
    legacy_months = sum(item["months"] for item in legacy_items)
    legacy_sum = sum(item["amount"] for item in legacy_items)

    cycle_titles = {str(c.get("title") or "").strip() for c in unpaid_cycles}
    extra_titles = [
        title for title in debt_titles_from_raw(debt_raw) if title not in cycle_titles
    ]
    shown_cycles = list(unpaid_cycles)[-max(current_months, 0):] if current_months else []
    # Keep cycles that exactly match recorded debt titles even if older
    if debt_titles_from_raw(debt_raw):
        titled = [c for c in unpaid_cycles if c.get("title") in set(debt_titles_from_raw(debt_raw))]
        if titled:
            shown_cycles = titled

    # Prorated cycles ("🆕 Bugundan qo‘shildi"): only the exact cycle they were
    # created for is billed at the custom amount; every other cycle is full fee.
    student_group = str(student.get("Guruh") or "").strip().lower()
    debt_title_set = set(debt_titles_from_raw(debt_raw))
    active_overrides: dict[str, dict[str, Any]] = {}
    for item in overrides or []:
        title = str(item.get("cycle_title") or "").strip()
        if (
            title in debt_title_set
            and str(item.get("group_name") or "").strip().lower() == student_group
        ):
            active_overrides[title] = {
                "remaining_lessons": int(item.get("remaining_lessons") or 0),
                "custom_amount": int(item.get("custom_amount") or 0),
            }
    prorated_count = min(len(active_overrides), max(current_months, 0))
    current_sum = (max(current_months, 0) - prorated_count) * int(fee or 0) + sum(
        v["custom_amount"] for v in active_overrides.values()
    )
    return {
        "student_id": str(student.get("Talaba_ID") or "").strip(),
        "name": str(student.get("F.I.O.") or student.get("Talaba_ID") or "").strip(),
        "group": str(student.get("Guruh") or "").strip(),
        "fee": int(fee or 0),
        "debt_raw": debt_raw,
        "current_months": current_months,
        "current_sum": current_sum,
        "overrides": active_overrides,
        "cycles": shown_cycles,
        "extra_titles": extra_titles[: max(0, current_months - len(shown_cycles))],
        "legacy": legacy_items,
        "legacy_months": legacy_months,
        "legacy_sum": legacy_sum,
        "total_months": current_months + legacy_months,
        "total_sum": current_sum + legacy_sum,
        "student": student,
    }


def _dates_text(cycle: dict[str, Any], lang: str) -> str:
    iso_dates = list(cycle.get("dates") or [])
    if iso_dates:
        return ", ".join(format_lesson_date(d, lang) for d in iso_dates)
    return ", ".join(html.escape(x) for x in cycle.get("date_strs") or []) or "—"


def format_child_detail(child: dict[str, Any], lang: str) -> str:
    lines = [
        _dt(
            "child_detail_header",
            lang,
            name=html.escape(child["name"]),
            group=html.escape(child["group"] or "—"),
        ),
        _dt("fee_line", lang, fee=format_uzs(child["fee"])),
    ]
    if child["legacy"]:
        lines.append(_dt("legacy_title", lang))
        for item in child["legacy"]:
            lines.append(
                _dt(
                    "legacy_item",
                    lang,
                    label=html.escape(item["label"]),
                    months=item["months"],
                    amount=format_uzs(item["amount"]),
                )
            )
            if item["dates"]:
                lines.append(
                    _dt("dates_line", lang, dates=format_legacy_dates(item["dates"], lang))
                )
    if child["cycles"] or child["extra_titles"]:
        lines.append(_dt("current_title", lang))
        for cycle in child["cycles"]:
            ov = (child.get("overrides") or {}).get(str(cycle.get("title") or "").strip())
            if ov:
                lines.append(
                    _dt(
                        "current_item",
                        lang,
                        title=format_cycle_title(cycle.get("title", ""), lang)
                        + _dt("prorated_suffix", lang, remaining=ov["remaining_lessons"]),
                        count=ov["remaining_lessons"],
                        fee=format_uzs(ov["custom_amount"]),
                    )
                )
            else:
                lines.append(
                    _dt(
                        "current_item",
                        lang,
                        title=format_cycle_title(cycle.get("title", ""), lang),
                        count=int(cycle.get("lesson_count") or len(cycle.get("dates") or [])),
                        fee=format_uzs(child["fee"]),
                    )
                )
            lines.append(_dt("dates_line", lang, dates=_dates_text(cycle, lang)))
        for title in child["extra_titles"]:
            ov = (child.get("overrides") or {}).get(str(title).strip())
            lines.append(
                _dt(
                    "extra_item",
                    lang,
                    title=format_cycle_title(title, lang)
                    + (
                        _dt("prorated_suffix", lang, remaining=ov["remaining_lessons"])
                        if ov
                        else ""
                    ),
                    fee=format_uzs(ov["custom_amount"] if ov else child["fee"]),
                )
            )
    lines.append(
        _dt(
            "child_total",
            lang,
            months=child["total_months"],
            total=format_uzs(child["total_sum"]),
        )
    )
    return "\n".join(lines)


def format_admin_extra_lines(child: dict[str, Any], lang: str, max_dates: int = 14) -> str:
    """Compact unpaid-dates + legacy lines for the admin debtor list."""
    out: list[str] = []
    iso_dates: list[str] = []
    for cycle in child["cycles"]:
        iso_dates.extend(cycle.get("dates") or [])
    if iso_dates:
        shown = [format_lesson_date(d, lang, full_weekday=True) for d in iso_dates[:max_dates]]
        more = len(iso_dates) - len(shown)
        dates_str = ", ".join(shown) + (f" … (+{more})" if more > 0 else "")
        out.append(_dt("admin_dates_line", lang, dates=dates_str))
    if child["legacy"]:
        items = "; ".join(
            f"{html.escape(it['label'])} ({it['months']} "
            f"{_dt('month_unit', lang)}, {format_uzs(it['amount'])} {_dt('currency', lang)})"
            for it in child["legacy"]
        )
        out.append(_dt("admin_legacy_line", lang, items=items))
    return "\n".join(out)


def build_debt_notice(
    children: list[dict[str, Any]],
    lang: str,
    audience: str,
    card_number: str = "",
    card_owner: str = "",
    recipient_name: str = "",
    header_key: Optional[str] = None,
    prefix: str = "",
    include_no_debt: bool = False,
    teacher_name: str = "",
) -> tuple[str, str]:
    """
    Returns (short_text, detailed_text) for a student / parent recipient.
    audience: 'student' | 'parent'.
    teacher_name: when the notice is sent on behalf of a teacher, it is signed
    "Hurmat bilan, guruh ustozi {teacher_name}"; otherwise with the official
    Mishkat signature.
    """
    debt_children = [c for c in children if c["total_sum"] > 0 or c["total_months"] > 0]
    sig = (
        f"<i>{teacher_signature(teacher_name, lang)}</i>"
        if teacher_name.strip()
        else f"<i>{signature(lang)}</i>"
    )
    card = _dt(
        "card_block",
        lang,
        card_number=html.escape(card_number or "—"),
        card_owner=html.escape(card_owner or "—"),
    )
    header = _dt(header_key or f"header_{'parent' if audience == 'parent' else 'student'}", lang)

    if not debt_children:
        text = f"{prefix}{header}\n\n{_dt('no_debt', lang)}\n\n{sig}"
        return text, text

    total_sum = sum(c["total_sum"] for c in debt_children)
    total_months = sum(c["total_months"] for c in debt_children)

    if audience == "parent":
        greet = _dt("greet_parent", lang)
        intro = _dt(
            "intro_parent_many" if len(debt_children) > 1 else "intro_parent_one", lang
        )
    else:
        greet = _dt(
            "greet_student",
            lang,
            name=html.escape(recipient_name or debt_children[0]["name"]),
        )
        intro = _dt("intro_student", lang)

    child_lines = "\n".join(
        _dt(
            "child_short_line",
            lang,
            name=html.escape(c["name"]),
            group=html.escape(c["group"] or "—"),
            months=c["total_months"],
            total=format_uzs(c["total_sum"]),
        )
        for c in debt_children
    )
    totals = (
        f"{_dt('total_sum_line', lang, total=format_uzs(total_sum))}\n"
        f"{_dt('total_months_line', lang, months=total_months)}"
    )
    short_text = (
        f"{prefix}{header}\n\n{greet}\n{intro}\n\n{child_lines}\n\n{totals}\n\n"
        f"{_dt('polite_request', lang)}\n\n{card}\n\n{_dt('detail_hint', lang)}\n\n{sig}"
    )

    detail_blocks = "\n\n".join(format_child_detail(c, lang) for c in debt_children)
    detailed_text = (
        f"{prefix}{_dt('detail_header', lang)}\n\n{detail_blocks}\n\n━━━━━━━━━━━━━━\n"
        f"{totals}\n\n{_dt('polite_request', lang)}\n\n{card}\n\n{sig}"
    )
    return safe_html_truncate(short_text), safe_html_truncate(detailed_text)


def safe_html_truncate(text: str, limit: int = 4000) -> str:
    if len(text) <= limit:
        return text
    lines: list[str] = []
    cur = 0
    for line in text.split("\n"):
        add = len(line) + (1 if lines else 0)
        if cur + add > limit - 6:
            break
        lines.append(line)
        cur += add
    return "\n".join(lines) + "\n…"


async def compute_children_debts(
    sheets: Any,
    students: list[dict[str, Any]],
    group_fees: dict[str, int],
    default_fee: int,
    legacy_map: Optional[dict[str, list[dict[str, Any]]]] = None,
    unpaid_map: Optional[dict[str, list[dict[str, Any]]]] = None,
) -> list[dict[str, Any]]:
    """Builds child-debt dicts (current cycles + legacy) for a list of students."""
    if not students:
        return []
    sids = [str(s.get("Talaba_ID") or "").strip() for s in students]
    if legacy_map is None:
        try:
            legacy_map = await get_unpaid_legacy_debts_map(sids)
        except Exception:
            logger.exception("Failed loading legacy debts")
            legacy_map = {}
    if unpaid_map is None:
        try:
            unpaid_map = await asyncio.to_thread(
                sheets.get_unpaid_cycles_for_students, students
            )
        except Exception:
            logger.exception("Failed loading unpaid cycles")
            unpaid_map = {}
    overrides_map = await get_cycle_overrides_for_students(sids)
    result: list[dict[str, Any]] = []
    for stu in students:
        sid = str(stu.get("Talaba_ID") or "").strip()
        grp = str(stu.get("Guruh") or "").strip()
        sobiq = str(stu.get("Sobiq_Guruh") or "").strip()
        fee = group_fees.get(grp.lower()) or group_fees.get(sobiq.lower()) or default_fee
        result.append(
            build_child_debt(
                stu,
                fee,
                unpaid_map.get(sid, []),
                legacy_map.get(sid, []),
                overrides_map.get(sid, []),
            )
        )
    return result


async def send_expandable_notice(
    bot: Any,
    chat_id: int,
    short_text: str,
    detailed_text: str,
    lang: str,
) -> bool:
    """Sends the short notice with a 📄 Batafsil / 📋 Qisqacha toggle. Logs failures."""
    notif_id = f"dbt{uuid.uuid4().hex[:12]}_{lang if lang in ('latn', 'cyrl') else 'latn'}"
    reply_markup = None
    if detailed_text and detailed_text != short_text:
        try:
            await save_notification_details(notif_id, short_text, detailed_text)
            reply_markup = build_expandable_notif_kb(notif_id, expanded=False, lang=lang)
        except Exception:
            logger.exception("Failed saving expandable debt notice %s", notif_id)
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=short_text,
            reply_markup=reply_markup,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return True
    except Exception as exc:
        logger.warning("Debt notice delivery failed for chat_id=%s: %s", chat_id, exc)
        return False


def localized_no_debt(lang: str) -> str:
    return t("no_debts_msg", lang)


def _group_fee_from_row(group: dict[str, Any], default_fee: int) -> int:
    raw = re.sub(r"[^\d]", "", str(group.get("Oylik_Tolov_Summa", "") or ""))
    return int(raw) if raw and int(raw) > 0 else default_fee


def default_monthly_fee() -> int:
    from app import config

    for candidate in (getattr(config, "DEFAULT_MONTHLY_FEE", None), os.getenv("DEFAULT_MONTHLY_FEE", "")):
        cleaned = re.sub(r"[^\d]", "", str(candidate or "").strip())
        if cleaned:
            return int(cleaned)
    return 500000


async def get_group_monthly_fee(sheets: Any, group_name: str) -> int:
    """Monthly fee (Oylik_Tolov_Summa, else the default fee) of one group."""
    group = await sheets.a_get_group(group_name) or {}
    return _group_fee_from_row(group, default_monthly_fee())


async def load_group_fees(sheets: Any) -> tuple[dict[str, int], int]:
    """Returns ({group_name_lower: monthly_fee}, default_fee)."""
    default_fee = default_monthly_fee()
    all_groups = await asyncio.to_thread(sheets.get_all_groups)
    fees = {
        str(g.get("Guruh_Nomi", "")).strip().lower(): _group_fee_from_row(g, default_fee)
        for g in all_groups
    }
    return fees, default_fee


async def compute_debt_details_map(
    sheets: Any, students: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """{Talaba_ID: child-debt dict} (incl. prorated overrides); {} on failure."""
    if not students:
        return {}
    try:
        group_fees, default_fee = await load_group_fees(sheets)
        children = await compute_children_debts(sheets, students, group_fees, default_fee)
        return {c["student_id"]: c for c in children}
    except Exception:
        logger.exception("Failed computing debt details map")
        return {}


async def compute_total_debt_map(
    sheets: Any, students: list[dict[str, Any]]
) -> dict[str, int]:
    """
    {Talaba_ID: total_debt_sum} (current unpaid cycles + legacy debts) for the
    given students. Never raises: on failure returns an empty map (= no debt).
    """
    if not students:
        return {}
    try:
        group_fees, default_fee = await load_group_fees(sheets)
        children = await compute_children_debts(sheets, students, group_fees, default_fee)
        return {c["student_id"]: int(c["total_sum"] or 0) for c in children}
    except Exception:
        logger.exception("Failed computing total debt map")
        return {}
