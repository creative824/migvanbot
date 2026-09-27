"""שרת קטן לעמוד חתימה שנשלח ללקוח בקישור (וואטסאפ)."""
from __future__ import annotations

import base64
import datetime as _dt
import html
import logging
from pathlib import Path

from aiohttp import web

import config
import store
from render import stamp_signature
from email_send import send_signed_agreement

log = logging.getLogger("quote-bot.web")


def _summary_rows(s: dict) -> str:
    rt = "מוזיקה ללא זכויות" if s.get("rights_free", True) else "מוזיקה רגילה (עם זכויות)"
    rows = [
        ("עסק", s.get("business_name", "")),
        ("מסלול", rt),
        ("מחיר חודשי לנגן", f'{s.get("monthly_price")} ₪'),
        ("מחיר התקנה לנגן", f'{s.get("install_price")} ₪'),
        ("כמות נגנים", s.get("qty", 1)),
    ]
    if s.get("broadcasts"):
        rows.append(("שירות תשדירים", f'{s["broadcasts"]} בחודש'))
    if s.get("qty", 1) > 1:
        rows.append(("סה\"כ חודשי (לפני מע\"מ)",
                     f'{s.get("monthly_price", 0) * s["qty"]} ₪'))
        rows.append(("סה\"כ התקנה (לפני מע\"מ)",
                     f'{s.get("install_price", 0) * s["qty"]} ₪'))
    return "".join(
        f'<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v))}</td></tr>'
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
fit();addEventListener('resize',fit);
let drawing=false,dirty=false,last=null;
function pos(e){const r=pad.getBoundingClientRect();const t=e.touches?e.touches[0]:e;
 return{x:t.clientX-r.left,y:t.clientY-r.top};}
function down(e){drawing=true;last=pos(e);e.preventDefault();}
function move(e){if(!drawing)return;const p=pos(e);ctx.beginPath();ctx.moveTo(last.x,last.y);
 ctx.lineTo(p.x,p.y);ctx.stroke();last=p;dirty=true;e.preventDefault();}
function up(){drawing=false;}
pad.addEventListener('pointerdown',down);pad.addEventListener('pointermove',move);
addEventListener('pointerup',up);
document.getElementById('clr').onclick=()=>{ctx.clearRect(0,0,pad.width,pad.height);dirty=false;};
document.getElementById('snd').onclick=async()=>{
 const err=document.getElementById('err');err.textContent='';
 const name=document.getElementById('name').value.trim();
 if(name.length<2){err.textContent='נא למלא שם מלא';return;}
 if(!dirty){err.textContent='נא לחתום במסגרת';return;}
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


async def _page(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    row = store.get(token)
    if not row:
        return web.Response(text="הקישור אינו תקין או שפג תוקפו.", status=404,
                            content_type="text/plain")
    s = row["summary"]
    if row["status"] == "signed":
        body = (f'<!doctype html><meta charset=utf-8><div dir=rtl '
                f'style="font-family:system-ui;text-align:center;padding:60px">'
                f'<div style="font-size:44px">✅</div>'
                f'<h2>ההצעה כבר אושרה</h2><p style="color:#666">ע"י {html.escape(str(row["signer"]))}</p></div>')
        return web.Response(text=body, content_type="text/html")
    page = (_PAGE
            .replace("{rows}", _summary_rows(s))
            .replace("{base}", config.PUBLIC_BASE_URL)
            .replace("{token}", token)
            .replace("{date}", _dt.date.today().strftime("%d.%m.%Y")))
    return web.Response(text=page, content_type="text/html")


async def _pdf(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    row = store.get(token)
    if not row:
        return web.Response(status=404, text="not found")
    name = row.get("signed_pdf") or row["pdf"]
    path = config.OUTPUT_DIR / name
    if not path.exists():
        path = config.OUTPUT_DIR / row["pdf"]
    if not path.exists():
        return web.Response(status=404, text="missing file")
    return web.Response(
        body=path.read_bytes(), content_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="quote.pdf"'},
    )


async def _sign(request: web.Request) -> web.Response:
    token = request.match_info["token"]
    row = store.get(token)
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

    src = config.OUTPUT_DIR / row["pdf"]
    signed_name = src.stem + " - חתום.pdf"
    signed_path = config.OUTPUT_DIR / signed_name
    try:
        stamp_signature(src, signed_path, png)
    except Exception:
        log.exception("stamp failed")
        return web.json_response({"ok": False, "error": "שגיאה בהחתמה"}, status=500)

    store.mark_signed(token, name, signed_name)

    tg_app = request.app["tg_app"]
    when = _dt.datetime.now().strftime("%H:%M %d.%m.%Y")
    biz = row["summary"].get("business_name", "")
    try:
        await tg_app.bot.send_message(
            row["chat_id"],
            f"✅ *{name}* אישר/ה וחתם/ה על ההצעה של ‏{biz}‏\nזמן: {when}",
            parse_mode="Markdown",
        )
        with open(signed_path, "rb") as fh:
            await tg_app.bot.send_document(row["chat_id"], document=fh,
                                          filename=signed_name,
                                          caption="ההצעה החתומה")
    except Exception:
        log.exception("notify failed")

    try:
        sent = await send_signed_agreement(business_name=biz, signer=name, pdf_path=signed_path)
        if sent:
            await tg_app.bot.send_message(row["chat_id"], f"📧 נשלח גם למייל {config.NOTIFY_EMAIL}")
    except Exception:
        log.exception("email notify failed")

    return web.json_response({"ok": True})


async def _health(_):
    return web.Response(text="quote-bot web ok")


def make_app(tg_app) -> web.Application:
    app = web.Application(client_max_size=8 * 1024 * 1024)
    app["tg_app"] = tg_app
    app.add_routes([
        web.get("/", _health),
        web.get("/q/{token}", _page),
        web.get("/q/{token}/pdf", _pdf),
        web.post("/q/{token}/sign", _sign),
    ])
    return app


async def start(tg_app) -> web.AppRunner:
    runner = web.AppRunner(make_app(tg_app))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.WEB_PORT)
    await site.start()
    log.info("sign server on :%s  (public: %s)", config.WEB_PORT, config.PUBLIC_BASE_URL)
    return runner
