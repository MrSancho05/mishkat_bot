import asyncio
import html
import logging
import os
import re
import secrets
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
)

from app import database
from app.config import ADMIN_IDS, DB_PATH, STUDENT_SHEET_NAME, SUPPORT_PHONE
from app.database import (
    add_legacy_debt,
    create_parent_batch_invite,
    delete_legacy_debt,
    get_legacy_debt,
    get_legacy_debts,
    get_user,
    get_user_lang,
    set_legacy_debt_paid,
)
from app.keyboards import (
    balance_inline_markup,
    confirm_delete_student_kb,
    get_main_menu_kb,
    groups_inline_kb,
    parent_batch_more_kb,
    parent_batch_type_kb,
    step_nav_inline_kb,
    student_actions_kb,
    student_add_method_kb,
    student_edit_fields_kb,
    student_root_menu_kb,
    student_transfer_keep_kb,
    students_list_kb,
)
from app.locales import button_texts, format_full_weekdays, t
from app.sheets import (
    COLOR_HEADER_GRAY,
    RESERVE_GROUP_NAME,
    STUDENT_HEADERS,
    _cell_bg_request,
    _col_letter,
    get_sheets_manager,
)
from app.states import LegacyDebtStates, StudentAddStates, StudentManageStates

logger = logging.getLogger(__name__)

router = Router(name="students")

PLACEHOLDER_TEXT = "Ma'lumot kiritilmagan"
NO_PHONE_VALUES = {"", "yo'q", "yoq", "йўқ", PLACEHOLDER_TEXT.lower()}

EXTENDED_STUDENT_COLUMNS = [
    "Otasi_FIO",
    "Otasi_Tel",
    "Otasi_Chat_ID",
    "Onasi_FIO",
    "Onasi_Tel",
    "Onasi_Chat_ID",
]

RESERVE_MENU_TEXTS = button_texts("btn_archive_group")


class _FallbackAttachDeviceStates(StatesGroup):
    entering_phone = State()


ATTACH_DEVICE_PHONE_STATE = getattr(
    StudentManageStates,
    "attaching_device_phone",
    _FallbackAttachDeviceStates.entering_phone,
)

