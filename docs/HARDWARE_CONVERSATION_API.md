# 灵犀硬件对话接口

本接口让 ESP32-S3 BOX 的真实麦克风录音经过阶跃 ASR → 有历史的对话模型 → TTS，并返回可以直接送入 ES8311 的 PCM。网页和板子共享设备设置、聊天记录与同一条服务链路。

没有配置有效的 API Key 时返回 HTTP 503；模型、额度、网络或权限错误返回明确错误，不生成假识别结果或假语音。API Key 只由电脑服务持有，不写入板端、响应元数据或公开设置接口。

## 准备

1. 电脑运行 `server.py --host 0.0.0.0 --port 8787`，板子与电脑在能够互访的网络内。
2. 在本机配置页配置阶跃 API Key，或者在启动服务前设置 `STEPFUN_API_KEY` 环境变量。不要把 Key 提交到仓库。
3. 默认使用现有 `https://api.stepfun.com/step_plan/v1` 地址；标准 API 账号可按实际开通情况设置 `STEPFUN_BASE_URL=https://api.stepfun.com/v1`。需要独立音频地址时设置 `STEPFUN_AUDIO_BASE_URL`，不设置则跟随主地址。账号必须拥有所选 ASR、对话、TTS 和音色的权限。

对话模型默认 `step-3.7-flash`，音频模型为现有 `stepaudio-2.5-asr` 和 `stepaudio-2.5-tts`。接口兼容性以账号实际可用能力为准。

## 外观、语气与声音

`GET /api/companion/catalog` 返回 `options`、`defaults`、`enabled`、`audio` 和 `limits`。选项以该接口为准。

| 设置字段 | 可选值 | 含义 |
| --- | --- | --- |
| `mode` | `assistant` / `companion` / `translate` | 日常聊天、暖心陪伴、中英翻译 |
| `voice` | `wenrounvsheng` / `cixingnansheng` / `yuanqishaonv` / `qingniandaxuesheng` | 温柔女声、磁性男声、元气少女、青年大学生 |
| `tone` | `warm` / `calm` / `cheerful` / `direct` | 温柔、平静、活泼、简洁 |
| `language` | `zh` / `en` | 对话语言；翻译模式下是目标语言 |
| `avatar` | `kangaroo` / `robot` | 蓝袋鼠、云朵小犀 |
| `speech_rate` | `slow` / `normal` / `fast` | 语速 |
| `persona` | `friend` / `mentor` / `playful` | 贴心朋友、耐心学长、元气搭子 |

语气通过模型指令控制；不同音色的实际表现会不同。声音 ID 来自阶跃官方 SDK 公开音色表，仍需相应账号权限。更换形象只改变外观，性格和声音可以独立搭配。

普通聊天使用所选语言进行识别并回复。翻译模式会识别相反的源语言：目标英文时听中文，目标中文时听英文。没有宣称自动支持未验证语言。

`GET /api/companion/settings?device_id=box-aabbccddeeff`：

```json
{"device_id":"box-aabbccddeeff","settings":{"mode":"companion","voice":"wenrounvsheng","tone":"warm","language":"zh","avatar":"kangaroo","speech_rate":"normal","persona":"friend"}}
```

`POST /api/companion/settings` 接受局部更新，其他选项保留。设置保存到当前 SQLite 数据库的 `companion_settings` 表，服务重启后仍保留；不同设备隔离。

```json
{"device_id":"box-aabbccddeeff","settings":{"voice":"cixingnansheng","tone":"calm","avatar":"kangaroo"}}
```

设备标识为 1–80 个 ASCII 字母、数字或 `._:-`。板子使用固定设备标识，网页选择相同标识即可调整该板子的设置。

## 板端语音请求

```http
POST /api/device/conversation HTTP/1.1
Host: 电脑IP:8787
Content-Type: audio/pcm
X-Device-Id: box-aabbccddeeff
Content-Length: 96000

<16kHz / 16bit / 单声道 / 小端 / 无 WAV 文件头的 PCM>
```

长度必须是偶数；最短 0.2 秒（6400 字节），最长 10 秒（320000 字节）。全静音或极低电平录音会在调用付费识别服务前被拒绝。

成功响应类型为 `application/vnd.lingxi.voice+binary`，结构如下，两个长度字段都是 uint32 little-endian：

