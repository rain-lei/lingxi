#include "lxaf_format.h"
#include <string.h>

static uint16_t u16(const uint8_t *p) { return p[0] | (uint16_t)p[1] << 8; }
static uint32_t u32(const uint8_t *p)
{ return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static bool zeros(const uint8_t *p, size_t count)
{ for (size_t i = 0; i < count; ++i) if (p[i]) return false; return true; }

bool lxaf_parse(const uint8_t h[64], const uint8_t *index, size_t index_bytes,
                uint32_t file_size, lxaf_info_t *o)
{
    if (!h || !index || !o || memcmp(h, "LXAF", 4) || (u16(h+4) != 1 && u16(h+4) != 2) ||
        u16(h+6) != 64 || u16(h+8) != 128 || u16(h+10) != 128 ||
        u16(h+12) != 1 || u16(h+14) < 1 || u16(h+14) > LXAF_MAX_CLIPS ||
        u32(h+16) != 64 || u32(h+28) || zeros(h+32, 32)) return false;
    uint16_t count = u16(h+14);
    uint32_t data_offset = 64u + count * 32u;
    if (index_bytes != count * 32u || u32(h+20) != data_offset ||
        u32(h+24) != file_size || file_size > LXAF_MAX_FILE_BYTES ||
        file_size <= data_offset) return false;
    memset(o, 0, sizeof(*o));
    o->version = u16(h+4); o->clip_count = count; o->data_offset = data_offset; o->total_size = file_size;
    memcpy(o->sha256, h+32, 32);
    uint64_t identifiers = 0;
    uint64_t bytes_total = 0;
    for (unsigned i = 0; i < count; ++i) {
        const uint8_t *p = index + i * 32u;
        lxaf_clip_t *c = &o->clips[i];
        c->avatar=p[0]; c->state=p[1]; c->flags=u16(p+2); c->frames=u16(p+4);
        c->frame_ms=u16(p+6); c->offset=u32(p+8); c->bytes=u32(p+12); c->crc32=u32(p+16);
        bool packed = (c->flags & LXAF_FLAG_RLE3) != 0;
        if (c->avatar > 4 || c->state >= LXAF_MAX_STATES || (c->flags & ~3u) ||
            (o->version == 1 && (packed || c->state > 5)) ||
            !c->frames || c->frames > LXAF_MAX_FRAMES || c->frame_ms < 40 || c->frame_ms > 1000 ||
            (!packed && c->bytes != c->frames * LXAF_FRAME_BYTES) ||
            (packed && (c->bytes < c->frames * 12u || c->bytes > c->frames * (LXAF_FRAME_BYTES + 128u + 8u))) ||
            c->offset < data_offset ||
            (uint64_t)c->offset + c->bytes > file_size || !zeros(p+20, 12)) return false;
        uint64_t bit = UINT64_C(1) << (c->avatar * LXAF_MAX_STATES + c->state);
        if (identifiers & bit) return false;
        identifiers |= bit;
        for (unsigned j = 0; j < i; ++j) {
            const lxaf_clip_t *other = &o->clips[j];
            if ((uint64_t)c->offset < (uint64_t)other->offset + other->bytes &&
                (uint64_t)other->offset < (uint64_t)c->offset + c->bytes) return false;
        }
        bytes_total += c->bytes;
    }
    return bytes_total == (uint64_t)file_size - data_offset;
}

static bool decode_rle3(const uint8_t *p, size_t bytes, uint8_t *out)
{
    size_t used = 0, produced = 0;
    while (used < bytes) {
        unsigned control = p[used++];
        size_t pixels = (control & 127u) + 1u;
        size_t count = pixels * 3u;
        if (count > LXAF_FRAME_BYTES - produced) return false;
        if (control & 128u) {
            if (bytes - used < 3u) return false;
            if (out) for (size_t i = 0; i < count; i += 3u) memcpy(out + produced + i, p + used, 3u);
            used += 3u;
        } else {
            if (bytes - used < count) return false;
            if (out) memcpy(out + produced, p + used, count);
            used += count;
        }
        produced += count;
    }
    return produced == LXAF_FRAME_BYTES;
}

bool lxaf_validate_rle3(const uint8_t *encoded, size_t bytes)
{ return encoded && decode_rle3(encoded, bytes, NULL); }

static bool frame_stream(const lxaf_clip_t *clip, const uint8_t *payload, size_t bytes,
                          unsigned frame, uint32_t *offset, uint32_t *length)
{
    if (!clip || !payload || bytes != clip->bytes || !clip->frames ||
        clip->frames > LXAF_MAX_FRAMES || frame >= clip->frames) return false;
    if (!(clip->flags & LXAF_FLAG_RLE3)) {
        if (bytes != clip->frames * LXAF_FRAME_BYTES) return false;
        *offset = frame * LXAF_FRAME_BYTES; *length = LXAF_FRAME_BYTES;
        return true;
    }
    size_t directory = clip->frames * 8u;
    if (bytes < directory) return false;
    *offset = u32(payload + frame * 8u); *length = u32(payload + frame * 8u + 4u);
    return *length && *offset >= directory && *offset <= bytes && *length <= bytes - *offset;
}

bool lxaf_validate_clip(const lxaf_clip_t *clip, const uint8_t *payload, size_t bytes)
{
    if (!clip || !payload || bytes != clip->bytes) return false;
    if (!(clip->flags & LXAF_FLAG_RLE3)) return bytes == clip->frames * LXAF_FRAME_BYTES;
    uint32_t expected = clip->frames * 8u;
    for (unsigned i = 0; i < clip->frames; ++i) {
        uint32_t offset, length;
        if (!frame_stream(clip, payload, bytes, i, &offset, &length) || offset != expected ||
            !decode_rle3(payload + offset, length, NULL)) return false;
        expected += length;
    }
    return expected == bytes;
}

bool lxaf_decode_frame(const lxaf_clip_t *clip, const uint8_t *payload, size_t bytes,
                       unsigned frame, uint8_t *output, size_t output_bytes)
{
    uint32_t offset, length;
    if (!output || output_bytes < LXAF_FRAME_BYTES ||
        !frame_stream(clip, payload, bytes, frame, &offset, &length)) return false;
    if (clip->flags & LXAF_FLAG_RLE3) return decode_rle3(payload + offset, length, output);
    memcpy(output, payload + offset, LXAF_FRAME_BYTES);
    return true;
}

uint32_t lxaf_crc32_update(uint32_t crc, const uint8_t *p, size_t count)
{
    /* A small immutable nibble table reduces TF verification/cache warmup
       work without allocating RAM or changing the portable CRC convention. */
    static const uint32_t nibble[16]={
        0x00000000u,0x1db71064u,0x3b6e20c8u,0x26d930acu,
        0x76dc4190u,0x6b6b51f4u,0x4db26158u,0x5005713cu,
        0xedb88320u,0xf00f9344u,0xd6d6a3e8u,0xcb61b38cu,
        0x9b64c2b0u,0x86d3d2d4u,0xa00ae278u,0xbdbdf21cu
    };
    while (count--) {
        crc ^= *p++;
        crc=(crc>>4)^nibble[crc&15u];
        crc=(crc>>4)^nibble[crc&15u];
    }
    return crc;
}
