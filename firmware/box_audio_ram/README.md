# LingXi BOX 袋鼠伙伴与语音对话

目标板：正点原子 DNESP32S3B / ESP32S3 BOX V1.1，ES8311，16 MB Flash / 8 MB PSRAM。
当前固件包含袋鼠桌宠、内存录音回放、AP 配网，以及连接本地灵犀服务的语音对话客户端。
录音上传后由电脑服务完成识别、回复与语音合成，板端显示回复并播放返回的 PCM 音频。
**2026-10-20：已配置 API Key，服务端真实对话与 ASR → 对话 → TTS 已通过；实板已切换到电脑近距离热点，修复收包超时。用户已确认实板人声测试在松开BOOT后5秒以内开始听到回复（单次反馈）。**
已有的启动、录音回放和协议检查记录见下方；“API 已连接”不代表模型服务已完成真实调用。

## v3 袋鼠伙伴

默认形象是蓝色毛绒袋鼠，保留 v2 蓝色机器人供伙伴设置切换。
袋鼠原始六格素材为 `assets/mascot-v3/kangaroo-concept.png`，按用户提供的形象参考，
使用内置 imagegen 生成：待机、眨眼、倾听、思考、开心回应、关切六种姿态。
这是一组预渲染的 3D 风格贴图，板端未运行实时 3D 引擎。

