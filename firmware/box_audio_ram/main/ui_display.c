/* One drawing owner, an aligned PSRAM canvas, and explicit DMA completion. */
#include "ui_display.h"
#include "sdkconfig.h"
#include <stdio.h>
#include <string.h>
#include "esp_attr.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lcd.h"
#include "asset_storage.h"
#include "font_storage.h"

static uint16_t *canvas;
static StaticSemaphore_t flush_storage;
static SemaphoreHandle_t flush_done;
static bool ready;
static ui_model_t model;
/* All rendering runs on app_main. A second complete 2 KiB reply model must
   never live on the default 3584-byte main task stack: the renderer, libc
   formatting, LCD driver and scheduler also need stack below draw(). */
static ui_model_t rendered;
static uint32_t next_tick, last_meter, last_reply_header, last_font_revision;
static unsigned last_reply_page;
static bool meter_slow;
static int displayed_external_avatar = -1;
static portMUX_TYPE stats_lock=portMUX_INITIALIZER_UNLOCKED;
static ui_display_stats_t stats;
static uint32_t fps_since, fps_frames, last_paint_ms, last_decode_count;
static bool preview_queued, preview_active;
static unsigned preview_avatar, preview_animation;
static uint32_t preview_duration, preview_until;
static unsigned queued_avatar, queued_animation;
static uint32_t queued_duration;
static unsigned ambient_animation, ambient_turn;
static uint32_t ambient_until, ambient_wait_since, next_ambient;
static uint32_t notice_until,last_stack_check;
static const char *TAG = "lingxi_ui";

static bool IRAM_ATTR flushed(esp_lcd_panel_io_handle_t io,
                              esp_lcd_panel_io_event_data_t *event, void *context)
{
    BaseType_t wake = pdFALSE;
    xSemaphoreGiveFromISR(flush_done, &wake);
    return wake == pdTRUE;
}

static uint32_t now_ms(void) { return esp_timer_get_time() / 1000; }

static unsigned current_animation(void)
{
    if(preview_active && model.state==UI_READY)return preview_animation;
    if(ambient_animation && model.state==UI_READY && !ui_scene_has_reply(&model))return ambient_animation;
    return model.state==UI_LISTENING?1:model.state==UI_THINKING?2:
           model.state==UI_PLAYING?3:model.state==UI_ERROR?4:0;
}
void ui_display_stats(ui_display_stats_t *output)
{
    if(!output)return;
    uint32_t now=now_ms();
    portENTER_CRITICAL(&stats_lock);*output=stats;
    if(now-last_paint_ms>1500)output->fps_x100=0;
    output->preview_remaining_ms=preview_active && (int32_t)(preview_until-now)>0?preview_until-now:0;
    portEXIT_CRITICAL(&stats_lock);
}
esp_err_t ui_display_request_preview(unsigned avatar,unsigned animation,uint32_t duration_ms)
{
    if(avatar>4 || animation>=12 || duration_ms<1000 || duration_ms>20000)return ESP_ERR_INVALID_ARG;
    asset_storage_status_t assets;asset_storage_status(&assets);
    if(asset_storage_busy() || assets.downloading || !asset_storage_clip_available(avatar,animation))return ESP_ERR_INVALID_STATE;
    portENTER_CRITICAL(&stats_lock);
    if(stats.ui_state!=UI_READY){portEXIT_CRITICAL(&stats_lock);return ESP_ERR_INVALID_STATE;}
    queued_avatar=avatar;queued_animation=animation;queued_duration=duration_ms;preview_queued=true;
    portEXIT_CRITICAL(&stats_lock);return ESP_OK;
}

