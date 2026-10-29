/* Optional TF assets. The worker alone owns card IO; UI reads a locked cache.
   No format, no arbitrary download URL, and no SD reads on the audio path. */
#include "asset_storage.h"
#include "lxaf_format.h"
#include "network_probe.h"
#include "font_storage.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#include "driver/spi_master.h"
#include "driver/sdspi_host.h"
#include "esp_crt_bundle.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_vfs_fat.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "mbedtls/sha256.h"

#define ASSET_PATH "/sdcard/lingxi/animations-v1.lxaf"
#define ASSET_PART ASSET_PATH ".part"
#define ASSET_OLD ASSET_PATH ".previous"
static const char *TAG="lingxi_assets";
static portMUX_TYPE guard=portMUX_INITIALIZER_UNLOCKED;
static asset_storage_status_t status={.stage="starting"};
static StaticSemaphore_t cache_lock_storage;
static SemaphoreHandle_t cache_lock;
static sdmmc_card_t *card;
static bool bus_ready, audio_active, voice_busy, install_requested;
static unsigned wanted_avatar, wanted_state;
#define CACHE_SLOTS 4u
#define CACHE_BUDGET (4u * 1024u * 1024u)
#define PSRAM_RESERVE (1200u * 1024u)
typedef struct {
    uint8_t *bytes;
    lxaf_clip_t clip;
    uint32_t generation, touched;
} cache_entry_t;
static cache_entry_t cache[CACHE_SLOTS];
static uint32_t cache_bytes, cache_generation;
/* These buffers belong to the sole UI task, never to the storage worker. */
static uint8_t *display_pixels, *decode_pixels;
static int display_avatar=-1, display_state=-1;
static unsigned display_frame;
static uint32_t display_generation, play_since;
static uint32_t displayed_since;
static unsigned play_avatar=99, play_state=99;
static bool play_ready;
static lxaf_info_t package;
static char active_path[112]=ASSET_PATH;

static void stage(const char *value, const char *error)
{
    portENTER_CRITICAL(&guard);
    snprintf(status.stage,sizeof(status.stage),"%s",value);
    snprintf(status.error,sizeof(status.error),"%s",error?error:"");
    portEXIT_CRITICAL(&guard);
}
void asset_storage_status(asset_storage_status_t *output)
{ portENTER_CRITICAL(&guard); *output=status; portEXIT_CRITICAL(&guard); }
void asset_storage_audio_active(bool value)
{ portENTER_CRITICAL(&guard); audio_active=value; portEXIT_CRITICAL(&guard); font_storage_audio_active(value); }
void asset_storage_voice_busy(bool value)
{ portENTER_CRITICAL(&guard); voice_busy=value; portEXIT_CRITICAL(&guard); }
static bool busy(void)
{
    portENTER_CRITICAL(&guard); bool value=audio_active||voice_busy; portEXIT_CRITICAL(&guard);
    return value;
}
bool asset_storage_busy(void) { return busy(); }
static bool audio_busy(void)
{ portENTER_CRITICAL(&guard); bool value=audio_active; portEXIT_CRITICAL(&guard); return value; }
static esp_err_t mount_card(void)
{
    if(status.mounted)return ESP_OK;
    if(card){esp_vfs_fat_sdcard_unmount("/sdcard",card);card=NULL;}
    if(!bus_ready){
        spi_bus_config_t bus={.mosi_io_num=16,.miso_io_num=15,.sclk_io_num=7,
            .quadwp_io_num=-1,.quadhd_io_num=-1,.max_transfer_sz=8192};
        esp_err_t error=spi_bus_initialize(SPI2_HOST,&bus,SPI_DMA_CH_AUTO);
        if(error!=ESP_OK && error!=ESP_ERR_INVALID_STATE)return error;
        bus_ready=true;
    }
    sdmmc_host_t host=SDSPI_HOST_DEFAULT(); host.slot=SPI2_HOST;host.max_freq_khz=10000;
    sdspi_device_config_t device=SDSPI_DEVICE_CONFIG_DEFAULT();
    device.gpio_cs=17;device.host_id=SPI2_HOST;
    esp_vfs_fat_mount_config_t config={.format_if_mount_failed=false,.max_files=4,.allocation_unit_size=16384};
    esp_err_t error=esp_vfs_fat_sdspi_mount("/sdcard",&host,&device,&config,&card);
    if(error!=ESP_OK){stage("no_card","TF card missing or FAT32 unreadable");return error;}
    portENTER_CRITICAL(&guard);status.mounted=true;portEXIT_CRITICAL(&guard);
    if(mkdir("/sdcard/lingxi",0775) && errno!=EEXIST){stage("card_error","Could not create LingXi folder");return ESP_FAIL;}
    font_storage_set_mounted(true);
    return ESP_OK;
}

