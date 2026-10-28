"""בוט טלגרם להפקת הצעות מחיר של מגוון מדיה קריאייטיב."""
from __future__ import annotations

import logging
import re
from functools import wraps
from pathlib import Path

from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ChatAction
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PicklePersistence,
    filters,
)

import config
import db
import pdfs
import web as signweb
from urllib.parse import quote_plus
from quote import (
    QuoteData,
    parse_free_text,
    parse_directives,
    parse_clone_request,
    parse_number,
    strip_lead,
    _SPLIT_MARK,
    _RIGHTS_FREE_DET,
    _RIGHTS_PAID_DET,
    _RIGHTS_STRIP,
)
from render import render_pdf

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s", level=logging.INFO
)
log = logging.getLogger("quote-bot")

# ── מצבי השיחה ─────────────────────────────────────────────────────
(BUSINESS, COMPANY_ID, MONTHLY, INSTALL, QTY, RIGHTS, LOGO) = range(7)

FIELD_ORDER = ["business_name", "company_id", "monthly_price",
               "install_price", "qty", "rights_free", "logo"]
STATE_OF = {
    "business_name": BUSINESS, "company_id": COMPANY_ID,
    "monthly_price": MONTHLY, "install_price": INSTALL, "qty": QTY,
    "rights_free": RIGHTS, "logo": LOGO,
}

SKIP_WORDS = {"דלג", "-", "אין", "ללא", "skip", "/skip"}
CANCEL_KB = ReplyKeyboardMarkup([["בטל ❌"]], resize_keyboard=True)


# ── בקרת גישה ─────────────────────────────────────────────────────
def restricted(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else 0
        if config.ALLOWED_USER_IDS and uid not in config.ALLOWED_USER_IDS:
            await update.effective_message.reply_text(
                f"אין לך הרשאה להשתמש בבוט הזה.\nמזהה המשתמש שלך: `{uid}`",
                parse_mode="Markdown",
            )
            return ConversationHandler.END
        return await func(update, context)
    return wrapper


# ── עזרי זרימה ────────────────────────────────────────────────────
def _d(context) -> dict:
    return context.user_data.setdefault("data", {})


_FIELD_HE = {
    "business_name": "שם", "company_id": "ח.פ",
    "monthly_price": "מחיר חודשי לנגן", "install_price": "מחיר התקנה לנגן",
    "qty": "כמות נגנים", "rights_free": "סוג מוזיקה", "broadcasts": "שירות תשדירים",
}


def _fmt_val(k, v):
    if k == "rights_free":
        return "מוזיקה ללא זכויות" if v else "מוזיקה עם זכויות"
    if k == "broadcasts":
        return f"{v} בחודש" if v else "ללא"
    return v


def _absorb_message(context, text: str) -> list[str]:
    """
    קולט נתונים מהודעה: בלוק רב-שורתי → פענוח מלא; אחרת הוראות מפורשות.
    מחזיר רשימת שדות שהשתנו (ערכים חדשים גוברים על קיימים).
    """
    d = _d(context)
    before = {k: d.get(k) for k in _FIELD_HE}
    if "\n" in text or _looks_like_details(text):
        vals, _ = parse_free_text(text)
        for k, v in vals.items():
            if v not in ("", None):
                d[k] = v
    for k, v in parse_directives(text).items():
        d[k] = v
    return [k for k in _FIELD_HE if d.get(k) != before.get(k) and d.get(k) not in ("", None)]


async def _report_changes(update, context, changed: list[str]):
    d = _d(context)
    lines = [f"{_FIELD_HE.get(k, k)}: {_fmt_val(k, d[k])}" for k in changed]
    await update.effective_message.reply_text("✏️ עודכן —\n• " + "\n• ".join(lines))


async def _absorb_or_none(update, context):
    """אם ההודעה נראית כמו בלוק פרטים / הוראת עדכון – קולט, מדווח וממשיך."""
    txt = update.message.text or ""
    if "\n" in txt or parse_directives(txt):
        changed = _absorb_message(context, txt)
        if changed:
            await _report_changes(update, context, changed)
            return await advance(update, context)
    return None


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE, field: str):
    """שולח את השאלה עבור השדה החסר ומחזיר את מצב-השיחה המתאים."""
    d = _d(context)
    msg = update.effective_message

    if field == "business_name":
        await msg.reply_text("✏️ מה שם העסק / הלקוח?", reply_markup=CANCEL_KB)
    elif field == "company_id":
        await msg.reply_text("🔢 מה מספר ח.פ / ע.מ?  (או שלח \"דלג\" אם אין)")
    elif field == "monthly_price":
        await msg.reply_text("💰 מחיר עלות חודשית לנגן (בש\"ח, לפני מע\"מ):")
    elif field == "install_price":
        await msg.reply_text("🔧 מחיר התקנה לנגן (בש\"ח, לפני מע\"מ):")
    elif field == "qty":
        await msg.reply_text("🎛️ כמה נגנים?  (מספר)")
    elif field == "rights_free":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎵 מוזיקה ללא זכויות", callback_data="rights_free")],
            [InlineKeyboardButton("🎼 מוזיקה עם זכויות", callback_data="rights_paid")],
        ])
        await msg.reply_text("איזה סוג מוזיקה?", reply_markup=kb)
    elif field == "logo":
        await msg.reply_text(
            "🖼️ רוצה לצרף לוגו של הלקוח? שלח עכשיו תמונה.\n"
            "אם לא — שלח \"דלג\" ואפיק את ההצעה."
        )
    return STATE_OF[field]


