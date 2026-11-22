import asyncio
import html
import inspect
import re
import secrets
from datetime import date, datetime, timedelta
from typing import Any, Optional

import aiosqlite
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

import app.config as _app_config
from app import database
from app.utils import now_tashkent, today_tashkent
from app.config import ADMIN_IDS, DB_PATH, STUDENT_SHEET_NAME, TZ
from app.database import (
    create_teacher_invite,
    get_active_teachers,
    get_notification_details,
    get_teacher_by_invite_code,
    get_teacher_by_telegram_id,
    get_user,
    get_user_lang,
    reset_user_role,
    save_notification_details,
)
from app.keyboards import (
    balance_inline_markup,
    pair_buttons,
    build_expandable_notif_kb,
    full_group_edit_confirm_kb,
    full_group_edit_count_kb,
    full_group_edit_step_kb,
    full_group_edit_weekdays_kb,
    group_add_cancel_kb,
    group_add_confirm_kb,
    group_add_lesson_count_kb,
    group_add_teacher_kb,
    group_add_weekdays_kb,
    group_delete_confirm_kb,
    group_edit_lesson_count_kb,
    group_edit_teacher_kb,
    group_edit_weekdays_kb,
    groups_inline_kb,
    lang_selection_kb,
    step_nav_inline_kb,
    teacher_manage_actions_kb,
    teacher_manage_assign_groups_kb,
    teacher_manage_confirm_delete_kb,
    teacher_manage_list_kb,
)
from app.locales import (
    WEEKDAYS_SHORT,
    button_texts,
    format_field_label,
    format_uz_date,
    format_uz_date_list,
    format_uzs,
    t,
)
from app.sheets import (
    COLOR_HEADER_GRAY,
    STUDENT_HEADERS,
    SheetsManager,
    _cell_bg_request,
    _col_letter,
    format_cycle_title,
    generate_cycle_dates,
    get_sheets_manager,
    parse_weekdays,
)
from app.states import (
    FullGroupEditStates,
    GroupAddStates,
    GroupEditStates,
    TeacherManageStates,
)

router = Router(name="groups_info")


class _FallbackGroupEditStates(StatesGroup):
    entering_price = State()
    confirming_schedule = State()


EDIT_PRICE_STATE = getattr(
    GroupEditStates, "entering_price", _FallbackGroupEditStates.entering_price
)
CONFIRM_SCHEDULE_STATE = getattr(
    GroupEditStates,
    "confirming_schedule",
    _FallbackGroupEditStates.confirming_schedule,
)

INVALID_SHEET_CHARS_RE = re.compile(r"[:\\/?*\[\]]")
TIME_FORMAT_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

TEACHER_SHEET_NAME = "Ustozlar"
TEACHER_HEADERS = [
    "Ustoz_ID",
    "F.I.O.",
    "Telefon",
    "TG_Username",
    "Chat_ID",
    "Status",
]
PLACEHOLDER_TEXT = "Ma'lumot kiritilmagan"

ADMIN_MANAGE_MENU_TEXTS = button_texts("menu_admin_manage_admins")
for _adm_key in (
    "menu_admin_admins",
    "menu_admins",
    "menu_admin_manage",
    "menu_admins_manage",
):
    for _l in ("latn", "cyrl"):
        _val = t(_adm_key, _l)
        if _val != _adm_key:
            ADMIN_MANAGE_MENU_TEXTS.add(_val)

TEACHER_MANAGE_MENU_TEXTS = button_texts("menu_admin_manage_teachers")

DELETE_GROUP_BTN_TEXTS = {
    t("btn_delete_group", "latn"),
    t("btn_delete_group", "cyrl"),
}