static bool verify_file(const char *path, lxaf_info_t *info)
{
    FILE *file=fopen(path,"rb");if(!file)return false;
    bool ok=false;
    uint8_t header[64],index[LXAF_MAX_CLIPS*32u];
    /* Largest literal RLE3 frame plus directory overhead; PSRAM keeps the
       network/I2S internal heap available while an old clip stays visible. */
    uint8_t *buffer=heap_caps_malloc(LXAF_FRAME_BYTES+128u,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!buffer){fclose(file);return false;}
    if(fseek(file,0,SEEK_END))goto done;
    long size=ftell(file);
    if(size<64 || size>LXAF_MAX_FILE_BYTES || fseek(file,0,SEEK_SET))goto done;
    if(fread(header,1,64,file)!=64)goto done;
    unsigned count=(unsigned)header[14]|(unsigned)header[15]<<8;
    if(!count || count>LXAF_MAX_CLIPS || fread(index,32,count,file)!=count)goto done;
    if(!lxaf_parse(header,index,count*32u,(uint32_t)size,info))goto done;
    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    if(mbedtls_sha256_starts(&sha,0) || mbedtls_sha256_update(&sha,index,count*32u)){
        mbedtls_sha256_free(&sha);goto done;
    }
    uint32_t crcs[LXAF_MAX_CLIPS];
    for(unsigned i=0;i<count;++i)crcs[i]=0xffffffffu;
    uint32_t offset=64u+count*32u;
    bool failed=false;
    while(offset<(uint32_t)size){
        /* During boot verification, let user audio run first. During install,
           a new conversation aborts safely, retaining the previous package. */
        while(busy()){
            if(status.downloading){failed=true;break;}
            vTaskDelay(pdMS_TO_TICKS(100));
        }
        if(failed)break;
        size_t bytes=(uint32_t)size-offset; if(bytes>8192)bytes=8192;
        if(fread(buffer,1,bytes,file)!=bytes || mbedtls_sha256_update(&sha,buffer,bytes)){failed=true;break;}
        for(unsigned i=0;i<count;++i){
            const lxaf_clip_t *clip=&info->clips[i];
            uint32_t first=offset>clip->offset?offset:clip->offset;
            uint32_t last=offset+bytes<clip->offset+clip->bytes?offset+bytes:clip->offset+clip->bytes;
            if(last>first)crcs[i]=lxaf_crc32_update(crcs[i],buffer+first-offset,last-first);
        }
        offset+=bytes;
        if((offset&65535u)<8192u)vTaskDelay(1);
    }
    uint8_t digest[32];
    if(!failed && !mbedtls_sha256_finish(&sha,digest) && !memcmp(digest,info->sha256,32)){
        ok=true;
        for(unsigned i=0;i<count;++i)if((crcs[i]^0xffffffffu)!=info->clips[i].crc32)ok=false;
    }
    mbedtls_sha256_free(&sha);
    if(ok){
        uint8_t directory[LXAF_MAX_FRAMES*8u];
        for(unsigned i=0;ok && i<count;++i){
            const lxaf_clip_t *clip=&info->clips[i];
            if(!(clip->flags&LXAF_FLAG_RLE3))continue;
            size_t directory_bytes=clip->frames*8u;
            if(fseek(file,clip->offset,SEEK_SET) || fread(directory,1,directory_bytes,file)!=directory_bytes){ok=false;break;}
            uint32_t expected=directory_bytes;
            for(unsigned f=0;ok && f<clip->frames;++f){
                const uint8_t *p=directory+f*8u;
                uint32_t offset=p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;
                uint32_t bytes=p[4]|(uint32_t)p[5]<<8|(uint32_t)p[6]<<16|(uint32_t)p[7]<<24;
                while(busy() && !status.downloading)vTaskDelay(pdMS_TO_TICKS(50));
                if(busy() || offset!=expected || !bytes || bytes>LXAF_FRAME_BYTES+128u ||
                   offset>clip->bytes || bytes>clip->bytes-offset || fread(buffer,1,bytes,file)!=bytes ||
                   !lxaf_validate_rle3(buffer,bytes)){ok=false;break;}
                expected+=bytes;
                if((f&7u)==0)vTaskDelay(1);
            }
            if(expected!=clip->bytes)ok=false;
        }
    }
done:
    free(buffer);fclose(file);return ok;
}
static void invalidate_cache(void)
{
    xSemaphoreTake(cache_lock,portMAX_DELAY);
    for(unsigned i=0;i<CACHE_SLOTS;++i){free(cache[i].bytes);memset(&cache[i],0,sizeof(cache[i]));}
    cache_bytes=0;++cache_generation;
    portENTER_CRITICAL(&guard);status.cache_bytes=0;status.cache_slots=0;portEXIT_CRITICAL(&guard);
    xSemaphoreGive(cache_lock);
}
static void use_package(const lxaf_info_t *info,const char *path)
{
    invalidate_cache();
    portENTER_CRITICAL(&guard);
    package=*info; status.installed=true;
    status.package_version=info->version;status.clip_count=info->clip_count;
    portEXIT_CRITICAL(&guard);
    snprintf(active_path,sizeof(active_path),"%s",path);
}

