/* LingXi: RAM-only ES8311 capture/playback for ATK-DNESP32S3B V1.1. */
#include "sdkconfig.h"
#if defined(CONFIG_GDMA_ISR_IRAM_SAFE) && !defined(CONFIG_I2S_ISR_IRAM_SAFE)
#error "GDMA IRAM-safe callbacks require CONFIG_I2S_ISR_IRAM_SAFE=y for internal I2S context"
#endif
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "driver/i2s_std.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "es8311.h"
#include "key.h"
#include "led.h"
#include "myiic.h"
#include "xl9555.h"
#include "network_probe.h"
#include "conversation_client.h"
#include "ui_display.h"
#include "asset_storage.h"
#include "font_storage.h"
#include "button_controls.h"

#define SAMPLE_RATE 16000
#define MAX_SECONDS 10
#define MAX_SAMPLES (SAMPLE_RATE * MAX_SECONDS)
#define CHUNK_FRAMES 320

static const char *TAG = "lingxi_audio";
static i2s_chan_handle_t audio_tx, audio_rx;
static int16_t *recording;
static int16_t stereo[CHUNK_FRAMES * 2];
static uint32_t displayed_network_revision = UINT32_MAX;
static uint32_t displayed_settings_revision = UINT32_MAX;

static void refresh_companion_settings(void)
{
    conversation_settings_t settings;
    conversation_client_settings(&settings);
    if (settings.revision != displayed_settings_revision) {
        static const char *avatars[] = {"kangaroo", "robot", "cat", "otter", "sprout"};
        int avatar = 0;
        for (int i = 1; i < 5; ++i) if (!strcmp(settings.avatar, avatars[i])) avatar = i;
        ui_display_avatar(avatar);
        ui_display_tone(settings.tone);
        displayed_settings_revision = settings.revision;
    }
}

static bool report_error(const char *stage, esp_err_t error)
{
    if (error == ESP_OK) return false;
    ESP_LOGE(TAG, "%s: %s", stage, esp_err_to_name(error));
    ui_display_error(stage, esp_err_to_name(error));
    return true;
}

static esp_err_t audio_init(void)
{
    i2s_chan_config_t channel = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    channel.dma_desc_num = 6;
    channel.dma_frame_num = 160;
    channel.auto_clear_after_cb = true;
    esp_err_t err = i2s_new_channel(&channel, &audio_tx, &audio_rx);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_new_channel: %s", esp_err_to_name(err));
        return err;
    }
    i2s_std_config_t config = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(
            I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = GPIO_NUM_NC, .bclk = GPIO_NUM_21, .ws = GPIO_NUM_13,
            .dout = GPIO_NUM_14, .din = GPIO_NUM_47,
        },
    };
    /* BCLK = 2 slots * 32 bits = 64 Fs. DMA still packs two int16_t per frame. */
    config.slot_cfg.slot_bit_width = I2S_SLOT_BIT_WIDTH_32BIT;
    config.slot_cfg.ws_width = 32;
    err = i2s_channel_init_std_mode(audio_tx, &config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Initialize TX standard mode: %s", esp_err_to_name(err));
        return err;
    }
    err = i2s_channel_init_std_mode(audio_rx, &config);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Initialize RX standard mode: %s", esp_err_to_name(err));
        return err;
    }
    err = i2s_channel_enable(audio_tx);
    if (err != ESP_OK) return err;
    return i2s_channel_enable(audio_rx);
}

static esp_err_t write_audio(const int16_t *data, size_t bytes)
{
    size_t offset = 0;
    while (offset < bytes) {
        size_t written = 0;
        esp_err_t err = i2s_channel_write(audio_tx, (const uint8_t *)data + offset,
                                        bytes - offset, &written, 1000);
        if (err != ESP_OK) return err;
        if (written == 0) return ESP_ERR_TIMEOUT;
        offset += written;
    }
    return ESP_OK;
}

static bool begin_playback(void)
{
    ui_display_state(UI_PLAYING);
    if (report_error("Unmute", es8311_set_voice_mute(0))) return false;
    xl9555_pin_write(SPK_CTRL_IO, 1);
    vTaskDelay(pdMS_TO_TICKS(30));
    return true;
}