LOCAL_TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "choose_groups_mode": "📚 <b>Guruhlar bo‘limi</b>\nKerakli bo‘limni tanlang:",
        "btn_all_groups": "📚 Barcha guruhlar",
        "btn_today_groups": "📅 Bugungi guruhlar",
        "btn_add_group": "➕ Yangi guruh",
        "btn_edit_group": "✏️ Guruhni tahrirlash",
        "btn_edit_group_name": "📝 Guruh nomi",
        "btn_edit_group_price": "💰 To‘lov summasi",
        "btn_admins_manage": "👑 Adminlar",
        "no_groups_all": "ℹ️ Sizga biriktirilgan guruhlar topilmadi.",
        "no_groups_today": "ℹ️ Bugun darsi belgilangan guruhlaringiz topilmadi.",
        "select_group_all": "📚 <b>Barcha guruhlar:</b>\nBatafsil ma'lumotlarni ko‘rish uchun guruhni tanlang:",
        "select_group_today": "📅 <b>Bugungi guruhlar:</b>\nBatafsil ma'lumotlarni ko‘rish uchun guruhni tanlang:",
        "select_teacher_groups": "👥 <b>Mening guruhlarim:</b>\nBatafsil ma'lumotlarni ko‘rish uchun guruhni tanlang:",
        "teacher_block": (
            "👨‍🏫 Guruh ustozi: <b>{teacher_name}</b>\n"
            "   📞 {teacher_phone} | 💬 {teacher_tg}"
        ),
        "teacher_unassigned": "👨‍🏫 Guruh ustozi: <i>Hali tayinlanmagan</i>",
        "student_group_header": (
            "👥 <b>Mening guruhim: {group}</b>\n"
            "📆 Dars kunlari: <b>{days}</b> | ⏰ Vaqt: <b>{time}</b>\n"
            "👥 Jami faol talabalar: <b>{total} ta</b>\n\n"
            "{teacher_block}\n\n"
            "<b>Guruhdoshlar kontaktlari:</b>"
        ),
        "teacher_group_header": (
            "📚 <b>Guruh: {group}</b>\n"
            "📆 Dars kunlari: <b>{days}</b> | ⏰ Vaqt: <b>{time}</b>\n"
            "🔢 Sikl: <b>{count} ta dars</b> | 👥 Jami faol talabalar: <b>{total} ta</b>\n\n"
            "{teacher_block}\n\n"
            "🔗 Talabalar o‘zi qo‘shilish havolasi:\n<code>{join_link}</code>\n\n"
            "<b>Talaba va ota-ona kontaktlari:</b>"
        ),
        "student_phone_label": "📞 Talaba",
        "father_label": "🧔‍♂️ Otasi",
        "mother_label": "🧕 Onasi",
        "parent_phone_label": "👨‍👩‍👧 Ota-ona",
        "telegram_label": "💬 Telegram",
        "bot_linked_label": "🤖 Bot",
        "linked_yes": "ulangan ✅",
        "linked_no": "ulanmagan ❌",
        "not_provided": "—",
        "no_permission": "❌ Sizda ushbu bo‘limga kirish huquqi yo‘q.",
        "group_not_found": "❌ Guruh topilmadi.",
        "add_teacher_select_group": (
            "👨‍🏫 <b>Ustoz qo‘shish / taklif havolasi</b>\n\n"
            "Ustozni qaysi guruhga biriktirmoqchisiz? Guruhni tanlang "
            "(avtomatik bir martalik taklif havolasi yaratiladi):"
        ),
        "add_teacher_no_group_btn": "🔗 Guruhsiz havola",
        "add_teacher_invite_ready": (
            "✅ <b>Ustoz taklif havolasi yaratildi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🔗 Bir martalik havola:\n<code>{invite_link}</code>\n\n"
            "Ushbu havolani ustozga yuboring. Ustoz botga kirib, ismi va telefon raqamini "
            "tasdiqlagach avtomatik ravishda tizimga qo‘shiladi."
        ),
        "add_group_enter_name": (
            "➕ <b>Yangi guruh yaratish (1/5)</b>\n\n"
            "Yangi guruh nomini kiriting (masalan: <code>Mishkat Kids</code>):"
        ),
        "add_group_invalid_name": (
            "❌ Guruh nomi noto‘g‘ri. Nom bo‘sh bo‘lmasligi, 50 belgidan oshmasligi "
            "va <code>: \\ / ? * [ ]</code> belgilarini o‘z ichiga olmasligi kerak.\n"
            "Qaytadan kiriting:"
        ),
        "add_group_already_exists": (
            "⚠️ <b>{group}</b> nomli guruh allaqachon mavjud.\n"
            "Iltimos, boshqa nom kiriting:"
        ),
        "add_group_select_teacher": (
            "👤 <b>Yangi guruh yaratish (2/5)</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "Ro‘yxatdan o‘tgan ustozlardan birini tanlang, o‘zingizni ustoz qiling "
            "yoki yangi ustoz taklif havolasini oling:"
        ),
        "add_group_select_teacher_btn_only": (
            "⚠️ Iltimos, quyidagi tugmalar orqali ustozni tanlang:"
        ),
        "add_group_invite_generated": (
            "🔗 <b>Yangi ustoz taklif havolasi yaratildi!</b>\n\n"
            "👉 Havola:\n<code>{invite_link}</code>\n\n"
            "Ustoz ushbu havola orqali ro‘yxatdan o‘tgach avtomatik ravishda ushbu guruhga biriktiriladi.\n\n"
            "Endi bir o‘quv oyidagi darslar sonini tanlang:"
        ),
        "add_group_select_days_alert": "Kamida bitta dars kunini tanlang!",
        "add_group_enter_fee": (
            "💰 <b>{group}</b> guruhi uchun <b>oylik to‘lov summasini</b> kiriting:\n\n"
            "<i>Masalan: <code>500000</code> yoki <code>500</code> "
            "(10 000 dan kichik son avtomatik 1000 ga ko‘paytiriladi).</i>"
        ),
        "add_group_fee_line": "💰 Oylik to‘lov summasi: <b>{amount} so‘m</b>",
        "add_group_confirm_summary": (
            "📋 <b>Yangi guruh ma'lumotlarini tasdiqlang:</b>\n\n"
            "📚 Guruh nomi: <b>{group}</b>\n"
            "👨‍🏫 Ustoz: <b>{teacher_label}</b>\n"
            "🔢 Sikl darslari soni: <b>{count} ta</b>\n"
            "📆 Dars kunlari: <b>{days}</b>\n"
            "⏰ Dars vaqti: <b>{time}</b>\n"
            "🗓 Boshlang‘ich sikl: <b>{cycle_title}</b> ({start_date} — {end_date})"
        ),
        "add_group_cancelled": "❌ Yangi guruh yaratish bekor qilindi.",
        "add_group_success": (
            "✅ <b>Yangi guruh muvaffaqiyatli yaratildi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "👨‍🏫 Ustoz: <b>{teacher_label}</b>\n"
            "📆 Kunlar: <b>{days}</b> | ⏰ Vaqt: <b>{time}</b>\n"
            "📄 Jadval varag‘i: <b>{sheet_title}</b>\n"
            "🗓 Birinchi sikl: <b>{cycle_title}</b> ({start_date} — {end_date})\n"
            "💳 <i>Eslatma: Yangi o'quv oyi uchun to'lov 1-darsdan boshlab to'lanishi lozim.</i>\n\n"
            "🔗 Talabalar o‘zi ro‘yxatdan o‘tishi uchun havola:\n<code>{join_link}</code>\n\n"
            "💬 Telegram guruh chatini ulash uchun guruh ichida yuboring:\n"
            "<code>/link_group {group}</code>"
        ),
        "edit_enter_new_name": "📝 <b>{group}</b> guruhi uchun yangi nomni kiriting:",
        "edit_select_teacher": (
            "👨‍🏫 <b>{group}</b> guruhi uchun yangi ustozni tanlang "
            "(eski ustoz o‘rniga biriktiriladi):"
        ),
        "edit_invite_created": (
            "🔗 <b>{group}</b> guruhi uchun yangi ustoz taklif havolasi yaratildi!\n\n"
            "👉 Havola:\n<code>{invite_link}</code>\n\n"
            "Ustoz ushbu havola orqali ro‘yxatdan o‘tgach avtomatik guruhga biriktiriladi."
        ),
        "edit_cancelled": "❌ Guruhni tahrirlash bekor qilindi.",
        "teacher_reassigned_notify": (
            "📚 Siz <b>{group}</b> guruhiga yangi ustoz sifatida tayinlandingiz!"
        ),
        "group_fee_line": "💰 Oylik to‘lov summasi: <b>{amount} so‘m</b>",
        "group_fee_not_set": "💰 Oylik to‘lov summasi: <i>belgilanmagan</i>",
        "edit_enter_price": (
            "💰 <b>{group}</b> guruhi uchun oylik to‘lov summasini kiriting:\n\n"
            "<i>Masalan: <code>500</code> yoki <code>500000</code> "
            "(10 000 dan kichik son avtomatik 1000 ga ko‘paytiriladi).</i>"
        ),
        "edit_invalid_price": (
            "❌ Noto‘g‘ri summa kiritildi. Faqat musbat raqam kiriting "
            "(masalan: <code>450</code> yoki <code>500000</code>):"
        ),
        "edit_price_saved": (
            "✅ <b>{group}</b> guruhining oylik to‘lov summasi "
            "<b>{amount} so'm</b> etib belgilandi!"
        ),
        "btn_confirm_and_update": "✅ Tasdiqlash",
        "edit_schedule_confirm_preview": (
            "📅 <b>Jadval o‘zgarishini tasdiqlaysizmi?</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🔢 Oylik darslar soni: <b>{count} ta</b>\n"
            "📆 Dars kunlari: <b>{days}</b>\n"
            "⏰ Dars vaqti: <b>{time}</b>\n\n"
            "🗓 <b>Yangilangan sikl sanalari:</b>\n"
            "<code>{dates_list}</code>\n\n"
            "{preserved_note}"
            "<i>Tasdiqlasangiz, Google Sheets jadvali yangilanadi va barcha talabalar, "
            "ota-onalar, ustoz hamda guruh chatiga xabar yuboriladi.</i>"
        ),
        "edit_schedule_preserved_note": (
            "ℹ️ <i>O‘tilgan {completed} ta dars va ularning davomati saqlab qolinadi.</i>\n\n"
        ),
        "edit_schedule_saved_broadcast": (
            "✅ <b>{group}</b> guruhi jadvali yangilandi va barcha ishtirokchilarga "
            "xabar yuborildi! (Yuborildi: <b>{sent_count} ta</b>)"
        ),
        "full_edit_invalid_chat_id": (
            "❌ Noto‘g‘ri Telegram Chat ID. Raqam kiriting (masalan: <code>-1001234567890</code>):"
        ),
        "full_edit_summary": (
            "🔄 <b>Guruh ma'lumotlarini to‘liq yangilash — Tasdiqlash</b>\n\n"
            "📚 Guruh nomi: <b>{old_name}</b> ➡️ <b>{new_name}</b>\n"
            "🔢 Darslar soni: <b>{old_count}</b> ➡️ <b>{new_count} ta</b>\n"
            "📆 Dars kunlari: <b>{old_days}</b> ➡️ <b>{new_days}</b>\n"
            "⏰ Dars vaqti: <b>{old_time}</b> ➡️ <b>{new_time}</b>\n"
            "💰 Oylik to‘lov: <b>{old_price}</b> ➡️ <b>{new_price}</b>\n"
            "💬 TG Chat ID: <code>{old_chat}</code> ➡️ <code>{new_chat}</code>"
        ),
        "full_edit_saved_notice": (
            "✅ <b>{group}</b> guruhi ma'lumotlari to‘liq yangilandi! (Xabar yuborildi: <b>{sent_count} ta</b>)"
        ),
        "broadcast_short": (
            "📢 <b>Guruh ma'lumotlari yangilandi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📝 <b>O‘zgarishlar:</b>\n{changes}\n\n"
            "<i>{signature}</i>"
        ),
        "broadcast_detailed": (
            "📢 <b>Guruh ma'lumotlari yangilandi (Batafsil)</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "{teacher_block}\n"
            "📆 Dars kunlari: <b>{days}</b>\n"
            "⏰ Dars vaqti: <b>{time}</b>\n"
            "🔢 Oylik darslar soni: <b>{count} ta</b>\n"
            "💰 Oylik to‘lov: <b>{price}</b>\n\n"
            "📝 <b>Kiritilgan o‘zgarishlar:</b>\n{changes}{dates_block}\n\n"
            "<i>{signature}</i>"
        ),
        "signature_admin": "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!",
        "notif_not_found": "⚠️ Xabarnoma tafsilotlari topilmadi.",
        "delete_group_select": "🗑 O‘chirmoqchi bo‘lgan guruhingizni tanlang:",
        "delete_group_confirm": (
            "⚠️ «<b>{group}</b>» guruhi va uning Google Sheets'dagi "
            "<code>{group}_{year}</code> jadval listi butunlay o'chiriladi. "
            "Talabalar, ota-onalar va ustoz ma'lumotlari saqlanib qoladi "
            "(talabalar Zaxira guruhiga o'tkaziladi). Tasdiqlaysizmi?"
        ),
        "delete_group_success": (
            "✅ «<b>{group}</b>» guruhi va uning jadval varaqalari tizimdan butunlay o‘chirildi.\n"
            "ℹ️ Guruhdagi talabalar ma'lumotlari saqlanib qoldi va <b>Zaxira</b> ro‘yxatiga o‘tkazildi."
        ),
        "delete_group_cancelled": "❌ Guruhni o‘chirish bekor qilindi.",
        "upfront_cycle_group_notice": (
            "🆕 <b>Yangi o‘quv oyi boshlandi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 Davr: <b>{cycle_title}</b> ({start_date} — {end_date})\n"
            "💳 <b>Muhim eslatma:</b> Yangi o‘quv oyi uchun to‘lov 1-darsdan oldin "
            "(1-darsdan boshlab) amalga oshirilishi lozim.{fee_block}{card_block}\n\n"
            "<i>Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!</i>"
        ),
        "upfront_cycle_student_notice": (
            "🆕 <b>Yangi o‘quv oyi ochildi!</b>\n\n"
            "Assalomu alaykum, <b>{student_name}</b>!\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 Davr: <b>{cycle_title}</b> ({start_date} — {end_date})\n\n"
            "💳 Yangi o‘quv oyi uchun oylik to‘lov <b>1-darsdan boshlab (1-darsdan oldin)</b> "
            "to‘lanishi lozim.{fee_block}{card_block}\n\n"
            "<i>Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!</i>"
        ),
        "upfront_cycle_parent_notice": (
            "🆕 <b>Yangi o‘quv oyi boshlandi!</b>\n\n"
            "Assalomu alaykum!\n"
            "🎓 Farzand(lar)ingiz: <b>{children_names}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 Davr: <b>{cycle_title}</b> ({start_date} — {end_date})\n\n"
            "💳 Yangi o‘quv oyi uchun to‘lov <b>1-darsdan boshlab (1-darsdan oldin)</b> "
            "amalga oshirilishi lozim.{fee_block}{card_block}\n\n"
            "<i>Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!</i>"
        ),
        "admins_panel_title": (
            "👑 <b>Adminlar boshqaruvi</b>\n\n"
            "<b>Joriy adminlar ro‘yxati:</b>\n{admins_lines}"
        ),
        "admins_static_tag": "Asosiy admin",
        "admins_dynamic_tag": "Tayinlangan admin",
        "admins_btn_invite": "🔗 Admin havolasi",
        "admins_invite_created": (
            "🔗 <b>Yangi admin uchun bir martalik taklif havolasi yaratildi!</b>\n\n"
            "👉 Havola:\n<code>{invite_link}</code>\n\n"
            "<i>Ushbu havola faqat 1 marta ishlatiladi.</i>"
        ),
        "admins_remove_confirm": (
            "⚠️ <b>{name}</b> (<code>{tid}</code>) ni adminlar ro‘yxatidan "
            "o‘chirmoqchimisiz?"
        ),
        "admins_btn_confirm_remove": "✅ Ha, o‘chirish",
        "admins_removed_ok": "✅ <b>{name}</b> adminlar ro‘yxatidan o‘chirildi.",
        "admins_cannot_remove_static": "⚠️ Asosiy adminni (.env) o‘chirib bo‘lmaydi!",
        "admins_cannot_remove_self": "⚠️ O‘zingizni o‘chira olmaysiz!",
        "admins_removed_notify": "ℹ️ Sizning admin huquqlaringiz bekor qilindi.",
        "admins_btn_groups": "📚 Guruhlar bo‘limi",
    },
    "cyrl": {
        "choose_groups_mode": "📚 <b>Гуруҳлар бўлими</b>\nКеракли бўлимни танланг:",
        "btn_all_groups": "📚 Барча гуруҳлар",
        "btn_today_groups": "📅 Бугунги гуруҳлар",
        "btn_add_group": "➕ Янги гуруҳ",
        "btn_edit_group": "✏️ Гуруҳни таҳрирлаш",
        "btn_edit_group_name": "📝 Гуруҳ номи",
        "btn_edit_group_price": "💰 Тўлов суммаси",
        "btn_admins_manage": "👑 Админлар",
        "no_groups_all": "ℹ️ Сизга бириктирилган гуруҳлар топилмади.",
        "no_groups_today": "ℹ️ Бугун дарси белгиланган гуруҳларингиз топилмади.",
        "select_group_all": "📚 <b>Барча гуруҳлар:</b>\nБатафсил маълумотларни кўриш учун гуруҳни танланг:",
        "select_group_today": "📅 <b>Бугунги гуруҳлар:</b>\nБатафсил маълумотларни кўриш учун гуруҳни танланг:",
        "select_teacher_groups": "👥 <b>Менинг гуруҳларим:</b>\nБатафсил маълумотларни кўриш учун гуруҳни танланг:",
        "teacher_block": (
            "👨‍🏫 Гуруҳ устози: <b>{teacher_name}</b>\n"
            "   📞 {teacher_phone} | 💬 {teacher_tg}"
        ),
        "teacher_unassigned": "👨‍🏫 Гуруҳ устози: <i>Ҳали тайинланмаган</i>",
        "student_group_header": (
            "👥 <b>Менинг гуруҳим: {group}</b>\n"
            "📆 Дарс кунлари: <b>{days}</b> | ⏰ Вақт: <b>{time}</b>\n"
            "👥 Жами фаол талабалар: <b>{total} та</b>\n\n"
            "{teacher_block}\n\n"
            "<b>Гуруҳдошлар контактлари:</b>"
        ),
        "teacher_group_header": (
            "📚 <b>Гуруҳ: {group}</b>\n"
            "📆 Дарс кунлари: <b>{days}</b> | ⏰ Вақт: <b>{time}</b>\n"
            "🔢 Сикл: <b>{count} та дарс</b> | 👥 Жами фаол талабалар: <b>{total} та</b>\n\n"
            "{teacher_block}\n\n"
            "🔗 Талабалар ўзи қўшилиш ҳаволаси:\n<code>{join_link}</code>\n\n"
            "<b>Талаба ва ота-она контактлари:</b>"
        ),
        "student_phone_label": "📞 Талаба",
        "father_label": "🧔‍♂️ Отаси",
        "mother_label": "🧕 Онаси",
        "parent_phone_label": "👨‍👩‍👧 Ота-она",
        "telegram_label": "💬 Telegram",
        "bot_linked_label": "🤖 Бот",
        "linked_yes": "уланган ✅",
        "linked_no": "уланмаган ❌",
        "not_provided": "—",
        "no_permission": "❌ Сизда ушбу бўлимга кириш ҳуқуқи йўқ.",
        "group_not_found": "❌ Гуруҳ топилмади.",
        "add_teacher_select_group": (
            "👨‍🏫 <b>Устоз қўшиш / таклиф ҳаволаси</b>\n\n"
            "Устозни қайси гуруҳга бириктирмоқчисиз? Гуруҳни танланг "
            "(автоматик бир марталик таклиф ҳаволаси яратилади):"
        ),
        "add_teacher_no_group_btn": "🔗 Гуруҳсиз ҳавола",
        "add_teacher_invite_ready": (
            "✅ <b>Устоз таклиф ҳаволаси яратилди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🔗 Бир марталик ҳавола:\n<code>{invite_link}</code>\n\n"
            "Ушбу ҳаволани устозга юборинг. Устоз ботга кириб, исми ва телефон рақамини "
            "тасдиқлагач автоматик равишда тизимга қўшилади."
        ),
        "add_group_enter_name": (
            "➕ <b>Янги гуруҳ яратиш (1/5)</b>\n\n"
            "Янги гуруҳ номини киритинг (масалан: <code>Mishkat Kids</code>):"
        ),
        "add_group_invalid_name": (
            "❌ Гуруҳ номи нотўғри. Ном бўш бўлмаслиги, 50 белгидан ошмаслиги "
            "ва <code>: \\ / ? * [ ]</code> белгиларини ўз ичига олмаслиги керак.\n"
            "Қайтадан киритинг:"
        ),
        "add_group_already_exists": (
            "⚠️ <b>{group}</b> номли гуруҳ аллақачон мавжуд.\n"
            "Илтимос, бошқа ном киритинг:"
        ),
        "add_group_select_teacher": (
            "👤 <b>Янги гуруҳ яратиш (2/5)</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "Рўйхатдан ўтган устозлардан бирини танланг, ўзингизни устоз қилинг "
            "ёки янги устоз таклиф ҳаволасини олинг:"
        ),
        "add_group_select_teacher_btn_only": (
            "⚠️ Илтимос, қуйидаги тугмалар орқали устозни танланг:"
        ),
        "add_group_invite_generated": (
            "🔗 <b>Янги устоз таклиф ҳаволаси яратилди!</b>\n\n"
            "👉 Ҳавола:\n<code>{invite_link}</code>\n\n"
            "Устоз ушбу ҳавола орқали рўйхатдан ўтгач автоматик равишда ушбу гуруҳга бириктирилади.\n\n"
            "Энди бир ўқув ойидаги дарслар сонини танланг:"
        ),
        "add_group_select_days_alert": "Камида битта дарс кунини танланг!",
        "add_group_enter_fee": (
            "💰 <b>{group}</b> гуруҳи учун <b>ойлик тўлов суммасини</b> киритинг:\n\n"
            "<i>Масалан: <code>500000</code> ёки <code>500</code> "
            "(10 000 дан кичик сон автоматик 1000 га кўпайтирилади).</i>"
        ),
        "add_group_fee_line": "💰 Ойлик тўлов суммаси: <b>{amount} сўм</b>",
        "add_group_confirm_summary": (
            "📋 <b>Янги гуруҳ маълумотларини тасдиқланг:</b>\n\n"
            "📚 Гуруҳ номи: <b>{group}</b>\n"
            "👨‍🏫 Устоз: <b>{teacher_label}</b>\n"
            "🔢 Сикл дарслари сони: <b>{count} та</b>\n"
            "📆 Дарс кунлари: <b>{days}</b>\n"
            "⏰ Дарс вақти: <b>{time}</b>\n"
            "🗓 Бошланғич сикл: <b>{cycle_title}</b> ({start_date} — {end_date})"
        ),
        "add_group_cancelled": "❌ Янги гуруҳ яратиш бекор қилинди.",
        "add_group_success": (
            "✅ <b>Янги гуруҳ муваффақиятли яратилди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "👨‍🏫 Устоз: <b>{teacher_label}</b>\n"
            "📆 Кунлар: <b>{days}</b> | ⏰ Вақт: <b>{time}</b>\n"
            "📄 Жадвал варағи: <b>{sheet_title}</b>\n"
            "🗓 Биринчи сикл: <b>{cycle_title}</b> ({start_date} — {end_date})\n"
            "💳 <i>Эслатма: Янги ўқув ойи учун тўлов 1-дарсдан бошлаб тўланиши лозим.</i>\n\n"
            "🔗 Талабалар ўзи рўйхатдан ўтиши учун ҳавола:\n<code>{join_link}</code>\n\n"
            "💬 Telegram гуруҳ чатини улаш учун гуруҳ ичида юборинг:\n"
            "<code>/link_group {group}</code>"
        ),
        "edit_enter_new_name": "📝 <b>{group}</b> гуруҳи учун янги номни киритинг:",
        "edit_select_teacher": (
            "👨‍🏫 <b>{group}</b> гуруҳи учун янги устозни танланг "
            "(эски устоз ўрнига бириктирилади):"
        ),
        "edit_invite_created": (
            "🔗 <b>{group}</b> гуруҳи учун янги устоз таклиф ҳаволаси яратилди!\n\n"
            "👉 Ҳавола:\n<code>{invite_link}</code>\n\n"
            "Устоз ушбу ҳавола орқали рўйхатдан ўтгач автоматик гуруҳга бириктирилади."
        ),
        "edit_cancelled": "❌ Гуруҳни таҳрирлаш бекор қилинди.",
        "teacher_reassigned_notify": (
            "📚 Сиз <b>{group}</b> гуруҳига янги устоз сифатида тайинландингиз!"
        ),
        "group_fee_line": "💰 Ойлик тўлов суммаси: <b>{amount} сўм</b>",
        "group_fee_not_set": "💰 Ойлик тўлов суммаси: <i>белгиланмаган</i>",
        "edit_enter_price": (
            "💰 <b>{group}</b> гуруҳи учун ойлик тўлов суммасини киритинг:\n\n"
            "<i>Масалан: <code>500</code> ёки <code>500000</code> "
            "(10 000 дан кичик сон автоматик 1000 га кўпайтирилади).</i>"
        ),
        "edit_invalid_price": (
            "❌ Нотўғри сумма киритилди. Фақат мусбат рақам киритинг "
            "(масалан: <code>450</code> ёки <code>500000</code>):"
        ),
        "edit_price_saved": (
            "✅ <b>{group}</b> гуруҳининг ойлик тўлов суммаси "
            "<b>{amount} сўм</b> этиб белгиланди!"
        ),
        "btn_confirm_and_update": "✅ Тасдиқлаш",
        "edit_schedule_confirm_preview": (
            "📅 <b>Жадвал ўзгаришини тасдиқлайсизми?</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🔢 Ойлик дарслар сони: <b>{count} та</b>\n"
            "📆 Дарс кунлари: <b>{days}</b>\n"
            "⏰ Дарс вақти: <b>{time}</b>\n\n"
            "🗓 <b>Янгиланган сикл саналари:</b>\n"
            "<code>{dates_list}</code>\n\n"
            "{preserved_note}"
            "<i>Тасдиқласангиз, Google Sheets жадвали янгиланади ва барча талабалар, "
            "ота-оналар, устоз ҳамда гуруҳ чатига хабар юборилади.</i>"
        ),
        "edit_schedule_preserved_note": (
            "ℹ️ <i>Ўтилган {completed} та дарс ва уларнинг давомати сақлаб қолинади.</i>\n\n"
        ),
        "edit_schedule_saved_broadcast": (
            "✅ <b>{group}</b> гуруҳи жадвали янгиланди ва барча иштирокчиларга "
            "хабар юборилди! (Юборилди: <b>{sent_count} та</b>)"
        ),
        "full_edit_invalid_chat_id": (
            "❌ Нотўғри Telegram Chat ID. Рақам киритинг (масалан: <code>-1001234567890</code>):"
        ),
        "full_edit_summary": (
            "🔄 <b>Гуруҳ маълумотларини тўлиқ янгилаш — Тасдиқлаш</b>\n\n"
            "📚 Гуруҳ номи: <b>{old_name}</b> ➡️ <b>{new_name}</b>\n"
            "🔢 Дарслар сони: <b>{old_count}</b> ➡️ <b>{new_count} та</b>\n"
            "📆 Дарс кунлари: <b>{old_days}</b> ➡️ <b>{new_days}</b>\n"
            "⏰ Дарс вақти: <b>{old_time}</b> ➡️ <b>{new_time}</b>\n"
            "💰 Ойлик тўлов: <b>{old_price}</b> ➡️ <b>{new_price}</b>\n"
            "💬 TG Chat ID: <code>{old_chat}</code> ➡️ <code>{new_chat}</code>"
        ),
        "full_edit_saved_notice": (
            "✅ <b>{group}</b> гуруҳи маълумотлари тўлиқ янгиланди! (Хабар юборилди: <b>{sent_count} та</b>)"
        ),
        "broadcast_short": (
            "📢 <b>Гуруҳ маълумотлари янгиланди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📝 <b>Ўзгаришлар:</b>\n{changes}\n\n"
            "<i>{signature}</i>"
        ),
        "broadcast_detailed": (
            "📢 <b>Гуруҳ маълумотлари янгиланди (Батафсил)</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "{teacher_block}\n"
            "📆 Дарс кунлари: <b>{days}</b>\n"
            "⏰ Дарс вақти: <b>{time}</b>\n"
            "🔢 Ойлик дарслар сони: <b>{count} та</b>\n"
            "💰 Ойлик тўлов: <b>{price}</b>\n\n"
            "📝 <b>Киритилган ўзгаришлар:</b>\n{changes}{dates_block}\n\n"
            "<i>{signature}</i>"
        ),
        "signature_admin": "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!",
        "notif_not_found": "⚠️ Хабарнома тафсилотлари топилмади.",
        "delete_group_select": "🗑 Ўчирмоқчи бўлган гуруҳингизни танланг:",
        "delete_group_confirm": (
            "⚠️ «<b>{group}</b>» гуруҳи ва унинг Google Sheets'даги "
            "<code>{group}_{year}</code> жадвал листи бутунлай ўчирилади. "
            "Талабалар, ота-оналар ва устоз маълумотлари сақланиб қолади "
            "(талабалар Захира гуруҳига ўтказилади). Тасдиқлайсизми?"
        ),
        "delete_group_success": (
            "✅ «<b>{group}</b>» гуруҳи ва унинг жадвал варақалари тизимдан бутунлай ўчирилди.\n"
            "ℹ️ Гуруҳдаги талабалар маълумотлари сақланиб қолди ва <b>Захира</b> рўйхатига ўтказилди."
        ),
        "delete_group_cancelled": "❌ Гуруҳни ўчириш бекор қилинди.",
        "upfront_cycle_group_notice": (
            "🆕 <b>Янги ўқув ойи бошланди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Давр: <b>{cycle_title}</b> ({start_date} — {end_date})\n"
            "💳 <b>Муҳим эслатма:</b> Янги ўқув ойи учун тўлов 1-дарсдан олдин "
            "(1-дарсдан бошлаб) амалга оширилиши лозим.{fee_block}{card_block}\n\n"
            "<i>Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!</i>"
        ),
        "upfront_cycle_student_notice": (
            "🆕 <b>Янги ўқув ойи очилди!</b>\n\n"
            "Ассалому алайкум, <b>{student_name}</b>!\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Давр: <b>{cycle_title}</b> ({start_date} — {end_date})\n\n"
            "💳 Янги ўқув ойи учун ойлик тўлов <b>1-дарсдан бошлаб (1-дарсдан олдин)</b> "
            "тўланиши лозим.{fee_block}{card_block}\n\n"
            "<i>Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!</i>"
        ),
        "upfront_cycle_parent_notice": (
            "🆕 <b>Янги ўқув ойи бошланди!</b>\n\n"
            "Ассалому алайкум!\n"
            "🎓 Фарзанд(лар)ингиз: <b>{children_names}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Давр: <b>{cycle_title}</b> ({start_date} — {end_date})\n\n"
            "💳 Янги ўқув ойи учун тўлов <b>1-дарсдан бошлаб (1-дарсдан олдин)</b> "
            "амалга оширилиши лозим.{fee_block}{card_block}\n\n"
            "<i>Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!</i>"
        ),
        "admins_panel_title": (
            "👑 <b>Админлар бошқаруви</b>\n\n"
            "<b>Жорий админлар рўйхати:</b>\n{admins_lines}"
        ),
        "admins_static_tag": "Асосий админ",
        "admins_dynamic_tag": "Тайинланган админ",
        "admins_btn_invite": "🔗 Админ ҳаволаси",
        "admins_invite_created": (
            "🔗 <b>Янги админ учун бир марталик таклиф ҳаволаси яратилди!</b>\n\n"
            "👉 Ҳавола:\n<code>{invite_link}</code>\n\n"
            "<i>Ушбу ҳавола фақат 1 марта ишлатилади.</i>"
        ),
        "admins_remove_confirm": (
            "⚠️ <b>{name}</b> (<code>{tid}</code>) ни админлар рўйхатидан "
            "ўчирмоқчимисиз?"
        ),
        "admins_btn_confirm_remove": "✅ Ҳа, ўчириш",
        "admins_removed_ok": "✅ <b>{name}</b> админлар рўйхатидан ўчирилди.",
        "admins_cannot_remove_static": "⚠️ Асосий админни (.env) ўчириб бўлмайди!",
        "admins_cannot_remove_self": "⚠️ Ўзингизни ўчира олмайсиз!",
        "admins_removed_notify": "ℹ️ Сизнинг админ ҳуқуқларингиз бекор қилинди.",
        "admins_btn_groups": "📚 Гуруҳлар бўлими",
    },
}


def _lt(key: str, lang: str = "latn", **kwargs: Any) -> str:
    safe_lang = lang if lang in LOCAL_TEXTS else "latn"
    template = LOCAL_TEXTS[safe_lang].get(key) or LOCAL_TEXTS["latn"].get(key, key)
    return template.format(**kwargs) if kwargs else template


