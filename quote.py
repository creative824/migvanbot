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


def months_label(n: int) -> str:
    n = int(n)
    if n == 1:
        return "חודש אחד"
    if n == 2:
        return "חודשיים"
    return f"{n} חודשים"


def track_label(rights_free: bool, rights_both: bool = False) -> str:
    """נוסח המסלול בשורת המחיר הראשונה."""
    suffix = "כולל עריכת מוזיקה בהתאמה אישית"
    if rights_both:
        return f"מסלול מוזיקה ללא זכויות/עם זכויות (לבחירת הלקוח) {suffix}"
    if rights_free:
        return f"מסלול מוזיקה ללא זכויות {suffix}"
    return f"מסלול מוזיקה רגילה {suffix}"


@dataclass
class QuoteData:
    business_name: str
    company_id: str = ""
    monthly_price: float = 0.0
    install_price: float = 0.0
    qty: int = 1
    rights_free: bool = True          # True = מוזיקה ללא זכויות
    rights_both: bool = False         # True = "ללא זכויות/עם זכויות (לבחירת הלקוח)"
    broadcasts: int = 0               # שירות תשדירים בחודש (0 = לא להציג שורה)
    broadcast_addon: float = 0.0      # תוספת מחיר לשילוב שירות תשדירים (0 = אין)
    rental_months: int = 12           # תקופת שכירות מינימלית
    address: str = ""
    logo_path: str | None = None
    date_str: str = ""

    def __post_init__(self):
        if not self.date_str:
            self.date_str = today_str()
        self.qty = max(1, int(self.qty))
        self.broadcasts = max(0, int(self.broadcasts or 0))
        self.broadcast_addon = max(0.0, float(self.broadcast_addon or 0))
        self.rental_months = max(1, int(self.rental_months or 12))
        self.rights_both = bool(self.rights_both)

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

    @property
    def no_install(self) -> bool:
        return not self.install_price

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
            rights_both=self.rights_both,
            broadcasts=self.broadcasts,
            broadcast_addon=fmt_money(self.broadcast_addon) if self.broadcast_addon else "",
            no_install=self.no_install,
            rental_label=months_label(self.rental_months),
            track_label=track_label(self.rights_free, self.rights_both),
            track_in="ב" + track_label(self.rights_free, self.rights_both),
        )


# ── פענוח הודעה חופשית מרובת-שורות ──────────────────────────────
_RIGHTS_FREE_DET = re.compile(r"ללא\s*זכויות|בלי\s*זכויות|no[\s-]*rights")
_RIGHTS_PAID_DET = re.compile(
    r"עם\s*זכויות|בר[ת]?\s*זכויות|בעלת\s*זכויות|מוזיקה\s+רגיל[הת]?|with[\s-]*rights")
_RIGHTS_BOTH_DET = re.compile(r"גם\s*וגם|שניהם|לבחירת\s*הלקוח|עם\s+ו(?:ללא|בלי)\s+זכויות")
# להסרה מתוך שורה (למשל כשהשם והסוג באותה שורה)
_RIGHTS_STRIP = re.compile(
    r"\s*(?:(?:מוזיקה\s+)?(?:ללא|בלי|עם|בר[ת]?|בעלת)\s+זכויות(?:\s+דרך\s+מגוון)?|מוזיקה\s+רגיל[הת]?)\s*"
)
_BOTH_STRIP = re.compile(r"\s*\(?\s*(?:גם\s*וגם|שניהם|לבחירת\s*הלקוח)\s*\)?\s*")
_NO_INSTALL = re.compile(r"(?:ללא|בלי|אין)\s+התקנ\S*")
_RENTAL_NUM = re.compile(r"(\d+)\s*חודשים")
_RENTAL_WORD = re.compile(r"חצי\s+שנה|שנתיים")
_RENTAL_NOISE = re.compile(r"(?<![א-ת])(?:תקופת|שכירות|מינימלית|התחייבות|רק|של|ל)(?![א-ת])")
_NO_LOGO = re.compile(r"(?:ללא|בלי|אין)\s+לוגו")
_LOGO_RE = re.compile(r"(?:(?:עם|תוסיף|תוסיפי|הוסף|הוסיפי|בליווי|וגם)\s+)?לוגו")
# "מחיר עם תשדירים" = המחיר החודשי לנגן כשכוללים שירות תשדירים (מחיר חלופי, לא תוספת על המחיר)
_BROADCAST_ADDON_WORDS = re.compile(
    r"תוספת|במידה|לשלב|אופציונל|(?:עם|כולל)\s+(?:שירות\s+)?תשדיר")
