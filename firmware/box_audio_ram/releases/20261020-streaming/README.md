# 2026-10-20 流式语音固件（已烧录，用户已试用）

正点原子 DNESP32S3B / BOX V1.1，ESP32-S3，16 MB Flash / 8 MB PSRAM / ES8311。
ESP-IDF 5.4.4；保留 I2S_ISR_IRAM_SAFE=y、HTTP 配网头上限 8192 字节。

新增 LXS1 分块 PCM 接收、64 KiB 队列、约 120 ms 预缓冲，边收边播；保留 LXI1 兼容。
可选设置轮询连接 750 ms、总计 1.5 秒；音频错误清队列、静音、可重试。

| 文件 | 地址 |
| --- | --- |
| bootloader.bin | 0x0 |
| partition-table.bin | 0x8000 |
| lingxi-kangaroo-streaming.bin | 0x10000 |

应用 2,089,264 字节；SHA256.json 记录全部产物校验。应用不是完整 Flash 镜像，不能写入 0x0。
已运行上一版分区的板子仅需更新 0x10000 应用，不擦除 NVS，保留已配置 Wi-Fi。

当前硬件服务地址：`http://192.168.137.1:8787`（电脑热点 LingXi-Link）。
网页配置：<http://127.0.0.1:8787/companion>。

本次构建通过。板子已重新接好，已核对 COM12 的 CH343 USB 身份，最终 2,089,264 字节应用已写入 `0x10000`，**哈希校验通过**。烧录日志：`../../../../tmp/streaming-firmware-flash-20261020.log`。
该流式版本启动检查通过：`APP_READY=True`、`BOOT_ERROR=False`，8 MB PSRAM 测试通过、ES8311 初始化成功，320000 字节录音缓冲已分配。已连上 `LingXi-Link`，本次 DHCP 地址 `192.168.137.103`，RSSI −42 dBm。证据：`../../../../tmp/streaming-firmware-boot-20261020.log`。
电脑热点已确认开启：`LingXi-Link`、2.4 GHz。用户已反馈新版实板新问题首句约 **3–7 秒**开始回复；这是一次非仪器计时的使用反馈，不是多轮统计或稳定延迟保证。回复文字框清晰度仍待改善。
之前可用版本保留在 `../20261020/`。
本机测试和使用说明见 [本次说明](../../../../docs/COMPANION_UPGRADE_20261020.md)。