static void draw(ui_rect_t area)
{
    if (!ready) return;
    int64_t paint_start=esp_timer_get_time();
    uint32_t ms = now_ms();
    unsigned animation=current_animation();
    /* A local silent preview is rendered on a copy. It never modifies the
       persisted companion, conversation state, or pending reply. */
    rendered=model;
    if(preview_active && model.state==UI_READY){rendered.avatar=preview_avatar;rendered.message[0]=0;}
    bool pet_visible=ui_scene_has_reply(&rendered)
        ? area.x<70 && area.y<54 && area.x+area.w>12 && area.y+area.h>0
        : area.x<138 && area.y<176 && area.x+area.w>10 && area.y+area.h>48;
    const uint8_t *frame=pet_visible?asset_storage_frame_begin(rendered.avatar,animation,ms)
                                    :asset_storage_frame_current(rendered.avatar);
    int external_avatar = frame ? rendered.avatar : -1;
    if (external_avatar != displayed_external_avatar) {
        area = (ui_rect_t){0, 0, UI_WIDTH, UI_HEIGHT};
        displayed_external_avatar = external_avatar;
    }
    ui_scene_external_frame(frame);
    const lxff_view_t *font=font_storage_frame_begin();
    ui_scene_external_font(font);
    ui_scene_draw(canvas, area, &rendered, ms);
    ui_scene_external_font(NULL);
    if(font)font_storage_frame_end();
    ui_scene_external_frame(NULL);
    if (frame) asset_storage_frame_end();
    int64_t render_done=esp_timer_get_time();
    /* Full-width strips keep both PSRAM address and length aligned to 64 bytes. */
    while (xSemaphoreTake(flush_done, 0) == pdTRUE) {}
    ESP_ERROR_CHECK(esp_lcd_panel_draw_bitmap(panel_handle, 0, area.y,
                                             UI_WIDTH, area.y + area.h,
                                             canvas + area.y * UI_WIDTH));
    /* Never change pixels while the asynchronous LCD transfer still owns them. */
    ESP_ERROR_CHECK(xSemaphoreTake(flush_done, pdMS_TO_TICKS(250)) == pdTRUE
                    ? ESP_OK : ESP_ERR_TIMEOUT);
    int64_t finish=esp_timer_get_time();
    asset_storage_status_t assets;asset_storage_status(&assets);
    uint32_t stack_free=0;
    if(!last_stack_check || ms-last_stack_check>=1000){stack_free=uxTaskGetStackHighWaterMark(NULL);last_stack_check=ms;}
    portENTER_CRITICAL(&stats_lock);
    ++stats.paints;
    if(pet_visible && frame && assets.decoded_frames!=last_decode_count){++stats.animation_frames;++fps_frames;}
    last_decode_count=assets.decoded_frames;
    stats.paint_us=finish-paint_start;stats.render_us=render_done-paint_start;stats.flush_us=finish-render_done;
    if(stats.paint_us>stats.max_paint_us)stats.max_paint_us=stats.paint_us;
    if(!fps_since)fps_since=ms;
    if(ms-fps_since>=2000){stats.fps_x100=(uint64_t)fps_frames*100000u/(ms-fps_since);fps_since=ms;fps_frames=0;}
    stats.avatar=rendered.avatar;stats.animation=animation;stats.ui_state=model.state;
    stats.preview_active=preview_active;stats.audio_paints_paused=meter_slow;
    if(stack_free)stats.main_stack_free_bytes=stack_free;
    last_paint_ms=ms;
    portEXIT_CRITICAL(&stats_lock);
}

esp_err_t ui_display_init(void)
{
    flush_done = xSemaphoreCreateBinaryStatic(&flush_storage);
    if (!flush_done) return ESP_ERR_NO_MEM;
    canvas = heap_caps_aligned_alloc(64, UI_WIDTH * UI_HEIGHT * sizeof(uint16_t),
                                     MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!canvas) return ESP_ERR_NO_MEM;
    lcd_cfg_t config = {.notify_flush_ready = flushed};
    lcd_init(config);
    if (lcd_dev.width != UI_WIDTH || lcd_dev.height != UI_HEIGHT) return ESP_ERR_NOT_SUPPORTED;
    /* A panel command drains the vendor init's queued clear-screen transfers. */
    esp_err_t error = esp_lcd_panel_mirror(panel_handle, true, false);
    if (error != ESP_OK) return error;
    ready = true;
    model.state = UI_STARTING;
    model.rounded_font = true;
#ifdef CONFIG_LINGXI_NETWORK_ENABLE
    model.network_enabled = true;
    snprintf(model.detail, sizeof(model.detail), "Wi-Fi connecting");
#endif
    draw((ui_rect_t){0, 0, UI_WIDTH, UI_HEIGHT});
    return ESP_OK;
}

