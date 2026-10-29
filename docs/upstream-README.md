# 上游 README 历史归档

来源：twofly653/lingxi@77bebed447cc8a0c65c29b4f6a3fda25f3522c68。以下机器路径、实板结果与现场配置是上游历史记录，不代表本次整合验证。当前启动和部署请以仓库根目录 README 和 integration.md 为准。

# 灵犀挂件 · 在线演示与系统控制台

## 项目文件统一位置（2026-10-24）

项目集中存放于 `D:\比赛项目\lingxi-main`。网页与服务入口为本目录的 `start_companion.cmd`；动画入口为 `start_animations.cmd`。

- `firmware/box_audio_ram/`：当前固件源码、素材与发布包。
- `firmware/local_projects/lingxi_tf_20261023/`：从 C 盘迁入的现场固件完整工程。
- `firmware/local_projects/lingxi_audio_ram/`、`lingxi_lcd/`：旧版固件工程归档。
- `backups/original_firmware/`：出厂小智固件备份。
- `vendor/ESP32_AI_BOX1/`：正点原子硬件原厂资料。
- `public/`、`data/`、`docs/`、`output/`：网页资源、本地配置与记录、说明和输出。

迁移说明见 [文件整理记录](docs/FILE_MIGRATION_20261024.md)。归档工程的历史构建缓存包含旧绝对路径，重新编译时使用新的构建目录（例如 `idf.py -B build-relocated build`），不要直接沿用旧 `build` 缓存。ESP-IDF 和编译器仍使用机器上已安装的工具链。

## 2026-10-23 现场展示 V3

陪伴网页重新设计，加入角色动作台、四语气字体、学习计划与偏好入口。硬件资源升级为 **五位伙伴 × 十种动作，共 50 段、2700 帧**；采用无损 RLE3 压缩与 50 ms 帧节拍，目标 20 fps，实际流畅度以实板测量为准。四套原生 20 px 中文字体可独立安装到 TF 卡。

板上 **K1 短按互动、长按 800 ms 切换展示模式；K2 短按切换语气、长按 800 ms 开始或结束本地 25 分钟专注；BOOT 按住说话、松开发送**。板上专注是本地计时，不自动生成网页或云端学习记录。启动异常涉及的主栈问题已改为静态绘制缓冲、8192 字节主栈及强栈保护；最终固件已写入校验，短时遥测无重启迹象。

双击 `start_companion.cmd`，打开 <http://127.0.0.1:8787/companion>；动画工坊为 <http://127.0.0.1:8787/animations.html>。**V3 动画和四字体已安装并校验，独立待机遥测为 12.218 秒 / 242 帧 / 19.807 fps**。六种静音预览解码错误为零，四字体缓存切换通过；用户不在板子旁，物理按键、真实语音、人眼流畅度及校标观感仍待确认。完整控制、下载、兼容性与验证清单见 [现场展示 V3 说明](docs/SHOWCASE_V3_20261023.md)。以下按日期保留早期发布记录，当前使用以 V3 说明为准。

## 2026-10-21 动画精修 V2

动画工坊与主陪伴页改用独立的 **512 × 512、20 fps 高清透明动画**，保留绒毛与五官细节；板端资源另行生成 128 × 128 帧。修复姿态重影、蓝蓝与芽芽的尾尖截断，蓝蓝六种姿态均合成官方校标。主陪伴页随真实对话状态切动作，空闲时可摸摸庆祝；高清与板端效果可在工坊切换查看。

入口仍为 <http://127.0.0.1:8787/animations.html>。下载分为轻量 TF 包和可选的高清离线预览；安装流程、固件和卡上文件名保持兼容，未刷板或操作用户 TF 卡。详细变更及验证见 [精修记录](docs/TF_ANIMATION_REFINEMENT_20261021.md)。

## 2026-10-21 TF 动画已备好，稍后可下载

双击 **`start_animations.cmd`**，打开 <http://127.0.0.1:8787/animations.html>。动画工坊可预览五位伙伴的六类动作，并下载 TF 资源与配套固件；文件保存在本机项目中，今晚或明早重开服务即可取用。

资源共 30 段、900 帧，板端 LXAF 文件约 42.2 MiB，16 GB FAT32 TF 卡足够。配套固件已编译并通过文件校验，**尚未烧录或完成你的 TF 卡实测**。更新后支持读卡器复制，也支持手机连接板子热点，在 `http://192.168.4.1/` 点击“从电脑安装动画”。当前待机、思考和回应小头像已接入；录音保持静态，安慰与庆祝动作待后续业务触发。

