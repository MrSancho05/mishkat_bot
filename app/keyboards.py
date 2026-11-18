from typing import Optional

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

from app.locales import WEEKDAYS_SHORT, t

_LOCAL_BTN_LABELS: dict[str, dict[str, str]] = {
    "latn": {
        "count_8": "8 ta dars",
        "count_12": "12 ta dars",
        "self_teacher": "👤 O‘zimni ustoz qilish",
        "invite_new_teacher": "🔗 Yangi ustoz taklif havolasi",
        "add_group": "➕ Yangi guruh",
        "edit_group": "✏️ Guruhni tahrirlash",
        "add_student": "➕ Yangi talaba",
        "manage_students": "👤 Talabalarni boshqarish",
        "student_manual": "✍️ Ma'lumotlarni qo‘lda kiritish",
        "student_invite": "🔗 Taklif havolasini yuborish",
        "toggle_status_to_inactive": "🔴 Status: O‘qimayapti",
        "toggle_status_to_active": "🟢 Status: O‘qiyapti",
        "edit_info": "✏️ Tahrirlash",
        "show_links": "🔗 Taklif havolalari",
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
        "field_price": "💰 To‘lov summasini belgilash",
        "profile_edit_name": "✏️ Ismni o‘zgartirish",
        "profile_edit_phone": "📱 Telefonni yangilash",
        "skip": "⏭ O‘tkazib yuborish",
        "att_topic_btn": "📝 Dars mavzusi / rejasi",
        "admin_new_invite": "🔗 Yangi admin havolasi",
        "admin_remove": "🗑 Adminni o‘chirish",
        "tch_assign_group": "🔗 Guruhga biriktirish",
        "tch_delete": "🗑 Ustozni o'chirish",
        "tch_del_yes": "✅ Ha, o'chirish",
        "tch_del_no": "❌ Yo'q, bekor qilish",
        "transfer_cancel": "⬅️ Bekor qilish",
        "tch_menu_topic": "📝 Dars mavzusini kiritish",
        "tch_menu_groups": "👥 Mening guruhlarim",
        "tch_menu_attendance": "📋 Yo'qlama qilish",
        "tch_menu_add_student": "➕ Yangi talaba qo'shish",
        "tch_menu_payments": "💳 To'lovlarni tasdiqlash",
        "tch_menu_lang": "🌐 Tilni o'zgartirish",
        "topic_new_btn": "➕ Yangi mavzu / reja kiritish",
        "topic_history_btn": "📚 Oldingi kiritilgan mavzular",
    },
    "cyrl": {
        "count_8": "8 та дарс",
        "count_12": "12 та дарс",
        "self_teacher": "👤 Ўзимни устоз қилиш",
        "invite_new_teacher": "🔗 Янги устоз таклиф ҳаволаси",
        "add_group": "➕ Янги гуруҳ",
        "edit_group": "✏️ Гуруҳни таҳрирлаш",
        "add_student": "➕ Янги талаба",
        "manage_students": "👤 Талабаларни бошқариш",
        "student_manual": "✍️ Маълумотларни қўлда киритиш",
        "student_invite": "🔗 Таклиф ҳаволасини юбориш",
        "toggle_status_to_inactive": "🔴 Статус: Ўқимаяпти",
        "toggle_status_to_active": "🟢 Статус: Ўқияпти",
        "edit_info": "✏️ Таҳрирлаш",
        "show_links": "🔗 Таклиф ҳаволалари",
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
        "field_price": "💰 Тўлов суммасини белгилаш",
        "profile_edit_name": "✏️ Исмни ўзгартириш",
        "profile_edit_phone": "📱 Телефонни янгилаш",
        "skip": "⏭ Ўтказиб юбориш",
        "att_topic_btn": "📝 Дарс мавзуси / режаси",
        "admin_new_invite": "🔗 Янги админ ҳаволаси",
        "admin_remove": "🗑 Админни ўчириш",
        "tch_assign_group": "🔗 Гуруҳга бириктириш",
        "tch_delete": "🗑 Устозни ўчириш",
        "tch_del_yes": "✅ Ҳа, ўчириш",
        "tch_del_no": "❌ Йўқ, бекор қилиш",
        "transfer_cancel": "⬅️ Бекор қилиш",
        "tch_menu_topic": "📝 Дарс мавзусини киритиш",
        "tch_menu_groups": "👥 Менинг гуруҳларим",
        "tch_menu_attendance": "📋 Йўқлама қилиш",
        "tch_menu_add_student": "➕ Янги талаба қўшиш",
        "tch_menu_payments": "💳 Тўловларни тасдиқлаш",
        "tch_menu_lang": "🌐 Тилни ўзгартириш",
        "topic_new_btn": "➕ Янги мавзу / режа киритиш",
        "topic_history_btn": "📚 Олдинги киритилган мавзулар",
    },
}