_LOCAL_STU_TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        "root_title": "👥 <b>Talabalar bo‘limi</b>\nKerakli amalni tanlang:",
        "no_groups": "ℹ️ Sizga biriktirilgan guruhlar topilmadi.",
        "no_permission": "❌ Sizda ushbu amalni bajarish huquqi yo‘q.",
        "select_group_add": "➕ Yangi talaba qo‘shiladigan guruhni tanlang:",
        "select_group_manage": "👤 Talabalarni ko‘rish uchun guruhni tanlang:",
        "invite_links_info": (
            "🔗 <b>Taklif havolalari ({group})</b>\n\n"
            "🎓 <b>Talaba o‘zi qo‘shilishi uchun havola:</b>\n"
            "<code>https://t.me/{bot_username}?start=join_{group_slug}</code>\n\n"
            "👨‍👩‍👧 <b>Ota-ona qo‘shilishi uchun:</b>\n"
            "Talaba so‘rovi tasdiqlangach avtomatik shaxsiy <code>?start=par_ID</code> havolasi yaratiladi. "
            "Mavjud talaba uchun esa «👤 Talabalarni boshqarish → 🔗 Taklif havolalari» orqali olishingiz mumkin."
        ),
        "teacher_invite_only_info": (
            "🔗 <b>{group} — Talaba taklif havolasi</b>\n\n"
            "Talaba ushbu havola orqali botga kirib, o‘z F.I.O. va telefon raqamini yuborgach, "
            "sizga tasdiqlash uchun so‘rov yuboriladi:\n\n"
            "<code>https://t.me/{bot_username}?start=join_{group_slug}</code>"
        ),
        "links_card": (
            "🔗 <b>{full_name}</b> (<code>{student_id}</code>) uchun taklif havolalari:\n\n"
            "🎓 Talaba uchun:\n<code>https://t.me/{bot_username}?start=stu_{student_id}</code>\n\n"
            "👨‍👩‍👧 Ota-ona uchun:\n<code>https://t.me/{bot_username}?start=par_{student_id}</code>"
        ),
        "links_card_parent_only": (
            "🔗 <b>{full_name}</b> (<code>{student_id}</code>) uchun taklif havolasi:\n\n"
            "👨‍👩‍👧 Ota-ona uchun:\n<code>https://t.me/{bot_username}?start=par_{student_id}</code>"
        ),
        "no_students_in_group": "ℹ️ <b>{group}</b> guruhida talabalar topilmadi.",
        "select_student": "👤 Talabani tanlang (<b>{group}</b>):",
        "student_card": (
            "👤 <b>Talaba kartasi</b>\n\n"
            "🆔 ID: <code>{student_id}</code>\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📊 Status: <b>{status}</b>\n"
            "📞 Talaba tel: {stu_phone}\n"
            "✈️ Talaba TG: {stu_tg}\n"
            "🧔‍♂️ Otasi: {father_info}\n"
            "🧕 Onasi: {mother_info}\n"
            "⚠️ Qarzdorlik: <b>{debts}</b>"
        ),
        "choose_edit_field": "✏️ Qaysi ma'lumotni o‘zgartirmoqchisiz?",
        "enter_new_value": "📝 <b>{field}</b> uchun yangi qiymatni kiriting:",
        "select_new_group": "📚 Yangi guruhni tanlang:",
        "updated_ok": "✅ Ma'lumot yangilandi!",
        "moved_to_reserve": (
            "🗄 Talaba «Zahira guruhi»ga o‘tkazildi. Barcha ma'lumotlari saqlab qolindi."
        ),
        "moved_to_reserve_detail": (
            "🗄 <b>{full_name}</b> «Zahira guruhi»ga o‘tkazildi.\n"
            "📚 Sobiq guruh: <b>{old_group}</b> (jadvaldan olib tashlandi)\n"
            "📨 Xabar yuborildi: talaba — <b>{stu_sent}</b>, ota-ona — <b>{par_sent}</b>"
        ),
        "reserve_notify_student": (
            "⏸ Hurmatli <b>{talaba_ismi}</b>,\n\n"
            "Siz <b>{guruh_nomi}</b> guruhidagi darslarga qatnashmay qo'yganingiz sababli "
            "vaqtincha o'quv markazimizning «Zaxira ro'yxati»ga o'tkazildingiz.\n\n"
            "📌 Barcha ma'lumotlaringiz tizimda saqlanib qolindi — o'qishni davom ettirishni "
            "istasangiz, xohlagan vaqtingizda mashg'ulotlarga qayta qo'shilishingiz mumkin.\n"
            "📞 Darslarga qaytish yoki savollaringiz bo'yicha ma'muriyatimizga murojaat qiling: "
            "{aloqa_raqami}\n\n"
            "Hurmat bilan,\n"
            "Mishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "reserve_notify_parent": (
            "⏸ Assalomu alaykum, hurmatli <b>{ota_ona_ismi}</b>!\n\n"
            "Farzandingiz <b>{talaba_ismi}</b> <b>{guruh_nomi}</b> guruhidagi darslarga "
            "qatnashmay qo'ygani sababli vaqtincha o'quv markazimizning «Zaxira ro'yxati»ga "
            "o'tkazildi.\n\n"
            "📌 Farzandingizning barcha ma'lumotlari tizimda saqlanib qolindi — o'qishni davom "
            "ettirish istagi bo'lsa, istalgan vaqtda guruhga qayta tiklanishi mumkin.\n"
            "📞 Qo'shimcha ma'lumot olish yoki darslarga qaytish uchun ma'muriyatimiz bilan "
            "bog'laning: {aloqa_raqami}\n\n"
            "Hurmat bilan,\n"
            "Mishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "btn_legacy_add": "➕ Qarz qo‘shish",
        "btn_legacy_list": "📜 Avvalgi qarzlar",
        "legacy_card_line": "📜 Avvalgi qarzlar: <b>{months} oy — {amount} so‘m</b>",
        "legacy_enter_label": (
            "➕ <b>{full_name}</b> uchun <b>avvalgi (tizimdan oldingi) qarz</b> qo‘shish\n\n"
            "1️⃣ Qarzdor bo‘lgan o‘quv oyi / sikl nomini kiriting "
            "(masalan: <code>Sentabr 2026</code> yoki <code>Sentabr–Oktabr 2026</code>):"
        ),
        "legacy_enter_dates": (
            "2️⃣ Ushbu sikldagi dars sanalarini kiriting (vergul bilan), masalan:\n"
            "<code>02.09.2026, 04.09.2026, 06.09.2026</code>\n\n"
            "yoki davr ko‘rinishida: <code>01.09.2026 – 30.09.2026</code>.\n"
            "Sanalar noma'lum bo‘lsa, «⏭ O‘tkazib yuborish» tugmasini bosing."
        ),
        "legacy_enter_months": "3️⃣ Necha oylik qarz? (raqam, masalan: <code>1</code> yoki <code>2</code>):",
        "legacy_enter_amount": (
            "4️⃣ Umumiy qarz summasini kiriting (so‘mda).\n"
            "Guruhning oylik to‘lovi bo‘yicha taklif: <b>{suggested} so‘m</b> — "
            "uni qabul qilish uchun «✅ {suggested}» tugmasini bosing."
        ),
        "legacy_invalid_number": "❌ Iltimos, faqat musbat raqam kiriting.",
        "legacy_confirm": (
            "📋 <b>Avvalgi qarzni tasdiqlang:</b>\n\n"
            "👤 Talaba: <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 Sikl: <b>{label}</b>\n"
            "📅 Dars sanalari: <i>{dates}</i>\n"
            "🔢 Oylar soni: <b>{months}</b>\n"
            "💰 Summa: <b>{amount} so‘m</b>"
        ),
        "legacy_saved": "✅ Avvalgi qarz saqlandi! Endi u barcha qarzdorlik xabarlarida hisobga olinadi.",
        "legacy_list_header": "📜 <b>{full_name}</b> — avvalgi (tizimdan oldingi) qarzlar:",
        "legacy_list_empty": "ℹ️ <b>{full_name}</b> uchun avvalgi qarzlar kiritilmagan.",
        "legacy_list_item": (
            "{idx}. <b>{label}</b> — {months} oy, <b>{amount} so‘m</b> {status}\n"
            "   📅 {dates}"
        ),
        "legacy_status_paid": "✅ to‘langan",
        "legacy_status_unpaid": "❗️ to‘lanmagan",
        "btn_legacy_mark_paid": "✅ #{idx} to‘landi",
        "btn_legacy_mark_unpaid": "↩️ #{idx} qaytarish",
        "btn_legacy_delete": "🗑 #{idx}",
        "btn_legacy_back_card": "⬅️ Talaba kartasiga",
        "legacy_paid_ok": "✅ Avvalgi qarz to‘langan deb belgilandi.",
        "legacy_unpaid_ok": "↩️ Avvalgi qarz yana to‘lanmagan holatga qaytarildi.",
        "legacy_deleted_ok": "🗑 Avvalgi qarz yozuvi o‘chirildi.",
        "legacy_paid_notify": (
            "✅ <b>To‘lov qabul qilindi!</b>\n\n"
            "👤 <b>{full_name}</b> bo‘yicha avvalgi qarz (<b>{label}</b>, {amount} so‘m) "
            "to‘langan deb belgilandi. Rahmat!\n\n"
            "<i>Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!</i>"
        ),
        "confirm_delete": "⚠️ Haqiqatan ham <b>{full_name}</b> (<code>{student_id}</code>) ni bazadan va guruh jadvalidan o‘chirmoqchimisiz?",
        "deleted_ok": "🗑 Talaba (<code>{student_id}</code>) bazadan va guruh jadvalidan o‘chirildi.",
        "deleted_purged": (
            "🗑 Talaba <b>{full_name}</b> (<code>{student_id}</code>) tizimdan to‘liq o‘chirildi.\n"
            "• Baza_Talabalar va barcha guruh jadvallaridan olib tashlandi: <b>{cycle_rows} ta</b> jadval qatori.\n"
            "• Botdagi talaba hisobi: <b>{student_state}</b>.\n"
            "• Farzandi qolmagan ota-onalar botdan to‘liq tozalandi: <b>{parents_purged} ta</b>.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "purge_state_deleted": "to‘liq o‘chirildi",
        "purge_state_updated": "talaba roli olib tashlandi (boshqa rol saqlandi)",
        "purge_state_none": "o‘zgarishsiz",
        "action_cancelled": "❌ Amal bekor qilindi.",
        "none_val": "Kiritilmagan",
        "reserve_header": (
            "🗄 <b>Zaxira guruhi (O‘qimayapti)</b>\n"
            "Jami talabalar: <b>{total} ta</b>\n\n"
            "Guruhga qaytarish uchun talaba tugmasini bosing:"
        ),
        "reserve_empty": "ℹ️ Hozircha 🗄 Zaxira guruhida (O‘qimayapti) talabalar mavjud emas.",
        "reserve_item": (
            "{idx}. <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "   📚 Avvalgi guruh: <b>{group}</b> | ⚠️ Qarz: <b>{debts}</b>\n"
            "   📞 Talaba: {stu_phone} | ✈️ {stu_tg}\n"
            "   🧔‍♂️ Otasi: {father_info}\n"
            "   🧕 Onasi: {mother_info}"
        ),
        "btn_restore_to_group": "♻️ Guruhga qaytarish",
        "restore_select_group": (
            "♻️ <b>{full_name}</b> (<code>{student_id}</code>) ni qaysi guruhga "
            "qaytarmoqchisiz?"
        ),
        "restore_success_admin": (
            "✅ <b>Talaba zaxiradan guruhga qaytarildi!</b>\n\n"
            "👤 Talaba: <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "📚 Yangi guruh: <b>{group}</b>\n"
            "📊 Status: <b>O‘qiyapti 🟢</b>"
        ),
        "restore_notify_student": (
            "▶️ Hurmatli <b>{talaba_ismi}</b>,\n\n"
            "Xushxabar! Siz yana <b>{guruh_nomi}</b> guruhidagi mashg'ulotlarga qayta "
            "tiklandingiz.\n\n"
            "🗓 Dars kunlari: <b>{dars_kunlari}</b>\n"
            "👨‍🏫 Guruh ustozi: <b>{oqituvchi_ismi}</b>\n\n"
            "O'qishlaringizda ulkan muvaffaqiyatlar tilaymiz!\n\n"
            "Hurmat bilan,\n"
            "Mishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "restore_notify_parent": (
            "▶️ Assalomu alaykum, hurmatli <b>{ota_ona_ismi}</b>!\n\n"
            "Xushxabar! Farzandingiz <b>{talaba_ismi}</b> yana <b>{guruh_nomi}</b> "
            "guruhidagi mashg'ulotlarga qayta tiklandi.\n\n"
            "🗓 Dars kunlari: <b>{dars_kunlari}</b>\n"
            "👨‍🏫 Guruh ustozi: <b>{oqituvchi_ismi}</b>\n\n"
            "Farzandingizga o'qishlarida ulkan muvaffaqiyatlar tilaymiz!\n\n"
            "Hurmat bilan,\n"
            "Mishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "restore_notify_teacher": (
            "♻️ <b>Guruhingizga talaba tiklandi</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "👤 Talaba: <b>{full_name}</b> (<code>{student_id}</code>)"
        ),
        "pb_choose_parent_type": (
            "👨‍👩‍👧‍👦 <b>Ota-ona orqali farzand(lar) qo‘shish (1/5)</b>\n\n"
            "Ma'lumotlari kiritiladigan ota-onani tanlang:"
        ),
        "pb_enter_parent_name": (
            "👨‍👩‍👧‍👦 <b>{parent_label}ning F.I.O. si (2/5)</b>\n\n"
            "<b>{parent_label}</b>ning <b>F.I.O.</b> sini kiriting (masalan: <i>Aliyev Olim</i>):"
        ),
        "pb_invalid_name": "❌ Iltimos, F.I.O. ni to‘g‘ri kiriting:",
        "pb_enter_parent_phone": (
            "📱 <b>{parent_label} telefon raqami (3/5)</b>\n\n"
            "{parent_label}: <b>{parent_name}</b>\n"
            "Telefon raqamini kiriting (masalan: <code>+998901234567</code>):"
        ),
        "pb_invalid_phone": "❌ Noto‘g‘ri telefon raqami. Qaytadan kiriting:",
        "pb_enter_child_name": (
            "👶 <b>{num}-farzand ma'lumoti (4/5)</b>\n\n"
            "Farzandning <b>F.I.O.</b> sini kiriting:"
        ),
        "pb_select_child_group": (
            "📚 <b>{child_name}</b> qaysi guruhga qo‘shilsin?"
        ),
        "pb_added_list": (
            "👨‍👩‍👧‍👦 <b>{parent_label}:</b> {parent_name} ({parent_phone})\n\n"
            "<b>Qo‘shiladigan farzandlar ro‘yxati:</b>\n{children_lines}\n\n"
            "Yana farzand qo‘shasizmi yoki yakunlaysizmi?"
        ),
        "pb_finished": (
            "✅ <b>Barcha farzandlar muvaffaqiyatli qo‘shildi!</b>\n\n"
            "👨‍👩‍👧‍👦 {parent_label}: <b>{parent_name}</b> ({parent_phone})\n\n"
            "<b>Qo‘shilgan farzandlar:</b>\n{children_lines}\n\n"
            "🔗 <b>Ota-ona uchun yagona taklif havolasi:</b>\n"
            "<code>https://t.me/{bot_username}?start=parbatch_{invite_code}</code>\n\n"
            "<i>Ota-ona ushbu bitta havola orqali kirib barcha farzandlariga avtomatik ulanadi!</i>"
        ),
        "pb_single_direct_link": (
            "\n\n🔗 <b>Shaxsiy ota-ona havolasi:</b>\n"
            "<code>https://t.me/{bot_username}?start=par_{student_id}</code>"
        ),
        "attach_device_prompt": (
            "📱 <b>Talabaga qurilma/havola biriktirish</b>\n\n"
            "👤 Talaba: <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "📚 Guruh: <b>{group}</b>\n\n"
            "Talabaning yangi telefon raqamini kiriting (masalan: <code>+998901234567</code>) "
            "yoki pastdagi «Raqamsiz havola berish» tugmasini bosing:"
        ),
        "attach_device_invalid_phone": (
            "❌ Noto‘g‘ri telefon raqami. Masalan: <code>+998901234567</code> ko‘rinishida kiriting "
            "yoki «Raqamsiz havola berish» tugmasini bosing:"
        ),
        "btn_attach_skip_phone": "📵 Raqamsiz havola",
        "attach_device_ready": (
            "✅ <b>Talaba uchun ulanish havolasi tayyor!</b>\n\n"
            "👤 Talaba: <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "📞 Telefon: <b>{phone}</b>\n\n"
            "🔗 <a href=\"https://t.me/{bot_username}?start=stu_{student_id}\">Talabani ulash havolasi</a>\n"
            "<code>https://t.me/{bot_username}?start=stu_{student_id}</code>\n\n"
            "<i>Ushbu havolani talabaga yuboring. Talaba havolani ochganda uning Telegram "
            "hisobi mavjud kartasiga avtomatik biriktiriladi!</i>"
        ),
    },
    "cyrl": {
        "root_title": "👥 <b>Талабалар бўлими</b>\nКеракли амални танланг:",
        "no_groups": "ℹ️ Сизга бириктирилган гуруҳлар топилмади.",
        "no_permission": "❌ Сизда ушбу амални бажариш ҳуқуқи йўқ.",
        "select_group_add": "➕ Янги талаба қўшиладиган гуруҳни танланг:",
        "select_group_manage": "👤 Талабаларни кўриш учун гуруҳни танланг:",
        "invite_links_info": (
            "🔗 <b>Таклиф ҳаволалари ({group})</b>\n\n"
            "🎓 <b>Талаба ўзи қўшилиши учун ҳавола:</b>\n"
            "<code>https://t.me/{bot_username}?start=join_{group_slug}</code>\n\n"
            "👨‍👩‍👧 <b>Ота-она қўшилиши учун:</b>\n"
            "Талаба сўрови тасдиқлангач автоматик шахсий <code>?start=par_ID</code> ҳаволаси яратилади. "
            "Мавжуд талаба учун эса «👤 Талабаларни бошқариш → 🔗 Таклиф ҳаволалари» орқали олишингиз мумкин."
        ),
        "teacher_invite_only_info": (
            "🔗 <b>{group} — Талаба таклиф ҳаволаси</b>\n\n"
            "Талаба ушбу ҳавола орқали ботга кириб, ўз Ф.И.О. ва телефон рақамини юборгач, "
            "сизга тасдиқлаш учун сўров юборилади:\n\n"
            "<code>https://t.me/{bot_username}?start=join_{group_slug}</code>"
        ),
        "links_card": (
            "🔗 <b>{full_name}</b> (<code>{student_id}</code>) учун таклиф ҳаволалари:\n\n"
            "🎓 Талаба учун:\n<code>https://t.me/{bot_username}?start=stu_{student_id}</code>\n\n"
            "👨‍👩‍👧 Ота-она учун:\n<code>https://t.me/{bot_username}?start=par_{student_id}</code>"
        ),
        "links_card_parent_only": (
            "🔗 <b>{full_name}</b> (<code>{student_id}</code>) учун таклиф ҳаволаси:\n\n"
            "👨‍👩‍👧 Ота-она учун:\n<code>https://t.me/{bot_username}?start=par_{student_id}</code>"
        ),
        "no_students_in_group": "ℹ️ <b>{group}</b> гуруҳида талабалар топилмади.",
        "select_student": "👤 Талабани танланг (<b>{group}</b>):",
        "student_card": (
            "👤 <b>Талаба картаси</b>\n\n"
            "🆔 ID: <code>{student_id}</code>\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📊 Статус: <b>{status}</b>\n"
            "📞 Талаба тел: {stu_phone}\n"
            "✈️ Талаба ТГ: {stu_tg}\n"
            "🧔‍♂️ Отаси: {father_info}\n"
            "🧕 Онаси: {mother_info}\n"
            "⚠️ Қарздорлик: <b>{debts}</b>"
        ),
        "choose_edit_field": "✏️ Қайси маълумотни ўзгартирмоқчисиз?",
        "enter_new_value": "📝 <b>{field}</b> учун янги қийматни киритинг:",
        "select_new_group": "📚 Янги гуруҳни танланг:",
        "updated_ok": "✅ Маълумот янгиланди!",
        "moved_to_reserve": (
            "🗄 Талаба «Захира гуруҳи»га ўтказилди. Барча маълумотлари сақлаб қолинди."
        ),
        "moved_to_reserve_detail": (
            "🗄 <b>{full_name}</b> «Захира гуруҳи»га ўтказилди.\n"
            "📚 Собиқ гуруҳ: <b>{old_group}</b> (жадвалдан олиб ташланди)\n"
            "📨 Хабар юборилди: талаба — <b>{stu_sent}</b>, ота-она — <b>{par_sent}</b>"
        ),
        "reserve_notify_student": (
            "⏸ Ҳурматли <b>{talaba_ismi}</b>,\n\n"
            "Сиз <b>{guruh_nomi}</b> гуруҳидаги дарсларга қатнашмай қўйганингиз сабабли "
            "вақтинча ўқув марказимизнинг «Захира рўйхати»га ўтказилдингиз.\n\n"
            "📌 Барча маълумотларингиз тизимда сақланиб қолинди — ўқишни давом эттиришни "
            "истасангиз, хоҳлаган вақтингизда машғулотларга қайта қўшилишингиз мумкин.\n"
            "📞 Дарсларга қайтиш ёки саволларингиз бўйича маъмуриятимизга мурожаат қилинг: "
            "{aloqa_raqami}\n\n"
            "Ҳурмат билан,\n"
            "Мишкат Нодавлат Таълим Муассасаси!"
        ),
        "reserve_notify_parent": (
            "⏸ Ассалому алайкум, ҳурматли <b>{ota_ona_ismi}</b>!\n\n"
            "Фарзандингиз <b>{talaba_ismi}</b> <b>{guruh_nomi}</b> гуруҳидаги дарсларга "
            "қатнашмай қўйгани сабабли вақтинча ўқув марказимизнинг «Захира рўйхати»га "
            "ўтказилди.\n\n"
            "📌 Фарзандингизнинг барча маълумотлари тизимда сақланиб қолинди — ўқишни давом "
            "эттириш истаги бўлса, исталган вақтда гуруҳга қайта тикланиши мумкин.\n"
            "📞 Қўшимча маълумот олиш ёки дарсларга қайтиш учун маъмуриятимизга мурожаат "
            "қилинг: {aloqa_raqami}\n\n"
            "Ҳурмат билан,\n"
            "Мишкат Нодавлат Таълим Муассасаси!"
        ),
        "btn_legacy_add": "➕ Қарз қўшиш",
        "btn_legacy_list": "📜 Аввалги қарзлар",
        "legacy_card_line": "📜 Аввалги қарзлар: <b>{months} ой — {amount} сўм</b>",
        "legacy_enter_label": (
            "➕ <b>{full_name}</b> учун <b>аввалги (тизимдан олдинги) қарз</b> қўшиш\n\n"
            "1️⃣ Қарздор бўлган ўқув ойи / цикл номини киритинг "
            "(масалан: <code>Сентябрь 2026</code>):"
        ),
        "legacy_enter_dates": (
            "2️⃣ Ушбу циклдаги дарс саналарини киритинг (вергул билан), масалан:\n"
            "<code>02.09.2026, 04.09.2026, 06.09.2026</code>\n\n"
            "ёки давр кўринишида: <code>01.09.2026 – 30.09.2026</code>.\n"
            "Саналар номаълум бўлса, «⏭ Ўтказиб юбориш» тугмасини босинг."
        ),
        "legacy_enter_months": "3️⃣ Неча ойлик қарз? (рақам, масалан: <code>1</code> ёки <code>2</code>):",
        "legacy_enter_amount": (
            "4️⃣ Умумий қарз суммасини киритинг (сўмда).\n"
            "Гуруҳнинг ойлик тўлови бўйича таклиф: <b>{suggested} сўм</b> — "
            "уни қабул қилиш учун «✅ {suggested}» тугмасини босинг."
        ),
        "legacy_invalid_number": "❌ Илтимос, фақат мусбат рақам киритинг.",
        "legacy_confirm": (
            "📋 <b>Аввалги қарзни тасдиқланг:</b>\n\n"
            "👤 Талаба: <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Цикл: <b>{label}</b>\n"
            "📅 Дарс саналари: <i>{dates}</i>\n"
            "🔢 Ойлар сони: <b>{months}</b>\n"
            "💰 Сумма: <b>{amount} сўм</b>"
        ),
        "legacy_saved": "✅ Аввалги қарз сақланди! Энди у барча қарздорлик хабарларида ҳисобга олинади.",
        "legacy_list_header": "📜 <b>{full_name}</b> — аввалги (тизимдан олдинги) қарзлар:",
        "legacy_list_empty": "ℹ️ <b>{full_name}</b> учун аввалги қарзлар киритилмаган.",
        "legacy_list_item": (
            "{idx}. <b>{label}</b> — {months} ой, <b>{amount} сўм</b> {status}\n"
            "   📅 {dates}"
        ),
        "legacy_status_paid": "✅ тўланган",
        "legacy_status_unpaid": "❗️ тўланмаган",
        "btn_legacy_mark_paid": "✅ #{idx} тўланди",
        "btn_legacy_mark_unpaid": "↩️ #{idx} қайтариш",
        "btn_legacy_delete": "🗑 #{idx}",
        "btn_legacy_back_card": "⬅️ Талаба картасига",
        "legacy_paid_ok": "✅ Аввалги қарз тўланган деб белгиланди.",
        "legacy_unpaid_ok": "↩️ Аввалги қарз яна тўланмаган ҳолатга қайтарилди.",
        "legacy_deleted_ok": "🗑 Аввалги қарз ёзуви ўчирилди.",
        "legacy_paid_notify": (
            "✅ <b>Тўлов қабул қилинди!</b>\n\n"
            "👤 <b>{full_name}</b> бўйича аввалги қарз (<b>{label}</b>, {amount} сўм) "
            "тўланган деб белгиланди. Раҳмат!\n\n"
            "<i>Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!</i>"
        ),
        "confirm_delete": "⚠️ Ҳақиқатан ҳам <b>{full_name}</b> (<code>{student_id}</code>) ни базадан ва гуруҳ жадвалидан ўчирмоқчимисиз?",
        "deleted_ok": "🗑 Талаба (<code>{student_id}</code>) базадан ва гуруҳ жадвалидан ўчирилди.",
        "deleted_purged": (
            "🗑 Талаба <b>{full_name}</b> (<code>{student_id}</code>) тизимдан тўлиқ ўчирилди.\n"
            "• Baza_Talabalar ва барча гуруҳ жадвалларидан олиб ташланди: <b>{cycle_rows} та</b> жадвал қатори.\n"
            "• Ботдаги талаба ҳисоби: <b>{student_state}</b>.\n"
            "• Фарзанди қолмаган ота-оналар ботдан тўлиқ тозаланди: <b>{parents_purged} та</b>.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "purge_state_deleted": "тўлиқ ўчирилди",
        "purge_state_updated": "талаба роли олиб ташланди (бошқа рол сақланди)",
        "purge_state_none": "ўзгаришсиз",
        "action_cancelled": "❌ Амал бекор қилинди.",
        "none_val": "Киритилмаган",
        "reserve_header": (
            "🗄 <b>Захира гуруҳи (Ўқимаяпти)</b>\n"
            "Жами талабалар: <b>{total} та</b>\n\n"
            "Гуруҳга қайтариш учун талаба тугмасини босинг:"
        ),
        "reserve_empty": "ℹ️ Ҳозирча 🗄 Захира гуруҳида (Ўқимаяпти) талабалар мавжуд эмас.",
        "reserve_item": (
            "{idx}. <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "   📚 Аввалги гуруҳ: <b>{group}</b> | ⚠️ Қарз: <b>{debts}</b>\n"
            "   📞 Талаба: {stu_phone} | ✈️ {stu_tg}\n"
            "   🧔‍♂️ Отаси: {father_info}\n"
            "   🧕 Онаси: {mother_info}"
        ),
        "btn_restore_to_group": "♻️ Гуруҳга қайтариш",
        "restore_select_group": (
            "♻️ <b>{full_name}</b> (<code>{student_id}</code>) ни қайси гуруҳга "
            "қайтармоқчисиз?"
        ),
        "restore_success_admin": (
            "✅ <b>Талаба захирадан гуруҳга қайтарилди!</b>\n\n"
            "👤 Талаба: <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "📚 Янги гуруҳ: <b>{group}</b>\n"
            "📊 Статус: <b>Ўқияпти 🟢</b>"
        ),
        "restore_notify_student": (
            "▶️ Ҳурматли <b>{talaba_ismi}</b>,\n\n"
            "Хушхабар! Сиз яна <b>{guruh_nomi}</b> гуруҳидаги машғулотларга қайта "
            "тикландингиз.\n\n"
            "🗓 Дарс кунлари: <b>{dars_kunlari}</b>\n"
            "👨‍🏫 Гуруҳ устози: <b>{oqituvchi_ismi}</b>\n\n"
            "Ўқишларингизда улкан муваффақиятлар тилаймиз!\n\n"
            "Ҳурмат билан,\n"
            "Мишкат Нодавлат Таълим Муассасаси!"
        ),
        "restore_notify_parent": (
            "▶️ Ассалому алайкум, ҳурматли <b>{ota_ona_ismi}</b>!\n\n"
            "Хушхабар! Фарзандингиз <b>{talaba_ismi}</b> яна <b>{guruh_nomi}</b> "
            "гуруҳидаги машғулотларга қайта тикланди.\n\n"
            "🗓 Дарс кунлари: <b>{dars_kunlari}</b>\n"
            "👨‍🏫 Гуруҳ устози: <b>{oqituvchi_ismi}</b>\n\n"
            "Фарзандингизга ўқишларида улкан муваффақиятлар тилаймиз!\n\n"
            "Ҳурмат билан,\n"
            "Мишкат Нодавлат Таълим Муассасаси!"
        ),
        "restore_notify_teacher": (
            "♻️ <b>Гуруҳингизга талаба тикланди</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "👤 Талаба: <b>{full_name}</b> (<code>{student_id}</code>)"
        ),
        "pb_choose_parent_type": (
            "👨‍👩‍👧‍👦 <b>Ота-она орқали фарзанд(лар) қўшиш (1/5)</b>\n\n"
            "Маълумотлари киритиладиган ота-онани танланг:"
        ),
        "pb_enter_parent_name": (
            "👨‍👩‍👧‍👦 <b>{parent_label}нинг Ф.И.О. си (2/5)</b>\n\n"
            "<b>{parent_label}</b>нинг <b>Ф.И.О.</b> сини киритинг (масалан: <i>Алиев Олим</i>):"
        ),
        "pb_invalid_name": "❌ Илтимос, Ф.И.О. ни тўғри киритинг:",
        "pb_enter_parent_phone": (
            "📱 <b>{parent_label} телефон рақами (3/5)</b>\n\n"
            "{parent_label}: <b>{parent_name}</b>\n"
            "Телефон рақамини киритинг (масалан: <code>+998901234567</code>):"
        ),
        "pb_invalid_phone": "❌ Нотўғри телефон рақами. Қайтадан киритинг:",
        "pb_enter_child_name": (
            "👶 <b>{num}-фарзанд маълумоти (4/5)</b>\n\n"
            "Фарзанднинг <b>Ф.И.О.</b> сини киритинг:"
        ),
        "pb_select_child_group": (
            "📚 <b>{child_name}</b> қайси гуруҳга қўшилсин?"
        ),
        "pb_added_list": (
            "👨‍👩‍👧‍👦 <b>{parent_label}:</b> {parent_name} ({parent_phone})\n\n"
            "<b>Қўшиладиган фарзандлар рўйхати:</b>\n{children_lines}\n\n"
            "Яна фарзанд қўшасизми ёки якунлайсизми?"
        ),
        "pb_finished": (
            "✅ <b>Барча фарзандлар муваффақиятли қўшилди!</b>\n\n"
            "👨‍👩‍👧‍👦 {parent_label}: <b>{parent_name}</b> ({parent_phone})\n\n"
            "<b>Қўшилган фарзандлар:</b>\n{children_lines}\n\n"
            "🔗 <b>Ота-она учун ягона таклиф ҳаволаси:</b>\n"
            "<code>https://t.me/{bot_username}?start=parbatch_{invite_code}</code>\n\n"
            "<i>Ота-она ушбу битта ҳавола орқали кириб барча фарзандларига автоматик уланади!</i>"
        ),
        "pb_single_direct_link": (
            "\n\n🔗 <b>Шахсий ота-она ҳаволаси:</b>\n"
            "<code>https://t.me/{bot_username}?start=par_{student_id}</code>"
        ),
        "attach_device_prompt": (
            "📱 <b>Талабага қурилма/ҳавола бириктириш</b>\n\n"
            "👤 Талаба: <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "📚 Гуруҳ: <b>{group}</b>\n\n"
            "Талабанинг янги телефон рақамини киритинг (масалан: <code>+998901234567</code>) "
            "ёки пастдаги «Рақамсиз ҳавола бериш» тугмасини босинг:"
        ),
        "attach_device_invalid_phone": (
            "❌ Нотўғри телефон рақами. Масалан: <code>+998901234567</code> кўринишида киритинг "
            "ёки «Рақамсиз ҳавола бериш» тугмасини босинг:"
        ),
        "btn_attach_skip_phone": "📵 Рақамсиз ҳавола",
        "attach_device_ready": (
            "✅ <b>Талаба учун уланиш ҳаволаси тайёр!</b>\n\n"
            "👤 Талаба: <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "📞 Телефон: <b>{phone}</b>\n\n"
            "🔗 <a href=\"https://t.me/{bot_username}?start=stu_{student_id}\">Талабани улаш ҳаволаси</a>\n"
            "<code>https://t.me/{bot_username}?start=stu_{student_id}</code>\n\n"
            "<i>Ушбу ҳаволани талабага юборинг. Талаба ҳаволани очганда унинг Telegram "
            "ҳисоби мавжуд картасига автоматик бириктирилади!</i>"
        ),
    },
}


def _st(key: str, lang: str, **kwargs: Any) -> str:
    safe = lang if lang in _LOCAL_STU_TEXTS else "latn"
    txt = _LOCAL_STU_TEXTS[safe][key]
    return txt.format(**kwargs) if kwargs else txt


def _pb_parent_type(data: dict[str, Any]) -> str:
    """'father' / 'mother' chosen by the admin for a phone-less student's parent."""
    return "mother" if str(data.get("batch_parent_type") or "") == "mother" else "father"


def _pb_parent_label(data: dict[str, Any], lang: str) -> str:
    key = "parent_label_mother" if _pb_parent_type(data) == "mother" else "parent_label_father"
    return t(key, lang)


def _slugify_group_name(group_name: str) -> str:
    return (
        re.sub(r"[^A-Za-z0-9_-]+", "_", group_name.strip()).strip("_")[:55]
        or "group"
    )


def _student_has_device(student: dict[str, Any]) -> bool:
    chat_id = str(student.get("Talaba_Chat_ID") or "").strip()
    return bool(chat_id and chat_id != PLACEHOLDER_TEXT)


def _normalize_phone_input(raw_phone: str) -> Optional[str]:
    digits = re.sub(r"[^\d]", "", (raw_phone or "").strip())
    if len(digits) < 7 or len(digits) > 15:
        return None
    compact = re.sub(r"[^\d+]", "", raw_phone.strip())
    if re.fullmatch(r"\d{9}", compact):
        compact = f"+998{compact}"
    elif re.fullmatch(r"998\d{9}", compact):
        compact = f"+{compact}"
    elif not compact.startswith("+"):
        compact = f"+{compact}"
    return compact


def _attach_device_kb(student_id: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_st("btn_attach_skip_phone", lang),
                    callback_data=f"attach_stu_skip:{student_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_back", lang),
                    callback_data=f"attach_stu_back:{student_id}",
                ),
                InlineKeyboardButton(
                    text=t("btn_cancel", lang),
                    callback_data="stu_act:cancel",
                ),
            ],
        ]
    )


