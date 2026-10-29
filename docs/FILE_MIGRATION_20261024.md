# 项目文件归集记录

目标目录：`D:\比赛项目\lingxi-main`。

## 目录对应

| 原位置 | 归集后位置 |
| --- | --- |
| Codex 的 C 盘工作目录下 `lingxi_tf_20261023` | `firmware/local_projects/lingxi_tf_20261023/` |
| `D:\esp32\lingxi_audio_ram` | `firmware/local_projects/lingxi_audio_ram/` |
| `D:\esp32\lingxi_lcd` | `firmware/local_projects/lingxi_lcd/` |
| `D:\esp32\backups` | `backups/original_firmware/` |
| `D:\BaiduNetdiskDownload\【正点原子】ESP32 AI BOX1` | `vendor/ESP32_AI_BOX1/` |

`D:\esp32` 的源目录归管理员所有，当前用户只有读取权限；其中的文件使用完整复制，旧目录保留。C 盘固件工程和原厂资料采用移动。每项完成后核对文件数量、长度和逐文件 SHA256，清单保存在同目录 `FILE_MIGRATION_20261024.json`。

`firmware/box_audio_ram/prepare.py` 已改为默认读取项目内的原厂资料、输出到项目内的固件工程。固件 README 中现用工程和备份路径也已更新；旧日期的文档与历史日志继续保留当时路径，溯源用的原始图片路径不构成运行依赖。

## 使用

双击项目根目录 `start_companion.cmd` 启动网页服务。原有本地配置、学习记录、50 段 TF 动画和字体仍在本项目目录中。

机器上的 ESP-IDF、Python、编译器、Windows 系统字体属于安装环境；本项目继续调用现有安装。历史工程的构建缓存含旧路径，重新编译应使用新构建目录；例如在对应工程目录运行 `idf.py -B build-relocated build`，避免直接复用旧 `build`。

原厂资料、出厂备份和含本地配置的完整工程用于本机保存，已加入 Git 忽略列表。
