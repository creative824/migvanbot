"""מודל הנתונים של הצעת מחיר + עזרי פרסום/פענוח."""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass

import config


def today_str() -> str:
    d = config.tz_now()
    return f"{d.day}.{d.month}.{d.year}"


def fmt_money(value: float) -> str:
    """1870 -> '1,870' ,  187.5 -> '187.5'"""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def parse_number(text: str) -> float | None:
    """מוציא מספר מתוך טקסט חופשי: '350 ש"ח', '1,870', '187.5 לחודש' וכו'."""
    if text is None:
        return None
    cleaned = text.replace(",", "").replace("₪", " ")
    m = re.search(r"\d+(?:\.\d+)?", cleaned)
    return float(m.group()) if m else None


@dataclass
class QuoteData:
    business_name: str
    company_id: str = ""
    monthly_price: float = 0.0
    install_price: float = 0.0
    qty: int = 1
    rights_free: bool = True          # True = מוזיקה ללא זכויות
    broadcasts: int = 0               # שירות תשדירים בחודש (0 = לא להציג שורה)
    address: str = ""
    logo_path: str | None = None
    date_str: str = ""

    def __post_init__(self):
        if not self.date_str:
            self.date_str = today_str()
        self.qty = max(1, int(self.qty))
        self.broadcasts = max(0, int(self.broadcasts or 0))

    # ── סכומים ──────────────────────────────────────────────
    @property
    def monthly_total(self) -> float:
        return self.monthly_price * self.qty

    @property
    def install_total(self) -> float:
        return self.install_price * self.qty

    # ── שם קובץ ה-PDF ──────────────────────────────────────
    def filename(self) -> str:
        safe = re.sub(r'[\\/:*?"<>|]+', "-", self.business_name).strip() or "לקוח"
        date_iso = config.tz_now().date().isoformat()
        return f"הצעת מחיר - {safe} - {date_iso}.pdf"

    # ── הקשר לתבנית ────────────────────────────────────────
    def template_context(self) -> dict:
        return dict(
            business_name=self.business_name,
            company_id=self.company_id,
            address=self.address,
            date_str=self.date_str,
            monthly_price=fmt_money(self.monthly_price),
            install_price=fmt_money(self.install_price),
            qty=self.qty,
            monthly_total=fmt_money(self.monthly_total),
            install_total=fmt_money(self.install_total),
            rights_free=self.rights_free,
            broadcasts=self.broadcasts,
            track_label=(
                "מסלול מוזיקה ללא זכויות כולל עריכת מוזיקה בהתאמה אישית"
                if self.rights_free
                else "מסלול מוזיקה רגילה כולל עריכת מוזיקה בהתאמה אישית"
            ),
        )


# ── פענוח הודעה חופשית מרובת-שורות ──────────────────────────────
_RIGHTS_FREE_DET = re.compile(r"ללא\s*זכויות|בלי\s*זכויות|no[\s-]*rights")
_RIGHTS_PAID_DET = re.compile(r"עם\s*זכויות|בר[ת]?\s*זכויות|בעלת\s*זכויות|with[\s-]*rights")
# להסרה מתוך שורה (למשל כשהשם והסוג באותה שורה)
_RIGHTS_STRIP = re.compile(
    r"\s*(מוזיקה\s+)?(ללא|בלי|עם|בר[ת]?|בעלת)\s+זכויות(\s+דרך\s+מגוון)?\s*"
)
_MONTHLY_HINT = re.compile(r"חודש|לחודש|חודשי|monthly|לנגן")
_INSTALL_HINT = re.compile(r"התקנ|install")
_QTY_HINT = re.compile(r"כמות|נגנים|מכשיר|יחיד")
_BROADCAST_HINT = re.compile(r"תשדיר")
_ID_RE = re.compile(r"\b\d{7,9}\b")

