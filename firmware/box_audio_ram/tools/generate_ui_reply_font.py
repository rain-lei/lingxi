"""Generate the LCD's native 20 px, antialiased conversation reply font.

Requires Pillow, OFL-licensed Noto Sans SC and Resource Han Rounded CN fonts. It rasterizes
the outlines directly at 20 px; it never scales a smaller bitmap. The subset
contains every GB2312 Han character, printable ASCII and common CJK punctuation.

    python generate_ui_reply_font.py --font <NotoSansSC.ttf> --rounded-font <Rounded.ttf>

Each glyph has a 26 px line box. Pixels are continuous row-major, 2-bit alpha
(0, 85, 170, 255), packed most-significant pair first without row padding.
"""
from __future__ import annotations

import argparse
import hashlib
import math
from pathlib import Path
import unicodedata

from PIL import Image, ImageDraw, ImageFont


FONT_SIZE = 20
LINE_HEIGHT = 26
BASELINE = 20
WEIGHT = 600
HAN_COUNT = 6763


def gb2312_han_codes() -> set[int]:
    codes: set[int] = set()
    for high in range(0xB0, 0xF8):
        for low in range(0xA1, 0xFF):
            try:
                character = bytes((high, low)).decode("gb2312")
            except UnicodeDecodeError:
                continue
            code = ord(character)
            if not 0x4E00 <= code <= 0x9FFF:
                raise ValueError(f"Unexpected GB2312 Han character U+{code:04X}")
            codes.add(code)
    if len(codes) != HAN_COUNT:
        raise ValueError(f"Expected {HAN_COUNT} GB2312 Han glyphs, got {len(codes)}")
    return codes


def character_codes() -> list[int]:
    codes = gb2312_han_codes()
    codes.update(range(0x20, 0x7F))
    # Include assigned punctuation and marks in the CJK/fullwidth blocks. Noto
    # Sans SC covers these; unassigned positions must not produce .notdef boxes.
    for first, last in ((0x3000, 0x303F), (0xFF01, 0xFF65)):
        codes.update(code for code in range(first, last + 1)
                     if unicodedata.category(chr(code)) != "Cn"
                     and not unicodedata.category(chr(code)).startswith("M"))
    codes.update(map(ord, "·—–‘’“”…℃°±×÷￥"))
    # These two vertical Kana repeat marks deliberately occupy two lines;
    # they are not horizontal conversation punctuation.
    codes.difference_update((0x3031, 0x3032))
    return sorted(codes)


def native_font(path: Path, require_weight_axis: bool = False) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(path), FONT_SIZE)
    try:
        axes = font.get_variation_axes()
    except OSError:
        axes = []
    if not axes and require_weight_axis:
        raise ValueError("Use the variable Noto Sans SC source to select weight 600")
    if not axes:
        return font
    values = [axis["default"] for axis in axes]
    found_weight = False
    for index, axis in enumerate(axes):
        name = axis["name"]
        if isinstance(name, bytes):
            name = name.decode("ascii", errors="replace")
        if name.lower() == "weight":
            if not axis["minimum"] <= WEIGHT <= axis["maximum"]:
                raise ValueError("The source font does not support weight 600")
            values[index] = WEIGHT
            found_weight = True
    if not found_weight:
        raise ValueError("The source font has no weight axis")
    font.set_variation_by_axes(values)
    return font


def glyph_metrics(fonts: list[ImageFont.FreeTypeFont], code: int) -> tuple[int, int, int]:
    character = chr(code)
    fullwidth = (0x4E00 <= code <= 0x9FFF or 0x3000 <= code <= 0x303F
                 or 0xFF01 <= code <= 0xFF60)
    lengths = [font.getlength(character) for font in fonts]
    advance = FONT_SIZE if fullwidth else max(1, max(round(length) for length in lengths))
    # Preserve outline overhang rather than clipping the odd 21 px Han glyph
    # into its 20 px advance. The shared union keeps both fonts' offsets valid.
    bounds = [font.getbbox(character, anchor="ls") for font in fonts]
    bearing_x = min(bound[0] for bound in bounds)
    width = max(1, max(bound[2] for bound in bounds) - bearing_x)
    return width, advance, bearing_x


