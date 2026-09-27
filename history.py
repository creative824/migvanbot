"""היסטוריית הצעות – שמירה מקומית ושליפה לפי שם לקוח (לשכפול)."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import config

HISTORY_FILE = config.OUTPUT_DIR / "history.json"

_FIELDS = ("business_name", "company_id", "monthly_price", "install_price",
          "qty", "rights_free", "broadcasts")


def _norm(s: str) -> str:
    return re.sub(r"[\s\"'׳״.\-–]+", "", (s or "").strip().lower())


def _load() -> list[dict]:
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(rows: list[dict]) -> None:
    try:
        HISTORY_FILE.write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except Exception:
        pass


def save_quote(data) -> None:
    """שומר/מעדכן רשומה לפי שם העסק (הכי חדש ראשון)."""
    rows = _load()
    entry = {f: getattr(data, f) for f in _FIELDS}
    entry["ts"] = int(time.time())
    key = _norm(entry["business_name"])
    rows = [r for r in rows if _norm(r.get("business_name", "")) != key]
    rows.insert(0, entry)
    _save(rows[:200])


def find_quote(query: str) -> dict | None:
    """שליפה: התאמה מדויקת → מכילה → חפיפת מילים."""
    rows = _load()
    if not rows:
        return None
    q = _norm(query)
    if not q:
        return None
    for r in rows:                       # מדויק
        if _norm(r.get("business_name", "")) == q:
            return r
    for r in rows:                       # מכיל
        n = _norm(r.get("business_name", ""))
        if q and (q in n or n in q):
            return r
    q_tokens = set(re.split(r"\s+", query.strip().lower()))
    best, best_score = None, 0
    for r in rows:
        n_tokens = set(re.split(r"\s+", r.get("business_name", "").lower()))
        score = len(q_tokens & n_tokens)
        if score > best_score:
            best, best_score = r, score
    return best if best_score else None


def recent(n: int = 10) -> list[dict]:
    return _load()[:n]
