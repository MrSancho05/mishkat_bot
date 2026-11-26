import os
import html
import sqlite3
import urllib.request
from datetime import datetime, timezone, timedelta
import gspread

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# The bot checkout (with the `app` package) — this script's own folder when it
# lives inside it, otherwise the production path.
BASE_DIR = (
    _SCRIPT_DIR
    if os.path.isdir(os.path.join(_SCRIPT_DIR, "app"))
    else "/home/opc/mishkat_bot"
)
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


def _fmt_uzs(amount):
    return f"{int(amount or 0):,}".replace(",", " ")


def _clean(value):
    text = str(value or "").strip()
    return "" if text == "Ma'lumot kiritilmagan" else text


def _count_debt_months(raw):
    cleaned = str(raw or "").strip()
    if not cleaned or cleaned == "0":
        return 0
    if cleaned.isdigit():
        return int(cleaned)
    return len([x for x in cleaned.split(";") if x.strip() and x.strip() != "0"])


def compute_report_with_bot_logic(base_dir):
    """
    Uses the bot's OWN debt logic (app.debt_view.compute_children_debts:
    closed Qarzdor_Oylar cycles + prorated overrides + legacy debts) and, on
    top of it, the active-cycle unpaid check, so a newly enrolled student whose
    current cycle payment is still unconfirmed is always counted as a debtor.
    Returns the report dict, or None when the bot modules cannot be loaded.
    """
    import asyncio
    import sys

    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    try:
        from app.database import get_cycle_overrides_for_students
        from app.debt_view import compute_children_debts, load_group_fees
        from app.sheets import get_sheets_manager
    except Exception as exc:
        print(f"Bot modules unavailable, using raw-sheet debt calculation: {exc}")
        return None

    async def _collect():
        sheets = get_sheets_manager()
        all_students = await asyncio.to_thread(sheets.get_all_students, None, False)
        groups = await asyncio.to_thread(sheets.get_all_groups)
        teachers = await asyncio.to_thread(sheets.get_all_teachers, False)
        group_fees, default_fee = await load_group_fees(sheets)
        unpaid_map = await asyncio.to_thread(
            sheets.get_unpaid_cycles_for_students, all_students
        )
        children = await compute_children_debts(
            sheets, all_students, group_fees, default_fee, unpaid_map=unpaid_map
        )
        sids = [str(s.get("Talaba_ID") or "").strip() for s in all_students]
        overrides_map = await get_cycle_overrides_for_students(sids)
        return all_students, groups, teachers, children, unpaid_map, overrides_map

    all_students, groups, teachers, children, unpaid_map, overrides_map = asyncio.run(
        _collect()
    )
    child_by_sid = {c["student_id"]: c for c in children}

    def _is_active(stu):
        return _clean(stu.get("Status")) == "O'qiyapti"

    debtors = []
    paid_active = 0
    active_count = 0
    for stu in all_students:
        sid = str(stu.get("Talaba_ID") or "").strip()
        child = child_by_sid.get(sid)
        active = _is_active(stu)
        total = int(child["total_sum"]) if child else 0
        cycle_titles = []
        if child:
            cycle_titles.extend(str(c.get("title") or "") for c in child.get("cycles") or [])
            cycle_titles.extend(str(x) for x in child.get("extra_titles") or [])
            cycle_titles.extend(
                f"Avvalgi qarz: {item['label']}" for item in child.get("legacy") or []
            )
        if active and total <= 0:
            # Active-cycle unpaid check: "To'lanmagan" row in the current cycle
            # while Qarzdor_Oylar was never charged (e.g. fresh enrollment).
            fee = int(child["fee"]) if child else 0
            ov_by_title = {
                str(o.get("cycle_title") or "").strip(): int(o.get("custom_amount") or 0)
                for o in overrides_map.get(sid, [])
            }
            for cyc in unpaid_map.get(sid, []):
                title = str(cyc.get("title") or "").strip()
                if title in cycle_titles:
                    continue
                total += ov_by_title.get(title) or fee
                cycle_titles.append(title)
        if active:
            active_count += 1
            if total <= 0:
                paid_active += 1
        if total > 0:
            debtors.append(
                {
                    "name": _clean(stu.get("F.I.O.")) or sid,
                    "group": _clean(stu.get("Guruh")) or "—",
                    "active": active,
                    "phone": _clean(stu.get("Talaba_Tel"))
                    or _clean(stu.get("Otasi_Tel"))
                    or _clean(stu.get("Onasi_Tel"))
                    or "—",
                    "cycles": [c for c in cycle_titles if c] or ["—"],
                    "amount": total,
                }
            )

    teacher_by_id = {
        _clean(tch.get("Ustoz_ID")): _clean(tch.get("F.I.O.")) for tch in teachers
    }
    teacher_by_cid = {
        _clean(tch.get("Chat_ID")): _clean(tch.get("F.I.O.")) for tch in teachers
    }
    active_by_group = {}
    for stu in all_students:
        if _is_active(stu):
            key = _clean(stu.get("Guruh")).lower()
            active_by_group[key] = active_by_group.get(key, 0) + 1
    groups_overview = []
    for grp in groups:
        name = _clean(grp.get("Guruh_Nomi"))
        if not name:
            continue
        teacher = teacher_by_id.get(_clean(grp.get("Ustoz_ID"))) or teacher_by_cid.get(
            _clean(grp.get("Ustoz_Chat_ID"))
        )
        groups_overview.append(
            {
                "name": name,
                "teacher": teacher or "",
                "done": _clean(grp.get("Otilgan_Dars_Hisoblagich")) or "0",
                "total": _clean(grp.get("Oylik_Dars_Soni")) or "12",
                "students": active_by_group.get(name.lower(), 0),
            }
        )
    debtors.sort(key=lambda d: (-d["amount"], d["group"].lower(), d["name"].lower()))
    return {
        "active_students": active_count,
        "paid_students": paid_active,
        "debtor_students": sum(1 for d in debtors if d["active"]),
        "total_debt": sum(d["amount"] for d in debtors),
        "debtors": debtors,
        "groups": groups_overview,
        "source": "bot",
    }


