/* Bounded PCM voice bridge. All blocking network I/O runs away from the LCD task. */
#include "conversation_client.h"
#include "network_probe.h"
#include "sdkconfig.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>
#include <errno.h>
#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

#define MAX_JSON 8192
#define MAX_PCM 640000
#define MAX_RESPONSE (12 + MAX_JSON + MAX_PCM)
#define STREAM_RING_BYTES 65536
#define STREAM_PREBUFFER_BYTES 3840
#define STREAM_FRAME_BYTES 4096
static const char *TAG = "lingxi_voice";
static SemaphoreHandle_t lock;
static TaskHandle_t worker;
static enum { JOB_IDLE, JOB_RUNNING, JOB_DONE } state;
static const int16_t *input_pcm;
static size_t input_samples;
static uint8_t *response_data;
static conversation_result_t result;
static size_t stream_head, stream_count, stream_total;
static bool stream_playing, stream_cancelled;
static conversation_settings_t settings = {.avatar = "kangaroo", .mode = "companion", .tone = "warm", .language = "zh"};
static bool tone_pending;
static uint32_t tone_revision;

static void copy_text(char *dest, size_t size, const char *source)
{
    if (!size) return;
    size_t count = strlen(source);
    if (count >= size) {
        count = size - 1;
        while (count && ((unsigned char)source[count] & 0xc0) == 0x80) --count;
    }
    memcpy(dest, source, count);
    dest[count] = 0;
}

static void json_text(cJSON *object, const char *key, char *dest, size_t size)
{
    cJSON *item = cJSON_GetObjectItemCaseSensitive(object, key);
    if (cJSON_IsString(item)) copy_text(dest, size, item->valuestring);
}

static void accept_settings(cJSON *object)
{
    if (!cJSON_IsObject(object)) return;
    xSemaphoreTake(lock, portMAX_DELAY);
    conversation_settings_t next = settings;
    json_text(object, "avatar", next.avatar, sizeof(next.avatar));
    json_text(object, "mode", next.mode, sizeof(next.mode));
    json_text(object, "voice", next.voice, sizeof(next.voice));
    json_text(object, "tone", next.tone, sizeof(next.tone));
    if(tone_pending)copy_text(next.tone,sizeof(next.tone),settings.tone);
    json_text(object, "language", next.language, sizeof(next.language));
    if (memcmp(&next, &settings, sizeof(next))) {
        next.revision = settings.revision + 1;
        settings = next;
    }
    xSemaphoreGive(lock);
}

typedef struct {
    uint8_t *data;
    size_t used, capacity, uploaded;
    int64_t deadline, started, advertised;
    const char *phase;
    int http_status;
    bool overflow, manual, voice;
} http_body_t;

static esp_err_t collect(esp_http_client_event_t *event)
{
    http_body_t *body = event->user_data;
    if (body->manual) return ESP_OK;
    if (esp_timer_get_time() > body->deadline) return ESP_ERR_TIMEOUT;
    if (event->event_id == HTTP_EVENT_ON_DATA && event->data_len > 0) {
        if ((size_t)event->data_len > body->capacity - body->used) {
            body->overflow = true;
            return ESP_ERR_INVALID_SIZE;
        }
        memcpy(body->data + body->used, event->data, event->data_len);
        body->used += event->data_len;
        body->data[body->used] = 0;
    }
    return ESP_OK;
}

static esp_http_client_handle_t make_client(const char *path, http_body_t *body, int timeout)
{
    char base[256], device[48], token[160], url[360], auth[176];
    if (!network_probe_config(base, sizeof(base), device, sizeof(device), token, sizeof(token))) return NULL;
    int length = snprintf(url, sizeof(url), "%s%s", base, path);
    if (length < 0 || length >= sizeof(url)) return NULL;
    esp_http_client_config_t config = {
        .url = url, .timeout_ms = timeout, .event_handler = collect,
        .user_data = body, .crt_bundle_attach = esp_crt_bundle_attach,
        .disable_auto_redirect = true, .buffer_size = 2048,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) return NULL;
    esp_http_client_set_header(client, "X-Device-Id", device);
    if (token[0]) {
        snprintf(auth, sizeof(auth), "Bearer %s", token);
        esp_http_client_set_header(client, "Authorization", auth);
    }
    return client;
}

