# 灵犀挂件系统实施规划（控制台先行）

版本：Console 0.4
目标：先把模型、语音、记忆、状态编排和控制台做成稳定底座，再接入 ESP32-S3 实机。网页端在硬件接入后继续作为设备控制与调试入口。

## 1. 本轮交付范围

### P0：必须跑通

1. 一键输入：文字输入稳定可用；浏览器支持时可按住挂件说话。
2. 状态可见：待机、倾听、思考、回应、断网均有 OLED、RGB 和文字反馈。
3. 流式响应：回复分块到达，OLED 与对话区同步渲染，避免长时间无反馈。
4. 场景闭环：问答、陪伴、翻译三种演示模式。
5. 轻量记忆：持久化用户称呼和播报语速，下一轮自动带入。
6. 声音输出：阶跃 StepAudio 2.5 TTS 播放回复；失败时回退浏览器 TTS。
7. 断网降级：明确提示“网络开小差了”，终止等待并保持界面可操作。
8. 反馈记忆：用户评价或修改结果后沉淀规则，相似任务自动召回。
9. 记忆可观测：显示召回条数、检索耗时、估算 token 和使用次数。

### P1：硬件联调时加入

- ESP32-S3 通过 WebSocket 上报按键、音频帧和设备状态。
- ESP32 上行 16 kHz / 16 bit / mono 音频，复用已接入的阶跃 ASR/Chat/TTS Provider。
- OLED 分页/滚动策略、WS2812 灯效、I2S 音频播放与中断恢复。
- 服务端设备会话、心跳、重连和超时控制。

### P2：赛后产品化

- 多用户身份与隐私授权、记忆查看/删除。
- 语义记忆提取、摘要和召回排序。
- 摄像头环境描述、实时校园数据与天气插件。
- 设备 OTA、日志脱敏、成本和延迟监控。

## 2. 架构

```text
┌──────────────────────┐       HTTP/NDJSON（本 Demo）       ┌────────────────────────┐
│ 浏览器设备模拟器       │ ────────────────────────────────▶ │ LingXi Orchestrator     │
│ OLED / RGB / 按键 / PCM│ ◀──────────────────────────────── │ 状态编排 / Provider 路由 │
└──────────────────────┘                                    └──────┬────────┬────────┘
                                                                    │        │
                                                        ┌───────────▼──┐  ┌──▼─────────┐
                                                        │ StepAudio 2.5│  │ SQLite     │
                                                        │ ASR/Chat/TTS │  │ 用户轻记忆 │
                                                        └──────────────┘  └────────────┘

下一阶段只替换两端，不改业务事件：

ESP32-S3 ── WebSocket/PCM ──▶ Orchestrator ──▶ STT ──▶ LLM ──▶ TTS
   ▲                                │                          │
   └──────── OLED/RGB/Audio events ─┴──────────────────────────┘
```

设计原则：

- UI 与模型供应商解耦：前端只消费状态事件和文本增量。
- Mock 与真实服务同协议：现场兜底不需要切换演示页面。
- 先文本、后音频：先验证业务闭环，再压缩音频链路延迟。
- 记忆可解释：Demo 只保存明确偏好，不做不可见的推断。

## 3. 核心状态机

```text
IDLE
  └─ button_down / text_submit → LISTENING
LISTENING
  └─ transcript_final          → THINKING
THINKING
  ├─ first_delta               → SPEAKING
  ├─ network_timeout           → OFFLINE
  └─ provider_error            → ERROR
SPEAKING
  └─ playback_end              → IDLE
OFFLINE / ERROR
  └─ acknowledgement / retry   → IDLE
```

状态与硬件反馈映射：

| 状态 | OLED | RGB | 声音 |
|---|---|---|---|
| IDLE | 待机/熄屏 | 低亮蓝色 | 无 |
| LISTENING | 我在听/转写片段 | 蓝色呼吸 | 可选提示音 |
| THINKING | 思考中 | 绿色闪烁 | 无 |
| SPEAKING | 流式回复 | 暖色跳动 | TTS 音频 |
| OFFLINE | 网络开小差了 | 红色常亮 | 离线提示音 |

## 4. Demo API 与事件协议

### HTTP 接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 服务健康检查 |
| GET | `/api/capabilities` | 返回 StepFun Chat / ASR / TTS 可用状态，不返回密钥 |
| GET | `/api/profile?device_id=...` | 获取称呼、语速偏好 |
| GET | `/api/history?device_id=...` | 恢复最近会话 |
| GET | `/api/memory/metrics?device_id=...` | 获取反馈记忆数量、召回与正反馈指标 |
| GET | `/api/device/protocol` | 获取 0.4-draft 设备协议清单 |
| POST | `/api/interactions` | 发起交互并流式接收事件 |
| POST | `/api/feedback` | 评价结果并把修改意见沉淀为规则 |
| POST | `/api/device/events` | 校验令牌保护的设备上行事件 |
| POST | `/api/audio/transcribe` | 接收 16 kHz PCM16 Base64，代理阶跃 SSE ASR |
| POST | `/api/audio/speech` | 接收回复文本，代理阶跃 TTS 并返回 MP3 |
| POST | `/api/reset` | 清空当前设备的记忆与会话 |