胸前 DUT 校徽使用独立的官方资源图层，随角色姿态定位，不将 AI 生成的图案作为正式校徽。
来源为大连理工大学[学校 VI 页面](https://www.dlut.edu.cn/xxgk/dxwh/xxVI.htm)
及[官网标识 SVG](https://www.dlut.edu.cn/images/logo.svg)。原图、生成提示词、打包记录及
官方资源说明见 [素材来源](assets/mascot-v3/SOURCES.md)。

`tools/pack_mascot.py --largest-component --prefix ui_kangaroo` 从六格素材提取每格主体，
移除跨格的独立尾巴残片，保留 2 像素毛绒边缘，再统一裁切、缩放和编码；原始 PNG 不修改。
每种形象为六张 128 × 128 RGB565 + alpha8 贴图，共 294912 字节，无需运行时解码 PNG。
当前袋鼠统一裁切 `(36,0,512,511)`，缩放为 `112×120`，置于贴图 `(8,4)`，
具体参数、源文件 SHA-256 和每格连通区域统计保存在 `assets/mascot-v3/pack-report.json`。

界面使用 320 × 240 RGB565 的 PSRAM 画布。固定界面文案使用 Noto Sans SC 的 4-bit 字形子集；
动态中文回复另有全部 **6763 个 GB2312 汉字**，Unicode 升序索引，12 × 16、每字 24 字节，
连续 1-bit 位图无需逐行补齐。该字库位图和索引合计 175838 字节，使用 SIL OFL 1.1，
完整许可证见 `assets/NotoSansSC-OFL.txt`；生成工具为 `tools/generate_ui_cjk.py`。
正常构建无需 TF 卡、完整字体文件或主机 Pillow。

## 本次实板验证（2026-10-20）

- 最终语音版已在 COM12 烧录，esptool 数据哈希校验通过。
- 重新上电日志确认 8 MB PSRAM、ES8311 初始化成功、320000 字节录音缓存可用。
- AP `LingXi-922C` 和 `192.168.4.1` DHCP 已启动，12 秒启动观察期间无崩溃。
- 项目最新79项测试通过；本机配置页、脚本和形象资源HTTP均为200。
- 最新真实服务调用耗时约5.3–6.5秒；实板切到电脑直连热点后8次网络探测全成功，用户反馈一次人声对话5秒以内开始回复。记录见 ../../docs/VOICE_LATENCY_FIX_20261020.md。
- 本次固件和 SHA-256 位于 `releases/20261020/`，启动日志为项目 `tmp/hardware-conversation-20261020.log`。
## 第一次配网和真实对话

当前本机为改善原网络丢包，已采用近距离电脑热点 `LingXi-Link`，密码 `lingxi2026`，
板子服务地址为 `http://192.168.137.1:8787`。双击根 start_companion.cmd 会检查/恢复本机临时热点并启动服务。
以下原Wi-Fi流程保留供其他网络使用；不要将当前板子的服务地址改回旧的172.6.1.59，除非重新切回对应网络。

2026-10-20 修复手机浏览器 `Header fields are too long`：构建时将
`CONFIG_HTTPD_MAX_REQ_HDR_LEN` 从默认512字节扩大到8192字节。
若旧固件出现此错误，重新运行 `prepare.py --update`、构建并烧录；本项目当天发布目录已更新。
问题及验证记录见 [HTTP 431 修复说明](../../docs/PORTAL_HEADER_FIX_20261020.md)。

1. 双击项目根目录的 **`start_companion.cmd`**。启动器会复用已运行的本地服务，
   或使用本机已安装的 IDF Python 启动服务，然后打开 `/companion` 伙伴页面。
   需要手动启动时可在终端执行：

   ~~~bat
   cd /d D:\比赛项目\lingxi-main
   python server.py --host 0.0.0.0 --port 8787 --database tmp/hardware-conversation-20261020.sqlite3
   ~~~

2. 在这台电脑打开 <http://127.0.0.1:8787/companion>，点击“连接服务”，填写有效的
   StepFun API Key 并保存。密钥只交给本地电脑服务，不填入板子的配网页，也不写入固件或仓库。
   账号须能调用对话、识别和合成模型。本机密钥已配置，真实服务链路已测试通过；其他电脑仍需配置自己的密钥。

3. 板子上电后，用手机连接本块板子的热点 **`LingXi-922C`**，密码 **`lingxi2026`**。
   热点后缀来自设备 MAC，其他板子以屏幕或日志显示的名称为准。
   浏览器打开 <http://192.168.4.1>，填写可供板子使用的 2.4 GHz Wi-Fi 名称、密码，
   服务地址填 **`http://172.6.1.59:8787`**，点击“保存并连接”。
   这是当前电脑的局域网地址；电脑换网或地址改变后，在配网页更新。
   板子里的服务地址不能填 `127.0.0.1`、`localhost` 或 `/companion` 页面路径。

4. 设备令牌可选。首次调试可两侧均不启用；若电脑服务配置了令牌，板子配网页和
   网页“设备与服务设置”中应填写相同令牌。设备令牌与模型 API Key 是两个不同字段。
   Wi-Fi、服务地址及设备令牌保存到板子的 NVS，断电后保留；模型 Key 由电脑服务管理。

5. 手机回到原网络。电脑和板子须能互相访问；屏幕显示板子 IP 和协议连接成功后，
   在伙伴页面核对设备编号，选择形象、声音和交流设置并保存。设置供后续对话使用。
   按住 **BOOT** 说话、松开提交，最长 **10 秒**；联网可用时进入思考、显示回复并播放语音。
   未连接服务时会明确提示并回放本次录音；服务调用失败时显示错误，按键可重试。

协议探测为 `GET /api/device/protocol`，设备语音请求为 `POST /api/device/conversation`。
电脑服务处理 ASR → 对话 → TTS，板子接收 16000 Hz、16-bit、单声道 PCM。
仅协议检查成功，不能作为真实 ASR、模型回复或 TTS 已通过的证明。
若 Wi-Fi 正常但服务不可达，核对电脑地址、`--host 0.0.0.0`、Windows 入站访问和网络终端隔离。

## 构建、更新与分区

在 ESP-IDF 5.4.4 CMD 中执行。首次准备工程时不加 `--update`：

~~~bat
python "D:\比赛项目\lingxi-main\firmware\box_audio_ram\prepare.py" --update --server-url http://172.6.1.59:8787
cd /d D:\比赛项目\lingxi-main\firmware\local_projects\lingxi_audio_ram
idf.py --no-ccache build
idf.py --no-ccache -p COM12 flash
~~~

COM12 是本次 CH343 UART 连接使用的端口；USB 重连后以实际端口为准。
prepare.py 从用户本地正点原子资料复制必要驱动，生成无空格的英文路径工程；
`--vendor-root` 和 `--destination` 可修改资料目录与构建位置。
更新前核对工程标记，并更新应用、资源和本项目的分区表。
Wi-Fi 和服务地址也可通过 `idf.py menuconfig` → `LingXi Network` 设置；
已保存的 NVS 配置会被固件读取，日常修改优先使用 AP 配网页。

应用布局扩展到 Flash 前 **4 MiB**，其中 `factory` 应用本身为 **4032 KiB**：

| 分区 | 起点 | 大小 |
| --- | --- | --- |
| nvs | `0x9000` | `0x6000` |
| phy_init | `0xF000` | `0x1000` |
| factory | `0x10000` | `0x3F0000` |
| vfs | `0x400000` | `0x800000` |
| storage | `0xC00000` | `0x400000` |

新布局为两套角色、中文字库和联网语音代码提供空间，NVS 与射频分区起点保持不变。
应用更新下载引导程序 `0x0`、分区表 `0x8000` 和应用 `0x10000`；不需要擦除整片 Flash。
原始小智完整备份 `D:\比赛项目\lingxi-main\backups\original_firmware\xiaozhi_1.9.4_full.bin`（16777216 字节）保留。
本固件不使用旧 VFS 或 SPIFFS 内容。

录音数据在 PSRAM，16000 Hz、PCM16 单声道，最长 10 秒占 320000 字节，断电丢失。
I2S 使用双声道 32-bit slot 承载 16-bit 数据，产生 ES8311 所需的 64 Fs BCLK；
采集左声道，播放时复制到两个输出声道。LCD 刷新等待 DMA 完成，
录音期间只刷新音量条；单次重绘超过 15 ms 时本段音频降级为停止后续绘制。

串口诊断用 `idf.py -p COM12 monitor`，按 Ctrl+] 退出。错误时记录底部错误名称；
日志 peak 持续为 0 表示没有有效麦克风样本。驱动来源见 [THIRD_PARTY.md](THIRD_PARTY.md)。

## 历史界面与验证记录

以下为各次构建与现场验证记录，旧版本“尚未烧录”等描述仅对应当时版本。
v2 机器人素材保留在 `assets/mascot-v2`，桌面预览保留在 `preview/v2`，
早期淡紫犀牛预览位于 `preview` 根目录。v3 原始来源详见 [SOURCES.md](assets/mascot-v3/SOURCES.md)。

<!-- Historical v2 implementation notes retained below for traceability. -->

<details>
<summary>早期 v2 界面和编译记录</summary>

## 小犀桌宠界面

当前 v2 采用浅蓝色界面和蓝色云朵机器人“小犀”，角色为 3D 渲染风格。
根据用户提供的形象参考，使用内置 imagegen 生成六种一致的表情，保留玻璃面罩、
明亮大眼睛、柔和蓝色外壳与立体光影。原始 1536 × 1024 RGBA 图保留在
assets/mascot-v2/xiaoxi-3d-concept-v2.png，完整提示词与制作说明也在该目录。
板端显示预渲染贴图，未运行实时 3D 引擎。待机轻晃、眨眼；按住 BOOT 时
举起小手倾听，回放时变为笑眼并挥手。思考姿态作为后续 AI 联调素材预留。
中文气泡和底部按键提示对应真实操作，没有尚未实现的触摸按钮。
顶栏“已连接”只在 Wi-Fi 和本地协议检查均成功后出现，不代表 AI 语音已接通。
底栏保留板子的 IP 与 API 检查结果，失败时显示简短错误。

- 待机：“我在呀，慢慢说～”，回放结束后展示本次录音时长。
- 录音：“嗯嗯，我在听！”，显示实际 PCM 音量和最长 5 秒的录音进度。
- 回放：“听见啦，是你的声音。”，显示实际回放进度和音量。
- 静音或错误：根据收到的音频或驱动错误显示提示，不伪造成功状态。

界面在 320 × 240 RGB565 画布上绘制，153600 字节画布放在 PSRAM，
中文使用内置的 Noto Sans SC 小字库，无需 TF 卡或单独下载字库。
六种角色姿态统一打包为 128 × 128 的 RGB565 + alpha8 常量，使用 294912 字节 Flash，
不在运行时解码 PNG、不额外分配角色帧缓冲。统一裁切、缩放及透明度转换由
tools/pack_mascot.py 完成，原始图不修改，来源及 SHA-256 记录在 assets/mascot-pack-report.json。
刷新等待 LCD DMA 完成；录音期间仅更新小面积音量条，避免重绘整个角色。
若实机一次音量条重绘超过 15 ms，本次音频期间停止后续绘制，优先完成录音/回放。
动画流畅度、音频连续性与颜色仍需烧录到实机后确认。

`preview/v2/xiaoxi-states.png` 是由同一份 C 绘图代码生成的三状态预览，
`preview/v2/xiaoxi-idle.gif` 展示待机动画。预览中的联网状态与音量是演示输入。
旧版淡紫小犀牛预览保留在 preview 根目录，供版本对照。
电脑有 GCC 和 Pillow 时，可运行 `python tools/render_ui_preview.py` 重新生成预览；
字体子集已随源码提供，正常编译无需安装 Pillow、GCC 主机编译器或完整字体。

## 使用

在 ESP-IDF 5.4.4 CMD 中执行：

~~~bat
python "D:\比赛项目\lingxi-main\firmware\box_audio_ram\prepare.py"
cd /d D:\比赛项目\lingxi-main\firmware\local_projects\lingxi_audio_ram
idf.py --no-ccache build
idf.py --no-ccache -p COM11 flash
~~~

prepare.py 从本机资料盘复制必要的原厂驱动，生成英文路径的独立工程。
默认资料路径可通过 --vendor-root 修改，工程位置可通过 --destination 修改。
目标目录非空时停止，不覆盖已有工程。录音回放不依赖 SD 卡、外部字库或网络。
编译看到 Project build complete 后再执行下载命令；关闭编译缓存可避开本机缓存卡顿。

已生成过工程时，更新本程序：

~~~bat
python "D:\比赛项目\lingxi-main\firmware\box_audio_ram\prepare.py" --update
cd /d D:\比赛项目\lingxi-main\firmware\local_projects\lingxi_audio_ram
idf.py --no-ccache build
idf.py --no-ccache -p COM11 flash
~~~

更新前会核对工程名称和主程序标记，只更新此录音工程的主程序、说明和必要配置。

## 本地网络联调

电脑和板子连接同一个网络；板子的 Wi-Fi 使用 2.4 GHz 个人热点或家用路由器。
下面的服务地址需要替换为电脑当前的 Wi-Fi IPv4 地址，不能填写 localhost 或 127.0.0.1。
本地服务器未运行时，在另一个终端进入灵犀仓库并启动：

~~~bat
python server.py --host 0.0.0.0 --port 8787 --database tmp/hardware-network.sqlite3
~~~

在 ESP-IDF CMD 更新现有工程并进入配置菜单：

~~~bat
python "D:\比赛项目\lingxi-main\firmware\box_audio_ram\prepare.py" --update --server-url http://192.168.1.100:8787
cd /d D:\比赛项目\lingxi-main\firmware\local_projects\lingxi_audio_ram
idf.py menuconfig
~~~

进入 LingXi Network，填写 Wi-Fi SSID 和 Wi-Fi password，核对服务地址后按 S 保存、Q 退出。
SSID 和密码只在用户本机的 sdkconfig 和固件中保存；无需发送到聊天。
然后执行前面的编译和下载命令。

正常显示 WiFi: 后接板子自己的 IP，以及 API OK / 0.4-draft，顶栏显示“已连接”。
固件检查 GET /api/device/protocol 的版本、采样率、位宽和声道数，每 15 秒检查一次。
Wi-Fi 断开时自动重连；检查服务失败时屏幕显示错误，本地录音回放仍可操作。
电脑地址改变后，更新服务地址并重新编译下载。只有 Wi-Fi 正常但 API 连接失败时，
再检查服务是否以 --host 0.0.0.0 启动、Windows 入站访问和校园网终端隔离。
HTTPS 地址会先同步时间，使用系统证书包验证服务器证书。

屏幕出现小犀与“我在呀，慢慢说～”后，按住 BOOT 说话，松开自动回放；最多保存 5 秒。
触及 5 秒上限也会自动回放，等待松开后才能开始下一次录音。
录音为 PSRAM 中的 16000 Hz、16 bit、有符号小端、单声道 PCM（最多 160000 字节）。
断电丢失，不写入 Flash。存储格式与灵犀设备音频草案一致。

I2S 总线以双声道 32-bit slot 传输 16-bit 数据，产生 ES8311 所需的 64 Fs BCLK；
保存左声道，播放时将单声道复制到两个输出声道。
原厂 ES8311 时钟表已支持 16000 Hz / 1024000 Hz，准备脚本将时钟倍数从 32 改为 64。
原厂驱动来自本地资料，见 THIRD_PARTY.md；没有复制 SD、文件系统或 WAV 播放器。

需要串口诊断时：

~~~bat
idf.py -p COM11 monitor
~~~

按 Ctrl+] 退出。USB 重连后端口号可能变化，需要使用实际端口。
屏幕显示错误提示时，记录底部错误名称；串口日志中的 peak 长期为 0 表示未收到有效麦克风信号。
编译成功只能证明代码能构建，麦克风声道、音量和实际回放需在实机确认。

