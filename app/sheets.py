import asyncio
import re
import threading
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any, Optional

import gspread
from google.oauth2.service_account import Credentials

import app.config as _app_config
from app.config import (
    CREDENTIALS_PATH,
    GROUP_SHEET_NAME,
    SPREADSHEET_ID,
    STUDENT_SHEET_NAME,
    TZ,
)
from app.locales import MONTHS_UPPER_LATN, WEEKDAYS_SHORT

TEACHER_SHEET_NAME = getattr(_app_config, "TEACHER_SHEET_NAME", "Ustozlar")

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
]

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


def _normalize_read_value(val: Any) -> str:
    if val is None:
        return ""
    cleaned = str(val).strip()
    if cleaned == MISSING_TEXT:
        return ""
    return cleaned


def _is_paid_status(status_val: str) -> bool:
    val = (status_val or "").strip().lower()
    if not val or "to'lanmagan" in val or "тўланмаган" in val:
        return False
    return "✅" in val or "to'langan" in val or "тўланган" in val


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
        today = datetime.now(TZ).date()
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

    def _get_spreadsheet(self) -> gspread.Spreadsheet:
        with self._lock:
            if self._spreadsheet is None:
                creds = Credentials.from_service_account_file(
                    self._credentials_path, scopes=SCOPES
                )
                self._client = gspread.authorize(creds)
                self._spreadsheet = self._client.open_by_key(self._spreadsheet_id)
            return self._spreadsheet

    def _get_or_create_worksheet(
        self, title: str, headers: Optional[list[str]] = None, rows: int = 200, cols: int = 26
    ) -> gspread.Worksheet:
        with self._lock:
            ss = self._get_spreadsheet()
            try:
                ws = ss.worksheet(title)
            except gspread.WorksheetNotFound:
                ws = ss.add_worksheet(title=title, rows=rows, cols=cols)
                if headers:
                    ws.update("A1", [headers], value_input_option="USER_ENTERED")
                    ss.batch_update(
                        {
                            "requests": [
                                _cell_bg_request(
                                    ws.id, 0, 1, 0, len(headers), COLOR_HEADER_GRAY, bold=True
                                )
                            ]
                        }
                    )
            else:
                if headers:
                    existing_first_row = ws.row_values(1)
                    if not existing_first_row:
                        ws.update("A1", [headers], value_input_option="USER_ENTERED")
            return ws

    def _ensure_missing_headers(
        self, ws: gspread.Worksheet, expected_headers: list[str]
    ) -> list[str]:
        headers = ws.row_values(1)
        if not headers:
            ws.update("A1", [expected_headers], value_input_option="USER_ENTERED")
            return list(expected_headers)
        missing = [h for h in expected_headers if h not in headers]
        if missing:
            start_col = len(headers)
            needed_cols = start_col + len(missing)
            if ws.col_count < needed_cols:
                ws.resize(cols=needed_cols + 2)
            a1 = f"{_col_letter(start_col)}1"
            ws.update(a1, [missing], value_input_option="USER_ENTERED")
            headers = headers + missing
        return headers

    def _cleanup_teacher_sheet_headers(self, ws: gspread.Worksheet) -> list[str]:
        """
        Ensures Ustozlar has ONLY ONE username column ('TG_Username') by removing
        any duplicate 'Telegram' column if present.
        """
        headers = ws.row_values(1)
        if not headers:
            ws.update("A1", [TEACHER_HEADERS], value_input_option="USER_ENTERED")
            return list(TEACHER_HEADERS)

        if "Telegram" in headers:
            tg_dup_idx = headers.index("Telegram")
            if "TG_Username" not in headers:
                ws.update(
                    f"{_col_letter(tg_dup_idx)}1",
                    [["TG_Username"]],
                    value_input_option="USER_ENTERED",
                )
            else:
                tg_main_idx = headers.index("TG_Username")
                all_rows = ws.get_all_values()
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
                    ws.batch_update(updates, value_input_option="USER_ENTERED")
                ws.delete_columns(tg_dup_idx + 1)

        return self._ensure_missing_headers(ws, TEACHER_HEADERS)

    def _append_row_and_get_index(
        self, ws: gspread.Worksheet, row_values: list[Any]
    ) -> int:
        resp = ws.append_row(row_values, value_input_option="USER_ENTERED")
        updated_range = ""
        if isinstance(resp, dict):
            updated_range = (resp.get("updates") or {}).get("updatedRange", "")
        match = re.search(r"!(?:[A-Z]+)(\d+)", updated_range)
        if match:
            return int(match.group(1))
        return max(len(ws.get_all_values()), 2)

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
            headers = ws.row_values(1)
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
                ws.resize(cols=total_cols + 2)
            if ws.row_count < row_idx:
                ws.resize(rows=row_idx + 20)

            end_col_letter = _col_letter(total_cols - 1)
            ws.update(
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
                ss.batch_update({"requests": requests})

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

    # ------------------------------------------------------------------
    # CRUD: Baza_Talabalar
    # ------------------------------------------------------------------

    def get_all_students(
        self, group_name: Optional[str] = None, active_only: bool = False
    ) -> list[dict[str, Any]]:
        with self._lock:
            ws = self._get_or_create_worksheet(
                STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
            )
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []

            headers = rows[0]
            students: list[dict[str, Any]] = []
            for idx, raw_row in enumerate(rows[1:], start=2):
                padded = raw_row + [""] * (len(headers) - len(raw_row))
                record: dict[str, Any] = {
                    h: _normalize_read_value(v) for h, v in zip(headers, padded)
                }
                for h in STUDENT_HEADERS:
                    record.setdefault(h, "")
                record["_row_number"] = idx
                if not record.get("Talaba_ID"):
                    continue
                if group_name and record.get("Guruh", "").strip().lower() != group_name.strip().lower():
                    continue
                if active_only and record.get("Status", "").strip() != "O'qiyapti":
                    continue
                students.append(record)
            return students

    def get_student_by_id(self, student_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            target = _normalize_read_value(student_id)
            if not target:
                return None
            for student in self.get_all_students():
                if student.get("Talaba_ID", "").strip() == target:
                    return student
            return None

    def get_student(self, student_id: str) -> Optional[dict[str, Any]]:
        return self.get_student_by_id(student_id)

    def get_student_by_chat_id(
        self, chat_id: int | str
    ) -> Optional[tuple[dict[str, Any], str]]:
        with self._lock:
            target = _normalize_read_value(chat_id)
            if not target:
                return None
            for student in self.get_all_students():
                if str(student.get("Talaba_Chat_ID", "")).strip() == target:
                    return student, "student"
                if str(student.get("Otasi_Chat_ID", "")).strip() == target:
                    return student, "parent"
                if str(student.get("Onasi_Chat_ID", "")).strip() == target:
                    return student, "parent"
                if str(student.get("OtaOna_Chat_ID", "")).strip() == target:
                    return student, "parent"
            return None

    def get_students_by_chat_id(
        self, chat_id: int | str
    ) -> list[dict[str, Any]]:
        """Returns all student enrollment records matching Talaba_Chat_ID."""
        with self._lock:
            target = _normalize_read_value(chat_id)
            if not target:
                return []
            return [
                student
                for student in self.get_all_students()
                if str(student.get("Talaba_Chat_ID", "")).strip() == target
            ]

    def get_children_by_parent_chat_id(
        self, chat_id: int | str
    ) -> list[dict[str, Any]]:
        """Returns all student enrollment records linked to a parent's chat_id."""
        with self._lock:
            target = _normalize_read_value(chat_id)
            if not target:
                return []
            matches: list[dict[str, Any]] = []
            for student in self.get_all_students():
                if (
                    str(student.get("Otasi_Chat_ID", "")).strip() == target
                    or str(student.get("Onasi_Chat_ID", "")).strip() == target
                    or str(student.get("OtaOna_Chat_ID", "")).strip() == target
                ):
                    matches.append(student)
            return matches

    def _generate_next_student_id(self, existing_students: list[dict[str, Any]]) -> str:
        max_num = 0
        for s in existing_students:
            sid = s.get("Talaba_ID", "").strip()
            m = re.search(r"(\d+)$", sid)
            if m:
                max_num = max(max_num, int(m.group(1)))
        return f"ST{max_num + 1:03d}"

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
        debt_months: str = "0",
    ) -> dict[str, Any]:
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

            debt_val = _normalize_read_value(debt_months) or "0"
            row_map = {
                "Talaba_ID": student_id,
                "F.I.O.": _normalize_read_value(full_name),
                "Guruh": _normalize_read_value(group_name),
                "Talaba_Tel": _normalize_read_value(student_phone),
                "Talaba_TG": tg_val,
                "Talaba_Chat_ID": _normalize_read_value(student_chat_id),
                "Otasi_FIO": _normalize_read_value(father_name),
                "Otasi_Tel": _normalize_read_value(father_phone),
                "Otasi_Chat_ID": _normalize_read_value(father_chat_id),
                "Onasi_FIO": _normalize_read_value(mother_name),
                "Onasi_Tel": _normalize_read_value(mother_phone),
                "Onasi_Chat_ID": _normalize_read_value(mother_chat_id),
                "OtaOna_Tel": _normalize_read_value(parent_phone),
                "OtaOna_Chat_ID": "",
                "Status": _normalize_read_value(status),
                "Qarzdor_Oylar": debt_val,
            }
            new_row = [row_map.get(h, "") for h in headers]
            new_row_idx = self._append_row_and_get_index(ws, new_row)
            self._sync_row_missing_cells(
                ws, new_row_idx, new_row, exclude_cols={"Qarzdor_Oylar"}
            )
            return self.get_student_by_id(student_id) or {
                h: _normalize_read_value(row_map.get(h, "")) for h in headers
            }

    def update_student(self, student_id: str, updates: dict[str, Any]) -> bool:
        with self._lock:
            ws = self._get_or_create_worksheet(
                STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
            )
            headers = self._ensure_missing_headers(ws, STUDENT_HEADERS)
            student = self.get_student_by_id(student_id)
            if not student:
                return False
            row_num = student["_row_number"]
            raw_row = ws.row_values(row_num)
            row_values = raw_row + [""] * (len(headers) - len(raw_row))
            for key, value in updates.items():
                if key in headers:
                    col_idx = headers.index(key)
                    row_values[col_idx] = "" if value is None else str(value)
            if "Qarzdor_Oylar" in headers:
                q_idx = headers.index("Qarzdor_Oylar")
                q_val = str(row_values[q_idx]).strip()
                if not q_val or q_val == MISSING_TEXT:
                    row_values[q_idx] = "0"
            self._sync_row_missing_cells(
                ws, row_num, row_values, exclude_cols={"Qarzdor_Oylar"}
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

            for cycle_ws in ss.worksheets():
                title_lower = cycle_ws.title.lower()
                if year is not None:
                    if title_lower != prefix_lower:
                        continue
                elif not title_lower.startswith(prefix_lower):
                    continue

                all_vals = cycle_ws.get_all_values()
                rows_to_delete = [
                    idx
                    for idx, raw_row in enumerate(all_vals, start=1)
                    if raw_row and raw_row[0].strip() == target_id
                ]
                for row_num in reversed(rows_to_delete):
                    cycle_ws.delete_rows(row_num)
                    removed_any = True

            return removed_any

    def add_student_to_active_cycle(
        self,
        group_name: str,
        student_id: str,
        full_name: str,
        year: Optional[int] = None,
    ) -> bool:
        """
        Inserts the student right below the header row of the active cycle in
        {group_name}_{year}.
        """
        with self._lock:
            target_group = group_name.strip()
            target_id = student_id.strip()
            if not target_group or not target_id:
                return False

            ss = self._get_spreadsheet()
            now_year = year or datetime.now(TZ).year
            ws: Optional[gspread.Worksheet] = None
            cycles: list[dict[str, Any]] = []

            for y in ([year] if year else [now_year, now_year - 1]):
                try:
                    candidate_ws = ss.worksheet(f"{target_group}_{y}")
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
                r["student_id"].strip() == target_id
                for r in latest["student_rows"]
            ):
                return True

            insert_row_0 = latest["header_row_idx"] + 1
            tolov_col_idx = latest["tolov_col_idx"]
            row_data = [target_id, full_name] + [""] * max(0, tolov_col_idx - 1)
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
            return True

    def delete_student(self, student_id: str) -> bool:
        """
        Deletes ONLY the exact student_id row from Baza_Talabalar and that specific
        group's {Group}_{Year} sheet — never deleting by Talaba_Chat_ID.
        """
        with self._lock:
            target_id = student_id.strip()
            if not target_id:
                return False
            student = self.get_student_by_id(target_id)
            if not student:
                return False

            group_name = str(student.get("Guruh", "")).strip()
            if group_name:
                self.remove_student_from_cycle_sheet(group_name, target_id)

            ws = self._get_or_create_worksheet(
                STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=16
            )
            ws.delete_rows(int(student["_row_number"]))
            return True

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

            old_group = str(student.get("Guruh", "")).strip()
            grp_obj = self.get_group(target_group)
            canonical_target = (
                grp_obj["Guruh_Nomi"].strip() if grp_obj else target_group.strip()
            )

            full_name = str(student.get("F.I.O.", "")).strip()
            student_phone = str(student.get("Talaba_Tel", "")).strip()
            student_tg = str(student.get("Talaba_TG", "")).strip()
            student_chat_id = str(student.get("Talaba_Chat_ID", "")).strip()
            father_name = str(student.get("Otasi_FIO", "")).strip()
            father_phone = str(student.get("Otasi_Tel", "")).strip()
            father_chat_id = str(student.get("Otasi_Chat_ID", "")).strip()
            mother_name = str(student.get("Onasi_FIO", "")).strip()
            mother_phone = str(student.get("Onasi_Tel", "")).strip()
            mother_chat_id = str(student.get("Onasi_Chat_ID", "")).strip()
            parent_phone = str(student.get("OtaOna_Tel", "")).strip()
            parent_chat_id = str(student.get("OtaOna_Chat_ID", "")).strip()
            status = str(student.get("Status", "")).strip() or "O'qiyapti"
            debt_months = str(student.get("Qarzdor_Oylar", "")).strip() or "0"

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
                    debt_months=debt_months,
                )
                new_id = new_student["Talaba_ID"]
                if parent_chat_id:
                    self.update_student(new_id, {"OtaOna_Chat_ID": parent_chat_id})
                    new_student = self.get_student_by_id(new_id) or new_student

                self.add_student_to_active_cycle(
                    canonical_target, new_id, full_name
                )
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
        if is_parent:
            p_type = (parent_type or "").strip().lower()
            if p_type in {"father", "otasi", "ota"}:
                updates["Otasi_Chat_ID"] = str(chat_id)
                if parent_name is not None:
                    updates["Otasi_FIO"] = parent_name
                if parent_phone is not None:
                    updates["Otasi_Tel"] = parent_phone
            elif p_type in {"mother", "onasi", "ona"}:
                updates["Onasi_Chat_ID"] = str(chat_id)
                if parent_name is not None:
                    updates["Onasi_FIO"] = parent_name
                if parent_phone is not None:
                    updates["Onasi_Tel"] = parent_phone
            else:
                updates["OtaOna_Chat_ID"] = str(chat_id)
                updates["Otasi_Chat_ID"] = str(chat_id)
                if parent_name is not None:
                    updates["Otasi_FIO"] = parent_name
                if parent_phone is not None:
                    updates["OtaOna_Tel"] = parent_phone
                    updates["Otasi_Tel"] = parent_phone
        else:
            updates["Talaba_Chat_ID"] = str(chat_id)
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

    def get_debtors(self, group_name: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            students = self.get_all_students(group_name=group_name)
            debtors: list[dict[str, Any]] = []
            for s in students:
                debt_val = s.get("Qarzdor_Oylar", "").strip()
                if debt_val and debt_val != "0":
                    debtors.append(s)
            return debtors

    # ------------------------------------------------------------------
    # CRUD: Ustozlar
    # ------------------------------------------------------------------

    def get_all_teachers(self, active_only: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            ws = self._get_or_create_worksheet(
                TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=100, cols=10
            )
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []
            headers = rows[0]
            teachers: list[dict[str, Any]] = []
            for idx, raw_row in enumerate(rows[1:], start=2):
                padded = raw_row + [""] * (len(headers) - len(raw_row))
                record: dict[str, Any] = {
                    h: _normalize_read_value(v) for h, v in zip(headers, padded)
                }
                for h in TEACHER_HEADERS:
                    record.setdefault(h, "")
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
            target = _normalize_read_value(chat_id)
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
            raw_row = ws.row_values(row_num)
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
                        self._get_spreadsheet().batch_update(
                            {"requests": bg_requests}
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
                self._get_spreadsheet().batch_update({"requests": requests})

            updated_teacher = self.get_teacher_by_id(t_id) or teacher
            return {
                "group": updated_group,
                "teacher": updated_teacher,
            }

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

            t_id = str(teacher.get("Ustoz_ID", "")).strip()
            t_chat_id = str(
                teacher.get("Chat_ID") or teacher.get("Ustoz_Chat_ID") or ""
            ).strip()
            row_num = teacher.get("_row_number")

            ws_teachers = self._get_or_create_worksheet(
                TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=100, cols=10
            )
            if row_num:
                ws_teachers.delete_rows(int(row_num))

            for grp in self.get_all_groups():
                g_tid = str(grp.get("Ustoz_ID", "")).strip()
                g_cid = str(grp.get("Ustoz_Chat_ID", "")).strip()
                if (t_id and g_tid == t_id) or (t_chat_id and g_cid == t_chat_id):
                    self.update_group(
                        grp["Guruh_Nomi"],
                        {
                            "Ustoz_ID": MISSING_TEXT,
                            "Ustoz_Chat_ID": MISSING_TEXT,
                        },
                    )

            return t_chat_id

    # ------------------------------------------------------------------
    # CRUD: Guruhlar
    # ------------------------------------------------------------------

    def get_all_groups(self) -> list[dict[str, Any]]:
        with self._lock:
            ws = self._get_or_create_worksheet(
                GROUP_SHEET_NAME, headers=GROUP_HEADERS, rows=100, cols=12
            )
            rows = ws.get_all_values()
            if len(rows) <= 1:
                return []
            headers = rows[0]
            groups: list[dict[str, Any]] = []
            for idx, raw_row in enumerate(rows[1:], start=2):
                padded = raw_row + [""] * (len(headers) - len(raw_row))
                record: dict[str, Any] = {
                    h: _normalize_read_value(v) for h, v in zip(headers, padded)
                }
                for h in GROUP_HEADERS:
                    record.setdefault(h, "")
                record["_row_number"] = idx
                if not record.get("Guruh_Nomi"):
                    continue
                groups.append(record)
            return groups

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
            target = _normalize_read_value(teacher_chat_id)
            if not target:
                return []
            return [
                grp
                for grp in self.get_all_groups()
                if str(grp.get("Ustoz_Chat_ID", "")).strip() == target
            ]

    def is_teacher(self, chat_id: int | str) -> bool:
        target = _normalize_read_value(chat_id)
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
            return self.get_group(group_name) or {
                h: _normalize_read_value(row_map.get(h, "")) for h in headers
            }

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
            raw_row = ws.row_values(row_num)
            row_values = raw_row + [""] * (len(headers) - len(raw_row))
            for key, value in updates.items():
                if key in headers:
                    col_idx = headers.index(key)
                    row_values[col_idx] = "" if value is None else str(value)
            self._sync_row_missing_cells(ws, row_num, row_values)
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
                stu_rows = stu_ws.get_all_values()
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
                        stu_ws.batch_update(stu_updates, value_input_option="USER_ENTERED")

                ss = self._get_spreadsheet()
                prefix_lower = f"{old_canonical.lower()}_"
                for ws in ss.worksheets():
                    if ws.title.lower().startswith(prefix_lower):
                        suffix = ws.title[len(old_canonical) + 1 :]
                        try:
                            ws.update_title(f"{new_name}_{suffix}")
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
        return self._get_or_create_worksheet(sheet_title, headers=None, rows=300, cols=22)

    def parse_cycles_from_sheet(self, ws: gspread.Worksheet) -> list[dict[str, Any]]:
        with self._lock:
            all_values = ws.get_all_values()
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
        - cancelled_cols: columns with Red (#F4CCCC) background.
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
            meta = ss.fetch_sheet_metadata(
                params={"includeGridData": True, "ranges": [a1_range]}
            )
            sheets_data = meta.get("sheets", [])
            if not sheets_data:
                return marked_cols, cancelled_cols
            grid_data = sheets_data[0].get("data", [])
            if not grid_data:
                return marked_cols, cancelled_cols
            row_data = grid_data[0].get("rowData", [])
            date_col_indices = {dc["col_idx"] for dc in cycle["date_columns"]}

            for r_obj in row_data:
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
                    elif _color_matches(bg, RED_BG):
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
            now_year = datetime.now(TZ).year
            years_to_check = [year] if year else [now_year, now_year - 1]

            target_ws: Optional[gspread.Worksheet] = None
            cycles: list[dict[str, Any]] = []
            for y in years_to_check:
                sheet_title = f"{group_name.strip()}_{y}"
                try:
                    ws = ss.worksheet(sheet_title)
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
                    d_val, m_val = map(int, date_str.split("."))
                    if prev_date and m_val < prev_date.month:
                        running_year += 1
                    parsed_date = date(running_year, m_val, d_val)
                    prev_date = parsed_date
                    weekday_str = weekdays_map[parsed_date.weekday()]
                    full_date_iso = parsed_date.isoformat()
                except (ValueError, KeyError):
                    pass

                has_cell_marks = any(
                    s_row["marks"].get(col_idx, "").strip() in {"✅", "❌"}
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

    def create_cycle_table(
        self,
        group_name: str,
        start_date: date,
        cycle_number: Optional[int] = None,
        year: Optional[int] = None,
    ) -> dict[str, Any]:
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

            active_students = self.get_all_students(group_name=group_name, active_only=True)
            total_cols = len(header_row)

            all_values = ws.get_all_values()
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
                    + [""]
                )

            end_row_0 = start_row_0 + len(block_rows)
            needed_rows = end_row_0 + 20
            needed_cols = max(total_cols + 5, ws.col_count)
            if ws.row_count < needed_rows or ws.col_count < needed_cols:
                ws.resize(rows=max(ws.row_count, needed_rows), cols=needed_cols)

            start_a1 = f"A{start_row_0 + 1}"
            ws.update(start_a1, block_rows, value_input_option="USER_ENTERED")

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
                    end_row_0,
                    2,
                    tolov_col_0,
                    COLOR_WHITE,
                    bold=None,
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
                        tolov_col_0,
                        tolov_col_0 + 1,
                        COLOR_WHITE,
                        h_align="CENTER",
                    )
                )

            ss.batch_update({"requests": requests})

            return {
                "sheet_title": ws.title,
                "cycle_title": cycle_title,
                "cycle_number": cycle_number,
                "dates": date_strs,
                "start_date": date_strs[0],
                "end_date": date_strs[-1],
            }

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
            now_dt = datetime.now(TZ)
            now_year = now_dt.year
            anchor_date = _get_anchor_date_for_schedule(now_dt, str(new_time))

            target_ws: Optional[gspread.Worksheet] = None
            cycles: list[dict[str, Any]] = []
            for y in (now_year, now_year - 1):
                sheet_title = f"{group_name.strip()}_{y}"
                try:
                    ws = ss.worksheet(sheet_title)
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
                    p_status = existing_payment_by_sid.get(sid, "")
                    block_rows.append(
                        [sid, student["F.I.O."]] + [""] * len(date_strs) + [p_status]
                    )

                new_end_row_0 = title_row_0 + len(block_rows)
                max_end_row_0 = max(old_end_row_0, new_end_row_0)
                max_cols = max(old_total_cols, total_cols)

                if target_ws.row_count < max_end_row_0 + 20 or target_ws.col_count < max_cols + 5:
                    target_ws.resize(
                        rows=max(target_ws.row_count, max_end_row_0 + 20),
                        cols=max(target_ws.col_count, max_cols + 5),
                    )

                clear_range = (
                    f"A{title_row_0 + 1}:"
                    f"{_col_letter(max_cols - 1)}{max_end_row_0}"
                )
                target_ws.batch_clear([clear_range])
                target_ws.update(
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
                        new_end_row_0,
                        2,
                        tolov_col_0,
                        COLOR_WHITE,
                        bold=None,
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
                    requests.append(
                        _cell_bg_request(
                            target_ws.id,
                            data_start_0,
                            new_end_row_0,
                            tolov_col_0,
                            tolov_col_0 + 1,
                            COLOR_WHITE,
                            h_align="CENTER",
                        )
                    )
                    for idx_offset, student in enumerate(active_students):
                        p_status = existing_payment_by_sid.get(
                            student["Talaba_ID"], ""
                        )
                        if _is_paid_status(p_status):
                            r_0 = data_start_0 + idx_offset
                            requests.append(
                                _cell_bg_request(
                                    target_ws.id,
                                    r_0,
                                    r_0 + 1,
                                    tolov_col_0,
                                    tolov_col_0 + 1,
                                    GREEN_BG,
                                    bold=True,
                                    h_align="CENTER",
                                )
                            )

                ss.batch_update({"requests": requests})
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
                target_ws.resize(cols=max_cols + 5)

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
                row_tail = [""] * len(upcoming_date_strs) + [s_row["payment_status"]]
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
                target_ws.batch_clear(clear_ranges)
            if value_updates:
                target_ws.batch_update(value_updates, value_input_option="USER_ENTERED")

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
                if header_row_0 + 1 < end_row_0:
                    requests.append(
                        _cell_bg_request(
                            target_ws.id,
                            header_row_0 + 1,
                            end_row_0,
                            upcoming_start_col_0,
                            new_tolov_col_0,
                            COLOR_WHITE,
                            bold=False,
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
                requests.append(
                    _cell_bg_request(
                        target_ws.id,
                        r_0,
                        r_0 + 1,
                        new_tolov_col_0,
                        new_tolov_col_0 + 1,
                        GREEN_BG if is_paid else COLOR_WHITE,
                        bold=is_paid,
                        h_align="CENTER",
                    )
                )

            requests.append(
                _borders_request(
                    target_ws.id, title_row_0, end_row_0, 0, new_total_cols
                )
            )
            ss.batch_update({"requests": requests})

            return final_date_strs

    def _find_cycle_for_date_str(
        self, group_name: str, target_date_str: str, year: Optional[int] = None
    ) -> Optional[tuple[gspread.Worksheet, dict[str, Any], int]]:
        target_str = target_date_str.strip()
        now_year = datetime.now(TZ).year
        candidate_years = [year] if year else [now_year, now_year - 1]
        ss = self._get_spreadsheet()

        for y in candidate_years:
            sheet_title = f"{group_name.strip()}_{y}"
            try:
                ws = ss.worksheet(sheet_title)
            except gspread.WorksheetNotFound:
                continue
            cycles = self.parse_cycles_from_sheet(ws)
            for cycle in reversed(cycles):
                for dc in cycle["date_columns"]:
                    if dc["date_str"] == target_str:
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
                ws = ss.worksheet(sheet_title)
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

            sheet_year = int(ws.title.rsplit("_", 1)[-1]) if "_" in ws.title else cancel_date.year
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
                ws.resize(cols=new_tolov_col_idx + 5)

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
            ws.batch_update(value_updates, value_input_option="USER_ENTERED")

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
                    header_row_0 + 1,
                    end_row_0,
                    tolov_col_idx,
                    tolov_col_idx + 1,
                    COLOR_WHITE,
                    bold=False,
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
                _cell_bg_request(
                    ws.id,
                    header_row_0 + 1,
                    end_row_0,
                    new_tolov_col_idx,
                    new_tolov_col_idx + 1,
                    COLOR_WHITE,
                    bold=False,
                    h_align="CENTER",
                ),
                _borders_request(ws.id, title_row_0, end_row_0, 0, new_tolov_col_idx + 1),
            ]
            ss.batch_update({"requests": requests})

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
        Writes ✅/❌ into target_date_str column for each student and colors cells Yellow (#FFF2CC).
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

            found = self._find_cycle_for_date_str(group_name, date_str, year)
            if not found:
                raise ValueError(
                    f"Date '{date_str}' not found in active cycle for group '{group_name}'"
                )

            ws, cycle, date_col_idx = found
            ss = self._get_spreadsheet()

            has_existing_marks = any(
                s_row["marks"].get(date_col_idx, "").strip() in {"✅", "❌"}
                for s_row in cycle["student_rows"]
            )
            marked_bg_cols, _ = self._get_cycle_colored_columns(ws, cycle)
            was_unmarked = not (has_existing_marks or (date_col_idx in marked_bg_cols))

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
                ws.batch_update(value_updates, value_input_option="USER_ENTERED")
            if color_requests:
                ss.batch_update({"requests": color_requests})

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
                red_requests: list[dict[str, Any]] = []
                for s_row in cycle["student_rows"]:
                    if not _is_paid_status(s_row.get("payment_status", "")):
                        r_idx_0 = s_row["row_idx"]
                        red_requests.append(
                            _cell_bg_request(
                                ws.id,
                                r_idx_0,
                                r_idx_0 + 1,
                                2,
                                tolov_col_idx + 1,
                                RED_BG,
                                h_align="CENTER",
                            )
                        )
                if red_requests:
                    ss.batch_update({"requests": red_requests})

            return {
                "sheet_title": ws.title,
                "cycle_title": cycle["title"],
                "date_str": date_str,
                "marked_count": len(value_updates),
                "was_unmarked": was_unmarked,
                "lesson_count": lesson_count,
                "lessons_limit": lessons_limit,
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

    def _locate_student_cycle(
        self,
        student_id: str,
        group_name: str,
        cycle_title: Optional[str] = None,
        year: Optional[int] = None,
        prefer_paid: Optional[bool] = None,
    ) -> Optional[tuple[gspread.Worksheet, dict[str, Any], dict[str, Any], bool]]:
        ss = self._get_spreadsheet()
        now_year = datetime.now(TZ).year
        years_to_check = [year] if year else [now_year, now_year - 1]
        clean_sid = student_id.strip()

        candidates: list[tuple[gspread.Worksheet, dict[str, Any], dict[str, Any], bool]] = []
        for y in years_to_check:
            sheet_title = f"{group_name.strip()}_{y}"
            try:
                ws = ss.worksheet(sheet_title)
            except gspread.WorksheetNotFound:
                continue
            cycles = self.parse_cycles_from_sheet(ws)
            for idx, cycle in enumerate(cycles):
                is_latest_cycle = (y == years_to_check[0]) and (idx == len(cycles) - 1)
                if cycle_title and cycle["title"].strip() != cycle_title.strip():
                    continue
                student_row = next(
                    (
                        s
                        for s in cycle["student_rows"]
                        if s["student_id"].strip() == clean_sid
                    ),
                    None,
                )
                if student_row:
                    candidates.append((ws, cycle, student_row, is_latest_cycle))

        if not candidates:
            return None

        if cycle_title is None and prefer_paid is not None:
            for item in reversed(candidates):
                is_paid = _is_paid_status(item[2].get("payment_status", ""))
                if is_paid == prefer_paid:
                    return item

        return candidates[-1]

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
            tolov_col_0 = target_cycle["tolov_col_idx"]

            target_ws.update(
                f"{_col_letter(tolov_col_0)}{r_idx_0 + 1}",
                [["To'langan"]],
                value_input_option="USER_ENTERED",
            )

            requests: list[dict[str, Any]] = [
                _cell_bg_request(
                    target_ws.id,
                    r_idx_0,
                    r_idx_0 + 1,
                    2,
                    tolov_col_0,
                    GREEN_BG,
                    h_align="CENTER",
                ),
                _cell_bg_request(
                    target_ws.id,
                    r_idx_0,
                    r_idx_0 + 1,
                    tolov_col_0,
                    tolov_col_0 + 1,
                    GREEN_BG,
                    bold=True,
                    h_align="CENTER",
                ),
            ]
            self._get_spreadsheet().batch_update({"requests": requests})
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
        RED_BG (if cycle is finished) or YELLOW_BG / WHITE_BG (if cycle is still ongoing).
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
            tolov_col_0 = target_cycle["tolov_col_idx"]

            target_ws.update(
                f"{_col_letter(tolov_col_0)}{r_idx_0 + 1}",
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
                    student_row["marks"].get(dc["col_idx"], "").strip() in {"✅", "❌"}
                    for dc in target_cycle["date_columns"]
                )

            requests: list[dict[str, Any]] = []
            if is_finished:
                requests.append(
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
            else:
                for dc in target_cycle["date_columns"]:
                    c_idx_0 = dc["col_idx"]
                    mark = student_row["marks"].get(c_idx_0, "").strip()
                    bg = YELLOW_BG if mark in {"✅", "❌"} else WHITE_BG
                    requests.append(
                        _cell_bg_request(
                            target_ws.id,
                            r_idx_0,
                            r_idx_0 + 1,
                            c_idx_0,
                            c_idx_0 + 1,
                            bg,
                            h_align="CENTER",
                        )
                    )
                requests.append(
                    _cell_bg_request(
                        target_ws.id,
                        r_idx_0,
                        r_idx_0 + 1,
                        tolov_col_0,
                        tolov_col_0 + 1,
                        WHITE_BG,
                        bold=False,
                        h_align="CENTER",
                    )
                )

            self._get_spreadsheet().batch_update({"requests": requests})
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
            target_year = year or datetime.now(TZ).year
            sheet_title = f"{group_name.strip()}_{target_year}"
            try:
                ws = ss.worksheet(sheet_title)
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
                    if mark == "✅":
                        present_count += 1
                    elif mark == "❌":
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
        debt_months: str = "0",
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
    ) -> bool:
        return await asyncio.to_thread(
            self.add_student_to_active_cycle,
            group_name,
            student_id,
            full_name,
            year,
        )

    async def a_delete_student(self, student_id: str) -> bool:
        return await asyncio.to_thread(self.delete_student, student_id)

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

    async def a_save_attendance_for_date(
        self,
        group_name: str,
        target_date_str: str,
        attendance_dict: dict[str, str],
        year: Optional[int] = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.save_attendance_for_date,
            group_name,
            target_date_str,
            attendance_dict,
            year,
        )

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
