# TF 动画提前交付：2026-10-21

## 下载入口

双击项目根目录 `start_animations.cmd`，访问 <http://127.0.0.1:8787/animations.html>。陪伴空间侧栏也新增“动画工坊”。启动器会复用或启动原有本地服务；电脑稍后重新开机时，再运行一次即可。没有设置定时任务。

动画和固件保存在 `public/animations/v1/`、`public/downloads/`。此为本机下载服务，没有上传到外部网站。下载页只开放实际文件存在且大小匹配的入口。

## 已交付

| 项目 | 内容 |
| --- | --- |
| 五位伙伴 | 蓝蓝、小犀、奶泡、团团、芽芽 |
| 六类动作 | 待机眨眼、认真倾听、思考、开口回应、温柔安慰、完成庆祝 |
| 总帧数 | 30 段，共 900 帧；每段 24 或 36 帧 |
| 板端数据 | 128 × 128，RGB565 小端 + alpha8；83 ms/帧，名义约 12 fps |
| 卡上文件 | `lingxi/animations-v1.lxaf`，44,237,824 字节（42.2 MiB） |
| 固件应用 | 4,102,080 字节；写入 `0x10000`；原应用分区剩 26,688 字节 |
| 可下载内容 | 完整 TF 资源 ZIP、原始 LXAF、含固件及主动更新脚本的固件 ZIP |

GIF 直接来自同一个 LXAF 的实际像素。它是预渲染 3D 风格的二维动画，不是实时 3D；说话是表情循环，不是音素同步。蓝蓝复用既有官方校徽独立层，未用生成模型重画校徽。

资源 SHA-256：`c83c1e21dabcb82d91ea1cf3caf5b745d792d84bfa52858973ebc63924c6e66f`。

固件应用 SHA-256：`cb48d94016a09189d547fa3167a88ebd0e4f07ad542746287d20cd12b83f28a5`。

ZIP 的实际大小及 SHA-256 以 `public/animations/v1/manifest.json` 为准。固件 ZIP 和其中 `.bin` 的校验值不同；更新脚本自动读取包内 `SHA256SUMS.txt` 校验 `.bin`。

## 第一次使用

完整步骤见 [安装指南](TF_ANIMATION_INSTALL_GUIDE_20261021.md)。先更新配套固件，原无卡微动效固件不会直接识别新动画。

有读卡器：把完整资源包解压出的 `lingxi` 文件夹复制到 FAT32 卡根目录，断电后插卡启动。卡内已有同名文件先备份。

免读卡器：电脑保持灵犀服务和既有调试网络运行；更新固件并断电插卡后，手机连接 `LingXi-922C`，打开 <http://192.168.4.1/>，点击“从电脑安装动画”，等待“动画已就绪”。手机提示无互联网正常；板子仍用已配置的联网 Wi-Fi 向电脑接收文件。

只更新应用，保留 NVS 与分区表；固件不会格式化 TF 卡。下载失败保留原有效动画。缺卡、文件不完整或缓存不足时回退内置形象。

## 当前实装范围

待机和思考自动播放，目标调度间隔 83 ms。语音回应使用提前预取到 PSRAM 的小头像，每 250 ms 至多绘制一次；单次绘制超过 10 ms 则暂停本次声音期间的头像动画，20 px 回复文字保持静止。录音时保持姿态并停止新的读卡。

安慰和庆祝已制作、打包并可预览，尚未自动连接情绪与任务完成事件。庆祝素材带单次播放标志。上述帧率和音频保护是实现目标，真实卡与 LCD/I2S 并发效果仍需首次实板测试。

## 验证记录及边界

- ESP-IDF 5.4.4 最终构建通过，启用 FAT32 长文件名，应用尺寸通过原分区门槛。
- 独立 Windows C reader 使用 BCrypt SHA-256，核验实际 30 段包的 body SHA、全部 CRC32、首末帧边界；重复 ID、重叠、溢出、超帧数、保留字与截断输入被拒绝。
- 五位伙伴使用同一个 C LCD 绘制器渲染通过；无卡回退、局部刷新等价、回应正文静止检查通过。总览在 `tmp/tf-ui-preview/tf-five-avatars.png`。
- 更新脚本在真实最终应用上通过 `-WhatIf` 检查及 esptool 4.11 镜像检查，匹配 SHA；该模式未打开串口。
- HTTP 静态路由已有七项回归测试通过；大资源使用 128 KiB 分块发送。真实下载的 HEAD 大小及完整 GET SHA 校验记录在 `tmp/tf-http-verification-20261021.json`。
- 网页已核对角色与动作切换、实际 GIF 载入、资源与固件下载入口。未进行用户真实 TF 卡挂载、板端 Wi-Fi 写卡、帧率、声音并发或功耗测试。

本轮未烧录板子，也未读取、格式化或写入用户的 TF 卡。

## 复现入口

资源生成：`tools/build_tf_animation_pack.py`，依赖 Pillow 和主机 GCC；来源及提示词见 `firmware/box_audio_ram/assets/tf-v1/SOURCES.md`。

固件生成方式沿用 `firmware/box_audio_ram/prepare.py`；最终应用与构建记录在 `firmware/box_audio_ram/releases/20261021-tf-animation/`。本地发布脚本：

```powershell
python tools/publish_tf_animation_release.py --firmware firmware/box_audio_ram/releases/20261021-tf-animation/lingxi-tf-animation.bin
```

该命令核对既有动画文件、生成下载固件 ZIP 并写入最终 manifest，不连接串口或卡片。