static uint32_t little_u32(const uint8_t *bytes)
{
    return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8)
         | ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static bool request_cancelled(void)
{
    xSemaphoreTake(lock, portMAX_DELAY);
    bool cancelled = stream_cancelled;
    xSemaphoreGive(lock);
    return cancelled;
}

/* The streaming protocol is self-delimiting. Do not use the SDK's zero
   Content-Length value for HTTP/1.0 connection-close replies as an empty body. */
static esp_err_t read_exact(esp_http_client_handle_t client, http_body_t *body,
                            uint8_t *dest, size_t length)
{
    size_t offset = 0;
    while (offset < length) {
        if (request_cancelled()) return ESP_ERR_INVALID_STATE;
        int64_t remaining = body->deadline - esp_timer_get_time();
        if (remaining <= 0) return ESP_ERR_TIMEOUT;
        int remaining_ms = remaining / 1000;
        if (remaining_ms < 1) return ESP_ERR_TIMEOUT;
        /* A short SDK wait allows BOOT cancellation. EAGAIN is a resumable
           idle interval, not a failed request: ASR / first tokens may exceed it. */
        esp_http_client_set_timeout_ms(client, remaining_ms < 1000 ? remaining_ms : 1000);
        size_t count = length - offset;
        if (count > 2048) count = 2048;
        int received = esp_http_client_read(client, (char *)dest + offset, count);
        if (received == -ESP_ERR_HTTP_EAGAIN) { vTaskDelay(1); continue; }
        if (received < 0) return ESP_FAIL;
        if (!received) return ESP_ERR_HTTP_INCOMPLETE_DATA;
        offset += received;
        body->used += received;
    }
    return ESP_OK;
}

static bool accept_metadata(const uint8_t *data, size_t length, bool require_audio)
{
    cJSON *metadata = cJSON_ParseWithLength((const char *)data, length);
    if (!cJSON_IsObject(metadata)) { cJSON_Delete(metadata); return false; }
    cJSON *audio = cJSON_GetObjectItemCaseSensitive(metadata, "audio");
    if (require_audio || audio) {
        cJSON *rate = cJSON_GetObjectItemCaseSensitive(audio, "sample_rate");
        cJSON *bits = cJSON_GetObjectItemCaseSensitive(audio, "bits");
        cJSON *channels = cJSON_GetObjectItemCaseSensitive(audio, "channels");
        cJSON *encoding = cJSON_GetObjectItemCaseSensitive(audio, "encoding");
        if (!cJSON_IsNumber(rate) || rate->valueint != 16000
                || !cJSON_IsNumber(bits) || bits->valueint != 16
                || !cJSON_IsNumber(channels) || channels->valueint != 1
                || !cJSON_IsString(encoding) || strcmp(encoding->valuestring, "pcm_s16le")) {
            cJSON_Delete(metadata);
            return false;
        }
    }
    if (!require_audio) {
        cJSON *bytes = cJSON_GetObjectItemCaseSensitive(audio, "bytes");
        if (!cJSON_IsNumber(bytes) || bytes->valuedouble != (double)stream_total) {
            cJSON_Delete(metadata);
            return false;
        }
    }
    accept_settings(cJSON_GetObjectItemCaseSensitive(metadata, "settings"));
    xSemaphoreTake(lock, portMAX_DELAY);
    json_text(metadata, "transcript", result.transcript, sizeof(result.transcript));
    json_text(metadata, "reply", result.reply, sizeof(result.reply));
    xSemaphoreGive(lock);
    cJSON_Delete(metadata);
    return true;
}