def compute_report_from_raw(sheets_data):
    """Fallback (bot modules unavailable): Qarzdor_Oylar months x group fee."""
    s_headers, s_rows = sheets_data.get("Baza_Talabalar", ([], []))
    g_headers, g_rows = sheets_data.get("Guruhlar", ([], []))
    t_headers, t_rows = sheets_data.get("Ustozlar", ([], []))

    def _rows(headers, rows):
        idx = {h.strip(): i for i, h in enumerate(headers)}
        return [
            {h: (r[i].strip() if i < len(r) else "") for h, i in idx.items()} for r in rows
        ]

    students = _rows(s_headers, s_rows)
    groups = _rows(g_headers, g_rows)
    teachers = _rows(t_headers, t_rows)
    fee_by_group = {}
    for grp in groups:
        digits = "".join(ch for ch in grp.get("Oylik_Tolov_Summa", "") if ch.isdigit())
        fee_by_group[_clean(grp.get("Guruh_Nomi")).lower()] = int(digits) if digits else 0
    debtors = []
    active_count = paid_active = 0
    active_by_group = {}
    for stu in students:
        active = _clean(stu.get("Status")) == "O'qiyapti"
        months = _count_debt_months(stu.get("Qarzdor_Oylar"))
        group_key = _clean(stu.get("Guruh")).lower()
        amount = months * fee_by_group.get(group_key, 0)
        if active:
            active_count += 1
            active_by_group[group_key] = active_by_group.get(group_key, 0) + 1
            if months <= 0:
                paid_active += 1
        if months > 0:
            raw = _clean(stu.get("Qarzdor_Oylar"))
            debtors.append(
                {
                    "name": _clean(stu.get("F.I.O.")) or _clean(stu.get("Talaba_ID")),
                    "group": _clean(stu.get("Guruh")) or "—",
                    "active": active,
                    "phone": _clean(stu.get("Talaba_Tel")) or "—",
                    "cycles": [x.strip() for x in raw.split(";") if x.strip()] or [raw],
                    "amount": amount,
                }
            )
    teacher_by_id = {_clean(x.get("Ustoz_ID")): _clean(x.get("F.I.O.")) for x in teachers}
    teacher_by_cid = {_clean(x.get("Chat_ID")): _clean(x.get("F.I.O.")) for x in teachers}
    groups_overview = [
        {
            "name": _clean(g.get("Guruh_Nomi")),
            "teacher": teacher_by_id.get(_clean(g.get("Ustoz_ID")))
            or teacher_by_cid.get(_clean(g.get("Ustoz_Chat_ID")))
            or "",
            "done": _clean(g.get("Otilgan_Dars_Hisoblagich")) or "0",
            "total": _clean(g.get("Oylik_Dars_Soni")) or "12",
            "students": active_by_group.get(_clean(g.get("Guruh_Nomi")).lower(), 0),
        }
        for g in groups
        if _clean(g.get("Guruh_Nomi"))
    ]
    debtors.sort(key=lambda d: (-d["amount"], d["group"].lower(), d["name"].lower()))
    return {
        "active_students": active_count,
        "paid_students": paid_active,
        "debtor_students": sum(1 for d in debtors if d["active"]),
        "total_debt": sum(d["amount"] for d in debtors),
        "debtors": debtors,
        "groups": groups_overview,
        "source": "raw",
    }


