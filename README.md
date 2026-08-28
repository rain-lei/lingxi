# 灵犀挂件 · 在线演示与系统控制台

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

没有 API Key 时系统使用确定性的 Mock AI，确保黑客松现场仍可演示。当前已实现持久化任务卡、确认/完成/取消闭环，以及对显式日期、时间和“提前 N 小时/分钟提醒”的服务器端调度；到期状态会在控制台轮询显示。它尚不是系统推送、短信或实机震动，ESP32-S3 WebSocket、I2S 音频和 OTA 仍属于 Device 0.5 实机阶段。完整阶段指标见[持续升级路线](docs/upgrade-roadmap.md)。