| 偏移 | 长度 | 内容 |
| --- | --- | --- |
| 0 | 4 | ASCII `LXI1` |
| 4 | 4 | JSON 字节数，不超过 8192 |
| 8 | 4 | PCM 字节数，不超过 640000 |
| 12 | JSON 字节数 | UTF-8 元数据 |
| 12 + JSON 字节数 | PCM 字节数 | 16kHz / PCM16LE / 单声道 |

元数据示例：

```json
{
  "transcript":"今天实验不太顺利，有点难过",
  "reply":"反复尝试真的会有点累。我陪你慢慢找原因，先休息一小会儿好吗？",
  "settings":{"mode":"companion","voice":"wenrounvsheng","tone":"warm","language":"zh","avatar":"kangaroo","speech_rate":"normal","persona":"friend"},
  "audio":{"encoding":"pcm_s16le","sample_rate":16000,"bits":16,"channels":1,"bytes":144000,"duration_ms":4500},
  "truncated":false,
  "provider":"stepfun",
  "elapsed_ms":6520,
  "conversation_id":12
}
```

上面是格式示例，不代表一次已完成的真实模型调用。

服务请求 WAV/16000Hz，读取真实 WAV 文件头。如果上游返回 24kHz 等支持的采样率，会在电脑端转成 16kHz；支持 16 位单声道或双声道 WAV，双声道取平均。转换只依赖 Python 标准库，无需 FFmpeg，也不依赖 Python 3.13 已移除的 audioop。

回复提示词会要求简短口语；输出 PCM 硬上限为 20 秒。超过上限时音频末尾淡出，`truncated=true`，客户端应提示该段语音已截短。原始录音不落盘；转写和回复进入现有按设备保存的对话历史，后续轮次使用最近四轮上下文。

## 网页文字测试

`POST /api/companion/chat`：

```json
{"device_id":"box-aabbccddeeff","text":"今天心情不太好，能陪我说会儿话吗？","speak":true}
```

`speak=true` 返回同一 `LXI1` 二进制结构；`speak=false` 只调用对话模型，返回 JSON 元数据、不调用 TTS，PCM 长度为 0。该接口可以区分对话模型配置错误和语音模型配置错误。

## 错误

| HTTP | `code` 示例 | 建议 |
| --- | --- | --- |
| 400 | `invalid_request` / `invalid_pcm` | 检查设置、音频格式或长度 |
| 413 | `audio_too_long` | 录音控制在 10 秒内 |
| 422 | `silent_audio` | 靠近麦克风重新说话 |
| 429 | `busy` | 等待当前请求结束再试 |
| 503 | `provider_not_configured` | 在本机配置有效 API Key |
| 502 | `asr_failed` / `chat_failed` / `tts_failed` / `invalid_audio` | 按错误阶段检查网络、账号权限、额度、上游返回格式 |

错误返回 JSON，不返回 `LXI1` 音频包；板端必须先检查 HTTP 状态。服务最多同时处理两次完整对话，避免短时间重复按键引起大量上游请求。

## 已验证与待验证

自动测试覆盖了完整 ASR→对话→TTS 调用顺序、个性化参数传递、历史上下文、设置持久化和设备隔离、无 Key 的明确失败、上游错误与 Key 隐去、录音长度和静音、WAV 解析、24kHz 双声道转 16kHz、20 秒上限和末尾淡出。测试使用内存中的可控上游响应，不消耗真实模型额度。

真实云端请求与板端收录播需要有效 Key、账号权限、网络可达和实机确认。测试通过不代表这几项已经自动完成。

## 官方资料

- [阶跃官方音频 SDK：音色、格式与采样率](https://github.com/stepfun-ai/stepfunApi-audio-sdk#配置参数说明)
- [阶跃官方 ASR 请求示例](https://github.com/stepfun-ai/StepAudio-Skills/blob/main/skills/step-asr/scripts/transcribe.py)
- [阶跃官方 StepAudio 2.5 ASR 发布说明及 Step Plan 音频入口](https://www.stepfun.com/news/stepaudio-2-5-asr)
- [StepAudio 3 TTS 官方示例：WAV 文件头验证及声音配置](https://platform.stepfun.com/cookbook/stepaudio-3-tts)
