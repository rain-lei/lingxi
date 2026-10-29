#pragma once
#include <stdint.h>

#define UI_MASCOT_WIDTH 128
#define UI_MASCOT_HEIGHT 128
#define UI_MASCOT_POSES 6

typedef enum {
    UI_MASCOT_IDLE = 0,
    UI_MASCOT_BLINK,
    UI_MASCOT_LISTENING,
    UI_MASCOT_THINKING,
    UI_MASCOT_HAPPY,
    UI_MASCOT_CONCERN
} ui_mascot_pose_t;

/* Flash-mapped const art. Alpha is straight (not premultiplied), 0..255. */
extern const uint16_t ui_mascot_rgb565[UI_MASCOT_POSES][UI_MASCOT_WIDTH * UI_MASCOT_HEIGHT];
extern const uint8_t ui_mascot_alpha[UI_MASCOT_POSES][UI_MASCOT_WIDTH * UI_MASCOT_HEIGHT];