static void download(void)
{
    stage("mounting",NULL);
    if(mount_card()!=ESP_OK)goto finished;
    char base[256],id[48],token[129],url[340];
    if(!network_probe_config(base,sizeof(base),id,sizeof(id),token,sizeof(token))){stage("error","Connect Wi-Fi before installing");goto finished;}
    snprintf(url,sizeof(url),"%s/animations/v1/lingxi-animations-v1.lxaf",base);
    esp_http_client_config_t config={.url=url,.timeout_ms=2500,.buffer_size=4096,
        .disable_auto_redirect=true,.crt_bundle_attach=esp_crt_bundle_attach};
    esp_http_client_handle_t client=esp_http_client_init(&config);
    if(!client){stage("error","Could not allocate network client");goto finished;}
    if(token[0])esp_http_client_set_header(client,"X-Device-Token",token);
    memset(token,0,sizeof(token));
    esp_err_t error=esp_http_client_open(client,0);
    int64_t length=error==ESP_OK?esp_http_client_fetch_headers(client):-1;
    int code=esp_http_client_get_status_code(client);
    if(error!=ESP_OK || code!=200 || length<64 || length>LXAF_MAX_FILE_BYTES){
        stage("error","Animation server unavailable or invalid size");goto network_done;
    }
    FILE *file=fopen(ASSET_PART,"wb");
    if(!file){stage("card_error","Could not write TF card");goto network_done;}
    uint8_t *buffer=malloc(8192);
    if(!buffer){stage("error","Not enough memory");fclose(file);goto network_done;}
    portENTER_CRITICAL(&guard);status.received_bytes=0;status.total_bytes=length;portEXIT_CRITICAL(&guard);
    stage("downloading",NULL);
    uint32_t used=0;
    /* A 60 MiB pack can exceed five minutes on an otherwise healthy TF card.
       Keep a finite total budget without rejecting sustained slow progress. */
    int64_t deadline=esp_timer_get_time()+900000000LL;
    while(used<(uint32_t)length && esp_timer_get_time()<deadline && !busy()){
        int bytes=esp_http_client_read(client,(char*)buffer,
                                      (uint32_t)length-used>8192?8192:(uint32_t)length-used);
        if(bytes<=0 || fwrite(buffer,1,bytes,file)!=(size_t)bytes)break;
        used+=bytes;
        portENTER_CRITICAL(&guard);status.received_bytes=used;portEXIT_CRITICAL(&guard);
        if((used&65535u)<8192u)vTaskDelay(1);
    }
    free(buffer);
    bool complete=used==(uint32_t)length && !fflush(file) && !fsync(fileno(file));
    if(fclose(file))complete=false;
    if(!complete){stage("error",busy()?"Audio started; install cancelled safely":
        esp_timer_get_time()>=deadline?"Download timed out; previous animation retained":
        "Transfer interrupted; previous animation retained");goto network_done;}
    stage("verifying",NULL);
    lxaf_info_t checked;
    if(!verify_file(ASSET_PART,&checked)){stage("error","Animation checksum failed; previous package retained");goto network_done;}
    /* The current file stays recoverable until the verified replacement is in
       place. A power failure between renames is recovered from .previous. */
    bool moved_old=false;
    if(!strcmp(active_path,ASSET_PATH) && status.installed){
        remove(ASSET_OLD);
        if(rename(ASSET_PATH,ASSET_OLD)){stage("card_error","Could not preserve previous animation");goto network_done;}
        moved_old=true;
    }else if(access(ASSET_PATH,F_OK)==0 && remove(ASSET_PATH)){
        stage("card_error","Could not replace invalid animation file");goto network_done;
    }
    if(rename(ASSET_PART,ASSET_PATH)){
        if(moved_old)rename(ASSET_OLD,ASSET_PATH);
        stage("card_error","Could not activate animation; previous package retained");goto network_done;
    }
    use_package(&checked,ASSET_PATH);stage("ready",NULL);
    ESP_LOGI(TAG,"Verified animation installed: %lu bytes, %u clips",(unsigned long)checked.total_size,checked.clip_count);
network_done:
    esp_http_client_close(client);esp_http_client_cleanup(client);
    remove(ASSET_PART);
finished:
    portENTER_CRITICAL(&guard);status.downloading=false;portEXIT_CRITICAL(&guard);
}