def _format_uzs(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


async def _ensure_admin_tables() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_invites (
                invite_code TEXT PRIMARY KEY,
                created_by INTEGER,
                status TEXT NOT NULL DEFAULT 'pending',
                used_by INTEGER,
                created_at TEXT NOT NULL
            );
            """
        )
        await db.commit()


async def _is_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    db_fn = getattr(database, "is_admin", None)
    if callable(db_fn):
        try:
            if await db_fn(user_id):
                return True
        except Exception:
            pass
    db_user = await get_user(user_id)
    if db_user and db_user.get("role") == "admin":
        return True
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT 1 FROM dynamic_admins WHERE telegram_id = ?;",
                (user_id,),
            ) as cur:
                if await cur.fetchone():
                    return True
    except Exception:
        pass
    return False


async def _create_admin_invite_record(invite_code: str, created_by: int) -> None:
    await _ensure_admin_tables()
    now_iso = now_tashkent().isoformat()
    db_fn = getattr(database, "create_admin_invite", None)
    if callable(db_fn):
        try:
            sig = inspect.signature(db_fn)
            if len(sig.parameters) >= 2:
                await db_fn(invite_code, created_by)
            else:
                await db_fn(invite_code)
        except Exception:
            pass

    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                """
                INSERT OR IGNORE INTO admin_invites (invite_code, created_by, status, created_at)
                VALUES (?, ?, 'pending', ?);
                """,
                (invite_code.strip(), created_by, now_iso),
            )
            await db.commit()
        except Exception:
            pass


async def _list_all_admins() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    static_admins: list[dict[str, Any]] = []
    for aid in ADMIN_IDS:
        u = await get_user(aid)
        static_admins.append(
            {
                "telegram_id": int(aid),
                "full_name": (u.get("full_name") if u else None) or str(aid),
            }
        )

    dynamic_map: dict[int, dict[str, Any]] = {}
    for fn_name in ("get_dynamic_admins", "get_all_admins", "get_all_dynamic_admins"):
        db_fn = getattr(database, fn_name, None)
        if callable(db_fn):
            try:
                rows = await db_fn()
                for r in rows or []:
                    tid = int(r.get("telegram_id") or r.get("chat_id") or 0)
                    if tid and tid not in ADMIN_IDS:
                        dynamic_map[tid] = {
                            "telegram_id": tid,
                            "full_name": r.get("full_name") or str(tid),
                        }
            except Exception:
                pass

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT telegram_id, full_name FROM users WHERE role = 'admin';"
        ) as cur:
            for row in await cur.fetchall():
                tid = int(row["telegram_id"])
                if tid not in ADMIN_IDS and tid not in dynamic_map:
                    dynamic_map[tid] = {
                        "telegram_id": tid,
                        "full_name": row["full_name"] or str(tid),
                    }
        try:
            async with db.execute(
                "SELECT telegram_id, full_name FROM dynamic_admins;"
            ) as cur:
                for row in await cur.fetchall():
                    tid = int(row["telegram_id"])
                    if tid not in ADMIN_IDS and tid not in dynamic_map:
                        dynamic_map[tid] = {
                            "telegram_id": tid,
                            "full_name": row["full_name"] or str(tid),
                        }
        except Exception:
            pass

    dynamic_admins = sorted(
        dynamic_map.values(), key=lambda x: str(x["full_name"]).lower()
    )
    return static_admins, dynamic_admins


async def _remove_dynamic_admin_record(target_id: int) -> None:
    for fn_name in ("remove_dynamic_admin", "remove_admin", "demote_admin"):
        db_fn = getattr(database, fn_name, None)
        if callable(db_fn):
            try:
                await db_fn(target_id)
            except Exception:
                pass

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT full_name FROM teachers WHERE telegram_id = ? AND status = 'active';",
            (target_id,),
        ) as cur:
            t_row = await cur.fetchone()
        if t_row:
            await db.execute(
                "UPDATE users SET role = 'teacher' WHERE telegram_id = ?;",
                (target_id,),
            )
        else:
            await db.execute(
                "DELETE FROM users WHERE telegram_id = ? AND role = 'admin';",
                (target_id,),
            )
        try:
            await db.execute(
                "DELETE FROM dynamic_admins WHERE telegram_id = ?;",
                (target_id,),
            )
        except Exception:
            pass
        await db.commit()


async def _reset_teacher_role_in_sqlite(
    teacher_id: str, chat_id: str
) -> None:
    clean_tid = str(teacher_id or "").strip()
    clean_cid = str(chat_id or "").strip()
    tg_id_int = int(clean_cid) if clean_cid.isdigit() else None

    if tg_id_int is not None:
        await reset_user_role(tg_id_int)

    async with aiosqlite.connect(DB_PATH) as db:
        if clean_tid:
            try:
                await db.execute(
                    "DELETE FROM teachers WHERE invite_code = ?;",
                    (clean_tid,),
                )
            except Exception:
                pass
            try:
                await db.execute(
                    "DELETE FROM teacher_meta WHERE invite_code = ?;",
                    (clean_tid,),
                )
            except Exception:
                pass
        await db.commit()


async def _ensure_teacher_meta_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS teacher_meta (
                invite_code TEXT PRIMARY KEY,
                telegram_id INTEGER,
                phone TEXT,
                username TEXT,
                linked_group_name TEXT,
                invited_by INTEGER
            );
            """
        )
        await db.commit()


async def _upsert_teacher_meta(
    invite_code: str,
    telegram_id: Optional[int] = None,
    phone: Optional[str] = None,
    username: Optional[str] = None,
    linked_group_name: Optional[str] = None,
    invited_by: Optional[int] = None,
) -> None:
    await _ensure_teacher_meta_table()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM teacher_meta WHERE invite_code = ?;",
            (invite_code.strip(),),
        ) as cur:
            row = await cur.fetchone()
            existing = dict(row) if row else None

        new_tg = (
            telegram_id
            if telegram_id is not None
            else (existing["telegram_id"] if existing else None)
        )
        new_phone = (
            phone if phone is not None else (existing["phone"] if existing else None)
        )
        new_username = (
            username
            if username is not None
            else (existing["username"] if existing else None)
        )
        new_group = (
            linked_group_name
            if linked_group_name is not None
            else (existing["linked_group_name"] if existing else None)
        )
        new_inviter = (
            invited_by
            if invited_by is not None
            else (existing["invited_by"] if existing else None)
        )

        await db.execute(
            """
            INSERT INTO teacher_meta (
                invite_code, telegram_id, phone, username, linked_group_name, invited_by
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(invite_code) DO UPDATE SET
                telegram_id = excluded.telegram_id,
                phone = excluded.phone,
                username = excluded.username,
                linked_group_name = excluded.linked_group_name,
                invited_by = excluded.invited_by;
            """,
            (
                invite_code.strip(),
                new_tg,
                new_phone,
                new_username,
                new_group,
                new_inviter,
            ),
        )
        await db.commit()


async def _get_teacher_meta_by_tg(telegram_id: int) -> Optional[dict[str, Any]]:
    await _ensure_teacher_meta_table()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM teacher_meta WHERE telegram_id = ? ORDER BY rowid DESC LIMIT 1;",
            (telegram_id,),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def _clear_group_link_in_teacher_meta(group_name: str) -> None:
    await _ensure_teacher_meta_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE teacher_meta SET linked_group_name = NULL WHERE LOWER(linked_group_name) = LOWER(?);",
            (group_name.strip(),),
        )
        await db.commit()


async def _cleanup_deleted_group_in_sqlite(group_name: str) -> None:
    await _clear_group_link_in_teacher_meta(group_name)
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "DELETE FROM group_counters WHERE LOWER(group_name) = LOWER(?);",
                (group_name.strip(),),
            )
        except Exception:
            pass
        await db.commit()


async def _rename_group_in_sqlite(old_name: str, new_name: str) -> None:
    await _ensure_teacher_meta_table()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE teacher_meta SET linked_group_name = ? WHERE LOWER(linked_group_name) = LOWER(?);",
            (new_name.strip(), old_name.strip()),
        )
        await db.execute(
            "UPDATE group_counters SET group_name = ? WHERE LOWER(group_name) = LOWER(?);",
            (new_name.strip(), old_name.strip()),
        )
        await db.execute(
            "UPDATE join_requests SET group_name = ? WHERE LOWER(group_name) = LOWER(?);",
            (new_name.strip(), old_name.strip()),
        )
        try:
            await db.execute(
                "UPDATE lesson_topics SET group_name = ? WHERE LOWER(group_name) = LOWER(?);",
                (new_name.strip(), old_name.strip()),
            )
        except Exception:
            pass
        await db.commit()


def _sync_refresh_teacher_groups_column(
    sheets: SheetsManager, teacher_chat_id: str
) -> None:
    if not teacher_chat_id.strip():
        return
    with sheets._lock:
        ws = sheets._get_or_create_worksheet(
            TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=200, cols=10
        )
        rows = ws.get_all_values()
        if len(rows) <= 1:
            return
        headers = rows[0]
        if "Chat_ID" not in headers or "Guruhlar" not in headers:
            return
        guruh_col = headers.index("Guruhlar")
        joined = ", ".join(
            g.get("Guruh_Nomi", "").strip()
            for g in sheets.get_teacher_groups(teacher_chat_id)
            if g.get("Guruh_Nomi", "").strip()
        )
        for idx, raw_row in enumerate(rows[1:], start=2):
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            if (
                dict(zip(headers, padded)).get("Chat_ID", "").strip()
                == teacher_chat_id.strip()
            ):
                ws.update(
                    f"{_col_letter(guruh_col)}{idx}",
                    [[joined]],
                    value_input_option="USER_ENTERED",
                )
                break


def _sync_get_teacher_sheet_by_chat_id(
    sheets: SheetsManager, chat_id: str
) -> Optional[dict[str, str]]:
    if not chat_id.strip():
        return None
    with sheets._lock:
        ws = sheets._get_or_create_worksheet(
            TEACHER_SHEET_NAME, headers=TEACHER_HEADERS, rows=200, cols=10
        )
        rows = ws.get_all_values()
        if len(rows) <= 1:
            return None
        headers = rows[0]
        for raw_row in rows[1:]:
            padded = raw_row + [""] * (len(headers) - len(raw_row))
            rec = dict(zip(headers, padded))
            if rec.get("Chat_ID", "").strip() == chat_id.strip():
                return rec
        return None


def _sync_rename_group_everywhere(
    sheets: SheetsManager, old_name: str, new_name: str
) -> None:
    sheets.update_group_full_info(old_name, {"Guruh_Nomi": new_name.strip()})


def _sync_update_group_fee(
    sheets: SheetsManager, group_name: str, amount: int
) -> None:
    with sheets._lock:
        ss = sheets._get_spreadsheet()
        ws = ss.worksheet("Guruhlar")
        headers = ws.row_values(1)
        if "Oylik_Tolov_Summa" not in headers:
            col_idx = len(headers)
            if ws.col_count < col_idx + 1:
                ws.resize(cols=col_idx + 1)
            ws.update(
                f"{_col_letter(col_idx)}1",
                [["Oylik_Tolov_Summa"]],
                value_input_option="USER_ENTERED",
            )
            ss.batch_update(
                {
                    "requests": [
                        _cell_bg_request(
                            ws.id,
                            0,
                            1,
                            col_idx,
                            col_idx + 1,
                            COLOR_HEADER_GRAY,
                            bold=True,
                        )
                    ]
                }
            )
        sheets.update_group(group_name, {"Oylik_Tolov_Summa": str(amount)})


def _make_join_slug(group_name: str) -> str:
    return (
        re.sub(r"[^A-Za-z0-9_-]+", "_", group_name.strip()).strip("_")[:55]
        or "group"
    )


def _format_clickable_phone(raw_phone: str, fallback: str = "—") -> str:
    cleaned = str(raw_phone or "").strip()
    if not cleaned or cleaned == PLACEHOLDER_TEXT:
        return fallback
    if cleaned.lower() in {"yo'q", "yoq", "йўқ"}:
        return html.escape(cleaned)
    compact = re.sub(r"[^\d+]", "", cleaned)
    if re.fullmatch(r"\d{9}", compact):
        compact = f"+998{compact}"
    elif re.fullmatch(r"998\d{9}", compact):
        compact = f"+{compact}"
    elif compact and not compact.startswith("+") and len(compact) >= 7:
        compact = f"+{compact}"
    if compact and re.fullmatch(r"\+\d{7,15}", compact):
        safe_tel = html.escape(compact)
        return f'<a href="tel:{safe_tel}">{safe_tel}</a>'
    return html.escape(cleaned)


def _format_clickable_tg(
    raw_tg: str,
    fallback: str = "—",
    chat_id: Optional[str | int] = None,
) -> str:
    cleaned = str(raw_tg or "").strip()
    if cleaned and cleaned != PLACEHOLDER_TEXT and cleaned != "-":
        if cleaned.startswith(("https://t.me/", "http://t.me/", "t.me/")):
            username = cleaned.rstrip("/").split("/")[-1].lstrip("@")
        else:
            username = cleaned.lstrip("@")
        if re.fullmatch(r"[A-Za-z0-9_]{3,}", username):
            safe_u = html.escape(username)
            return f'<a href="https://t.me/{safe_u}">@{safe_u}</a>'
    clean_cid = str(chat_id or "").strip()
    if clean_cid.isdigit():
        return f'<a href="tg://user?id={clean_cid}">Telegram</a>'
    if cleaned and cleaned != PLACEHOLDER_TEXT:
        return html.escape(cleaned)
    return fallback


async def _resolve_group_teacher_info(
    sheets: SheetsManager,
    teacher_chat_id: str,
    lang: str,
    viewer_user_id: Optional[int] = None,
) -> dict[str, str]:
    none_val = _lt("not_provided", lang)
    clean_id = str(teacher_chat_id or "").strip()
    if not clean_id:
        return {
            "name": "",
            "phone": none_val,
            "tg": none_val,
            "block": _lt("teacher_unassigned", lang),
        }

    sheet_t = await asyncio.to_thread(
        _sync_get_teacher_sheet_by_chat_id, sheets, clean_id
    )
    db_t = await get_teacher_by_telegram_id(int(clean_id)) if clean_id.isdigit() else None
    meta_t = await _get_teacher_meta_by_tg(int(clean_id)) if clean_id.isdigit() else None
    db_u = await get_user(int(clean_id)) if clean_id.isdigit() else None

    raw_name = (
        (sheet_t.get("F.I.O.") if sheet_t else "")
        or (db_t.get("full_name") if db_t else "")
        or (db_u.get("full_name") if db_u else "")
        or clean_id
    )
    if raw_name == PLACEHOLDER_TEXT:
        raw_name = clean_id
    raw_phone = (
        (sheet_t.get("Telefon") if sheet_t else "")
        or (meta_t.get("phone") if meta_t else "")
        or ""
    )
    raw_tg = (
        (sheet_t.get("TG_Username") if sheet_t else "")
        or (sheet_t.get("Telegram") if sheet_t else "")
        or (f"@{meta_t['username']}" if meta_t and meta_t.get("username") else "")
        or ""
    )

    phone_fmt = _format_clickable_phone(raw_phone, none_val)
    tg_fmt = _format_clickable_tg(raw_tg, none_val, chat_id=clean_id)
    display_name = html.escape(raw_name)
    if viewer_user_id is not None and clean_id == str(viewer_user_id):
        display_name = f"{display_name} {t('self_marker', lang)}"

    return {
        "name": raw_name,
        "phone": phone_fmt,
        "tg": tg_fmt,
        "block": _lt(
            "teacher_block",
            lang,
            teacher_name=display_name,
            teacher_phone=phone_fmt,
            teacher_tg=tg_fmt,
        ),
    }


def _format_days(days_raw: str, lang: str) -> str:
    day_indices = parse_weekdays(days_raw)
    if not day_indices:
        return html.escape(days_raw.strip()) if days_raw.strip() else "—"
    names = WEEKDAYS_SHORT.get(lang, WEEKDAYS_SHORT["latn"])
    return ", ".join(names[idx] for idx in day_indices if idx in names)


def _format_days_from_indices(day_indices: list[int], lang: str) -> str:
    names = WEEKDAYS_SHORT.get(lang, WEEKDAYS_SHORT["latn"])
    return ", ".join(names[idx] for idx in day_indices if idx in names)


def _format_change_value(field_key: str, val: str, lang: str) -> str:
    cleaned = str(val or "").strip()
    if field_key == "Oylik_Dars_Soni":
        if not cleaned:
            return "—"
        unit = "та" if lang == "cyrl" else "ta"
        return f"{html.escape(cleaned)} {unit}"
    if field_key == "Dars_Kunlari":
        return _format_days(cleaned, lang) if cleaned else "—"
    if field_key in {"Oylik_Tolov_Summa", "Tolov_Summasi"}:
        if cleaned.isdigit() and int(cleaned) > 0:
            return html.escape(format_uzs(cleaned, lang))
        return html.escape(t("group_price_not_set", lang))
    return html.escape(cleaned) if cleaned else "—"


def _format_change_item(
    field_key: str, old_val: str, new_val: str, lang: str
) -> str:
    label = html.escape(format_field_label(field_key, lang))
    old_fmt = _format_change_value(field_key, old_val, lang)
    new_fmt = _format_change_value(field_key, new_val, lang)
    return f"• <b>{label}:</b> {old_fmt} ➡️ {new_fmt}"


def _format_changes_list(
    change_items: list[tuple[str, str, str]], lang: str
) -> str:
    if not change_items:
        return "• —"
    return "\n".join(
        _format_change_item(fk, ov, nv, lang) for fk, ov, nv in change_items
    )


