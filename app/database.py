import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiosqlite

from app.utils import now_tashkent, to_tashkent
from app.config import ADMIN_IDS, DB_PATH

VALID_LANGS = {"latn", "cyrl"}

# Initial Mishkat course catalog (seeded only when the `courses` table is empty).
# Prices are 0 ("narxi administrator orqali") until Admin sets them through
# "📚 Kurslarni boshqarish".
DEFAULT_COURSES: list[tuple[str, str, str, str]] = [
    (
        "Arab tili",
        "Arab tilini noldan o‘rganish: alifbo, o‘qish, yozish, grammatika (nahv va sarf) "
        "hamda so‘zlashuv amaliyoti.",
        "6–12 oy",
        "Haftasiga 3 marta",
    ),
    (
        "Qur'on o‘qish va Tajvid",
        "Qur'oni Karimni to‘g‘ri va chiroyli o‘qish, tajvid qoidalari, yod olish (hifz) "
        "bo‘yicha amaliy mashg‘ulotlar.",
        "6–12 oy",
        "Haftasiga 3 marta",
    ),
    (
        "Ingliz tili",
        "Beginner darajasidan IELTS / CEFR tayyorgarligigacha: grammatika, lug‘at, "
        "speaking, listening, reading va writing.",
        "3–9 oy",
        "Haftasiga 3 marta",
    ),
    (
        "Rus tili",
        "Kundalik muloqot, grammatika va so‘z boyligini oshirishga yo‘naltirilgan amaliy kurs.",
        "3–6 oy",
        "Haftasiga 3 marta",
    ),
    (
        "Matematika",
        "Maktab dasturi, olimpiada va oliy ta'limga kirish imtihonlariga tayyorgarlik.",
        "6–9 oy",
        "Haftasiga 3 marta",
    ),
    (
        "Kompyuter savodxonligi",
        "Kompyuter bilan ishlash asoslari, MS Office (Word, Excel, PowerPoint) va internet xavfsizligi.",
        "2–3 oy",
        "Haftasiga 3 marta",
    ),
]


def _parse_roles_list(
    roles_raw: Any, fallback_role: Optional[str] = None
) -> list[str]:
    parsed: list[str] = []
    if isinstance(roles_raw, list):
        candidates = roles_raw
    elif isinstance(roles_raw, str):
        stripped = roles_raw.strip()
        if stripped:
            try:
                loaded = json.loads(stripped)
                candidates = loaded if isinstance(loaded, list) else [stripped]
            except Exception:
                candidates = [stripped]
        else:
            candidates = []
    else:
        candidates = []

    for item in candidates:
        val = str(item).strip()
        if val and val not in parsed:
            parsed.append(val)

    if not parsed and fallback_role:
        fb = str(fallback_role).strip()
        if fb:
            parsed.append(fb)

    return parsed


def _normalize_user_row(row: aiosqlite.Row) -> dict[str, Any]:
    data = dict(row)
    raw_role = (data.get("role") or "").strip() or None
    roles_list = _parse_roles_list(data.get("roles"), raw_role)
    raw_active = (data.get("active_role") or "").strip() or None
    active_role = raw_active or raw_role or (roles_list[0] if roles_list else None)
    if active_role and active_role not in roles_list:
        roles_list.append(active_role)
    data["roles"] = roles_list
    data["active_role"] = active_role
    data["role"] = active_role or raw_role
    return data


def _normalize_role_change_row(row: aiosqlite.Row) -> dict[str, Any]:
    data = dict(row)
    if data.get("chat_id") is None:
        data["chat_id"] = data.get("user_id")
    if data.get("existing_role") is None:
        data["existing_role"] = data.get("current_role")
    if data.get("current_role") is None:
        data["current_role"] = data.get("existing_role")

    raw_payload = data.get("invite_payload")
    if isinstance(raw_payload, dict):
        data["invite_payload_json"] = json.dumps(raw_payload, ensure_ascii=False)
        data["invite_payload"] = raw_payload
    else:
        payload_str = (raw_payload or "{}").strip() if raw_payload is not None else "{}"
        data["invite_payload_json"] = payload_str
        try:
            loaded = json.loads(payload_str)
            if isinstance(loaded, dict):
                data["invite_payload"] = loaded
            elif loaded:
                data["invite_payload"] = {"raw": loaded}
            else:
                data["invite_payload"] = {}
        except Exception:
            data["invite_payload"] = {"raw": payload_str} if payload_str else {}
    return data