async def advance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מוצא את השדה הבא שחסר, שואל עליו, ואם הכל מלא – מפיק PDF."""
    d = _d(context)
    for field in FIELD_ORDER:
        if field == "logo":
            if "logo_done" not in d:
                return await ask(update, context, "logo")
            continue
        if field not in d:
            return await ask(update, context, field)
    return await generate(update, context)


# ── נקודות כניסה ─────────────────────────────────────────────────
@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "שלום! אני מפיק הצעות מחיר של *מגוון מדיה קריאייטיב*.\n\n"
        "אפשר להתחיל בשתי דרכים:\n"
        "1️⃣ פשוט לענות על כמה שאלות – שלח /new\n"
        "2️⃣ לשלוח את כל הפרטים בהודעה אחת, למשל:\n\n"
        "`תוציא הצעה`\n"
        "`ממן מחסנים`\n"
        "`434234234`\n"
        "`מוזיקה ללא זכויות`\n"
        "`187 לחודש לנגן`\n"
        "`350 התקנה`\n\n"
        "בסוף אפשר לצרף לוגו של הלקוח כתמונה, ותקבל PDF מוכן.\n\n"
        "📋 כל ההצעות, מי חתם ומי לא: /list\n"
        "🖥️ לוח בקרה באינטרנט: /dashboard",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


@restricted
async def new_quote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    _d(context)
    await update.message.reply_text("מתחילים הצעה חדשה 📝")
    return await advance(update, context)


def _looks_like_details(text: str) -> bool:
    return (
        text.count("\n") >= 1
        or any(ch.isdigit() for ch in text)
        or "זכויות" in text
    )


_EDIT_VERB = re.compile(r"תקן|לתקן|שנה|לשנות|תשנה|החלף|להחליף|עדכן|לעדכן|טעות|לא נכון|שגוי")
_FIELD_WORDS = [
    ("business_name", re.compile(r"\bשם\b|השם")),
    ("company_id", re.compile(r"ח\.?פ|ע\.?מ|עוסק|ח\"פ")),
    ("monthly_price", re.compile(r"חודשי|מחיר חודשי|עלות חודשית")),
    ("install_price", re.compile(r"התקנ")),
    ("qty", re.compile(r"כמות|נגנים")),
    ("rights_free", re.compile(r"זכויות|מסלול")),
    ("broadcasts", re.compile(r"תשדיר")),
    ("logo", re.compile(r"לוגו")),
]


def _edit_intent(text: str):
    """'רוצה לתקן את השם' -> 'business_name'. אחרת None."""
    if not _EDIT_VERB.search(text):
        return None
    for field, rx in _FIELD_WORDS:
        if rx.search(text):
            return field
    return None


# ── רשימת הצעות (המאגר) ──────────────────────────────────────────
PAGE_SIZE = 8
_STATUS_KEY = {"a": None, "p": "pending", "s": "signed"}
_STATUS_LABEL = {"a": "הכל", "p": "⏳ ממתינות", "s": "✅ נחתמו"}
_SEARCH_RE = re.compile(r"^(?:חפש|חיפוש|הצעות\s+של|הצעות\s+ל)\s+(.+)$")
_PENDING_RE = re.compile(
    r"^(?:מי\s+(?:עוד\s+)?לא\s+חתם|ממתינות(?:\s+לחתימה)?|הצעות\s+ממתינות|לא\s+חתמו)[\s?!.]*$")
_SIGNED_RE = re.compile(r"^(?:מי\s+חתם|נחתמו|הצעות\s+חתומות|חתמו)[\s?!.]*$")
_LIST_RE = re.compile(r"^(?:רשימה|הצעות|כל\s+ההצעות|הצג\s+הצעות)[\s?!.]*$")


def _icon(r: dict) -> str:
    if r["status"] == "signed":
        return "✅"
    return "👀" if r.get("viewed_at") else "⏳"


def _status_text(r: dict) -> str:
    if r["status"] == "signed":
        return f"✅ נחתמה ע\"י {r['signer']} ({db.fmt_ts(r['signed_at'])})"
    if r.get("viewed_at"):
        return f"👀 נפתחה ע\"י הלקוח ({db.fmt_ts(r['viewed_at'])}) — ממתינה לחתימה"
    return "⏳ ממתינה לחתימה"


def _list_view(sk: str, offset: int, q):
    status = _STATUS_KEY[sk]
    total = db.count(status, q)
    if total and offset >= total:
        offset = ((total - 1) // PAGE_SIZE) * PAGE_SIZE
    offset = max(0, offset)
    rows = db.list_quotes(status, q, limit=PAGE_SIZE, offset=offset)
    c = db.counts()
    text = f"📋 הצעות מחיר  ·  סה\"כ {c['total']}  ·  ✅ {c['signed']}  ·  ⏳ {c['pending']}"
    if q:
        text += f"\n🔎 חיפוש: {q}"
    if not rows:
        text += "\n\nלא נמצאו הצעות."
    kb = [[
        InlineKeyboardButton(("● " if k == sk else "") + _STATUS_LABEL[k], callback_data=f"ls:{k}:0")
        for k in ("a", "p", "s")
    ]]
    for r in rows:
        d = config.tz_from_ts(r["created_at"]).strftime("%d.%m")
        kb.append([InlineKeyboardButton(
            f"{_icon(r)} {r['business_name'][:26]} · {d}",
            callback_data=f"qd:{r['id']}:{sk}:{offset}")])
    nav = []
    if offset > 0:
        nav.append(InlineKeyboardButton("⬅️ הקודמים", callback_data=f"ls:{sk}:{max(0, offset - PAGE_SIZE)}"))
    if offset + PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("הבאים ➡️", callback_data=f"ls:{sk}:{offset + PAGE_SIZE}"))
    if nav:
        kb.append(nav)
    return text, InlineKeyboardMarkup(kb)


def _detail_view(r: dict, sk: str, offset: int):
    lines = [
        f"🧾 הצעה #{r['id']} — {r['business_name']}",
        f"ח.פ: {r['company_id']}" if r.get("company_id") else None,
        "מסלול: " + ("מוזיקה ללא זכויות" if r["rights_free"] else "מוזיקה רגילה (עם זכויות)"),
        f"חודשי לנגן: {r['monthly_price']:g} ₪  ·  התקנה: {r['install_price']:g} ₪  ·  נגנים: {r['qty']}",
        f"שירות תשדירים: {r['broadcasts']} בחודש" if r.get("broadcasts") else None,
        "",
        f"הופקה: {db.fmt_ts(r['created_at'])}",
        _status_text(r),
    ]
    text = "\n".join(x for x in lines if x is not None)
    kb = [[InlineKeyboardButton("📄 PDF", callback_data=f"qp:{r['id']}")]]
    if r["status"] == "signed":
        kb[0].append(InlineKeyboardButton("✍️ PDF חתום", callback_data=f"qs:{r['id']}"))
    elif config.WEB_ENABLED:
        link = f"{config.PUBLIC_BASE_URL}/q/{r['token']}"
        wa = quote_plus(f"הצעת מחיר עבור {r['business_name']}\nלצפייה ולאישור: {link}")
        kb.append([
            InlineKeyboardButton("🔗 קישור לחתימה", callback_data=f"ql:{r['id']}"),
            InlineKeyboardButton("📲 וואטסאפ", url=f"https://wa.me/?text={wa}"),
        ])
    kb.append([
        InlineKeyboardButton("📋 שכפל להצעה חדשה", callback_data=f"qc:{r['id']}"),
        InlineKeyboardButton("🗑 מחק", callback_data=f"qx:{r['id']}:{sk}:{offset}"),
    ])
    kb.append([InlineKeyboardButton("⬅️ חזרה לרשימה", callback_data=f"ls:{sk}:{offset}")])
    return text, InlineKeyboardMarkup(kb)


async def _send_list(update, context, sk: str, q=None):
    context.user_data["lq"] = q
    text, kb = _list_view(sk, 0, q)
    await update.effective_message.reply_text(text, reply_markup=kb)


@restricted
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_list(update, context, "a")


@restricted
async def cmd_pending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_list(update, context, "p")


@restricted
async def cmd_signed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _send_list(update, context, "s")


@restricted
async def cmd_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not config.WEB_ENABLED:
        await update.message.reply_text("לוח הבקרה כבוי (השרת לא פועל במצב הזה).")
        return
    if not config.ADMIN_PASSWORD:
        await update.message.reply_text(
            "לוח הבקרה עדיין לא הופעל.\nצריך להגדיר סיסמה: ב-Railway → Variables → "
            "הוסף ADMIN_PASSWORD עם סיסמה לבחירתך.")
        return
    url = f"{config.PUBLIC_BASE_URL}/admin"
    await update.message.reply_text(
        f"🖥️ לוח הבקרה של ההצעות:\n{url}\n\nבחלון ההתחברות: שם משתמש — כל דבר, "
        "סיסמה — ה-ADMIN_PASSWORD שהגדרת.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("פתח את הלוח", url=url)]]),
        disable_web_page_preview=True,
    )


async def _safe_edit(q, text, kb):
    try:
        await q.edit_message_text(text, reply_markup=kb)
    except BadRequest as e:                      # "message is not modified"
        if "not modified" not in str(e).lower():
            raise


async def _send_file(context, chat_id, path, filename, caption=None):
    with open(path, "rb") as fh:
        await context.bot.send_document(chat_id, document=fh, filename=filename, caption=caption)


@restricted
async def on_lib(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """כל כפתורי הרשימה/כרטיס ההצעה (ls, qd, qp, qs, ql, qx, qy)."""
    q = update.callback_query
    await q.answer()
    parts = q.data.split(":")
    act = parts[0]
    chat_id = q.message.chat_id

    if act == "ls":
        sk, off = parts[1], int(parts[2])
        text, kb = _list_view(sk, off, context.user_data.get("lq"))
        return await _safe_edit(q, text, kb)

    qid = int(parts[1])
    sk = parts[2] if len(parts) > 2 else "a"
    off = int(parts[3]) if len(parts) > 3 else 0
    row = db.get(qid)
    back = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ חזרה לרשימה", callback_data=f"ls:{sk}:{off}")]])
    if not row:
        return await _safe_edit(q, "ההצעה לא נמצאה (אולי נמחקה).", back)

    if act == "qd":
        text, kb = _detail_view(row, sk, off)
        return await _safe_edit(q, text, kb)

    if act == "qp":
        path = await pdfs.ensure_pdf(row)
        if not path:
            return await q.message.reply_text("לא הצלחתי להפיק את הקובץ.")
        return await _send_file(context, chat_id, path, db.nice_filename(row),
                                caption=f"הצעה #{row['id']} — {row['business_name']}")

    if act == "qs":
        sp = db.path_of(row.get("signed_pdf"))
        if not sp or not sp.exists():
            return await q.message.reply_text("הקובץ החתום לא נמצא.")
        return await _send_file(context, chat_id, sp, db.nice_filename(row, signed=True),
                                caption=f"נחתם ע\"י {row['signer']} · {db.fmt_ts(row['signed_at'])}")

    if act == "ql":
        link = f"{config.PUBLIC_BASE_URL}/q/{row['token']}"
        return await q.message.reply_text(
            f"🔗 קישור לחתימה — {row['business_name']}:\n{link}", disable_web_page_preview=True)

    if act == "qx":
        warn = ("\n\n⚠️ ההצעה חתומה! המחיקה סופית ותמחק גם את הקובץ החתום."
                if row["status"] == "signed" else "\n\nהמחיקה סופית.")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🗑 כן, מחק", callback_data=f"qy:{qid}:{sk}:{off}"),
            InlineKeyboardButton("ביטול", callback_data=f"qd:{qid}:{sk}:{off}"),
        ]])
        return await _safe_edit(q, f"למחוק את ההצעה #{row['id']} של \"{row['business_name']}\"?{warn}", kb)

    if act == "qy":
        gone = db.delete(qid)
        log.info("quote #%s deleted via bot", qid)
        return await _safe_edit(q, f"🗑 ההצעה של \"{gone['business_name']}\" נמחקה.", back)


@restricted
async def on_clone_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """כפתור 'שכפל להצעה חדשה' – מתחיל שיחה עם הנתונים של ההצעה הקיימת."""
    q = update.callback_query
    await q.answer()
    row = db.get(int(q.data.split(":")[1]))
    if not row:
        await q.message.reply_text("ההצעה לא נמצאה (אולי נמחקה).")
        return ConversationHandler.END
    context.user_data.clear()
    d = _d(context)
    for k in ("monthly_price", "install_price", "qty", "rights_free", "broadcasts"):
        d[k] = row[k]
    d["_cloned_from"] = row["business_name"]
    await q.message.reply_text(f"משכפל את ההצעה של \"{row['business_name']}\" — מה שם העסק החדש?")
    return await advance(update, context)


def _resolve_ref(ref_name: str, new_name):
    """מחזיר (row, new_name). אם השם המלא לא נמצא – מנסה לפצל '<ref> ל<new>'."""
    row = db.find_by_name(ref_name)
    if row or new_name:
        return row, new_name
    # אין new_name ולא נמצא – ננסה למצוא נקודת פיצול בתוך ref_name
    m = _SPLIT_MARK.match(ref_name)
    if m and db.find_by_name(m.group(1)):
        return db.find_by_name(m.group(1)), m.group(2).strip(" -,\t")
    # פיצול הדרגתי לפי רווחים (הקידומת הכי ארוכה שנמצאת)
    words = ref_name.split()
    for i in range(len(words) - 1, 0, -1):
        cand = " ".join(words[:i])
        hit = db.find_by_name(cand)
        if hit:
            tail = " ".join(words[i:])
            tail = re.sub(r"^(?:אבל\s+|ו?רק\s+|עבור\s+|בשביל\s+|ל(?=[א-ת]))", "", tail)
            return hit, tail.strip(" -,\t") or None
    return None, new_name


async def _handle_clone(update, context, ref_name, new_name, overrides):
    context.user_data.clear()
    d = _d(context)
    row, new_name = _resolve_ref(ref_name, new_name)
    if not row:
        rows = db.recent(10)
        hint = ("\n\nהצעות קיימות:\n" +
                "\n".join(f"• {r.get('business_name')}" for r in rows)) if rows else ""
        await update.message.reply_text(
            f"לא מצאתי הצעה קודמת בשם \"{ref_name}\".{hint}"
        )
        return ConversationHandler.END

    for k in ("monthly_price", "install_price", "qty", "rights_free", "broadcasts"):
        if row.get(k) is not None:
            d[k] = row[k]
    d.update(overrides)                       # שינויי מחיר/כמות שנכתבו בהודעה
    d["_cloned_from"] = row.get("business_name")
    if new_name:
        d["business_name"] = _RIGHTS_STRIP.sub(" ", new_name).strip(" -,\t")

    src = row.get("business_name")
    await update.message.reply_text(
        f"משכפל את ההצעה של \"{src}\" "
        + (f"בשם \"{d['business_name']}\"." if new_name else "— מה שם העסק החדש?")
    )
    return await advance(update, context)


@restricted
async def quick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    נקודת כניסה לטקסט חופשי:
    • אם ההצעה הקודמת הושלמה וההודעה היא תיקון מפורש → מעדכן ומפיק מחדש.
    • אחרת → מתחיל הצעה חדשה ומפענח כמה שאפשר מההודעה.
    """
    text = update.message.text or ""
    if _is_cancel(text):
        return await cancel(update, context)

    # רשימה / חיפוש / סטטוס בטקסט חופשי ("מי לא חתם?", "חפש פנטו") – לא נוגע בהצעה הנוכחית
    st = text.strip()
    if _PENDING_RE.match(st):
        await _send_list(update, context, "p")
        return ConversationHandler.END
    if _SIGNED_RE.match(st):
        await _send_list(update, context, "s")
        return ConversationHandler.END
    if _LIST_RE.match(st):
        await _send_list(update, context, "a")
        return ConversationHandler.END
    m = _SEARCH_RE.match(st)
    if m:
        await _send_list(update, context, "a", q=m.group(1).strip())
        return ConversationHandler.END

    # בקשת שכפול: "תעשה הצעה כמו פנטו אנג'וי אבל בשם X"
    clone = parse_clone_request(text)
    if clone:
        return await _handle_clone(update, context, *clone)

    prev = context.user_data.get("data", {})

    # תיקון מהיר להצעה שכבר נשלחה
    if prev.get("_done"):
        edits = parse_directives(text)
        if edits:                                    # ניתן ערך מפורש -> מעדכן ומפיק
            prev.pop("_done", None)
            changed = []
            for k, v in edits.items():
                if prev.get(k) != v:
                    prev[k] = v
                    changed.append(k)
            if changed:
                await _report_changes(update, context, changed)
            await update.message.reply_text("מפיק מחדש…")
            return await advance(update, context)

        field = _edit_intent(text)                   # "רוצה לתקן את השם" -> שואל ערך
        if field:
            prev.pop("_done", None)
            prev.pop(field, None)
            if field == "logo":
                prev.pop("logo_done", None)
                prev.pop("logo_path", None)
            return await advance(update, context)
        # לא תיקון – מתחילים הצעה חדשה
    context.user_data.clear()
    d = _d(context)

    if not _looks_like_details(text):
        # שורה בודדת – אם היא לא "רעש", ניקח אותה כשם העסק
        one = strip_lead(text)
        if one:
            d["business_name"] = one
            await update.message.reply_text(f"שם: {one} ✏️")
        else:
            await update.message.reply_text("נתחיל 📝")
        return await advance(update, context)

    values, missing = parse_free_text(text)
    d.update(values)

    got = []
    if "business_name" in d: got.append(f"שם: {d['business_name']}")
    if "company_id" in d: got.append(f"ח.פ: {d['company_id']}")
    if "monthly_price" in d: got.append(f"חודשי לנגן: {parse_number(str(d['monthly_price']))}")
    if "install_price" in d: got.append(f"התקנה לנגן: {parse_number(str(d['install_price']))}")
    if "qty" in d: got.append(f"כמות נגנים: {d['qty']}")
    if "rights_free" in d:
        got.append("מוזיקה ללא זכויות" if d["rights_free"] else "מוזיקה עם זכויות")
    if got:
        await update.message.reply_text("קלטתי:\n• " + "\n• ".join(got))
    return await advance(update, context)


