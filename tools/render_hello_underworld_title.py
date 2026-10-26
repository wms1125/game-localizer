from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


EXPECTED_SOURCE_SHA256 = "5c923fe755c93ea7f5770ee6cc7d6828da7d30be18e5f22b468296f725c4bb68"
EXPECTED_SIZE = (816, 624)
SYMBOL_REGION = (326, 292, 486, 510)
TITLE_TEXT = "冥界"
TITLE_CENTER = (408, 216)
FONT_SIZE = 126
CHARACTER_SPACING = 18
SCALE = 4


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean_title_region(source: Image.Image) -> Image.Image:
    dark_plate = source.convert("RGB").point(lambda value: min(value, 18)).filter(
        ImageFilter.GaussianBlur(22)
    )
    mask = Image.new("L", source.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((108, 124, 708, 300), radius=34, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(14))
    cleaned = Image.composite(dark_plate, source.convert("RGB"), mask).convert("RGBA")
    cleaned.paste(source.crop(SYMBOL_REGION), SYMBOL_REGION[:2])
    return cleaned


def _spaced_text_layer(
    font: ImageFont.FreeTypeFont,
    *,
    fill: tuple[int, int, int, int],
    stroke_fill: tuple[int, int, int, int],
    stroke_width: int,
) -> tuple[Image.Image, tuple[int, int, int, int]]:
    glyphs: list[tuple[str, tuple[int, int, int, int]]] = []
    width = 0
    top = 0
    bottom = 0
    spacing = CHARACTER_SPACING * SCALE
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    for character in TITLE_TEXT:
        bounds = probe.textbbox(
            (0, 0),
            character,
            font=font,
            stroke_width=stroke_width,
        )
        glyphs.append((character, bounds))
        width += bounds[2] - bounds[0]
        top = min(top, bounds[1])
        bottom = max(bottom, bounds[3])
    width += spacing * (len(glyphs) - 1)
    height = bottom - top
    padding = 20 * SCALE
    layer = Image.new("RGBA", (width + padding * 2, height + padding * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cursor = padding
    for character, bounds in glyphs:
        draw.text(
            (cursor - bounds[0], padding - top),
            character,
            font=font,
            fill=fill,
            stroke_fill=stroke_fill,
            stroke_width=stroke_width,
        )
        cursor += bounds[2] - bounds[0] + spacing
    content_bounds = (padding, padding, padding + width, padding + height)
    return layer, content_bounds


def _draw_localized_title(base: Image.Image, font_path: Path) -> Image.Image:
    font = ImageFont.truetype(str(font_path), size=FONT_SIZE * SCALE)
    title, bounds = _spaced_text_layer(
        font,
        fill=(4, 5, 6, 255),
        stroke_fill=(232, 235, 238, 255),
        stroke_width=3 * SCALE,
    )

    alpha = title.getchannel("A")
    glow_wide = alpha.filter(ImageFilter.GaussianBlur(8 * SCALE))
    glow_tight = alpha.filter(ImageFilter.GaussianBlur(3 * SCALE))
    glow = Image.new("RGBA", title.size, (220, 229, 238, 0))
    glow.putalpha(glow_wide.point(lambda value: round(value * 0.34)))
    tight = Image.new("RGBA", title.size, (242, 246, 250, 0))
    tight.putalpha(glow_tight.point(lambda value: round(value * 0.42)))

    rune_line = Image.new("RGBA", title.size, (0, 0, 0, 0))
    rune_draw = ImageDraw.Draw(rune_line)
    line_y = (bounds[1] + bounds[3]) // 2 + 3 * SCALE
    rune_draw.line(
        (bounds[0] + 9 * SCALE, line_y, bounds[2] - 9 * SCALE, line_y),
        fill=(218, 224, 230, 230),
        width=SCALE,
    )
    rune_line.putalpha(Image.composite(rune_line.getchannel("A"), Image.new("L", title.size), alpha))

    composition = Image.new("RGBA", title.size, (0, 0, 0, 0))
    composition = Image.alpha_composite(composition, glow)
    composition = Image.alpha_composite(composition, tight)
    composition = Image.alpha_composite(composition, title)
    composition = Image.alpha_composite(composition, rune_line)
    composition = composition.resize(
        (composition.width // SCALE, composition.height // SCALE),
        Image.Resampling.LANCZOS,
    )

    target_x = round(TITLE_CENTER[0] - composition.width / 2)
    target_y = round(TITLE_CENTER[1] - composition.height / 2)
    result = base.copy()
    result.alpha_composite(composition, (target_x, target_y))
    result.paste(base.crop(SYMBOL_REGION), SYMBOL_REGION[:2])
    return result


def render_title(source_path: Path, font_path: Path, output_path: Path) -> Path:
    source = source_path.resolve(strict=True)
    font = font_path.resolve(strict=True)
    output = output_path.resolve()
    if output == source:
        raise ValueError("output must not overwrite the source image")
    source_hash = _sha256_file(source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError(
            f"unexpected source SHA-256: {source_hash}; expected {EXPECTED_SOURCE_SHA256}"
        )
    image = Image.open(source).convert("RGBA")
    if image.size != EXPECTED_SIZE:
        raise ValueError(f"unexpected source dimensions: {image.size}; expected {EXPECTED_SIZE}")
    output.parent.mkdir(parents=True, exist_ok=True)
    localized = _draw_localized_title(_clean_title_region(image), font)
    localized.save(output, format="PNG", optimize=False, compress_level=9)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministically localize the fixed Hello Underworld title artwork."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--font", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = render_title(args.source, args.font, args.output)
    print(f"Localized title: {output}")
    print(f"SHA-256: {_sha256_file(output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