# מילות "רעש" – בקשות/פתיחים שאינם נתון
_NOISE_WORD = (
    r"תעשה|עשה|תעשי|שלח|תשלח|תשלוח|תשלחי|שלחי|תוצי?א|תוצא|תוציאי|תכין|תכיני|תכן|"
    r"הכן|הכיני|צור|תצור|בוא|בואי|רוצה|נתחיל|נעשה|בוט|הצעה|הצעת|"
    r"לקוח\s*חדש|עסק\s*חדש|הצעה\s*חדשה|לקוח|עסק|חדש|מחיר|הבא|חדשה"
)
# שורה שכולה מילות רעש/מילוי → מדלגים
_FILLER = r"לי|לו|לה|להם|לנו|לך|בבקשה|כזה|כזו|עכשיו|מהר|אחת|אחד|נא|תודה|של"
_NOISE_LINE = re.compile(
    r"^\s*(?:(?:" + _NOISE_WORD + r"|" + _FILLER + r")[\s,.:!?\-–]*)+$"
)
# שורת פתיחה שמתחילה במילת רעש אך יש אחריה תוכן ("תוציא הצעה עבור X")
_PREAMBLE = re.compile(r"^\s*(?:" + _NOISE_WORD + r")\b")
# פתיחים לפני שם ("כתבתי לך X", "השם הוא X", "קוראים לו X")
_LEADIN = re.compile(
    r"^\s*(?:כתבתי|רשמתי|אמרתי|כבר\s+אמרתי|הנה|זה|זהו|השם|שם|שמו|"
    r"קוראים\s+לו|שקוראים\s+לו|תרשום|רשום|תכתוב)\s+(?:לך|לו|היא|הוא|זה|הוא\s*)?\s*"
)
# קידומת שם ("הצעה עבור ...", "הצעת מחיר ל...", "עבור ...", "ללקוח ...")
_NAME_PREFIX = re.compile(
    r"^\s*(?:הצעת\s+מחיר\s+(?:עבור|ל)?|הצעה\s+(?:עבור|ל)|עבור|ללקוח|לעסק|שם\s*[:\-–]?\s*)\s*"
)

# טוקן בודד שיש להסיר מתחילת המשפט (רעש/מילוי/מילת חיבור לפני השם).
# מוסר שוב ושוב עד שלא נשאר כלום להסיר - כך "תוציא לי הצעה עבור X" -> "X"
# גם כשהמילים "עבור"/"בשם"/"של" לא בתחילת המשפט ממש.
_LEAD_TOKEN = re.compile(
    r"^(?:" + _NOISE_WORD + r"|" + _FILLER + r"|עבור|בשם|ללקוח|לעסק|של)\b[\s,.:!\-–]*"
)


def strip_lead(text: str) -> str:
    """מסיר מתחילת הטקסט רצף מילות בקשה/רעש/פתיח, ומחזיר את מה שנשאר (השם)."""
    s = (text or "").strip()
    prev = None
    while s and s != prev:
        prev = s
        s = _LEAD_TOKEN.sub("", s, count=1).strip()
        s = _LEADIN.sub("", s, count=1).strip()
    return s