static esp_err_t queue_audio(const uint8_t *data, size_t length, http_body_t *body)
{
    size_t offset = 0;
    while (offset < length) {
        if (esp_timer_get_time() > body->deadline) return ESP_ERR_TIMEOUT;
        xSemaphoreTake(lock, portMAX_DELAY);
        if (stream_cancelled) { xSemaphoreGive(lock); return ESP_ERR_INVALID_STATE; }
        size_t count = STREAM_RING_BYTES - stream_count;
        if (count > length - offset) count = length - offset;
        size_t tail = (stream_head + stream_count) % STREAM_RING_BYTES;
        if (count > STREAM_RING_BYTES - tail) count = STREAM_RING_BYTES - tail;
        if (count) {
            memcpy(response_data + tail, data + offset, count);
            stream_count += count;
            stream_total += count;
            result.samples = stream_total / sizeof(int16_t);
            if (!result.first_audio_ms) {
                result.first_audio_ms = (esp_timer_get_time() - body->started) / 1000;
                ESP_LOGI(TAG, "First streaming PCM received in %lu ms", (unsigned long)result.first_audio_ms);
            }
        }
        xSemaphoreGive(lock);
        offset += count;
        if (!count) vTaskDelay(pdMS_TO_TICKS(5));
    }
    return ESP_OK;
}

static esp_err_t read_stream(esp_http_client_handle_t client, http_body_t *body)
{
    uint8_t *frame = heap_caps_malloc(MAX_JSON + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!frame) return ESP_ERR_NO_MEM;
    xSemaphoreTake(lock, portMAX_DELAY);
    result.streamed = true;
    xSemaphoreGive(lock);
    esp_err_t error = ESP_ERR_INVALID_RESPONSE;
    bool metadata_seen = false;
    while (1) {
        uint8_t header[5];
        error = read_exact(client, body, header, sizeof(header));
        if (error != ESP_OK) break;
        uint32_t length = little_u32(header + 1);
        bool audio = header[0] == 'A';
        if (!length || length > (audio ? STREAM_FRAME_BYTES : MAX_JSON)
                || (audio && (!metadata_seen || length % 2 || length > MAX_PCM - stream_total))) {
            error = ESP_ERR_INVALID_SIZE;
            break;
        }
        error = read_exact(client, body, frame, length);
        if (error != ESP_OK) break;
        frame[length] = 0;
        if (audio) {
            body->phase = "Stream audio";
            error = queue_audio(frame, length, body);
            if (error != ESP_OK) break;
        } else if (header[0] == 'J' && !metadata_seen) {
            if (!accept_metadata(frame, length, true)) { error = ESP_ERR_INVALID_RESPONSE; break; }
            metadata_seen = true;
            body->phase = "First reply audio";
        } else if (header[0] == 'D' && metadata_seen) {
            error = stream_total && accept_metadata(frame, length, false)
                    ? ESP_OK : ESP_ERR_INVALID_RESPONSE;
            break;
        } else if (header[0] == 'E') {
            cJSON *value = cJSON_ParseWithLength((const char *)frame, length);
            cJSON *nested = cJSON_GetObjectItemCaseSensitive(value, "error");
            xSemaphoreTake(lock, portMAX_DELAY);
            json_text(value, "message", result.error, sizeof(result.error));
            if (cJSON_IsString(nested)) copy_text(result.error, sizeof(result.error), nested->valuestring);
            else if (cJSON_IsObject(nested)) json_text(nested, "message", result.error, sizeof(result.error));
            xSemaphoreGive(lock);
            cJSON_Delete(value);
            error = ESP_FAIL;
            break;
        } else { error = ESP_ERR_INVALID_RESPONSE; break; }
    }
    free(frame);
    return error;
}

