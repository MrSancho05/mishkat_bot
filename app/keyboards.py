import re
from typing import Any, Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import (
    InlineKeyboardBuilder as _AiogramInlineKeyboardBuilder,
    ReplyKeyboardBuilder as _AiogramReplyKeyboardBuilder,
)

from app.locales import WEEKDAYS_SHORT, t


# ----------------------------------------------------------------------
# Button layout: never let a label get cut off with "..."
# ----------------------------------------------------------------------

# A half-width slot on a phone shows roughly 22-24 characters (emoji count double).
# Every static label is written to stay well below that; this is only the safety
# net for long dynamic labels (group, teacher and student names).
_MAX_PAIR_LABEL_WIDTH = 24
_MAX_TRIPLE_LABEL_WIDTH = 12

_ZWJ_TAIL_RE = re.compile("\u200d.")


def label_width(text: str) -> int:
    """Visual width of a button label (emoji are about two characters wide)."""
    clean = _ZWJ_TAIL_RE.sub("", str(text or "")).replace("\u200d", "").replace("\ufe0f", "")
    wide = sum(
        1
        for ch in clean
        if (ord(ch) >= 0x1F000 and not 0x1F1E6 <= ord(ch) <= 0x1F1FF)
        or 0x2600 <= ord(ch) <= 0x27BF
        or 0x2B00 <= ord(ch) <= 0x2BFF
    )
    return len(clean) + wide


def _split_wide_rows(rows: list[list[Any]]) -> list[list[Any]]:
    """
    Rows whose buttons would not fit side by side get one button per line, so
    every label is shown in full and visually centred in a full-width button.
    """
    balanced: list[list[Any]] = []
    for row in rows:
        if len(row) >= 2:
            limit = _MAX_PAIR_LABEL_WIDTH if len(row) == 2 else _MAX_TRIPLE_LABEL_WIDTH
            if any(label_width(btn.text) > limit for btn in row):
                balanced.extend([btn] for btn in row)
                continue
        balanced.append(list(row))
    return balanced


def balance_inline_markup(markup: InlineKeyboardMarkup) -> InlineKeyboardMarkup:
    """Apply the same no-truncation row balancing to a hand-built inline markup."""
    return markup.model_copy(
        update={"inline_keyboard": _split_wide_rows(markup.inline_keyboard)}
    )


def pair_buttons(
    buttons: list[InlineKeyboardButton], per_row: int = 2
) -> list[list[InlineKeyboardButton]]:
    """Chunk buttons into rows of `per_row` (2 by default)."""
    return [list(buttons[i : i + per_row]) for i in range(0, len(buttons), per_row)]


class InlineKeyboardBuilder(_AiogramInlineKeyboardBuilder):
    def as_markup(self, **kwargs: Any) -> InlineKeyboardMarkup:
        markup = super().as_markup(**kwargs)
        return markup.model_copy(
            update={"inline_keyboard": _split_wide_rows(markup.inline_keyboard)}
        )


class ReplyKeyboardBuilder(_AiogramReplyKeyboardBuilder):
    def as_markup(self, **kwargs: Any) -> ReplyKeyboardMarkup:
        markup = super().as_markup(**kwargs)
        return markup.model_copy(
            update={"keyboard": _split_wide_rows(markup.keyboard)}
        )


_LOCAL_BTN_LABELS: dict[str, dict[str, str]] = {
    "latn": {
        "count_8": "8 ta dars",
        "count_12": "12 ta dars",
        "self_teacher": "👤 O‘zimni tanlash",
        "invite_new_teacher": "🔗 Taklif havolasi",
        "add_group": "➕ Yangi guruh",
        "edit_group": "✏️ Guruhni tahrirlash",
        "add_student": "➕ Yangi talaba",
        "manage_students": "👤 Talabalar ro‘yxati",
        "student_invite": "🔗 Havola orqali",
        "attach_stu_device": "📱 Qurilma ulash",
        "toggle_status_to_inactive": "🔴 O‘qimayapti",
        "toggle_status_to_active": "🟢 O‘qiyapti",
        "edit_info": "✏️ Tahrirlash",
        "show_links": "🔗 Havolalar",
        "delete_student": "🗑 O‘chirish",
        "field_name": "👤 F.I.O.",
        "field_stu_phone": "📞 Talaba tel",
        "field_stu_tg": "✈️ Telegram",
        "field_father_phone": "🧔‍♂️ Otasi tel",
        "field_mother_phone": "🧕 Onasi tel",
        "field_group": "📚 Guruh",
        "field_teacher": "👨‍🏫 Ustoz",
        "field_lesson_count": "🔢 Dars soni",
        "field_days": "📆 Dars kunlari",
        "field_time": "⏰ Dars vaqti",
        "field_price": "💰 To‘lov summasi",
        "profile_edit_name": "✏️ Ismni o‘zgartirish",
        "profile_edit_phone": "📱 Raqamni yangilash",
        "profile_switch_parent": "🔄 Ota/Ona rolini almashtirish",
        "skip": "⏭ O‘tkazib yuborish",
        "att_topic_btn": "📝 Mavzu / reja",
        "admin_new_invite": "🔗 Yangi havola",
        "admin_remove": "🗑 Adminni o‘chirish",
        "tch_assign_group": "🔗 Guruh biriktirish",
        "tch_delete": "🗑 Ustozni o‘chirish",
        "tch_del_yes": "✅ Ha, o‘chirish",
        "tch_del_no": "❌ Bekor qilish",
        "transfer_cancel": "⬅️ Bekor qilish",
        "topic_new_btn": "➕ Yangi mavzu",
        "topic_history_btn": "📚 Mavzular tarixi",
        "add_more_child": "➕ Yana farzand",
        "legacy_add": "➕ Avvalgi qarz",
        "legacy_list": "📜 Avvalgi qarzlar",
    },
    "cyrl": {
        "count_8": "8 та дарс",
        "count_12": "12 та дарс",
        "self_teacher": "👤 Ўзимни танлаш",
        "invite_new_teacher": "🔗 Таклиф ҳаволаси",
        "add_group": "➕ Янги гуруҳ",
        "edit_group": "✏️ Гуруҳни таҳрирлаш",
        "add_student": "➕ Янги талаба",
        "manage_students": "👤 Талабалар рўйхати",
        "student_invite": "🔗 Ҳавола орқали",
        "attach_stu_device": "📱 Қурилма улаш",
        "toggle_status_to_inactive": "🔴 Ўқимаяпти",
        "toggle_status_to_active": "🟢 Ўқияпти",
        "edit_info": "✏️ Таҳрирлаш",
        "show_links": "🔗 Ҳаволалар",
        "delete_student": "🗑 Ўчириш",
        "field_name": "👤 Ф.И.О.",
        "field_stu_phone": "📞 Талаба тел",
        "field_stu_tg": "✈️ Telegram",
        "field_father_phone": "🧔‍♂️ Отаси тел",
        "field_mother_phone": "🧕 Онаси тел",
        "field_group": "📚 Гуруҳ",
        "field_teacher": "👨‍🏫 Устоз",
        "field_lesson_count": "🔢 Дарс сони",
        "field_days": "📆 Дарс кунлари",
        "field_time": "⏰ Дарс вақти",
        "field_price": "💰 Тўлов суммаси",
        "profile_edit_name": "✏️ Исмни ўзгартириш",
        "profile_edit_phone": "📱 Рақамни янгилаш",
        "profile_switch_parent": "🔄 Ота/Она ролини алмаштириш",
        "skip": "⏭ Ўтказиб юбориш",
        "att_topic_btn": "📝 Мавзу / режа",
        "admin_new_invite": "🔗 Янги ҳавола",
        "admin_remove": "🗑 Админни ўчириш",
        "tch_assign_group": "🔗 Гуруҳ бириктириш",
        "tch_delete": "🗑 Устозни ўчириш",
        "tch_del_yes": "✅ Ҳа, ўчириш",
        "tch_del_no": "❌ Бекор қилиш",
        "transfer_cancel": "⬅️ Бекор қилиш",
        "topic_new_btn": "➕ Янги мавзу",
        "topic_history_btn": "📚 Мавзулар тарихи",
        "add_more_child": "➕ Яна фарзанд",
        "legacy_add": "➕ Аввалги қарз",
        "legacy_list": "📜 Аввалги қарзлар",
    },
}


