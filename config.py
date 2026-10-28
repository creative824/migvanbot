"""הגדרות הבוט. הערכים נטענים ממשתני סביבה (קובץ .env) עם ברירות מחדל."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
ASSETS_DIR = BASE_DIR / "assets"


def _resolve_data_dir() -> Path:
    """איפה נשמרים הקבצים והמאגר. בענן: דיסק קבוע (Railway Volume), אחרת התיקייה output."""
    p = os.getenv("DATA_DIR", "").strip() or os.getenv("RAILWAY_VOLUME_MOUNT_PATH", "").strip()
    return Path(p) if p else BASE_DIR / "output"


DATA_DIR = _resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR = DATA_DIR          # שם ישן, נשאר לתאימות

# ── אזור זמן (לתאריכים בהצעה ובהודעות) ──────────────────────────────
TIMEZONE = os.getenv("TIMEZONE", "Asia/Jerusalem").strip() or "Asia/Jerusalem"


def tz_now():
    """השעה עכשיו באזור הזמן של העסק (השרת בענן רץ ב-UTC)."""
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.now(ZoneInfo(TIMEZONE))
    except Exception:
        return _dt.datetime.now()


def tz_from_ts(ts):
    import datetime as _dt
    try:
        from zoneinfo import ZoneInfo
        return _dt.datetime.fromtimestamp(ts, ZoneInfo(TIMEZONE))
    except Exception:
        return _dt.datetime.fromtimestamp(ts)

# ── חובה ─────────────────────────────────────────────────────────────
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

# ── פרטי מגיש ההצעה (ניתן לשנות ב-.env) ─────────────────────────────
PRESENTER_NAME = os.getenv("PRESENTER_NAME", "עודד אירמייב").strip()
PRESENTER_PHONE = os.getenv("PRESENTER_PHONE", "052-8281005").strip()

# ── הגבלת גישה: רשימת מזהי משתמשי טלגרם שמורשים להשתמש בבוט ──────────
#    ריק = פתוח לכולם. דוגמה:  ALLOWED_USER_IDS=123456789,987654321
_allowed = os.getenv("ALLOWED_USER_IDS", "").replace(" ", "")
ALLOWED_USER_IDS = {int(x) for x in _allowed.split(",") if x.isdigit()}

# נתיב אופציונלי ל-Chromium (בדוקר מוגדר אוטומטית)
PLAYWRIGHT_EXECUTABLE = os.getenv("PLAYWRIGHT_EXECUTABLE", "").strip() or None

# ── שרת החתימה (קישור לוואטסאפ) ────────────────────────────────────
# כבוי כברירת מחדל. הפעלה: WEB_ENABLED=1 ב-.env, או הרצה דרך run_with_link.bat
WEB_ENABLED = os.getenv("WEB_ENABLED", "0").strip() in ("1", "true", "yes", "on")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
# הכתובת הציבורית שממנה נבנים קישורי החתימה. בענן: הדומיין של השירות.
# מקומית עם מנהרת cloudflared: הכתובת שהמנהרה מדפיסה.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/") \
    or f"http://localhost:{WEB_PORT}"

# ── לוח בקרה (רשימת כל ההצעות) ─────────────────────────────────────
# סיסמת הכניסה ל-/admin. בלי סיסמה – הלוח כבוי.
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "").strip()

# ── מייל בעת חתימה (Resend) ────────────────────────────────────────
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "").strip()      # לאן לשלוח את ההסכם החתום
EMAIL_FROM = os.getenv("EMAIL_FROM", "onboarding@resend.dev").strip()
