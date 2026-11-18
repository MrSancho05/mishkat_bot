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

CREDENTIALS_PATH: Path = _resolve_path("CREDENTIALS_PATH", "credentials.json")
DB_PATH: Path = _resolve_path("DB_PATH", "data/bot.db")

TIMEZONE_NAME: str = "Asia/Tashkent"
TZ: ZoneInfo = ZoneInfo(TIMEZONE_NAME)

STUDENT_SHEET_NAME: str = "Baza_Talabalar"
GROUP_SHEET_NAME: str = "Guruhlar"

PENDING_ACTION_DELAY_SECONDS: int = 300