static esp_err_t read_response(esp_http_client_handle_t client, http_body_t *body)
{
    body->phase = "Reply headers";
    int64_t headers_started = esp_timer_get_time();
    int64_t advertised = esp_http_client_fetch_headers(client);
    body->advertised = advertised;
    if (advertised < 0)
        return advertised == -ESP_ERR_HTTP_EAGAIN ? ESP_ERR_TIMEOUT : ESP_FAIL;
    body->http_status = esp_http_client_get_status_code(client);
    ESP_LOGI(TAG, "HTTP %d, content length %" PRId64 ", headers in %lld ms",
             body->http_status, advertised, (esp_timer_get_time() - headers_started) / 1000);
    /* Error replies are JSON only; they must never consume an audio-sized body. */
    if (body->http_status != 200 && body->capacity > MAX_JSON) body->capacity = MAX_JSON;
    if (advertised > body->capacity) { body->overflow = true; return ESP_ERR_INVALID_SIZE; }
    if (body->voice && body->http_status == 200) {
        esp_err_t error = read_exact(client, body, body->data, 4);
        if (error != ESP_OK) return error;
        if (!memcmp(body->data, "LXS1", 4)) return read_stream(client, body);
        if (memcmp(body->data, "LXI1", 4)) return ESP_ERR_INVALID_RESPONSE;
    }
    bool known_length = !esp_http_client_is_chunked_response(client) && advertised >= 0;
    body->phase = "Reply audio";
    /* Fetch-headers may already have cached the entire body. Always drain it. */
    size_t next_yield = 16384;
    while (1) {
        if (known_length && body->used == (size_t)advertised) break;
        if (esp_timer_get_time() > body->deadline) return ESP_ERR_TIMEOUT;
        int remaining_ms = (body->deadline - esp_timer_get_time()) / 1000;
        if (remaining_ms < 1) return ESP_ERR_TIMEOUT;
        esp_http_client_set_timeout_ms(client, remaining_ms < 10000 ? remaining_ms : 10000);
        size_t count = body->capacity - body->used;
        /* FIONREAD is unavailable when LWIP_SO_RCVBUF is disabled (our board's
           configuration). Never fall back to one-byte TCP reads: a normal audio
           response would take minutes. Drain SDK-cached data in 2-KB blocks. */
        if (count > 2048) count = 2048;
        if (known_length && count > (size_t)advertised - body->used)
            count = (size_t)advertised - body->used;
        char extra;
        int received = esp_http_client_read(client,
                count ? (char *)body->data + body->used : &extra, count ? count : 1);
        if (received < 0)
            return received == -ESP_ERR_HTTP_EAGAIN ? ESP_ERR_TIMEOUT : ESP_FAIL;
        if (received == 0) {
            if (!esp_http_client_is_complete_data_received(client)) return ESP_ERR_HTTP_INCOMPLETE_DATA;
            break;
        }
        if (!count) { body->overflow = true; return ESP_ERR_INVALID_SIZE; }
        body->used += received;
        if (body->used >= next_yield) {
            vTaskDelay(1);
            next_yield = body->used + 16384;
        }
    }
    body->data[body->used] = 0;
    ESP_LOGI(TAG, "HTTP body complete: %u/%" PRId64 " bytes in %lld ms",
             (unsigned)body->used, advertised, (esp_timer_get_time() - headers_started) / 1000);
    return ESP_OK;
}

static esp_err_t transfer_voice(esp_http_client_handle_t client, http_body_t *body)
{
    const size_t bytes = input_samples * sizeof(int16_t);
    body->phase = "Connect service";
    esp_err_t error = esp_http_client_open(client, bytes);
    if (error != ESP_OK) return error;
    body->phase = "Upload recording";
    size_t sent = 0;
    while (sent < bytes) {
        if (esp_timer_get_time() > body->deadline) return ESP_ERR_TIMEOUT;
        size_t chunk = bytes - sent;
        if (chunk > 4096) chunk = 4096;
        int count = esp_http_client_write(client, (const char *)input_pcm + sent, chunk);
        if (count <= 0) return ESP_FAIL;
        sent += count;
        body->uploaded = sent;
    }
    /* ASR + reply generation + TTS can take a while before response headers. */
    int remaining_ms = (body->deadline - esp_timer_get_time()) / 1000;
    if (remaining_ms < 1) return ESP_ERR_TIMEOUT;
    esp_http_client_set_timeout_ms(client, remaining_ms < 90000 ? remaining_ms : 90000);
    return read_response(client, body);
}

