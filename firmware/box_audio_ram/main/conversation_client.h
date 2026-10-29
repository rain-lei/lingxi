#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include "esp_err.h"

typedef struct {
    char avatar[24];
    char mode[24];
    char voice[64];
    char tone[24];
    char language[16];
    uint32_t revision;
} conversation_settings_t;

typedef struct {
    const int16_t *pcm;
    size_t samples;
    char transcript[1024];
    char reply[2048];
    char error[160];
    int http_status;
    esp_err_t status;
    bool streamed;
    bool cancelled;
    uint32_t first_audio_ms;
} conversation_result_t;

esp_err_t conversation_client_init(void);
/* The caller keeps pcm unchanged until poll returns a completed result. */
esp_err_t conversation_client_start(const int16_t *pcm, size_t samples);
bool conversation_client_poll(conversation_result_t *result);
/* Streaming PCM is consumed by app_main, the only I2S / LCD owner. Audio starts
   after a short prebuffer and remains bounded by a 64-KiB producer/consumer ring. */
bool conversation_client_progress(conversation_result_t *result);
size_t conversation_client_read_audio(int16_t *pcm, size_t capacity_samples);
void conversation_client_cancel(void);
void conversation_client_release(void);
void conversation_client_settings(conversation_settings_t *settings);
/* Immediately changes the local tone, then asynchronously patches only that
   preference on the PC. Pending changes survive old settings polls. */
esp_err_t conversation_client_set_tone(const char *tone);
bool conversation_client_tone_pending(void);
