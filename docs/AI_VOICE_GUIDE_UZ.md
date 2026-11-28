# Mishkat AI yordamchisi — foydalanish yo‘riqnomasi

**Mishkat Nodavlat Ta'lim Muassasasi** Telegram botidagi AI yordamchi orqali
ishlarni **matn** yoki **ovozli xabar** bilan bajarish mumkin. Bot sizning
gapingizni tushunadi, kerakli ma’lumotni Google Sheets / bazadan o‘qiydi va
har qanday o‘zgarishni **avval qoralama karta** ko‘rinishida ko‘rsatadi.

---

## 1. Asosiy qoidalar (hamma uchun)

| Qoida | Izoh |
|---|---|
| 🔐 Kim foydalana oladi | Faqat **Admin** va **Ustoz** (joriy roli shu bo‘lsa). Talaba, ota-ona va mehmonlar uchun AI o‘chirilgan — ular odatdagi menyu tugmalaridan foydalanadi. |
| ✅ Tasdiqlash shart | Har bir yozish / tahrirlash / o‘chirish amali avval **qoralama karta** bo‘lib chiqadi. Faqat **✅ Tasdiqlash** bosilgandan keyin ma’lumot o‘zgaradi. **❌ Bekor qilish** — hech narsa o‘zgarmaydi. |
| ⌛️ Muddat | Qoralama **10 daqiqa** amal qiladi va faqat uni yaratgan odam tasdiqlay oladi. Har bir karta faqat bir marta ishlatiladi. |
| 🗣 Ovozli xabar | 15 MB gacha. Aniq va sekinroq gapiring; guruh va talaba ismini to‘liq ayting. |
| 🔗 Bir nechta amal | Bitta xabarda bir nechta buyruq berish mumkin — har biri uchun alohida karta chiqadi (masalan: yo‘qlama + qarz + mavzu). |
| 🚫 Mavzudan tashqari | Ob-havo, hazil, dasturlash, yangiliklar kabi savollarga bot javob bermaydi: *«⚠️ Men faqat Mishkat o'quv markazi … savollarga javob beraman.»* |
| ⏳ «AI band» | Ikkala model ham band bo‘lsa chiqadi — biroz kutib qayta yozing. Bot menyusi har doim ishlaydi. |
| 📅 Sanalar | «bugun», «kecha», «ertaga», «25.11», «25.11.2026». Yo‘qlama uchun **kelajak sanasi qabul qilinmaydi**. |
| ✍️ Yozuv | Lotin yoki kirill alifbosida yozing — javob shu alifboda keladi. |

---

## 2. 👑 Admin uchun

Admin markazdagi **barcha guruhlar** bilan ishlaydi.

### 2.1. Ma’lumot ko‘rish (karta chiqmaydi, darhol javob)
- «Barcha guruhlar ro‘yxatini ko‘rsat»
- «Bugun qaysi guruhlarda dars bor?»
- «Frontend_1 guruhining jadvali va talabalari»
- «Python_2 talabalari va ota-onalarining telefonlari»
- «Zaxiradagi talabalar ro‘yxati»
- «Qarzdorlar ro‘yxati» / «Frontend_1 qarzdorlari»
- «Ali Valiyevning qaysi darslari to‘lanmagan? Sanalari bilan»
- «Ali Valiyevning avvalgi qarzlari»
- «Yangi lidlar» / «Barcha lidlar»
- «Ustozlar ro‘yxati»
- «Markaz statistikasi»
- «Frontend_1 ning saqlangan dars mavzulari»
- «Frontend_1 uchun talaba taklif havolasi»

### 2.2. 📋 Yo‘qlama — kiritish, tahrirlash, tozalash
- Kiritish: «**Frontend_1 da bugun hamma keldi, faqat Ali Valiyev kelmadi**»
- O‘tgan kun: «**Kecha Python_2 da hamma qatnashdi**»
- Aniq sana: «25.11 kuni Frontend_1 da Ali va Bobur kelmadi»
- Faqat kelganlar: «Bugun Arab guruhida faqat Ali va Vali keldi» (qolganlar 🔴)
- Juft dars kuni: «Bugun Frontend_1 2-dars: hamma keldi»
- **Tahrirlash**: xuddi shu sana uchun qaytadan aytsangiz yo‘qlama yangilanadi:
  «Kechagi Frontend_1 yo‘qlamasini to‘g‘rila: Ali keldi, Bobur kelmadi»
