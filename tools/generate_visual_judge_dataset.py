from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SCHEMA_VERSION = "hanengine.visual-judge-benchmark/v1"
GENERATOR_VERSION = "hanengine.visual-judge-controlled/v2"
CANVAS = (960, 540)
CHROME_TEXT = {
    "en": {
        "title": "MOONLIGHT ARCHIVE",
        "chapter": "CHAPTER 04",
        "terminal": "Archive terminal",
        "continue": "CONTINUE",
        "slot": "SLOT",
    },
    "zh": {
        "title": "月光档案",
        "chapter": "第四章",
        "terminal": "档案终端",
        "continue": "继续",
        "slot": "存档",
    },
}
CATEGORIES = (
    ("normal_control", None),
    ("residual_english", "residual_untranslated_text"),
    ("clipped_text", "clipped"),
    ("overflow", "overflow"),
    ("overlap", "overlap"),
    ("missing_glyphs", "missing_glyphs"),
    ("garbled_text", "garbled_text"),
    ("bad_wrapping", "bad_wrapping"),
    ("style_readability", "style_readability"),
)
FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/msyh.ttc"),
    Path("C:/Windows/Fonts/simhei.ttf"),
    Path("C:/Windows/Fonts/simsun.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)


def _font_path() -> Path:
    for candidate in FONT_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise RuntimeError("no supported deterministic font was found")


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=size)


def _theme(variant: int) -> dict[str, tuple[int, int, int]]:
    return (
        {"background": (27, 31, 38), "panel": (246, 247, 249), "accent": (190, 67, 57)},
        {"background": (221, 230, 224), "panel": (255, 255, 255), "accent": (34, 111, 79)},
        {"background": (37, 42, 52), "panel": (235, 238, 242), "accent": (177, 111, 33)},
        {"background": (228, 225, 219), "panel": (253, 253, 252), "accent": (61, 91, 133)},
    )[variant - 1]


def _base_scene(font_path: Path, variant: int, language: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    colors = _theme(variant)
    labels = CHROME_TEXT[language]
    image = Image.new("RGB", CANVAS, colors["background"])
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 960, 58), fill=(18, 21, 26))
    draw.text((28, 16), labels["title"], font=_font(font_path, 21), fill=(239, 242, 244))
    draw.rounded_rectangle((62, 94, 898, 472), radius=7, fill=colors["panel"], outline=(194, 200, 205), width=2)
    draw.rectangle((62, 94, 898, 151), fill=(231, 234, 237))
    draw.text((88, 111), labels["chapter"], font=_font(font_path, 19), fill=(84, 91, 98))
    draw.ellipse((827, 108, 845, 126), fill=colors["accent"])
    draw.text((88, 181), labels["terminal"], font=_font(font_path, 31), fill=(39, 44, 49))
    draw.line((88, 229, 872, 229), fill=(216, 220, 223), width=2)
    draw.rounded_rectangle((88, 382, 234, 428), radius=5, fill=colors["accent"])
    draw.text((130, 393), labels["continue"], font=_font(font_path, 18), fill=(255, 255, 255))
    draw.text((88, 444), f"{labels['slot']} {variant:02d}  |  20:4{variant}", font=_font(font_path, 15), fill=(119, 126, 132))
    return image, draw


def _healthy_copy(draw: ImageDraw.ImageDraw, font_path: Path, language: str) -> None:
    if language == "en":
        lines = ("The observatory is quiet tonight.", "Open the recovered record before dawn.")
    else:
        lines = ("今晚的观测站格外安静。", "请在黎明前打开已恢复的记录。")
    draw.text((88, 257), lines[0], font=_font(font_path, 23), fill=(55, 61, 67))
    draw.text((88, 303), lines[1], font=_font(font_path, 23), fill=(55, 61, 67))


