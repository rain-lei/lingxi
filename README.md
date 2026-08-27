# 灵犀挂件 · 系统控制台

这是“灵犀挂件”的系统控制台与云端编排实现。当前使用网页数字孪生验证完整链路；接入真实硬件后，网页端继续用于设备配置、调试、遥测和记忆管理：

- 挂件状态机：待机、倾听、思考、回应、断网
- 三种场景：知识问答、情感陪伴、多语言翻译
- 流式文本：后端以 NDJSON 分块返回，OLED 与对话区同步更新
- 语音能力：浏览器语音识别（可用时）与本地 TTS 播报
- 阶跃模型：`step-3.7-flash` 对话与原生图片理解 + `stepaudio-2.5-asr` 语音识别 + `stepaudio-2.5-tts` 语音合成
- 反馈记忆 Agent：结果评价/修改、规则沉淀、相似任务召回和 Agent Trace
- 记忆指标：召回条数、估算 token 成本、检索时间、使用次数与正反馈率
- 访客隔离：每个浏览器生成独立匿名 ID，不共享会话和记忆
- 优雅降级：一键模拟现场断网，不死机、不无限等待
- 控制台能力：设备自检、运行遥测、自动播报控制、诊断导出和请求限流
- 硬件协议：可查询、可校验的 `0.4-draft` 设备事件协议和令牌保护入口
- 零安装依赖：服务端仅使用 Python 标准库

## 运行

需要 Python 3.10 或更高版本。

```powershell
python server.py
```

浏览器打开：<http://127.0.0.1:8787>

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

## 30 秒验证

```powershell
python -m unittest discover -s tests -v
```

启动服务后也可以检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8787/api/health
```

## 建议演示顺序

1. 完成一个学习或信息整理任务，观察 Agent 计划和记忆工具调用。
2. 对结果选择“需要调整”，输入“以后回答更简短，先给结论”。
3. 提交相似任务，展示规则自动召回、token 成本和结果变化。
4. 上传图片，展示 Step 3.7 原生多模态理解。
5. 运行设备自检，展示 OLED / RGB / 音频状态映射。
6. 打开“断网演练”，展示网络不可用时的明确反馈和优雅降级。

## 主要 API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/capabilities` | 模型、语音和设备桥接能力 |
| GET | `/api/device/protocol` | 机器可读的设备协议清单 |
| GET | `/api/memory/metrics` | 当前访客反馈记忆指标 |
| POST | `/api/interactions` | 流式 Agent 任务 |
| POST | `/api/feedback` | 评价结果并沉淀修改规则 |
| POST | `/api/device/events` | 令牌保护的设备事件校验入口 |

## 目录

```text
.
├── server.py               # HTTP 服务、流式编排、SQLite 记忆、Mock AI
├── device_protocol.py      # 0.4-draft 设备事件协议与校验
├── public/
│   ├── index.html          # 挂件与对话控制台
│   ├── styles.css          # 响应式视觉与设备状态动画
│   └── app.js              # 流式客户端、PCM 采集、语音、状态机与交互
├── providers/stepfun.py    # 阶跃 Step Plan Chat / ASR / TTS 客户端
├── tests/                  # 核心记忆与 Provider 协议测试
├── THIRD_PARTY.md          # 第三方资源与 AI 工具使用声明
└── docs/
    ├── competition-alignment.md # 官方赛题与提交材料对齐审计
    ├── project-brief.md    # 可直接用于提交的项目简介
    ├── software-plan.md    # 当前实现、架构、协议与硬件接入计划
    └── upgrade-roadmap.md  # 持续升级路线、阶段指标与黑客松脚本
```

## 当前状态

没有 API Key 时系统使用确定性的 Mock AI，确保黑客松现场仍可演示。ESP32-S3 WebSocket、I2S 音频和 OTA 属于 Device 0.4 实机阶段；当前页面只将已验证链路标记为“已完成”。完整阶段指标见[持续升级路线](docs/upgrade-roadmap.md)。
