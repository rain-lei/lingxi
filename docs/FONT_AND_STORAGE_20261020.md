# 圆润字体、语气与 TF 卡

## 当前方案

板子为 16 MiB Flash / 8 MiB PSRAM。字体由电脑生成常用字位图、随固件放入板载 Flash；运行不需要 TF 卡，也不需要把完整 TTF 在 ESP32 上实时解析。

资源圆体完整的 `ResourceHanRoundedCN-Medium.ttf` 已从作者官方 v0.990 简体包下载到：

`firmware/box_audio_ram/assets/fonts/ResourceHanRoundedCN-Medium.ttf`

原文件 14,423,652 字节；这份源文件可供电脑预览。板子只使用转换后的 20 px 字库，包含 6,763 个 GB2312 汉字及 ASCII / 常用标点，采用 2 bit 灰度，保持深色中等或中粗笔画。转换不能靠把原来 12 px 小字放大完成。

已在可读版固件实现的对应关系：

| 用户选择的语气 | 回复字体 |
| --- | --- |
| 温柔安慰 / 活泼元气 | Resource Han Rounded CN Medium（资源圆体） |
| 平静沉稳 / 简洁利落 | Noto Sans SC 600（思源系清晰黑体） |

语气对应的是网页里明确选择的偏好，不会根据聊天内容反复跳字。音色是另一项设置，四种声音仍可独立选择。

字体来源和许可：

- 作者仓库：<https://github.com/CyanoHao/Resource-Han-Rounded>
- 官方简体下载：<https://github.com/CyanoHao/Resource-Han-Rounded/releases/download/v0.990/RHR-CN-0.990.7z>
- 作者完整许可已保存至 `firmware/box_audio_ram/assets/ResourceHanRounded-OFL.txt`；字体部分使用 SIL OFL 1.1。

## 什么时候考虑 TF 卡

以后需要大量动画、离线音乐/音效、长录音文件或许多大字库时，可将这些资源转到 TF 卡。现在的对话、角色提示词、语气和两套裁剪字体使用板载存储，暂不需要为这些功能购买卡。

当前 app 分区约 4032 KiB，双字库会占去较多余量；后续继续扩展时应重新核对构建大小，必要时使用已有数据分区放资源。不要以完整 TTF 文件大小直接估计可用字体数量，也不要覆盖现有 NVS 配网数据。

可读版编译产物为 3,997,280 字节，当前应用分区剩 131,488 字节。字库和四行回复卡已通过实际 C 渲染预览与局部刷新等价检查。
发布文件见 `firmware/box_audio_ram/releases/20261020-readable/`；实际烧录和启动结果以本轮最终日志为准。
本版已在 COM12 烧录，哈希校验通过；启动确认 PSRAM 8MB、ES8311、320000字节录音缓存正常，APP_READY=True、BOOT_ERROR=False。