_NO_BROADCAST = re.compile(r"(?:בלי|ללא|אין)\s+(?:שירות\s+)?תשדיר\S*")
_MONEY_WORDS = re.compile(r"₪|ש\"ח|ש״ח|שקל", re.I)


def clean_rights(text: str) -> str:
    """מסיר מהשורה ביטויי סוג מוזיקה (כולל 'לבחירת הלקוח') ושאריות פיסוק."""
    t = _BOTH_STRIP.sub(" ", text)
    t = _RIGHTS_STRIP.sub(" ", t)
    return t.strip(" -,\t/\\()")


def rights_in(line: str):
    """'both' / 'free' / 'paid' / None לפי הניסוח בשורה."""
    free = bool(_RIGHTS_FREE_DET.search(line))
    paid = bool(_RIGHTS_PAID_DET.search(line))
    if (free and paid) or _RIGHTS_BOTH_DET.search(line):
        return "both"
    if free:
        return "free"
    if paid:
        return "paid"
    return None


def broadcast_kind(line: str, num: float) -> str:
    """'addon' = המחיר החודשי כשכוללים תשדירים, 'count' = כמות תשדירים בחודש."""
    if _BROADCAST_ADDON_WORDS.search(line) or _MONEY_WORDS.search(line):
        return "addon"
    if re.search(r"בחודש|לחודש|עד\s*\d", line):
        return "count"
    return "addon" if num >= 40 else "count"