详见 [首次安装步骤](docs/TF_ANIMATION_INSTALL_GUIDE_20261021.md) 和 [本次发布及验证记录](docs/TF_ANIMATION_RELEASE_20261021.md)。

## 2026-10-21 学习搭子与五位伙伴

网页新增独立学习页、可编辑待办与定时提醒、真实专注归档、手动学习记录及七天统计，个人称呼 / 兴趣 / 学习目标 / 回答长短可保存并用于后续对话。新伙伴奶泡、团团、芽芽已加入图鉴；当前新三形象用于网页，板端安全显示蓝蓝。页面文字与控件已放大，入口仍为 <http://127.0.0.1:8787/companion>。

提醒需本机服务和网页运行，系统通知由用户主动授权。使用方法、素材及验证边界见 [学习搭子更新说明](docs/LEARNING_COMPANION_20261021.md)。

## 2026-10-21 视觉与动效更新

陪伴空间已重排为暖白纸色、深蓝导航、角色舞台与独立偏好面板，加入摸摸回应、轻微呼吸和真实声量波形；窄窗口和手机使用纵向布局。入口仍为 <http://127.0.0.1:8787/companion>，双击 `start_companion.cmd` 启动。

板端无卡微动效版已烧录，保留20px清晰回复。当前不读取TF动画；扩展多套素材建议32GB microSDHC / TF、Class10 / U1、FAT32，已有16GB也够用。详见 [视觉更新与验证](docs/VISUAL_UPGRADE_20261021.md) 和 [动画容量方案](docs/ANIMATION_STORAGE_PLAN_20261020.md)。

## 2026-10-20 陪伴空间更新

双击 `start_companion.cmd`，打开 <http://127.0.0.1:8787/companion>。
新增蓝蓝角色提示词、可查看/删除的显式记忆、持久专注计时、一分钟呼吸工具，以及网页和固件的 LXS1 流式声音。
电脑端三条真实云端测试首 PCM 约 3.2–6.3 秒；这不是实板延迟保证。
板子已重新接好，流式版已通过烧录、启动和用户对话验证；用户反馈新问题首句约 3–7 秒，这是一次非仪器计时反馈。
随后大字双字体版（3,997,280 字节）也已烧录并通过哈希和启动检查，恢复连接电脑 `LingXi-Link` 热点：回复使用20px白底深字卡，温柔/活泼为资源圆体，平静/利落为黑体，无需TF卡。字体说明见 [字体与存储](docs/FONT_AND_STORAGE_20261020.md)，此前可用版本均保留。
详细体验步骤、测试边界和交付状态见 [本次说明](docs/COMPANION_UPGRADE_20261020.md)，角色设定见 [角色提示词](prompts/lanlan_system.md)。

这是“灵犀挂件”的系统控制台与云端编排实现。当前使用网页数字孪生验证完整链路；接入真实硬件后，网页端继续用于设备配置、调试、遥测和记忆管理：

- 挂件状态机：待机、倾听、思考、回应、断网
- 三种任务模式：通用任务、情感陪伴、多语言翻译
- 流式文本：后端以 NDJSON 分块返回，OLED 与对话区同步更新
- 语音能力：浏览器语音识别（可用时）与本地 TTS 播报
- 阶跃模型：`step-3.7-flash` 对话与原生图片理解 + `stepaudio-2.5-asr` 语音识别 + `stepaudio-2.5-tts` 语音合成
- 可执行任务中心：行动型输入自动保存为任务卡，支持待确认、已确认、已完成和已取消状态；显式日期、时间与提前提醒会由服务端持久化调度，已召回的提醒偏好也会作用于相似后续任务
- 反馈记忆 Agent：结果评价/修改、规则沉淀、相似任务召回和 Agent Trace
- 记忆可控：当前匿名访客可查看、核对并单条撤销已沉淀规则
- 记忆指标：召回条数、估算 token 成本、检索时间、使用次数与正反馈率
- 访客隔离：每个浏览器生成独立匿名 ID，不共享会话和记忆
- 优雅降级：一键模拟现场断网，不死机、不无限等待
- 控制台能力：任务队列管理、设备自检、运行遥测、自动播报控制、诊断导出和请求限流
- 硬件协议：可查询、可校验的 `0.4-draft` 事件契约，含令牌鉴权、握手、序号与状态校验
- 零安装依赖：服务端仅使用 Python 标准库