async def _broadcast_group_update(
    bot: Any,
    sheets: SheetsManager,
    group_name: str,
    change_items: list[tuple[str, str, str]],
    dates_list: Optional[list[str]] = None,
    triggered_by_user_id: Optional[int] = None,
) -> int:
    """
    Universal broadcast on ANY group change (Name, Teacher, Fee, Days, Time, Count, TG Chat).
    Uses plain human-readable labels (no raw column names), builds short + detailed texts,
    saves them via database.save_notification_details(...), and sends the short version
    with a `📄 Batafsil` / `📋 Qisqacha` inline toggle button.
    """
    group = await sheets.a_get_group(group_name)
    if not group:
        return 0
    canonical = group["Guruh_Nomi"].strip()
    students = await asyncio.to_thread(
        sheets.get_all_students, group_name=canonical, active_only=True
    )

    recipient_ids: list[int] = []
    seen_ids: set[int] = set()

    def _add_recipient(raw_val: Any) -> None:
        cleaned = str(raw_val or "").strip()
        if not cleaned:
            return
        try:
            cid = int(cleaned)
        except ValueError:
            return
        if cid not in seen_ids:
            seen_ids.add(cid)
            recipient_ids.append(cid)

    _add_recipient(group.get("Guruh_TG_Chat_ID"))
    _add_recipient(group.get("Ustoz_Chat_ID"))
    for stu in students:
        _add_recipient(stu.get("Talaba_Chat_ID"))
        _add_recipient(stu.get("Otasi_Chat_ID"))
        _add_recipient(stu.get("Onasi_Chat_ID"))
        _add_recipient(stu.get("OtaOna_Chat_ID"))

    if not recipient_ids:
        return 0

    is_teacher_actor = False
    actor_teacher_name = ""
    if triggered_by_user_id is not None and not await _is_admin(triggered_by_user_id):
        is_teacher_actor = True
        actor_info = await _resolve_group_teacher_info(
            sheets, str(triggered_by_user_id), "latn"
        )
        actor_teacher_name = actor_info["name"] or str(triggered_by_user_id)

    raw_fee = str(group.get("Oylik_Tolov_Summa", "")).strip()
    count_val = str(group.get("Oylik_Dars_Soni", "")).strip() or "12"
    time_val = html.escape(str(group.get("Dars_Vaqti", "")).strip() or "—")
    days_raw = str(group.get("Dars_Kunlari", "")).strip()
    teacher_cid = str(group.get("Ustoz_Chat_ID", "")).strip()

    base_notif_id = f"grp_{secrets.token_hex(4)}"
    cached_by_lang: dict[str, tuple[str, str, str]] = {}
    sent_count = 0

    for cid in recipient_ids:
        try:
            r_lang = await get_user_lang(cid) if cid > 0 else "latn"
            if r_lang not in cached_by_lang:
                notif_id = f"{base_notif_id}_{r_lang}"
                changes_str = _format_changes_list(change_items, r_lang)
                teacher_info = await _resolve_group_teacher_info(
                    sheets, teacher_cid, r_lang
                )
                price_str = (
                    html.escape(format_uzs(raw_fee, r_lang))
                    if raw_fee.isdigit() and int(raw_fee) > 0
                    else html.escape(t("group_price_not_set", r_lang))
                )
                dates_block = ""
                if dates_list:
                    dates_fmt = format_uz_date_list(dates_list, r_lang)
                    lbl = (
                        "🗓 <b>Янгиланган саналар:</b> "
                        if r_lang == "cyrl"
                        else "🗓 <b>Yangilangan sanalar:</b> "
                    )
                    dates_block = f"\n{lbl}<code>{html.escape(dates_fmt)}</code>"

                if is_teacher_actor:
                    signature = t(
                        "topic_teacher_footer",
                        r_lang,
                        teacher_name=html.escape(actor_teacher_name),
                    )
                else:
                    signature = _lt("signature_admin", r_lang)

                short_text = _lt(
                    "broadcast_short",
                    r_lang,
                    group=html.escape(canonical),
                    changes=changes_str,
                    signature=signature,
                )
                detailed_text = _lt(
                    "broadcast_detailed",
                    r_lang,
                    group=html.escape(canonical),
                    teacher_block=teacher_info["block"],
                    days=_format_days(days_raw, r_lang),
                    time=time_val,
                    count=html.escape(count_val),
                    price=price_str,
                    changes=changes_str,
                    dates_block=dates_block,
                    signature=signature,
                )
                await save_notification_details(notif_id, short_text, detailed_text)
                cached_by_lang[r_lang] = (notif_id, short_text, detailed_text)

            notif_id, short_text, _ = cached_by_lang[r_lang]
            kb = build_expandable_notif_kb(notif_id, expanded=False, lang=r_lang)
            await bot.send_message(
                chat_id=cid,
                text=short_text,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            sent_count += 1
        except Exception:
            pass
    return sent_count


async def _notify_upfront_cycle_payment(
    bot: Any,
    sheets: SheetsManager,
    group_name: str,
    cycle_info: dict[str, Any],
) -> None:
    """
    Announces that payment for the newly created group/cycle is due starting
    before Lesson 1, and sends deduplicated parent notices (combining siblings
    in the same group into ONE message with accurate summed fee).
    """
    group = await sheets.a_get_group(group_name)
    if not group:
        return
    canonical = group["Guruh_Nomi"].strip()
    active_students = await asyncio.to_thread(
        sheets.get_all_students, group_name=canonical, active_only=True
    )

    raw_fee = str(group.get("Oylik_Tolov_Summa", "")).strip()
    fee_per_student = int(raw_fee) if raw_fee.isdigit() and int(raw_fee) > 0 else 0
    card_number = str(getattr(_app_config, "CARD_NUMBER", "") or "").strip()
    card_owner = str(getattr(_app_config, "CARD_OWNER", "") or "").strip()

    cycle_title = str(cycle_info.get("cycle_title") or "").strip()
    start_raw = str(cycle_info.get("start_date") or "").strip()
    end_raw = str(cycle_info.get("end_date") or "").strip()

    def _card_block_for(lang: str) -> str:
        if not card_number:
            return ""
        return "\n\n" + t(
            "payment_card_block",
            lang,
            card_number=html.escape(card_number),
            card_owner=html.escape(card_owner or "—"),
        )

    # 1. Group TG chat announcement (if linked)
    group_tg_cid = str(group.get("Guruh_TG_Chat_ID", "")).strip()
    if group_tg_cid and re.fullmatch(r"-?\d+", group_tg_cid):
        g_lang = "latn"
        fee_blk = (
            f"\n💰 Oylik to‘lov summasi: <b>{html.escape(format_uzs(fee_per_student, g_lang))}</b>"
            if fee_per_student > 0
            else ""
        )
        try:
            await bot.send_message(
                chat_id=int(group_tg_cid),
                text=_lt(
                    "upfront_cycle_group_notice",
                    g_lang,
                    group=html.escape(canonical),
                    cycle_title=html.escape(cycle_title),
                    start_date=html.escape(format_uz_date(start_raw, g_lang)),
                    end_date=html.escape(format_uz_date(end_raw, g_lang)),
                    fee_block=fee_blk,
                    card_block=_card_block_for(g_lang),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    if not active_students:
        return

    # 2. Individual student notices + aggregate parent -> children mapping
    parent_children: dict[int, list[dict[str, Any]]] = {}
    parent_seen_sids: dict[int, set[str]] = {}

    for stu in active_students:
        sid = str(stu.get("Talaba_ID", "")).strip()
        stu_name = str(stu.get("F.I.O.", "")).strip() or sid
        stu_cid_str = str(stu.get("Talaba_Chat_ID", "")).strip()
        if stu_cid_str.isdigit():
            s_cid = int(stu_cid_str)
            try:
                s_lang = await get_user_lang(s_cid)
                fee_blk = (
                    f"\n💰 Oylik to‘lov summasi: <b>{html.escape(format_uzs(fee_per_student, s_lang))}</b>"
                    if fee_per_student > 0
                    else ""
                )
                if s_lang == "cyrl" and fee_per_student > 0:
                    fee_blk = f"\n💰 Ойлик тўлов суммаси: <b>{html.escape(format_uzs(fee_per_student, s_lang))}</b>"
                await bot.send_message(
                    chat_id=s_cid,
                    text=_lt(
                        "upfront_cycle_student_notice",
                        s_lang,
                        student_name=html.escape(stu_name),
                        group=html.escape(canonical),
                        cycle_title=html.escape(cycle_title),
                        start_date=html.escape(format_uz_date(start_raw, s_lang)),
                        end_date=html.escape(format_uz_date(end_raw, s_lang)),
                        fee_block=fee_blk,
                        card_block=_card_block_for(s_lang),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

        for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
            raw_p = str(stu.get(col, "")).strip()
            if raw_p.isdigit():
                p_cid = int(raw_p)
                seen_for_parent = parent_seen_sids.setdefault(p_cid, set())
                if sid not in seen_for_parent:
                    seen_for_parent.add(sid)
                    parent_children.setdefault(p_cid, []).append(stu)

    # 3. Deduplicated parent notices (1 message per parent per group with summed fee)
    for p_cid, children in parent_children.items():
        try:
            p_lang = await get_user_lang(p_cid)
            children_names = ", ".join(
                html.escape(str(c.get("F.I.O.", "")).strip() or str(c.get("Talaba_ID", "")))
                for c in children
            )
            fee_blk = ""
            if fee_per_student > 0:
                total_fee = fee_per_student * len(children)
                single_fmt = html.escape(format_uzs(fee_per_student, p_lang))
                total_fmt = html.escape(format_uzs(total_fee, p_lang))
                if len(children) > 1:
                    if p_lang == "cyrl":
                        fee_blk = (
                            f"\n💰 Жами тўлов суммаси ({len(children)} та фарзанд × {single_fmt}): "
                            f"<b>{total_fmt}</b>"
                        )
                    else:
                        fee_blk = (
                            f"\n💰 Jami to‘lov summasi ({len(children)} ta farzand × {single_fmt}): "
                            f"<b>{total_fmt}</b>"
                        )
                else:
                    if p_lang == "cyrl":
                        fee_blk = f"\n💰 Ойлик тўлов суммаси: <b>{total_fmt}</b>"
                    else:
                        fee_blk = f"\n💰 Oylik to‘lov summasi: <b>{total_fmt}</b>"

            await bot.send_message(
                chat_id=p_cid,
                text=_lt(
                    "upfront_cycle_parent_notice",
                    p_lang,
                    children_names=children_names,
                    group=html.escape(canonical),
                    cycle_title=html.escape(cycle_title),
                    start_date=html.escape(format_uz_date(start_raw, p_lang)),
                    end_date=html.escape(format_uz_date(end_raw, p_lang)),
                    fee_block=fee_blk,
                    card_block=_card_block_for(p_lang),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass


def _format_student_contact_block(
    index: int,
    student: dict[str, Any],
    lang: str,
    include_bot_status: bool = False,
    viewer_user_id: Optional[int] = None,
) -> str:
    none_val = _lt("not_provided", lang)
    name = html.escape(student.get("F.I.O.", "").strip() or none_val)
    stu_cid = str(student.get("Talaba_Chat_ID", "")).strip()
    if viewer_user_id is not None and stu_cid == str(viewer_user_id):
        name = f"{name} {t('self_marker', lang)}"

    stu_phone = _format_clickable_phone(student.get("Talaba_Tel", ""), none_val)
    tg_link = _format_clickable_tg(
        student.get("Talaba_TG", ""), none_val, chat_id=stu_cid
    )
    lines = [
        f"{index}. <b>{name}</b>",
        f"   {_lt('student_phone_label', lang)}: {stu_phone} | {_lt('telegram_label', lang)}: {tg_link}",
    ]

    father_fio = str(student.get("Otasi_FIO", "")).strip()
    if father_fio == PLACEHOLDER_TEXT:
        father_fio = ""
    father_tel = str(student.get("Otasi_Tel", "")).strip()
    father_cid = str(student.get("Otasi_Chat_ID", "")).strip()
    mother_fio = str(student.get("Onasi_FIO", "")).strip()
    if mother_fio == PLACEHOLDER_TEXT:
        mother_fio = ""
    mother_tel = str(student.get("Onasi_Tel", "")).strip()
    mother_cid = str(student.get("Onasi_Chat_ID", "")).strip()
    legacy_tel = str(student.get("OtaOna_Tel", "")).strip()
    legacy_cid = str(student.get("OtaOna_Chat_ID", "")).strip()

    if not father_tel and not mother_tel and legacy_tel:
        father_tel = legacy_tel
    if not father_cid and not mother_cid and legacy_cid:
        father_cid = legacy_cid

    if include_bot_status or father_fio or father_tel or (
        viewer_user_id is not None and father_cid == str(viewer_user_id)
    ):
        f_name_disp = html.escape(father_fio) if father_fio else none_val
        if viewer_user_id is not None and father_cid == str(viewer_user_id):
            f_name_disp = f"{f_name_disp} {t('self_marker', lang)}"
        f_tel_disp = _format_clickable_phone(father_tel, none_val)
        f_tg_part = (
            f" | {_format_clickable_tg('', none_val, chat_id=father_cid)}"
            if father_cid.isdigit()
            else ""
        )
        lines.append(
            f"   {_lt('father_label', lang)}: <b>{f_name_disp}</b> | 📞 {f_tel_disp}{f_tg_part}"
        )

    if include_bot_status or mother_fio or mother_tel or (
        viewer_user_id is not None and mother_cid == str(viewer_user_id)
    ):
        m_name_disp = html.escape(mother_fio) if mother_fio else none_val
        if viewer_user_id is not None and mother_cid == str(viewer_user_id):
            m_name_disp = f"{m_name_disp} {t('self_marker', lang)}"
        m_tel_disp = _format_clickable_phone(mother_tel, none_val)
        m_tg_part = (
            f" | {_format_clickable_tg('', none_val, chat_id=mother_cid)}"
            if mother_cid.isdigit()
            else ""
        )
        lines.append(
            f"   {_lt('mother_label', lang)}: <b>{m_name_disp}</b> | 📞 {m_tel_disp}{m_tg_part}"
        )

    if include_bot_status:
        stu_linked = (
            _lt("linked_yes", lang)
            if stu_cid
            else _lt("linked_no", lang)
        )
        has_par = any(
            str(student.get(k, "")).strip()
            for k in ("OtaOna_Chat_ID", "Otasi_Chat_ID", "Onasi_Chat_ID")
        )
        par_linked = _lt("linked_yes", lang) if has_par else _lt("linked_no", lang)
        lines.append(
            f"   {_lt('bot_linked_label', lang)}: Talaba ({stu_linked}), Ota-ona ({par_linked})"
            if lang == "latn"
            else f"   {_lt('bot_linked_label', lang)}: Талаба ({stu_linked}), Ота-она ({par_linked})"
        )
    return "\n".join(lines)


def _chunk_lines(header: str, blocks: list[str], max_len: int = 3900) -> list[str]:
    if not blocks:
        return [header]
    messages: list[str] = []
    current = header
    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if len(candidate) > max_len and current != header:
            messages.append(current)
            current = block
        elif len(candidate) > max_len:
            messages.append(current)
            current = block[:max_len]
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def _mode_keyboard(lang: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=_lt("btn_all_groups", lang), callback_data="groups_info:mode:all"
            ),
            InlineKeyboardButton(
                text=_lt("btn_today_groups", lang), callback_data="groups_info:mode:today"
            ),
        ]
    ]
    if is_admin:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_lt("btn_add_group", lang), callback_data="grp_add:start"
                ),
                InlineKeyboardButton(
                    text=_lt("btn_edit_group", lang), callback_data="grp_edit:start"
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("teacher_invite_btn", lang), callback_data="tch_add:start"
                ),
                InlineKeyboardButton(
                    text=_lt("btn_admins_manage", lang), callback_data="adm_mgr:open"
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_delete_group", lang), callback_data="grp_menu:delete"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _groups_list_keyboard(
    groups: list[dict[str, Any]],
    mode: str,
    lang: str,
    include_back: bool = True,
) -> InlineKeyboardMarkup:
    group_buttons = [
        InlineKeyboardButton(
            text=(
                f"📚 {g.get('Guruh_Nomi', '').strip()} ({g.get('Dars_Vaqti', '').strip()})"
                if g.get("Dars_Vaqti", "").strip()
                else f"📚 {g.get('Guruh_Nomi', '').strip()}"
            ),
            callback_data=f"groups_info:view:{mode}:{idx}",
        )
        for idx, g in enumerate(groups)
    ]
    rows = pair_buttons(group_buttons)
    if include_back:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_back", lang), callback_data="groups_info:modes"
                )
            ]
        )
    return balance_inline_markup(InlineKeyboardMarkup(inline_keyboard=rows))


def _group_detail_kb(
    group_name: str, mode: str, lang: str, is_admin: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_admin:
        rows.append(
            [
                InlineKeyboardButton(
                    text=_lt("btn_edit_group", lang),
                    callback_data=f"grp_edit:open:{group_name}",
                ),
                InlineKeyboardButton(
                    text=t("btn_delete_group", lang),
                    callback_data=f"grp_del_ask:{group_name}",
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_back", lang), callback_data=f"groups_info:mode:{mode}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _group_edit_fields_kb(group_name: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_lt("btn_edit_group_name", lang),
                    callback_data=f"grp_edit_fld:{group_name}:name",
                ),
                InlineKeyboardButton(
                    text="👨‍🏫 Ustoz" if lang == "latn" else "👨‍🏫 Устоз",
                    callback_data=f"grp_edit_fld:{group_name}:teacher",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔢 Dars soni" if lang == "latn" else "🔢 Дарс сони",
                    callback_data=f"grp_edit_fld:{group_name}:count",
                ),
                InlineKeyboardButton(
                    text="📆 Dars kunlari" if lang == "latn" else "📆 Дарс кунлари",
                    callback_data=f"grp_edit_fld:{group_name}:days",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏰ Dars vaqti" if lang == "latn" else "⏰ Дарс вақти",
                    callback_data=f"grp_edit_fld:{group_name}:time",
                ),
                InlineKeyboardButton(
                    text=_lt("btn_edit_group_price", lang),
                    callback_data=f"grp_edit_fld:{group_name}:price",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_group_full_update", lang),
                    callback_data=f"grp_edit_fld:{group_name}:full_update",
                ),
                InlineKeyboardButton(
                    text=t("btn_delete_group", lang),
                    callback_data=f"grp_del_ask:{group_name}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_back", lang), callback_data="grp_edit:back:list"
                ),
                InlineKeyboardButton(
                    text=t("btn_cancel", lang), callback_data="grp_edit:cancel"
                ),
            ],
        ]
    )


def _schedule_confirm_kb(group_name: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_lt("btn_confirm_and_update", lang),
                    callback_data="grp_edit:sched_confirm",
                ),
                InlineKeyboardButton(
                    text=t("btn_cancel", lang),
                    callback_data="grp_edit:cancel",
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_back", lang),
                    callback_data=f"grp_edit:back:fields:{group_name}",
                ),
            ],
        ]
    )


async def _build_schedule_preview_dates(
    sheets: SheetsManager,
    group_name: str,
    group: dict[str, Any],
    new_count: int,
    new_days_indices: list[int],
) -> tuple[list[str], int]:
    today = today_tashkent()
    completed_lessons = int(group.get("Otilgan_Dars_Hisoblagich") or 0)
    existing_info = await asyncio.to_thread(
        sheets.get_cycle_dates_with_status, group_name
    )

    if completed_lessons <= 0:
        start_date = today
        if existing_info:
            full_iso = existing_info[0].get("full_date", "")
            if full_iso:
                try:
                    start_date = date.fromisoformat(full_iso)
                except ValueError:
                    start_date = today
        dates = generate_cycle_dates(start_date, new_days_indices, new_count)
        return [d.strftime("%d.%m") for d in dates], 0

    preserved_info = existing_info[:completed_lessons]
    preserved_strs = [item["date_str"] for item in preserved_info]

    last_preserved_date: Optional[date] = None
    if preserved_info:
        full_iso = preserved_info[-1].get("full_date", "")
        if full_iso:
            try:
                last_preserved_date = date.fromisoformat(full_iso)
            except ValueError:
                last_preserved_date = None

    if last_preserved_date and last_preserved_date >= today:
        upcoming_start = last_preserved_date + timedelta(days=1)
    else:
        upcoming_start = today

    remaining = max(0, new_count - len(preserved_strs))
    upcoming_dates = (
        generate_cycle_dates(upcoming_start, new_days_indices, remaining)
        if remaining > 0
        else []
    )
    return preserved_strs + [d.strftime("%d.%m") for d in upcoming_dates], len(
        preserved_strs
    )


async def _prompt_schedule_edit_confirmation(
    target_msg: Message,
    state: FSMContext,
    group_name: str,
    new_count: int,
    new_days_indices: list[int],
    new_time: str,
    lang: str,
    edit: bool = True,
) -> None:
    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    if not group:
        await state.clear()
        await (target_msg.edit_text if edit else target_msg.answer)(
            _lt("group_not_found", lang), parse_mode="HTML"
        )
        return

    preview_dates, preserved_count = await _build_schedule_preview_dates(
        sheets, group_name, group, new_count, new_days_indices
    )
    days_latn = _format_days_from_indices(new_days_indices, "latn")
    days_display = _format_days_from_indices(new_days_indices, lang)
    preserved_note = (
        _lt("edit_schedule_preserved_note", lang, completed=preserved_count)
        if preserved_count > 0
        else ""
    )

    await state.update_data(
        edit_group_name=group["Guruh_Nomi"].strip(),
        pending_sched_count=new_count,
        pending_sched_days_indices=new_days_indices,
        pending_sched_days_str=days_latn,
        pending_sched_time=new_time,
    )
    await state.set_state(CONFIRM_SCHEDULE_STATE)

    text = _lt(
        "edit_schedule_confirm_preview",
        lang,
        group=html.escape(group["Guruh_Nomi"].strip()),
        count=new_count,
        days=days_display,
        time=html.escape(new_time),
        dates_list=(
            format_uz_date_list(preview_dates, lang) if preview_dates else "—"
        ),
        preserved_note=preserved_note,
    )
    kb = _schedule_confirm_kb(group["Guruh_Nomi"].strip(), lang)
    await (target_msg.edit_text if edit else target_msg.answer)(
        text, reply_markup=kb, parse_mode="HTML"
    )


def _admins_manage_kb(
    dynamic_admins: list[dict[str, Any]], lang: str
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=_lt("admins_btn_invite", lang), callback_data="adm_mgr:invite"
            )
        ]
    ]
    for adm in dynamic_admins:
        tid = adm["telegram_id"]
        name = str(adm["full_name"])[:28]
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"🗑 {name} ({tid})",
                    callback_data=f"adm_mgr:del:{tid}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=_lt("admins_btn_groups", lang), callback_data="groups_info:modes"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_admins_panel(
    lang: str, notice: str = ""
) -> tuple[str, InlineKeyboardMarkup]:
    static_admins, dynamic_admins = await _list_all_admins()
    lines: list[str] = []
    static_tag = _lt("admins_static_tag", lang)
    dynamic_tag = _lt("admins_dynamic_tag", lang)

    for sa in static_admins:
        lines.append(
            f"• 🔒 <b>{html.escape(str(sa['full_name']))}</b> "
            f"(<code>{sa['telegram_id']}</code>) — <i>{static_tag}</i>"
        )
    for da in dynamic_admins:
        lines.append(
            f"• 👤 <b>{html.escape(str(da['full_name']))}</b> "
            f"(<code>{da['telegram_id']}</code>) — <i>{dynamic_tag}</i>"
        )

    body = _lt(
        "admins_panel_title",
        lang,
        admins_lines="\n".join(lines) if lines else "—",
    )
    text = f"{notice}\n\n{body}" if notice else body
    return text, _admins_manage_kb(dynamic_admins, lang)


async def _get_accessible_groups(user_id: int, mode: str) -> list[dict[str, Any]]:
    sheets = get_sheets_manager()
    if await _is_admin(user_id):
        groups = await asyncio.to_thread(sheets.get_all_groups)
    else:
        raw_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
        groups = [
            g
            for g in raw_groups
            if str(g.get("Ustoz_Chat_ID", "")).strip() == str(user_id)
        ]
    if mode == "today":
        wd = now_tashkent().weekday()
        groups = [
            g for g in groups if wd in parse_weekdays(g.get("Dars_Kunlari", ""))
        ]
    return groups


