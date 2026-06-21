"""Generate icon.ico for DuneBox-sandcam — a desert-dune themed app icon.

Run once to (re)create the desktop/shortcut icon. Zero state, deterministic.

    uv run --with pillow python generate_icon.py

Produces a multi-resolution Windows .ico (16/32/48/64/128/256) at icon.ico.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 256
ICO_SIZES = [16, 32, 48, 64, 128, 256]


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def render(size: int = SIZE) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-square background with a sky-to-sand vertical gradient.
    radius = round(size * 0.22)
    sky_top = (38, 52, 92)       # deep dusk blue
    sky_bot = (214, 156, 88)     # warm sand horizon
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        grad.putpixel((0, y), _lerp(sky_top, sky_bot, y / (size - 1)))
    grad = grad.resize((size, size))

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.paste(grad, (0, 0), mask)

    # Stylised dune ridges (sine bands) in graduated sand tones.
    dune_colors = [(232, 196, 132), (210, 162, 96), (176, 124, 70)]
    bases = [0.62, 0.74, 0.86]
    for ci, (color, base) in enumerate(zip(dune_colors, bases)):
        pts = []
        amp = size * (0.05 + 0.015 * ci)
        period = size * (0.9 - 0.1 * ci)
        phase = ci * 1.3
        for x in range(size + 1):
            y = base * size + amp * math.sin(2 * math.pi * x / period + phase)
            pts.append((x, y))
        pts += [(size, size), (0, size)]
        draw.polygon(pts, fill=color)

    # Soft sun low on the horizon.
    sun_r = round(size * 0.12)
    cx, cy = round(size * 0.70), round(size * 0.50)
    draw.ellipse([cx - sun_r, cy - sun_r, cx + sun_r, cy + sun_r], fill=(255, 226, 170))

    # Re-apply rounded mask so the dunes/sun stay inside the badge.
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def main() -> None:
    base = render(SIZE)
    out = Path(__file__).with_name("icon.ico")
    base.save(out, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    print(f"Wrote {out} ({out.stat().st_size} bytes, sizes={ICO_SIZES})")


if __name__ == "__main__":
    main()