def _render_debtors_table(debtors):
    title = "⚠️ To‘lov kutilayotgan talabalar (Qarzdorlar)"
    if not debtors:
        return (
            f"<h2>{html.escape(title)}</h2>"
            "<p class='ok'>✅ Barcha talabalar to‘lovni amalga oshirgan — qarzdorlar yo‘q.</p>"
        )
    rows = []
    for idx, d in enumerate(debtors, 1):
        group_cell = html.escape(d["group"])
        if not d["active"]:
            group_cell += " <span class='badge muted'>zaxira</span>"
        cycles = "<br>".join(html.escape(c) for c in d["cycles"])
        rows.append(
            f"<tr><td>{idx}</td><td><b>{html.escape(d['name'])}</b></td>"
            f"<td>{group_cell}</td><td>{html.escape(d['phone'])}</td>"
            f"<td class='wrap'>{cycles}</td>"
            f"<td class='num debt'>{_fmt_uzs(d['amount'])} so'm</td></tr>"
        )
    total = sum(d["amount"] for d in debtors)
    return (
        f"<h2>{html.escape(title)} ({len(debtors)} nafar)</h2>"
        "<div class='table-wrap'><table><thead><tr><th>№</th><th>Talaba</th><th>Guruh</th>"
        "<th>Telefon</th><th>To‘lanmagan sikl(lar)</th><th>Qarz summasi</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"<tfoot><tr><td colspan='5'><b>Jami qarz</b></td>"
        f"<td class='num debt'><b>{_fmt_uzs(total)} so'm</b></td></tr></tfoot>"
        "</table></div>"
    )


