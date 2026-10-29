"""Generate the small OFL Noto Sans SC glyph subset used by the board UI.

python generate_ui_font.py --font <NotoSansSC[wght].ttf>
The full font is only needed when editing the interface copy, not to build IDF.
"""
from pathlib import Path
import argparse
import math
import re
from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--font", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    scene = (root / "main/ui_scene.c").read_text(encoding="utf-8")
    characters = set(chr(i) for i in range(32, 127))
    for literal in re.findall(r'"([^"\n]*)"', scene):
        characters.update(ch for ch in literal if ord(ch) >= 128)
    glyphs, data = [], bytearray()
    for size in (10, 12, 14, 18, 20):
        font = ImageFont.truetype(str(args.font), size * 3)
        font.set_variation_by_axes([600 if size >= 18 else 450])
        for char in sorted(characters):
            advance = max(1, round(font.getlength(char) / 3))
            width, height = advance + 2, math.ceil(size * 1.3)
            image = Image.new("L", (width * 3, height * 3))
            ImageDraw.Draw(image).text((0, size * 3), char, font=font, fill=255, anchor="ls")
            values = list(image.resize((width, height), Image.Resampling.LANCZOS).getdata())
            values = [min(15, (v + 8) // 17) for v in values]
            offset = len(data)
            for i in range(0, len(values), 2):
                data.append((values[i] << 4) | (values[i + 1] if i + 1 < len(values) else 0))
            glyphs.append((ord(char), offset, size, width, height, advance))
    output = ['/* Generated Noto Sans SC subset, SIL OFL 1.1; see assets/NotoSansSC-OFL.txt. */',
              '#include "ui_font.h"', 'const ui_glyph_t ui_glyphs[] = {']
    output.extend('    {%d, %d, %d, %d, %d, %d},' % g for g in glyphs)
    output.extend(['};', 'const size_t ui_glyph_count = sizeof(ui_glyphs) / sizeof(ui_glyphs[0]);',
                   'const uint8_t ui_font_alpha[] = {'])
    output.extend('    ' + ','.join('0x%02x' % v for v in data[i:i + 24]) + ','
                  for i in range(0, len(data), 24))
    output.append('};\n')
    (root / 'main/ui_font.c').write_text('\n'.join(output), encoding='utf-8')
    print(f'{len(glyphs)} glyphs, {len(data)} bytes of alpha data')


if __name__ == '__main__':
    main()