def _lbl(key: str, lang: str) -> str:
    safe_lang = lang if lang in _LOCAL_BTN_LABELS else "latn"
    return _LOCAL_BTN_LABELS[safe_lang][key]


def _btn(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def _confirm_nav(
    builder: InlineKeyboardBuilder,
    lang: str,
    confirm_cb: str,
    cancel_cb: str,
    back_cb: Optional[str] = None,
) -> None:
    """[✅ Tasdiqlash | ❌ Bekor qilish] on one row, optional full-width Back below."""
    builder.row(
        _btn(t("btn_confirm", lang), confirm_cb),
        _btn(t("btn_cancel", lang), cancel_cb),
    )
    if back_cb:
        builder.row(_btn(t("btn_back", lang), back_cb))


def _add_weekday_buttons(
    builder: InlineKeyboardBuilder,
    selected_days: list[int],
    lang: str,
    callback_template: str,
) -> None:
    """Seven weekday toggles laid out two per row (call before adding other rows)."""
    safe_lang = lang if lang in WEEKDAYS_SHORT else "latn"
    days_map = WEEKDAYS_SHORT[safe_lang]
    for day_idx in range(7):
        mark = "✅" if day_idx in selected_days else "❌"
        builder.button(
            text=f"{mark} {days_map[day_idx]}",
            callback_data=callback_template.format(idx=day_idx),
        )
    builder.adjust(2)


def _nav_row(
    builder: InlineKeyboardBuilder,
    lang: str = "latn",
    back_cb: Optional[str] = None,
    cancel_cb: Optional[str] = None,
) -> None:
    buttons: list[InlineKeyboardButton] = []
    if back_cb:
        buttons.append(
            InlineKeyboardButton(text=t("btn_back", lang), callback_data=back_cb)
        )
    if cancel_cb:
        buttons.append(
            InlineKeyboardButton(text=t("btn_cancel", lang), callback_data=cancel_cb)
        )
    if buttons:
        builder.row(*buttons)


# ----------------------------------------------------------------------
# Language Selection & Global FSM Lock
# ----------------------------------------------------------------------


def lang_selection_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=t("btn_lang_latn", "latn"), callback_data="set_lang:latn")
    builder.button(text=t("btn_lang_cyrl", "cyrl"), callback_data="set_lang:cyrl")
    builder.adjust(2)
    return builder.as_markup()


def global_cancel_fsm_kb(lang: str = "latn") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("btn_cancel", lang), callback_data="global_cancel_fsm"
        )
    )
    return builder.as_markup()


# ----------------------------------------------------------------------
# Expandable Notification Keyboard (📄 Batafsil / 📋 Qisqacha)
# ----------------------------------------------------------------------


def build_expandable_notif_kb(
    notif_id: int | str,
    expanded: bool = False,
    lang: str = "latn",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    btn_text = t("btn_short", lang) if expanded else t("btn_detailed", lang)
    builder.row(
        InlineKeyboardButton(
            text=btn_text,
            callback_data=f"notif_toggle:{notif_id}:{int(not expanded)}",
        )
    )
    return builder.as_markup()


# ----------------------------------------------------------------------
# Role-Lock & Role-Change Request Keyboards
# ----------------------------------------------------------------------


def role_lock_request_kb(
    invite_code: str,
    requested_role: str,
    lang: str = "latn",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("btn_request_role_change", lang),
            callback_data=f"role_req:send:{requested_role}:{invite_code}",
        )
    )
    return builder.as_markup()


def role_change_admin_kb(
    req_id: int, lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(t("btn_role_change_approve", lang), f"role_req:approve:{req_id}"),
        _btn(t("btn_role_change_reject", lang), f"role_req:reject:{req_id}"),
    )
    return builder.as_markup()