def glyph_raster(font: ImageFont.FreeTypeFont, code: int,
                 metrics: tuple[int, int, int] | None = None) -> tuple[Image.Image, int]:
    character = chr(code)
    width, advance, bearing_x = metrics or glyph_metrics([font], code)
    raster = Image.new("L", (width, LINE_HEIGHT), 0)
    ImageDraw.Draw(raster).text((-bearing_x, BASELINE), character, font=font,
                                fill=255, anchor="ls")
    if not character.isspace() and not raster.getbbox():
        raise ValueError(f"Empty glyph U+{code:04X}")
    # Quantizing at native size preserves FreeType's outline antialiasing.
    raster = raster.point(lambda value: min(3, (value + 42) // 85) * 85)
    return raster, advance


def pack_alpha(raster: Image.Image) -> bytes:
    pixel_reader = getattr(raster, "get_flattened_data", raster.getdata)
    values = list(pixel_reader())
    packed = bytearray((len(values) + 3) // 4)
    for index, value in enumerate(values):
        packed[index // 4] |= (value // 85) << (6 - (index % 4) * 2)
    # Independent unpacking validates the documented layout across row edges.
    if values != [((packed[index // 4] >> (6 - (index % 4) * 2)) & 3) * 85
                  for index in range(len(values))]:
        raise ValueError("2-bit alpha packing failed its round-trip check")
    return bytes(packed)


HEADER = '''/* Generated native 20 px Noto Sans SC / Resource Han Rounded reply font.
 * Both source fonts are licensed under SIL OFL 1.1.
 * See assets/NotoSansSC-OFL.txt and assets/ResourceHanRounded-OFL.txt.
 * Regenerate with tools/generate_ui_reply_font.py.
 */
#pragma once
#include <stddef.h>
#include <stdint.h>

#define UI_REPLY_FONT_SIZE 20
#define UI_REPLY_HEIGHT 26
#define UI_REPLY_ALPHA_BITS 2

typedef struct {
    uint32_t codepoint;
    uint32_t offset;
    uint8_t width;
    uint8_t height;
    uint8_t advance;
    int8_t bearing_x;
} ui_reply_glyph_t;

/* Continuous row-major alpha: pixel n is byte n/4, shift 6-(n%4)*2.
 * Values 0..3 correspond to alpha 0, 85, 170, 255. No row padding.
 */
extern const ui_reply_glyph_t ui_reply_glyphs[];
extern const size_t ui_reply_glyph_count;
extern const uint8_t ui_reply_font_alpha[];
extern const uint8_t ui_reply_font_rounded_alpha[];
extern const size_t ui_reply_font_alpha_bytes;

/* Sorted binary search. Unknown code points return the ASCII '?' glyph. */
const ui_reply_glyph_t *ui_reply_glyph(uint32_t codepoint);
'''


def write_preview(path: Path, fonts: list[ImageFont.FreeTypeFont]) -> None:
    lines = ["你好呀，我是蓝蓝，很高兴遇见你！", "今天有点累吗？慢慢说，我听着。",
             "先喝口水，再一起想个小办法。", "大连理工大学 · LingXi 2026", "。！？：；，、（）【】《》“”…—"]
    preview = Image.new("RGB", (360 * len(fonts), 26 * len(lines) + 50), "#eff9ff")
    draw = ImageDraw.Draw(preview)
    for font_number, font in enumerate(fonts):
        draw.text((font_number * 360 + 12, 8), ("Noto Sans SC", "Resource Han Rounded")[font_number],
                  fill="#153b53")
        for line_number, line in enumerate(lines):
            x, y = font_number * 360 + 12, 36 + line_number * LINE_HEIGHT
            for character in line:
                metrics = glyph_metrics(fonts, ord(character))
                raster, advance = glyph_raster(font, ord(character), metrics)
                preview.paste("#153b53", (x + metrics[2], y), raster)
                x += advance
    path.parent.mkdir(parents=True, exist_ok=True)
    preview.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--rounded-font", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parents[1] / "main")
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--single-fallback", action="store_true",
                        help="Embed only Noto; four per-tone styles are supplied by the TF font pack")
    args = parser.parse_args()
    if not args.font.is_file():
        parser.error(f"Source font does not exist: {args.font}")
    if not args.rounded_font.is_file():
        parser.error(f"Rounded source font does not exist: {args.rounded_font}")
    fonts = [native_font(args.font, require_weight_axis=True), native_font(args.rounded_font)]
    codes = character_codes()
    alpha_sets = [bytearray(), bytearray()]
    glyphs = []
    for code in codes:
        metrics = glyph_metrics(fonts, code)
        for font_number, font in enumerate(fonts):
            raster, advance = glyph_raster(font, code, metrics)
            if font_number == 0:
                glyphs.append((code, len(alpha_sets[0]), raster.width, raster.height, advance, metrics[2]))
            alpha_sets[font_number].extend(pack_alpha(raster))
    if len(alpha_sets[0]) != len(alpha_sets[1]):
        raise ValueError("The two fonts must use the same glyph offsets")
    if any(left >= right for left, right in zip(codes, codes[1:])):
        raise ValueError("Glyph codes are not strictly sorted")
    if not set(range(0x20, 0x7F)).issubset(codes):
        raise ValueError("Missing printable ASCII glyphs")
    digest = hashlib.sha256(args.font.read_bytes()).hexdigest()
    rounded_digest = hashlib.sha256(args.rounded_font.read_bytes()).hexdigest()
    output = [
        "/* Generated by tools/generate_ui_reply_font.py; do not edit manually.",
        " * Native 20 px Noto Sans SC / Resource Han Rounded CN; SIL OFL 1.1.",
        " * Noto weight 600; Rounded uses the native Medium source outlines.",
        " * See assets/NotoSansSC-OFL.txt and assets/ResourceHanRounded-OFL.txt.",
        f" * Noto source font SHA-256: {digest}",
        f" * Rounded source font SHA-256: {rounded_digest}",
        f" * {len(codes)} sorted glyphs; {len(alpha_sets[0])} bytes per 2-bit alpha font.",
        " */", '#include "ui_reply_font.h"', "",
        "const ui_reply_glyph_t ui_reply_glyphs[] = {",
    ]
    output.extend("    {0x%04x, %d, %d, %d, %d, %d}," % glyph for glyph in glyphs)
    output.extend(["};", "", "const size_t ui_reply_glyph_count =",
                   "    sizeof(ui_reply_glyphs) / sizeof(ui_reply_glyphs[0]);", "",
                   ])
    embedded = [("ui_reply_font_alpha", alpha_sets[0])]
    if not args.single_fallback:
        embedded.append(("ui_reply_font_rounded_alpha", alpha_sets[1]))
    for name, data in embedded:
        output.append(f"const uint8_t {name}[] = {{")
        output.extend("    " + ",".join(f"0x{byte:02x}" for byte in data[i:i + 24]) + ","
                      for i in range(0, len(data), 24))
        output.extend(["};", ""])
    output.extend(["const size_t ui_reply_font_alpha_bytes = sizeof(ui_reply_font_alpha);", "",
                   "const ui_reply_glyph_t *ui_reply_glyph(uint32_t codepoint)", "{",
                   "    size_t left = 0, right = ui_reply_glyph_count;",
                   "    while (left < right) {",
                   "        size_t mid = left + (right - left) / 2;",
                   "        uint32_t code = ui_reply_glyphs[mid].codepoint;",
                   "        if (code == codepoint) return &ui_reply_glyphs[mid];",
                   "        if (code < codepoint) left = mid + 1;",
                   "        else right = mid;", "    }",
                   "    /* ASCII starts at U+0020 and is contiguous. */",
                   "    return &ui_reply_glyphs['?' - ' '];", "}", ""])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    header = HEADER
    if args.single_fallback:
        header = header.replace("extern const uint8_t ui_reply_font_rounded_alpha[];",
                                "/* Per-tone fonts are optional TF assets; no-card uses the Noto fallback. */")
    (args.output_dir / "ui_reply_font.h").write_text(header, encoding="utf-8", newline="\n")
    (args.output_dir / "ui_reply_font.c").write_text("\n".join(output), encoding="utf-8", newline="\n")
    if args.preview:
        write_preview(args.preview, fonts)
    print(f"Generated {len(codes)} glyphs ({HAN_COUNT} GB2312 Han + ASCII/punctuation)")
    print(f"Native {FONT_SIZE} px / Noto weight {WEIGHT}, Rounded native Medium; line height {LINE_HEIGHT}; 2-bit alpha")
    print(f"Bitmap {len(alpha_sets[0]):,} bytes per font; C index {len(glyphs) * 12:,} bytes (12-byte struct)")
    print(f"Noto source SHA-256: {digest}")
    print(f"Rounded source SHA-256: {rounded_digest}")
    print(f"Output: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
