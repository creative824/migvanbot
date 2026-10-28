"""מאגר ההצעות (SQLite) – מקור האמת של הבוט ושל לוח הבקרה."""
from __future__ import annotations

import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import config

DB_PATH = config.DATA_DIR / "quotes.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    token         TEXT UNIQUE NOT NULL,
    created_at    INTEGER NOT NULL,
    chat_id       INTEGER,
    business_name TEXT NOT NULL,
    company_id    TEXT DEFAULT '',
    monthly_price REAL DEFAULT 0,
    install_price REAL DEFAULT 0,
    qty           INTEGER DEFAULT 1,
    rights_free   INTEGER DEFAULT 1,
    broadcasts    INTEGER DEFAULT 0,
    pdf           TEXT,
    signed_pdf    TEXT,
    status        TEXT DEFAULT 'pending',
    viewed_at     INTEGER,
    signed_at     INTEGER,
    signer        TEXT
);
CREATE INDEX IF NOT EXISTS idx_quotes_created ON quotes(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quotes_status ON quotes(status);
"""


@contextmanager
def _conn():
    con = sqlite3.connect(str(DB_PATH), timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    with _conn() as c:
        c.executescript(SCHEMA)


init()


# ── המרות ─────────────────────────────────────────────────────────
def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    d["rights_free"] = bool(d.get("rights_free"))
    d["qty"] = int(d.get("qty") or 1)
    d["broadcasts"] = int(d.get("broadcasts") or 0)
    return d


def fmt_ts(ts: int | None, with_time: bool = True) -> str:
    if not ts:
        return "—"
    d = config.tz_from_ts(ts)
    return d.strftime("%d.%m.%Y %H:%M" if with_time else "%d.%m.%Y")


def date_str_of(row: dict) -> str:
    d = config.tz_from_ts(row["created_at"])
    return f"{d.day}.{d.month}.{d.year}"


def nice_filename(row: dict, signed: bool = False) -> str:
    """שם קובץ קריא למשתמש (ב-DB הקבצים נשמרים בשם טכני q<id>.pdf)."""
    safe = re.sub(r'[\\/:*?"<>|]+', "-", row["business_name"]).strip() or "לקוח"
    d = config.tz_from_ts(row["created_at"]).date().isoformat()
    kind = "הצעת מחיר חתומה" if signed else "הצעת מחיר"
    return f"{kind} - {safe} - {d}.pdf"


def path_of(name: str | None) -> Path | None:
    """נתיב בטוח לקובץ בתוך DATA_DIR (מונע יציאה מהתיקייה)."""
    if not name:
        return None
    p = (config.DATA_DIR / name).resolve()
    try:
        p.relative_to(config.DATA_DIR.resolve())
    except ValueError:
        return None
    return p


# ── כתיבה ─────────────────────────────────────────────────────────
def create(*, chat_id: int | None, data) -> dict:
    """רשומה חדשה (ממתינה לחתימה). data = QuoteData."""
    token = secrets.token_urlsafe(9)
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO quotes (token, created_at, chat_id, business_name, company_id,
                   monthly_price, install_price, qty, rights_free, broadcasts)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (token, int(time.time()), chat_id, data.business_name, data.company_id or "",
             data.monthly_price, data.install_price, data.qty,
             1 if data.rights_free else 0, data.broadcasts),
        )
        qid = cur.lastrowid
    return get(qid)


def update_data(qid: int, data) -> dict | None:
    """עדכון פרטי הצעה ממתינה (תיקון לפני חתימה). הטוקן/הקישור נשארים."""
    with _conn() as c:
        c.execute(
            """UPDATE quotes SET business_name=?, company_id=?, monthly_price=?,
                   install_price=?, qty=?, rights_free=?, broadcasts=?
               WHERE id=?""",
            (data.business_name, data.company_id or "", data.monthly_price,
             data.install_price, data.qty, 1 if data.rights_free else 0,
             data.broadcasts, qid),
        )
    return get(qid)


def set_pdf(qid: int, pdf_name: str) -> None:
    with _conn() as c:
        c.execute("UPDATE quotes SET pdf=? WHERE id=?", (pdf_name, qid))


def mark_viewed(token: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE quotes SET viewed_at=? WHERE token=? AND viewed_at IS NULL",
            (int(time.time()), token),
        )


def mark_signed(token: str, signer: str, signed_pdf: str) -> dict | None:
    with _conn() as c:
        c.execute(
            """UPDATE quotes SET status='signed', signer=?, signed_at=?, signed_pdf=?
               WHERE token=? AND status!='signed'""",
            (signer, int(time.time()), signed_pdf, token),
        )
    return get_by_token(token)


def delete(qid: int) -> dict | None:
    """מוחק את הרשומה ואת הקבצים שלה. מחזיר את הרשומה שנמחקה (או None)."""
    row = get(qid)
    if not row:
        return None
    with _conn() as c:
        c.execute("DELETE FROM quotes WHERE id=?", (qid,))
    for name in (row.get("pdf"), row.get("signed_pdf")):
        p = path_of(name)
        if p and p.exists():
            try:
                p.unlink()
            except OSError:
                pass
    return row


# ── קריאה ─────────────────────────────────────────────────────────
def get(qid: int) -> dict | None:
    with _conn() as c:
        return _row(c.execute("SELECT * FROM quotes WHERE id=?", (qid,)).fetchone())


def get_by_token(token: str) -> dict | None:
    with _conn() as c:
        return _row(c.execute("SELECT * FROM quotes WHERE token=?", (token,)).fetchone())


def _like(s: str) -> str:
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def list_quotes(status: str | None = None, q: str | None = None,
                limit: int = 100, offset: int = 0) -> list[dict]:
    where, args = [], []
    if status in ("signed", "pending"):
        where.append("status=?")
        args.append(status)
    if q:
        where.append("(business_name LIKE ? ESCAPE '\\' OR company_id LIKE ? ESCAPE '\\' "
                     "OR signer LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 3
    sql = "SELECT * FROM quotes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    with _conn() as c:
        return [_row(r) for r in c.execute(sql, args).fetchall()]


def count(status: str | None = None, q: str | None = None) -> int:
    where, args = [], []
    if status in ("signed", "pending"):
        where.append("status=?")
        args.append(status)
    if q:
        where.append("(business_name LIKE ? ESCAPE '\\' OR company_id LIKE ? ESCAPE '\\' "
                     "OR signer LIKE ? ESCAPE '\\')")
        args += [_like(q)] * 3
    sql = "SELECT COUNT(*) FROM quotes"
    if where:
        sql += " WHERE " + " AND ".join(where)
    with _conn() as c:
        return c.execute(sql, args).fetchone()[0]


def counts() -> dict:
    return {
        "total": count(),
        "signed": count("signed"),
        "pending": count("pending"),
    }


def recent(n: int = 10) -> list[dict]:
    return list_quotes(limit=n)


# ── חיפוש לשכפול ("כמו X") ────────────────────────────────────────
def _norm(s: str) -> str:
    return re.sub(r"[\s\"'׳״.\-–]+", "", (s or "").strip().lower())


def find_by_name(query: str) -> dict | None:
    """ההצעה הכי חדשה שהשם שלה תואם: מדויק → מכיל → חפיפת מילים."""
    rows = list_quotes(limit=500)
    q = _norm(query)
    if not rows or not q:
        return None
    for r in rows:
        if _norm(r["business_name"]) == q:
            return r
    for r in rows:
        n = _norm(r["business_name"])
        if q in n or n in q:
            return r
    q_tokens = set(re.split(r"\s+", query.strip().lower()))
    best, best_score = None, 0
    for r in rows:
        score = len(q_tokens & set(re.split(r"\s+", r["business_name"].lower())))
        if score > best_score:
            best, best_score = r, score
    return best if best_score else None
