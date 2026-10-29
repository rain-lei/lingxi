#pragma once
#include "esp_err.h"
#include "network_probe.h"
#include "ui_scene.h"

esp_err_t ui_display_init(void);
void ui_display_state(ui_state_t state);
void ui_display_network(const network_status_t *network);
void ui_display_tick(void);
void ui_display_meter(int peak, uint32_t elapsed_ms, uint32_t duration_ms);
void ui_display_recorded(uint32_t duration_ms, bool silent);
void ui_display_error(const char *stage, const char *error);
void ui_display_message(const char *message);
void ui_display_avatar(int avatar);
void ui_display_tone(const char *tone);
void ui_display_stop_preview(void);
void ui_display_notice(const char *message,uint32_t duration_ms);
void ui_display_control_state(bool focus_active,uint32_t seconds,bool showcase,const char *tone);

typedef struct {
    uint32_t paints, animation_frames, paint_us, max_paint_us, render_us, flush_us;
    uint32_t fps_x100, skipped_paints, target_interval_ms, preview_remaining_ms, main_stack_free_bytes;
    uint8_t avatar, animation, ui_state;
    bool preview_active, audio_paints_paused;
} ui_display_stats_t;
/* Read-only snapshot. FPS counts newly decoded/displayed frames in the last
   measured window, rather than assuming the asset frame rate was achieved. */
void ui_display_stats(ui_display_stats_t *output);
/* Queues one bounded, silent demo on the UI owner. No speech/model requests,
   no credentials/settings changes, rejected while audio/install is active. */
esp_err_t ui_display_request_preview(unsigned avatar, unsigned animation, uint32_t duration_ms);
