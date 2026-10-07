"""Local brand layer (Pillow): logo overlay, exact-text cards, quote-cards.

The Google image backend's replacement for what Pixfaro did server-side:
  - `overlay`     stamps the brand logo (or a handle) onto an image, pixel-exact.
  - `text_card`   typesets a headline + short items onto a picture (or a plain
                  brand background). Text is typed, never drawn by a model, so a
                  CRA deadline or a percentage comes out exactly as written.
  - `quote_card`  a typeset quote-card of the hook line.

Every function writes a new PNG into `output/images/` and returns its path.
Re-saving drops embedded metadata (C2PA included), which matches what
Pixfaro's composited images carried: none.

Brand fields come from the environment so nothing personal lives in code:
  BRAND_LOGO_PATH   transparent PNG (relative paths resolve from the repo root)
  BRAND_PRIMARY     hex, e.g. #2c366c        (bands, headline panels)
  BRAND_ACCENT      hex, e.g. #4aa6dd        (rules, bullet markers)
  BRAND_BACKGROUND  hex, default #f5f3ee     (off-white canvas)
  BRAND_HANDLE      e.g. @yourcompany        (optional text stamp)
Mirror them in references/voice-profile.md §6 so the writing skills see them.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path
from typing import Any, Optional, Sequence

from ._env import load_env

ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = Path(__file__).resolve().parent / "fonts" / "PlusJakartaSans.ttf"
OUTPUT_DIR = ROOT / "output" / "images"

#: Canvas sizes in px for the shapes LinkedIn shows best. 4:5 portrait leads
#: single-image engagement (AuthoredUp 2026, 368k posts).
SIZES = {"4:5": (1080, 1350), "1:1": (1080, 1080), "16:9": (1200, 675), "9:16": (1080, 1920)}

_FALLBACK_FONTS = ("C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/Helvetica.ttc",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def brand() -> dict[str, Any]:
    load_env()
    logo = os.getenv("BRAND_LOGO_PATH") or ""
    if logo and not Path(logo).is_absolute():
        logo = str(ROOT / logo)
    return {
        "logo_path": logo if logo and Path(logo).is_file() else None,
        "primary": os.getenv("BRAND_PRIMARY") or "#1f2a44",
        "accent": os.getenv("BRAND_ACCENT") or "#3b82c4",
        "background": os.getenv("BRAND_BACKGROUND") or "#f5f3ee",
        "handle": os.getenv("BRAND_HANDLE") or None,
    }


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageOps
    except ImportError as e:  # pragma: no cover
        raise ImportError("Pillow is needed for the brand layer: pip install Pillow") from e
    return Image, ImageDraw, ImageFont, ImageOps


def font(size: int, weight: str = "Bold"):
    _, _, ImageFont, _ = _pil()
    if FONT_PATH.is_file():
        f = ImageFont.truetype(str(FONT_PATH), size)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        return f
    for p in _FALLBACK_FONTS:
        if Path(p).is_file():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


def _load(path: str):
    """Open an image fully into memory and release the file handle."""
    Image, _, _, _ = _pil()
    with Image.open(path) as im:
        im.load()
        return im.copy()


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _save(img, tag: str) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(img.tobytes() + tag.encode()).hexdigest()[:16]
    path = OUTPUT_DIR / f"gcard_{digest}.png"
    img.convert("RGB").save(path, "PNG", optimize=True)
    return str(path)


def _wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        words, cur = para.split(), ""
        for w in words:
            trial = f"{cur} {w}".strip()
            if draw.textlength(trial, font=fnt) <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
    return lines


def _fit(draw, text: str, max_w: int, max_h: int, start: int, floor: int, weight: str = "Bold",
         leading: float = 1.22):
    """Largest font size (start..floor) whose wrapped text fits the box."""
    size = start
    while True:
        fnt = font(size, weight)
        lines = _wrap(draw, text, fnt, max_w)
        h = int(len(lines) * size * leading)
        if h <= max_h or size <= floor:
            return fnt, lines, size, h
        size -= 2


def _cover(img, w: int, h: int):
    _, _, _, ImageOps = _pil()
    return ImageOps.fit(img.convert("RGB"), (w, h), centering=(0.5, 0.5))


def _logo_sticker(canvas, logo_path: str, *, width_frac: float, position: str, margin: int,
                  sticker: bool = True) -> None:
    Image, ImageDraw, _, _ = _pil()
    logo = _load(logo_path).convert("RGBA")
    W, H = canvas.size
    lw = int(W * width_frac)
    logo = logo.resize((lw, max(1, int(logo.height * lw / logo.width))), Image.LANCZOS)
    pad = int(logo.height * 0.35) if sticker else 0
    bw, bh = logo.width + 2 * pad, logo.height + 2 * pad
    x = margin if "left" in position else W - bw - margin
    y = margin if "top" in position else H - bh - margin
    if sticker:
        layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle([x, y, x + bw, y + bh], radius=pad,
                                                fill=(255, 255, 255, 240))
        canvas.alpha_composite(layer)
    canvas.alpha_composite(logo, (x + pad, y + pad))


def overlay(image_path: str, *, logo_path: Optional[str] = None, text: Optional[str] = None,
            position: str = "bottom-right", width_frac: float = 0.2, color: Optional[str] = None,
            sticker: bool = True) -> str:
    """Stamp a logo (preferred) or a text handle onto an image. Returns the new path.

    `logo_path=None` and `text=None` use the brand defaults (BRAND_LOGO_PATH,
    else BRAND_HANDLE). Position: bottom-right | bottom-left | top-right | top-left.
    """
    Image, ImageDraw, _, _ = _pil()
    b = brand()
    canvas = _load(image_path).convert("RGBA")
    W, H = canvas.size
    margin = int(min(W, H) * 0.03)
    logo = logo_path or (None if text else b["logo_path"])
    if logo:
        _logo_sticker(canvas, logo, width_frac=width_frac, position=position, margin=margin, sticker=sticker)
    else:
        label = text or b["handle"]
        if not label:
            return _save(canvas, "overlay-none")
        fnt = font(max(18, int(H * 0.028)), "SemiBold")
        d = ImageDraw.Draw(canvas)
        tw = int(d.textlength(label, font=fnt))
        x = margin if "left" in position else W - tw - margin
        y = margin if "top" in position else H - int(H * 0.028 * 1.4) - margin
        d.text((x, y), label, font=fnt, fill=_rgb(color or b["primary"]))
    return _save(canvas, f"overlay-{position}")


def text_card(headline: str, items: Sequence[str] = (), *, background: Optional[str] = None,
              subhead: Optional[str] = None, footer: Optional[str] = None, size: str = "4:5",
              numbered: bool = True, logo: bool = True) -> str:
    """Typeset a headline (and up to 7 short items) as an on-brand card.

    `background`: path to a picture (e.g. a wordless Gemini illustration) shown
    between the headline band and the item panel; None for a plain brand canvas.
    All text is typed with the brand font, so every character is exactly as given.
    """
    Image, ImageDraw, _, _ = _pil()
    if len(items) > 7:
        raise ValueError("text_card holds at most 7 items; split into a carousel")
    b = brand()
    W, H = SIZES.get(size, SIZES["4:5"])
    primary, accent, bg = _rgb(b["primary"]), _rgb(b["accent"]), _rgb(b["background"])
    canvas = Image.new("RGBA", (W, H), bg + (255,))
    d = ImageDraw.Draw(canvas)
    pad = int(W * 0.07)
    inner = W - 2 * pad

    # Headline band (primary colour, white type).
    band_max = int(H * (0.30 if items else 0.42))
    hfnt, hlines, hsize, hh = _fit(d, headline, inner, band_max - 2 * pad, start=int(W * 0.075), floor=36)
    sub_h = 0
    if subhead:
        sfnt, slines, ssize, sub_h = _fit(d, subhead, inner, int(H * 0.08), start=int(W * 0.034), floor=22,
                                          weight="Medium")
    band_h = hh + sub_h + 2 * pad + (int(pad * 0.4) if subhead else 0)
    d.rectangle([0, 0, W, band_h], fill=primary)
    d.rectangle([0, band_h, W, band_h + int(H * 0.008)], fill=accent)
    y = pad
    for ln in hlines:
        d.text((pad, y), ln, font=hfnt, fill=(255, 255, 255))
        y += int(hsize * 1.22)
    if subhead:
        y += int(pad * 0.4)
        for ln in slines:
            d.text((pad, y), ln, font=sfnt, fill=(255, 255, 255, 220))
            y += int(ssize * 1.22)

    footer_h = int(H * 0.10)
    body_top = band_h + int(H * 0.008)
    body_bottom = H - footer_h

    if items:
        # Item panel sizing first, so the picture gets whatever is left.
        n = len(items)
        ipad = int(pad * 0.7)
        avail = body_bottom - body_top - int(pad * 0.6)
        pic_h = int((avail) * 0.38) if background else 0
        panel_h_max = avail - pic_h - int(pad * 0.4)
        row_max = (panel_h_max - 2 * ipad) // n
        marker = int(min(row_max * 0.62, W * 0.065))
        text_w = inner - 2 * ipad - marker - int(ipad * 0.8)
        # One font size for every item, the largest that fits all rows.
        isize = int(W * 0.042)
        while isize > 22:
            ifnt = font(isize, "SemiBold")
            if all(len(_wrap(d, it, ifnt, text_w)) * isize * 1.2 <= row_max * 0.9 for it in items):
                break
            isize -= 2
        ifnt = font(isize, "SemiBold")
        wrapped = [_wrap(d, it, ifnt, text_w) for it in items]
        rows_h = [max(marker, int(len(w) * isize * 1.2)) for w in wrapped]
        gap = int(ipad * 0.55)
        panel_h = sum(rows_h) + gap * (n - 1) + 2 * ipad
        if background:
            pic_h = avail - panel_h - int(pad * 0.4)
            pic = _cover(_load(background), W, max(1, pic_h + int(pad * 0.6)))
            canvas.paste(pic, (0, body_top))
        py = (body_top + (pic_h + int(pad * 0.6) if background else int(pad * 0.6)))
        if background:
            py -= int(pad * 0.3)
        d.rounded_rectangle([pad, py, W - pad, py + panel_h], radius=int(pad * 0.45),
                            fill=(255, 255, 255, 255), outline=accent, width=3)
        ry = py + ipad
        mfnt = font(int(marker * 0.55), "Bold")
        for i, (lines, rh) in enumerate(zip(wrapped, rows_h)):
            mx, my = pad + ipad, ry + (rh - marker) // 2
            d.ellipse([mx, my, mx + marker, my + marker], fill=accent if numbered else primary)
            label = str(i + 1) if numbered else "\u2713"
            lw = d.textlength(label, font=mfnt)
            d.text((mx + (marker - lw) / 2, my + marker * 0.18), label, font=mfnt, fill=(255, 255, 255))
            ty = ry + (rh - int(len(lines) * isize * 1.2)) // 2
            for ln in lines:
                d.text((mx + marker + int(ipad * 0.8), ty), ln, font=ifnt, fill=primary)
                ty += int(isize * 1.2)
            ry += rh + gap
    elif background:
        pic = _cover(_load(background), W, body_bottom - body_top)
        canvas.paste(pic, (0, body_top))

    # Footer strip: optional footer text left, logo right.
    d.rectangle([0, body_bottom, W, H], fill=bg)
    if footer:
        ffnt = font(int(W * 0.026), "Medium")
        d.text((pad, body_bottom + footer_h * 0.36), footer, font=ffnt, fill=primary)
    if logo and b["logo_path"]:
        lw, lh = _load(b["logo_path"]).size
        logo_h = W * 0.24 * lh / lw
        _logo_sticker(canvas, b["logo_path"], width_frac=0.24, position="bottom-right",
                      margin=max(pad // 2, int((footer_h - logo_h) / 2)), sticker=False)
    elif b["handle"]:
        hf = font(int(W * 0.026), "SemiBold")
        tw = d.textlength(b["handle"], font=hf)
        d.text((W - pad - tw, body_bottom + footer_h * 0.36), b["handle"], font=hf, fill=primary)
    return _save(canvas, f"text_card-{headline}-{'|'.join(items)}")


def quote_card(quote: str, *, name: Optional[str] = None, handle: Optional[str] = None,
               size: str = "4:5", logo: bool = True) -> str:
    """Typeset the hook line as a quote-card. Exact text, brand font and colours."""
    Image, ImageDraw, _, _ = _pil()
    if len(quote) > 280:
        raise ValueError("quote is capped at 280 characters")
    b = brand()
    W, H = SIZES.get(size, SIZES["4:5"])
    primary, accent, bg = _rgb(b["primary"]), _rgb(b["accent"]), _rgb(b["background"])
    canvas = Image.new("RGBA", (W, H), bg + (255,))
    d = ImageDraw.Draw(canvas)
    pad = int(W * 0.09)
    stripe = int(H * 0.11)
    d.rectangle([0, H - stripe, W, H], fill=primary)
    d.rectangle([0, H - stripe - int(H * 0.008), W, H - stripe], fill=accent)

    qfnt = font(int(W * 0.30), "ExtraBold")
    mark = "“"
    # Measure the drawn ink: textbbox reports the default instance of the
    # variable font, which overstates this glyph's height.
    probe = Image.new("L", (W, W), 0)
    ImageDraw.Draw(probe).text((0, 0), mark, font=qfnt, fill=255)
    mb = probe.getbbox() or (0, 0, 0, 0)
    mark_h = mb[3] - mb[1]
    attr = " · ".join(x for x in (name, handle or None) if x)
    attr_h = int(W * 0.09) if attr else 0
    area = (H - stripe) - 2 * pad
    fnt, lines, fsize, th = _fit(d, quote, W - 2 * pad, area - mark_h - attr_h, start=int(W * 0.085), floor=34)
    gap = int(fsize * 0.5)
    y = pad + max(0, (area - (mark_h + gap + th + attr_h)) // 2)
    d.text((pad - int(W * 0.01), y - mb[1]), mark, font=qfnt, fill=accent)
    y += mark_h + gap
    for ln in lines:
        d.text((pad, y), ln, font=fnt, fill=primary)
        y += int(fsize * 1.22)
    if attr:
        y += int(fsize * 0.4)
        d.rectangle([pad, y, pad + int(W * 0.08), y + 6], fill=accent)
        d.text((pad, y + 20), attr, font=font(int(W * 0.032), "SemiBold"), fill=primary)
    if logo and b["logo_path"]:
        _logo_sticker(canvas, b["logo_path"], width_frac=0.26, position="bottom-right",
                      margin=int(stripe * 0.18), sticker=True)
    return _save(canvas, f"quote_card-{quote}-{attr}")