def _format_clickable_phone(raw_phone: str, fallback: str) -> str:
    cleaned = str(raw_phone or "").strip()
    if not cleaned or cleaned == PLACEHOLDER_TEXT:
        return html.escape(fallback)
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
    fallback: str,
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
    return html.escape(fallback)


def _format_parent_contact_info(
    fio: str,
    phone: str,
    chat_id: str,
    none_val: str,
    lang: str,
    viewer_user_id: Optional[int] = None,
) -> str:
    clean_fio = fio.strip() if fio and fio.strip() != PLACEHOLDER_TEXT else ""
    clean_phone = phone.strip() if phone and phone.strip() != PLACEHOLDER_TEXT else ""
    clean_cid = chat_id.strip()

    parts: list[str] = []
    if clean_fio:
        name_html = f"<b>{html.escape(clean_fio)}</b>"
        if viewer_user_id is not None and clean_cid == str(viewer_user_id):
            name_html = f"{name_html} {t('self_marker', lang)}"
        parts.append(name_html)

    if clean_phone:
        parts.append(_format_clickable_phone(clean_phone, none_val))
    elif not clean_fio and not clean_cid.isdigit():
        parts.append(html.escape(none_val))

    if clean_cid.isdigit():
        parts.append(_format_clickable_tg("", none_val, chat_id=clean_cid))
        if not clean_fio and viewer_user_id is not None and clean_cid == str(viewer_user_id):
            parts.append(t("self_marker", lang))

    return " | ".join(parts) if parts else html.escape(none_val)


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


async def _get_role_and_groups(
    user_id: int, include_unlisted_student_groups: bool = False
) -> tuple[str | None, list[dict]]:
    sheets = get_sheets_manager()
    if await _is_admin(user_id):
        if hasattr(sheets, "a_get_groups_for_role"):
            groups = await sheets.a_get_groups_for_role(user_id, is_admin=True)
        else:
            groups = await asyncio.to_thread(sheets.get_all_groups)

        if include_unlisted_student_groups:
            seen_lower = {
                str(g.get("Guruh_Nomi") or "").strip().lower()
                for g in groups
                if str(g.get("Guruh_Nomi") or "").strip()
            }
            all_students = await sheets.a_get_all_students()
            for stu in all_students:
                stu_grp = str(stu.get("Guruh") or "").strip()
                if (
                    stu_grp
                    and not stu_grp.lower().startswith("zaxira")
                    and stu_grp.lower() not in seen_lower
                ):
                    seen_lower.add(stu_grp.lower())
                    groups.append({"Guruh_Nomi": stu_grp})
        return "admin", groups

    raw_groups = await asyncio.to_thread(sheets.get_teacher_groups, user_id)
    t_groups = [
        g
        for g in raw_groups
        if str(g.get("Ustoz_Chat_ID") or "").strip() == str(user_id)
    ]
    if t_groups:
        return "teacher", t_groups
    return None, []


async def _can_manage_student_device(user_id: int, student: dict[str, Any]) -> bool:
    if await _is_admin(user_id):
        return True
    stu_group = str(student.get("Guruh") or "").strip().lower()
    if not stu_group:
        return False
    role, t_groups = await _get_role_and_groups(user_id)
    if role == "teacher":
        return any(
            str(g.get("Guruh_Nomi") or "").strip().lower() == stu_group
            for g in t_groups
        )
    return False


def _ensure_extended_student_headers_sync() -> None:
    sheets = get_sheets_manager()
    with sheets._lock:
        ws = sheets._get_or_create_worksheet(
            STUDENT_SHEET_NAME, headers=STUDENT_HEADERS, rows=500, cols=18
        )
        headers = ws.row_values(1) or list(STUDENT_HEADERS)
        missing = [c for c in EXTENDED_STUDENT_COLUMNS if c not in headers]
        if missing:
            if ws.col_count < len(headers) + len(missing):
                ws.resize(cols=len(headers) + len(missing))
            start_col = len(headers)
            ws.update(
                f"{_col_letter(start_col)}1",
                [missing],
                value_input_option="USER_ENTERED",
            )
            sheets._get_spreadsheet().batch_update(
                {
                    "requests": [
                        _cell_bg_request(
                            ws.id,
                            0,
                            1,
                            start_col,
                            start_col + len(missing),
                            COLOR_HEADER_GRAY,
                            bold=True,
                        )
                    ]
                }
            )


async def _attach_student_device_safe(
    student_id: str, new_phone: Optional[str]
) -> Optional[dict[str, Any]]:
    sheets = get_sheets_manager()
    if hasattr(sheets, "a_attach_student_device_info"):
        return await sheets.a_attach_student_device_info(
            student_id=student_id, new_phone=new_phone
        )
    if hasattr(sheets, "attach_student_device_info"):
        return await asyncio.to_thread(
            sheets.attach_student_device_info, student_id, new_phone
        )
    if new_phone:
        await asyncio.to_thread(
            sheets.update_student, student_id, {"Talaba_Tel": new_phone}
        )
    return await sheets.a_get_student_by_id(student_id)


async def _cleanup_deleted_student_sqlite(
    student_id: str, deleted_student: Optional[dict[str, Any]] = None
) -> None:
    sheets = get_sheets_manager()
    clean_sid = student_id.strip()

    stu_cid_str = (
        str(deleted_student.get("Talaba_Chat_ID") or "").strip()
        if deleted_student
        else ""
    )
    parent_cids: list[str] = []
    if deleted_student:
        for col in ("Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
            val = str(deleted_student.get(col) or "").strip()
            if val and val not in parent_cids:
                parent_cids.append(val)

    async with aiosqlite.connect(DB_PATH) as db:
        if stu_cid_str.isdigit():
            remaining = await sheets.a_get_students_by_chat_id(stu_cid_str)
            if remaining:
                next_sid = remaining[0]["Talaba_ID"]
                await db.execute(
                    "UPDATE users SET role = 'student', linked_student_id = ? "
                    "WHERE telegram_id = ? AND (linked_student_id = ? OR linked_student_id IS NULL);",
                    (next_sid, int(stu_cid_str), clean_sid),
                )
            else:
                await db.execute(
                    "UPDATE users SET role = NULL, linked_student_id = NULL "
                    "WHERE telegram_id = ? AND role = 'student';",
                    (int(stu_cid_str),),
                )

        for p_cid in parent_cids:
            if not p_cid.isdigit():
                continue
            remaining_children = await sheets.a_get_children_by_parent_chat_id(
                p_cid
            )
            if remaining_children:
                next_sid = remaining_children[0]["Talaba_ID"]
                await db.execute(
                    "UPDATE users SET role = 'parent', linked_student_id = ? "
                    "WHERE telegram_id = ? AND linked_student_id = ?;",
                    (next_sid, int(p_cid), clean_sid),
                )
            else:
                await db.execute(
                    "UPDATE users SET role = NULL, linked_student_id = NULL "
                    "WHERE telegram_id = ? AND role = 'parent';",
                    (int(p_cid),),
                )

        await db.execute(
            "UPDATE users SET role = NULL, linked_student_id = NULL WHERE linked_student_id = ?;",
            (clean_sid,),
        )
        try:
            await db.execute(
                "DELETE FROM parent_meta WHERE student_id = ?;",
                (clean_sid,),
            )
        except Exception:
            pass
        await db.commit()


def _format_legacy_card_line(
    legacy_rows: Optional[list[dict[str, Any]]], lang: str
) -> str:
    rows = [r for r in (legacy_rows or []) if not int(r.get("is_paid") or 0)]
    if not rows:
        return ""
    months = sum(max(1, int(r.get("months") or 1)) for r in rows)
    amount = sum(max(0, int(r.get("amount") or 0)) for r in rows)
    return _st(
        "legacy_card_line",
        lang,
        months=months,
        amount=f"{amount:,}".replace(",", " "),
    )


def _norm_cid(raw: Any) -> Optional[int]:
    val = str(raw or "").strip()
    if re.fullmatch(r"-?\d+(?:\.0+)?", val):
        num = int(val.split(".", 1)[0])
        return num if num != 0 else None
    return None


def _phone_key(raw: Any) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) < 7:
        return ""
    if len(digits) == 9:
        return f"998{digits}"
    return digits


_PARENT_NOTICE_COLUMNS = (
    ("Otasi_Chat_ID", "Otasi_Tel", "Otasi_FIO", "parent_label_father"),
    ("Onasi_Chat_ID", "Onasi_Tel", "Onasi_FIO", "parent_label_mother"),
    ("OtaOna_Chat_ID", "OtaOna_Tel", "Otasi_FIO", "role_parent"),
)


