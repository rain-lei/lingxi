#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define LXFF_HEADER_BYTES 64u
#define LXFF_ENTRY_BYTES 64u
#define LXFF_GLYPH_BYTES 12u
#define LXFF_FONT_COUNT 4u
#define LXFF_MAX_FILE_BYTES (8u * 1024u * 1024u)
#define LXFF_MAX_CACHE_BYTES (1200u * 1024u)
/* Tone order is shared by the font manifest, UI and TF storage. */
typedef struct {
    uint8_t tone, pixel_size, line_height, alpha_bits;
    uint32_t glyph_count, glyph_offset, glyph_bytes, alpha_offset, alpha_bytes, crc32;
    char name[33];
} lxff_font_t;
typedef struct { uint32_t total_bytes; uint8_t sha256[32]; lxff_font_t fonts[4]; } lxff_info_t;
typedef struct { const uint8_t *glyphs, *alpha; lxff_font_t font; } lxff_view_t;
typedef struct {
    uint32_t codepoint, offset;
    uint8_t width, height, advance;
    int8_t bearing_x;
} lxff_glyph_t;
bool lxff_parse(const uint8_t header[64], const uint8_t *index, size_t index_bytes,
                uint32_t file_bytes, lxff_info_t *out);
bool lxff_validate_view(const lxff_view_t *view);
bool lxff_glyph(const lxff_view_t *view, uint32_t codepoint, lxff_glyph_t *out);
uint32_t lxff_crc32_update(uint32_t crc, const uint8_t *data, size_t bytes);
unsigned lxff_tone_id(const char *tone);
