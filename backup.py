import os
import html
import sqlite3
import urllib.request
from datetime import datetime, timezone, timedelta
import gspread

BASE_DIR = "/home/opc/mishkat_bot"
ENV_PATH = os.path.join(BASE_DIR, ".env")
BACKUP_DIR = "/home/opc/backups"

def load_env(path):
    env = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env

def send_to_telegram(token, chat_id, file_path, caption, thread_id=None):
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    boundary = "----MishkatBackupBoundary987654321"
    with open(file_path, "rb") as f:
        file_data = f.read()
    filename = os.path.basename(file_path)

    thread_part = ""
    if thread_id and str(thread_id).strip() and str(thread_id).strip() != "1":
        thread_part = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="message_thread_id"\r\n\r\n{str(thread_id).strip()}\r\n'
        )

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        f"{thread_part}"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_data + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        resp.read()

def render_table(title, headers, rows):
    if not rows:
        return f"<h2>{html.escape(title)}</h2><p class='empty'>Ma'lumot mavjud emas.</p>"
    th_html = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    tr_list = []
    for idx, row in enumerate(rows, 1):
        padded = list(row) + [""] * max(0, len(headers) - len(row))
        tds = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in padded[:len(headers)])
        tr_list.append(f"<tr><td>{idx}</td>{tds}</tr>")
    return (
        f"<h2>{html.escape(title)} ({len(rows)} ta)</h2>"
        f"<div class='table-wrap'><table><thead><tr><th>№</th>{th_html}</tr></thead>"
        f"<tbody>{''.join(tr_list)}</tbody></table></div>"
    )

def build_html_report(sheets_data, now_human):
    students_headers, students_rows = sheets_data.get("Baza_Talabalar", ([], []))
    debtors_rows = []
    if students_headers and students_rows:
        h_map = {h.strip(): i for i, h in enumerate(students_headers)}
        for r in students_rows:
            def get_col(name):
                idx = h_map.get(name, -1)
                return r[idx].strip() if 0 <= idx < len(r) else ""
            qarz_raw = get_col("Qarz") or get_col("Qarzdorlik") or get_col("Umumiy_Qarz")
            qarz_digits = "".join(ch for ch in qarz_raw if ch.isdigit())
            if qarz_digits and int(qarz_digits) > 0:
                fio = get_col("F.I.O.") or get_col("Talaba_FIO") or get_col("Ism_Familiya")
                guruh = get_col("Guruh") or get_col("Guruh_Nomi")
                tel = get_col("Telefon") or get_col("Talaba_Tel")
                ota = f"{get_col('Otasi_FIO')} ({get_col('Otasi_Tel')})".strip(" ()")
                ona = f"{get_col('Onasi_FIO')} ({get_col('Onasi_Tel')})".strip(" ()")
                debtors_rows.append([fio, guruh, f"{int(qarz_digits):,} so'm".replace(",", " "), tel, ota, ona])

    sections = []
    if debtors_rows:
        sections.append(render_table(
            "1. Qarzdor talabalar ro'yxati",
            ["Talaba F.I.O.", "Guruh", "Qarz summasi", "Talaba telefoni", "Otasi", "Onasi"],
            debtors_rows
        ))

    order = ["Baza_Talabalar", "Ustozlar", "Guruhlar", "Qiziquvchilar_Lidlar"]
    titles = {
        "Baza_Talabalar": "2. Barcha talabalar va ota-onalar bazasi",
        "Ustozlar": "3. Ustozlar ro'yxati",
        "Guruhlar": "4. Guruhlar ro'yxati",
        "Qiziquvchilar_Lidlar": "5. Qiziquvchi lidlar (Arizalar)"
    }
    for tab in order:
        if tab in sheets_data:
            h, r = sheets_data[tab]
            sections.append(render_table(titles.get(tab, tab), h, r))

    for tab, (h, r) in sheets_data.items():
        if tab not in order:
            sections.append(render_table(f"Dars va to'lov jurnali: {tab}", h, r))

    return f"""<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mishkat NTM — Rasmiy Zaxira Hujjati ({now_human})</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #f4f6f9; color: #1f2937; margin: 0; padding: 16px; }}
  .doc {{ max-width: 1100px; margin: 0 auto; background: #fff; padding: 24px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }}
  .header {{ border-bottom: 2px solid #1e3a8a; padding-bottom: 14px; margin-bottom: 20px; }}
  .header h1 {{ margin: 0; font-size: 20px; color: #1e3a8a; }}
  .header p {{ margin: 6px 0 0; font-size: 13px; color: #4b5563; }}
  .summary {{ display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 20px; }}
  .card {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 8px; padding: 10px 14px; font-size: 13px; }}
  .card b {{ display: block; font-size: 17px; color: #1e40af; }}
  h2 {{ font-size: 16px; color: #111827; margin: 24px 0 10px; border-left: 4px solid #2563eb; padding-left: 10px; }}
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ border: 1px solid #d1d5db; padding: 8px 10px; text-align: left; white-space: nowrap; }}
  th {{ background: #1e3a8a; color: #fff; font-weight: 600; }}
  tr:nth-child(even) {{ background: #f9fafb; }}
  .empty {{ color: #6b7280; font-style: italic; font-size: 13px; }}
  .footer {{ margin-top: 28px; padding-top: 12px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; }}
</style>
</head>
<body>
<div class="doc">
  <div class="header">
    <h1>MISHKAT NODAVLAT TA'LIM MUASSASASI</h1>
    <p>Tizim ma'lumotlarining rasmiy zaxira nusxasi • Sana va vaqt: <b>{html.escape(now_human)} (Toshkent)</b></p>
  </div>
  <div class="summary">
    <div class="card">Jami talabalar <b>{len(students_rows)} nafar</b></div>
    <div class="card">Qarzdorlar <b>{len(debtors_rows)} nafar</b></div>
    <div class="card">Ustozlar <b>{len(sheets_data.get('Ustozlar', ([], []))[1])} nafar</b></div>
    <div class="card">Guruhlar <b>{len(sheets_data.get('Guruhlar', ([], []))[1])} ta</b></div>
    <div class="card">Lidlar <b>{len(sheets_data.get('Qiziquvchilar_Lidlar', ([], []))[1])} ta</b></div>
  </div>
  {''.join(sections)}
  <div class="footer">Ushbu hujjat Mishkat Nodavlat Ta'lim Muassasasi avtomatlashtirilgan axborot tizimi tomonidan shakllantirildi.</div>
</div>
</body>
</html>"""