# ----------------------------------------------------------------------
# Expandable Notification Toggle (`📄 Batafsil` / `📋 Qisqacha`)
# ----------------------------------------------------------------------


@router.callback_query(F.data.startswith("notif_toggle:"))
async def cb_notif_toggle(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    parts = (callback.data or "").split(":")
    if len(parts) < 3:
        await callback.answer()
        return
    notif_id = parts[1].strip()
    mode = parts[2].strip().lower()
    is_expanded = mode in {"1", "detail", "detailed", "true"}

    user_lang = await get_user_lang(callback.from_user.id)
    details = await get_notification_details(notif_id)
    if not details:
        await callback.answer(_lt("notif_not_found", user_lang), show_alert=True)
        return

    if notif_id.endswith("_latn"):
        kb_lang = "latn"
    elif notif_id.endswith("_cyrl"):
        kb_lang = "cyrl"
    else:
        kb_lang = user_lang

    new_text = details["detailed_text"] if is_expanded else details["short_text"]
    kb = build_expandable_notif_kb(notif_id, expanded=is_expanded, lang=kb_lang)
    try:
        await callback.message.edit_text(
            new_text,
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await callback.answer()


# ----------------------------------------------------------------------
# Complete Group Deletion (`🗑 Guruhni o'chirish`)
# ----------------------------------------------------------------------


async def _show_delete_group_list(
    target_msg: Message, state: FSMContext, lang: str, edit: bool
) -> None:
    await state.clear()
    groups = await asyncio.to_thread(get_sheets_manager().get_all_groups)
    if not groups:
        back_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("btn_back", lang), callback_data="groups_info:modes"
                    )
                ]
            ]
        )
        await (target_msg.edit_text if edit else target_msg.answer)(
            _lt("no_groups_all", lang),
            reply_markup=back_kb if edit else None,
            parse_mode="HTML",
        )
        return

    kb = groups_inline_kb(
        groups, "grp_del_sel", lang, include_back=True, include_cancel=True
    )
    await (target_msg.edit_text if edit else target_msg.answer)(
        _lt("delete_group_select", lang),
        reply_markup=kb,
        parse_mode="HTML",
    )


async def _prompt_delete_group_confirmation(
    target_msg: Message, group_name: str, lang: str, edit: bool = True
) -> None:
    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    canonical = group["Guruh_Nomi"].strip() if group else group_name.strip()
    now_year = now_tashkent().year
    await (target_msg.edit_text if edit else target_msg.answer)(
        _lt(
            "delete_group_confirm",
            lang,
            group=html.escape(canonical),
            year=now_year,
        ),
        reply_markup=group_delete_confirm_kb(canonical, lang),
        parse_mode="HTML",
    )


@router.message(F.text.in_(DELETE_GROUP_BTN_TEXTS))
async def msg_delete_group_menu(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    await _show_delete_group_list(message, state, lang, edit=False)


@router.callback_query(F.data.startswith("grp_menu:"))
async def cb_groups_root_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    action = (callback.data or "").split(":", 1)[1].strip()

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text(
            _lt("delete_group_cancelled", lang), parse_mode="HTML"
        )
        await callback.answer()
        return

    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return

    if action == "delete":
        await _show_delete_group_list(callback.message, state, lang, edit=True)
    elif action == "add":
        await cb_add_group_start(callback, state)
        return
    elif action == "edit":
        await cb_edit_group_start(callback, state)
        return
    elif action == "add_teacher":
        await cb_add_teacher_start(callback, state)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("grp_del_sel:"))
async def cb_delete_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    val = (callback.data or "").split(":", 1)[1].strip()
    if val == "__cancel__":
        await state.clear()
        await callback.message.edit_text(
            _lt("delete_group_cancelled", lang), parse_mode="HTML"
        )
        await callback.answer()
        return
    if val == "__back__":
        await state.clear()
        await callback.message.edit_text(
            _lt("choose_groups_mode", lang),
            reply_markup=_mode_keyboard(lang, is_admin=True),
            parse_mode="HTML",
        )
        await callback.answer()
        return
    await _prompt_delete_group_confirmation(callback.message, val, lang, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("grp_del_ask:"))
async def cb_delete_group_ask_direct(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    group_name = (callback.data or "").split("grp_del_ask:", 1)[1].strip()
    await state.clear()
    await _prompt_delete_group_confirmation(
        callback.message, group_name, lang, edit=True
    )
    await callback.answer()


@router.callback_query(F.data.startswith("grp_del_ok:"))
async def cb_delete_group_confirm(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return

    group_name = (callback.data or "").split("grp_del_ok:", 1)[1].strip()
    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    canonical = group["Guruh_Nomi"].strip() if group else group_name
    old_teacher_chat_id = (
        str(group.get("Ustoz_Chat_ID", "")).strip() if group else ""
    )

    deleted = await sheets.a_delete_group_completely(canonical)
    await state.clear()

    if not deleted:
        await callback.message.edit_text(
            _lt("group_not_found", lang), parse_mode="HTML"
        )
        await callback.answer()
        return

    await _cleanup_deleted_group_in_sqlite(canonical)
    if old_teacher_chat_id:
        await asyncio.to_thread(
            _sync_refresh_teacher_groups_column, sheets, old_teacher_chat_id
        )

    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_lt("admins_btn_groups", lang),
                    callback_data="groups_info:modes",
                )
            ]
        ]
    )
    await callback.message.edit_text(
        _lt("delete_group_success", lang, group=html.escape(canonical)),
        reply_markup=back_kb,
        parse_mode="HTML",
    )
    await callback.answer()


# ----------------------------------------------------------------------
# Admin: "👨‍🏫 Ustozlar boshqaruvi" (tch_mgr:...)
# ----------------------------------------------------------------------


def _build_teacher_card_text(teacher: dict[str, Any], lang: str) -> str:
    none_val = _lt("not_provided", lang)
    t_id = html.escape(str(teacher.get("Ustoz_ID", "")).strip() or none_val)
    t_cid = str(teacher.get("Chat_ID") or teacher.get("Ustoz_Chat_ID") or "").strip()
    full_name = html.escape(str(teacher.get("F.I.O.", "")).strip() or none_val)
    phone_fmt = _format_clickable_phone(str(teacher.get("Telefon", "")), none_val)
    raw_tg = str(
        teacher.get("TG_Username") or teacher.get("Telegram") or ""
    ).strip()
    tg_fmt = _format_clickable_tg(raw_tg, none_val, chat_id=t_cid)
    assigned_groups = teacher.get("assigned_groups") or []
    groups_str = (
        ", ".join(html.escape(str(g)) for g in assigned_groups)
        if assigned_groups
        else t("teacher_manage_no_groups", lang)
    )
    return t(
        "teacher_manage_card",
        lang,
        teacher_id=t_id,
        full_name=full_name,
        phone=phone_fmt,
        tg=tg_fmt,
        groups=groups_str,
    )


async def _show_teacher_list_panel(
    target_msg: Message,
    state: FSMContext,
    lang: str,
    edit: bool = False,
    notice: str = "",
) -> None:
    sheets = get_sheets_manager()
    teachers = await sheets.a_get_all_teachers_detailed()
    if not teachers:
        await state.clear()
        empty_text = t("teacher_manage_empty", lang)
        text = f"{notice}\n\n{empty_text}" if notice else empty_text
        await (target_msg.edit_text if edit else target_msg.answer)(
            text, parse_mode="HTML"
        )
        return

    await state.set_state(TeacherManageStates.choosing_teacher)
    header = t("teacher_manage_list_header", lang)
    text = f"{notice}\n\n{header}" if notice else header
    kb = teacher_manage_list_kb(teachers, lang)
    await (target_msg.edit_text if edit else target_msg.answer)(
        text, reply_markup=kb, parse_mode="HTML"
    )


