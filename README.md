# 灵犀挂件 · 软件闭环 Demo

这是“灵犀挂件”在硬件到位前的软件先行原型。它把计划书里的核心链路做成一个可运行、可体验、可验证的本地 Demo：

- 挂件状态机：待机、倾听、思考、回应、断网
- 三种场景：知识问答、情感陪伴、多语言翻译
- 流式文本：后端以 NDJSON 分块返回，OLED 与对话区同步更新
- 语音能力：浏览器语音识别（可用时）与本地 TTS 播报
- 阶跃模型：`step-3.7-flash` 对话与原生图片理解 + `stepaudio-2.5-asr` 语音识别 + `stepaudio-2.5-tts` 语音合成
- 轻量记忆：SQLite 持久化用户称呼与语速偏好
- 优雅降级：一键模拟现场断网，不死机、不无限等待
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

1. 点击“记住我的偏好”，展示 SQLite 用户画像更新。
2. 点击“陪伴场景”，展示称呼和慢速偏好被下一轮自动使用。
3. 点击“实时翻译”，展示流式 OLED 文字和语音播报。
4. 打开“断网演练”，展示网络不可用时的明确反馈和优雅降级。

## 目录

```text
.
├── server.py               # HTTP 服务、流式编排、SQLite 记忆、Mock AI
├── public/
│   ├── index.html          # 挂件与对话控制台
│   ├── styles.css          # 响应式视觉与设备状态动画
│   └── app.js              # 流式客户端、PCM 采集、语音、状态机与交互
├── providers/stepfun.py    # 阶跃 Step Plan Chat / ASR / TTS 客户端
├── tests/                  # 核心记忆与 Provider 协议测试
└── docs/software-plan.md   # 软件范围、架构、协议与硬件接入计划
```

## 当前边界

Demo 没有 API Key 时使用确定性的 Mock AI，确保黑客松现场仍可演示。实时天气、校园开放数据和 ESP32-S3 WebSocket 传输留在下一阶段接入；接口与状态事件已经在[软件计划](docs/software-plan.md)中预留。
