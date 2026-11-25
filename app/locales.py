from typing import Any, Optional

MONTHS_UPPER_LATN: dict[int, str] = {
    1: "YANVAR",
    2: "FEVRAL",
    3: "MART",
    4: "APREL",
    5: "MAY",
    6: "IYUN",
    7: "IYUL",
    8: "AVGUST",
    9: "SENTABR",
    10: "OKTABR",
    11: "NOYABR",
    12: "DEKABR",
}

MONTHS_UZ: dict[str, dict[int, str]] = {
    "latn": {
        1: "Yanvar",
        2: "Fevral",
        3: "Mart",
        4: "Aprel",
        5: "May",
        6: "Iyun",
        7: "Iyul",
        8: "Avgust",
        9: "Sentabr",
        10: "Oktabr",
        11: "Noyabr",
        12: "Dekabr",
    },
    "cyrl": {
        1: "Январь",
        2: "Февраль",
        3: "Март",
        4: "Апрель",
        5: "Май",
        6: "Июнь",
        7: "Июль",
        8: "Август",
        9: "Сентябрь",
        10: "Октябрь",
        11: "Ноябрь",
        12: "Декабрь",
    },
}

WEEKDAYS_SHORT: dict[str, dict[int, str]] = {
    "latn": {
        0: "Dush",
        1: "Sesh",
        2: "Chor",
        3: "Pay",
        4: "Jum",
        5: "Shan",
        6: "Yak",
    },
    "cyrl": {
        0: "Душ",
        1: "Сеш",
        2: "Чор",
        3: "Пай",
        4: "Жум",
        5: "Шан",
        6: "Як",
    },
}

WEEKDAYS_FULL: dict[str, dict[int, str]] = {
    "latn": {
        0: "Dushanba",
        1: "Seshanba",
        2: "Chorshanba",
        3: "Payshanba",
        4: "Juma",
        5: "Shanba",
        6: "Yakshanba",
    },
    "cyrl": {
        0: "Душанба",
        1: "Сешанба",
        2: "Чоршанба",
        3: "Пайшанба",
        4: "Жума",
        5: "Шанба",
        6: "Якшанба",
    },
}

_WEEKDAY_TOKEN_TO_IDX: dict[str, int] = {
    "dush": 0,
    "du": 0,
    "dushanba": 0,
    "душ": 0,
    "ду": 0,
    "душанба": 0,
    "mon": 0,
    "monday": 0,
    "пн": 0,
    "понедельник": 0,
    "sesh": 1,
    "se": 1,
    "seshanba": 1,
    "сеш": 1,
    "се": 1,
    "сешанба": 1,
    "tue": 1,
    "tuesday": 1,
    "вт": 1,
    "вторник": 1,
    "chor": 2,
    "cho": 2,
    "ch": 2,
    "chorshanba": 2,
    "чор": 2,
    "чо": 2,
    "ч": 2,
    "чоршанба": 2,
    "wed": 2,
    "wednesday": 2,
    "ср": 2,
    "среда": 2,
    "pay": 3,
    "pa": 3,
    "payshanba": 3,
    "пай": 3,
    "па": 3,
    "пайшанба": 3,
    "thu": 3,
    "thursday": 3,
    "чт": 3,
    "четверг": 3,
    "jum": 4,
    "ju": 4,
    "juma": 4,
    "жум": 4,
    "жу": 4,
    "жума": 4,
    "fri": 4,
    "friday": 4,
    "пт": 4,
    "пятница": 4,
    "shan": 5,
    "sha": 5,
    "sh": 5,
    "shanba": 5,
    "шан": 5,
    "ша": 5,
    "ш": 5,
    "шанба": 5,
    "sat": 5,
    "saturday": 5,
    "сб": 5,
    "суббота": 5,
    "yak": 6,
    "ya": 6,
    "yakshanba": 6,
    "як": 6,
    "я": 6,
    "якшанба": 6,
    "sun": 6,
    "sunday": 6,
    "вс": 6,
    "воскресенье": 6,
}

FIELD_LABELS: dict[str, dict[str, str]] = {
    "latn": {
        "Guruh_Nomi": "Guruh nomi",
        "Oylik_Dars_Soni": "Oylik darslar soni",
        "Dars_Kunlari": "Dars kunlari",
        "Dars_Vaqti": "Dars vaqti",
        "Tolov_Summasi": "Oylik to'lov summasi",
        "Oylik_Tolov_Summa": "Oylik to'lov summasi",
        "Guruh_TG_Chat_ID": "Guruh Telegram kanali/guruhi",
        "Boshlanish_Sanasi": "Boshlanish sanasi",
        "Ustoz_ID": "Ustoz",
        "Ustoz": "Ustoz",
    },
    "cyrl": {
        "Guruh_Nomi": "Гуруҳ номи",
        "Oylik_Dars_Soni": "Ойлик дарслар сони",
        "Dars_Kunlari": "Дарс кунлари",
        "Dars_Vaqti": "Дарс вақти",
        "Tolov_Summasi": "Ойлик тўлов суммаси",
        "Oylik_Tolov_Summa": "Ойлик тўлов суммаси",
        "Guruh_TG_Chat_ID": "Гуруҳ Telegram канали/гуруҳи",
        "Boshlanish_Sanasi": "Бошланиш санаси",
        "Ustoz_ID": "Устоз",
        "Ustoz": "Устоз",
    },
}