@router.message(F.text.in_(TEACHER_MANAGE_MENU_TEXTS))
async def handle_teachers_manage_menu(
    message: Message, state: FSMContext
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    await state.clear()
    await _show_teacher_list_panel(message, state, lang, edit=False)


@router.message(
    StateFilter(TeacherManageStates),
    F.text.in_({t("btn_cancel", "latn"), t("btn_cancel", "cyrl"), "/cancel"}),
)
async def msg_teacher_manage_cancel(
    message: Message, state: FSMContext
) -> None:
    if message.from_user:
        lang = await get_user_lang(message.from_user.id)
        await state.clear()
        await message.answer(t("teacher_manage_cancelled", lang), parse_mode="HTML")


@router.callback_query(F.data == "tch_mgr:back_menu")
async def cb_teacher_manage_close(
    callback: CallbackQuery, state: FSMContext
) -> None:
    lang = await get_user_lang(callback.from_user.id)
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            t("teacher_manage_cancelled", lang), parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "tch_mgr:list")
async def cb_teacher_manage_list(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    if callback.message:
        await _show_teacher_list_panel(callback.message, state, lang, edit=True)
    await callback.answer()


@router.callback_query(F.data.startswith("tch_mgr:view:"))
async def cb_teacher_manage_view(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    teacher_id = (callback.data or "").split(":", 2)[2].strip()
    sheets = get_sheets_manager()
    teachers = await sheets.a_get_all_teachers_detailed()
    teacher = next(
        (
            tch
            for tch in teachers
            if str(tch.get("Ustoz_ID", "")).strip() == teacher_id
        ),
        None,
    )
    if not teacher:
        if callback.message:
            await _show_teacher_list_panel(callback.message, state, lang, edit=True)
        await callback.answer()
        return

    await state.update_data(manage_teacher_id=teacher_id)
    await state.set_state(TeacherManageStates.viewing_teacher)
    if callback.message:
        await callback.message.edit_text(
            _build_teacher_card_text(teacher, lang),
            reply_markup=teacher_manage_actions_kb(teacher_id, lang),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tch_mgr:assign:"))
async def cb_teacher_manage_assign_prompt(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    teacher_id = (callback.data or "").split(":", 2)[2].strip()
    sheets = get_sheets_manager()
    teacher = await sheets.a_get_teacher_by_id(teacher_id)
    if not teacher:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    groups = await sheets.a_get_all_groups()
    if not groups:
        await callback.answer(
            t("teacher_manage_assign_no_groups", lang), show_alert=True
        )
        return

    await state.update_data(manage_teacher_id=teacher_id)
    await state.set_state(TeacherManageStates.choosing_group_to_assign)
    if callback.message:
        await callback.message.edit_text(
            t(
                "teacher_manage_assign_select_group",
                lang,
                full_name=html.escape(str(teacher.get("F.I.O.", "")).strip()),
            ),
            reply_markup=teacher_manage_assign_groups_kb(
                teacher_id, groups, lang
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tch_mgr:assign_grp:"))
async def cb_teacher_manage_assign_execute(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return

    parts = (callback.data or "").split(":", 3)
    if len(parts) < 4:
        await callback.answer()
        return
    teacher_id = parts[2].strip()
    group_name = parts[3].strip()

    sheets = get_sheets_manager()
    old_group = await sheets.a_get_group(group_name)
    old_teacher_chat_id = (
        str(old_group.get("Ustoz_Chat_ID", "")).strip() if old_group else ""
    )
    old_teacher_name = "—"
    if old_teacher_chat_id:
        old_t_info = await _resolve_group_teacher_info(
            sheets, old_teacher_chat_id, "latn"
        )
        old_teacher_name = old_t_info["name"] or old_teacher_chat_id

    try:
        result = await sheets.a_assign_teacher_to_group(teacher_id, group_name)
    except Exception:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    teacher = result["teacher"]
    group = result["group"]
    canonical_group = str(group.get("Guruh_Nomi", group_name)).strip()
    teacher_name = str(teacher.get("F.I.O.", teacher_id)).strip()
    teacher_chat_id = str(
        teacher.get("Chat_ID") or teacher.get("Ustoz_Chat_ID") or ""
    ).strip()

    if old_teacher_chat_id and old_teacher_chat_id != teacher_chat_id:
        await asyncio.to_thread(
            _sync_refresh_teacher_groups_column, sheets, old_teacher_chat_id
        )
    if teacher_chat_id:
        await asyncio.to_thread(
            _sync_refresh_teacher_groups_column, sheets, teacher_chat_id
        )

    if teacher_chat_id.isdigit() and int(teacher_chat_id) != user_id:
        try:
            t_lang = await get_user_lang(int(teacher_chat_id))
            await callback.bot.send_message(
                chat_id=int(teacher_chat_id),
                text=t(
                    "teacher_manage_assign_notify_teacher",
                    t_lang,
                    group=html.escape(canonical_group),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await _broadcast_group_update(
        callback.bot,
        sheets,
        canonical_group,
        change_items=[("Ustoz", old_teacher_name, teacher_name)],
        triggered_by_user_id=user_id,
    )

    teachers = await sheets.a_get_all_teachers_detailed()
    enriched_teacher = next(
        (
            tch
            for tch in teachers
            if str(tch.get("Ustoz_ID", "")).strip() == teacher_id
        ),
        None,
    )
    notice = t(
        "teacher_manage_assign_success_admin",
        lang,
        full_name=html.escape(teacher_name),
        group=html.escape(canonical_group),
    )

    await state.set_state(TeacherManageStates.viewing_teacher)
    if callback.message:
        if enriched_teacher:
            card_text = _build_teacher_card_text(enriched_teacher, lang)
            await callback.message.edit_text(
                f"{notice}\n\n{card_text}",
                reply_markup=teacher_manage_actions_kb(teacher_id, lang),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        else:
            await callback.message.edit_text(notice, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("tch_mgr:del:"))
async def cb_teacher_manage_delete_prompt(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    teacher_id = (callback.data or "").split(":", 2)[2].strip()
    sheets = get_sheets_manager()
    teachers = await sheets.a_get_all_teachers_detailed()
    teacher = next(
        (
            tch
            for tch in teachers
            if str(tch.get("Ustoz_ID", "")).strip() == teacher_id
        ),
        None,
    )
    if not teacher:
        if callback.message:
            await _show_teacher_list_panel(callback.message, state, lang, edit=True)
        await callback.answer()
        return

    assigned_groups = teacher.get("assigned_groups") or []
    groups_str = (
        ", ".join(html.escape(str(g)) for g in assigned_groups)
        if assigned_groups
        else t("teacher_manage_no_groups", lang)
    )
    await state.update_data(manage_teacher_id=teacher_id)
    await state.set_state(TeacherManageStates.confirm_delete_teacher)
    if callback.message:
        await callback.message.edit_text(
            t(
                "teacher_manage_delete_confirm",
                lang,
                full_name=html.escape(str(teacher.get("F.I.O.", "")).strip()),
                teacher_id=html.escape(teacher_id),
                groups=groups_str,
            ),
            reply_markup=teacher_manage_confirm_delete_kb(teacher_id, lang),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tch_mgr:del_ok:"))
async def cb_teacher_manage_delete_confirm(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    teacher_id = (callback.data or "").split(":", 2)[2].strip()
    sheets = get_sheets_manager()
    teacher = await sheets.a_get_teacher_by_id(teacher_id)
    teacher_name = (
        str(teacher.get("F.I.O.", teacher_id)).strip() if teacher else teacher_id
    )

    payload = await sheets.a_purge_teacher_completely(teacher_id)
    t_cid_int = payload.get("teacher_chat_id")
    teacher_lang_before = await get_user_lang(int(t_cid_int)) if t_cid_int else "latn"
    chat_id = str(t_cid_int) if t_cid_int else ""
    real_tid = str(payload.get("teacher_id") or teacher_id).strip()
    if t_cid_int:
        await database.purge_deleted_person_from_db(int(t_cid_int), "teacher")
    await _reset_teacher_role_in_sqlite(real_tid, "")

    if chat_id.isdigit() and int(chat_id) != user_id:
        target_cid = int(chat_id)
        try:
            t_lang = teacher_lang_before
            await callback.bot.send_message(
                chat_id=target_cid,
                text=t("teacher_manage_delete_notify_teacher", t_lang),
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="HTML",
            )
            await callback.bot.send_message(
                chat_id=target_cid,
                text=t("choose_language", "latn"),
                reply_markup=lang_selection_kb(),
                parse_mode="HTML",
            )
        except Exception:
            pass

    notice = t(
        "teacher_manage_delete_success",
        lang,
        full_name=html.escape(teacher_name),
    )
    notice += t("teacher_manage_delete_purged", lang)
    if callback.message:
        await _show_teacher_list_panel(
            callback.message, state, lang, edit=True, notice=notice
        )
    await callback.answer()


# ----------------------------------------------------------------------
# Student / Parent: "Mening guruhim"
# ----------------------------------------------------------------------


@router.message(
    F.text.in_({t("menu_student_group", "latn"), t("menu_student_group", "cyrl")})
)
async def handle_student_my_group(message: Message) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    sheets = get_sheets_manager()
    user_row = await get_user(user_id)
    student = (
        await sheets.a_get_student_by_id(user_row["linked_student_id"])
        if user_row and user_row.get("linked_student_id")
        else None
    )
    if not student:
        found = await sheets.a_get_student_by_chat_id(user_id)
        if found:
            student = found[0]
    if not student:
        await message.answer(t("unregistered_user", lang), parse_mode="HTML")
        return

    group_name = student.get("Guruh", "").strip()
    if not group_name:
        await message.answer(t("contacts_empty", lang), parse_mode="HTML")
        return
    group = await sheets.a_get_group(group_name)
    classmates = await asyncio.to_thread(
        sheets.get_all_students, group_name=group_name, active_only=True
    )
    days_text = _format_days(group.get("Dars_Kunlari", "") if group else "", lang)
    time_text = (
        html.escape(group.get("Dars_Vaqti", "").strip() or "—") if group else "—"
    )
    teacher_info = await _resolve_group_teacher_info(
        sheets,
        str(group.get("Ustoz_Chat_ID", "") if group else ""),
        lang,
        viewer_user_id=user_id,
    )

    header = _lt(
        "student_group_header",
        lang,
        group=html.escape(group_name),
        days=days_text,
        time=time_text,
        total=len(classmates),
        teacher_block=teacher_info["block"],
    )
    if not classmates:
        await message.answer(
            f"{header}\n\n{t('contacts_empty', lang)}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return
    blocks = [
        _format_student_contact_block(
            idx, s, lang, include_bot_status=False, viewer_user_id=user_id
        )
        for idx, s in enumerate(classmates, start=1)
    ]
    for chunk in _chunk_lines(header, blocks):
        await message.answer(
            chunk, parse_mode="HTML", disable_web_page_preview=True
        )


# ----------------------------------------------------------------------
# Admin Management: "👑 Adminlar boshqaruvi"
# ----------------------------------------------------------------------


@router.message(F.text.in_(ADMIN_MANAGE_MENU_TEXTS))
async def handle_admins_manage_menu(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    await state.clear()
    text, kb = await _render_admins_panel(lang)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "adm_mgr:open")
async def cb_admins_manage_open(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    text, kb = await _render_admins_panel(lang)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "adm_mgr:invite")
async def cb_admins_manage_invite(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    invite_code = secrets.token_hex(4).upper()
    await _create_admin_invite_record(invite_code, user_id)
    bot_me = await callback.bot.get_me()
    invite_link = f"https://t.me/{bot_me.username}?start=adm_{invite_code}"
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_back", lang), callback_data="adm_mgr:open"
                )
            ]
        ]
    )
    if callback.message:
        await callback.message.edit_text(
            _lt("admins_invite_created", lang, invite_link=html.escape(invite_link)),
            reply_markup=back_kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_mgr:del:"))
async def cb_admins_manage_delete_prompt(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    raw_id = (callback.data or "").split(":", 2)[2]
    if not raw_id.isdigit():
        await callback.answer()
        return
    target_id = int(raw_id)
    if target_id in ADMIN_IDS:
        await callback.answer(_lt("admins_cannot_remove_static", lang), show_alert=True)
        return
    if target_id == user_id:
        await callback.answer(_lt("admins_cannot_remove_self", lang), show_alert=True)
        return

    target_user = await get_user(target_id)
    target_name = (target_user.get("full_name") if target_user else None) or str(
        target_id
    )
    confirm_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_lt("admins_btn_confirm_remove", lang),
                    callback_data=f"adm_mgr:del_ok:{target_id}",
                ),
                InlineKeyboardButton(
                    text=t("btn_back", lang), callback_data="adm_mgr:open"
                ),
            ]
        ]
    )
    if callback.message:
        await callback.message.edit_text(
            _lt(
                "admins_remove_confirm",
                lang,
                name=html.escape(target_name),
                tid=target_id,
            ),
            reply_markup=confirm_kb,
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("adm_mgr:del_ok:"))
async def cb_admins_manage_delete_confirm(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    raw_id = (callback.data or "").split(":", 2)[2]
    if not raw_id.isdigit():
        await callback.answer()
        return
    target_id = int(raw_id)
    if target_id in ADMIN_IDS:
        await callback.answer(_lt("admins_cannot_remove_static", lang), show_alert=True)
        return
    if target_id == user_id:
        await callback.answer(_lt("admins_cannot_remove_self", lang), show_alert=True)
        return

    target_user = await get_user(target_id)
    target_name = (target_user.get("full_name") if target_user else None) or str(
        target_id
    )
    await _remove_dynamic_admin_record(target_id)

    try:
        t_lang = await get_user_lang(target_id)
        await callback.bot.send_message(
            chat_id=target_id,
            text=_lt("admins_removed_notify", t_lang),
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML",
        )
    except Exception:
        pass

    notice = _lt("admins_removed_ok", lang, name=html.escape(target_name))
    text, kb = await _render_admins_panel(lang, notice=notice)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


# ----------------------------------------------------------------------
# Teacher / Admin: "Mening guruhlarim" / "Guruhlar"
# ----------------------------------------------------------------------


@router.message(
    F.text.in_(button_texts("menu_teacher_groups", "menu_admin_groups"))
)
async def handle_teacher_groups_menu(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    sheets = get_sheets_manager()
    is_admin = await _is_admin(user_id)
    if not (
        is_admin
        or (await get_teacher_by_telegram_id(user_id) is not None)
        or await sheets.a_is_teacher(user_id)
    ):
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    await state.clear()
    if is_admin:
        await message.answer(
            _lt("choose_groups_mode", lang),
            reply_markup=_mode_keyboard(lang, is_admin=True),
            parse_mode="HTML",
        )
        return

    groups = await _get_accessible_groups(user_id, "all")
    if not groups:
        await message.answer(_lt("no_groups_all", lang), parse_mode="HTML")
        return
    await message.answer(
        _lt("select_teacher_groups", lang),
        reply_markup=_groups_list_keyboard(groups, "all", lang, include_back=False),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "groups_info:modes")
async def cb_groups_modes(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    is_admin = await _is_admin(user_id)
    if not is_admin:
        groups = await _get_accessible_groups(user_id, "all")
        if callback.message:
            if not groups:
                await callback.message.edit_text(
                    _lt("no_groups_all", lang), parse_mode="HTML"
                )
            else:
                await callback.message.edit_text(
                    _lt("select_teacher_groups", lang),
                    reply_markup=_groups_list_keyboard(
                        groups, "all", lang, include_back=False
                    ),
                    parse_mode="HTML",
                )
        await callback.answer()
        return

    if callback.message:
        await callback.message.edit_text(
            _lt("choose_groups_mode", lang),
            reply_markup=_mode_keyboard(lang, is_admin=True),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("groups_info:mode:"))
async def cb_groups_list_by_mode(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    is_admin = await _is_admin(user_id)
    mode = (callback.data or "").split(":")[-1]
    if mode not in {"all", "today"}:
        await callback.answer()
        return
    groups = await _get_accessible_groups(user_id, mode)
    if not groups:
        back_kb = (
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=t("btn_back", lang), callback_data="groups_info:modes"
                        )
                    ]
                ]
            )
            if is_admin
            else None
        )
        if callback.message:
            await callback.message.edit_text(
                _lt("no_groups_today" if mode == "today" else "no_groups_all", lang),
                reply_markup=back_kb,
                parse_mode="HTML",
            )
        await callback.answer()
        return
    if callback.message:
        title = (
            _lt("select_group_today" if mode == "today" else "select_group_all", lang)
            if is_admin
            else _lt("select_teacher_groups", lang)
        )
        await callback.message.edit_text(
            title,
            reply_markup=_groups_list_keyboard(
                groups, mode, lang, include_back=is_admin
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("groups_info:view:"))
async def cb_group_contacts_detail(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    is_admin = await _is_admin(user_id)
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer()
        return
    mode = parts[2]
    try:
        idx = int(parts[3])
    except ValueError:
        await callback.answer()
        return
    groups = await _get_accessible_groups(user_id, mode)
    if idx < 0 or idx >= len(groups):
        if callback.message:
            if is_admin:
                await callback.message.edit_text(
                    _lt("group_not_found", lang),
                    reply_markup=_mode_keyboard(lang, is_admin=True),
                    parse_mode="HTML",
                )
            else:
                await callback.message.edit_text(
                    _lt("group_not_found", lang), parse_mode="HTML"
                )
        await callback.answer()
        return

    group = groups[idx]
    group_name = group.get("Guruh_Nomi", "").strip()
    sheets = get_sheets_manager()
    students = await asyncio.to_thread(
        sheets.get_all_students, group_name=group_name, active_only=True
    )
    bot_me = await callback.bot.get_me()
    join_link = f"https://t.me/{bot_me.username}?start=join_{_make_join_slug(group_name)}"
    teacher_info = await _resolve_group_teacher_info(
        sheets,
        str(group.get("Ustoz_Chat_ID", "")),
        lang,
        viewer_user_id=user_id,
    )

    header = _lt(
        "teacher_group_header",
        lang,
        group=html.escape(group_name),
        days=_format_days(group.get("Dars_Kunlari", ""), lang),
        time=html.escape(group.get("Dars_Vaqti", "").strip() or "—"),
        count=html.escape(str(group.get("Oylik_Dars_Soni", "").strip() or "12")),
        total=len(students),
        teacher_block=teacher_info["block"],
        join_link=html.escape(join_link),
    )
    detail_kb = _group_detail_kb(group_name, mode, lang, is_admin=is_admin)

    if not students:
        if callback.message:
            await callback.message.edit_text(
                f"{header}\n\n{t('contacts_empty', lang)}",
                reply_markup=detail_kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        await callback.answer()
        return

    chunks = _chunk_lines(
        header,
        [
            _format_student_contact_block(
                i, s, lang, include_bot_status=True, viewer_user_id=user_id
            )
            for i, s in enumerate(students, start=1)
        ],
    )
    if callback.message:
        if len(chunks) == 1:
            await callback.message.edit_text(
                chunks[0],
                reply_markup=detail_kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        else:
            await callback.message.edit_text(
                chunks[0], parse_mode="HTML", disable_web_page_preview=True
            )
            for pos, chunk in enumerate(chunks[1:], start=1):
                await callback.message.answer(
                    chunk,
                    reply_markup=(detail_kb if pos == len(chunks) - 1 else None),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )
    await callback.answer()


# ----------------------------------------------------------------------
# Admin: "👨‍🏫 Ustoz qo‘shish" (tch_add:start -> Group Picker -> Auto Invite Link)
# ----------------------------------------------------------------------


@router.callback_query(F.data == "tch_add:start")
async def cb_add_teacher_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    await state.clear()
    groups = await asyncio.to_thread(get_sheets_manager().get_all_groups)

    if not groups:
        invite_code = secrets.token_hex(4).upper()
        await create_teacher_invite(invite_code, PLACEHOLDER_TEXT)
        await _upsert_teacher_meta(invite_code=invite_code, invited_by=user_id)
        bot_me = await callback.bot.get_me()
        invite_link = f"https://t.me/{bot_me.username}?start=tch_{invite_code}"
        back_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("btn_back", lang), callback_data="groups_info:modes"
                    )
                ]
            ]
        )
        if callback.message:
            await callback.message.edit_text(
                _lt(
                    "add_teacher_invite_ready",
                    lang,
                    group="—",
                    invite_link=html.escape(invite_link),
                ),
                reply_markup=back_kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        await callback.answer()
        return

    group_buttons: list[InlineKeyboardButton] = []
    for g in groups:
        g_name = g["Guruh_Nomi"].strip()
        group_buttons.append(
            InlineKeyboardButton(
                text=f"📚 {g_name}",
                callback_data=f"tch_add_grp:{g_name}",
            )
        )
    rows = pair_buttons(group_buttons)
    rows.append(
        [
            InlineKeyboardButton(
                text=_lt("add_teacher_no_group_btn", lang),
                callback_data="tch_add_grp:__none__",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text=t("btn_back", lang), callback_data="groups_info:modes"
            )
        ]
    )
    if callback.message:
        await callback.message.edit_text(
            _lt("add_teacher_select_group", lang),
            reply_markup=balance_inline_markup(
                InlineKeyboardMarkup(inline_keyboard=rows)
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("tch_add_grp:"))
async def cb_add_teacher_group_selected(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    group_name = (callback.data or "").split(":", 1)[1].strip()
    linked_group = None if group_name == "__none__" else group_name

    invite_code = secrets.token_hex(4).upper()
    await create_teacher_invite(invite_code, PLACEHOLDER_TEXT)
    await _upsert_teacher_meta(
        invite_code=invite_code,
        linked_group_name=linked_group,
        invited_by=user_id,
    )
    bot_me = await callback.bot.get_me()
    invite_link = f"https://t.me/{bot_me.username}?start=tch_{invite_code}"
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_back", lang), callback_data="groups_info:modes"
                )
            ]
        ]
    )
    if callback.message:
        await callback.message.edit_text(
            _lt(
                "add_teacher_invite_ready",
                lang,
                group=html.escape(linked_group or "—"),
                invite_link=html.escape(invite_link),
            ),
            reply_markup=back_kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    await callback.answer()


# ----------------------------------------------------------------------
# Admin: "➕ Yangi guruh qo‘shish" (grp_add:...)
# ----------------------------------------------------------------------


@router.callback_query(F.data == "grp_add:start")
async def cb_add_group_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    await state.clear()
    await state.set_state(GroupAddStates.entering_name)
    if callback.message:
        await callback.message.edit_text(
            _lt("add_group_enter_name", lang),
            reply_markup=group_add_cancel_kb(lang, back_cb="grp_add:back:menu"),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "grp_add:back:menu")
async def cb_add_group_back_menu(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    is_admin = await _is_admin(user_id)
    if not is_admin:
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            _lt("choose_groups_mode", lang),
            reply_markup=_mode_keyboard(lang, is_admin=True),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "grp_add:cancel")
async def cb_add_group_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await get_user_lang(callback.from_user.id)
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            _lt("add_group_cancelled", lang), parse_mode="HTML"
        )
    await callback.answer()


@router.message(
    StateFilter(GroupAddStates),
    F.text.in_({t("btn_cancel", "latn"), t("btn_cancel", "cyrl"), "/cancel"}),
)
async def msg_add_group_cancel(message: Message, state: FSMContext) -> None:
    if message.from_user:
        lang = await get_user_lang(message.from_user.id)
        await state.clear()
        await message.answer(_lt("add_group_cancelled", lang), parse_mode="HTML")


@router.callback_query(StateFilter(GroupAddStates), F.data.startswith("grp_add:back:"))
async def cb_add_group_step_back(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    target = (callback.data or "").split(":")[-1]
    data = await state.get_data()
    if target == "name":
        await state.set_state(GroupAddStates.entering_name)
        if callback.message:
            await callback.message.edit_text(
                _lt("add_group_enter_name", lang),
                reply_markup=group_add_cancel_kb(lang, back_cb="grp_add:back:menu"),
                parse_mode="HTML",
            )
    elif target == "teacher":
        teachers = await get_active_teachers()
        await state.set_state(GroupAddStates.selecting_teacher)
        if callback.message:
            await callback.message.edit_text(
                _lt(
                    "add_group_select_teacher",
                    lang,
                    group=html.escape(data.get("group_name", "")),
                ),
                reply_markup=group_add_teacher_kb(
                    teachers, lang, back_cb="grp_add:back:name"
                ),
                parse_mode="HTML",
            )
    elif target == "count":
        await state.set_state(GroupAddStates.selecting_lesson_count)
        if callback.message:
            await callback.message.edit_text(
                t("schedule_select_count", lang),
                reply_markup=group_add_lesson_count_kb(
                    lang, back_cb="grp_add:back:teacher"
                ),
                parse_mode="HTML",
            )
    elif target == "days":
        await state.set_state(GroupAddStates.selecting_days)
        if callback.message:
            await callback.message.edit_text(
                t("schedule_select_days", lang),
                reply_markup=group_add_weekdays_kb(
                    list(data.get("selected_days", [])),
                    lang,
                    back_cb="grp_add:back:count",
                ),
                parse_mode="HTML",
            )
    elif target == "time":
        await state.set_state(GroupAddStates.entering_time)
        if callback.message:
            await callback.message.edit_text(
                t("schedule_enter_time", lang),
                reply_markup=group_add_cancel_kb(lang, back_cb="grp_add:back:days"),
                parse_mode="HTML",
            )
    elif target == "fee":
        await state.set_state(GroupAddStates.entering_fee)
        if callback.message:
            await callback.message.edit_text(
                _lt(
                    "add_group_enter_fee",
                    lang,
                    group=html.escape(data.get("group_name", "")),
                ),
                reply_markup=group_add_cancel_kb(lang, back_cb="grp_add:back:time"),
                parse_mode="HTML",
            )
    await callback.answer()


@router.message(GroupAddStates.entering_name)
async def msg_add_group_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    group_name = (message.text or "").strip()
    if (
        not group_name
        or len(group_name) > 50
        or group_name.startswith("__")
        or INVALID_SHEET_CHARS_RE.search(group_name)
        or "\n" in group_name
    ):
        await message.answer(
            _lt("add_group_invalid_name", lang),
            reply_markup=group_add_cancel_kb(lang, back_cb="grp_add:back:menu"),
            parse_mode="HTML",
        )
        return
    if await get_sheets_manager().a_get_group(group_name):
        await message.answer(
            _lt("add_group_already_exists", lang, group=html.escape(group_name)),
            reply_markup=group_add_cancel_kb(lang, back_cb="grp_add:back:menu"),
            parse_mode="HTML",
        )
        return
    teachers = await get_active_teachers()
    await state.update_data(group_name=group_name)
    await state.set_state(GroupAddStates.selecting_teacher)
    await message.answer(
        _lt("add_group_select_teacher", lang, group=html.escape(group_name)),
        reply_markup=group_add_teacher_kb(
            teachers, lang, back_cb="grp_add:back:name"
        ),
        parse_mode="HTML",
    )


@router.callback_query(
    GroupAddStates.selecting_teacher, F.data == "grp_add:self_teacher"
)
async def cb_add_group_self_teacher(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    await state.update_data(
        teacher_chat_id=str(user_id),
        teacher_label=f"{callback.from_user.full_name} ({user_id})",
        pending_teacher_invite_code=None,
    )
    await state.set_state(GroupAddStates.selecting_lesson_count)
    if callback.message:
        await callback.message.edit_text(
            t("schedule_select_count", lang),
            reply_markup=group_add_lesson_count_kb(
                lang, back_cb="grp_add:back:teacher"
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(
    GroupAddStates.selecting_teacher, F.data == "grp_add:invite_teacher"
)
async def cb_add_group_invite_teacher(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    group_name = (await state.get_data()).get("group_name", "")
    invite_code = secrets.token_hex(4).upper()
    await create_teacher_invite(invite_code, PLACEHOLDER_TEXT)
    await _upsert_teacher_meta(
        invite_code=invite_code,
        linked_group_name=group_name or None,
        invited_by=user_id,
    )
    bot_me = await callback.bot.get_me()
    invite_link = f"https://t.me/{bot_me.username}?start=tch_{invite_code}"
    await state.update_data(
        teacher_chat_id="",
        teacher_label=f"🔗 Taklif havolasi ({invite_code})",
        pending_teacher_invite_code=invite_code,
    )
    await state.set_state(GroupAddStates.selecting_lesson_count)
    if callback.message:
        await callback.message.edit_text(
            _lt("add_group_invite_generated", lang, invite_link=html.escape(invite_link)),
            reply_markup=group_add_lesson_count_kb(
                lang, back_cb="grp_add:back:teacher"
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    await callback.answer()


@router.callback_query(
    GroupAddStates.selecting_teacher, F.data.startswith("grp_add:teacher:")
)
async def cb_add_group_select_teacher(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    raw_id = (callback.data or "").split(":")[-1]
    if not raw_id.isdigit():
        await callback.answer()
        return
    teacher = await get_teacher_by_telegram_id(int(raw_id))
    await state.update_data(
        teacher_chat_id=raw_id,
        teacher_label=teacher["full_name"] if teacher else raw_id,
        pending_teacher_invite_code=None,
    )
    await state.set_state(GroupAddStates.selecting_lesson_count)
    if callback.message:
        await callback.message.edit_text(
            t("schedule_select_count", lang),
            reply_markup=group_add_lesson_count_kb(
                lang, back_cb="grp_add:back:teacher"
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(GroupAddStates.selecting_teacher)
async def msg_add_group_teacher_fallback(
    message: Message, state: FSMContext
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    await message.answer(
        _lt("add_group_select_teacher_btn_only", lang),
        reply_markup=group_add_teacher_kb(
            await get_active_teachers(), lang, back_cb="grp_add:back:name"
        ),
        parse_mode="HTML",
    )


@router.callback_query(
    GroupAddStates.selecting_lesson_count, F.data.startswith("grp_add:count:")
)
async def cb_add_group_lesson_count(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    raw_count = (callback.data or "").split(":")[-1]
    if raw_count not in {"8", "12"}:
        await callback.answer()
        return
    await state.update_data(lesson_count=int(raw_count), selected_days=[])
    await state.set_state(GroupAddStates.selecting_days)
    if callback.message:
        await callback.message.edit_text(
            t("schedule_select_days", lang),
            reply_markup=group_add_weekdays_kb(
                [], lang, back_cb="grp_add:back:count"
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(
    GroupAddStates.selecting_days, F.data.startswith("grp_add:day:")
)
async def cb_add_group_toggle_day(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    try:
        day_idx = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    if not (0 <= day_idx <= 6):
        await callback.answer()
        return
    selected_days = list((await state.get_data()).get("selected_days", []))
    if day_idx in selected_days:
        selected_days.remove(day_idx)
    else:
        selected_days.append(day_idx)
    selected_days.sort()
    await state.update_data(selected_days=selected_days)
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=group_add_weekdays_kb(
                selected_days, lang, back_cb="grp_add:back:count"
            )
        )
    await callback.answer()


@router.callback_query(
    GroupAddStates.selecting_days, F.data == "grp_add:days_done"
)
async def cb_add_group_days_done(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    if not (await state.get_data()).get("selected_days"):
        await callback.answer(
            _lt("add_group_select_days_alert", lang), show_alert=True
        )
        return
    await state.set_state(GroupAddStates.entering_time)
    if callback.message:
        await callback.message.edit_text(
            t("schedule_enter_time", lang),
            reply_markup=group_add_cancel_kb(lang, back_cb="grp_add:back:days"),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(GroupAddStates.entering_time)
async def msg_add_group_time(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    match = TIME_FORMAT_RE.fullmatch((message.text or "").strip())
    if not match:
        await message.answer(
            t("schedule_invalid_time", lang),
            reply_markup=group_add_cancel_kb(lang, back_cb="grp_add:back:days"),
            parse_mode="HTML",
        )
        return
    lesson_time = f"{int(match.group(1)):02d}:{match.group(2)}"
    data = await state.get_data()
    await state.update_data(lesson_time=lesson_time)
    # Next step: monthly tuition fee ("Oylik to'lov summasi") right in creation
    await state.set_state(GroupAddStates.entering_fee)
    await message.answer(
        _lt(
            "add_group_enter_fee",
            lang,
            group=html.escape(str(data.get("group_name", ""))),
        ),
        reply_markup=group_add_cancel_kb(lang, back_cb="grp_add:back:time"),
        parse_mode="HTML",
    )


def _parse_fee_input(raw: str) -> Optional[int]:
    raw_text = (raw or "").strip().lower()
    for suffix in ("so'm", "so‘m", "som", "sum", "сўм", "uzs"):
        raw_text = raw_text.replace(suffix, "")
    cleaned = re.sub(r"[\s,._]", "", raw_text)
    if not cleaned.isdigit():
        return None
    amount = int(cleaned)
    if amount <= 0 or amount > 100_000_000:
        return None
    if amount < 10000:
        amount *= 1000
    return amount


@router.message(GroupAddStates.entering_fee)
async def msg_add_group_fee(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    amount = _parse_fee_input(message.text or "")
    if amount is None:
        await message.answer(
            _lt("edit_invalid_price", lang),
            reply_markup=group_add_cancel_kb(lang, back_cb="grp_add:back:time"),
            parse_mode="HTML",
        )
        return
    data = await state.get_data()
    selected_days = sorted(data["selected_days"])
    lesson_count = int(data["lesson_count"])
    lesson_time = str(data.get("lesson_time") or "")
    lesson_dates = generate_cycle_dates(
        today_tashkent(), selected_days, lesson_count
    )
    await state.update_data(monthly_fee=amount)
    await state.set_state(GroupAddStates.confirming)
    summary = _lt(
        "add_group_confirm_summary",
        lang,
        group=html.escape(data["group_name"]),
        teacher_label=html.escape(
            str(data.get("teacher_label") or data.get("teacher_chat_id") or "—")
        ),
        count=lesson_count,
        days=_format_days_from_indices(selected_days, lang),
        time=html.escape(lesson_time),
        cycle_title=html.escape(format_cycle_title(lesson_dates, 1)),
        start_date=format_uz_date(lesson_dates[0].strftime("%d.%m"), lang),
        end_date=format_uz_date(lesson_dates[-1].strftime("%d.%m"), lang),
    )
    summary += "\n" + _lt("add_group_fee_line", lang, amount=_format_uzs(amount))
    await message.answer(
        summary,
        reply_markup=group_add_confirm_kb(lang, back_cb="grp_add:back:fee"),
        parse_mode="HTML",
    )


@router.callback_query(GroupAddStates.confirming, F.data == "grp_add:confirm")
async def cb_add_group_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    data = await state.get_data()
    if not {"group_name", "lesson_count", "selected_days", "lesson_time"}.issubset(
        data.keys()
    ):
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                t("error_generic", lang), parse_mode="HTML"
            )
        await callback.answer()
        return

    group_name = data["group_name"]
    teacher_chat_id = str(data.get("teacher_chat_id") or "")
    teacher_label = str(data.get("teacher_label") or teacher_chat_id or "—")
    pending_invite = data.get("pending_teacher_invite_code")
    lesson_count = int(data["lesson_count"])
    selected_days = sorted(data["selected_days"])
    lesson_time = data["lesson_time"]
    monthly_fee = int(data.get("monthly_fee") or 0)

    if pending_invite:
        inv = await get_teacher_by_invite_code(pending_invite)
        if inv and inv.get("status") == "active" and inv.get("telegram_id"):
            teacher_chat_id = str(inv["telegram_id"])
            teacher_label = inv.get("full_name") or teacher_chat_id
        else:
            await _upsert_teacher_meta(
                invite_code=pending_invite,
                linked_group_name=group_name,
                invited_by=user_id,
            )

    sheets = get_sheets_manager()
    if await sheets.a_get_group(group_name):
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                _lt("add_group_already_exists", lang, group=html.escape(group_name)),
                parse_mode="HTML",
            )
        await callback.answer()
        return

    today = today_tashkent()
    try:
        await asyncio.to_thread(
            sheets.add_group,
            group_name,
            teacher_chat_id,
            "",
            lesson_count,
            _format_days_from_indices(selected_days, "latn"),
            lesson_time,
            "",
            str(monthly_fee) if monthly_fee > 0 else "",
        )
        cycle_info = await asyncio.to_thread(
            sheets.create_cycle_table, group_name, today, 1, today.year
        )
        if teacher_chat_id:
            await asyncio.to_thread(
                _sync_refresh_teacher_groups_column, sheets, teacher_chat_id
            )
    except Exception:
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                t("error_generic", lang), parse_mode="HTML"
            )
        await callback.answer()
        return

    if teacher_chat_id.isdigit() and int(teacher_chat_id) != user_id:
        try:
            t_lang = await get_user_lang(int(teacher_chat_id))
            await callback.bot.send_message(
                chat_id=int(teacher_chat_id),
                text=_lt(
                    "teacher_reassigned_notify",
                    t_lang,
                    group=html.escape(group_name),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await _notify_upfront_cycle_payment(
        callback.bot, sheets, group_name, cycle_info
    )

    bot_me = await callback.bot.get_me()
    join_link = f"https://t.me/{bot_me.username}?start=join_{_make_join_slug(group_name)}"
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            _lt(
                "add_group_success",
                lang,
                group=html.escape(group_name),
                teacher_label=html.escape(teacher_label),
                days=_format_days_from_indices(selected_days, lang),
                time=html.escape(lesson_time),
                sheet_title=html.escape(cycle_info["sheet_title"]),
                cycle_title=html.escape(cycle_info["cycle_title"]),
                start_date=html.escape(format_uz_date(cycle_info["start_date"], lang)),
                end_date=html.escape(format_uz_date(cycle_info["end_date"], lang)),
                join_link=html.escape(join_link),
            )
            + (
                "\n\n" + _lt("add_group_fee_line", lang, amount=_format_uzs(monthly_fee))
                if monthly_fee > 0
                else ""
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    await callback.answer()


# ----------------------------------------------------------------------
# Admin: "✏️ Guruhni tahrirlash" (grp_edit:...)
# ----------------------------------------------------------------------


async def _show_group_edit_panel(
    message: Message,
    state: FSMContext,
    group_name: str,
    lang: str,
    edit: bool = True,
    notice: str = "",
) -> None:
    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    if not group:
        await state.clear()
        await (message.edit_text if edit else message.answer)(
            _lt("group_not_found", lang), parse_mode="HTML"
        )
        return
    canonical = group["Guruh_Nomi"].strip()
    teacher_info = await _resolve_group_teacher_info(
        sheets, str(group.get("Ustoz_Chat_ID", "")), lang
    )
    await state.update_data(edit_group_name=canonical)
    await state.set_state(GroupEditStates.choosing_action)
    body = t(
        "group_edit_info",
        lang,
        group=html.escape(canonical),
        teacher_name=html.escape(teacher_info["name"] or _lt("not_provided", lang)),
        count=html.escape(str(group.get("Oylik_Dars_Soni") or "12")),
        days=_format_days(group.get("Dars_Kunlari", ""), lang),
        time=html.escape(group.get("Dars_Vaqti", "").strip() or "—"),
    )
    raw_fee = str(group.get("Oylik_Tolov_Summa", "")).strip()
    if raw_fee.isdigit() and int(raw_fee) > 0:
        fee_line = _lt("group_fee_line", lang, amount=_format_uzs(int(raw_fee)))
    else:
        fee_line = _lt("group_fee_not_set", lang)
    body = f"{body}\n{fee_line}"

    text = f"{notice}\n\n{body}" if notice else body
    kb = _group_edit_fields_kb(canonical, lang)
    await (message.edit_text if edit else message.answer)(
        text, reply_markup=kb, parse_mode="HTML"
    )


@router.callback_query(F.data == "grp_edit:start")
async def cb_edit_group_start(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    groups = await asyncio.to_thread(get_sheets_manager().get_all_groups)
    if not groups:
        await callback.answer(_lt("no_groups_all", lang), show_alert=True)
        return
    await state.clear()
    await state.set_state(GroupEditStates.selecting_group)
    if callback.message:
        await callback.message.edit_text(
            t("group_edit_select", lang),
            reply_markup=groups_inline_kb(
                groups, "grp_edit_sel", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("grp_edit:open:"))
async def cb_edit_group_direct(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    group_name = (callback.data or "").split("grp_edit:open:", 1)[1]
    await state.clear()
    if callback.message:
        await _show_group_edit_panel(callback.message, state, group_name, lang, edit=True)
    await callback.answer()


@router.callback_query(
    StateFilter(GroupEditStates, EDIT_PRICE_STATE, CONFIRM_SCHEDULE_STATE),
    F.data == "grp_edit:cancel",
)
async def cb_edit_group_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await get_user_lang(callback.from_user.id)
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            _lt("edit_cancelled", lang), parse_mode="HTML"
        )
    await callback.answer()


@router.message(
    StateFilter(GroupEditStates, EDIT_PRICE_STATE, CONFIRM_SCHEDULE_STATE),
    F.text.in_({t("btn_cancel", "latn"), t("btn_cancel", "cyrl"), "/cancel"}),
)
async def msg_edit_group_cancel(message: Message, state: FSMContext) -> None:
    if message.from_user:
        lang = await get_user_lang(message.from_user.id)
        await state.clear()
        await message.answer(_lt("edit_cancelled", lang), parse_mode="HTML")


@router.callback_query(
    GroupEditStates.selecting_group, F.data.startswith("grp_edit_sel:")
)
async def cb_edit_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    val = (callback.data or "").split(":", 1)[1]
    if val == "__cancel__":
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                _lt("edit_cancelled", lang), parse_mode="HTML"
            )
        await callback.answer()
        return
    if val == "__back__":
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                _lt("choose_groups_mode", lang),
                reply_markup=_mode_keyboard(lang, is_admin=True),
                parse_mode="HTML",
            )
        await callback.answer()
        return
    if callback.message:
        await _show_group_edit_panel(callback.message, state, val, lang, edit=True)
    await callback.answer()


@router.callback_query(
    StateFilter(GroupEditStates, EDIT_PRICE_STATE, CONFIRM_SCHEDULE_STATE),
    F.data.startswith("grp_edit:back:"),
)
async def cb_edit_group_back(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    parts = (callback.data or "").split(":", 3)
    target = parts[2] if len(parts) > 2 else "list"
    if target == "list":
        groups = await asyncio.to_thread(get_sheets_manager().get_all_groups)
        await state.set_state(GroupEditStates.selecting_group)
        if callback.message:
            await callback.message.edit_text(
                t("group_edit_select", lang),
                reply_markup=groups_inline_kb(
                    groups,
                    "grp_edit_sel",
                    lang,
                    include_back=True,
                    include_cancel=True,
                ),
                parse_mode="HTML",
            )
    elif target == "fields":
        group_name = (
            parts[3]
            if len(parts) > 3
            else (await state.get_data()).get("edit_group_name", "")
        )
        if callback.message:
            await _show_group_edit_panel(
                callback.message, state, group_name, lang, edit=True
            )
    await callback.answer()


@router.callback_query(
    GroupEditStates.choosing_action, F.data.startswith("grp_edit_fld:")
)
async def cb_edit_group_field(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    _, group_name, field = (callback.data or "").split(":", 2)
    await state.update_data(edit_group_name=group_name)
    if not callback.message:
        await callback.answer()
        return

    if field == "name":
        await state.set_state(GroupEditStates.entering_new_name)
        await callback.message.edit_text(
            _lt("edit_enter_new_name", lang, group=html.escape(group_name)),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb=f"grp_edit:back:fields:{group_name}",
                cancel_cb="grp_edit:cancel",
            ),
            parse_mode="HTML",
        )
    elif field == "teacher":
        teachers = await get_active_teachers()
        await state.set_state(GroupEditStates.selecting_teacher)
        await callback.message.edit_text(
            _lt("edit_select_teacher", lang, group=html.escape(group_name)),
            reply_markup=group_edit_teacher_kb(group_name, teachers, lang),
            parse_mode="HTML",
        )
    elif field == "count":
        await state.set_state(GroupEditStates.selecting_lesson_count)
        await callback.message.edit_text(
            t("schedule_select_count", lang),
            reply_markup=group_edit_lesson_count_kb(group_name, lang),
            parse_mode="HTML",
        )
    elif field == "days":
        group = await get_sheets_manager().a_get_group(group_name)
        current_days = parse_weekdays(group.get("Dars_Kunlari", "") if group else "")
        await state.update_data(edit_selected_days=current_days)
        await state.set_state(GroupEditStates.selecting_days)
        await callback.message.edit_text(
            t("schedule_select_days", lang),
            reply_markup=group_edit_weekdays_kb(group_name, current_days, lang),
            parse_mode="HTML",
        )
    elif field == "time":
        await state.set_state(GroupEditStates.entering_time)
        await callback.message.edit_text(
            t("schedule_enter_time", lang),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb=f"grp_edit:back:fields:{group_name}",
                cancel_cb="grp_edit:cancel",
            ),
            parse_mode="HTML",
        )
    elif field == "price":
        await state.set_state(EDIT_PRICE_STATE)
        await callback.message.edit_text(
            _lt("edit_enter_price", lang, group=html.escape(group_name)),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb=f"grp_edit:back:fields:{group_name}",
                cancel_cb="grp_edit:cancel",
            ),
            parse_mode="HTML",
        )
    elif field == "full_update":
        group = await get_sheets_manager().a_get_group(group_name)
        if not group:
            await callback.answer(_lt("group_not_found", lang), show_alert=True)
            return
        canonical = group["Guruh_Nomi"].strip()
        orig = {
            "Guruh_Nomi": canonical,
            "Oylik_Dars_Soni": str(group.get("Oylik_Dars_Soni") or "12"),
            "Dars_Kunlari": str(group.get("Dars_Kunlari") or ""),
            "Dars_Vaqti": str(group.get("Dars_Vaqti") or ""),
            "Oylik_Tolov_Summa": str(group.get("Oylik_Tolov_Summa") or ""),
            "Guruh_TG_Chat_ID": str(group.get("Guruh_TG_Chat_ID") or ""),
        }
        await state.update_data(
            full_old_group_name=canonical,
            full_orig=orig,
            full_new={},
            full_selected_days=parse_weekdays(orig["Dars_Kunlari"]),
        )
        await state.set_state(FullGroupEditStates.editing_name)
        await callback.message.edit_text(
            t("group_full_edit_name", lang, current=html.escape(canonical)),
            reply_markup=full_group_edit_step_kb(lang),
            parse_mode="HTML",
        )
    await callback.answer()


@router.message(GroupEditStates.entering_new_name)
async def msg_edit_group_new_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    old_name = (await state.get_data()).get("edit_group_name", "")
    new_name = (message.text or "").strip()
    if (
        not new_name
        or len(new_name) > 50
        or new_name.startswith("__")
        or INVALID_SHEET_CHARS_RE.search(new_name)
        or "\n" in new_name
    ):
        await message.answer(
            _lt("add_group_invalid_name", lang),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb=f"grp_edit:back:fields:{old_name}",
                cancel_cb="grp_edit:cancel",
            ),
            parse_mode="HTML",
        )
        return
    sheets = get_sheets_manager()
    existing = await sheets.a_get_group(new_name)
    if (
        existing
        and existing.get("Guruh_Nomi", "").strip().lower() != old_name.strip().lower()
    ):
        await message.answer(
            _lt("add_group_already_exists", lang, group=html.escape(new_name)),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb=f"grp_edit:back:fields:{old_name}",
                cancel_cb="grp_edit:cancel",
            ),
            parse_mode="HTML",
        )
        return

    await asyncio.to_thread(_sync_rename_group_everywhere, sheets, old_name, new_name)
    await _rename_group_in_sqlite(old_name, new_name)
    await _broadcast_group_update(
        message.bot,
        sheets,
        new_name,
        change_items=[("Guruh_Nomi", old_name, new_name)],
        triggered_by_user_id=user_id,
    )
    await _show_group_edit_panel(
        message,
        state,
        new_name,
        lang,
        edit=False,
        notice=t("group_edit_saved", lang, group=html.escape(new_name)),
    )


@router.callback_query(
    GroupEditStates.selecting_teacher, F.data.startswith("grp_edit_tch:")
)
async def cb_edit_group_teacher(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    _, group_name, target = (callback.data or "").split(":", 2)
    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    old_teacher_id = str(group.get("Ustoz_Chat_ID", "") if group else "").strip()
    old_teacher_name = "—"
    if old_teacher_id:
        old_t_info = await _resolve_group_teacher_info(sheets, old_teacher_id, "latn")
        old_teacher_name = old_t_info["name"] or old_teacher_id

    if target == "__invite__":
        invite_code = secrets.token_hex(4).upper()
        await create_teacher_invite(invite_code, PLACEHOLDER_TEXT)
        await _clear_group_link_in_teacher_meta(group_name)
        await _upsert_teacher_meta(
            invite_code=invite_code, linked_group_name=group_name, invited_by=user_id
        )
        await asyncio.to_thread(sheets.update_group, group_name, {"Ustoz_Chat_ID": ""})
        if old_teacher_id:
            await asyncio.to_thread(
                _sync_refresh_teacher_groups_column, sheets, old_teacher_id
            )
        bot_me = await callback.bot.get_me()
        invite_link = f"https://t.me/{bot_me.username}?start=tch_{invite_code}"
        notice = _lt(
            "edit_invite_created",
            lang,
            group=html.escape(group_name),
            invite_link=html.escape(invite_link),
        )
        if callback.message:
            await _show_group_edit_panel(
                callback.message, state, group_name, lang, edit=True, notice=notice
            )
        await callback.answer()
        return

    new_teacher_id = str(user_id) if target == "__self__" else target
    await _clear_group_link_in_teacher_meta(group_name)
    await asyncio.to_thread(
        sheets.update_group, group_name, {"Ustoz_Chat_ID": new_teacher_id}
    )
    if old_teacher_id and old_teacher_id != new_teacher_id:
        await asyncio.to_thread(
            _sync_refresh_teacher_groups_column, sheets, old_teacher_id
        )
    await asyncio.to_thread(
        _sync_refresh_teacher_groups_column, sheets, new_teacher_id
    )

    if new_teacher_id.isdigit() and int(new_teacher_id) != user_id:
        try:
            t_lang = await get_user_lang(int(new_teacher_id))
            await callback.bot.send_message(
                chat_id=int(new_teacher_id),
                text=_lt(
                    "teacher_reassigned_notify",
                    t_lang,
                    group=html.escape(group_name),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    t_info = await _resolve_group_teacher_info(sheets, new_teacher_id, "latn")
    new_teacher_name = t_info["name"] or new_teacher_id
    await _broadcast_group_update(
        callback.bot,
        sheets,
        group_name,
        change_items=[("Ustoz", old_teacher_name, new_teacher_name)],
        triggered_by_user_id=user_id,
    )

    if callback.message:
        await _show_group_edit_panel(
            callback.message,
            state,
            group_name,
            lang,
            edit=True,
            notice=t("group_edit_saved", lang, group=html.escape(group_name)),
        )
    await callback.answer()


@router.callback_query(
    GroupEditStates.selecting_lesson_count, F.data.startswith("grp_edit_cnt:")
)
async def cb_edit_group_count(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    _, group_name, count_str = (callback.data or "").split(":", 2)
    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    if not group:
        await callback.answer(_lt("group_not_found", lang), show_alert=True)
        return

    new_count = int(count_str)
    current_days_indices = parse_weekdays(group.get("Dars_Kunlari", ""))
    if not current_days_indices:
        current_days_indices = [0, 2, 4]
    current_time = group.get("Dars_Vaqti", "").strip() or "14:00"

    if callback.message:
        await _prompt_schedule_edit_confirmation(
            callback.message,
            state,
            group_name,
            new_count,
            current_days_indices,
            current_time,
            lang,
            edit=True,
        )
    await callback.answer()


@router.callback_query(
    GroupEditStates.selecting_days, F.data.startswith("grp_edit_day:")
)
async def cb_edit_group_toggle_day(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    try:
        day_idx = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    selected = list(data.get("edit_selected_days", []))
    if day_idx in selected:
        selected.remove(day_idx)
    else:
        selected.append(day_idx)
    selected.sort()
    await state.update_data(edit_selected_days=selected)
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=group_edit_weekdays_kb(
                data.get("edit_group_name", ""), selected, lang
            )
        )
    await callback.answer()


@router.callback_query(
    GroupEditStates.selecting_days, F.data.startswith("grp_edit_days_done:")
)
async def cb_edit_group_days_done(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    group_name = (callback.data or "").split(":", 1)[1]
    selected = sorted((await state.get_data()).get("edit_selected_days", []))
    if not selected:
        await callback.answer(
            _lt("add_group_select_days_alert", lang), show_alert=True
        )
        return

    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    if not group:
        await callback.answer(_lt("group_not_found", lang), show_alert=True)
        return

    current_count = int(group.get("Oylik_Dars_Soni") or 12)
    current_time = group.get("Dars_Vaqti", "").strip() or "14:00"

    if callback.message:
        await _prompt_schedule_edit_confirmation(
            callback.message,
            state,
            group_name,
            current_count,
            selected,
            current_time,
            lang,
            edit=True,
        )
    await callback.answer()


@router.message(GroupEditStates.entering_time)
async def msg_edit_group_time(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    group_name = (await state.get_data()).get("edit_group_name", "")
    match = TIME_FORMAT_RE.fullmatch((message.text or "").strip())
    if not match:
        await message.answer(
            t("schedule_invalid_time", lang),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb=f"grp_edit:back:fields:{group_name}",
                cancel_cb="grp_edit:cancel",
            ),
            parse_mode="HTML",
        )
        return
    lesson_time = f"{int(match.group(1)):02d}:{match.group(2)}"

    sheets = get_sheets_manager()
    group = await sheets.a_get_group(group_name)
    if not group:
        await state.clear()
        await message.answer(_lt("group_not_found", lang), parse_mode="HTML")
        return

    current_count = int(group.get("Oylik_Dars_Soni") or 12)
    current_days_indices = parse_weekdays(group.get("Dars_Kunlari", ""))
    if not current_days_indices:
        current_days_indices = [0, 2, 4]

    await _prompt_schedule_edit_confirmation(
        message,
        state,
        group_name,
        current_count,
        current_days_indices,
        lesson_time,
        lang,
        edit=False,
    )


@router.callback_query(
    StateFilter(CONFIRM_SCHEDULE_STATE), F.data == "grp_edit:sched_confirm"
)
async def cb_edit_group_schedule_confirm(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return

    data = await state.get_data()
    group_name = data.get("edit_group_name", "")
    new_count = int(data.get("pending_sched_count") or 12)
    days_indices = list(data.get("pending_sched_days_indices") or [])
    days_str = str(data.get("pending_sched_days_str") or "")
    new_time = str(data.get("pending_sched_time") or "14:00")

    if not group_name or not days_indices:
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                t("error_generic", lang), parse_mode="HTML"
            )
        await callback.answer()
        return

    sheets = get_sheets_manager()
    old_group = await sheets.a_get_group(group_name)
    old_count = str(old_group.get("Oylik_Dars_Soni") or "12") if old_group else "12"
    old_days = str(old_group.get("Dars_Kunlari") or "") if old_group else ""
    old_time = str(old_group.get("Dars_Vaqti") or "") if old_group else ""

    change_items: list[tuple[str, str, str]] = []
    if str(new_count) != old_count.strip():
        change_items.append(("Oylik_Dars_Soni", old_count, str(new_count)))
    if parse_weekdays(old_days) != sorted(days_indices):
        change_items.append(("Dars_Kunlari", old_days, days_str))
    if new_time.strip() != old_time.strip():
        change_items.append(("Dars_Vaqti", old_time, new_time))
    if not change_items:
        change_items.append(("Dars_Vaqti", old_time, new_time))

    try:
        final_dates = await asyncio.to_thread(
            sheets.rebuild_active_cycle_sheet,
            group_name,
            new_count,
            days_str,
            new_time,
        )
    except Exception:
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                t("error_generic", lang), parse_mode="HTML"
            )
        await callback.answer()
        return

    sent_count = await _broadcast_group_update(
        callback.bot,
        sheets,
        group_name,
        change_items=change_items,
        dates_list=final_dates,
        triggered_by_user_id=user_id,
    )

    notice = _lt(
        "edit_schedule_saved_broadcast",
        lang,
        group=html.escape(group_name),
        sent_count=sent_count,
    )
    if callback.message:
        await _show_group_edit_panel(
            callback.message, state, group_name, lang, edit=True, notice=notice
        )
    await callback.answer()


@router.message(StateFilter(EDIT_PRICE_STATE))
async def msg_edit_group_price(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    group_name = (await state.get_data()).get("edit_group_name", "")

    raw_text = (message.text or "").strip().lower()
    for suffix in ("so'm", "so‘m", "som", "sum", "сўм", "uzs"):
        raw_text = raw_text.replace(suffix, "")
    cleaned = re.sub(r"[\s,_]", "", raw_text)

    if not cleaned.isdigit():
        await message.answer(
            _lt("edit_invalid_price", lang),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb=f"grp_edit:back:fields:{group_name}",
                cancel_cb="grp_edit:cancel",
            ),
            parse_mode="HTML",
        )
        return

    amount = int(cleaned)
    if amount <= 0 or amount > 100_000_000:
        await message.answer(
            _lt("edit_invalid_price", lang),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb=f"grp_edit:back:fields:{group_name}",
                cancel_cb="grp_edit:cancel",
            ),
            parse_mode="HTML",
        )
        return

    if amount < 10000:
        amount *= 1000

    sheets = get_sheets_manager()
    old_group = await sheets.a_get_group(group_name)
    old_fee = str(old_group.get("Oylik_Tolov_Summa", "") if old_group else "").strip()

    await asyncio.to_thread(_sync_update_group_fee, sheets, group_name, amount)
    await _broadcast_group_update(
        message.bot,
        sheets,
        group_name,
        change_items=[("Oylik_Tolov_Summa", old_fee, str(amount))],
        triggered_by_user_id=user_id,
    )
    notice = _lt(
        "edit_price_saved",
        lang,
        group=html.escape(group_name),
        amount=_format_uzs(amount),
    )
    await _show_group_edit_panel(
        message, state, group_name, lang, edit=False, notice=notice
    )


# ----------------------------------------------------------------------
# Admin: Full Group Update Wizard (FullGroupEditStates)
# ----------------------------------------------------------------------


async def _advance_full_group_step(
    target_msg: Message,
    state: FSMContext,
    next_step: str,
    lang: str,
    edit: bool = True,
) -> None:
    data = await state.get_data()
    orig = data.get("full_orig", {})
    new_vals = data.get("full_new", {})

    if next_step == "count":
        await state.set_state(FullGroupEditStates.editing_lesson_count)
        text = t(
            "group_full_edit_count",
            lang,
            current=html.escape(str(orig.get("Oylik_Dars_Soni") or "12")),
        )
        kb = full_group_edit_count_kb(lang)
    elif next_step == "days":
        selected = list(data.get("full_selected_days") or [])
        await state.set_state(FullGroupEditStates.editing_days)
        text = t(
            "group_full_edit_days",
            lang,
            current=_format_days(orig.get("Dars_Kunlari", ""), lang),
        )
        kb = full_group_edit_weekdays_kb(selected, lang)
    elif next_step == "time":
        await state.set_state(FullGroupEditStates.editing_time)
        text = t(
            "group_full_edit_time",
            lang,
            current=html.escape(orig.get("Dars_Vaqti") or "—"),
        )
        kb = full_group_edit_step_kb(lang)
    elif next_step == "fee":
        await state.set_state(FullGroupEditStates.editing_fee)
        raw_fee = str(orig.get("Oylik_Tolov_Summa") or "").strip()
        fee_disp = (
            format_uzs(raw_fee, lang)
            if raw_fee.isdigit() and int(raw_fee) > 0
            else t("group_price_not_set", lang)
        )
        text = t("group_full_edit_price", lang, current=fee_disp)
        kb = full_group_edit_step_kb(lang)
    elif next_step == "chat_id":
        await state.set_state(FullGroupEditStates.editing_chat_id)
        text = t(
            "group_full_edit_tg_chat",
            lang,
            current=html.escape(orig.get("Guruh_TG_Chat_ID") or "—"),
        )
        kb = full_group_edit_step_kb(lang)
    else:
        await state.set_state(FullGroupEditStates.confirm_all)
        old_fee = str(orig.get("Oylik_Tolov_Summa") or "").strip()
        new_fee = str(new_vals.get("Oylik_Tolov_Summa", old_fee)).strip()
        old_fee_disp = (
            format_uzs(old_fee, lang)
            if old_fee.isdigit() and int(old_fee) > 0
            else "—"
        )
        new_fee_disp = (
            format_uzs(new_fee, lang)
            if new_fee.isdigit() and int(new_fee) > 0
            else "—"
        )
        text = _lt(
            "full_edit_summary",
            lang,
            old_name=html.escape(orig.get("Guruh_Nomi", "")),
            new_name=html.escape(
                new_vals.get("Guruh_Nomi", orig.get("Guruh_Nomi", ""))
            ),
            old_count=html.escape(orig.get("Oylik_Dars_Soni", "12")),
            new_count=html.escape(
                str(new_vals.get("Oylik_Dars_Soni", orig.get("Oylik_Dars_Soni", "12")))
            ),
            old_days=_format_days(orig.get("Dars_Kunlari", ""), lang),
            new_days=_format_days(
                new_vals.get("Dars_Kunlari", orig.get("Dars_Kunlari", "")), lang
            ),
            old_time=html.escape(orig.get("Dars_Vaqti") or "—"),
            new_time=html.escape(
                new_vals.get("Dars_Vaqti", orig.get("Dars_Vaqti") or "—")
            ),
            old_price=old_fee_disp,
            new_price=new_fee_disp,
            old_chat=html.escape(orig.get("Guruh_TG_Chat_ID") or "—"),
            new_chat=html.escape(
                new_vals.get("Guruh_TG_Chat_ID", orig.get("Guruh_TG_Chat_ID") or "—")
            ),
        )
        kb = full_group_edit_confirm_kb(lang)

    await (target_msg.edit_text if edit else target_msg.answer)(
        text, reply_markup=kb, parse_mode="HTML"
    )


@router.callback_query(StateFilter(FullGroupEditStates), F.data == "full_grp:cancel")
async def cb_full_group_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await get_user_lang(callback.from_user.id)
    await state.clear()
    if callback.message:
        await callback.message.edit_text(
            _lt("edit_cancelled", lang), parse_mode="HTML"
        )
    await callback.answer()


@router.message(
    StateFilter(FullGroupEditStates),
    F.text.in_({t("btn_cancel", "latn"), t("btn_cancel", "cyrl"), "/cancel"}),
)
async def msg_full_group_cancel(message: Message, state: FSMContext) -> None:
    if message.from_user:
        lang = await get_user_lang(message.from_user.id)
        await state.clear()
        await message.answer(_lt("edit_cancelled", lang), parse_mode="HTML")


@router.callback_query(
    StateFilter(FullGroupEditStates), F.data == "full_grp:skip_field"
)
async def cb_full_group_skip(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    cur = await state.get_state()
    next_map = {
        FullGroupEditStates.editing_name.state: "count",
        FullGroupEditStates.editing_lesson_count.state: "days",
        FullGroupEditStates.editing_days.state: "time",
        FullGroupEditStates.editing_time.state: "fee",
        FullGroupEditStates.editing_fee.state: "chat_id",
        FullGroupEditStates.editing_chat_id.state: "confirm",
    }
    nxt = next_map.get(cur or "", "confirm")
    if callback.message:
        await _advance_full_group_step(callback.message, state, nxt, lang, edit=True)
    await callback.answer()


@router.message(FullGroupEditStates.editing_name)
async def msg_full_group_name(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    new_name = (message.text or "").strip()
    if (
        not new_name
        or len(new_name) > 50
        or new_name.startswith("__")
        or INVALID_SHEET_CHARS_RE.search(new_name)
        or "\n" in new_name
    ):
        await message.answer(
            _lt("add_group_invalid_name", lang),
            reply_markup=full_group_edit_step_kb(lang),
            parse_mode="HTML",
        )
        return
    data = await state.get_data()
    old_name = data.get("full_old_group_name", "")
    existing = await get_sheets_manager().a_get_group(new_name)
    if (
        existing
        and existing.get("Guruh_Nomi", "").strip().lower() != old_name.strip().lower()
    ):
        await message.answer(
            _lt("add_group_already_exists", lang, group=html.escape(new_name)),
            reply_markup=full_group_edit_step_kb(lang),
            parse_mode="HTML",
        )
        return
    full_new = dict(data.get("full_new", {}))
    if new_name != old_name:
        full_new["Guruh_Nomi"] = new_name
    await state.update_data(full_new=full_new)
    await _advance_full_group_step(message, state, "count", lang, edit=False)


@router.callback_query(
    FullGroupEditStates.editing_lesson_count, F.data.startswith("full_grp:count:")
)
async def cb_full_group_count(callback: CallbackQuery, state: FSMContext) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    count_str = (callback.data or "").split(":")[-1]
    if count_str not in {"8", "12"}:
        await callback.answer()
        return
    data = await state.get_data()
    full_new = dict(data.get("full_new", {}))
    full_new["Oylik_Dars_Soni"] = count_str
    await state.update_data(full_new=full_new)
    if callback.message:
        await _advance_full_group_step(callback.message, state, "days", lang, edit=True)
    await callback.answer()


@router.callback_query(
    FullGroupEditStates.editing_days, F.data.startswith("full_grp:day:")
)
async def cb_full_group_toggle_day(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    try:
        day_idx = int((callback.data or "").split(":")[-1])
    except ValueError:
        await callback.answer()
        return
    selected = list((await state.get_data()).get("full_selected_days") or [])
    if day_idx in selected:
        selected.remove(day_idx)
    else:
        selected.append(day_idx)
    selected.sort()
    await state.update_data(full_selected_days=selected)
    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=full_group_edit_weekdays_kb(selected, lang)
        )
    await callback.answer()


@router.callback_query(
    FullGroupEditStates.editing_days, F.data == "full_grp:days_done"
)
async def cb_full_group_days_done(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return
    data = await state.get_data()
    selected = sorted(data.get("full_selected_days") or [])
    if not selected:
        await callback.answer(
            _lt("add_group_select_days_alert", lang), show_alert=True
        )
        return
    full_new = dict(data.get("full_new", {}))
    full_new["Dars_Kunlari"] = _format_days_from_indices(selected, "latn")
    await state.update_data(full_new=full_new)
    if callback.message:
        await _advance_full_group_step(callback.message, state, "time", lang, edit=True)
    await callback.answer()


@router.message(FullGroupEditStates.editing_time)
async def msg_full_group_time(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    match = TIME_FORMAT_RE.fullmatch((message.text or "").strip())
    if not match:
        await message.answer(
            t("schedule_invalid_time", lang),
            reply_markup=full_group_edit_step_kb(lang),
            parse_mode="HTML",
        )
        return
    lesson_time = f"{int(match.group(1)):02d}:{match.group(2)}"
    data = await state.get_data()
    full_new = dict(data.get("full_new", {}))
    full_new["Dars_Vaqti"] = lesson_time
    await state.update_data(full_new=full_new)
    await _advance_full_group_step(message, state, "fee", lang, edit=False)


@router.message(FullGroupEditStates.editing_fee)
async def msg_full_group_fee(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    raw_text = (message.text or "").strip().lower()
    for suffix in ("so'm", "so‘m", "som", "sum", "сўм", "uzs"):
        raw_text = raw_text.replace(suffix, "")
    cleaned = re.sub(r"[\s,_]", "", raw_text)
    if not cleaned.isdigit() or int(cleaned) <= 0 or int(cleaned) > 100_000_000:
        await message.answer(
            _lt("edit_invalid_price", lang),
            reply_markup=full_group_edit_step_kb(lang),
            parse_mode="HTML",
        )
        return
    amount = int(cleaned)
    if amount < 10000:
        amount *= 1000
    data = await state.get_data()
    full_new = dict(data.get("full_new", {}))
    full_new["Oylik_Tolov_Summa"] = str(amount)
    await state.update_data(full_new=full_new)
    await _advance_full_group_step(message, state, "chat_id", lang, edit=False)


@router.message(FullGroupEditStates.editing_chat_id)
async def msg_full_group_chat_id(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_lt("no_permission", lang), parse_mode="HTML")
        return
    raw = (message.text or "").strip()
    if not re.fullmatch(r"-?\d{5,20}", raw):
        await message.answer(
            _lt("full_edit_invalid_chat_id", lang),
            reply_markup=full_group_edit_step_kb(lang),
            parse_mode="HTML",
        )
        return
    data = await state.get_data()
    full_new = dict(data.get("full_new", {}))
    full_new["Guruh_TG_Chat_ID"] = raw
    await state.update_data(full_new=full_new)
    await _advance_full_group_step(message, state, "confirm", lang, edit=False)


@router.callback_query(
    FullGroupEditStates.confirm_all, F.data == "full_grp:confirm_all"
)
async def cb_full_group_confirm_all(
    callback: CallbackQuery, state: FSMContext
) -> None:
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_lt("no_permission", lang), show_alert=True)
        return

    data = await state.get_data()
    old_group_name = str(data.get("full_old_group_name") or "").strip()
    orig = dict(data.get("full_orig") or {})
    full_new = dict(data.get("full_new") or {})
    if not old_group_name:
        await state.clear()
        if callback.message:
            await callback.message.edit_text(
                t("error_generic", lang), parse_mode="HTML"
            )
        await callback.answer()
        return

    sheets = get_sheets_manager()
    new_group_name = str(full_new.get("Guruh_Nomi") or old_group_name).strip()

    if full_new:
        ok = await sheets.a_update_group_full_info(old_group_name, full_new)
        if not ok:
            await state.clear()
            if callback.message:
                await callback.message.edit_text(
                    t("error_generic", lang), parse_mode="HTML"
                )
            await callback.answer()
            return
        if new_group_name.lower() != old_group_name.lower():
            await _rename_group_in_sqlite(old_group_name, new_group_name)

    sent_count = 0
    if full_new:
        change_items = [
            (str(k), str(orig.get(k, "")), str(v))
            for k, v in full_new.items()
        ]
        dates_list: Optional[list[str]] = None
        if "Oylik_Dars_Soni" in full_new or "Dars_Kunlari" in full_new:
            cycle_dates = await asyncio.to_thread(
                sheets.get_cycle_dates_with_status, new_group_name
            )
            if cycle_dates:
                dates_list = [d["date_str"] for d in cycle_dates]

        sent_count = await _broadcast_group_update(
            callback.bot,
            sheets,
            new_group_name,
            change_items=change_items,
            dates_list=dates_list,
            triggered_by_user_id=user_id,
        )

    notice = _lt(
        "full_edit_saved_notice",
        lang,
        group=html.escape(new_group_name),
        sent_count=sent_count,
    )
    if callback.message:
        await _show_group_edit_panel(
            callback.message, state, new_group_name, lang, edit=True, notice=notice
        )
    await callback.answer()