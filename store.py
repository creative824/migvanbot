"""אחסון הצעות שממתינות לחתימה (טוקן → פרטים)."""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

import config

PENDING_FILE = config.OUTPUT_DIR / "pending.json"


def _load() -> dict:
    try:
        return json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(data: dict) -> None:
    try:
        PENDING_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        pass


def create(*, pdf_name: str, chat_id: int, summary: dict) -> str:
    """יוצר טוקן חדש ומחזיר אותו."""
    data = _load()
    token = secrets.token_urlsafe(9)
    data[token] = {
        "pdf": pdf_name,
        "chat_id": chat_id,
        "summary": summary,
        "created": int(time.time()),
        "status": "pending",
        "signer": None,
        "signed_at": None,
        "signed_pdf": None,
    }
    _save(data)
    return token


def get(token: str) -> dict | None:
    return _load().get(token)


def mark_signed(token: str, signer: str, signed_pdf: str) -> dict | None:
    data = _load()
    row = data.get(token)
    if not row:
        return None
    row["status"] = "signed"
    row["signer"] = signer
    row["signed_at"] = int(time.time())
    row["signed_pdf"] = signed_pdf
    _save(data)
    return row