`POST /api/interactions` 请求示例：

```json
{
  "device_id": "demo-pendant-01",
  "mode": "companion",
  "text": "今天心情不好怎么办",
  "offline": false
}
```

服务端返回 `application/x-ndjson`，一行一个事件：

```json
{"type":"state","state":"thinking","label":"读取记忆并生成回复"}
{"type":"memory","changes":["称呼：小林"],"profile":{"preferred_name":"小林"}}
{"type":"delta","text":"小林，听起来"}
{"type":"delta","text":"你今天有点难受。"}
{"type":"complete","text":"...","latency_ms":823,"offline":false}
```

### WebSocket 升级协议（P1）

设备上行事件：

- `device.hello`：固件版本、能力、设备 ID。
- `input.begin`：按键按下，开始会话。
- `audio.chunk`：序号、时间戳、PCM 二进制帧。
- `input.end`：按键松开，结束录音。
- `playback.done`：音频播放完成。
- `device.heartbeat`：网络质量、电量、温度。

服务下行事件：

- `session.state`：LISTENING / THINKING / SPEAKING / OFFLINE。
- `transcript.partial`、`transcript.final`：识别结果。
- `reply.delta`、`reply.done`：OLED 流式文字。
- `audio.chunk`：TTS 音频帧。
- `memory.updated`：已保存的显式偏好。
- `error`：可恢复错误与用户提示。

## 5. 数据模型

当前 SQLite 保留四张核心表：

- `profiles`：`device_id`、`preferred_name`、`speech_rate`、`updated_at`。
- `conversations`：模式、用户输入、助手回复、完成状态和时间。
- `feedback`：结果正/负反馈及用户修改意见。
- `feedback_memories`：全局或相似任务规则、上下文和召回次数。

约束：

- 只从“我叫/请叫我/语速慢一点”等显式表达写入偏好。
- 页面提供清空入口；测试环境使用独立临时数据库。
- 每个浏览器使用独立匿名设备 ID，避免公开 Demo 访客互相读取记忆。
- 每个访客最多保留最近 50 轮会话，反馈随会话清理。
- P1 联调前增加最多 10 条会话摘要的轮转策略。
- 产品化前增加加密、保留期限与用户授权。

## 6. Provider 替换点

当前已实现 `providers/stepfun.py`，密钥仅从 `STEPFUN_API_KEY` 环境变量读取；没有密钥或上游失败时自动使用 `DemoEngine.generate_reply()` Mock Provider。后续仍按统一接口拆分：

```python
class SpeechToTextProvider:
    def stream(self, pcm_chunks): ...

class LanguageModelProvider:
    def stream(self, messages, profile): ...

class TextToSpeechProvider:
    def stream(self, text_chunks, voice, rate): ...
```

Provider 失败必须转换为统一的 `error` 或 `offline` 事件，不能把第三方异常直接暴露给设备。

## 7. 两阶段执行计划

### 阶段 A：系统控制台（当前交付）

- 完成状态机、流式协议、三类场景、SQLite 记忆和断网兜底。
- 完成阶跃 `step-3.7-flash`、`stepaudio-2.5-asr`、`stepaudio-2.5-tts` 服务端接入。
- 用数字孪生验证硬件状态映射和 5 分钟演示脚本。
- 通过单元测试、HTTP 检查和浏览器交互检查。

### 阶段 B：硬件接入（建议 1–2 天）

1. ESP32 先只发文本事件，验证 WebSocket、灯光和 OLED。
2. 加入麦克风 PCM 上行，接 STT partial/final。
3. 加入 TTS 音频下行与 I2S 播放。
4. 做断网、重连、超时、长回复截断和现场噪音测试。
5. 冻结一套 Mock/预录 Plan B，现场一键切换。

## 8. 验收标准

- 服务启动不需要安装第三方包。
- 三个推荐问题都能完整结束，界面不会卡在“思考中”。
- 回复到达时 OLED 与对话区逐步更新，而不是最后一次性出现。
- “记住我叫小林，语速慢一点”后，下一轮能使用“小林”并按慢速播报。
- 断网演练在 1 秒内给出明确反馈，并恢复可操作状态。
- 页面在桌面和手机宽度下均无横向溢出、遮挡或不可点击控件。
- 真实 Provider 或 ESP32 尚未接入时，界面明确标注为 Demo，不伪造实时数据。
