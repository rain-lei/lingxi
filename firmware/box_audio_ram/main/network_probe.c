/* Wi-Fi setup portal and bounded protocol probe. No LCD calls from this task. */
#include "network_probe.h"
#include "asset_storage.h"
#include "ui_display.h"
#include "font_storage.h"
#include "button_controls.h"
#include "sdkconfig.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
static portMUX_TYPE status_lock = portMUX_INITIALIZER_UNLOCKED;
static network_status_t status = {.wifi="WiFi: disabled", .service="Local audio only"};
static bool voice_busy;
void network_probe_status(network_status_t *output)
{
    portENTER_CRITICAL(&status_lock); *output = status; portEXIT_CRITICAL(&status_lock);
}
void network_probe_voice_busy(bool busy)
{
    portENTER_CRITICAL(&status_lock); voice_busy=busy; portEXIT_CRITICAL(&status_lock);
    asset_storage_voice_busy(busy);
}
#ifdef CONFIG_LINGXI_NETWORK_ENABLE
#include <time.h>
#include "cJSON.h"
#include "esp_crt_bundle.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_wifi.h"
#include "esp_timer.h"
#include "freertos/event_groups.h"
#include "freertos/semphr.h"
#if defined(CONFIG_ESP_CONSOLE_UART) && CONFIG_ESP_CONSOLE_UART_NUM == 0
#include "driver/uart.h"
#endif
#include "nvs.h"
#include "nvs_flash.h"
#define CONNECTED BIT0
#define RECONFIGURE BIT1
#define MAX_BODY 8192
static const char *TAG="lingxi_network";
static EventGroupHandle_t events;
static SemaphoreHandle_t config_lock;
static char service_url[256], saved_ssid[33], saved_password[65], saved_token[129], device_id[48], ap_name[32];
static httpd_handle_t portal;
static esp_event_handler_instance_t wifi_handler, ip_handler;
static void update_status(const char *wifi, const char *service)
{
    portENTER_CRITICAL(&status_lock);
    if(wifi) snprintf(status.wifi,sizeof(status.wifi),"%s",wifi);
    if(service) snprintf(status.service,sizeof(status.service),"%s",service);
    ++status.revision;
    portEXIT_CRITICAL(&status_lock);
}
bool network_probe_connected(void) { return events && (xEventGroupGetBits(events)&CONNECTED); }
bool network_probe_config(char *url,size_t size,char *id,size_t id_size,char *token,size_t token_size)
{
    if(!network_probe_connected()) return false;
    portENTER_CRITICAL(&status_lock);
    snprintf(url,size,"%s",service_url); snprintf(id,id_size,"%s",device_id);
    snprintf(token,token_size,"%s",saved_token);
    portEXIT_CRITICAL(&status_lock);
    return url[0]!=0;
}
static bool valid_url(const char *url)
{
    size_t size=strlen(url);
    if(size<8 || size>=sizeof(service_url)) return false;
    const char *host=!strncmp(url,"http://",7)?url+7:!strncmp(url,"https://",8)?url+8:NULL;
    if(!host || !*host) return false;
    for(const char *p=host;*p;++p) {
        if((unsigned char)*p<=32 || *p=='@' || *p=='?' || *p=='#' || *p=='\\') return false;
        if(*p=='/' && p[1]) return false;
    }
    return *host!='/';
}
static bool valid_token(const char *token)
{
    if(strlen(token)>128) return false;
    for(const unsigned char *p=(const unsigned char *)token;*p;++p)
        if(*p<33 || *p>126) return false;
    return true;
}
static void load_config(void)
{
    snprintf(service_url,sizeof(service_url),"%s",CONFIG_LINGXI_SERVER_URL);
    snprintf(saved_ssid,sizeof(saved_ssid),"%s",CONFIG_LINGXI_WIFI_SSID);
    snprintf(saved_password,sizeof(saved_password),"%s",CONFIG_LINGXI_WIFI_PASSWORD);
    if(valid_token(CONFIG_LINGXI_DEVICE_TOKEN))
        snprintf(saved_token,sizeof(saved_token),"%s",CONFIG_LINGXI_DEVICE_TOKEN);
    /* A build-time placeholder is never a real Wi-Fi credential. */
    if(!strcmp(saved_ssid,"compile-check")) saved_ssid[0]=0;
    nvs_handle_t nvs;
    if(nvs_open("lingxi_wifi",NVS_READONLY,&nvs)==ESP_OK) {
        size_t size=sizeof(service_url); nvs_get_str(nvs,"url",service_url,&size);
        size=sizeof(saved_ssid); nvs_get_str(nvs,"ssid",saved_ssid,&size);
        size=sizeof(saved_password); nvs_get_str(nvs,"password",saved_password,&size);
        size=sizeof(saved_token); nvs_get_str(nvs,"token",saved_token,&size);
        nvs_close(nvs);
    }
    if(!valid_token(saved_token)) saved_token[0]=0;
    size_t length=strlen(service_url);
    while(length && service_url[length-1]=='/') service_url[--length]=0;
}
static void network_event(void *arg,esp_event_base_t base,int32_t id,void *data)
{
    if(base==WIFI_EVENT && id==WIFI_EVENT_STA_START) {
        if(saved_ssid[0]) esp_wifi_connect();
    } else if(base==WIFI_EVENT && id==WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *event=data;
        xEventGroupClearBits(events,CONNECTED);
        portENTER_CRITICAL(&status_lock); status.provisioning=true; portEXIT_CRITICAL(&status_lock);
        char text[40];
        snprintf(text,sizeof(text),"Setup: %s",ap_name);
        update_status(text,"Setup: 192.168.4.1");
        ESP_LOGW(TAG,"Wi-Fi disconnected, reason %u; setup portal remains available",event->reason);
    } else if(base==IP_EVENT && id==IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event=data;
        char address[40]; snprintf(address,sizeof(address),"WiFi: " IPSTR,IP2STR(&event->ip_info.ip));
        portENTER_CRITICAL(&status_lock); status.provisioning=false; portEXIT_CRITICAL(&status_lock);
        update_status(address,"API: checking...");
        ESP_LOGI(TAG,"Station address: " IPSTR,IP2STR(&event->ip_info.ip));
        xEventGroupSetBits(events,CONNECTED);
    }
}
static const char SETUP_PAGE[]=
"<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
"<title>小犀连接设置</title><style>body{font:16px system-ui;background:#eff7ff;color:#183f67;margin:0;padding:24px}main{max-width:460px;margin:20px auto;background:white;padding:28px;border-radius:28px;box-shadow:0 20px 60px #24568615}h1{font-size:26px}label{display:block;margin:18px 0 6px}input,button{font:inherit;width:100%;box-sizing:border-box;padding:13px;border:1px solid #d3e4f6;border-radius:13px}button{margin-top:22px;color:white;background:#227ed7;border:0}p{line-height:1.7}small{color:#637e99}#out{white-space:pre-wrap}</style>"
"<main><h1>让小犀连上你</h1><p>填写电脑与小犀共用的 2.4 GHz Wi-Fi，再填写电脑的灵犀服务地址。</p>"
"<form id='f'><label>Wi-Fi 名称</label><input name='ssid' maxlength='32' required autocomplete='off'><label>Wi-Fi 密码</label><input name='password' type='password' maxlength='64' autocomplete='new-password'><small>同名 Wi-Fi 留空保留现有密码；更换网络时请重新填写。</small>"
"<label>电脑服务地址</label><input name='server_url' required placeholder='http://192.168.1.100:8787' autocomplete='off'>"
"<label>设备配对令牌（可选）</label><input name='device_token' type='password' maxlength='128' autocomplete='new-password' placeholder='留空保留现有令牌'><small>仅填写灵犀服务的设备令牌，不要填写模型 API 密钥。</small><button>保存并连接</button></form>"
"<p id='out'></p><small>校园网若需要网页认证，请改用手机 2.4 GHz 热点。保存后将手机切回原网络。声音、语气、角色可在电脑控制台切换。</small>"
"<hr><h2>给小伙伴换上动画</h2><p>插入 FAT32 TF 卡，保持电脑服务开启，连接好 Wi-Fi 后点击安装。只下载校验后的动画包，安装时请先暂停对话。</p>"
"<button type='button' id='install'>从电脑安装动画</button><p id='assets'>正在读取 TF 卡状态…</p><small>不会格式化 TF 卡。中断安装会保留原有动画；未插卡仍可正常聊天。若已设置设备令牌，请在上方令牌框填写后再安装。</small>"
"<hr><h2>让语气拥有自己的字体</h2><p>下载到 TF 卡后，切换温柔、活泼、平静或直接语气，会同步选用对应字体。没有卡或安装失败时继续使用内置字体。</p>"
"<button type='button' id='installFonts'>从电脑安装语气字体</button><p id='fontsOut'>正在读取字体状态…</p></main>"
"<script>fetch('/api/config').then(r=>r.json()).then(d=>{f.ssid.value=d.ssid;f.server_url.value=d.server_url});f.onsubmit=async e=>{e.preventDefault();out.textContent='正在保存…';try{let r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(f)))});let d=await r.json();out.textContent=d.ok?'已保存，小犀正在连接。请观察屏幕。':d.error}catch(e){out.textContent='连接暂时中断，请观察小犀屏幕。'}};"
"const labels={starting:'正在启动',no_card:'未识别到 FAT32 TF 卡',no_package:'TF 卡已就绪，等待安装',queued:'准备安装',mounting:'正在读取 TF 卡',downloading:'正在下载',verifying:'正在校验完整性',checking:'正在检查动画',ready:'动画已就绪',cache_error:'动画缓存空间不足',error:'安装未完成',card_error:'TF 卡读写失败'};"
"async function checkAssets(){try{let d=await(await fetch('/api/assets')).json();assets.textContent=(labels[d.stage]||d.stage)+(d.total_bytes?' · '+d.progress+'%':'')+(d.error?' · '+d.error:'');install.disabled=d.downloading}catch(e){assets.textContent='暂时无法读取状态，正在重试'}};"
"install.onclick=async()=>{install.disabled=true;try{let r=await fetch('/api/assets/install',{method:'POST',headers:{'Content-Type':'application/json','X-Device-Token':f.device_token.value},body:'{}'});let d=await r.json();if(!r.ok)assets.textContent=d.error;else checkAssets()}catch(e){assets.textContent='请求未完成，请刷新状态后重试'}install.disabled=false};checkAssets();setInterval(checkAssets,2000);"
"async function checkFonts(){try{let d=await(await fetch('/api/fonts')).json();fontsOut.textContent=(d.cached?'当前字体：'+d.name:(labels[d.stage]||d.stage))+(d.total_bytes?' · '+Math.floor(d.bytes_received*100/d.total_bytes)+'%':'')+(d.error?' · '+d.error:'');installFonts.disabled=d.downloading}catch(e){fontsOut.textContent='暂时无法读取字体状态'}};"
"installFonts.onclick=async()=>{installFonts.disabled=true;try{let r=await fetch('/api/fonts/install',{method:'POST',headers:{'Content-Type':'application/json','X-Device-Token':f.device_token.value},body:'{}'});let d=await r.json();if(!r.ok)fontsOut.textContent=d.error;else checkFonts()}catch(e){fontsOut.textContent='请求未完成，请刷新后重试'}installFonts.disabled=false};checkFonts();setInterval(checkFonts,2000);</script></html>";
static esp_err_t setup_get(httpd_req_t *req)
{
    httpd_resp_set_type(req,"text/html; charset=utf-8");
    httpd_resp_set_hdr(req,"Cache-Control","no-store");
    esp_err_t error=httpd_resp_send(req,SETUP_PAGE,HTTPD_RESP_USE_STRLEN);
    if(error==ESP_OK)ESP_LOGI(TAG,"Setup page served; request header limit %d bytes",CONFIG_HTTPD_MAX_REQ_HDR_LEN);
    return error;
}
static esp_err_t config_get(httpd_req_t *req)
{
    cJSON *value=cJSON_CreateObject();
    if(!value) return ESP_ERR_NO_MEM;
    portENTER_CRITICAL(&status_lock);
    char url[256],ssid[33]; snprintf(url,sizeof(url),"%s",service_url); snprintf(ssid,sizeof(ssid),"%s",saved_ssid);
    bool token_configured=saved_token[0]!=0;
    portEXIT_CRITICAL(&status_lock);
    cJSON_AddStringToObject(value,"ssid",ssid); cJSON_AddStringToObject(value,"server_url",url);
    cJSON_AddStringToObject(value,"device_id",device_id); cJSON_AddBoolToObject(value,"connected",network_probe_connected());
    cJSON_AddBoolToObject(value,"device_token_configured",token_configured);
    char *text=cJSON_PrintUnformatted(value); cJSON_Delete(value);
    if(!text) return ESP_ERR_NO_MEM;
    httpd_resp_set_type(req,"application/json"); httpd_resp_set_hdr(req,"Cache-Control","no-store");
    esp_err_t err=httpd_resp_send(req,text,HTTPD_RESP_USE_STRLEN); free(text); return err;
}
static esp_err_t bad_config(httpd_req_t *req,const char *message)
{
    httpd_resp_set_status(req,"400 Bad Request"); httpd_resp_set_type(req,"application/json");
    return httpd_resp_send(req,message,HTTPD_RESP_USE_STRLEN);
}
/* One validator/save path for HTTP and USB/UART. Returned errors contain no input. */
static const char *save_config_inner(const char *body)
{
    if(!body || !body[0] || strlen(body)>1024) return "{\"error\":\"Request too large\"}";
    cJSON *value=cJSON_ParseWithLengthOpts(body,strlen(body)+1,NULL,true);
    cJSON *ssid=cJSON_GetObjectItemCaseSensitive(value,"ssid"),*password=cJSON_GetObjectItemCaseSensitive(value,"password"),*url=cJSON_GetObjectItemCaseSensitive(value,"server_url");
    cJSON *token=cJSON_GetObjectItemCaseSensitive(value,"device_token");
    if(!cJSON_IsString(ssid)||!strlen(ssid->valuestring)||strlen(ssid->valuestring)>32
       ||!cJSON_IsString(password)||strlen(password->valuestring)>64
       ||!cJSON_IsString(url)||!valid_url(url->valuestring)
       ||(token && (!cJSON_IsString(token)||!valid_token(token->valuestring)))) {
        cJSON_Delete(value); return "{\"error\":\"Check Wi-Fi name, password, service URL and optional device token\"}";
    }
    char desired_password[65];
    snprintf(desired_password,sizeof(desired_password),"%s",password->valuestring);
    /* Updating only the server or pair token must not silently forget Wi-Fi. */
    portENTER_CRITICAL(&status_lock);
    if(!desired_password[0]&&!strcmp(saved_ssid,ssid->valuestring))
        snprintf(desired_password,sizeof(desired_password),"%s",saved_password);
    portEXIT_CRITICAL(&status_lock);
    size_t password_length=strlen(desired_password);
    bool password_valid=password_length==0 || (password_length>=8&&password_length<=63);
    if(password_length==64){
        password_valid=true;
        for(size_t i=0;i<password_length;++i)
            if(!isxdigit((unsigned char)desired_password[i]))password_valid=false;
    }
    if(!password_valid){cJSON_Delete(value);return "{\"error\":\"Wi-Fi password must have 8-63 bytes or a 64-character hex key\"}";}
    nvs_handle_t nvs; esp_err_t error=nvs_open("lingxi_wifi",NVS_READWRITE,&nvs);
    if(error==ESP_OK) {
        error=nvs_set_str(nvs,"ssid",ssid->valuestring);
        if(error==ESP_OK) error=nvs_set_str(nvs,"password",desired_password);
        if(error==ESP_OK) error=nvs_set_str(nvs,"url",url->valuestring);
        if(error==ESP_OK && token && token->valuestring[0])
            error=nvs_set_str(nvs,"token",token->valuestring);
        if(error==ESP_OK) error=nvs_commit(nvs);
        nvs_close(nvs);
    }
    if(error!=ESP_OK) { cJSON_Delete(value); return "{\"error\":\"Could not save network configuration\"}"; }
    portENTER_CRITICAL(&status_lock);
    snprintf(saved_ssid,sizeof(saved_ssid),"%s",ssid->valuestring);
    snprintf(saved_password,sizeof(saved_password),"%s",desired_password);
    snprintf(service_url,sizeof(service_url),"%s",url->valuestring);
    if(token && token->valuestring[0]) snprintf(saved_token,sizeof(saved_token),"%s",token->valuestring);
    size_t length=strlen(service_url); while(length&&service_url[length-1]=='/')service_url[--length]=0;
    portEXIT_CRITICAL(&status_lock);
    cJSON_Delete(value); xEventGroupSetBits(events,RECONFIGURE);
    return NULL;
}
static const char *save_config_json(const char *body)
{
    if(!config_lock) return "{\"error\":\"Configuration is not ready\"}";
    xSemaphoreTake(config_lock,portMAX_DELAY);
    const char *error=save_config_inner(body);
    xSemaphoreGive(config_lock);
    return error;
}
static esp_err_t config_post(httpd_req_t *req)
{
    if(req->content_len<=0 || req->content_len>1024) return bad_config(req,"{\"error\":\"Request too large\"}");
    char body[1025]; size_t used=0;
    while(used<(size_t)req->content_len) {
        int count=httpd_req_recv(req,body+used,req->content_len-used);
        if(count<=0) return ESP_FAIL;
        used+=count;
    }
    body[used]=0;
    const char *error=save_config_json(body);
    if(error) return bad_config(req,error);
    httpd_resp_set_type(req,"application/json"); return httpd_resp_send(req,"{\"ok\":true}",HTTPD_RESP_USE_STRLEN);
}