def _clean_sheet_name(raw: Any) -> str:
    val = str(raw or "").strip()
    return "" if val == PLACEHOLDER_TEXT else val


async def _collect_parent_notice_targets(
    student: dict[str, Any],
) -> list[tuple[int, str, str]]:
    """
    Parent recipients of a student's notices as (chat_id, sheet_name, label_key).
    Each chat is addressed by ITS OWN name: Otasi_FIO for the father's chat,
    Onasi_FIO for the mother's chat. Sibling rows that share the same parent phone
    contribute the parent chat bound there. Student chat ids are never included.
    """
    targets: dict[int, tuple[str, str]] = {}

    def _add_row(row: dict[str, Any], only_phones: Optional[set[str]] = None) -> None:
        for cid_col, tel_col, name_col, label_key in _PARENT_NOTICE_COLUMNS:
            p_cid = _norm_cid(row.get(cid_col))
            if p_cid is None or p_cid in targets:
                continue
            if only_phones is not None and _phone_key(row.get(tel_col)) not in only_phones:
                continue
            name = _clean_sheet_name(row.get(name_col))
            if not name and cid_col == "OtaOna_Chat_ID":
                name = _clean_sheet_name(row.get("Onasi_FIO"))
            targets[p_cid] = (name, label_key)

    _add_row(student)
    src_phones = {
        _phone_key(student.get(col)) for col in ("Otasi_Tel", "Onasi_Tel", "OtaOna_Tel")
    } - {""}
    if src_phones:
        try:
            for row in await get_sheets_manager().a_get_all_students():
                row_phones = {
                    _phone_key(row.get(col))
                    for col in ("Otasi_Tel", "Onasi_Tel", "OtaOna_Tel")
                } - {""}
                if src_phones & row_phones:
                    _add_row(row, only_phones=src_phones)
        except Exception:
            logger.exception("Failed resolving sibling parent chat ids for notice")
    return [(cid, name, key) for cid, (name, key) in targets.items()]


def _center_phone_html() -> str:
    return _format_clickable_phone(SUPPORT_PHONE, "—")


async def _group_teacher_name(sheets: Any, group: Optional[dict[str, Any]]) -> str:
    """Official name of the group's teacher ('—' when it cannot be resolved)."""
    if not group:
        return "—"
    teacher: Optional[dict[str, Any]] = None
    try:
        t_id = str(group.get("Ustoz_ID") or "").strip()
        if t_id:
            teacher = await sheets.a_get_teacher_by_id(t_id)
        if not teacher:
            t_cid = str(group.get("Ustoz_Chat_ID") or "").strip()
            if t_cid:
                teacher = await sheets.a_get_teacher_by_chat_id(t_cid)
    except Exception:
        logger.exception("Failed resolving group teacher name")
    name = str((teacher or {}).get("F.I.O.") or "").strip()
    return name or "—"