def build_dual_role_approval_kb(
    req_id: str, lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(t("btn_dual_role_keep_both", lang), f"dual_role:keep_both:{req_id}"),
        _btn(t("btn_dual_role_replace", lang), f"dual_role:replace:{req_id}"),
    )
    builder.row(
        _btn(t("btn_dual_role_reject", lang), f"dual_role:reject:{req_id}")
    )
    return builder.as_markup()


# ----------------------------------------------------------------------
# Main Role Menus (ReplyKeyboards)
# ----------------------------------------------------------------------


def admin_menu_kb(lang: str = "latn") -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=t("menu_admin_groups", lang)),
        KeyboardButton(text=t("menu_admin_students", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_admin_attendance", lang)),
        KeyboardButton(text=t("btn_archive_group", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_admin_payments", lang)),
        KeyboardButton(text=t("menu_admin_debtors", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_admin_manage_teachers", lang)),
        KeyboardButton(text=t("menu_admin_manage_admins", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_admin_courses", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_profile", lang)),
        KeyboardButton(text=t("btn_change_lang", lang)),
    )
    return builder.as_markup(resize_keyboard=True)


def teacher_menu_kb(lang: str = "latn") -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=t("menu_teacher_topic", lang)),
        KeyboardButton(text=t("menu_teacher_groups", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_teacher_attendance", lang)),
        KeyboardButton(text=t("menu_teacher_add_student", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_teacher_payments", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_profile", lang)),
        KeyboardButton(text=t("btn_change_lang", lang)),
    )
    return builder.as_markup(resize_keyboard=True)


get_teacher_main_kb = teacher_menu_kb


def student_menu_kb(
    lang: str = "latn", has_dual_role: bool = False
) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=t("menu_student_group", lang)),
        KeyboardButton(text=t("menu_student_schedule", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_student_payments", lang)),
        KeyboardButton(text=t("menu_profile", lang)),
    )
    if has_dual_role:
        builder.row(
            KeyboardButton(text=t("btn_change_lang", lang)),
            KeyboardButton(text=t("btn_switch_to_parent", lang)),
        )
    else:
        builder.row(
            KeyboardButton(text=t("btn_change_lang", lang)),
        )
    return builder.as_markup(resize_keyboard=True)


def parent_menu_kb(
    lang: str = "latn", has_dual_role: bool = False
) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=t("menu_parent_schedule", lang)),
        KeyboardButton(text=t("menu_parent_payments", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_profile", lang)),
        KeyboardButton(text=t("btn_change_lang", lang)),
    )
    if has_dual_role:
        builder.row(
            KeyboardButton(text=t("btn_switch_to_student", lang)),
        )
    return builder.as_markup(resize_keyboard=True)


def guest_menu_kb(lang: str = "latn") -> ReplyKeyboardMarkup:
    """Menu for brand-new users without an approved role."""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=t("menu_guest_courses", lang)),
        KeyboardButton(text=t("menu_guest_enroll", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_guest_contact", lang)),
        KeyboardButton(text=t("btn_change_lang", lang)),
    )
    return builder.as_markup(resize_keyboard=True)


def get_main_menu_kb(
    role: str, lang: str = "latn", has_dual_role: bool = False
) -> ReplyKeyboardMarkup:
    if role == "guest":
        return guest_menu_kb(lang)
    if role == "admin":
        return admin_menu_kb(lang)
    if role == "teacher":
        return teacher_menu_kb(lang)
    if role == "student":
        return student_menu_kb(lang, has_dual_role=has_dual_role)
    return parent_menu_kb(lang, has_dual_role=has_dual_role)


def cancel_reply_kb(
    lang: str = "latn", include_back: bool = False
) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    if include_back:
        builder.row(
            KeyboardButton(text=t("btn_back", lang)),
            KeyboardButton(text=t("btn_cancel", lang)),
        )
    else:
        builder.row(KeyboardButton(text=t("btn_cancel", lang)))
    return builder.as_markup(resize_keyboard=True)


def share_phone_reply_kb(
    lang: str = "latn", include_back: bool = True
) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(
            text=t("btn_share_phone", lang),
            request_contact=True,
        )
    )
    if include_back:
        builder.row(
            KeyboardButton(text=t("btn_back", lang)),
            KeyboardButton(text=t("btn_cancel", lang)),
        )
    else:
        builder.row(KeyboardButton(text=t("btn_cancel", lang)))
    return builder.as_markup(resize_keyboard=True, one_time_keyboard=True)


def join_share_phone_kb(lang: str = "latn") -> ReplyKeyboardMarkup:
    return share_phone_reply_kb(lang=lang, include_back=True)


# ----------------------------------------------------------------------
# Parent Role Choice & Personal Profile Keyboards
# ----------------------------------------------------------------------


def parent_type_kb(lang: str = "latn") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("btn_parent_father", lang),
            callback_data="parent_type:father",
        ),
        InlineKeyboardButton(
            text=t("btn_parent_mother", lang),
            callback_data="parent_type:mother",
        ),
    )
    _nav_row(builder, lang=lang, cancel_cb="parent_type:cancel")
    return builder.as_markup()


def profile_actions_kb(lang: str = "latn", role: str = "") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("profile_edit_name", lang),
            callback_data="profile_edit:name",
        ),
        InlineKeyboardButton(
            text=_lbl("profile_edit_phone", lang),
            callback_data="profile_edit:phone",
        ),
    )
    if role == "parent":
        builder.row(
            InlineKeyboardButton(
                text=_lbl("profile_switch_parent", lang),
                callback_data="profile_edit:role",
            )
        )
    _nav_row(builder, lang=lang, cancel_cb="profile_edit:close")
    return builder.as_markup()


