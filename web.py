"""שרת אינטרנט: עמוד חתימה ללקוח (בקישור) + לוח בקרה של כל ההצעות (/admin)."""
from __future__ import annotations

import asyncio
import base64
import html
import logging
import secrets
import time
from urllib.parse import quote as _urlquote

from aiohttp import web

import config
import db
import pdfs
from render import stamp_signature
from email_send import send_signed_agreement

log = logging.getLogger("quote-bot.web")


def _summary_rows(s: dict) -> str:
    rt = "מוזיקה ללא זכויות" if s.get("rights_free", True) else "מוזיקה רגילה (עם זכויות)"
    qty = int(s.get("qty") or 1)
    mp, ip = float(s.get("monthly_price") or 0), float(s.get("install_price") or 0)
    rows = [
        ("עסק", s.get("business_name", "")),
        ("מסלול", rt),
        ("מחיר חודשי לנגן", f"{mp:g} ₪"),
        ("מחיר התקנה לנגן", f"{ip:g} ₪"),
        ("כמות נגנים", qty),
    ]
    if s.get("broadcasts"):
        rows.append(("שירות תשדירים", f'{s["broadcasts"]} בחודש'))
    if qty > 1:
        rows.append(('סה"כ חודשי (לפני מע"מ)', f"{mp * qty:g} ₪"))
        rows.append(('סה"כ התקנה (לפני מע"מ)', f"{ip * qty:g} ₪"))
    return "".join(
        f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>"
        for k, v in rows
    )