def parse_broadcast_numbers(line: str):
    """
    משורה על תשדירים מחזיר (מחיר חודשי כולל תשדירים | None, כמות תשדירים בחודש | None).
    "תשדירים 199 4 בחודש" -> (199, 4);  "199 עם תשדירים" -> (199, None);  "תשדירים 4 בחודש" -> (None, 4)
    """
    nums = [parse_number(x) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", line)]
    nums = [n for n in nums if n is not None]
    if not nums:
        return None, None
    cm = re.search(r"(\d+)\s*(?:תשדירים\s*)?(?:ב|ל)חודש", line) or re.search(r"עד\s*(\d+)", line)
    count = int(cm.group(1)) if cm else None
    if count is not None and count > 60:        # "199 לחודש עם תשדירים" – זה מחיר, לא כמות
        count = None
    if len(nums) >= 2:
        if count is not None:
            rest = [n for n in nums if int(n) != count] or nums[:1]
            return float(rest[0]), count
        return float(max(nums)), int(min(nums))
    n = nums[0]
    if count is not None:
        return None, count
    return (float(n), None) if broadcast_kind(line, n) == "addon" else (None, int(n))


_UP_TO_RE = re.compile(r"עד\s*(\d+)\s*(?:ב|ל)חודש")


def scan_flags(line: str, out: dict, override: bool = False) -> str:
    """
    מזהה בשורה "דגלים" (סוג מוזיקה, לוגו, תקופת שכירות, ללא התקנה), רושם אותם ל-out
    ומחזיר את מה שנשאר מהשורה (השם / מחיר וכד').
    """
    def put(key, val):
        if override or key not in out:
            out[key] = val

    work = line

    r = rights_in(work)
    if r == "both":
        put("rights_both", True); put("rights_free", True)
    elif r == "free":
        put("rights_free", True); put("rights_both", False)
    elif r == "paid":
        put("rights_free", False); put("rights_both", False)
    if r:
        work = clean_rights(work)

    if _NO_LOGO.search(work):
        work = _NO_LOGO.sub(" ", work).strip(" -,\t")
    elif _LOGO_RE.search(work):
        put("want_logo", True)
        work = _LOGO_RE.sub(" ", work).strip(" -,\t")

    m = _RENTAL_NUM.search(work)
    if m:
        put("rental_months", int(m.group(1)))
        work = _RENTAL_NUM.sub(" ", work)
        work = _RENTAL_NOISE.sub(" ", work).strip(" -,:\t")
    else:
        m = _RENTAL_WORD.search(work)
        if m:
            put("rental_months", 24 if "שנתיים" in m.group(0) else 6)
            work = _RENTAL_WORD.sub(" ", work)
            work = _RENTAL_NOISE.sub(" ", work).strip(" -,:\t")

    if _NO_INSTALL.search(work):
        put("install_price", 0.0)
        work = _NO_INSTALL.sub(" ", work).strip(" -,\t")

    return work.strip()
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
        scan_flags(ln, out, override=True)
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
            elif field == "company_id":
                out[field] = val.replace(" ", "")
            else:
                if val:
                    out[field] = val
            break
        else:
            # שורה על תשדירים: "140 בלי תשדירים" / "199 עם תשדירים" / "תשדירים 4 בחודש"
            mu = _UP_TO_RE.fullmatch(ln)
            if mu:
                out["broadcasts"] = int(mu.group(1))
            elif _BROADCAST_HINT.search(ln):
                if _NO_BROADCAST.search(ln):
                    mnum = re.search(r"\d[\d.,]*", ln)
                    if mnum and parse_number(mnum.group(0)) is not None:
                        out["monthly_price"] = parse_number(mnum.group(0))
                else:
                    price, count = parse_broadcast_numbers(ln)
                    if price is not None:
                        out["broadcast_addon"] = price
                    if count is not None:
                        out["broadcasts"] = count
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

        # דגלים: סוג מוזיקה, לוגו, תקופת שכירות, ללא התקנה – מזהים ומסירים מהשורה
        work = scan_flags(work, values)
        if not work:
            continue

        low = work.lower()
        num = parse_number(work)

        # "עד 4 בחודש" בשורה נפרדת = כמות התשדירים
        mu = _UP_TO_RE.fullmatch(work.strip())
        if mu:
            if "broadcasts" not in values:
                values["broadcasts"] = int(mu.group(1))
            continue
        # שורות על תשדירים קודם לכל (כדי ש"199 לחודש עם תשדירים" לא ייקלט כמחיר הרגיל)
        if num is not None and _BROADCAST_HINT.search(low):
            if _NO_BROADCAST.search(low):                 # "140 בלי תשדירים" = המחיר הרגיל
                if "monthly_price" not in values:
                    values["monthly_price"] = num
            else:                                         # "תשדירים 199 4 בחודש" = מחיר + כמות
                price, count = parse_broadcast_numbers(work)
                if price is not None and "broadcast_addon" not in values:
                    values["broadcast_addon"] = price
                if count is not None and "broadcasts" not in values:
                    values["broadcasts"] = count
            continue
        if num is not None and _MONTHLY_HINT.search(low) and "monthly_price" not in values:
            values["monthly_price"] = num
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
        work = scan_flags(ln, {})
        low = work.lower()
        n = parse_number(work)
        if n is None:
            continue
        if _INSTALL_HINT.search(low) or _QTY_HINT.search(low) or _BROADCAST_HINT.search(low):
            continue
        if _UP_TO_RE.fullmatch(work.strip()):     # "עד 4 בחודש" = כמות תשדירים, לא מחיר
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
