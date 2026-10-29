#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

typedef struct {
    bool mounted, installed, downloading;
    uint32_t received_bytes, total_bytes;
    uint32_t cache_bytes, cache_hits, cache_misses, loads, load_ms;
    uint32_t decoded_frames, decode_errors, decode_us;
    uint16_t package_version, clip_count, frame_ms, frame_index, frame_count;
    int8_t cached_avatar, cached_state;
    uint8_t cache_slots;
    char stage[24], error[96];
} asset_storage_status_t;
esp_err_t asset_storage_init(void);
void asset_storage_status(asset_storage_status_t *output);
esp_err_t asset_storage_request_download(void);
void asset_storage_audio_active(bool active);
void asset_storage_voice_busy(bool busy);
bool asset_storage_busy(void);
/* UI task only. Non-blocking cache try-lock. A compressed clip is decoded in
   RAM, and the mutex is released before the CPU renderer/LCD DMA starts.
   The UI-owned returned pixels stay valid until the next frame_begin call. */
const uint8_t *asset_storage_frame_begin(unsigned avatar, unsigned state, uint32_t ms);
const uint8_t *asset_storage_frame_current(unsigned avatar);
void asset_storage_frame_end(void);
bool asset_storage_avatar_available(unsigned avatar);
bool asset_storage_clip_available(unsigned avatar, unsigned state);
unsigned asset_storage_frame_interval(unsigned avatar, unsigned state);
uint32_t asset_storage_clip_duration(unsigned avatar, unsigned state);
