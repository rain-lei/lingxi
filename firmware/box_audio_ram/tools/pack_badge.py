"""Encode the official emblem as a separate UI layer, preserving the source art."""
from pathlib import Path
import json
from PIL import Image
root = Path(__file__).resolve().parents[1]
image = Image.open(root / 'assets/mascot-v3/dlut-badge.png').convert('RGBA').resize((26, 26), Image.Resampling.LANCZOS)
colors, alpha = [], []
for r, g, b, a in image.getdata():
    colors.append((r >> 3) << 11 | (g >> 2) << 5 | b >> 3)
    alpha.append(a)
report = json.loads((root / 'assets/mascot-v3/pack-report.json').read_text(encoding='utf8'))
left, top, right, bottom = report['common_crop_bounds']
width, height = report['scaled_art_size']
ox, oy = report['common_origin']
points = [(274,368),(268,365),(263,369),(279,356),(254,347),(256,350)]
centers = [(round((x-left)*width/(right-left)+ox), round((y-top)*height/(bottom-top)+oy)) for x,y in points]
(root / 'main/ui_badge.h').write_text(
    '#pragma once\n#include <stdint.h>\n#define UI_BADGE_SIZE 26\n'
    'extern const uint16_t ui_badge_rgb565[676];\nextern const uint8_t ui_badge_alpha[676];\n'
    'extern const uint8_t ui_kangaroo_badge_centers[6][2];\n', encoding='utf8')
(root / 'main/ui_badge.c').write_text(
    '/* Official DLUT emblem UI layer; see assets/mascot-v3/SOURCES.md. */\n#include "ui_badge.h"\n'
    'const uint16_t ui_badge_rgb565[676]={' + ','.join(map(str, colors)) + '};\n'
    'const uint8_t ui_badge_alpha[676]={' + ','.join(map(str, alpha)) + '};\n'
    'const uint8_t ui_kangaroo_badge_centers[6][2]={' + ','.join('{%d,%d}' % p for p in centers) + '};\n', encoding='utf8')
print('Official emblem layer encoded: 26 x 26 RGB565 + alpha8.')
