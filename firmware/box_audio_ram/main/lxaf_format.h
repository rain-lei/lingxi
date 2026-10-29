#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define LXAF_HEADER_BYTES 64u
#define LXAF_INDEX_BYTES 32u
#define LXAF_MAX_CLIPS 64u
#define LXAF_FRAME_BYTES (128u * 128u * 3u)
#define LXAF_MAX_FILE_BYTES (256u * 1024u * 1024u)
#define LXAF_MAX_FRAMES 96u
#define LXAF_FLAG_LOOP 1u
#define LXAF_FLAG_RLE3 2u
#define LXAF_MAX_STATES 12u

typedef struct {
    uint8_t avatar, state;
    uint16_t flags, frames, frame_ms;
    uint32_t offset, bytes, crc32;
} lxaf_clip_t;
typedef struct {
    uint16_t version, clip_count;
    uint32_t data_offset, total_size;
    uint8_t sha256[32];
    lxaf_clip_t clips[LXAF_MAX_CLIPS];
} lxaf_info_t;

/* Portable, alignment-independent parser. Hash and payload CRC are checked by
   the storage adapter before any frame becomes visible. */
bool lxaf_parse(const uint8_t header[LXAF_HEADER_BYTES], const uint8_t *index,
                size_t index_bytes, uint32_t file_size, lxaf_info_t *output);
/* RLE3 v2 payload: frames x {LE32 relative offset, LE32 encoded bytes},
   followed by contiguous frame streams. Packet low seven bits + 1 is the
   pixel count. Bit 7 repeats one RGB565LE+alpha pixel, otherwise pixels are
   literal. Every source/output bound and the exact decoded size is checked. */
bool lxaf_validate_clip(const lxaf_clip_t *clip, const uint8_t *payload, size_t bytes);
bool lxaf_decode_frame(const lxaf_clip_t *clip, const uint8_t *payload, size_t bytes,
                       unsigned frame, uint8_t *output, size_t output_bytes);
bool lxaf_validate_rle3(const uint8_t *encoded, size_t bytes);
uint32_t lxaf_crc32_update(uint32_t state, const uint8_t *bytes, size_t length);