# ── הוראות עדכון מפורשות ("שם: X", "התקנה 400", ...) ─────────────
_SEP = r"\s*[:\-–=]?\s*"
_DIRECTIVES = [
    ("business_name", re.compile(
        r"^(?:שם\s*(?:העסק|הספק|הלקוח|החברה)?|השם(?:\s*הוא)?|הספק|הלקוח|"
        r"שנה\s*(?:את\s*ה)?שם(?:\s*ל)?|תקרא\s*לו)" + _SEP + r"(.+)$")),
    ("company_id", re.compile(
        r"^(?:ח[\.\s\"׳']*פ|ע[\.\s\"׳']*מ|עוסק(?:\s*מורשה)?|מספר\s*עוסק|"
        r"מספר\s*חברה|ח\.?פ\.?)" + _SEP + r"(\d[\d\s]{4,})$")),
    ("address", re.compile(r"^(?:כתובת|רחוב|כתובת\s*העסק)" + _SEP + r"(.+)$")),
    ("monthly_price", re.compile(
        r"^(?:מחיר\s*)?(?:חודשי|לחודש|עלות\s*חודשית|חודש|תשלום\s*חודשי)"
        r"(?:\s*לנגן)?" + _SEP + r"([\d][\d.,]*)")),
    ("install_price", re.compile(
        r"^(?:מחיר\s*)?התקנ\S*(?:\s*לנגן)?" + _SEP + r"([\d][\d.,]*)")),
    ("qty", re.compile(
        r"^(?:כמות|מספר)\s*(?:נגנים|הנגנים)?" + _SEP + r"(\d+)")),
    ("broadcasts", re.compile(
        r"^(?:שירות\s*)?תשדיר\S*(?:\s*(?:עד|של))?" + _SEP + r"(\d+)")),
]


# ── בקשת שכפול: "תעשה הצעה כמו פנטו אנג'וי אבל בשם X" ──────────────
_CLONE_TRIGGER = re.compile(r"כמו\s+(?:ה?הצעה\s+של\s+|ה?לקוח\s+|ה?עסק\s+|של\s+)?")
# סמנים חד-משמעיים לשם החדש
_NEW_NAME_MARK = re.compile(
    r"\s+(?:"
    r"(?:אבל|ו?רק)\s+(?:בשם|לשם|שם\s+ל|ל(?=[א-ת]))"
    r"|בשם|לשם|עבור|בשביל"
    r"|שנה\s+(?:את\s+ה?שם\s+)?ל|תשנה\s+(?:את\s+ה?שם\s+)?ל|החלף\s+(?:שם\s+)?ל"
    r")\s*[:\-–]?\s*(.+)$"
)
# פיצול-גיבוי כשלא נמצא: "<ref> רק ל<new>" / "<ref> ל<new>" / "<ref> עבור <new>"
_SPLIT_MARK = re.compile(r"^(.*?)\s+(?:(?:אבל|ו?רק)\s+ל|עבור\s+|בשביל\s+|ל(?=[א-ת]))(.+)$")


def parse_clone_request(text: str):
    """
    מזהה בקשה מסוג "כמו <לקוח> [בשם <חדש>]".
    מחזיר (ref_name, new_name_or_None, overrides_dict) או None.
    """
    m = _CLONE_TRIGGER.search(text)
    if not m:
        return None
    rest = text[m.end():].strip()
    # פירוק שורות – לוקחים רק את השורה שבה מופיע "כמו"
    rest = rest.splitlines()[0].strip() if rest else ""
    if not rest:
        return None

    new_name = None
    nm = _NEW_NAME_MARK.search(rest)
    if nm:
        raw = nm.group(1)
        raw = re.split(r"[,\n]|(?:\s[-–]\s)", raw)[0]          # עד הפריט הראשון
        new_name = re.sub(r"^ל(?=\S)", "", raw.strip()).strip(" .,-–\"'")
        ref = rest[:nm.start()].strip(" .,-–")
    else:
        ref = rest.strip(" .,-–")

    ref = re.sub(r"[,\s]+(?:שנה|תשנה|החלף|רק|אבל|ו?רק)\s*$", "", ref)
    ref = _RIGHTS_STRIP.sub(" ", ref).strip(" .,-–")
    if not ref:
        return None
    overrides = parse_directives(text)
    overrides.pop("business_name", None)   # השם מטופל בנפרד
    return ref, new_name, overrides