def _lbl(key: str, lang: str) -> str:
    safe_lang = lang if lang in _LOCAL_BTN_LABELS else "latn"
    return _LOCAL_BTN_LABELS[safe_lang][key]


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
    builder.adjust(1)
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
        InlineKeyboardButton(
            text=t("btn_role_change_approve", lang),
            callback_data=f"role_req:approve:{req_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_role_change_reject", lang),
            callback_data=f"role_req:reject:{req_id}",
        )
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
        KeyboardButton(text=t("menu_admin_schedule", lang)),
        KeyboardButton(text=t("menu_admin_attendance", lang)),
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
        KeyboardButton(text=t("btn_change_lang", lang)),
    )
    return builder.as_markup(resize_keyboard=True)


def teacher_menu_kb(lang: str = "latn") -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=_lbl("tch_menu_topic", lang)),
    )
    builder.row(
        KeyboardButton(text=_lbl("tch_menu_groups", lang)),
        KeyboardButton(text=_lbl("tch_menu_attendance", lang)),
    )
    builder.row(
        KeyboardButton(text=_lbl("tch_menu_add_student", lang)),
        KeyboardButton(text=_lbl("tch_menu_payments", lang)),
    )
    builder.row(
        KeyboardButton(text=_lbl("tch_menu_lang", lang)),
    )
    return builder.as_markup(resize_keyboard=True)


get_teacher_main_kb = teacher_menu_kb


def student_menu_kb(lang: str = "latn") -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=t("menu_student_group", lang)),
        KeyboardButton(text=t("menu_student_schedule", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_student_payments", lang)),
        KeyboardButton(text=t("menu_profile", lang)),
    )
    builder.row(
        KeyboardButton(text=t("btn_change_lang", lang)),
    )
    return builder.as_markup(resize_keyboard=True)


def parent_menu_kb(lang: str = "latn") -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text=t("menu_parent_schedule", lang)),
        KeyboardButton(text=t("menu_parent_payments", lang)),
    )
    builder.row(
        KeyboardButton(text=t("menu_profile", lang)),
        KeyboardButton(text=t("btn_change_lang", lang)),
    )
    return builder.as_markup(resize_keyboard=True)


def get_main_menu_kb(role: str, lang: str = "latn") -> ReplyKeyboardMarkup:
    if role == "admin":
        return admin_menu_kb(lang)
    if role == "teacher":
        return teacher_menu_kb(lang)
    if role == "student":
        return student_menu_kb(lang)
    return parent_menu_kb(lang)


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


def profile_actions_kb(lang: str = "latn") -> InlineKeyboardMarkup:
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
    _nav_row(builder, lang=lang, cancel_cb="profile_edit:close")
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
        builder.row(
            InlineKeyboardButton(
                text=f"👨‍🏫 {name} ({grp_count})",
                callback_data=f"tch_mgr:view:{tid}",
            )
        )
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
        InlineKeyboardButton(
            text=_lbl("admin_new_invite", lang),
            callback_data="adm_mng:invite",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_admin_list", lang),
            callback_data="adm_mng:list",
        ),
        InlineKeyboardButton(
            text=_lbl("admin_remove", lang),
            callback_data="adm_mng:remove",
        ),
    )
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
    builder.row(
        InlineKeyboardButton(text=t("btn_confirm", lang), callback_data=confirm_cb)
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
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
    safe_lang = lang if lang in WEEKDAYS_SHORT else "latn"
    days_map = WEEKDAYS_SHORT[safe_lang]
    builder = InlineKeyboardBuilder()
    for day_idx in range(7):
        mark = "✅" if day_idx in selected_days else "❌"
        builder.button(
            text=f"{mark} {days_map[day_idx]}",
            callback_data=f"sched_day:{day_idx}",
        )
    builder.adjust(3, 3, 1)
    builder.row(
        InlineKeyboardButton(
            text=t("btn_confirm", lang), callback_data="sched_days_done"
        )
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="sched_cancel")
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
        )
    )
    _nav_row(builder, lang=lang, cancel_cb="grp_menu:cancel")
    return builder.as_markup()


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
        InlineKeyboardButton(
            text=_lbl("self_teacher", lang), callback_data="grp_add:self_teacher"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("invite_new_teacher", lang),
            callback_data="grp_add:invite_teacher",
        )
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
    safe_lang = lang if lang in WEEKDAYS_SHORT else "latn"
    days_map = WEEKDAYS_SHORT[safe_lang]
    builder = InlineKeyboardBuilder()
    for day_idx in range(7):
        mark = "✅" if day_idx in selected_days else "❌"
        builder.button(
            text=f"{mark} {days_map[day_idx]}",
            callback_data=f"grp_add:day:{day_idx}",
        )
    builder.adjust(3, 3, 1)
    builder.row(
        InlineKeyboardButton(
            text=t("btn_confirm", lang), callback_data="grp_add:days_done"
        )
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="grp_add:cancel")
    return builder.as_markup()