async def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                role TEXT,
                linked_student_id TEXT,
                full_name TEXT,
                lang TEXT NOT NULL DEFAULT 'latn',
                roles TEXT,
                active_role TEXT
            );
            """
        )
        for alter_user_sql in (
            "ALTER TABLE users ADD COLUMN roles TEXT;",
            "ALTER TABLE users ADD COLUMN active_role TEXT;",
            "ALTER TABLE users ADD COLUMN phone TEXT;",
        ):
            try:
                await db.execute(alter_user_sql)
            except Exception:
                pass
        # lang_selected = 1 once the user has explicitly picked a language.
        # When the column is first introduced, every pre-existing user row has
        # already passed through the language picker, so they are marked as 1.
        try:
            await db.execute(
                "ALTER TABLE users ADD COLUMN lang_selected INTEGER NOT NULL DEFAULT 0;"
            )
            await db.execute(
                "UPDATE users SET lang_selected = 1 WHERE lang IN ('latn', 'cyrl');"
            )
        except Exception:
            pass

        async with db.execute(
            "SELECT telegram_id, role, roles, active_role FROM users;"
        ) as cursor:
            user_rows = await cursor.fetchall()
        for tid, raw_role, raw_roles, raw_active in user_rows:
            clean_role = (raw_role or "").strip() or None
            roles_list = _parse_roles_list(raw_roles, clean_role)
            clean_active = (raw_active or "").strip() or None
            resolved_active = clean_active or clean_role or (
                roles_list[0] if roles_list else None
            )
            if resolved_active and resolved_active not in roles_list:
                roles_list.append(resolved_active)
            expected_roles_json = json.dumps(roles_list, ensure_ascii=False)
            if raw_roles != expected_roles_json or clean_active != resolved_active:
                await db.execute(
                    """
                    UPDATE users
                    SET roles = ?, active_role = ?
                    WHERE telegram_id = ?;
                    """,
                    (expected_roles_json, resolved_active, tid),
                )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                execute_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS group_counters (
                group_name TEXT PRIMARY KEY,
                lesson_count INTEGER NOT NULL DEFAULT 0,
                last_reminded_date TEXT,
                last_1h_reminded_date TEXT
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS teachers (
                invite_code TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                telegram_id INTEGER,
                status TEXT NOT NULL DEFAULT 'pending'
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_telegram_id INTEGER NOT NULL,
                student_username TEXT,
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                group_name TEXT NOT NULL,
                student_lang TEXT NOT NULL DEFAULT 'latn',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                lesson_date TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lesson_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL,
                lesson_date TEXT NOT NULL,
                topic_title TEXT NOT NULL DEFAULT '',
                lesson_details TEXT NOT NULL DEFAULT '',
                created_by INTEGER,
                updated_at TEXT NOT NULL DEFAULT '',
                topic TEXT NOT NULL DEFAULT '',
                plan TEXT NOT NULL DEFAULT '',
                teacher_id INTEGER,
                created_at TEXT NOT NULL DEFAULT '',
                is_published INTEGER NOT NULL DEFAULT 0,
                published_at TEXT NOT NULL DEFAULT '',
                edit_mode TEXT NOT NULL DEFAULT 'new',
                teacher_name TEXT NOT NULL DEFAULT '',
                UNIQUE(group_name, lesson_date)
            );
            """
        )
        for alter_sql in (
            "ALTER TABLE lesson_topics ADD COLUMN topic TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE lesson_topics ADD COLUMN plan TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE lesson_topics ADD COLUMN teacher_id INTEGER;",
            "ALTER TABLE lesson_topics ADD COLUMN created_at TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE lesson_topics ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE lesson_topics ADD COLUMN is_published INTEGER NOT NULL DEFAULT 0;",
            "ALTER TABLE lesson_topics ADD COLUMN published_at TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE lesson_topics ADD COLUMN edit_mode TEXT NOT NULL DEFAULT 'new';",
            "ALTER TABLE lesson_topics ADD COLUMN teacher_name TEXT NOT NULL DEFAULT '';",
        ):
            try:
                await db.execute(alter_sql)
            except Exception:
                pass
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS role_change_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER,
                full_name TEXT NOT NULL,
                current_role TEXT,
                existing_role TEXT,
                requested_role TEXT NOT NULL,
                invite_code TEXT NOT NULL DEFAULT '',
                invite_payload TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
            """
        )
        for alter_rc_sql in (
            "ALTER TABLE role_change_requests ADD COLUMN chat_id INTEGER;",
            "ALTER TABLE role_change_requests ADD COLUMN existing_role TEXT;",
            "ALTER TABLE role_change_requests ADD COLUMN invite_payload TEXT NOT NULL DEFAULT '{}';",
        ):
            try:
                await db.execute(alter_rc_sql)
            except Exception:
                pass
        await db.execute(
            """
            UPDATE role_change_requests
            SET chat_id = user_id
            WHERE chat_id IS NULL;
            """
        )
        await db.execute(
            """
            UPDATE role_change_requests
            SET existing_role = current_role
            WHERE existing_role IS NULL AND current_role IS NOT NULL;
            """
        )

        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_invites (
                code TEXT PRIMARY KEY,
                created_by INTEGER NOT NULL,
                is_used INTEGER NOT NULL DEFAULT 0,
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
                phone TEXT NOT NULL DEFAULT '',
                added_by INTEGER
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_details (
                notif_id TEXT PRIMARY KEY,
                short_text TEXT NOT NULL,
                detailed_text TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS parent_batch_invites (
                invite_code TEXT PRIMARY KEY,
                parent_name TEXT NOT NULL DEFAULT '',
                parent_phone TEXT NOT NULL DEFAULT '',
                student_ids_json TEXT NOT NULL DEFAULT '[]',
                is_used INTEGER NOT NULL DEFAULT 0,
                used_by INTEGER,
                created_at TEXT NOT NULL,
                parent_type TEXT NOT NULL DEFAULT ''
            );
            """
        )
        # Migrate older databases: which parent (father/mother) the admin chose.
        async with db.execute("PRAGMA table_info(parent_batch_invites);") as cur:
            pbi_cols = {str(r[1]) for r in await cur.fetchall()}
        if "parent_type" not in pbi_cols:
            await db.execute(
                "ALTER TABLE parent_batch_invites "
                "ADD COLUMN parent_type TEXT NOT NULL DEFAULT '';"
            )
        # Pre-system (legacy) unpaid cycles recorded manually by Admin
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS legacy_debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                student_name TEXT NOT NULL DEFAULT '',
                group_name TEXT NOT NULL DEFAULT '',
                cycle_label TEXT NOT NULL DEFAULT '',
                lesson_dates TEXT NOT NULL DEFAULT '',
                months INTEGER NOT NULL DEFAULT 1,
                amount INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '',
                is_paid INTEGER NOT NULL DEFAULT 0,
                paid_at TEXT NOT NULL DEFAULT '',
                created_by INTEGER,
                created_at TEXT NOT NULL
            );
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_legacy_debts_student ON legacy_debts(student_id);"
        )
        # Public course catalog for guests (managed by Admin)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS courses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price INTEGER NOT NULL DEFAULT 0,
                duration TEXT NOT NULL DEFAULT '',
                schedule TEXT NOT NULL DEFAULT '',
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        async with db.execute("SELECT COUNT(*) FROM courses;") as cursor:
            course_count_row = await cursor.fetchone()
        if not course_count_row or int(course_count_row[0] or 0) == 0:
            seeded_at = now_tashkent().isoformat()
            for order_idx, (c_name, c_desc, c_dur, c_sched) in enumerate(
                DEFAULT_COURSES, start=1
            ):
                await db.execute(
                    """
                    INSERT INTO courses (
                        name, description, price, duration, schedule,
                        is_active, sort_order, created_at
                    )
                    VALUES (?, ?, 0, ?, ?, 1, ?, ?);
                    """,
                    (c_name, c_desc, c_dur, c_sched, order_idx, seeded_at),
                )
        # Guest course enrollment requests (leads)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                full_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                course_id INTEGER,
                course_name TEXT NOT NULL DEFAULT '',
                lang TEXT NOT NULL DEFAULT 'latn',
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL,
                contacted_at TEXT,
                contacted_by INTEGER
            );
            """
        )
        # Migrate older databases: contacted_at / contacted_by columns.
        async with db.execute("PRAGMA table_info(leads);") as cur:
            lead_cols = {str(r[1]) for r in await cur.fetchall()}
        if "contacted_at" not in lead_cols:
            await db.execute("ALTER TABLE leads ADD COLUMN contacted_at TEXT;")
        if "contacted_by" not in lead_cols:
            await db.execute("ALTER TABLE leads ADD COLUMN contacted_by INTEGER;")
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_leads_telegram_id ON leads(telegram_id);"
        )
        # Admin notification messages per lead (so every admin's copy can be edited).
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS lead_admin_messages (
                lead_id INTEGER NOT NULL,
                admin_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                PRIMARY KEY (lead_id, admin_id)
            );
            """
        )
        # Self-service profile store (used for Admin profiles, mirrors others)
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                telegram_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL DEFAULT '',
                phone TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT ''
            );
            """
        )
        await db.commit()


async def get_user_lang(telegram_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT lang FROM users WHERE telegram_id = ?;", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row and row[0] in VALID_LANGS:
                return row[0]
            return "latn"


async def set_user_lang(telegram_id: int, lang: str) -> None:
    normalized_lang = lang if lang in VALID_LANGS else "latn"
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (telegram_id, lang, roles, lang_selected)
            VALUES (?, ?, '[]', 1)
            ON CONFLICT(telegram_id) DO UPDATE SET
                lang = excluded.lang,
                lang_selected = 1;
            """,
            (telegram_id, normalized_lang),
        )
        await db.commit()


async def has_saved_language(telegram_id: int) -> bool:
    """True when the user has already explicitly chosen a language once."""
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            async with db.execute(
                "SELECT lang, COALESCE(lang_selected, 0) FROM users WHERE telegram_id = ?;",
                (telegram_id,),
            ) as cursor:
                row = await cursor.fetchone()
        except Exception:
            return False
        if not row:
            return False
        return bool(row[1]) and row[0] in VALID_LANGS


async def get_user(telegram_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT telegram_id, role, linked_student_id, full_name, lang,
                   roles, active_role
            FROM users
            WHERE telegram_id = ?;
            """,
            (telegram_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return _normalize_user_row(row) if row else None


async def upsert_user(
    telegram_id: int,
    role: Optional[str] = None,
    linked_student_id: Optional[str] = None,
    full_name: Optional[str] = None,
    lang: Optional[str] = None,
    roles: Optional[list[str]] = None,
    active_role: Optional[str] = None,
) -> None:
    existing = await get_user(telegram_id)
    if existing:
        existing_roles = list(existing.get("roles") or [])
        existing_active = existing.get("active_role") or existing.get("role")
        if roles is not None:
            new_roles = _parse_roles_list(roles, role)
        elif role is not None:
            clean_role = role.strip()
            if clean_role and clean_role in existing_roles:
                new_roles = existing_roles
            elif clean_role:
                new_roles = [clean_role]
            else:
                new_roles = []
        else:
            new_roles = existing_roles

        if active_role is not None:
            new_active_role = active_role.strip() or None
        elif role is not None:
            new_active_role = role.strip() or None
        else:
            new_active_role = existing_active

        if new_active_role and new_active_role not in new_roles:
            new_roles.append(new_active_role)

        new_role = (
            new_active_role
            if new_active_role is not None
            else (role if role is not None else existing["role"])
        )
        new_linked = (
            linked_student_id
            if linked_student_id is not None
            else existing["linked_student_id"]
        )
        new_name = full_name if full_name is not None else existing["full_name"]
        new_lang = lang if (lang in VALID_LANGS) else existing["lang"]
    else:
        new_roles = _parse_roles_list(roles, role)
        if active_role is not None:
            new_active_role = active_role.strip() or None
        elif role is not None:
            new_active_role = role.strip() or None
        else:
            new_active_role = new_roles[0] if new_roles else None

        if new_active_role and new_active_role not in new_roles:
            new_roles.append(new_active_role)

        new_role = role if role is not None else new_active_role
        new_linked = linked_student_id
        new_name = full_name
        new_lang = lang if (lang in VALID_LANGS) else "latn"

    roles_json = json.dumps(new_roles, ensure_ascii=False)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (
                telegram_id, role, linked_student_id, full_name, lang,
                roles, active_role
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                role = excluded.role,
                linked_student_id = excluded.linked_student_id,
                full_name = excluded.full_name,
                lang = excluded.lang,
                roles = excluded.roles,
                active_role = excluded.active_role;
            """,
            (
                telegram_id,
                new_role,
                new_linked,
                new_name,
                new_lang,
                roles_json,
                new_active_role,
            ),
        )
        await db.commit()


