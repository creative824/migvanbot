"""המרת נתוני הצעה -> HTML -> PDF באמצעות Chromium (Playwright)."""
from __future__ import annotations

import base64
import mimetypes
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.async_api import async_playwright

import config
from quote import QuoteData

_env = Environment(
    loader=FileSystemLoader(str(config.TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def _data_uri(path: Path, mime: str | None = None) -> str:
    mime = mime or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


@lru_cache(maxsize=1)
def _static_assets() -> dict:
    return dict(
        header_b64=_data_uri(config.ASSETS_DIR / "header.jpg", "image/jpeg"),
        footer_b64=_data_uri(config.ASSETS_DIR / "footer.png", "image/png"),
        footer_slim_b64=_data_uri(config.ASSETS_DIR / "footer_slim.png", "image/png"),
        font_b64=_data_uri(config.ASSETS_DIR / "fonts" / "Heebo.ttf", "font/ttf"),
    )


def build_html(data: QuoteData) -> str:
    ctx = dict(_static_assets())
    ctx.update(data.template_context())
    ctx["presenter_name"] = config.PRESENTER_NAME
    ctx["presenter_phone"] = config.PRESENTER_PHONE
    ctx["logo_b64"] = _data_uri(Path(data.logo_path)) if data.logo_path else None
    return _env.get_template("quote.html").render(**ctx)


async def render_pdf(data: QuoteData, out_path: str | Path) -> Path:
    out_path = Path(out_path)
    html = build_html(data)

    launch_kwargs = {"args": ["--no-sandbox", "--disable-dev-shm-usage"]}
    if config.PLAYWRIGHT_EXECUTABLE:
        launch_kwargs["executable_path"] = config.PLAYWRIGHT_EXECUTABLE

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(**launch_kwargs)
        try:
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            await page.emulate_media(media="print")
            await page.pdf(
                path=str(out_path),
                width="210mm",
                height="297mm",
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )
        finally:
            await browser.close()
    return out_path


def stamp_signature(pdf_in: str | Path, pdf_out: str | Path, png_bytes: bytes) -> Path:
    """מטביע תמונת חתימה על עמוד החתימה (ליד 'חתימה וחותמת')."""
    import pymupdf

    pdf_in, pdf_out = Path(pdf_in), Path(pdf_out)
    doc = pymupdf.open(str(pdf_in))
    page = doc[-1]
    hits = page.search_for("חתימה וחותמת")
    ph = page.rect.height
    if hits:
        anchor = hits[0]
        x1 = anchor.x1
        y0 = anchor.y1 + 4
        y1 = min(y0 + 52, ph - 42)
        rect = pymupdf.Rect(max(x1 - 150, 28), y0, x1, y1)
    else:
        r = page.rect
        rect = pymupdf.Rect(r.width - 190, ph - 120, r.width - 40, ph - 70)
    page.insert_image(rect, stream=png_bytes, keep_proportion=True, overlay=True)
    doc.save(str(pdf_out), garbage=3, deflate=True)
    doc.close()
    return pdf_out