- **Tozalash / o‘chirish** (xato kiritilgan bo‘lsa): «**Frontend_1 ning 25.11 dagi yo‘qlamasini o‘chir**»
  → belgilar o‘chadi, katakchalar oq bo‘ladi, o‘tilgan darslar soni 1 taga kamayadi.

✅ Tasdiqlanganda talabalar va ota-onalarga rasmiy xabar (dars raqami, mavzu, qarz eslatmasi), guruh chatiga dars yakuni va adminlarga hisobot yuboriladi.

### 2.3. 💳 To‘lovlar — tasdiqlash yoki bekor qilish
- «**Ali Valiyevning Noyabr oyi to‘lovini tasdiqla**»
- «Bobur Karimovning eng eski qarzini tasdiqla»
- Xato tasdiqlangan bo‘lsa: «**Ali Valiyevning Noyabr to‘lovini bekor qil**»

To‘lov tasdiqlanganda jadval yashil bo‘ladi, qarz olib tashlanadi; bekor qilinganda qizil rang va qarz qaytadi. Talaba, ota, ona, ustoz va guruhga xabar ketadi, Audit_Log yoziladi.

### 2.4. 📝 Dars mavzusi — saqlash, tahrirlash, o‘chirish
- «**Frontend_1 ning bugungi mavzusi: Loops va ro‘yxatlar, reja: amaliy mashqlar**»
- O‘tgan sana: «Python_2 ning 25.11 dagi mavzusi: Funksiyalar»
- Tahrirlash: shu sana uchun yangi mavzuni ayting — eskisi almashadi va qayta e’lon qilinadi.
- O‘chirish: «**Frontend_1 ning 25.11 dagi mavzusini o‘chir**»

### 2.5. 👨‍🎓 Talabalar
- Taklif havolasi: «Frontend_1 uchun talaba taklif havolasini ber»
- Qurilmaga ulash: «**Ali Valiyev uchun botga ulash havolasini yarat**» (telefon bilan: «…, telefoni +998901234567»)
- Ma’lumotni o‘zgartirish: «Ali Valiyevning telefonini +998901112233 ga o‘zgartir»,
  «Ali Valiyevning otasining ismini Karim Valiyev qil», «Onasining telefoni +998…»
- Zaxiraga: «**Ali Valiyevni zaxiraga o‘tkaz**»
- Qaytarish: «Ali Valiyevni Frontend_1 ga qaytar»
- Boshqa guruhga: «Ali Valiyevni Python_2 ga o‘tkaz» / «… eski guruhida ham qolsin»
- Butunlay o‘chirish: «**Ali Valiyevni butunlay o‘chir**» (Sheets + baza, faqat shu talabasi bo‘lgan ota-onalar ham tozalanadi)