def main():
    env = load_env(ENV_PATH)
    token = env.get("BOT_TOKEN", "")
    admin_ids = env.get("ADMIN_IDS", "").split(",")
    fallback_chat = admin_ids[0].strip() if admin_ids and admin_ids[0].strip() else ""
    target_chat = env.get("BACKUP_CHAT_ID", "").strip() or fallback_chat
    target_thread = env.get("BACKUP_THREAD_ID", "").strip()
    spreadsheet_id = env.get("SPREADSHEET_ID", "")
    creds_rel = env.get("CREDENTIALS_PATH", "credentials.json")
    db_rel = env.get("DB_PATH", "data/bot.db")

    creds_path = creds_rel if os.path.isabs(creds_rel) else os.path.join(BASE_DIR, creds_rel)
    db_path = db_rel if os.path.isabs(db_rel) else os.path.join(BASE_DIR, db_rel)
    if not os.path.exists(db_path) and os.path.exists(os.path.join(BASE_DIR, "bot.db")):
        db_path = os.path.join(BASE_DIR, "bot.db")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    tz_tashkent = timezone(timedelta(hours=5))
    now_dt = datetime.now(tz_tashkent)
    now_file = now_dt.strftime("%Y-%m-%d_%H-%M")
    now_human = now_dt.strftime("%d.%m.%Y %H:%M")

    # 1. SQLite bazadan jonli nusxa olish
    db_backup_file = os.path.join(BACKUP_DIR, f"bot_{now_file}.db")
    if os.path.exists(db_path):
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(db_backup_file)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()

    # 2. Google Sheets barcha varaqlarni o'qib, sodda rasmiy HTML hujjat yaratish
    sheets_data = {}
    if spreadsheet_id and os.path.exists(creds_path):
        gc = gspread.service_account(filename=creds_path)
        sh = gc.open_by_key(spreadsheet_id)
        for ws in sh.worksheets():
            values = ws.get_all_values()
            if values:
                sheets_data[ws.title] = (values[0], values[1:])
            else:
                sheets_data[ws.title] = ([], [])

    html_backup_file = os.path.join(BACKUP_DIR, f"Mishkat_Hisobot_{now_file}.html")
    with open(html_backup_file, "w", encoding="utf-8") as f:
        f.write(build_html_report(sheets_data, now_human))

    # 14 kundan eski lokal nusxalarni tozalash
    cutoff = datetime.now().timestamp() - (14 * 86400)
    for fname in os.listdir(BACKUP_DIR):
        fpath = os.path.join(BACKUP_DIR, fname)
        if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
            os.remove(fpath)

    # 3. Ikkala faylni ham Telegram'ga yuborish
    if token and target_chat:
        if os.path.exists(db_backup_file):
            send_to_telegram(
                token, target_chat, db_backup_file,
                f"🗄 1/2. Texnik baza nusxasi (tizimni tiklash uchun)\n📅 {now_human} (Toshkent)",
                target_thread
            )
        send_to_telegram(
            token, target_chat, html_backup_file,
            f"📄 2/2. Mishkat NTM — To'liq rasmiy hisobot (Qarzdorlar, Talabalar, Ota-onalar, Ustozlar)\n📅 {now_human} (Toshkent)\n💡 Telefonda ustiga bosib brauzerda ochishingiz mumkin.",
            target_thread
        )
        print("Ikkala zaxira fayl ham muvaffaqiyatli yuborildi!")

if __name__ == "__main__":
    main()
