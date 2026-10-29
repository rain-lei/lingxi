/* Xiao Xi: pre-rendered 3D companion sprites, embedded without a font/image card. */
#include "ui_scene.h"
#include "ui_font.h"
#include "ui_reply_font.h"
#include "ui_mascot.h"
#include "ui_kangaroo.h"
#include "ui_badge.h"
#include "ui_cjk.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

typedef struct { uint16_t *p; ui_rect_t clip; } canvas_t;
typedef uint32_t color_t;
static const color_t INK = 0x293957, MUTED = 0x7B879C;
static const color_t ACCENT = 0x4169B4, PAPER = 0xFFFFFF;
static const uint8_t *external_frame;
static const lxff_view_t *external_font;
void ui_scene_external_frame(const uint8_t *frame) { external_frame = frame; }
void ui_scene_external_font(const lxff_view_t *font) { external_font = font; }
static const char *companion_name(const ui_model_t *m)
{
    static const char *names[] = {"蓝蓝", "小犀", "奶泡", "团团", "芽芽"};
    return names[(external_frame && m->avatar <= 4) ? m->avatar : m->avatar == 1 ? 1 : 0];
}

static int maximum(int a, int b) { return a > b ? a : b; }
static int minimum(int a, int b) { return a < b ? a : b; }
static float clamp(float x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
static uint16_t rgb565(color_t c)
{ return ((c >> 8) & 0xf800) | ((c >> 5) & 0x07e0) | ((c >> 3) & 0x001f); }
static color_t mix(color_t a, color_t b, float t)
{
    t = clamp(t);
    unsigned r = ((a >> 16) & 255) * (1 - t) + ((b >> 16) & 255) * t;
    unsigned g = ((a >> 8) & 255) * (1 - t) + ((b >> 8) & 255) * t;
    unsigned bl = (a & 255) * (1 - t) + (b & 255) * t;
    return (r << 16) | (g << 8) | bl;
}
static void pixel(canvas_t *c, int x, int y, color_t color, float alpha)
{
    if (x < c->clip.x || x >= c->clip.x + c->clip.w ||
            y < c->clip.y || y >= c->clip.y + c->clip.h) return;
    uint16_t *p = &c->p[y * UI_WIDTH + x];
    if (alpha < 0.99f) {
        color_t previous = (((*p >> 11) * 255 / 31) << 16) |
                          ((((*p >> 5) & 63) * 255 / 63) << 8) |
                          ((*p & 31) * 255 / 31);
        color = mix(previous, color, alpha);
    }
    *p = rgb565(color);
}
static void rect(canvas_t *c, int x, int y, int w, int h, color_t color)
{
    for (int yy = maximum(y, c->clip.y); yy < minimum(y + h, c->clip.y + c->clip.h); yy++)
        for (int xx = maximum(x, c->clip.x); xx < minimum(x + w, c->clip.x + c->clip.w); xx++)
            c->p[yy * UI_WIDTH + xx] = rgb565(color);
}
static void ellipse(canvas_t *c, float x, float y, float rx, float ry,
                    color_t top, color_t bottom, float opacity)
{
    for (int yy = maximum((int)(y - ry - 1), c->clip.y);
         yy < minimum((int)(y + ry + 2), c->clip.y + c->clip.h); yy++) {
        float dy = (yy - y) / ry;
        color_t row = mix(top, bottom, (dy + 1) * .5f);
        for (int xx = maximum((int)(x - rx - 1), c->clip.x);
             xx < minimum((int)(x + rx + 2), c->clip.x + c->clip.w); xx++) {
            float dx = (xx - x) / rx;
            float coverage = clamp((1 - sqrtf(dx * dx + dy * dy)) * minimum(rx, ry) + .5f);
            if (coverage > 0) pixel(c, xx, yy, row, coverage * opacity);
        }
    }
}
static void roundrect(canvas_t *c, int x, int y, int w, int h, int radius, color_t color)
{
    for (int yy = maximum(y, c->clip.y); yy < minimum(y + h, c->clip.y + c->clip.h); yy++) {
        for (int xx = maximum(x, c->clip.x); xx < minimum(x + w, c->clip.x + c->clip.w); xx++) {
            float dx = fmaxf(fmaxf(x + radius - xx, xx - (x + w - radius - 1)), 0);
            float dy = fmaxf(fmaxf(y + radius - yy, yy - (y + h - radius - 1)), 0);
            /* Only rounded corners need a square root; straight spans keep
             * exactly the same coverage without the costly per-pixel sqrt. */
            float distance = dx == 0 ? dy : dy == 0 ? dx : sqrtf(dx * dx + dy * dy);
            float coverage = clamp(radius + .5f - distance);
            if (coverage > 0) pixel(c, xx, yy, color, coverage);
        }
    }
}
static void segment(canvas_t *c, float x0, float y0, float x1, float y1,
                    float width, color_t color)
{
    float vx = x1 - x0, vy = y1 - y0, length = vx * vx + vy * vy;
    for (int y = maximum((int)fminf(y0, y1) - (int)width - 1, c->clip.y);
         y <= minimum((int)fmaxf(y0, y1) + (int)width + 1, c->clip.y + c->clip.h - 1); y++) {
        for (int x = maximum((int)fminf(x0, x1) - (int)width - 1, c->clip.x);
             x <= minimum((int)fmaxf(x0, x1) + (int)width + 1, c->clip.x + c->clip.w - 1); x++) {
            float t = length ? clamp(((x - x0) * vx + (y - y0) * vy) / length) : 0;
            float dx = x - x0 - t * vx, dy = y - y0 - t * vy;
            float a = clamp(width * .5f + .5f - sqrtf(dx * dx + dy * dy));
            if (a > 0) pixel(c, x, y, color, a);
        }
    }
}
static uint32_t next_character(const char **p)
{
    const unsigned char *s = (const unsigned char *)*p;
    uint32_t result;
    if (*s < 128) { result = *s; *p += 1; }
    else if ((*s & 0xe0) == 0xc0 && s[1]) {
        result = ((s[0] & 31) << 6) | (s[1] & 63); *p += 2;
    } else if ((*s & 0xf0) == 0xe0 && s[1] && s[2]) {
        result = ((s[0] & 15) << 12) | ((s[1] & 63) << 6) | (s[2] & 63); *p += 3;
    } else { result = '?'; *p += 1; }
    return result;
}
static const ui_glyph_t *glyph(uint32_t code, int size)
{
    /* Sorted by size then codepoint, so no scanning hundreds of glyphs per frame. */
    size_t lo = 0, hi = ui_glyph_count;
    while (lo < hi) {
        size_t mid = (lo + hi) / 2;
        const ui_glyph_t *g = &ui_glyphs[mid];
        if (g->size < size || (g->size == size && g->codepoint < code)) lo = mid + 1;
        else hi = mid;
    }
    if (lo < ui_glyph_count && ui_glyphs[lo].size == size && ui_glyphs[lo].codepoint == code)
        return &ui_glyphs[lo];
    return NULL;
}
static int cjk_index(uint32_t code)
{
    size_t lo = 0, hi = ui_cjk_count;
    while (lo < hi) {
        size_t mid = (lo + hi) / 2;
        if (ui_cjk_codes[mid] < code) lo = mid + 1; else hi = mid;
    }
    return lo < ui_cjk_count && ui_cjk_codes[lo] == code ? (int)lo : -1;
}
static void text(canvas_t *c, int x, int y, const char *s, int size, color_t color)
{
    if (y >= c->clip.y + c->clip.h) return;
    while (*s) {
        uint32_t code = next_character(&s);
        const ui_glyph_t *g = glyph(code, size);
        int han = !g && size == 12 ? cjk_index(code) : -1;
        if (han >= 0) {
            const uint8_t *bits = ui_cjk_bits + han * UI_CJK_BYTES_PER_GLYPH;
            for (int yy = maximum(0, c->clip.y - y); yy < minimum(UI_CJK_HEIGHT, c->clip.y + c->clip.h - y); yy++)
                for (int xx = maximum(0, c->clip.x - x); xx < minimum(UI_CJK_WIDTH, c->clip.x + c->clip.w - x); xx++) {
                    int bit = yy * UI_CJK_WIDTH + xx;
                    if (bits[bit / 8] & (0x80 >> (bit % 8))) pixel(c, x + xx, y + yy, color, 1);
                }
            x += UI_CJK_WIDTH;
            continue;
        }
        if (!g) g = glyph('?', size);
        if (!g) continue;
        for (int yy = maximum(0, c->clip.y - y);
             yy < minimum(g->height, c->clip.y + c->clip.h - y); yy++) {
            for (int xx = maximum(0, c->clip.x - x);
                 xx < minimum(g->width, c->clip.x + c->clip.w - x); xx++) {
                int index = yy * g->width + xx;
                uint8_t packed = ui_font_alpha[g->offset + index / 2];
                int a = index & 1 ? packed & 15 : packed >> 4;
                if (a) pixel(c, x + xx, y + yy, color, a / 15.f);
            }
        }
        x += g->advance;
    }
}
static void message_text(canvas_t *c, int x, int y, const char *s)
{
    int row = 0, start = x;
    while (*s && row < 3) {
        const char *before = s;
        uint32_t code = next_character(&s);
        const ui_glyph_t *g = glyph(code, 12);
        int advance = g ? g->advance : 12;
        if (code == '\n' || x + advance > start + 126) {
            x = start; y += 17; row++;
            if (row >= 3) break;
            if (code == '\n') continue;
        }
        char character[5] = {0};
        size_t count = s - before;
        if (count > 4) count = 4;
        memcpy(character, before, count);
        text(c, x, y, character, 12, INK);
        x += advance;
    }
}

bool ui_scene_has_reply(const ui_model_t *m)
{
    return m->message[0] && (m->state == UI_PLAYING || m->state == UI_READY
                           || m->state == UI_THINKING);
}

static void reply_character(canvas_t *c, int x, int y, uint32_t code, bool rounded)
{
    const ui_reply_glyph_t *fallback = ui_reply_glyph(code);
    lxff_glyph_t cached;
    /* Every TF style preserves fallback advances, so pagination is stable
       before/after async cache swaps. Raster widths/bearings stay native. */
    bool loaded = lxff_glyph(external_font, code, &cached);
    unsigned width = loaded ? cached.width : fallback->width;
    unsigned height = loaded ? cached.height : fallback->height;
    unsigned offset = loaded ? cached.offset : fallback->offset;
    x += loaded ? cached.bearing_x : fallback->bearing_x;
    (void)rounded;
    const uint8_t *alpha_data = loaded ? external_font->alpha : ui_reply_font_alpha;
    for (int yy = maximum(0, c->clip.y - y);
         yy < minimum(height, c->clip.y + c->clip.h - y); yy++) {
        for (int xx = maximum(0, c->clip.x - x);
             xx < minimum(width, c->clip.x + c->clip.w - x); xx++) {
            int index = yy * width + xx;
            unsigned packed = alpha_data[offset + index / 4];
            unsigned alpha = (packed >> (6 - 2 * (index % 4))) & 3;
            if (alpha) pixel(c, x + xx, y + yy, 0x142239, alpha / 3.f);
        }
    }
}

/* Measure and paint with the same native font advances. A page has fourteen
   full-width Han cells per line and four lines; never shrink an overflowing reply. */
static unsigned reply_layout(canvas_t *c, const char *message, unsigned page, bool rounded)
{
    const char *s = message;
    unsigned row = 0, last_row = 0;
    int x = 20;
    while (*s) {
        uint32_t code = next_character(&s);
        if (code == '\r') continue;
        if (code == '\n') { x = 20; row++; continue; }
        const ui_reply_glyph_t *g = ui_reply_glyph(code);
        if (x + g->advance > 300 && x > 20) { x = 20; row++; }
        if (*s && x > 20) {
            const char *next = s;
            uint32_t after = next_character(&next);
            bool close = after == 0x3002 || after == 0xff0c || after == 0xff01
                      || after == 0xff1f || after == 0x3001 || after == 0xff1b
                      || after == 0xff1a || after == 0xff09 || after == 0x300b
                      || after == 0x3011 || after == 0x300d || after == 0x300f
                      || after == '.' || after == ',' || after == '!' || after == '?';
            bool open = code == '(' || code == 0xff08 || code == 0x300a
                     || code == 0x3010 || code == 0x300c || code == 0x300e;
            if ((close || open) && x + g->advance + ui_reply_glyph(after)->advance > 300) {
                x = 20;
                row++;
            }
        }
        if (c && row / 4 == page) reply_character(c, x, 68 + (row % 4) * 32, code, rounded);
        x += g->advance;
        last_row = row;
    }
    return last_row / 4 + 1;
}

unsigned ui_scene_reply_pages(const ui_model_t *m)
{
    return reply_layout(NULL, m->message, 0, false);
}

static void mini_companion(canvas_t *c, const ui_model_t *m, uint32_t ms)
{
    /* Once playback finishes the pet continues to breathe above still text. */
    bool resting = m->state == UI_READY;
    int x = 12, y = resting ? (int)(sinf(ms * .0016f) * 1.4f) : 0;
    const int size = 54;
    int pose = m->state == UI_PLAYING ? 4 : 0;
    if (resting && (ms % 6500 > 6280 || (ms % 6500 > 5800 && ms % 6500 < 6010)))
        pose = 1;
    for (int yy = maximum(0, c->clip.y - y); yy < minimum(size, c->clip.y + c->clip.h - y); yy++) {
        for (int xx = maximum(0, c->clip.x - x); xx < minimum(size, c->clip.x + c->clip.w - x); xx++) {
            int index = (yy * UI_MASCOT_HEIGHT / size) * UI_MASCOT_WIDTH + xx * UI_MASCOT_WIDTH / size;
            unsigned a = external_frame ? external_frame[index * 3 + 2]
                : m->avatar == 1 ? ui_mascot_alpha[pose][index] : ui_kangaroo_alpha[pose][index];
            if (!a) continue;
            uint16_t f = external_frame ? (uint16_t)external_frame[index * 3] | (uint16_t)external_frame[index * 3 + 1] << 8
                : m->avatar == 1 ? ui_mascot_rgb565[pose][index] : ui_kangaroo_rgb565[pose][index];
            uint16_t *p = &c->p[(y + yy) * UI_WIDTH + x + xx];
            unsigned inverse = 255 - a;
            unsigned r = ((f >> 11) * a + (*p >> 11) * inverse + 127) / 255;
            unsigned g = (((f >> 5) & 63) * a + ((*p >> 5) & 63) * inverse + 127) / 255;
            unsigned b = ((f & 31) * a + (*p & 31) * inverse + 127) / 255;
            *p = (r << 11) | (g << 5) | b;
        }
    }
    if (!external_frame && m->avatar != 1) {
        int bx = x + ui_kangaroo_badge_centers[pose][0] * size / UI_MASCOT_WIDTH - 5;
        int by = y + ui_kangaroo_badge_centers[pose][1] * size / UI_MASCOT_HEIGHT - 5;
        for (int yy = maximum(0, c->clip.y - by); yy < minimum(11, c->clip.y + c->clip.h - by); yy++)
            for (int xx = maximum(0, c->clip.x - bx); xx < minimum(11, c->clip.x + c->clip.w - bx); xx++) {
                int index = (yy * UI_BADGE_SIZE / 11) * UI_BADGE_SIZE + xx * UI_BADGE_SIZE / 11;
                unsigned a = ui_badge_alpha[index];
                if (!a) continue;
                uint16_t f = ui_badge_rgb565[index];
                color_t color = (((f >> 11) * 255 / 31) << 16)
                              | ((((f >> 5) & 63) * 255 / 63) << 8) | ((f & 31) * 255 / 31);
                pixel(c, bx + xx, by + yy, color, a / 255.f);
            }
    }
}

static void readable_reply(canvas_t *c, const ui_model_t *m, uint32_t ms)
{
    mini_companion(c, m, ms);
    text(c, 75, 8, companion_name(m), m->avatar > 1 && external_frame ? 12 : 18, INK);
    text(c, 75, 34, "一只住进口袋的小伙伴", 10, MUTED);
    roundrect(c, 237, 12, 71, 25, 12, 0xDDE9FC);
    text(c, 246, 18, m->state == UI_PLAYING ? "正在回答" : "我在这里", 12, ACCENT);
    rect(c, 12, 54, 296, 1, 0xD8E2F2);
    if (c->clip.y + c->clip.h <= 60) return;
    roundrect(c, 12, 61, 296, 143, 13, PAPER);
    unsigned pages = ui_scene_reply_pages(m);
    unsigned page = m->state == UI_READY
            ? ((ms - m->message_started_ms) / UI_REPLY_PAGE_MS) % pages : 0;
    reply_layout(c, m->message, page, m->rounded_font);
    char controls[80];
    if(m->focus_active)snprintf(controls,sizeof(controls),"专注 %02lu:%02lu · 长按 K2 结束",
        (unsigned long)(m->focus_remaining_seconds/60),(unsigned long)(m->focus_remaining_seconds%60));
    else snprintf(controls,sizeof(controls),"%s",m->showcase_mode?"展示中 · 长按 K1 返回":"BOOT 说话 · K1 互动 · K2 语气");
    text(c, 17, 216, m->state==UI_PLAYING?"轻按 BOOT 停止播放":m->control_notice[0]?m->control_notice:controls,12,0x41516C);
    char counter[24];
    snprintf(counter, sizeof(counter), "%u/%u", page + 1, pages);
    text(c, 270, 216, counter, 12, ACCENT);
}
static void badge(canvas_t *c, int x, int y)
{
    for (int yy = maximum(0, c->clip.y - y); yy < minimum(UI_BADGE_SIZE, c->clip.y + c->clip.h - y); yy++)
        for (int xx = maximum(0, c->clip.x - x); xx < minimum(UI_BADGE_SIZE, c->clip.x + c->clip.w - x); xx++) {
            int index = yy * UI_BADGE_SIZE + xx;
            unsigned a = ui_badge_alpha[index];
            if (!a) continue;
            uint16_t f = ui_badge_rgb565[index], *p = &c->p[(y + yy) * UI_WIDTH + x + xx];
            unsigned inverse = 255 - a;
            unsigned r = ((f >> 11) * a + (*p >> 11) * inverse + 127) / 255;
            unsigned g = (((f >> 5) & 63) * a + ((*p >> 5) & 63) * inverse + 127) / 255;
            unsigned b = ((f & 31) * a + (*p & 31) * inverse + 127) / 255;
            *p = (r << 11) | (g << 5) | b;
        }
}
static void sparkle(canvas_t *c, int x, int y, int r, color_t color)
{
    segment(c, x - r, y, x + r, y, 1.5f, color);
    segment(c, x, y - r, x, y + r, 1.5f, color);
}
static void companion(canvas_t *c, const ui_model_t *m, uint32_t ms)
{
    /* All moving pixels stay inside the existing 0,50,144,126 repaint area.
       Small procedural details reuse the six poses; no frame cache is needed. */
    bool moving = !external_frame && (m->state == UI_READY || m->state == UI_THINKING
               || m->state == UI_STARTING);
    float phase = ms * .0016f;
    float breath = moving ? (sinf(phase) + 1.f) * .5f : .5f;
    float bob = moving ? sinf(phase) * 2.f : 0;
    int x = 10 + (moving ? (int)(sinf(phase * .5f) * 1.2f) : 0);
    int y = 48 + (int)bob;
    int pose = 0;
    if (m->state == UI_LISTENING) pose = 2;
    else if (m->state == UI_PLAYING) pose = 4;
    else if (m->state == UI_ERROR) pose = 5;
    else if (m->state == UI_THINKING) pose = 3;
    else if (m->state == UI_STARTING || ms % 6500 > 6280
             || (ms % 6500 > 5800 && ms % 6500 < 6010)) pose = 1;
    /* The soft grounding light breathes with the pet, unlike a moving panel. */
    ellipse(c, 76, 168, 46 + breath * 2, 6, 0xB8CBF1, 0xD4E2F8, .22f);
    ellipse(c, 76, 170, 38 - bob, 4, 0x829BC9, 0x829BC9, .12f);
    for (int yy = maximum(0, c->clip.y - y);
         yy < minimum(UI_MASCOT_HEIGHT, c->clip.y + c->clip.h - y); yy++) {
        for (int xx = maximum(0, c->clip.x - x);
             xx < minimum(UI_MASCOT_WIDTH, c->clip.x + c->clip.w - x); xx++) {
            int index = yy * UI_MASCOT_WIDTH + xx;
            unsigned alpha = external_frame ? external_frame[index * 3 + 2]
                : m->avatar == 1 ? ui_mascot_alpha[pose][index] : ui_kangaroo_alpha[pose][index];
            if (!alpha) continue;
            uint16_t foreground = external_frame ? (uint16_t)external_frame[index * 3] | (uint16_t)external_frame[index * 3 + 1] << 8
                : m->avatar == 1 ? ui_mascot_rgb565[pose][index] : ui_kangaroo_rgb565[pose][index];
            uint16_t *destination = &c->p[(y + yy) * UI_WIDTH + x + xx];
            if (alpha >= 250) *destination = foreground;
            else {
                uint16_t background = *destination;
                unsigned inverse = 255 - alpha;
                unsigned r = ((foreground >> 11) * alpha + (background >> 11) * inverse + 127) / 255;
                unsigned g = (((foreground >> 5) & 63) * alpha + ((background >> 5) & 63) * inverse + 127) / 255;
                unsigned b = ((foreground & 31) * alpha + (background & 31) * inverse + 127) / 255;
                *destination = (r << 11) | (g << 5) | b;
            }
        }
    }
    if (!external_frame && m->avatar != 1) {
        badge(c, x + ui_kangaroo_badge_centers[pose][0] - UI_BADGE_SIZE / 2,
              y + ui_kangaroo_badge_centers[pose][1] - UI_BADGE_SIZE / 2);
    }
    float shimmer = moving ? (sinf(phase + 1.3f) + 1.f) * .5f : .5f;
    sparkle(c, 22, 75 + (moving ? (int)(sinf(phase * .8f) * 3.f) : 0),
            shimmer > .65f ? 3 : 2, mix(0xDFE7F5, 0xA5BCEA, shimmer));
    sparkle(c, 132, 150 + (moving ? (int)(sinf(phase * .7f + 2) * 3.f) : 0),
            shimmer < .35f ? 3 : 2, mix(0xAFC6ED, 0xE2EAF7, shimmer));
    ellipse(c, 16, 119 + (moving ? (int)(sinf(phase * .6f) * 5.f) : 0),
            1.3f, 1.3f, 0xBACBEB, 0xBACBEB, .7f);
    if (m->state == UI_THINKING) {
        roundrect(c, 105, 57, 32, 18, 8, PAPER);
        ellipse(c, 106, 78, 2, 2, PAPER, PAPER, 1);
        for (int i = 0; i < 3; i++) {
            float pulse = (sinf(ms * .005f - i * 1.1f) + 1.f) * .5f;
            ellipse(c, 113 + i * 8, 66, 1.5f + pulse * .5f, 1.5f + pulse * .5f,
                    mix(0xCDD9EE, ACCENT, pulse), mix(0xCDD9EE, ACCENT, pulse), 1);
        }
    } else if (m->state == UI_LISTENING) {
        /* A still listening cue avoids repaints competing with microphone DMA. */
        segment(c, 123, 78, 127, 82, 1.5f, 0x9FB8E2);
        segment(c, 127, 82, 123, 86, 1.5f, 0x9FB8E2);
        segment(c, 130, 74, 137, 82, 1.5f, 0xC5D4EE);
        segment(c, 137, 82, 130, 90, 1.5f, 0xC5D4EE);
    }
    if (m->state == UI_PLAYING) {
        text(c, 131, 82, "♪", 14, ACCENT);
    }
}
static void action(canvas_t *c, const ui_model_t *m)
{
    char counter[32];
    color_t bg = m->state == UI_ERROR ? 0xAD645D : ACCENT;
    roundrect(c, 16, 183, 288, 32, 12, bg);
    if(m->state==UI_READY && m->control_notice[0]){
        text(c,27,192,m->control_notice,12,PAPER);
    }else if(m->state==UI_READY && m->focus_active){
        snprintf(counter,sizeof(counter),"专注 %02lu:%02lu",(unsigned long)(m->focus_remaining_seconds/60),
            (unsigned long)(m->focus_remaining_seconds%60));
        text(c,29,192,counter,12,PAPER);text(c,218,193,"BOOT 说话",12,0xDCEAFF);
    }else if(m->state==UI_READY && m->showcase_mode){
        text(c,29,192,"展示模式",12,PAPER);text(c,176,193,"长按 K1 回到陪伴",12,0xDCEAFF);
    }else if (m->state == UI_LISTENING || m->state == UI_PLAYING) {
        for (int i = 0; i < 18; i++) {
            int h = 3 + m->levels[i] * 17 / 255;
            roundrect(c, 30 + i * 5, 199 - h / 2, 3, h, 1, 0xDCEAFF);
        }
        snprintf(counter, sizeof(counter), "%u.%u / %u.%us",
                 (unsigned)(m->elapsed_ms / 1000), (unsigned)(m->elapsed_ms / 100 % 10),
                 (unsigned)(m->duration_ms / 1000), (unsigned)(m->duration_ms / 100 % 10));
        text(c, 190, 191, counter, 12, PAPER);
    } else if (m->state == UI_ERROR) {
        text(c, 29, 190, !strcmp(m->detail, "Conversation")
             ? "按住BOOT说话再试" : "请记录提示，重启后再试", 14, PAPER);
    } else if (m->state == UI_STARTING) {
        text(c, 29, 190, "正在准备麦克风…", 14, PAPER);
    } else if (m->state == UI_THINKING) {
        text(c, 29, 190, "正在认真想怎么回应你…", 14, PAPER);
    } else if (m->provisioning) {
        text(c, 29, 190, "配网：192.168.4.1", 14, PAPER);
    } else {
        roundrect(c, 29, 191, 9, 12, 4, 0xDCEAFF);
        segment(c, 26, 198, 26, 202, 1.2f, PAPER);
        segment(c, 41, 198, 41, 202, 1.2f, PAPER);
        segment(c, 27, 203, 40, 203, 1.2f, PAPER);
        segment(c, 34, 204, 34, 207, 1.2f, PAPER);
        text(c, 52, 190, "按住 BOOT 说话", 14, PAPER);
        text(c, 239, 193, "松开发送", 10, 0xDCEAFF);
    }
}

void ui_scene_draw(uint16_t *pixels, ui_rect_t region, const ui_model_t *m, uint32_t ms)
{
    canvas_t c = {.p = pixels, .clip = {
        maximum(region.x, 0), maximum(region.y, 0), 0, 0}};
    c.clip.w = minimum(region.x + region.w, UI_WIDTH) - c.clip.x;
    c.clip.h = minimum(region.y + region.h, UI_HEIGHT) - c.clip.y;
    for (int y = c.clip.y; y < c.clip.y + c.clip.h; y++)
        rect(&c, c.clip.x, y, c.clip.w, 1, mix(0xF5F8FF, 0xEAF0FA, y / 240.f));
    if (ui_scene_has_reply(m)) {
        if (c.clip.x + c.clip.w <= 70 && c.clip.y + c.clip.h <= 54) {
            mini_companion(&c, m, ms);
            return;
        }
        readable_reply(&c, m, ms);
        return;
    }
    /* This band contains only the action control. During PCM capture/playback,
     * skip the character, unrelated text and scene decoration entirely. */
    if (c.clip.y >= 183 && c.clip.y + c.clip.h <= 215) {
        action(&c, m);
        return;
    }
    /* Idle animation only repaints the pet, never lays out unrelated text. */
    if (c.clip.x + c.clip.w <= 144 && c.clip.y >= 48 &&
        c.clip.y + c.clip.h <= 178) {
        companion(&c, m, ms);
        /* Preserve the single bubble-tail edge that overlaps x=143. */
        for (int i = 0; i < 9; i++) segment(&c, 143 + i, 111, 152, 108 - i, 2, PAPER);
        return;
    }
    text(&c, 17, 12, "灵犀", 18, INK);
    text(&c, 64, 20, "一只住进口袋的小伙伴", 10, MUTED);
    color_t chip_bg = m->service_online ? 0xE0EAFD : 0xE4E8F0;
    roundrect(&c, 240, 14, 64, 23, 11, chip_bg);
    ellipse(&c, 251, 25, 2, 2, m->service_online ? ACCENT : 0xA6AFC0,
            m->service_online ? ACCENT : 0xA6AFC0, 1);
    text(&c, 259, 19, m->service_online ? "已连接" : m->wifi_connected ? "联调中" : m->provisioning ? "待配网" : "本地", 10, ACCENT);
    rect(&c, 17, 44, 286, 1, 0xE0E7F2);
    companion(&c, m, ms);
    roundrect(&c, 151, 64, 153, 87, 15, PAPER);
    /* A rounded bubble tail points towards the pet. */
    for (int i = 0; i < 9; i++) segment(&c, 143 + i, 111, 152, 108 - i, 2, PAPER);
    char identity[64];
    snprintf(identity, sizeof(identity), "%s · 大工小伙伴", companion_name(m));
    text(&c, 164, 72, identity, m->avatar > 1 && external_frame ? 12 : 10, MUTED);
    const char *first = "我在呀，", *second = "慢慢说～";
    const char *hint = "先试着说一句你好";
    if (m->state == UI_STARTING) {
        first = "等我一下，"; second = "马上就好。"; hint = "小犀正在伸个懒腰";
    } else if (m->state == UI_LISTENING) {
        first = "嗯嗯，"; second = "我在听！"; hint = "松开按键，就发给我吧";
    } else if (m->state == UI_PLAYING) {
        first = "听见啦，"; second = "我想对你说。"; hint = "轻按 BOOT 可停止播放";
        if (m->microphone_silent) {
            first = "咦，"; second = "刚刚很安静。"; hint = "麦克风暂未收到声音";
        }
    } else if (m->state == UI_ERROR) {
        first = "哎呀，"; second = "需要帮帮忙。"; hint = "请查看下方的错误提示";
    } else if (m->state == UI_THINKING) {
        first = "让我想想，"; second = "马上回应你。"; hint = "正在连接语音服务";
    }
    if (m->message[0] && (m->state == UI_PLAYING || m->state == UI_READY || m->state == UI_ERROR))
        message_text(&c, 164, 92, m->message);
    else {
        text(&c, 164, 91, first, 20, INK);
        text(&c, 164, 117, second, 20, INK);
    }
    if (m->state == UI_ERROR) text(&c, 161, 160, m->detail, 10, MUTED);
    else if (m->state == UI_READY && m->message[0]) {
        text(&c, 161, 160, "按住 BOOT 可以继续聊", 10, MUTED);
    } else if (m->state == UI_READY && m->microphone_silent) {
        text(&c, 161, 160, "麦克风暂未收到声音", 10, 0xAD645D);
    } else if (m->state == UI_READY && m->duration_ms) {
        char summary[40];
        snprintf(summary, sizeof(summary), "刚刚听见 %u.%u 秒的你", (unsigned)(m->duration_ms / 1000),
                 (unsigned)(m->duration_ms / 100 % 10));
        text(&c, 161, 160, summary, 10, MUTED);
    } else if(m->focus_active && m->state==UI_READY){
        text(&c,161,160,"长按 K2 结束这段专注",12,ACCENT);
    } else text(&c, 161, 160, m->provisioning ? "手机连接热点后配网" : hint, 10, MUTED);
    action(&c, m);
    if (m->state == UI_ERROR) {
        text(&c, 17, 221, m->error, 10, 0xAD645D);
    } else {
        if (m->service_online && !m->provisioning) {
            text(&c, 17, 220, "K1 互动 · K2 语气 · 长按更多", 12, MUTED);
            char here[32]; snprintf(here, sizeof(here), "%s在这里", companion_name(m));
            text(&c, 221, 220, here, 12, ACCENT);
        } else {
            text(&c, 17, 221, m->wifi_connected ? m->address : m->provisioning ? m->address : "本地录音 · 最长 10 秒", 10, MUTED);
            text(&c, 185, 221, m->network_enabled ? m->detail : "声音只留在这里", 10, ACCENT);
        }
    }
}