void ui_display_state(ui_state_t state)
{
    if(state!=UI_READY){portENTER_CRITICAL(&stats_lock);preview_active=preview_queued=false;portEXIT_CRITICAL(&stats_lock);}
    model.state = state;
    ambient_animation=0;ambient_until=0;next_ambient=now_ms()+14000;
    asset_storage_audio_active(state == UI_LISTENING || state == UI_PLAYING);
    model.elapsed_ms = 0;
    memset(model.levels, 0, sizeof(model.levels));
    meter_slow = false;
    last_meter = 0;
    last_reply_header = 0;
    last_reply_page = 0;
    next_tick=now_ms();
    if (state == UI_READY && model.message[0]) model.message_started_ms = now_ms();
    if (state == UI_LISTENING) {
        model.message[0] = 0;
        model.microphone_silent = false;
        model.duration_ms = 10000;
    }
    draw((ui_rect_t){0, 0, UI_WIDTH, UI_HEIGHT});
}

void ui_display_network(const network_status_t *network)
{
    bool connected=!strncmp(network->wifi,"WiFi: ",6) && network->wifi[6]>='0' && network->wifi[6]<='9';
    bool online=!strcmp(network->service,"API: OK / 0.4-draft");
    if(model.wifi_connected==connected && model.service_online==online &&
       model.provisioning==network->provisioning && !strcmp(model.address,network->wifi) &&
       !strncmp(model.detail,network->service,22))return;
    model.wifi_connected = !strncmp(network->wifi, "WiFi: ", 6) &&
                            network->wifi[6] >= '0' && network->wifi[6] <= '9';
    model.service_online = !strcmp(network->service, "API: OK / 0.4-draft");
    model.provisioning = network->provisioning;
    snprintf(model.address, sizeof(model.address), "%s", network->wifi);
    snprintf(model.detail, sizeof(model.detail), "%.22s", network->service);
    if (model.state != UI_ERROR && !ui_scene_has_reply(&model)) draw((ui_rect_t){0, 0, UI_WIDTH, UI_HEIGHT});
}

