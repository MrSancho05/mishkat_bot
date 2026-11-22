import asyncio
import copy
import re
import threading
import time as _time
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

import logging

import gspread
from google.oauth2.service_account import Credentials

import app.config as _app_config
from app.utils import now_tashkent, to_tashkent, today_tashkent
from app.config import (
    CREDENTIALS_PATH,
    GROUP_SHEET_NAME,
    SPREADSHEET_ID,
    STUDENT_SHEET_NAME,
    TZ,
)
from app.locales import MONTHS_UPPER_LATN, WEEKDAYS_SHORT

TEACHER_SHEET_NAME = getattr(_app_config, "TEACHER_SHEET_NAME", "Ustozlar")
_sheets_logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

MISSING_TEXT = "Ma'lumot kiritilmagan"
YELLOW_BG = {"red": 1.0, "green": 0.949, "blue": 0.8}
RED_BG = {"red": 0.957, "green": 0.8, "blue": 0.8}
GREEN_BG = {"red": 0.851, "green": 0.918, "blue": 0.827}
WHITE_BG = {"red": 1.0, "green": 1.0, "blue": 1.0}

STUDENT_HEADERS = [
    "Talaba_ID",
    "F.I.O.",
    "Guruh",
    "Talaba_Tel",
    "Talaba_TG",
    "Talaba_Chat_ID",
    "Otasi_FIO",
    "Otasi_Tel",
    "Otasi_Chat_ID",
    "Onasi_FIO",
    "Onasi_Tel",
    "Onasi_Chat_ID",
    "Status",
    "Qarzdor_Oylar",
    "Sobiq_Guruh",
    "Izoh",
]

# Columns that may legitimately stay empty (never auto-filled with the yellow
# "Ma'lumot kiritilmagan" placeholder).
STUDENT_OPTIONAL_COLS = {"Qarzdor_Oylar", "Sobiq_Guruh", "Izoh"}

RESERVE_GROUP_NAME = "Zahira guruhi"
LEAD_SHEET_NAME = "Qiziquvchilar_Lidlar"
LEAD_HEADERS = [
    "Lead_ID",
    "Sana_Vaqt",
    "F.I.O.",
    "Telefon",
    "Tanlangan_Kurs",
    "Telegram_Username",
    "Chat_ID",
    "Holat",
]
# Older spreadsheets used these header names; they are renamed in place on init.
LEAD_LEGACY_HEADER_RENAMES = {
    "Lid_ID": "Lead_ID",
    "Sana": "Sana_Vaqt",
    "Kurs": "Tanlangan_Kurs",
    "TG_Username": "Telegram_Username",
}
LEAD_OBSOLETE_HEADERS = ("Til",)

LEAD_STATUS_NEW = "Yangi"
LEAD_STATUS_CONTACTED = "Bog'lanildi"
# Light red (#F4CCCC) = pending, light green (#D9EAD3) = contacted.
LEAD_COLOR_NEW = {"red": 244 / 255, "green": 204 / 255, "blue": 204 / 255}
LEAD_COLOR_CONTACTED = {"red": 217 / 255, "green": 234 / 255, "blue": 211 / 255}

GROUP_HEADERS = [
    "Guruh_Nomi",
    "Ustoz_ID",
    "Ustoz_Chat_ID",
    "Guruh_TG_Chat_ID",
    "Oylik_Dars_Soni",
    "Dars_Kunlari",
    "Dars_Vaqti",
    "Otilgan_Dars_Hisoblagich",
    "Oylik_Tolov_Summa",
]

TEACHER_HEADERS = [
    "Ustoz_ID",
    "F.I.O.",
    "Telefon",
    "TG_Username",
    "Chat_ID",
    "Status",
]

COLOR_WHITE = WHITE_BG
COLOR_RED = RED_BG
COLOR_YELLOW = YELLOW_BG
COLOR_GREEN = GREEN_BG
COLOR_HEADER_GRAY = {"red": 239 / 255.0, "green": 239 / 255.0, "blue": 239 / 255.0}
COLOR_TITLE_BLUE = {"red": 207 / 255.0, "green": 226 / 255.0, "blue": 243 / 255.0}

WEEKDAY_MAP: dict[str, int] = {
    "dush": 0, "du": 0, "dushanba": 0, "mon": 0, "0": 0, "душ": 0, "ду": 0,
    "sesh": 1, "se": 1, "seshanba": 1, "tue": 1, "1": 1, "сеш": 1, "се": 1,
    "chor": 2, "ch": 2, "chorshanba": 2, "wed": 2, "2": 2, "чор": 2, "ч": 2,
    "pay": 3, "pa": 3, "payshanba": 3, "thu": 3, "3": 3, "пай": 3, "па": 3,
    "jum": 4, "ju": 4, "juma": 4, "fri": 4, "4": 4, "жум": 4, "жу": 4,
    "shan": 5, "sh": 5, "shanba": 5, "sat": 5, "5": 5, "шан": 5, "ш": 5,
    "yak": 6, "ya": 6, "yakshanba": 6, "sun": 6, "6": 6, "як": 6,
}

CYCLE_TITLE_RE = re.compile(r"^(?P<title>.+\(Sikl #(?P<num>\d+)\))$")
DATE_HEADER_RE = re.compile(r"^\d{2}\.\d{2}$")

PRESENT_MARKS = {"✅", "keldi", "келди"}
ABSENT_MARKS = {"❌", "kelmadi", "келмади", "yo'q", "yoq", "йўқ"}

STUDENT_CHAT_ID_COLS = (
    "Talaba_Chat_ID",
    "Otasi_Chat_ID",
    "Onasi_Chat_ID",
    "OtaOna_Chat_ID",
)


def _is_present_mark(mark: Any) -> bool:
    val = str(mark or "").strip().lower()
    return val in PRESENT_MARKS


def _is_absent_mark(mark: Any) -> bool:
    val = str(mark or "").strip().lower()
    return val in ABSENT_MARKS


def _is_recorded_mark(mark: Any) -> bool:
    return _is_present_mark(mark) or _is_absent_mark(mark)


def _normalize_read_value(val: Any) -> str:
    if val is None:
        return ""
    cleaned = str(val).strip()
    if cleaned == MISSING_TEXT:
        return ""
    return cleaned


def _normalize_chat_id(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if val != 0 else None
    if isinstance(val, float):
        try:
            int_val = int(val)
            return int_val if int_val != 0 and float(int_val) == val else None
        except (ValueError, OverflowError):
            return None
    cleaned = str(val).strip()
    if not cleaned or cleaned == MISSING_TEXT:
        return None
    if re.fullmatch(r"-?\d+(?:\.0+)?", cleaned):
        int_val = int(cleaned.split(".", 1)[0])
        return int_val if int_val != 0 else None
    return None


def _normalize_phone_key(phone: Any) -> str:
    cleaned = _normalize_read_value(phone)
    if not cleaned or cleaned.lower() in {"yo'q", "yoq", "йўқ", "—", "-"}:
        return ""
    digits = re.sub(r"\D", "", cleaned)
    if not digits or len(digits) < 7:
        return ""
    if len(digits) == 9:
        return f"998{digits}"
    if len(digits) == 12 and digits.startswith("998"):
        return digits
    return digits


def _normalize_student_id_key(val: Any) -> str:
    """Case/whitespace-insensitive Talaba_ID key (e.g. ' st001 ' -> 'ST001')."""
    cleaned = _normalize_read_value(val)
    return re.sub(r"\s+", "", cleaned).upper()


def _normalize_fio_key(val: Any) -> str:
    """Normalized F.I.O. key: collapsed whitespace, lower-case, unified apostrophes."""
    cleaned = _normalize_read_value(val)
    for ch in ("‘", "’", "ʻ", "ʼ", "`", "´"):
        cleaned = cleaned.replace(ch, "'")
    return " ".join(cleaned.split()).lower()


def _chat_id_str(val: Any) -> str:
    """Normalized chat id as a string ('123456.0' -> '123456'); '' if invalid."""
    norm = _normalize_chat_id(val)
    return str(norm) if norm is not None else ""


def _is_paid_status(status_val: str) -> bool:
    val = (status_val or "").strip().lower()
    if not val or "to'lanmagan" in val or "тўланмаган" in val:
        return False
    return "✅" in val or "to'langan" in val or "тўланган" in val


def _parse_today_date(today_str: str) -> date:
    clean = (today_str or "").strip()
    if not clean:
        return today_tashkent()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    if re.match(r"^\d{1,2}\.\d{1,2}$", clean):
        try:
            d_val, m_val = map(int, clean.split("."))
            return date(now_tashkent().year, m_val, d_val)
        except ValueError:
            pass
    return today_tashkent()


def parse_weekdays(days_str: str) -> list[int]:
    result: list[int] = []
    for token in re.split(r"[,;/\s]+", days_str.strip()):
        cleaned = token.strip().lower()
        if cleaned in WEEKDAY_MAP:
            day_idx = WEEKDAY_MAP[cleaned]
            if day_idx not in result:
                result.append(day_idx)
    return sorted(result)


def _get_anchor_date_for_schedule(
    now_dt: datetime, lesson_time_str: str = ""
) -> date:
    today = now_dt.date()
    match = re.match(r"^(\d{1,2})[:.](\d{2})$", (lesson_time_str or "").strip())
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            if now_dt.time() >= time(hour=hour, minute=minute):
                return today + timedelta(days=1)
    return today


def generate_cycle_dates(
    start_date: date, lesson_days: list[int], count: int
) -> list[date]:
    if not lesson_days:
        raise ValueError("lesson_days cannot be empty")
    if count <= 0:
        raise ValueError("count must be positive")
    dates: list[date] = []
    cursor = start_date
    while len(dates) < count:
        if cursor.weekday() in lesson_days:
            dates.append(cursor)
        cursor += timedelta(days=1)
    return dates


generate_lesson_dates = generate_cycle_dates


def get_next_lesson_date_after(after_date: date, lesson_days: list[int]) -> date:
    if not lesson_days:
        raise ValueError("lesson_days cannot be empty")
    cursor = after_date + timedelta(days=1)
    while cursor.weekday() not in lesson_days:
        cursor += timedelta(days=1)
    return cursor


def format_cycle_title(dates: list[date], cycle_number: int) -> str:
    if not dates:
        today = today_tashkent()
        month_name = MONTHS_UPPER_LATN[today.month]
        return f"{month_name} {today.year} (Sikl #{cycle_number})"
    dominant_year, dominant_month = Counter(
        (d.year, d.month) for d in dates
    ).most_common(1)[0][0]
    month_name = MONTHS_UPPER_LATN[dominant_month]
    return f"{month_name} {dominant_year} (Sikl #{cycle_number})"


def _col_letter(col_idx_0: int) -> str:
    n = col_idx_0 + 1
    letters = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _color_matches(bg: Optional[dict[str, Any]], target: dict[str, float]) -> bool:
    if not bg:
        return False
    r = float(bg.get("red", 0.0))
    g = float(bg.get("green", 0.0))
    b = float(bg.get("blue", 0.0))
    return (
        abs(r - target["red"]) < 0.05
        and abs(g - target["green"]) < 0.05
        and abs(b - target["blue"]) < 0.05
    )


def _cell_bg_request(
    sheet_id: int,
    row_start: int,
    row_end: int,
    col_start: int,
    col_end: int,
    color: dict[str, float],
    bold: Optional[bool] = None,
    h_align: Optional[str] = None,
) -> dict[str, Any]:
    cell_format: dict[str, Any] = {"backgroundColor": color}
    fields = ["userEnteredFormat.backgroundColor"]
    if bold is not None:
        cell_format["textFormat"] = {"bold": bold}
        fields.append("userEnteredFormat.textFormat.bold")
    if h_align is not None:
        cell_format["horizontalAlignment"] = h_align
        fields.append("userEnteredFormat.horizontalAlignment")
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_start,
                "endRowIndex": row_end,
                "startColumnIndex": col_start,
                "endColumnIndex": col_end,
            },
            "cell": {"userEnteredFormat": cell_format},
            "fields": ",".join(fields),
        }
    }


def _borders_request(
    sheet_id: int,
    row_start: int,
    row_end: int,
    col_start: int,
    col_end: int,
) -> dict[str, Any]:
    border_style = {
        "style": "SOLID",
        "width": 1,
        "color": {"red": 0.75, "green": 0.75, "blue": 0.75},
    }
    return {
        "updateBorders": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_start,
                "endRowIndex": row_end,
                "startColumnIndex": col_start,
                "endColumnIndex": col_end,
            },
            "top": border_style,
            "bottom": border_style,
            "left": border_style,
            "right": border_style,
            "innerHorizontal": border_style,
            "innerVertical": border_style,
        }
    }


def _clear_borders_request(
    sheet_id: int,
    row_start: int,
    row_end: int,
    col_start: int,
    col_end: int,
) -> dict[str, Any]:
    no_border = {"style": "NONE"}
    return {
        "updateBorders": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row_start,
                "endRowIndex": row_end,
                "startColumnIndex": col_start,
                "endColumnIndex": col_end,
            },
            "top": no_border,
            "bottom": no_border,
            "left": no_border,
            "right": no_border,
            "innerHorizontal": no_border,
            "innerVertical": no_border,
        }
    }


def _is_rate_limit_error(exc: Exception) -> bool:
    if isinstance(exc, gspread.exceptions.APIError):
        resp = getattr(exc, "response", None)
        status_code = getattr(resp, "status_code", None)
        if status_code == 429:
            return True
        msg = str(exc).lower()
        if "429" in msg or "quota exceeded" in msg or "rate limit" in msg:
            return True
    return False


