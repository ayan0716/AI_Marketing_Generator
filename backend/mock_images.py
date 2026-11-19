"""Offline placeholder image renderer (IMAGE_PROVIDER=mock). Lets the whole Phase 3 workflow run, be tested and
be demoed without an API key. Output varies with the prompt (style, colours) and uses the uploaded product photo
when one is supplied, so the product-incorporation workflow is visible too."""

import hashlib
import io
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

PALETTES = {
    "studio": ((246, 248, 255), (206, 220, 252), (59, 91, 253)),
    "lifestyle": ((255, 232, 205), (244, 190, 150), (46, 125, 90)),
    "graphic": ((255, 196, 61), (255, 107, 74), (28, 28, 60)),
    "cinematic": ((14, 18, 36), (40, 52, 98), (255, 170, 80)),
    "minimal": ((250, 248, 244), (232, 228, 220), (60, 60, 60)),
}
COLOR_WORDS = {
    "blue": (50, 100, 235), "red": (226, 60, 60), "green": (40, 160, 100), "pink": (240, 120, 170),
    "orange": (245, 130, 40), "yellow": (250, 205, 50), "purple": (130, 80, 220), "teal": (30, 160, 160),
}

def _style_key(prompt: str) -> str:
    p = prompt.lower()[:170]  # the style direction opens the prompt; later text (rules) must not decide it
    for key, words in (("cinematic", ("cinematic", "moody", "dramatic")), ("graphic", ("graphic", "flat", "poster", "bold")),
                       ("minimal", ("minimal", "editorial", "negative space")), ("lifestyle", ("lifestyle", "natural", "in context")),
                       ("studio", ("studio", "seamless"))):
        if any(w in p for w in words):
            return key
    return "studio"

def _grad(size, top, bottom):
    w, h = size
    im = Image.new("RGB", size, top)
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(h - 1, 1)
        d.line([(0, y), (w, y)], fill=tuple(round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return im

def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()

def render_mock(prompt: str, spec: dict, product_bytes: bytes | None) -> bytes:
    rnd = random.Random(int(hashlib.sha256(prompt.encode()).hexdigest()[:12], 16))
    w, h = spec["width"] // 2, spec["height"] // 2
    w, h = max(w, 512), max(h, 512)
    key = _style_key(prompt)
    top, bottom, accent = PALETTES[key]
    low = prompt.lower()
    if any(x in low for x in ("dark", "night", "black", "moody")) and key != "cinematic":
        top, bottom = (16, 20, 40), (44, 52, 90)
    revision = low.split("revision", 1)[1] if "revision" in low else ""
    for word, rgb in COLOR_WORDS.items():
        if word in revision:
            accent = rgb
            bottom = tuple(int(c * 0.35 + 255 * 0.65) for c in rgb)
    im = _grad((w, h), top, bottom)
    d = ImageDraw.Draw(im, "RGBA")
    m = min(w, h)
    # decorative shapes differ by style
    if key == "graphic":
        d.polygon([(0, h * .55), (w, h * .25), (w, h), (0, h)], fill=accent + (255,))
        d.ellipse([w * .55, h * .05, w * .55 + m * .45, h * .05 + m * .45], fill=(255, 255, 255, 190))
    elif key == "cinematic":
        for _ in range(3):
            r = rnd.randint(m // 4, m // 2)
            cx, cy = rnd.randint(0, w), rnd.randint(0, h // 2)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=accent + (38,))
    elif key == "minimal":
        d.ellipse([w * .15, h * .12, w * .15 + m * .7, h * .12 + m * .7], fill=(255, 255, 255, 220))
        d.line([(w * .1, h * .9), (w * .9, h * .9)], fill=accent + (160,), width=3)
    elif key == "lifestyle":
        for i in range(4):
            x = w * (0.08 + 0.22 * i)
            d.rounded_rectangle([x, h * .08, x + w * .16, h * .42], radius=14, fill=(255, 255, 255, 110))
        for _ in range(7):
            x, y = rnd.randint(0, w), rnd.randint(int(h * .6), h)
            d.ellipse([x, y, x + m * .22, y + m * .1], fill=accent + (120,))
    else:
        d.ellipse([w * .2, h * .18, w * .8, h * .18 + w * .6], fill=(255, 255, 255, 170))
        d.ellipse([w * .3, h * .86, w * .7, h * .93], fill=(0, 0, 0, 45))
    im = im.convert("RGBA")
    # the hero product: uploaded photo if given, otherwise a stylised bottle
    ph = int(h * (0.5 if h > w else 0.62))
    if product_bytes:
        try:
            prod = Image.open(io.BytesIO(product_bytes)).convert("RGBA")
            prod.thumbnail((int(w * 0.62), ph))
            shadow = Image.new("RGBA", prod.size, (0, 0, 0, 0))
            shadow.putalpha(prod.split()[-1].point(lambda a: int(a * 0.35)))
            shadow = shadow.filter(ImageFilter.GaussianBlur(14))
            x, y = (w - prod.width) // 2, int(h * 0.5 - prod.height / 2) + 6
            im.alpha_composite(shadow, (x + 10, y + 16))
            im.alpha_composite(prod, (x, y))
        except Exception:
            product_bytes = None
    if not product_bytes:
        bw = int(ph * 0.34)
        x0, y0 = (w - bw) // 2, int(h * 0.5 - ph / 2)
        d = ImageDraw.Draw(im, "RGBA")
        d.rounded_rectangle([x0 + 8, y0 + 14, x0 + bw + 8, y0 + ph + 14], radius=bw // 4, fill=(0, 0, 0, 50))
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + ph], radius=bw // 4, fill=accent + (255,))
        d.rounded_rectangle([x0 + bw * .28, y0 - ph * .07, x0 + bw * .72, y0 + ph * .03], radius=8, fill=(255, 255, 255, 235))
        d.rounded_rectangle([x0 + bw * .12, y0 + ph * .3, x0 + bw * .88, y0 + ph * .62], radius=10, fill=(255, 255, 255, 60))
    d = ImageDraw.Draw(im, "RGBA")
    label = f"MOCK PREVIEW  -  {spec['label']}  -  {key}"
    d.text((16, h - 28), label, fill=(120, 120, 140, 200) if key not in ("cinematic",) else (200, 205, 230, 200), font=_font(max(12, m // 40)))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG")
    return buf.getvalue()
