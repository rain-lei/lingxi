/* K1/P0.4 and K2/P0.3 are XL9555 keys. RST and BOOT are not repurposed. */
#include "button_controls.h"
#include "button_debounce.h"
#include "asset_storage.h"
#include "font_storage.h"
#include "conversation_client.h"
#include "ui_display.h"
#include "key.h"
#include "xl9555.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include <stdio.h>
#include <string.h>

extern i2c_master_dev_handle_t xl9555_handle;
static portMUX_TYPE guard=portMUX_INITIALIZER_UNLOCKED;
static button_controls_status_t status={.tone="warm"};
static button_debounce_t keys[2];
static uint32_t next_scan,next_demo,focus_until,last_remaining=UINT32_MAX;
static unsigned action_index,demo_index;
static const char *tones[]={"warm","calm","cheerful","direct"};
static const char *tone_names[]={"温柔安慰","平静沉稳","活泼元气","简洁利落"};
static const unsigned actions[]={6,9,5,4,7,8,1,2,3,0};
static bool showcase,focus_active,focus_completion_pending;
static uint32_t now_ms(void){return esp_timer_get_time()/1000;}

static unsigned avatar_id(const char *name)
{
    static const char *names[]={"kangaroo","robot","cat","otter","sprout"};
    for(unsigned i=1;i<5;++i)if(!strcmp(name,names[i]))return i;
    return 0;
}
static void action_name(const char *name)
{portENTER_CRITICAL(&guard);snprintf(status.last_action,sizeof(status.last_action),"%s",name);portEXIT_CRITICAL(&guard);}
void button_controls_init(void)
{
    memset(keys,0,sizeof(keys));
    ui_display_control_state(false,0,false,"warm");
}
void button_controls_suspend(void)
{
    uint32_t now=now_ms();
    for(unsigned i=0;i<2;++i)button_debounce_update(&keys[i],false,false,now);
    portENTER_CRITICAL(&guard);status.blocked=true;portEXIT_CRITICAL(&guard);
    /* BOOT always takes priority, including leaving a silent display loop. */
    if(showcase){showcase=false;ui_display_stop_preview();}
}
static void play_action(unsigned avatar,unsigned *index,uint32_t duration)
{
    for(unsigned i=0;i<sizeof(actions)/sizeof(actions[0]);++i){
        unsigned animation=actions[(*index)++%(sizeof(actions)/sizeof(actions[0]))];
        if(asset_storage_clip_available(avatar,animation) &&
           ui_display_request_preview(avatar,animation,duration)==ESP_OK)return;
    }
    ui_display_notice("先安装 TF 动画，就能和我互动啦",3500);
}
static void key_action(unsigned key,button_event_t event,uint32_t now,unsigned avatar,const char *tone)
{
    if(key==0 && event==BUTTON_SHORT){play_action(avatar,&action_index,6000);action_name("interaction");}
    if(key==0 && event==BUTTON_LONG){
        showcase=!showcase;next_demo=now;
        if(!showcase)ui_display_stop_preview();
        ui_display_notice(showcase?"展示模式 · 长按 K1 返回":"回到陪伴模式",3000);
        action_name(showcase?"showcase_start":"showcase_stop");
    }
    if(key==1 && event==BUTTON_SHORT){
        unsigned selected=0;for(unsigned i=0;i<4;++i)if(!strcmp(tone,tones[i]))selected=i;
        selected=(selected+1)%4;
        if(conversation_client_set_tone(tones[selected])==ESP_OK){
            ui_display_tone(tones[selected]);
            char notice[72];snprintf(notice,sizeof(notice),"换个心情 · %s",tone_names[selected]);ui_display_notice(notice,3000);
            action_name("tone_changed");
        }
    }
    if(key==1 && event==BUTTON_LONG){
        focus_active=!focus_active;focus_completion_pending=false;
        focus_until=focus_active?now+25u*60u*1000u:0;last_remaining=UINT32_MAX;
        ui_display_notice(focus_active?"一起专注 25 分钟，我陪着你":"这段专注结束啦，休息一下吧",3500);
        action_name(focus_active?"focus_start":"focus_stop");
    }
}
void button_controls_tick(void)
{
    uint32_t now=now_ms();
    if((int32_t)(now-next_scan)<0)return;
    next_scan=now+10;
    asset_storage_status_t assets;asset_storage_status(&assets);
    font_storage_status_t fonts;font_storage_status(&fonts);
    ui_display_stats_t display;ui_display_stats(&display);
    bool allowed=!asset_storage_busy() && !assets.downloading && !fonts.downloading &&
                 display.ui_state==UI_READY && BOOT!=0;
    uint8_t reg=XL9555_INPUT_PORT0_REG,inputs=0xff;
    /* Never use vendor key_scan(): it sleeps for debounce and its I2C read
       waits forever. A broken expander must not freeze talking or animation. */
    esp_err_t read=xl9555_handle?i2c_master_transmit_receive(xl9555_handle,&reg,1,&inputs,1,2):ESP_ERR_INVALID_STATE;
    if(read!=ESP_OK)allowed=false;
    bool down[2]={!(inputs&KEY0_IO),!(inputs&KEY1_IO)};
    conversation_settings_t settings;conversation_client_settings(&settings);
    unsigned avatar=avatar_id(settings.avatar);
    for(unsigned i=0;i<2;++i){
        button_event_t event=button_debounce_update(&keys[i],down[i],allowed,now);
        if(event!=BUTTON_NONE){
            portENTER_CRITICAL(&guard);
            if(event==BUTTON_SHORT)++status.short_presses[i];else ++status.long_presses[i];
            portEXIT_CRITICAL(&guard);key_action(i,event,now,avatar,settings.tone);
        }
    }
    uint32_t remaining=focus_active && (int32_t)(focus_until-now)>0?(focus_until-now+999)/1000:0;
    if(focus_active && !remaining){
        focus_active=false;focus_completion_pending=true;action_name("focus_complete");
    }
    if(focus_completion_pending && allowed){
        focus_completion_pending=false;next_demo=now+8000;
        ui_display_notice("25 分钟完成了，给认真努力的你鼓掌",5000);ui_display_request_preview(avatar,5,6000);
    }
    if(showcase && allowed && (int32_t)(now-next_demo)>=0){
        play_action(avatar,&demo_index,7000);next_demo=now+5000;
    }
    if(remaining!=last_remaining || status.showcase!=showcase || strcmp(status.tone,settings.tone)){
        last_remaining=remaining;ui_display_control_state(focus_active,remaining,showcase,settings.tone);
    }
    bool pending=conversation_client_tone_pending();
    portENTER_CRITICAL(&guard);
    status.k1_down=down[0];status.k2_down=down[1];status.blocked=!allowed;
    status.showcase=showcase;status.focus_active=focus_active;status.focus_remaining_seconds=remaining;status.tone_pending=pending;
    snprintf(status.tone,sizeof(status.tone),"%s",settings.tone);
    portEXIT_CRITICAL(&guard);
}
void button_controls_status(button_controls_status_t *out)
{if(!out)return;portENTER_CRITICAL(&guard);*out=status;portEXIT_CRITICAL(&guard);}