static bool write_mono_chunk(const int16_t *pcm, size_t count, int *peak)
{
    *peak = 0;
    for (size_t i = 0; i < count; ++i) {
        int value = pcm[i];
        stereo[2 * i] = stereo[2 * i + 1] = value;
        if (value < 0) value = -value;
        if (value > *peak) *peak = value;
    }
    return !report_error("Play audio", write_audio(stereo, count * 2 * sizeof(int16_t)));
}

static bool finish_playback(void)
{
    memset(stereo, 0, sizeof(stereo));
    esp_err_t tail = write_audio(stereo, sizeof(stereo));
    vTaskDelay(pdMS_TO_TICKS(100));
    xl9555_pin_write(SPK_CTRL_IO, 0);
    if (report_error("Finish playback", tail)) return false;
    return !report_error("Mute", es8311_set_voice_mute(1));
}

static bool play_mono(const int16_t *pcm, size_t samples)
{
    if (!begin_playback()) return false;
    bool can_interrupt = BOOT != 0;
    for (size_t offset = 0; offset < samples; offset += CHUNK_FRAMES) {
        if (BOOT != 0) can_interrupt = true;
        if (can_interrupt && BOOT == 0) break;
        size_t count = samples - offset;
        if (count > CHUNK_FRAMES) count = CHUNK_FRAMES;
        int chunk_peak;
        if (!write_mono_chunk(pcm + offset, count, &chunk_peak)) {
            xl9555_pin_write(SPK_CTRL_IO, 0);
            return false;
        }
        ui_display_meter(chunk_peak, (offset + count) * 1000 / SAMPLE_RATE,
                         samples * 1000 / SAMPLE_RATE);
    }
    return finish_playback();
}

/* Only app_main touches I2S or the LCD. The network worker can fill a bounded
   ring while this loop begins playing the first PCM, before TTS has finished. */
static bool await_conversation(conversation_result_t *response)
{
    static int16_t chunk[CHUNK_FRAMES];
    bool playing = false, playback_ok = true, interrupted = false, metadata_shown = false;
    bool can_interrupt = BOOT != 0;
    size_t played_samples = 0;
    int64_t started = esp_timer_get_time();
    while (1) {
        bool done = conversation_client_poll(response);
        if (done && response->streamed && response->status != ESP_OK) {
            if (playing) {
                /* Mute immediately on a failed stream, before drawing errors.
                   Remaining DMA samples must never leak after a failed D/E. */
                xl9555_pin_write(SPK_CTRL_IO, 0);
                playback_ok = !report_error("Mute failed stream", es8311_set_voice_mute(1))
                              && playback_ok;
                memset(stereo, 0, sizeof(stereo));
                playback_ok = !report_error("Clear failed stream", write_audio(stereo, sizeof(stereo)))
                              && playback_ok;
                playing = false;
            }
            break;
        }
        bool streaming = conversation_client_progress(response);
        if (streaming && response->reply[0] && !metadata_shown && !interrupted) {
            refresh_companion_settings();
            ui_display_message(response->reply);
            metadata_shown = true;
        }
        if (BOOT != 0) can_interrupt = true;
        if (streaming && can_interrupt && BOOT == 0 && !interrupted) {
            interrupted = true;
            conversation_client_cancel();
            if (playing) {
                playback_ok = finish_playback() && playback_ok;
                playing = false;
            }
            ui_display_state(UI_READY);
            ESP_LOGI(TAG, "Streaming reply interrupted by BOOT");
        }
        size_t count = streaming && !interrupted
                ? conversation_client_read_audio(chunk, CHUNK_FRAMES) : 0;
        if (count) {
            if (!playing) {
                conversation_client_progress(response);
                refresh_companion_settings();
                if (!metadata_shown) {
                    ui_display_message(response->reply);
                    metadata_shown = true;
                }
                playing = begin_playback();
                if (!playing) {
                    playback_ok = false;
                    interrupted = true;
                    conversation_client_cancel();
                }
            }
            if (playing) {
                int peak;
                if (!write_mono_chunk(chunk, count, &peak)) {
                    playback_ok = false;
                    interrupted = true;
                    conversation_client_cancel();
                    xl9555_pin_write(SPK_CTRL_IO, 0);
                    playing = false;
                } else {
                    if (!played_samples) {
                        ESP_LOGI(TAG, "First streaming playback in %lld ms (%lu ms to PCM receipt)",
                                 (esp_timer_get_time() - started) / 1000,
                                 (unsigned long)response->first_audio_ms);
                    }
                    played_samples += count;
                    ui_display_meter(peak, played_samples * 1000 / SAMPLE_RATE, 0);
                }
            }
        }
        /* A completed request can still have queued PCM. Drain that before
           releasing its memory, including the short final prebuffer. */
        if (done && !count) break;
        if (!count) {
            ui_display_tick();
            vTaskDelay(pdMS_TO_TICKS(10));
        }
    }
    if (playing) playback_ok = finish_playback() && playback_ok;
    /* Copy the final status after the worker has stopped modifying it. */
    conversation_client_poll(response);
    return playback_ok;
}