static void request_voice(void)
{
    response_data = heap_caps_malloc(MAX_RESPONSE + 1, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!response_data) {
        result.status = ESP_ERR_NO_MEM;
        copy_text(result.error, sizeof(result.error), "Insufficient audio memory");
        return;
    }
    http_body_t body = {.data = response_data, .capacity = MAX_RESPONSE, .manual = true,
                        .started = esp_timer_get_time(), .advertised = -1,
                        .voice = true,
                        .deadline = esp_timer_get_time() + 120000000LL};
    esp_http_client_handle_t client = make_client("/api/device/conversation", &body, 10000);
    if (!client) {
        copy_text(result.error, sizeof(result.error), "Connect Wi-Fi and configure the service first");
        return;
    }
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "Content-Type", "audio/pcm");
    esp_http_client_set_header(client, "Accept", "application/vnd.lingxi.voice-stream");
    /* A queued button change must affect this request even when the optional
       background settings save has not reached the PC yet. */
    xSemaphoreTake(lock,portMAX_DELAY);
    bool apply_tone=tone_pending;char selected_tone[24];copy_text(selected_tone,sizeof(selected_tone),settings.tone);
    xSemaphoreGive(lock);
    if(apply_tone)esp_http_client_set_header(client,"X-Lingxi-Tone",selected_tone);
    result.status = transfer_voice(client, &body);
    result.http_status = body.http_status;
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
    result.cancelled = request_cancelled();
    if (result.streamed && result.status != ESP_OK) {
        /* An E frame or truncated connection must not leave unconfirmed PCM
           playing after the terminal failure. app_main mutes on JOB_DONE. */
        xSemaphoreTake(lock, portMAX_DELAY);
        stream_count = 0;
        xSemaphoreGive(lock);
    }
    if (result.status != ESP_OK || body.overflow) {
        if (body.overflow) result.status = ESP_ERR_INVALID_SIZE;
        if (!result.error[0]) snprintf(result.error, sizeof(result.error), "%s: %s",
                                     body.phase ? body.phase : "Voice request", esp_err_to_name(result.status));
        ESP_LOGW(TAG, "%s failed after %lld ms: %s; uploaded %u, received %u/%" PRId64 ", HTTP %d",
                 body.phase ? body.phase : "Voice request", (esp_timer_get_time() - body.started) / 1000,
                 esp_err_to_name(result.status), (unsigned)body.uploaded,
                 (unsigned)body.used, body.advertised, body.http_status);
        return;
    }
    if (result.streamed) {
        ESP_LOGI(TAG, "Streaming response complete: %u PCM samples, %lld ms total",
                 (unsigned)result.samples, (esp_timer_get_time() - body.started) / 1000);
        return;
    }
    if (result.http_status != 200) {
        result.status = ESP_FAIL;
        snprintf(result.error, sizeof(result.error), "Service HTTP %d", result.http_status);
        cJSON *error = cJSON_ParseWithLength((char *)body.data, body.used);
        cJSON *value = cJSON_GetObjectItemCaseSensitive(error, "error");
        if (cJSON_IsString(value)) copy_text(result.error, sizeof(result.error), value->valuestring);
        else if (cJSON_IsObject(value)) json_text(value, "message", result.error, sizeof(result.error));
        cJSON_Delete(error);
        return;
    }
    if (body.used < 12 || memcmp(body.data, "LXI1", 4)) goto invalid;
    uint32_t json_size = little_u32(body.data + 4), pcm_size = little_u32(body.data + 8);
    if (!json_size || json_size > MAX_JSON || pcm_size > MAX_PCM || pcm_size % 2
            || body.used != 12 + (size_t)json_size + pcm_size) goto invalid;
    cJSON *metadata = cJSON_ParseWithLength((char *)body.data + 12, json_size);
    cJSON *audio = cJSON_GetObjectItemCaseSensitive(metadata, "audio");
    cJSON *rate = cJSON_GetObjectItemCaseSensitive(audio, "sample_rate");
    cJSON *bits = cJSON_GetObjectItemCaseSensitive(audio, "bits");
    cJSON *channels = cJSON_GetObjectItemCaseSensitive(audio, "channels");
    cJSON *encoding = cJSON_GetObjectItemCaseSensitive(audio, "encoding");
    if (!cJSON_IsObject(metadata) || !cJSON_IsNumber(rate) || rate->valueint != 16000
            || !cJSON_IsNumber(bits) || bits->valueint != 16
            || !cJSON_IsNumber(channels) || channels->valueint != 1
            || !cJSON_IsString(encoding) || strcmp(encoding->valuestring, "pcm_s16le")) {
        cJSON_Delete(metadata);
        goto invalid;
    }
    json_text(metadata, "transcript", result.transcript, sizeof(result.transcript));
    json_text(metadata, "reply", result.reply, sizeof(result.reply));
    accept_settings(cJSON_GetObjectItemCaseSensitive(metadata, "settings"));
    cJSON_Delete(metadata);
    /* JSON length can be odd. Align PCM to a 16-bit address before I2S access. */
    memmove(response_data, response_data + 12 + json_size, pcm_size);
    result.pcm = (const int16_t *)response_data;
    result.samples = pcm_size / sizeof(int16_t);
    result.status = ESP_OK;
    ESP_LOGI(TAG, "Voice response: %u PCM samples", (unsigned)result.samples);
    return;