# ── מטפלי מצבים ──────────────────────────────────────────────────
def _is_cancel(text: str) -> bool:
    return text.strip().lower() in {"בטל", "בטל ❌", "/cancel", "cancel"}


async def on_business(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if _is_cancel(txt):
        return await cancel(update, context)
    res = await _absorb_or_none(update, context)
    if res is not None:
        return res
    d = _d(context)
    # סוג מוזיקה שצורף לאותה שורה – נקלוט ונסיר
    if "rights_free" not in d:
        if _RIGHTS_FREE_DET.search(txt):
            d["rights_free"] = True
        elif _RIGHTS_PAID_DET.search(txt):
            d["rights_free"] = False
    txt = _RIGHTS_STRIP.sub(" ", txt).strip(" -,\t")
    txt = strip_lead(txt)
    if not txt:
        await update.message.reply_text("לא הבנתי את שם העסק. נסה שוב:")
        return BUSINESS
    d["business_name"] = txt
    return await advance(update, context)


async def on_company_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if _is_cancel(txt):
        return await cancel(update, context)
    if txt.lower() in SKIP_WORDS:
        _d(context)["company_id"] = ""
        return await advance(update, context)
    res = await _absorb_or_none(update, context)
    if res is not None:
        return res
    _d(context)["company_id"] = txt
    return await advance(update, context)


async def _store_number(update, context, key, label):
    txt = update.message.text.strip()
    if _is_cancel(txt):
        return await cancel(update, context)
    res = await _absorb_or_none(update, context)
    if res is not None:
        return res
    n = parse_number(txt)
    if n is None or n < 0:
        await update.message.reply_text(f"לא הצלחתי להבין את ה{label}. נסה שוב, מספר בלבד:")
        return STATE_OF[key]
    _d(context)[key] = n
    return await advance(update, context)


async def on_monthly(update, context):
    return await _store_number(update, context, "monthly_price", "מחיר החודשי")


async def on_install(update, context):
    return await _store_number(update, context, "install_price", "מחיר ההתקנה")


async def on_qty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip()
    if _is_cancel(txt):
        return await cancel(update, context)
    res = await _absorb_or_none(update, context)
    if res is not None:
        return res
    n = parse_number(txt)
    if n is None or int(n) < 1:
        await update.message.reply_text("כמות לא תקינה. שלח מספר שלם, למשל 1:")
        return QTY
    _d(context)["qty"] = int(n)
    return await advance(update, context)


async def on_rights(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _d(context)["rights_free"] = (q.data == "rights_free")
    await q.edit_message_text(
        "✅ מוזיקה ללא זכויות" if _d(context)["rights_free"] else "✅ מוזיקה עם זכויות"
    )
    return await advance(update, context)


async def on_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = _d(context)
    msg = update.message

    if msg.text and _is_cancel(msg.text):
        return await cancel(update, context)

    if msg.text and msg.text.strip().lower() in SKIP_WORDS:
        d["logo_done"] = True
        d["logo_path"] = None
        return await advance(update, context)

    file = None
    if msg.photo:
        file = await msg.photo[-1].get_file()
        ext = ".jpg"
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        file = await msg.document.get_file()
        ext = Path(msg.document.file_name or "logo.png").suffix or ".png"

    if file is None:
        await msg.reply_text("שלח תמונה של הלוגו, או \"דלג\".")
        return LOGO

    logo_path = config.OUTPUT_DIR / f"logo_{update.effective_user.id}{ext}"
    await file.download_to_drive(str(logo_path))
    d["logo_done"] = True
    d["logo_path"] = str(logo_path)
    return await advance(update, context)


# ── הפקה ────────────────────────────────────────────────────────
async def generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = _d(context)
    chat = update.effective_chat
    await context.bot.send_chat_action(chat.id, ChatAction.UPLOAD_DOCUMENT)

    data = QuoteData(
        business_name=d["business_name"],
        company_id=str(d["company_id"]),
        monthly_price=float(d["monthly_price"]),
        install_price=float(d["install_price"]),
        qty=int(d.get("qty", 1)),
        rights_free=bool(d.get("rights_free", True)),
        broadcasts=int(d.get("broadcasts", 0) or 0),
        address=d.get("address", "") or "",
        logo_path=d.get("logo_path"),
    )

    # רשומה במאגר: תיקון של הצעה שעדיין לא נחתמה מעדכן אותה (אותו קישור);
    # אחרת (הצעה חדשה / הצעה שכבר נחתמה) נוצרת רשומה חדשה.
    rec, created = None, False
    qid = d.get("_quote_id")
    if qid:
        old = db.get(qid)
        if old and old["status"] == "pending":
            rec = db.update_data(qid, data)
    if rec is None:
        rec, created = db.create(chat_id=chat.id, data=data), True
    data.date_str = db.date_str_of(rec)

    pdf_name = f"q{rec['id']}.pdf"
    out_path = config.DATA_DIR / pdf_name
    try:
        await render_pdf(data, out_path)
    except Exception as e:  # noqa: BLE001
        log.exception("render failed")
        if created:
            db.delete(rec["id"])
        await context.bot.send_message(chat.id, f"אירעה שגיאה בהפקת ההצעה:\n{e}")
        return ConversationHandler.END
    db.set_pdf(rec["id"], pdf_name)
    d["_quote_id"] = rec["id"]

    await _send_file(
        context, chat.id, out_path, db.nice_filename(rec),
        caption=f"הצעת מחיר #{rec['id']} עבור {data.business_name}\nתאריך: {data.date_str}",
    )

    # קישור חתימה לשליחה בוואטסאפ
    if config.WEB_ENABLED:
        try:
            link = f"{config.PUBLIC_BASE_URL}/q/{rec['token']}"
            wa_text = quote_plus(
                f"הצעת מחיר עבור {data.business_name}\nלצפייה ולאישור: {link}"
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("📲 שליחה בוואטסאפ",
                                     url=f"https://wa.me/?text={wa_text}")
            ]])
            await context.bot.send_message(
                chat.id,
                f"🔗 קישור לחתימת הלקוח:\n{link}\n\n"
                "שלח/י אותו ללקוח. כשהוא חותם — תקבל/י כאן התראה ואת ההצעה החתומה.",
                reply_markup=kb, disable_web_page_preview=True,
            )
        except Exception:
            log.exception("sign link failed")

    await context.bot.send_message(
        chat.id,
        "מוכן ✅  (נשמר במאגר כהצעה #%d)\n"
        "• לתקן ולשלוח שוב: כתוב למשל `שם: ...` / `התקנה: 400` / `כמות: 3`\n"
        "• הצעה חדשה: /new\n"
        "• כל ההצעות ומי חתם: /list   • לוח בקרה: /dashboard" % rec["id"],
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    d["_done"] = True          # שומרים את הנתונים כדי לאפשר תיקון מהיר
    return ConversationHandler.END


@restricted
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.effective_message.reply_text(
        "בוטל. להתחלה מחדש שלח /new", reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END


async def _post_init(app: Application) -> None:
    try:
        await app.bot.set_my_commands([
            BotCommand("new", "הצעה חדשה"),
            BotCommand("list", "כל ההצעות"),
            BotCommand("pending", "ממתינות לחתימה"),
            BotCommand("signed", "נחתמו"),
            BotCommand("dashboard", "לוח בקרה"),
            BotCommand("cancel", "ביטול"),
        ])
    except Exception:
        log.exception("set_my_commands failed")
    log.info("data dir: %s  (quotes in DB: %s)", config.DATA_DIR, db.counts())
    if config.WEB_ENABLED:
        try:
            app.bot_data["_web_runner"] = await signweb.start(app)
        except Exception:
            log.exception("web server failed to start")


async def _post_shutdown(app: Application) -> None:
    runner = app.bot_data.get("_web_runner")
    if runner is not None:
        await runner.cleanup()


def build_application() -> Application:
    if not config.BOT_TOKEN:
        raise SystemExit("חסר BOT_TOKEN. הגדר אותו בקובץ .env")

    persistence = PicklePersistence(
        filepath=str(config.OUTPUT_DIR / "bot_state.pkl")
    )
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .persistence(persistence)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    text_only = filters.TEXT & ~filters.COMMAND
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("new", new_quote),
            CommandHandler("start", start),
            CallbackQueryHandler(on_clone_cb, pattern=r"^qc:"),
            MessageHandler(text_only, quick),
        ],
        states={
            BUSINESS: [MessageHandler(text_only, on_business)],
            COMPANY_ID: [MessageHandler(text_only, on_company_id)],
            MONTHLY: [MessageHandler(text_only, on_monthly)],
            INSTALL: [MessageHandler(text_only, on_install)],
            QTY: [MessageHandler(text_only, on_qty)],
            RIGHTS: [CallbackQueryHandler(on_rights, pattern="^rights_")],
            LOGO: [
                MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_logo),
                MessageHandler(text_only, on_logo),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("new", new_quote),
            CommandHandler("start", start),
        ],
        name="quote_conv",
        persistent=True,
    )
    app.add_handler(conv)
    # רשימת ההצעות עובדת גם באמצע שיחה, בלי להפריע לה
    app.add_handler(CommandHandler("list", cmd_list))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("signed", cmd_signed))
    app.add_handler(CommandHandler("dashboard", cmd_dashboard))
    app.add_handler(CallbackQueryHandler(on_lib, pattern=r"^(ls|qd|qp|qs|ql|qx|qy):"))
    return app


def main():
    app = build_application()
    log.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