static bool capture_and_play(void)
{
    size_t samples = 0;
    int peak = 0;
    int64_t next_led = 0;
    xl9555_pin_write(SPK_CTRL_IO, 0);
    if (report_error("Mute", es8311_set_voice_mute(1))) return false;
    ui_display_state(UI_LISTENING);
    /* Reset after drawing the screen so the first frame is current microphone audio. */
    if (report_error("Reset RX", i2s_channel_disable(audio_rx))) return false;
    if (report_error("Enable RX", i2s_channel_enable(audio_rx))) return false;
    ESP_LOGI(TAG, "Recording: 16000 Hz, PCM16, mono, maximum %d seconds", MAX_SECONDS);
    int64_t deadline = esp_timer_get_time() + MAX_SECONDS * 1000000LL;
    while (BOOT == 0 && samples < MAX_SAMPLES && esp_timer_get_time() < deadline) {
        size_t bytes = 0;
        esp_err_t err = i2s_channel_read(audio_rx, stereo, sizeof(stereo), &bytes, 500);
        if (report_error("Read microphone", err)) return false;
        if (bytes == 0 || bytes % (2 * sizeof(int16_t)) != 0) {
            report_error("Invalid audio frame", ESP_ERR_INVALID_SIZE);
            return false;
        }
        size_t frames = bytes / (2 * sizeof(int16_t));
        for (size_t i = 0; i < frames && samples < MAX_SAMPLES; ++i) {
            /* ES8311 ADC uses the left I2S slot. */
            int16_t sample = stereo[2 * i];
            recording[samples++] = sample;
            int magnitude = sample < 0 ? -(int)sample : (int)sample;
            if (magnitude > peak) peak = magnitude;
        }
        int chunk_peak = 0;
        for (size_t i = 0; i < frames; ++i) {
            int value = stereo[2 * i];
            if (value < 0) value = -value;
            if (value > chunk_peak) chunk_peak = value;
        }
        /* Only the small meter strip updates during audio; the pet stays still. */
        ui_display_meter(chunk_peak, samples * 1000 / SAMPLE_RATE, MAX_SECONDS * 1000);
        if (esp_timer_get_time() >= next_led) {
            LED_TOGGLE();
            next_led = esp_timer_get_time() + 200000;
        }
    }
    ESP_LOGI(TAG, "Captured %u mono samples, %u bytes, peak %d",
             (unsigned)samples, (unsigned)(samples * sizeof(int16_t)), peak);
    if (samples < SAMPLE_RATE / 5) {
        ui_display_recorded(0, false);
        ui_display_state(UI_READY);
        return true;
    }
    ui_display_recorded(samples * 1000 / SAMPLE_RATE, peak == 0);
    esp_err_t request = conversation_client_start(recording, samples);
    if (request == ESP_OK) {
        ui_display_state(UI_THINKING);
        /* Keep the text buffers out of ESP-IDF's small app_main task stack. */
        static conversation_result_t response;
        bool streamed_ok = await_conversation(&response);
        refresh_companion_settings();
        if (!streamed_ok) {
            conversation_client_release();
            return false;
        }
        if (response.cancelled) {
            conversation_client_release();
            ui_display_state(UI_READY);
            return streamed_ok;
        }
        if (response.status != ESP_OK) {
            ui_display_error("Conversation", response.error);
            ESP_LOGW(TAG, "Conversation request failed: HTTP %d, %s",
                     response.http_status, esp_err_to_name(response.status));
            conversation_client_release();
            /* Keep the error visible and let the next BOOT press retry. */
            return true;
        }
        ui_display_message(response.reply);
        bool played = streamed_ok && (response.streamed || !response.samples
                                      || play_mono(response.pcm, response.samples));
        conversation_client_release();
        if (!played) return false;
    } else {
        ui_display_message("未连接服务，正在回放录音");
        if (!play_mono(recording, samples)) return false;
    }
    ui_display_state(UI_READY);
    return true;
}