class SheetsManager:
    def __init__(
        self,
        spreadsheet_id: str = SPREADSHEET_ID,
        credentials_path: str = str(CREDENTIALS_PATH),
    ) -> None:
        self._spreadsheet_id = spreadsheet_id
        self._credentials_path = credentials_path
        self._lock = threading.RLock()
        self._client: Optional[gspread.Client] = None
        self._spreadsheet: Optional[gspread.Spreadsheet] = None
        self._ws_cache: dict[str, tuple[gspread.Worksheet, list[str]]] = {}
        self._students_cache: Optional[tuple[float, list[dict[str, Any]]]] = None
        self._groups_cache: Optional[tuple[float, list[dict[str, Any]]]] = None
        self._cache_ttl: float = 20.0
        self._cycle_snapshot_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def _invalidate_students_cache(self) -> None:
        self._students_cache = None

    def _invalidate_groups_cache(self) -> None:
        self._groups_cache = None

    def _execute_with_retry(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        backoff_delays = (2.0, 4.0, 8.0, 15.0)
        attempt = 0
        while True:
            try:
                return func(*args, **kwargs)
            except gspread.exceptions.APIError as exc:
                if _is_rate_limit_error(exc) and attempt < len(backoff_delays):
                    _time.sleep(backoff_delays[attempt])
                    attempt += 1
                    continue
                raise

    def _retry_sheets_op(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        last_exc: Optional[Exception] = None
        for attempt in range(3):
            try:
                return self._execute_with_retry(func, *args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    _time.sleep(1)
        if last_exc is not None:
            raise last_exc
        return None

    def _verify_and_format_range(
        self,
        ws: gspread.Worksheet,
        start_row_1: int,
        end_row_1: int,
        start_col_0: int,
        end_col_0: int,
        color: dict[str, float],
        bold: Optional[bool] = None,
        h_align: Optional[str] = None,
    ) -> None:
        if start_row_1 < 1 or end_row_1 < start_row_1:
            raise ValueError(f"Invalid row range: {start_row_1}:{end_row_1}")
        if start_col_0 < 0 or end_col_0 < start_col_0:
            raise ValueError(f"Invalid column range: {start_col_0}:{end_col_0}")

        start_col_letter = _col_letter(start_col_0)
        end_col_letter = _col_letter(end_col_0)
        if start_row_1 == end_row_1 and start_col_0 == end_col_0:
            a1_range = f"{start_col_letter}{start_row_1}"
        else:
            a1_range = f"{start_col_letter}{start_row_1}:{end_col_letter}{end_row_1}"

        if not re.fullmatch(r"[A-Z]+\d+(?::[A-Z]+\d+)?", a1_range):
            raise ValueError(f"Invalid A1 range: {a1_range}")

        cell_format: dict[str, Any] = {"backgroundColor": color}
        if bold is not None:
            cell_format["textFormat"] = {"bold": bold}
        if h_align is not None:
            cell_format["horizontalAlignment"] = h_align

        self._retry_sheets_op(ws.format, a1_range, cell_format)

    def _apply_color_requests_with_fallback(
        self,
        ws: gspread.Worksheet,
        requests: list[dict[str, Any]],
        fallback_ranges: Optional[
            list[Optional[tuple[int, int, int, dict[str, float], Optional[bool]]]]
        ] = None,
    ) -> bool:
        """
        Applies background-color requests in ONE batch_update (429-aware retry).
        If the batch still fails, falls back to per-range `ws.format` calls
        (each with its own retry) so the payment colour is never silently lost.
        fallback_ranges items: (row_1, start_col_0, end_col_0, color, bold).
        """
        if not requests:
            return True
        try:
            self._retry_sheets_op(
                self._get_spreadsheet().batch_update, {"requests": requests}
            )
            return True
        except Exception as batch_exc:
            _sheets_logger.warning(
                "Batch colour update failed on '%s' (%s); retrying per range.",
                ws.title,
                batch_exc,
            )
        ok = True
        for item in fallback_ranges or []:
            if not item:
                continue
            row_1, c_start, c_end, color, bold = item
            try:
                self._verify_and_format_range(
                    ws, row_1, row_1, c_start, c_end, color, bold=bold, h_align="CENTER"
                )
            except Exception:
                ok = False
                _sheets_logger.exception(
                    "Failed to colour %s row %s cols %s-%s", ws.title, row_1, c_start, c_end
                )
        return ok

    def _get_spreadsheet(self) -> gspread.Spreadsheet:
        with self._lock:
            if self._spreadsheet is None:
                creds = Credentials.from_service_account_file(
                    self._credentials_path, scopes=SCOPES
                )
                self._client = gspread.authorize(creds)
                self._spreadsheet = self._execute_with_retry(
                    self._client.open_by_key, self._spreadsheet_id
                )
            return self._spreadsheet

    def _get_or_create_worksheet(
        self,
        title: str,
        headers: Optional[list[str]] = None,
        rows: int = 200,
        cols: int = 26,
    ) -> gspread.Worksheet:
        with self._lock:
            cached = self._ws_cache.get(title)
            if cached is not None:
                ws, cached_headers = cached
                if headers and not cached_headers:
                    self._execute_with_retry(
                        ws.update, "A1", [headers], value_input_option="USER_ENTERED"
                    )
                    self._ws_cache[title] = (ws, list(headers))
                return ws

            ss = self._get_spreadsheet()
            try:
                ws = self._execute_with_retry(ss.worksheet, title)
            except gspread.WorksheetNotFound:
                ws = self._execute_with_retry(
                    ss.add_worksheet, title=title, rows=rows, cols=cols
                )
                cached_headers: list[str] = []
                if headers:
                    self._execute_with_retry(
                        ws.update, "A1", [headers], value_input_option="USER_ENTERED"
                    )
                    self._execute_with_retry(
                        ss.batch_update,
                        {
                            "requests": [
                                _cell_bg_request(
                                    ws.id,
                                    0,
                                    1,
                                    0,
                                    len(headers),
                                    COLOR_HEADER_GRAY,
                                    bold=True,
                                )
                            ]
                        },
                    )
                    cached_headers = list(headers)
                self._ws_cache[title] = (ws, cached_headers)
            else:
                cached_headers = []
                if headers:
                    existing_first_row = self._execute_with_retry(ws.row_values, 1)
                    if not existing_first_row:
                        self._execute_with_retry(
                            ws.update,
                            "A1",
                            [headers],
                            value_input_option="USER_ENTERED",
                        )
                        cached_headers = list(headers)
                    else:
                        cached_headers = list(existing_first_row)
                self._ws_cache[title] = (ws, cached_headers)
            return ws

    def _get_cached_headers(self, ws: gspread.Worksheet) -> list[str]:
        cached = self._ws_cache.get(ws.title)
        if cached is not None and cached[1]:
            return list(cached[1])
        headers = self._execute_with_retry(ws.row_values, 1)
        self._ws_cache[ws.title] = (ws, list(headers))
        return list(headers)

    def _ensure_missing_headers(
        self, ws: gspread.Worksheet, expected_headers: list[str]
    ) -> list[str]:
        headers = self._get_cached_headers(ws)
        if not headers:
            self._execute_with_retry(
                ws.update, "A1", [expected_headers], value_input_option="USER_ENTERED"
            )
            self._ws_cache[ws.title] = (ws, list(expected_headers))
            return list(expected_headers)
        missing = [h for h in expected_headers if h not in headers]
        if missing:
            start_col = len(headers)
            needed_cols = start_col + len(missing)
            if ws.col_count < needed_cols:
                self._execute_with_retry(ws.resize, cols=needed_cols + 2)
            a1 = f"{_col_letter(start_col)}1"
            self._execute_with_retry(
                ws.update, a1, [missing], value_input_option="USER_ENTERED"
            )
            headers = headers + missing
            self._ws_cache[ws.title] = (ws, list(headers))
        return headers

    def _cleanup_teacher_sheet_headers(self, ws: gspread.Worksheet) -> list[str]:
        """
        Ensures Ustozlar has ONLY ONE username column ('TG_Username') by removing
        any duplicate 'Telegram' column if present.
        """
        headers = self._get_cached_headers(ws)
        if not headers:
            self._execute_with_retry(
                ws.update, "A1", [TEACHER_HEADERS], value_input_option="USER_ENTERED"
            )
            self._ws_cache[ws.title] = (ws, list(TEACHER_HEADERS))
            return list(TEACHER_HEADERS)

        if "Telegram" in headers:
            tg_dup_idx = headers.index("Telegram")
            if "TG_Username" not in headers:
                self._execute_with_retry(
                    ws.update,
                    f"{_col_letter(tg_dup_idx)}1",
                    [["TG_Username"]],
                    value_input_option="USER_ENTERED",
                )
                headers[tg_dup_idx] = "TG_Username"
                self._ws_cache[ws.title] = (ws, list(headers))
            else:
                tg_main_idx = headers.index("TG_Username")
                all_rows = self._execute_with_retry(ws.get_all_values)
                updates: list[dict[str, Any]] = []
                for r_idx, raw_row in enumerate(all_rows[1:], start=2):
                    main_val = (
                        _normalize_read_value(raw_row[tg_main_idx])
                        if tg_main_idx < len(raw_row)
                        else ""
                    )
                    dup_val = (
                        _normalize_read_value(raw_row[tg_dup_idx])
                        if tg_dup_idx < len(raw_row)
                        else ""
                    )
                    if not main_val and dup_val:
                        updates.append(
                            {
                                "range": f"{_col_letter(tg_main_idx)}{r_idx}",
                                "values": [[dup_val]],
                            }
                        )
                if updates:
                    self._execute_with_retry(
                        ws.batch_update, updates, value_input_option="USER_ENTERED"
                    )
                self._execute_with_retry(ws.delete_columns, tg_dup_idx + 1)
                headers.pop(tg_dup_idx)
                self._ws_cache[ws.title] = (ws, list(headers))

        return self._ensure_missing_headers(ws, TEACHER_HEADERS)

    def _append_row_and_get_index(
        self, ws: gspread.Worksheet, row_values: list[Any]
    ) -> int:
        resp = self._execute_with_retry(
            ws.append_row, row_values, value_input_option="USER_ENTERED"
        )
        updated_range = ""
        if isinstance(resp, dict):
            updated_range = (resp.get("updates") or {}).get("updatedRange", "")
        match = re.search(r"!(?:[A-Z]+)(\d+)", updated_range)
        if match:
            return int(match.group(1))
        return max(len(self._execute_with_retry(ws.get_all_values)), 2)

    def _sync_row_missing_cells(
        self,
        ws: gspread.Worksheet,
        row_idx: int,
        row_values: list[Any],
        exclude_cols: Optional[
            set[str | int] | list[str | int] | tuple[str | int, ...]
        ] = None,
    ) -> list[str]:
        with self._lock:
            headers = self._get_cached_headers(ws)
            total_cols = max(len(headers), len(row_values))
            if total_cols == 0:
                return []

            exclude_indices: set[int] = set()
            if exclude_cols:
                for item in exclude_cols:
                    if isinstance(item, int):
                        exclude_indices.add(item)
                    elif isinstance(item, str) and item in headers:
                        exclude_indices.add(headers.index(item))

            padded = list(row_values) + [""] * (total_cols - len(row_values))
            normalized_row: list[str] = []
            cell_colors: list[dict[str, float]] = []

            for col_idx in range(total_cols):
                raw = padded[col_idx]
                val_str = "" if raw is None else str(raw).strip()
                if col_idx in exclude_indices:
                    normalized_row.append(val_str)
                    cell_colors.append(WHITE_BG)
                elif val_str == "" or val_str == MISSING_TEXT:
                    normalized_row.append(MISSING_TEXT)
                    cell_colors.append(YELLOW_BG)
                else:
                    normalized_row.append(val_str)
                    cell_colors.append(WHITE_BG)

            if ws.col_count < total_cols:
                self._execute_with_retry(ws.resize, cols=total_cols + 2)
            if ws.row_count < row_idx:
                self._execute_with_retry(ws.resize, rows=row_idx + 20)

            end_col_letter = _col_letter(total_cols - 1)
            self._retry_sheets_op(
                ws.update,
                f"A{row_idx}:{end_col_letter}{row_idx}",
                [normalized_row],
                value_input_option="USER_ENTERED",
            )

            requests: list[dict[str, Any]] = []
            start_col = 0
            while start_col < total_cols:
                current_color = cell_colors[start_col]
                end_col = start_col + 1
                while end_col < total_cols and cell_colors[end_col] == current_color:
                    end_col += 1
                requests.append(
                    _cell_bg_request(
                        ws.id,
                        row_idx - 1,
                        row_idx,
                        start_col,
                        end_col,
                        current_color,
                    )
                )
                start_col = end_col

            if requests:
                ss = self._get_spreadsheet()
                self._retry_sheets_op(ss.batch_update, {"requests": requests})

            return normalized_row

    def ensure_master_sheets(self) -> None:
        with self._lock:
            ws_students = self._get_or_create_worksheet(
                STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
            )
            self._ensure_missing_headers(ws_students, STUDENT_HEADERS)

            ws_groups = self._get_or_create_worksheet(
                GROUP_SHEET_NAME, headers=GROUP_HEADERS, rows=100, cols=12
            )
            self._ensure_missing_headers(ws_groups, GROUP_HEADERS)

            ws_teachers = self._get_or_create_worksheet(
                TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=100, cols=10
            )
            self._cleanup_teacher_sheet_headers(ws_teachers)

            ws_leads = self._get_or_create_worksheet(
                LEAD_SHEET_NAME,
                headers=LEAD_HEADERS,
                rows=500,
                cols=len(LEAD_HEADERS) + 2,
            )
            self._ensure_missing_headers(ws_leads, LEAD_HEADERS)

    # ------------------------------------------------------------------
    # CRUD: Baza_Talabalar & Global Propagation
    # ------------------------------------------------------------------

    def _normalize_student_record(self, record: dict[str, Any]) -> dict[str, Any]:
        for col in STUDENT_CHAT_ID_COLS:
            if col in record:
                norm_cid = _normalize_chat_id(record.get(col))
                record[col] = norm_cid if norm_cid is not None else ""
        return record

    def _parse_students_from_rows(
        self, rows: list[list[str]]
    ) -> tuple[list[str], list[dict[str, Any]]]:
        if len(rows) <= 1:
            return (rows[0] if rows else list(STUDENT_HEADERS)), []
        headers = rows[0]
        students: list[dict[str, Any]] = []
        for idx, raw_row in enumerate(rows[1:], start=2):
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            record: dict[str, Any] = {
                h: _normalize_read_value(v) for h, v in zip(headers, padded)
            }
            for h in STUDENT_HEADERS:
                record.setdefault(h, "")
            self._normalize_student_record(record)
            record["_row_number"] = idx
            if not record.get("Talaba_ID"):
                continue
            students.append(record)
        return headers, students

    def get_all_students(
        self, group_name: Optional[str] = None, active_only: bool = False
    ) -> list[dict[str, Any]]:
        with self._lock:
            now_ts = _time.monotonic()
            cached = self._students_cache
            if cached is not None and (now_ts - cached[0]) < self._cache_ttl:
                all_students = cached[1]
            else:
                ws = self._get_or_create_worksheet(
                    STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
                )
                rows = self._execute_with_retry(ws.get_all_values)
                if rows:
                    self._ws_cache[ws.title] = (ws, list(rows[0]))
                _, all_students = self._parse_students_from_rows(rows)
                self._students_cache = (now_ts, all_students)

            if not group_name and not active_only:
                return copy.deepcopy(all_students)

            target_group = group_name.strip().lower() if group_name else ""
            filtered: list[dict[str, Any]] = []
            for record in all_students:
                if (
                    target_group
                    and record.get("Guruh", "").strip().lower() != target_group
                ):
                    continue
                if active_only and record.get("Status", "").strip() != "O'qiyapti":
                    continue
                filtered.append(copy.deepcopy(record))
            return filtered

    def get_reserve_students(self) -> list[dict[str, Any]]:
        """Returns all students in Baza_Talabalar with Status == \"O'qimayapti\"."""
        with self._lock:
            return [
                student
                for student in self.get_all_students()
                if str(student.get("Status", "")).strip().lower() == "o'qimayapti"
            ]

    def get_student_by_id(self, student_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            target = _normalize_student_id_key(student_id)
            if not target:
                return None
            for student in self.get_all_students():
                if _normalize_student_id_key(student.get("Talaba_ID", "")) == target:
                    return student
            return None

    def get_student(self, student_id: str) -> Optional[dict[str, Any]]:
        return self.get_student_by_id(student_id)

    def get_student_by_chat_id(
        self, chat_id: int | str
    ) -> Optional[tuple[dict[str, Any], str]]:
        with self._lock:
            norm_cid = _normalize_chat_id(chat_id)
            target = str(norm_cid) if norm_cid is not None else _normalize_read_value(chat_id)
            if not target:
                return None
            for student in self.get_all_students():
                if str(student.get("Talaba_Chat_ID") or "").strip() == target:
                    return student, "student"
                if str(student.get("Otasi_Chat_ID") or "").strip() == target:
                    return student, "parent"
                if str(student.get("Onasi_Chat_ID") or "").strip() == target:
                    return student, "parent"
                if str(student.get("OtaOna_Chat_ID") or "").strip() == target:
                    return student, "parent"
            return None

    def get_students_by_chat_id(
        self, chat_id: int | str
    ) -> list[dict[str, Any]]:
        """Returns all student enrollment records matching Talaba_Chat_ID."""
        with self._lock:
            norm_cid = _normalize_chat_id(chat_id)
            target = str(norm_cid) if norm_cid is not None else _normalize_read_value(chat_id)
            if not target:
                return []
            return [
                student
                for student in self.get_all_students()
                if str(student.get("Talaba_Chat_ID") or "").strip() == target
            ]

    def get_children_by_parent_chat_id(
        self, chat_id: int | str
    ) -> list[dict[str, Any]]:
        """Returns all student enrollment records linked to a parent's chat_id."""
        with self._lock:
            norm_cid = _normalize_chat_id(chat_id)
            target = str(norm_cid) if norm_cid is not None else _normalize_read_value(chat_id)
            if not target:
                return []
            matches: list[dict[str, Any]] = []
            parent_phones: set[str] = set()
            all_rows = self.get_all_students()
            for student in all_rows:
                matched = False
                for cid_col, tel_col in (
                    ("Otasi_Chat_ID", "Otasi_Tel"),
                    ("Onasi_Chat_ID", "Onasi_Tel"),
                    ("OtaOna_Chat_ID", "OtaOna_Tel"),
                ):
                    if _chat_id_str(student.get(cid_col)) == target:
                        matched = True
                        p_key = _normalize_phone_key(student.get(tel_col))
                        if p_key:
                            parent_phones.add(p_key)
                if matched:
                    matches.append(student)

            # Sibling rows sharing the same parent phone but not yet bound to
            # this chat id: include them and propagate the chat id (once).
            if parent_phones:
                try:
                    stu_ws = self._get_or_create_worksheet(
                        STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
                    )
                    existing_cols = set(self._get_cached_headers(stu_ws))
                except Exception:
                    existing_cols = set(STUDENT_HEADERS)
                matched_ids = {str(m.get("Talaba_ID", "")).strip() for m in matches}
                for other in all_rows:
                    o_sid = str(other.get("Talaba_ID", "")).strip()
                    if not o_sid or o_sid in matched_ids:
                        continue
                    sib_updates: dict[str, Any] = {}
                    for cid_col, tel_col in (
                        ("Otasi_Chat_ID", "Otasi_Tel"),
                        ("Onasi_Chat_ID", "Onasi_Tel"),
                        ("OtaOna_Chat_ID", "OtaOna_Tel"),
                    ):
                        p_key = _normalize_phone_key(other.get(tel_col))
                        if (
                            p_key
                            and cid_col in existing_cols
                            and p_key in parent_phones
                            and not _chat_id_str(other.get(cid_col))
                        ):
                            sib_updates[cid_col] = target
                    if sib_updates:
                        try:
                            self.update_student(o_sid, sib_updates, _propagate_parent=False)
                        except Exception:
                            _sheets_logger.exception(
                                "Failed propagating parent chat id to sibling %s", o_sid
                            )
                        refreshed = dict(other)
                        refreshed.update(sib_updates)
                        matches.append(refreshed)
                        matched_ids.add(o_sid)
            return matches

    def _generate_next_student_id(self, existing_students: list[dict[str, Any]]) -> str:
        max_num = 0
        for s in existing_students:
            sid = s.get("Talaba_ID", "").strip()
            m = re.search(r"(\d+)$", sid)
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"ST{max_num + 1:03d}"

    def _propagate_parent_chat_ids_to_siblings(
        self,
        source_student: dict[str, Any],
        updates: dict[str, Any],
    ) -> None:
        """
        Propagates Otasi_Chat_ID / Onasi_Chat_ID / OtaOna_Chat_ID to all sibling
        rows in Baza_Talabalar that share the same normalized parent phone number
        (Otasi_Tel / Onasi_Tel / OtaOna_Tel) or parent_id.
        """
        source_sid = str(source_student.get("Talaba_ID", "")).strip()
        father_cid = _normalize_chat_id(updates.get("Otasi_Chat_ID"))
        mother_cid = _normalize_chat_id(updates.get("Onasi_Chat_ID"))
        generic_parent_cid = _normalize_chat_id(updates.get("OtaOna_Chat_ID"))

        if father_cid is None and mother_cid is None and generic_parent_cid is None:
            return

        def _merged(col: str) -> str:
            if col in updates and updates[col] is not None:
                return _normalize_read_value(updates[col])
            return _normalize_read_value(source_student.get(col))

        src_father_tel = _normalize_phone_key(_merged("Otasi_Tel"))
        src_mother_tel = _normalize_phone_key(_merged("Onasi_Tel"))
        src_generic_tel = _normalize_phone_key(_merged("OtaOna_Tel"))
        src_parent_id = _merged("parent_id") or _merged("Parent_ID")

        all_src_phones = {
            p for p in (src_father_tel, src_mother_tel, src_generic_tel) if p
        }
        if not all_src_phones and not src_parent_id:
            return

        for other in self.get_all_students():
            other_sid = str(other.get("Talaba_ID", "")).strip()
            if not other_sid or other_sid == source_sid:
                continue

            oth_father_tel = _normalize_phone_key(other.get("Otasi_Tel"))
            oth_mother_tel = _normalize_phone_key(other.get("Onasi_Tel"))
            oth_generic_tel = _normalize_phone_key(other.get("OtaOna_Tel"))
            oth_parent_id = _normalize_read_value(
                other.get("parent_id") or other.get("Parent_ID")
            )
            all_oth_phones = {
                p for p in (oth_father_tel, oth_mother_tel, oth_generic_tel) if p
            }

            same_parent_id = bool(src_parent_id and oth_parent_id == src_parent_id)
            shares_any_phone = bool(all_src_phones & all_oth_phones)
            if not (same_parent_id or shares_any_phone):
                continue

            sibling_updates: dict[str, Any] = {}
            if father_cid is not None:
                father_phones_src = {p for p in (src_father_tel, src_generic_tel) if p}
                father_phones_oth = {p for p in (oth_father_tel, oth_generic_tel) if p}
                if same_parent_id or bool(father_phones_src & father_phones_oth) or shares_any_phone:
                    if _normalize_chat_id(other.get("Otasi_Chat_ID")) != father_cid:
                        sibling_updates["Otasi_Chat_ID"] = str(father_cid)

            if mother_cid is not None:
                mother_phones_src = {p for p in (src_mother_tel, src_generic_tel) if p}
                mother_phones_oth = {p for p in (oth_mother_tel, oth_generic_tel) if p}
                if same_parent_id or bool(mother_phones_src & mother_phones_oth) or shares_any_phone:
                    if _normalize_chat_id(other.get("Onasi_Chat_ID")) != mother_cid:
                        sibling_updates["Onasi_Chat_ID"] = str(mother_cid)

            if generic_parent_cid is not None:
                if _normalize_chat_id(other.get("OtaOna_Chat_ID")) != generic_parent_cid:
                    sibling_updates["OtaOna_Chat_ID"] = str(generic_parent_cid)

            if sibling_updates:
                self.update_student(
                    other_sid, sibling_updates, _propagate_parent=False
                )

    def sync_student_across_all_sheets(
        self,
        student_id: str,
        old_fio: str = "",
        new_fio: str = "",
        updated_fields: Optional[dict[str, Any]] = None,
    ) -> int:
        """
        Propagates updated F.I.O. (and any other matching columns) across EVERY
        {Group}_{Year} cycle worksheet in the entire Google Spreadsheet, matching
        by Talaba_ID column if present AND/OR by the student's previous F.I.O. string.
        Returns the total number of cells updated across all cycle worksheets.
        """
        with self._lock:
            clean_sid = _normalize_read_value(student_id)
            clean_old_fio = _normalize_read_value(old_fio)
            clean_new_fio = _normalize_read_value(new_fio)
            if not clean_new_fio and updated_fields and "F.I.O." in updated_fields:
                clean_new_fio = _normalize_read_value(updated_fields.get("F.I.O."))

            if not clean_sid and not clean_old_fio:
                return 0

            ss = self._get_spreadsheet()
            master_titles = {
                STUDENT_SHEET_NAME.strip().lower(),
                GROUP_SHEET_NAME.strip().lower(),
                TEACHER_SHEET_NAME.strip().lower(),
                LEAD_SHEET_NAME.strip().lower(),
            }
            total_cells_updated = 0

            for ws in self._execute_with_retry(ss.worksheets):
                if ws.title.strip().lower() in master_titles:
                    continue

                all_rows = self._execute_with_retry(ws.get_all_values)
                if not all_rows:
                    continue

                updates: list[dict[str, Any]] = []
                current_headers: Optional[list[str]] = None

                for r_idx, raw_row in enumerate(all_rows, start=1):
                    first_cell = raw_row[0].strip() if raw_row else ""
                    if not any(cell.strip() for cell in raw_row):
                        current_headers = None
                        continue
                    if CYCLE_TITLE_RE.match(first_cell):
                        current_headers = None
                        continue

                    stripped_cells = [c.strip() for c in raw_row]
                    if "Talaba_ID" in stripped_cells or "F.I.O." in stripped_cells:
                        current_headers = stripped_cells
                        continue

                    headers_for_row = current_headers or ["Talaba_ID", "F.I.O."]
                    id_idx = (
                        headers_for_row.index("Talaba_ID")
                        if "Talaba_ID" in headers_for_row
                        else None
                    )
                    fio_idx = (
                        headers_for_row.index("F.I.O.")
                        if "F.I.O." in headers_for_row
                        else None
                    )

                    row_id = (
                        raw_row[id_idx].strip()
                        if id_idx is not None and id_idx < len(raw_row)
                        else ""
                    )
                    row_fio = (
                        raw_row[fio_idx].strip()
                        if fio_idx is not None and fio_idx < len(raw_row)
                        else ""
                    )

                    id_matches = bool(
                        clean_sid and id_idx is not None and row_id == clean_sid
                    )
                    fio_matches = bool(
                        clean_old_fio
                        and fio_idx is not None
                        and row_fio.lower() == clean_old_fio.lower()
                        and (not row_id or not clean_sid or row_id == clean_sid)
                    )

                    if not (id_matches or fio_matches):
                        continue

                    if (
                        fio_idx is not None
                        and clean_new_fio
                        and row_fio != clean_new_fio
                    ):
                        updates.append(
                            {
                                "range": f"{_col_letter(fio_idx)}{r_idx}",
                                "values": [[clean_new_fio]],
                            }
                        )

                    if updated_fields and current_headers:
                        for key, val in updated_fields.items():
                            if key in {"Talaba_ID", "F.I.O."}:
                                continue
                            if key in current_headers:
                                col_idx = current_headers.index(key)
                                new_val = "" if val is None else str(val).strip()
                                old_val = (
                                    raw_row[col_idx].strip()
                                    if col_idx < len(raw_row)
                                    else ""
                                )
                                if old_val != new_val:
                                    updates.append(
                                        {
                                            "range": f"{_col_letter(col_idx)}{r_idx}",
                                            "values": [[new_val]],
                                        }
                                    )

                if updates:
                    self._execute_with_retry(
                        ws.batch_update, updates, value_input_option="USER_ENTERED"
                    )
                    total_cells_updated += len(updates)

            return total_cells_updated

    def add_student(
        self,
        full_name: str = "",
        group_name: str = "",
        student_phone: str = "",
        student_tg: str = "",
        parent_phone: str = "",
        status: str = "O'qiyapti",
        student_chat_id: int | str = "",
        father_name: str = "",
        father_phone: str = "",
        father_chat_id: int | str = "",
        mother_name: str = "",
        mother_phone: str = "",
        mother_chat_id: int | str = "",
        debt_months: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Appends a new student row to Baza_Talabalar. A brand-new ACTIVE student
        is charged upfront for the current month right away (Qarzdor_Oylar = 1),
        unless an explicit `debt_months` value is provided (e.g. dual-enrollment).
        """
        with self._lock:
            ws = self._get_or_create_worksheet(
                STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
            )
            headers = self._ensure_missing_headers(ws, STUDENT_HEADERS)
            existing = self.get_all_students()
            student_id = self._generate_next_student_id(existing)

            tg_val = _normalize_read_value(student_tg)
            if tg_val and not tg_val.startswith("@"):
                tg_val = f"@{tg_val}"

            clean_student_phone = _normalize_read_value(student_phone)
            if clean_student_phone.lower() in {"yo'q", "yoq", "йўқ"}:
                clean_student_phone = "Yo'q"

            norm_stu_cid = _normalize_chat_id(student_chat_id)
            norm_father_cid = _normalize_chat_id(father_chat_id)
            norm_mother_cid = _normalize_chat_id(mother_chat_id)

            if debt_months is None:
                debt_val = (
                    "1"
                    if _normalize_read_value(status).strip().lower() == "o'qiyapti"
                    else "0"
                )
            else:
                debt_val = _normalize_read_value(debt_months) or "0"
            row_map = {
                "Talaba_ID": student_id,
                "F.I.O.": _normalize_read_value(full_name),
                "Guruh": _normalize_read_value(group_name),
                "Talaba_Tel": clean_student_phone,
                "Talaba_TG": tg_val,
                "Talaba_Chat_ID": str(norm_stu_cid) if norm_stu_cid is not None else "",
                "Otasi_FIO": _normalize_read_value(father_name),
                "Otasi_Tel": _normalize_read_value(father_phone),
                "Otasi_Chat_ID": str(norm_father_cid) if norm_father_cid is not None else "",
                "Onasi_FIO": _normalize_read_value(mother_name),
                "Onasi_Tel": _normalize_read_value(mother_phone),
                "Onasi_Chat_ID": str(norm_mother_cid) if norm_mother_cid is not None else "",
                "OtaOna_Tel": _normalize_read_value(parent_phone),
                "OtaOna_Chat_ID": "",
                "Status": _normalize_read_value(status),
                "Qarzdor_Oylar": debt_val,
            }
            new_row = [row_map.get(h, "") for h in headers]
            new_row_idx = self._append_row_and_get_index(ws, new_row)
            self._sync_row_missing_cells(
                ws, new_row_idx, new_row, exclude_cols=STUDENT_OPTIONAL_COLS
            )
            self._invalidate_students_cache()
            created = self.get_student_by_id(student_id)
            if created is None:
                created = {
                    h: _normalize_read_value(row_map.get(h, "")) for h in headers
                }
                self._normalize_student_record(created)

            if norm_father_cid is not None or norm_mother_cid is not None:
                self._propagate_parent_chat_ids_to_siblings(
                    created,
                    {
                        "Otasi_Chat_ID": norm_father_cid,
                        "Onasi_Chat_ID": norm_mother_cid,
                    },
                )
            return created

    def update_student(
        self,
        student_id: str,
        updates: dict[str, Any],
        _propagate_parent: bool = True,
    ) -> bool:
        with self._lock:
            ws = self._get_or_create_worksheet(
                STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
            )
            headers = self._ensure_missing_headers(ws, STUDENT_HEADERS)
            student = self.get_student_by_id(student_id)
            if not student:
                return False

            old_fio = str(student.get("F.I.O.", "")).strip()
            row_num = student["_row_number"]
            raw_row = self._execute_with_retry(ws.row_values, row_num)
            row_values = raw_row + [""] * (len(headers) - len(raw_row))

            normalized_updates: dict[str, Any] = {}
            for key, value in updates.items():
                if key == "Talaba_Tel" and value is not None:
                    v_str = str(value).strip()
                    if v_str.lower() in {"yo'q", "yoq", "йўқ"}:
                        value = "Yo'q"
                elif key in STUDENT_CHAT_ID_COLS and value is not None:
                    norm_cid = _normalize_chat_id(value)
                    value = str(norm_cid) if norm_cid is not None else ""
                normalized_updates[key] = value
                if key in headers:
                    col_idx = headers.index(key)
                    row_values[col_idx] = "" if value is None else str(value)

            if "Qarzdor_Oylar" in headers:
                q_idx = headers.index("Qarzdor_Oylar")
                q_val = str(row_values[q_idx]).strip()
                if not q_val or q_val == MISSING_TEXT:
                    row_values[q_idx] = "0"

            self._sync_row_missing_cells(
                ws, row_num, row_values, exclude_cols=STUDENT_OPTIONAL_COLS
            )
            self._invalidate_students_cache()

            if _propagate_parent and any(
                k in normalized_updates
                for k in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID")
            ):
                self._propagate_parent_chat_ids_to_siblings(
                    student, normalized_updates
                )

            if set(normalized_updates.keys()) != {"Qarzdor_Oylar"}:
                new_fio = (
                    _normalize_read_value(normalized_updates["F.I.O."])
                    if "F.I.O." in normalized_updates
                    else old_fio
                )
                self.sync_student_across_all_sheets(
                    student_id=student_id,
                    old_fio=old_fio,
                    new_fio=new_fio,
                    updated_fields=normalized_updates,
                )

            return True

    def remove_student_from_cycle_sheet(
        self,
        group_name: str,
        student_id: str,
        year: Optional[int] = None,
    ) -> bool:
        """
        Deletes ONLY the exact student_id row from the specified group's {Group}_{Year}
        cycle sheet(s). Leaves other enrollments untouched.
        """
        with self._lock:
            target_group = group_name.strip()
            target_id = student_id.strip()
            if not target_group or not target_id:
                return False

            ss = self._get_spreadsheet()
            prefix_lower = (
                f"{target_group.lower()}_{year}"
                if year is not None
                else f"{target_group.lower()}_"
            )
            removed_any = False

            for cycle_ws in self._execute_with_retry(ss.worksheets):
                title_lower = cycle_ws.title.lower()
                if year is not None:
                    if title_lower != prefix_lower:
                        continue
                else:
                    if not title_lower.startswith(prefix_lower):
                        continue
                    suffix = cycle_ws.title[len(target_group) + 1 :]
                    if not suffix.isdigit():
                        continue

                all_vals = self._execute_with_retry(cycle_ws.get_all_values)
                rows_to_delete = [
                    idx
                    for idx, raw_row in enumerate(all_vals, start=1)
                    if raw_row and raw_row[0].strip() == target_id
                ]
                for row_num in reversed(rows_to_delete):
                    self._execute_with_retry(cycle_ws.delete_rows, row_num)
                    removed_any = True

            return removed_any

    def add_student_to_active_cycle(
        self,
        group_name: str,
        student_id: str,
        full_name: str,
        year: Optional[int] = None,
        charge_upfront: bool = False,
    ) -> bool:
        """
        Inserts the student right below the header row of the active cycle in
        {group_name}_{year}, initialized as unpaid red (#F4CCCC).
        When `charge_upfront` is True (brand-new student), the student owes this
        cycle from Lesson 1: Qarzdor_Oylar is set to exactly 1 month (stored as
        the cycle title, which counts as 1 and stays dedupe-safe), or incremented
        cumulatively if they already owe earlier months.
        """
        with self._lock:
            target_group = group_name.strip()
            target_id = student_id.strip()
            if not target_group or not target_id:
                return False

            ss = self._get_spreadsheet()
            now_year = year or now_tashkent().year
            ws: Optional[gspread.Worksheet] = None
            cycles: list[dict[str, Any]] = []

            for y in ([year] if year else [now_year, now_year - 1]):
                try:
                    candidate_ws = self._execute_with_retry(
                        ss.worksheet, f"{target_group}_{y}"
                    )
                except gspread.WorksheetNotFound:
                    continue
                parsed = self.parse_cycles_from_sheet(candidate_ws)
                if parsed:
                    ws = candidate_ws
                    cycles = parsed
                    break

            if not ws or not cycles:
                return False

            latest = cycles[-1]
            if any(
                _normalize_student_id_key(r["student_id"])
                == _normalize_student_id_key(target_id)
                for r in latest["student_rows"]
            ):
                if charge_upfront:
                    self._charge_upfront_for_cycle(target_id, latest["title"])
                return True

            insert_row_0 = latest["header_row_idx"] + 1
            tolov_col_idx = latest["tolov_col_idx"]
            num_date_cols = max(0, tolov_col_idx - 2)
            row_data = (
                [target_id, full_name]
                + [""] * num_date_cols
                + ["To'lanmagan"]
            )
            self._execute_with_retry(
                ws.insert_row,
                row_data,
                index=insert_row_0 + 1,
                value_input_option="USER_ENTERED",
            )
            self._execute_with_retry(
                ss.batch_update,
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
                            RED_BG,
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
                },
            )
            if charge_upfront:
                self._charge_upfront_for_cycle(target_id, latest["title"])
            return True

    def get_active_cycle_title(self, group_name: str) -> str:
        with self._lock:
            cycles = self._load_all_group_cycles(group_name)
            return cycles[-1]["title"] if cycles else ""

    def _charge_upfront_for_cycle(self, student_id: str, cycle_title: str) -> bool:
        student = self.get_student_by_id(student_id)
        if not student:
            return False
        current_raw = str(student.get("Qarzdor_Oylar", "")).strip()
        if current_raw in {"", "0", "1"}:
            if current_raw == cycle_title:
                return True
            return self.update_student(student_id, {"Qarzdor_Oylar": cycle_title})
        return self._increment_debt_field(student_id, cycle_title)

    def restore_student_from_reserve(
        self, student_id: str, new_group_name: str
    ) -> dict[str, Any]:
        """
        Restores an inactive ('O'qimayapti') student back to 'O'qiyapti' in the
        target group, adds them to the group's active cycle, and syncs across all sheets.
        """
        with self._lock:
            student = self.get_student_by_id(student_id)
            if not student:
                raise ValueError(f"Student not found: {student_id}")

            grp_obj = self.get_group(new_group_name)
            canonical_group = (
                grp_obj["Guruh_Nomi"].strip()
                if grp_obj
                else new_group_name.strip()
            )
            if not canonical_group:
                raise ValueError("Target group name cannot be empty")

            old_fio = str(student.get("F.I.O.", "")).strip()
            updates = {
                "Status": "O'qiyapti",
                "Guruh": canonical_group,
            }
            self.update_student(student_id, updates)
            # Re-joining the group's running cycle: unpaid red row + upfront
            # month (dedupe-safe by cycle title) so sheet and debt stay in sync.
            self.add_student_to_active_cycle(
                canonical_group, student_id, old_fio, charge_upfront=True
            )
            self.sync_student_across_all_sheets(
                student_id=student_id,
                old_fio=old_fio,
                new_fio=old_fio,
                updated_fields=updates,
            )
            return self.get_student_by_id(student_id) or student

    def remove_student_from_all_group_sheets(
        self, group_name: str, student_id: str, student_fio: str = ""
    ) -> int:
        """
        Deletes the student's rows (matched by normalized Talaba_ID, fallback
        normalized F.I.O. for rows without an ID) from EVERY {Group}_{Year}
        worksheet of `group_name`. Returns the number of deleted rows.
        """
        with self._lock:
            target_id = _normalize_student_id_key(student_id)
            target_fio = _normalize_fio_key(student_fio)
            if not group_name.strip() or not (target_id or target_fio):
                return 0
            removed = 0
            for _, cycle_ws in self._find_group_cycle_worksheets(group_name):
                all_vals = self._execute_with_retry(cycle_ws.get_all_values)
                rows_to_delete: list[int] = []
                for idx, raw_row in enumerate(all_vals, start=1):
                    if not raw_row:
                        continue
                    row_id = _normalize_student_id_key(raw_row[0])
                    row_fio = _normalize_fio_key(raw_row[1]) if len(raw_row) > 1 else ""
                    if row_id in {"TALABA_ID"} or CYCLE_TITLE_RE.match(raw_row[0].strip()):
                        continue
                    if target_id and row_id == target_id:
                        rows_to_delete.append(idx)
                    elif not row_id and target_fio and row_fio == target_fio:
                        rows_to_delete.append(idx)
                for row_num in reversed(rows_to_delete):
                    self._retry_sheets_op(cycle_ws.delete_rows, row_num)
                    removed += 1
            return removed

    def move_student_to_reserve(self, student_id: str) -> dict[str, Any]:
        """
        Moves a student to the reserve group ('Zahira guruhi') when their status
        becomes "O'qimayapti":
        - deletes their rows from the old group's {Group}_{Year} worksheet(s),
        - keeps the row in Baza_Talabalar (all contacts / debts preserved),
        - sets Guruh = 'Zahira guruhi', Sobiq_Guruh = old group, Izoh = note.
        Returns {"student": ..., "old_group": ..., "removed_rows": int}.
        """
        with self._lock:
            student = self.get_student_by_id(student_id)
            if not student:
                raise ValueError(f"Student not found: {student_id}")
            sid = str(student.get("Talaba_ID") or student_id).strip()
            fio = str(student.get("F.I.O.") or "").strip()
            current_group = str(student.get("Guruh") or "").strip()

            old_group = current_group
            zaxira_match = re.match(r"^Zaxira\s*\((.+)\)$", current_group, re.IGNORECASE)
            if zaxira_match:
                old_group = zaxira_match.group(1).strip()
            if old_group.strip().lower() == RESERVE_GROUP_NAME.lower():
                old_group = str(student.get("Sobiq_Guruh") or "").strip()

            removed_rows = 0
            if old_group:
                try:
                    removed_rows = self.remove_student_from_all_group_sheets(
                        old_group, sid, fio
                    )
                except Exception:
                    _sheets_logger.exception(
                        "Failed removing %s from %s cycle sheets", sid, old_group
                    )

            today_str = now_tashkent().strftime("%d.%m.%Y")
            prev_note = str(student.get("Izoh") or "").strip()
            new_note = (
                f"{today_str}: '{old_group}' guruhidan Zahira guruhiga o'tkazildi"
                if old_group
                else f"{today_str}: Zahira guruhiga o'tkazildi"
            )
            if prev_note and new_note not in prev_note:
                new_note = f"{prev_note} | {new_note}"

            updates = {
                "Status": "O'qimayapti",
                "Guruh": RESERVE_GROUP_NAME,
                "Sobiq_Guruh": old_group,
                "Izoh": new_note[-480:],
            }
            self.update_student(sid, updates)
            fresh = self.get_student_by_id(sid) or {**student, **updates}
            return {
                "student": fresh,
                "old_group": old_group,
                "removed_rows": removed_rows,
            }

    # ------------------------------------------------------------------
    # Unpaid cycles (exact lesson dates) for debt notices
    # ------------------------------------------------------------------

    @staticmethod
    def _cycle_title_year_month(title: str) -> tuple[Optional[int], Optional[int]]:
        clean = str(title or "").upper()
        year_m = re.search(r"(\d{4})", clean)
        year_val = int(year_m.group(1)) if year_m else None
        month_val: Optional[int] = None
        for m_idx, m_name in MONTHS_UPPER_LATN.items():
            if m_name in clean:
                month_val = m_idx
                break
        return year_val, month_val

    @classmethod
    def resolve_cycle_dates(cls, cycle: dict[str, Any]) -> list[date]:
        """Converts a cycle's 'dd.mm' headers into full dates (handles Dec→Jan)."""
        title_year, title_month = cls._cycle_title_year_month(cycle.get("title", ""))
        base_year = title_year or now_tashkent().year
        resolved: list[date] = []
        for dc in cycle.get("date_columns", []):
            raw = str(dc.get("date_str", "")).strip()
            m = re.match(r"^(\d{1,2})\.(\d{1,2})", raw)
            if not m:
                continue
            d_val, m_val = int(m.group(1)), int(m.group(2))
            year_val = base_year
            if title_month is not None:
                if title_month >= 11 and m_val <= 2:
                    year_val += 1
                elif title_month <= 2 and m_val >= 11:
                    year_val -= 1
            try:
                resolved.append(date(year_val, m_val, d_val))
            except ValueError:
                continue
        return resolved

    def extract_unpaid_cycles(
        self,
        cycles: list[dict[str, Any]],
        student_id: str,
        student_fio: str = "",
    ) -> list[dict[str, Any]]:
        sid_key = _normalize_student_id_key(student_id)
        fio_key = _normalize_fio_key(student_fio)
        unpaid: list[dict[str, Any]] = []
        for cycle in cycles:
            s_row = None
            if sid_key:
                s_row = next(
                    (
                        r
                        for r in cycle.get("student_rows", [])
                        if _normalize_student_id_key(r.get("student_id")) == sid_key
                    ),
                    None,
                )
            if s_row is None and fio_key:
                s_row = next(
                    (
                        r
                        for r in cycle.get("student_rows", [])
                        if not _normalize_student_id_key(r.get("student_id"))
                        and _normalize_fio_key(r.get("full_name")) == fio_key
                    ),
                    None,
                )
            if s_row is None or _is_paid_status(s_row.get("payment_status", "")):
                continue
            full_dates = self.resolve_cycle_dates(cycle)
            unpaid.append(
                {
                    "title": cycle.get("title", ""),
                    "cycle_number": cycle.get("cycle_number"),
                    "dates": [d.isoformat() for d in full_dates],
                    "date_strs": [
                        str(dc.get("date_str", "")) for dc in cycle.get("date_columns", [])
                    ],
                    "lesson_count": len(cycle.get("date_columns", [])),
                    "payment_status": s_row.get("payment_status", ""),
                }
            )
        return unpaid

    def get_student_unpaid_cycles(
        self, group_name: str, student_id: str, student_fio: str = ""
    ) -> list[dict[str, Any]]:
        with self._lock:
            if not group_name or group_name.strip().lower() == RESERVE_GROUP_NAME.lower():
                return []
            cycles = self._load_all_group_cycles(group_name)
            return self.extract_unpaid_cycles(cycles, student_id, student_fio)

    def get_unpaid_cycles_for_students(
        self, students: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        """Bulk variant with per-group caching (one sheet read per group)."""
        with self._lock:
            cache: dict[str, list[dict[str, Any]]] = {}
            result: dict[str, list[dict[str, Any]]] = {}
            for stu in students:
                sid = str(stu.get("Talaba_ID") or "").strip()
                grp = str(stu.get("Guruh") or "").strip()
                if not sid or not grp or grp.lower() == RESERVE_GROUP_NAME.lower():
                    result[sid] = []
                    continue
                key = grp.lower()
                if key not in cache:
                    try:
                        cache[key] = self._load_all_group_cycles(grp)
                    except Exception:
                        _sheets_logger.exception("Failed loading cycles for %s", grp)
                        cache[key] = []
                result[sid] = self.extract_unpaid_cycles(
                    cache[key], sid, str(stu.get("F.I.O.") or "")
                )
            return result

    # ------------------------------------------------------------------
    # Qiziquvchilar_Lidlar (guest leads)
    # ------------------------------------------------------------------

    def _lead_ws(self) -> tuple[gspread.Worksheet, list[str]]:
        ws = self._get_or_create_worksheet(
            LEAD_SHEET_NAME, headers=LEAD_HEADERS, rows=500, cols=len(LEAD_HEADERS) + 2
        )
        if not getattr(self, "_lead_schema_checked", False):
            self._migrate_lead_schema(ws)
            self._lead_schema_checked = True
        headers = self._ensure_missing_headers(ws, LEAD_HEADERS)
        return ws, headers

    def _migrate_lead_schema(self, ws: gspread.Worksheet) -> None:
        """
        One-time upgrade of an existing Qiziquvchilar_Lidlar tab:
        1. renames legacy headers (Lid_ID -> Lead_ID, ...),
        2. deletes the obsolete 'Til' column (right-to-left, so indexes never
           shift under a column that still has to be removed).
        Columns are always located by header name, never by fixed position.
        """
        try:
            row1 = [
                str(h or "").strip()
                for h in (self._execute_with_retry(ws.row_values, 1) or [])
            ]
            if not row1:
                return
            renamed = False
            for idx, head in enumerate(row1):
                new_name = LEAD_LEGACY_HEADER_RENAMES.get(head)
                if new_name and new_name not in row1:
                    row1[idx] = new_name
                    renamed = True
            if renamed:
                self._execute_with_retry(
                    ws.update, "A1", [row1], value_input_option="USER_ENTERED"
                )
            for idx in range(len(row1) - 1, -1, -1):
                if row1[idx] in LEAD_OBSOLETE_HEADERS:
                    self._execute_with_retry(ws.delete_columns, idx + 1)
                    row1.pop(idx)
            self._ws_cache[ws.title] = (ws, list(row1))
        except Exception:
            _sheets_logger.exception(
                "Could not migrate %s header layout", LEAD_SHEET_NAME
            )

    @staticmethod
    def _parse_lead_number(raw: Any) -> int:
        """'L0007' / '7' / '#7' -> 7; anything else -> 0."""
        m = re.search(r"(\d+)", str(raw or ""))
        return int(m.group(1)) if m else 0

    def get_lead_snapshot(self) -> dict[str, Any]:
        """
        One sheet read describing Qiziquvchilar_Lidlar:
        {"by_chat": {chat_id: {"status", "lead_id"}}, "max_id": int, "count": int}
        Raises on API failure so callers can skip destructive syncing.
        """
        with self._lock:
            ws, headers = self._lead_ws()
            rows = self._retry_sheets_op(ws.get_all_values) or []
            cid_idx = headers.index("Chat_ID") if "Chat_ID" in headers else -1
            holat_idx = headers.index("Holat") if "Holat" in headers else -1
            lid_idx = headers.index("Lead_ID") if "Lead_ID" in headers else -1
            by_chat: dict[str, dict[str, Any]] = {}
            max_id = 0
            count = 0
            for row in rows[1:]:
                if not any(str(c).strip() for c in row):
                    continue
                count += 1
                lead_raw = row[lid_idx].strip() if 0 <= lid_idx < len(row) else ""
                max_id = max(max_id, self._parse_lead_number(lead_raw))
                if cid_idx < 0 or cid_idx >= len(row):
                    continue
                chat = _chat_id_str(row[cid_idx])
                if not chat:
                    continue
                holat = row[holat_idx] if 0 <= holat_idx < len(row) else ""
                status = "contacted" if self._lead_status_is_contacted(holat) else "new"
                prev = by_chat.get(chat)
                if prev is None or (status == "contacted" and prev["status"] != "contacted"):
                    by_chat[chat] = {"status": status, "lead_id": lead_raw}
            return {"by_chat": by_chat, "max_id": max_id, "count": count}

    def _color_lead_status_cell(
        self,
        ws: gspread.Worksheet,
        row_1: int,
        holat_col_0: int,
        color: dict[str, float],
    ) -> None:
        """Paints one Holat cell (429-aware batch, per-cell format fallback)."""
        request = _cell_bg_request(
            ws.id, row_1 - 1, row_1, holat_col_0, holat_col_0 + 1, color
        )
        self._apply_color_requests_with_fallback(
            ws,
            [request],
            fallback_ranges=[(row_1, holat_col_0, holat_col_0, color, None)],
        )

    def append_lead(self, lead: dict[str, Any]) -> bool:
        with self._lock:
            ws, headers = self._lead_ws()
            username = str(lead.get("username") or "").strip().lstrip("@")
            created_local = to_tashkent(lead.get("created_at")) or now_tashkent()
            row_map = {
                "Lead_ID": f"L{int(lead.get('id') or 0):04d}",
                "Sana_Vaqt": created_local.strftime("%d.%m.%Y %H:%M"),
                "F.I.O.": str(lead.get("full_name") or "").strip(),
                "Telefon": str(lead.get("phone") or "").strip(),
                "Tanlangan_Kurs": str(lead.get("course_name") or "").strip(),
                "Telegram_Username": f"@{username}" if username else "",
                "Chat_ID": _chat_id_str(lead.get("telegram_id")),
                "Holat": LEAD_STATUS_NEW,
            }
            new_row = [row_map.get(h, "") for h in headers]
            response = self._retry_sheets_op(
                ws.append_row, new_row, value_input_option="USER_ENTERED"
            )

            row_1 = 0
            try:
                updated_range = str(
                    ((response or {}).get("updates") or {}).get("updatedRange") or ""
                )
                match = re.search(r"![A-Z]+(\d+)", updated_range)
                if match:
                    row_1 = int(match.group(1))
            except Exception:
                row_1 = 0
            if row_1 <= 0:
                row_1 = self._find_lead_row(ws, headers, lead.get("id"), lead.get("telegram_id"))
            if row_1 > 0 and "Holat" in headers:
                try:
                    self._color_lead_status_cell(
                        ws, row_1, headers.index("Holat"), LEAD_COLOR_NEW
                    )
                except Exception:
                    _sheets_logger.exception(
                        "Failed colouring new lead row %s red in %s", row_1, LEAD_SHEET_NAME
                    )
            return True

    def _find_lead_row(
        self,
        ws: gspread.Worksheet,
        headers: list[str],
        lead_id: Any,
        chat_id: Any,
        rows: Optional[list[list[str]]] = None,
    ) -> int:
        """1-based row of the lead (by Lead_ID, then Chat_ID); 0 when absent."""
        if rows is None:
            rows = self._retry_sheets_op(ws.get_all_values) or []
        lid_idx = headers.index("Lead_ID") if "Lead_ID" in headers else -1
        cid_idx = headers.index("Chat_ID") if "Chat_ID" in headers else -1
        want_lid = f"L{int(lead_id):04d}" if str(lead_id or "").isdigit() else ""
        want_cid = _chat_id_str(chat_id)
        if want_lid and lid_idx >= 0:
            for i in range(len(rows) - 1, 0, -1):
                row = rows[i]
                if len(row) > lid_idx and row[lid_idx].strip().upper() == want_lid:
                    return i + 1
        if want_cid and cid_idx >= 0:
            for i in range(len(rows) - 1, 0, -1):
                row = rows[i]
                if len(row) > cid_idx and _chat_id_str(row[cid_idx]) == want_cid:
                    return i + 1
        return 0

    @staticmethod
    def _lead_status_is_contacted(raw: str) -> bool:
        val = (raw or "").strip().lower().replace("\u2018", "'").replace("\u2019", "'")
        return val.startswith("bog") or val.startswith("боғ") or "contacted" in val

    def get_lead_status_by_chat_id(self, chat_id: Any) -> Optional[dict[str, Any]]:
        """
        Looks the account up in Qiziquvchilar_Lidlar by Chat_ID.
        Returns None when no application exists, else
        {"status": "new" | "contacted", "lead_id": "L0001"}.
        """
        want_cid = _chat_id_str(chat_id)
        if not want_cid:
            return None
        with self._lock:
            ws, headers = self._lead_ws()
            rows = self._retry_sheets_op(ws.get_all_values) or []
            if "Chat_ID" not in headers:
                return None
            cid_idx = headers.index("Chat_ID")
            holat_idx = headers.index("Holat") if "Holat" in headers else -1
            lid_idx = headers.index("Lead_ID") if "Lead_ID" in headers else -1
            found: Optional[dict[str, Any]] = None
            for row in rows[1:]:
                if len(row) <= cid_idx or _chat_id_str(row[cid_idx]) != want_cid:
                    continue
                holat = row[holat_idx] if 0 <= holat_idx < len(row) else ""
                status = "contacted" if self._lead_status_is_contacted(holat) else "new"
                lead_id = row[lid_idx].strip() if 0 <= lid_idx < len(row) else ""
                if found is None or status == "contacted":
                    found = {"status": status, "lead_id": lead_id}
                if status == "contacted":
                    break
            return found

    def mark_lead_contacted(self, lead_id: Any, chat_id: Any = None) -> bool:
        """Holat 'Yangi' -> "Bog'lanildi" and red -> green background."""
        with self._lock:
            ws, headers = self._lead_ws()
            if "Holat" not in headers:
                return False
            row_1 = self._find_lead_row(ws, headers, lead_id, chat_id)
            if row_1 <= 0:
                _sheets_logger.warning(
                    "Lead %s / chat %s not found in %s", lead_id, chat_id, LEAD_SHEET_NAME
                )
                return False
            holat_col_0 = headers.index("Holat")
            self._retry_sheets_op(
                ws.update_cell, row_1, holat_col_0 + 1, LEAD_STATUS_CONTACTED
            )
            self._color_lead_status_cell(ws, row_1, holat_col_0, LEAD_COLOR_CONTACTED)
            return True

    # ------------------------------------------------------------------
    # Self-service profile sync
    # ------------------------------------------------------------------

    def update_student_self_profile(
        self,
        chat_id: int | str,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> list[str]:
        """
        Updates F.I.O. / Talaba_Tel on EVERY Baza_Talabalar enrollment row whose
        Talaba_Chat_ID matches, propagating F.I.O. to all {Group}_{Year} sheets.
        """
        with self._lock:
            target = _chat_id_str(chat_id)
            if not target:
                return []
            updated: list[str] = []
            for stu in self.get_all_students():
                if _chat_id_str(stu.get("Talaba_Chat_ID")) != target:
                    continue
                upd: dict[str, Any] = {}
                if full_name is not None and full_name.strip():
                    upd["F.I.O."] = full_name.strip()
                if phone is not None and phone.strip():
                    upd["Talaba_Tel"] = phone.strip()
                if upd and self.update_student(str(stu["Talaba_ID"]), upd):
                    updated.append(str(stu["Talaba_ID"]))
            return updated

    def update_parent_self_profile(
        self,
        chat_id: int | str,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> list[str]:
        """
        Updates the parent's F.I.O. / phone on every child row where the parent's
        chat id is bound (Otasi_* or Onasi_* columns), so siblings stay in sync.
        """
        with self._lock:
            target = _chat_id_str(chat_id)
            if not target:
                return []
            updated: list[str] = []
            for stu in self.get_all_students():
                upd: dict[str, Any] = {}
                is_father = _chat_id_str(stu.get("Otasi_Chat_ID")) == target
                is_mother = _chat_id_str(stu.get("Onasi_Chat_ID")) == target
                is_generic = _chat_id_str(stu.get("OtaOna_Chat_ID")) == target
                if not (is_father or is_mother or is_generic):
                    continue
                prefixes: list[str] = []
                if is_father or (is_generic and not is_mother):
                    prefixes.append("Otasi")
                if is_mother:
                    prefixes.append("Onasi")
                for prefix in prefixes:
                    if full_name is not None and full_name.strip():
                        upd[f"{prefix}_FIO"] = full_name.strip()
                    if phone is not None and phone.strip():
                        upd[f"{prefix}_Tel"] = phone.strip()
                if is_generic and phone is not None and phone.strip():
                    upd["OtaOna_Tel"] = phone.strip()
                if upd and self.update_student(
                    str(stu["Talaba_ID"]), upd, _propagate_parent=False
                ):
                    updated.append(str(stu["Talaba_ID"]))
            return updated

    def switch_parent_role(
        self,
        chat_id: int | str,
        new_type: str,
    ) -> list[str]:
        """
        Switches a parent between 🧔 Otasi and 🧕 Onasi on EVERY linked child.

        For each Baza_Talabalar row where this chat is bound, the three fields
        FIO / Tel / Chat_ID are swapped between the Otasi_* and Onasi_* column
        groups (so whoever previously held the target slot moves to the other one
        and nothing is lost). Rows where the parent already sits in the requested
        slot are left untouched. Returns the student ids that were changed.
        """
        with self._lock:
            target = _chat_id_str(chat_id)
            wanted = "Onasi" if str(new_type).strip().lower() in {"mother", "onasi", "ona"} else "Otasi"
            if not target:
                return []
            # Binds sibling rows that share the parent's phone, so they swap too.
            try:
                self.get_children_by_parent_chat_id(chat_id)
            except Exception:
                _sheets_logger.exception("Sibling binding before role switch failed")
            changed: list[str] = []
            for stu in self.get_all_students():
                is_father = _chat_id_str(stu.get("Otasi_Chat_ID")) == target
                is_mother = _chat_id_str(stu.get("Onasi_Chat_ID")) == target
                if is_father == is_mother:
                    continue
                current = "Otasi" if is_father else "Onasi"
                if current == wanted:
                    continue
                upd: dict[str, Any] = {}
                for suffix in ("FIO", "Tel", "Chat_ID"):
                    upd[f"{current}_{suffix}"] = _normalize_read_value(
                        stu.get(f"{wanted}_{suffix}")
                    )
                    upd[f"{wanted}_{suffix}"] = _normalize_read_value(
                        stu.get(f"{current}_{suffix}")
                    )
                sid = str(stu.get("Talaba_ID") or "").strip()
                if sid and self.update_student(sid, upd, _propagate_parent=False):
                    changed.append(sid)
            self._invalidate_students_cache()
            return changed

    def update_teacher_self_profile(
        self,
        chat_id: int | str,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> bool:
        with self._lock:
            teacher = self.get_teacher_by_chat_id(chat_id)
            if not teacher:
                return False
            upd: dict[str, Any] = {}
            if full_name is not None and full_name.strip():
                upd["F.I.O."] = full_name.strip()
            if phone is not None and phone.strip():
                upd["Telefon"] = phone.strip()
            if not upd:
                return True
            return self.update_teacher(str(teacher.get("Ustoz_ID", "")), upd)

    def remove_student_from_every_cycle_sheet(
        self, student_id: str, student_fio: str = ""
    ) -> int:
        """
        Deletes the student's rows from EVERY {Group}_{Year} cycle worksheet in
        the spreadsheet (current group, former groups, reserve history...).
        Rows are matched by normalized Talaba_ID; rows without an ID fall back to
        the normalized F.I.O. Returns the number of deleted rows.
        """
        with self._lock:
            target_id = _normalize_student_id_key(student_id)
            target_fio = _normalize_fio_key(student_fio)
            if not (target_id or target_fio):
                return 0
            ss = self._get_spreadsheet()
            cycle_sheet_re = re.compile(r"^.+_\d{4}$")
            removed = 0
            for cycle_ws in list(self._execute_with_retry(ss.worksheets)):
                if not cycle_sheet_re.match(cycle_ws.title.strip()):
                    continue
                all_vals = self._execute_with_retry(cycle_ws.get_all_values)
                rows_to_delete: list[int] = []
                for idx, raw_row in enumerate(all_vals, start=1):
                    if not raw_row:
                        continue
                    first_cell = str(raw_row[0]).strip()
                    row_id = _normalize_student_id_key(first_cell)
                    if row_id == "TALABA_ID" or CYCLE_TITLE_RE.match(first_cell):
                        continue
                    row_fio = (
                        _normalize_fio_key(raw_row[1]) if len(raw_row) > 1 else ""
                    )
                    if target_id and row_id == target_id:
                        rows_to_delete.append(idx)
                    elif not row_id and target_fio and row_fio == target_fio:
                        rows_to_delete.append(idx)
                for row_num in reversed(rows_to_delete):
                    self._retry_sheets_op(cycle_ws.delete_rows, row_num)
                    removed += 1
            return removed

    def purge_student_completely(self, student_id: str) -> dict[str, Any]:
        """
        Permanently deletes a student from the whole spreadsheet:
        1. captures Talaba_Chat_ID, Otasi/Onasi chat ids and parent phones FIRST,
        2. deletes the row from every {Group}_{Year} worksheet,
        3. deletes the row from Baza_Talabalar,
        4. checks which parents have NO remaining children in Baza_Talabalar.

        Returns a cleanup payload:
        {
          "deleted": bool,
          "student_id": str,
          "student_name": str,
          "student_chat_id": int | None,
          "student_has_other_enrollments": bool,
          "parent_chat_ids": [int, ...],
          "parent_phones": [str, ...],
          "orphaned_parent_chat_ids": [int, ...],
          "removed_cycle_rows": int,
        }
        """
        with self._lock:
            payload: dict[str, Any] = {
                "deleted": False,
                "student_id": str(student_id or "").strip(),
                "student_name": "",
                "student_chat_id": None,
                "student_has_other_enrollments": False,
                "parent_chat_ids": [],
                "parent_phones": [],
                "orphaned_parent_chat_ids": [],
                "removed_cycle_rows": 0,
            }
            target_id = str(student_id or "").strip()
            if not target_id:
                return payload
            student = self.get_student_by_id(target_id)
            if not student:
                return payload

            real_sid = str(student.get("Talaba_ID") or target_id).strip()
            fio = str(student.get("F.I.O.") or "").strip()
            payload["student_id"] = real_sid
            payload["student_name"] = fio

            # --- 1. Capture contacts BEFORE deleting anything ---------------
            stu_cid = _normalize_chat_id(student.get("Talaba_Chat_ID"))
            payload["student_chat_id"] = stu_cid

            parent_cols = (
                ("Otasi_Chat_ID", "Otasi_Tel"),
                ("Onasi_Chat_ID", "Onasi_Tel"),
                ("OtaOna_Chat_ID", "OtaOna_Tel"),
            )
            parent_chat_ids: list[int] = []
            parent_phone_keys: list[str] = []
            for cid_col, tel_col in parent_cols:
                p_cid = _normalize_chat_id(student.get(cid_col))
                if p_cid is not None and p_cid not in parent_chat_ids:
                    parent_chat_ids.append(p_cid)
                p_key = _normalize_phone_key(student.get(tel_col))
                if p_key and p_key not in parent_phone_keys:
                    parent_phone_keys.append(p_key)
            payload["parent_chat_ids"] = list(parent_chat_ids)
            payload["parent_phones"] = list(parent_phone_keys)

            # --- 2. Delete from all cycle worksheets --------------------------
            try:
                payload["removed_cycle_rows"] = (
                    self.remove_student_from_every_cycle_sheet(real_sid, fio)
                )
            except Exception:
                _sheets_logger.exception(
                    "Failed removing %s from cycle worksheets", real_sid
                )

            # --- 3. Delete from Baza_Talabalar ----------------------------------
            ws = self._get_or_create_worksheet(
                STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
            )
            self._execute_with_retry(ws.delete_rows, int(student["_row_number"]))
            self._invalidate_students_cache()
            payload["deleted"] = True

            # --- 4. Which parents are orphaned? ---------------------------------
            remaining_students = [
                st
                for st in self.get_all_students()
                if _normalize_student_id_key(st.get("Talaba_ID", ""))
                != _normalize_student_id_key(real_sid)
            ]

            if stu_cid is not None:
                payload["student_has_other_enrollments"] = any(
                    _normalize_chat_id(st.get("Talaba_Chat_ID")) == stu_cid
                    for st in remaining_students
                )

            orphaned: list[int] = []
            for p_cid in parent_chat_ids:
                # Phones that belong to THIS parent in the deleted student's row.
                own_phones: set[str] = set()
                for cid_col, tel_col in parent_cols:
                    if _normalize_chat_id(student.get(cid_col)) == p_cid:
                        key = _normalize_phone_key(student.get(tel_col))
                        if key:
                            own_phones.add(key)
                has_other_child = False
                for st in remaining_students:
                    for cid_col, tel_col in parent_cols:
                        if _normalize_chat_id(st.get(cid_col)) == p_cid:
                            has_other_child = True
                            break
                        if own_phones and (
                            _normalize_phone_key(st.get(tel_col)) in own_phones
                        ):
                            has_other_child = True
                            break
                    if has_other_child:
                        break
                if not has_other_child:
                    orphaned.append(p_cid)
            payload["orphaned_parent_chat_ids"] = orphaned
            return payload

    def delete_student(self, student_id: str) -> bool:
        """
        Permanently deletes the exact student_id from Baza_Talabalar and from
        every {Group}_{Year} worksheet — never deleting by Talaba_Chat_ID.
        """
        return bool(self.purge_student_completely(student_id).get("deleted"))

    def transfer_or_enroll_student(
        self,
        student_id: str,
        target_group: str,
        keep_in_old_group: bool,
    ) -> dict[str, Any]:
        """
        Transfers a student to target_group or dual-enrolls them if keep_in_old_group
        is True, preserving all student, father, and mother details.
        """
        with self._lock:
            student = self.get_student_by_id(student_id)
            if not student:
                raise ValueError(f"Student not found: {student_id}")

            old_group = str(student.get("Guruh") or "").strip()
            grp_obj = self.get_group(target_group)
            canonical_target = (
                grp_obj["Guruh_Nomi"].strip() if grp_obj else target_group.strip()
            )

            full_name = str(student.get("F.I.O.") or "").strip()
            student_phone = str(student.get("Talaba_Tel") or "").strip()
            student_tg = str(student.get("Talaba_TG") or "").strip()
            student_chat_id = str(student.get("Talaba_Chat_ID") or "").strip()
            father_name = str(student.get("Otasi_FIO") or "").strip()
            father_phone = str(student.get("Otasi_Tel") or "").strip()
            father_chat_id = str(student.get("Otasi_Chat_ID") or "").strip()
            mother_name = str(student.get("Onasi_FIO") or "").strip()
            mother_phone = str(student.get("Onasi_Tel") or "").strip()
            mother_chat_id = str(student.get("Onasi_Chat_ID") or "").strip()
            parent_phone = str(student.get("OtaOna_Tel") or "").strip()
            parent_chat_id = str(student.get("OtaOna_Chat_ID") or "").strip()
            status = str(student.get("Status") or "").strip() or "O'qiyapti"
            if keep_in_old_group:
                new_student = self.add_student(
                    full_name=full_name,
                    group_name=canonical_target,
                    student_phone=student_phone,
                    student_tg=student_tg,
                    parent_phone=parent_phone,
                    status=status,
                    student_chat_id=student_chat_id,
                    father_name=father_name,
                    father_phone=father_phone,
                    father_chat_id=father_chat_id,
                    mother_name=mother_name,
                    mother_phone=mother_phone,
                    mother_chat_id=mother_chat_id,
                    # New enrollment row: owes its own first month upfront
                    # (the old group's debt stays on the old row only).
                    debt_months=None if status == "O'qiyapti" else "0",
                )
                new_id = new_student["Talaba_ID"]
                if parent_chat_id:
                    self.update_student(new_id, {"OtaOna_Chat_ID": parent_chat_id})
                    new_student = self.get_student_by_id(new_id) or new_student

                self.add_student_to_active_cycle(
                    canonical_target,
                    new_id,
                    full_name,
                    charge_upfront=(status == "O'qiyapti"),
                )
                new_student = self.get_student_by_id(new_id) or new_student
                return {
                    "mode": "dual_enroll",
                    "old_group": old_group,
                    "new_group": canonical_target,
                    "old_student_id": student_id,
                    "new_student_id": new_id,
                    "student": new_student,
                }

            if old_group:
                self.remove_student_from_cycle_sheet(old_group, student_id)

            self.update_student(student_id, {"Guruh": canonical_target})
            self.add_student_to_active_cycle(
                canonical_target, student_id, full_name
            )
            updated_student = self.get_student_by_id(student_id) or student
            return {
                "mode": "transfer",
                "old_group": old_group,
                "new_group": canonical_target,
                "old_student_id": student_id,
                "new_student_id": student_id,
                "student": updated_student,
            }

    def link_student_chat_id(
        self,
        student_id: str,
        chat_id: int | str,
        is_parent: bool = False,
        telegram_username: Optional[str] = None,
        parent_type: Optional[str] = None,
        parent_name: Optional[str] = None,
        parent_phone: Optional[str] = None,
    ) -> bool:
        updates: dict[str, Any] = {}
        norm_cid = _normalize_chat_id(chat_id)
        clean_chat_id = str(norm_cid) if norm_cid is not None else _normalize_read_value(chat_id)
        if not clean_chat_id:
            return False

        if is_parent:
            p_type = (parent_type or "").strip().lower()
            if p_type in {"father", "otasi", "ota"}:
                updates["Otasi_Chat_ID"] = clean_chat_id
                if parent_name is not None:
                    updates["Otasi_FIO"] = _normalize_read_value(parent_name)
                if parent_phone is not None:
                    updates["Otasi_Tel"] = _normalize_read_value(parent_phone)
            elif p_type in {"mother", "onasi", "ona"}:
                updates["Onasi_Chat_ID"] = clean_chat_id
                if parent_name is not None:
                    updates["Onasi_FIO"] = _normalize_read_value(parent_name)
                if parent_phone is not None:
                    updates["Onasi_Tel"] = _normalize_read_value(parent_phone)
            else:
                updates["OtaOna_Chat_ID"] = clean_chat_id
                updates["Otasi_Chat_ID"] = clean_chat_id
                if parent_name is not None:
                    updates["Otasi_FIO"] = _normalize_read_value(parent_name)
                if parent_phone is not None:
                    clean_p_phone = _normalize_read_value(parent_phone)
                    updates["OtaOna_Tel"] = clean_p_phone
                    updates["Otasi_Tel"] = clean_p_phone
        else:
            updates["Talaba_Chat_ID"] = clean_chat_id
            if telegram_username is not None:
                cleaned_tg = _normalize_read_value(telegram_username)
                if cleaned_tg:
                    updates["Talaba_TG"] = (
                        cleaned_tg
                        if cleaned_tg.startswith("@")
                        else f"@{cleaned_tg}"
                    )
                else:
                    updates["Talaba_TG"] = ""
        return self.update_student(student_id, updates)

    def bind_parent_to_students(
        self,
        student_ids: str | list[str] | tuple[str, ...] | set[str],
        parent_chat_id: int | str,
        parent_type: Optional[str] = None,
        parent_name: Optional[str] = None,
        parent_phone: Optional[str] = None,
    ) -> list[str]:
        """
        Safely binds a parent's chat_id (Otasi_Chat_ID / Onasi_Chat_ID) to one
        or multiple student_id records in Baza_Talabalar using a single read and
        a single batch_update write. Works cleanly even when the student has NO
        phone ('Yo'q' or empty) and NO Talaba_Chat_ID yet.
        Returns the list of student_ids that were successfully linked.
        """
        with self._lock:
            norm_cid = _normalize_chat_id(parent_chat_id)
            clean_chat_id = (
                str(norm_cid)
                if norm_cid is not None
                else _normalize_read_value(parent_chat_id)
            )
            if not clean_chat_id:
                return []

            if isinstance(student_ids, str):
                raw_ids = [
                    part.strip()
                    for part in re.split(r"[,;\s]+", student_ids.strip())
                    if part.strip()
                ]
            else:
                raw_ids = [
                    _normalize_read_value(sid)
                    for sid in student_ids
                    if _normalize_read_value(sid)
                ]

            ordered_sids: list[str] = []
            seen_sids: set[str] = set()
            for sid in raw_ids:
                if sid not in seen_sids:
                    seen_sids.add(sid)
                    ordered_sids.append(sid)

            if not ordered_sids:
                return []

            ws = self._get_or_create_worksheet(
                STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
            )
            rows = self._execute_with_retry(ws.get_all_values)
            if rows:
                self._ws_cache[ws.title] = (ws, list(rows[0]))
            headers = self._ensure_missing_headers(ws, STUDENT_HEADERS)
            _, all_students = self._parse_students_from_rows(rows)
            self._students_cache = (_time.monotonic(), all_students)

            students_by_id = {
                str(s.get("Talaba_ID", "")).strip(): s for s in all_students
            }

            p_type = (parent_type or "").strip().lower()
            target_updates: dict[str, Any] = {}
            if p_type in {"father", "otasi", "ota"}:
                target_updates["Otasi_Chat_ID"] = clean_chat_id
                if parent_name is not None:
                    target_updates["Otasi_FIO"] = _normalize_read_value(parent_name)
                if parent_phone is not None:
                    target_updates["Otasi_Tel"] = _normalize_read_value(parent_phone)
            elif p_type in {"mother", "onasi", "ona"}:
                target_updates["Onasi_Chat_ID"] = clean_chat_id
                if parent_name is not None:
                    target_updates["Onasi_FIO"] = _normalize_read_value(parent_name)
                if parent_phone is not None:
                    target_updates["Onasi_Tel"] = _normalize_read_value(parent_phone)
            else:
                target_updates["OtaOna_Chat_ID"] = clean_chat_id
                target_updates["Otasi_Chat_ID"] = clean_chat_id
                if parent_name is not None:
                    target_updates["Otasi_FIO"] = _normalize_read_value(parent_name)
                if parent_phone is not None:
                    clean_p_phone = _normalize_read_value(parent_phone)
                    target_updates["OtaOna_Tel"] = clean_p_phone
                    target_updates["Otasi_Tel"] = clean_p_phone

            bound_ids: list[str] = []
            row_updates_by_sid: dict[str, dict[str, Any]] = {}

            for sid in ordered_sids:
                if sid in students_by_id:
                    bound_ids.append(sid)
                    row_updates_by_sid[sid] = dict(target_updates)

            if not bound_ids:
                return []

            father_cid = _normalize_chat_id(target_updates.get("Otasi_Chat_ID"))
            mother_cid = _normalize_chat_id(target_updates.get("Onasi_Chat_ID"))
            generic_parent_cid = _normalize_chat_id(
                target_updates.get("OtaOna_Chat_ID")
            )

            for sid in bound_ids:
                src_student = students_by_id[sid]

                def _merged(col: str, _src: dict[str, Any] = src_student) -> str:
                    if col in target_updates and target_updates[col] is not None:
                        return _normalize_read_value(target_updates[col])
                    return _normalize_read_value(_src.get(col))

                src_father_tel = _normalize_phone_key(_merged("Otasi_Tel"))
                src_mother_tel = _normalize_phone_key(_merged("Onasi_Tel"))
                src_generic_tel = _normalize_phone_key(_merged("OtaOna_Tel"))
                src_parent_id = _merged("parent_id") or _merged("Parent_ID")
                all_src_phones = {
                    p for p in (src_father_tel, src_mother_tel, src_generic_tel) if p
                }
                if not all_src_phones and not src_parent_id:
                    continue

                for other in all_students:
                    other_sid = str(other.get("Talaba_ID", "")).strip()
                    if not other_sid or other_sid in row_updates_by_sid:
                        continue

                    oth_father_tel = _normalize_phone_key(other.get("Otasi_Tel"))
                    oth_mother_tel = _normalize_phone_key(other.get("Onasi_Tel"))
                    oth_generic_tel = _normalize_phone_key(other.get("OtaOna_Tel"))
                    oth_parent_id = _normalize_read_value(
                        other.get("parent_id") or other.get("Parent_ID")
                    )
                    all_oth_phones = {
                        p
                        for p in (oth_father_tel, oth_mother_tel, oth_generic_tel)
                        if p
                    }

                    same_parent_id = bool(
                        src_parent_id and oth_parent_id == src_parent_id
                    )
                    shares_any_phone = bool(all_src_phones & all_oth_phones)
                    if not (same_parent_id or shares_any_phone):
                        continue

                    sib_upd: dict[str, Any] = {}
                    if father_cid is not None:
                        f_src = {p for p in (src_father_tel, src_generic_tel) if p}
                        f_oth = {p for p in (oth_father_tel, oth_generic_tel) if p}
                        if same_parent_id or bool(f_src & f_oth) or shares_any_phone:
                            if (
                                _normalize_chat_id(other.get("Otasi_Chat_ID"))
                                != father_cid
                            ):
                                sib_upd["Otasi_Chat_ID"] = str(father_cid)

                    if mother_cid is not None:
                        m_src = {p for p in (src_mother_tel, src_generic_tel) if p}
                        m_oth = {p for p in (oth_mother_tel, oth_generic_tel) if p}
                        if same_parent_id or bool(m_src & m_oth) or shares_any_phone:
                            if (
                                _normalize_chat_id(other.get("Onasi_Chat_ID"))
                                != mother_cid
                            ):
                                sib_upd["Onasi_Chat_ID"] = str(mother_cid)

                    if generic_parent_cid is not None:
                        if (
                            _normalize_chat_id(other.get("OtaOna_Chat_ID"))
                            != generic_parent_cid
                        ):
                            sib_upd["OtaOna_Chat_ID"] = str(generic_parent_cid)

                    if sib_upd:
                        row_updates_by_sid[other_sid] = sib_upd

            batch_value_updates: list[dict[str, Any]] = []
            bg_requests: list[dict[str, Any]] = []

            for sid, col_updates in row_updates_by_sid.items():
                stu = students_by_id.get(sid)
                if not stu:
                    continue
                row_num = int(stu["_row_number"])
                for col_name, raw_val in col_updates.items():
                    if col_name not in headers:
                        continue
                    col_idx = headers.index(col_name)
                    val_str = "" if raw_val is None else str(raw_val).strip()
                    cell_val = val_str if val_str else MISSING_TEXT
                    cell_bg = WHITE_BG if val_str else YELLOW_BG
                    batch_value_updates.append(
                        {
                            "range": f"{_col_letter(col_idx)}{row_num}",
                            "values": [[cell_val]],
                        }
                    )
                    bg_requests.append(
                        _cell_bg_request(
                            ws.id,
                            row_num - 1,
                            row_num,
                            col_idx,
                            col_idx + 1,
                            cell_bg,
                        )
                    )

            if batch_value_updates:
                self._execute_with_retry(
                    ws.batch_update,
                    batch_value_updates,
                    value_input_option="USER_ENTERED",
                )
            if bg_requests:
                ss = self._get_spreadsheet()
                self._execute_with_retry(ss.batch_update, {"requests": bg_requests})

            self._invalidate_students_cache()
            return bound_ids

    def attach_student_device_info(
        self,
        student_id: str,
        new_phone: Optional[str] = None,
        student_chat_id: Optional[int | str] = None,
        telegram_username: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """
        Finds an existing student row by Talaba_ID in Baza_Talabalar, updates
        Talaba_Tel (if new_phone is provided) and/or Talaba_Chat_ID (when the
        student clicks ?start=stu_{student_id}), and syncs across all sheets via
        sync_student_across_all_sheets without creating any duplicate student row.
        """
        with self._lock:
            clean_sid = _normalize_read_value(student_id)
            if not clean_sid:
                return None
            student = self.get_student_by_id(clean_sid)
            if not student:
                return None

            updates: dict[str, Any] = {}
            if new_phone is not None:
                clean_phone = _normalize_read_value(new_phone)
                if clean_phone:
                    if clean_phone.lower() in {"yo'q", "yoq", "йўқ"}:
                        clean_phone = "Yo'q"
                    updates["Talaba_Tel"] = clean_phone

            if student_chat_id is not None:
                norm_cid = _normalize_chat_id(student_chat_id)
                clean_cid = (
                    str(norm_cid)
                    if norm_cid is not None
                    else _normalize_read_value(student_chat_id)
                )
                if clean_cid:
                    updates["Talaba_Chat_ID"] = clean_cid

            if telegram_username is not None:
                clean_tg = _normalize_read_value(telegram_username)
                if clean_tg:
                    updates["Talaba_TG"] = (
                        clean_tg if clean_tg.startswith("@") else f"@{clean_tg}"
                    )

            if updates:
                self.update_student(clean_sid, updates)
                return self.get_student_by_id(clean_sid) or student
            return student

    def _increment_debt_field(
        self, student_id: str, cycle_title: Optional[str] = None
    ) -> bool:
        with self._lock:
            student = self.get_student_by_id(student_id)
            if not student:
                return False
            current_raw = str(student.get("Qarzdor_Oylar", "")).strip()
            if not current_raw or current_raw == "0":
                new_val = cycle_title.strip() if cycle_title else "1"
            elif current_raw.isdigit():
                new_val = str(int(current_raw) + 1)
            else:
                items = [
                    x.strip()
                    for x in current_raw.split(";")
                    if x.strip() and x.strip() != "0"
                ]
                if cycle_title and cycle_title.strip() not in items:
                    items.append(cycle_title.strip())
                new_val = "; ".join(items) if items else "1"
            if new_val == current_raw:
                return True
            return self.update_student(student_id, {"Qarzdor_Oylar": new_val})

    def _decrement_debt_field(
        self, student_id: str, cycle_title: Optional[str] = None
    ) -> bool:
        with self._lock:
            student = self.get_student_by_id(student_id)
            if not student:
                return False
            current_raw = str(student.get("Qarzdor_Oylar", "")).strip()
            if not current_raw or current_raw == "0":
                new_val = "0"
            elif current_raw.isdigit():
                new_val = str(max(0, int(current_raw) - 1))
            else:
                items = [
                    x.strip()
                    for x in current_raw.split(";")
                    if x.strip() and x.strip() != "0"
                ]
                if cycle_title:
                    items = [x for x in items if x != cycle_title.strip()]
                elif items:
                    items.pop(0)
                new_val = "; ".join(items) if items else "0"
            return self.update_student(student_id, {"Qarzdor_Oylar": new_val})

    def add_debt_cycle(self, student_id: str, cycle_title: str) -> bool:
        return self._increment_debt_field(student_id, cycle_title)

    def remove_debt_cycle(self, student_id: str, cycle_title: str) -> bool:
        return self._decrement_debt_field(student_id, cycle_title)

    def _load_all_group_cycles(self, group_name: str) -> list[dict[str, Any]]:
        clean_group = group_name.strip()
        if not clean_group:
            return []
        zaxira_match = re.match(r"^Zaxira\s*\((.+)\)$", clean_group, re.IGNORECASE)
        candidate_names = [clean_group]
        if zaxira_match:
            inner = zaxira_match.group(1).strip()
            if inner and inner not in candidate_names:
                candidate_names.append(inner)

        ss = self._get_spreadsheet()
        now_year = now_tashkent().year
        years_to_check = [now_year - 1, now_year, now_year + 1]
        collected_cycles: list[dict[str, Any]] = []

        for g_name in candidate_names:
            for y in years_to_check:
                sheet_title = f"{g_name}_{y}"
                try:
                    ws = self._execute_with_retry(ss.worksheet, sheet_title)
                except gspread.WorksheetNotFound:
                    continue
                parsed = self.parse_cycles_from_sheet(ws)
                if parsed:
                    collected_cycles.extend(parsed)
            if collected_cycles:
                break

        return collected_cycles

    def _extract_student_cycle_lesson_stats(
        self,
        cycles: list[dict[str, Any]],
        student_id: str,
        student_fio: str = "",
    ) -> dict[str, Any]:
        if not cycles:
            return {
                "total_held_lessons": 0,
                "attended_lessons": 0,
                "missed_lessons": 0,
                "cycle_title": "",
            }

        clean_sid = (student_id or "").strip()
        clean_fio = (student_fio or "").strip().lower()

        matched_cycles: list[tuple[dict[str, Any], dict[str, Any], int]] = []
        for cycle in cycles:
            student_row = None
            if clean_sid:
                student_row = next(
                    (
                        s
                        for s in cycle["student_rows"]
                        if s["student_id"].strip() == clean_sid
                    ),
                    None,
                )
            if student_row is None and clean_fio:
                student_row = next(
                    (
                        s
                        for s in cycle["student_rows"]
                        if s["full_name"].strip().lower() == clean_fio
                    ),
                    None,
                )
            if student_row is None:
                continue

            held_count = 0
            for dc in cycle["date_columns"]:
                c_idx = dc["col_idx"]
                if any(
                    _is_recorded_mark(row["marks"].get(c_idx, ""))
                    for row in cycle["student_rows"]
                ):
                    held_count += 1

            matched_cycles.append((cycle, student_row, held_count))

        if not matched_cycles:
            return {
                "total_held_lessons": 0,
                "attended_lessons": 0,
                "missed_lessons": 0,
                "cycle_title": "",
            }

        unpaid_matches = [
            item
            for item in matched_cycles
            if not _is_paid_status(item[1].get("payment_status", ""))
        ]
        if unpaid_matches:
            unpaid_with_held = [item for item in unpaid_matches if item[2] > 0]
            target_cycle, target_s_row, total_held = (
                unpaid_with_held[-1] if unpaid_with_held else unpaid_matches[-1]
            )
        else:
            target_cycle, target_s_row, total_held = matched_cycles[-1]

        attended = 0
        missed = 0
        for dc in target_cycle["date_columns"]:
            c_idx = dc["col_idx"]
            mark = target_s_row["marks"].get(c_idx, "")
            if _is_present_mark(mark):
                attended += 1
            elif _is_absent_mark(mark):
                missed += 1

        return {
            "total_held_lessons": total_held,
            "attended_lessons": attended,
            "missed_lessons": missed,
            "cycle_title": target_cycle["title"],
        }

    def get_student_cycle_lesson_stats(
        self,
        group_name: str,
        student_id: str,
        student_fio: str = "",
    ) -> dict[str, Any]:
        """
        Inspects the active/unpaid {Group}_{Year} cycle sheet for that group and
        counts:
        - total_held_lessons: lesson date columns with recorded attendance
        - attended_lessons: ✅ / Keldi count for that student
        - missed_lessons: ❌ / Kelmadi / Yo'q count for that student
        """
        with self._lock:
            cycles = self._load_all_group_cycles(group_name)
            return self._extract_student_cycle_lesson_stats(
                cycles=cycles,
                student_id=student_id,
                student_fio=student_fio,
            )

    def get_debtors(self, group_name: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            students = self.get_all_students(group_name=group_name)
            debtors: list[dict[str, Any]] = []
            cycles_cache: dict[str, list[dict[str, Any]]] = {}

            for s in students:
                debt_val = s.get("Qarzdor_Oylar", "").strip()
                if debt_val and debt_val != "0":
                    stu_group = str(s.get("Guruh", "")).strip()
                    cache_key = stu_group.lower()
                    if cache_key not in cycles_cache:
                        cycles_cache[cache_key] = self._load_all_group_cycles(stu_group)
                    stats = self._extract_student_cycle_lesson_stats(
                        cycles=cycles_cache[cache_key],
                        student_id=str(s.get("Talaba_ID", "")).strip(),
                        student_fio=str(s.get("F.I.O.", "")).strip(),
                    )
                    enriched = dict(s)
                    enriched["total_held_lessons"] = stats["total_held_lessons"]
                    enriched["attended_lessons"] = stats["attended_lessons"]
                    enriched["missed_lessons"] = stats["missed_lessons"]
                    if stats["cycle_title"]:
                        enriched["cycle_title"] = stats["cycle_title"]
                    debtors.append(enriched)
            return debtors

    # ------------------------------------------------------------------
    # CRUD: Ustozlar
    # ------------------------------------------------------------------

    def get_all_teachers(self, active_only: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            ws = self._get_or_create_worksheet(
                TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=100, cols=10
            )
            rows = self._execute_with_retry(ws.get_all_values)
            if len(rows) <= 1:
                return []
            headers = rows[0]
            self._ws_cache[ws.title] = (ws, list(headers))
            teachers: list[dict[str, Any]] = []
            for idx, raw_row in enumerate(rows[1:], start=2):
                padded = raw_row + [""] * (len(headers) - len(raw_row))
                record: dict[str, Any] = {
                    h: _normalize_read_value(v) for h, v in zip(headers, padded)
                }
                for h in TEACHER_HEADERS:
                    record.setdefault(h, "")
                for cid_col in ("Chat_ID", "Ustoz_Chat_ID"):
                    if cid_col in record and record.get(cid_col):
                        record[cid_col] = (
                            _chat_id_str(record[cid_col]) or record[cid_col]
                        )
                record["_row_number"] = idx
                if not record.get("Ustoz_ID"):
                    continue
                if active_only and record.get("Status", "").strip().lower() in {
                    "arxiv",
                    "noaktiv",
                    "o'chirilgan",
                }:
                    continue
                teachers.append(record)
            return teachers

    def get_all_teachers_detailed(self) -> list[dict[str, Any]]:
        """
        Returns all registered teachers from Ustozlar (filtering out uncompleted
        pending rows where F.I.O. is 'Ma'lumot kiritilmagan'), enriched with
        'assigned_groups' from Guruhlar matching Ustoz_ID or Ustoz_Chat_ID.
        """
        with self._lock:
            teachers = self.get_all_teachers()
            groups = self.get_all_groups()
            detailed: list[dict[str, Any]] = []

            for teacher in teachers:
                full_name = str(teacher.get("F.I.O.", "")).strip()
                if not full_name or full_name == MISSING_TEXT:
                    continue

                t_id = str(teacher.get("Ustoz_ID", "")).strip()
                t_chat_id = str(
                    teacher.get("Chat_ID") or teacher.get("Ustoz_Chat_ID") or ""
                ).strip()

                assigned_groups: list[str] = []
                for grp in groups:
                    g_tid = str(grp.get("Ustoz_ID", "")).strip()
                    g_cid = str(grp.get("Ustoz_Chat_ID", "")).strip()
                    g_name = str(grp.get("Guruh_Nomi", "")).strip()
                    if not g_name:
                        continue
                    if (t_id and g_tid == t_id) or (t_chat_id and g_cid == t_chat_id):
                        assigned_groups.append(g_name)

                enriched = dict(teacher)
                enriched["assigned_groups"] = assigned_groups
                detailed.append(enriched)

            return detailed

    def get_teacher_by_id(self, teacher_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            target = _normalize_read_value(teacher_id)
            if not target:
                return None
            for teacher in self.get_all_teachers():
                if teacher.get("Ustoz_ID", "").strip() == target:
                    return teacher
            return None

    def get_teacher_by_chat_id(
        self, chat_id: int | str
    ) -> Optional[dict[str, Any]]:
        with self._lock:
            target = _chat_id_str(chat_id) or _normalize_read_value(chat_id)
            if not target:
                return None
            for teacher in self.get_all_teachers():
                if (
                    str(teacher.get("Chat_ID", "")).strip() == target
                    or str(teacher.get("Ustoz_Chat_ID", "")).strip() == target
                ):
                    return teacher
            return None

    def get_teacher(self, teacher_id_or_chat_id: str | int) -> Optional[dict[str, Any]]:
        with self._lock:
            return self.get_teacher_by_id(str(teacher_id_or_chat_id)) or self.get_teacher_by_chat_id(
                teacher_id_or_chat_id
            )

    def _generate_next_teacher_id(
        self, existing_teachers: list[dict[str, Any]], prefix: str = "TCH"
    ) -> str:
        max_num = 0
        pattern = re.compile(r"^(?:TCH|UST)(\d+)$", re.IGNORECASE)
        for t in existing_teachers:
            tid = t.get("Ustoz_ID", "").strip()
            m = pattern.match(tid)
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"{prefix}{max_num + 1:03d}"

    def add_teacher(
        self,
        full_name: str = "",
        phone: str = "",
        tg_username: str = "",
        chat_id: int | str = "",
        status: str = "Faol",
        teacher_id: str = "",
    ) -> dict[str, Any]:
        with self._lock:
            ws = self._get_or_create_worksheet(
                TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=100, cols=10
            )
            headers = self._cleanup_teacher_sheet_headers(ws)
            existing = self.get_all_teachers()
            resolved_id = _normalize_read_value(teacher_id) or self._generate_next_teacher_id(existing)
            already = self.get_teacher_by_id(resolved_id)
            if already:
                return already

            tg_val = _normalize_read_value(tg_username)
            if tg_val and not tg_val.startswith("@"):
                tg_val = f"@{tg_val}"

            row_map = {
                "Ustoz_ID": resolved_id,
                "F.I.O.": _normalize_read_value(full_name),
                "Telefon": _normalize_read_value(phone),
                "TG_Username": tg_val,
                "Chat_ID": _normalize_read_value(chat_id),
                "Ustoz_Chat_ID": _normalize_read_value(chat_id),
                "Status": _normalize_read_value(status),
            }
            new_row = [row_map.get(h, "") for h in headers]
            new_row_idx = self._append_row_and_get_index(ws, new_row)
            self._sync_row_missing_cells(
                ws, new_row_idx, new_row, exclude_cols={"Guruhlar"}
            )
            return self.get_teacher_by_id(resolved_id) or {
                h: _normalize_read_value(row_map.get(h, "")) for h in headers
            }

    def update_teacher(self, teacher_id: str, updates: dict[str, Any]) -> bool:
        with self._lock:
            ws = self._get_or_create_worksheet(
                TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=100, cols=10
            )
            headers = self._cleanup_teacher_sheet_headers(ws)
            teacher = self.get_teacher_by_id(teacher_id)
            if not teacher:
                return False
            row_num = teacher["_row_number"]
            raw_row = self._execute_with_retry(ws.row_values, row_num)
            row_values = raw_row + [""] * (len(headers) - len(raw_row))
            for key, value in updates.items():
                if key in headers:
                    col_idx = headers.index(key)
                    row_values[col_idx] = "" if value is None else str(value)
            self._sync_row_missing_cells(
                ws, row_num, row_values, exclude_cols={"Guruhlar"}
            )
            return True

    def link_teacher_chat_id(
        self,
        teacher_id: str,
        chat_id: int | str,
        telegram_username: Optional[str] = None,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> bool:
        updates: dict[str, Any] = {
            "Chat_ID": str(chat_id),
            "Ustoz_Chat_ID": str(chat_id),
        }
        if telegram_username is not None:
            cleaned_tg = _normalize_read_value(telegram_username)
            if cleaned_tg:
                tg_fmt = cleaned_tg if cleaned_tg.startswith("@") else f"@{cleaned_tg}"
                updates["TG_Username"] = tg_fmt
            else:
                updates["TG_Username"] = ""
        if full_name is not None:
            updates["F.I.O."] = full_name
        if phone is not None:
            updates["Telefon"] = phone
        return self.update_teacher(teacher_id, updates)

    def register_teacher_and_assign_group(
        self,
        teacher_data: dict[str, Any],
        target_group_name: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Single-step atomic teacher registration across both Ustozlar and Guruhlar.
        Only writes to Ustozlar when the teacher completes registration via invite
        link (no premature placeholder rows). Cleans up any duplicate 'Telegram'
        column so only 'TG_Username' exists.
        """
        with self._lock:
            ws_teachers = self._get_or_create_worksheet(
                TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=100, cols=10
            )
            headers = self._cleanup_teacher_sheet_headers(ws_teachers)

            chat_id = _normalize_read_value(
                teacher_data.get("chat_id")
                or teacher_data.get("Chat_ID")
                or teacher_data.get("telegram_id")
            )
            full_name = _normalize_read_value(
                teacher_data.get("full_name") or teacher_data.get("F.I.O.")
            )
            phone = _normalize_read_value(
                teacher_data.get("phone") or teacher_data.get("Telefon")
            )
            raw_tg = _normalize_read_value(
                teacher_data.get("tg_username")
                or teacher_data.get("TG_Username")
                or teacher_data.get("username")
                or teacher_data.get("Telegram")
            )
            tg_val = (
                raw_tg
                if not raw_tg or raw_tg.startswith("@")
                else f"@{raw_tg}"
            )
            status = (
                _normalize_read_value(
                    teacher_data.get("status") or teacher_data.get("Status")
                )
                or "Faol"
            )
            invite_code = _normalize_read_value(teacher_data.get("invite_code"))

            existing_teachers = self.get_all_teachers()
            existing_by_chat = (
                self.get_teacher_by_chat_id(chat_id) if chat_id else None
            )

            if existing_by_chat:
                ustoz_id = str(existing_by_chat.get("Ustoz_ID", "")).strip()
                if not ustoz_id or (invite_code and ustoz_id == invite_code):
                    ustoz_id = self._generate_next_teacher_id(
                        existing_teachers, prefix="TCH"
                    )
                target_row_num: Optional[int] = int(existing_by_chat["_row_number"])
                existing_groups_str = str(
                    existing_by_chat.get("Guruhlar", "")
                ).strip()
            else:
                ustoz_id = self._generate_next_teacher_id(
                    existing_teachers, prefix="TCH"
                )
                target_row_num = None
                existing_groups_str = ""

            assigned_group: Optional[str] = None
            if target_group_name and target_group_name.strip():
                group = self.get_group(target_group_name.strip())
                if group:
                    canonical_group = group["Guruh_Nomi"].strip()
                    self.update_group(
                        canonical_group,
                        {
                            "Ustoz_ID": ustoz_id,
                            "Ustoz_Chat_ID": chat_id,
                        },
                    )
                    ws_groups = self._get_or_create_worksheet(
                        GROUP_SHEET_NAME, headers=GROUP_HEADERS, rows=100, cols=12
                    )
                    grp_headers = self._ensure_missing_headers(
                        ws_groups, GROUP_HEADERS
                    )
                    updated_group = self.get_group(canonical_group) or group
                    grp_row_num = updated_group["_row_number"]
                    bg_requests: list[dict[str, Any]] = []
                    for col_name in ("Ustoz_ID", "Ustoz_Chat_ID"):
                        if col_name in grp_headers:
                            c_idx = grp_headers.index(col_name)
                            bg_requests.append(
                                _cell_bg_request(
                                    ws_groups.id,
                                    grp_row_num - 1,
                                    grp_row_num,
                                    c_idx,
                                    c_idx + 1,
                                    WHITE_BG,
                                )
                            )
                    if bg_requests:
                        self._execute_with_retry(
                            self._get_spreadsheet().batch_update,
                            {"requests": bg_requests},
                        )
                    assigned_group = canonical_group

            group_names_list = [
                g.get("Guruh_Nomi", "").strip()
                for g in self.get_all_groups()
                if (
                    str(g.get("Ustoz_ID", "")).strip() == ustoz_id
                    or (chat_id and str(g.get("Ustoz_Chat_ID", "")).strip() == chat_id)
                )
                and g.get("Guruh_Nomi", "").strip()
            ]
            if assigned_group and assigned_group not in group_names_list:
                group_names_list.append(assigned_group)
            groups_joined = ", ".join(group_names_list) or existing_groups_str

            row_map = {
                "Ustoz_ID": ustoz_id,
                "F.I.O.": full_name,
                "Telefon": phone,
                "TG_Username": tg_val,
                "Chat_ID": chat_id,
                "Ustoz_Chat_ID": chat_id,
                "Guruhlar": groups_joined,
                "Status": status,
            }
            row_values = [row_map.get(h, "") for h in headers]

            if target_row_num is not None:
                self._sync_row_missing_cells(
                    ws_teachers,
                    target_row_num,
                    row_values,
                    exclude_cols={"Guruhlar"},
                )
            else:
                new_row_idx = self._append_row_and_get_index(
                    ws_teachers, row_values
                )
                self._sync_row_missing_cells(
                    ws_teachers,
                    new_row_idx,
                    row_values,
                    exclude_cols={"Guruhlar"},
                )

            return {
                "ustoz_id": ustoz_id,
                "group_assigned": assigned_group,
            }

    def assign_teacher_to_group(
        self, teacher_id: str, group_name: str
    ) -> dict[str, Any]:
        """
        Updates Guruhlar row for group_name with the teacher's Ustoz_ID and Chat_ID,
        resets those cells' background to white (#FFFFFF), and returns the updated
        group and teacher dicts.
        """
        with self._lock:
            teacher = self.get_teacher(teacher_id)
            if not teacher:
                raise ValueError(f"Teacher not found: {teacher_id}")

            group = self.get_group(group_name)
            if not group:
                raise ValueError(f"Group not found: {group_name}")

            t_id = str(teacher.get("Ustoz_ID", "")).strip()
            t_chat_id = str(
                teacher.get("Chat_ID") or teacher.get("Ustoz_Chat_ID") or ""
            ).strip()
            canonical_group_name = group["Guruh_Nomi"].strip()

            self.update_group(
                canonical_group_name,
                {
                    "Ustoz_ID": t_id,
                    "Ustoz_Chat_ID": t_chat_id,
                },
            )

            ws_groups = self._get_or_create_worksheet(
                GROUP_SHEET_NAME, headers=GROUP_HEADERS, rows=100, cols=12
            )
            headers = self._ensure_missing_headers(ws_groups, GROUP_HEADERS)
            updated_group = self.get_group(canonical_group_name) or group
            row_num = updated_group["_row_number"]
            requests: list[dict[str, Any]] = []
            for col_name in ("Ustoz_ID", "Ustoz_Chat_ID"):
                if col_name in headers:
                    c_idx = headers.index(col_name)
                    requests.append(
                        _cell_bg_request(
                            ws_groups.id,
                            row_num - 1,
                            row_num,
                            c_idx,
                            c_idx + 1,
                            WHITE_BG,
                        )
                    )
            if requests:
                self._execute_with_retry(
                    self._get_spreadsheet().batch_update, {"requests": requests}
                )

            updated_teacher = self.get_teacher_by_id(t_id) or teacher
            return {
                "group": updated_group,
                "teacher": updated_teacher,
            }

    def purge_teacher_completely(self, teacher_id: str) -> dict[str, Any]:
        """
        Permanently deletes a teacher: captures Ustoz_Chat_ID, deletes the row
        from Ustozlar and clears the teacher from every Guruhlar assignment
        (back to 'Ma'lumot kiritilmagan'). Returns
        {"deleted": bool, "teacher_id": str, "teacher_name": str,
         "teacher_chat_id": int | None, "cleared_groups": [str, ...]}.
        """
        with self._lock:
            payload: dict[str, Any] = {
                "deleted": False,
                "teacher_id": str(teacher_id or "").strip(),
                "teacher_name": "",
                "teacher_chat_id": None,
                "cleared_groups": [],
            }
            teacher = self.get_teacher(teacher_id)
            if not teacher:
                return payload

            t_id = str(teacher.get("Ustoz_ID", "")).strip()
            t_chat_raw = str(
                teacher.get("Chat_ID") or teacher.get("Ustoz_Chat_ID") or ""
            ).strip()
            t_chat_id = _normalize_chat_id(t_chat_raw)
            row_num = teacher.get("_row_number")
            payload["teacher_id"] = t_id
            payload["teacher_name"] = str(teacher.get("F.I.O.") or "").strip()
            payload["teacher_chat_id"] = t_chat_id

            ws_teachers = self._get_or_create_worksheet(
                TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=100, cols=10
            )
            if row_num:
                self._execute_with_retry(ws_teachers.delete_rows, int(row_num))
            payload["deleted"] = True

            cleared: list[str] = []
            for grp in self.get_all_groups():
                g_tid = str(grp.get("Ustoz_ID", "")).strip()
                g_cid = str(grp.get("Ustoz_Chat_ID", "")).strip()
                if (t_id and g_tid == t_id) or (t_chat_raw and g_cid == t_chat_raw):
                    self.update_group(
                        grp["Guruh_Nomi"],
                        {
                            "Ustoz_ID": MISSING_TEXT,
                            "Ustoz_Chat_ID": MISSING_TEXT,
                        },
                    )
                    cleared.append(str(grp["Guruh_Nomi"]))
            payload["cleared_groups"] = cleared
            return payload

    def delete_teacher_completely(self, teacher_id: str) -> str:
        """
        Deletes the teacher's row from Ustozlar, clears Ustoz_ID and Ustoz_Chat_ID
        in any assigned Guruhlar rows back to 'Ma'lumot kiritilmagan' with yellow
        background (#FFF2CC), and returns the teacher's Chat_ID.
        """
        with self._lock:
            teacher = self.get_teacher(teacher_id)
            if not teacher:
                return ""
            t_chat_raw = str(
                teacher.get("Chat_ID") or teacher.get("Ustoz_Chat_ID") or ""
            ).strip()
            self.purge_teacher_completely(teacher_id)
            return t_chat_raw

    # ------------------------------------------------------------------
    # CRUD: Guruhlar
    # ------------------------------------------------------------------

    def get_all_groups(self) -> list[dict[str, Any]]:
        with self._lock:
            now_ts = _time.monotonic()
            cached = self._groups_cache
            if cached is not None and (now_ts - cached[0]) < self._cache_ttl:
                return copy.deepcopy(cached[1])

            ws = self._get_or_create_worksheet(
                GROUP_SHEET_NAME, headers=GROUP_HEADERS, rows=100, cols=12
            )
            rows = self._execute_with_retry(ws.get_all_values)
            if len(rows) <= 1:
                if rows:
                    self._ws_cache[ws.title] = (ws, list(rows[0]))
                self._groups_cache = (now_ts, [])
                return []
            headers = rows[0]
            self._ws_cache[ws.title] = (ws, list(headers))
            groups: list[dict[str, Any]] = []
            for idx, raw_row in enumerate(rows[1:], start=2):
                padded = raw_row + [""] * (len(headers) - len(raw_row))
                record: dict[str, Any] = {
                    h: _normalize_read_value(v) for h, v in zip(headers, padded)
                }
                for h in GROUP_HEADERS:
                    record.setdefault(h, "")
                for cid_col in ("Ustoz_Chat_ID", "Guruh_TG_Chat_ID"):
                    if record.get(cid_col):
                        record[cid_col] = (
                            _chat_id_str(record[cid_col]) or record[cid_col]
                        )
                record["_row_number"] = idx
                if not record.get("Guruh_Nomi"):
                    continue
                groups.append(record)
            self._groups_cache = (now_ts, groups)
            return copy.deepcopy(groups)

    def get_group(self, group_name: str) -> Optional[dict[str, Any]]:
        with self._lock:
            target = _normalize_read_value(group_name).lower()
            if not target:
                return None
            for grp in self.get_all_groups():
                if grp.get("Guruh_Nomi", "").strip().lower() == target:
                    return grp
            return None

    def get_teacher_groups(self, teacher_chat_id: int | str) -> list[dict[str, Any]]:
        with self._lock:
            target = _chat_id_str(teacher_chat_id) or _normalize_read_value(
                teacher_chat_id
            )
            if not target:
                return []
            return [
                grp
                for grp in self.get_all_groups()
                if str(grp.get("Ustoz_Chat_ID", "")).strip() == target
            ]

    def get_groups_for_role(
        self, user_chat_id: int | str, is_admin: bool = False
    ) -> list[dict[str, Any]]:
        """
        Returns groups accessible for the given role:
        - When is_admin=True, ALWAYS returns 100% of all groups in Guruhlar
          regardless of whether user_chat_id is assigned as a teacher.
        - When is_admin=False, returns groups assigned to that teacher.
        """
        with self._lock:
            if is_admin:
                return self.get_all_groups()
            target = _chat_id_str(user_chat_id) or _normalize_read_value(user_chat_id)
            if not target:
                return []
            teacher = self.get_teacher_by_chat_id(target)
            teacher_id = str(teacher.get("Ustoz_ID", "")).strip() if teacher else ""
            return [
                grp
                for grp in self.get_all_groups()
                if str(grp.get("Ustoz_Chat_ID", "")).strip() == target
                or (teacher_id and str(grp.get("Ustoz_ID", "")).strip() == teacher_id)
            ]

    def get_all_groups_for_user(
        self, user_chat_id: int | str, is_admin: bool = False
    ) -> list[dict[str, Any]]:
        return self.get_groups_for_role(user_chat_id=user_chat_id, is_admin=is_admin)

    def is_teacher(self, chat_id: int | str) -> bool:
        target = _chat_id_str(chat_id) or _normalize_read_value(chat_id)
        if not target:
            return False
        return (
            self.get_teacher_by_chat_id(target) is not None
            or len(self.get_teacher_groups(target)) > 0
        )

    def add_group(
        self,
        group_name: str,
        teacher_chat_id: int | str = "",
        tg_chat_id: int | str = "",
        lessons_per_month: int = 12,
        lesson_days: str = "",
        lesson_time: str = "",
        teacher_id: str = "",
        monthly_price: int | str = "",
    ) -> dict[str, Any]:
        with self._lock:
            ws = self._get_or_create_worksheet(
                GROUP_SHEET_NAME, headers=GROUP_HEADERS, rows=100, cols=12
            )
            existing = self.get_group(group_name)
            if existing:
                return existing
            headers = self._ensure_missing_headers(ws, GROUP_HEADERS)
            row_map = {
                "Guruh_Nomi": _normalize_read_value(group_name),
                "Ustoz_ID": _normalize_read_value(teacher_id),
                "Ustoz_Chat_ID": _normalize_read_value(teacher_chat_id),
                "Guruh_TG_Chat_ID": _normalize_read_value(tg_chat_id),
                "Oylik_Dars_Soni": _normalize_read_value(lessons_per_month),
                "Dars_Kunlari": _normalize_read_value(lesson_days),
                "Dars_Vaqti": _normalize_read_value(lesson_time),
                "Otilgan_Dars_Hisoblagich": "0",
                "Oylik_Tolov_Summa": _normalize_read_value(monthly_price),
            }
            new_row = [row_map.get(h, "") for h in headers]
            new_row_idx = self._append_row_and_get_index(ws, new_row)
            self._sync_row_missing_cells(ws, new_row_idx, new_row)
            self._invalidate_groups_cache()
            return self.get_group(group_name) or {
                h: _normalize_read_value(row_map.get(h, "")) for h in headers
            }

    def create_group(
        self,
        group_name: str,
        teacher_chat_id: int | str = "",
        tg_chat_id: int | str = "",
        lessons_per_month: int = 12,
        lesson_days: str = "",
        lesson_time: str = "",
        teacher_id: str = "",
        monthly_price: int | str = "",
        start_date: Optional[date] = None,
        create_cycle: bool = True,
    ) -> dict[str, Any]:
        """
        Creates a new group in Guruhlar and, when schedule days are configured,
        immediately initializes its first cycle sheet with upfront unpaid red
        formatting and Qarzdor_Oylar += 1 for any active students.
        """
        with self._lock:
            group = self.add_group(
                group_name=group_name,
                teacher_chat_id=teacher_chat_id,
                tg_chat_id=tg_chat_id,
                lessons_per_month=lessons_per_month,
                lesson_days=lesson_days,
                lesson_time=lesson_time,
                teacher_id=teacher_id,
                monthly_price=monthly_price,
            )
            canonical_name = group["Guruh_Nomi"].strip()
            if create_cycle and parse_weekdays(group.get("Dars_Kunlari", "")):
                ss = self._get_spreadsheet()
                now_dt = now_tashkent()
                has_existing_cycle = False
                for y in (now_dt.year, now_dt.year - 1):
                    try:
                        ws = self._execute_with_retry(
                            ss.worksheet, f"{canonical_name}_{y}"
                        )
                        if self.parse_cycles_from_sheet(ws):
                            has_existing_cycle = True
                            break
                    except gspread.WorksheetNotFound:
                        continue
                if not has_existing_cycle:
                    resolved_start = start_date or _get_anchor_date_for_schedule(
                        now_dt, group.get("Dars_Vaqti", "")
                    )
                    self.create_cycle_table(
                        canonical_name,
                        resolved_start,
                        cycle_number=1,
                        year=resolved_start.year,
                    )
            return group

    def delete_group_completely(self, group_name: str) -> bool:
        """
        Deletes the group row from Guruhlar and all {group_name}_{year} cycle
        worksheets from the spreadsheet, while preserving every student and teacher
        row: all students in that group are moved to reserve ('O'qimayapti' with
        Guruh='Zahira guruhi', Sobiq_Guruh={group_name}) with debts/contacts intact.
        """
        with self._lock:
            target = _normalize_read_value(group_name)
            if not target:
                return False

            group = self.get_group(target)
            canonical_name = group["Guruh_Nomi"].strip() if group else target
            canonical_lower = canonical_name.lower()
            deleted_any = False

            if group and group.get("_row_number"):
                ws_groups = self._get_or_create_worksheet(
                    GROUP_SHEET_NAME, headers=GROUP_HEADERS, rows=100, cols=12
                )
                self._execute_with_retry(
                    ws_groups.delete_rows, int(group["_row_number"])
                )
                self._invalidate_groups_cache()
                deleted_any = True

            ss = self._get_spreadsheet()
            prefix_lower = f"{canonical_lower}_"
            for ws in list(self._execute_with_retry(ss.worksheets)):
                title_stripped = ws.title.strip()
                if title_stripped.lower().startswith(prefix_lower):
                    suffix = title_stripped[len(canonical_name) + 1 :]
                    if suffix.isdigit():
                        self._execute_with_retry(ss.del_worksheet, ws)
                        self._ws_cache.pop(ws.title, None)
                        deleted_any = True

            today_str = now_tashkent().strftime("%d.%m.%Y")
            for student in self.get_all_students():
                stu_group = str(student.get("Guruh", "")).strip()
                if stu_group.lower() == canonical_lower:
                    prev_note = str(student.get("Izoh") or "").strip()
                    note = (
                        f"{today_str}: '{canonical_name}' guruhi o'chirilgani sababli "
                        "Zahira guruhiga o'tkazildi"
                    )
                    self.update_student(
                        student["Talaba_ID"],
                        {
                            "Status": "O'qimayapti",
                            "Guruh": RESERVE_GROUP_NAME,
                            "Sobiq_Guruh": canonical_name,
                            "Izoh": (f"{prev_note} | {note}" if prev_note else note)[-480:],
                        },
                    )
                    deleted_any = True

            return deleted_any

    def update_group(self, group_name: str, updates: dict[str, Any]) -> bool:
        with self._lock:
            ws = self._get_or_create_worksheet(
                GROUP_SHEET_NAME, headers=GROUP_HEADERS, rows=100, cols=12
            )
            headers = self._ensure_missing_headers(ws, GROUP_HEADERS)
            group = self.get_group(group_name)
            if not group:
                return False
            row_num = group["_row_number"]
            raw_row = self._execute_with_retry(ws.row_values, row_num)
            row_values = raw_row + [""] * (len(headers) - len(raw_row))
            for key, value in updates.items():
                if key in headers:
                    col_idx = headers.index(key)
                    row_values[col_idx] = "" if value is None else str(value)
            self._sync_row_missing_cells(ws, row_num, row_values)
            self._invalidate_groups_cache()
            return True

    def update_group_full_info(
        self, old_group_name: str, updates: dict[str, Any]
    ) -> bool:
        """
        Safely updates any combination of Guruh_Nomi (renaming {old_group_name}_{year}
        worksheet tabs and Baza_Talabalar.Guruh if changed), Oylik_Dars_Soni,
        Dars_Kunlari, Dars_Vaqti, Tolov_Summasi / Oylik_Tolov_Summa, and
        Guruh_TG_Chat_ID in Guruhlar, rebuilding active cycle dates if
        Oylik_Dars_Soni or Dars_Kunlari changed.
        """
        with self._lock:
            old_group = self.get_group(old_group_name)
            if not old_group:
                return False

            old_canonical = old_group["Guruh_Nomi"].strip()
            clean_updates: dict[str, Any] = {}
            for k, v in (updates or {}).items():
                if k == "Tolov_Summasi":
                    clean_updates["Oylik_Tolov_Summa"] = v
                else:
                    clean_updates[k] = v

            if not clean_updates:
                return True

            new_name = str(clean_updates.get("Guruh_Nomi", "")).strip()
            name_changed = bool(
                new_name and new_name.lower() != old_canonical.lower()
            )

            self.update_group(old_canonical, clean_updates)
            active_name = new_name if name_changed else old_canonical

            if name_changed:
                stu_ws = self._get_or_create_worksheet(
                    STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
                )
                stu_rows = self._execute_with_retry(stu_ws.get_all_values)
                if len(stu_rows) > 1 and "Guruh" in stu_rows[0]:
                    g_col = stu_rows[0].index("Guruh")
                    stu_updates = [
                        {
                            "range": f"{_col_letter(g_col)}{idx}",
                            "values": [[new_name]],
                        }
                        for idx, raw_row in enumerate(stu_rows[1:], start=2)
                        if len(raw_row) > g_col
                        and raw_row[g_col].strip().lower() == old_canonical.lower()
                    ]
                    if stu_updates:
                        self._execute_with_retry(
                            stu_ws.batch_update,
                            stu_updates,
                            value_input_option="USER_ENTERED",
                        )
                        self._invalidate_students_cache()

                ss = self._get_spreadsheet()
                prefix_lower = f"{old_canonical.lower()}_"
                for ws in self._execute_with_retry(ss.worksheets):
                    if ws.title.lower().startswith(prefix_lower):
                        suffix = ws.title[len(old_canonical) + 1 :]
                        if suffix.isdigit():
                            try:
                                old_ws_title = ws.title
                                new_ws_title = f"{new_name}_{suffix}"
                                self._execute_with_retry(ws.update_title, new_ws_title)
                                if old_ws_title in self._ws_cache:
                                    cached_ws, cached_hdrs = self._ws_cache.pop(old_ws_title)
                                    self._ws_cache[new_ws_title] = (cached_ws, cached_hdrs)
                            except Exception:
                                pass

            if "Oylik_Dars_Soni" in clean_updates or "Dars_Kunlari" in clean_updates:
                grp_now = self.get_group(active_name)
                if grp_now:
                    new_count = int(grp_now.get("Oylik_Dars_Soni") or 12)
                    new_days = str(grp_now.get("Dars_Kunlari", "")).strip()
                    new_time = str(grp_now.get("Dars_Vaqti", "")).strip()
                    if new_days:
                        self.rebuild_active_cycle_sheet(
                            active_name, new_count, new_days, new_time
                        )

            return True

    def update_group_price(self, group_name: str, price_uzs: int | str) -> bool:
        clean_price = str(price_uzs).strip()
        return self.update_group(group_name, {"Oylik_Tolov_Summa": clean_price})

    def link_group_tg_chat(self, group_name: str, tg_chat_id: int | str) -> bool:
        return self.update_group(group_name, {"Guruh_TG_Chat_ID": str(tg_chat_id)})

    def increment_group_lesson_counter(self, group_name: str) -> tuple[int, int]:
        """Increments Otilgan_Dars_Hisoblagich by 1. Returns (new_count, lessons_limit)."""
        with self._lock:
            group = self.get_group(group_name)
            if not group:
                raise ValueError(f"Group not found: {group_name}")
            current = int(group.get("Otilgan_Dars_Hisoblagich") or 0)
            limit = int(group.get("Oylik_Dars_Soni") or 12)
            new_count = current + 1
            self.update_group(group_name, {"Otilgan_Dars_Hisoblagich": str(new_count)})
            return new_count, limit

    def reset_group_lesson_counter(self, group_name: str) -> bool:
        return self.update_group(group_name, {"Otilgan_Dars_Hisoblagich": "0"})

    # ------------------------------------------------------------------
    # Dynamic Group Cycle Sheets: {Group_Name}_{Year}
    # ------------------------------------------------------------------

    def get_or_create_group_year_sheet(
        self, group_name: str, year: int
    ) -> gspread.Worksheet:
        sheet_title = f"{group_name.strip()}_{year}"
        return self._get_or_create_worksheet(
            sheet_title, headers=None, rows=300, cols=22
        )

    def parse_cycles_from_sheet(self, ws: gspread.Worksheet) -> list[dict[str, Any]]:
        with self._lock:
            all_values = self._execute_with_retry(ws.get_all_values)
            cycles: list[dict[str, Any]] = []
            i = 0
            total_rows = len(all_values)

            while i < total_rows:
                row = all_values[i]
                first_cell = row[0].strip() if row else ""
                match = CYCLE_TITLE_RE.match(first_cell)
                if not match:
                    i += 1
                    continue

                title = match.group("title")
                cycle_num = int(match.group("num"))
                title_row_idx = i

                if i + 1 >= total_rows:
                    break
                header_row_idx = i + 1
                header_row = all_values[header_row_idx]

                date_columns: list[dict[str, Any]] = []
                tolov_col_idx: Optional[int] = None
                for col_idx, cell_val in enumerate(header_row):
                    val = cell_val.strip()
                    if col_idx >= 2 and val == "To'lov":
                        tolov_col_idx = col_idx
                        break
                    if col_idx >= 2 and val:
                        date_columns.append({"col_idx": col_idx, "date_str": val})

                if tolov_col_idx is None:
                    tolov_col_idx = (
                        date_columns[-1]["col_idx"] + 1 if date_columns else 2
                    )

                student_rows: list[dict[str, Any]] = []
                j = header_row_idx + 1
                while j < total_rows:
                    s_row = all_values[j]
                    s_first = s_row[0].strip() if s_row else ""
                    if not s_first or CYCLE_TITLE_RE.match(s_first):
                        break
                    padded = s_row + [""] * (tolov_col_idx + 1 - len(s_row))
                    marks = {
                        dc["col_idx"]: padded[dc["col_idx"]].strip()
                        for dc in date_columns
                    }
                    student_rows.append(
                        {
                            "row_idx": j,
                            "student_id": padded[0].strip(),
                            "full_name": padded[1].strip(),
                            "marks": marks,
                            "payment_status": padded[tolov_col_idx].strip(),
                        }
                    )
                    j += 1

                cycles.append(
                    {
                        "title": title,
                        "cycle_number": cycle_num,
                        "title_row_idx": title_row_idx,
                        "header_row_idx": header_row_idx,
                        "date_columns": date_columns,
                        "tolov_col_idx": tolov_col_idx,
                        "student_rows": student_rows,
                        "last_row_idx": (
                            student_rows[-1]["row_idx"] if student_rows else header_row_idx
                        ),
                    }
                )
                i = j
            return cycles

    def _get_cycle_colored_columns(
        self, ws: gspread.Worksheet, cycle: dict[str, Any]
    ) -> tuple[set[int], set[int]]:
        """
        Inspects cell backgrounds in the cycle block.
        Returns (marked_cols, cancelled_cols) where:
        - marked_cols: columns with Yellow (#FFF2CC) or Green (#D9EAD3) background.
        - cancelled_cols: columns with Red (#F4CCCC) background (when entire header/column is red).
        """
        marked_cols: set[int] = set()
        cancelled_cols: set[int] = set()
        if not cycle["date_columns"]:
            return marked_cols, cancelled_cols

        header_row_0 = cycle["header_row_idx"]
        last_row_0 = cycle["last_row_idx"]
        max_col_idx = cycle["tolov_col_idx"]
        a1_range = (
            f"'{ws.title}'!A{header_row_0 + 1}:"
            f"{_col_letter(max_col_idx)}{last_row_0 + 1}"
        )

        try:
            ss = self._get_spreadsheet()
            meta = self._execute_with_retry(
                ss.fetch_sheet_metadata,
                params={"includeGridData": True, "ranges": [a1_range]},
            )
            sheets_data = meta.get("sheets", [])
            if not sheets_data:
                return marked_cols, cancelled_cols
            grid_data = sheets_data[0].get("data", [])
            if not grid_data:
                return marked_cols, cancelled_cols
            row_data = grid_data[0].get("rowData", [])
            date_col_indices = {dc["col_idx"] for dc in cycle["date_columns"]}

            for row_offset, r_obj in enumerate(row_data):
                values = r_obj.get("values", [])
                for c_idx in date_col_indices:
                    if c_idx >= len(values):
                        continue
                    cell = values[c_idx]
                    fmt = cell.get("effectiveFormat") or cell.get("userEnteredFormat") or {}
                    bg = fmt.get("backgroundColor")
                    if not bg:
                        bg_style = fmt.get("backgroundColorStyle") or {}
                        bg = bg_style.get("rgbColor")
                    if _color_matches(bg, YELLOW_BG) or _color_matches(bg, GREEN_BG):
                        marked_cols.add(c_idx)
                    elif row_offset == 0 and _color_matches(bg, RED_BG):
                        cancelled_cols.add(c_idx)
        except Exception:
            pass

        return marked_cols, cancelled_cols

    def get_cycle_dates_with_status(
        self,
        group_name: str,
        year: Optional[int] = None,
        lang: str = "latn",
    ) -> list[dict[str, Any]]:
        """
        Reads row 2 date headers from the active cycle in {Group}_{Year},
        calculates the exact Uzbek weekday name (Dush..Yak), and checks whether
        each column already has attendance marks (✅/❌ or yellow/green background).
        """
        with self._lock:
            ss = self._get_spreadsheet()
            now_year = now_tashkent().year
            years_to_check = [year] if year else [now_year, now_year - 1]

            target_ws: Optional[gspread.Worksheet] = None
            cycles: list[dict[str, Any]] = []
            for y in years_to_check:
                sheet_title = f"{group_name.strip()}_{y}"
                try:
                    ws = self._execute_with_retry(ss.worksheet, sheet_title)
                except gspread.WorksheetNotFound:
                    continue
                parsed = self.parse_cycles_from_sheet(ws)
                if parsed:
                    target_ws = ws
                    cycles = parsed
                    break

            if not target_ws or not cycles:
                return []

            active_cycle = cycles[-1]
            marked_bg_cols, cancelled_bg_cols = self._get_cycle_colored_columns(
                target_ws, active_cycle
            )

            try:
                sheet_year = int(target_ws.title.rsplit("_", 1)[-1])
            except ValueError:
                sheet_year = now_year

            safe_lang = lang if lang in WEEKDAYS_SHORT else "latn"
            weekdays_map = WEEKDAYS_SHORT[safe_lang]

            results: list[dict[str, Any]] = []
            prev_date: Optional[date] = None
            running_year = sheet_year

            for dc in active_cycle["date_columns"]:
                col_idx = dc["col_idx"]
                date_str = dc["date_str"]

                weekday_str = ""
                full_date_iso = ""
                try:
                    parts = date_str.split(".")
                    if len(parts) == 3:
                        d_val, m_val, y_val = map(int, parts)
                        running_year = y_val
                    else:
                        d_val, m_val = map(int, parts)
                        if prev_date and m_val < prev_date.month:
                            running_year += 1
                    parsed_date = date(running_year, m_val, d_val)
                    prev_date = parsed_date
                    weekday_str = weekdays_map[parsed_date.weekday()]
                    full_date_iso = parsed_date.isoformat()
                except (ValueError, KeyError):
                    pass

                has_cell_marks = any(
                    _is_recorded_mark(s_row["marks"].get(col_idx, ""))
                    for s_row in active_cycle["student_rows"]
                )
                is_marked = has_cell_marks or (col_idx in marked_bg_cols)
                is_cancelled = col_idx in cancelled_bg_cols

                results.append(
                    {
                        "date_str": date_str,
                        "col_idx": col_idx,
                        "weekday": weekday_str,
                        "full_date": full_date_iso,
                        "is_marked": is_marked,
                        "is_cancelled": is_cancelled,
                        "cycle_title": active_cycle["title"],
                    }
                )

            return results

    def get_group_active_cycle_snapshot(
        self, group_name: str, year: Optional[int] = None
    ) -> dict[str, Any]:
        """
        Snapshot of the active (last) cycle of {Group}_{Year}: lesson dates (ISO),
        cancelled columns and every student's attendance cell values.
        Cached for a short TTL so repeated parent taps do not hit the Sheets quota.
        """
        import time as _time

        clean_group = (group_name or "").strip()
        cache_key = f"{clean_group.lower()}|{year or ''}"
        with self._lock:
            now_ts = _time.monotonic()
            cached = self._cycle_snapshot_cache.get(cache_key)
            if cached and (now_ts - cached[0]) < self._cache_ttl:
                return cached[1]

            empty: dict[str, Any] = {"cycle_title": "", "dates": [], "rows": []}
            if not clean_group or clean_group.lower() == RESERVE_GROUP_NAME.lower():
                return empty

            ss = self._get_spreadsheet()
            now_year = now_tashkent().year
            years_to_check = [year] if year else [now_year, now_year - 1]

            target_ws: Optional[gspread.Worksheet] = None
            cycles: list[dict[str, Any]] = []
            for y in years_to_check:
                try:
                    ws = self._execute_with_retry(ss.worksheet, f"{clean_group}_{y}")
                except gspread.WorksheetNotFound:
                    continue
                parsed = self.parse_cycles_from_sheet(ws)
                if parsed:
                    target_ws = ws
                    cycles = parsed
                    break

            if not target_ws or not cycles:
                self._cycle_snapshot_cache[cache_key] = (now_ts, empty)
                return empty

            active_cycle = cycles[-1]
            _marked_cols, cancelled_cols = self._get_cycle_colored_columns(
                target_ws, active_cycle
            )
            try:
                sheet_year = int(target_ws.title.rsplit("_", 1)[-1])
            except ValueError:
                sheet_year = now_year

            dates: list[dict[str, Any]] = []
            prev_date: Optional[date] = None
            running_year = sheet_year
            for dc in active_cycle["date_columns"]:
                try:
                    parts = dc["date_str"].split(".")
                    if len(parts) == 3:
                        d_val, m_val, y_val = map(int, parts)
                        running_year = y_val
                    else:
                        d_val, m_val = map(int, parts)
                        if prev_date and m_val < prev_date.month:
                            running_year += 1
                    parsed_date = date(running_year, m_val, d_val)
                except (ValueError, TypeError):
                    continue
                prev_date = parsed_date
                dates.append(
                    {
                        "col_idx": dc["col_idx"],
                        "date_str": dc["date_str"],
                        "iso": parsed_date.isoformat(),
                        "is_cancelled": dc["col_idx"] in cancelled_cols,
                    }
                )

            snapshot = {
                "cycle_title": active_cycle["title"],
                "dates": dates,
                "rows": [
                    {
                        "student_id": r["student_id"],
                        "full_name": r["full_name"],
                        "marks": dict(r["marks"]),
                    }
                    for r in active_cycle["student_rows"]
                ],
            }
            self._cycle_snapshot_cache[cache_key] = (now_ts, snapshot)
            return snapshot

    def get_student_current_cycle_lessons(
        self,
        group_name: str,
        student_id: str,
        student_fio: str = "",
    ) -> list[dict[str, Any]]:
        """
        Lesson dates of the group's current cycle with the student's attendance:
        [{"iso": "2026-11-22", "date_str": "22.11", "mark": "present"|"absent"|""}].
        Cancelled lesson columns are skipped.
        """
        snapshot = self.get_group_active_cycle_snapshot(group_name)
        clean_sid = (student_id or "").strip()
        clean_fio = (student_fio or "").strip().lower()
        row = next(
            (r for r in snapshot["rows"] if clean_sid and r["student_id"] == clean_sid),
            None,
        )
        if row is None and clean_fio:
            row = next(
                (r for r in snapshot["rows"] if r["full_name"].strip().lower() == clean_fio),
                None,
            )
        lessons: list[dict[str, Any]] = []
        for d in snapshot["dates"]:
            if d["is_cancelled"]:
                continue
            raw_mark = row["marks"].get(d["col_idx"], "") if row else ""
            if _is_present_mark(raw_mark):
                mark = "present"
            elif _is_absent_mark(raw_mark):
                mark = "absent"
            else:
                mark = ""
            lessons.append(
                {"iso": d["iso"], "date_str": d["date_str"], "mark": mark}
            )
        return lessons

    def get_group_lesson_dates_categorized(
        self,
        group_name: str,
        today_str: str = "",
        lang: str = "latn",
    ) -> dict[str, Any]:
        """
        Reads all lesson dates from the group's active {Group}_{Year} sheet and
        strictly separates them (using Asia/Tashkent date comparison DD.MM.YYYY) into:
        - today_lessons: lesson dates equal to today_str
        - past_lessons: lesson dates strictly < today_str (sorted newest first)
        Future dates (> today_str) are never exposed for attendance.
        """
        with self._lock:
            today_date = _parse_today_date(today_str)
            resolved_today_str = today_date.strftime("%d.%m.%Y")

            ss = self._get_spreadsheet()
            now_year = now_tashkent().year
            years_to_check = [now_year, now_year - 1]

            target_ws: Optional[gspread.Worksheet] = None
            cycles: list[dict[str, Any]] = []
            for y in years_to_check:
                sheet_title = f"{group_name.strip()}_{y}"
                try:
                    ws = self._execute_with_retry(ss.worksheet, sheet_title)
                except gspread.WorksheetNotFound:
                    continue
                parsed = self.parse_cycles_from_sheet(ws)
                if parsed:
                    target_ws = ws
                    cycles = parsed
                    break

            if not target_ws or not cycles:
                return {
                    "today_str": resolved_today_str,
                    "today_lessons": [],
                    "past_lessons": [],
                    "cycle_title": "",
                }

            active_cycle = cycles[-1]
            marked_bg_cols, cancelled_bg_cols = self._get_cycle_colored_columns(
                target_ws, active_cycle
            )

            try:
                sheet_year = int(target_ws.title.rsplit("_", 1)[-1])
            except ValueError:
                sheet_year = today_date.year

            safe_lang = lang if lang in WEEKDAYS_SHORT else "latn"
            weekdays_map = WEEKDAYS_SHORT[safe_lang]

            today_lessons: list[dict[str, Any]] = []
            past_entries: list[tuple[date, dict[str, Any]]] = []

            prev_date: Optional[date] = None
            running_year = sheet_year

            for dc in active_cycle["date_columns"]:
                col_idx = dc["col_idx"]
                date_str = dc["date_str"].strip()

                parsed_date: Optional[date] = None
                try:
                    parts = date_str.split(".")
                    if len(parts) == 3:
                        d_val, m_val, y_val = map(int, parts)
                        running_year = y_val
                        parsed_date = date(running_year, m_val, d_val)
                    elif len(parts) == 2:
                        d_val, m_val = map(int, parts)
                        if prev_date and m_val < prev_date.month:
                            running_year += 1
                        parsed_date = date(running_year, m_val, d_val)
                except ValueError:
                    parsed_date = None

                if parsed_date is None:
                    continue
                prev_date = parsed_date

                if parsed_date > today_date:
                    continue

                has_cell_marks = any(
                    _is_recorded_mark(s_row["marks"].get(col_idx, ""))
                    for s_row in active_cycle["student_rows"]
                )
                is_marked = has_cell_marks or (col_idx in marked_bg_cols)
                is_cancelled = col_idx in cancelled_bg_cols

                entry = {
                    "date_str": date_str,
                    "full_date_dmy": parsed_date.strftime("%d.%m.%Y"),
                    "full_date": parsed_date.isoformat(),
                    "col_idx": col_idx,
                    "weekday": weekdays_map.get(parsed_date.weekday(), ""),
                    "is_marked": is_marked,
                    "is_cancelled": is_cancelled,
                    "allow_notify": True,
                    "can_notify": True,
                    "cycle_title": active_cycle["title"],
                }

                if parsed_date == today_date:
                    today_lessons.append(entry)
                else:
                    past_entries.append((parsed_date, entry))

            past_entries.sort(key=lambda item: item[0], reverse=True)
            past_lessons = [item[1] for item in past_entries]

            return {
                "today_str": resolved_today_str,
                "today_lessons": today_lessons,
                "past_lessons": past_lessons,
                "cycle_title": active_cycle["title"],
            }

    def create_cycle_table(
        self,
        group_name: str,
        start_date: date,
        cycle_number: Optional[int] = None,
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Creates a new cycle block in {Group}_{Year}, immediately enforcing upfront
        payment status: every active student gets Qarzdor_Oylar incremented by 1
        (if not already charged for that cycle) and their cycle row initialized
        with 'To'lanmagan' in RED_BG (#F4CCCC) right from before Lesson 1.
        """
        with self._lock:
            group = self.get_group(group_name)
            if not group:
                raise ValueError(f"Group '{group_name}' not found in Guruhlar")

            lesson_count = int(group.get("Oylik_Dars_Soni") or 12)
            lesson_days = parse_weekdays(group.get("Dars_Kunlari", ""))
            if not lesson_days:
                raise ValueError(f"Group '{group_name}' has no valid Dars_Kunlari")

            lesson_dates = generate_cycle_dates(start_date, lesson_days, lesson_count)
            target_year = year or lesson_dates[0].year
            ws = self.get_or_create_group_year_sheet(group_name, target_year)
            ss = self._get_spreadsheet()

            existing_cycles = self.parse_cycles_from_sheet(ws)
            if cycle_number is None:
                cycle_number = (
                    max((c["cycle_number"] for c in existing_cycles), default=0) + 1
                )

            cycle_title = format_cycle_title(lesson_dates, cycle_number)
            date_strs = [d.strftime("%d.%m") for d in lesson_dates]
            header_row = ["Talaba_ID", "F.I.O.", *date_strs, "To'lov"]

            active_students = self.get_all_students(
                group_name=group_name, active_only=True
            )
            total_cols = len(header_row)

            all_values = self._execute_with_retry(ws.get_all_values)
            start_row_0 = (
                0
                if not any(any(cell.strip() for cell in r) for r in all_values)
                else len(all_values) + 1
            )

            block_rows: list[list[str]] = [
                [cycle_title] + [""] * (total_cols - 1),
                header_row,
            ]
            for student in active_students:
                block_rows.append(
                    [student["Talaba_ID"], student["F.I.O."]]
                    + [""] * len(date_strs)
                    + ["To'lanmagan"]
                )

            end_row_0 = start_row_0 + len(block_rows)
            needed_rows = end_row_0 + 20
            needed_cols = max(total_cols + 5, ws.col_count)
            if ws.row_count < needed_rows or ws.col_count < needed_cols:
                self._execute_with_retry(
                    ws.resize,
                    rows=max(ws.row_count, needed_rows),
                    cols=needed_cols,
                )

            start_a1 = f"A{start_row_0 + 1}"
            self._execute_with_retry(
                ws.update, start_a1, block_rows, value_input_option="USER_ENTERED"
            )

            header_row_0 = start_row_0 + 1
            data_start_0 = start_row_0 + 2
            tolov_col_0 = total_cols - 1

            requests: list[dict[str, Any]] = [
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": start_row_0,
                            "endRowIndex": start_row_0 + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": total_cols,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                },
                _cell_bg_request(
                    ws.id,
                    start_row_0,
                    start_row_0 + 1,
                    0,
                    total_cols,
                    COLOR_TITLE_BLUE,
                    bold=True,
                    h_align="CENTER",
                ),
                _cell_bg_request(
                    ws.id,
                    header_row_0,
                    header_row_0 + 1,
                    0,
                    2,
                    COLOR_HEADER_GRAY,
                    bold=True,
                    h_align="CENTER",
                ),
                _cell_bg_request(
                    ws.id,
                    header_row_0,
                    header_row_0 + 1,
                    tolov_col_0,
                    tolov_col_0 + 1,
                    COLOR_HEADER_GRAY,
                    bold=True,
                    h_align="CENTER",
                ),
                _cell_bg_request(
                    ws.id,
                    header_row_0,
                    header_row_0 + 1,
                    2,
                    tolov_col_0,
                    COLOR_WHITE,
                    bold=True,
                    h_align="CENTER",
                ),
                _borders_request(ws.id, start_row_0, end_row_0, 0, total_cols),
            ]
            if data_start_0 < end_row_0:
                requests.append(
                    _cell_bg_request(
                        ws.id,
                        data_start_0,
                        end_row_0,
                        0,
                        2,
                        COLOR_WHITE,
                    )
                )
                requests.append(
                    _cell_bg_request(
                        ws.id,
                        data_start_0,
                        end_row_0,
                        2,
                        tolov_col_0 + 1,
                        RED_BG,
                        bold=False,
                        h_align="CENTER",
                    )
                )

            self._execute_with_retry(ss.batch_update, {"requests": requests})

            # Upfront charge for the new cycle (cumulative 1 -> 2 -> 3 ...).
            # Students who were added BEFORE the group's very first cycle already
            # carry their upfront "1" month from enrollment — don't double-charge.
            is_first_cycle = not existing_cycles and int(cycle_number) == 1
            if is_first_cycle:
                try:
                    for _, other_ws in self._find_group_cycle_worksheets(group_name):
                        if other_ws.id != ws.id and self.parse_cycles_from_sheet(other_ws):
                            is_first_cycle = False
                            break
                except Exception:
                    is_first_cycle = False
            for student in active_students:
                if (
                    is_first_cycle
                    and str(student.get("Qarzdor_Oylar", "")).strip() == "1"
                ):
                    # Convert the enrollment placeholder "1" into this cycle's
                    # title (still exactly 1 month owed; dedupe-safe later).
                    self.update_student(
                        student["Talaba_ID"], {"Qarzdor_Oylar": cycle_title}
                    )
                    continue
                self._increment_debt_field(student["Talaba_ID"], cycle_title)

            return {
                "sheet_title": ws.title,
                "cycle_title": cycle_title,
                "cycle_number": cycle_number,
                "dates": date_strs,
                "start_date": date_strs[0],
                "end_date": date_strs[-1],
            }

    def create_new_cycle(
        self,
        group_name: str,
        start_date: Optional[date] = None,
        cycle_number: Optional[int] = None,
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Creates a new cycle for group_name (auto-calculating start_date after the
        previous cycle if omitted) with upfront unpaid red status and debt charge.
        """
        with self._lock:
            group = self.get_group(group_name)
            if not group:
                raise ValueError(f"Group '{group_name}' not found in Guruhlar")

            lesson_days = parse_weekdays(group.get("Dars_Kunlari", ""))
            if not lesson_days:
                raise ValueError(f"Group '{group_name}' has no valid Dars_Kunlari")

            resolved_start = start_date
            if resolved_start is None:
                now_dt = now_tashkent()
                ss = self._get_spreadsheet()
                years_to_check = [year] if year else [now_dt.year, now_dt.year - 1]
                for y in years_to_check:
                    try:
                        ws = self._execute_with_retry(
                            ss.worksheet, f"{group['Guruh_Nomi'].strip()}_{y}"
                        )
                    except gspread.WorksheetNotFound:
                        continue
                    parsed = self.parse_cycles_from_sheet(ws)
                    if parsed and parsed[-1]["date_columns"]:
                        prev_date: Optional[date] = None
                        running_year = y
                        for dc in parsed[-1]["date_columns"]:
                            try:
                                d_val, m_val = map(int, dc["date_str"].split("."))
                                if prev_date and m_val < prev_date.month:
                                    running_year += 1
                                prev_date = date(running_year, m_val, d_val)
                            except ValueError:
                                pass
                        if prev_date is not None:
                            resolved_start = get_next_lesson_date_after(
                                prev_date, lesson_days
                            )
                            break

                if resolved_start is None:
                    resolved_start = _get_anchor_date_for_schedule(
                        now_dt, group.get("Dars_Vaqti", "")
                    )

            return self.create_cycle_table(
                group_name=group["Guruh_Nomi"].strip(),
                start_date=resolved_start,
                cycle_number=cycle_number,
                year=year or resolved_start.year,
            )

    def rebuild_active_cycle_sheet(
        self,
        group_name: str,
        new_lesson_count: int,
        new_days: str | list[int],
        new_time: str,
    ) -> list[str]:
        """
        Rebuilds or resizes the active cycle in {group_name}_{year} when schedule
        settings (lesson count, days, time) change, and updates Guruhlar.
        Returns the final list of lesson date strings (e.g. ["19.11", "21.11", ...]).
        """
        with self._lock:
            group = self.get_group(group_name)
            if not group:
                raise ValueError(f"Group '{group_name}' not found in Guruhlar")

            count = int(new_lesson_count)
            if count <= 0:
                raise ValueError("new_lesson_count must be positive")

            if isinstance(new_days, str):
                lesson_days = parse_weekdays(new_days)
                days_str = new_days.strip()
            else:
                lesson_days = sorted(set(int(d) for d in new_days))
                weekdays_map = WEEKDAYS_SHORT["latn"]
                days_str = ", ".join(
                    weekdays_map[d] for d in lesson_days if d in weekdays_map
                )

            if not lesson_days:
                raise ValueError(f"Invalid lesson days: {new_days}")

            self.update_group(
                group_name,
                {
                    "Oylik_Dars_Soni": str(count),
                    "Dars_Kunlari": days_str,
                    "Dars_Vaqti": str(new_time).strip(),
                },
            )

            ss = self._get_spreadsheet()
            now_dt = now_tashkent()
            now_year = now_dt.year
            anchor_date = _get_anchor_date_for_schedule(now_dt, str(new_time))

            target_ws: Optional[gspread.Worksheet] = None
            cycles: list[dict[str, Any]] = []
            for y in (now_year, now_year - 1):
                sheet_title = f"{group_name.strip()}_{y}"
                try:
                    ws = self._execute_with_retry(ss.worksheet, sheet_title)
                except gspread.WorksheetNotFound:
                    continue
                parsed = self.parse_cycles_from_sheet(ws)
                if parsed:
                    target_ws = ws
                    cycles = parsed
                    break

            if not target_ws or not cycles:
                created = self.create_cycle_table(
                    group_name, anchor_date, year=anchor_date.year
                )
                return created["dates"]

            active_cycle = cycles[-1]
            try:
                sheet_year = int(target_ws.title.rsplit("_", 1)[-1])
            except ValueError:
                sheet_year = now_year

            completed_lessons = int(group.get("Otilgan_Dars_Hisoblagich") or 0)

            if completed_lessons <= 0:
                lesson_dates = generate_cycle_dates(anchor_date, lesson_days, count)
                date_strs = [d.strftime("%d.%m") for d in lesson_dates]
                cycle_title = format_cycle_title(
                    lesson_dates, active_cycle["cycle_number"]
                )
                header_row = ["Talaba_ID", "F.I.O.", *date_strs, "To'lov"]
                total_cols = len(header_row)

                existing_payment_by_sid = {
                    s["student_id"]: s["payment_status"]
                    for s in active_cycle["student_rows"]
                    if s.get("student_id")
                }
                active_students = self.get_all_students(
                    group_name=group_name, active_only=True
                )

                title_row_0 = active_cycle["title_row_idx"]
                header_row_0 = active_cycle["header_row_idx"]
                data_start_0 = title_row_0 + 2
                old_end_row_0 = active_cycle["last_row_idx"] + 1
                old_total_cols = active_cycle["tolov_col_idx"] + 1

                block_rows: list[list[str]] = [
                    [cycle_title] + [""] * (total_cols - 1),
                    header_row,
                ]
                for student in active_students:
                    sid = student["Talaba_ID"]
                    p_status = existing_payment_by_sid.get(sid, "") or "To'lanmagan"
                    block_rows.append(
                        [sid, student["F.I.O."]] + [""] * len(date_strs) + [p_status]
                    )

                new_end_row_0 = title_row_0 + len(block_rows)
                max_end_row_0 = max(old_end_row_0, new_end_row_0)
                max_cols = max(old_total_cols, total_cols)

                if (
                    target_ws.row_count < max_end_row_0 + 20
                    or target_ws.col_count < max_cols + 5
                ):
                    self._execute_with_retry(
                        target_ws.resize,
                        rows=max(target_ws.row_count, max_end_row_0 + 20),
                        cols=max(target_ws.col_count, max_cols + 5),
                    )

                clear_range = (
                    f"A{title_row_0 + 1}:"
                    f"{_col_letter(max_cols - 1)}{max_end_row_0}"
                )
                self._execute_with_retry(target_ws.batch_clear, [clear_range])
                self._execute_with_retry(
                    target_ws.update,
                    f"A{title_row_0 + 1}",
                    block_rows,
                    value_input_option="USER_ENTERED",
                )

                tolov_col_0 = total_cols - 1
                requests: list[dict[str, Any]] = [
                    {
                        "unmergeCells": {
                            "range": {
                                "sheetId": target_ws.id,
                                "startRowIndex": title_row_0,
                                "endRowIndex": title_row_0 + 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": max_cols,
                            }
                        }
                    },
                    _clear_borders_request(
                        target_ws.id, title_row_0, max_end_row_0, 0, max_cols
                    ),
                    _cell_bg_request(
                        target_ws.id,
                        title_row_0,
                        max_end_row_0,
                        0,
                        max_cols,
                        COLOR_WHITE,
                        bold=False,
                    ),
                    {
                        "mergeCells": {
                            "range": {
                                "sheetId": target_ws.id,
                                "startRowIndex": title_row_0,
                                "endRowIndex": title_row_0 + 1,
                                "startColumnIndex": 0,
                                "endColumnIndex": total_cols,
                            },
                            "mergeType": "MERGE_ALL",
                        }
                    },
                    _cell_bg_request(
                        target_ws.id,
                        title_row_0,
                        title_row_0 + 1,
                        0,
                        total_cols,
                        COLOR_TITLE_BLUE,
                        bold=True,
                        h_align="CENTER",
                    ),
                    _cell_bg_request(
                        target_ws.id,
                        header_row_0,
                        header_row_0 + 1,
                        0,
                        2,
                        COLOR_HEADER_GRAY,
                        bold=True,
                        h_align="CENTER",
                    ),
                    _cell_bg_request(
                        target_ws.id,
                        header_row_0,
                        header_row_0 + 1,
                        tolov_col_0,
                        tolov_col_0 + 1,
                        COLOR_HEADER_GRAY,
                        bold=True,
                        h_align="CENTER",
                    ),
                    _cell_bg_request(
                        target_ws.id,
                        header_row_0,
                        header_row_0 + 1,
                        2,
                        tolov_col_0,
                        COLOR_WHITE,
                        bold=True,
                        h_align="CENTER",
                    ),
                    _borders_request(
                        target_ws.id, title_row_0, new_end_row_0, 0, total_cols
                    ),
                ]
                if data_start_0 < new_end_row_0:
                    requests.append(
                        _cell_bg_request(
                            target_ws.id,
                            data_start_0,
                            new_end_row_0,
                            0,
                            2,
                            COLOR_WHITE,
                        )
                    )
                    for idx_offset, student in enumerate(active_students):
                        p_status = existing_payment_by_sid.get(
                            student["Talaba_ID"], ""
                        )
                        is_paid = _is_paid_status(p_status)
                        r_0 = data_start_0 + idx_offset
                        requests.append(
                            _cell_bg_request(
                                target_ws.id,
                                r_0,
                                r_0 + 1,
                                2,
                                tolov_col_0 + 1,
                                GREEN_BG if is_paid else RED_BG,
                                bold=is_paid,
                                h_align="CENTER",
                            )
                        )

                self._execute_with_retry(ss.batch_update, {"requests": requests})
                return date_strs

            # Mid-cycle change: completed_lessons > 0
            preserved_cols = active_cycle["date_columns"][:completed_lessons]
            preserved_date_strs = [dc["date_str"] for dc in preserved_cols]

            prev_date: Optional[date] = None
            running_year = sheet_year
            for dc in preserved_cols:
                try:
                    d_val, m_val = map(int, dc["date_str"].split("."))
                    if prev_date and m_val < prev_date.month:
                        running_year += 1
                    prev_date = date(running_year, m_val, d_val)
                except ValueError:
                    pass

            if prev_date and prev_date >= anchor_date:
                upcoming_start = prev_date + timedelta(days=1)
            else:
                upcoming_start = anchor_date

            remaining_count = max(0, count - len(preserved_cols))
            upcoming_dates = (
                generate_cycle_dates(upcoming_start, lesson_days, remaining_count)
                if remaining_count > 0
                else []
            )
            upcoming_date_strs = [d.strftime("%d.%m") for d in upcoming_dates]
            final_date_strs = preserved_date_strs + upcoming_date_strs

            title_row_0 = active_cycle["title_row_idx"]
            header_row_0 = active_cycle["header_row_idx"]
            end_row_0 = active_cycle["last_row_idx"] + 1

            upcoming_start_col_0 = 2 + len(preserved_cols)
            new_tolov_col_0 = 2 + len(final_date_strs)
            new_total_cols = new_tolov_col_0 + 1
            old_tolov_col_0 = active_cycle["tolov_col_idx"]
            old_total_cols = old_tolov_col_0 + 1
            max_cols = max(old_total_cols, new_total_cols)

            if target_ws.col_count < max_cols + 5:
                self._execute_with_retry(target_ws.resize, cols=max_cols + 5)

            value_updates: list[dict[str, Any]] = []
            clear_ranges: list[str] = []

            if old_total_cols > new_total_cols:
                clear_ranges.append(
                    f"{_col_letter(new_total_cols)}{title_row_0 + 1}:"
                    f"{_col_letter(old_total_cols - 1)}{end_row_0}"
                )

            header_tail = [*upcoming_date_strs, "To'lov"]
            value_updates.append(
                {
                    "range": (
                        f"{_col_letter(upcoming_start_col_0)}{header_row_0 + 1}:"
                        f"{_col_letter(new_tolov_col_0)}{header_row_0 + 1}"
                    ),
                    "values": [header_tail],
                }
            )

            for s_row in active_cycle["student_rows"]:
                r_num = s_row["row_idx"] + 1
                p_status = s_row["payment_status"] or "To'lanmagan"
                row_tail = [""] * len(upcoming_date_strs) + [p_status]
                value_updates.append(
                    {
                        "range": (
                            f"{_col_letter(upcoming_start_col_0)}{r_num}:"
                            f"{_col_letter(new_tolov_col_0)}{r_num}"
                        ),
                        "values": [row_tail],
                    }
                )

            if clear_ranges:
                self._execute_with_retry(target_ws.batch_clear, clear_ranges)
            if value_updates:
                self._execute_with_retry(
                    target_ws.batch_update,
                    value_updates,
                    value_input_option="USER_ENTERED",
                )

            requests = [
                {
                    "unmergeCells": {
                        "range": {
                            "sheetId": target_ws.id,
                            "startRowIndex": title_row_0,
                            "endRowIndex": title_row_0 + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": max_cols,
                        }
                    }
                },
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": target_ws.id,
                            "startRowIndex": title_row_0,
                            "endRowIndex": title_row_0 + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": new_total_cols,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                },
                _cell_bg_request(
                    target_ws.id,
                    title_row_0,
                    title_row_0 + 1,
                    0,
                    new_total_cols,
                    COLOR_TITLE_BLUE,
                    bold=True,
                    h_align="CENTER",
                ),
            ]

            if old_total_cols > new_total_cols:
                requests.append(
                    _clear_borders_request(
                        target_ws.id,
                        title_row_0,
                        end_row_0,
                        new_total_cols,
                        old_total_cols,
                    )
                )
                requests.append(
                    _cell_bg_request(
                        target_ws.id,
                        title_row_0,
                        end_row_0,
                        new_total_cols,
                        old_total_cols,
                        COLOR_WHITE,
                        bold=False,
                    )
                )

            if upcoming_date_strs:
                requests.append(
                    _cell_bg_request(
                        target_ws.id,
                        header_row_0,
                        header_row_0 + 1,
                        upcoming_start_col_0,
                        new_tolov_col_0,
                        COLOR_WHITE,
                        bold=True,
                        h_align="CENTER",
                    )
                )

            requests.append(
                _cell_bg_request(
                    target_ws.id,
                    header_row_0,
                    header_row_0 + 1,
                    new_tolov_col_0,
                    new_tolov_col_0 + 1,
                    COLOR_HEADER_GRAY,
                    bold=True,
                    h_align="CENTER",
                )
            )
            for s_row in active_cycle["student_rows"]:
                r_0 = s_row["row_idx"]
                is_paid = _is_paid_status(s_row.get("payment_status", ""))
                row_bg = GREEN_BG if is_paid else RED_BG
                if upcoming_date_strs:
                    requests.append(
                        _cell_bg_request(
                            target_ws.id,
                            r_0,
                            r_0 + 1,
                            upcoming_start_col_0,
                            new_tolov_col_0,
                            row_bg,
                            bold=False,
                            h_align="CENTER",
                        )
                    )
                requests.append(
                    _cell_bg_request(
                        target_ws.id,
                        r_0,
                        r_0 + 1,
                        new_tolov_col_0,
                        new_tolov_col_0 + 1,
                        row_bg,
                        bold=is_paid,
                        h_align="CENTER",
                    )
                )

            requests.append(
                _borders_request(
                    target_ws.id, title_row_0, end_row_0, 0, new_total_cols
                )
            )
            self._execute_with_retry(ss.batch_update, {"requests": requests})

            return final_date_strs

    def _find_cycle_for_date_str(
        self, group_name: str, target_date_str: str, year: Optional[int] = None
    ) -> Optional[tuple[gspread.Worksheet, dict[str, Any], int]]:
        target_str = target_date_str.strip()
        short_str = target_str[:5] if re.match(r"^\d{2}\.\d{2}\.\d{4}$", target_str) else target_str
        now_year = now_tashkent().year
        candidate_years = [year] if year else [now_year, now_year - 1]
        ss = self._get_spreadsheet()

        for y in candidate_years:
            sheet_title = f"{group_name.strip()}_{y}"
            try:
                ws = self._execute_with_retry(ss.worksheet, sheet_title)
            except gspread.WorksheetNotFound:
                continue
            cycles = self.parse_cycles_from_sheet(ws)
            for cycle in reversed(cycles):
                for dc in cycle["date_columns"]:
                    if dc["date_str"] == target_str or dc["date_str"] == short_str:
                        return ws, cycle, dc["col_idx"]
        return None

    def _find_cycle_for_date_or_latest(
        self, group_name: str, target_date: date, year: Optional[int] = None
    ) -> tuple[gspread.Worksheet, dict[str, Any]]:
        target_str = target_date.strftime("%d.%m")
        candidate_years = [year] if year else [target_date.year, target_date.year - 1]
        ss = self._get_spreadsheet()

        for y in candidate_years:
            sheet_title = f"{group_name.strip()}_{y}"
            try:
                ws = self._execute_with_retry(ss.worksheet, sheet_title)
            except gspread.WorksheetNotFound:
                continue
            cycles = self.parse_cycles_from_sheet(ws)
            for cycle in reversed(cycles):
                if any(dc["date_str"] == target_str for dc in cycle["date_columns"]):
                    return ws, cycle

        ws = self.get_or_create_group_year_sheet(group_name, target_date.year)
        cycles = self.parse_cycles_from_sheet(ws)
        if not cycles:
            self.create_cycle_table(group_name, target_date, year=target_date.year)
            cycles = self.parse_cycles_from_sheet(ws)
        return ws, cycles[-1]

    def _parse_date_str_near_year(self, date_str: str, base_year: int) -> date:
        day, month = map(int, date_str.split("."))
        return date(base_year, month, day)

    def cancel_lesson_and_shift_date(
        self,
        group_name: str,
        cancel_date: date,
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        """Marks cancelled date column Red (#F4CCCC) and appends the next lesson date before To'lov."""
        with self._lock:
            group = self.get_group(group_name)
            if not group:
                raise ValueError(f"Group '{group_name}' not found")
            lesson_days = parse_weekdays(group.get("Dars_Kunlari", ""))
            if not lesson_days:
                raise ValueError(f"Group '{group_name}' has no Dars_Kunlari")

            ws, cycle = self._find_cycle_for_date_or_latest(group_name, cancel_date, year)
            ss = self._get_spreadsheet()
            cancel_str = cancel_date.strftime("%d.%m")

            cancel_col_idx: Optional[int] = None
            for dc in cycle["date_columns"]:
                if dc["date_str"] == cancel_str:
                    cancel_col_idx = dc["col_idx"]
                    break

            if cancel_col_idx is None:
                raise ValueError(
                    f"Date {cancel_str} not found in active cycle '{cycle['title']}'"
                )

            sheet_year = (
                int(ws.title.rsplit("_", 1)[-1]) if "_" in ws.title else cancel_date.year
            )
            prev_date: Optional[date] = None
            running_year = sheet_year
            for dc in cycle["date_columns"]:
                d_val, m_val = map(int, dc["date_str"].split("."))
                if prev_date and m_val < prev_date.month:
                    running_year += 1
                prev_date = date(running_year, m_val, d_val)

            last_cycle_date = prev_date or cancel_date
            new_lesson_date = get_next_lesson_date_after(last_cycle_date, lesson_days)
            new_date_str = new_lesson_date.strftime("%d.%m")

            tolov_col_idx = cycle["tolov_col_idx"]
            new_tolov_col_idx = tolov_col_idx + 1
            if ws.col_count <= new_tolov_col_idx + 1:
                self._execute_with_retry(ws.resize, cols=new_tolov_col_idx + 5)

            header_row_0 = cycle["header_row_idx"]
            end_row_0 = cycle["last_row_idx"] + 1
            title_row_0 = cycle["title_row_idx"]

            value_updates: list[dict[str, Any]] = [
                {
                    "range": f"{_col_letter(tolov_col_idx)}{header_row_0 + 1}",
                    "values": [[new_date_str]],
                },
                {
                    "range": f"{_col_letter(new_tolov_col_idx)}{header_row_0 + 1}",
                    "values": [["To'lov"]],
                },
            ]
            for s_row in cycle["student_rows"]:
                r_num = s_row["row_idx"] + 1
                value_updates.append(
                    {
                        "range": f"{_col_letter(tolov_col_idx)}{r_num}",
                        "values": [[""]],
                    }
                )
                value_updates.append(
                    {
                        "range": f"{_col_letter(new_tolov_col_idx)}{r_num}",
                        "values": [[s_row["payment_status"]]],
                    }
                )
            self._execute_with_retry(
                ws.batch_update, value_updates, value_input_option="USER_ENTERED"
            )

            requests: list[dict[str, Any]] = [
                {
                    "unmergeCells": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": title_row_0,
                            "endRowIndex": title_row_0 + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": new_tolov_col_idx + 1,
                        }
                    }
                },
                {
                    "mergeCells": {
                        "range": {
                            "sheetId": ws.id,
                            "startRowIndex": title_row_0,
                            "endRowIndex": title_row_0 + 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": new_tolov_col_idx + 1,
                        },
                        "mergeType": "MERGE_ALL",
                    }
                },
                _cell_bg_request(
                    ws.id,
                    title_row_0,
                    title_row_0 + 1,
                    0,
                    new_tolov_col_idx + 1,
                    COLOR_TITLE_BLUE,
                    bold=True,
                    h_align="CENTER",
                ),
                _cell_bg_request(
                    ws.id,
                    header_row_0,
                    end_row_0,
                    cancel_col_idx,
                    cancel_col_idx + 1,
                    RED_BG,
                    h_align="CENTER",
                ),
                _cell_bg_request(
                    ws.id,
                    header_row_0,
                    header_row_0 + 1,
                    tolov_col_idx,
                    tolov_col_idx + 1,
                    COLOR_WHITE,
                    bold=True,
                    h_align="CENTER",
                ),
                _cell_bg_request(
                    ws.id,
                    header_row_0,
                    header_row_0 + 1,
                    new_tolov_col_idx,
                    new_tolov_col_idx + 1,
                    COLOR_HEADER_GRAY,
                    bold=True,
                    h_align="CENTER",
                ),
                _borders_request(
                    ws.id, title_row_0, end_row_0, 0, new_tolov_col_idx + 1
                ),
            ]
            for s_row in cycle["student_rows"]:
                r_0 = s_row["row_idx"]
                is_paid = _is_paid_status(s_row.get("payment_status", ""))
                row_bg = GREEN_BG if is_paid else RED_BG
                requests.append(
                    _cell_bg_request(
                        ws.id,
                        r_0,
                        r_0 + 1,
                        tolov_col_idx,
                        new_tolov_col_idx + 1,
                        row_bg,
                        bold=False,
                        h_align="CENTER",
                    )
                )
            self._execute_with_retry(ss.batch_update, {"requests": requests})

            return {
                "cycle_title": cycle["title"],
                "cancelled_date": cancel_str,
                "new_end_date": new_date_str,
            }

    def save_attendance_for_date(
        self,
        group_name: str,
        target_date_str: str,
        attendance_dict: dict[str, str],
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        Writes ✅/❌ into target_date_str column for each student and colors cells Yellow (#FFF2CC)
        (or Green #D9EAD3 if already paid).
        Increments Otilgan_Dars_Hisoblagich in Guruhlar by +1 ONLY if the column was previously unmarked.
        When the final lesson of the cycle completes (completed_lessons >= total_lessons),
        colors all lesson cells AND To'lov cell in RED_BG (#F4CCCC) for every unpaid student.
        """
        with self._lock:
            for sid, mark in attendance_dict.items():
                if mark not in {"✅", "❌"}:
                    raise ValueError(
                        f"Invalid attendance mark '{mark}' for student {sid}. Only ✅ or ❌ allowed."
                    )

            date_str = target_date_str.strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                date_str = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")
            elif re.match(r"^\d{2}\.\d{2}\.\d{4}$", date_str):
                date_str = datetime.strptime(date_str, "%d.%m.%Y").strftime("%d.%m")

            found = self._find_cycle_for_date_str(group_name, date_str, year)
            if not found:
                raise ValueError(
                    f"Date '{date_str}' not found in active cycle for group '{group_name}'"
                )

            ws, cycle, date_col_idx = found
            ss = self._get_spreadsheet()

            has_existing_marks = any(
                _is_recorded_mark(s_row["marks"].get(date_col_idx, ""))
                for s_row in cycle["student_rows"]
            )
            marked_bg_cols, cancelled_bg_cols = self._get_cycle_colored_columns(
                ws, cycle
            )
            was_unmarked = not (has_existing_marks or (date_col_idx in marked_bg_cols))
            # 1-based ordinal of this date inside ITS OWN monthly cycle (cancelled
            # lesson columns are not counted, so numbers match lessons actually held).
            lesson_number = 0
            for dc in cycle["date_columns"]:
                if dc["col_idx"] in cancelled_bg_cols and dc["col_idx"] != date_col_idx:
                    continue
                lesson_number += 1
                if dc["col_idx"] == date_col_idx:
                    break

            row_by_sid = {s["student_id"]: s for s in cycle["student_rows"]}
            value_updates: list[dict[str, Any]] = []
            color_requests: list[dict[str, Any]] = [
                _cell_bg_request(
                    ws.id,
                    cycle["header_row_idx"],
                    cycle["header_row_idx"] + 1,
                    date_col_idx,
                    date_col_idx + 1,
                    YELLOW_BG,
                    bold=True,
                    h_align="CENTER",
                )
            ]

            for sid, mark in attendance_dict.items():
                student_row = row_by_sid.get(sid)
                if not student_row:
                    continue
                r_idx_0 = student_row["row_idx"]
                value_updates.append(
                    {
                        "range": f"{_col_letter(date_col_idx)}{r_idx_0 + 1}",
                        "values": [[mark]],
                    }
                )
                is_already_paid = _is_paid_status(student_row.get("payment_status", ""))
                cell_color = GREEN_BG if is_already_paid else YELLOW_BG
                color_requests.append(
                    _cell_bg_request(
                        ws.id,
                        r_idx_0,
                        r_idx_0 + 1,
                        date_col_idx,
                        date_col_idx + 1,
                        cell_color,
                        h_align="CENTER",
                    )
                )

            if value_updates:
                self._retry_sheets_op(
                    ws.batch_update, value_updates, value_input_option="USER_ENTERED"
                )
            if color_requests:
                self._retry_sheets_op(ss.batch_update, {"requests": color_requests})

            group = self.get_group(group_name)
            if not group:
                raise ValueError(f"Group not found: {group_name}")

            if was_unmarked:
                lesson_count, lessons_limit = self.increment_group_lesson_counter(
                    group_name
                )
            else:
                lesson_count = int(group.get("Otilgan_Dars_Hisoblagich") or 0)
                lessons_limit = int(group.get("Oylik_Dars_Soni") or 12)

            if lesson_count >= lessons_limit:
                tolov_col_idx = cycle["tolov_col_idx"]
                for s_row in cycle["student_rows"]:
                    if not _is_paid_status(s_row.get("payment_status", "")):
                        r_idx_1 = s_row["row_idx"] + 1
                        self._verify_and_format_range(
                            ws,
                            r_idx_1,
                            r_idx_1,
                            2,
                            tolov_col_idx,
                            RED_BG,
                            h_align="CENTER",
                        )

            return {
                "sheet_title": ws.title,
                "cycle_title": cycle["title"],
                "date_str": date_str,
                "marked_count": len(value_updates),
                "was_unmarked": was_unmarked,
                "lesson_count": lesson_count,
                "lessons_limit": lessons_limit,
                "lesson_number": lesson_number,
            }

    def mark_attendance_for_date(
        self,
        group_name: str,
        lesson_date: date,
        attendance_map: dict[str, str],
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        """Writes ONLY ✅ or ❌ into cells and colors completed lesson cells Yellow (#FFF2CC)."""
        with self._lock:
            date_str = lesson_date.strftime("%d.%m")
            found = self._find_cycle_for_date_str(group_name, date_str, year)
            if found:
                return self.save_attendance_for_date(
                    group_name, date_str, attendance_map, year=year
                )

            for sid, mark in attendance_map.items():
                if mark not in {"✅", "❌"}:
                    raise ValueError(
                        f"Invalid attendance mark '{mark}' for student {sid}. Only ✅ or ❌ allowed."
                    )

            ws, cycle = self._find_cycle_for_date_or_latest(group_name, lesson_date, year)
            if not cycle["date_columns"]:
                raise ValueError(f"Cycle '{cycle['title']}' has no date columns")
            fallback_date_str = cycle["date_columns"][0]["date_str"]
            return self.save_attendance_for_date(
                group_name, fallback_date_str, attendance_map, year=year
            )

    def _find_group_cycle_worksheets(
        self, group_name: str, year: Optional[int] = None
    ) -> list[tuple[int, gspread.Worksheet]]:
        ss = self._get_spreadsheet()
        clean_group = group_name.strip()
        zaxira_match = re.match(r"^Zaxira\s*\((.+)\)$", clean_group, re.IGNORECASE)
        candidate_names = [clean_group]
        if zaxira_match:
            inner = zaxira_match.group(1).strip()
            if inner and inner not in candidate_names:
                candidate_names.append(inner)

        all_sheets = self._execute_with_retry(ss.worksheets)
        matched: list[tuple[int, gspread.Worksheet]] = []

        for g_name in candidate_names:
            pattern = re.compile(
                rf"^{re.escape(g_name)}_(\d{{4}})$", re.IGNORECASE
            )
            for ws in all_sheets:
                m = pattern.match(ws.title.strip())
                if not m:
                    continue
                ws_year = int(m.group(1))
                if year is not None and ws_year != year:
                    continue
                matched.append((ws_year, ws))
            if matched:
                break

        matched.sort(key=lambda item: item[0])
        return matched

    def _locate_student_cycle(
        self,
        student_id: str,
        group_name: str,
        cycle_title: Optional[str] = None,
        year: Optional[int] = None,
        prefer_paid: Optional[bool] = None,
    ) -> Optional[tuple[gspread.Worksheet, dict[str, Any], dict[str, Any], bool]]:
        clean_sid = _normalize_student_id_key(student_id)
        student_obj = self.get_student_by_id(clean_sid) if clean_sid else None
        clean_fio = (
            _normalize_fio_key(student_obj.get("F.I.O.", ""))
            if student_obj
            else ""
        )

        group_sheets = self._find_group_cycle_worksheets(group_name, year=year)
        if not group_sheets:
            return None

        all_candidates: list[
            tuple[gspread.Worksheet, dict[str, Any], dict[str, Any], bool]
        ] = []
        latest_sheet_idx = len(group_sheets) - 1

        for s_idx, (_, ws) in enumerate(group_sheets):
            cycles = self.parse_cycles_from_sheet(ws)
            last_cycle_idx = len(cycles) - 1
            for c_idx, cycle in enumerate(cycles):
                is_latest_cycle = (s_idx == latest_sheet_idx) and (
                    c_idx == last_cycle_idx
                )
                student_row = None
                if clean_sid:
                    student_row = next(
                        (
                            s
                            for s in cycle["student_rows"]
                            if _normalize_student_id_key(s.get("student_id", ""))
                            == clean_sid
                        ),
                        None,
                    )
                if student_row is None and clean_fio:
                    # Fallback by normalized F.I.O. only for rows without a
                    # conflicting Talaba_ID (avoids matching a namesake).
                    student_row = next(
                        (
                            s
                            for s in cycle["student_rows"]
                            if _normalize_fio_key(s.get("full_name", "")) == clean_fio
                            and (
                                not _normalize_student_id_key(s.get("student_id", ""))
                                or not clean_sid
                                or _normalize_student_id_key(s.get("student_id", ""))
                                == clean_sid
                            )
                        ),
                        None,
                    )
                if student_row is not None:
                    all_candidates.append((ws, cycle, student_row, is_latest_cycle))

        if not all_candidates:
            return None

        if cycle_title:
            target_title = cycle_title.strip()
            exact_matches = [
                item
                for item in all_candidates
                if item[1]["title"].strip() == target_title
            ]
            if exact_matches:
                return exact_matches[-1]

        if prefer_paid is not None:
            for item in reversed(all_candidates):
                is_paid = _is_paid_status(item[2].get("payment_status", ""))
                if is_paid == prefer_paid:
                    return item

        return all_candidates[-1]

    def confirm_student_payment(
        self,
        student_id: str,
        group_name: str,
        cycle_title: Optional[str] = None,
        year: Optional[int] = None,
    ) -> bool:
        """
        Marks the student's To'lov cell as "To'langan", decrements Qarzdor_Oylar
        (minimum 0) in Baza_Talabalar, and immediately colors that student's entire
        cycle row (all lesson cells + To'lov cell) in GREEN_BG (#D9EAD3).
        """
        with self._lock:
            located = self._locate_student_cycle(
                student_id,
                group_name,
                cycle_title=cycle_title,
                year=year,
                prefer_paid=False,
            )
            if not located:
                return False

            target_ws, target_cycle, student_row, _ = located
            r_idx_0 = student_row["row_idx"]
            r_idx_1 = r_idx_0 + 1
            tolov_col_0 = target_cycle["tolov_col_idx"]
            tolov_cell_a1 = f"{_col_letter(tolov_col_0)}{r_idx_1}"

            self._retry_sheets_op(
                target_ws.update,
                tolov_cell_a1,
                [["To'langan"]],
                value_input_option="USER_ENTERED",
            )

            color_requests: list[dict[str, Any]] = []
            if tolov_col_0 > 2:
                color_requests.append(
                    _cell_bg_request(
                        target_ws.id,
                        r_idx_0,
                        r_idx_0 + 1,
                        2,
                        tolov_col_0,
                        GREEN_BG,
                        h_align="CENTER",
                    )
                )
            color_requests.append(
                _cell_bg_request(
                    target_ws.id,
                    r_idx_0,
                    r_idx_0 + 1,
                    tolov_col_0,
                    tolov_col_0 + 1,
                    GREEN_BG,
                    bold=True,
                    h_align="CENTER",
                )
            )
            self._apply_color_requests_with_fallback(
                target_ws,
                color_requests,
                fallback_ranges=[
                    (r_idx_1, 2, tolov_col_0 - 1, GREEN_BG, None)
                    if tolov_col_0 > 2
                    else None,
                    (r_idx_1, tolov_col_0, tolov_col_0, GREEN_BG, True),
                ],
            )

            self._decrement_debt_field(student_id, target_cycle["title"])
            return True

    def revert_student_payment(
        self,
        student_id: str,
        group_name: str,
        cycle_title: Optional[str] = None,
        year: Optional[int] = None,
    ) -> bool:
        """
        Reverts To'lov cell back to "To'lanmagan", increments Qarzdor_Oylar by 1
        in Baza_Talabalar, and reverts that student's cycle row color back to
        RED_BG (for finished cycles or unpaid/unmarked cells) or YELLOW_BG (for
        marked lessons in an ongoing cycle).
        """
        with self._lock:
            located = self._locate_student_cycle(
                student_id,
                group_name,
                cycle_title=cycle_title,
                year=year,
                prefer_paid=True,
            )
            if not located:
                return False

            target_ws, target_cycle, student_row, is_latest_cycle = located
            r_idx_0 = student_row["row_idx"]
            r_idx_1 = r_idx_0 + 1
            tolov_col_0 = target_cycle["tolov_col_idx"]
            tolov_cell_a1 = f"{_col_letter(tolov_col_0)}{r_idx_1}"

            self._retry_sheets_op(
                target_ws.update,
                tolov_cell_a1,
                [["To'lanmagan"]],
                value_input_option="USER_ENTERED",
            )

            group = self.get_group(group_name)
            if not is_latest_cycle:
                is_finished = True
            elif group:
                completed = int(group.get("Otilgan_Dars_Hisoblagich") or 0)
                limit = int(group.get("Oylik_Dars_Soni") or 12)
                is_finished = completed >= limit
            else:
                is_finished = all(
                    _is_recorded_mark(student_row["marks"].get(dc["col_idx"], ""))
                    for dc in target_cycle["date_columns"]
                )

            color_requests: list[dict[str, Any]] = []
            fallback_ranges: list[Optional[tuple[int, int, int, dict[str, float], Optional[bool]]]] = []
            if is_finished:
                color_requests.append(
                    _cell_bg_request(
                        target_ws.id,
                        r_idx_0,
                        r_idx_0 + 1,
                        2,
                        tolov_col_0 + 1,
                        RED_BG,
                        bold=False,
                        h_align="CENTER",
                    )
                )
                fallback_ranges.append((r_idx_1, 2, tolov_col_0, RED_BG, False))
            else:
                for dc in target_cycle["date_columns"]:
                    c_idx_0 = dc["col_idx"]
                    mark = student_row["marks"].get(c_idx_0, "").strip()
                    bg = YELLOW_BG if _is_recorded_mark(mark) else RED_BG
                    color_requests.append(
                        _cell_bg_request(
                            target_ws.id,
                            r_idx_0,
                            r_idx_0 + 1,
                            c_idx_0,
                            c_idx_0 + 1,
                            bg,
                            bold=False,
                            h_align="CENTER",
                        )
                    )
                    fallback_ranges.append((r_idx_1, c_idx_0, c_idx_0, bg, False))
                color_requests.append(
                    _cell_bg_request(
                        target_ws.id,
                        r_idx_0,
                        r_idx_0 + 1,
                        tolov_col_0,
                        tolov_col_0 + 1,
                        RED_BG,
                        bold=False,
                        h_align="CENTER",
                    )
                )
                fallback_ranges.append((r_idx_1, tolov_col_0, tolov_col_0, RED_BG, False))

            self._apply_color_requests_with_fallback(
                target_ws, color_requests, fallback_ranges=fallback_ranges
            )

            self._increment_debt_field(student_id, target_cycle["title"])
            return True

    def confirm_cycle_payment(
        self,
        group_name: str,
        student_id: str,
        cycle_title: str,
        year: Optional[int] = None,
    ) -> bool:
        """
        Marks To'lov as paid and turns that student's entire cycle row
        (lesson cells + To'lov cell) Green (#D9EAD3).
        """
        return self.confirm_student_payment(
            student_id=student_id,
            group_name=group_name,
            cycle_title=cycle_title,
            year=year,
        )

    def get_student_cycle_history(
        self,
        group_name: str,
        student_id: str,
        year: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            ss = self._get_spreadsheet()
            target_year = year or now_tashkent().year
            sheet_title = f"{group_name.strip()}_{target_year}"
            try:
                ws = self._execute_with_retry(ss.worksheet, sheet_title)
            except gspread.WorksheetNotFound:
                return []

            history: list[dict[str, Any]] = []
            for cycle in self.parse_cycles_from_sheet(ws):
                s_row = next(
                    (
                        s
                        for s in cycle["student_rows"]
                        if s["student_id"].strip() == student_id.strip()
                    ),
                    None,
                )
                if not s_row:
                    continue
                lessons: list[dict[str, str]] = []
                present_count = 0
                absent_count = 0
                for dc in cycle["date_columns"]:
                    mark = s_row["marks"].get(dc["col_idx"], "").strip()
                    if _is_present_mark(mark):
                        present_count += 1
                    elif _is_absent_mark(mark):
                        absent_count += 1
                    lessons.append({"date": dc["date_str"], "mark": mark or "⏳"})

                dates_only = [dc["date_str"] for dc in cycle["date_columns"]]
                history.append(
                    {
                        "cycle_title": cycle["title"],
                        "cycle_number": cycle["cycle_number"],
                        "start_date": dates_only[0] if dates_only else "",
                        "end_date": dates_only[-1] if dates_only else "",
                        "lessons": lessons,
                        "present_count": present_count,
                        "absent_count": absent_count,
                        "payment_status": s_row["payment_status"],
                        "is_paid": _is_paid_status(s_row["payment_status"]),
                    }
                )
            return history

    # ------------------------------------------------------------------
    # Async convenience wrappers for aiogram handlers
    # ------------------------------------------------------------------

    async def a_get_all_students(
        self, group_name: Optional[str] = None, active_only: bool = False
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_all_students, group_name, active_only
        )

    async def a_get_reserve_students(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.get_reserve_students)

    async def a_get_student(self, student_id: str) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_student, student_id)

    async def a_get_student_by_id(self, student_id: str) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_student_by_id, student_id)

    async def a_get_student_by_chat_id(
        self, chat_id: int | str
    ) -> Optional[tuple[dict[str, Any], str]]:
        return await asyncio.to_thread(self.get_student_by_chat_id, chat_id)

    async def a_get_students_by_chat_id(
        self, chat_id: int | str
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.get_students_by_chat_id, chat_id)

    async def a_get_children_by_parent_chat_id(
        self, chat_id: int | str
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_children_by_parent_chat_id, chat_id
        )

    async def a_sync_student_across_all_sheets(
        self,
        student_id: str,
        old_fio: str = "",
        new_fio: str = "",
        updated_fields: Optional[dict[str, Any]] = None,
    ) -> int:
        return await asyncio.to_thread(
            self.sync_student_across_all_sheets,
            student_id,
            old_fio,
            new_fio,
            updated_fields,
        )

    async def a_add_student(
        self,
        full_name: str = "",
        group_name: str = "",
        student_phone: str = "",
        student_tg: str = "",
        parent_phone: str = "",
        status: str = "O'qiyapti",
        student_chat_id: int | str = "",
        father_name: str = "",
        father_phone: str = "",
        father_chat_id: int | str = "",
        mother_name: str = "",
        mother_phone: str = "",
        mother_chat_id: int | str = "",
        debt_months: Optional[str] = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.add_student,
            full_name,
            group_name,
            student_phone,
            student_tg,
            parent_phone,
            status,
            student_chat_id,
            father_name,
            father_phone,
            father_chat_id,
            mother_name,
            mother_phone,
            mother_chat_id,
            debt_months,
        )

    async def a_update_student(
        self, student_id: str, updates: dict[str, Any]
    ) -> bool:
        return await asyncio.to_thread(self.update_student, student_id, updates)

    async def a_remove_student_from_cycle_sheet(
        self,
        group_name: str,
        student_id: str,
        year: Optional[int] = None,
    ) -> bool:
        return await asyncio.to_thread(
            self.remove_student_from_cycle_sheet, group_name, student_id, year
        )

    async def a_add_student_to_active_cycle(
        self,
        group_name: str,
        student_id: str,
        full_name: str,
        year: Optional[int] = None,
        charge_upfront: bool = False,
    ) -> bool:
        return await asyncio.to_thread(
            self.add_student_to_active_cycle,
            group_name,
            student_id,
            full_name,
            year,
            charge_upfront,
        )

    async def a_restore_student_from_reserve(
        self, student_id: str, new_group_name: str
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.restore_student_from_reserve, student_id, new_group_name
        )

    async def a_move_student_to_reserve(self, student_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.move_student_to_reserve, student_id)

    async def a_get_student_unpaid_cycles(
        self, group_name: str, student_id: str, student_fio: str = ""
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_student_unpaid_cycles, group_name, student_id, student_fio
        )

    async def a_get_unpaid_cycles_for_students(
        self, students: list[dict[str, Any]]
    ) -> dict[str, list[dict[str, Any]]]:
        return await asyncio.to_thread(self.get_unpaid_cycles_for_students, students)

    async def a_append_lead(self, lead: dict[str, Any]) -> bool:
        return await asyncio.to_thread(self.append_lead, lead)

    async def a_switch_parent_role(
        self, chat_id: int | str, new_type: str
    ) -> list[str]:
        return await asyncio.to_thread(self.switch_parent_role, chat_id, new_type)

    async def a_get_lead_snapshot(self) -> dict[str, Any]:
        return await asyncio.to_thread(self.get_lead_snapshot)

    async def a_get_lead_status_by_chat_id(self, chat_id: Any) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_lead_status_by_chat_id, chat_id)

    async def a_mark_lead_contacted(self, lead_id: Any, chat_id: Any = None) -> bool:
        return await asyncio.to_thread(self.mark_lead_contacted, lead_id, chat_id)

    async def a_update_student_self_profile(
        self,
        chat_id: int | str,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> list[str]:
        return await asyncio.to_thread(
            self.update_student_self_profile, chat_id, full_name, phone
        )

    async def a_update_parent_self_profile(
        self,
        chat_id: int | str,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> list[str]:
        return await asyncio.to_thread(
            self.update_parent_self_profile, chat_id, full_name, phone
        )

    async def a_update_teacher_self_profile(
        self,
        chat_id: int | str,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> bool:
        return await asyncio.to_thread(
            self.update_teacher_self_profile, chat_id, full_name, phone
        )

    async def a_delete_student(self, student_id: str) -> bool:
        return await asyncio.to_thread(self.delete_student, student_id)

    async def a_purge_student_completely(self, student_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.purge_student_completely, student_id)

    async def a_purge_teacher_completely(self, teacher_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self.purge_teacher_completely, teacher_id)

    async def a_transfer_or_enroll_student(
        self,
        student_id: str,
        target_group: str,
        keep_in_old_group: bool,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.transfer_or_enroll_student,
            student_id,
            target_group,
            keep_in_old_group,
        )

    async def a_link_student_chat_id(
        self,
        student_id: str,
        chat_id: int | str,
        is_parent: bool = False,
        telegram_username: Optional[str] = None,
        parent_type: Optional[str] = None,
        parent_name: Optional[str] = None,
        parent_phone: Optional[str] = None,
    ) -> bool:
        return await asyncio.to_thread(
            self.link_student_chat_id,
            student_id,
            chat_id,
            is_parent,
            telegram_username,
            parent_type,
            parent_name,
            parent_phone,
        )

    async def a_bind_parent_to_students(
        self,
        student_ids: str | list[str] | tuple[str, ...] | set[str],
        parent_chat_id: int | str,
        parent_type: Optional[str] = None,
        parent_name: Optional[str] = None,
        parent_phone: Optional[str] = None,
    ) -> list[str]:
        return await asyncio.to_thread(
            self.bind_parent_to_students,
            student_ids,
            parent_chat_id,
            parent_type,
            parent_name,
            parent_phone,
        )

    async def a_attach_student_device_info(
        self,
        student_id: str,
        new_phone: Optional[str] = None,
        student_chat_id: Optional[int | str] = None,
        telegram_username: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(
            self.attach_student_device_info,
            student_id,
            new_phone,
            student_chat_id,
            telegram_username,
        )

    async def a_get_student_cycle_lesson_stats(
        self,
        group_name: str,
        student_id: str,
        student_fio: str = "",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.get_student_cycle_lesson_stats,
            group_name,
            student_id,
            student_fio,
        )

    async def a_get_debtors(
        self, group_name: Optional[str] = None
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.get_debtors, group_name)

    async def a_get_all_teachers(
        self, active_only: bool = False
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.get_all_teachers, active_only)

    async def a_get_all_teachers_detailed(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.get_all_teachers_detailed)

    async def a_get_teacher(
        self, teacher_id_or_chat_id: str | int
    ) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_teacher, teacher_id_or_chat_id)

    async def a_get_teacher_by_id(
        self, teacher_id: str
    ) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_teacher_by_id, teacher_id)

    async def a_get_teacher_by_chat_id(
        self, chat_id: int | str
    ) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_teacher_by_chat_id, chat_id)

    async def a_add_teacher(
        self,
        full_name: str = "",
        phone: str = "",
        tg_username: str = "",
        chat_id: int | str = "",
        status: str = "Faol",
        teacher_id: str = "",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.add_teacher,
            full_name,
            phone,
            tg_username,
            chat_id,
            status,
            teacher_id,
        )

    async def a_update_teacher(
        self, teacher_id: str, updates: dict[str, Any]
    ) -> bool:
        return await asyncio.to_thread(self.update_teacher, teacher_id, updates)

    async def a_link_teacher_chat_id(
        self,
        teacher_id: str,
        chat_id: int | str,
        telegram_username: Optional[str] = None,
        full_name: Optional[str] = None,
        phone: Optional[str] = None,
    ) -> bool:
        return await asyncio.to_thread(
            self.link_teacher_chat_id,
            teacher_id,
            chat_id,
            telegram_username,
            full_name,
            phone,
        )

    async def a_register_teacher_and_assign_group(
        self,
        teacher_data: dict[str, Any],
        target_group_name: Optional[str] = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.register_teacher_and_assign_group,
            teacher_data,
            target_group_name,
        )

    async def a_assign_teacher_to_group(
        self, teacher_id: str, group_name: str
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.assign_teacher_to_group, teacher_id, group_name
        )

    async def a_delete_teacher_completely(self, teacher_id: str) -> str:
        return await asyncio.to_thread(self.delete_teacher_completely, teacher_id)

    async def a_get_all_groups(self) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.get_all_groups)

    async def a_get_groups_for_role(
        self, user_chat_id: int | str, is_admin: bool = False
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_groups_for_role, user_chat_id, is_admin
        )

    async def a_get_all_groups_for_user(
        self, user_chat_id: int | str, is_admin: bool = False
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_all_groups_for_user, user_chat_id, is_admin
        )

    async def a_get_group(self, group_name: str) -> Optional[dict[str, Any]]:
        return await asyncio.to_thread(self.get_group, group_name)

    async def a_add_group(
        self,
        group_name: str,
        teacher_chat_id: int | str = "",
        tg_chat_id: int | str = "",
        lessons_per_month: int = 12,
        lesson_days: str = "",
        lesson_time: str = "",
        teacher_id: str = "",
        monthly_price: int | str = "",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.add_group,
            group_name,
            teacher_chat_id,
            tg_chat_id,
            lessons_per_month,
            lesson_days,
            lesson_time,
            teacher_id,
            monthly_price,
        )

    async def a_create_group(
        self,
        group_name: str,
        teacher_chat_id: int | str = "",
        tg_chat_id: int | str = "",
        lessons_per_month: int = 12,
        lesson_days: str = "",
        lesson_time: str = "",
        teacher_id: str = "",
        monthly_price: int | str = "",
        start_date: Optional[date] = None,
        create_cycle: bool = True,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.create_group,
            group_name,
            teacher_chat_id,
            tg_chat_id,
            lessons_per_month,
            lesson_days,
            lesson_time,
            teacher_id,
            monthly_price,
            start_date,
            create_cycle,
        )

    async def a_delete_group_completely(self, group_name: str) -> bool:
        return await asyncio.to_thread(self.delete_group_completely, group_name)

    async def a_update_group(
        self, group_name: str, updates: dict[str, Any]
    ) -> bool:
        return await asyncio.to_thread(self.update_group, group_name, updates)

    async def a_update_group_full_info(
        self, old_group_name: str, updates: dict[str, Any]
    ) -> bool:
        return await asyncio.to_thread(
            self.update_group_full_info, old_group_name, updates
        )

    async def a_update_group_price(
        self, group_name: str, price_uzs: int | str
    ) -> bool:
        return await asyncio.to_thread(self.update_group_price, group_name, price_uzs)

    async def a_create_cycle_table(
        self,
        group_name: str,
        start_date: date,
        cycle_number: Optional[int] = None,
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.create_cycle_table, group_name, start_date, cycle_number, year
        )

    async def a_create_new_cycle(
        self,
        group_name: str,
        start_date: Optional[date] = None,
        cycle_number: Optional[int] = None,
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.create_new_cycle, group_name, start_date, cycle_number, year
        )

    async def a_rebuild_active_cycle_sheet(
        self,
        group_name: str,
        new_lesson_count: int,
        new_days: str | list[int],
        new_time: str,
    ) -> list[str]:
        return await asyncio.to_thread(
            self.rebuild_active_cycle_sheet,
            group_name,
            new_lesson_count,
            new_days,
            new_time,
        )

    async def a_get_cycle_dates_with_status(
        self,
        group_name: str,
        year: Optional[int] = None,
        lang: str = "latn",
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_cycle_dates_with_status, group_name, year, lang
        )

    async def a_get_student_current_cycle_lessons(
        self,
        group_name: str,
        student_id: str,
        student_fio: str = "",
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_student_current_cycle_lessons, group_name, student_id, student_fio
        )

    async def a_get_group_lesson_dates_categorized(
        self,
        group_name: str,
        today_str: str = "",
        lang: str = "latn",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.get_group_lesson_dates_categorized, group_name, today_str, lang
        )

    async def a_save_attendance_for_date(
        self,
        group_name: str,
        target_date_str: str,
        attendance_dict: dict[str, str],
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                self.save_attendance_for_date,
                group_name,
                target_date_str,
                attendance_dict,
                year,
            )
        finally:
            self._cycle_snapshot_cache.clear()

    async def a_confirm_student_payment(
        self,
        student_id: str,
        group_name: str,
        cycle_title: Optional[str] = None,
        year: Optional[int] = None,
    ) -> bool:
        return await asyncio.to_thread(
            self.confirm_student_payment,
            student_id,
            group_name,
            cycle_title,
            year,
        )

    async def a_revert_student_payment(
        self,
        student_id: str,
        group_name: str,
        cycle_title: Optional[str] = None,
        year: Optional[int] = None,
    ) -> bool:
        return await asyncio.to_thread(
            self.revert_student_payment,
            student_id,
            group_name,
            cycle_title,
            year,
        )

    async def a_get_student_cycle_history(
        self,
        group_name: str,
        student_id: str,
        year: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_student_cycle_history, group_name, student_id, year
        )

    async def a_is_teacher(self, chat_id: int | str) -> bool:
        return await asyncio.to_thread(self.is_teacher, chat_id)

    async def a_link_group_tg_chat(
        self, group_name: str, tg_chat_id: int | str
    ) -> bool:
        return await asyncio.to_thread(self.link_group_tg_chat, group_name, tg_chat_id)


_default_sheets_manager: Optional[SheetsManager] = None


def get_sheets_manager() -> SheetsManager:
    global _default_sheets_manager
    if _default_sheets_manager is None:
        _default_sheets_manager = SheetsManager()
    return _default_sheets_manager
