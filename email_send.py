"""שליחת מייל עם ההסכם החתום, דרך Resend (https://resend.com)."""
from __future__ import annotations

import base64
import logging
from pathlib import Path

import aiohttp

import config

log = logging.getLogger("quote-bot.email")

RESEND_URL = "https://api.resend.com/emails"


async def send_signed_agreement(*, business_name: str, signer: str, pdf_path: str | Path) -> bool:
    """שולח מייל עם ה-PDF החתום מצורף. מחזיר True אם נשלח בהצלחה."""
    if not (config.RESEND_API_KEY and config.NOTIFY_EMAIL):
        log.info("email skipped: RESEND_API_KEY/NOTIFY_EMAIL not configured")
        return False

    pdf_path = Path(pdf_path)
    payload = {
        "from": config.EMAIL_FROM,
        "to": [config.NOTIFY_EMAIL],
        "subject": f'קיבלת הסכם חתום מ"{business_name}"',
        "html": (
            "<div dir='rtl' style='font-family:Arial,sans-serif;font-size:15px'>"
            f"<p>ההסכם / הצעת המחיר עבור <b>{business_name}</b> נחתם/ה ע\"י "
            f"<b>{signer}</b>.</p>"
            "<p>הקובץ החתום מצורף להודעה זו.</p>"
            "</div>"
        ),
        "attachments": [{
            "filename": pdf_path.name,
            "content": base64.b64encode(pdf_path.read_bytes()).decode("ascii"),
        }],
    }
    headers = {
        "Authorization": f"Bearer {config.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                RESEND_URL, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status >= 300:
                    log.error("resend failed %s: %s", resp.status, await resp.text())
                    return False
                return True
    except Exception:
        log.exception("email send failed")
        return False
