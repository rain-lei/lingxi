/* Generated native 20 px Noto Sans SC / Resource Han Rounded reply font.
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
/* Per-tone fonts are optional TF assets; no-card uses the Noto fallback. */
extern const size_t ui_reply_font_alpha_bytes;

/* Sorted binary search. Unknown code points return the ASCII '?' glyph. */
const ui_reply_glyph_t *ui_reply_glyph(uint32_t codepoint);