def profile_parent_role_kb(
    lang: str = "latn",
    back_cb: str = "profile_edit:back",
    cancel_cb: str = "profile_edit:close",
) -> InlineKeyboardMarkup:
    """🧔 Otasi / 🧕 Onasi picker for the parent role switch."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("btn_parent_father", lang),
            callback_data="profile_role:father",
        ),
        InlineKeyboardButton(
            text=t("btn_parent_mother", lang),
            callback_data="profile_role:mother",
        ),
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    return builder.as_markup()


def profile_step_nav_kb(
    lang: str = "latn",
    back_cb: str = "profile_edit:back",
    cancel_cb: str = "profile_edit:close",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    return builder.as_markup()


# ----------------------------------------------------------------------
# Teacher Management Keyboards (Admin)
# ----------------------------------------------------------------------


def teacher_manage_list_kb(
    teachers: list[dict], lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tch in teachers:
        tid = str(tch.get("Ustoz_ID", "")).strip()
        name = str(tch.get("F.I.O.", "")).strip() or tid
        grp_count = len(tch.get("assigned_groups") or [])
        builder.button(
            text=f"👨‍🏫 {name} ({grp_count})",
            callback_data=f"tch_mgr:view:{tid}",
        )
    builder.adjust(2)
    _nav_row(builder, lang=lang, back_cb="tch_mgr:back_menu")
    return builder.as_markup()


def teacher_manage_actions_kb(
    teacher_id: str, lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("tch_assign_group", lang),
            callback_data=f"tch_mgr:assign:{teacher_id}",
        ),
        InlineKeyboardButton(
            text=_lbl("tch_delete", lang),
            callback_data=f"tch_mgr:del:{teacher_id}",
        ),
    )
    _nav_row(builder, lang=lang, back_cb="tch_mgr:list")
    return builder.as_markup()


def teacher_manage_assign_groups_kb(
    teacher_id: str, groups: list[dict], lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for grp in groups:
        g_name = str(grp.get("Guruh_Nomi", "")).strip()
        if g_name:
            builder.button(
                text=f"📚 {g_name}",
                callback_data=f"tch_mgr:assign_grp:{teacher_id}:{g_name}",
            )
    builder.adjust(2)
    _nav_row(builder, lang=lang, back_cb=f"tch_mgr:view:{teacher_id}")
    return builder.as_markup()


def teacher_manage_confirm_delete_kb(
    teacher_id: str, lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("tch_del_yes", lang),
            callback_data=f"tch_mgr:del_ok:{teacher_id}",
        ),
        InlineKeyboardButton(
            text=_lbl("tch_del_no", lang),
            callback_data=f"tch_mgr:view:{teacher_id}",
        ),
    )
    return builder.as_markup()


# ----------------------------------------------------------------------
# Admin Management Keyboards
# ----------------------------------------------------------------------


def admin_manage_menu_kb(lang: str = "latn") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(_lbl("admin_new_invite", lang), "adm_mng:invite"),
        _btn(t("btn_admin_list", lang), "adm_mng:list"),
    )
    builder.row(_btn(_lbl("admin_remove", lang), "adm_mng:remove"))
    _nav_row(builder, lang=lang, cancel_cb="adm_mng:cancel")
    return builder.as_markup()


def admin_remove_list_kb(
    admins: list[dict], lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for adm in admins:
        tid = adm["telegram_id"]
        name = adm.get("full_name") or str(tid)
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 {name} ({tid})",
                callback_data=f"adm_rm:{tid}",
            )
        )
    _nav_row(
        builder,
        lang=lang,
        back_cb="adm_mng:back",
        cancel_cb="adm_mng:cancel",
    )
    return builder.as_markup()


def admin_remove_confirm_kb(
    telegram_id: int, lang: str = "latn"
) -> InlineKeyboardMarkup:
    return confirm_cancel_kb(
        confirm_cb=f"adm_rm_ok:{telegram_id}",
        cancel_cb="adm_mng:cancel",
        lang=lang,
        back_cb="adm_mng:remove",
    )


# ----------------------------------------------------------------------
# Group Self-Join Keyboards
# ----------------------------------------------------------------------


def join_approval_kb(request_id: int, lang: str = "latn") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("join_btn_approve", lang),
            callback_data=f"join_approve:{request_id}",
        ),
        InlineKeyboardButton(
            text=t("join_btn_reject", lang),
            callback_data=f"join_reject:{request_id}",
        ),
    )
    return builder.as_markup()


# ----------------------------------------------------------------------
# Shared Inline Keyboards
# ----------------------------------------------------------------------


def groups_inline_kb(
    groups: list[dict],
    prefix: str,
    lang: str = "latn",
    include_back: bool = False,
    include_cancel: bool = True,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for g in groups:
        name = g["Guruh_Nomi"]
        builder.button(text=f"📚 {name}", callback_data=f"{prefix}:{name}")
    builder.adjust(2)
    _nav_row(
        builder,
        lang=lang,
        back_cb=f"{prefix}:__back__" if include_back else None,
        cancel_cb=f"{prefix}:__cancel__" if include_cancel else None,
    )
    return builder.as_markup()


def confirm_cancel_kb(
    confirm_cb: str,
    cancel_cb: str,
    lang: str = "latn",
    back_cb: Optional[str] = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _confirm_nav(builder, lang, confirm_cb, cancel_cb, back_cb)
    return builder.as_markup()


def step_nav_inline_kb(
    lang: str = "latn",
    back_cb: Optional[str] = None,
    cancel_cb: Optional[str] = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    return builder.as_markup()


# ----------------------------------------------------------------------
# Schedule Setup Keyboards
# ----------------------------------------------------------------------


def lesson_count_kb(
    lang: str = "latn", back_cb: str = "sched_back:group"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("count_8", lang), callback_data="sched_count:8"
        ),
        InlineKeyboardButton(
            text=_lbl("count_12", lang), callback_data="sched_count:12"
        ),
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="sched_cancel")
    return builder.as_markup()


def weekdays_toggle_kb(
    selected_days: list[int],
    lang: str = "latn",
    back_cb: str = "sched_back:count",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _add_weekday_buttons(builder, selected_days, lang, "sched_day:{idx}")
    _confirm_nav(builder, lang, "sched_days_done", "sched_cancel", back_cb)
    return builder.as_markup()


# ----------------------------------------------------------------------
# Group Menu, Create & Edit Group, Full Update Wizard, Teacher Invite
# ----------------------------------------------------------------------


def groups_root_menu_kb(lang: str = "latn") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("add_group", lang), callback_data="grp_menu:add"
        ),
        InlineKeyboardButton(
            text=_lbl("edit_group", lang), callback_data="grp_menu:edit"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=t("teacher_invite_btn", lang), callback_data="grp_menu:add_teacher"
        ),
        InlineKeyboardButton(
            text=t("btn_delete_group", lang), callback_data="grp_menu:delete"
        ),
    )
    _nav_row(builder, lang=lang, cancel_cb="grp_menu:cancel")
    return builder.as_markup()


def group_delete_confirm_kb(
    group_name: str, lang: str = "latn"
) -> InlineKeyboardMarkup:
    return confirm_cancel_kb(
        confirm_cb=f"grp_del_ok:{group_name}",
        cancel_cb="grp_menu:cancel",
        lang=lang,
        back_cb="grp_menu:delete",
    )


def teacher_add_cancel_kb(
    lang: str = "latn", back_cb: Optional[str] = "tch_add:back"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="tch_add:cancel")
    return builder.as_markup()


def group_add_cancel_kb(
    lang: str = "latn", back_cb: Optional[str] = None
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="grp_add:cancel")
    return builder.as_markup()


def group_add_teacher_kb(
    teachers: Optional[list[dict]] = None,
    lang: str = "latn",
    back_cb: str = "grp_add:back:name",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tch in teachers or []:
        tg_id = tch.get("telegram_id") or tch.get("Chat_ID")
        full_name = tch.get("full_name") or tch.get("F.I.O.", "")
        if tg_id:
            builder.button(
                text=f"👨‍🏫 {full_name}",
                callback_data=f"grp_add:teacher:{tg_id}",
            )
    if teachers:
        builder.adjust(2)
    builder.row(
        _btn(_lbl("self_teacher", lang), "grp_add:self_teacher"),
        _btn(_lbl("invite_new_teacher", lang), "grp_add:invite_teacher"),
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="grp_add:cancel")
    return builder.as_markup()


def group_add_lesson_count_kb(
    lang: str = "latn", back_cb: str = "grp_add:back:teacher"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("count_8", lang), callback_data="grp_add:count:8"
        ),
        InlineKeyboardButton(
            text=_lbl("count_12", lang), callback_data="grp_add:count:12"
        ),
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="grp_add:cancel")
    return builder.as_markup()


def group_add_weekdays_kb(
    selected_days: list[int],
    lang: str = "latn",
    back_cb: str = "grp_add:back:count",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _add_weekday_buttons(builder, selected_days, lang, "grp_add:day:{idx}")
    _confirm_nav(builder, lang, "grp_add:days_done", "grp_add:cancel", back_cb)
    return builder.as_markup()


def group_add_confirm_kb(
    lang: str = "latn", back_cb: str = "grp_add:back:time"
) -> InlineKeyboardMarkup:
    """
    [📅 Boshlanish sanasini o‘zgartirish] sits on its own full-width row directly
    ABOVE the [✅ Tasdiqlash | ❌ Bekor qilish] row; Back goes below.
    """
    builder = InlineKeyboardBuilder()
    builder.row(_btn(t("btn_change_start_date", lang), "grp_add:pick_start"))
    _confirm_nav(builder, lang, "grp_add:confirm", "grp_add:cancel", back_cb)
    return builder.as_markup()


def enroll_choice_kb(
    full_cb: str,
    new_cb: str,
    lang: str = "latn",
    extra_row: Optional[tuple[str, str]] = None,
) -> InlineKeyboardMarkup:
    """
    Mid-cycle enrollment choice for a NEW student: the labels are long, so every
    choice gets its own full-width row; an optional extra (e.g. reject) row follows.
    """
    builder = InlineKeyboardBuilder()
    builder.row(_btn(t("btn_enroll_full", lang), full_cb))
    builder.row(_btn(t("btn_enroll_new", lang), new_cb))
    if extra_row:
        builder.row(_btn(extra_row[0], extra_row[1]))
    return builder.as_markup()


def group_start_calendar_kb(
    year: int,
    month: int,
    selected: Optional[Any] = None,
    lang: str = "latn",
    back_cb: str = "grp_cal:back",
) -> InlineKeyboardMarkup:
    """
    Interactive monthly calendar: [◀️ | Month YYYY | ▶️], weekday header row and
    one clickable button per day (callback grp_cal:day:YYYY-MM-DD).
    `selected` (a date) is highlighted.
    """
    from app.locales import MONTHS_UZ
    from app.utils import month_weeks, shift_month

    safe_lang = lang if lang in MONTHS_UZ else "latn"
    prev_y, prev_m = shift_month(year, month, -1)
    next_y, next_m = shift_month(year, month, 1)
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn("◀️", f"grp_cal:nav:{prev_y:04d}-{prev_m:02d}"),
        _btn(f"{MONTHS_UZ[safe_lang][month]} {year}", "grp_cal:noop"),
        _btn("▶️", f"grp_cal:nav:{next_y:04d}-{next_m:02d}"),
    )
    wk = WEEKDAYS_SHORT.get(safe_lang) or WEEKDAYS_SHORT["latn"]
    builder.row(*[_btn(str(wk[i])[:2], "grp_cal:noop") for i in range(7)])
    for week in month_weeks(year, month):
        row: list[InlineKeyboardButton] = []
        for day in week:
            if day == 0:
                row.append(_btn(" ", "grp_cal:noop"))
                continue
            is_selected = (
                selected is not None
                and selected.year == year
                and selected.month == month
                and selected.day == day
            )
            row.append(
                _btn(
                    f"✅{day}" if is_selected else str(day),
                    f"grp_cal:day:{year:04d}-{month:02d}-{day:02d}",
                )
            )
        builder.row(*row)
    builder.row(_btn(t("btn_back", lang), back_cb))
    return builder.as_markup()


def group_edit_fields_kb(
    group_name: str, lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(_lbl("field_teacher", lang), f"grp_edit_fld:{group_name}:teacher"),
        _btn(_lbl("field_lesson_count", lang), f"grp_edit_fld:{group_name}:count"),
    )
    builder.row(
        _btn(_lbl("field_days", lang), f"grp_edit_fld:{group_name}:days"),
        _btn(_lbl("field_time", lang), f"grp_edit_fld:{group_name}:time"),
    )
    builder.row(
        _btn(_lbl("field_price", lang), f"grp_edit_fld:{group_name}:price"),
        _btn(
            t("btn_group_full_update", lang),
            f"grp_edit_fld:{group_name}:full_update",
        ),
    )
    _nav_row(
        builder,
        lang=lang,
        back_cb="grp_edit:back:list",
        cancel_cb="grp_edit:cancel",
    )
    return builder.as_markup()


def full_group_edit_step_kb(
    lang: str = "latn",
    skip_cb: str = "full_grp:skip_field",
    cancel_cb: str = "full_grp:cancel",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(t("btn_keep_current", lang), skip_cb),
        _btn(t("btn_cancel", lang), cancel_cb),
    )
    return builder.as_markup()


def full_group_edit_count_kb(
    lang: str = "latn",
    skip_cb: str = "full_grp:skip_field",
    cancel_cb: str = "full_grp:cancel",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(_lbl("count_8", lang), "full_grp:count:8"),
        _btn(_lbl("count_12", lang), "full_grp:count:12"),
    )
    builder.row(
        _btn(t("btn_keep_current", lang), skip_cb),
        _btn(t("btn_cancel", lang), cancel_cb),
    )
    return builder.as_markup()


def full_group_edit_weekdays_kb(
    selected_days: list[int],
    lang: str = "latn",
    skip_cb: str = "full_grp:skip_field",
    cancel_cb: str = "full_grp:cancel",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _add_weekday_buttons(builder, selected_days, lang, "full_grp:day:{idx}")
    builder.row(
        _btn(t("btn_confirm", lang), "full_grp:days_done"),
        _btn(t("btn_keep_current", lang), skip_cb),
    )
    builder.row(_btn(t("btn_cancel", lang), cancel_cb))
    return builder.as_markup()


def full_group_edit_confirm_kb(lang: str = "latn") -> InlineKeyboardMarkup:
    return confirm_cancel_kb(
        confirm_cb="full_grp:confirm_all",
        cancel_cb="full_grp:cancel",
        lang=lang,
    )


def group_edit_teacher_kb(
    group_name: str,
    teachers: Optional[list[dict]] = None,
    lang: str = "latn",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for tch in teachers or []:
        tg_id = tch.get("telegram_id") or tch.get("Chat_ID")
        full_name = tch.get("full_name") or tch.get("F.I.O.", "")
        if tg_id:
            builder.button(
                text=f"👨‍🏫 {full_name}",
                callback_data=f"grp_edit_tch:{group_name}:{tg_id}",
            )
    if teachers:
        builder.adjust(2)
    builder.row(
        _btn(_lbl("self_teacher", lang), f"grp_edit_tch:{group_name}:__self__"),
        _btn(
            _lbl("invite_new_teacher", lang),
            f"grp_edit_tch:{group_name}:__invite__",
        ),
    )
    _nav_row(
        builder,
        lang=lang,
        back_cb=f"grp_edit:back:fields:{group_name}",
        cancel_cb="grp_edit:cancel",
    )
    return builder.as_markup()


def group_edit_lesson_count_kb(
    group_name: str, lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("count_8", lang),
            callback_data=f"grp_edit_cnt:{group_name}:8",
        ),
        InlineKeyboardButton(
            text=_lbl("count_12", lang),
            callback_data=f"grp_edit_cnt:{group_name}:12",
        ),
    )
    _nav_row(
        builder,
        lang=lang,
        back_cb=f"grp_edit:back:fields:{group_name}",
        cancel_cb="grp_edit:cancel",
    )
    return builder.as_markup()


def group_edit_weekdays_kb(
    group_name: str, selected_days: list[int], lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    _add_weekday_buttons(builder, selected_days, lang, "grp_edit_day:{idx}")
    _confirm_nav(
        builder,
        lang,
        f"grp_edit_days_done:{group_name}",
        "grp_edit:cancel",
        f"grp_edit:back:fields:{group_name}",
    )
    return builder.as_markup()


# ----------------------------------------------------------------------
# Attendance, Lesson Topic & Plan, Admin Attendance Report Keyboards
# ----------------------------------------------------------------------


def build_attendance_mode_kb(
    today_str: str, lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(t("attendance_btn_today", lang, today_date=today_str), "att_mode:today"),
        _btn(t("attendance_btn_other_day", lang), "att_mode:other"),
    )
    return builder.as_markup()


def attendance_date_picker_kb(
    dates_info: list[dict],
    group_name: str,
    lang: str = "latn",
    include_topic_btn: bool = True,
    back_cb: str = "att_back:group",
    cancel_cb: str = "att_cancel",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in dates_info:
        date_str = item["date_str"]
        weekday = item.get("weekday") or ""
        if item.get("is_cancelled"):
            status_icon = "🚫"
        elif item.get("is_marked"):
            status_icon = "✅"
        else:
            status_icon = "⏳"
        label = (
            f"📅 {date_str} ({weekday}) {status_icon}"
            if weekday
            else f"📅 {date_str} {status_icon}"
        )
        builder.button(text=label, callback_data=f"att_date:{date_str}")
    builder.adjust(2)
    if include_topic_btn:
        builder.row(
            InlineKeyboardButton(
                text=_lbl("att_topic_btn", lang),
                callback_data=f"att_topic_menu:{group_name}",
            )
        )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    return builder.as_markup()


def attendance_marking_kb(
    students: list[dict],
    marks_map: dict[str, str],
    lang: str = "latn",
    back_cb: str = "att_back:date",
    include_topic_btn: bool = True,
    topic_cb: str = "att_topic_current",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in students:
        sid = s["Talaba_ID"]
        name = s["F.I.O."]
        current = marks_map.get(sid, "✅")
        status_icon = "🟢" if current == "✅" else "🔴"
        builder.row(
            InlineKeyboardButton(
                text=f"{status_icon} {name}",
                callback_data=f"att_toggle:{sid}",
            )
        )
    action_row = []
    if include_topic_btn:
        action_row.append(_btn(_lbl("att_topic_btn", lang), topic_cb))
    action_row.append(_btn(t("btn_finish", lang), "att_finish"))
    builder.row(*action_row)
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="att_cancel")
    return builder.as_markup()


def topic_group_action_kb(
    group_name: str,
    lang: str = "latn",
    back_cb: str = "topic_back:group",
    cancel_cb: str = "topic_cancel",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(_lbl("topic_new_btn", lang), f"topic_act:new:{group_name}"),
        _btn(_lbl("topic_history_btn", lang), f"topic_act:history:{group_name}"),
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    return builder.as_markup()


def topic_dates_kb(
    dates_info: list[dict],
    lang: str = "latn",
    back_cb: str = "topic_back:group",
    cancel_cb: str = "topic_cancel",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in dates_info:
        date_str = item["date_str"]
        weekday = item.get("weekday") or ""
        if item.get("is_cancelled"):
            status_icon = "🚫"
        elif item.get("is_marked"):
            status_icon = "✅"
        else:
            status_icon = "⏳"
        label = (
            f"📅 {date_str} ({weekday}) {status_icon}"
            if weekday
            else f"📅 {date_str} {status_icon}"
        )
        builder.button(text=label, callback_data=f"topic_date:{date_str}")
    builder.adjust(2)
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    return builder.as_markup()


def topic_existing_kb(
    date_str: str,
    lang: str = "latn",
    back_cb: str = "topic_back:date",
    cancel_cb: str = "topic_cancel",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(t("btn_topic_broadcast", lang), f"topic_bc:{date_str}"),
        _btn(t("btn_topic_edit", lang), f"topic_edit:{date_str}"),
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    return builder.as_markup()


def topic_after_save_kb(
    date_str: str,
    lang: str = "latn",
    include_save_only: bool = True,
    back_cb: str = "topic_back:date",
    cancel_cb: str = "topic_cancel",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    broadcast_btn = _btn(t("btn_topic_broadcast", lang), f"topic_bc:{date_str}")
    edit_btn = _btn(t("btn_topic_edit", lang), f"topic_edit:{date_str}")
    if include_save_only:
        builder.row(
            broadcast_btn,
            _btn(t("btn_topic_save_only", lang), f"topic_save:{date_str}"),
        )
        builder.row(edit_btn)
    else:
        builder.row(broadcast_btn, edit_btn)
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    return builder.as_markup()


def admin_attendance_report_kb(
    report_id: int,
    is_detailed: bool,
    lang: str = "latn",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_text = t("btn_compact", lang) if is_detailed else t("btn_details", lang)
    builder.row(
        InlineKeyboardButton(
            text=toggle_text,
            callback_data=f"att_rep_toggle:{report_id}:{int(not is_detailed)}",
        )
    )
    return builder.as_markup()


def pending_action_kb(action_id: int, lang: str = "latn") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("btn_edit", lang), callback_data=f"pending_edit:{action_id}"
        ),
        InlineKeyboardButton(
            text=t("btn_cancel", lang), callback_data=f"pending_cancel:{action_id}"
        ),
    )
    return builder.as_markup()


# ----------------------------------------------------------------------
# Payments Keyboards
# ----------------------------------------------------------------------


def payment_confirm_kb(
    student_id: str,
    cycle_idx: int,
    is_detailed: bool,
    lang: str = "latn",
    include_confirm: bool = True,
    back_cb: Optional[str] = "pay_back:cycle",
    is_paid: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_text = t("btn_compact", lang) if is_detailed else t("btn_details", lang)
    toggle_btn = _btn(
        toggle_text,
        f"pay_toggle:{student_id}:{cycle_idx}:{int(not is_detailed)}",
    )
    revert_btn = _btn(
        t("btn_payment_revert", lang), f"pay_revert:{student_id}:{cycle_idx}"
    )
    if include_confirm:
        builder.row(toggle_btn)
        builder.row(
            _btn(
                t("btn_payment_confirm", lang),
                f"pay_confirm:{student_id}:{cycle_idx}",
            ),
            revert_btn,
        )
        _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="pay_cancel")
    elif is_paid:
        builder.row(toggle_btn, revert_btn)
        _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="pay_cancel")
    else:
        builder.row(toggle_btn)
        if back_cb:
            _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="pay_cancel")
    return builder.as_markup()


def parent_schedule_kb(expanded: bool = False, lang: str = "latn") -> InlineKeyboardMarkup:
    """Parent schedule: [📄 Batafsil] on the compact view, [🔙 Ortga] on the detail view."""
    builder = InlineKeyboardBuilder()
    if expanded:
        builder.row(
            InlineKeyboardButton(
                text=t("parent_sched_btn_back", lang),
                callback_data="psched:back",
            )
        )
    else:
        builder.row(
            InlineKeyboardButton(
                text=t("btn_detailed", lang),
                callback_data="psched:detail",
            )
        )
    return builder.as_markup()


def student_payment_detail_kb(
    student_id: str,
    cycle_idx: int,
    is_detailed: bool,
    lang: str = "latn",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_text = t("btn_compact", lang) if is_detailed else t("btn_details", lang)
    builder.row(
        InlineKeyboardButton(
            text=toggle_text,
            callback_data=f"stu_pay_toggle:{student_id}:{cycle_idx}:{int(not is_detailed)}",
        )
    )
    return builder.as_markup()


# ----------------------------------------------------------------------
# Student Management Keyboards
# ----------------------------------------------------------------------


def student_root_menu_kb(lang: str = "latn") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(_lbl("add_student", lang), "stu_menu:add"),
        _btn(_lbl("manage_students", lang), "stu_menu:manage"),
    )
    builder.row(_btn(t("btn_archive_group", lang), "stu_menu:reserve"))
    _nav_row(builder, lang=lang, cancel_cb="stu_menu:cancel")
    return builder.as_markup()


def parent_batch_type_kb(
    lang: str = "latn",
    back_cb: Optional[str] = "stu_add_back:method",
    cancel_cb: str = "stu_add_cancel",
) -> InlineKeyboardMarkup:
    """Admin picks whether the phone-less student's parent is the father or mother."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=t("btn_parent_father", lang),
            callback_data="pb_type:father",
        ),
        InlineKeyboardButton(
            text=t("btn_parent_mother", lang),
            callback_data="pb_type:mother",
        ),
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    return builder.as_markup()