async def reset_user_role(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE users
            SET role = NULL, linked_student_id = NULL, roles = '[]', active_role = NULL
            WHERE telegram_id = ?;
            """,
            (user_id,),
        )
        await db.execute(
            "DELETE FROM teachers WHERE telegram_id = ?;",
            (user_id,),
        )
        await db.execute(
            "DELETE FROM dynamic_admins WHERE telegram_id = ?;",
            (user_id,),
        )
        try:
            await db.execute(
                "DELETE FROM teacher_meta WHERE telegram_id = ?;",
                (user_id,),
            )
        except Exception:
            pass
        await db.commit()


async def _table_exists(db: aiosqlite.Connection, table: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?;",
        (table,),
    ) as cur:
        return (await cur.fetchone()) is not None


async def _is_admin_in_db(db: aiosqlite.Connection, chat_id: int) -> bool:
    if int(chat_id) in {int(a) for a in ADMIN_IDS}:
        return True
    if await _table_exists(db, "dynamic_admins"):
        async with db.execute(
            "SELECT 1 FROM dynamic_admins WHERE telegram_id = ?;", (int(chat_id),)
        ) as cur:
            if await cur.fetchone():
                return True
    return False


async def _strip_role_or_delete_user(
    db: aiosqlite.Connection,
    chat_id: int,
    role_to_remove: str,
    student_id: Optional[str] = None,
) -> str:
    """
    Removes `role_to_remove` from the user's roles list inside an open
    connection (no commit). If the user has no other active role left (and is
    not an admin) the whole `users` row is deleted.
    Returns "deleted", "updated" or "missing".
    """
    clean_role = (role_to_remove or "").strip()
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT telegram_id, role, linked_student_id, full_name, lang,
               roles, active_role
        FROM users WHERE telegram_id = ?;
        """,
        (int(chat_id),),
    ) as cur:
        row = await cur.fetchone()
    if not row:
        return "missing"

    user = _normalize_user_row(row)
    roles_list = [r for r in user.get("roles") or [] if r != clean_role]
    is_admin = await _is_admin_in_db(db, int(chat_id))
    if is_admin and "admin" not in roles_list:
        roles_list.append("admin")

    if not roles_list:
        await db.execute("DELETE FROM users WHERE telegram_id = ?;", (int(chat_id),))
        return "deleted"

    active = user.get("active_role")
    if active == clean_role or active not in roles_list:
        active = roles_list[0]

    linked = user.get("linked_student_id")
    if clean_role in {"student", "parent"} and (
        not student_id or str(linked or "").strip() == str(student_id).strip()
    ):
        linked = None
    if active not in {"student", "parent"} and clean_role in {"student", "parent"}:
        linked = None

    await db.execute(
        """
        UPDATE users
        SET role = ?, roles = ?, active_role = ?, linked_student_id = ?
        WHERE telegram_id = ?;
        """,
        (
            active,
            json.dumps(roles_list, ensure_ascii=False),
            active,
            linked,
            int(chat_id),
        ),
    )
    return "updated"


async def _delete_requests_for_person(
    db: aiosqlite.Connection,
    chat_id: Optional[int],
    student_id: Optional[str],
) -> None:
    """Deletes pending role-change requests (and parent_meta) tied to the person."""
    if chat_id is not None and await _table_exists(db, "role_change_requests"):
        await db.execute(
            """
            DELETE FROM role_change_requests
            WHERE status = 'pending' AND (user_id = ? OR chat_id = ?);
            """,
            (int(chat_id), int(chat_id)),
        )
    if student_id and await _table_exists(db, "role_change_requests"):
        await db.execute(
            """
            DELETE FROM role_change_requests
            WHERE status = 'pending' AND invite_payload LIKE ?;
            """,
            (f'%"{str(student_id).strip()}"%',),
        )
    if chat_id is not None and await _table_exists(db, "parent_meta"):
        await db.execute(
            "DELETE FROM parent_meta WHERE telegram_id = ?;", (int(chat_id),)
        )
    if student_id and await _table_exists(db, "parent_meta"):
        await db.execute(
            "DELETE FROM parent_meta WHERE student_id = ?;", (str(student_id).strip(),)
        )


async def purge_deleted_person_from_db(chat_id: int, role_to_remove: str) -> str:
    """
    Removes `role_to_remove` ('student' / 'parent' / 'teacher') from the user's
    roles list. If no other active role remains (not also admin / student /
    parent / teacher) the whole `users` row is deleted so the person re-enters
    the bot as a brand-new guest. Also drops their pending role-change
    requests, teacher invite rows and parent meta.
    Returns "deleted", "updated" or "missing".
    """
    clean_role = (role_to_remove or "").strip()
    if not chat_id or not clean_role:
        return "missing"
    async with aiosqlite.connect(DB_PATH) as db:
        await _delete_requests_for_person(db, int(chat_id), None)
        if clean_role == "teacher":
            if await _table_exists(db, "teachers"):
                await db.execute(
                    "DELETE FROM teachers WHERE telegram_id = ?;", (int(chat_id),)
                )
            if await _table_exists(db, "teacher_meta"):
                await db.execute(
                    "DELETE FROM teacher_meta WHERE telegram_id = ?;", (int(chat_id),)
                )
        result = await _strip_role_or_delete_user(db, int(chat_id), clean_role)
        await db.commit()
        return result


async def purge_student_and_orphaned_parents(
    student_id: str,
    student_chat_id: Optional[int],
    orphaned_parent_chat_ids: list[int],
) -> dict[str, Any]:
    """
    Full SQLite cleanup after a student was permanently deleted:
    - deletes legacy_debts and pending role-change requests tied to the
      student_id / student chat id,
    - removes the 'student' role from `student_chat_id` (deleting the users row
      when no other active role is left),
    - removes the 'parent' role from every orphaned parent (deleting the users
      row when no other active role is left),
    - clears any remaining users.linked_student_id pointing at this student.
    Returns {"student_user": str, "parents": {chat_id: str}}.
    """
    clean_sid = str(student_id or "").strip()
    result: dict[str, Any] = {"student_user": "missing", "parents": {}}
    async with aiosqlite.connect(DB_PATH) as db:
        if clean_sid:
            if await _table_exists(db, "legacy_debts"):
                await db.execute(
                    "DELETE FROM legacy_debts WHERE student_id = ?;", (clean_sid,)
                )
            await _delete_requests_for_person(db, None, clean_sid)

        if student_chat_id:
            await _delete_requests_for_person(db, int(student_chat_id), clean_sid)
            result["student_user"] = await _strip_role_or_delete_user(
                db, int(student_chat_id), "student", clean_sid
            )

        for p_cid in orphaned_parent_chat_ids or []:
            try:
                p_int = int(p_cid)
            except (TypeError, ValueError):
                continue
            await _delete_requests_for_person(db, p_int, clean_sid)
            result["parents"][p_int] = await _strip_role_or_delete_user(
                db, p_int, "parent", clean_sid
            )

        if clean_sid:
            await db.execute(
                "UPDATE users SET linked_student_id = NULL WHERE linked_student_id = ?;",
                (clean_sid,),
            )
        await db.commit()
    return result