## 构建验证

2026-10-19：在本机 ESP-IDF 5.4.4 / GCC 14.2.0 下，
使用 idf.py --no-ccache build 完成编译，输出 Project build complete。
应用镜像为 298304 字节（0x48d40），通过分区大小检查。
该构建随后由用户下载到设备，初版反馈见下方。

初版实机反馈：I2S 初始化返回 ESP_ERR_INVALID_ARG。
通过 COM11 启动日志定位为 gdma_register_tx_event_callbacks 的
“user context not in internal RAM”，原因为 LCD 配置启用了 GDMA ISR IRAM-safe，
而 I2S ISR IRAM-safe 未启用。准备/更新脚本现强制设置 CONFIG_I2S_ISR_IRAM_SAFE=y，
使 I2S 驱动上下文分配到内部 RAM；大块录音缓冲仍使用 PSRAM。
主程序也加入了不兼容配置的编译错误检查。
修复版已再次通过 ESP-IDF 5.4.4 完整构建，镜像大小 298864 字节（0x48f70），
分区大小检查通过。用户随后反馈“可以”，按录音回放已通过理解，尚待后续联调记录补充。

同日联网检查版构建通过，应用大小 0x106350；本机服务的协议接口经主机 HTTP 请求验证可用。
加入小犀桌宠界面后，再次在启用网络检查的配置下完整构建成功，应用大小
1223184 字节（0x12aa10），最小应用分区仍有 40% 空余。
桌面预览对比检查通过：局部角色动画、局部音量条绘制与全屏绘制结果逐像素一致。
以上为构建及桌面绘图验证，尚未将此界面版本烧录到实机。