def group_add_confirm_kb(
    lang: str = "latn", back_cb: str = "grp_add:back:time"
) -> InlineKeyboardMarkup:
    return confirm_cancel_kb(
        confirm_cb="grp_add:confirm",
        cancel_cb="grp_add:cancel",
        lang=lang,
        back_cb=back_cb,
    )


def group_edit_fields_kb(
    group_name: str, lang: str = "latn"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("field_teacher", lang),
            callback_data=f"grp_edit_fld:{group_name}:teacher",
        ),
        InlineKeyboardButton(
            text=_lbl("field_lesson_count", lang),
            callback_data=f"grp_edit_fld:{group_name}:count",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("field_days", lang),
            callback_data=f"grp_edit_fld:{group_name}:days",
        ),
        InlineKeyboardButton(
            text=_lbl("field_time", lang),
            callback_data=f"grp_edit_fld:{group_name}:time",
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("field_price", lang),
            callback_data=f"grp_edit_fld:{group_name}:price",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_group_full_update", lang),
            callback_data=f"grp_edit_fld:{group_name}:full_update",
        )
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
        InlineKeyboardButton(
            text=t("btn_keep_current", lang),
            callback_data=skip_cb,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_cancel", lang),
            callback_data=cancel_cb,
        )
    )
    return builder.as_markup()


def full_group_edit_count_kb(
    lang: str = "latn",
    skip_cb: str = "full_grp:skip_field",
    cancel_cb: str = "full_grp:cancel",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("count_8", lang), callback_data="full_grp:count:8"
        ),
        InlineKeyboardButton(
            text=_lbl("count_12", lang), callback_data="full_grp:count:12"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_keep_current", lang), callback_data=skip_cb
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_cancel", lang), callback_data=cancel_cb
        )
    )
    return builder.as_markup()


def full_group_edit_weekdays_kb(
    selected_days: list[int],
    lang: str = "latn",
    skip_cb: str = "full_grp:skip_field",
    cancel_cb: str = "full_grp:cancel",
) -> InlineKeyboardMarkup:
    safe_lang = lang if lang in WEEKDAYS_SHORT else "latn"
    days_map = WEEKDAYS_SHORT[safe_lang]
    builder = InlineKeyboardBuilder()
    for day_idx in range(7):
        mark = "✅" if day_idx in selected_days else "❌"
        builder.button(
            text=f"{mark} {days_map[day_idx]}",
            callback_data=f"full_grp:day:{day_idx}",
        )
    builder.adjust(3, 3, 1)
    builder.row(
        InlineKeyboardButton(
            text=t("btn_confirm", lang), callback_data="full_grp:days_done"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_keep_current", lang), callback_data=skip_cb
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_cancel", lang), callback_data=cancel_cb
        )
    )
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
        InlineKeyboardButton(
            text=_lbl("self_teacher", lang),
            callback_data=f"grp_edit_tch:{group_name}:__self__",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("invite_new_teacher", lang),
            callback_data=f"grp_edit_tch:{group_name}:__invite__",
        )
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
    safe_lang = lang if lang in WEEKDAYS_SHORT else "latn"
    days_map = WEEKDAYS_SHORT[safe_lang]
    builder = InlineKeyboardBuilder()
    for day_idx in range(7):
        mark = "✅" if day_idx in selected_days else "❌"
        builder.button(
            text=f"{mark} {days_map[day_idx]}",
            callback_data=f"grp_edit_day:{day_idx}",
        )
    builder.adjust(3, 3, 1)
    builder.row(
        InlineKeyboardButton(
            text=t("btn_confirm", lang),
            callback_data=f"grp_edit_days_done:{group_name}",
        )
    )
    _nav_row(
        builder,
        lang=lang,
        back_cb=f"grp_edit:back:fields:{group_name}",
        cancel_cb="grp_edit:cancel",
    )
    return builder.as_markup()