def _candidate(category: str, font_path: Path, variant: int) -> Image.Image:
    image, draw = _base_scene(font_path, variant, "zh")
    normal = (55, 61, 67)
    if category == "normal_control":
        _healthy_copy(draw, font_path, "zh")
    elif category == "residual_english":
        draw.text((88, 257), "今晚的观测站格外安静。", font=_font(font_path, 23), fill=normal)
        draw.text((88, 303), "Open the recovered record before dawn.", font=_font(font_path, 23), fill=normal)
    elif category == "clipped_text":
        draw.text((88, 257), "今晚的观测站格外安静。", font=_font(font_path, 23), fill=normal)
        layer = Image.new("RGB", (420, 35), (246, 247, 249))
        layer_draw = ImageDraw.Draw(layer)
        layer_draw.text((0, 0), "请在黎明前打开已恢复的记录。", font=_font(font_path, 23), fill=normal)
        image.paste(layer.crop((0, 0, 235 + variant * 12, 35)), (88, 303))
        draw.line((335 + variant * 12, 300, 335 + variant * 12, 340), fill=(190, 67, 57), width=2)
    elif category == "overflow":
        draw.text((88, 257), "今晚的观测站格外安静。", font=_font(font_path, 23), fill=normal)
        draw.text((690, 303), "这段译文已经冲出内容区域之外", font=_font(font_path, 23), fill=(154, 55, 48))
    elif category == "overlap":
        draw.text((88, 267), "今晚的观测站格外安静。", font=_font(font_path, 27), fill=normal)
        draw.text((88, 279 + variant), "请在黎明前打开已恢复的记录。", font=_font(font_path, 27), fill=(85, 56, 53))
    elif category == "missing_glyphs":
        draw.text((88, 257), "今晚的观测站格外安静。", font=_font(font_path, 23), fill=normal)
        draw.text((88, 303), "请在黎明前打开 □□□□ 的记录。", font=_font(font_path, 23), fill=normal)
    elif category == "garbled_text":
        draw.text((88, 257), "今晚的观测站格外安静。", font=_font(font_path, 23), fill=normal)
        draw.text((88, 303), "璇峰湪榛庢槑鍓嶆墦寮€宸叉仮澶嶇殑璁板綍", font=_font(font_path, 23), fill=normal)
    elif category == "bad_wrapping":
        draw.text((88, 249), "今晚的观测站格外安静。", font=_font(font_path, 23), fill=normal)
        draw.multiline_text((88, 287), "请在黎明前打\n开\n已恢复的记录。", font=_font(font_path, 21), fill=normal, spacing=0)
    elif category == "style_readability":
        draw.text((88, 263), "今晚的观测站格外安静。", font=_font(font_path, 12 + variant), fill=(205, 208, 210))
        draw.text((88, 303), "请在黎明前打开已恢复的记录。", font=_font(font_path, 12 + variant), fill=(210, 212, 214))
    else:
        raise ValueError(f"unknown category: {category}")
    return image


def build_dataset(output_root: Path) -> tuple[Path, ...]:
    font_path = _font_path()
    images_root = output_root / "images"
    images_root.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, object]] = []
    written: list[Path] = []
    for category, issue_code in CATEGORIES:
        for variant in range(1, 5):
            sample_id = f"{category}-{variant:02d}"
            reference_path = images_root / f"{sample_id}-reference.png"
            candidate_path = images_root / f"{sample_id}-candidate.png"
            reference, reference_draw = _base_scene(font_path, variant, "en")
            _healthy_copy(reference_draw, font_path, "en")
            candidate = _candidate(category, font_path, variant)
            reference.save(reference_path, format="PNG", optimize=False)
            candidate.save(candidate_path, format="PNG", optimize=False)
            written.extend((reference_path, candidate_path))
            samples.append(
                {
                    "sample_id": sample_id,
                    "reference_image": reference_path.relative_to(output_root).as_posix(),
                    "candidate_image": candidate_path.relative_to(output_root).as_posix(),
                    "expected_defect": issue_code is not None,
                    "expected_issue_codes": [] if issue_code is None else [issue_code],
                }
            )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset": {
            "generator": GENERATOR_VERSION,
            "canvas": list(CANVAS),
            "font": font_path.name,
            "license": "CC0-1.0",
            "category_count": len(CATEGORIES),
            "sample_count": len(samples),
        },
        "samples": samples,
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return (manifest_path, *written)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate HanEngine's controlled visual-judge dataset")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "benchmarks" / "visual_judge_controlled",
    )
    args = parser.parse_args(argv)
    paths = build_dataset(args.output.resolve())
    print(f"Generated {len(paths) - 1} images and {paths[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