def _render_groups_overview(groups):
    title = "📚 Guruhlar holati"
    if not groups:
        return f"<h2>{html.escape(title)}</h2><p class='empty'>Ma'lumot mavjud emas.</p>"
    rows = []
    for idx, g in enumerate(groups, 1):
        teacher_cell = (
            html.escape(g["teacher"])
            if g["teacher"]
            else "<span class='badge warn'>⚠️ Ustoz biriktirilmagan</span>"
        )
        rows.append(
            f"<tr><td>{idx}</td><td><b>{html.escape(g['name'])}</b></td>"
            f"<td>{teacher_cell}</td>"
            f"<td class='num'>{html.escape(g['done'])} / {html.escape(g['total'])}</td>"
            f"<td class='num'>{int(g['students'])}</td></tr>"
        )
    return (
        f"<h2>{html.escape(title)} ({len(groups)} ta)</h2>"
        "<div class='table-wrap'><table><thead><tr><th>№</th><th>Guruh</th><th>Ustoz</th>"
        "<th>Darslar (o‘tilgan / oylik)</th><th>Faol talabalar</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def build_html_report(sheets_data, now_human, report=None):
    report = report or compute_report_from_raw(sheets_data)
    sections = [
        _render_debtors_table(report["debtors"]),
        _render_groups_overview(report["groups"]),
    ]

    order = ["Baza_Talabalar", "Ustozlar", "Guruhlar", "Qiziquvchilar_Lidlar"]
    titles = {
        "Baza_Talabalar": "Barcha talabalar va ota-onalar bazasi",
        "Ustozlar": "Ustozlar ro'yxati",
        "Guruhlar": "Guruhlar jadvali (to‘liq)",
        "Qiziquvchilar_Lidlar": "Qiziquvchi lidlar (Arizalar)",
    }
    raw_sections = []
    for tab in order:
        if tab in sheets_data:
            h, r = sheets_data[tab]
            raw_sections.append(render_table(titles.get(tab, tab), h, r))
    for tab, (h, r) in sheets_data.items():
        if tab not in order:
            raw_sections.append(render_table(f"Dars va to'lov jurnali: {tab}", h, r))

    kpis = (
        f"<div class='kpi'><span>👥 Faol talabalar</span><b>{report['active_students']}</b></div>"
        f"<div class='kpi good'><span>✅ To‘lov qilganlar</span><b>{report['paid_students']}</b></div>"
        f"<div class='kpi bad'><span>⚠️ Qarzdorlar</span><b>{report['debtor_students']}</b></div>"
        f"<div class='kpi bad'><span>💰 Jami qarz</span><b>{_fmt_uzs(report['total_debt'])} so'm</b></div>"
    )
    source_note = (
        "Qarzdorlik bot bilan bir xil hisob-kitob asosida (joriy sikl + yopilgan sikllar + avvalgi qarzlar) hisoblandi."
        if report.get("source") == "bot"
        else "Qarzdorlik «Qarzdor_Oylar» ustuni va guruh oylik to‘lovi asosida hisoblandi."
    )

    return f"""<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mishkat NTM — Kunlik hisobot ({now_human})</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; background: #f4f6f9; color: #1f2937; margin: 0; padding: 16px; }}
  .doc {{ max-width: 1100px; margin: 0 auto; background: #fff; padding: 24px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.08); }}
  .header {{ border-bottom: 2px solid #1e3a8a; padding-bottom: 14px; margin-bottom: 20px; }}
  .header h1 {{ margin: 0; font-size: 20px; color: #1e3a8a; }}
  .header p {{ margin: 6px 0 0; font-size: 13px; color: #4b5563; }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin-bottom: 8px; }}
  .kpi {{ background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 10px; padding: 14px; }}
  .kpi span {{ display: block; font-size: 13px; color: #374151; }}
  .kpi b {{ display: block; font-size: 24px; margin-top: 6px; color: #1e40af; }}
  .kpi.good {{ background: #ecfdf5; border-color: #a7f3d0; }} .kpi.good b {{ color: #047857; }}
  .kpi.bad {{ background: #fef2f2; border-color: #fecaca; }} .kpi.bad b {{ color: #b91c1c; }}
  .note {{ font-size: 12px; color: #6b7280; margin: 6px 0 18px; }}
  h2 {{ font-size: 16px; color: #111827; margin: 26px 0 10px; border-left: 4px solid #2563eb; padding-left: 10px; }}
  .table-wrap {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ border: 1px solid #d1d5db; padding: 8px 10px; text-align: left; white-space: nowrap; vertical-align: top; }}
  td.wrap {{ white-space: normal; min-width: 180px; }}
  td.num {{ text-align: right; }}
  td.debt {{ color: #b91c1c; font-weight: 600; }}
  th {{ background: #1e3a8a; color: #fff; font-weight: 600; }}
  tr:nth-child(even) {{ background: #f9fafb; }}
  tfoot td {{ background: #fef2f2; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 12px; }}
  .badge.warn {{ background: #fef3c7; color: #92400e; font-weight: 600; }}
  .badge.muted {{ background: #e5e7eb; color: #374151; }}
  .ok {{ background: #ecfdf5; border: 1px solid #a7f3d0; color: #065f46; padding: 10px 14px; border-radius: 8px; font-size: 14px; }}
  .empty {{ color: #6b7280; font-style: italic; font-size: 13px; }}
  details {{ margin-top: 28px; }}
  summary {{ cursor: pointer; font-weight: 600; color: #1e3a8a; font-size: 15px; }}
  .footer {{ margin-top: 28px; padding-top: 12px; border-top: 1px solid #e5e7eb; font-size: 12px; color: #6b7280; }}
</style>
</head>
<body>
<div class="doc">
  <div class="header">
    <h1>MISHKAT NODAVLAT TA'LIM MUASSASASI</h1>
    <p>Kunlik hisobot • Sana va vaqt: <b>{html.escape(now_human)} (Toshkent)</b></p>
  </div>
  <div class="kpis">{kpis}</div>
  <p class="note">{html.escape(source_note)}</p>
  {''.join(sections)}
  <details>
    <summary>📂 To‘liq zaxira jadvallari (barcha varaqlar)</summary>
    {''.join(raw_sections)}
  </details>
  <div class="footer">Hurmat bilan,<br>Mishkat Nodavlat Ta'lim Muassasasi!</div>
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

    report = None
    if spreadsheet_id and os.path.exists(creds_path):
        try:
            report = compute_report_with_bot_logic(BASE_DIR)
        except Exception as exc:
            print(f"Bot debt logic failed, using raw-sheet calculation: {exc}")
            report = None

    html_backup_file = os.path.join(BACKUP_DIR, f"Mishkat_Hisobot_{now_file}.html")
    with open(html_backup_file, "w", encoding="utf-8") as f:
        f.write(build_html_report(sheets_data, now_human, report))

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
