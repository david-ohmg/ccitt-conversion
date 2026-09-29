"""Generate the app icon (icon.icns) — a smooth waveform turning into u-law samples.

Run:  uv run --with pillow make_icon.py
"""

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

SIZE = 1024
SCALE = 2  # draw at 2x and downsample for smooth edges
S = SIZE * SCALE

# macOS icon grid: 824px rounded square centered on a 1024 canvas.
TILE = 824 * SCALE
INSET = (S - TILE) // 2
RADIUS = 185 * SCALE

TOP = (34, 58, 140)
BOTTOM = (17, 158, 170)
WAVE = (255, 255, 255)
STEPS = (255, 214, 102)


def rounded_mask(size, box, radius):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, fill=255)
    return mask


def gradient(size, top, bottom):
    w, h = size
    img = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / (h - 1)
        img.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img.resize((w, h))


def wave_y(x, left, width, mid, amp):
    t = (x - left) / width
    return mid - amp * math.sin(t * 2 * math.pi * 2) * (0.6 + 0.4 * math.sin(t * math.pi))


def find_font(size):
    for name in ("/System/Library/Fonts/SFNSRounded.ttf", "/System/Library/Fonts/SFNS.ttf",
                 "/System/Library/Fonts/Helvetica.ttc"):
        try:
            font = ImageFont.truetype(name, size)
        except OSError:
            continue
        try:
            font.set_variation_by_name("Semibold")
        except (OSError, ValueError):
            pass
        return font
    return ImageFont.load_default(size)


def draw_icon() -> Image.Image:
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    box = (INSET, INSET, INSET + TILE, INSET + TILE)

    # Soft drop shadow under the tile.
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (box[0], box[1] + 14 * SCALE, box[2], box[3] + 14 * SCALE), radius=RADIUS, fill=(0, 0, 0, 90))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18 * SCALE)))

    tile = gradient((S, S), TOP, BOTTOM).convert("RGBA")
    tile.putalpha(rounded_mask((S, S), box, RADIUS))
    canvas.alpha_composite(tile)

    draw = ImageDraw.Draw(canvas)
    left, right = INSET + 110 * SCALE, INSET + TILE - 110 * SCALE
    width = right - left
    mid = INSET + 290 * SCALE
    amp = 160 * SCALE
    split = left + width * 0.5

    # Left: smooth analog waveform.
    points = [(x, wave_y(x, left, width, mid, amp)) for x in range(int(left), int(split) + 1, SCALE)]
    r = 14 * SCALE
    for px, py in points:
        draw.ellipse((px - r, py - r, px + r, py + r), fill=WAVE)

    # Right: the same wave as quantized sample bars.
    bar_w, gap = 30 * SCALE, 14 * SCALE
    x = split + gap
    while x + bar_w <= right:
        y = wave_y(x + bar_w / 2, left, width, mid, amp)
        y = mid + round((y - mid) / (34 * SCALE)) * 34 * SCALE  # snap to levels
        top, bottom = sorted((mid, y))
        draw.rounded_rectangle((x, top - 6 * SCALE, x + bar_w, bottom + 6 * SCALE), radius=8 * SCALE, fill=STEPS)
        x += bar_w + gap

    # Label.
    font = find_font(200 * SCALE)
    text = "µ-law"
    tw = draw.textlength(text, font=font)
    draw.text(((S - tw) / 2, INSET + 700 * SCALE), text, font=font, fill=WAVE, anchor="ls")

    return canvas.resize((SIZE, SIZE), Image.LANCZOS)


def main():
    icon = draw_icon()
    here = Path(__file__).parent
    icon.save(here / "icon.png")
    iconutil = shutil.which("iconutil")
    if not iconutil:
        print("Wrote icon.png (iconutil not found, skipped icon.icns)")
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for px in (16, 32, 128, 256, 512):
            icon.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{px}x{px}.png")
            icon.resize((px * 2, px * 2), Image.LANCZOS).save(iconset / f"icon_{px}x{px}@2x.png")
        subprocess.run([iconutil, "-c", "icns", str(iconset), "-o", str(here / "icon.icns")], check=True)
    print("Wrote icon.png and icon.icns")


if __name__ == "__main__":
    main()
