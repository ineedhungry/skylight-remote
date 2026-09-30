#!/usr/bin/env python3
"""Generate the Skylight brand icon/logo PNGs for home-assistant/brands.

Draws an original skylight motif (a framed 4-pane roof window with a warm sun
over a daylight-gradient sky) - no third-party logos. Rendered at 4x and
downscaled for anti-aliasing. Requires only Pillow.

    python3 brands/make_icon.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SS = 4  # supersample factor

# palette
SKY_TOP = (78, 168, 232)      # #4EA8E8
SKY_BOT = (198, 233, 255)     # #C6E9FF
FRAME = (255, 255, 255)
FRAME_EDGE = (41, 60, 74)     # subtle dark outline so it reads on white bg
SUN = (255, 202, 64)          # #FFCA40
SUN_CORE = (255, 231, 150)    # #FFE796
TEXT = (38, 50, 62)           # #26323E


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_icon(size: int) -> Image.Image:
    """Draw the square skylight icon at `size` px (transparent background)."""
    n = size * SS
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def s(v):
        return round(v / 256 * n)

    # --- sky silhouette (rounded square, fills the canvas edge-to-edge) ---
    sky_box = (s(8), s(8), s(248), s(248))
    radius = s(48)
    mask = Image.new("L", (n, n), 0)
    ImageDraw.Draw(mask).rounded_rectangle(sky_box, radius=radius, fill=255)
    grad = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    top, bot = sky_box[1], sky_box[3]
    for y in range(top, bot + 1):
        t = (y - top) / max(1, (bot - top))
        gd.line((0, y, n, y), fill=_lerp(SKY_TOP, SKY_BOT, t) + (255,))
    img.paste(grad, (0, 0), mask)

    # subtle dark outline around the silhouette (so it shows on light cards)
    d.rounded_rectangle(sky_box, radius=radius, outline=FRAME_EDGE + (55,),
                        width=s(3))

    # --- sun in the top-left pane (drawn under the muntins) ---
    cx = cy = s(128)
    sun_c = (s(80), s(80))
    sun_r = s(27)
    d.ellipse((sun_c[0] - sun_r, sun_c[1] - sun_r,
               sun_c[0] + sun_r, sun_c[1] + sun_r), fill=SUN + (255,))
    cr = s(15)
    d.ellipse((sun_c[0] - cr - s(5), sun_c[1] - cr - s(5),
               sun_c[0] - s(5) + cr, sun_c[1] - s(5) + cr),
              fill=SUN_CORE + (255,))

    # --- white window frame ring ---
    frame_box = (s(26), s(26), s(230), s(230))
    d.rounded_rectangle(frame_box, radius=s(34), outline=FRAME + (255,),
                        width=s(15))

    # --- muntins (white cross) dividing four panes ---
    hw = s(7)
    inner0, inner1 = s(34), s(222)
    d.rectangle((cx - hw, inner0, cx + hw, inner1), fill=FRAME + (255,))
    d.rectangle((inner0, cy - hw, inner1, cy + hw), fill=FRAME + (255,))

    return img.resize((size, size), Image.LANCZOS)


def _font(px: int):
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/SFNS.ttf",
    ):
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px)
            except Exception:
                continue
    return ImageFont.load_default()


def draw_logo() -> Image.Image:
    """Horizontal lockup: icon + 'Skylight' wordmark, max 512 on the long side."""
    icon_px = 200
    icon = draw_icon(icon_px)
    font = _font(120)
    text = "Skylight"

    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    l, t, r, b = tmp.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t

    gap = 28
    pad = 8
    w = icon_px + gap + tw + pad * 2
    h = max(icon_px, th) + pad * 2
    logo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    logo.paste(icon, (pad, (h - icon_px) // 2), icon)
    ImageDraw.Draw(logo).text(
        (pad + icon_px + gap - l, (h - th) // 2 - t), text,
        font=font, fill=TEXT + (255,))

    # clamp to 512 on the longest side
    if max(w, h) > 512:
        scale = 512 / max(w, h)
        logo = logo.resize((round(w * scale), round(h * scale)), Image.LANCZOS)
    return logo


def main() -> None:
    draw_icon(256).save(os.path.join(HERE, "icon.png"))
    draw_icon(512).save(os.path.join(HERE, "icon@2x.png"))
    logo2x = draw_logo()  # 512 on the long side == the @2x asset
    logo2x.save(os.path.join(HERE, "logo@2x.png"))
    logo1x = logo2x.resize(
        (logo2x.width // 2, logo2x.height // 2), Image.LANCZOS)
    logo1x.save(os.path.join(HERE, "logo.png"))
    print(f"wrote icon.png (256), icon@2x.png (512), "
          f"logo.png ({logo1x.width}x{logo1x.height}), "
          f"logo@2x.png ({logo2x.width}x{logo2x.height})")


if __name__ == "__main__":
    main()