void app_main(void)
{
    led_init();
    key_init();
    ESP_ERROR_CHECK(myiic_init());
    ESP_ERROR_CHECK(xl9555_init());
    xl9555_pin_write(SPK_CTRL_IO, 0);
    ESP_ERROR_CHECK(ui_display_init());
    if (report_error("ES8311 not detected",
                     i2c_master_probe(bus_handle, ES8311_ADDR, 300))) return;
    if (report_error("Initialize I2S", audio_init())) return;
    if (report_error("Initialize ES8311", es8311_init(SAMPLE_RATE))) return;
    if (report_error("Mic gain", es8311_set_mic_gain(ES8311_MIC_GAIN_24DB))) return;
    if (report_error("Speaker volume", es8311_set_voice_volume(55))) return;
    if (report_error("Mute", es8311_set_voice_mute(1))) return;
    recording = heap_caps_malloc(MAX_SAMPLES * sizeof(int16_t),
                                 MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!recording) {
        report_error("Allocate PSRAM", ESP_ERR_NO_MEM);
        return;
    }
    ESP_LOGI(TAG, "Ready: allocated %u bytes in PSRAM", (unsigned)(MAX_SAMPLES * sizeof(int16_t)));
    esp_err_t network_error = network_probe_start();
    if (network_error != ESP_OK) {
        ESP_LOGW(TAG, "Network setup: %s; local playback remains available",
                 esp_err_to_name(network_error));
    }
    if (report_error("Conversation worker", conversation_client_init())) return;
    esp_err_t assets_error = asset_storage_init();
    if (assets_error != ESP_OK) ESP_LOGW(TAG, "Optional TF assets: %s", esp_err_to_name(assets_error));
    refresh_companion_settings();
    ui_display_state(UI_READY);
    button_controls_init();
    while (1) {
        button_controls_tick();
        if (BOOT == 0) {
            vTaskDelay(pdMS_TO_TICKS(20));
            if (BOOT == 0) {
                asset_storage_status_t assets;
                asset_storage_status(&assets);
                font_storage_status_t fonts;
                font_storage_status(&fonts);
                if (assets.downloading || fonts.downloading) {
                    ui_display_message("正在安装素材，完成后再聊");
                    while (BOOT == 0) vTaskDelay(pdMS_TO_TICKS(20));
                    continue;
                }
                button_controls_suspend();
                bool ok = capture_and_play();
                xl9555_pin_write(SPK_CTRL_IO, 0);
                while (BOOT == 0) vTaskDelay(pdMS_TO_TICKS(20));
                vTaskDelay(pdMS_TO_TICKS(30));
                if (!ok) return;
            }
        }
        network_status_t network;
        network_probe_status(&network);
        if (network.revision != displayed_network_revision) {
            ui_display_network(&network);
            displayed_network_revision = network.revision;
        }
        ui_display_tick();
        refresh_companion_settings();
        vTaskDelay(pdMS_TO_TICKS(10));
    }
}