async def get_user_roles(chat_id: int) -> list[str]:
    user = await get_user(chat_id)
    if not user:
        return []
    return list(user.get("roles") or [])


async def get_active_role(chat_id: int) -> Optional[str]:
    user = await get_user(chat_id)
    if not user:
        return None
    return user.get("active_role") or user.get("role")


async def add_user_role(chat_id: int, new_role: str) -> list[str]:
    clean_role = (new_role or "").strip()
    existing = await get_user(chat_id)
    if existing:
        roles_list = list(existing.get("roles") or [])
        if clean_role and clean_role not in roles_list:
            roles_list.append(clean_role)
        active_role = (
            clean_role
            or existing.get("active_role")
            or existing.get("role")
            or (roles_list[0] if roles_list else None)
        )
        roles_json = json.dumps(roles_list, ensure_ascii=False)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                UPDATE users
                SET role = ?, roles = ?, active_role = ?
                WHERE telegram_id = ?;
                """,
                (active_role, roles_json, active_role, chat_id),
            )
            await db.commit()
        return roles_list

    roles_list = [clean_role] if clean_role else []
    active_role = clean_role or None
    roles_json = json.dumps(roles_list, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (
                telegram_id, role, lang, roles, active_role
            )
            VALUES (?, ?, 'latn', ?, ?);
            """,
            (chat_id, active_role, roles_json, active_role),
        )
        await db.commit()
    return roles_list