同日 v2 蓝色 3D 风格形象已接入固件并构建通过，应用大小 1516832 字节（0x172520），
最小应用分区剩余 25%。三个实际交互状态的桌面预览与局部刷新比较通过；
角色与眨眼姿态的透明像素边界经核对均在待机刷新范围内。尚未烧录此版本到实机。

## 2026-10-20 实机体验版

按用户要求，已通过 COM12（CH343 UART）将蓝色 3D 小犀体验版写入实际板子，
esptool 写后哈希校验通过。设备识别为 ESP32-S3，16 MB Flash、8 MB PSRAM。
体验版关闭未配置的网络，使用 UART0 主日志及 USB Serial/JTAG 副日志，通电即可操作。
原固件备份 D:\比赛项目\lingxi-main\backups\original_firmware\xiaozhi_1.9.4_full.bin（16777216 字节）保留。

首次启动检查通过 PSRAM 测试、ES8311 初始化和 160000 字节录音缓冲分配，
未见 panic、assert 或 ESP_ERROR_CHECK 失败。现场一次按键操作捕获 46400 个单声道样本
（约 2.9 秒）并进入回放；实际喇叭音质及屏幕观感由用户体验确认。

实机日志发现音量条绘制约 28 ms，触发了保守的绘制降级；随后优化了音量条的专用绘制、
圆角计算和字体裁切。桌面局部/全屏比较通过，再次编译并写入应用分区，哈希校验通过。
最终应用大小 752848 字节（0xB7CD0），应用分区剩余 63%；更新后再次启动就绪，未见启动异常。
优化后的实机音量条耗时仍待下一次录音检查，当前不声称已完成录音期间的性能测量。
本地启动证据保存在仓库 tmp/hardware-preview-20261020.log，首次录音记录另存
tmp/hardware-preview-20261020-before-meter-fix.log（tmp 不纳入公开仓库）。

</details>

## 当前验收边界

v3 已加入袋鼠、独立官方校徽图层、完整 GB2312 汉字字库、AP 配网和语音对话客户端。
模型API Key已配置，服务端真实ASR、模型回复、TTS已通过。用户随后确认实体板子人声测试可在5秒以内开始听到回复；
这是单次用户反馈，不是连续多轮延迟分布或固定时延保证。此前自动声学回放测试未识别到清晰语音，没有计为成功对话。
