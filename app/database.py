import json
from datetime import datetime, timezone
from typing import Any, Optional

import aiosqlite

from app.config import DB_PATH

VALID_LANGS = {"latn", "cyrl"}


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
                lang TEXT NOT NULL DEFAULT 'latn'
            );
            """
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
                UNIQUE(group_name, lesson_date)
            );
            """
        )
        for alter_sql in (
            "ALTER TABLE lesson_topics ADD COLUMN topic TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE lesson_topics ADD COLUMN plan TEXT NOT NULL DEFAULT '';",
            "ALTER TABLE lesson_topics ADD COLUMN teacher_id INTEGER;",
            "ALTER TABLE lesson_topics ADD COLUMN created_at TEXT NOT NULL DEFAULT '';",
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
                full_name TEXT NOT NULL,
                current_role TEXT,
                requested_role TEXT NOT NULL,
                invite_code TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
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
            INSERT INTO users (telegram_id, lang)
            VALUES (?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET lang = excluded.lang;
            """,
            (telegram_id, normalized_lang),
        )
        await db.commit()


async def get_user(telegram_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT telegram_id, role, linked_student_id, full_name, lang
            FROM users
            WHERE telegram_id = ?;
            """,
            (telegram_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


async def upsert_user(
    telegram_id: int,
    role: Optional[str] = None,
    linked_student_id: Optional[str] = None,
    full_name: Optional[str] = None,
    lang: Optional[str] = None,
) -> None:
    existing = await get_user(telegram_id)
    if existing:
        new_role = role if role is not None else existing["role"]
        new_linked = (
            linked_student_id
            if linked_student_id is not None
            else existing["linked_student_id"]
        )
        new_name = full_name if full_name is not None else existing["full_name"]
        new_lang = lang if (lang in VALID_LANGS) else existing["lang"]
    else:
        new_role = role
        new_linked = linked_student_id
        new_name = full_name
        new_lang = lang if (lang in VALID_LANGS) else "latn"

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (telegram_id, role, linked_student_id, full_name, lang)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                role = excluded.role,
                linked_student_id = excluded.linked_student_id,
                full_name = excluded.full_name,
                lang = excluded.lang;
            """,
            (telegram_id, new_role, new_linked, new_name, new_lang),
        )
        await db.commit()


async def reset_user_role(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE users
            SET role = NULL, linked_student_id = NULL
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
# Role Change Requests CRUD
# ----------------------------------------------------------------------


async def create_role_change_request(
    user_id: int,
    full_name: str,
    current_role: Optional[str],
    requested_role: str,
    invite_code: str,
) -> int:
    created_at = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            INSERT INTO role_change_requests (
                user_id, full_name, current_role, requested_role,
                invite_code, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, 'pending', ?);
            """,
            (
                user_id,
                full_name.strip(),
                current_role.strip() if current_role else None,
                requested_role.strip(),
                invite_code.strip(),
                created_at,
            ),
        )
        await db.commit()
        return int(cursor.lastrowid)


async def get_role_change_request(req_id: int) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, user_id, full_name, current_role, requested_role,
                   invite_code, status, created_at
            FROM role_change_requests
            WHERE id = ?;
            """,
            (req_id,),
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


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
            SELECT id, user_id, full_name, current_role, requested_role,
                   invite_code, status, created_at
            FROM role_change_requests
            WHERE id = ?;
            """,
            (req_id,),
        ) as sel:
            row = await sel.fetchone()
            return dict(row) if row else None


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
    created_at = datetime.now(timezone.utc).isoformat()
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
    created_at = datetime.now(timezone.utc).isoformat()
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
    return data


async def save_lesson_topic(
    group_name: str,
    lesson_date: str,
    topic: str,
    plan: str = "",
    teacher_id: Optional[int] = None,
) -> dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_group = group_name.strip()
    clean_date = lesson_date.strip()
    clean_topic = topic.strip()
    clean_plan = plan.strip()

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            """
            INSERT INTO lesson_topics (
                group_name, lesson_date, topic_title, lesson_details,
                created_by, updated_at, topic, plan, teacher_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_name, lesson_date) DO UPDATE SET
                topic_title = excluded.topic_title,
                lesson_details = excluded.lesson_details,
                created_by = COALESCE(excluded.created_by, lesson_topics.created_by),
                updated_at = excluded.updated_at,
                topic = excluded.topic,
                plan = excluded.plan,
                teacher_id = COALESCE(excluded.teacher_id, lesson_topics.teacher_id),
                created_at = excluded.created_at;
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
                now_iso,
            ),
        )
        await db.commit()
        async with db.execute(
            """
            SELECT id, group_name, lesson_date, topic_title, lesson_details,
                   created_by, updated_at, topic, plan, teacher_id, created_at
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
) -> dict[str, Any]:
    return await save_lesson_topic(
        group_name=group_name,
        lesson_date=lesson_date,
        topic=topic_title,
        plan=lesson_details,
        teacher_id=created_by,
    )


async def get_lesson_topic(
    group_name: str, lesson_date: str
) -> Optional[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT id, group_name, lesson_date, topic_title, lesson_details,
                   created_by, updated_at, topic, plan, teacher_id, created_at
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
                   created_by, updated_at, topic, plan, teacher_id, created_at
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


# ----------------------------------------------------------------------
# Admin Invites & Dynamic Admins CRUD
# ----------------------------------------------------------------------


async def create_admin_invite(code: str, created_by: int) -> dict[str, Any]:
    created_at = datetime.now(timezone.utc).isoformat()
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