async def replace_user_role(chat_id: int, new_role: str) -> list[str]:
    clean_role = (new_role or "").strip()
    roles_list = [clean_role] if clean_role else []
    active_role = clean_role or None
    roles_json = json.dumps(roles_list, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (
                telegram_id, role, lang, roles, active_role
            )
            VALUES (?, ?, 'latn', ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                role = excluded.role,
                roles = excluded.roles,
                active_role = excluded.active_role;
            """,
            (chat_id, active_role, roles_json, active_role),
        )
        await db.commit()
    return roles_list


async def switch_active_role(chat_id: int) -> Optional[str]:
    user = await get_user(chat_id)
    if not user:
        return None
    roles_list = list(user.get("roles") or [])
    current_active = user.get("active_role") or user.get("role")
    if "student" in roles_list and "parent" in roles_list:
        new_active = "parent" if current_active == "student" else "student"
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                UPDATE users
                SET active_role = ?, role = ?
                WHERE telegram_id = ?;
                """,
                (new_active, new_active, chat_id),
            )
            await db.commit()
        return new_active
    return current_active


async def has_dual_student_parent_role(chat_id: int) -> bool:
    roles_list = await get_user_roles(chat_id)
    return "student" in roles_list and "parent" in roles_list


# ----------------------------------------------------------------------
# Teachers CRUD (invite codes & active teachers)
# ----------------------------------------------------------------------


async def create_teacher_invite(invite_code: str, full_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO teachers (invite_code, full_name, telegram_id, status)
            VALUES (?, ?, NULL, 'pending');
            """,
            (invite_code.strip(), full_name.strip()),
        )
        await db.commit()


async def get_teacher_by_invite_code(invite_code: str) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT invite_code, full_name, telegram_id, status
            FROM teachers
            WHERE invite_code = ?;
            """,
            (invite_code.strip(),),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def activate_teacher_invite(
    invite_code: str, telegram_id: int
) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            UPDATE teachers
            SET telegram_id = ?, status = 'active'
            WHERE invite_code = ?
              AND (status = 'pending' OR telegram_id = ?);
            """,
            (telegram_id, invite_code.strip(), telegram_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            return None
        async with db.execute(
            """
            SELECT invite_code, full_name, telegram_id, status
            FROM teachers
            WHERE invite_code = ?;
            """,
            (invite_code.strip(),),
        ) as sel:
            row = await sel.fetchone()
            return dict(row) if row else None


async def get_teacher_by_telegram_id(
    telegram_id: int,
) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT invite_code, full_name, telegram_id, status
            FROM teachers
            WHERE telegram_id = ? AND status = 'active'
            ORDER BY rowid DESC
            LIMIT 1;
            """,
            (telegram_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_active_teachers() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT invite_code, full_name, telegram_id, status
            FROM teachers
            WHERE status = 'active' AND telegram_id IS NOT NULL
            ORDER BY full_name ASC;
            """
        ) as cursor:
            rows = await cursor.fetchall()
            seen_ids: set[int] = set()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                tid = int(item["telegram_id"])
                if tid not in seen_ids:
                    seen_ids.add(tid)
                    result.append(item)
            return result


# ----------------------------------------------------------------------
# Role Change & Dual-Role Conflict Requests CRUD
# ----------------------------------------------------------------------


async def create_role_change_request(
    user_id: int,
    full_name: str,
    current_role: Optional[str],
    requested_role: str,
    invite_code: str = "",
    chat_id: Optional[int] = None,
    existing_role: Optional[str] = None,
    invite_payload: Optional[dict[str, Any] | str] = None,
) -> int:
    created_at = now_tashkent().isoformat()
    resolved_chat_id = chat_id if chat_id is not None else user_id
    resolved_existing = (
        existing_role.strip()
        if existing_role
        else (current_role.strip() if current_role else None)
    )
    resolved_current = (
        current_role.strip() if current_role else resolved_existing
    )
    if isinstance(invite_payload, dict):
        payload_json = json.dumps(invite_payload, ensure_ascii=False)
    elif isinstance(invite_payload, str) and invite_payload.strip():
        try:
            loaded = json.loads(invite_payload)
            payload_json = json.dumps(loaded, ensure_ascii=False)
        except Exception:
            payload_json = json.dumps(
                {"raw": invite_payload.strip()}, ensure_ascii=False
            )
    else:
        payload_json = "{}"

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO role_change_requests (
                user_id, chat_id, full_name, current_role, existing_role,
                requested_role, invite_code, invite_payload, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?);
            """,
            (
                user_id,
                resolved_chat_id,
                full_name.strip(),
                resolved_current,
                resolved_existing,
                requested_role.strip(),
                (invite_code or "").strip(),
                payload_json,
                created_at,
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def create_role_conflict_request(
    chat_id: int,
    full_name: str,
    existing_role: Optional[str],
    requested_role: str,
    invite_payload: Optional[dict[str, Any] | str] = None,
    invite_code: str = "",
) -> int:
    return await create_role_change_request(
        user_id=chat_id,
        full_name=full_name,
        current_role=existing_role,
        requested_role=requested_role,
        invite_code=invite_code,
        chat_id=chat_id,
        existing_role=existing_role,
        invite_payload=invite_payload,
    )


async def get_role_change_request(req_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, user_id, chat_id, full_name, current_role, existing_role,
                   requested_role, invite_code, invite_payload, status, created_at
            FROM role_change_requests
            WHERE id = ?;
            """,
            (req_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return _normalize_role_change_row(row) if row else None


async def resolve_role_change_request(
    req_id: int, status: str
) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            UPDATE role_change_requests
            SET status = ?
            WHERE id = ? AND status = 'pending';
            """,
            (status.strip(), req_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            return None
        async with db.execute(
            """
            SELECT id, user_id, chat_id, full_name, current_role, existing_role,
                   requested_role, invite_code, invite_payload, status, created_at
            FROM role_change_requests
            WHERE id = ?;
            """,
            (req_id,),
        ) as sel:
            row = await sel.fetchone()
            return _normalize_role_change_row(row) if row else None


# ----------------------------------------------------------------------
# Student Group Self-Join Requests
# ----------------------------------------------------------------------


async def create_join_request(
    student_telegram_id: int,
    student_username: Optional[str],
    full_name: str,
    phone: str,
    group_name: str,
    student_lang: str = "latn",
) -> int:
    created_at = now_tashkent().isoformat()
    safe_lang = student_lang if student_lang in VALID_LANGS else "latn"
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO join_requests (
                student_telegram_id,
                student_username,
                full_name,
                phone,
                group_name,
                student_lang,
                status,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?);
            """,
            (
                student_telegram_id,
                student_username,
                full_name.strip(),
                phone.strip(),
                group_name.strip(),
                safe_lang,
                created_at,
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def get_join_request(request_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, student_telegram_id, student_username, full_name, phone,
                   group_name, student_lang, status, created_at
            FROM join_requests
            WHERE id = ?;
            """,
            (request_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def resolve_join_request(
    request_id: int, new_status: str
) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            UPDATE join_requests
            SET status = ?
            WHERE id = ? AND status = 'pending';
            """,
            (new_status, request_id),
        )
        await db.commit()
        if cursor.rowcount == 0:
            return None
        async with db.execute(
            """
            SELECT id, student_telegram_id, student_username, full_name, phone,
                   group_name, student_lang, status, created_at
            FROM join_requests
            WHERE id = ?;
            """,
            (request_id,),
        ) as sel:
            row = await sel.fetchone()
            return dict(row) if row else None


# ----------------------------------------------------------------------
# Pending Actions & Group Counters
# ----------------------------------------------------------------------


async def create_pending_action(
    action_type: str, payload: dict[str, Any], execute_at: str
) -> int:
    payload_json = json.dumps(payload, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO pending_actions (action_type, payload_json, execute_at, status)
            VALUES (?, ?, ?, 'pending');
            """,
            (action_type, payload_json, execute_at),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def get_pending_action(action_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, action_type, payload_json, execute_at, status
            FROM pending_actions
            WHERE id = ?;
            """,
            (action_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["payload"] = json.loads(data["payload_json"])
            return data


async def get_due_pending_actions(now_iso: str) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, action_type, payload_json, execute_at, status
            FROM pending_actions
            WHERE status = 'pending' AND execute_at <= ?
            ORDER BY id ASC;
            """,
            (now_iso,),
        ) as cursor:
            rows = await cursor.fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                item = dict(row)
                item["payload"] = json.loads(item["payload_json"])
                results.append(item)
            return results


async def update_pending_action_status(action_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE pending_actions SET status = ? WHERE id = ?;",
            (status, action_id),
        )
        await db.commit()


async def update_pending_action_payload(
    action_id: int,
    payload: dict[str, Any],
    execute_at: Optional[str] = None,
) -> None:
    payload_json = json.dumps(payload, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        if execute_at is not None:
            await db.execute(
                """
                UPDATE pending_actions
                SET payload_json = ?, execute_at = ?
                WHERE id = ?;
                """,
                (payload_json, execute_at, action_id),
            )
        else:
            await db.execute(
                """
                UPDATE pending_actions
                SET payload_json = ?
                WHERE id = ?;
                """,
                (payload_json, action_id),
            )
        await db.commit()


async def get_group_counter(group_name: str) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT group_name, lesson_count, last_reminded_date, last_1h_reminded_date
            FROM group_counters
            WHERE group_name = ?;
            """,
            (group_name,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def upsert_group_counter(
    group_name: str,
    lesson_count: Optional[int] = None,
    last_reminded_date: Optional[str] = None,
    last_1h_reminded_date: Optional[str] = None,
) -> None:
    existing = await get_group_counter(group_name)
    if existing:
        new_count = lesson_count if lesson_count is not None else existing["lesson_count"]
        new_reminded = (
            last_reminded_date
            if last_reminded_date is not None
            else existing["last_reminded_date"]
        )
        new_1h_reminded = (
            last_1h_reminded_date
            if last_1h_reminded_date is not None
            else existing["last_1h_reminded_date"]
        )
    else:
        new_count = lesson_count if lesson_count is not None else 0
        new_reminded = last_reminded_date
        new_1h_reminded = last_1h_reminded_date

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO group_counters (
                group_name, lesson_count, last_reminded_date, last_1h_reminded_date
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(group_name) DO UPDATE SET
                lesson_count = excluded.lesson_count,
                last_reminded_date = excluded.last_reminded_date,
                last_1h_reminded_date = excluded.last_1h_reminded_date;
            """,
            (group_name, new_count, new_reminded, new_1h_reminded),
        )
        await db.commit()


# ----------------------------------------------------------------------
# Attendance Reports CRUD
# ----------------------------------------------------------------------


async def create_attendance_report(
    group_name: str, lesson_date: str, payload: dict[str, Any]
) -> int:
    created_at = now_tashkent().isoformat()
    payload_json = json.dumps(payload, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO attendance_reports (group_name, lesson_date, payload_json, created_at)
            VALUES (?, ?, ?, ?);
            """,
            (group_name.strip(), lesson_date.strip(), payload_json, created_at),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def get_attendance_report(report_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, group_name, lesson_date, payload_json, created_at
            FROM attendance_reports
            WHERE id = ?;
            """,
            (report_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            data["payload"] = json.loads(data["payload_json"])
            return data


async def update_attendance_report(
    report_id: int, payload: dict[str, Any]
) -> bool:
    payload_json = json.dumps(payload, ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE attendance_reports
            SET payload_json = ?
            WHERE id = ?;
            """,
            (payload_json, report_id),
        )
        await db.commit()
        return cursor.rowcount > 0


# ----------------------------------------------------------------------
# Lesson Topics CRUD (group_name + lesson_date)
# ----------------------------------------------------------------------


def _normalize_topic_row(row: aiosqlite.Row) -> dict[str, Any]:
    data = dict(row)
    topic_val = data.get("topic") or data.get("topic_title") or ""
    plan_val = data.get("plan") or data.get("lesson_details") or ""
    teacher_val = (
        data.get("teacher_id")
        if data.get("teacher_id") is not None
        else data.get("created_by")
    )
    created_val = data.get("created_at") or data.get("updated_at") or ""
    data["topic"] = topic_val
    data["topic_title"] = topic_val
    data["plan"] = plan_val
    data["lesson_details"] = plan_val
    data["teacher_id"] = teacher_val
    data["created_by"] = teacher_val
    data["created_at"] = created_val
    data["updated_at"] = data.get("updated_at") or created_val
    data["is_published"] = int(data.get("is_published") or 0)
    data["published_at"] = data.get("published_at") or ""
    data["edit_mode"] = data.get("edit_mode") or "new"
    data["teacher_name"] = data.get("teacher_name") or ""
    return data


async def save_lesson_topic(
    group_name: str,
    lesson_date: str,
    topic: str,
    plan: str = "",
    teacher_id: Optional[int] = None,
    teacher_name: str = "",
    edit_mode: Optional[str] = None,
    is_published: Optional[int] = None,
) -> dict[str, Any]:
    now_iso = now_tashkent().isoformat()
    clean_group = group_name.strip()
    clean_date = lesson_date.strip()
    clean_topic = topic.strip()
    clean_plan = plan.strip()
    clean_teacher_name = teacher_name.strip()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, group_name, lesson_date, topic_title, lesson_details,
                   created_by, updated_at, topic, plan, teacher_id, created_at,
                   is_published, published_at, edit_mode, teacher_name
            FROM lesson_topics
            WHERE group_name = ? AND lesson_date = ?;
            """,
            (clean_group, clean_date),
        ) as cur:
            existing_row = await cur.fetchone()

        existing = _normalize_topic_row(existing_row) if existing_row else None

        if existing:
            was_published = int(existing.get("is_published") or 0) == 1
            old_topic = (existing.get("topic") or "").strip()
            old_plan = (existing.get("plan") or "").strip()

            if edit_mode in {"new", "appended", "edited"}:
                resolved_edit_mode = edit_mode
            elif was_published:
                is_appended_plan = (
                    clean_topic == old_topic
                    and clean_plan != old_plan
                    and (not old_plan or clean_plan.startswith(old_plan))
                )
                is_appended_topic = (
                    clean_plan == old_plan
                    and bool(old_topic)
                    and clean_topic.startswith(old_topic)
                    and len(clean_topic) > len(old_topic)
                )
                resolved_edit_mode = (
                    "appended" if (is_appended_plan or is_appended_topic) else "edited"
                )
            else:
                resolved_edit_mode = existing.get("edit_mode") or "new"

            if is_published is not None:
                resolved_is_published = int(is_published)
            elif was_published:
                resolved_is_published = 0
            else:
                resolved_is_published = int(existing.get("is_published") or 0)

            resolved_published_at = (
                now_iso
                if resolved_is_published == 1 and not was_published
                else (existing.get("published_at") or "")
            )
            resolved_created_at = existing.get("created_at") or now_iso
            resolved_teacher_name = (
                clean_teacher_name or existing.get("teacher_name") or ""
            )
        else:
            resolved_edit_mode = (
                edit_mode if edit_mode in {"new", "appended", "edited"} else "new"
            )
            resolved_is_published = int(is_published) if is_published is not None else 0
            resolved_published_at = now_iso if resolved_is_published == 1 else ""
            resolved_created_at = now_iso
            resolved_teacher_name = clean_teacher_name

        await db.execute(
            """
            INSERT INTO lesson_topics (
                group_name, lesson_date, topic_title, lesson_details,
                created_by, updated_at, topic, plan, teacher_id, created_at,
                is_published, published_at, edit_mode, teacher_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_name, lesson_date) DO UPDATE SET
                topic_title = excluded.topic_title,
                lesson_details = excluded.lesson_details,
                created_by = COALESCE(excluded.created_by, lesson_topics.created_by),
                updated_at = excluded.updated_at,
                topic = excluded.topic,
                plan = excluded.plan,
                teacher_id = COALESCE(excluded.teacher_id, lesson_topics.teacher_id),
                created_at = COALESCE(NULLIF(lesson_topics.created_at, ''), excluded.created_at),
                is_published = excluded.is_published,
                published_at = excluded.published_at,
                edit_mode = excluded.edit_mode,
                teacher_name = COALESCE(NULLIF(excluded.teacher_name, ''), lesson_topics.teacher_name);
            """,
            (
                clean_group,
                clean_date,
                clean_topic,
                clean_plan,
                teacher_id,
                now_iso,
                clean_topic,
                clean_plan,
                teacher_id,
                resolved_created_at,
                resolved_is_published,
                resolved_published_at,
                resolved_edit_mode,
                resolved_teacher_name,
            ),
        )
        await db.commit()
        async with db.execute(
            """
            SELECT id, group_name, lesson_date, topic_title, lesson_details,
                   created_by, updated_at, topic, plan, teacher_id, created_at,
                   is_published, published_at, edit_mode, teacher_name
            FROM lesson_topics
            WHERE group_name = ? AND lesson_date = ?;
            """,
            (clean_group, clean_date),
        ) as cursor:
            row = await cursor.fetchone()
            return _normalize_topic_row(row) if row else {}


async def upsert_lesson_topic(
    group_name: str,
    lesson_date: str,
    topic_title: str,
    lesson_details: str = "",
    created_by: Optional[int] = None,
    teacher_name: str = "",
    edit_mode: Optional[str] = None,
    is_published: Optional[int] = None,
) -> dict[str, Any]:
    return await save_lesson_topic(
        group_name=group_name,
        lesson_date=lesson_date,
        topic=topic_title,
        plan=lesson_details,
        teacher_id=created_by,
        teacher_name=teacher_name,
        edit_mode=edit_mode,
        is_published=is_published,
    )


async def get_lesson_topic(
    group_name: str, lesson_date: str
) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, group_name, lesson_date, topic_title, lesson_details,
                   created_by, updated_at, topic, plan, teacher_id, created_at,
                   is_published, published_at, edit_mode, teacher_name
            FROM lesson_topics
            WHERE group_name = ? AND lesson_date = ?;
            """,
            (group_name.strip(), lesson_date.strip()),
        ) as cursor:
            row = await cursor.fetchone()
            return _normalize_topic_row(row) if row else None


async def get_group_topics_history(
    group_name: str, limit: int = 20
) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, group_name, lesson_date, topic_title, lesson_details,
                   created_by, updated_at, topic, plan, teacher_id, created_at,
                   is_published, published_at, edit_mode, teacher_name
            FROM lesson_topics
            WHERE group_name = ?
            ORDER BY id DESC
            LIMIT ?;
            """,
            (group_name.strip(), int(limit)),
        ) as cursor:
            rows = await cursor.fetchall()
            return [_normalize_topic_row(row) for row in rows]


async def get_lesson_topics_for_group(group_name: str) -> list[dict[str, Any]]:
    return await get_group_topics_history(group_name, limit=100)


async def delete_lesson_topic(group_name: str, lesson_date: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            DELETE FROM lesson_topics
            WHERE group_name = ? AND lesson_date = ?;
            """,
            (group_name.strip(), lesson_date.strip()),
        )
        await db.commit()
        return cursor.rowcount > 0


async def mark_topics_published(
    group_name: str, lesson_dates: Optional[list[str]] = None
) -> int:
    now_iso = now_tashkent().isoformat()
    clean_group = group_name.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        if lesson_dates is None:
            cursor = await db.execute(
                """
                UPDATE lesson_topics
                SET is_published = 1, published_at = ?
                WHERE group_name = ? AND is_published = 0;
                """,
                (now_iso, clean_group),
            )
        else:
            clean_dates = [d.strip() for d in lesson_dates if d and d.strip()]
            if not clean_dates:
                return 0
            placeholders = ",".join("?" for _ in clean_dates)
            cursor = await db.execute(
                f"""
                UPDATE lesson_topics
                SET is_published = 1, published_at = ?
                WHERE group_name = ? AND lesson_date IN ({placeholders}) AND is_published = 0;
                """,
                [now_iso, clean_group, *clean_dates],
            )
        await db.commit()
        return int(cursor.rowcount or 0)


async def get_unpublished_topics_older_than(
    minutes: int = 30,
) -> list[dict[str, Any]]:
    cutoff = now_tashkent() - timedelta(minutes=minutes)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, group_name, lesson_date, topic_title, lesson_details,
                   created_by, updated_at, topic, plan, teacher_id, created_at,
                   is_published, published_at, edit_mode, teacher_name
            FROM lesson_topics
            WHERE is_published = 0
            ORDER BY id ASC;
            """
        ) as cursor:
            rows = await cursor.fetchall()
            results: list[dict[str, Any]] = []
            for row in rows:
                item = _normalize_topic_row(row)
                ts_str = item.get("updated_at") or item.get("created_at") or ""
                if not ts_str:
                    continue
                try:
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt <= cutoff:
                        results.append(item)
                except ValueError:
                    continue
            return results


# ----------------------------------------------------------------------
# Admin Invites & Dynamic Admins CRUD
# ----------------------------------------------------------------------


async def create_admin_invite(code: str, created_by: int) -> dict[str, Any]:
    created_at = now_tashkent().isoformat()
    clean_code = code.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO admin_invites (code, created_by, is_used, used_by, created_at)
            VALUES (?, ?, 0, NULL, ?);
            """,
            (clean_code, created_by, created_at),
        )
        await db.commit()
        async with db.execute(
            """
            SELECT code, created_by, is_used, used_by, created_at
            FROM admin_invites
            WHERE code = ?;
            """,
            (clean_code,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {}


async def get_admin_invite(code: str) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT code, created_by, is_used, used_by, created_at
            FROM admin_invites
            WHERE code = ?;
            """,
            (code.strip(),),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def use_admin_invite(code: str, used_by: int) -> Optional[dict[str, Any]]:
    clean_code = code.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            UPDATE admin_invites
            SET is_used = 1, used_by = ?
            WHERE code = ? AND is_used = 0;
            """,
            (used_by, clean_code),
        )
        await db.commit()
        if cursor.rowcount == 0:
            return None
        async with db.execute(
            """
            SELECT code, created_by, is_used, used_by, created_at
            FROM admin_invites
            WHERE code = ?;
            """,
            (clean_code,),
        ) as sel:
            row = await sel.fetchone()
            return dict(row) if row else None


async def add_dynamic_admin(
    telegram_id: int,
    full_name: str,
    phone: str = "",
    added_by: Optional[int] = None,
) -> dict[str, Any]:
    clean_name = full_name.strip()
    clean_phone = phone.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO dynamic_admins (telegram_id, full_name, phone, added_by)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                full_name = excluded.full_name,
                phone = excluded.phone,
                added_by = COALESCE(excluded.added_by, dynamic_admins.added_by);
            """,
            (telegram_id, clean_name, clean_phone, added_by),
        )
        await db.commit()
        async with db.execute(
            """
            SELECT telegram_id, full_name, phone, added_by
            FROM dynamic_admins
            WHERE telegram_id = ?;
            """,
            (telegram_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else {}


async def get_dynamic_admin(telegram_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT telegram_id, full_name, phone, added_by
            FROM dynamic_admins
            WHERE telegram_id = ?;
            """,
            (telegram_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def get_all_dynamic_admins() -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT telegram_id, full_name, phone, added_by
            FROM dynamic_admins
            ORDER BY full_name ASC;
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def remove_dynamic_admin(telegram_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM dynamic_admins WHERE telegram_id = ?;",
            (telegram_id,),
        )
        await db.commit()
        return cursor.rowcount > 0


async def is_dynamic_admin(telegram_id: int) -> bool:
    admin = await get_dynamic_admin(telegram_id)
    return admin is not None


# ----------------------------------------------------------------------
# Expandable Notification Payloads CRUD
# ----------------------------------------------------------------------


async def save_notification_details(
    notif_id: str, short_text: str, detailed_text: str
) -> None:
    created_at = now_tashkent().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO notification_details (
                notif_id, short_text, detailed_text, created_at
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(notif_id) DO UPDATE SET
                short_text = excluded.short_text,
                detailed_text = excluded.detailed_text,
                created_at = excluded.created_at;
            """,
            (notif_id.strip(), short_text, detailed_text, created_at),
        )
        await db.commit()


async def get_notification_details(notif_id: str) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT notif_id, short_text, detailed_text, created_at
            FROM notification_details
            WHERE notif_id = ?;
            """,
            (notif_id.strip(),),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


# ----------------------------------------------------------------------
# Multi-Child Parent Batch Invites CRUD
# ----------------------------------------------------------------------


async def create_parent_batch_invite(
    invite_code: str,
    parent_name: str,
    parent_phone: str,
    student_ids: list[str],
    parent_type: str = "",
) -> dict[str, Any]:
    created_at = now_tashkent().isoformat()
    clean_code = invite_code.strip()
    clean_type = parent_type if parent_type in {"father", "mother"} else ''
    clean_name = (parent_name or "").strip()
    clean_phone = (parent_phone or "").strip()
    clean_ids: list[str] = []
    seen: set[str] = set()
    for sid in student_ids:
        s = str(sid).strip()
        if s and s not in seen:
            seen.add(s)
            clean_ids.append(s)
    student_ids_json = json.dumps(clean_ids, ensure_ascii=False)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO parent_batch_invites (
                invite_code, parent_name, parent_phone, student_ids_json,
                is_used, used_by, created_at, parent_type
            )
            VALUES (?, ?, ?, ?, 0, NULL, ?, ?)
            ON CONFLICT(invite_code) DO UPDATE SET
                parent_name = excluded.parent_name,
                parent_phone = excluded.parent_phone,
                student_ids_json = excluded.student_ids_json,
                is_used = 0,
                used_by = NULL,
                created_at = excluded.created_at,
                parent_type = excluded.parent_type;
            """,
            (clean_code, clean_name, clean_phone, student_ids_json, created_at, clean_type),
        )
        await db.commit()
        async with db.execute(
            """
            SELECT invite_code, parent_name, parent_phone, student_ids_json,
                   is_used, used_by, created_at, parent_type
            FROM parent_batch_invites
            WHERE invite_code = ?;
            """,
            (clean_code,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return {}
            data = dict(row)
            data["student_ids"] = json.loads(data["student_ids_json"])
            return data


async def get_parent_batch_invite(invite_code: str) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT invite_code, parent_name, parent_phone, student_ids_json,
                   is_used, used_by, created_at, parent_type
            FROM parent_batch_invites
            WHERE invite_code = ?;
            """,
            (invite_code.strip(),),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["student_ids"] = json.loads(data.get("student_ids_json") or "[]")
            except Exception:
                data["student_ids"] = []
            return data


async def mark_parent_batch_invite_used(
    invite_code: str, used_by: int
) -> Optional[dict[str, Any]]:
    clean_code = invite_code.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            UPDATE parent_batch_invites
            SET is_used = 1, used_by = ?
            WHERE invite_code = ?;
            """,
            (used_by, clean_code),
        )
        await db.commit()
        async with db.execute(
            """
            SELECT invite_code, parent_name, parent_phone, student_ids_json,
                   is_used, used_by, created_at, parent_type
            FROM parent_batch_invites
            WHERE invite_code = ?;
            """,
            (clean_code,),
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return None
            data = dict(row)
            try:
                data["student_ids"] = json.loads(data.get("student_ids_json") or "[]")
            except Exception:
                data["student_ids"] = []
            return data

# ----------------------------------------------------------------------
# Legacy (pre-system) debts CRUD
# ----------------------------------------------------------------------


def _clean_int(val: Any, default: int = 0) -> int:
    try:
        digits = "".join(ch for ch in str(val) if ch.isdigit())
        return int(digits) if digits else default
    except Exception:
        return default


async def add_legacy_debt(
    student_id: str,
    cycle_label: str,
    amount: int,
    months: int = 1,
    lesson_dates: str = "",
    student_name: str = "",
    group_name: str = "",
    note: str = "",
    created_by: Optional[int] = None,
) -> dict[str, Any]:
    created_at = now_tashkent().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            INSERT INTO legacy_debts (
                student_id, student_name, group_name, cycle_label, lesson_dates,
                months, amount, note, is_paid, paid_at, created_by, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, '', ?, ?);
            """,
            (
                str(student_id).strip(),
                (student_name or "").strip(),
                (group_name or "").strip(),
                (cycle_label or "").strip(),
                (lesson_dates or "").strip(),
                max(1, int(months or 1)),
                max(0, _clean_int(amount)),
                (note or "").strip(),
                created_by,
                created_at,
            ),
        )
        await db.commit()
        new_id = cursor.lastrowid
        async with db.execute(
            "SELECT * FROM legacy_debts WHERE id = ?;", (new_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else {}


async def get_legacy_debt(debt_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM legacy_debts WHERE id = ?;", (int(debt_id),)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_legacy_debts(
    student_id: str, include_paid: bool = False
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM legacy_debts WHERE student_id = ?"
    if not include_paid:
        sql += " AND COALESCE(is_paid, 0) = 0"
    sql += " ORDER BY id ASC;"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, (str(student_id).strip(),)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_unpaid_legacy_debts_map(
    student_ids: Optional[list[str]] = None,
) -> dict[str, list[dict[str, Any]]]:
    """Returns {student_id: [unpaid legacy rows...]} (all students when ids is None)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM legacy_debts WHERE COALESCE(is_paid, 0) = 0 ORDER BY id ASC;"
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    wanted = (
        {str(s).strip() for s in student_ids if str(s).strip()}
        if student_ids is not None
        else None
    )
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sid = str(row.get("student_id") or "").strip()
        if not sid or (wanted is not None and sid not in wanted):
            continue
        result.setdefault(sid, []).append(row)
    return result


async def set_legacy_debt_paid(debt_id: int, paid: bool = True) -> bool:
    paid_at = now_tashkent().isoformat() if paid else ""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE legacy_debts SET is_paid = ?, paid_at = ? WHERE id = ?;",
            (1 if paid else 0, paid_at, int(debt_id)),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_legacy_debt(debt_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM legacy_debts WHERE id = ?;", (int(debt_id),)
        )
        await db.commit()
        return cursor.rowcount > 0


async def update_legacy_debts_student_name(student_id: str, new_name: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE legacy_debts SET student_name = ? WHERE student_id = ?;",
            ((new_name or "").strip(), str(student_id).strip()),
        )
        await db.commit()


# ----------------------------------------------------------------------
# Courses catalog CRUD (guest menu)
# ----------------------------------------------------------------------


async def get_courses(active_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM courses"
    if active_only:
        sql += " WHERE COALESCE(is_active, 1) = 1"
    sql += " ORDER BY sort_order ASC, id ASC;"
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_course(course_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM courses WHERE id = ?;", (int(course_id),)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def add_course(
    name: str,
    description: str = "",
    price: int = 0,
    duration: str = "",
    schedule: str = "",
) -> dict[str, Any]:
    created_at = now_tashkent().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM courses;"
        ) as cur:
            max_row = await cur.fetchone()
        next_order = int(max_row[0] or 0) + 1 if max_row else 1
        cursor = await db.execute(
            """
            INSERT INTO courses (
                name, description, price, duration, schedule,
                is_active, sort_order, created_at
            )
            VALUES (?, ?, ?, ?, ?, 1, ?, ?);
            """,
            (
                (name or "").strip(),
                (description or "").strip(),
                max(0, _clean_int(price)),
                (duration or "").strip(),
                (schedule or "").strip(),
                next_order,
                created_at,
            ),
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM courses WHERE id = ?;", (cursor.lastrowid,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else {}


_COURSE_EDITABLE_FIELDS = {"name", "description", "price", "duration", "schedule", "is_active"}


async def update_course(course_id: int, updates: dict[str, Any]) -> bool:
    clean: dict[str, Any] = {}
    for key, val in (updates or {}).items():
        if key not in _COURSE_EDITABLE_FIELDS:
            continue
        if key in {"price", "is_active"}:
            clean[key] = max(0, _clean_int(val))
        else:
            clean[key] = str(val or "").strip()
    if not clean:
        return False
    set_sql = ", ".join(f"{k} = ?" for k in clean)
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            f"UPDATE courses SET {set_sql} WHERE id = ?;",
            (*clean.values(), int(course_id)),
        )
        await db.commit()
        return cursor.rowcount > 0


async def delete_course(course_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM courses WHERE id = ?;", (int(course_id),)
        )
        await db.commit()
        return cursor.rowcount > 0


# ----------------------------------------------------------------------
# Leads CRUD (guest enrollment requests)
# ----------------------------------------------------------------------


async def create_lead(
    telegram_id: int,
    full_name: str,
    phone: str,
    course_id: Optional[int],
    course_name: str,
    username: str = "",
    lang: str = "latn",
    sheet_max_id: int = 0,
) -> dict[str, Any]:
    """
    Inserts a lead with a strictly sequential id.

    Numbering rule: when BOTH SQLite `leads` and the Qiziquvchilar_Lidlar sheet
    (reported via ``sheet_max_id``) are empty, the AUTOINCREMENT counter in
    `sqlite_sequence` is reset and the lead gets id 1; otherwise the id is
    max(existing ids in both places) + 1, so a drifted counter never skips numbers.
    """
    created_at = now_tashkent().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT COALESCE(MAX(id), 0) FROM leads;") as cur:
            row = await cur.fetchone()
            db_max_id = int(row[0] or 0) if row else 0
        sheet_max = max(0, int(sheet_max_id or 0))
        if db_max_id == 0 and sheet_max == 0:
            await db.execute("UPDATE sqlite_sequence SET seq = 0 WHERE name = 'leads';")
            new_id = 1
        else:
            new_id = max(db_max_id, sheet_max) + 1
        cursor = await db.execute(
            """
            INSERT INTO leads (
                id, telegram_id, username, full_name, phone, course_id, course_name,
                lang, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?);
            """,
            (
                new_id,
                int(telegram_id),
                (username or "").strip().lstrip("@"),
                (full_name or "").strip(),
                (phone or "").strip(),
                course_id,
                (course_name or "").strip(),
                lang if lang in VALID_LANGS else "latn",
                created_at,
            ),
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM leads WHERE id = ?;", (cursor.lastrowid,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else {}


async def sync_leads_with_sheet(
    sheet_chat_ids: set[str], grace_seconds: int = 120
) -> int:
    """
    Removes stale SQLite leads whose chat id no longer appears in the
    Qiziquvchilar_Lidlar sheet (an admin deleted the row there), so that account
    may submit a new application. Leads younger than ``grace_seconds`` are kept
    (the sheet append may still be in flight). Returns the number removed.
    """
    removed = 0
    now = now_tashkent()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id, telegram_id, created_at FROM leads;"
        ) as cur:
            rows = [dict(r) for r in await cur.fetchall()]
        stale_ids: list[int] = []
        for r in rows:
            if str(r["telegram_id"]) in sheet_chat_ids:
                continue
            created = to_tashkent(r.get("created_at"))
            if created is not None and (now - created).total_seconds() < grace_seconds:
                continue
            stale_ids.append(int(r["id"]))
        for lead_id in stale_ids:
            await db.execute(
                "DELETE FROM lead_admin_messages WHERE lead_id = ?;", (lead_id,)
            )
            await db.execute("DELETE FROM leads WHERE id = ?;", (lead_id,))
            removed += 1
        if removed:
            await db.commit()
    return removed


async def get_recent_leads(limit: int = 20) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM leads ORDER BY id DESC LIMIT ?;", (int(limit),)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def update_lead_status(lead_id: int, status: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "UPDATE leads SET status = ? WHERE id = ?;",
            ((status or "new").strip(), int(lead_id)),
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_lead(lead_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM leads WHERE id = ?;", (int(lead_id),)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_lead_by_telegram_id(telegram_id: int) -> Optional[dict[str, Any]]:
    """
    The account's application (1 chat_id = max 1 lead). If legacy duplicates exist,
    a contacted one wins over a pending one, then the newest.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM leads WHERE telegram_id = ?
            ORDER BY CASE WHEN status = 'contacted' THEN 0 ELSE 1 END, id DESC
            LIMIT 1;
            """,
            (int(telegram_id),),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def mark_lead_contacted(
    lead_id: int, admin_chat_id: int, contacted_at: str
) -> bool:
    """
    Marks a lead as contacted (status / contacted_at / contacted_by).
    Returns True only when this call performed the transition (not already contacted).
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            UPDATE leads
            SET status = 'contacted', contacted_at = ?, contacted_by = ?
            WHERE id = ? AND status != 'contacted';
            """,
            (contacted_at, int(admin_chat_id), int(lead_id)),
        )
        await db.commit()
        return cursor.rowcount > 0


async def save_lead_admin_message(lead_id: int, admin_id: int, message_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO lead_admin_messages (lead_id, admin_id, message_id)
            VALUES (?, ?, ?);
            """,
            (int(lead_id), int(admin_id), int(message_id)),
        )
        await db.commit()


async def get_lead_admin_messages(lead_id: int) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT admin_id, message_id FROM lead_admin_messages WHERE lead_id = ?;",
            (int(lead_id),),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ----------------------------------------------------------------------
# Self-service profiles (👤 Shaxsiy ma'lumotlarim)
# ----------------------------------------------------------------------


async def get_user_profile(telegram_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_profiles WHERE telegram_id = ?;", (int(telegram_id),)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def upsert_user_profile(
    telegram_id: int,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
) -> dict[str, Any]:
    existing = await get_user_profile(telegram_id) or {}
    new_name = (
        full_name.strip() if full_name is not None else str(existing.get("full_name") or "")
    )
    new_phone = (
        phone.strip() if phone is not None else str(existing.get("phone") or "")
    )
    updated_at = now_tashkent().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_profiles (telegram_id, full_name, phone, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                full_name = excluded.full_name,
                phone = excluded.phone,
                updated_at = excluded.updated_at;
            """,
            (int(telegram_id), new_name, new_phone, updated_at),
        )
        if full_name is not None:
            await db.execute(
                "UPDATE users SET full_name = ? WHERE telegram_id = ?;",
                (new_name, int(telegram_id)),
            )
            await db.execute(
                "UPDATE dynamic_admins SET full_name = ? WHERE telegram_id = ?;",
                (new_name, int(telegram_id)),
            )
            await db.execute(
                "UPDATE teachers SET full_name = ? WHERE telegram_id = ?;",
                (new_name, int(telegram_id)),
            )
        if phone is not None:
            try:
                await db.execute(
                    "UPDATE users SET phone = ? WHERE telegram_id = ?;",
                    (new_phone, int(telegram_id)),
                )
            except Exception:
                pass
            await db.execute(
                "UPDATE dynamic_admins SET phone = ? WHERE telegram_id = ?;",
                (new_phone, int(telegram_id)),
            )
        await db.commit()
    return {"telegram_id": int(telegram_id), "full_name": new_name, "phone": new_phone}
