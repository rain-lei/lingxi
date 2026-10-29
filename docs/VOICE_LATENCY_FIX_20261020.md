# 2026-10-20 对话超时与等待优化

## 根因和修复

实板显示 Conversation / ESP_ERR_TIMEOUT。原日志在17:28:26已记录设备请求HTTP200，但板端直到17:30:23才恢复轮询，接近120秒期限。

构建禁用了 CONFIG_LWIP_SO_RCVBUF；ESP-IDF 5.4.4 的 lwIP sockets.c 仅在 LWIP_SO_RCVBUF 或 LWIP_FIONREAD_LINUXMODE 启用时实现 FIONREAD。
旧逻辑的 ioctl 因此不可用，音频收包持续退化成1字节读取，数十万次TCP/HTTP调用消耗大量时间。

- conversation_client.c 和 network_probe.c 改为每次最多2048字节，按Content-Length剩余量收包，收足即退出。
- 保留响应大小和超时检查；新增阶段、HTTP状态、上传/接收字节数与耗时日志，不打印录音、密码或密钥。
- HTTP 431 的8192字节请求头修复继续保留。
- 对话请求显式使用官方支持的 reasoning_effort=low；它降低推理强度，不代表关闭思考。
- 口语回复优先一到两句，减少不必要的长回复。
- 服务返回 timings_ms，区分ASR、首字、完整生成、TTS和总耗时。

官方参数依据：https://platform.stepfun.com/docs/zh/guides/models/step-3.7-flash 。

## 本次验证

- ESP-IDF编译、COM12烧录及哈希校验通过。
- 实板重启后自动读取原NVS配置并联网，地址172.6.1.132；8192字节请求头限制保持生效。
- 测试79项通过（tmp/latency-regression-tests-20261020.log）。
- 三次真实云服务调用均成功，无音频截断：

| 请求 | 优化前单次测量 | 优化后单次测量 |
| --- | --- | --- |
| 文字问候+TTS | 6.77s | 5.28s |
| 安慰文字+TTS | 7.83s | 6.53s |
| ASR+对话+TTS | 7.00s | 5.59s |

输入提示相同，回复文本与长度存在随机差异；这是小样本观测，不代表稳定延迟或承诺。
最后一项用此前实际生成的语音回送ASR：ASR921ms、生成1344ms、TTS3281ms、总计5578ms。
它仍需区别于实体麦克风、无线传输和实体扬声器的完整验收。

实板启动日志观察到Wi-Fi RSSI=-85dBm，首次认证失败后重试成功。较弱信号可能继续影响实际传输耗时。
当前下行仍是完整LXI1音频收齐后播放，未宣称已实现边生成边播或实时全双工。

记录：tmp/fast-conversation-results-20261020.json、tmp/voice-latency-fix-boot-20261020.log。

## 无线链路的进一步实测与处理

修复后用实际麦克风录音再次测试，原校园Wi-Fi上传仍在10秒后超时；512字节ping发送8次仅成功1次（87%丢失），板端HTTP请求也在8秒超时。
因此已建立Windows临时2.4GHz热点 LingXi-Link，并通过新增的USB串口配网命令将已确认设备切到电脑近距离网络。
热点由微软per-session API启动，不覆盖用户原热点配置；电脑原有WLAN上网连接保留。

- 板子RSSI从约-85dBm改善至-22dBm，当前板子IP为192.168.137.247。
- 本地服务地址改为 http://192.168.137.1:8787 。
- 新链路8次ping全部成功，1–41ms、平均11ms；板端HTTP页面200，实测95ms。
- 实际录音约169KB已经能上传，错误响应完整返回约2.4秒。该次声学测试ASR返回“没有识别到清晰语音”，未将其计为成功对话。
- 后续用户已按要求进行人声实板测试，反馈松开BOOT后“5秒以内”开始听到回复，该轮人声对话验收通过；这是单次用户反馈，未将其当作仪器计时或固定延迟承诺。

USB命令：`LINGXI_STATUS` 查询非敏感状态；`LINGXI_CONFIG {ssid,password,server_url,device_token}` 使用与HTTP同一验证/保存规则，凭据无串口回显。
`tools/device_hotspot.ps1` 可创建临时热点，`run_companion.py` 在本机 data/local-device-link.json 已启用时自动恢复该连接，用户仍可双击 start_companion.cmd。
Microsoft API依据：https://learn.microsoft.com/en-us/uwp/api/windows.networking.networkoperators.networkoperatortetheringsessionaccesspointconfiguration 。