async def _notify_reserve_move(
    bot: Any,
    student: dict[str, Any],
    old_group: str,
    actor_user_id: int,
) -> tuple[int, int]:
    """
    Zaxira notice (student stopped attending). Strict role routing:
    * the student-addressed text goes ONLY to the student's own Talaba_Chat_ID;
    * every parent chat receives ONLY the parent-addressed text, greeted by that
      parent's own name (Otasi_FIO / Onasi_FIO).
    Returns (student_sent, parents_sent).
    """
    full_name = str(student.get("F.I.O.") or student.get("Talaba_ID") or "").strip()
    stu_cid = _norm_cid(student.get("Talaba_Chat_ID"))
    parent_targets = await _collect_parent_notice_targets(student)

    stu_sent = 0
    par_sent = 0
    if stu_cid is not None:
        try:
            s_lang = await database.get_user_lang(stu_cid)
            await bot.send_message(
                chat_id=stu_cid,
                text=_st(
                    "reserve_notify_student",
                    s_lang,
                    talaba_ismi=html.escape(full_name),
                    guruh_nomi=html.escape(old_group),
                    aloqa_raqami=_center_phone_html(),
                ),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            stu_sent += 1
        except Exception as exc:
            logger.warning(
                "Reserve notice to student chat_id=%s failed: %s", stu_cid, exc
            )
    for p_cid, p_name, label_key in parent_targets:
        if p_cid == stu_cid:
            continue
        try:
            p_lang = await database.get_user_lang(p_cid)
            await bot.send_message(
                chat_id=p_cid,
                text=_st(
                    "reserve_notify_parent",
                    p_lang,
                    ota_ona_ismi=html.escape(p_name or t(label_key, p_lang)),
                    talaba_ismi=html.escape(full_name),
                    guruh_nomi=html.escape(old_group),
                    aloqa_raqami=_center_phone_html(),
                ),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            par_sent += 1
        except Exception as exc:
            logger.warning(
                "Reserve notice to parent chat_id=%s failed: %s", p_cid, exc
            )
    return stu_sent, par_sent


async def _notify_restore_from_reserve(
    bot: Any,
    restored: dict[str, Any],
    new_group: str,
    actor_user_id: int,
) -> tuple[int, int]:
    """
    Restoration notice (Zaxira -> active group). Same strict routing as the
    reserve notice: student text only to Talaba_Chat_ID, parent text (with the
    parent's own name) only to parent chats. Includes lesson days + group teacher.
    Returns (student_sent, parents_sent).
    """
    sheets = get_sheets_manager()
    full_name = str(restored.get("F.I.O.") or restored.get("Talaba_ID") or "").strip()
    stu_cid = _norm_cid(restored.get("Talaba_Chat_ID"))
    group_obj = await sheets.a_get_group(new_group) if new_group else None
    teacher_name = await _group_teacher_name(sheets, group_obj)
    days_raw = str((group_obj or {}).get("Dars_Kunlari") or "").strip()
    parent_targets = await _collect_parent_notice_targets(restored)

    stu_sent = 0
    par_sent = 0
    if stu_cid is not None and stu_cid != actor_user_id:
        try:
            s_lang = await database.get_user_lang(stu_cid)
            await bot.send_message(
                chat_id=stu_cid,
                text=_st(
                    "restore_notify_student",
                    s_lang,
                    talaba_ismi=html.escape(full_name),
                    guruh_nomi=html.escape(new_group),
                    dars_kunlari=html.escape(format_full_weekdays(days_raw, s_lang) or "—"),
                    oqituvchi_ismi=html.escape(teacher_name),
                ),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            stu_sent += 1
        except Exception as exc:
            logger.warning(
                "Restore notice to student chat_id=%s failed: %s", stu_cid, exc
            )
    for p_cid, p_name, label_key in parent_targets:
        if p_cid == stu_cid or p_cid == actor_user_id:
            continue
        try:
            p_lang = await database.get_user_lang(p_cid)
            await bot.send_message(
                chat_id=p_cid,
                text=_st(
                    "restore_notify_parent",
                    p_lang,
                    ota_ona_ismi=html.escape(p_name or t(label_key, p_lang)),
                    talaba_ismi=html.escape(full_name),
                    guruh_nomi=html.escape(new_group),
                    dars_kunlari=html.escape(format_full_weekdays(days_raw, p_lang) or "—"),
                    oqituvchi_ismi=html.escape(teacher_name),
                ),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            par_sent += 1
        except Exception as exc:
            logger.warning(
                "Restore notice to parent chat_id=%s failed: %s", p_cid, exc
            )
    return stu_sent, par_sent


async def _format_student_card_full(
    student: dict[str, Any],
    lang: str,
    viewer_user_id: Optional[int] = None,
) -> str:
    """Student card + pre-system (legacy) debt summary + previous group line."""
    card = _format_student_card(student, lang, viewer_user_id=viewer_user_id)
    try:
        legacy_rows = await get_legacy_debts(str(student.get("Talaba_ID") or ""))
    except Exception:
        logger.exception("Failed loading legacy debts for card")
        legacy_rows = []
    extra = _format_legacy_card_line(legacy_rows, lang)
    sobiq = str(student.get("Sobiq_Guruh") or "").strip()
    if sobiq and str(student.get("Guruh") or "").strip().lower() == RESERVE_GROUP_NAME.lower():
        extra_sobiq = (
            f"📚 Собиқ гуруҳ: <b>{html.escape(sobiq)}</b>"
            if lang == "cyrl"
            else f"📚 Sobiq guruh: <b>{html.escape(sobiq)}</b>"
        )
        extra = f"{extra}\n{extra_sobiq}" if extra else extra_sobiq
    return f"{card}\n{extra}" if extra else card


def _format_student_card(
    student: dict[str, Any],
    lang: str,
    viewer_user_id: Optional[int] = None,
) -> str:
    none_val = _st("none_val", lang)
    stu_cid = str(student.get("Talaba_Chat_ID") or "").strip()
    full_name_disp = html.escape(str(student.get("F.I.O.") or ""))
    if viewer_user_id is not None and stu_cid == str(viewer_user_id):
        full_name_disp = f"{full_name_disp} {t('self_marker', lang)}"

    stu_phone_html = _format_clickable_phone(
        str(student.get("Talaba_Tel") or ""), none_val
    )
    stu_tg_html = _format_clickable_tg(
        str(student.get("Talaba_TG") or ""), none_val, chat_id=stu_cid
    )

    father_phone = (
        str(student.get("Otasi_Tel") or "").strip()
        or str(student.get("OtaOna_Tel") or "").strip()
    )
    father_cid = (
        str(student.get("Otasi_Chat_ID") or "").strip()
        or str(student.get("OtaOna_Chat_ID") or "").strip()
    )
    father_info = _format_parent_contact_info(
        str(student.get("Otasi_FIO") or ""),
        father_phone,
        father_cid,
        none_val,
        lang,
        viewer_user_id=viewer_user_id,
    )

    mother_info = _format_parent_contact_info(
        str(student.get("Onasi_FIO") or ""),
        str(student.get("Onasi_Tel") or ""),
        str(student.get("Onasi_Chat_ID") or ""),
        none_val,
        lang,
        viewer_user_id=viewer_user_id,
    )

    return _st(
        "student_card",
        lang,
        student_id=html.escape(str(student.get("Talaba_ID") or "")),
        full_name=full_name_disp,
        group=html.escape(str(student.get("Guruh") or "")),
        status=html.escape(str(student.get("Status") or "")),
        stu_phone=stu_phone_html,
        stu_tg=stu_tg_html,
        father_info=father_info,
        mother_info=mother_info,
        debts=html.escape(str(student.get("Qarzdor_Oylar") or none_val)),
    )


def _chunk_reserve_items(
    header: str, blocks: list[str], max_len: int = 3800
) -> list[str]:
    if not blocks:
        return [header]
    chunks: list[str] = []
    cur = header
    for blk in blocks:
        candidate = f"{cur}\n\n{blk}"
        if len(candidate) > max_len and cur != header:
            chunks.append(cur)
            cur = blk
        else:
            cur = candidate
    if cur:
        chunks.append(cur)
    return chunks


async def _show_reserve_students_panel(
    target_msg: Message,
    state: FSMContext,
    lang: str,
    edit: bool = False,
    from_stu_menu: bool = False,
    viewer_user_id: Optional[int] = None,
) -> None:
    sheets = get_sheets_manager()
    reserve_students = await sheets.a_get_reserve_students()
    if not reserve_students:
        await state.clear()
        back_kb = (
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=t("btn_back", lang), callback_data="res_back:root"
                        )
                    ]
                ]
            )
            if from_stu_menu
            else None
        )
        await (target_msg.edit_text if edit else target_msg.answer)(
            _st("reserve_empty", lang),
            reply_markup=back_kb,
            parse_mode="HTML",
        )
        return

    await state.set_state(StudentManageStates.select_reserve_student)
    none_val = _st("none_val", lang)
    header = _st("reserve_header", lang, total=len(reserve_students))
    blocks: list[str] = []
    kb_rows: list[list[InlineKeyboardButton]] = []
    restore_label = _st("btn_restore_to_group", lang)

    for idx, stu in enumerate(reserve_students, start=1):
        sid = str(stu.get("Talaba_ID") or "").strip()
        full_name = str(stu.get("F.I.O.") or "").strip() or sid
        stu_cid = str(stu.get("Talaba_Chat_ID") or "").strip()
        prev_group = (
            str(stu.get("Sobiq_Guruh") or "").strip()
            or str(stu.get("Guruh") or "").strip()
            or "—"
        )
        debts = str(stu.get("Qarzdor_Oylar") or "").strip() or "0"
        stu_phone_html = _format_clickable_phone(
            str(stu.get("Talaba_Tel") or ""), none_val
        )
        stu_tg_html = _format_clickable_tg(
            str(stu.get("Talaba_TG") or ""), none_val, chat_id=stu_cid
        )
        father_info = _format_parent_contact_info(
            str(stu.get("Otasi_FIO") or ""),
            str(stu.get("Otasi_Tel") or "") or str(stu.get("OtaOna_Tel") or ""),
            str(stu.get("Otasi_Chat_ID") or "") or str(stu.get("OtaOna_Chat_ID") or ""),
            none_val,
            lang,
            viewer_user_id=viewer_user_id,
        )
        mother_info = _format_parent_contact_info(
            str(stu.get("Onasi_FIO") or ""),
            str(stu.get("Onasi_Tel") or ""),
            str(stu.get("Onasi_Chat_ID") or ""),
            none_val,
            lang,
            viewer_user_id=viewer_user_id,
        )
        blocks.append(
            _st(
                "reserve_item",
                lang,
                idx=idx,
                full_name=html.escape(full_name),
                student_id=html.escape(sid),
                group=html.escape(prev_group),
                debts=html.escape(debts),
                stu_phone=stu_phone_html,
                stu_tg=stu_tg_html,
                father_info=father_info,
                mother_info=mother_info,
            )
        )
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=f"{restore_label} ({full_name})",
                    callback_data=f"res_restore:{sid}",
                )
            ]
        )

    if from_stu_menu:
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_back", lang), callback_data="res_back:root"
                ),
                InlineKeyboardButton(
                    text=t("btn_cancel", lang), callback_data="stu_act:cancel"
                ),
            ]
        )
    else:
        kb_rows.append(
            [
                InlineKeyboardButton(
                    text=t("btn_cancel", lang), callback_data="stu_act:cancel"
                )
            ]
        )

    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    chunks = _chunk_reserve_items(header, blocks)

    if len(chunks) == 1:
        await (target_msg.edit_text if edit else target_msg.answer)(
            chunks[0],
            reply_markup=kb,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await (target_msg.edit_text if edit else target_msg.answer)(
            chunks[0], parse_mode="HTML", disable_web_page_preview=True
        )
        for pos, ch in enumerate(chunks[1:], start=1):
            await target_msg.answer(
                ch,
                reply_markup=(kb if pos == len(chunks) - 1 else None),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )


# ======================================================================
# Entry Points (Admin & Teacher) + Reserve Group
# ======================================================================


@router.message(
    F.text.in_({t("menu_admin_students", "latn"), t("menu_admin_students", "cyrl")})
)
async def admin_students_menu(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await message.answer(_st("no_permission", lang), parse_mode="HTML")
        return
    await state.clear()
    await message.answer(
        _st("root_title", lang),
        reply_markup=student_root_menu_kb(lang),
        parse_mode="HTML",
    )


@router.message(F.text.in_(RESERVE_MENU_TEXTS))
async def admin_reserve_group_menu(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await message.answer(_st("no_permission", lang), parse_mode="HTML")
        return
    await state.clear()
    await _show_reserve_students_panel(
        message,
        state,
        lang,
        edit=False,
        from_stu_menu=False,
        viewer_user_id=user_id,
    )


@router.message(F.text.in_(button_texts("menu_teacher_add_student")))
async def teacher_add_student_direct(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    role, groups = await _get_role_and_groups(user_id)
    if role not in {"admin", "teacher"}:
        return
    if not groups:
        await message.answer(_st("no_groups", lang), parse_mode="HTML")
        return
    await state.clear()
    await state.update_data(
        stu_entry_role="admin_direct" if role == "admin" else "teacher_direct"
    )
    await state.set_state(StudentAddStates.selecting_group)
    await message.answer(
        _st("select_group_add", lang),
        reply_markup=groups_inline_kb(
            groups,
            "stu_add_grp",
            lang,
            include_back=(role == "admin"),
            include_cancel=True,
        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("stu_menu:"))
async def student_root_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    action = (callback.data or "").split(":", 1)[1]
    if action == "cancel":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return

    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return

    if action == "reserve":
        await state.clear()
        await _show_reserve_students_panel(
            callback.message,
            state,
            lang,
            edit=True,
            from_stu_menu=True,
            viewer_user_id=user_id,
        )
        await callback.answer()
        return

    _, groups = await _get_role_and_groups(
        user_id, include_unlisted_student_groups=(action == "manage")
    )
    if not groups:
        await callback.message.edit_text(_st("no_groups", lang), parse_mode="HTML")
        await callback.answer()
        return

    await state.update_data(stu_entry_role="admin_menu")
    if action == "add":
        await state.set_state(StudentAddStates.selecting_group)
        await callback.message.edit_text(
            _st("select_group_add", lang),
            reply_markup=groups_inline_kb(
                groups, "stu_add_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
    elif action == "manage":
        await state.set_state(StudentManageStates.selecting_group)
        await callback.message.edit_text(
            _st("select_group_manage", lang),
            reply_markup=groups_inline_kb(
                groups, "stu_mng_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "res_back:root")
async def cb_reserve_back_root(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        _st("root_title", lang),
        reply_markup=student_root_menu_kb(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("res_restore:"))
async def cb_reserve_restore_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1].strip()
    sheets = get_sheets_manager()
    student = await sheets.a_get_student_by_id(sid)
    if not student:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return
    groups = await asyncio.to_thread(sheets.get_all_groups)
    if not groups:
        await callback.answer(_st("no_groups", lang), show_alert=True)
        return

    await state.update_data(restore_student_id=sid)
    await state.set_state(StudentManageStates.select_restore_group)
    await callback.message.edit_text(
        _st(
            "restore_select_group",
            lang,
            full_name=html.escape(str(student.get("F.I.O.") or "")),
            student_id=html.escape(sid),
        ),
        reply_markup=groups_inline_kb(
            groups, "res_grp", lang, include_back=True, include_cancel=True
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.select_restore_group),
    F.data.startswith("res_grp:"),
)
async def cb_reserve_restore_group_selected(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    val = (callback.data or "").split(":", 1)[1].strip()
    if val == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return
    if val == "__back__":
        await _show_reserve_students_panel(
            callback.message,
            state,
            lang,
            edit=True,
            from_stu_menu=True,
            viewer_user_id=user_id,
        )
        await callback.answer()
        return

    sid = str((await state.get_data()).get("restore_student_id") or "").strip()
    if not sid:
        await state.clear()
        await callback.message.edit_text(t("error_generic", lang))
        await callback.answer()
        return

    sheets = get_sheets_manager()
    try:
        restored = await sheets.a_restore_student_from_reserve(sid, val)
    except Exception:
        logger.exception("Error restoring student %s to group %s", sid, val)
        await state.clear()
        await callback.message.edit_text(t("error_generic", lang))
        await callback.answer()
        return

    full_name = str(restored.get("F.I.O.") or "").strip() or sid
    new_group = str(restored.get("Guruh") or val).strip()

    await _notify_restore_from_reserve(callback.bot, restored, new_group, user_id)

    grp_obj = await sheets.a_get_group(new_group)
    t_raw = str(grp_obj.get("Ustoz_Chat_ID") or "" if grp_obj else "").strip()
    if t_raw.isdigit() and int(t_raw) != user_id:
        try:
            t_lang = await get_user_lang(int(t_raw))
            await callback.bot.send_message(
                chat_id=int(t_raw),
                text=_st(
                    "restore_notify_teacher",
                    t_lang,
                    group=html.escape(new_group),
                    full_name=html.escape(full_name),
                    student_id=html.escape(sid),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    await state.clear()
    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_archive_group", lang),
                    callback_data="stu_menu:reserve",
                )
            ]
        ]
    )
    await callback.message.edit_text(
        _st(
            "restore_success_admin",
            lang,
            full_name=html.escape(full_name),
            student_id=html.escape(sid),
            group=html.escape(new_group),
        ),
        reply_markup=back_kb,
        parse_mode="HTML",
    )
    await callback.answer()


# ======================================================================
# 1. ADD NEW STUDENT FLOW (Invite Link & Multi-Child Parent Batch Only)
# ======================================================================


@router.callback_query(
    StateFilter(StudentAddStates.selecting_group), F.data.startswith("stu_add_grp:")
)
async def stu_add_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    group_name = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()

    if group_name == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return

    is_admin = await _is_admin(user_id)
    if group_name == "__back__":
        await state.clear()
        if is_admin and data.get("stu_entry_role") == "admin_menu":
            await callback.message.edit_text(
                _st("root_title", lang),
                reply_markup=student_root_menu_kb(lang),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return

    if not is_admin:
        _, t_groups = await _get_role_and_groups(user_id)
        allowed = any(
            str(g.get("Guruh_Nomi") or "").strip().lower()
            == group_name.strip().lower()
            for g in t_groups
        )
        if not allowed:
            await state.clear()
            await callback.answer(_st("no_permission", lang), show_alert=True)
            return

        bot_me = await callback.bot.get_me()
        group_slug = _slugify_group_name(group_name)
        await state.clear()
        await callback.message.edit_text(
            _st(
                "teacher_invite_only_info",
                lang,
                group=html.escape(group_name),
                bot_username=bot_me.username,
                group_slug=group_slug,
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await callback.answer()
        return

    await state.update_data(group_name=group_name)
    await state.set_state(StudentAddStates.choosing_method)
    await callback.message.edit_text(
        t("student_add_choose_method", lang),
        reply_markup=student_add_method_kb(lang, back_cb="stu_add_method:back"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentAddStates.choosing_method), F.data.startswith("stu_add_method:")
)
async def stu_add_method_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    choice = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()

    if choice == "cancel":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return

    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return

    if choice == "back":
        _, groups = await _get_role_and_groups(user_id)
        await state.set_state(StudentAddStates.selecting_group)
        await callback.message.edit_text(
            _st("select_group_add", lang),
            reply_markup=groups_inline_kb(
                groups, "stu_add_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    if choice == "invite":
        group_name = data["group_name"]
        entry_role = data.get("stu_entry_role", "admin_menu")
        bot_me = await callback.bot.get_me()
        group_slug = _slugify_group_name(group_name)
        await state.clear()
        await callback.message.edit_text(
            _st(
                "invite_links_info",
                lang,
                group=html.escape(group_name),
                bot_username=bot_me.username,
                group_slug=group_slug,
            ),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb=f"stu_add_invite_back:{entry_role}:{group_name}",
                cancel_cb="stu_add_cancel",
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await callback.answer()
        return

    if choice == "parent_batch":
        await state.update_data(batch_children=[], batch_parent_type=None)
        await state.set_state(StudentAddStates.parent_batch_type)
        await callback.message.edit_text(
            _st("pb_choose_parent_type", lang),
            reply_markup=parent_batch_type_kb(lang),
            parse_mode="HTML",
        )
        await callback.answer()


@router.callback_query(F.data.startswith("stu_add_invite_back:"))
async def stu_add_invite_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    _, entry_role, group_name = (callback.data or "").split(":", 2)
    await state.update_data(stu_entry_role=entry_role, group_name=group_name)
    await state.set_state(StudentAddStates.choosing_method)
    await callback.message.edit_text(
        t("student_add_choose_method", lang),
        reply_markup=student_add_method_kb(lang, back_cb="stu_add_method:back"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.in_({"stu_add_cancel", "stu_add:cancel"}))
async def stu_add_cancel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user and callback.message:
        lang = await get_user_lang(callback.from_user.id)
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
    await callback.answer()


@router.message(
    StateFilter(
        StudentAddStates,
        StudentManageStates,
        _FallbackAttachDeviceStates,
    ),
    F.text.in_({t("btn_cancel", "latn"), t("btn_cancel", "cyrl"), "/cancel"}),
)
async def stu_global_text_cancel(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    is_adm = await _is_admin(user_id)
    await state.clear()
    await message.answer(
        _st("action_cancelled", lang),
        reply_markup=get_main_menu_kb("admin" if is_adm else "teacher", lang),
    )


@router.callback_query(StateFilter(StudentAddStates), F.data.startswith("stu_add_back:"))
async def stu_add_step_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    target = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()

    if target == "method":
        await state.set_state(StudentAddStates.choosing_method)
        await callback.message.edit_text(
            t("student_add_choose_method", lang),
            reply_markup=student_add_method_kb(lang, back_cb="stu_add_method:back"),
            parse_mode="HTML",
        )
    elif target == "pb_parent_type":
        await state.set_state(StudentAddStates.parent_batch_type)
        await callback.message.edit_text(
            _st("pb_choose_parent_type", lang),
            reply_markup=parent_batch_type_kb(lang),
            parse_mode="HTML",
        )
    elif target == "pb_parent_name":
        await state.set_state(StudentAddStates.parent_batch_name)
        await callback.message.edit_text(
            _st("pb_enter_parent_name", lang, parent_label=_pb_parent_label(data, lang)),
            reply_markup=step_nav_inline_kb(
                lang, back_cb="stu_add_back:pb_parent_type", cancel_cb="stu_add_cancel"
            ),
            parse_mode="HTML",
        )
    elif target == "pb_parent_phone":
        await state.set_state(StudentAddStates.parent_batch_phone)
        await callback.message.edit_text(
            _st(
                "pb_enter_parent_phone",
                lang,
                parent_label=_pb_parent_label(data, lang),
                parent_name=html.escape(data.get("batch_parent_name", "")),
            ),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb="stu_add_back:pb_parent_name",
                cancel_cb="stu_add_cancel",
            ),
            parse_mode="HTML",
        )
    await callback.answer()


# --- Multi-Child Phone-less Parent Batch Handlers ---


@router.callback_query(
    StateFilter(StudentAddStates.parent_batch_type), F.data.startswith("pb_type:")
)
async def pb_parent_type_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Step 1: admin picks 🧔 Otasi or 🧕 Onasi BEFORE any parent details are asked."""
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    choice = (callback.data or "").split(":", 1)[1].strip()
    if choice not in {"father", "mother"}:
        await callback.answer()
        return
    await state.update_data(batch_parent_type=choice)
    await state.set_state(StudentAddStates.parent_batch_name)
    data = await state.get_data()
    await callback.message.edit_text(
        _st("pb_enter_parent_name", lang, parent_label=_pb_parent_label(data, lang)),
        reply_markup=step_nav_inline_kb(
            lang, back_cb="stu_add_back:pb_parent_type", cancel_cb="stu_add_cancel"
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(StateFilter(StudentAddStates.parent_batch_name))
async def pb_parent_name_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_st("no_permission", lang), parse_mode="HTML")
        return
    parent_name = " ".join((message.text or "").strip().split())
    if not parent_name or len(parent_name) < 2:
        await message.answer(
            _st("pb_invalid_name", lang),
            reply_markup=step_nav_inline_kb(
                lang, back_cb="stu_add_back:pb_parent_type", cancel_cb="stu_add_cancel"
            ),
            parse_mode="HTML",
        )
        return
    await state.update_data(batch_parent_name=parent_name)
    await state.set_state(StudentAddStates.parent_batch_phone)
    pb_data = await state.get_data()
    await message.answer(
        _st(
            "pb_enter_parent_phone",
            lang,
            parent_label=_pb_parent_label(pb_data, lang),
            parent_name=html.escape(parent_name),
        ),
        reply_markup=step_nav_inline_kb(
            lang,
            back_cb="stu_add_back:pb_parent_name",
            cancel_cb="stu_add_cancel",
        ),
        parse_mode="HTML",
    )


@router.message(StateFilter(StudentAddStates.parent_batch_phone))
async def pb_parent_phone_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_st("no_permission", lang), parse_mode="HTML")
        return
    compact = _normalize_phone_input(message.text or "")
    if not compact:
        await message.answer(
            _st("pb_invalid_phone", lang),
            reply_markup=step_nav_inline_kb(
                lang,
                back_cb="stu_add_back:pb_parent_name",
                cancel_cb="stu_add_cancel",
            ),
            parse_mode="HTML",
        )
        return

    await state.update_data(batch_parent_phone=compact, batch_children=[])
    await state.set_state(StudentAddStates.parent_batch_child_name)
    await message.answer(
        _st("pb_enter_child_name", lang, num=1),
        reply_markup=step_nav_inline_kb(
            lang,
            back_cb="stu_add_back:pb_parent_phone",
            cancel_cb="stu_add_cancel",
        ),
        parse_mode="HTML",
    )


@router.message(StateFilter(StudentAddStates.parent_batch_child_name))
async def pb_child_name_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_st("no_permission", lang), parse_mode="HTML")
        return
    child_name = " ".join((message.text or "").strip().split())
    if not child_name or len(child_name) < 2:
        await message.answer(
            _st("pb_invalid_name", lang),
            reply_markup=step_nav_inline_kb(lang, cancel_cb="stu_add_cancel"),
            parse_mode="HTML",
        )
        return
    _, groups = await _get_role_and_groups(user_id)
    if not groups:
        await state.clear()
        await message.answer(_st("no_groups", lang), parse_mode="HTML")
        return

    await state.update_data(pb_pending_child_name=child_name)
    await state.set_state(StudentAddStates.parent_batch_child_group)
    await message.answer(
        _st("pb_select_child_group", lang, child_name=html.escape(child_name)),
        reply_markup=groups_inline_kb(
            groups, "pb_grp", lang, include_back=True, include_cancel=True
        ),
        parse_mode="HTML",
    )


@router.callback_query(
    StateFilter(StudentAddStates.parent_batch_child_group),
    F.data.startswith("pb_grp:"),
)
async def pb_child_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    val = (callback.data or "").split(":", 1)[1].strip()
    data = await state.get_data()

    if val == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return
    if val == "__back__":
        num = len(data.get("batch_children", [])) + 1
        await state.set_state(StudentAddStates.parent_batch_child_name)
        await callback.message.edit_text(
            _st("pb_enter_child_name", lang, num=num),
            reply_markup=step_nav_inline_kb(lang, cancel_cb="stu_add_cancel"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    child_name = str(data.get("pb_pending_child_name") or "").strip()
    if not child_name:
        await state.clear()
        await callback.message.edit_text(t("error_generic", lang))
        await callback.answer()
        return

    children = list(data.get("batch_children", []))
    children.append({"full_name": child_name, "group_name": val})
    await state.update_data(batch_children=children, pb_pending_child_name=None)
    await state.set_state(StudentAddStates.parent_batch_add_more)

    children_lines = "\n".join(
        f"{idx}. <b>{html.escape(c['full_name'])}</b> — 📚 <b>{html.escape(c['group_name'])}</b>"
        for idx, c in enumerate(children, start=1)
    )
    await callback.message.edit_text(
        _st(
            "pb_added_list",
            lang,
            parent_label=_pb_parent_label(data, lang),
            parent_name=html.escape(data.get("batch_parent_name", "")),
            parent_phone=_format_clickable_phone(
                data.get("batch_parent_phone", ""), "—"
            ),
            children_lines=children_lines,
        ),
        reply_markup=parent_batch_more_kb(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentAddStates.parent_batch_add_more),
    F.data.startswith("parent_batch:"),
)
async def pb_add_more_or_finish(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    action = (callback.data or "").split(":", 1)[1].strip()
    data = await state.get_data()
    children = list(data.get("batch_children", []))

    if action == "more":
        await state.set_state(StudentAddStates.parent_batch_child_name)
        await callback.message.edit_text(
            _st("pb_enter_child_name", lang, num=len(children) + 1),
            reply_markup=step_nav_inline_kb(lang, cancel_cb="stu_add_cancel"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    if action == "finish":
        if not children:
            await state.clear()
            await callback.message.edit_text(t("error_generic", lang))
            await callback.answer()
            return

        parent_name = str(data.get("batch_parent_name") or "").strip()
        parent_phone = str(data.get("batch_parent_phone") or "").strip()
        parent_type = _pb_parent_type(data)
        is_mother = parent_type == "mother"
        sheets = get_sheets_manager()

        try:
            await asyncio.to_thread(_ensure_extended_student_headers_sync)
            created_ids: list[str] = []
            created_lines: list[str] = []
            for idx, child in enumerate(children, start=1):
                new_stu = await sheets.a_add_student(
                    full_name=child["full_name"],
                    group_name=child["group_name"],
                    student_phone="Yo'q",
                    student_tg="",
                    parent_phone=parent_phone,
                    status="O'qiyapti",
                    # Strict column routing: a mother is NEVER stored as Otasi_*.
                    father_name="" if is_mother else parent_name,
                    father_phone="" if is_mother else parent_phone,
                    mother_name=parent_name if is_mother else "",
                    mother_phone=parent_phone if is_mother else "",
                )
                sid = str(new_stu.get("Talaba_ID") or "").strip()
                if not sid:
                    continue
                created_ids.append(sid)
                await sheets.a_add_student_to_active_cycle(
                    child["group_name"], sid, child["full_name"], charge_upfront=True
                )
                created_lines.append(
                    f"{idx}. <b>{html.escape(child['full_name'])}</b> "
                    f"(<code>{html.escape(sid)}</code>) — 📚 <b>{html.escape(child['group_name'])}</b>"
                )

            if not created_ids:
                await state.clear()
                await callback.message.edit_text(t("error_generic", lang))
                await callback.answer()
                return

            invite_code = secrets.token_hex(5).upper()
            await create_parent_batch_invite(
                invite_code=invite_code,
                parent_name=parent_name,
                parent_phone=parent_phone,
                student_ids=created_ids,
                parent_type=parent_type,
            )

            bot_info = await callback.bot.get_me()
            await state.clear()
            text = _st(
                "pb_finished",
                lang,
                parent_label=_pb_parent_label(data, lang),
                parent_name=html.escape(parent_name),
                parent_phone=_format_clickable_phone(parent_phone, "—"),
                children_lines="\n".join(created_lines),
                bot_username=bot_info.username,
                invite_code=invite_code,
            )
            if len(created_ids) == 1:
                text += _st(
                    "pb_single_direct_link",
                    lang,
                    bot_username=bot_info.username,
                    student_id=created_ids[0],
                )
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Error finishing parent_batch student creation")
            await state.clear()
            await callback.message.edit_text(t("error_generic", lang))
        await callback.answer()


# ======================================================================
# 2. ATTACH DEVICE / INVITE LINK LATER (attach_stu_device:{student_id})
# ======================================================================


@router.callback_query(F.data.startswith("attach_stu_device:"))
async def cb_attach_student_device(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    sid = (callback.data or "").split(":", 1)[1].strip()
    sheets = get_sheets_manager()

    try:
        student = await sheets.a_get_student_by_id(sid)
    except Exception:
        logger.exception("Error fetching student %s in attach_stu_device", sid)
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    if not student:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    if not await _can_manage_student_device(user_id, student):
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return

    full_name = str(student.get("F.I.O.") or "").strip() or sid
    group_name = str(student.get("Guruh") or "").strip() or "—"

    await state.update_data(attach_student_id=sid)
    await state.set_state(ATTACH_DEVICE_PHONE_STATE)
    await callback.message.edit_text(
        _st(
            "attach_device_prompt",
            lang,
            full_name=html.escape(full_name),
            student_id=html.escape(sid),
            group=html.escape(group_name),
        ),
        reply_markup=_attach_device_kb(sid, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("attach_stu_back:"))
async def cb_attach_student_device_back(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    sid = (callback.data or "").split(":", 1)[1].strip()
    student = await get_sheets_manager().a_get_student_by_id(sid)
    if not student:
        await state.clear()
        await callback.answer()
        return
    if not await _can_manage_student_device(user_id, student):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    await state.update_data(student_id=sid)
    await state.set_state(StudentManageStates.viewing_student)
    await callback.message.edit_text(
        await _format_student_card_full(student, lang, viewer_user_id=user_id),
        reply_markup=student_actions_kb(
            sid,
            student.get("Status", "O'qiyapti"),
            lang,
            has_device=_student_has_device(student),
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("attach_stu_skip:"))
async def cb_attach_student_device_skip(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    sid = (callback.data or "").split(":", 1)[1].strip()
    sheets = get_sheets_manager()

    try:
        student = await sheets.a_get_student_by_id(sid)
        if not student:
            await state.clear()
            await callback.answer(t("error_generic", lang), show_alert=True)
            return
        if not await _can_manage_student_device(user_id, student):
            await state.clear()
            await callback.answer(_st("no_permission", lang), show_alert=True)
            return

        updated = await _attach_student_device_safe(sid, new_phone=None)
        final_student = updated or student
        full_name = str(final_student.get("F.I.O.") or "").strip() or sid
        phone_disp = str(final_student.get("Talaba_Tel") or "").strip() or _st(
            "none_val", lang
        )

        bot_info = await callback.bot.get_me()
        await state.clear()
        await callback.message.edit_text(
            _st(
                "attach_device_ready",
                lang,
                full_name=html.escape(full_name),
                student_id=html.escape(sid),
                phone=html.escape(phone_disp),
                bot_username=bot_info.username,
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.exception("Error skipping phone in attach_stu_device for %s", sid)
        await state.clear()
        await callback.message.edit_text(t("error_generic", lang))
    await callback.answer()


@router.message(StateFilter(ATTACH_DEVICE_PHONE_STATE))
async def msg_attach_student_device_phone(
    message: Message, state: FSMContext
) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    data = await state.get_data()
    sid = str(data.get("attach_student_id") or "").strip()
    if not sid:
        await state.clear()
        await message.answer(t("error_generic", lang))
        return

    sheets = get_sheets_manager()
    try:
        student = await sheets.a_get_student_by_id(sid)
        if not student:
            await state.clear()
            await message.answer(t("error_generic", lang))
            return
        if not await _can_manage_student_device(user_id, student):
            await state.clear()
            await message.answer(_st("no_permission", lang), parse_mode="HTML")
            return

        normalized_phone = _normalize_phone_input(message.text or "")
        if not normalized_phone:
            await message.answer(
                _st("attach_device_invalid_phone", lang),
                reply_markup=_attach_device_kb(sid, lang),
                parse_mode="HTML",
            )
            return

        updated = await _attach_student_device_safe(sid, new_phone=normalized_phone)
        final_student = updated or student
        full_name = str(final_student.get("F.I.O.") or "").strip() or sid

        bot_info = await message.bot.get_me()
        await state.clear()
        await message.answer(
            _st(
                "attach_device_ready",
                lang,
                full_name=html.escape(full_name),
                student_id=html.escape(sid),
                phone=html.escape(normalized_phone),
                bot_username=bot_info.username,
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.exception("Error attaching phone in attach_stu_device for %s", sid)
        await state.clear()
        await message.answer(t("error_generic", lang))


# ======================================================================
# 3. MANAGE EXISTING STUDENTS (Admin Unrestricted Visibility: Status, Edit, Transfer, Links, Delete)
# ======================================================================


@router.callback_query(
    StateFilter(StudentManageStates.selecting_group), F.data.startswith("stu_mng_grp:")
)
async def stu_mng_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    group_name = (callback.data or "").split(":", 1)[1]

    if group_name == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return
    if group_name == "__back__":
        await state.clear()
        await callback.message.edit_text(
            _st("root_title", lang),
            reply_markup=student_root_menu_kb(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    sheets = get_sheets_manager()
    students = await asyncio.to_thread(
        sheets.get_all_students, group_name=group_name, active_only=False
    )
    if not students:
        _, groups = await _get_role_and_groups(
            user_id, include_unlisted_student_groups=True
        )
        await callback.message.edit_text(
            _st("no_students_in_group", lang, group=html.escape(group_name)),
            reply_markup=groups_inline_kb(
                groups, "stu_mng_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.update_data(group_name=group_name)
    await state.set_state(StudentManageStates.selecting_student)
    await callback.message.edit_text(
        _st("select_student", lang, group=html.escape(group_name)),
        reply_markup=students_list_kb(
            students, "stu_sel", lang, include_back=True, include_cancel=True
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.selecting_student), F.data.startswith("stu_sel:")
)
async def stu_mng_student_selected(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1]

    if sid == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return
    if sid == "__back__":
        _, groups = await _get_role_and_groups(
            user_id, include_unlisted_student_groups=True
        )
        await state.set_state(StudentManageStates.selecting_group)
        await callback.message.edit_text(
            _st("select_group_manage", lang),
            reply_markup=groups_inline_kb(
                groups, "stu_mng_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    student = await get_sheets_manager().a_get_student_by_id(sid)
    if not student:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    await state.update_data(student_id=sid)
    await state.set_state(StudentManageStates.viewing_student)
    await callback.message.edit_text(
        await _format_student_card_full(student, lang, viewer_user_id=user_id),
        reply_markup=student_actions_kb(
            sid,
            student.get("Status", "O'qiyapti"),
            lang,
            has_device=_student_has_device(student),
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.viewing_student), F.data.startswith("stu_act:")
)
async def stu_mng_action_clicked(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    parts = (callback.data or "").split(":")
    action = parts[1]

    if action == "cancel":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return
    if action == "back":
        group_name = (await state.get_data()).get("group_name", "")
        students = await asyncio.to_thread(
            get_sheets_manager().get_all_students,
            group_name=group_name,
            active_only=False,
        )
        await state.set_state(StudentManageStates.selecting_student)
        await callback.message.edit_text(
            _st("select_student", lang, group=html.escape(group_name)),
            reply_markup=students_list_kb(
                students, "stu_sel", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    sid = parts[2]
    sheets = get_sheets_manager()
    student = await sheets.a_get_student_by_id(sid)
    if not student:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return

    if action == "status":
        old_fio = str(student.get("F.I.O.") or "").strip()
        new_status = (
            "O'qimayapti" if student.get("Status") == "O'qiyapti" else "O'qiyapti"
        )
        reserve_note = ""
        if new_status == "O'qimayapti":
            # Move to "Zahira guruhi": remove from old {Group}_{Year} sheets,
            # keep the Baza_Talabalar row, save Sobiq_Guruh / Izoh, notify
            # the student AND parent(s).
            try:
                move_res = await sheets.a_move_student_to_reserve(sid)
            except Exception:
                logger.exception("Failed moving student %s to reserve", sid)
                await callback.answer(t("error_generic", lang), show_alert=True)
                return
            old_group = str(move_res.get("old_group") or "").strip() or "—"
            stu_sent, par_sent = await _notify_reserve_move(
                callback.bot, move_res.get("student") or student, old_group, user_id
            )
            reserve_note = _st(
                "moved_to_reserve_detail",
                lang,
                full_name=html.escape(old_fio or sid),
                old_group=html.escape(old_group),
                stu_sent=stu_sent,
                par_sent=par_sent,
            )
        else:
            cur_group = str(student.get("Guruh") or "").strip()
            sobiq = str(student.get("Sobiq_Guruh") or "").strip()
            restored = False
            if cur_group.lower() == RESERVE_GROUP_NAME.lower() and sobiq:
                if await sheets.a_get_group(sobiq):
                    try:
                        restored_stu = await sheets.a_restore_student_from_reserve(
                            sid, sobiq
                        )
                        restored = True
                    except Exception:
                        logger.exception("Failed restoring %s to %s", sid, sobiq)
                    else:
                        try:
                            await _notify_restore_from_reserve(
                                callback.bot,
                                restored_stu or student,
                                str((restored_stu or {}).get("Guruh") or sobiq).strip(),
                                user_id,
                            )
                        except Exception:
                            logger.exception("Restore notice failed for %s", sid)
            if not restored:
                await asyncio.to_thread(
                    sheets.update_student, sid, {"Status": new_status}
                )
                await sheets.a_sync_student_across_all_sheets(
                    sid,
                    old_fio=old_fio,
                    new_fio=old_fio,
                    updated_fields={"Status": new_status},
                )
        student = await sheets.a_get_student_by_id(sid)
        card_text = await _format_student_card_full(
            student, lang, viewer_user_id=user_id
        )
        if reserve_note:
            card_text = f"{reserve_note}\n\n{card_text}"
        await callback.message.edit_text(
            card_text,
            reply_markup=student_actions_kb(
                sid,
                new_status,
                lang,
                has_device=_student_has_device(student),
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await callback.answer(
            _st("moved_to_reserve", lang)
            if new_status == "O'qimayapti"
            else _st("updated_ok", lang),
            show_alert=(new_status == "O'qimayapti"),
        )
    elif action == "legacy_add":
        await state.update_data(
            legacy_sid=sid,
            legacy_name=str(student.get("F.I.O.") or sid),
            legacy_group=str(student.get("Guruh") or "").strip(),
            legacy_sobiq=str(student.get("Sobiq_Guruh") or "").strip(),
        )
        await state.set_state(LegacyDebtStates.entering_label)
        await callback.message.edit_text(
            _st(
                "legacy_enter_label",
                lang,
                full_name=html.escape(str(student.get("F.I.O.") or sid)),
            ),
            reply_markup=_legacy_nav_kb(lang),
            parse_mode="HTML",
        )
        await callback.answer()
    elif action == "legacy_list":
        await _show_legacy_list(callback.message, sid, lang, edit=True)
        await callback.answer()
    elif action == "edit":
        await state.set_state(StudentManageStates.editing_field)
        await callback.message.edit_text(
            _st("choose_edit_field", lang),
            reply_markup=student_edit_fields_kb(sid, lang),
            parse_mode="HTML",
        )
        await callback.answer()
    elif action == "links":
        bot_info = await callback.bot.get_me()
        stu_phone_raw = str(student.get("Talaba_Tel") or "").strip().lower()
        link_key = (
            "links_card_parent_only"
            if (stu_phone_raw in NO_PHONE_VALUES and not _student_has_device(student))
            else "links_card"
        )
        await callback.message.answer(
            _st(
                link_key,
                lang,
                full_name=html.escape(str(student.get("F.I.O.") or "")),
                student_id=html.escape(sid),
                bot_username=bot_info.username,
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await callback.answer()
    elif action == "delete":
        await state.set_state(StudentManageStates.confirming_delete)
        await callback.message.edit_text(
            _st(
                "confirm_delete",
                lang,
                full_name=html.escape(str(student.get("F.I.O.") or "")),
                student_id=html.escape(sid),
            ),
            reply_markup=confirm_delete_student_kb(sid, lang),
            parse_mode="HTML",
        )
        await callback.answer()


@router.callback_query(F.data == "stu_act:cancel")
async def stu_mng_global_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user and callback.message:
        lang = await get_user_lang(callback.from_user.id)
        await state.clear()
        try:
            await callback.message.edit_text(_st("action_cancelled", lang))
        except Exception:
            pass
    await callback.answer()


@router.callback_query(
    StateFilter(
        StudentManageStates.editing_field,
        StudentManageStates.entering_new_value,
        StudentManageStates.selecting_new_group,
    ),
    F.data.startswith("stu_field_back:"),
)
async def stu_edit_field_back(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1]
    student = await get_sheets_manager().a_get_student_by_id(sid)
    if not student:
        await state.clear()
        await callback.answer()
        return
    await state.set_state(StudentManageStates.viewing_student)
    await callback.message.edit_text(
        _format_student_card(student, lang, viewer_user_id=user_id),
        reply_markup=student_actions_kb(
            sid,
            student.get("Status", "O'qiyapti"),
            lang,
            has_device=_student_has_device(student),
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(
    StateFilter(
        StudentManageStates.entering_new_value,
        StudentManageStates.selecting_new_group,
    ),
    F.data.startswith("stu_edit_fields_back:"),
)
async def stu_edit_back_to_fields(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1]
    await state.set_state(StudentManageStates.editing_field)
    await callback.message.edit_text(
        _st("choose_edit_field", lang),
        reply_markup=student_edit_fields_kb(sid, lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.editing_field), F.data.startswith("stu_field:")
)
async def stu_edit_field_selected(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    _, sid, field_name = (callback.data or "").split(":", 2)
    await state.update_data(student_id=sid, edit_field=field_name)

    if field_name == "Guruh":
        _, groups = await _get_role_and_groups(user_id)
        await state.set_state(StudentManageStates.selecting_new_group)
        await callback.message.edit_text(
            _st("select_new_group", lang),
            reply_markup=groups_inline_kb(
                groups, "stu_new_grp", lang, include_back=True, include_cancel=True
            ),
            parse_mode="HTML",
        )
    else:
        await state.set_state(StudentManageStates.entering_new_value)
        await callback.message.edit_text(
            _st("enter_new_value", lang, field=html.escape(field_name)),
            reply_markup=step_nav_inline_kb(
                lang, back_cb=f"stu_edit_fields_back:{sid}", cancel_cb="stu_act:cancel"
            ),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.selecting_new_group),
    F.data.startswith("stu_new_grp:"),
)
async def stu_edit_new_group_selected(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    new_group = (callback.data or "").split(":", 1)[1]
    data = await state.get_data()
    sid = data["student_id"]

    if new_group == "__cancel__":
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
        await callback.answer()
        return
    if new_group == "__back__":
        await state.set_state(StudentManageStates.editing_field)
        await callback.message.edit_text(
            _st("choose_edit_field", lang),
            reply_markup=student_edit_fields_kb(sid, lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    sheets = get_sheets_manager()
    student = await sheets.a_get_student_by_id(sid)
    if not student:
        await state.clear()
        await callback.message.edit_text(t("error_generic", lang))
        await callback.answer()
        return

    old_group = str(student.get("Guruh") or "").strip()
    if old_group.lower() == new_group.strip().lower():
        await state.set_state(StudentManageStates.viewing_student)
        await callback.message.edit_text(
            _format_student_card(student, lang, viewer_user_id=user_id),
            reply_markup=student_actions_kb(
                sid,
                student.get("Status", "O'qiyapti"),
                lang,
                has_device=_student_has_device(student),
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await callback.answer()
        return

    await state.update_data(
        student_id=sid,
        target_group=new_group.strip(),
        old_group=old_group,
    )
    await state.set_state(StudentManageStates.confirm_keep_in_old_group)
    await callback.message.edit_text(
        t(
            "stu_transfer_keep_question",
            lang,
            student_name=html.escape(str(student.get("F.I.O.") or "")),
            old_group=html.escape(old_group),
            new_group=html.escape(new_group.strip()),
        ),
        reply_markup=student_transfer_keep_kb(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.confirm_keep_in_old_group),
    F.data.startswith("transfer_keep:"),
)
async def stu_transfer_keep_confirmed(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    choice = (callback.data or "").split(":", 1)[1]
    keep_in_old_group = choice == "yes"

    data = await state.get_data()
    sid = str(data.get("student_id") or "").strip()
    target_group = str(data.get("target_group") or "").strip()
    if not sid or not target_group:
        await state.clear()
        await callback.message.edit_text(t("error_generic", lang))
        await callback.answer()
        return

    sheets = get_sheets_manager()
    try:
        result = await sheets.a_transfer_or_enroll_student(
            sid, target_group, keep_in_old_group
        )
    except Exception:
        logger.exception("Error transferring student %s to %s", sid, target_group)
        await state.clear()
        await callback.message.edit_text(t("error_generic", lang))
        await callback.answer()
        return

    old_group = result["old_group"]
    new_group = result["new_group"]
    new_student_id = result["new_student_id"]
    updated_student = result["student"]
    student_name = str(updated_student.get("F.I.O.") or "").strip()

    await sheets.a_sync_student_across_all_sheets(
        new_student_id,
        old_fio=student_name,
        new_fio=student_name,
        updated_fields={"Guruh": new_group},
    )

    stu_cid_str = str(updated_student.get("Talaba_Chat_ID") or "").strip()
    if stu_cid_str.isdigit() and int(stu_cid_str) != user_id:
        try:
            s_cid = int(stu_cid_str)
            s_lang = await get_user_lang(s_cid)
            s_key = (
                "stu_transfer_notify_dual_student"
                if keep_in_old_group
                else "stu_transfer_notify_move_student"
            )
            await callback.bot.send_message(
                chat_id=s_cid,
                text=t(
                    s_key,
                    s_lang,
                    student_name=html.escape(student_name),
                    old_group=html.escape(old_group),
                    new_group=html.escape(new_group),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    notified_parents: set[int] = set()
    father_cid_str = str(updated_student.get("Otasi_Chat_ID") or "").strip()
    if father_cid_str.isdigit() and int(father_cid_str) != user_id:
        f_cid = int(father_cid_str)
        notified_parents.add(f_cid)
        try:
            f_lang = await get_user_lang(f_cid)
            f_name = (
                str(updated_student.get("Otasi_FIO") or "").strip()
                or t("parent_label_father", f_lang)
            )
            f_key = (
                "stu_transfer_notify_dual_father"
                if keep_in_old_group
                else "stu_transfer_notify_move_father"
            )
            await callback.bot.send_message(
                chat_id=f_cid,
                text=t(
                    f_key,
                    f_lang,
                    parent_name=html.escape(f_name),
                    student_name=html.escape(student_name),
                    old_group=html.escape(old_group),
                    new_group=html.escape(new_group),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    mother_cid_str = str(updated_student.get("Onasi_Chat_ID") or "").strip()
    if mother_cid_str.isdigit() and int(mother_cid_str) != user_id:
        m_cid = int(mother_cid_str)
        if m_cid not in notified_parents:
            notified_parents.add(m_cid)
            try:
                m_lang = await get_user_lang(m_cid)
                m_name = (
                    str(updated_student.get("Onasi_FIO") or "").strip()
                    or t("parent_label_mother", m_lang)
                )
                m_key = (
                    "stu_transfer_notify_dual_mother"
                    if keep_in_old_group
                    else "stu_transfer_notify_move_mother"
                )
                await callback.bot.send_message(
                    chat_id=m_cid,
                    text=t(
                        m_key,
                        m_lang,
                        parent_name=html.escape(m_name),
                        student_name=html.escape(student_name),
                        old_group=html.escape(old_group),
                        new_group=html.escape(new_group),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    legacy_parent_cid_str = str(
        updated_student.get("OtaOna_Chat_ID") or ""
    ).strip()
    if legacy_parent_cid_str.isdigit() and int(legacy_parent_cid_str) != user_id:
        p_cid = int(legacy_parent_cid_str)
        if p_cid not in notified_parents:
            try:
                p_lang = await get_user_lang(p_cid)
                p_key = (
                    "stu_transfer_notify_dual_father"
                    if keep_in_old_group
                    else "stu_transfer_notify_move_father"
                )
                await callback.bot.send_message(
                    chat_id=p_cid,
                    text=t(
                        p_key,
                        p_lang,
                        parent_name=t("role_parent", p_lang),
                        student_name=html.escape(student_name),
                        old_group=html.escape(old_group),
                        new_group=html.escape(new_group),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    new_grp_obj = await sheets.a_get_group(new_group)
    new_t_cid_str = (
        str(new_grp_obj.get("Ustoz_Chat_ID") or "").strip()
        if new_grp_obj
        else ""
    )
    if new_t_cid_str.isdigit() and int(new_t_cid_str) != user_id:
        try:
            nt_cid = int(new_t_cid_str)
            nt_lang = await get_user_lang(nt_cid)
            await callback.bot.send_message(
                chat_id=nt_cid,
                text=t(
                    "stu_transfer_notify_new_teacher",
                    nt_lang,
                    new_group=html.escape(new_group),
                    student_name=html.escape(student_name),
                    student_id=html.escape(new_student_id),
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass

    if not keep_in_old_group and old_group:
        old_grp_obj = await sheets.a_get_group(old_group)
        old_t_cid_str = (
            str(old_grp_obj.get("Ustoz_Chat_ID") or "").strip()
            if old_grp_obj
            else ""
        )
        if (
            old_t_cid_str.isdigit()
            and int(old_t_cid_str) != user_id
            and old_t_cid_str != new_t_cid_str
        ):
            try:
                ot_cid = int(old_t_cid_str)
                ot_lang = await get_user_lang(ot_cid)
                await callback.bot.send_message(
                    chat_id=ot_cid,
                    text=t(
                        "stu_transfer_notify_old_teacher_moved",
                        ot_lang,
                        student_name=html.escape(student_name),
                        old_group=html.escape(old_group),
                        new_group=html.escape(new_group),
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass

    if keep_in_old_group:
        admin_notice = t(
            "stu_transfer_success_dual_admin",
            lang,
            student_name=html.escape(student_name),
            old_group=html.escape(old_group),
            new_group=html.escape(new_group),
            new_student_id=html.escape(new_student_id),
        )
    else:
        admin_notice = t(
            "stu_transfer_success_move_admin",
            lang,
            student_name=html.escape(student_name),
            student_id=html.escape(new_student_id),
            old_group=html.escape(old_group),
            new_group=html.escape(new_group),
        )

    await state.update_data(student_id=new_student_id, group_name=new_group)
    await state.set_state(StudentManageStates.viewing_student)
    card_text = _format_student_card(updated_student, lang, viewer_user_id=user_id)
    await callback.message.edit_text(
        f"{admin_notice}\n\n{card_text}",
        reply_markup=student_actions_kb(
            new_student_id,
            updated_student.get("Status", "O'qiyapti"),
            lang,
            has_device=_student_has_device(updated_student),
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await callback.answer(_st("updated_ok", lang))


@router.message(StateFilter(StudentManageStates.entering_new_value))
async def stu_edit_new_value_entered(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    user_id = message.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await message.answer(_st("no_permission", lang), parse_mode="HTML")
        return
    new_val = (message.text or "").strip()
    data = await state.get_data()
    sid = data["student_id"]
    field_name = data["edit_field"]

    if field_name == "Talaba_TG" and new_val and not new_val.startswith("@"):
        new_val = f"@{new_val}"

    sheets = get_sheets_manager()
    await asyncio.to_thread(_ensure_extended_student_headers_sync)
    student_before = await sheets.a_get_student_by_id(sid)
    old_fio = (
        str(student_before.get("F.I.O.") or "").strip() if student_before else ""
    )

    updates: dict[str, Any] = {field_name: new_val}
    if field_name == "Otasi_Tel" and student_before:
        if not str(student_before.get("OtaOna_Tel") or "").strip():
            updates["OtaOna_Tel"] = new_val

    await asyncio.to_thread(sheets.update_student, sid, updates)
    new_fio = new_val if field_name == "F.I.O." else old_fio
    await sheets.a_sync_student_across_all_sheets(
        sid,
        old_fio=old_fio,
        new_fio=new_fio,
        updated_fields=updates,
    )

    if field_name == "F.I.O." and student_before:
        stu_cid_str = str(student_before.get("Talaba_Chat_ID") or "").strip()
        if stu_cid_str.isdigit():
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE users SET full_name = ? WHERE telegram_id = ?;",
                        (new_val, int(stu_cid_str)),
                    )
                    await db.commit()
            except Exception:
                pass

    student = await sheets.a_get_student_by_id(sid)
    await state.set_state(StudentManageStates.viewing_student)

    await message.answer(_st("updated_ok", lang), parse_mode="HTML")
    if student:
        await message.answer(
            _format_student_card(student, lang, viewer_user_id=user_id),
            reply_markup=student_actions_kb(
                sid,
                student.get("Status", "O'qiyapti"),
                lang,
                has_device=_student_has_device(student),
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )


@router.callback_query(
    StateFilter(StudentManageStates.confirming_delete),
    F.data.startswith("stu_del_cancel:"),
)
async def stu_delete_cancelled(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1]
    student = await get_sheets_manager().a_get_student_by_id(sid)
    await state.set_state(StudentManageStates.viewing_student)
    if student:
        await callback.message.edit_text(
            _format_student_card(student, lang, viewer_user_id=user_id),
            reply_markup=student_actions_kb(
                sid,
                student.get("Status", "O'qiyapti"),
                lang,
                has_device=_student_has_device(student),
            ),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    await callback.answer()


@router.callback_query(
    StateFilter(StudentManageStates.confirming_delete),
    F.data.startswith("stu_del_confirm:"),
)
async def stu_delete_confirmed(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 1)[1]
    sheets = get_sheets_manager()
    student_before = await sheets.a_get_student_by_id(sid)
    # Sheets purge (Baza_Talabalar + every {Group}_{Year} worksheet); the
    # returned payload says which parents are left without any child.
    payload = await sheets.a_purge_student_completely(sid)
    await state.clear()
    if payload.get("deleted"):
        stu_cid = payload.get("student_chat_id")
        # A student with another enrollment (same chat id) keeps the student role.
        purge_stu_cid = None if payload.get("student_has_other_enrollments") else stu_cid
        db_result = await database.purge_student_and_orphaned_parents(
            str(payload.get("student_id") or sid),
            purge_stu_cid,
            list(payload.get("orphaned_parent_chat_ids") or []),
        )
        # Re-point still-valid users (remaining enrollments / other children).
        await _cleanup_deleted_student_sqlite(sid, student_before)
        state_key = {
            "deleted": "purge_state_deleted",
            "updated": "purge_state_updated",
        }.get(str(db_result.get("student_user")), "purge_state_none")
        parents_purged = sum(
            1 for v in (db_result.get("parents") or {}).values() if v == "deleted"
        )
        await callback.message.edit_text(
            _st(
                "deleted_purged",
                lang,
                full_name=html.escape(str(payload.get("student_name") or sid)),
                student_id=html.escape(str(payload.get("student_id") or sid)),
                cycle_rows=int(payload.get("removed_cycle_rows") or 0),
                student_state=_st(state_key, lang),
                parents_purged=parents_purged,
            ),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(t("error_generic", lang), parse_mode="HTML")
    await callback.answer()


# ======================================================================
# PRE-SYSTEM (LEGACY) DEBTS — "➕ Avvalgi qarz qo'shish" / "📜 Avvalgi qarzlar"
# ======================================================================

_LEGACY_DATE_RE = re.compile(r"\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?")


def _fmt_sum(amount: int) -> str:
    return f"{int(amount or 0):,}".replace(",", " ")


def _legacy_nav_kb(
    lang: str, include_skip: bool = False, suggested: Optional[int] = None
) -> InlineKeyboardMarkup:
    action_buttons: list[InlineKeyboardButton] = []
    if suggested:
        action_buttons.append(
            InlineKeyboardButton(
                text=f"✅ {_fmt_sum(suggested)}",
                callback_data="legacy:use_suggested",
            )
        )
    if include_skip:
        action_buttons.append(
            InlineKeyboardButton(
                text="⏭ Ўтказиб юбориш" if lang == "cyrl" else "⏭ O‘tkazib yuborish",
                callback_data="legacy:skip_dates",
            )
        )
    cancel_button = InlineKeyboardButton(
        text=t("btn_cancel", lang), callback_data="legacy:cancel"
    )
    if len(action_buttons) == 1:
        rows = [[action_buttons[0], cancel_button]]
    else:
        rows = [action_buttons] if action_buttons else []
        rows.append([cancel_button])
    return balance_inline_markup(InlineKeyboardMarkup(inline_keyboard=rows))


def _legacy_confirm_kb(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Тасдиқлаш" if lang == "cyrl" else "✅ Tasdiqlash",
                    callback_data="legacy:save",
                ),
                InlineKeyboardButton(
                    text=t("btn_cancel", lang), callback_data="legacy:cancel"
                ),
            ],
        ]
    )


def _parse_positive_int(raw: str) -> Optional[int]:
    cleaned = (raw or "").strip().lower()
    for suffix in ("so'm", "so‘m", "som", "sum", "сўм", "uzs"):
        cleaned = cleaned.replace(suffix, "")
    cleaned = re.sub(r"[\s,._]", "", cleaned)
    if not cleaned.isdigit():
        return None
    val = int(cleaned)
    return val if val > 0 else None


def _normalize_legacy_dates(raw: str) -> str:
    text = " ".join((raw or "").split())
    if not text:
        return ""
    found = _LEGACY_DATE_RE.findall(text)
    if len(found) == 2 and re.search(r"[–—-]\s*\d", text) and "," not in text:
        return f"{found[0]} – {found[1]}"
    if found:
        return ", ".join(found)
    return text[:300]


async def _resolve_student_fee(student_group: str, sobiq_group: str) -> int:
    sheets = get_sheets_manager()
    for g_name in (student_group, sobiq_group):
        if not g_name:
            continue
        grp = await sheets.a_get_group(g_name)
        if grp:
            digits = re.sub(r"[^\d]", "", str(grp.get("Oylik_Tolov_Summa") or ""))
            if digits and int(digits) > 0:
                return int(digits)
    env_fee = re.sub(r"[^\d]", "", str(os.getenv("DEFAULT_MONTHLY_FEE", "")))
    return int(env_fee) if env_fee else 500000


async def _show_student_card_after_legacy(
    message: Message,
    state: FSMContext,
    sid: str,
    lang: str,
    viewer_user_id: int,
    notice: str = "",
    edit: bool = True,
) -> None:
    student = await get_sheets_manager().a_get_student_by_id(sid)
    if not student:
        await state.clear()
        await (message.edit_text if edit else message.answer)(t("error_generic", lang))
        return
    await state.set_state(StudentManageStates.viewing_student)
    await state.update_data(student_id=sid)
    card = await _format_student_card_full(student, lang, viewer_user_id=viewer_user_id)
    text = f"{notice}\n\n{card}" if notice else card
    kb = student_actions_kb(
        sid,
        student.get("Status", "O'qiyapti"),
        lang,
        has_device=_student_has_device(student),
    )
    try:
        await (message.edit_text if edit else message.answer)(
            text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True
        )
    except Exception:
        await message.answer(
            text, reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True
        )


async def _show_legacy_list(
    message: Message, sid: str, lang: str, edit: bool = True, notice: str = ""
) -> None:
    student = await get_sheets_manager().a_get_student_by_id(sid)
    full_name = str((student or {}).get("F.I.O.") or sid)
    rows = await get_legacy_debts(sid, include_paid=True)
    kb_rows: list[list[InlineKeyboardButton]] = []
    if not rows:
        text = _st("legacy_list_empty", lang, full_name=html.escape(full_name))
    else:
        lines = [_st("legacy_list_header", lang, full_name=html.escape(full_name))]
        for idx, row in enumerate(rows, start=1):
            is_paid = bool(int(row.get("is_paid") or 0))
            lines.append(
                _st(
                    "legacy_list_item",
                    lang,
                    idx=idx,
                    label=html.escape(str(row.get("cycle_label") or "—")),
                    months=int(row.get("months") or 1),
                    amount=_fmt_sum(int(row.get("amount") or 0)),
                    status=_st(
                        "legacy_status_paid" if is_paid else "legacy_status_unpaid", lang
                    ),
                    dates=html.escape(str(row.get("lesson_dates") or "—")),
                )
            )
            toggle_key = "btn_legacy_mark_unpaid" if is_paid else "btn_legacy_mark_paid"
            kb_rows.append(
                [
                    InlineKeyboardButton(
                        text=_st(toggle_key, lang, idx=idx),
                        callback_data=f"legacy:paid:{row['id']}:{0 if is_paid else 1}",
                    ),
                    InlineKeyboardButton(
                        text=_st("btn_legacy_delete", lang, idx=idx),
                        callback_data=f"legacy:del:{row['id']}",
                    ),
                ]
            )
        text = "\n\n".join(lines)
    if notice:
        text = f"{notice}\n\n{text}"
    kb_rows.append(
        [
            InlineKeyboardButton(
                text=_st("btn_legacy_add", lang),
                callback_data=f"legacy:add:{sid}",
            ),
            InlineKeyboardButton(
                text=_st("btn_legacy_back_card", lang),
                callback_data=f"legacy:card:{sid}",
            ),
        ]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)
    try:
        await (message.edit_text if edit else message.answer)(
            text, reply_markup=kb, parse_mode="HTML"
        )
    except Exception:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "legacy:cancel")
async def cb_legacy_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    sid = str((await state.get_data()).get("legacy_sid") or "").strip()
    if sid and await _is_admin(user_id):
        await _show_student_card_after_legacy(
            callback.message, state, sid, lang, user_id, notice=_st("action_cancelled", lang)
        )
    else:
        await state.clear()
        await callback.message.edit_text(_st("action_cancelled", lang))
    await callback.answer()


@router.callback_query(F.data.startswith("legacy:add:"))
async def cb_legacy_add_from_list(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 2)[2].strip()
    student = await get_sheets_manager().a_get_student_by_id(sid)
    if not student:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return
    await state.update_data(
        student_id=sid,
        legacy_sid=sid,
        legacy_name=str(student.get("F.I.O.") or sid),
        legacy_group=str(student.get("Guruh") or "").strip(),
        legacy_sobiq=str(student.get("Sobiq_Guruh") or "").strip(),
    )
    await state.set_state(LegacyDebtStates.entering_label)
    await callback.message.edit_text(
        _st(
            "legacy_enter_label",
            lang,
            full_name=html.escape(str(student.get("F.I.O.") or sid)),
        ),
        reply_markup=_legacy_nav_kb(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(LegacyDebtStates.entering_label)
async def msg_legacy_label(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return
    label = " ".join((message.text or "").split())
    if not label or label.startswith("/") or len(label) > 120:
        await message.answer(
            _st("legacy_invalid_number", lang) if not label else "❌",
            reply_markup=_legacy_nav_kb(lang),
        )
        return
    await state.update_data(legacy_label=label)
    await state.set_state(LegacyDebtStates.entering_dates)
    await message.answer(
        _st("legacy_enter_dates", lang),
        reply_markup=_legacy_nav_kb(lang, include_skip=True),
        parse_mode="HTML",
    )


async def _legacy_ask_months(target: Message, state: FSMContext, lang: str) -> None:
    await state.set_state(LegacyDebtStates.entering_months)
    await target.answer(
        _st("legacy_enter_months", lang),
        reply_markup=_legacy_nav_kb(lang),
        parse_mode="HTML",
    )


@router.callback_query(LegacyDebtStates.entering_dates, F.data == "legacy:skip_dates")
async def cb_legacy_skip_dates(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    await state.update_data(legacy_dates="")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _legacy_ask_months(callback.message, state, lang)
    await callback.answer()


@router.message(LegacyDebtStates.entering_dates)
async def msg_legacy_dates(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return
    await state.update_data(legacy_dates=_normalize_legacy_dates(message.text or ""))
    await _legacy_ask_months(message, state, lang)


@router.message(LegacyDebtStates.entering_months)
async def msg_legacy_months(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return
    months = _parse_positive_int(message.text or "")
    if months is None or months > 60:
        await message.answer(
            _st("legacy_invalid_number", lang), reply_markup=_legacy_nav_kb(lang)
        )
        return
    data = await state.get_data()
    fee = await _resolve_student_fee(
        str(data.get("legacy_group") or ""), str(data.get("legacy_sobiq") or "")
    )
    suggested = months * fee
    await state.update_data(legacy_months=months, legacy_suggested=suggested)
    await state.set_state(LegacyDebtStates.entering_amount)
    await message.answer(
        _st("legacy_enter_amount", lang, suggested=_fmt_sum(suggested)),
        reply_markup=_legacy_nav_kb(lang, suggested=suggested),
        parse_mode="HTML",
    )


async def _legacy_show_confirm(
    target: Message, state: FSMContext, lang: str, amount: int
) -> None:
    await state.update_data(legacy_amount=amount)
    data = await state.get_data()
    await state.set_state(LegacyDebtStates.confirming)
    group_disp = str(data.get("legacy_group") or "—")
    if group_disp.lower() == RESERVE_GROUP_NAME.lower() and data.get("legacy_sobiq"):
        group_disp = f"{group_disp} ({data.get('legacy_sobiq')})"
    await target.answer(
        _st(
            "legacy_confirm",
            lang,
            full_name=html.escape(str(data.get("legacy_name") or "")),
            student_id=html.escape(str(data.get("legacy_sid") or "")),
            group=html.escape(group_disp),
            label=html.escape(str(data.get("legacy_label") or "—")),
            dates=html.escape(str(data.get("legacy_dates") or "—")),
            months=int(data.get("legacy_months") or 1),
            amount=_fmt_sum(amount),
        ),
        reply_markup=_legacy_confirm_kb(lang),
        parse_mode="HTML",
    )


@router.callback_query(LegacyDebtStates.entering_amount, F.data == "legacy:use_suggested")
async def cb_legacy_use_suggested(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    lang = await get_user_lang(callback.from_user.id)
    suggested = int((await state.get_data()).get("legacy_suggested") or 0)
    if suggested <= 0:
        await callback.answer(_st("legacy_invalid_number", lang), show_alert=True)
        return
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await _legacy_show_confirm(callback.message, state, lang, suggested)
    await callback.answer()


@router.message(LegacyDebtStates.entering_amount)
async def msg_legacy_amount(message: Message, state: FSMContext) -> None:
    if not message.from_user:
        return
    lang = await get_user_lang(message.from_user.id)
    if not await _is_admin(message.from_user.id):
        await state.clear()
        return
    amount = _parse_positive_int(message.text or "")
    if amount is None or amount > 1_000_000_000:
        suggested = int((await state.get_data()).get("legacy_suggested") or 0)
        await message.answer(
            _st("legacy_invalid_number", lang),
            reply_markup=_legacy_nav_kb(lang, suggested=suggested or None),
        )
        return
    if amount < 10000:
        amount *= 1000
    await _legacy_show_confirm(message, state, lang, amount)


@router.callback_query(LegacyDebtStates.confirming, F.data == "legacy:save")
async def cb_legacy_save(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await state.clear()
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    data = await state.get_data()
    sid = str(data.get("legacy_sid") or "").strip()
    if not sid:
        await state.clear()
        await callback.answer(t("error_generic", lang), show_alert=True)
        return
    group_name = str(data.get("legacy_group") or "").strip()
    if group_name.lower() == RESERVE_GROUP_NAME.lower() and data.get("legacy_sobiq"):
        group_name = str(data.get("legacy_sobiq"))
    try:
        await add_legacy_debt(
            student_id=sid,
            cycle_label=str(data.get("legacy_label") or ""),
            amount=int(data.get("legacy_amount") or 0),
            months=int(data.get("legacy_months") or 1),
            lesson_dates=str(data.get("legacy_dates") or ""),
            student_name=str(data.get("legacy_name") or ""),
            group_name=group_name,
            created_by=user_id,
        )
    except Exception:
        logger.exception("Failed saving legacy debt for %s", sid)
        await callback.answer(t("error_generic", lang), show_alert=True)
        return
    await state.update_data(
        legacy_label=None, legacy_dates=None, legacy_months=None, legacy_amount=None
    )
    await _show_student_card_after_legacy(
        callback.message, state, sid, lang, user_id, notice=_st("legacy_saved", lang)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("legacy:card:"))
async def cb_legacy_back_to_card(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    sid = (callback.data or "").split(":", 2)[2].strip()
    await _show_student_card_after_legacy(callback.message, state, sid, lang, user_id)
    await callback.answer()


async def _notify_legacy_paid(bot: Any, debt: dict[str, Any]) -> None:
    student = await get_sheets_manager().a_get_student_by_id(str(debt.get("student_id") or ""))
    if not student:
        return
    full_name = str(student.get("F.I.O.") or debt.get("student_name") or "").strip()
    recipients: list[int] = []
    for col in ("Talaba_Chat_ID", "Otasi_Chat_ID", "Onasi_Chat_ID", "OtaOna_Chat_ID"):
        cid = _norm_cid(student.get(col))
        if cid is not None and cid not in recipients:
            recipients.append(cid)
    for cid in recipients:
        try:
            r_lang = await get_user_lang(cid)
            await bot.send_message(
                chat_id=cid,
                text=_st(
                    "legacy_paid_notify",
                    r_lang,
                    full_name=html.escape(full_name),
                    label=html.escape(str(debt.get("cycle_label") or "—")),
                    amount=_fmt_sum(int(debt.get("amount") or 0)),
                ),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("Legacy paid notice to %s failed: %s", cid, exc)


@router.callback_query(F.data.startswith("legacy:paid:"))
async def cb_legacy_toggle_paid(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    parts = (callback.data or "").split(":")
    try:
        debt_id = int(parts[2])
        paid = parts[3] == "1"
    except (IndexError, ValueError):
        await callback.answer()
        return
    debt = await get_legacy_debt(debt_id)
    if not debt:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return
    await set_legacy_debt_paid(debt_id, paid)
    if paid:
        await _notify_legacy_paid(callback.bot, debt)
    await _show_legacy_list(
        callback.message,
        str(debt.get("student_id") or ""),
        lang,
        edit=True,
        notice=_st("legacy_paid_ok" if paid else "legacy_unpaid_ok", lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("legacy:del:"))
async def cb_legacy_delete(callback: CallbackQuery) -> None:
    if not callback.from_user or not callback.message:
        await callback.answer()
        return
    user_id = callback.from_user.id
    lang = await get_user_lang(user_id)
    if not await _is_admin(user_id):
        await callback.answer(_st("no_permission", lang), show_alert=True)
        return
    try:
        debt_id = int((callback.data or "").split(":")[2])
    except (IndexError, ValueError):
        await callback.answer()
        return
    debt = await get_legacy_debt(debt_id)
    if not debt:
        await callback.answer(t("error_generic", lang), show_alert=True)
        return
    await delete_legacy_debt(debt_id)
    await _show_legacy_list(
        callback.message,
        str(debt.get("student_id") or ""),
        lang,
        edit=True,
        notice=_st("legacy_deleted_ok", lang),
    )
    await callback.answer()