## 运行

需要 Python 3.10 或更高版本。

```powershell
python server.py
```

浏览器打开在线演示：<http://127.0.0.1:8787/demo>；完整控制台：<http://127.0.0.1:8787/console>

### Docker 运行

生产环境使用非 root 容器，并将 SQLite 数据保存在独立卷中：

```bash
docker build -t lingxi-demo:latest .
sudo install -d -o 100 -g 101 /srv/lingxi-demo/data
docker run -d \
  --name lingxi-demo \
  --restart unless-stopped \
  --env-file .env \
  -p 127.0.0.1:8787:8787 \
  -v /srv/lingxi-demo/data:/app/data \
  lingxi-demo:latest
```

服务器反向代理示例见 `deploy/nginx/lingxi.rainlei.xyz.conf`。容器端口只绑定在
`127.0.0.1`，公网访问统一通过 Nginx 和 HTTPS。

### 接入阶跃 StepAudio

密钥只通过进程环境变量读取，不会返回给浏览器，也不要写入仓库：

```powershell
$env:STEPFUN_API_KEY="你的 API Key"
python server.py
```

可选音色：

```powershell
$env:STEPFUN_TTS_VOICE="cixingnansheng"
```

真实硬件配对时再生成设备令牌；未配置时设备事件写入接口保持关闭：

```powershell
$env:LINGXI_DEVICE_TOKEN="使用密码生成器创建的随机值"
```

配置成功后，顶部会显示“Step 3.7 已连接”，按住挂件会采集单声道 PCM、下采样到 16 kHz 后交给阶跃 ASR；文字和图片回复都由具备原生多模态能力的 `step-3.7-flash` 流式生成。发送 JPG、PNG、GIF 或 WebP 图片时，界面会显示图片预览并自动走视觉输入；语音回复仍由 `stepaudio-2.5-tts` 合成为 MP3。任何上游失败都会自动切回 Mock/浏览器语音兜底。

使用其他端口：

```powershell
python server.py --port 9000
```

一次文本任务默认最多等待 45 秒，图片任务最多等待 60 秒；控制台和在线演示均可点击“停止”立即恢复可操作状态。服务端的 StepFun 上游超时默认为 45 秒，可通过 `STEPFUN_TIMEOUT` 调整。

任务调度支持 `8月30日 18:30`、`明天 18:30`、`后天 18:30`、`本周三 18:30` 与 `下周五 18:30` 这类明确时间。已过去的“今天/本周”时间不会被悄悄改成即时提醒；图片任务可使用视觉回复中提取的日期和时间，但“提前 N 小时/分钟”仍需由用户输入或已召回的偏好明确给出。

## 30 秒验证

```powershell
python -m unittest discover -s tests -v
```

运行一次不触碰生产库的记忆闭环评测，输出命中、误召回、提示注入和 token/耗时证据：

```powershell
python tools/memory_eval.py
```

需要保存脱敏证据时可指定输出文件（例如 `python tools/memory_eval.py --output .tmp/memory-eval.json`）。

提交前运行以下命令，会检查必备材料、`.env` 是否误入 Git、公开 Demo/控制台、健康检查、模型、视觉和提醒能力；它不读取或输出密钥：

```powershell
python tools/submission_preflight.py
```

启动服务后也可以检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/health
```

## 建议演示顺序

1. 在 `/demo` 点击示例任务，让 Agent 从自然语言中生成真实任务卡并点击“确认任务”。
2. 打开 `/console`，展示同一匿名访客的任务队列、状态筛选和完成闭环。
3. 对结果选择“需要调整”，输入“以后回答更简短，先给结论”。
4. 提交相似任务，展示规则自动召回、token 成本和结果变化。
5. 上传图片，展示 Step 3.7 原生多模态理解。
6. 运行设备自检，再打开“断网演练”，展示状态映射与优雅降级。

## 主要 API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/capabilities` | 模型、语音和设备桥接能力 |
| GET | `/api/device/protocol` | 机器可读的设备协议清单 |
| GET | `/api/memory/metrics` | 当前访客反馈记忆指标 |
| GET | `/api/memory/items` | 查看当前访客已沉淀的反馈规则 |
| GET | `/api/tasks` | 查看当前访客的可执行任务队列 |
| POST | `/api/interactions` | 流式 Agent 任务 |
| POST | `/api/tasks/update` | 确认、完成、取消或恢复任务 |
| POST | `/api/feedback` | 评价结果并沉淀修改规则 |
| POST | `/api/memory/delete` | 撤销一条属于当前访客的反馈规则 |
| POST | `/api/device/events` | 令牌保护的设备事件校验入口 |