invalid:
    result.status = ESP_ERR_INVALID_RESPONSE;
    copy_text(result.error, sizeof(result.error), "Invalid server audio response");
}

static void refresh_settings(void)
{
    xSemaphoreTake(lock, portMAX_DELAY);
    bool idle = state == JOB_IDLE;
    xSemaphoreGive(lock);
    if (!idle) return;
    char base[256], device[48], token[160], path[160];
    if (!network_probe_config(base, sizeof(base), device, sizeof(device), token, sizeof(token))) return;
    snprintf(path, sizeof(path), "/api/companion/settings?device_id=%s", device);
    http_body_t body = {.data = calloc(MAX_JSON + 1, 1), .capacity = MAX_JSON, .manual = true,
                        .deadline = esp_timer_get_time() + 1500000LL};
    if (!body.data) return;
    /* Settings are optional and retain their last good value on failure. A
       slow settings GET must never occupy this voice worker for eight seconds. */
    esp_http_client_handle_t client = make_client(path, &body, 750);
    if (client) {
        xSemaphoreTake(lock, portMAX_DELAY);
        idle = state == JOB_IDLE;
        xSemaphoreGive(lock);
        esp_err_t error = idle ? esp_http_client_open(client, 0) : ESP_ERR_INVALID_STATE;
        xSemaphoreTake(lock, portMAX_DELAY);
        idle = state == JOB_IDLE;
        xSemaphoreGive(lock);
        if (error == ESP_OK && idle) error = read_response(client, &body);
        if (error == ESP_OK && body.http_status == 200 && !body.overflow) {
            cJSON *value = cJSON_ParseWithLength((char *)body.data, body.used);
            accept_settings(cJSON_GetObjectItemCaseSensitive(value, "settings"));
            cJSON_Delete(value);
        }
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
    }
    free(body.data);
}