#if defined(CONFIG_ESP_CONSOLE_UART) && CONFIG_ESP_CONSOLE_UART_NUM == 0
static void uart_status(void)
{
    char ssid[33],url[256],ip[16]="";
    portENTER_CRITICAL(&status_lock);
    snprintf(ssid,sizeof(ssid),"%s",saved_ssid);
    snprintf(url,sizeof(url),"%s",service_url);
    portEXIT_CRITICAL(&status_lock);
    bool connected=network_probe_connected();
    esp_netif_t *station=esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    esp_netif_ip_info_t info;
    if(connected&&station&&esp_netif_get_ip_info(station,&info)==ESP_OK)
        snprintf(ip,sizeof(ip),IPSTR,IP2STR(&info.ip));
    cJSON *value=cJSON_CreateObject();
    if(!value){printf("\nLINGXI_ACK {\"error\":\"Out of memory\"}\n");return;}
    cJSON_AddStringToObject(value,"device_id",device_id);
    cJSON_AddStringToObject(value,"ssid",ssid);
    cJSON_AddStringToObject(value,"server_url",url);
    cJSON_AddStringToObject(value,"ip",ip);
    cJSON_AddBoolToObject(value,"connected",connected);
    char *text=cJSON_PrintUnformatted(value);
    cJSON_Delete(value);
    if(text){printf("\nLINGXI_STATUS %s\n",text);free(text);fflush(stdout);}
}
static void uart_command(char *line)
{
    while(isspace((unsigned char)*line))++line;
    size_t length=strlen(line);
    while(length&&isspace((unsigned char)line[length-1]))line[--length]=0;
    if(!strcmp(line,"LINGXI_STATUS")){uart_status();return;}
    const char prefix[]="LINGXI_CONFIG ";
    if(!strncmp(line,prefix,sizeof(prefix)-1)){
        const char *error=save_config_json(line+sizeof(prefix)-1);
        printf("\nLINGXI_ACK %s\n",error?error:"{\"ok\":true}");
        fflush(stdout);
    } else if(!strncmp(line,"LINGXI_",7)) {
        printf("\nLINGXI_ACK {\"error\":\"Unknown command\"}\n");fflush(stdout);
    }
}
static void uart_config_task(void *unused)
{
    char line[1025];size_t used=0;bool overflow=false;
    uint8_t chunk[128];
    while(1){
        int count=uart_read_bytes(UART_NUM_0,chunk,sizeof(chunk),pdMS_TO_TICKS(200));
        for(int i=0;i<count;++i){
            uint8_t value=chunk[i];
            if(value=='\r')continue;
            if(value=='\n'){
                if(overflow)printf("\nLINGXI_ACK {\"error\":\"Command exceeds 1024 bytes\"}\n");
                else {line[used]=0;uart_command(line);}
                /* Never echo the command; it can contain Wi-Fi credentials. */
                memset(line,0,sizeof(line));used=0;overflow=false;fflush(stdout);
            } else if(value==0 || used>=1024) overflow=true;
            else if(!overflow)line[used++]=(char)value;
        }
    }
}
static void start_uart_config(void)
{
    if(!uart_is_driver_installed(UART_NUM_0)){
        /* The boot console already selected baud rate and pins. Preserve both,
           and leave stdout's existing UART/VFS implementation untouched. */
        esp_err_t error=uart_driver_install(UART_NUM_0,1024,0,0,NULL,0);
        if(error!=ESP_OK){ESP_LOGW(TAG,"UART setup receiver: %s",esp_err_to_name(error));return;}
    }
    if(xTaskCreate(uart_config_task,"lingxi_uart_cfg",6144,NULL,3,NULL)!=pdPASS){
        ESP_LOGW(TAG,"UART setup receiver: task allocation failed");return;
    }
    ESP_LOGI(TAG,"UART0 setup commands ready at %d baud (no input echo)",CONFIG_ESP_CONSOLE_UART_BAUDRATE);
}
#else
static void start_uart_config(void) {}
#endif
static esp_err_t assets_get(httpd_req_t *req)
{
    asset_storage_status_t assets; asset_storage_status(&assets);
    cJSON *value=cJSON_CreateObject(); if(!value)return ESP_ERR_NO_MEM;
    cJSON_AddBoolToObject(value,"mounted",assets.mounted);
    cJSON_AddBoolToObject(value,"installed",assets.installed);
    cJSON_AddBoolToObject(value,"downloading",assets.downloading);
    cJSON_AddNumberToObject(value,"bytes_received",assets.received_bytes);
    cJSON_AddNumberToObject(value,"total_bytes",assets.total_bytes);
    cJSON_AddNumberToObject(value,"progress",assets.total_bytes?(uint64_t)assets.received_bytes*100/assets.total_bytes:0);
    cJSON_AddStringToObject(value,"stage",assets.stage);
    cJSON_AddStringToObject(value,"error",assets.error);
    cJSON_AddNumberToObject(value,"package_version",assets.package_version);
    cJSON_AddNumberToObject(value,"clip_count",assets.clip_count);
    cJSON_AddNumberToObject(value,"cache_bytes",assets.cache_bytes);
    cJSON_AddNumberToObject(value,"cache_slots",assets.cache_slots);
    cJSON_AddNumberToObject(value,"cache_hits",assets.cache_hits);
    cJSON_AddNumberToObject(value,"cache_misses",assets.cache_misses);
    cJSON_AddNumberToObject(value,"loads",assets.loads);
    cJSON_AddNumberToObject(value,"last_load_ms",assets.load_ms);
    cJSON_AddNumberToObject(value,"decoded_frames",assets.decoded_frames);
    cJSON_AddNumberToObject(value,"decode_errors",assets.decode_errors);
    cJSON_AddNumberToObject(value,"last_decode_us",assets.decode_us);
    cJSON_AddNumberToObject(value,"cached_avatar",assets.cached_avatar);
    cJSON_AddNumberToObject(value,"cached_state",assets.cached_state);
    cJSON_AddNumberToObject(value,"frame_index",assets.frame_index);
    cJSON_AddNumberToObject(value,"frame_count",assets.frame_count);
    cJSON_AddNumberToObject(value,"frame_ms",assets.frame_ms);
    char *body=cJSON_PrintUnformatted(value); cJSON_Delete(value);
    if(!body)return ESP_ERR_NO_MEM;
    httpd_resp_set_type(req,"application/json");httpd_resp_set_hdr(req,"Cache-Control","no-store");
    esp_err_t error=httpd_resp_send(req,body,HTTPD_RESP_USE_STRLEN);free(body);return error;
}
static esp_err_t install_denied(httpd_req_t *req,const char *status_code,const char *body)
{
    httpd_resp_set_status(req,status_code);httpd_resp_set_type(req,"application/json");
    return httpd_resp_send(req,body,HTTPD_RESP_USE_STRLEN);
}
static esp_err_t assets_install(httpd_req_t *req)
{
    /* Browser installs are same-origin explicit button actions. No URL field is
       accepted; the resource endpoint is fixed in the storage worker. */
    char origin[180],host[120],expected[180];
    if(httpd_req_get_hdr_value_len(req,"Origin")){
        if(httpd_req_get_hdr_value_str(req,"Origin",origin,sizeof(origin))!=ESP_OK ||
           httpd_req_get_hdr_value_str(req,"Host",host,sizeof(host))!=ESP_OK)
            return install_denied(req,"403 Forbidden","{\"error\":\"Use this device setup page\"}");
        snprintf(expected,sizeof(expected),"http://%s",host);
        if(strcmp(origin,expected))return install_denied(req,"403 Forbidden","{\"error\":\"Use this device setup page\"}");
    }
    char configured[129],supplied[129]={0};
    portENTER_CRITICAL(&status_lock);snprintf(configured,sizeof(configured),"%s",saved_token);portEXIT_CRITICAL(&status_lock);
    bool authorized=!configured[0] || (httpd_req_get_hdr_value_str(req,"X-Device-Token",supplied,sizeof(supplied))==ESP_OK && !strcmp(supplied,configured));
    memset(configured,0,sizeof(configured));memset(supplied,0,sizeof(supplied));
    if(!authorized)return install_denied(req,"401 Unauthorized","{\"error\":\"Fill in your device pairing token above\"}");
    if(req->content_len!=2)return bad_config(req,"{\"error\":\"Only the fixed animation package can be installed\"}");
    char body[2];size_t used=0;
    while(used<sizeof(body)){
        int count=httpd_req_recv(req,body+used,sizeof(body)-used);
        if(count<=0)return ESP_FAIL;
        used+=count;
    }
    if(body[0]!='{' || body[1]!='}')return bad_config(req,"{\"error\":\"Invalid install request\"}");
    if(asset_storage_request_download()!=ESP_OK)
        return install_denied(req,"409 Conflict","{\"error\":\"Connect Wi-Fi and pause conversation or wait for current installation\"}");
    httpd_resp_set_status(req,"202 Accepted");httpd_resp_set_type(req,"application/json");
    return httpd_resp_send(req,"{\"ok\":true}",HTTPD_RESP_USE_STRLEN);
}