def student_add_method_kb(
    lang: str = "latn", back_cb: Optional[str] = "stu_add_method:back"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(_lbl("student_invite", lang), "stu_add_method:invite"),
        _btn(
            t("btn_add_children_via_parent", lang), "stu_add_method:parent_batch"
        ),
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="stu_add_method:cancel")
    return builder.as_markup()


def student_no_phone_inline_kb(
    no_phone_cb: str,
    skip_cb: str,
    cancel_cb: str,
    lang: str = "latn",
    back_cb: Optional[str] = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(t("btn_student_no_phone", lang), no_phone_cb),
        _btn(_lbl("skip", lang), skip_cb),
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    return builder.as_markup()


def parent_batch_more_kb(lang: str = "latn") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(_lbl("add_more_child", lang), "parent_batch:more"),
        _btn(t("btn_finish", lang), "parent_batch:finish"),
    )
    _nav_row(builder, lang=lang, cancel_cb="stu_add:cancel")
    return builder.as_markup()


def skip_or_cancel_inline_kb(
    skip_cb: str,
    cancel_cb: str,
    lang: str = "latn",
    back_cb: Optional[str] = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if back_cb:
        builder.row(_btn(_lbl("skip", lang), skip_cb))
        _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
    else:
        builder.row(
            _btn(_lbl("skip", lang), skip_cb),
            _btn(t("btn_cancel", lang), cancel_cb),
        )
    return builder.as_markup()


def students_list_kb(
    students: list[dict],
    prefix: str,
    lang: str = "latn",
    include_back: bool = True,
    include_cancel: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for s in students:
        sid = s["Talaba_ID"]
        name = s["F.I.O."]
        status_icon = "🟢" if s.get("Status") == "O'qiyapti" else "🔴"
        builder.row(
            InlineKeyboardButton(
                text=f"{status_icon} {name} ({sid})",
                callback_data=f"{prefix}:{sid}",
            )
        )
    _nav_row(
        builder,
        lang=lang,
        back_cb=f"{prefix}:__back__" if include_back else None,
        cancel_cb=f"{prefix}:__cancel__" if include_cancel else None,
    )
    return builder.as_markup()


def student_actions_kb(
    student_id: str,
    current_status: str,
    lang: str = "latn",
    has_device: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_label = (
        _lbl("toggle_status_to_inactive", lang)
        if current_status == "O'qiyapti"
        else _lbl("toggle_status_to_active", lang)
    )
    builder.row(
        _btn(toggle_label, f"stu_act:status:{student_id}"),
        _btn(_lbl("edit_info", lang), f"stu_act:edit:{student_id}"),
    )
    builder.row(
        _btn(_lbl("legacy_add", lang), f"stu_act:legacy_add:{student_id}"),
        _btn(_lbl("legacy_list", lang), f"stu_act:legacy_list:{student_id}"),
    )
    tail = [_btn(_lbl("show_links", lang), f"stu_act:links:{student_id}")]
    if not has_device:
        tail.append(
            _btn(_lbl("attach_stu_device", lang), f"attach_stu_device:{student_id}")
        )
    tail.append(_btn(_lbl("delete_student", lang), f"stu_act:delete:{student_id}"))
    for row in pair_buttons(tail):
        builder.row(*row)
    _nav_row(builder, lang=lang, back_cb="stu_act:back", cancel_cb="stu_act:cancel")
    return builder.as_markup()


def student_edit_fields_kb(
    student_id: str, lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("field_name", lang),
            callback_data=f"stu_field:{student_id}:F.I.O.",
        ),
        InlineKeyboardButton(
            text=_lbl("field_group", lang),
            callback_data=f"stu_field:{student_id}:Guruh",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("field_stu_phone", lang),
            callback_data=f"stu_field:{student_id}:Talaba_Tel",
        ),
        InlineKeyboardButton(
            text=_lbl("field_stu_tg", lang),
            callback_data=f"stu_field:{student_id}:Talaba_TG",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("field_father_phone", lang),
            callback_data=f"stu_field:{student_id}:Otasi_Tel",
        ),
        InlineKeyboardButton(
            text=_lbl("field_mother_phone", lang),
            callback_data=f"stu_field:{student_id}:Onasi_Tel",
        ),
    )
    _nav_row(
        builder,
        lang=lang,
        back_cb=f"stu_field_back:{student_id}",
        cancel_cb="stu_act:cancel",
    )
    return builder.as_markup()


def student_transfer_keep_kb(lang: str = "latn") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _btn(t("btn_stu_transfer_keep", lang), "transfer_keep:yes"),
        _btn(t("btn_stu_transfer_move", lang), "transfer_keep:no"),
    )
    builder.row(_btn(_lbl("transfer_cancel", lang), "stu_act:cancel"))
    return builder.as_markup()


def confirm_delete_student_kb(
    student_id: str, lang: str = "latn"
) -> InlineKeyboardMarkup:
    return confirm_cancel_kb(
        confirm_cb=f"stu_del_confirm:{student_id}",
        cancel_cb="stu_act:cancel",
        lang=lang,
        back_cb=f"stu_del_cancel:{student_id}",
    )