void ui_display_tick(void)
{
    uint32_t now = now_ms();
    if(model.control_notice[0] && (int32_t)(now-notice_until)>=0){
        model.control_notice[0]=0;
        if(model.state==UI_READY)draw(ui_scene_has_reply(&model)?(ui_rect_t){0,210,UI_WIDTH,30}:(ui_rect_t){0,183,UI_WIDTH,32});
    }
    bool changed=false;
    portENTER_CRITICAL(&stats_lock);
    if(preview_queued){
        preview_queued=false;preview_active=true;preview_avatar=queued_avatar;preview_animation=queued_animation;
        preview_duration=queued_duration;preview_until=now+preview_duration;changed=true;
    }
    if(preview_active && (model.state!=UI_READY || (int32_t)(now-preview_until)>=0)){preview_active=false;changed=true;}
    portEXIT_CRITICAL(&stats_lock);
    if(changed){next_tick=now;draw((ui_rect_t){0,0,UI_WIDTH,UI_HEIGHT});}
    if(model.state==UI_READY && !preview_active && !ui_scene_has_reply(&model)){
        if(ambient_animation){
            asset_storage_status_t assets;asset_storage_status(&assets);
            if(!ambient_until && assets.cached_avatar==model.avatar && assets.cached_state==(int)ambient_animation)
                ambient_until=now+asset_storage_clip_duration(model.avatar,ambient_animation);
            if((ambient_until && (int32_t)(now-ambient_until)>=0) || now-ambient_wait_since>8000){
                ambient_animation=0;ambient_until=0;next_ambient=now+14000+(ambient_turn%3)*2000;
            }
        }else if(next_ambient && (int32_t)(now-next_ambient)>=0){
            unsigned reaction=(ambient_turn++&1u)?9:6;
            next_ambient=now+16000;
            if(asset_storage_clip_available(model.avatar,reaction)){
                ambient_animation=reaction;ambient_wait_since=now;ambient_until=0;
            }
        }
    }
    font_storage_status_t fonts;font_storage_status(&fonts);
    if(fonts.revision!=last_font_revision){
        last_font_revision=fonts.revision;
        if(model.state==UI_READY && ui_scene_has_reply(&model))draw((ui_rect_t){0,0,UI_WIDTH,UI_HEIGHT});
    }
    if (ui_scene_has_reply(&model) && !preview_active) {
        /* Large reply text remains still throughout audio playback. A page
           changes only after playback, at a human reading pace. */
        if (model.state != UI_READY) return;
        unsigned pages = ui_scene_reply_pages(&model);
        unsigned page = pages ? ((now - model.message_started_ms) / UI_REPLY_PAGE_MS) % pages : 0;
        if (page != last_reply_page) {
            last_reply_page = page;
            draw((ui_rect_t){0, 60, UI_WIDTH, UI_HEIGHT - 60});
        }
        /* Only the little pet breathes/blinks above a completed reply. Keep
           the large reading area still and all audio states free of repaints. */
        unsigned interval=asset_storage_frame_interval(model.avatar,current_animation());
        if (now - last_reply_header >= interval) {
            last_reply_header = now;
            draw((ui_rect_t){0, 0, 70, 54});
        }
        return;
    }
    unsigned avatar=preview_active?preview_avatar:model.avatar;
    unsigned interval=asset_storage_frame_interval(avatar,current_animation());
    portENTER_CRITICAL(&stats_lock);stats.target_interval_ms=interval;portEXIT_CRITICAL(&stats_lock);
    if ((int32_t)(now-next_tick)<0 || (model.state!=UI_READY && model.state!=UI_STARTING && model.state!=UI_THINKING))return;
    /* Deadline scheduling avoids adding a complete loop/paint duration to
       every frame. Late frames are skipped, never replayed in a burst. */
    next_tick+=interval;
    if((int32_t)(now-next_tick)>=0){next_tick=now+interval;portENTER_CRITICAL(&stats_lock);++stats.skipped_paints;portEXIT_CRITICAL(&stats_lock);}
    draw((ui_rect_t){0, 48, 144, 130});
}

void ui_display_meter(int peak, uint32_t elapsed_ms, uint32_t duration_ms)
{
    /* Wave height comes from actual PCM, never random animation. */
    memmove(model.levels, model.levels + 1, sizeof(model.levels) - 1);
    unsigned level = peak > 32767 ? 32767 : peak < 0 ? 0 : peak;
    /* A square-root display curve makes normal speech visible without changing PCM. */
    unsigned scaled = 0;
    while (scaled < 255 && scaled * scaled < level * 2) scaled++;
    model.levels[17] = scaled;
    model.elapsed_ms = elapsed_ms;
    model.duration_ms = duration_ms;
    uint32_t now = now_ms();
    if (ui_scene_has_reply(&model)) {
        /* Optional speaking clip is already in PSRAM. Only the little header
           moves; never repaint the large reply or touch SD while I2S runs. */
        unsigned interval=asset_storage_frame_interval(model.avatar,3);
        if (model.state == UI_PLAYING && !meter_slow &&
            asset_storage_avatar_available(model.avatar) && now - last_reply_header >= interval) {
            last_reply_header = now;
            int64_t start = esp_timer_get_time();
            draw((ui_rect_t){0, 0, 70, 54});
            if (esp_timer_get_time() - start > 12000) meter_slow = true;
        }
        return;
    }
    /* Cached speaking frames can animate during local playback as well.
       Capture remains static. A measured 12 ms safety budget disables live
       pet paints if this board cannot keep audio DMA fed comfortably. */
    if(model.state==UI_PLAYING && !meter_slow && asset_storage_avatar_available(model.avatar) &&
       now-last_reply_header>=asset_storage_frame_interval(model.avatar,3)){
        last_reply_header=now;
        int64_t start=esp_timer_get_time();draw((ui_rect_t){0,48,144,130});
        if(esp_timer_get_time()-start>12000)meter_slow=true;
    }
    if (meter_slow || now - last_meter < 200) return;
    last_meter = now;
    int64_t start = esp_timer_get_time();
    draw((ui_rect_t){16, 183, 288, 32});
    /* Audio has priority. Disable further live paints if this board paints slowly. */
    int64_t paint_us = esp_timer_get_time() - start;
    if (paint_us > 15000) {
        meter_slow = true;
        ESP_LOGW(TAG, "Meter paint took %lld us; keeping audio uninterrupted", paint_us);
    }
}

