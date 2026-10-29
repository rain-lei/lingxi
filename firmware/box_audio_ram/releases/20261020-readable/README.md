# 2026-10-20 大字双字体版

正点原子 DNESP32S3B / BOX V1.1，ESP32-S3，16 MB Flash / 8 MB PSRAM / ES8311。
ESP-IDF 5.4.4，应用 3,997,280 字节，factory 分区剩 131,488 字节（约 3%）。
后续扩展必须继续核对构建大小；本次不修改分区、不擦除 NVS。

| 文件 | 地址 |
| --- | --- |
| bootloader.bin | 0x0 |
| partition-table.bin | 0x8000 |
| lingxi-readable-dualfont.bin | 0x10000 |

已使用前一版分区的板子仅需更新 0x10000 应用。文件不是完整 Flash 镜像，不可写入 0x0。
全部 SHA-256 见 SHA256.json。

## 变化

- 回答态使用 296 px 全宽白底深字卡，20 px 原生字形，四行，约 56 个汉字。
- 温柔 / 活泼语气使用资源圆体；平静 / 利落使用 Noto Sans SC。
- 20 px 双字库含 6,763 个 GB2312 汉字及 ASCII / 常用标点，无需 TF 卡。
- 回复 UTF-8 缓冲 2048 字节，长句不缩字号；播放结束后每 7 秒自动翻页。
- 播放期间停止正文和音量条重绘；保留 LXS1 流式接收和约 120 ms 音频预缓冲。
- 待机和录音保留原来的大袋鼠，回答时显示头部小伙伴缩略图。

实际 C 渲染预览：../../preview/readable-20261020/reply-font-styles.png。
字体来源和使用说明：../../../../docs/FONT_AND_STORAGE_20261020.md。
前一版已验证的流式固件保留在 ../20261020-streaming/。

本版烧录及启动验收见本轮最终日志：tmp/readable-dualfont-flash-20261020.log、tmp/readable-dualfont-boot-20261020.log（路径相对项目根目录）。
已COM12刷写并通过哈希校验；启动 PSRAM / ES8311 / 录音缓存正常、无崩溃。重启后恢复电脑热点，已知MAC的板子已重新加入 LingXi-Link，当前IP为192.168.137.18，并恢复查询本地服务协议和设置。