static bool local_action_authorized(httpd_req_t *req)
{
    char origin[180],host[120],expected[180];
    if(httpd_req_get_hdr_value_len(req,"Origin")){
        if(httpd_req_get_hdr_value_str(req,"Origin",origin,sizeof(origin))!=ESP_OK ||
           httpd_req_get_hdr_value_str(req,"Host",host,sizeof(host))!=ESP_OK)return false;
        snprintf(expected,sizeof(expected),"http://%s",host);
        if(strcmp(origin,expected))return false;
    }
    char configured[129],supplied[129]={0};
    portENTER_CRITICAL(&status_lock);snprintf(configured,sizeof(configured),"%s",saved_token);portEXIT_CRITICAL(&status_lock);
    bool authorized=!configured[0] || (httpd_req_get_hdr_value_str(req,"X-Device-Token",supplied,sizeof(supplied))==ESP_OK && !strcmp(supplied,configured));
    memset(configured,0,sizeof(configured));memset(supplied,0,sizeof(supplied));return authorized;
}
static esp_err_t json_response(httpd_req_t *req,cJSON *value)
{
    if(!value)return ESP_ERR_NO_MEM;
    char *text=cJSON_PrintUnformatted(value);cJSON_Delete(value);
    if(!text)return ESP_ERR_NO_MEM;
    httpd_resp_set_type(req,"application/json");httpd_resp_set_hdr(req,"Cache-Control","no-store");
    esp_err_t result=httpd_resp_send(req,text,HTTPD_RESP_USE_STRLEN);free(text);return result;
}
static esp_err_t display_get(httpd_req_t *req)
{
    ui_display_stats_t display;ui_display_stats(&display);
    cJSON *value=cJSON_CreateObject();if(!value)return ESP_ERR_NO_MEM;
    cJSON_AddNumberToObject(value,"paints",display.paints);
    cJSON_AddNumberToObject(value,"animation_frames",display.animation_frames);
    cJSON_AddNumberToObject(value,"measured_fps",display.fps_x100/100.0);
    cJSON_AddNumberToObject(value,"target_interval_ms",display.target_interval_ms);
    cJSON_AddNumberToObject(value,"paint_us",display.paint_us);
    cJSON_AddNumberToObject(value,"max_paint_us",display.max_paint_us);
    cJSON_AddNumberToObject(value,"render_us",display.render_us);
    cJSON_AddNumberToObject(value,"flush_us",display.flush_us);
    cJSON_AddNumberToObject(value,"skipped_paints",display.skipped_paints);
    cJSON_AddNumberToObject(value,"main_stack_free_bytes",display.main_stack_free_bytes);
    cJSON_AddNumberToObject(value,"avatar",display.avatar);
    cJSON_AddNumberToObject(value,"animation",display.animation);
    cJSON_AddNumberToObject(value,"ui_state",display.ui_state);
    cJSON_AddBoolToObject(value,"preview_active",display.preview_active);
    cJSON_AddNumberToObject(value,"preview_remaining_ms",display.preview_remaining_ms);
    cJSON_AddBoolToObject(value,"audio_paints_paused",display.audio_paints_paused);
    cJSON_AddBoolToObject(value,"silent_preview",true);
    button_controls_status_t controls;button_controls_status(&controls);
    cJSON *buttons=cJSON_AddObjectToObject(value,"buttons");
    if(buttons){
        cJSON_AddBoolToObject(buttons,"k1_down",controls.k1_down);cJSON_AddBoolToObject(buttons,"k2_down",controls.k2_down);
        cJSON_AddBoolToObject(buttons,"blocked",controls.blocked);cJSON_AddBoolToObject(buttons,"showcase",controls.showcase);
        cJSON_AddBoolToObject(buttons,"focus_active",controls.focus_active);
        cJSON_AddNumberToObject(buttons,"focus_remaining_seconds",controls.focus_remaining_seconds);
        cJSON_AddStringToObject(buttons,"tone",controls.tone);cJSON_AddBoolToObject(buttons,"tone_pending",controls.tone_pending);
        cJSON_AddStringToObject(buttons,"last_action",controls.last_action);
        cJSON_AddNumberToObject(buttons,"k1_short",controls.short_presses[0]);cJSON_AddNumberToObject(buttons,"k1_long",controls.long_presses[0]);
        cJSON_AddNumberToObject(buttons,"k2_short",controls.short_presses[1]);cJSON_AddNumberToObject(buttons,"k2_long",controls.long_presses[1]);
    }
    return json_response(req,value);
}
static esp_err_t display_preview(httpd_req_t *req)
{
    if(!local_action_authorized(req))return install_denied(req,"403 Forbidden","{\"error\":\"Use the device setup page and pairing token\"}");
    if(req->content_len<2 || req->content_len>160)return bad_config(req,"{\"error\":\"Invalid preview request size\"}");
    char body[161];size_t used=0;
    while(used<req->content_len){int n=httpd_req_recv(req,body+used,req->content_len-used);if(n<=0)return ESP_FAIL;used+=n;}
    body[used]=0;
    cJSON *value=cJSON_ParseWithLengthOpts(body,used+1,NULL,true);
    cJSON *avatar=cJSON_GetObjectItemCaseSensitive(value,"avatar"),*animation=cJSON_GetObjectItemCaseSensitive(value,"state"),
          *duration=cJSON_GetObjectItemCaseSensitive(value,"duration_ms");
    bool valid=cJSON_IsObject(value) && cJSON_IsNumber(avatar) && cJSON_IsNumber(animation) &&
        avatar->valuedouble==avatar->valueint && avatar->valueint>=0 && avatar->valueint<=4 &&
        animation->valuedouble==animation->valueint && animation->valueint>=0 && animation->valueint<12 &&
        (!duration || (cJSON_IsNumber(duration) && duration->valuedouble==duration->valueint && duration->valueint>=1000 && duration->valueint<=20000));
    esp_err_t error=valid?ui_display_request_preview(avatar->valueint,animation->valueint,duration?duration->valueint:8000):ESP_ERR_INVALID_ARG;
    cJSON_Delete(value);
    if(error==ESP_ERR_INVALID_ARG)return bad_config(req,"{\"error\":\"Use avatar 0..4, state 0..11 and 1000..20000 ms\"}");
    if(error!=ESP_OK)return install_denied(req,"409 Conflict","{\"error\":\"Wait for idle and install this animation first\"}");
    httpd_resp_set_status(req,"202 Accepted");httpd_resp_set_type(req,"application/json");
    return httpd_resp_send(req,"{\"ok\":true,\"silent\":true}",HTTPD_RESP_USE_STRLEN);
}
static esp_err_t fonts_get(httpd_req_t *req)
{
    font_storage_status_t fonts;font_storage_status(&fonts);
    cJSON *value=cJSON_CreateObject();if(!value)return ESP_ERR_NO_MEM;
    cJSON_AddBoolToObject(value,"mounted",fonts.mounted);cJSON_AddBoolToObject(value,"installed",fonts.installed);
    cJSON_AddBoolToObject(value,"downloading",fonts.downloading);cJSON_AddBoolToObject(value,"cached",fonts.cached);
    cJSON_AddNumberToObject(value,"active_tone",fonts.active_tone);cJSON_AddNumberToObject(value,"wanted_tone",fonts.wanted_tone);
    cJSON_AddNumberToObject(value,"cache_bytes",fonts.cache_bytes);cJSON_AddNumberToObject(value,"revision",fonts.revision);
    cJSON_AddNumberToObject(value,"bytes_received",fonts.received_bytes);cJSON_AddNumberToObject(value,"total_bytes",fonts.total_bytes);
    cJSON_AddStringToObject(value,"stage",fonts.stage);cJSON_AddStringToObject(value,"error",fonts.error);cJSON_AddStringToObject(value,"name",fonts.name);
    return json_response(req,value);
}
static esp_err_t fonts_install(httpd_req_t *req)
{
    if(!local_action_authorized(req))return install_denied(req,"403 Forbidden","{\"error\":\"Use the device setup page and pairing token\"}");
    if(req->content_len!=2)return bad_config(req,"{\"error\":\"Only the fixed verified font pack can be installed\"}");
    char body[2];size_t used=0;
    while(used<2){int n=httpd_req_recv(req,body+used,2-used);if(n<=0)return ESP_FAIL;used+=n;}
    if(body[0]!='{' || body[1]!='}')return bad_config(req,"{\"error\":\"Invalid install request\"}");
    if(asset_storage_busy())return install_denied(req,"409 Conflict","{\"error\":\"Pause conversation before installing\"}");
    if(font_storage_request_download()!=ESP_OK)return install_denied(req,"409 Conflict","{\"error\":\"Connect Wi-Fi and wait for the current font installation\"}");
    httpd_resp_set_status(req,"202 Accepted");httpd_resp_set_type(req,"application/json");
    return httpd_resp_send(req,"{\"ok\":true}",HTTPD_RESP_USE_STRLEN);
}
static esp_err_t start_portal(void)
{
    httpd_config_t config=HTTPD_DEFAULT_CONFIG(); config.stack_size=6144; config.lru_purge_enable=true;
    config.max_uri_handlers=12;
    esp_err_t err=httpd_start(&portal,&config); if(err!=ESP_OK) return err;
    httpd_uri_t root={.uri="/",.method=HTTP_GET,.handler=setup_get};
    httpd_uri_t get={.uri="/api/config",.method=HTTP_GET,.handler=config_get};
    httpd_uri_t post={.uri="/api/config",.method=HTTP_POST,.handler=config_post};
    httpd_uri_t assets={.uri="/api/assets",.method=HTTP_GET,.handler=assets_get};
    httpd_uri_t install={.uri="/api/assets/install",.method=HTTP_POST,.handler=assets_install};
    httpd_uri_t display={.uri="/api/display",.method=HTTP_GET,.handler=display_get};
    httpd_uri_t preview={.uri="/api/display/preview",.method=HTTP_POST,.handler=display_preview};
    httpd_uri_t fonts={.uri="/api/fonts",.method=HTTP_GET,.handler=fonts_get};
    httpd_uri_t font_install={.uri="/api/fonts/install",.method=HTTP_POST,.handler=fonts_install};
    if((err=httpd_register_uri_handler(portal,&root))!=ESP_OK)return err;
    if((err=httpd_register_uri_handler(portal,&get))!=ESP_OK)return err;
    if((err=httpd_register_uri_handler(portal,&post))!=ESP_OK)return err;
    if((err=httpd_register_uri_handler(portal,&assets))!=ESP_OK)return err;
    if((err=httpd_register_uri_handler(portal,&install))!=ESP_OK)return err;
    if((err=httpd_register_uri_handler(portal,&display))!=ESP_OK)return err;
    if((err=httpd_register_uri_handler(portal,&preview))!=ESP_OK)return err;
    if((err=httpd_register_uri_handler(portal,&fonts))!=ESP_OK)return err;
    return httpd_register_uri_handler(portal,&font_install);
}
typedef struct{char *data;size_t used;bool overflow;}response_t;
static esp_err_t protocol_request(esp_http_client_handle_t client,response_t *body,int *code)
{
    int64_t deadline=esp_timer_get_time()+8000000LL;
    esp_err_t error=esp_http_client_open(client,0);
    if(error!=ESP_OK)return error;
    int remaining=(deadline-esp_timer_get_time())/1000;
    if(remaining<1)return ESP_ERR_TIMEOUT;
    esp_http_client_set_timeout_ms(client,remaining);
    int64_t advertised=esp_http_client_fetch_headers(client);
    if(advertised<0)return ESP_FAIL;
    *code=esp_http_client_get_status_code(client);
    if(advertised>MAX_BODY){body->overflow=true;return ESP_ERR_INVALID_SIZE;}
    bool known_length=!esp_http_client_is_chunked_response(client)&&advertised>=0;
    while(1){
        if(known_length&&body->used==(size_t)advertised)break;
        remaining=(deadline-esp_timer_get_time())/1000;
        if(remaining<1)return ESP_ERR_TIMEOUT;
        esp_http_client_set_timeout_ms(client,remaining<1000?remaining:1000);
        size_t count=MAX_BODY-body->used;if(count>2048)count=2048;
        if(known_length&&count>(size_t)advertised-body->used)count=(size_t)advertised-body->used;
        char extra;
        int received=esp_http_client_read(client,count?body->data+body->used:&extra,count?count:1);
        if(received<0)return ESP_FAIL;
        if(received==0){if(!esp_http_client_is_complete_data_received(client))return ESP_ERR_TIMEOUT;break;}
        if(!count){body->overflow=true;return ESP_ERR_INVALID_SIZE;}
        body->used+=received;
    }
    body->data[body->used]=0;
    return ESP_OK;
}
static bool sync_https_clock(void)
{
    static bool started;
    if(time(NULL)>1704067200)return true;
    if(!started){esp_sntp_config_t config=ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");if(esp_netif_sntp_init(&config)!=ESP_OK)return false;started=true;}
    return esp_netif_sntp_sync_wait(pdMS_TO_TICKS(10000))==ESP_OK;
}
static void check_service(void)
{
    char base[256],id[48],token[160],endpoint[320],text[40];
    if(!network_probe_config(base,sizeof(base),id,sizeof(id),token,sizeof(token))||!valid_url(base)){update_status(NULL,"API: configure service URL");return;}
    snprintf(endpoint,sizeof(endpoint),"%s/api/device/protocol",base);
    if(!strncmp(base,"https://",8)&&!sync_https_clock()){update_status(NULL,"API: TLS clock unavailable");return;}
    response_t body={.data=calloc(MAX_BODY+1,1)}; if(!body.data)return;
    esp_http_client_config_t config={.url=endpoint,.timeout_ms=5000,.crt_bundle_attach=esp_crt_bundle_attach,.disable_auto_redirect=true};
    esp_http_client_handle_t client=esp_http_client_init(&config);
    if(!client){free(body.data);return;}
    esp_http_client_set_header(client,"X-Device-Id",id);
    if(token[0]){char auth[176];snprintf(auth,sizeof(auth),"Bearer %s",token);esp_http_client_set_header(client,"Authorization",auth);}
    int code=0;esp_err_t err=protocol_request(client,&body,&code);
    if(err!=ESP_OK)snprintf(text,sizeof(text),"API: %.28s",esp_err_to_name(err));
    else if(code!=200)snprintf(text,sizeof(text),"API: HTTP %d",code);
    else if(body.overflow)snprintf(text,sizeof(text),"API: response too large");
    else {
        cJSON *manifest=cJSON_ParseWithLength(body.data,body.used);
        cJSON *version=cJSON_GetObjectItemCaseSensitive(manifest,"version");
        cJSON *audio=cJSON_GetObjectItemCaseSensitive(manifest,"audio");
        cJSON *rate=cJSON_GetObjectItemCaseSensitive(audio,"sample_rate");
        cJSON *bits=cJSON_GetObjectItemCaseSensitive(audio,"bits");
        cJSON *channels=cJSON_GetObjectItemCaseSensitive(audio,"channels");
        bool valid=cJSON_IsString(version)&&!strcmp(version->valuestring,"0.4-draft")&&cJSON_IsNumber(rate)&&rate->valueint==16000&&cJSON_IsNumber(bits)&&bits->valueint==16&&cJSON_IsNumber(channels)&&channels->valueint==1;
        snprintf(text,sizeof(text),"%s",valid?"API: OK / 0.4-draft":"API: protocol mismatch");cJSON_Delete(manifest);
    }
    esp_http_client_close(client);esp_http_client_cleanup(client);free(body.data);
    if(network_probe_connected())update_status(NULL,text);
}
static void configure_station(void)
{
    wifi_config_t wifi={0};
    portENTER_CRITICAL(&status_lock);
    memcpy(wifi.sta.ssid,saved_ssid,strlen(saved_ssid));memcpy(wifi.sta.password,saved_password,strlen(saved_password));
    portEXIT_CRITICAL(&status_lock);
    esp_wifi_disconnect();
    esp_err_t err=esp_wifi_set_config(WIFI_IF_STA,&wifi);
    if(err==ESP_OK && wifi.sta.ssid[0]){update_status("WiFi: connecting...","API: waiting for Wi-Fi");esp_wifi_connect();}
}
static void network_task(void *arg)
{
    unsigned tick=0;
    while(1){
        EventBits_t bits=xEventGroupGetBits(events);
        portENTER_CRITICAL(&status_lock); bool busy=voice_busy; portEXIT_CRITICAL(&status_lock);
        if((bits&RECONFIGURE)&&!busy){xEventGroupClearBits(events,RECONFIGURE);configure_station();tick=0;}
        if(!busy && tick%15==0){if(network_probe_connected())check_service();else if(saved_ssid[0])esp_wifi_connect();}
        ++tick;vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
esp_err_t network_probe_start(void)
{
    esp_err_t err;
#define STEP(call) do{err=(call);if(err!=ESP_OK){update_status("WiFi: initialization error",esp_err_to_name(err));return err;}}while(0)
    STEP(nvs_flash_init());load_config();
    uint8_t mac[6];STEP(esp_read_mac(mac,ESP_MAC_WIFI_STA));
    snprintf(device_id,sizeof(device_id),"lingxi-%02x%02x%02x%02x%02x%02x",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
    snprintf(ap_name,sizeof(ap_name),"LingXi-%02X%02X",mac[4],mac[5]);
    STEP(esp_netif_init());err=esp_event_loop_create_default();if(err!=ESP_OK&&err!=ESP_ERR_INVALID_STATE)return err;
    if(!esp_netif_create_default_wifi_sta()||!esp_netif_create_default_wifi_ap())return ESP_ERR_NO_MEM;
    events=xEventGroupCreate();if(!events)return ESP_ERR_NO_MEM;
    config_lock=xSemaphoreCreateMutex();if(!config_lock)return ESP_ERR_NO_MEM;
    STEP(esp_event_handler_instance_register(WIFI_EVENT,ESP_EVENT_ANY_ID,network_event,NULL,&wifi_handler));
    STEP(esp_event_handler_instance_register(IP_EVENT,IP_EVENT_STA_GOT_IP,network_event,NULL,&ip_handler));
    wifi_init_config_t init=WIFI_INIT_CONFIG_DEFAULT();STEP(esp_wifi_init(&init));STEP(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    wifi_config_t ap={0},sta={0};
    snprintf((char *)ap.ap.ssid,sizeof(ap.ap.ssid),"%s",ap_name);ap.ap.ssid_len=strlen(ap_name);ap.ap.max_connection=2;ap.ap.channel=1;
    size_t pass_length=strlen(CONFIG_LINGXI_SETUP_PASSWORD);
    if(pass_length<8||pass_length>63)return ESP_ERR_INVALID_ARG;
    memcpy(ap.ap.password,CONFIG_LINGXI_SETUP_PASSWORD,pass_length);ap.ap.authmode=WIFI_AUTH_WPA2_PSK;
    memcpy(sta.sta.ssid,saved_ssid,strlen(saved_ssid));memcpy(sta.sta.password,saved_password,strlen(saved_password));
    STEP(esp_wifi_set_mode(WIFI_MODE_APSTA));STEP(esp_wifi_set_config(WIFI_IF_AP,&ap));STEP(esp_wifi_set_config(WIFI_IF_STA,&sta));
    portENTER_CRITICAL(&status_lock);status.provisioning=true;portEXIT_CRITICAL(&status_lock);
    char hint[40];snprintf(hint,sizeof(hint),"Setup: %s",ap_name);update_status(hint,"Open 192.168.4.1");
    STEP(esp_wifi_start());STEP(esp_wifi_set_ps(WIFI_PS_NONE));STEP(start_portal());
    if(xTaskCreate(network_task,"lingxi_network",8192,NULL,3,NULL)!=pdPASS)return ESP_ERR_NO_MEM;
    start_uart_config();
    ESP_LOGI(TAG,"Setup portal: %s, http://192.168.4.1; device %s; headers %d bytes",ap_name,device_id,CONFIG_HTTPD_MAX_REQ_HDR_LEN);
    return ESP_OK;
#undef STEP
}
#else
esp_err_t network_probe_start(void){return ESP_OK;}
bool network_probe_connected(void){return false;}
bool network_probe_config(char *url,size_t size,char *id,size_t id_size,char *token,size_t token_size)
{if(size)url[0]=0;if(id_size)id[0]=0;if(token_size)token[0]=0;return false;}
#endif
