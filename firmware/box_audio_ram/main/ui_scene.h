#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "lxff_format.h"

#define UI_WIDTH 320
#define UI_HEIGHT 240
#define UI_REPLY_PAGE_MS 7000

typedef enum {
    UI_STARTING, UI_READY, UI_LISTENING, UI_PLAYING, UI_ERROR, UI_THINKING
} ui_state_t;

typedef struct { int x, y, w, h; } ui_rect_t;
typedef struct {
    ui_state_t state;
    bool wifi_connected;
    bool service_online;
    bool network_enabled;
    bool microphone_silent;
    uint32_t elapsed_ms;
    uint32_t duration_ms;
    uint8_t levels[18];
    char address[40];
    char detail[40];
    char error[40];
    uint8_t avatar; /* kangaroo, robot, cat, otter, sprout; no card: embedded fallback */
    bool provisioning;
    char message[2048];
    uint32_t message_started_ms;
    bool rounded_font;
    bool focus_active, showcase_mode;
    uint32_t focus_remaining_seconds;
    char control_notice[96];
    char control_tone[24];
} ui_model_t;

/* Portable RGB565 renderer; the desktop preview uses exactly this code. */
void ui_scene_draw(uint16_t *pixels, ui_rect_t region,
                   const ui_model_t *model, uint32_t now_ms);
bool ui_scene_has_reply(const ui_model_t *model);
unsigned ui_scene_reply_pages(const ui_model_t *model);
/* Borrowed 128x128 RGB565LE+alpha frame, valid only for the next draw call. */
void ui_scene_external_frame(const uint8_t *frame);
/* Borrowed verified font cache; lifetime is controlled by font_storage. */
void ui_scene_external_font(const lxff_view_t *font);
