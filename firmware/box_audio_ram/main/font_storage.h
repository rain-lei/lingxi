#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "lxff_format.h"
typedef struct {
    bool mounted, installed, downloading, cached;
    uint8_t active_tone, wanted_tone;
    uint32_t received_bytes, total_bytes, cache_bytes, revision;
    char stage[24], error[96], name[40];
} font_storage_status_t;
/* All file/network IO is performed by asset_storage's single SD worker. */
void font_storage_set_mounted(bool mounted);
void font_storage_worker_poll(bool recording);
void font_storage_audio_active(bool active);
void font_storage_request(const char *tone);
esp_err_t font_storage_request_download(void);
void font_storage_status(font_storage_status_t *status);
/* Borrowed cache; must pair with end. No file IO, allocation or decoding. */
const lxff_view_t *font_storage_frame_begin(void);
void font_storage_frame_end(void);