static void save_pending_tone(void)
{
    char base[256],device[48],token[160],tone[24],payload[150];uint32_t revision;
    if(!network_probe_config(base,sizeof(base),device,sizeof(device),token,sizeof(token)))return;
    xSemaphoreTake(lock,portMAX_DELAY);
    bool pending=tone_pending && state==JOB_IDLE;revision=tone_revision;copy_text(tone,sizeof(tone),settings.tone);
    xSemaphoreGive(lock);
    if(!pending)return;
    int length=snprintf(payload,sizeof(payload),"{\"device_id\":\"%s\",\"settings\":{\"tone\":\"%s\"}}",device,tone);
    if(length<1 || length>=(int)sizeof(payload))return;
    http_body_t body={.data=calloc(MAX_JSON+1,1),.capacity=MAX_JSON,.manual=true,
        .deadline=esp_timer_get_time()+1500000LL};
    if(!body.data)return;
    esp_http_client_handle_t client=make_client("/api/companion/settings",&body,750);
    if(client){
        esp_http_client_set_method(client,HTTP_METHOD_POST);
        esp_http_client_set_header(client,"Content-Type","application/json");
        esp_err_t error=esp_http_client_open(client,length);
        size_t used=0;
        while(error==ESP_OK && used<(size_t)length){
            int n=esp_http_client_write(client,payload+used,length-used);
            if(n<=0){error=ESP_FAIL;break;}used+=n;
        }
        if(error==ESP_OK)error=read_response(client,&body);
        if(error==ESP_OK && body.http_status==200 && !body.overflow){
            cJSON *value=cJSON_ParseWithLength((char*)body.data,body.used);
            cJSON *saved=cJSON_GetObjectItemCaseSensitive(cJSON_GetObjectItemCaseSensitive(value,"settings"),"tone");
            if(cJSON_IsString(saved) && !strcmp(saved->valuestring,tone)){
                xSemaphoreTake(lock,portMAX_DELAY);
                if(tone_revision==revision)tone_pending=false;
                xSemaphoreGive(lock);
                accept_settings(cJSON_GetObjectItemCaseSensitive(value,"settings"));
            }
            cJSON_Delete(value);
        }
        esp_http_client_close(client);esp_http_client_cleanup(client);
    }
    free(body.data);
}
static void voice_task(void *unused)
{
    while (1) {
        ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(15000));
        xSemaphoreTake(lock, portMAX_DELAY);
        bool pending = state == JOB_RUNNING;
        xSemaphoreGive(lock);
        if (pending) {
            network_probe_voice_busy(true);
            request_voice();
            network_probe_voice_busy(false);
            xSemaphoreTake(lock, portMAX_DELAY);
            state = JOB_DONE;
            xSemaphoreGive(lock);
        } else if (network_probe_connected()) {
            if(conversation_client_tone_pending())save_pending_tone();
            else refresh_settings();
        }
    }
}

esp_err_t conversation_client_init(void)
{
    lock = xSemaphoreCreateMutex();
    if (!lock) return ESP_ERR_NO_MEM;
    if (xTaskCreate(voice_task, "lingxi_voice", 10240, NULL, 4, &worker) != pdPASS) return ESP_ERR_NO_MEM;
    return ESP_OK;
}

esp_err_t conversation_client_start(const int16_t *pcm, size_t samples)
{
#ifndef CONFIG_LINGXI_CONVERSATION_ENABLE
    return ESP_ERR_NOT_SUPPORTED;
#else
    if (!worker || !pcm || !samples || samples > 160000) return ESP_ERR_INVALID_ARG;
    if (!network_probe_connected()) return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(lock, portMAX_DELAY);
    if (state != JOB_IDLE) { xSemaphoreGive(lock); return ESP_ERR_INVALID_STATE; }
    input_pcm = pcm;
    input_samples = samples;
    stream_head = stream_count = stream_total = 0;
    stream_playing = stream_cancelled = false;
    memset(&result, 0, sizeof(result));
    result.status = ESP_FAIL;
    state = JOB_RUNNING;
    xSemaphoreGive(lock);
    xTaskNotifyGive(worker);
    return ESP_OK;
#endif
}