def parse_directives(text: str) -> dict:
    """מזהה הוראות עדכון מפורשות בהודעה. מחזיר מילון שדות מעודכנים בלבד."""
    out: dict = {}
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if _RIGHTS_FREE_DET.search(ln):
            out["rights_free"] = True
        elif _RIGHTS_PAID_DET.search(ln):
            out["rights_free"] = False
        for field, rx in _DIRECTIVES:
            m = rx.match(ln)
            if not m:
                continue
            val = m.group(1).strip(" .,-–")
            if field in ("monthly_price", "install_price"):
                n = parse_number(val)
                if n is not None:
                    out[field] = n
            elif field == "qty":
                out[field] = max(1, int(parse_number(val) or 1))
            elif field == "broadcasts":
                out[field] = max(0, int(parse_number(val) or 0))
            elif field == "company_id":
                out[field] = val.replace(" ", "")
            else:
                if val:
                    out[field] = val
            break
    return out


def parse_free_text(text: str) -> tuple[dict, list[str]]:
    """
    מקבל בלוק טקסט חופשי ומחזיר (values, missing_fields).
    values עשוי להכיל: business_name, company_id, monthly_price,
    install_price, qty, rights_free, address
    """
    values: dict = {}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    body_lines: list[str] = []
    for ln in lines:
        # מסירים רצף מילות בקשה/רעש/קידומת מתחילת השורה ("תוציא לי הצעה עבור X" -> "X").
        # שורה שהיא כולה רעש (לא נשאר ממנה כלום) - מתעלמים.
        s = strip_lead(ln)
        if s:
            body_lines.append(s)

    for ln in body_lines:
        work = ln

        # סוג מוזיקה – מזהים, ומסירים את הביטוי מהשורה כדי לא לאבד שם עסק
        if "rights_free" not in values:
            if _RIGHTS_FREE_DET.search(work):
                values["rights_free"] = True
            elif _RIGHTS_PAID_DET.search(work):
                values["rights_free"] = False
        work = _RIGHTS_STRIP.sub(" ", work).strip(" -,\t")
        if not work:
            continue

        low = work.lower()
        num = parse_number(work)

        if num is not None and _MONTHLY_HINT.search(low) and "monthly_price" not in values:
            values["monthly_price"] = num
            continue
        if num is not None and _BROADCAST_HINT.search(low) and "broadcasts" not in values:
            values["broadcasts"] = int(num)
            continue
        if num is not None and _INSTALL_HINT.search(low) and "install_price" not in values:
            values["install_price"] = num
            continue
        if num is not None and _QTY_HINT.search(low) and "qty" not in values:
            values["qty"] = int(num)
            continue

        # שורה שהיא רק ח.פ / ע.מ (7-9 ספרות)
        if "company_id" not in values and _ID_RE.fullmatch(work.replace(" ", "")):
            values["company_id"] = work.replace(" ", "")
            continue

        # שורת טקסט שאינה מספרית ואינה מזוהה = שם העסק/הספק
        if "business_name" not in values and num is None and not _ID_RE.search(work):
            values["business_name"] = work
            continue

    # מספרים "יתומים" שלא סווגו — נשייך לפי הסדר: חודשי, ואז התקנה
    orphan_nums = []
    for ln in body_lines:
        work = _RIGHTS_STRIP.sub(" ", ln).strip(" -,\t")
        low = work.lower()
        n = parse_number(work)
        if n is None:
            continue
        if _INSTALL_HINT.search(low) or _QTY_HINT.search(low) or _BROADCAST_HINT.search(low):
            continue
        if _ID_RE.fullmatch(work.replace(" ", "")):
            continue
        if _MONTHLY_HINT.search(low):
            orphan_nums.insert(0, n)   # רמז "חודשי/לנגן" -> קדימות
        else:
            orphan_nums.append(n)
    if "monthly_price" not in values and orphan_nums:
        values["monthly_price"] = orphan_nums.pop(0)
    if "install_price" not in values and orphan_nums:
        values["install_price"] = orphan_nums.pop(0)

    required = ["business_name", "monthly_price", "install_price"]
    missing = [f for f in required if f not in values]
    return values, missing
