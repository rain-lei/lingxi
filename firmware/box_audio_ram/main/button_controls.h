#pragma once
#include <stdbool.h>
#include <stdint.h>

typedef struct {
    bool k1_down, k2_down, blocked, showcase, focus_active, tone_pending;
    uint32_t short_presses[2],long_presses[2],focus_remaining_seconds;
    char tone[24],last_action[32];
} button_controls_status_t;

void button_controls_init(void);
/* Called only by app_main. It performs one bounded XL9555 input read; all
   debounce, long-press and focus timing use timestamps without sleeps. */
void button_controls_tick(void);
void button_controls_suspend(void);
void button_controls_status(button_controls_status_t *output);