_PAGE = """<!doctype html><html lang="he" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>אישור הצעת מחיר</title>
<style>
 *{box-sizing:border-box} body{margin:0;font-family:system-ui,"Segoe UI",Arial,sans-serif;
   background:#f4f5f7;color:#1a1a1a;padding:16px}
 .card{max-width:520px;margin:0 auto;background:#fff;border-radius:14px;
   box-shadow:0 2px 14px rgba(0,0,0,.08);padding:20px}
 h1{font-size:19px;margin:0 0 4px} .sub{color:#666;font-size:13px;margin:0 0 16px}
 table{width:100%;border-collapse:collapse;font-size:14px;margin-bottom:14px}
 td{padding:7px 8px;border-bottom:1px solid #eee} td:first-child{color:#666;width:45%}
 a.view{display:block;text-align:center;padding:11px;border:1px solid #6aa84f;color:#3d7a1f;
   border-radius:9px;text-decoration:none;font-weight:600;margin-bottom:18px}
 label{display:block;font-size:13px;color:#444;margin:12px 0 5px}
 input[type=text]{width:100%;padding:11px;border:1px solid #ccc;border-radius:9px;font-size:15px}
 .can-wrap{border:1px dashed #bbb;border-radius:9px;background:#fafafa;margin-top:6px}
 canvas{display:block;width:100%;height:180px;touch-action:none;border-radius:9px}
 .row{display:flex;gap:8px;margin-top:8px}
 button{flex:1;padding:12px;border:0;border-radius:9px;font-size:15px;font-weight:600;cursor:pointer}
 .clear{background:#eee;color:#333} .send{background:#25a244;color:#fff}
 .send:disabled{opacity:.5}
 .done{text-align:center;padding:30px 10px} .done .big{font-size:44px}
 .err{color:#c0392b;font-size:13px;margin-top:8px;min-height:18px}
</style></head><body>
<div class="card" id="card">
 <h1>אישור הצעת מחיר</h1>
 <p class="sub">מגוון מדיה קריאייטיב · {date}</p>
 <table>{rows}</table>
 <a class="view" href="{base}/q/{token}/pdf" target="_blank">צפייה בהצעה המלאה (PDF) ↗</a>

 <label for="name">שם מלא של החותם/ת</label>
 <input type="text" id="name" autocomplete="name" placeholder="שם מלא">

 <label>חתימה (חתמו עם האצבע)</label>
 <div class="can-wrap"><canvas id="pad"></canvas></div>
 <div class="row">
   <button class="clear" type="button" id="clr">נקה</button>
   <button class="send" type="button" id="snd">אני מאשר/ת וחותם/ת</button>
 </div>
 <div class="err" id="err"></div>
</div>
<script>
const pad=document.getElementById('pad'), ctx=pad.getContext('2d');
function fit(){const r=pad.getBoundingClientRect();const dpr=window.devicePixelRatio||1;
 pad.width=r.width*dpr;pad.height=r.height*dpr;ctx.scale(dpr,dpr);
 ctx.lineWidth=2.5;ctx.lineCap='round';ctx.strokeStyle='#12245b';}
fit();
// לא קושרים ל-resize: בטלפון המקלדת שנפתחת/נסגרת (למשל בלחיצה על שדה השם)
// מפעילה resize, וקריאה חוזרת ל-fit() הייתה מוחקת את החתימה שכבר צוירה.
let drawing=false,dirty=false,last=null;
function pos(e){const r=pad.getBoundingClientRect();const t=e.touches?e.touches[0]:e;
 return{x:t.clientX-r.left,y:t.clientY-r.top};}
function down(e){drawing=true;last=pos(e);e.preventDefault();}
function move(e){if(!drawing)return;const p=pos(e);ctx.beginPath();ctx.moveTo(last.x,last.y);
 ctx.lineTo(p.x,p.y);ctx.stroke();last=p;dirty=true;e.preventDefault();}
function up(){drawing=false;}
function hasInk(){
 // בדיקה אמיתית שיש קווים על הלוח (לא רק שה-flag dirty דלוק) -
 // מגנה מפני מצב שבו הציור נמחק (למשל ע"י המקלדת שנפתחה) אבל dirty נשאר true.
 try{
  const d=ctx.getImageData(0,0,pad.width,pad.height).data;
  for(let i=3;i<d.length;i+=4){ if(d[i]>10) return true; }
  return false;
 }catch(e){ return dirty; }
}
pad.addEventListener('pointerdown',down);pad.addEventListener('pointermove',move);
addEventListener('pointerup',up);
document.getElementById('clr').onclick=()=>{ctx.clearRect(0,0,pad.width,pad.height);dirty=false;};
document.getElementById('snd').onclick=async()=>{
 const err=document.getElementById('err');err.textContent='';
 const name=document.getElementById('name').value.trim();
 if(name.length<2){err.textContent='נא למלא שם מלא';return;}
 if(!dirty || !hasInk()){err.textContent='נא לחתום במסגרת - נראה שהחתימה נמחקה, נסו לחתום שוב';return;}
 // תמונה משולבת: החתימה + שורת טקסט עם השם והתאריך
 const out=document.createElement('canvas');out.width=pad.width;out.height=pad.height+70;
 const o=out.getContext('2d');o.fillStyle='#fff';o.fillRect(0,0,out.width,out.height);
 o.drawImage(pad,0,0);
 o.fillStyle='#12245b';o.font='22px system-ui, Arial';o.direction='rtl';o.textAlign='right';
 const d=new Date().toLocaleDateString('he-IL');
 o.fillText('נחתם דיגיטלית ע"י '+name+' · '+d, out.width-14, pad.height+42);
 const snd=document.getElementById('snd');snd.disabled=true;
 try{
  const r=await fetch('{base}/q/{token}/sign',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:name,image:out.toDataURL('image/png')})});
  const j=await r.json();
  if(!r.ok||!j.ok){throw new Error(j.error||'שגיאה');}
  document.getElementById('card').innerHTML=
   '<div class="done"><div class="big">✅</div><h1>ההצעה אושרה</h1>'+
   '<p class="sub">תודה '+name.replace(/</g,'')+'. העותק החתום נשלח לנציג.</p></div>';
 }catch(e){err.textContent=e.message||'שגיאה בשליחה';snd.disabled=false;}
};
</script></body></html>"""


_NOINDEX = {"X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-store"}