/* Only the low priority storage worker opens the card. The mutex is never
   held during IO, allocation, or LCD DMA. A 4 MiB LRU budget leaves room for
   the PCM ring, display and active TF font on this board's 8 MiB PSRAM. */
static bool core_state(unsigned state) { return state==0 || state==2 || state==3; }
static int find_cache(unsigned avatar,unsigned state)
{
    for(unsigned i=0;i<CACHE_SLOTS;++i)
        if(cache[i].bytes && cache[i].clip.avatar==avatar && cache[i].clip.state==state)return (int)i;
    return -1;
}
static void update_cache_status(void)
{
    unsigned count=0;for(unsigned i=0;i<CACHE_SLOTS;++i)if(cache[i].bytes)++count;
    portENTER_CRITICAL(&guard);status.cache_bytes=cache_bytes;status.cache_slots=count;portEXIT_CRITICAL(&guard);
}
static int evict_one(unsigned avatar,unsigned requested,bool force,bool preserve_display)
{
    int victim=-1;
    unsigned active_state;
    portENTER_CRITICAL(&guard);active_state=wanted_state;portEXIT_CRITICAL(&guard);
    for(unsigned i=0;i<CACHE_SLOTS;++i){
        if(!cache[i].bytes)continue;
        if(cache[i].clip.avatar==avatar && cache[i].clip.state==active_state)continue;
        if(preserve_display && cache[i].clip.avatar==avatar &&
           cache[i].clip.avatar==status.cached_avatar && cache[i].clip.state==status.cached_state)continue;
        bool protected=cache[i].clip.avatar==avatar &&
            (cache[i].clip.state==requested || core_state(cache[i].clip.state));
        if(protected && !force)continue;
        if(cache[i].clip.avatar==avatar && cache[i].clip.state==requested)continue;
        if(victim<0 || cache[i].touched<cache[victim].touched)victim=(int)i;
    }
    if(victim>=0){
        cache_bytes-=cache[victim].clip.bytes;free(cache[victim].bytes);
        memset(&cache[victim],0,sizeof(cache[victim]));
    }
    return victim;
}
static bool ensure_clip(unsigned avatar,unsigned state,bool requested)
{
    const lxaf_clip_t *clip=NULL;
    for(unsigned i=0;i<package.clip_count;++i)
        if(package.clips[i].avatar==avatar && package.clips[i].state==state){clip=&package.clips[i];break;}
    if(!clip || audio_busy() || status.downloading)return false;
    xSemaphoreTake(cache_lock,portMAX_DELAY);
    if(find_cache(avatar,state)>=0){xSemaphoreGive(cache_lock);return true;}
    size_t free_psram=heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    while(cache_bytes+clip->bytes>CACHE_BUDGET || free_psram<clip->bytes+PSRAM_RESERVE){
        int victim=evict_one(avatar,state,requested,true);
        /* A legacy raw clip may itself use most of the budget. V1 remains
           usable even when preserving two complete raw clips cannot fit. */
        if(victim<0 && requested)victim=evict_one(avatar,state,true,false);
        if(victim<0 || !cache_bytes)break;
        free_psram=heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    }
    bool room=cache_bytes+clip->bytes<=CACHE_BUDGET &&
        heap_caps_get_free_size(MALLOC_CAP_SPIRAM)>=clip->bytes+PSRAM_RESERVE;
    int slot=-1;
    for(unsigned i=0;i<CACHE_SLOTS;++i)if(!cache[i].bytes){slot=(int)i;break;}
    if(room && slot<0)slot=evict_one(avatar,state,requested,true);
    update_cache_status();
    xSemaphoreGive(cache_lock);
    if(!room || slot<0)return false;
    int64_t started=esp_timer_get_time();
    uint8_t *data=heap_caps_malloc(clip->bytes,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!data)return false;
    FILE *file=fopen(active_path,"rb");
    bool ok=file && !fseek(file,clip->offset,SEEK_SET);
    size_t used=0;
    while(ok && used<clip->bytes && !audio_busy() && !status.downloading){
        size_t count=clip->bytes-used;if(count>8192)count=8192;
        if(fread(data+used,1,count,file)!=count){ok=false;break;}
        used+=count;if((used&65535u)<8192u)vTaskDelay(1);
    }
    if(file)fclose(file);
    if(!ok || used!=clip->bytes ||
       (lxaf_crc32_update(0xffffffffu,data,used)^0xffffffffu)!=clip->crc32 ||
       !lxaf_validate_clip(clip,data,used)){free(data);return false;}
    xSemaphoreTake(cache_lock,portMAX_DELAY);
    cache[slot]=(cache_entry_t){.bytes=data,.clip=*clip,.generation=++cache_generation,
                              .touched=(uint32_t)(esp_timer_get_time()/1000)};
    cache_bytes+=clip->bytes;update_cache_status();
    xSemaphoreGive(cache_lock);
    portENTER_CRITICAL(&guard);++status.loads;status.load_ms=(esp_timer_get_time()-started)/1000;portEXIT_CRITICAL(&guard);
    return true;
}
static void preload(void)
{
    unsigned avatar,state;
    portENTER_CRITICAL(&guard);avatar=wanted_avatar;state=wanted_state;portEXIT_CRITICAL(&guard);
    ensure_clip(avatar,state,true);
    /* Warm the states that precede live audio. Additional reactions use the
       spare slot; replaying a warm state never resets its clip or reads SD. */
    static const unsigned priority[]={0,3,2};
    for(unsigned i=0;i<sizeof(priority)/sizeof(priority[0]) && !audio_busy();++i){
        portENTER_CRITICAL(&guard);bool changed=wanted_avatar!=avatar || wanted_state!=state;portEXIT_CRITICAL(&guard);
        if(changed || status.downloading)break;
        ensure_clip(avatar,priority[i],false);
    }
}
static void worker(void *unused)
{
    if(mount_card()==ESP_OK){
        lxaf_info_t checked;stage("checking",NULL);
        if(verify_file(ASSET_PATH,&checked)){use_package(&checked,ASSET_PATH);stage("ready",NULL);}
        else if(verify_file(ASSET_OLD,&checked)){use_package(&checked,ASSET_OLD);stage("ready","Recovered previous animation");}
        else stage("no_package","Use the install button after inserting a FAT32 card");
    }
    while(1){
        portENTER_CRITICAL(&guard);bool install=install_requested;install_requested=false;portEXIT_CRITICAL(&guard);
        if(install)download();
        if(status.installed && !audio_busy() && !status.downloading)preload();
        if(status.mounted && !busy() && !status.downloading)font_storage_worker_poll(false);
        vTaskDelay(pdMS_TO_TICKS(30));
    }
}
esp_err_t asset_storage_init(void)
{
    cache_lock=xSemaphoreCreateMutexStatic(&cache_lock_storage);
    if(!cache_lock)return ESP_ERR_NO_MEM;
    display_pixels=heap_caps_malloc(LXAF_FRAME_BYTES,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    decode_pixels=heap_caps_malloc(LXAF_FRAME_BYTES,MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT);
    if(!display_pixels || !decode_pixels){free(display_pixels);free(decode_pixels);display_pixels=decode_pixels=NULL;return ESP_ERR_NO_MEM;}
    return xTaskCreate(worker,"lingxi_tf",16384,NULL,1,NULL)==pdPASS?ESP_OK:ESP_ERR_NO_MEM;
}
esp_err_t asset_storage_request_download(void)
{
    if(!cache_lock || busy() || !network_probe_connected())return ESP_ERR_INVALID_STATE;
    portENTER_CRITICAL(&guard);
    if(status.downloading){portEXIT_CRITICAL(&guard);return ESP_ERR_INVALID_STATE;}
    status.downloading=true;status.received_bytes=0;status.total_bytes=0;install_requested=true;
    snprintf(status.stage,sizeof(status.stage),"queued");status.error[0]=0;
    portEXIT_CRITICAL(&guard);
    return ESP_OK;
}
bool asset_storage_clip_available(unsigned avatar,unsigned state)
{
    bool available=false;
    portENTER_CRITICAL(&guard);
    for(unsigned i=0;status.installed && i<package.clip_count;++i)
        if(package.clips[i].avatar==avatar && package.clips[i].state==state){available=true;break;}
    portEXIT_CRITICAL(&guard);return available;
}
bool asset_storage_avatar_available(unsigned avatar)
{ return asset_storage_clip_available(avatar,0); }
unsigned asset_storage_frame_interval(unsigned avatar,unsigned state)
{
    unsigned interval=150;
    portENTER_CRITICAL(&guard);
    for(unsigned i=0;status.installed && i<package.clip_count;++i)
        if(package.clips[i].avatar==avatar && package.clips[i].state==state){interval=package.clips[i].frame_ms;break;}
    portEXIT_CRITICAL(&guard);return interval;
}
uint32_t asset_storage_clip_duration(unsigned avatar,unsigned state)
{
    uint32_t duration=0;
    portENTER_CRITICAL(&guard);
    for(unsigned i=0;status.installed && i<package.clip_count;++i)
        if(package.clips[i].avatar==avatar && package.clips[i].state==state){
            duration=package.clips[i].frame_ms*package.clips[i].frames;break;
        }
    portEXIT_CRITICAL(&guard);return duration;
}
const uint8_t *asset_storage_frame_begin(unsigned avatar,unsigned state,uint32_t ms)
{
    portENTER_CRITICAL(&guard);wanted_avatar=avatar;wanted_state=state;portEXIT_CRITICAL(&guard);
    if(play_avatar!=avatar || play_state!=state){play_avatar=avatar;play_state=state;play_since=ms;play_ready=false;}
    const uint8_t *previous=display_avatar==(int)avatar ? display_pixels : NULL;
    if(!cache_lock || !display_pixels || xSemaphoreTake(cache_lock,0)!=pdTRUE)return previous;
    int slot=find_cache(avatar,state);
    bool fallback=slot<0;
    if(slot<0){
        portENTER_CRITICAL(&guard);++status.cache_misses;portEXIT_CRITICAL(&guard);
        /* Keep the previous cached animation advancing while the worker
           loads the next reaction. Showing a static first pose here caused
           visible pauses at every state transition in the earlier player. */
        if(display_avatar==(int)avatar && display_state>=0)slot=find_cache(avatar,display_state);
        if(slot<0){xSemaphoreGive(cache_lock);return previous;}
    }
    cache_entry_t *entry=&cache[slot];
    if(!fallback && !play_ready){play_since=ms;play_ready=true;}
    uint32_t since=fallback?displayed_since:play_since;
    uint32_t frame=(ms-since)/entry->clip.frame_ms;
    if(entry->clip.flags&LXAF_FLAG_LOOP)frame%=entry->clip.frames;
    else if(frame>=entry->clip.frames)frame=entry->clip.frames-1;
    entry->touched=ms;
    portENTER_CRITICAL(&guard);++status.cache_hits;portEXIT_CRITICAL(&guard);
    if(display_avatar==(int)avatar && display_state==entry->clip.state &&
       display_generation==entry->generation && display_frame==frame){xSemaphoreGive(cache_lock);return display_pixels;}
    int64_t start=esp_timer_get_time();
    bool ok=lxaf_decode_frame(&entry->clip,entry->bytes,entry->clip.bytes,frame,decode_pixels,LXAF_FRAME_BYTES);
    uint32_t elapsed=esp_timer_get_time()-start;
    if(ok){
        uint8_t *swap=display_pixels;display_pixels=decode_pixels;decode_pixels=swap;
        display_avatar=avatar;display_state=entry->clip.state;display_generation=entry->generation;display_frame=frame;
        displayed_since=since;
    }
    portENTER_CRITICAL(&guard);
    if(ok)++status.decoded_frames;else ++status.decode_errors;
    status.decode_us=elapsed;status.cached_avatar=avatar;status.cached_state=entry->clip.state;
    status.frame_ms=entry->clip.frame_ms;status.frame_index=frame;status.frame_count=entry->clip.frames;
    portEXIT_CRITICAL(&guard);
    xSemaphoreGive(cache_lock);
    return ok?display_pixels:previous;
}
void asset_storage_frame_end(void) {}
const uint8_t *asset_storage_frame_current(unsigned avatar)
{ return display_avatar==(int)avatar?display_pixels:NULL; }
