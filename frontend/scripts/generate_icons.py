"""Generate the PWA icon PNGs from the Spark mark.

Run from the repo root:
    .venv/Scripts/python.exe frontend/scripts/generate_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "public" / "icons"
SCALE = 4


def vertical_gradient(size: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (1, size))
    pixels = image.load()
    for y in range(size):
        ratio = y / max(1, size - 1)
        pixels[0, y] = tuple(
            round(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3)
        )
    return image.resize((size, size), Image.Resampling.BILINEAR)


def diagonal_gradient(size: int, start: tuple[int, int, int], end: tuple[int, int, int]) -> Image.Image:
    image = Image.new("RGB", (size, size))
    pixels = image.load()
    for y in range(size):
        for x in range(size):
            ratio = (x + y) / max(1, (size - 1) * 2)
            pixels[x, y] = tuple(
                round(start[i] + (end[i] - start[i]) * ratio) for i in range(3)
            )
    return image


def star_points(cx: float, cy: float, radius: float, waist: float = 0.17) -> list[tuple[float, float]]:
    inner = radius * waist
    return [
        (cx, cy - radius),
        (cx + inner, cy - inner),
        (cx + radius, cy),
        (cx + inner, cy + inner),
        (cx, cy + radius),
        (cx - inner, cy + inner),
        (cx - radius, cy),
        (cx - inner, cy - inner),
    ]


def render(size: int, *, maskable: bool) -> Image.Image:
    canvas = size * SCALE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    background = diagonal_gradient(canvas, (29, 29, 45), (11, 11, 18))
    if maskable:
        image.paste(background, (0, 0))
    else:
        mask = Image.new("L", (canvas, canvas), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, canvas - 1, canvas - 1), radius=round(canvas * 0.22), fill=255
        )
        image.paste(background, (0, 0), mask)

    # Soft radial glow behind the mark.
    cx, cy = canvas / 2, canvas / 2
    glow = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    steps = 30
    max_glow = canvas * 0.34
    for index in range(steps, 0, -1):
        radius = max_glow * index / steps
        alpha = round(2.4 * (steps - index))
        glow_draw.ellipse(
            (cx - radius, cy - radius, cx + radius, cy + radius),
            fill=(232, 115, 42, alpha),
        )
    image.alpha_composite(glow)

    star_radius = canvas * (0.285 if maskable else 0.32)
    star_mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(star_mask).polygon(
        star_points(cx, cy, star_radius), fill=255
    )
    star_fill = diagonal_gradient(canvas, (255, 196, 128), (214, 96, 31))
    image.paste(star_fill, (0, 0), star_mask)

    small_radius = star_radius * 0.32
    small_cx = cx + star_radius * 0.62
    small_cy = cy + star_radius * 0.62
    small_mask = Image.new("L", (canvas, canvas), 0)
    ImageDraw.Draw(small_mask).polygon(
        star_points(small_cx, small_cy, small_radius, waist=0.2), fill=255
    )
    small_fill = diagonal_gradient(canvas, (255, 196, 128), (255, 176, 107))
    image.paste(small_fill, (0, 0), small_mask)

    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size, name, maskable in (
        (192, "icon-192.png", False),
        (512, "icon-512.png", False),
        (512, "maskable-512.png", True),
    ):
        render(size, maskable=maskable).save(OUT / name, optimize=True)
        print(f"wrote {OUT / name}")


if __name__ == "__main__":
    main()