TEXTS: dict[str, dict[str, str]] = {
    "latn": {
        # Language selection
        "choose_language": (
            "O‘zingizga qulay bo‘lgan tilni tanlang / "
            "Ўзингизга қулай бўлган тилни танланг:"
        ),
        "btn_lang_latn": "🇺🇿 O'zbekcha",
        "btn_lang_cyrl": "🇺🇿 Ўзбекча",
        "lang_saved": "✅ Til muvaffaqiyatli tanlandi: O'zbekcha (Lotin).",
        "btn_change_lang": "🌐 Tilni o'zgartirish",
        "self_marker": "(siz)",

        # FSM Lock Middleware
        "fsm_lock_warning": (
            "⚠️ Sizda tugallanmagan jarayon bor. Davom eting yoki "
            "«❌ Bekor qilish» tugmasini bosing."
        ),
        "fsm_cancelled": "❌ Joriy jarayon bekor qilindi.",

        # Roles & welcome
        "role_admin": "Admin",
        "role_teacher": "Ustoz",
        "role_student": "Talaba",
        "role_parent": "Ota-ona",
        "welcome_menu": (
            "Assalomu alaykum, <b>{name}</b>!\n"
            "Siz tizimga <b>{role}</b> sifatida kirdingiz.\n"
            "Kerakli bo‘limni tanlang:"
        ),
        "welcome_menu_father": (
            "Assalomu alaykum, <b>{name}</b>!\n"
            "🧔 Siz Otasi sifatida tizimga kirdingiz!\n"
            "Kerakli bo‘limni tanlang:"
        ),
        "welcome_menu_mother": (
            "Assalomu alaykum, <b>{name}</b>!\n"
            "🧕 Siz Onasi sifatida tizimga kirdingiz!\n"
            "Kerakli bo‘limni tanlang:"
        ),
        "profile_role_pick": (
            "🔄 <b>Otasi / Onasi rolini almashtirish</b>\n\n"
            "Hozirgi rolingiz: <b>{current_role}</b>\n"
            "Yangi rolni tanlang:"
        ),
        "profile_role_same": "ℹ️ Siz allaqachon <b>{role}</b> sifatida ro‘yxatdan o‘tgansiz.",
        "profile_role_switched": (
            "✅ Rolingiz <b>{role}</b> ga o‘zgartirildi.\n"
            "Barcha farzandlaringiz bo‘yicha ma'lumotlar yangilandi."
        ),
        "unregistered_user": (
            "Assalomu alaykum!\n"
            "Sizning hisobingiz hali tizimga bog‘lanmagan.\n"
            "Iltimos, ustozingiz yoki o‘quv markazi administratori yuborgan "
            "maxsus taklif havolasi orqali kiring."
        ),

        # Strict Role Lock & Admin Role-Change Request
        "role_lock_warning": (
            "⚠️ Siz tizimda «{current_role}» sifatida ro'yxatdan o'tgansiz. "
            "Boshqa rolga o'tish uchun avval eski rolingiz bekor qilinishi kerak."
        ),
        "btn_request_role_change": "📨 So'rov yuborish",
        "role_change_request_sent": (
            "✅ Rolni o'zgartirish bo'yicha so'rovingiz adminga yuborildi. "
            "Tasdiqlanishini kuting."
        ),
        "role_change_admin_card": (
            "🔄 <b>Rolni o'zgartirish so'rovi</b>\n\n"
            "👤 Foydalanuvchi: <b>{full_name}</b> (<code>{user_id}</code>)\n"
            "📌 Joriy roli: <b>{current_role}</b>\n"
            "🎯 So'ralayotgan rol: <b>{requested_role}</b>"
        ),
        "btn_role_change_approve": "✅ Almashtirish",
        "btn_role_change_reject": "❌ Rad etish",
        "role_change_approved_user": (
            "✅ Admin so'rovingizni tasdiqladi! Endi yangi rol uchun berilgan "
            "taklif havolasi ustiga qayta bosing."
        ),
        "role_change_rejected_user": (
            "❌ Kechirasiz, rolni o'zgartirish bo'yicha so'rovingiz admin tomonidan rad etildi."
        ),
        "role_change_approved_admin": (
            "✅ Foydalanuvchi (<code>{user_id}</code>) ning eski roli o'chirildi. "
            "Endi u yangi taklif havolasi orqali qayta ro'yxatdan o'tishi mumkin."
        ),
        "role_change_rejected_admin": "❌ Rolni o'zgartirish so'rovi rad etildi.",

        # Dual-Role Admin Prompt & Role Switcher
        "dual_role_admin_prompt": (
            "Foydalanuvchi {full_name} tizimda avvaldan {old_role} sifatida mavjud. "
            "Hozir esa {new_role} bo'lib ham qo'shilmoqchi. Qanday tasdiqlaymiz?"
        ),
        "btn_dual_role_keep_both": "➕ Ikkalasi qolsin",
        "btn_dual_role_replace": "🔄 Faqat yangisi",
        "btn_dual_role_reject": "❌ Rad etish",
        "btn_switch_to_parent": "👨‍👩‍👧 Ota-ona rejimi",
        "btn_switch_to_student": "🎓 Talaba rejimi",
        "notif_role_header_student": "🎓 <b>Shaxsiy darsingiz bo'yicha:</b>",
        "notif_role_header_parent": "👨‍👩‍👧 <b>Farzandingiz {talaba_ismi} bo'yicha:</b>",

        # Mandatory Name + Phone Sharing (Shared)
        "btn_share_phone": "📱 Telefon raqamni ulashish",
        "use_contact_button_only": (
            "⚠️ Iltimos, telefon raqamingizni qo‘lda yozmang — pastdagi "
            "«📱 Telefon raqamni ulashish» tugmasini bosing."
        ),
        "own_contact_only": (
            "⚠️ Iltimos, faqat o‘zingizning telefon raqamingizni ulashing."
        ),

        # Teacher invite & self-registration
        "teacher_invite_btn": "👨‍🏫 Ustoz qo‘shish",
        "teacher_add_enter_name": (
            "👨‍🏫 <b>Yangi ustoz taklif havolasi</b>\n\n"
            "Ustozning haqiqiy <b>Familiya va Ismini</b> kiriting "
            "(masalan: <i>Karimov Sardor</i>):"
        ),
        "teacher_add_invalid_name": (
            "❌ Iltimos, ustozning Familiya va Ismini to‘liq kiriting "
            "(kamida 2 ta so‘z, masalan: <i>Karimov Sardor</i>):"
        ),
        "teacher_add_created": (
            "✅ <b>Ustoz taklif havolasi yaratildi!</b>\n\n"
            "👨‍🏫 Ustoz: <b>{full_name}</b>\n"
            "🔗 Bir martalik havola:\n<code>{invite_link}</code>\n\n"
            "Ushbu havolani ustozga yuboring. Ustoz botga kirib, ismi va telefon raqamini "
            "tasdiqlagach avtomatik ravishda tizimga qo‘shiladi."
        ),
        "teacher_add_cancelled": "❌ Ustoz taklif havolasini yaratish bekor qilindi.",
        "teacher_link_invalid": (
            "❌ Kechirasiz, ushbu ustoz taklif havolasi yaroqsiz yoki allaqachon ishlatilgan."
        ),
        "teacher_self_reg_enter_name": (
            "👨‍🏫 <b>Ustoz sifatida ro‘yxatdan o‘tish</b>\n\n"
            "✍️ Iltimos, haqiqiy <b>Familiya va Ismingizni</b> to‘liq kiriting "
            "(masalan: <i>Karimov Sardor</i>):"
        ),
        "teacher_self_reg_invalid_name": (
            "❌ Iltimos, Familiya va Ismingizni to‘liq yozing (kamida 2 ta so‘z, "
            "masalan: <i>Karimov Sardor</i>):"
        ),
        "teacher_self_reg_share_phone": (
            "📱 Rahmat, <b>{full_name}</b>!\n"
            "Ro‘yxatdan o‘tishni yakunlash uchun pastdagi "
            "«📱 Telefon raqamni ulashish» tugmasini bosing:"
        ),
        "teacher_link_success": (
            "✅ Assalomu alaykum, <b>{teacher_name}</b>!\n"
            "Siz tizimga <b>Ustoz</b> sifatida muvaffaqiyatli qo‘shildingiz."
        ),

        # Admin Teacher Management (👨‍🏫 Ustozlar boshqaruvi)
        "menu_admin_manage_teachers": "👨‍🏫 Ustozlar",
        "teacher_manage_title": (
            "👨‍🏫 <b>Ustozlar boshqaruvi</b>\n\n"
            "Ro‘yxatdan o‘tgan ustozlardan birini tanlang yoki yangi ustoz taklif havolasini yarating:"
        ),
        "teacher_manage_list_header": (
            "👨‍🏫 <b>Ustozlar ro‘yxati:</b>\n"
            "Batafsil ma'lumot va boshqarish uchun ustozni tanlang:"
        ),
        "teacher_manage_empty": "ℹ️ Hozircha ro‘yxatdan o‘tgan ustozlar mavjud emas.",
        "teacher_manage_card": (
            "👨‍🏫 <b>Ustoz ma'lumotlari</b>\n\n"
            "🆔 Ustoz ID: <code>{teacher_id}</code>\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📞 Telefon: {phone}\n"
            "💬 Telegram: {tg}\n"
            "📚 Biriktirilgan guruhlar: <b>{groups}</b>"
        ),
        "teacher_manage_no_groups": "Hali biriktirilmagan",
        "teacher_manage_btn_assign": "🔗 Guruh biriktirish",
        "teacher_manage_btn_delete": "🗑 Ustozni o‘chirish",
        "teacher_manage_assign_select_group": (
            "📚 <b>{full_name}</b> ustozni biriktirmoqchi bo‘lgan guruhni tanlang:"
        ),
        "teacher_manage_assign_no_groups": "ℹ️ Hozircha tizimda guruhlar mavjud emas.",
        "teacher_manage_assign_success_admin": (
            "✅ Ustoz <b>{full_name}</b> muvaffaqiyatli ravishda "
            "<b>{group}</b> guruhiga biriktirildi!"
        ),
        "teacher_manage_assign_notify_teacher": (
            "👨‍🏫 Siz <b>{group}</b> guruhiga ustoz sifatida biriktirildingiz!"
        ),
        "teacher_manage_delete_confirm": (
            "🗑 <b>Ustozni o‘chirishni tasdiqlaysizmi?</b>\n\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "🆔 Ustoz ID: <code>{teacher_id}</code>\n"
            "📚 Biriktirilgan guruhlar: <b>{groups}</b>\n\n"
            "<i>Diqqat: Ustoz o‘chirilsa, unga biriktirilgan barcha guruhlardan ustoz ma'lumoti tozalanadi.</i>"
        ),
        "teacher_manage_delete_success": (
            "✅ Ustoz <b>{full_name}</b> tizimdan muvaffaqiyatli o‘chirildi."
        ),
        "teacher_manage_delete_purged": (
            "\n🧹 Ustozning bot hisobi va guruh biriktirmalari to‘liq tozalandi.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "teacher_manage_delete_notify_teacher": (
            "ℹ️ Sizning ustozlik hisobingiz administrator tomonidan tizimdan o‘chirildi."
        ),
        "teacher_manage_cancelled": "❌ Ustozlar boshqaruvi yopildi.",

        # Student Group Transfer / Dual Enrollment
        "stu_transfer_keep_question": (
            "Talaba <b>{student_name}</b> avvalgi «<b>{old_group}</b>» guruhida ham qoldirilsinmi?\n\n"
            "➡️ Yangi tanlangan guruh: <b>{new_group}</b>"
        ),
        "btn_stu_transfer_keep": "✅ Ikkalasida qolsin",
        "btn_stu_transfer_move": "🔀 Faqat yangisida",
        "stu_transfer_success_dual_admin": (
            "✅ <b>Talaba qo‘shimcha guruhga qo‘shildi!</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Avvalgi guruh: <b>{old_group}</b> (saqlab qolindi)\n"
            "➕ Yangi guruh: <b>{new_group}</b> (🆔 <code>{new_student_id}</code>)"
        ),
        "stu_transfer_success_move_admin": (
            "✅ <b>Talaba yangi guruhga o‘tkazildi!</b>\n\n"
            "👤 Talaba: <b>{student_name}</b> (<code>{student_id}</code>)\n"
            "📤 Avvalgi guruh: <b>{old_group}</b>\n"
            "📥 Yangi guruh: <b>{new_group}</b>"
        ),
        "stu_transfer_notify_dual_student": (
            "🎉 <b>Yangi guruhga qo‘shildingiz!</b>\n\n"
            "Assalomu alaykum, <b>{student_name}</b>!\n"
            "Siz avvalgi «<b>{old_group}</b>» guruhingizda qolgan holda qo‘shimcha ravishda "
            "«<b>{new_group}</b>» guruhiga ham qabul qilindingiz.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "stu_transfer_notify_move_student": (
            "🔄 <b>Guruhingiz o‘zgartirildi!</b>\n\n"
            "Assalomu alaykum, <b>{student_name}</b>!\n"
            "Siz «<b>{old_group}</b>» guruhidan «<b>{new_group}</b>» guruhiga o‘tkazildingiz.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "stu_transfer_notify_dual_father": (
            "📚 <b>Qo‘shimcha guruh xabarnomasi</b>\n\n"
            "Assalomu alaykum, hurmatli <b>{parent_name}</b>!\n"
            "Farzandingiz <b>{student_name}</b> avvalgi «<b>{old_group}</b>» guruhida o‘qishini "
            "davom ettirgan holda qo‘shimcha ravishda «<b>{new_group}</b>» guruhiga ham qo‘shildi.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "stu_transfer_notify_dual_mother": (
            "📚 <b>Qo‘shimcha guruh xabarnomasi</b>\n\n"
            "Assalomu alaykum, hurmatli <b>{parent_name}</b>!\n"
            "Farzandingiz <b>{student_name}</b> avvalgi «<b>{old_group}</b>» guruhida o‘qishini "
            "davom ettirgan holda qo‘shimcha ravishda «<b>{new_group}</b>» guruhiga ham qo‘shildi.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "stu_transfer_notify_move_father": (
            "🔄 <b>Guruh o‘zgarishi xabarnomasi</b>\n\n"
            "Assalomu alaykum, hurmatli <b>{parent_name}</b>!\n"
            "Farzandingiz <b>{student_name}</b> «<b>{old_group}</b>» guruhidan "
            "«<b>{new_group}</b>» guruhiga o‘tkazildi.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "stu_transfer_notify_move_mother": (
            "🔄 <b>Guruh o‘zgarishi xabarnomasi</b>\n\n"
            "Assalomu alaykum, hurmatli <b>{parent_name}</b>!\n"
            "Farzandingiz <b>{student_name}</b> «<b>{old_group}</b>» guruhidan "
            "«<b>{new_group}</b>» guruhiga o‘tkazildi.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "stu_transfer_notify_new_teacher": (
            "👨‍🏫 <b>Guruhingizga talaba qo‘shildi!</b>\n\n"
            "📚 Guruh: <b>{new_group}</b>\n"
            "👤 Talaba: <b>{student_name}</b> (<code>{student_id}</code>)\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "stu_transfer_notify_old_teacher_moved": (
            "ℹ️ <b>Talaba boshqa guruhga o‘tkazildi</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📤 Avvalgi guruh: <b>{old_group}</b>\n"
            "📥 Yangi guruh: <b>{new_group}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),

        # Admin Management & Invite (?start=adm_<CODE>)
        "menu_admin_manage_admins": "👑 Adminlar",
        "admin_manage_title": (
            "👑 <b>Adminlar boshqaruvi</b>\n\n"
            "Yangi admin taklif qilish, mavjud adminlar ro‘yxatini ko‘rish yoki "
            "adminni tizimdan o‘chirish uchun kerakli amalni tanlang:"
        ),
        "btn_admin_create_invite": "🔗 Yangi havola",
        "btn_admin_list": "📋 Adminlar ro‘yxati",
        "btn_admin_remove": "🗑 Adminni o‘chirish",
        "admin_invite_created": (
            "✅ <b>Yangi admin taklif havolasi yaratildi!</b>\n\n"
            "🔗 Bir martalik havola:\n<code>{invite_link}</code>\n\n"
            "Ushbu havolani bo‘lajak adminga yuboring. Havola orqali kirib, ism va "
            "telefon raqamini tasdiqlagach avtomatik ravishda <b>Admin</b> bo‘ladi."
        ),
        "admin_invite_invalid": (
            "❌ Kechirasiz, ushbu admin taklif havolasi yaroqsiz yoki allaqachon ishlatilgan."
        ),
        "admin_reg_enter_name": (
            "👑 <b>Admin sifatida ro‘yxatdan o‘tish</b>\n\n"
            "✍️ Iltimos, haqiqiy <b>Familiya va Ismingizni</b> to‘liq kiriting "
            "(masalan: <i>Karimov Sardor</i>):"
        ),
        "admin_reg_invalid_name": (
            "❌ Iltimos, Familiya va Ismingizni to‘liq yozing (kamida 2 ta so‘z, "
            "masalan: <i>Karimov Sardor</i>):"
        ),
        "admin_reg_share_phone": (
            "📱 Rahmat, <b>{full_name}</b>!\n"
            "Admin sifatida ro‘yxatdan o‘tishni yakunlash uchun pastdagi "
            "«📱 Telefon raqamni ulashish» tugmasini bosing:"
        ),
        "admin_reg_success": (
            "✅ Assalomu alaykum, <b>{full_name}</b>!\n"
            "Siz tizimga <b>Admin</b> sifatida muvaffaqiyatli qo‘shildingiz."
        ),
        "admin_reg_notify_inviter": (
            "👑 <b>Yangi admin qo‘shildi!</b>\n\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📞 Telefon: <b>{phone}</b>\n"
            "🆔 Telegram ID: <code>{telegram_id}</code>"
        ),
        "admin_list_header": "👑 <b>Tizim adminlari ro‘yxati:</b>\n",
        "admin_list_super_item": "• 🛡 <b>Bosh Admin</b> (<code>{telegram_id}</code>)",
        "admin_list_dynamic_item": (
            "• 👤 <b>{full_name}</b> (<code>{telegram_id}</code>) | 📞 {phone}"
        ),
        "admin_list_empty": "ℹ️ Hozircha qo‘shimcha adminlar mavjud emas.",
        "admin_remove_select": "🗑 Tizimdan o‘chirmoqchi bo‘lgan adminni tanlang:",
        "admin_remove_confirm": (
            "🗑 <b>Adminni o‘chirishni tasdiqlaysizmi?</b>\n\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "🆔 Telegram ID: <code>{telegram_id}</code>"
        ),
        "admin_removed_success": (
            "✅ Admin <b>{full_name}</b> tizimdan muvaffaqiyatli o‘chirildi."
        ),
        "admin_cannot_remove_self": (
            "⚠️ O‘zingizni adminlikdan o‘chira olmaysiz."
        ),
        "admin_manage_cancelled": "❌ Adminlar boshqaruvi yopildi.",

        # Student & Parent deep-link registration
        "link_student_not_found": (
            "❌ Kechirasiz, <code>{student_id}</code> ID raqamli talaba bazadan topilmadi. "
            "Admin yoki ustoz bilan bog‘laning."
        ),
        "student_reg_enter_name": (
            "🎓 <b>Talaba sifatida ro‘yxatdan o‘tish</b>\n"
            "📚 Guruh: <b>{group}</b>\n\n"
            "✍️ Iltimos, haqiqiy <b>Familiya va Ismingizni</b> to‘liq kiriting "
            "(masalan: <i>Aliyev Vali</i>):"
        ),
        "student_reg_invalid_name": (
            "❌ Iltimos, Familiya va Ismingizni to‘liq yozing (kamida 2 ta so‘z, "
            "masalan: <i>Aliyev Vali</i>):"
        ),
        "student_reg_share_phone": (
            "📱 Rahmat, <b>{full_name}</b>!\n"
            "Endi pastdagi «📱 Telefon raqamni ulashish» tugmasi orqali "
            "o‘zingizning telefon raqamingizni yuboring:"
        ),
        "link_success_student": (
            "✅ Assalomu alaykum, <b>{student_name}</b>!\n"
            "Sizning Telegram hisobingiz <b>{group}</b> guruhiga talaba sifatida muvaffaqiyatli bog‘landi."
        ),
        "parent_reg_choose_type": (
            "👨‍👩‍👧 <b>Ota-ona sifatida ro‘yxatdan o‘tish</b>\n\n"
            "👤 Talaba: <b>{student_name}</b> ({group})\n"
            "Iltimos, kim ekanligingizni tanlang:"
        ),
        "btn_parent_father": "🧔 Otasi",
        "btn_parent_mother": "🧕 Onasi",
        "parent_label_father": "Otasi",
        "parent_label_mother": "Onasi",
        "parent_reg_enter_name": (
            "✍️ Iltimos, haqiqiy <b>Familiya va Ismingizni</b> to‘liq kiriting "
            "(masalan: <i>Aliyev Olim</i>):"
        ),
        "parent_reg_invalid_name": (
            "❌ Iltimos, Familiya va Ismingizni to‘liq yozing (kamida 2 ta so‘z):"
        ),
        "parent_reg_share_phone": (
            "📱 Rahmat, <b>{full_name}</b>!\n"
            "Endi farzandingiz darslari va to‘lovlari haqida xabarnoma olish uchun "
            "pastdagi «📱 Telefon raqamni ulashish» tugmasini bosing:"
        ),
        "link_success_parent": (
            "✅ Assalomu alaykum, <b>{parent_name}</b>!\n"
            "Sizning Telegram hisobingiz <b>{student_name}</b> ({group} guruhi) "
            "uchun <b>{parent_role}</b> sifatida muvaffaqiyatli bog‘landi."
        ),
        "btn_student_no_phone": "📵 Telefon yo‘q",
        "btn_add_children_via_parent": "👨‍👩‍👧‍👦 Ota-ona orqali",

        # Personal Profile Editing
        "menu_profile": "⚙️ Ma'lumotlarim",
        "profile_view_admin": (
            "👤 <b>Shaxsiy ma'lumotlarim (Admin)</b>\n\n"
            "🆔 Telegram ID: <code>{user_id}</code>\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📞 Telefon: <b>{phone}</b>\n"
            "✈️ Telegram: <b>{tg}</b>"
        ),
        "menu_guest_courses": "📚 Kurslarimiz",
        "menu_guest_enroll": "✍️ Kursga yozilish",
        "menu_guest_contact": "📍 Manzil va aloqa",
        "menu_admin_courses": "📚 Kurslarni boshqarish",
        "guest_welcome": (
            "Assalomu alaykum, <b>{name}</b>! 🌟\n\n"
            "<b>Mishkat Nodavlat Ta'lim Muassasasi</b>ning rasmiy botiga xush kelibsiz!\n\n"
            "Bu yerda siz:\n"
            "📚 kurslarimiz va narxlari bilan tanishishingiz,\n"
            "✍️ o‘zingizga ma'qul kursga ariza qoldirishingiz,\n"
            "📍 manzil va aloqa ma'lumotlarini olishingiz mumkin.\n\n"
            "Agar siz allaqachon o‘quvchimiz (yoki ota-ona) bo‘lsangiz, ustozingiz yoki "
            "administrator yuborgan maxsus taklif havolasi orqali kiring.\n\n"
            "Kerakli bo‘limni tanlang 👇"
        ),
        "profile_view_teacher": (
            "👤 <b>Shaxsiy ma'lumotlarim (Ustoz)</b>\n\n"
            "🆔 Ustoz ID: <code>{teacher_id}</code>\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📞 Telefon: <b>{phone}</b>\n"
            "✈️ Telegram: <b>{tg}</b>"
        ),
        "profile_view_student": (
            "👤 <b>Shaxsiy ma'lumotlarim (Talaba)</b>\n\n"
            "🆔 Talaba ID: <code>{student_id}</code>\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📞 Telefon: <b>{phone}</b>\n"
            "✈️ Telegram: <b>{tg}</b>"
        ),
        "profile_view_parent": (
            "👤 <b>Shaxsiy ma'lumotlarim ({parent_role})</b>\n\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📞 Telefon: <b>{phone}</b>\n"
            "🎓 Farzandingiz: <b>{student_name}</b> ({group})"
        ),
        "profile_enter_new_name": "✍️ Yangi <b>Familiya va Ismingizni</b> kiriting:",
        "profile_share_new_phone": (
            "📱 Yangi telefon raqamingizni yuborish uchun pastdagi "
            "«📱 Telefon raqamni ulashish» tugmasini bosing:"
        ),
        "profile_updated": "✅ Shaxsiy ma'lumotlaringiz muvaffaqiyatli yangilandi!",

        # Group linking
        "link_group_private_error": (
            "ℹ️ Ushbu buyruq faqat Telegram guruh chatining ichida ishlaydi:\n"
            "<code>/link_group Guruh_Nomi</code>"
        ),
        "link_group_usage": (
            "ℹ️ Guruh nomini kiriting. Masalan:\n"
            "<code>/link_group Frontend</code>"
        ),
        "link_group_no_permission": (
            "❌ Sizda bu guruhni ulash uchun ruxsat yo‘q. "
            "Faqat Admin yoki ushbu guruhning ustozi ulashi mumkin."
        ),
        "link_group_not_found": (
            "❌ <b>{group}</b> nomli guruh Google Sheets'dagi «Guruhlar» jadvalida topilmadi."
        ),
        "link_group_success": (
            "✅ Ushbu Telegram guruhi <b>{group}</b> guruhi bilan muvaffaqiyatli bog‘landi!"
        ),

        # Student Group Self-Join (?start=join_<Group>)
        "join_group_not_found": (
            "❌ Kechirasiz, bunday guruh topilmadi. Havolani tekshirib qayta urinib ko‘ring."
        ),
        "join_already_in_group": (
            "ℹ️ <b>{student_name}</b>, siz allaqachon <b>{group}</b> guruhiga a'zosiz!"
        ),
        "join_enter_full_name": (
            "📚 <b>{group}</b> guruhiga ro‘yxatdan o‘tish.\n\n"
            "✍️ Iltimos, haqiqiy <b>Familiya va Ismingizni</b> to‘liq kiriting "
            "(masalan: <i>Aliyev Vali</i>):"
        ),
        "join_invalid_full_name": (
            "❌ Iltimos, Familiya va Ismingizni to‘liq yozing (kamida 2 ta so‘z, "
            "masalan: <i>Aliyev Vali</i>):"
        ),
        "join_share_phone": (
            "📱 Rahmat, <b>{full_name}</b>!\n"
            "Endi quyidagi «📱 Telefon raqamni ulashish» tugmasi orqali "
            "telefon raqamingizni yuboring:"
        ),
        "join_btn_share_phone": "📱 Telefon raqamni ulashish",
        "join_use_contact_button": (
            "⚠️ Iltimos, raqamni qo‘lda yozmang — pastdagi "
            "«📱 Telefon raqamni ulashish» tugmasini bosing."
        ),
        "join_own_contact_only": (
            "⚠️ Iltimos, faqat o‘zingizning telefon raqamingizni ulashing."
        ),
        "join_request_sent": (
            "⏳ <b>So‘rovingiz yuborildi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📞 Telefon: <b>{phone}</b>\n\n"
            "Ustoz yoki administrator tasdiqlashini kuting."
        ),
        "join_cancelled": "❌ Guruhga ro‘yxatdan o‘tish bekor qilindi.",
        "join_approval_card": (
            "🆕 <b>Guruhga qo‘shilish so‘rovi</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "👤 F.I.O.: <b>{full_name}</b>\n"
            "📞 Telefon: <b>{phone}</b>\n"
            "💬 Telegram: {tg}\n\n"
            "Talabani guruhga qabul qilasizmi?"
        ),
        "join_btn_approve": "✅ Tasdiqlash",
        "join_btn_reject": "❌ Rad etish",
        "join_already_processed": "ℹ️ Ushbu so‘rov allaqachon ko‘rib chiqilgan.",
        "join_no_permission": "❌ Sizda ushbu so‘rovni tasdiqlash huquqi yo‘q.",
        "join_approved_card": (
            "✅ <b>So‘rov tasdiqlandi!</b>\n"
            "👤 Talaba: <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "📚 Guruh: <b>{group}</b>"
        ),
        "join_rejected_card": (
            "❌ <b>So‘rov rad etildi.</b>\n"
            "👤 Talaba: <b>{full_name}</b>\n"
            "📚 Guruh: <b>{group}</b>"
        ),
        "join_approved_student": (
            "🎉 <b>Tabriklaymiz, {full_name}!</b>\n"
            "Sizning <b>{group}</b> guruhiga qo‘shilish so‘rovingiz tasdiqlandi.\n"
            "🆔 Talaba ID: <code>{student_id}</code>"
        ),
        "join_rejected_student": (
            "❌ Kechirasiz, sizning <b>{group}</b> guruhiga qo‘shilish so‘rovingiz rad etildi."
        ),

        # Group Management, Full Update Wizard & Group Price Setup
        "group_menu_title": "📚 <b>Guruhlar bo‘limi</b>\nKerakli amalni tanlang:",
        "group_edit_select": "✏️ Tahrirlash uchun guruhni tanlang:",
        "group_edit_info": (
            "📚 <b>Guruh: {group}</b>\n\n"
            "👨‍🏫 Ustoz: <b>{teacher_name}</b>\n"
            "🔢 Oylik darslar: <b>{count} ta</b>\n"
            "📆 Kunlar: <b>{days}</b>\n"
            "⏰ Vaqt: <b>{time}</b>\n\n"
            "Qaysi ma'lumotni o‘zgartirmoqchisiz?"
        ),
        "group_edit_info_with_price": (
            "📚 <b>Guruh: {group}</b>\n\n"
            "👨‍🏫 Ustoz: <b>{teacher_name}</b>\n"
            "🔢 Oylik darslar: <b>{count} ta</b>\n"
            "📆 Kunlar: <b>{days}</b>\n"
            "⏰ Vaqt: <b>{time}</b>\n"
            "💰 Oylik to‘lov: <b>{price}</b>\n\n"
            "Qaysi ma'lumotni o‘zgartirmoqchisiz?"
        ),
        "group_edit_saved": "✅ <b>{group}</b> guruhi ma'lumotlari yangilandi!",
        "btn_group_price": "💰 To‘lov summasi",
        "btn_group_full_update": "🔄 To‘liq yangilash",
        "btn_archive_group": "🗄 Zaxira guruhi",
        "btn_delete_group": "🗑 Guruhni o'chirish",
        "btn_keep_current": "⏭ Eskisi qolsin",
        # Admin "✏️ Guruhni tahrirlash" panel: one button per group attribute
        "btn_grp_edit_name": "📝 Guruh nomini o‘zgartirish",
        "btn_grp_edit_teacher": "👨‍🏫 Ustozni o‘zgartirish",
        "btn_grp_edit_days": "📆 Dars kunlarini o‘zgartirish",
        "btn_grp_edit_time": "⏰ Dars vaqtini o‘zgartirish",
        "btn_grp_edit_price": "💰 Oylik to‘lovni o‘zgartirish",
        "btn_grp_edit_count": "🔢 Oylik darslar sonini o‘zgartirish",
        "btn_grp_edit_chat": "💬 Guruh chat ID ni o‘zgartirish",
        "btn_grp_edit_start": "📅 Boshlanish sanasini o‘zgartirish",
        "group_edit_extra_info": (
            "📅 Boshlanish sanasi: <b>{start}</b>\n"
            "💬 Guruh chat ID: <code>{chat}</code>"
        ),
        "grp_edit_enter_chat_id": (
            "💬 <b>{group}</b> — guruh Telegram chat ID sini o‘zgartirish\n\n"
            "Joriy chat ID: <code>{current}</code>\n\n"
            "Yangi chat ID ni kiriting (masalan: <code>-1001234567890</code>):"
        ),
        "grp_edit_invalid_chat_id": (
            "❌ Chat ID noto‘g‘ri. Faqat raqamlardan iborat bo‘lishi kerak "
            "(masalan: <code>-1001234567890</code>). Qaytadan kiriting:"
        ),
        "grp_edit_chat_saved": (
            "✅ <b>{group}</b> guruhining chat ID si yangilandi: <code>{chat}</code>"
        ),
        "grp_edit_start_calendar_title": (
            "📅 <b>{group}</b> — boshlanish sanasini o‘zgartirish\n\n"
            "Joriy boshlanish sanasi: <b>{current}</b>\n"
            "Dars kunlari: <b>{days}</b> | Oylik darslar: <b>{count} ta</b>\n\n"
            "Kalendardan yangi boshlanish sanasini tanlang. Joriy siklning "
            "barcha dars sanalari shu kundan boshlab qayta tuziladi:"
        ),
        "grp_edit_start_saved": (
            "✅ <b>{group}</b> guruhining boshlanish sanasi yangilandi!\n\n"
            "📅 Boshlanish: <b>{start}</b>\n"
            "🏁 Tugash: <b>{end}</b>\n"
            "🔢 O‘tilgan darslar: <b>{elapsed}/{total}</b>\n\n"
            "🗓 <b>Yangi dars jadvali:</b>\n{schedule}"
        ),
        "grp_edit_start_all_past": (
            "⚠️ Bu sanadan boshlangan siklning barcha darslari allaqachon o‘tib ketgan. "
            "Iltimos, yaqinroq sanani tanlang."
        ),
        "grp_edit_start_year_mismatch": (
            "⚠️ Joriy sikl {year}-yil jadvalida joylashgan. Iltimos, {year}-yil "
            "ichidagi sanani tanlang."
        ),
        "grp_edit_start_no_days": (
            "⚠️ Avval guruhning dars kunlarini belgilang."
        ),
        "grp_edit_start_nearest": "📅 {date} — eng yaqin dars kuni",
        "callback_token_expired": (
            "⌛️ Bu tugma eskirgan. Iltimos, menyudan qaytadan tanlang."
        ),
        "group_full_edit_name": (
            "1/6 📝 <b>Guruh nomi</b>\n"
            "Hozirgi qiymat: <b>{current}</b>\n"
            "Yangi guruh nomini kiriting yoki «⏭ Eski holatida qoldirish» tugmasini bosing:"
        ),
        "group_full_edit_count": (
            "2/6 🔢 <b>Oylik darslar soni</b>\n"
            "Hozirgi qiymat: <b>{current} ta</b>\n"
            "Yangi dars sonini tanlang yoki eski holatida qoldiring:"
        ),
        "group_full_edit_days": (
            "3/6 📆 <b>Dars kunlari</b>\n"
            "Hozirgi qiymat: <b>{current}</b>\n"
            "Hafta kunlarini belgilang yoki eski holatida qoldiring:"
        ),
        "group_full_edit_time": (
            "4/6 ⏰ <b>Dars vaqti</b>\n"
            "Hozirgi qiymat: <b>{current}</b>\n"
            "Dars vaqtini qanday belgilashni tanlang yoki eski holatida qoldiring:"
        ),
        "group_full_edit_price": (
            "5/6 💰 <b>Oylik to'lov summasi</b>\n"
            "Hozirgi qiymat: <b>{current}</b>\n"
            "Yangi summani kiriting (ming so'mda, masalan <code>500</code>) yoki eski holatida qoldiring:"
        ),
        "group_full_edit_tg_chat": (
            "6/6 💬 <b>Guruh Telegram Chat ID</b>\n"
            "Hozirgi qiymat: <b>{current}</b>\n"
            "Yangi Telegram Chat ID kiriting (masalan <code>-1001234567890</code>) yoki eski holatida qoldiring:"
        ),
        "group_change_broadcast": (
            "📢 <b>Guruh ma'lumotlari yangilandi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "👨‍🏫 Ustoz: <b>{teacher_name}</b>\n"
            "📆 Kunlar: <b>{days}</b> | ⏰ Vaqt: <b>{time}</b>\n"
            "🔢 Oylik darslar: <b>{count} ta</b>\n"
            "💰 Oylik to'lov: <b>{price}</b>\n\n"
            "<i>O'zgarishlar: {changes}</i>"
        ),
        "group_price_select_group": "💰 Oylik to‘lov summasini belgilash uchun guruhni tanlang:",
        "group_price_enter": (
            "💰 <b>{group} — Guruh to‘lov summasi</b>\n\n"
            "Oylik to‘lov summasini ming so‘mda kiriting.\n"
            "💡 <i>Masalan:</i> <code>500</code> yozsangiz — avtomatik ravishda "
            "<b>500 000 so‘m</b> deb saqlanadi (yoki to‘liq <code>500000</code> kiriting):"
        ),
        "group_price_invalid": (
            "❌ Noto‘g‘ri summa kiritildi. Iltimos, faqat musbat son kiriting "
            "(masalan: <code>500</code> → 500 000 so‘m)."
        ),
        "group_price_saved": (
            "✅ <b>{group}</b> guruhi uchun oylik to‘lov summasi saqlandi: <b>{price}</b>."
        ),
        "group_price_not_set": "Belgilanmagan",
        "student_add_choose_method": (
            "➕ <b>Yangi talaba qo‘shish</b>\n\n"
            "Talabani qanday usulda qo‘shmoqchisiz?"
        ),
        "student_invite_link_created": (
            "🔗 <b>Talaba taklif havolasi yaratildi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "👉 Havola:\n<code>{invite_link}</code>\n\n"
            "Talaba ushbu havola orqali kirib, o‘z ismi va telefon raqamini yuborgach, "
            "sizga tasdiqlash uchun so‘rov keladi."
        ),

        # Common buttons
        "btn_back": "⬅️ Orqaga",
        "btn_cancel": "❌ Bekor qilish",
        "btn_confirm": "✅ Tasdiqlash",
        "btn_edit": "✏️ O‘zgartirish",
        "btn_details": "📄 Batafsil",
        "btn_detailed": "📄 Batafsil",
        "btn_compact": "🔼 Qisqacha",
        "btn_short": "📋 Qisqacha",
        "btn_present": "🟢 Qatnashdi",
        "btn_absent": "🔴 Kelmadi",
        "btn_finish": "✅ Yakunlash",

        # Admin menu buttons
        "menu_admin_groups": "📚 Guruhlar",
        "menu_admin_students": "👥 Talabalar",
        "menu_admin_schedule": "📅 Dars jadvali",
        "menu_admin_cancel_lesson": "🚫 Darsni bekor qilish",
        "menu_admin_attendance": "📋 Yo‘qlama qilish",
        "menu_admin_payments": "💳 To‘lovlar",
        "menu_admin_debtors": "⚠️ Qarzdorlar",

        # Teacher menu buttons
        "menu_teacher_topic": "📝 Dars mavzusi",
        "menu_teacher_groups": "👥 Guruhlarim",
        "menu_teacher_attendance": "📋 Yo‘qlama qilish",
        "menu_teacher_add_student": "➕ Talaba qo‘shish",
        "menu_teacher_schedule": "📅 Dars jadvali",
        "menu_teacher_cancel_lesson": "🚫 Darsni bekor qilish",
        "menu_teacher_payments": "💳 To‘lovlar",
        "menu_teacher_debtors": "⚠️ Qarzdorlar",

        # Teacher detailed group roster view
        "teacher_roster_header": (
            "📚 <b>Guruh: {group}</b>\n"
            "👨‍🏫 Ustoz: <b>{teacher_name}</b>\n"
            "📆 Dars kunlari: <b>{days}</b> | ⏰ Vaqt: <b>{time}</b>\n"
            "🔢 Sikl: <b>{count} ta dars</b> | 👥 Jami faol talabalar: <b>{total} ta</b>\n\n"
            "🔗 Talabalar o‘zi qo‘shilish havolasi:\n<code>{join_link}</code>\n\n"
            "<b>Talabalar va ota-onalar ro‘yxati:</b>"
        ),
        "roster_student_line": (
            "{idx}. <b>{full_name}</b>\n"
            "   📞 Talaba: {phone} | 💬 {tg}"
        ),
        "roster_father_line": "   🧔‍♂️ Otasi: <b>{father_name}</b> | 📞 {father_phone}",
        "roster_mother_line": "   🧕 Onasi: <b>{mother_name}</b> | 📞 {mother_phone}",
        "roster_bot_status_line": "   🤖 Bot: Talaba ({stu_status}), Ota-ona ({par_status})",

        # Lesson Topic & Plan builder + Polite 1-Day Reminder
        "menu_lesson_topic": "📝 Dars mavzusi",
        "btn_enter_topic_plan": "📝 Mavzu/reja kiritish",
        "btn_past_topics_history": "📚 Mavzular tarixi",
        "topic_history_header": "📚 <b>{group} — Oldingi kiritilgan mavzular:</b>\n",
        "topic_history_empty": "ℹ️ Ushbu guruh uchun hali mavzu va reja kiritilmagan.",
        "reminder_teacher_1day_before": (
            "Assalomu alaykum, hurmatli <b>{teacher_name}</b> ustoz!\n"
            "Ertaga «<b>{group_name}</b>» guruhida darsingiz bor.\n"
            "Talabalar va ota-onalar oldindan tayyorlanishlari uchun ertangi dars "
            "mavzusi va rejasini kiritib qo'yishingizni iltimos qilamiz."
        ),
        "topic_select_group": "📝 Dars mavzusi va rejasini kiritish uchun guruhni tanlang:",
        "topic_select_date": (
            "📅 <b>{group}</b> — qaysi dars sanasi uchun mavzu va reja kiritasiz?"
        ),
        "topic_existing_view": (
            "📝 <b>Saqlangan dars mavzusi va rejasi</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📅 Sana: <b>{date}</b>\n"
            "📖 Mavzu: <b>{topic_title}</b>\n"
            "📋 Mazmuni / Uyga vazifa:\n<i>{lesson_details}</i>"
        ),
        "topic_enter_title": (
            "📖 <b>{group} ({date})</b> darsi uchun <b>Mavzu</b> nomini kiriting:"
        ),
        "topic_invalid_title": (
            "❌ Mavzu nomi bo‘sh bo‘lishi mumkin emas. Iltimos, mavzuni kiriting:"
        ),
        "topic_enter_details": (
            "📋 Rahmat! Endi ushbu darsda <b>nimalar o‘tilishi / dars mazmuni va uyga vazifa</b> "
            "haqida yozing:"
        ),
        "topic_invalid_details": (
            "❌ Iltimos, dars mazmunini kiriting (kamida bir nechta so‘z):"
        ),
        "topic_confirm_preview": (
            "📝 <b>Dars mavzusi va rejasi tayyor!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📅 Sana: <b>{date}</b>\n"
            "📖 Mavzu: <b>{topic_title}</b>\n"
            "📋 Nimalar o‘tiladi / Vazifa:\n<i>{lesson_details}</i>\n\n"
            "Ma'lumotni saqlab, guruh chatiga yuboramizmi?"
        ),
        "btn_topic_broadcast": "📢 Guruhga yuborish",
        "btn_send_to_group": "📢 Guruhga yuborish",
        "btn_topic_save_only": "💾 Faqat saqlash",
        "btn_topic_edit": "✏️ Tahrirlash",
        "topic_status_added": "➕ Mavzularga qo'shimcha kiritildi",
        "topic_status_updated": "✏️ Dars mavzusi o'zgartirildi",
        "topic_teacher_footer": "Hurmat bilan, guruh ustozi {teacher_name}",
        "topic_saved": (
            "✅ <b>{group} ({date})</b> uchun dars mavzusi va rejasi saqlandi!"
        ),
        "topic_broadcasted": (
            "✅ Dars mavzusi va rejasi saqlandi hamda <b>{group}</b> Telegram guruhiga yuborildi!"
        ),
        "topic_no_group_chat": (
            "⚠️ Mavzu saqlandi, lekin <b>{group}</b> guruhiga Telegram chat bog‘lanmagan.\n"
            "Guruhga yuborish uchun Telegram guruh ichida <code>/link_group {group}</code> buyrug‘ini yozing."
        ),
        "topic_group_broadcast_msg": (
            "📢 <b>Dars mavzusi va rejasi</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📅 Sana: <b>{date}</b>\n"
            "📖 Mavzu: <b>{topic_title}</b>\n\n"
            "📝 <b>Darsda o‘tiladigan mavzular / vazifa:</b>\n{lesson_details}\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "topic_cancelled": "❌ Dars mavzusi va rejasini kiritish bekor qilindi.",

        # Student menu buttons
        "menu_student_group": "👥 Mening guruhim",
        "menu_student_schedule": "📅 Dars jadvali",
        "menu_student_payments": "💳 To‘lov va qarzlar",

        # Parent menu buttons
        "menu_parent_schedule": "📅 Farzandim jadvali",
        "menu_parent_payments": "💳 To‘lov va qarzlar",

        # Human-friendly cycle & lesson labels
        "human_cycle_label": "{num}-o‘quv oyi ({count} ta dars)",
        "human_cycle_label_prorated": "{num}-o‘quv oyi (qolgan {remaining} ta dars)",
        "lesson_status_present": "✅ Qatnashdi",
        "lesson_status_absent": "❌ Kelmadi",
        "lesson_status_pending": "⏳ Kutilmoqda",
        "lesson_line_template": "{lesson_num}-dars | {date} ({weekday}) — {status}",
        "next_payment_template": "{lesson_num}-dars yakunida ({date})",
        "payment_card_block": (
            "💳 To‘lov uchun karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>"
        ),

        # Schedule setup & cancel lesson
        "schedule_select_group": "📅 Dars jadvalini sozlash uchun guruhni tanlang:",
        "schedule_select_count": "Bir o‘quv oyidagi darslar sonini tanlang:",
        "schedule_select_days": (
            "Hafta dars kunlarini belgilang va «✅ Tasdiqlash» tugmasini bosing:"
        ),
        "schedule_enter_time": "Dars boshlanish vaqtini kiriting (format: <code>HH:MM</code>, masalan: <code>14:00</code>):",
        "schedule_invalid_time": "❌ Noto‘g‘ri vaqt formati. Iltimos <code>HH:MM</code> ko‘rinishida yozing (masalan: <code>09:00</code>).",
        "lesson_time_mode_prompt": "🕒 <b>Dars vaqtini qanday belgilaymiz?</b>\n\nTanlangan kunlar: <b>{days}</b>",
        "btn_lesson_time_uniform": "🕒 Hamma kunlarga bir xil vaqt",
        "btn_lesson_time_per_day": "⚙️ Har bir kun uchun alohida vaqt",
        "lesson_time_day_prompt": "{n}/{total} — <b>{day}</b> kuni dars soati nechada? (Masalan: <code>14:00</code>)",
        "lesson_time_missing_days_alert": "⚠️ Yangi kunlar uchun dars vaqti belgilanmagan. Iltimos, vaqtni qayta belgilang.",
        "schedule_confirm_summary": (
            "📅 <b>Dars jadvali tasdiqlansinmi?</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🔢 Oylik darslar soni: <b>{count} ta</b>\n"
            "📆 Kunlar: <b>{days}</b>\n"
            "⏰ Vaqt: <b>{time}</b>\n"
            "🗓 Birinchi o‘quv oyi: <b>{cycle_title}</b> ({start_date} — {end_date})"
        ),
        "schedule_saved": "✅ <b>{group}</b> guruhi uchun dars jadvali saqlandi va yangi o‘quv oyi jadvali yaratildi.",
        "schedule_notify_user": (
            "📅 <b>Dars jadvali yangilandi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📆 Kunlar: <b>{days}</b>\n"
            "⏰ Vaqt: <b>{time}</b>\n"
            "🔢 Har bir o‘quv oyi: <b>{count} ta dars</b>"
        ),
        "schedule_view_student": (
            "📅 <b>Dars jadvalingiz</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📆 Dars kunlari: <b>{days}</b>\n"
            "⏰ Dars vaqti: <b>{time}</b>\n"
            "📊 Oylik reja: <b>{count} ta dars</b>"
        ),
        "schedule_view_parent": (
            "📅 <b>Farzandingizning dars jadvali</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📆 Dars kunlari: <b>{days}</b>\n"
            "⏰ Dars vaqti: <b>{time}</b>\n"
            "📊 Oylik reja: <b>{count} ta dars</b>"
        ),
        "cancel_lesson_select_group": "🚫 Bugungi darsini bekor qilmoqchi bo‘lgan guruhni tanlang:",
        "cancel_lesson_no_today": "ℹ️ Bugun darsi belgilangan guruhlar topilmadi.",
        "cancel_lesson_enter_reason": "📝 <b>{group}</b> guruhi darsini bekor qilish sababini yozing:",
        "cancel_lesson_confirm": (
            "🚫 <b>Darsni bekor qilishni tasdiqlaysizmi?</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📅 Sana: <b>{date}</b>\n"
            "📝 Sabab: <i>{reason}</i>"
        ),
        "cancel_lesson_notify_private": (
            "🚫 <b>Dars bekor qilindi</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📅 Bugungi ({date}) dars bekor qilindi.\n"
            "📝 Sabab: <i>{reason}</i>\n"
            "➡️ O‘quv oyi oxiriga qo‘shimcha dars sanasi qo‘shildi: <b>{new_end_date}</b>"
        ),
        "cancel_lesson_notify_group": (
            "🚫 <b>Diqqat! Bugungi dars bekor qilindi.</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📅 Sana: <b>{date}</b>\n"
            "📝 Sabab: <i>{reason}</i>\n"
            "➡️ Ushbu dars o‘quv oyi oxiriga ({new_end_date}) ko‘chirildi."
        ),

        # Attendance
        "attendance_select_group": "📋 Yo‘qlama qilish uchun guruhni tanlang:",
        "attendance_no_groups_today": "ℹ️ Yo‘qlama uchun guruhlar topilmadi.",
        "attendance_btn_today": "📅 Bugun, {today_date}",
        "attendance_btn_other_day": "🗓 Boshqa kun",
        "attendance_past_date_notice": "⚠️ O'tib ketgan ({sana}) gi dars yo'qlamasi qilindi\n\n",
        "attendance_topic_line": "📖 Mavzu: \"{mavzu}\"\n",
        "attendance_signature": "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!",
        "attendance_student_present": (
            "🟢 Hurmatli <b>{talaba_ismi}</b>,\n\n"
            "Siz <b>{guruh_nomi}</b> guruhida <b>{sana_uz} ({hafta_kuni})</b> kungi o'tkazilgan <b>{dars_raqami}-dars</b>ga qatnashdingiz.\n"
            "{mavzu_qatori}Biz sizning bilim olishdagi qat'iyatingiz va ishtiyoqingizni yuqori baholaymiz."
            "{talaba_qarz_eslatmasi}\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "attendance_student_absent": (
            "🔴 Hurmatli <b>{talaba_ismi}</b>,\n\n"
            "Siz <b>{guruh_nomi}</b> guruhida <b>{sana_uz} ({hafta_kuni})</b> kungi o'tkazilgan <b>{dars_raqami}-dars</b>da qatnashmadingiz.\n"
            "{mavzu_qatori}Yangi mavzularni o'tkazib yubormaslik uchun dars materiallari va uyga vazifalarni ko'rib chiqishingizni tavsiya qilamiz. Keyingi darsda sizni albatta kutamiz!"
            "{talaba_qarz_eslatmasi}\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "attendance_student_debt_note": (
            "\n\n💳 Eslatma: Joriy o'quv oyi uchun <b>{qarz_summasi} so'm</b> to'lov hali amalga oshirilmagan. To'lovni 1-darsdan kechiktirmay amalga oshirishingizni so'raymiz.\n"
        ),
        "attendance_parent_present": (
            "🟢 Assalomu alaykum, hurmatli {ota_ona_ismi}!\n\n"
            "Farzandingiz <b>{talaba_ismi}</b> <b>{guruh_nomi}</b> guruhida <b>{sana_uz} ({hafta_kuni})</b> kungi o'tkazilgan <b>{dars_raqami}-dars</b>ga qatnashdi.\n"
            "{mavzu_qatori}Biz farzandingizning bilim olishdagi qat'iyati va intilishini yuqori baholaymiz!"
            "{ota_ona_qarz_eslatmasi}\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "attendance_parent_absent": (
            "🔴 Assalomu alaykum, hurmatli {ota_ona_ismi}!\n\n"
            "Farzandingiz <b>{talaba_ismi}</b> <b>{guruh_nomi}</b> guruhida <b>{sana_uz} ({hafta_kuni})</b> kungi o'tkazilgan <b>{dars_raqami}-dars</b>da qatnashmadi.\n"
            "{mavzu_qatori}Yangi mavzularni o'tkazib yubormaslik uchun dars materiallari va uyga vazifalarni ko'rib chiqishini tavsiya qilamiz. Keyingi darsda albatta kutib qolamiz!"
            "{ota_ona_qarz_eslatmasi}\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "attendance_parent_debt_note": (
            "\n\n💳 Eslatma: Farzandingizning joriy o'quv oyi uchun <b>{qarz_summasi} so'm</b> to'lovi hali amalga oshirilmagan. To'lovni 1-darsdan kechiktirmay amalga oshirishingizni hurmat bilan so'raymiz.\n"
        ),
        "attendance_student_debt_note_prorated": (
            "\n\n💳 Eslatma: Joriy o‘quv oyining qolgan {remaining_lessons} ta darsi uchun <b>{qarz_summasi} so‘m</b> to‘lov hali amalga oshirilmagan. To‘lovni 1-darsdan kechiktirmay amalga oshirishingizni so‘raymiz.\n"
        ),
        "attendance_parent_debt_note_prorated": (
            "\n\n💳 Eslatma: Farzandingizning joriy o‘quv oyining qolgan {remaining_lessons} ta darsi uchun <b>{qarz_summasi} so‘m</b> to‘lovi hali amalga oshirilmagan. To‘lovni 1-darsdan kechiktirmay amalga oshirishingizni hurmat bilan so‘raymiz.\n"
        ),
        "group_lesson_progress": (
            "📋 <b>Dars yakunlandi</b>\n\n"
            "📚 Guruh: <b>{group_name}</b>\n"
            "🗓 O‘quv oyi: <b>{cycle_title}</b>\n"
            "✅ O‘tilgan dars: <b>{lesson_num}-dars</b> (jami <b>{total_lessons} ta</b> darsdan) — <b>{date_str}</b>\n"
            "{optional_topic_line}\n"
            "Hurmat bilan,\n"
            "Guruh ustozi: <b>{teacher_name}</b>"
        ),
        "group_lesson_progress_topic_line": "📖 Mavzu: <b>{topic}</b>\n",
        "btn_change_start_date": "📅 Boshlanish sanasini o‘zgartirish",
        "add_group_start_date_lines": (
            "📅 Boshlanish sanasi: <b>{start_date}</b>\n"
            "🏁 Sikl tugash sanasi: <b>{end_date}</b>"
        ),
        "add_group_calendar_title": (
            "📅 <b>Sikl boshlanish sanasini tanlang</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "Hozirgi tanlov: <b>{selected}</b>\n\n"
            "<i>O‘tgan yoki kelgusi sanani bosing.</i>"
        ),
        "btn_enroll_full": "📚 Oy boshidan beri o‘qiydi",
        "btn_enroll_new": "🆕 Bugundan qo‘shildi (Yangi talaba)",
        "enroll_choice_prompt": (
            "🗓 <b>{group}</b> guruhining joriy o‘quv oyida (<b>{cycle_title}</b>) "
            "<b>{past_count} ta</b> dars allaqachon o‘tib bo‘lgan.\n\n"
            "👤 Talaba: <b>{student_name}</b>\n\n"
            "Talaba qaysi holatda qo‘shiladi?"
        ),
        "enroll_result_full": (
            "📚 O‘tgan <b>{marked} ta</b> dars jimgina ✅ deb belgilandi (xabarnomasiz).\n"
            "💰 To‘liq oylik to‘lov: <b>{amount} so‘m</b>"
        ),
        "enroll_result_new": (
            "🆕 Joriy o‘quv oyining qolgan <b>{remaining} ta</b> darsi uchun to‘lov: "
            "<b>{amount} so‘m</b>.\n"
            "Keyingi o‘quv oyidan boshlab to‘liq oylik to‘lov qo‘llanadi."
        ),
        "attendance_multi_header": (
            "📋 Assalomu alaykum, hurmatli {ota_ona_ismi}!\n\n"
            "Farzandlaringizning <b>{sana_uz} ({hafta_kuni})</b> kungi o'tkazilgan darslar bo'yicha davomat ma'lumoti:\n\n"
        ),
        "attendance_multi_child": (
            "{status_emoji} {tartib}. <b>{talaba_ismi}</b>\n"
            "📚 Dars/Guruh: <b>{guruh_nomi}</b> • <b>{dars_raqami}-dars</b>\n"
            "🗓 Dars kuni: {hafta_kuni} | Holati: {holat_matni}\n"
            "👨‍🏫 Ustoz: {oqituvchi_ismi}\n"
            "{mavzu_qatori}\n"
            "──────────────────"
        ),
        "attendance_multi_status_present": "Darsga qatnashdi",
        "attendance_multi_status_absent": "Darsga qatnashmadi",
        "attendance_multi_debt_title": "💳 To'lov eslatmasi:",
        "attendance_multi_debt_item": (
            "• <b>{talaba_ismi}</b> — <b>{qarz_summasi} so'm</b> qarzdorlik mavjud. "
            "Joriy o'quv oyi to'lovini 1-darsdan kechiktirmay amalga oshirishingizni so'raymiz."
        ),
        "parent_pay_header": "💳 Farzandlaringizning to'lov va qarzdorlik holati:\n\n",
        "parent_pay_child": (
            "👶 {tartib}. {talaba_ismi}\n"
            "📚 Dars/Guruh: {guruh_nomi}\n"
            "💵 Oylik to'lov: {oylik_tolov} so'm\n"
            "📊 Holati: {tolov_holati}\n"
            "❗️ Qarzdorlik: {qarz_summasi} so'm"
        ),
        "parent_pay_separator": "\n\n──────────────────\n\n",
        "parent_pay_total": "\n\n💰 Umumiy qarzdorlik: {umumiy_qarz} so'm",
        "parent_pay_status_paid": "✅ To'langan",
        "parent_pay_status_unpaid": "❌ To'lanmagan",
        "parent_sched_btn_back": "🔙 Ortga",
        "attendance_select_date": (
            "📅 <b>{group} — Yo‘qlama sanasini tanlang</b>\n\n"
            "Bugungi darsni belgilashingiz, qolib ketgan o‘tgan darsni to‘ldirishingiz "
            "yoki avval belgilangan yo‘qlamani tahrirlashingiz mumkin:"
        ),
        "attendance_date_btn_marked": "{date} ({weekday}) — ✅ Belgilangan",
        "attendance_date_btn_unmarked": "{date} ({weekday}) — ⏳ Belgilanmagan",
        "attendance_date_btn_cancelled": "{date} ({weekday}) — 🚫 Bekor qilingan",
        "attendance_no_cycle_dates": (
            "ℹ️ <b>{group}</b> guruhi uchun faol o‘quv oyi jadvali topilmadi. "
            "Avval «📅 Dars jadvali» bo‘limidan jadval yarating."
        ),
        "attendance_mark_title": (
            "📋 <b>Yo‘qlama: {group}</b> ({date})\n"
            "Har bir talaba holatini belgilang va «✅ Yakunlash» tugmasini bosing:"
        ),
        "attendance_pending_5min": (
            "⏳ <b>{group}</b> guruhi yo‘qlamasi navbatga qo‘yildi.\n"
            "5 daqiqadan so‘ng saqlanadi hamda talaba va ota-onalarga yuboriladi.\n\n"
            "🟢 Qatnashdi: <b>{present_count}</b> | 🔴 Kelmadi: <b>{absent_count}</b>"
        ),
        "attendance_saved_instant": (
            "✅ <b>{group}</b> guruhi ({date}) yo‘qlamasi darhol saqlandi "
            "va barcha xabarnomalar yuborildi!\n\n"
            "🟢 Qatnashdi: <b>{present_count}</b> | 🔴 Kelmadi: <b>{absent_count}</b>"
        ),
        "attendance_updated_instant": (
            "🔄 <b>{group}</b> guruhi ({date}) yo‘qlamasi qayta tekshirilib yangilandi!\n\n"
            "🟢 Qatnashdi: <b>{present_count}</b> | 🔴 Kelmadi: <b>{absent_count}</b>"
        ),
        "attendance_cancelled": "❌ Yo‘qlama bekor qilindi. Ma'lumotlar saqlanmadi.",
        "attendance_committed": (
            "✅ <b>{group}</b> guruhi ({date}) yo‘qlamasi saqlandi "
            "va xabarnomalar yuborildi."
        ),
        "attendance_notify_present": (
            "🟢 <b>Davomat xabarnomasi</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📅 Sana: <b>{date}</b>\n"
            "Holat: <b>Qatnashdi ✅</b>"
        ),
        "attendance_notify_absent": (
            "🔴 <b>Davomat xabarnomasi</b>\n\n"
            "Assalomu alaykum, <b>{student_name}</b>!\n"
            "Siz <b>{date}</b> kungi <b>{group}</b> guruhi darsida qatnasha olmadingiz (Kelmadi ❌).\n"
            "Iltimos, keyingi darsgacha o‘tilgan mavzuni ko‘rib chiqib, tayyorlanib keling.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "attendance_notify_absent_parent": (
            "🔴 <b>Davomat xabarnomasi</b>\n\n"
            "Assalomu alaykum!\n"
            "Sizga shuni ma'lum qilamizki, farzandingiz <b>{student_name}</b> "
            "<b>{date}</b> kungi <b>{group}</b> guruhi darsida qatnashmadi (Kelmadi ❌).\n"
            "Iltimos, darslarga muntazam qatnashishini nazorat qilib borishingizni so‘raymiz.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "attendance_notify_updated_present": (
            "🔄 <b>Davomat holati yangilandi</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "📅 Sana: <b>{date}</b>\n"
            "Yangi holat: <b>Qatnashdi ✅</b>"
        ),
        "attendance_notify_updated_absent": (
            "🔄 <b>Davomat holati yangilandi</b>\n\n"
            "Assalomu alaykum, <b>{student_name}</b>!\n"
            "<b>{date}</b> kungi <b>{group}</b> guruhi darsidagi holatingiz "
            "<b>Kelmadi ❌</b> deb yangilandi.\n"
            "Iltimos, o‘tilgan mavzuni mustaqil o‘zlashtirib, keyingi darsga tayyorlanib keling.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "attendance_notify_updated_absent_parent": (
            "🔄 <b>Davomat holati yangilandi</b>\n\n"
            "Assalomu alaykum!\n"
            "Sizga ma'lum qilamizki, farzandingiz <b>{student_name}</b>ning "
            "<b>{date}</b> kungi <b>{group}</b> guruhi darsidagi davomati "
            "<b>Kelmadi ❌</b> deb yangilandi.\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "attendance_topic_addon": (
            "\n\n📚 Mavzu: <b>{topic_title}</b>\n"
            "📝 O'tilgan dars mazmuni: <i>{lesson_details}</i>"
        ),
        "attendance_topic_title_only_addon": (
            "\n\n📚 Mavzu: <b>{topic_title}</b>"
        ),
        "admin_attendance_report_compact": (
            "📋 <b>Davomat hisoboti{updated_badge}</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "👨‍🏫 Ustoz: <b>{teacher_name}</b>\n"
            "📅 Sana: <b>{date}</b> | ⏰ <b>{lesson_time}</b>\n"
            "🟢 Qatnashdi: <b>{present_count}</b> ta | 🔴 Kelmadi: <b>{absent_count}</b> ta"
        ),
        "admin_attendance_report_detailed": (
            "📋 <b>Davomat hisoboti (Batafsil){updated_badge}</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "👨‍🏫 Ustoz: <b>{teacher_name}</b>\n"
            "📅 Sana: <b>{date}</b> | ⏰ <b>{lesson_time}</b>\n"
            "🟢 Qatnashdi: <b>{present_count}</b> ta | 🔴 Kelmadi: <b>{absent_count}</b> ta\n\n"
            "🟢 <b>Qatnashganlar:</b>\n{present_lines}\n\n"
            "🔴 <b>Kelmaganlar (Aloqa uchun):</b>\n{absent_lines}\n\n"
            "⚠️ <b>Qarzdorlar:</b>\n{debtor_lines}"
        ),
        "admin_report_updated_tag": " (Yangilandi 🔄)",

        # Cycle completion & Payments (Confirm + Revert)
        "cycle_completed_remind_student": (
            "🔔 <b>O‘quv oyi yakunlandi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 Davr: <b>{cycle_title}</b>\n\n"
            "Keyingi darslar uchun oylik to‘lovni amalga oshirishingizni so‘raymiz.\n\n"
            "💳 To‘lov uchun karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>"
        ),
        "cycle_completed_remind_parent": (
            "🔔 <b>O‘quv oyi yakunlandi!</b>\n\n"
            "👤 Farzandingiz: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 Davr: <b>{cycle_title}</b>\n\n"
            "Iltimos, navbatdagi oylik to‘lovni o‘z vaqtida amalga oshiring.\n\n"
            "💳 To‘lov uchun karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>"
        ),
        "cycle_completed_report_teacher": (
            "📊 <b>O‘quv oyi yakunlandi: {group}</b>\n"
            "🗓 Yakunlangan davr: <b>{cycle_title}</b>\n"
            "🆕 Yangi o‘quv oyi avtomatik ochildi: <b>{next_cycle_title}</b>"
        ),
        "btn_payment_confirm": "✅ Tasdiqlash",
        "btn_payment_revert": "↩️ Qaytarish",
        "payment_select_group": "💰 To‘lovni tasdiqlash uchun guruhni tanlang:",
        "payment_select_student": "👤 Talabani tanlang (<b>{group}</b>):",
        "payment_select_cycle": "🗓 To‘lov qilinayotgan o‘quv oyini tanlang:",
        "payment_summary_compact": (
            "💰 <b>To‘lov ma'lumoti</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 O‘quv oyi: <b>{cycle_title}</b>\n"
            "📆 Keyingi to‘lov: <b>{next_payment_info}</b>\n"
            "💳 Holat: <b>{payment_status}</b>\n\n"
            "💳 Karta: <code>{card_number}</code> ({card_owner})"
        ),
        "payment_summary_detailed": (
            "💰 <b>To‘lov ma'lumoti (Batafsil)</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 O‘quv oyi: <b>{cycle_title}</b>\n"
            "📅 Davr: <b>{start_date} — {end_date}</b>\n"
            "📆 Keyingi to‘lov: <b>{next_payment_info}</b>\n"
            "🟢 Qatnashdi: <b>{present_count}</b> | 🔴 Kelmadi: <b>{absent_count}</b>\n"
            "💳 Holat: <b>{payment_status}</b>\n\n"
            "📋 <b>Darslar kunma-kun:</b>\n{dates_lines}\n\n"
            "💳 Karta: <code>{card_number}</code> ({card_owner})"
        ),
        "payment_pending_5min": (
            "⏳ <b>To‘lov navbatga qo‘yildi!</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "🗓 O‘quv oyi: <b>{cycle_title}</b>\n"
            "5 daqiqadan so‘ng jadvalda yashil rang bilan tasdiqlanadi va xabar yuboriladi."
        ),
        "payment_confirmed_student": (
            "✅ <b>To‘lovingiz tasdiqlandi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 O‘quv oyi: <b>{cycle_title}</b>\n"
            "Rahmat! O‘qishlaringizda omad tilaymiz."
        ),
        "payment_confirmed_parent": (
            "✅ <b>To‘lov tasdiqlandi!</b>\n\n"
            "👤 Farzandingiz: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 O‘quv oyi: <b>{cycle_title}</b>\n"
            "O‘z vaqtida to‘lov qilganingiz uchun rahmat!"
        ),
        "payment_confirmed_teacher": (
            "✅ <b>To‘lov yakuniy tasdiqlandi</b>\n\n"
            "👤 Talaba: <b>{student_name}</b> ({group})\n"
            "🗓 O‘quv oyi: <b>{cycle_title}</b>"
        ),
        "payment_confirmed_group": (
            "✅ <b>To‘lov tasdiqlandi!</b>\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 O‘quv oyi: <b>{cycle_title}</b>"
        ),
        "payment_reverted_admin": (
            "↩️ <b>To'lov bekor qilindi (rad etildi)!</b>\n\n"
            "👤 Talaba: <b>{student_name}</b> ({group})\n"
            "🗓 O'quv oyi: <b>{cycle_title}</b>\n"
            "Qarzdorlik qayta tiklandi."
        ),
        "payment_reverted_student": (
            "↩️ <b>To'lov holati qaytarildi</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 O'quv oyi: <b>{cycle_title}</b>\n"
            "Ushbu oy uchun to'lov holati «To'lanmagan ❌» ga o'zgartirildi. "
            "Savolingiz bo'lsa, ustoz yoki admin bilan bog'laning."
        ),
        "payment_reverted_parent": (
            "↩️ <b>To'lov holati qaytarildi</b>\n\n"
            "👤 Farzandingiz: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 O'quv oyi: <b>{cycle_title}</b>\n"
            "Ushbu oy uchun to'lov holati «To'lanmagan ❌» ga o'zgartirildi."
        ),
        "payment_reverted_teacher": (
            "↩️ <b>To'lov bekor qilindi</b>\n\n"
            "👤 Talaba: <b>{student_name}</b> ({group})\n"
            "🗓 O'quv oyi: <b>{cycle_title}</b>"
        ),
        "payment_reverted_group": (
            "↩️ <b>To'lov holati o'zgartirildi</b>\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🗓 O'quv oyi: <b>{cycle_title}</b> — To'lanmagan ❌"
        ),
        "student_payments_header": (
            "💳 <b>To‘lovlar va Darslar hisoboti</b>\n"
            "👤 Talaba: <b>{student_name}</b> ({group})\n\n"
            "💳 To‘lov uchun karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>"
        ),
        "student_payment_cycle_compact": (
            "🗓 <b>{cycle_title}</b>\n"
            "📆 Keyingi to‘lov: <b>{next_payment_info}</b>\n"
            "Holat: <b>{status_label}</b>"
        ),
        "student_payment_cycle_detailed": (
            "🗓 <b>{cycle_title}</b>\n"
            "📅 Davr: <b>{start_date} — {end_date}</b>\n"
            "📆 Keyingi to‘lov: <b>{next_payment_info}</b>\n"
            "🟢 Qatnashdi: <b>{present_count}</b> | 🔴 Kelmadi: <b>{absent_count}</b>\n"
            "Holat: <b>{status_label}</b>\n\n"
            "📋 <b>Darslar kunma-kun:</b>\n{dates_lines}"
        ),
        "status_paid": "To‘langan ✅",
        "status_unpaid": "To‘lanmagan ❌",
        "status_active_cycle": "Joriy o‘quv oyi ⏳",
        "no_debts_msg": "✅ Sizda qarzdorlik mavjud emas.",

        # Debtors & Contacts
        "debtors_list_header": "⚠️ <b>Qarzdor talabalar ro‘yxati:</b>\n",
        "debtors_empty": "✅ Hozirda qarzdor talabalar mavjud emas.",
        "debtor_item": "• <b>{student_name}</b> ({group}) — <i>{debts}</i> | Tel: {phone}",
        "contacts_header": "👥 <b>{group} guruhi kontaktlari:</b>\n",
        "contact_student_item": "• <b>{student_name}</b>\n  📞 {phone} | {tg}",
        "contacts_empty": "ℹ️ Ushbu guruhda faol talabalar topilmadi.",

        # Smart reminders
        "reminder_evening_before": (
            "🌙 <b>Ertangi dars eslatmasi</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "⏰ Ertaga soat <b>{time}</b> da darsingiz bor. Vaqtida kelishni unutmang!"
        ),
        "reminder_morning_today": (
            "☀️ <b>Bugungi dars eslatmasi</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "⏰ Bugun soat <b>{time}</b> da darsingiz bor."
        ),
        "reminder_1h_before": (
            "⏰ <b>Darsga 1 soat qoldi!</b>\n\n"
            "📚 Guruh: <b>{group}</b>\n"
            "🕒 Boshlanish vaqti: <b>{time}</b>. Yo‘lga chiqish vaqti keldi!"
        ),
        "reminder_weekly_debt_student": (
            "⚠️ <b>Qarzdorlik eslatmasi</b>\n\n"
            "👤 Talaba: <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group}</b>\n"
            "To‘lanmagan o‘quv oylari: <b>{debts}</b>\n\n"
            "Iltimos, to‘lovni imkon qadar tezroq amalga oshiring.\n"
            "💳 Karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>"
        ),
        "reminder_weekly_debt_parent": (
            "⚠️ <b>Qarzdorlik eslatmasi</b>\n\n"
            "👤 Farzandingiz: <b>{student_name}</b> ({group})\n"
            "To‘lanmagan o‘quv oylari: <b>{debts}</b>\n\n"
            "Iltimos, o‘quv markazi to‘lovini amalga oshirishingizni so‘raymiz.\n"
            "💳 Karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>"
        ),
        "weekly_debt_student_dm": (
            "⚠️ <b>Haftalik to‘lov eslatmasi</b>\n\n"
            "Hurmatli <b>{student_name}</b>,\n\n"
            "Sizning <b>{group_name}</b> guruhi bo‘yicha quyidagi o‘quv oyi uchun to‘lovingiz hali amalga oshirilmagan:\n"
            "🗓 To‘lanmagan davr: <b>{debts}</b>\n"
            "💰 Qarzdorlik miqdori: <b>{amount} so‘m</b>\n\n"
            "Iltimos, oylik to‘lovni 1-darsdan kechiktirmay o‘z vaqtida amalga oshiring.\n\n"
            "💳 To‘lov uchun karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "weekly_debt_parent_single_dm": (
            "⚠️ <b>Haftalik to‘lov eslatmasi</b>\n\n"
            "Assalomu alaykum, hurmatli <b>{parent_name}</b>!\n\n"
            "Farzandingiz <b>{student_name}</b>ning <b>{group_name}</b> guruhi bo‘yicha quyidagi o‘quv oyi uchun to‘lovi hali amalga oshirilmagan:\n"
            "🗓 To‘lanmagan davr: <b>{debts}</b>\n"
            "💰 Qarzdorlik miqdori: <b>{amount} so‘m</b>\n\n"
            "Iltimos, oylik to‘lovni 1-darsdan kechiktirmay o‘z vaqtida amalga oshirishingizni hurmat bilan so‘raymiz.\n\n"
            "💳 To‘lov uchun karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "weekly_debt_parent_multi_dm": (
            "⚠️ <b>Haftalik to‘lov eslatmasi</b>\n\n"
            "Assalomu alaykum, hurmatli <b>{parent_name}</b>!\n\n"
            "Farzandlaringizning to‘lanmagan o‘quv oylari bo‘yicha qarzdorlik ma’lumoti:\n\n"
            "{children_blocks}\n\n"
            "💵 <b>Umumiy qarzdorlik: {grand_total} so‘m</b>\n\n"
            "Iltimos, oylik to‘lovlarni 1-darsdan kechiktirmay o‘z vaqtida amalga oshirishingizni hurmat bilan so‘raymiz.\n\n"
            "💳 To‘lov uchun karta: <code>{card_number}</code>\n"
            "👤 Karta egasi: <b>{card_owner}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "group_initial_notice": (
            "💳 <b>Oylik to‘lov eslatmasi</b>\n\n"
            "📚 Guruh: <b>{canonical_group}</b>\n\n"
            "Yangi o‘quv oyi boshlanishi munosabati bilan oylik to‘lovni 1-darsdan kechiktirmay o‘z vaqtida amalga oshirishingizni so‘raymiz.\n\n"
            "💳 To‘lov uchun karta: <code>{card_esc}</code>\n"
            "👤 Karta egasi: <b>{owner_esc}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "group_weekly_reminder": (
            "⚠️ <b>Haftalik to‘lov eslatmasi</b>\n\n"
            "📚 Guruh: <b>{canonical_group}</b>\n\n"
            "Joriy o‘quv oyi uchun to‘lovni hali amalga oshirmagan talabalar soni: <b>{unpaid_count} nafar</b>.\n\n"
            "Iltimos, oylik to‘lovni 1-darsdan kechiktirmay o‘z vaqtida amalga oshirishingizni so‘raymiz.\n\n"
            "💳 To‘lov uchun karta: <code>{card_esc}</code>\n"
            "👤 Karta egasi: <b>{owner_esc}</b>\n\n"
            "Hurmat bilan,\nMishkat Nodavlat Ta'lim Muassasasi!"
        ),
        "weekly_debt_child_block": (
            "👶 <b>{student_name}</b>\n"
            "📚 Guruh: <b>{group_name}</b>\n"
            "🗓 To‘lanmagan davr: <b>{debts}</b>\n"
            "💰 Qarzdorlik miqdori: <b>{amount} so‘m</b>"
        ),
        "error_generic": "❌ Xatolik yuz berdi. Keyinroq qayta urinib ko‘ring.",
    },
    "cyrl": {
        # Language selection
        "choose_language": (
            "O‘zingizga qulay bo‘lgan tilni tanlang / "
            "Ўзингизга қулай бўлган тилни танланг:"
        ),
        "btn_lang_latn": "🇺🇿 O'zbekcha",
        "btn_lang_cyrl": "🇺🇿 Ўзбекча",
        "lang_saved": "✅ Тил муваффақиятли танланди: Ўзбекча (Кирилл).",
        "btn_change_lang": "🌐 Тилни ўзгартириш",
        "self_marker": "(сиз)",

        # FSM Lock Middleware
        "fsm_lock_warning": (
            "⚠️ Сизда тугалланмаган жараён бор. Давом этинг ёки "
            "«❌ Бекор қилиш» тугмасини босинг."
        ),
        "fsm_cancelled": "❌ Жорий жараён бекор қилинди.",

        # Roles & welcome
        "role_admin": "Админ",
        "role_teacher": "Устоз",
        "role_student": "Талаба",
        "role_parent": "Ота-она",
        "welcome_menu": (
            "Ассалому алайкум, <b>{name}</b>!\n"
            "Сиз тизимга <b>{role}</b> сифатида кирдингиз.\n"
            "Керакли бўлимни танланг:"
        ),
        "welcome_menu_father": (
            "Ассалому алайкум, <b>{name}</b>!\n"
            "🧔 Сиз Отаси сифатида тизимга кирдингиз!\n"
            "Керакли бўлимни танланг:"
        ),
        "welcome_menu_mother": (
            "Ассалому алайкум, <b>{name}</b>!\n"
            "🧕 Сиз Онаси сифатида тизимга кирдингиз!\n"
            "Керакли бўлимни танланг:"
        ),
        "profile_role_pick": (
            "🔄 <b>Отаси / Онаси ролини алмаштириш</b>\n\n"
            "Ҳозирги ролингиз: <b>{current_role}</b>\n"
            "Янги ролни танланг:"
        ),
        "profile_role_same": "ℹ️ Сиз аллақачон <b>{role}</b> сифатида рўйхатдан ўтгансиз.",
        "profile_role_switched": (
            "✅ Ролингиз <b>{role}</b> га ўзгартирилди.\n"
            "Барча фарзандларингиз бўйича маълумотлар янгиланди."
        ),
        "unregistered_user": (
            "Ассалому алайкум!\n"
            "Сизнинг ҳисобингиз ҳали тизимга боғланмаган.\n"
            "Илтимос, устозингиз ёки ўқув маркази администратори юборган "
            "махсус таклиф ҳаволаси орқали киринг."
        ),

        # Strict Role Lock & Admin Role-Change Request
        "role_lock_warning": (
            "⚠️ Сиз тизимда «{current_role}» сифатида рўйхатдан ўтгансиз. "
            "Бошқа ролга ўтиш учун аввал эски ролингиз бекор қилиниши керак."
        ),
        "btn_request_role_change": "📨 Сўров юбориш",
        "role_change_request_sent": (
            "✅ Ролни ўзгартириш бўйича сўровингиз админга юборилди. "
            "Тасдиқланишини кутинг."
        ),
        "role_change_admin_card": (
            "🔄 <b>Ролни ўзгартириш сўрови</b>\n\n"
            "👤 Фойдаланувчи: <b>{full_name}</b> (<code>{user_id}</code>)\n"
            "📌 Жорий роли: <b>{current_role}</b>\n"
            "🎯 Сўралаётган рол: <b>{requested_role}</b>"
        ),
        "btn_role_change_approve": "✅ Алмаштириш",
        "btn_role_change_reject": "❌ Рад этиш",
        "role_change_approved_user": (
            "✅ Админ сўровингизни тасдиқлади! Энди янги рол учун берилган "
            "таклиф ҳаволаси устига қайта босинг."
        ),
        "role_change_rejected_user": (
            "❌ Кечирасиз, ролни ўзгартириш бўйича сўровингиз админ томонидан рад этилди."
        ),
        "role_change_approved_admin": (
            "✅ Фойдаланувчи (<code>{user_id}</code>) нинг эски роли ўчирилди. "
            "Энди у янги таклиф ҳаволаси орқали қайта рўйхатдан ўтиши мумкин."
        ),
        "role_change_rejected_admin": "❌ Ролни ўзгартириш сўрови рад этилди.",

        # Dual-Role Admin Prompt & Role Switcher
        "dual_role_admin_prompt": (
            "Фойдаланувчи {full_name} тизимда аввалдан {old_role} сифатида мавжуд. "
            "Ҳозир эса {new_role} бўлиб ҳам қўшилмоқчи. Қандай тасдиқлаймиз?"
        ),
        "btn_dual_role_keep_both": "➕ Иккаласи қолсин",
        "btn_dual_role_replace": "🔄 Фақат янгиси",
        "btn_dual_role_reject": "❌ Рад этиш",
        "btn_switch_to_parent": "👨‍👩‍👧 Ота-она режими",
        "btn_switch_to_student": "🎓 Талаба режими",
        "notif_role_header_student": "🎓 <b>Шахсий дарсингиз бўйича:</b>",
        "notif_role_header_parent": "👨‍👩‍👧 <b>Фарзандингиз {talaba_ismi} бўйича:</b>",

        # Mandatory Name + Phone Sharing (Shared)
        "btn_share_phone": "📱 Телефон рақамни улашиш",
        "use_contact_button_only": (
            "⚠️ Илтимос, телефон рақамингизни қўлда ёзманг — пастдаги "
            "«📱 Телефон рақамни улашиш» тугмасини босинг."
        ),
        "own_contact_only": (
            "⚠️ Илтимос, фақат ўзингизнинг телефон рақамингизни улашинг."
        ),

        # Teacher invite & self-registration
        "teacher_invite_btn": "👨‍🏫 Устоз қўшиш",
        "teacher_add_enter_name": (
            "👨‍🏫 <b>Янги устоз таклиф ҳаволаси</b>\n\n"
            "Устознинг ҳақиқий <b>Фамилия ва Исмини</b> киритинг "
            "(масалан: <i>Каримов Сардор</i>):"
        ),
        "teacher_add_invalid_name": (
            "❌ Илтимос, устознинг Фамилия ва Исмини тўлиқ киритинг "
            "(камида 2 та сўз, масалан: <i>Каримов Сардор</i>):"
        ),
        "teacher_add_created": (
            "✅ <b>Устоз таклиф ҳаволаси яратилди!</b>\n\n"
            "👨‍🏫 Устоз: <b>{full_name}</b>\n"
            "🔗 Бир марталик ҳавола:\n<code>{invite_link}</code>\n\n"
            "Ушбу ҳаволани устозга юборинг. Устоз ботга кириб, исми ва телефон рақамини "
            "тасдиқлагач автоматик равишда тизимга қўшилади."
        ),
        "teacher_add_cancelled": "❌ Устоз таклиф ҳаволасини яратиш бекор қилинди.",
        "teacher_link_invalid": (
            "❌ Кечирасиз, ушбу устоз таклиф ҳаволаси яроқсиз ёки аллақачон ишлатилган."
        ),
        "teacher_self_reg_enter_name": (
            "👨‍🏫 <b>Устоз сифатида рўйхатдан ўтиш</b>\n\n"
            "✍️ Илтимос, ҳақиқий <b>Фамилия ва Исмингизни</b> тўлиқ киритинг "
            "(масалан: <i>Каримов Сардор</i>):"
        ),
        "teacher_self_reg_invalid_name": (
            "❌ Илтимос, Фамилия ва Исмингизни тўлиқ ёзинг (камида 2 та сўз, "
            "масалан: <i>Каримов Сардор</i>):"
        ),
        "teacher_self_reg_share_phone": (
            "📱 Раҳмат, <b>{full_name}</b>!\n"
            "Рўйхатдан ўтишни якунлаш учун пастдаги "
            "«📱 Телефон рақамни улашиш» тугмасини босинг:"
        ),
        "teacher_link_success": (
            "✅ Ассалому алайкум, <b>{teacher_name}</b>!\n"
            "Сиз тизимга <b>Устоз</b> сифатида муваффақиятли қўшилдингиз."
        ),

        # Admin Teacher Management (👨‍🏫 Устозлар бошқаруви)
        "menu_admin_manage_teachers": "👨‍🏫 Устозлар",
        "teacher_manage_title": (
            "👨‍🏫 <b>Устозлар бошқаруви</b>\n\n"
            "Рўйхатдан ўтган устозлардан бирини танланг ёки янги устоз таклиф ҳаволасини яратинг:"
        ),
        "teacher_manage_list_header": (
            "👨‍🏫 <b>Устозлар рўйхати:</b>\n"
            "Батафсил маълумот ва бошқариш учун устозни танланг:"
        ),
        "teacher_manage_empty": "ℹ️ Ҳозирча рўйхатдан ўтган устозлар мавжуд эмас.",
        "teacher_manage_card": (
            "👨‍🏫 <b>Устоз маълумотлари</b>\n\n"
            "🆔 Устоз ID: <code>{teacher_id}</code>\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📞 Телефон: {phone}\n"
            "💬 Telegram: {tg}\n"
            "📚 Бириктирилган гуруҳлар: <b>{groups}</b>"
        ),
        "teacher_manage_no_groups": "Ҳали бириктирилмаган",
        "teacher_manage_btn_assign": "🔗 Гуруҳ бириктириш",
        "teacher_manage_btn_delete": "🗑 Устозни ўчириш",
        "teacher_manage_assign_select_group": (
            "📚 <b>{full_name}</b> устозни бириктирмоқчи бўлган гуруҳни танланг:"
        ),
        "teacher_manage_assign_no_groups": "ℹ️ Ҳозирча тизимда гуруҳлар мавжуд эмас.",
        "teacher_manage_assign_success_admin": (
            "✅ Устоз <b>{full_name}</b> муваффақиятли равишда "
            "<b>{group}</b> гуруҳига бириктирилди!"
        ),
        "teacher_manage_assign_notify_teacher": (
            "👨‍🏫 Сиз <b>{group}</b> гуруҳига устоз сифада бириктирилдингиз!"
        ),
        "teacher_manage_delete_confirm": (
            "🗑 <b>Устозни ўчиришни тасдиқлайсизми?</b>\n\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "🆔 Устоз ID: <code>{teacher_id}</code>\n"
            "📚 Бириктирилган гуруҳлар: <b>{groups}</b>\n\n"
            "<i>Диққат: Устоз ўчирилса, унга бириктирилган барча гуруҳлардан устоз маълумоти тозаланади.</i>"
        ),
        "teacher_manage_delete_success": (
            "✅ Устоз <b>{full_name}</b> тизимдан муваффақиятли ўчирилди."
        ),
        "teacher_manage_delete_purged": (
            "\n🧹 Устознинг бот ҳисоби ва гуруҳ бириктирмалари тўлиқ тозаланди.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "teacher_manage_delete_notify_teacher": (
            "ℹ️ Сизнинг устозлик ҳисобингиз администратор томонидан тизимдан ўчирилди."
        ),
        "teacher_manage_cancelled": "❌ Устозлар бошқаруви ёпилди.",

        # Student Group Transfer / Dual Enrollment
        "stu_transfer_keep_question": (
            "Талаба <b>{student_name}</b> аввалги «<b>{old_group}</b>» гуруҳида ҳам қолдирилсинми?\n\n"
            "➡️ Янги танланган гуруҳ: <b>{new_group}</b>"
        ),
        "btn_stu_transfer_keep": "✅ Иккаласида қолсин",
        "btn_stu_transfer_move": "🔀 Фақат янгисида",
        "stu_transfer_success_dual_admin": (
            "✅ <b>Талаба қўшимча гуруҳга қўшилди!</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Аввалги гуруҳ: <b>{old_group}</b> (сақлаб қолинди)\n"
            "➕ Янги гуруҳ: <b>{new_group}</b> (🆔 <code>{new_student_id}</code>)"
        ),
        "stu_transfer_success_move_admin": (
            "✅ <b>Талаба янги гуруҳга ўтказилди!</b>\n\n"
            "👤 Талаба: <b>{student_name}</b> (<code>{student_id}</code>)\n"
            "📤 Аввалги гуруҳ: <b>{old_group}</b>\n"
            "📥 Янги гуруҳ: <b>{new_group}</b>"
        ),
        "stu_transfer_notify_dual_student": (
            "🎉 <b>Янги гуруҳга қўшилдингиз!</b>\n\n"
            "Ассалому алайкум, <b>{student_name}</b>!\n"
            "Сиз аввалги «<b>{old_group}</b>» гуруҳингизда қолган ҳолда қўшимча равишда "
            "«<b>{new_group}</b>» гуруҳига ҳам қабул қилиндингиз.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "stu_transfer_notify_move_student": (
            "🔄 <b>Гуруҳингиз ўзгартирилди!</b>\n\n"
            "Ассалому алайкум, <b>{student_name}</b>!\n"
            "Сиз «<b>{old_group}</b>» гуруҳидан «<b>{new_group}</b>» гуруҳига ўтказилдингиз.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "stu_transfer_notify_dual_father": (
            "📚 <b>Қўшимча гуруҳ хабарномаси</b>\n\n"
            "Ассалому алайкум, ҳурматли <b>{parent_name}</b>!\n"
            "Фарзандингиз <b>{student_name}</b> аввалги «<b>{old_group}</b>» гуруҳида ўқишини "
            "давом эттирган ҳолда қўшимча равишда «<b>{new_group}</b>» гуруҳига ҳам қўшилди.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "stu_transfer_notify_dual_mother": (
            "📚 <b>Қўшимча гуруҳ хабарномаси</b>\n\n"
            "Ассалому алайкум, ҳурматли <b>{parent_name}</b>!\n"
            "Фарзандингиз <b>{student_name}</b> аввалги «<b>{old_group}</b>» гуруҳида ўқишини "
            "давом эттирган ҳолда қўшимча равишда «<b>{new_group}</b>» гуруҳига ҳам қўшилди.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "stu_transfer_notify_move_father": (
            "🔄 <b>Гуруҳ ўзгариши хабарномаси</b>\n\n"
            "Ассалому алайкум, ҳурматли <b>{parent_name}</b>!\n"
            "Фарзандингиз <b>{student_name}</b> «<b>{old_group}</b>» гуруҳидан "
            "«<b>{new_group}</b>» гуруҳига ўтказилди.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "stu_transfer_notify_move_mother": (
            "🔄 <b>Гуруҳ ўзгариши хабарномаси</b>\n\n"
            "Ассалому алайкум, ҳурматли <b>{parent_name}</b>!\n"
            "Фарзандингиз <b>{student_name}</b> «<b>{old_group}</b>» гуруҳидан "
            "«<b>{new_group}</b>» гуруҳига ўтказилди.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "stu_transfer_notify_new_teacher": (
            "👨‍🏫 <b>Гуруҳингизга талаба қўшилди!</b>\n\n"
            "📚 Гуруҳ: <b>{new_group}</b>\n"
            "👤 Талаба: <b>{student_name}</b> (<code>{student_id}</code>)\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "stu_transfer_notify_old_teacher_moved": (
            "ℹ️ <b>Талаба бошқа гуруҳга ўтказилди</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📤 Аввалги гуруҳ: <b>{old_group}</b>\n"
            "📥 Янги гуруҳ: <b>{new_group}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),

        # Admin Management & Invite (?start=adm_<CODE>)
        "menu_admin_manage_admins": "👑 Админлар",
        "admin_manage_title": (
            "👑 <b>Админлар бошқаруви</b>\n\n"
            "Янги админ таклиф қилиш, мавжуд админлар рўйхатини кўриш ёки "
            "админни тизимдан ўчириш учун керакли амални танланг:"
        ),
        "btn_admin_create_invite": "🔗 Янги ҳавола",
        "btn_admin_list": "📋 Админлар рўйхати",
        "btn_admin_remove": "🗑 Админни ўчириш",
        "admin_invite_created": (
            "✅ <b>Янги админ таклиф ҳаволаси яратилди!</b>\n\n"
            "🔗 Бир марталик ҳавола:\n<code>{invite_link}</code>\n\n"
            "Ушбу ҳаволани бўлажак админга юборинг. Ҳавола орқали кириб, исм ва "
            "телефон рақамини тасдиқлагач автоматик равишда <b>Админ</b> бўлади."
        ),
        "admin_invite_invalid": (
            "❌ Кечирасиз, ушбу админ таклиф ҳаволаси яроқсиз ёки аллақачон ишлатилган."
        ),
        "admin_reg_enter_name": (
            "👑 <b>Админ сифатида рўйхатдан ўтиш</b>\n\n"
            "✍️ Илтимос, ҳақиқий <b>Фамилия ва Исмингизни</b> тўлиқ киритинг "
            "(масалан: <i>Каримов Сардор</i>):"
        ),
        "admin_reg_invalid_name": (
            "❌ Илтимос, Фамилия ва Исмингизни тўлиқ ёзинг (камида 2 та сўз, "
            "масалан: <i>Каримов Сардор</i>):"
        ),
        "admin_reg_share_phone": (
            "📱 Раҳмат, <b>{full_name}</b>!\n"
            "Админ сифатида рўйхатдан ўтишни якунлаш учун пастдаги "
            "«📱 Телефон рақамни улашиш» тугмасини босинг:"
        ),
        "admin_reg_success": (
            "✅ Ассалому алайкум, <b>{full_name}</b>!\n"
            "Сиз тизимга <b>Админ</b> сифатида муваффақиятли қўшилдингиз."
        ),
        "admin_reg_notify_inviter": (
            "👑 <b>Янги админ қўшилди!</b>\n\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📞 Телефон: <b>{phone}</b>\n"
            "🆔 Telegram ID: <code>{telegram_id}</code>"
        ),
        "admin_list_header": "👑 <b>Тизим админлари рўйхати:</b>\n",
        "admin_list_super_item": "• 🛡 <b>Бош Админ</b> (<code>{telegram_id}</code>)",
        "admin_list_dynamic_item": (
            "• 👤 <b>{full_name}</b> (<code>{telegram_id}</code>) | 📞 {phone}"
        ),
        "admin_list_empty": "ℹ️ Ҳозирча қўшимча админлар мавжуд эмас.",
        "admin_remove_select": "🗑 Тизимдан ўчирмоқчи бўлган админни танланг:",
        "admin_remove_confirm": (
            "🗑 <b>Админни ўчиришни тасдиқлайсизми?</b>\n\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "🆔 Telegram ID: <code>{telegram_id}</code>"
        ),
        "admin_removed_success": (
            "✅ Админ <b>{full_name}</b> тизимдан муваффақиятли ўчирилди."
        ),
        "admin_cannot_remove_self": (
            "⚠️ Ўзингизни админликдан ўчира олмайсиз."
        ),
        "admin_manage_cancelled": "❌ Админлар бошқаруви ёпилди.",

        # Student & Parent deep-link registration
        "link_student_not_found": (
            "❌ Кечирасиз, <code>{student_id}</code> ID рақамли талаба базадан топилмади. "
            "Админ ёки устоз билан боғланинг."
        ),
        "student_reg_enter_name": (
            "🎓 <b>Талаба сифатида рўйхатдан ўтиш</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n\n"
            "✍️ Илтимос, ҳақиқий <b>Фамилия ва Исмингизни</b> тўлиқ киритинг "
            "(масалан: <i>Алиев Вали</i>):"
        ),
        "student_reg_invalid_name": (
            "❌ Илтимос, Фамилия ва Исмингизни тўлиқ ёзинг (камида 2 та сўз, "
            "масалан: <i>Алиев Вали</i>):"
        ),
        "student_reg_share_phone": (
            "📱 Раҳмат, <b>{full_name}</b>!\n"
            "Энди пастдаги «📱 Телефон рақамни улашиш» тугмаси орқали "
            "ўзингизнинг телефон рақамингизни юборинг:"
        ),
        "link_success_student": (
            "✅ Ассалому алайкум, <b>{student_name}</b>!\n"
            "Сизнинг Telegram ҳисобингиз <b>{group}</b> гуруҳига талаба сифатида муваффақиятли боғланди."
        ),
        "parent_reg_choose_type": (
            "👨‍👩‍👧 <b>Ота-она сифатида рўйхатдан ўтиш</b>\n\n"
            "👤 Талаба: <b>{student_name}</b> ({group})\n"
            "Илтимос, ким эканлигингизни танланг:"
        ),
        "btn_parent_father": "🧔 Отаси",
        "btn_parent_mother": "🧕 Онаси",
        "parent_label_father": "Отаси",
        "parent_label_mother": "Онаси",
        "parent_reg_enter_name": (
            "✍️ Илтимос, ҳақиқий <b>Фамилия ва Исмингизни</b> тўлиқ киритинг "
            "(масалан: <i>Алиев Олим</i>):"
        ),
        "parent_reg_invalid_name": (
            "❌ Илтимос, Фамилия ва Исмингизни тўлиқ ёзинг (камида 2 та сўз):"
        ),
        "parent_reg_share_phone": (
            "📱 Раҳмат, <b>{full_name}</b>!\n"
            "Энди фарзандингиз дарслари ва тўловлари ҳақида хабарнома олиш учун "
            "пастдаги «📱 Телефон рақамни улашиш» тугмасини босинг:"
        ),
        "link_success_parent": (
            "✅ Ассалому алайкум, <b>{parent_name}</b>!\n"
            "Сизнинг Telegram ҳисобингиз <b>{student_name}</b> ({group} гуруҳи) "
            "учун <b>{parent_role}</b> сифатида муваффақиятли боғланди."
        ),
        "btn_student_no_phone": "📵 Телефон йўқ",
        "btn_add_children_via_parent": "👨‍👩‍👧‍👦 Ота-она орқали",

        # Personal Profile Editing
        "menu_profile": "⚙️ Маълумотларим",
        "profile_view_admin": (
            "👤 <b>Шахсий маълумотларим (Админ)</b>\n\n"
            "🆔 Telegram ID: <code>{user_id}</code>\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📞 Телефон: <b>{phone}</b>\n"
            "✈️ Telegram: <b>{tg}</b>"
        ),
        "menu_guest_courses": "📚 Курсларимиз",
        "menu_guest_enroll": "✍️ Курсга ёзилиш",
        "menu_guest_contact": "📍 Манзил ва алоқа",
        "menu_admin_courses": "📚 Курсларни бошқариш",
        "guest_welcome": (
            "Ассалому алайкум, <b>{name}</b>! 🌟\n\n"
            "<b>Мишкат Нодавлат Таълим Муассасаси</b>нинг расмий ботига хуш келибсиз!\n\n"
            "Бу ерда сиз:\n"
            "📚 курсларимиз ва нархлари билан танишишингиз,\n"
            "✍️ ўзингизга маъқул курсга ариза қолдиришингиз,\n"
            "📍 манзил ва алоқа маълумотларини олишингиз мумкин.\n\n"
            "Агар сиз аллақачон ўқувчимиз (ёки ота-она) бўлсангиз, устозингиз ёки "
            "администратор юборган махсус таклиф ҳаволаси орқали киринг.\n\n"
            "Керакли бўлимни танланг 👇"
        ),
        "profile_view_teacher": (
            "👤 <b>Шахсий маълумотларим (Устоз)</b>\n\n"
            "🆔 Устоз ID: <code>{teacher_id}</code>\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📞 Телефон: <b>{phone}</b>\n"
            "✈️ Telegram: <b>{tg}</b>"
        ),
        "profile_view_student": (
            "👤 <b>Шахсий маълумотларим (Талаба)</b>\n\n"
            "🆔 Талаба ID: <code>{student_id}</code>\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📞 Телефон: <b>{phone}</b>\n"
            "✈️ Telegram: <b>{tg}</b>"
        ),
        "profile_view_parent": (
            "👤 <b>Шахсий маълумотларим ({parent_role})</b>\n\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📞 Телефон: <b>{phone}</b>\n"
            "🎓 Фарзандингиз: <b>{student_name}</b> ({group})"
        ),
        "profile_enter_new_name": "✍️ Янги <b>Фамилия ва Исмингизни</b> киритинг:",
        "profile_share_new_phone": (
            "📱 Янги телефон рақамингизни юбориш учун пастдаги "
            "«📱 Телефон рақамни улашиш» тугмасини босинг:"
        ),
        "profile_updated": "✅ Шахсий маълумотларингиз муваффақиятли янгиланди!",

        # Group linking
        "link_group_private_error": (
            "ℹ️ Ушбу буйруқ фақат Telegram гуруҳ чатининг ичида ишлайди:\n"
            "<code>/link_group Гуруҳ_Номи</code>"
        ),
        "link_group_usage": (
            "ℹ️ Гуруҳ номини киритинг. Масалан:\n"
            "<code>/link_group Frontend</code>"
        ),
        "link_group_no_permission": (
            "❌ Сизда бу гуруҳни улаш учун рухсат йўқ. "
            "Фақат Админ ёки ушбу гуруҳнинг устози улаши мумкин."
        ),
        "link_group_not_found": (
            "❌ <b>{group}</b> номли гуруҳ Google Sheets'даги «Guruhlar» жадвалида топилмади."
        ),
        "link_group_success": (
            "✅ Ушбу Telegram гуруҳи <b>{group}</b> гуруҳи билан муваффақиятли боғланди!"
        ),

        # Student Group Self-Join (?start=join_<Group>)
        "join_group_not_found": (
            "❌ Кечирасиз, бундай гуруҳ топилмади. Ҳаволани текшириб қайта уриниб кўринг."
        ),
        "join_already_in_group": (
            "ℹ️ <b>{student_name}</b>, сиз аллақачон <b>{group}</b> гуруҳига аъзосиз!"
        ),
        "join_enter_full_name": (
            "📚 <b>{group}</b> гуруҳига рўйхатдан ўтиш.\n\n"
            "✍️ Илтимос, ҳақиқий <b>Фамилия ва Исмингизни</b> тўлиқ киритинг "
            "(масалан: <i>Алиев Вали</i>):"
        ),
        "join_invalid_full_name": (
            "❌ Илтимос, Фамилия ва Исмингизни тўлиқ ёзинг (камида 2 та сўз, "
            "масалан: <i>Алиев Вали</i>):"
        ),
        "join_share_phone": (
            "📱 Раҳмат, <b>{full_name}</b>!\n"
            "Энди қуйидаги «📱 Телефон рақамни улашиш» тугмаси орқали "
            "телефон рақамингизни юборинг:"
        ),
        "join_btn_share_phone": "📱 Телефон рақамни улашиш",
        "join_use_contact_button": (
            "⚠️ Илтимос, рақамни қўлда ёзманг — пастдаги "
            "«📱 Телефон рақамни улашиш» тугмасини босинг."
        ),
        "join_own_contact_only": (
            "⚠️ Илтимос, фақат ўзингизнинг телефон рақамингизни улашинг."
        ),
        "join_request_sent": (
            "⏳ <b>Сўровингиз юборилди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📞 Телефон: <b>{phone}</b>\n\n"
            "Устоз ёки администратор тасдиқлашини кутинг."
        ),
        "join_cancelled": "❌ Гуруҳга рўйхатдан ўтиш бекор қилинди.",
        "join_approval_card": (
            "🆕 <b>Гуруҳга қўшилиш сўрови</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "👤 Ф.И.О.: <b>{full_name}</b>\n"
            "📞 Телефон: <b>{phone}</b>\n"
            "💬 Telegram: {tg}\n\n"
            "Талабани гуруҳга қабул қиласизми?"
        ),
        "join_btn_approve": "✅ Тасдиқлаш",
        "join_btn_reject": "❌ Рад этиш",
        "join_already_processed": "ℹ️ Ушбу сўров аллақачон кўриб чиқилган.",
        "join_no_permission": "❌ Сизда ушбу сўровни тасдиқлаш ҳуқуқи йўқ.",
        "join_approved_card": (
            "✅ <b>Сўров тасдиқланди!</b>\n"
            "👤 Талаба: <b>{full_name}</b> (<code>{student_id}</code>)\n"
            "📚 Гуруҳ: <b>{group}</b>"
        ),
        "join_rejected_card": (
            "❌ <b>Сўров рад этилди.</b>\n"
            "👤 Талаба: <b>{full_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>"
        ),
        "join_approved_student": (
            "🎉 <b>Табриклаймиз, {full_name}!</b>\n"
            "Сизнинг <b>{group}</b> гуруҳига қўшилиш сўровингиз тасдиқланди.\n"
            "🆔 Талаба ID: <code>{student_id}</code>"
        ),
        "join_rejected_student": (
            "❌ Кечирасиз, сизнинг <b>{group}</b> гуруҳига қўшилиш сўровингиз рад этилди."
        ),

        # Group Management, Full Update Wizard & Group Price Setup
        "group_menu_title": "📚 <b>Гуруҳлар бўлими</b>\nКеракли амални танланг:",
        "group_edit_select": "✏️ Таҳрирлаш учун гуруҳни танланг:",
        "group_edit_info": (
            "📚 <b>Гуруҳ: {group}</b>\n\n"
            "👨‍🏫 Устоз: <b>{teacher_name}</b>\n"
            "🔢 Ойлик дарслар: <b>{count} та</b>\n"
            "📆 Кунлар: <b>{days}</b>\n"
            "⏰ Вақт: <b>{time}</b>\n\n"
            "Қайси маълумотни ўзгартирмоқчисиз?"
        ),
        "group_edit_info_with_price": (
            "📚 <b>Гуруҳ: {group}</b>\n\n"
            "👨‍🏫 Устоз: <b>{teacher_name}</b>\n"
            "🔢 Ойлик дарслар: <b>{count} та</b>\n"
            "📆 Кунлар: <b>{days}</b>\n"
            "⏰ Вақт: <b>{time}</b>\n"
            "💰 Ойлик тўлов: <b>{price}</b>\n\n"
            "Қайси маълумотни ўзгартирмоқчисиз?"
        ),
        "group_edit_saved": "✅ <b>{group}</b> гуруҳи маълумотлари янгиланди!",
        "btn_group_price": "💰 Тўлов суммаси",
        "btn_group_full_update": "🔄 Тўлиқ янгилаш",
        "btn_archive_group": "🗄 Захира гуруҳи",
        "btn_delete_group": "🗑 Гуруҳни ўчириш",
        "btn_keep_current": "⏭ Эскиси қолсин",
        # Admin "✏️ Гуруҳни таҳрирлаш" panel: one button per group attribute
        "btn_grp_edit_name": "📝 Гуруҳ номини ўзгартириш",
        "btn_grp_edit_teacher": "👨‍🏫 Устозни ўзгартириш",
        "btn_grp_edit_days": "📆 Дарс кунларини ўзгартириш",
        "btn_grp_edit_time": "⏰ Дарс вақтини ўзгартириш",
        "btn_grp_edit_price": "💰 Ойлик тўловни ўзгартириш",
        "btn_grp_edit_count": "🔢 Ойлик дарслар сонини ўзгартириш",
        "btn_grp_edit_chat": "💬 Гуруҳ чат ID ни ўзгартириш",
        "btn_grp_edit_start": "📅 Бошланиш санасини ўзгартириш",
        "group_edit_extra_info": (
            "📅 Бошланиш санаси: <b>{start}</b>\n"
            "💬 Гуруҳ чат ID: <code>{chat}</code>"
        ),
        "grp_edit_enter_chat_id": (
            "💬 <b>{group}</b> — гуруҳ Telegram чат ID сини ўзгартириш\n\n"
            "Жорий чат ID: <code>{current}</code>\n\n"
            "Янги чат ID ни киритинг (масалан: <code>-1001234567890</code>):"
        ),
        "grp_edit_invalid_chat_id": (
            "❌ Чат ID нотўғри. Фақат рақамлардан иборат бўлиши керак "
            "(масалан: <code>-1001234567890</code>). Қайтадан киритинг:"
        ),
        "grp_edit_chat_saved": (
            "✅ <b>{group}</b> гуруҳининг чат ID си янгиланди: <code>{chat}</code>"
        ),
        "grp_edit_start_calendar_title": (
            "📅 <b>{group}</b> — бошланиш санасини ўзгартириш\n\n"
            "Жорий бошланиш санаси: <b>{current}</b>\n"
            "Дарс кунлари: <b>{days}</b> | Ойлик дарслар: <b>{count} та</b>\n\n"
            "Календардан янги бошланиш санасини танланг. Жорий циклнинг "
            "барча дарс саналари шу кундан бошлаб қайта тузилади:"
        ),
        "grp_edit_start_saved": (
            "✅ <b>{group}</b> гуруҳининг бошланиш санаси янгиланди!\n\n"
            "📅 Бошланиш: <b>{start}</b>\n"
            "🏁 Тугаш: <b>{end}</b>\n"
            "🔢 Ўтилган дарслар: <b>{elapsed}/{total}</b>\n\n"
            "🗓 <b>Янги дарс жадвали:</b>\n{schedule}"
        ),
        "grp_edit_start_all_past": (
            "⚠️ Бу санадан бошланган циклнинг барча дарслари аллақачон ўтиб кетган. "
            "Илтимос, яқинроқ санани танланг."
        ),
        "grp_edit_start_year_mismatch": (
            "⚠️ Жорий цикл {year}-йил жадвалида жойлашган. Илтимос, {year}-йил "
            "ичидаги санани танланг."
        ),
        "grp_edit_start_no_days": (
            "⚠️ Аввал гуруҳнинг дарс кунларини белгиланг."
        ),
        "grp_edit_start_nearest": "📅 {date} — энг яқин дарс куни",
        "callback_token_expired": (
            "⌛️ Бу тугма эскирган. Илтимос, менюдан қайтадан танланг."
        ),
        "group_full_edit_name": (
            "1/6 📝 <b>Гуруҳ номи</b>\n"
            "Ҳозирги қиймат: <b>{current}</b>\n"
            "Янги гуруҳ номини киритинг ёки «⏭ Эски ҳолатида қолдириш» тугмасини босинг:"
        ),
        "group_full_edit_count": (
            "2/6 🔢 <b>Ойлик дарслар сони</b>\n"
            "Ҳозирги қиймат: <b>{current} та</b>\n"
            "Янги дарс сонини танланг ёки эски ҳолатида қолдиринг:"
        ),
        "group_full_edit_days": (
            "3/6 📆 <b>Дарс кунлари</b>\n"
            "Ҳозирги қиймат: <b>{current}</b>\n"
            "Ҳафта кунларини белгиланг ёки эски ҳолатида қолдиринг:"
        ),
        "group_full_edit_time": (
            "4/6 ⏰ <b>Дарс вақти</b>\n"
            "Ҳозирги қиймат: <b>{current}</b>\n"
            "Дарс вақтини қандай белгилашни танланг ёки эски ҳолатида қолдиринг:"
        ),
        "group_full_edit_price": (
            "5/6 💰 <b>Ойлик тўлов суммаси</b>\n"
            "Ҳозирги қиймат: <b>{current}</b>\n"
            "Янги суммани киритинг (минг сўмда, масалан <code>500</code>) ёки эски ҳолатида қолдиринг:"
        ),
        "group_full_edit_tg_chat": (
            "6/6 💬 <b>Гуруҳ Telegram Chat ID</b>\n"
            "Ҳозирги қиймат: <b>{current}</b>\n"
            "Янги Telegram Chat ID киритинг (масалан <code>-1001234567890</code>) ёки эски ҳолатида қолдиринг:"
        ),
        "group_change_broadcast": (
            "📢 <b>Гуруҳ маълумотлари янгиланди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "👨‍🏫 Устоз: <b>{teacher_name}</b>\n"
            "📆 Кунлар: <b>{days}</b> | ⏰ Вақт: <b>{time}</b>\n"
            "🔢 Ойлик дарслар: <b>{count} та</b>\n"
            "💰 Ойлик тўлов: <b>{price}</b>\n\n"
            "<i>Ўзгаришлар: {changes}</i>"
        ),
        "group_price_select_group": "💰 Ойлик тўлов суммасини белгилаш учун гуруҳни танланг:",
        "group_price_enter": (
            "💰 <b>{group} — Гуруҳ тўлов суммаси</b>\n\n"
            "Ойлик тўлов суммасини минг сўмда киритинг.\n"
            "💡 <i>Масалан:</i> <code>500</code> ёзсангиз — автоматик равишда "
            "<b>500 000 сўм</b> деб сақланади (ёки тўлиқ <code>500000</code> киритинг):"
        ),
        "group_price_invalid": (
            "❌ Нотўғри сумма киритилди. Илтимос, фақат мусбат сон киритинг "
            "(масалан: <code>500</code> → 500 000 сўм)."
        ),
        "group_price_saved": (
            "✅ <b>{group}</b> гуруҳи учун ойлик тўлов суммаси сақланди: <b>{price}</b>."
        ),
        "group_price_not_set": "Белгиланмаган",
        "student_add_choose_method": (
            "➕ <b>Янги талаба қўшиш</b>\n\n"
            "Талабани қандай усулда қўшмоқчисиз?"
        ),
        "student_invite_link_created": (
            "🔗 <b>Талаба таклиф ҳаволаси яратилди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "👉 Ҳавола:\n<code>{invite_link}</code>\n\n"
            "Талаба ушбу ҳавола орқали кириб, ўз исми ва телефон рақамини юборгач, "
            "сизга тасдиқлаш учун сўров келади."
        ),

        # Common buttons
        "btn_back": "⬅️ Орқага",
        "btn_cancel": "❌ Бекор қилиш",
        "btn_confirm": "✅ Тасдиқлаш",
        "btn_edit": "✏️ Ўзгартириш",
        "btn_details": "📄 Батафсил",
        "btn_detailed": "📄 Батафсил",
        "btn_compact": "🔼 Қисқача",
        "btn_short": "📋 Қисқача",
        "btn_present": "🟢 Қатнашди",
        "btn_absent": "🔴 Келмади",
        "btn_finish": "✅ Якунлаш",

        # Admin menu buttons
        "menu_admin_groups": "📚 Гуруҳлар",
        "menu_admin_students": "👥 Талабалар",
        "menu_admin_schedule": "📅 Дарс жадвали",
        "menu_admin_cancel_lesson": "🚫 Дарсни бекор қилиш",
        "menu_admin_attendance": "📋 Йўқлама қилиш",
        "menu_admin_payments": "💳 Тўловлар",
        "menu_admin_debtors": "⚠️ Қарздорлар",

        # Teacher menu buttons
        "menu_teacher_topic": "📝 Дарс мавзуси",
        "menu_teacher_groups": "👥 Гуруҳларим",
        "menu_teacher_attendance": "📋 Йўқлама қилиш",
        "menu_teacher_add_student": "➕ Талаба қўшиш",
        "menu_teacher_schedule": "📅 Дарс жадвали",
        "menu_teacher_cancel_lesson": "🚫 Дарсни бекор қилиш",
        "menu_teacher_payments": "💳 Тўловлар",
        "menu_teacher_debtors": "⚠️ Қарздорлар",

        # Teacher detailed group roster view
        "teacher_roster_header": (
            "📚 <b>Гуруҳ: {group}</b>\n"
            "👨‍🏫 Устоз: <b>{teacher_name}</b>\n"
            "📆 Дарс кунлари: <b>{days}</b> | ⏰ Вақт: <b>{time}</b>\n"
            "🔢 Сикл: <b>{count} та дарс</b> | 👥 Жами фаол талабалар: <b>{total} та</b>\n\n"
            "🔗 Талабалар ўзи қўшилиш ҳаволаси:\n<code>{join_link}</code>\n\n"
            "<b>Талабалар ва ота-оналар рўйхати:</b>"
        ),
        "roster_student_line": (
            "{idx}. <b>{full_name}</b>\n"
            "   📞 Талаба: {phone} | 💬 {tg}"
        ),
        "roster_father_line": "   🧔‍♂️ Отаси: <b>{father_name}</b> | 📞 {father_phone}",
        "roster_mother_line": "   🧕 Онаси: <b>{mother_name}</b> | 📞 {mother_phone}",
        "roster_bot_status_line": "   🤖 Бот: Талаба ({stu_status}), Ота-она ({par_status})",

        # Lesson Topic & Plan builder + Polite 1-Day Reminder
        "menu_lesson_topic": "📝 Дарс мавзуси",
        "btn_enter_topic_plan": "📝 Мавзу/режа киритиш",
        "btn_past_topics_history": "📚 Мавзулар тарихи",
        "topic_history_header": "📚 <b>{group} — Олдинги киритилган мавзулар:</b>\n",
        "topic_history_empty": "ℹ️ Ушбу гуруҳ учун ҳали мавзу ва режа киритилмаган.",
        "reminder_teacher_1day_before": (
            "Ассалому алайкум, ҳурматли <b>{teacher_name}</b> устоз!\n"
            "Эртага «<b>{group_name}</b>» гуруҳида дарсингиз бор.\n"
            "Талабалар ва ота-оналар олдиндан тайёрланишлари учун эртанги дарс "
            "мавзуси ва режасини киритиб қўйишингизни илтимос қиламиз."
        ),
        "topic_select_group": "📝 Дарс мавзуси ва режасини киритиш учун гуруҳни танланг:",
        "topic_select_date": (
            "📅 <b>{group}</b> — қайси дарс санаси учун мавзу ва режа киритасиз?"
        ),
        "topic_existing_view": (
            "📝 <b>Сақланган дарс мавзуси ва режаси</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📅 Сана: <b>{date}</b>\n"
            "📖 Мавзу: <b>{topic_title}</b>\n"
            "📋 Мазмуни / Уйга вазифа:\n<i>{lesson_details}</i>"
        ),
        "topic_enter_title": (
            "📖 <b>{group} ({date})</b> дарси учун <b>Мавзу</b> номини киритинг:"
        ),
        "topic_invalid_title": (
            "❌ Мавзу номи бўш бўлиши мумкин эмас. Илтимос, мавзуни киритинг:"
        ),
        "topic_enter_details": (
            "📋 Раҳмат! Энди ушбу дарсда <b>нималар ўтилиши / дарс мазмуни ва уйга вазифа</b> "
            "ҳақида ёзинг:"
        ),
        "topic_invalid_details": (
            "❌ Илтимос, дарс мазмунини киритинг (камида бир нечта сўз):"
        ),
        "topic_confirm_preview": (
            "📝 <b>Дарс мавзуси ва режаси тайёр!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📅 Сана: <b>{date}</b>\n"
            "📖 Мавзу: <b>{topic_title}</b>\n"
            "📋 Нималар ўтилади / Вазифа:\n<i>{lesson_details}</i>\n\n"
            "Маълумотни сақлаб, гуруҳ чатига юборамизми?"
        ),
        "btn_topic_broadcast": "📢 Гуруҳга юбориш",
        "btn_send_to_group": "📢 Гуруҳга юбориш",
        "btn_topic_save_only": "💾 Фақат сақлаш",
        "btn_topic_edit": "✏️ Таҳрирлаш",
        "topic_status_added": "➕ Мавзуларга қўшимча киритилди",
        "topic_status_updated": "✏️ Дарс мавзуси ўзгартирилди",
        "topic_teacher_footer": "Ҳурмат билан, гуруҳ устози {teacher_name}",
        "topic_saved": (
            "✅ <b>{group} ({date})</b> учун дарс мавзуси ва режаси сақланди!"
        ),
        "topic_broadcasted": (
            "✅ Дарс мавзуси ва режаси сақланди ҳамда <b>{group}</b> Telegram гуруҳига юборилди!"
        ),
        "topic_no_group_chat": (
            "⚠️ Мавзу сақланди, лекин <b>{group}</b> гуруҳига Telegram чат боғланмаган.\n"
            "Гуруҳга юбориш учун Telegram гуруҳ ичида <code>/link_group {group}</code> буйруғини ёзинг."
        ),
        "topic_group_broadcast_msg": (
            "📢 <b>Дарс мавзуси ва режаси</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📅 Сана: <b>{date}</b>\n"
            "📖 Мавзу: <b>{topic_title}</b>\n\n"
            "📝 <b>Дарсда ўтиладиган мавзулар / вазифа:</b>\n{lesson_details}\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "topic_cancelled": "❌ Дарс мавзуси ва режасини киритиш бекор қилинди.",

        # Student menu buttons
        "menu_student_group": "👥 Менинг гуруҳим",
        "menu_student_schedule": "📅 Дарс жадвали",
        "menu_student_payments": "💳 Тўлов ва қарзлар",

        # Parent menu buttons
        "menu_parent_schedule": "📅 Фарзандим жадвали",
        "menu_parent_payments": "💳 Тўлов ва қарзлар",

        # Human-friendly cycle & lesson labels
        "human_cycle_label": "{num}-ўқув ойи ({count} та дарс)",
        "human_cycle_label_prorated": "{num}-ўқув ойи (қолган {remaining} та дарс)",
        "lesson_status_present": "✅ Қатнашди",
        "lesson_status_absent": "❌ Келмади",
        "lesson_status_pending": "⏳ Кутилмоқда",
        "lesson_line_template": "{lesson_num}-дарс | {date} ({weekday}) — {status}",
        "next_payment_template": "{lesson_num}-дарс якунида ({date})",
        "payment_card_block": (
            "💳 Тўлов учун карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>"
        ),

        # Schedule setup & cancel lesson
        "schedule_select_group": "📅 Дарс жадвалини созлаш учун гуруҳни танланг:",
        "schedule_select_count": "Бир ўқув ойидаги дарслар сонини танланг:",
        "schedule_select_days": (
            "Ҳафта дарс кунларини белгиланг ва «✅ Тасдиқлаш» тугмасини босинг:"
        ),
        "schedule_enter_time": "Дарс бошланиш вақтини киритинг (формат: <code>HH:MM</code>, масалан: <code>14:00</code>):",
        "schedule_invalid_time": "❌ Нотўғри вақт формати. Илтимос <code>HH:MM</code> кўринишида ёзинг (масалан: <code>09:00</code>).",
        "lesson_time_mode_prompt": "🕒 <b>Дарс вақтини қандай белгилаймиз?</b>\n\nТанланган кунлар: <b>{days}</b>",
        "btn_lesson_time_uniform": "🕒 Ҳамма кунларга бир хил вақт",
        "btn_lesson_time_per_day": "⚙️ Ҳар бир кун учун алоҳида вақт",
        "lesson_time_day_prompt": "{n}/{total} — <b>{day}</b> куни дарс соати нечада? (Масалан: <code>14:00</code>)",
        "lesson_time_missing_days_alert": "⚠️ Янги кунлар учун дарс вақти белгиланмаган. Илтимос, вақтни қайта белгиланг.",
        "schedule_confirm_summary": (
            "📅 <b>Дарс жадвали тасдиқлансинми?</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🔢 Ойлик дарслар сони: <b>{count} та</b>\n"
            "📆 Кунлар: <b>{days}</b>\n"
            "⏰ Вақт: <b>{time}</b>\n"
            "🗓 Биринчи ўқув ойи: <b>{cycle_title}</b> ({start_date} — {end_date})"
        ),
        "schedule_saved": "✅ <b>{group}</b> гуруҳи учун дарс жадвали сақланди ва янги ўқув ойи жадвали яратилди.",
        "schedule_notify_user": (
            "📅 <b>Дарс жадвали янгиланди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📆 Кунлар: <b>{days}</b>\n"
            "⏰ Вақт: <b>{time}</b>\n"
            "🔢 Ҳар бир ўқув ойи: <b>{count} та дарс</b>"
        ),
        "schedule_view_student": (
            "📅 <b>Дарс жадвалингиз</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📆 Дарс кунлари: <b>{days}</b>\n"
            "⏰ Дарс вақти: <b>{time}</b>\n"
            "📊 Ойлик режа: <b>{count} та дарс</b>"
        ),
        "schedule_view_parent": (
            "📅 <b>Фарзандингизнинг дарс жадвали</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📆 Дарс кунлари: <b>{days}</b>\n"
            "⏰ Дарс вақти: <b>{time}</b>\n"
            "📊 Ойлик режа: <b>{count} та дарс</b>"
        ),
        "cancel_lesson_select_group": "🚫 Бугунги дарсини бекор қилмоқчи бўлган гуруҳни танланг:",
        "cancel_lesson_no_today": "ℹ️ Бугун дарси белгиланган гуруҳлар топилмади.",
        "cancel_lesson_enter_reason": "📝 <b>{group}</b> гуруҳи дарсини бекор қилиш сабабини ёзинг:",
        "cancel_lesson_confirm": (
            "🚫 <b>Дарсни бекор қилишни тасдиқлайсизми?</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📅 Сана: <b>{date}</b>\n"
            "📝 Сабаб: <i>{reason}</i>"
        ),
        "cancel_lesson_notify_private": (
            "🚫 <b>Дарс бекор қилинди</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📅 Бугунги ({date}) дарс бекор қилинди.\n"
            "📝 Сабаб: <i>{reason}</i>\n"
            "➡️ Ўқув ойи охирига қўшимча дарс санаси қўшилди: <b>{new_end_date}</b>"
        ),
        "cancel_lesson_notify_group": (
            "🚫 <b>Диққат! Бугунги дарс бекор қилинди.</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📅 Сана: <b>{date}</b>\n"
            "📝 Сабаб: <i>{reason}</i>\n"
            "➡️ Ушбу дарс ўқув ойи охирига ({new_end_date}) кўчирилди."
        ),

        # Attendance
        "attendance_select_group": "📋 Йўқлама қилиш учун гуруҳни танланг:",
        "attendance_no_groups_today": "ℹ️ Йўқлама учун гуруҳлар топилмади.",
        "attendance_btn_today": "📅 Бугун, {today_date}",
        "attendance_btn_other_day": "🗓 Бошқа кун",
        "attendance_past_date_notice": "⚠️ Ўтиб кетган ({sana}) ги дарс йўқламаси қилинди\n\n",
        "attendance_topic_line": "📖 Мавзу: \"{mavzu}\"\n",
        "attendance_signature": "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!",
        "attendance_student_present": (
            "🟢 Ҳурматли <b>{talaba_ismi}</b>,\n\n"
            "Сиз <b>{guruh_nomi}</b> гуруҳида <b>{sana_uz} ({hafta_kuni})</b> кунги ўтказилган <b>{dars_raqami}-дарс</b>га қатнашдингиз.\n"
            "{mavzu_qatori}Биз сизнинг билим олишдаги қатъиятингиз ва иштиёқингизни юқори баҳолаймиз."
            "{talaba_qarz_eslatmasi}\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "attendance_student_absent": (
            "🔴 Ҳурматли <b>{talaba_ismi}</b>,\n\n"
            "Сиз <b>{guruh_nomi}</b> гуруҳида <b>{sana_uz} ({hafta_kuni})</b> кунги ўтказилган <b>{dars_raqami}-дарс</b>да қатнашмадингиз.\n"
            "{mavzu_qatori}Янги мавзуларни ўтказиб юбормаслик учун дарс материаллари ва уйга вазифаларни кўриб чиқишингизни тавсия қиламиз. Кейинги дарсда сизни албатта кутамиз!"
            "{talaba_qarz_eslatmasi}\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "attendance_student_debt_note": (
            "\n\n💳 Эслатма: Жорий ўқув ойи учун <b>{qarz_summasi} сўм</b> тўлов ҳали амалга оширилмаган. Тўловни 1-дарсдан кечиктирмай амалга оширишингизни сўраймиз.\n"
        ),
        "attendance_parent_present": (
            "🟢 Ассалому алайкум, ҳурматли {ota_ona_ismi}!\n\n"
            "Фарзандингиз <b>{talaba_ismi}</b> <b>{guruh_nomi}</b> гуруҳида <b>{sana_uz} ({hafta_kuni})</b> кунги ўтказилган <b>{dars_raqami}-дарс</b>га қатнашди.\n"
            "{mavzu_qatori}Биз фарзандингизнинг билим олишдаги қатъияти ва интилишини юқори баҳолаймиз!"
            "{ota_ona_qarz_eslatmasi}\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "attendance_parent_absent": (
            "🔴 Ассалому алайкум, ҳурматли {ota_ona_ismi}!\n\n"
            "Фарзандингиз <b>{talaba_ismi}</b> <b>{guruh_nomi}</b> гуруҳида <b>{sana_uz} ({hafta_kuni})</b> кунги ўтказилган <b>{dars_raqami}-дарс</b>да қатнашмади.\n"
            "{mavzu_qatori}Янги мавзуларни ўтказиб юбормаслик учун дарс материаллари ва уйга вазифаларни кўриб чиқишини тавсия қиламиз. Кейинги дарсда албатта кутиб қоламиз!"
            "{ota_ona_qarz_eslatmasi}\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "attendance_parent_debt_note": (
            "\n\n💳 Эслатма: Фарзандингизнинг жорий ўқув ойи учун <b>{qarz_summasi} сўм</b> тўлови ҳали амалга оширилмаган. Тўловни 1-дарсдан кечиктирмай амалга оширишингизни ҳурмат билан сўраймиз.\n"
        ),
        "attendance_student_debt_note_prorated": (
            "\n\n💳 Эслатма: Жорий ўқув ойининг қолган {remaining_lessons} та дарси учун <b>{qarz_summasi} сўм</b> тўлов ҳали амалга оширилмаган. Тўловни 1-дарсдан кечиктирмай амалга оширишингизни сўраймиз.\n"
        ),
        "attendance_parent_debt_note_prorated": (
            "\n\n💳 Эслатма: Фарзандингизнинг жорий ўқув ойининг қолган {remaining_lessons} та дарси учун <b>{qarz_summasi} сўм</b> тўлови ҳали амалга оширилмаган. Тўловни 1-дарсдан кечиктирмай амалга оширишингизни ҳурмат билан сўраймиз.\n"
        ),
        "group_lesson_progress": (
            "📋 <b>Дарс якунланди</b>\n\n"
            "📚 Гуруҳ: <b>{group_name}</b>\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>\n"
            "✅ Ўтилган дарс: <b>{lesson_num}-дарс</b> (жами <b>{total_lessons} та</b> дарсдан) — <b>{date_str}</b>\n"
            "{optional_topic_line}\n"
            "Ҳурмат билан,\n"
            "Гуруҳ устози: <b>{teacher_name}</b>"
        ),
        "group_lesson_progress_topic_line": "📖 Мавзу: <b>{topic}</b>\n",
        "btn_change_start_date": "📅 Бошланиш санасини ўзгартириш",
        "add_group_start_date_lines": (
            "📅 Бошланиш санаси: <b>{start_date}</b>\n"
            "🏁 Сикл тугаш санаси: <b>{end_date}</b>"
        ),
        "add_group_calendar_title": (
            "📅 <b>Сикл бошланиш санасини танланг</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "Ҳозирги танлов: <b>{selected}</b>\n\n"
            "<i>Ўтган ёки келгуси санани босинг.</i>"
        ),
        "btn_enroll_full": "📚 Ой бошидан бери ўқийди",
        "btn_enroll_new": "🆕 Бугундан қўшилди (Янги талаба)",
        "enroll_choice_prompt": (
            "🗓 <b>{group}</b> гуруҳининг жорий ўқув ойида (<b>{cycle_title}</b>) "
            "<b>{past_count} та</b> дарс аллақачон ўтиб бўлган.\n\n"
            "👤 Талаба: <b>{student_name}</b>\n\n"
            "Талаба қайси ҳолатда қўшилади?"
        ),
        "enroll_result_full": (
            "📚 Ўтган <b>{marked} та</b> дарс жимгина ✅ деб белгиланди (хабарномасиз).\n"
            "💰 Тўлиқ ойлик тўлов: <b>{amount} сўм</b>"
        ),
        "enroll_result_new": (
            "🆕 Жорий ўқув ойининг қолган <b>{remaining} та</b> дарси учун тўлов: "
            "<b>{amount} сўм</b>.\n"
            "Кейинги ўқув ойидан бошлаб тўлиқ ойлик тўлов қўлланади."
        ),
        "attendance_multi_header": (
            "📋 Ассалому алайкум, ҳурматли {ota_ona_ismi}!\n\n"
            "Фарзандларингизнинг <b>{sana_uz} ({hafta_kuni})</b> кунги ўтказилган дарслар бўйича давомат маълумоти:\n\n"
        ),
        "attendance_multi_child": (
            "{status_emoji} {tartib}. <b>{talaba_ismi}</b>\n"
            "📚 Дарс/Гуруҳ: <b>{guruh_nomi}</b> • <b>{dars_raqami}-дарс</b>\n"
            "🗓 Дарс куни: {hafta_kuni} | Ҳолати: {holat_matni}\n"
            "👨‍🏫 Устоз: {oqituvchi_ismi}\n"
            "{mavzu_qatori}\n"
            "──────────────────"
        ),
        "attendance_multi_status_present": "Дарсга қатнашди",
        "attendance_multi_status_absent": "Дарсга қатнашмади",
        "attendance_multi_debt_title": "💳 Тўлов эслатмаси:",
        "attendance_multi_debt_item": (
            "• <b>{talaba_ismi}</b> — <b>{qarz_summasi} сўм</b> қарздорлик мавжуд. "
            "Жорий ўқув ойи тўловини 1-дарсдан кечиктирмай амалга оширишингизни сўраймиз."
        ),
        "parent_pay_header": "💳 Фарзандларингизнинг тўлов ва қарздорлик ҳолати:\n\n",
        "parent_pay_child": (
            "👶 {tartib}. {talaba_ismi}\n"
            "📚 Дарс/Гуруҳ: {guruh_nomi}\n"
            "💵 Ойлик тўлов: {oylik_tolov} сўм\n"
            "📊 Ҳолати: {tolov_holati}\n"
            "❗️ Қарздорлик: {qarz_summasi} сўм"
        ),
        "parent_pay_separator": "\n\n──────────────────\n\n",
        "parent_pay_total": "\n\n💰 Умумий қарздорлик: {umumiy_qarz} сўм",
        "parent_pay_status_paid": "✅ Тўланган",
        "parent_pay_status_unpaid": "❌ Тўланмаган",
        "parent_sched_btn_back": "🔙 Ортга",
        "attendance_select_date": (
            "📅 <b>{group} — Йўқлама санасини танланг</b>\n\n"
            "Бугунги дарсни белгилашингиз, қолиб кетган ўтган дарсни тўлдиришинги "
            "ёки аввал белгиланган йўқламани таҳрирлашингиз мумкин:"
        ),
        "attendance_date_btn_marked": "{date} ({weekday}) — ✅ Белгиланган",
        "attendance_date_btn_unmarked": "{date} ({weekday}) — ⏳ Белгиланмаган",
        "attendance_date_btn_cancelled": "{date} ({weekday}) — 🚫 Бекор қилинган",
        "attendance_no_cycle_dates": (
            "ℹ️ <b>{group}</b> гуруҳи учун фаол ўқув ойи жадвали топилмади. "
            "Аввал «📅 Дарс жадвали» бўлимидан жадвал яратинг."
        ),
        "attendance_mark_title": (
            "📋 <b>Йўқлама: {group}</b> ({date})\n"
            "Ҳар бир талаба ҳолатини белгиланг ва «✅ Якунлаш» тугмасини босинг:"
        ),
        "attendance_pending_5min": (
            "⏳ <b>{group}</b> гуруҳи йўқламаси навбатга қўйилди.\n"
            "5 дақиқадан сўнг сақланади ҳамда талаба ва ота-оналарга юборилади.\n\n"
            "🟢 Қатнашди: <b>{present_count}</b> | 🔴 Келмади: <b>{absent_count}</b>"
        ),
        "attendance_saved_instant": (
            "✅ <b>{group}</b> гуруҳи ({date}) йўқламаси дарҳол сақланди "
            "ва барча хабарномалар юборилди!\n\n"
            "🟢 Қатнашди: <b>{present_count}</b> | 🔴 Келмади: <b>{absent_count}</b>"
        ),
        "attendance_updated_instant": (
            "🔄 <b>{group}</b> гуруҳи ({date}) йўқламаси қайта текширилиб янгиланди!\n\n"
            "🟢 Қатнашди: <b>{present_count}</b> | 🔴 Келмади: <b>{absent_count}</b>"
        ),
        "attendance_cancelled": "❌ Йўқлама бекор қилинди. Маълумотлар сақланмади.",
        "attendance_committed": (
            "✅ <b>{group}</b> гуруҳи ({date}) йўқламаси сақланди "
            "ва хабарномалар юборилди."
        ),
        "attendance_notify_present": (
            "🟢 <b>Давомат хабарномаси</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📅 Сана: <b>{date}</b>\n"
            "Ҳолат: <b>Қатнашди ✅</b>"
        ),
        "attendance_notify_absent": (
            "🔴 <b>Давомат хабарномаси</b>\n\n"
            "Ассалому алайкум, <b>{student_name}</b>!\n"
            "Сиз <b>{date}</b> кунги <b>{group}</b> гуруҳи дарсида қатнаша олмадингиз (Келмади ❌).\n"
            "Илтимос, кейинги дарсгача ўтилган мавзуни кўриб чиқиб, тайёрланиб келинг.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "attendance_notify_absent_parent": (
            "🔴 <b>Давомат хабарномаси</b>\n\n"
            "Ассалому алайкум!\n"
            "Сизга шуни маълум қиламизки, фарзандингиз <b>{student_name}</b> "
            "<b>{date}</b> кунги <b>{group}</b> гуруҳи дарсида қатнашмади (Келмади ❌).\n"
            "Илтимос, дарсларга мунтазам қатнашишини назорат қилиб боришингизни сўраймиз.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "attendance_notify_updated_present": (
            "🔄 <b>Давомат ҳолати янгиланди</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "📅 Сана: <b>{date}</b>\n"
            "Янги ҳолат: <b>Қатнашди ✅</b>"
        ),
        "attendance_notify_updated_absent": (
            "🔄 <b>Давомат ҳолати янгиланди</b>\n\n"
            "Ассалому алайкум, <b>{student_name}</b>!\n"
            "<b>{date}</b> кунги <b>{group}</b> гуруҳи дарсидаги ҳолатингиз "
            "<b>Келмади ❌</b> деб янгиланди.\n"
            "Илтимос, ўтилган мавзуни мустақил ўзлаштириб, кейинги дарсга тайёрланиб келинг.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "attendance_notify_updated_absent_parent": (
            "🔄 <b>Давомат ҳолати янгиланди</b>\n\n"
            "Ассалому алайкум!\n"
            "Сизга маълум қиламизки, фарзандингиз <b>{student_name}</b>нинг "
            "<b>{date}</b> кунги <b>{group}</b> гуруҳи дарсидаги давомати "
            "<b>Келмади ❌</b> деб янгиланди.\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "attendance_topic_addon": (
            "\n\n📚 Мавзу: <b>{topic_title}</b>\n"
            "📝 Ўтилган дарс мазмуни: <i>{lesson_details}</i>"
        ),
        "attendance_topic_title_only_addon": (
            "\n\n📚 Мавзу: <b>{topic_title}</b>"
        ),
        "admin_attendance_report_compact": (
            "📋 <b>Давомат ҳисоботи{updated_badge}</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "👨‍🏫 Устоз: <b>{teacher_name}</b>\n"
            "📅 Сана: <b>{date}</b> | ⏰ <b>{lesson_time}</b>\n"
            "🟢 Қатнашди: <b>{present_count}</b> та | 🔴 Келмади: <b>{absent_count}</b> та"
        ),
        "admin_attendance_report_detailed": (
            "📋 <b>Давомат ҳисоботи (Батафсил){updated_badge}</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "👨‍🏫 Устоз: <b>{teacher_name}</b>\n"
            "📅 Сана: <b>{date}</b> | ⏰ <b>{lesson_time}</b>\n"
            "🟢 Қатнашди: <b>{present_count}</b> та | 🔴 Келмади: <b>{absent_count}</b> та\n\n"
            "🟢 <b>Қатнашганлар:</b>\n{present_lines}\n\n"
            "🔴 <b>Келмаганлар (Алоқа учун):</b>\n{absent_lines}\n\n"
            "⚠️ <b>Қарздорлар:</b>\n{debtor_lines}"
        ),
        "admin_report_updated_tag": " (Янгиланди 🔄)",

        # Cycle completion & Payments (Confirm + Revert)
        "cycle_completed_remind_student": (
            "🔔 <b>Ўқув ойи якунланди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Давр: <b>{cycle_title}</b>\n\n"
            "Кейинги дарслар учун ойлик тўловни амалга оширишингизни сўраймиз.\n\n"
            "💳 Тўлов учун карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>"
        ),
        "cycle_completed_remind_parent": (
            "🔔 <b>Ўқув ойи якунланди!</b>\n\n"
            "👤 Фарзандингиз: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Давр: <b>{cycle_title}</b>\n\n"
            "Илтимос, навбатдаги ойлик тўловни ўз вақтида амалга оширинг.\n\n"
            "💳 Тўлов учун карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>"
        ),
        "cycle_completed_report_teacher": (
            "📊 <b>Ўқув ойи якунланди: {group}</b>\n"
            "🗓 Якунланган давр: <b>{cycle_title}</b>\n"
            "🆕 Янги ўқув ойи автоматик очилди: <b>{next_cycle_title}</b>"
        ),
        "btn_payment_confirm": "✅ Тасдиқлаш",
        "btn_payment_revert": "↩️ Қайтариш",
        "payment_select_group": "💰 Тўловни тасдиқлаш учун гуруҳни танланг:",
        "payment_select_student": "👤 Талабани танланг (<b>{group}</b>):",
        "payment_select_cycle": "🗓 Тўлов қилинаётган ўқув ойини танланг:",
        "payment_summary_compact": (
            "💰 <b>Тўлов маълумоти</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>\n"
            "📆 Кейинги тўлов: <b>{next_payment_info}</b>\n"
            "💳 Ҳолат: <b>{payment_status}</b>\n\n"
            "💳 Карта: <code>{card_number}</code> ({card_owner})"
        ),
        "payment_summary_detailed": (
            "💰 <b>Тўлов маълумоти (Батафсил)</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>\n"
            "📅 Давр: <b>{start_date} — {end_date}</b>\n"
            "📆 Кейинги тўлов: <b>{next_payment_info}</b>\n"
            "🟢 Қатнашди: <b>{present_count}</b> | 🔴 Келмади: <b>{absent_count}</b>\n"
            "💳 Ҳолат: <b>{payment_status}</b>\n\n"
            "📋 <b>Дарслар кунма-кун:</b>\n{dates_lines}\n\n"
            "💳 Карта: <code>{card_number}</code> ({card_owner})"
        ),
        "payment_pending_5min": (
            "⏳ <b>Тўлов навбатга қўйилди!</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>\n"
            "5 дақиқадан сўнг жадвалда яшил ранг билан тасдиқланади ва хабар юборилади."
        ),
        "payment_confirmed_student": (
            "✅ <b>Тўловингиз тасдиқланди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>\n"
            "Раҳмат! Ўқишларингизда омад тилаймиз."
        ),
        "payment_confirmed_parent": (
            "✅ <b>Тўлов тасдиқланди!</b>\n\n"
            "👤 Фарзандингиз: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>\n"
            "Ўз вақтида тўлов қилганингиз учун раҳмат!"
        ),
        "payment_confirmed_teacher": (
            "✅ <b>Тўлов якуний тасдиқланди</b>\n\n"
            "👤 Талаба: <b>{student_name}</b> ({group})\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>"
        ),
        "payment_confirmed_group": (
            "✅ <b>Тўлов тасдиқланди!</b>\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>"
        ),
        "payment_reverted_admin": (
            "↩️ <b>Тўлов бекор қилинди (рад этилди)!</b>\n\n"
            "👤 Талаба: <b>{student_name}</b> ({group})\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>\n"
            "Қарздорлик қайта тикланди."
        ),
        "payment_reverted_student": (
            "↩️ <b>Тўлов ҳолати қайтарилди</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>\n"
            "Ушбу ой учун тўлов ҳолати «Тўланмаган ❌» га ўзгартирилди. "
            "Саволингиз бўлса, устоз ёки админ билан боғланинг."
        ),
        "payment_reverted_parent": (
            "↩️ <b>Тўлов ҳолати қайтарилди</b>\n\n"
            "👤 Фарзандингиз: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>\n"
            "Ушбу ой учун тўлов ҳолати «Тўланмаган ❌» га ўзгартирилди."
        ),
        "payment_reverted_teacher": (
            "↩️ <b>Тўлов бекор қилинди</b>\n\n"
            "👤 Талаба: <b>{student_name}</b> ({group})\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b>"
        ),
        "payment_reverted_group": (
            "↩️ <b>Тўлов ҳолати ўзгартирилди</b>\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🗓 Ўқув ойи: <b>{cycle_title}</b> — Тўланмаган ❌"
        ),
        "student_payments_header": (
            "💳 <b>Тўловлар ва Дарслар ҳисоботи</b>\n"
            "👤 Талаба: <b>{student_name}</b> ({group})\n\n"
            "💳 Тўлов учун карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>"
        ),
        "student_payment_cycle_compact": (
            "🗓 <b>{cycle_title}</b>\n"
            "📆 Кейинги тўлов: <b>{next_payment_info}</b>\n"
            "Ҳолат: <b>{status_label}</b>"
        ),
        "student_payment_cycle_detailed": (
            "🗓 <b>{cycle_title}</b>\n"
            "📅 Давр: <b>{start_date} — {end_date}</b>\n"
            "📆 Кейинги тўлов: <b>{next_payment_info}</b>\n"
            "🟢 Қатнашди: <b>{present_count}</b> | 🔴 Келмади: <b>{absent_count}</b>\n"
            "Ҳолат: <b>{status_label}</b>\n\n"
            "📋 <b>Дарслар кунма-кун:</b>\n{dates_lines}"
        ),
        "status_paid": "Тўланган ✅",
        "status_unpaid": "Тўланмаган ❌",
        "status_active_cycle": "Жорий ўқув ойи ⏳",
        "no_debts_msg": "✅ Сизда қарздорлик мавжуд эмас.",

        # Debtors & Contacts
        "debtors_list_header": "⚠️ <b>Қарздор талабалар рўйхати:</b>\n",
        "debtors_empty": "✅ Ҳозирда қарздор талабалар мавжуд эмас.",
        "debtor_item": "• <b>{student_name}</b> ({group}) — <i>{debts}</i> | Тел: {phone}",
        "contacts_header": "👥 <b>{group} гуруҳи контактлари:</b>\n",
        "contact_student_item": "• <b>{student_name}</b>\n  📞 {phone} | {tg}",
        "contacts_empty": "ℹ️ Ушбу гуруҳда фаол талабалар топилмади.",

        # Smart reminders
        "reminder_evening_before": (
            "🌙 <b>Эртанги дарс эслатмаси</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "⏰ Эртага соat <b>{time}</b> да дарсингиз бор. Вақтида келишни унутманг!"
        ),
        "reminder_morning_today": (
            "☀️ <b>Бугунги дарс эслатмаси</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "⏰ Бугун соат <b>{time}</b> да дарсингиз бор."
        ),
        "reminder_1h_before": (
            "⏰ <b>Дарсга 1 соат қолди!</b>\n\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "🕒 Бошланиш вақти: <b>{time}</b>. Йўлга чиқиш вақти келди!"
        ),
        "reminder_weekly_debt_student": (
            "⚠️ <b>Қарздорлик эслатмаси</b>\n\n"
            "👤 Талаба: <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group}</b>\n"
            "Тўланмаган ўқув ойлари: <b>{debts}</b>\n\n"
            "Илтимос, тўловни имкон қадар тезроқ амалга оширинг.\n"
            "💳 Карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>"
        ),
        "reminder_weekly_debt_parent": (
            "⚠️ <b>Қарздорлик эслатмаси</b>\n\n"
            "👤 Фарзандингиз: <b>{student_name}</b> ({group})\n"
            "Тўланмаган ўқув ойлари: <b>{debts}</b>\n\n"
            "Илтимос, ўқув маркази тўловини амалга оширишингизни сўраймиз.\n"
            "💳 Карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>"
        ),
        "weekly_debt_student_dm": (
            "⚠️ <b>Ҳафталик тўлов эслатмаси</b>\n\n"
            "Ҳурматли <b>{student_name}</b>,\n\n"
            "Сизнинг <b>{group_name}</b> гуруҳи бўйича қуйидаги ўқув ойи учун тўловингиз ҳали амалга оширилмаган:\n"
            "🗓 Тўланмаган давр: <b>{debts}</b>\n"
            "💰 Қарздорлик миқдори: <b>{amount} сўм</b>\n\n"
            "Илтимос, ойлик тўловни 1-дарсдан кечиктирмай ўз вақтида амалга оширинг.\n\n"
            "💳 Тўлов учун карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "weekly_debt_parent_single_dm": (
            "⚠️ <b>Ҳафталик тўлов эслатмаси</b>\n\n"
            "Ассалому алайкум, ҳурматли <b>{parent_name}</b>!\n\n"
            "Фарзандингиз <b>{student_name}</b>нинг <b>{group_name}</b> гуруҳи бўйича қуйидаги ўқув ойи учун тўлови ҳали амалга оширилмаган:\n"
            "🗓 Тўланмаган давр: <b>{debts}</b>\n"
            "💰 Қарздорлик миқдори: <b>{amount} сўм</b>\n\n"
            "Илтимос, ойлик тўловни 1-дарсдан кечиктирмай ўз вақтида амалга оширишингизни ҳурмат билан сўраймиз.\n\n"
            "💳 Тўлов учун карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "weekly_debt_parent_multi_dm": (
            "⚠️ <b>Ҳафталик тўлов эслатмаси</b>\n\n"
            "Ассалому алайкум, ҳурматли <b>{parent_name}</b>!\n\n"
            "Фарзандларингизнинг тўланмаган ўқув ойлари бўйича қарздорлик маълумоти:\n\n"
            "{children_blocks}\n\n"
            "💵 <b>Умумий қарздорлик: {grand_total} сўм</b>\n\n"
            "Илтимос, ойлик тўловларни 1-дарсдан кечиктирмай ўз вақтида амалга оширишингизни ҳурмат билан сўраймиз.\n\n"
            "💳 Тўлов учун карта: <code>{card_number}</code>\n"
            "👤 Карта эгаси: <b>{card_owner}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "group_initial_notice": (
            "💳 <b>Ойлик тўлов эслатмаси</b>\n\n"
            "📚 Гуруҳ: <b>{canonical_group}</b>\n\n"
            "Янги ўқув ойи бошланиши муносабати билан ойлик тўловни 1-дарсдан кечиктирмай ўз вақтида амалга оширишингизни сўраймиз.\n\n"
            "💳 Тўлов учун карта: <code>{card_esc}</code>\n"
            "👤 Карта эгаси: <b>{owner_esc}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "group_weekly_reminder": (
            "⚠️ <b>Ҳафталик тўлов эслатмаси</b>\n\n"
            "📚 Гуруҳ: <b>{canonical_group}</b>\n\n"
            "Жорий ўқув ойи учун тўловни ҳали амалга оширмаган талабалар сони: <b>{unpaid_count} нафар</b>.\n\n"
            "Илтимос, ойлик тўловни 1-дарсдан кечиктирмай ўз вақтида амалга оширишингизни сўраймиз.\n\n"
            "💳 Тўлов учун карта: <code>{card_esc}</code>\n"
            "👤 Карта эгаси: <b>{owner_esc}</b>\n\n"
            "Ҳурмат билан,\nМишкат Нодавлат Таълим Муассасаси!"
        ),
        "weekly_debt_child_block": (
            "👶 <b>{student_name}</b>\n"
            "📚 Гуруҳ: <b>{group_name}</b>\n"
            "🗓 Тўланмаган давр: <b>{debts}</b>\n"
            "💰 Қарздорлик миқдори: <b>{amount} сўм</b>"
        ),
        "error_generic": "❌ Хатолик юз берди. Кейинроқ қайта уриниб кўринг.",
    },
}

# Previous ReplyKeyboard labels. Users may still have an older menu on screen;
# handlers match these through button_texts() so old buttons keep working.
LEGACY_BUTTON_TEXTS: dict[str, tuple[str, ...]] = {
    "btn_change_lang": (
        "🌐 Tilni o‘zgartirish",
    ),
    "btn_switch_to_parent": (
        "👨‍👩‍👧 Ota-ona rejimiga o'tish",
        "👨‍👩‍👧 Ота-она режимига ўтиш",
    ),
    "btn_switch_to_student": (
        "🎓 Talaba rejimiga o'tish",
        "🎓 Талаба режимига ўтиш",
    ),
    "menu_admin_attendance": (
        "📋 Yo'qlama qilish",
    ),
    "menu_admin_manage_admins": (
        "👑 Adminlar boshqaruvi",
        "👑 Админлар бошқаруви",
    ),
    "menu_admin_manage_teachers": (
        "👨‍🏫 Ustozlar boshqaruvi",
        "👨‍🏫 Устозлар бошқаруви",
    ),
    "menu_admin_payments": (
        "💰 To'lovni tasdiqlash",
        "💰 To‘lovni tasdiqlash",
        "💰 Тўловни тасдиқлаш",
    ),
    "menu_lesson_topic": (
        "📝 Dars mavzusi va rejasi",
        "📝 Дарс мавзуси ва режаси",
    ),
    "menu_parent_payments": (
        "💳 To‘lovlar va Qarzlar",
        "💳 Тўловлар ва Қарзлар",
    ),
    "menu_parent_schedule": (
        "📅 Farzandim dars jadvali",
        "📅 Farzandimning dars jadvali",
        "📅 Фарзандим дарс жадвали",
        "📅 Фарзандимнинг дарс жадвали",
    ),
    "menu_profile": (
        "⚙️ Shaxsiy ma'lumotlar",
        "⚙️ Шахсий маълумотлар",
        "👤 Shaxsiy ma'lumotlarim",
        "👤 Шахсий маълумотларим",
    ),
    "menu_student_payments": (
        "💳 To‘lovlar va Qarzlar",
        "💳 Тўловлар ва Қарзлар",
    ),
    "menu_teacher_add_student": (
        "➕ Yangi talaba qo'shish",
        "➕ Янги талаба қўшиш",
    ),
    "menu_teacher_attendance": (
        "📋 Yo'qlama qilish",
    ),
    "menu_teacher_groups": (
        "👥 Mening guruhlarim",
        "👥 Менинг гуруҳларим",
    ),
    "menu_teacher_payments": (
        "💳 To'lovlarni tasdiqlash",
        "💳 Тўловларни тасдиқлаш",
    ),
    "menu_teacher_topic": (
        "📝 Dars mavzusini kiritish",
        "📝 Дарс мавзусини киритиш",
    ),
}


def button_texts(*keys: str) -> set[str]:
    """Every label (current latn/cyrl and legacy) a ReplyKeyboard button may send."""
    result: set[str] = set()
    for key in keys:
        for lang in ("latn", "cyrl"):
            value = TEXTS[lang].get(key)
            if value:
                result.add(value)
        result.update(LEGACY_BUTTON_TEXTS.get(key, ()))
    return result


class _SafeFormatDict(dict[str, Any]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def t(key: str, lang: str = "latn", **kwargs: Any) -> str:
    safe_lang = lang if lang in TEXTS else "latn"
    template = TEXTS[safe_lang].get(key) or TEXTS["latn"].get(key, key)
    if kwargs:
        try:
            return template.format(**kwargs)
        except KeyError:
            return template.format_map(_SafeFormatDict(kwargs))
    return template


def format_field_label(field_key: str, lang: str = "latn") -> str:
    safe_lang = lang if lang in FIELD_LABELS else "latn"
    return (
        FIELD_LABELS[safe_lang].get(field_key)
        or FIELD_LABELS["latn"].get(field_key)
        or field_key
    )


def format_full_weekdays(days_str: str, lang: str = "latn") -> str:
    cleaned = str(days_str or "").strip()
    if not cleaned:
        return ""
    safe_lang = lang if lang in WEEKDAYS_FULL else "latn"
    full_map = WEEKDAYS_FULL[safe_lang]
    raw_tokens = [tok.strip() for tok in cleaned.split(",") if tok.strip()]
    if len(raw_tokens) <= 1 and " " in cleaned and "," not in cleaned:
        raw_tokens = [tok.strip() for tok in cleaned.split() if tok.strip()]
    result: list[str] = []
    for tok in raw_tokens:
        norm = tok.lower().strip(".- ")
        idx = _WEEKDAY_TOKEN_TO_IDX.get(norm)
        if idx is not None:
            result.append(full_map[idx])
        else:
            result.append(tok)
    return ", ".join(result)


def format_human_cycle_title(
    cycle_num: int, lesson_count: int, lang: str = "latn"
) -> str:
    return t("human_cycle_label", lang, num=cycle_num, count=lesson_count)


def format_lesson_line(
    lesson_num: int,
    date_str: str,
    weekday_idx: Optional[int],
    mark: str,
    lang: str = "latn",
) -> str:
    safe_lang = lang if lang in WEEKDAYS_SHORT else "latn"
    weekday_str = (
        WEEKDAYS_SHORT[safe_lang].get(weekday_idx, "")
        if weekday_idx is not None
        else "-"
    )
    if mark == "✅":
        status_text = t("lesson_status_present", safe_lang)
    elif mark == "❌":
        status_text = t("lesson_status_absent", safe_lang)
    else:
        status_text = t("lesson_status_pending", safe_lang)
    return t(
        "lesson_line_template",
        safe_lang,
        lesson_num=lesson_num,
        date=date_str,
        weekday=weekday_str,
        status=status_text,
    )


def format_next_payment_info(
    lesson_num: int, date_str: str, lang: str = "latn"
) -> str:
    return t(
        "next_payment_template",
        lang,
        lesson_num=lesson_num,
        date=date_str or "-",
    )


def format_uzs(amount: int | str, lang: str = "latn") -> str:
    digits = "".join(ch for ch in str(amount) if ch.isdigit())
    if not digits:
        return t("group_price_not_set", lang)
    val = int(digits)
    formatted = f"{val:,}".replace(",", " ")
    suffix = "сўм" if lang == "cyrl" else "so‘m"
    return f"{formatted} {suffix}"


def format_uz_date(date_str: str, lang: str = "latn") -> str:
    cleaned = str(date_str or "").strip()
    if not cleaned:
        return ""
    safe_lang = lang if lang in MONTHS_UZ else "latn"
    parts = cleaned.split(".")
    if len(parts) not in (2, 3):
        return cleaned
    try:
        day = int(parts[0])
        month = int(parts[1])
    except ValueError:
        return cleaned
    month_name = MONTHS_UZ[safe_lang].get(month)
    if not month_name:
        return cleaned
    return f"{day}-{month_name.lower()}"


def format_uz_date_long(d_val: Any, lang: str = "latn") -> str:
    """date -> '2026-yil 22-Noyabr' (Cyrillic: '2026-йил 22-Ноябрь')."""
    safe_lang = lang if lang in MONTHS_UZ else "latn"
    year_word = "йил" if safe_lang == "cyrl" else "yil"
    month_name = MONTHS_UZ[safe_lang].get(d_val.month, "")
    return f"{d_val.year}-{year_word} {d_val.day}-{month_name}"


def format_weekday_full(d_val: Any, lang: str = "latn") -> str:
    """date -> full Uzbek weekday name (e.g. 'Yakshanba')."""
    safe_lang = lang if lang in WEEKDAYS_FULL else "latn"
    return WEEKDAYS_FULL[safe_lang][d_val.weekday()]


def format_uz_date_list(dates: list[str], lang: str = "latn") -> str:
    return ", ".join(format_uz_date(d, lang) for d in dates if str(d).strip())