bool conversation_client_poll(conversation_result_t *output)
{
    if (!lock) return false;
    xSemaphoreTake(lock, portMAX_DELAY);
    bool done = state == JOB_DONE;
    if (done) *output = result;
    xSemaphoreGive(lock);
    return done;
}

bool conversation_client_progress(conversation_result_t *output)
{
    if (!lock) return false;
    xSemaphoreTake(lock, portMAX_DELAY);
    bool active = state != JOB_IDLE && result.streamed;
    /* Only the metadata fields are published during a running job. Final
       status / error / sizes remain worker-owned until JOB_DONE. */
    if (active) {
        output->streamed = true;
        output->first_audio_ms = result.first_audio_ms;
        copy_text(output->transcript, sizeof(output->transcript), result.transcript);
        copy_text(output->reply, sizeof(output->reply), result.reply);
    }
    xSemaphoreGive(lock);
    return active;
}

size_t conversation_client_read_audio(int16_t *pcm, size_t capacity_samples)
{
    if (!lock || !pcm || !capacity_samples) return 0;
    xSemaphoreTake(lock, portMAX_DELAY);
    if (!result.streamed || stream_cancelled || (!stream_playing
            && stream_count < STREAM_PREBUFFER_BYTES && state != JOB_DONE)) {
        xSemaphoreGive(lock);
        return 0;
    }
    size_t count = stream_count;
    if (count > capacity_samples * sizeof(int16_t)) count = capacity_samples * sizeof(int16_t);
    size_t first = count;
    if (first > STREAM_RING_BYTES - stream_head) first = STREAM_RING_BYTES - stream_head;
    memcpy(pcm, response_data + stream_head, first);
    if (count > first) memcpy((uint8_t *)pcm + first, response_data, count - first);
    stream_head = (stream_head + count) % STREAM_RING_BYTES;
    stream_count -= count;
    if (count) stream_playing = true;
    xSemaphoreGive(lock);
    return count / sizeof(int16_t);
}

void conversation_client_cancel(void)
{
    if (!lock) return;
    xSemaphoreTake(lock, portMAX_DELAY);
    stream_cancelled = true;
    stream_count = 0;
    result.cancelled = true;
    xSemaphoreGive(lock);
}

void conversation_client_release(void)
{
    if (!lock) return;
    xSemaphoreTake(lock, portMAX_DELAY);
    if (state == JOB_DONE) {
        free(response_data);
        response_data = NULL;
        state = JOB_IDLE;
    }
    xSemaphoreGive(lock);
}

void conversation_client_settings(conversation_settings_t *output)
{
    if (!lock) { *output = settings; return; }
    xSemaphoreTake(lock, portMAX_DELAY);
    *output = settings;
    xSemaphoreGive(lock);
}
esp_err_t conversation_client_set_tone(const char *tone)
{
    if(!tone || (strcmp(tone,"warm") && strcmp(tone,"calm") && strcmp(tone,"cheerful") && strcmp(tone,"direct")))return ESP_ERR_INVALID_ARG;
    if(!lock || !worker)return ESP_ERR_INVALID_STATE;
    xSemaphoreTake(lock,portMAX_DELAY);
    if(state!=JOB_IDLE){xSemaphoreGive(lock);return ESP_ERR_INVALID_STATE;}
    copy_text(settings.tone,sizeof(settings.tone),tone);++settings.revision;++tone_revision;tone_pending=true;
    xSemaphoreGive(lock);xTaskNotifyGive(worker);return ESP_OK;
}
bool conversation_client_tone_pending(void)
{
    if(!lock)return false;
    xSemaphoreTake(lock,portMAX_DELAY);bool pending=tone_pending;xSemaphoreGive(lock);return pending;
}