# ----------------------------------------------------------------------
# Attendance, Lesson Topic & Plan, Admin Attendance Report Keyboards
# ----------------------------------------------------------------------


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
    if include_topic_btn:
        builder.row(
            InlineKeyboardButton(
                text=_lbl("att_topic_btn", lang),
                callback_data=topic_cb,
            )
        )
    builder.row(
        InlineKeyboardButton(text=t("btn_finish", lang), callback_data="att_finish")
    )
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
        InlineKeyboardButton(
            text=_lbl("topic_new_btn", lang),
            callback_data=f"topic_act:new:{group_name}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("topic_history_btn", lang),
            callback_data=f"topic_act:history:{group_name}",
        )
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
        InlineKeyboardButton(
            text=t("btn_topic_broadcast", lang),
            callback_data=f"topic_bc:{date_str}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_topic_edit", lang),
            callback_data=f"topic_edit:{date_str}",
        )
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
    builder.row(
        InlineKeyboardButton(
            text=t("btn_topic_broadcast", lang),
            callback_data=f"topic_bc:{date_str}",
        )
    )
    if include_save_only:
        builder.row(
            InlineKeyboardButton(
                text=t("btn_topic_save_only", lang),
                callback_data=f"topic_save:{date_str}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_topic_edit", lang),
            callback_data=f"topic_edit:{date_str}",
        )
    )
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
    builder.row(
        InlineKeyboardButton(
            text=toggle_text,
            callback_data=f"pay_toggle:{student_id}:{cycle_idx}:{int(not is_detailed)}",
        )
    )
    if include_confirm:
        builder.row(
            InlineKeyboardButton(
                text=t("btn_payment_confirm", lang),
                callback_data=f"pay_confirm:{student_id}:{cycle_idx}",
            )
        )
        builder.row(
            InlineKeyboardButton(
                text=t("btn_payment_revert", lang),
                callback_data=f"pay_revert:{student_id}:{cycle_idx}",
            )
        )
        _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="pay_cancel")
    elif is_paid:
        builder.row(
            InlineKeyboardButton(
                text=t("btn_payment_revert", lang),
                callback_data=f"pay_revert:{student_id}:{cycle_idx}",
            )
        )
        _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="pay_cancel")
    elif back_cb:
        _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="pay_cancel")
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
        InlineKeyboardButton(
            text=_lbl("add_student", lang), callback_data="stu_menu:add"
        ),
        InlineKeyboardButton(
            text=_lbl("manage_students", lang), callback_data="stu_menu:manage"
        ),
    )
    _nav_row(builder, lang=lang, cancel_cb="stu_menu:cancel")
    return builder.as_markup()


def student_add_method_kb(
    lang: str = "latn", back_cb: Optional[str] = "stu_add_method:back"
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=_lbl("student_manual", lang),
            callback_data="stu_add_method:manual",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("student_invite", lang),
            callback_data="stu_add_method:invite",
        )
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb="stu_add_method:cancel")
    return builder.as_markup()


def skip_or_cancel_inline_kb(
    skip_cb: str,
    cancel_cb: str,
    lang: str = "latn",
    back_cb: Optional[str] = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text=_lbl("skip", lang), callback_data=skip_cb)
    )
    _nav_row(builder, lang=lang, back_cb=back_cb, cancel_cb=cancel_cb)
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
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_label = (
        _lbl("toggle_status_to_inactive", lang)
        if current_status == "O'qiyapti"
        else _lbl("toggle_status_to_active", lang)
    )
    builder.row(
        InlineKeyboardButton(
            text=toggle_label, callback_data=f"stu_act:status:{student_id}"
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("edit_info", lang), callback_data=f"stu_act:edit:{student_id}"
        ),
        InlineKeyboardButton(
            text=_lbl("show_links", lang), callback_data=f"stu_act:links:{student_id}"
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("delete_student", lang),
            callback_data=f"stu_act:delete:{student_id}",
        )
    )
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
        InlineKeyboardButton(
            text=t("btn_stu_transfer_keep", lang),
            callback_data="transfer_keep:yes",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=t("btn_stu_transfer_move", lang),
            callback_data="transfer_keep:no",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=_lbl("transfer_cancel", lang),
            callback_data="stu_act:cancel",
        )
    )
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