void ui_display_recorded(uint32_t duration_ms, bool silent)
{
    model.duration_ms = duration_ms;
    model.microphone_silent = silent;
}

void ui_display_error(const char *stage, const char *error)
{
    model.state = UI_ERROR;
    asset_storage_audio_active(false);
    snprintf(model.detail, sizeof(model.detail), "%.25s", stage);
    snprintf(model.error, sizeof(model.error), "%s", error);
    snprintf(model.message, sizeof(model.message), "%s", error);
    draw((ui_rect_t){0, 0, UI_WIDTH, UI_HEIGHT});
}

void ui_display_message(const char *message)
{
    const char *source = message ? message : "";
    size_t length = strlen(source);
    if (length >= sizeof(model.message)) {
        length = sizeof(model.message) - 1;
        while (length && ((unsigned char)source[length] & 0xc0) == 0x80) --length;
    }
    if (strlen(model.message) != length || memcmp(model.message, source, length)) {
        memcpy(model.message, source, length);
        model.message[length] = 0;
        model.message_started_ms = now_ms();
        last_reply_page = 0;
    }
    draw((ui_rect_t){0, 0, UI_WIDTH, UI_HEIGHT});
}

void ui_display_avatar(int avatar)
{
    uint8_t selected = avatar >= 0 && avatar <= 4 ? avatar : 0;
    if (selected == model.avatar) return;
    model.avatar = selected;
    draw((ui_rect_t){0, 0, UI_WIDTH, UI_HEIGHT});
}

void ui_display_tone(const char *tone)
{
    font_storage_request(tone);
    bool rounded = !tone || (strcmp(tone, "calm") && strcmp(tone, "direct"));
    if (rounded == model.rounded_font) return;
    model.rounded_font = rounded;
    if (ui_scene_has_reply(&model)) draw((ui_rect_t){0, 0, UI_WIDTH, UI_HEIGHT});
}
void ui_display_stop_preview(void)
{
    portENTER_CRITICAL(&stats_lock);preview_active=preview_queued=false;portEXIT_CRITICAL(&stats_lock);
    if(ready)draw((ui_rect_t){0,0,UI_WIDTH,UI_HEIGHT});
}
void ui_display_notice(const char *message,uint32_t duration_ms)
{
    snprintf(model.control_notice,sizeof(model.control_notice),"%s",message?message:"");
    notice_until=now_ms()+(duration_ms>10000?10000:duration_ms);
    if(model.state==UI_READY || model.state==UI_ERROR)draw((ui_rect_t){0,0,UI_WIDTH,UI_HEIGHT});
}
void ui_display_control_state(bool focus_active,uint32_t seconds,bool showcase,const char *tone)
{
    bool mode_changed=model.focus_active!=focus_active || model.showcase_mode!=showcase;
    bool changed=model.focus_active!=focus_active || model.focus_remaining_seconds!=seconds ||
                 model.showcase_mode!=showcase || strcmp(model.control_tone,tone?tone:"warm");
    model.focus_active=focus_active;model.focus_remaining_seconds=seconds;model.showcase_mode=showcase;
    snprintf(model.control_tone,sizeof(model.control_tone),"%s",tone?tone:"warm");
    if(changed && ready && model.state==UI_READY){
        if(ui_scene_has_reply(&model) && !preview_active)draw((ui_rect_t){0,210,UI_WIDTH,30});
        else{
            if(mode_changed)draw((ui_rect_t){151,151,169,27});
            draw((ui_rect_t){0,183,UI_WIDTH,57});
        }
    }
}
