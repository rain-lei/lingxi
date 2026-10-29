#pragma once
#include <stdint.h>

#define UI_KANGAROO_WIDTH 128
#define UI_KANGAROO_HEIGHT 128
#define UI_KANGAROO_POSES 6

/* Pose order: idle, blink, listening, thinking, happy, concern.
 * Straight alpha 0..255; source PNG remains unchanged. */
extern const uint16_t ui_kangaroo_rgb565[UI_KANGAROO_POSES][UI_KANGAROO_WIDTH * UI_KANGAROO_HEIGHT];
extern const uint8_t ui_kangaroo_alpha[UI_KANGAROO_POSES][UI_KANGAROO_WIDTH * UI_KANGAROO_HEIGHT];
