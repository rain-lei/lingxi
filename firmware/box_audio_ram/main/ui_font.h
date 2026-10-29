#pragma once
#include <stdint.h>
#include <stddef.h>
typedef struct {
    uint32_t codepoint;
    uint32_t offset;
    uint8_t size, width, height, advance;
} ui_glyph_t;
extern const ui_glyph_t ui_glyphs[];
extern const size_t ui_glyph_count;
extern const uint8_t ui_font_alpha[];
