import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _resolve_path(env_key: str, default_relative: str) -> Path:
    raw_value = os.getenv(env_key, default_relative).strip()
    path = Path(raw_value)
    if not path.is_absolute():
        path = BASE_DIR / path
    return path


def _parse_admin_ids(raw: str) -> list[int]:
    admin_ids: list[int] = []
    for item in raw.split(","):
        cleaned = item.strip()
        if cleaned:
            try:
                admin_ids.append(int(cleaned))
            except ValueError:
                continue
    return admin_ids


BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
SPREADSHEET_ID: str = os.getenv("SPREADSHEET_ID", "").strip()
ADMIN_IDS: list[int] = _parse_admin_ids(os.getenv("ADMIN_IDS", ""))

# Main (primary) admin: ADMIN_ID from .env, otherwise the first of ADMIN_IDS.
# Only this account may use "🔄 Rolni almashtirish" (Admin / Ustoz / Talaba /
# Ota-ona menu switcher); secondary admins (👑 Adminlar) never see it.
_MAIN_ADMIN_RAW = os.getenv("ADMIN_ID", "").strip()
try:
    MAIN_ADMIN_ID: int | None = int(_MAIN_ADMIN_RAW) if _MAIN_ADMIN_RAW else None
except ValueError:
    MAIN_ADMIN_ID = None
if MAIN_ADMIN_ID is None and ADMIN_IDS:
    MAIN_ADMIN_ID = ADMIN_IDS[0]
if MAIN_ADMIN_ID is not None and MAIN_ADMIN_ID not in ADMIN_IDS:
    ADMIN_IDS.insert(0, MAIN_ADMIN_ID)


# ----------------------------------------------------------------------
# Mishkat AI Assistant (Google Gemini via the google-genai SDK)
# ----------------------------------------------------------------------
# Without GEMINI_API_KEY the assistant is simply OFF: no client is created,
# nothing is sent to Google and every existing menu keeps working unchanged.
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "").strip() or "gemini-3.5-flash-lite"
AI_ENABLED: bool = bool(GEMINI_API_KEY)


def is_main_admin(user_id: object) -> bool:
    try:
        return MAIN_ADMIN_ID is not None and int(str(user_id)) == MAIN_ADMIN_ID
    except (TypeError, ValueError):
        return False


def _parse_optional_int(raw: str) -> int | None:
    try:
        return int(raw.strip()) if raw and raw.strip() else None
    except ValueError:
        return None


# Annual archive reports (Mishkat_Yillik_Hisobot_*.html) are delivered here;
# falls back to ADMIN_IDS[0] when BACKUP_CHAT_ID is not set.
BACKUP_CHAT_ID: int | None = _parse_optional_int(os.getenv("BACKUP_CHAT_ID", ""))
BACKUP_THREAD_ID: int | None = _parse_optional_int(os.getenv("BACKUP_THREAD_ID", ""))

CREDENTIALS_PATH: Path = _resolve_path("CREDENTIALS_PATH", "credentials.json")
DB_PATH: Path = _resolve_path("DB_PATH", "data/bot.db")

TIMEZONE_NAME: str = "Asia/Tashkent"
TZ: ZoneInfo = ZoneInfo(TIMEZONE_NAME)

STUDENT_SHEET_NAME: str = "Baza_Talabalar"
GROUP_SHEET_NAME: str = "Guruhlar"

PENDING_ACTION_DELAY_SECONDS: int = 300
# ----------------------------------------------------------------------
# Public centre info for the Guest menu ("📍 Manzil va aloqa").
# Set these in .env; empty values are hidden from the message.
# ----------------------------------------------------------------------
CENTER_NAME: str = os.getenv("CENTER_NAME", "Mishkat Nodavlat Ta'lim Muassasasi").strip()
CENTER_ADDRESS: str = os.getenv("CENTER_ADDRESS", "").strip()
CENTER_LANDMARK: str = os.getenv("CENTER_LANDMARK", "").strip()
CENTER_PHONE: str = os.getenv("CENTER_PHONE", "").strip()
CENTER_PHONE_2: str = os.getenv("CENTER_PHONE_2", "").strip()
# Official contact number reused for leads that were already contacted. It is the
# same number shown in "📍 Manzil va aloqa" (first configured centre phone).
SUPPORT_PHONE: str = CENTER_PHONE or CENTER_PHONE_2
CENTER_TELEGRAM: str = os.getenv("CENTER_TELEGRAM", "").strip()
CENTER_INSTAGRAM: str = os.getenv("CENTER_INSTAGRAM", "").strip()
CENTER_WORKING_HOURS: str = os.getenv("CENTER_WORKING_HOURS", "").strip()
CENTER_MAP_URL: str = os.getenv("CENTER_MAP_URL", "").strip()


def _parse_float(raw: str) -> float | None:
    try:
        return float(raw.strip()) if raw and raw.strip() else None
    except ValueError:
        return None


CENTER_LATITUDE: float | None = _parse_float(os.getenv("CENTER_LATITUDE", ""))
CENTER_LONGITUDE: float | None = _parse_float(os.getenv("CENTER_LONGITUDE", ""))
