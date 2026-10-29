# 2026-10-20 无卡微动效版

适用正点原子 DNESP32S3B / ESP32S3 BOX V1.1；ESP-IDF 5.4.4。
应用 3,998,544 字节，SHA-256 见 SHA256.json；当前 factory 分区剩130,224字节。

| 文件 | 地址 |
| --- | --- |
| bootloader.bin | 0x0 |
| partition-table.bin | 0x8000 |
| lingxi-motion.bin | 0x10000 |

已在相同分区的板子上仅更新应用，不擦除 NVS。应用文件不是完整Flash镜像，不可写入0x0。

新增待机呼吸、双眨眼、漂浮光点和思考气泡；回复结束后顶部小角色有轻微动作，20px字幕保持静止。语音播放时不增加动画重绘。
使用现有六姿态和程序绘图，无新增帧包、线程或画布；此版不读取TF卡动画。

实际C渲染严格GCC编译和522组完整/局部刷新比对通过。COM12刷写哈希校验通过，启动确认8MB PSRAM、ES8311、320000字节录音缓存正常，APP_READY=True，BOOT_ERROR=False。

日志：项目根目录 tmp/motion-firmware-build-20261020.log、tmp/motion-firmware-flash-20261020.log、tmp/motion-firmware-boot-20261020.log。
动态预览：../../preview/motion-20261020/。先前双字体可读版保留在 ../20261020-readable/。
TF资源扩展方案见 ../../../../docs/ANIMATION_STORAGE_PLAN_20261020.md。
