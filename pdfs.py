"""עזרי קבצי PDF של הצעות שמורות."""
from __future__ import annotations

import logging
from pathlib import Path

import config
import db
from quote import QuoteData
from render import render_pdf

log = logging.getLogger("quote-bot.pdfs")


def quote_data_of(row: dict) -> QuoteData:
    """בונה QuoteData מרשומה שמורה (כולל התאריך המקורי של ההפקה)."""
    return QuoteData(
        business_name=row["business_name"],
        company_id=row.get("company_id") or "",
        monthly_price=float(row["monthly_price"] or 0),
        install_price=float(row["install_price"] or 0),
        qty=int(row.get("qty") or 1),
        rights_free=bool(row.get("rights_free")),
        broadcasts=int(row.get("broadcasts") or 0),
        date_str=db.date_str_of(row),
    )


async def ensure_pdf(row: dict) -> Path | None:
    """מחזיר נתיב ל-PDF (הלא-חתום) של ההצעה; אם הקובץ אבד – מפיק מחדש מהנתונים השמורים."""
    p = db.path_of(row.get("pdf"))
    if p and p.exists():
        return p
    name = f"q{row['id']}.pdf"
    p = db.path_of(name)
    try:
        await render_pdf(quote_data_of(row), p)
        db.set_pdf(row["id"], name)
        return p
    except Exception:
        log.exception("re-render failed for quote %s", row["id"])
        return None