async def _page(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    row = db.get_by_token(token)
    if not row:
        return web.Response(text="הקישור אינו תקין או שפג תוקפו.", status=404,
                            content_type="text/plain", headers=_NOINDEX)
    if row["status"] == "signed":
        body = ('<!doctype html><meta charset=utf-8>'
                '<meta name=viewport content="width=device-width,initial-scale=1">'
                '<div dir=rtl style="font-family:system-ui;text-align:center;padding:60px 16px">'
                '<div style="font-size:44px">✅</div>'
                '<h2>ההצעה כבר אושרה</h2>'
                f'<p style="color:#666">ע"י {html.escape(str(row["signer"]))}</p></div>')
        return web.Response(text=body, content_type="text/html", headers=_NOINDEX)
    db.mark_viewed(token)
    page = (_PAGE
            .replace("{rows}", _summary_rows(row))
            .replace("{base}", config.PUBLIC_BASE_URL)
            .replace("{token}", token)
            .replace("{date}", db.fmt_ts(row["created_at"], with_time=False)))
    return web.Response(text=page, content_type="text/html", headers=_NOINDEX)


def _pdf_response(path, filename: str) -> web.Response:
    return web.Response(
        body=path.read_bytes(), content_type="application/pdf",
        headers={
            "Content-Disposition": 'inline; filename="quote.pdf"; filename*=UTF-8\'\''
                                   + _urlquote(filename),
            **_NOINDEX,
        },
    )


async def _pdf(request: web.Request) -> web.Response:
    row = db.get_by_token(request.match_info["token"])
    if not row:
        return web.Response(status=404, text="not found")
    signed = bool(row.get("signed_pdf"))
    path = db.path_of(row["signed_pdf"] if signed else row["pdf"])
    if not path or not path.exists():
        path = await pdfs.ensure_pdf(row)
        signed = False
    if not path or not path.exists():
        return web.Response(status=404, text="missing file")
    return _pdf_response(path, db.nice_filename(row, signed=signed))


async def _sign(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    row = db.get_by_token(token)
    if not row:
        return web.json_response({"ok": False, "error": "קישור לא תקין"}, status=404)
    if row["status"] == "signed":
        return web.json_response({"ok": False, "error": "כבר אושר"}, status=409)
    try:
        data = await request.json()
        name = (data.get("name") or "").strip()[:80]
        img = data.get("image") or ""
        b64 = img.split(",", 1)[1] if "," in img else img
        png = base64.b64decode(b64)
        assert name and len(png) > 500
    except Exception:
        return web.json_response({"ok": False, "error": "נתונים חסרים"}, status=400)

    src = await pdfs.ensure_pdf(row)
    if not src:
        return web.json_response({"ok": False, "error": "קובץ ההצעה לא נמצא"}, status=500)
    signed_name = f"q{row['id']}_signed.pdf"
    signed_path = db.path_of(signed_name)
    try:
        stamp_signature(src, signed_path, png)
    except Exception:
        log.exception("stamp failed")
        return web.json_response({"ok": False, "error": "שגיאה בהחתמה"}, status=500)

    row = db.mark_signed(token, name, signed_name) or row

    tg_app = request.app["tg_app"]
    when = db.fmt_ts(row.get("signed_at") or int(time.time()))
    biz = row["business_name"]
    nice = db.nice_filename(row, signed=True)
    try:
        await tg_app.bot.send_message(
            row["chat_id"],
            f"✅ *{name}* אישר/ה וחתם/ה על ההצעה של ‏{biz}‏ (#{row['id']})\nזמן: {when}",
            parse_mode="Markdown",
        )
        with open(signed_path, "rb") as fh:
            await tg_app.bot.send_document(row["chat_id"], document=fh,
                                          filename=nice, caption="ההצעה החתומה")
    except Exception:
        log.exception("notify failed")

    try:
        sent = await send_signed_agreement(business_name=biz, signer=name, pdf_path=signed_path)
        if sent:
            await tg_app.bot.send_message(row["chat_id"], f"📧 נשלח גם למייל {config.NOTIFY_EMAIL}")
    except Exception:
        log.exception("email notify failed")

    return web.json_response({"ok": True})


# ── לוח בקרה (/admin) ─────────────────────────────────────────────
_FAILS: dict[str, list[float]] = {}


def _client_ip(request: web.Request) -> str:
    fwd = request.headers.get("X-Forwarded-For", "")
    return (fwd.split(",")[0].strip() if fwd else (request.remote or "?")) or "?"


def _basic_ok(request: web.Request) -> bool:
    h = request.headers.get("Authorization", "")
    if not h.lower().startswith("basic "):
        return False
    try:
        raw = base64.b64decode(h[6:].strip()).decode("utf-8")
        pw = raw.split(":", 1)[1]
    except Exception:
        return False
    return secrets.compare_digest(pw.encode(), config.ADMIN_PASSWORD.encode())


@web.middleware
async def _admin_guard(request: web.Request, handler):
    if not request.path.startswith("/admin"):
        return await handler(request)
    if not config.ADMIN_PASSWORD:
        return web.Response(
            status=503, content_type="text/plain", headers=_NOINDEX,
            text="לוח הבקרה כבוי. יש להגדיר ADMIN_PASSWORD בהגדרות השרת.")
    ip = _client_ip(request)
    now = time.time()
    recent = [t for t in _FAILS.get(ip, []) if now - t < 600]
    _FAILS[ip] = recent
    if len(recent) >= 10:
        return web.Response(status=429, text="יותר מדי ניסיונות. נסו שוב בעוד כמה דקות.",
                            content_type="text/plain", headers=_NOINDEX)
    if not _basic_ok(request):
        if request.headers.get("Authorization"):
            _FAILS[ip].append(now)
            await asyncio.sleep(0.8)
        return web.Response(
            status=401, text="נדרשת התחברות", content_type="text/plain",
            headers={"WWW-Authenticate": 'Basic realm="Migvan quotes", charset="UTF-8"',
                     **_NOINDEX})
    if request.method not in ("GET", "HEAD") and request.headers.get("X-Admin") != "1":
        return web.Response(status=403, text="forbidden")
    resp = await handler(request)
    resp.headers.update(_NOINDEX)
    return resp


def _public(row: dict) -> dict:
    out = {k: row[k] for k in (
        "id", "business_name", "company_id", "monthly_price", "install_price", "qty",
        "rights_free", "broadcasts", "created_at", "viewed_at", "signed_at", "signer",
        "status")}
    out["link"] = f"{config.PUBLIC_BASE_URL}/q/{row['token']}"
    out["has_pdf"] = True      # אם הקובץ אבד – מפיקים מחדש בעת הצפייה
    sp = db.path_of(row.get("signed_pdf"))
    out["has_signed"] = bool(sp and sp.exists())
    return out


async def _admin_page(request: web.Request) -> web.Response:
    text = (config.TEMPLATES_DIR / "admin.html").read_text(encoding="utf-8")
    return web.Response(text=text, content_type="text/html")


async def _admin_list(request: web.Request) -> web.Response:
    status = request.query.get("status") or None
    q = (request.query.get("q") or "").strip() or None
    rows = db.list_quotes(status=status, q=q, limit=500)
    return web.json_response({"counts": db.counts(), "quotes": [_public(r) for r in rows]})


async def _admin_pdf(request: web.Request) -> web.Response:
    try:
        qid = int(request.match_info["id"])
    except ValueError:
        return web.Response(status=404, text="not found")
    row = db.get(qid)
    if not row:
        return web.Response(status=404, text="not found")
    if request.query.get("signed"):
        sp = db.path_of(row.get("signed_pdf"))
        if sp and sp.exists():
            return _pdf_response(sp, db.nice_filename(row, signed=True))
        return web.Response(status=404, text="no signed file")
    path = await pdfs.ensure_pdf(row)
    if not path:
        return web.Response(status=404, text="missing file")
    return _pdf_response(path, db.nice_filename(row))


async def _admin_delete(request: web.Request) -> web.Response:
    try:
        qid = int(request.match_info["id"])
    except ValueError:
        return web.json_response({"ok": False}, status=404)
    row = db.delete(qid)
    if not row:
        return web.json_response({"ok": False}, status=404)
    log.info("quote #%s (%s) deleted from dashboard", qid, row["business_name"])
    return web.json_response({"ok": True})


async def _health(_):
    return web.Response(text="quote-bot web ok")


def make_app(tg_app) -> web.Application:
    app = web.Application(client_max_size=8 * 1024 * 1024, middlewares=[_admin_guard])
    app["tg_app"] = tg_app
    app.add_routes([
        web.get("/", _health),
        web.get("/q/{token}", _page),
        web.get("/q/{token}/pdf", _pdf),
        web.post("/q/{token}/sign", _sign),
        web.get("/admin", _admin_page),
        web.get("/admin/api/quotes", _admin_list),
        web.get("/admin/pdf/{id}", _admin_pdf),
        web.post("/admin/api/delete/{id}", _admin_delete),
    ])
    return app


async def start(tg_app) -> web.AppRunner:
    runner = web.AppRunner(make_app(tg_app))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.WEB_PORT)
    await site.start()
    log.info("web server on :%s  (public: %s, dashboard: %s)", config.WEB_PORT,
             config.PUBLIC_BASE_URL, "on" if config.ADMIN_PASSWORD else "off")
    return runner
