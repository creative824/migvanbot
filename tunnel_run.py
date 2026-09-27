"""
מריץ מנהרת cloudflared (כתובת אינטרנט ציבורית זמנית לעמוד החתימה),
מעדכן PUBLIC_BASE_URL בקובץ .env, ואז מפעיל את הבוט.
שימוש:  python tunnel_run.py
עצירה:  Ctrl+C  (עוצר גם את המנהרה)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENV = BASE / ".env"
PORT = os.getenv("WEB_PORT", "8080")

_CANDIDATES = [
    shutil.which("cloudflared"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\cloudflared.exe"),
    os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
        r"\Cloudflare.cloudflared_Microsoft.Winget.Source_8wekyb3d8bbwe\cloudflared.exe"
    ),
]


def _find_cloudflared() -> str:
    for c in _CANDIDATES:
        if c and Path(c).exists():
            return c
    sys.exit(
        "לא נמצא cloudflared. התקן עם:\n"
        "  winget install --id Cloudflare.cloudflared -e"
    )


def _set_env_var(key: str, value: str) -> None:
    lines = []
    if ENV.exists():
        lines = [ln for ln in ENV.read_text(encoding="utf-8").splitlines()
                 if not ln.strip().startswith(key + "=")]
    lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    cf = _find_cloudflared()
    print("מפעיל מנהרה ציבורית…")
    proc = subprocess.Popen(
        [cf, "tunnel", "--url", f"http://localhost:{PORT}", "--no-autoupdate"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    url = None
    rx = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
    t0 = time.time()
    try:
        for line in proc.stdout:                       # type: ignore[union-attr]
            m = rx.search(line)
            if m:
                url = m.group(0)
                break
            if time.time() - t0 > 40:
                break
    except Exception:
        pass

    if not url:
        proc.terminate()
        sys.exit("לא הצלחתי לקבל כתובת מהמנהרה. נסה שוב, או בדוק חיבור אינטרנט.")

    print(f"\n  כתובת ציבורית:  {url}\n")
    _set_env_var("PUBLIC_BASE_URL", url)
    _set_env_var("WEB_ENABLED", "1")

    # מפעילים את הבוט באותו חלון
    try:
        env = dict(os.environ, PUBLIC_BASE_URL=url, WEB_ENABLED="1")
        bot = subprocess.Popen([sys.executable, "-u", "bot.py"], cwd=str(BASE), env=env)
        bot.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in (locals().get("bot"), proc):
            try:
                if p:
                    p.terminate()
            except Exception:
                pass
        print("\nהמנהרה והבוט נעצרו.")


if __name__ == "__main__":
    main()