### 设备协议契约检查

不连接服务器即可验证一组完整设备上行事件：

```powershell
python tools/device_simulator.py
```

硬件配对后，可通过环境变量读取设备令牌并验证服务器鉴权、事件顺序和状态转换：

```powershell
$env:LINGXI_DEVICE_TOKEN="你的设备令牌"
python tools/device_simulator.py --send --base-url http://127.0.0.1:8787
```

脚本不会从命令行参数读取或输出设备令牌。

## 目录

```text
.
├── server.py               # HTTP 服务、流式编排、SQLite 记忆、Mock AI
├── device_protocol.py      # 0.4-draft 设备事件协议与校验
├── public/
│   ├── index.html          # 系统控制台（兼容根路径与 /console）
│   ├── demo.html           # 对外在线演示页
│   ├── demo.js             # 在线演示流式交互客户端
│   ├── styles.css          # 响应式视觉与设备状态动画
│   └── app.js              # 流式客户端、PCM 采集、语音、状态机与交互
├── providers/stepfun.py    # 阶跃 Step Plan Chat / ASR / TTS 客户端
├── tests/                  # 核心记忆与 Provider 协议测试
├── tools/device_simulator.py # 设备事件契约模拟器，不含密钥
├── THIRD_PARTY.md          # 第三方资源与 AI 工具使用声明
└── docs/
    ├── competition-alignment.md # 官方赛题与提交材料对齐审计
    ├── demo-video-script.md # 4 分钟初赛演示视频分镜与旁白
    ├── project-brief.md    # 可直接用于提交的项目简介
    ├── user-test-plan.md   # 5 人校园测试流程、指标与脱敏证据模板
    ├── software-plan.md    # 当前实现、架构、协议与硬件接入计划
    └── upgrade-roadmap.md  # 持续升级路线、阶段指标与黑客松脚本
```

## 当前状态

没有 API Key 时原有网页演示可使用确定性的 Mock AI。当前已实现持久化任务卡、确认/完成/取消闭环，对日期、相对日期、本/下周星期和图片提取时间的服务器端调度，以及反馈记忆驱动的提醒偏好；到期状态与来源会在控制台显示。系统推送、短信、实机震动、ESP32-S3 WebSocket 与 OTA 仍待后续阶段。完整阶段指标见[持续升级路线](docs/upgrade-roadmap.md)。

### ESP32S3 BOX 硬件

正点原子 BOX V1.1 已完成实际启动、ES8311 初始化和内存录音回放验证。
v3 固件加入蓝色毛绒袋鼠六姿态、独立官方 DUT 校徽、完整 GB2312 汉字字库、AP 配网，
并接入本地服务的录音上传、识别、对话与语音返回客户端。应用布局扩展至 Flash 前4MiB。
**API Key已在本机配置，真实服务对话已验证，最新服务耗时约5.3–6.5秒；板端收包超时和手机HTTP431已修复。用户已确认实板人声对话能在松开BOOT后5秒以内开始听到回复（单次用户反馈）。**

当前已改用电脑近距离2.4GHz热点 `LingXi-Link`，板子服务地址 `http://192.168.137.1:8787`，用于改善原网络87%丢包。
双击启动器会按本机配置恢复临时热点。测速与验收边界见 [对话等待优化记录](docs/VOICE_LATENCY_FIX_20261020.md)。

双击根目录 **`start_companion.cmd`** 即可复用或启动本地服务，并打开伙伴页面；
启动逻辑位于 `run_companion.py`，使用 `tmp/hardware-conversation-20261020.sqlite3` 数据库。
本机在 <http://127.0.0.1:8787/companion> 配置密钥；本块板的配网热点为 `LingXi-922C`，
密码 `lingxi2026`，打开 <http://192.168.4.1>，当前服务地址填写 `http://172.6.1.59:8787`。
如启用设备令牌，电脑服务与板子须一致。详细构建、配网和验收流程见
[硬件固件说明](firmware/box_audio_ram/README.md)，形象及官方校徽来源见
[素材说明](firmware/box_audio_ram/assets/mascot-v3/SOURCES.md)。