### 2.6. 📜 Avvalgi (tizimgacha bo‘lgan) qarzlar
- Qo‘shish: «**Ali Valiyevga avvalgi 2 oylik 900 ming qarz qo‘sh, Sentyabr-Oktyabr**»
- Ko‘rish: «Ali Valiyevning avvalgi qarzlari» (har birining raqami #ID bilan)
- Tahrirlash: «**#12 raqamli avvalgi qarzni 600 ming qil**»
- O‘chirish: «**#12 avvalgi qarzni o‘chir**»

### 2.7. 👥 Guruhlar
- Yaratish: «**Arab 1-guruh yarat, ustozi Aziz Rahimov, Du Chor Ju soat 14:00, 12 dars, oylik 450 ming**»
  (vaqt aytilmasa — «Kelishilgan vaqtda»; kuniga 2 dars: «kuniga 2 ta dars, 10:00 / 11:30»)
  → tasdiqdan so‘ng guruh chatida yuborish uchun `/link_group Guruh_nomi` buyrug‘i beriladi.
- Tahrirlash: «Python_2 vaqtini 11:00 ga o‘zgartir», «Python_2 oylik to‘lovini 500 ming qil»,
  «Python_2 ustozini Bek Usmonov qil», «Python_2 nomini Python kechki qil»,
  «Python_2 darslarini Se va Pay kunlari, 8 ta qil», «Har kuni alohida: Du 14:00, Chor 15:30»
- O‘chirish: «**Python_2 guruhini o‘chir**» (talabalar Zahira guruhiga o‘tadi)

### 2.8. 👨‍🏫 Ustozlar
- «Yangi ustoz uchun taklif havolasi, Frontend_1 guruhiga»
- «Bek Usmonovni Python_2 guruhiga biriktir»
- «Bek Usmonovni butunlay o‘chir»

### 2.9. 📋 Lidlar
- «Yangi lidlarni ko‘rsat»
- «#15 lid bilan bog‘lanildi deb belgila»
- «#16 lidni o‘chir, spam ekan»

### 2.10. Bir xabarda bir nechta amal
- «Frontend_1 da bugun hamma keldi faqat Ali kelmadi, keyin Aliga avvalgi 2 oylik 900 ming qarz qo‘shib qo‘y»
- «Ali Valiyevning Noyabr to‘lovini tasdiqla va Frontend_1 dars mavzusini Loops deb saqla»

Har bir amal uchun alohida karta chiqadi — kerakligini ✅ tasdiqlang.

---

## 3. 👨‍🏫 Ustoz uchun

Ustoz **faqat o‘ziga biriktirilgan guruhlar** va ularning talabalari bilan ishlaydi.
Boshqa ustozlarning guruhlari, lidlar, guruh yaratish/o‘chirish, ustozlarni boshqarish,
talabani butunlay o‘chirish va avvalgi qarzlar ustoz uchun **yopiq**.

Ustoz uchun ruxsat etilgan buyruqlar:
- Ko‘rish: «Mening guruhlarim», «Bugungi darslarim», «Frontend_1 talabalari va ota-onalari telefonlari», «Guruhimdagi qarzdorlar», «Ali ning to‘lanmagan dars sanalari», «Saqlangan mavzular»
- Yo‘qlama: «Bugun hamma keldi, faqat Ali kelmadi», «Kecha Frontend_1 da Bobur kelmadi», «25.11 yo‘qlamasini o‘chir»
- To‘lov: «Ali Valiyevning to‘lovini tasdiqla», «Ali ning Noyabr to‘lovini bekor qil»
- Mavzu: «Bugungi mavzu: Loops, reja: amaliy mashq», «25.11 mavzusini o‘chir»
- Talabalar: «Ali ning telefonini o‘zgartir», «Ali uchun ulash havolasi», «Ali ni zaxiraga o‘tkaz», «Ali ni Frontend_2 ga o‘tkaz» (ikkala guruh ham sizniki bo‘lishi kerak), «Guruh uchun taklif havolasi»

---

## 4. 🎓 Talaba uchun

AI yordamchi talabalar uchun **o‘chirilgan** (hech qanday so‘rov yuborilmaydi).
Bot menyusi tugmalaridan foydalaning:
- 👥 **Mening guruhim** — guruh, ustoz va guruhdoshlar
- 📅 **Dars jadvali** — dars kunlari va vaqtlari
- 💳 **To‘lov va qarzlar** — qarzdorlik va to‘langan oylar
- ⚙️ **Ma'lumotlarim**, 🌐 **Tilni o'zgartirish**

## 5. 👨‍👩‍👧 Ota-ona uchun

AI yordamchi ota-onalar uchun ham **o‘chirilgan**. Bot menyusi:
- 📅 **Farzandim jadvali**
- 💳 **To‘lov va qarzlar** — har bir farzand bo‘yicha qarz va sanalar
- ⚙️ **Ma'lumotlarim**, 🌐 **Tilni o'zgartirish**
- Davomat, dars mavzusi va to‘lov xabarlari avtomatik keladi.

---

## 6. Ko‘p beriladigan savollar

- **Bot javob bermadi?** — Agar biror jarayon (masalan, menyuda guruh yaratish) ochiq bo‘lsa, avval uni yakunlang yoki «❌ Bekor qilish» bosing. Talaba / ota-ona rolida AI ishlamaydi.
- **Noto‘g‘ri talaba tanlandi?** — Kartada ism ko‘rsatiladi; noto‘g‘ri bo‘lsa «❌ Bekor qilish» bosing va to‘liq ism-familiyani ayting. Bir xil ismlilar bo‘lsa bot qaysi biri ekanini so‘raydi.
- **Karta eskirdi?** — 10 daqiqadan keyin buyruqni qaytadan yuboring.
- **Xatoni qaytarish** — yo‘qlamani tozalash, to‘lovni bekor qilish, mavzuni o‘chirish, avvalgi qarzni tahrirlash/o‘chirish buyruqlaridan foydalaning.

Hurmat bilan,
Mishkat Nodavlat Ta'lim Muassasasi!
