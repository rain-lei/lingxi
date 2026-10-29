/* The asset worker owns all TF IO. A draw borrows one verified PSRAM font. */
#include "font_storage.h"
#include "network_probe.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "mbedtls/sha256.h"

#define FONT_PATH "/sdcard/lingxi/fonts-v1.lxff"
#define FONT_PART FONT_PATH ".part"
#define FONT_OLD FONT_PATH ".previous"
#define FONT_URL "/fonts/v1/lingxi-fonts-v1.lxff"
static portMUX_TYPE guard=portMUX_INITIALIZER_UNLOCKED;
static StaticSemaphore_t lock_storage;
static SemaphoreHandle_t lock;
static font_storage_status_t status={.stage="no_card"};
static bool audio_active, install_requested, checked_card;
static lxff_info_t package;
static lxff_view_t active;
static uint8_t *cached;
static int cached_tone=-1;
static char active_path[112]=FONT_PATH;

static void stage(const char *s,const char *error)
{portENTER_CRITICAL(&guard);snprintf(status.stage,sizeof(status.stage),"%s",s);snprintf(status.error,sizeof(status.error),"%s",error?error:"");portEXIT_CRITICAL(&guard);}
static bool busy(void)
{portENTER_CRITICAL(&guard);bool b=audio_active;portEXIT_CRITICAL(&guard);return b;}
void font_storage_audio_active(bool b)
{portENTER_CRITICAL(&guard);audio_active=b;portEXIT_CRITICAL(&guard);}
void font_storage_set_mounted(bool mounted)
{
    if(!lock)lock=xSemaphoreCreateMutexStatic(&lock_storage);
    portENTER_CRITICAL(&guard);status.mounted=mounted;portEXIT_CRITICAL(&guard);
    if(!mounted){checked_card=false;stage("no_card",NULL);}
}
void font_storage_request(const char *tone)
{portENTER_CRITICAL(&guard);status.wanted_tone=lxff_tone_id(tone);portEXIT_CRITICAL(&guard);}
void font_storage_status(font_storage_status_t *out)
{if(!out)return;portENTER_CRITICAL(&guard);*out=status;portEXIT_CRITICAL(&guard);}
const lxff_view_t *font_storage_frame_begin(void)
{
    if(!lock || xSemaphoreTake(lock,0)!=pdTRUE)return NULL;
    if(!cached){xSemaphoreGive(lock);return NULL;}
    return &active;
}
void font_storage_frame_end(void){if(lock)xSemaphoreGive(lock);}
esp_err_t font_storage_request_download(void)
{
    if(busy() || !network_probe_connected())return ESP_ERR_INVALID_STATE;
    portENTER_CRITICAL(&guard);
    if(!status.mounted || status.downloading){portEXIT_CRITICAL(&guard);return ESP_ERR_INVALID_STATE;}
    status.downloading=true;status.received_bytes=0;status.total_bytes=0;install_requested=true;
    snprintf(status.stage,sizeof(status.stage),"queued");status.error[0]=0;
    portEXIT_CRITICAL(&guard);return ESP_OK;
}
static bool verify(const char *path,lxff_info_t *info,const uint8_t *expected)
{
    FILE *f=fopen(path,"rb");if(!f)return false;
    bool ok=false;uint8_t h[64],index[256],digest[32],*buffer=malloc(8192);
    if(!buffer || fseek(f,0,SEEK_END))goto done;
    long size=ftell(f);
    if(size<320 || (unsigned long)size>LXFF_MAX_FILE_BYTES || fseek(f,0,SEEK_SET) ||
       fread(h,1,64,f)!=64 || fread(index,1,256,f)!=256 ||
       !lxff_parse(h,index,256,(uint32_t)size,info))goto done;
    mbedtls_sha256_context sha,whole;mbedtls_sha256_init(&sha);mbedtls_sha256_init(&whole);
    bool failed=mbedtls_sha256_starts(&sha,0) || mbedtls_sha256_starts(&whole,0) ||
        mbedtls_sha256_update(&sha,index,256) || mbedtls_sha256_update(&whole,h,64) ||
        mbedtls_sha256_update(&whole,index,256);
    uint32_t crcs[4]={0xffffffffu,0xffffffffu,0xffffffffu,0xffffffffu};
    uint32_t offset=320;
    while(!failed && offset<(uint32_t)size){
        if(busy()){failed=true;break;}
        size_t n=(uint32_t)size-offset;if(n>8192)n=8192;
        if(fread(buffer,1,n,f)!=n || mbedtls_sha256_update(&sha,buffer,n) ||
           mbedtls_sha256_update(&whole,buffer,n)){failed=true;break;}
        for(unsigned i=0;i<4;i++){
            const lxff_font_t *font=&info->fonts[i];
            uint32_t first=offset>font->glyph_offset?offset:font->glyph_offset;
            uint32_t last=offset+n<font->alpha_offset+font->alpha_bytes?offset+n:font->alpha_offset+font->alpha_bytes;
            if(last>first)crcs[i]=lxff_crc32_update(crcs[i],buffer+first-offset,last-first);
        }
        offset+=n;if((offset&65535u)<8192)vTaskDelay(1);
    }
    if(!failed && !mbedtls_sha256_finish(&sha,digest) && !memcmp(digest,info->sha256,32) &&
       !mbedtls_sha256_finish(&whole,digest) && (!expected || !memcmp(digest,expected,32))){
        ok=true;for(unsigned i=0;i<4;i++)if((crcs[i]^0xffffffffu)!=info->fonts[i].crc32)ok=false;
    }
    mbedtls_sha256_free(&sha);mbedtls_sha256_free(&whole);
done:free(buffer);fclose(f);return ok;
}
static void activate(const lxff_info_t *info,const char *path)
{
    package=*info;snprintf(active_path,sizeof(active_path),"%s",path);
    /* Preserve the old cache until its requested replacement has passed CRC. */
    cached_tone=-1;
    portENTER_CRITICAL(&guard);status.installed=true;portEXIT_CRITICAL(&guard);
}
static esp_http_client_handle_t client_for(const char *base,const char *path,const char *token)
{
    char url[360];if(snprintf(url,sizeof(url),"%s%s",base,path)>=(int)sizeof(url))return NULL;
    esp_http_client_config_t cfg={.url=url,.timeout_ms=3000,.buffer_size=2048,
        .disable_auto_redirect=true,.crt_bundle_attach=esp_crt_bundle_attach};
    esp_http_client_handle_t c=esp_http_client_init(&cfg);
    if(c && token[0])esp_http_client_set_header(c,"X-Device-Token",token);
    return c;
}
static bool manifest(const char *base,const char *token,uint32_t *bytes,uint8_t sha[32])
{
    esp_http_client_handle_t c=client_for(base,"/fonts/v1/install.json",token);if(!c)return false;
    char data[4096];bool ok=false;int used=0;
    if(esp_http_client_open(c,0)!=ESP_OK)goto done;
    int64_t length=esp_http_client_fetch_headers(c);
    if(esp_http_client_get_status_code(c)!=200 || length<1 || length>4095)goto done;
    while(used<length && !busy()){int n=esp_http_client_read(c,data+used,(int)length-used);if(n<=0)break;used+=n;}
    if(used!=length)goto done;
    data[used]=0;
    cJSON *root=cJSON_Parse(data);if(!root)goto done;
    cJSON *d=cJSON_GetObjectItemCaseSensitive(root,"download");
    cJSON *path=cJSON_GetObjectItemCaseSensitive(d,"path"),*size=cJSON_GetObjectItemCaseSensitive(d,"bytes"),*hash=cJSON_GetObjectItemCaseSensitive(d,"sha256");
    if(cJSON_IsString(path) && !strcmp(path->valuestring,FONT_URL) && cJSON_IsNumber(size) &&
       size->valuedouble>=320 && size->valuedouble<=LXFF_MAX_FILE_BYTES &&
       size->valuedouble==(uint32_t)size->valuedouble && cJSON_IsString(hash) && strlen(hash->valuestring)==64){
        ok=true;*bytes=(uint32_t)size->valuedouble;
        for(unsigned i=0;i<32;i++){
            unsigned value=0;
            for(unsigned j=0;j<2;j++){
                char b=hash->valuestring[i*2+j];unsigned x;
                if(b>='0' && b<='9')x=b-'0';else if(b>='a' && b<='f')x=b-'a'+10;else if(b>='A' && b<='F')x=b-'A'+10;else {ok=false;x=0;}
                value=value*16+x;
            }sha[i]=value;
        }
    }
    cJSON_Delete(root);
done:esp_http_client_close(c);esp_http_client_cleanup(c);return ok;
}
static void download(void)
{
    char base[256],id[48],token[129];uint32_t expected=0;uint8_t hash[32];
    if(!network_probe_config(base,sizeof(base),id,sizeof(id),token,sizeof(token)) ||
       !manifest(base,token,&expected,hash)){stage("error","Font manifest unavailable or invalid");goto finished;}
    esp_http_client_handle_t c=client_for(base,FONT_URL,token);memset(token,0,sizeof(token));
    if(!c){stage("error","Could not allocate font client");goto finished;}
    if(esp_http_client_open(c,0)!=ESP_OK || esp_http_client_fetch_headers(c)!=expected ||
       esp_http_client_get_status_code(c)!=200){stage("error","Invalid font size or server response");goto network_done;}
    FILE *f=fopen(FONT_PART,"wb");uint8_t *buffer=malloc(8192);
    if(!f || !buffer){if(f)fclose(f);free(buffer);stage("error","Cannot write font temporary file");goto network_done;}
    portENTER_CRITICAL(&guard);status.total_bytes=expected;portEXIT_CRITICAL(&guard);stage("downloading",NULL);
    uint32_t used=0;int64_t deadline=esp_timer_get_time()+180000000LL;
    while(used<expected && !busy() && esp_timer_get_time()<deadline){
        int n=esp_http_client_read(c,(char*)buffer,expected-used>8192?8192:expected-used);
        if(n<=0 || fwrite(buffer,1,n,f)!=(size_t)n)break;
        used+=n;
        portENTER_CRITICAL(&guard);status.received_bytes=used;portEXIT_CRITICAL(&guard);vTaskDelay(1);
    }
    free(buffer);bool complete=used==expected && !fflush(f) && !fsync(fileno(f));if(fclose(f))complete=false;
    if(!complete){stage("error",busy()?"Audio started; font install paused safely":"Font transfer interrupted; previous retained");goto network_done;}
    stage("verifying",NULL);lxff_info_t checked;
    if(!verify(FONT_PART,&checked,hash)){stage("error","Font checksum failed; previous retained");goto network_done;}
    bool old=false;
    if(!strcmp(active_path,FONT_PATH) && status.installed){remove(FONT_OLD);if(rename(FONT_PATH,FONT_OLD)){stage("error","Cannot preserve previous font");goto network_done;}old=true;}
    else if(access(FONT_PATH,F_OK)==0 && remove(FONT_PATH)){stage("error","Cannot replace invalid font");goto network_done;}
    if(rename(FONT_PART,FONT_PATH)){if(old)rename(FONT_OLD,FONT_PATH);stage("error","Cannot activate font; previous retained");goto network_done;}
    activate(&checked,FONT_PATH);stage("ready",NULL);
network_done:esp_http_client_close(c);esp_http_client_cleanup(c);remove(FONT_PART);
finished:memset(token,0,sizeof(token));portENTER_CRITICAL(&guard);status.downloading=false;portEXIT_CRITICAL(&guard);
}
static void load_wanted(void)
{
    unsigned tone;portENTER_CRITICAL(&guard);tone=status.wanted_tone;portEXIT_CRITICAL(&guard);
    if(cached_tone==(int)tone)return;
    const lxff_font_t *font=&package.fonts[tone];size_t bytes=font->glyph_bytes+font->alpha_bytes;
    FILE *f=fopen(active_path,"rb");if(!f)return;
    uint8_t *data=heap_caps_malloc(bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!data){fclose(f);stage("cache_wait","Not enough PSRAM; keeping current font");return;}
    size_t used=0;bool ok=!fseek(f,font->glyph_offset,SEEK_SET);uint32_t crc=0xffffffffu;
    while(ok && used<bytes && !busy()){
        size_t n=bytes-used;if(n>8192)n=8192;
        if(fread(data+used,1,n,f)!=n){ok=false;break;}
        crc=lxff_crc32_update(crc,data+used,n);used+=n;if((used&65535u)<8192)vTaskDelay(1);
    }
    fclose(f);lxff_view_t view={.glyphs=data,.alpha=data+font->glyph_bytes,.font=*font};
    if(!ok || used!=bytes || (crc^0xffffffffu)!=font->crc32 || !lxff_validate_view(&view)){free(data);return;}
    portENTER_CRITICAL(&guard);bool stale=status.wanted_tone!=tone;portEXIT_CRITICAL(&guard);
    if(stale){free(data);return;}
    xSemaphoreTake(lock,portMAX_DELAY);uint8_t *previous=cached;cached=data;active=view;cached_tone=tone;xSemaphoreGive(lock);free(previous);
    portENTER_CRITICAL(&guard);status.cached=true;status.active_tone=tone;status.cache_bytes=bytes;
    status.revision++;snprintf(status.name,sizeof(status.name),"%s",font->name);portEXIT_CRITICAL(&guard);stage("ready",NULL);
}
void font_storage_worker_poll(bool recording)
{
    if(recording || busy() || !lock || !status.mounted)return;
    if(!checked_card){
        lxff_info_t checked;
        if(verify(FONT_PATH,&checked,NULL)){activate(&checked,FONT_PATH);stage("ready",NULL);checked_card=true;}
        else if(busy())return;
        else if(verify(FONT_OLD,&checked,NULL)){activate(&checked,FONT_OLD);stage("ready","Recovered previous font");checked_card=true;}
        else if(busy())return;
        else {checked_card=true;stage("no_package","Install the optional four-tone font pack");}
    }
    portENTER_CRITICAL(&guard);bool install=install_requested;install_requested=false;portEXIT_CRITICAL(&guard);
    if(install)download();
    if(status.installed && !busy() && !status.downloading)load_wanted();
}
